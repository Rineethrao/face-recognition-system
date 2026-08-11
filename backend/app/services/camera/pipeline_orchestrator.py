"""
pipeline_orchestrator.py — 3-Thread Decoupled AI Pipeline

Architecture per camera:
    ┌─────────────────────────────────────────────────────────────┐
    │  Thread 1: Streaming Worker (runs at stream_fps, e.g. 25)  │
    │    Reads raw frame → draws cached overlays → JPEG encode   │
    │    Writes to AnnotatedFrameBuffer                          │
    │    NEVER calls SCRFD or ArcFace                            │
    ├─────────────────────────────────────────────────────────────┤
    │  Thread 2: Detection Worker (runs at detection_fps, e.g. 8)│
    │    Reads raw frame → SCRFD detect → ByteTrack update       │
    │    Updates DetectionResultsSlot (tracked faces)            │
    │    Triggers Recognition Worker if new tracks appear        │
    ├─────────────────────────────────────────────────────────────┤
    │  Thread 3: Recognition Worker (async, event-driven)        │
    │    Reads DetectionResultsSlot → best-frame selection       │
    │    Quality check → ArcFace → FAISS → TrackResultsCache     │
    │    Updates TrackResultsCache with identity results         │
    └─────────────────────────────────────────────────────────────┘

Streaming is NEVER blocked by AI inference.
Recognition is NEVER run more than once per track.
"""

import cv2
import time
import logging
import threading
import numpy as np
from typing import List, Dict, Tuple, Optional, Any

from app.core.frame_buffer import LatestFrameBuffer, AnnotatedFrameBuffer
from app.core.detector import detector_engine
from app.core.tracker import ByteTrackTracker
from app.config import settings

logger = logging.getLogger(__name__)


class TrackState:
    """State machine for a single tracked face."""
    __slots__ = [
        'track_id', 'first_seen', 'last_seen', 'frames_collected',
        'best_frame', 'best_landmarks', 'best_bbox', 'best_quality_est',
        'recognition_attempted', 'final_match', 'current_bbox', 'current_landmarks'
    ]

    def __init__(self, track_id: int):
        self.track_id = track_id
        self.first_seen = time.monotonic()
        self.last_seen = time.monotonic()
        self.frames_collected = 0
        self.best_frame: Optional[np.ndarray] = None
        self.best_landmarks: Optional[np.ndarray] = None
        self.best_bbox: Optional[List[float]] = None
        self.best_quality_est: float = -1.0
        self.recognition_attempted: bool = False
        self.final_match: Optional[Dict[str, Any]] = None
        # Updated every detection frame for overlay rendering
        self.current_bbox: Optional[List[float]] = None
        self.current_landmarks: Optional[List] = None


class PipelineOrchestrator:
    """
    Per-Camera AI Pipeline with 3 independent worker threads.
    Camera isolation: each camera gets its own PipelineOrchestrator instance.
    """

    def __init__(
        self,
        camera_id: str,
        raw_buffer: LatestFrameBuffer,
        annotated_buffer: AnnotatedFrameBuffer,
    ):
        self.camera_id = camera_id
        self.raw_buffer = raw_buffer              # Input: raw frames from camera
        self.annotated_buffer = annotated_buffer  # Output: frames with overlays

        # Per-camera tracker instance (no global shared state)
        self.tracker = ByteTrackTracker(
            high_thresh=settings.TRACK_HIGH_THRESH,
            low_thresh=settings.TRACK_LOW_THRESH,
            match_thresh=settings.MATCH_THRESH,
            max_time_lost=settings.TRACK_BUFFER,
        )

        # Thread control
        self._running = False
        self._threads: List[threading.Thread] = []

        # Shared state between threads (protected by lightweight locks)
        self._track_states: Dict[int, TrackState] = {}
        self._track_lock = threading.Lock()

        # Latest detected bounding boxes for overlay rendering (set by Detection, read by Streaming)
        self._latest_overlay: List[Dict[str, Any]] = []
        self._overlay_lock = threading.Lock()

        # Real-time metadata for registration overlays
        self._latest_metadata_list: List[Dict[str, Any]] = []
        self._metadata_lock = threading.Lock()

        # Recognition queue (Detection → Recognition thread)
        self._recognition_event = threading.Event()

        # FPS tracking
        self._stream_fps: float = 0.0
        self._detect_fps: float = 0.0
        self._last_stream_t = time.monotonic()
        self._last_detect_t = time.monotonic()

        # Config
        self._stream_fps_target: int = getattr(settings, 'STREAM_FPS', 25)
        self._detect_fps_target: int = getattr(settings, 'DETECTION_FPS', 8)
        self._jpeg_quality: int = getattr(settings, 'JPEG_QUALITY', 90)
        self._adaptive_quality: bool = getattr(settings, 'ADAPTIVE_QUALITY', True)

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self):
        """Start all 3 pipeline worker threads."""
        if self._running:
            return
        self._running = True

        self._threads = [
            threading.Thread(target=self._streaming_worker, name=f"StreamWorker-{self.camera_id}", daemon=True),
            threading.Thread(target=self._detection_worker, name=f"DetectWorker-{self.camera_id}", daemon=True),
            threading.Thread(target=self._recognition_worker, name=f"RecognWorker-{self.camera_id}", daemon=True),
        ]
        for t in self._threads:
            t.start()
        logger.info(f"[Pipeline:{self.camera_id}] All 3 workers started.")

    def stop(self):
        """Stop all pipeline workers."""
        self._running = False
        self._recognition_event.set()  # Unblock recognition thread
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=2.0)
        self._threads.clear()
        logger.info(f"[Pipeline:{self.camera_id}] All workers stopped.")

    def is_running(self) -> bool:
        return self._running and all(t.is_alive() for t in self._threads)

    def get_fps(self) -> Dict[str, float]:
        return {
            "stream_fps": round(self._stream_fps, 1),
            "detect_fps": round(self._detect_fps, 1),
        }

    def get_annotated_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        return self.annotated_buffer.get_frame(timeout=0.04)

    def get_face_crops(self) -> List[Dict[str, Any]]:
        """Return current face crops for the live thumbnail panel."""
        with self._track_lock:
            crops = []
            for state in self._track_states.values():
                if state.final_match is not None and state.best_frame is not None:
                    crops.append({
                        "track_id": state.track_id,
                        "name": state.final_match.get("name", "Unknown"),
                        "similarity": state.final_match.get("similarity", 0.0),
                        "bbox": state.current_bbox,
                    })
            return crops

    def get_active_tracks_metadata(self) -> List[Dict[str, Any]]:
        """Return real-time active track metadata for overlays."""
        with self._metadata_lock:
            return list(self._latest_metadata_list)

    # ─────────────────────────────────────────────────────────────────────────
    # Thread 1: Streaming Worker
    # ─────────────────────────────────────────────────────────────────────────

    def _streaming_worker(self):
        """
        Reads raw frames and draws cached detection/recognition overlays.
        Runs at stream_fps (e.g. 25 FPS). NEVER calls SCRFD or ArcFace.
        Publishes JPEG bytes to AnnotatedFrameBuffer for the MJPEG endpoint.
        """
        interval = 1.0 / max(1, self._stream_fps_target)
        jpeg_quality = self._jpeg_quality
        last_processed_t = 0.0

        while self._running:
            t_start = time.monotonic()

            curr_t = self.raw_buffer.timestamp
            if curr_t <= last_processed_t:
                time.sleep(0.002)
                continue

            ret, frame = self.raw_buffer.peek()
            if not ret or frame is None:
                time.sleep(0.002)
                continue

            last_processed_t = curr_t

            # ── Draw overlays (non-blocking read of cached detection results) ──
            # During ANY active registration, serve a clean stream.
            # Frontend draws a single face-box layer — never bake boxes into MJPEG.
            suppress_overlays = False
            try:
                from app.services.registration.registration_engine import registration_engine as _reg
                suppress_overlays = bool(_reg.is_registering)
            except Exception:
                pass

            annotated = frame  # Start with raw frame (no copy until we draw)
            with self._overlay_lock:
                overlay_data = list(self._latest_overlay)  # Snapshot

            if overlay_data and not suppress_overlays:
                annotated = frame.copy()  # Only copy when we actually need to draw
                for item in overlay_data:
                    self._draw_overlay(annotated, item)


            # ── JPEG encode ───────────────────────────────────────────────────
            encode_start = time.monotonic()
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality,
                             int(cv2.IMWRITE_JPEG_OPTIMIZE), 1]
            ret_enc, jpeg_buf = cv2.imencode('.jpg', annotated, encode_params)

            if not ret_enc:
                time.sleep(0.01)
                continue

            # Adaptive quality: reduce if encoding is too slow, but keep minimum at 85 for high definition
            encode_ms = (time.monotonic() - encode_start) * 1000
            if self._adaptive_quality:
                if encode_ms > 25 and jpeg_quality > 85:
                    jpeg_quality = max(85, jpeg_quality - 3)
                elif encode_ms < 10 and jpeg_quality < self._jpeg_quality:
                    jpeg_quality = min(self._jpeg_quality, jpeg_quality + 2)

            jpeg_bytes = jpeg_buf.tobytes()

            # Validate JPEG integrity (must end with FFD9 marker)
            if len(jpeg_bytes) < 4 or jpeg_bytes[-2:] != b'\xff\xd9':
                continue  # Drop corrupt JPEG

            self.annotated_buffer.put(annotated, jpeg_bytes)

            # ── FPS tracking ──────────────────────────────────────────────────
            now = time.monotonic()
            elapsed = now - self._last_stream_t
            self._last_stream_t = now
            if elapsed > 0:
                self._stream_fps = 0.9 * self._stream_fps + 0.1 * (1.0 / elapsed)

            # Sleep to maintain target FPS
            spent = time.monotonic() - t_start
            sleep_t = interval - spent
            if sleep_t > 0:
                time.sleep(sleep_t)

    # ─────────────────────────────────────────────────────────────────────────
    # Thread 2: Detection Worker
    # ─────────────────────────────────────────────────────────────────────────

    def _detection_worker(self):
        """
        Runs SCRFD face detection + ByteTrack at detection_fps (e.g. 8 FPS).
        Updates the overlay cache and track states.
        Signals the recognition worker when new unrecognized tracks appear.
        """
        interval = 1.0 / max(1, self._detect_fps_target)
        last_processed_t = 0.0

        while self._running:
            t_start = time.monotonic()

            curr_t = self.raw_buffer.timestamp
            if curr_t <= last_processed_t:
                time.sleep(0.005)
                continue

            ret, frame = self.raw_buffer.peek()
            if not ret or frame is None:
                time.sleep(0.005)
                continue

            last_processed_t = curr_t

            try:
                # ── SCRFD Detection ───────────────────────────────────────────
                detected_faces = detector_engine.detect(frame)

                # ── ByteTrack Update ──────────────────────────────────────────
                tracked_faces = self.tracker.update(detected_faces) if detected_faces else []

                # Process live registration session if active
                try:
                    from app.services.registration.registration_engine import registration_engine
                    from app.services.registration.capture_service import capture_service
                    if registration_engine.is_registering and tracked_faces:
                        if not capture_service.active_camera_id or capture_service.active_camera_id == self.camera_id:
                            registration_engine.process_frame(frame, tracked_faces, method="CCTV")
                except Exception as reg_err:
                    logger.debug(f"[Pipeline:{self.camera_id}] Registration frame process: {reg_err}")

                now = time.monotonic()
                new_unrecognized = False

                with self._track_lock:
                    active_ids = set()
                    for face in tracked_faces:
                        tid = face.track_id
                        active_ids.add(tid)

                        if tid not in self._track_states:
                            self._track_states[tid] = TrackState(tid)

                        state = self._track_states[tid]
                        state.last_seen = now
                        state.current_bbox = face.bbox
                        state.current_landmarks = face.landmarks

                        # ── Continuous best frame selection for unresolved tracks ─────────
                        if not state.recognition_attempted:
                            x1, y1, x2, y2 = face.bbox
                            face_size = min(max(0, x2 - x1), max(0, y2 - y1))

                            # Face size gate: minimum 22px (allows distant CCTV office faces)
                            if face_size >= getattr(settings, 'VISITOR_MIN_FACE_WIDTH', 22):
                                ih, iw = frame.shape[:2]
                                cx1 = int(max(0, x1)); cy1 = int(max(0, y1))
                                cx2 = int(min(iw, x2)); cy2 = int(min(ih, y2))
                                if cx2 > cx1 and cy2 > cy1:
                                    crop = frame[cy1:cy2, cx1:cx2]
                                    gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                                    blur = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
                                else:
                                    blur = 0.0

                                quality_est = face_size * blur
                                if quality_est > state.best_quality_est or state.best_frame is None:
                                    state.best_quality_est = quality_est
                                    state.best_frame = frame.copy()
                                    state.best_landmarks = np.array(face.landmarks)
                                    state.best_bbox = face.bbox
                                    new_unrecognized = True

                                state.frames_collected += 1

                    # Cleanup stale tracks (gone > 30 seconds)
                    stale = [tid for tid, s in self._track_states.items()
                             if (now - s.last_seen) > 30.0]
                    for tid in stale:
                        del self._track_states[tid]

                # ── Build overlay data for streaming worker ────────────────────
                overlay = []
                with self._track_lock:
                    for face in tracked_faces:
                        tid = face.track_id
                        state = self._track_states.get(tid)
                        match_info = state.final_match if state else None
                        overlay.append({
                            "track_id": tid,
                            "bbox": face.bbox,
                            "landmarks": face.landmarks,
                            "match": match_info,
                        })

                with self._overlay_lock:
                    self._latest_overlay = overlay

                # ── Build active track metadata for CCTV registration ─────────
                metadata_list = []
                import base64
                
                for face in tracked_faces:
                    try:
                        tid = face.track_id
                        bbox = [float(v) for v in face.bbox]
                        landmarks = face.landmarks
                        
                        # Calculate blur score
                        x1, y1, x2, y2 = bbox
                        ih, iw = frame.shape[:2]
                        cx1 = int(max(0, x1)); cy1 = int(max(0, y1))
                        cx2 = int(min(iw, x2)); cy2 = int(min(ih, y2))
                        if cx2 > cx1 and cy2 > cy1:
                            crop = frame[cy1:cy2, cx1:cx2]
                            gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                            blur = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
                        else:
                            blur = 0.0
                            
                        # Generate base64 face crop (using standard face alignment)
                        from app.core.utils import align_face
                        aligned_crop = align_face(frame, np.array(landmarks))
                        crop_base64 = ""
                        if aligned_crop is not None and aligned_crop.size > 0:
                            ret_enc, buf = cv2.imencode('.jpg', aligned_crop)
                            if ret_enc:
                                crop_base64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode('utf-8')
                        
                        # Include recognition result if available
                        with self._track_lock:
                            state = self._track_states.get(tid)
                            final_match = state.final_match if state else None

                        is_recognized = bool(final_match and final_match.get("person_id") not in (None, "unknown"))
                        rec_name = final_match.get("name", "Unknown") if final_match else "Analyzing..."
                        rec_sim = final_match.get("similarity", 0.0) if final_match else 0.0

                        metadata_list.append({
                            "track_id": tid,  # internal pipeline continuity only
                            "detection_id": f"{self.camera_id}_face_{tid}",
                            "bbox": bbox,
                            "match": final_match,
                            "blur_score": round(blur, 1),
                            "crop_base64": crop_base64,
                            "is_recognized": is_recognized,
                            "name": rec_name,
                            "similarity": round(rec_sim, 3),
                            "timestamp": time.strftime("%H:%M:%S"),
                            "confidence": float(getattr(face, 'score', 0.95)),
                            "quality": float(round(min(blur / 80.0, 1.0), 2)),
                            "landmarks": landmarks.tolist() if hasattr(landmarks, 'tolist') else list(landmarks) if landmarks is not None else None,
                            "camera_id": self.camera_id
                        })
                    except Exception:
                        pass

                # Deduplicate overlapping face boxes before publishing to registration UI
                deduped = []
                for item in sorted(
                    metadata_list,
                    key=lambda x: float(x.get("confidence", 0) or 0) + float(x.get("quality", 0) or 0),
                    reverse=True,
                ):
                    bb = item.get("bbox") or []
                    overlap = False
                    for kept in deduped:
                        kb = kept.get("bbox") or []
                        if len(bb) != 4 or len(kb) != 4:
                            continue
                        ix1 = max(bb[0], kb[0]); iy1 = max(bb[1], kb[1])
                        ix2 = min(bb[2], kb[2]); iy2 = min(bb[3], kb[3])
                        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                        if inter <= 0:
                            continue
                        union = (
                            max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1])
                            + max(0.0, kb[2] - kb[0]) * max(0.0, kb[3] - kb[1])
                            - inter
                        )
                        if union > 0 and (inter / union) >= 0.40:
                            overlap = True
                            break
                    if not overlap:
                        deduped.append(item)
                metadata_list = deduped

                with self._metadata_lock:
                    self._latest_metadata_list = metadata_list

                # Signal recognition worker if there are unresolved tracks
                if new_unrecognized:
                    self._recognition_event.set()

                # ── FPS tracking ──────────────────────────────────────────────
                now2 = time.monotonic()
                elapsed = now2 - self._last_detect_t
                self._last_detect_t = now2
                if elapsed > 0:
                    self._detect_fps = 0.9 * self._detect_fps + 0.1 * (1.0 / elapsed)

            except Exception as e:
                logger.error(f"[Detection:{self.camera_id}] Error: {e}", exc_info=True)

            spent = time.monotonic() - t_start
            sleep_t = interval - spent
            if sleep_t > 0:
                time.sleep(sleep_t)

    # ─────────────────────────────────────────────────────────────────────────
    # Thread 3: Recognition Worker
    # ─────────────────────────────────────────────────────────────────────────

    def _recognition_worker(self):
        """
        Event-driven recognition. Wakes up when detection finds new tracks.
        Runs quality check → ArcFace → FAISS exactly ONCE per track ID.
        Locks the result in TrackState.final_match for all future frames.
        """
        from app.core.recognizer import arcface_recognizer
        from app.core.faiss_index import faiss_manager
        from app.core.utils import align_face, l2_normalize

        while self._running:
            # Block until detection signals new unrecognized tracks
            self._recognition_event.wait(timeout=1.0)
            self._recognition_event.clear()

            if not self._running:
                break

            # Collect all tracks that need recognition
            candidates = []
            with self._track_lock:
                now = time.monotonic()
                for tid, state in self._track_states.items():
                    if state.recognition_attempted:
                        continue
                    if state.best_frame is not None:
                        candidates.append((tid, state.best_frame, state.best_bbox, state.best_landmarks))
                        state.best_frame = None  # Reset best frame so next observation can be picked up
                        state.best_quality_est = 0.0

            for tid, best_frame, best_box, best_lms in candidates:
                try:
                    match_info = self._run_recognition(
                        tid, best_frame, best_box, best_lms,
                        arcface_recognizer, faiss_manager, l2_normalize, align_face
                    )

                    with self._track_lock:
                        state = self._track_states.get(tid)
                        if state:
                            state.final_match = match_info
                            # Lock sticky ONLY when identity is resolved (Registered or Visitor)
                            if match_info.get("status") in ("RECOGNIZED", "VISITOR"):
                                state.recognition_attempted = True
                            else:
                                state.recognition_attempted = False

                    # Log recognition event if identity is resolved
                    if match_info.get("status") in ("RECOGNIZED", "VISITOR"):
                        self._log_event(tid, match_info)

                except Exception as e:
                    logger.error(f"[Recognition:{self.camera_id}] Track {tid} error: {e}", exc_info=True)
                    with self._track_lock:
                        state = self._track_states.get(tid)
                        if state:
                            state.final_match = {"person_id": "unknown", "name": "Identifying...", "similarity": 0.0}

    def _run_recognition(self, track_id, frame, bbox, landmarks, arcface, faiss_mgr, l2_normalize_fn, align_fn) -> Dict[str, Any]:
        """Quality gate → ArcFace embedding → FAISS registered search (if active) → VisitorManager."""
        t0 = time.perf_counter()
        from app.visitors.face_quality import visitor_quality_evaluator

        # Multi-Tier Face Quality Evaluation
        quality_res = visitor_quality_evaluator.evaluate_quality(frame, bbox, landmarks)

        # POOR face quality check: If unusable for matching, DO NOT proceed to recognition!
        if not quality_res.usable_for_matching:
            logger.debug(f"[Recognition:{self.camera_id}] Quality tier {quality_res.quality_tier} unusable for matching on track {track_id}")
            return {"person_id": "unknown", "name": "Identifying...", "similarity": 0.0, "status": "IDENTIFYING"}

        aligned_crop = quality_res.aligned_crop
        if aligned_crop is None:
            return {"person_id": "unknown", "name": "Identifying...", "similarity": 0.0, "status": "IDENTIFYING"}

        # ArcFace embedding
        embedding = arcface.extract_embedding(aligned_crop)
        if embedding is None:
            return {"person_id": "unknown", "name": "Identifying...", "similarity": 0.0, "status": "IDENTIFYING"}

        # 1. Registered Person Search (Shortcut: Skip FAISS search completely if registered gallery is empty!)
        best_pid = None
        best_name = "Unknown"
        best_sim = 0.0

        if faiss_mgr.index.ntotal > 0:
            top_k_hits = faiss_mgr.search(query_embedding=embedding, k=10, threshold=0.35)
            q_norm = l2_normalize_fn(embedding)

            for hit in top_k_hits:
                pid = hit["person_id"]
                name = hit["name"]
                cached_embs = faiss_mgr.embeddings_cache.get(pid, [])
                if not cached_embs:
                    continue
                sims = [float(np.dot(q_norm, l2_normalize_fn(e))) for e in cached_embs]
                max_sim = max(sims)
                if max_sim > best_sim:
                    best_sim = max_sim
                    best_pid = pid
                    best_name = name

            threshold = getattr(settings, 'REGISTERED_CONFIRMED_THRESHOLD', getattr(settings, 'VISITOR_REGISTERED_MATCH_THRESHOLD', 0.40))
            if best_pid and best_sim >= threshold:
                try:
                    from app.services.learning.progressive_learning import progressive_learning_engine
                    progressive_learning_engine.queue_profile_auto_improvement(
                        person_id=best_pid, name=best_name, aligned_crop=aligned_crop,
                        new_embedding=embedding, match_score=best_sim, camera_id=self.camera_id
                    )
                except Exception:
                    pass
                t_tot = (time.perf_counter() - t0) * 1000.0
                logger.info(f"[Perf:{self.camera_id}] Track {track_id} matched REGISTERED {best_name} ({best_sim*100:.1f}%) in {t_tot:.1f}ms")
                return {
                    "person_id": best_pid,
                    "name": best_name,
                    "similarity": round(best_sim, 4),
                    "status": "RECOGNIZED",
                    "aligned_crop": aligned_crop,
                    "quality_score": quality_res.quality_score
                }

        # Registered recognition returned no match -> Route to VisitorManager
        try:
            from app.core.database import SessionLocal
            from app.visitors.visitor_manager import visitor_manager
            db = SessionLocal()
            try:
                vis_res = visitor_manager.resolve_unregistered_track(
                    db=db,
                    camera_id=self.camera_id,
                    track_id=track_id,
                    embedding=embedding,
                    quality_res=quality_res,
                    crop_img=aligned_crop
                )
                if vis_res.is_resolved:
                    return {
                        "person_id": vis_res.visitor_code,
                        "name": vis_res.visitor_code,
                        "similarity": vis_res.similarity,
                        "status": "VISITOR",
                        "aligned_crop": aligned_crop,
                        "quality_score": quality_res.quality_score
                    }
                else:
                    return {
                        "person_id": "unknown",
                        "name": vis_res.visitor_code,
                        "similarity": 0.0,
                        "status": "IDENTIFYING",
                        "aligned_crop": aligned_crop,
                        "quality_score": quality_res.quality_score
                    }
            finally:
                db.close()
        except Exception as vis_err:
            logger.error(f"[Recognition:{self.camera_id}] Visitor resolution error: {vis_err}")

        return {
            "person_id": "unknown",
            "name": "Identifying...",
            "similarity": round(best_sim, 4),
            "status": "UNKNOWN",
            "aligned_crop": aligned_crop,
            "quality_score": quality_res.quality_score
        }

    def _log_event(self, track_id: int, match_info: Dict[str, Any]):
        """Log a recognition event to the database (non-blocking)."""
        if match_info.get("person_id") == "unknown":
            return
        try:
            from app.config import settings
            from app.core.database import get_db
            from app.models.db_models import RecognitionLogModel
            from app.models.schemas import RecognitionEvent
            from app.services.presence_service import presence_service
            import os
            import time as _time
            import cv2

            db = next(get_db())
            try:
                str_tid = str(track_id)

                # Always record presence detection & update duration tracking for registered persons
                try:
                    presence_service.on_person_detected(
                        db=db,
                        person_id=match_info["person_id"],
                        person_name=match_info["name"],
                        camera_id=self.camera_id
                    )
                except Exception as pres_err:
                    logger.warning(f"Presence tracking error on camera {self.camera_id}: {pres_err}")

                existing = db.query(RecognitionLogModel).filter(
                    RecognitionLogModel.track_id == str_tid,
                    RecognitionLogModel.person_id == match_info["person_id"]
                ).order_by(RecognitionLogModel.id.desc()).first()

                if existing:
                    diff = (_time.time() - existing.timestamp.timestamp())
                    if diff < 5.0:
                        return

                # Save face snapshot crop to disk
                snapshot_path = None
                crop = match_info.get("aligned_crop")
                if crop is not None and crop.size > 0:
                    snapshots_dir = settings.STORAGE_DIR / "snapshots"
                    os.makedirs(snapshots_dir, exist_ok=True)
                    snap_filename = f"snap_{match_info['person_id']}_{int(_time.time())}_{track_id}.jpg"
                    full_path = snapshots_dir / snap_filename
                    cv2.imwrite(str(full_path), crop)
                    snapshot_path = str(full_path)

                log_entry = RecognitionLogModel(
                    person_id=match_info["person_id"],
                    name=match_info["name"],
                    similarity=match_info["similarity"],
                    track_id=str_tid,
                    camera_id=self.camera_id,
                    quality_score=match_info.get("quality_score", 0.0),
                    face_snapshot_path=snapshot_path
                )
                db.add(log_entry)
                db.commit()
                db.refresh(log_entry)

                snap_url = f"/faces/snapshots/{os.path.basename(snapshot_path)}" if snapshot_path else None

                event = RecognitionEvent(
                    id=log_entry.id,
                    person_id=match_info["person_id"],
                    name=match_info["name"],
                    similarity=match_info["similarity"],
                    track_id=str_tid,
                    camera_id=self.camera_id,
                    embedding_version=1,
                    quality_score=match_info.get("quality_score", 0.0),
                    recognized_at=log_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    face_snapshot_url=snap_url
                )

                # Dispatch to plugin system
                try:
                    from app.projects.manager import plugin_manager
                    plugin_manager.dispatch_face_recognized(event)
                except Exception:
                    pass

                logger.info(
                    f"[RECOGNIZED] {match_info['name']} ({match_info['person_id']}) "
                    f"| Sim: {match_info['similarity']:.2f} | Track: {track_id} | Cam: {self.camera_id} | Snapshot: {snapshot_path}"
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[Pipeline:{self.camera_id}] DB log error: {e}")


    def reset_track_recognitions(self):
        """Resets recognition status on all active tracks so they are immediately re-evaluated against updated FAISS index."""
        with self._track_lock:
            for state in self._track_states.values():
                state.recognition_attempted = False
                state.final_match = None
                state.frames_collected = 0
        self._recognition_event.set()

    # ─────────────────────────────────────────────────────────────────────────
    # Overlay Rendering
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_overlay(self, frame: np.ndarray, item: Dict[str, Any]):
        """
        Draws Live Stream Video Face Overlays:
        1. ANALYZING (Initial Detection) → GRAY Box (160, 160, 160) + Analyzing...
        2. RECOGNIZED (Registered Person) → GREEN Box (0, 255, 0) + Name & Score
        3. POSSIBLE_MATCH (Low Confidence) → ORANGE Box (0, 140, 255) + Possible Match
        4. UNKNOWN (Non-registered Person) → RED Box (0, 0, 255) + Unknown Badge
        """
        bbox = item.get("bbox")
        if not bbox:
            return

        x1, y1, x2, y2 = [int(v) for v in bbox]
        match_info = item.get("match")

        if match_info is None:
            # 1. Initial Detection / Processing: GRAY Box
            color = (160, 160, 160)
            line1 = "Analyzing..."
            line2 = ""
            text_color = (255, 255, 255)
        else:
            status = match_info.get("status") or ("RECOGNIZED" if match_info.get("person_id") not in (None, "unknown") else "UNKNOWN")
            name = match_info.get("name", "Unknown")
            similarity = match_info.get("similarity", 0.0)
            sim_pct = int(similarity * 100) if similarity <= 1.0 else int(similarity)

            if status == "RECOGNIZED":
                # 2. High Confidence Recognized: GREEN (BGR: 0, 255, 0)
                color = (0, 255, 0)
                line1 = name
                line2 = f"{sim_pct}%"
                text_color = (0, 0, 0)
            elif status == "VISITOR" or (isinstance(name, str) and name.startswith("VISITOR-")):
                # 3. Visitor Re-ID: CYAN / GOLD (BGR: 255, 200, 0)
                color = (255, 200, 0)
                line1 = name
                line2 = "Visitor"
                text_color = (0, 0, 0)
            elif status in ("IDENTIFYING", "ANALYZING") or name in ("Analyzing...", "Identifying..."):
                # 4. Collecting / Identifying: AMBER (BGR: 0, 215, 255)
                color = (0, 215, 255)
                line1 = "Identifying..."
                line2 = ""
                text_color = (0, 0, 0)
            elif status == "POSSIBLE_MATCH":
                # 5. Low Confidence Possible Match: ORANGE (BGR: 0, 140, 255)
                color = (0, 140, 255)
                line1 = "Possible Match"
                line2 = f"{name} ({sim_pct}%)"
                text_color = (0, 0, 0)
            else:
                # 6. Fallback: AMBER (BGR: 0, 165, 255)
                color = (0, 165, 255)
                line1 = name if name != "Unknown" else "Identifying..."
                line2 = ""
                text_color = (0, 0, 0)

        # Draw main bounding box (thickness = 2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        # Draw header badge box above top of bounding box
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale1 = 0.50
        scale2 = 0.40

        (w1, h1), _ = cv2.getTextSize(line1, font, scale1, 1)
        w2, h2 = (0, 0)
        if line2:
            (w2, h2), _ = cv2.getTextSize(line2, font, scale2, 1)

        badge_w = max(w1, w2) + 12
        badge_h = (h1 + h2 + 10) if line2 else (h1 + 8)

        # Ensure badge stays inside frame boundaries
        badge_y1 = max(0, y1 - badge_h - 4)
        badge_y2 = badge_y1 + badge_h

        # Solid badge background
        cv2.rectangle(frame, (x1, badge_y1), (x1 + badge_w, badge_y2), color, -1)

        # Render Line 1 (Name / Possible Match / Unknown / Analyzing)
        cv2.putText(frame, line1, (x1 + 6, badge_y1 + h1 + 3), font, scale1, text_color, 1, cv2.LINE_AA)

        # Render Line 2 if present (Percentage / Details)
        if line2:
            cv2.putText(frame, line2, (x1 + 6, badge_y1 + h1 + h2 + 7), font, scale2, text_color, 1, cv2.LINE_AA)
