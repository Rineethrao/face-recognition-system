from app.config import settings
import cv2
import time
import logging
import threading
import numpy as np
from typing import List, Optional, Tuple, Dict, Any


from app.core.stream import camera_manager
from app.core.detector import detector_engine
from app.core.tracker import face_tracker
from app.core.database import get_db
from app.models.db_models import RecognitionLogModel
from app.models.schemas import RecognitionMatch, RecognitionEvent
from app.services.recognition_service import recognition_service
from app.services.registration_service import registration_service

logger = logging.getLogger(__name__)

class DetectionService:
    """
    Background Stream Processing Engine.
    Orchestrates face detection, ByteTrack tracking, recognition, and registration loop,
    and caches annotated frames for real-time video streaming.
    """
    def __init__(self):
        self.is_recognizing: bool = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.recent_events: List[RecognitionEvent] = []
        self.event_counter: int = 0
        self.latest_annotated_frame: Optional[np.ndarray] = None
        self.recent_face_crops: Dict[int, Dict[str, Any]] = {}

    def get_recent_face_crops(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.recent_face_crops.values())

    def get_latest_annotated_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            if self.latest_annotated_frame is None:
                return False, None
            return True, self.latest_annotated_frame.copy()

    def get_latest_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            if self.latest_annotated_frame is None:
                return False, None
            return True, self.latest_annotated_frame.copy()

    def start_recognition(self):
        with self.lock:
            if self.is_recognizing:
                return
            self.is_recognizing = True
            self.thread = threading.Thread(target=self._processing_loop, daemon=True)
            self.thread.start()
            logger.info("Background detection processing loop started.")

    def stop_recognition(self):
        with self.lock:
            self.is_recognizing = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        logger.info("Background detection processing loop stopped.")

    def _processing_loop(self):
        import numpy as np

        frame_counter = 0
        cached_detected_faces = []
        detect_interval = 1.0 / max(1, getattr(settings, 'DETECTION_FPS', 8))
        last_detect_time = 0.0

        while self.is_recognizing:
            if not camera_manager.is_active():
                time.sleep(0.1)
                continue

            # Non-blocking read from the lock-free buffer
            ret, frame = camera_manager.frame_buffer.peek()
            if not ret or frame is None:
                time.sleep(0.02)
                continue

            annotated_frame = frame.copy()
            frame_counter += 1

            try:
                # 1. SCRFD Face Detection (Every 2nd frame on CPU for 2x speedup)
                if frame_counter % 2 == 0 or not cached_detected_faces:
                    detected_faces = detector_engine.detect(frame)
                    cached_detected_faces = detected_faces
                else:
                    detected_faces = cached_detected_faces

                # Live Registration processing if active
                if registration_service.is_registering and detected_faces:
                    registration_service.process_frame_registration(frame, detected_faces)

                # ByteTrack Face Tracking & ArcFace Recognition
                if detected_faces:
                    tracked_faces = face_tracker.update(detected_faces)
                    matches = recognition_service.process_tracked_faces(frame, tracked_faces)
                    match_map = {m.track_id: m for m in matches}

                    for match in matches:
                        self._log_recognition_event(match)

                    # Cache base64 aligned face crops for live stream face enrolment
                    import base64
                    from app.core.utils import align_face
                    for face in tracked_faces:
                        try:
                            track_id = face.track_id
                            landmarks_np = np.array(face.landmarks)
                            aligned = align_face(frame, landmarks_np)
                            ret_b64, buffer = cv2.imencode('.jpg', aligned)
                            if ret_b64:
                                b64_str = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
                                is_rec = match_map.get(track_id) is not None
                                self.recent_face_crops[track_id] = {
                                    "track_id": track_id,
                                    "crop_base64": b64_str,
                                    "is_recognized": is_rec,
                                    "name": match_map[track_id].name if is_rec else "Unregistered",
                                    "timestamp": time.strftime("%H:%M:%S")
                                }
                        except Exception as crop_err:
                            pass

                    # Clean stale face crops older than 20 items
                    if len(self.recent_face_crops) > 20:
                        keys = list(self.recent_face_crops.keys())
                        for k in keys[:-20]:
                            del self.recent_face_crops[k]

                    # Draw face bounding box and landmark overlays onto annotated frame
                    for face in tracked_faces:
                        track_id = face.track_id
                        x1, y1, x2, y2 = [int(v) for v in face.bbox]

                        match = match_map.get(track_id)
                        if match:
                            if match.person_id == "unknown":
                                if match.name and match.name != "Unknown":
                                    color = (255, 180, 0)  # Amber for Identifying...
                                    text = f"ID:{track_id} | {match.name}"
                                else:
                                    color = (0, 165, 255)  # Orange for Analyzing
                                    text = f"ID:{track_id} | Identifying..."
                            elif match.person_id.startswith("VISITOR-"):
                                color = (255, 215, 0)  # Cyan/Gold for Global Visitor
                                text = f"ID:{track_id} | {match.person_id}"
                            else:
                                color = (0, 255, 0)  # Green for Registered Person
                                text = f"ID:{track_id} | {match.name} ({int(match.similarity * 100)}%)"
                        else:
                            color = (0, 165, 255)
                            text = f"ID:{track_id} | Identifying..."

                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)



                        for kp in face.landmarks:
                            kx, ky = int(kp[0]), int(kp[1])
                            cv2.circle(annotated_frame, (kx, ky), 3, (0, 0, 255), -1)

                        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
                        cv2.rectangle(annotated_frame, (x1, max(0, y1 - 25)), (x1 + tw + 6, max(0, y1)), color, -1)
                        cv2.putText(annotated_frame, text, (x1 + 3, max(15, y1 - 7)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

                if registration_service.is_registering:
                    overlay_text = f"REGISTRATION: {registration_service.target_name} ({len(registration_service.collected_samples)}/{registration_service.target_samples} samples)"
                    cv2.rectangle(annotated_frame, (0, 0), (annotated_frame.shape[1], 40), (255, 128, 0), -1)
                    cv2.putText(annotated_frame, overlay_text, (15, 27),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

            except Exception as e:
                logger.error(f"Error in detection processing loop: {e}", exc_info=True)

            with self.lock:
                self.latest_annotated_frame = annotated_frame

            time.sleep(0.01)

    def _log_recognition_event(self, match: RecognitionMatch):
        if match.person_id == "unknown":
            return
        db = next(get_db())
        try:
            # Cast track_id to string for DB compatibility (RecognitionLogModel.track_id is String)
            str_track_id = str(match.track_id)

            # Always update presence tracking for detected person
            try:
                from app.services.presence_service import presence_service
                presence_service.on_person_detected(
                    db=db,
                    person_id=match.person_id,
                    person_name=match.name,
                    camera_id=getattr(match, 'camera_id', 'default')
                )
            except Exception:
                pass

            existing_recent = db.query(RecognitionLogModel).filter(
                RecognitionLogModel.track_id == str_track_id,
                RecognitionLogModel.person_id == match.person_id
            ).order_by(RecognitionLogModel.id.desc()).first()

            if existing_recent:
                time_diff = (time.time() - existing_recent.timestamp.timestamp())
                if time_diff < 5.0:
                    return

            log_entry = RecognitionLogModel(
                person_id=match.person_id,
                name=match.name,
                similarity=match.similarity,
                track_id=str_track_id,
                camera_id=getattr(match, 'camera_id', 'default'),
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)

            self.event_counter += 1
            event = RecognitionEvent(
                id=log_entry.id,
                person_id=match.person_id,
                name=match.name,
                similarity=match.similarity,
                track_id=str_track_id,
                camera_id=getattr(match, 'camera_id', 'default'),
                embedding_version=1,
                quality_score=0.0,
                recognized_at=log_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            )

            with self.lock:
                self.recent_events.append(event)
                if len(self.recent_events) > 100:
                    self.recent_events.pop(0)

            # Dispatch face recognized event to active project plugins (Office Attendance, Temple Security, Retail)
            try:
                from app.projects.manager import plugin_manager
                plugin_manager.dispatch_face_recognized(event)
            except Exception as plug_err:
                logger.debug(f"Plugin event dispatch info: {plug_err}")

            logger.info(f"[RECOGNIZED] Person: {match.name} ({match.person_id}) | Similarity: {match.similarity:.2f} | Track ID: {str_track_id}")

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to log recognition event: {e}")
        finally:
            db.close()

detection_service = DetectionService()
