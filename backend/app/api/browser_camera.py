"""
Browser Webcam Recognition API
-------------------------------
Lets the React frontend use the user's own device camera (laptop/phone webcam via
getUserMedia) as a live recognition source WITHOUT needing an RTSP/CCTV camera
configured on the backend. The browser captures a JPEG frame every ~700ms and
POSTs it here; we run the same SCRFD -> ArcFace -> FAISS pipeline used for
CCTV streams and return bounding boxes + identity for overlay rendering.
"""
import base64
import logging
import threading
import time
from typing import Optional, Dict, Any

import cv2
import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.core.detector import detector_engine
from app.core.recognizer import arcface_recognizer
from app.core.faiss_index import faiss_manager
from app.core.utils import align_face, evaluate_face_quality
from app.core.database import SessionLocal
from app.models.db_models import RecognitionLogModel
from app.models.schemas import APIResponse

logger = logging.getLogger("BrowserCamera")
router = APIRouter(prefix="/recognition", tags=["Browser Live Camera"])

# Per (camera_id, person_id) cooldown so we don't spam the recognition_logs
# table every ~700ms while the same person sits in front of the webcam.
_LOG_COOLDOWN_SECONDS = 8.0
_last_logged: Dict[str, float] = {}


class FrameAnalyzeRequest(BaseModel):
    image_base64: str
    camera_id: Optional[str] = "browser_cam"
    log_events: Optional[bool] = True


def _decode_base64_image(image_base64: str) -> Optional[np.ndarray]:
    try:
        if "," in image_base64 and image_base64.strip().startswith("data:"):
            image_base64 = image_base64.split(",", 1)[1]
        raw = base64.b64decode(image_base64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame
    except Exception as e:
        logger.warning(f"Failed to decode incoming browser frame: {e}")
        return None


def _maybe_log_event(camera_id: str, person_id: str, name: str, similarity: float, quality_score: float):
    key = f"{camera_id}:{person_id}"
    now = time.time()
    last = _last_logged.get(key, 0.0)
    if now - last < _LOG_COOLDOWN_SECONDS:
        return
    _last_logged[key] = now

    db = SessionLocal()
    try:
        log = RecognitionLogModel(
            person_id=person_id,
            name=name,
            similarity=similarity,
            track_id=-1,
            camera_id=camera_id,
            quality_score=quality_score,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to persist browser-camera recognition log: {e}")
        db.rollback()
    finally:
        db.close()

_browser_track_lock = threading.Lock()
_browser_tracks: Dict[str, Dict[str, Any]] = {}  # track_id -> {"embedding": np.ndarray, "last_seen": float, "bbox": list}
_browser_track_counter = 0

def _get_or_create_browser_track(embedding: np.ndarray, bbox: list, camera_id: str) -> str:
    """Associates incoming face with existing track via embedding similarity, or creates new track."""
    global _browser_track_counter
    from app.core.utils import l2_normalize
    
    now = time.time()
    q_norm = l2_normalize(embedding)
    
    with _browser_track_lock:
        stale = [tid for tid, t in _browser_tracks.items() if now - t["last_seen"] > 30.0]
        for tid in stale:
            del _browser_tracks[tid]
            
        best_track_id = None
        best_sim = 0.0
        for tid, t_data in _browser_tracks.items():
            sim = float(np.dot(q_norm, l2_normalize(t_data["embedding"]).T))
            if sim > best_sim:
                best_sim = sim
                best_track_id = tid
        
        if best_track_id and best_sim >= 0.48:
            _browser_tracks[best_track_id]["embedding"] = embedding
            _browser_tracks[best_track_id]["last_seen"] = now
            _browser_tracks[best_track_id]["bbox"] = bbox
            return best_track_id
            
        _browser_track_counter += 1
        new_id = f"browser_track_{_browser_track_counter}"
        _browser_tracks[new_id] = {
            "embedding": embedding,
            "last_seen": now,
            "bbox": bbox
        }
        return new_id


@router.post("/analyze_frame", response_model=APIResponse)
def analyze_frame(req: FrameAnalyzeRequest):
    """
    Runs a single browser-captured frame through detection + recognition.
    Stateless (no multi-frame consensus/tracking) so we apply a slightly higher
    confidence bar than the CCTV pipeline to keep single-shot matches reliable.
    """
    frame = _decode_base64_image(req.image_base64)
    if frame is None:
        return APIResponse(status="error", message="Could not decode image frame.", data={"faces": []})

    camera_id = req.camera_id or "browser_cam"
    faces = detector_engine.detect(frame)

    results = []
    # Single-shot matches need a bit more margin than the multi-frame CCTV
    # consensus engine, since there's no track-based voting to smooth noise.
    strong_threshold = max(settings.RECOGNITION_SIMILARITY_THRESHOLD, 0.50)

    for idx, face in enumerate(faces):
        bbox = face.bbox
        landmarks = face.landmarks or []
        entry: Dict[str, Any] = {
            "bbox": bbox,
            "score": round(float(face.score), 4),
            "person_id": "unknown",
            "name": "Unknown",
            "similarity": 0.0,
            "status": "unknown",
        }

        if len(landmarks) >= 5:
            is_good, reason, blur_score = evaluate_face_quality(frame, bbox, landmarks)
            entry["quality_ok"] = is_good
            entry["quality_reason"] = reason

            aligned = align_face(frame, np.array(landmarks))
            embedding = arcface_recognizer.extract_embedding(aligned)

            hits = faiss_manager.search(embedding, k=5, threshold=0.35)
            best = None
            for hit in hits:
                if best is None or hit["similarity"] > best["similarity"]:
                    best = hit

            if best and best["similarity"] >= strong_threshold:
                entry["person_id"] = best["person_id"]
                entry["name"] = best["name"]
                entry["similarity"] = round(float(best["similarity"]), 4)
                entry["status"] = "recognized"

                if req.log_events:
                    _maybe_log_event(
                        camera_id=camera_id,
                        person_id=best["person_id"],
                        name=best["name"],
                        similarity=entry["similarity"],
                        quality_score=float(blur_score) if is_good is not None else 0.0,
                    )
            else:
                # Registered recognition returned no match -> Route to VisitorManager
                try:
                    from app.visitors.visitor_manager import visitor_manager
                    from app.visitors.face_quality import visitor_quality_evaluator
                    db = SessionLocal()
                    try:
                        quality_res = visitor_quality_evaluator.evaluate_quality(
                            frame, bbox, landmarks, det_score=float(face.score)
                        )
                        track_id = _get_or_create_browser_track(embedding, bbox, camera_id)
                        vis_res = visitor_manager.resolve_unregistered_track(
                            db=db,
                            camera_id=camera_id,
                            track_id=track_id,
                            embedding=embedding,
                            quality_res=quality_res,
                            crop_img=aligned
                        )
                        if vis_res.is_resolved:
                            entry["person_id"] = vis_res.visitor_code
                            entry["name"] = vis_res.visitor_code
                            entry["similarity"] = vis_res.similarity
                            entry["status"] = "visitor"

                            if req.log_events:
                                _maybe_log_event(
                                    camera_id=camera_id,
                                    person_id=vis_res.visitor_code,
                                    name=vis_res.visitor_code,
                                    similarity=vis_res.similarity,
                                    quality_score=float(blur_score) if is_good else 0.0,
                                )
                        else:
                            entry["person_id"] = "unknown"
                            entry["name"] = vis_res.visitor_code
                            entry["similarity"] = 0.0
                            entry["status"] = "identifying"
                    finally:
                        db.close()
                except Exception as vis_err:
                    logger.error(f"Error in browser visitor resolution: {vis_err}")
                    entry["similarity"] = round(float(best["similarity"]), 4) if best else 0.0
                    entry["status"] = "low_confidence"
        else:
            entry["status"] = "no_landmarks"

        results.append(entry)

    return APIResponse(
        status="success",
        message=f"Analyzed frame — {len(results)} face(s) detected.",
        data={
            "faces": results,
            "frame_width": int(frame.shape[1]),
            "frame_height": int(frame.shape[0]),
            "camera_id": camera_id,
        },
    )
