import base64
import logging
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, status

from app.models.schemas import APIResponse, FlexibleModel
from app.services.detection_service import detection_service
from app.services.registration.capture_service import capture_service
from app.services.registration.registration_engine import registration_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Face Registration"])


class SessionStartRequest(FlexibleModel):
    person_id: str
    first_name: str
    last_name: str
    employee_id: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    role: Optional[str] = "Employee"
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class FrameProcessRequest(FlexibleModel):
    image_base64: str
    method: Optional[str] = "WEBCAM"


class TrackSelectRequest(FlexibleModel):
    track_id: int
    camera_id: Optional[str] = None


class FaceSelectRequest(FlexibleModel):
    camera_id: str
    detection_id: Optional[str] = None
    bbox: Optional[List[float]] = None


def _bbox_iou(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _get_camera_frame_and_faces(camera_id: str):
    """Resolve current frame + face detections from the shared camera pipeline."""
    from app.services.camera.camera_registry import camera_registry

    with camera_registry.lock:
        worker = camera_registry.workers.get(camera_id)

    if worker is None or not worker.is_active():
        return None, []

    orch = worker.orchestrator
    ret, frame = orch.raw_buffer.peek()
    if not ret or frame is None:
        return None, []

    meta = orch.get_active_tracks_metadata()
    return frame, meta


def _meta_to_face_obj(item: Dict[str, Any]):
    """Build a DetectedFace-like object from pipeline metadata."""
    from types import SimpleNamespace

    return SimpleNamespace(
        bbox=item.get("bbox") or [],
        landmarks=item.get("landmarks"),
        score=float(item.get("confidence", item.get("score", 0.95))),
        track_id=item.get("track_id"),  # internal continuity only
    )


# --- Wizard Session Endpoints ---

@router.post("/register/session/start", response_model=APIResponse)
def start_wizard_session(req: SessionStartRequest):
    """Step 1: Starts a new enterprise registration wizard session."""
    res = registration_engine.start_session(
        person_id=req.person_id,
        first_name=req.first_name,
        last_name=req.last_name,
        employee_id=req.employee_id,
        department=req.department,
        designation=req.designation,
        role=req.role,
        phone=req.phone,
        email=req.email,
        notes=req.notes,
    )
    return APIResponse(status="success", message=res["message"], data=res)


@router.post("/register/session/frame", response_model=APIResponse)
def process_wizard_frame(req: FrameProcessRequest):
    """Step 3: Evaluates live webcam frame (base64). CCTV uses shared pipeline."""
    try:
        data = req.image_base64
        if not data or len(data) < 10:
            return APIResponse(
                status="success",
                message="Empty frame payload",
                data={"is_registering": True, "ai_assistant": {"status": "Waiting for camera frame..."}},
            )

        if "," in data:
            data = data.split(",")[1]

        missing_padding = len(data) % 4
        if missing_padding:
            data += "=" * (4 - missing_padding)

        img_bytes = base64.b64decode(data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        if nparr.size == 0:
            return APIResponse(
                status="success",
                message="Empty image buffer",
                data={"is_registering": True, "ai_assistant": {"status": "Frame buffer empty"}},
            )

        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return APIResponse(
                status="success",
                message="Could not decode frame image",
                data={"is_registering": True, "ai_assistant": {"status": "Decoding frame..."}},
            )

        from app.core.detector import detector_engine

        detected_faces = detector_engine.detect(frame)
        result = registration_engine.process_frame(frame, detected_faces, method=req.method or "WEBCAM")
        return APIResponse(status="success", message="Frame processed", data=result)

    except Exception as e:
        import traceback

        logger.error("Error processing registration frame: %s\n%s", e, traceback.format_exc())
        return APIResponse(
            status="error",
            message=f"Frame processing error: {str(e)}",
            data={
                "is_registering": True,
                "ai_assistant": {
                    "face_detected": False,
                    "centered": False,
                    "sharp": False,
                    "lighting": False,
                    "eyes_visible": False,
                    "guidance": "Position face in frame",
                    "status": "Frame evaluation active",
                },
            },
        )


@router.post("/register/session/select_face", response_model=APIResponse)
def select_registration_face(req: FaceSelectRequest):
    """
    Face-first CCTV selection: operator clicks a FACE box.
    Backend locates the face on the current frame and locks a temporary identity template.
    """
    if not registration_engine.is_registering:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active registration session")

    frame, meta = _get_camera_frame_and_faces(req.camera_id)
    if frame is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera frame unavailable")

    selected_item = None

    if req.detection_id:
        for item in meta:
            if item.get("detection_id") == req.detection_id:
                selected_item = item
                break

    if selected_item is None and req.bbox:
        best_iou = 0.0
        for item in meta:
            iou = _bbox_iou(req.bbox, item.get("bbox") or [])
            if iou > best_iou:
                best_iou = iou
                selected_item = item
        if best_iou < 0.15:
            selected_item = None

    if selected_item is None:
        # Fallback: run fresh detection and match by bbox IoU
        from app.core.detector import detector_engine

        faces = detector_engine.detect(frame)
        best_iou = 0.0
        best_face = None
        if req.bbox:
            for face in faces:
                iou = _bbox_iou(req.bbox, list(face.bbox))
                if iou > best_iou:
                    best_iou = iou
                    best_face = face
        if best_face is None or best_iou < 0.15:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not locate the selected face in the current frame. Try again.",
            )
        result = registration_engine.select_face(frame, best_face, camera_id=req.camera_id)
    else:
        face_obj = _meta_to_face_obj(selected_item)
        if not face_obj.landmarks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected face has no landmarks. Try again.",
            )
        result = registration_engine.select_face(frame, face_obj, camera_id=req.camera_id)

    if result.get("status") != "success":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("message", "Face select failed"))

    return APIResponse(status="success", message=result["message"], data=result)


@router.post("/register/session/track_select", response_model=APIResponse)
def lock_cctv_track(req: TrackSelectRequest):
    """
    Legacy compatibility endpoint.
    Prefer /register/session/select_face for face-first enrollment.
    """
    if req.track_id < 0:
        res = registration_engine.unlock_target()
        return APIResponse(status="success", message=res["message"], data=res)

    frame, meta = _get_camera_frame_and_faces(req.camera_id or "")
    selected = None
    for item in meta:
        if item.get("track_id") == req.track_id:
            selected = item
            break

    if selected is None or frame is None:
        # Soft-lock for legacy clients; face-first path still preferred
        capture_service.lock_track(req.track_id, req.camera_id)
        registration_engine.target_track_id = req.track_id
        registration_engine.locked_camera_id = req.camera_id
        registration_engine.target_locked = True
        registration_engine.target_state = "TARGET_LOCKED"
        return APIResponse(
            status="success",
            message="Legacy track lock applied",
            data={"camera_id": req.camera_id},
        )

    face_obj = _meta_to_face_obj(selected)
    result = registration_engine.select_face(frame, face_obj, camera_id=req.camera_id)
    return APIResponse(status="success", message=result.get("message", "Face locked"), data=result)


@router.delete("/register/session/sample/{sample_id}", response_model=APIResponse)
def remove_gallery_sample(sample_id: str):
    """Step 4: Removes a face sample during Gallery Review."""
    res = registration_engine.remove_sample(sample_id)
    return APIResponse(status=res["status"], message=res["message"], data=res)


@router.post("/register/session/check_duplicate", response_model=APIResponse)
def check_session_duplicate():
    """
    Step 4: Non-destructive soft/hard duplicate assessment against FAISS.
    Does not write to DB or FAISS. Commit path remains unchanged.
    """
    data = registration_engine.assess_duplicate_status()
    level = data.get("level", "none")
    if level == "hard":
        message = "Hard duplicate match detected"
    elif level == "soft":
        message = "Possible duplicate match detected"
    else:
        message = "No duplicate match detected"
    return APIResponse(status="success", message=message, data=data)


@router.post("/register/session/commit", response_model=APIResponse)
def commit_wizard_registration():
    """Step 5: Final enrollment into DB + FAISS using production embedding pipeline."""
    success, msg, data = registration_engine.commit_registration()
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return APIResponse(status="success", message=msg, data=data)


@router.delete("/register/session", response_model=APIResponse)
def cancel_registration_session():
    """Cancel active registration and clean temporary resources."""
    res = registration_engine.cancel_session()
    return APIResponse(status="success", message=res["message"], data=res)


# --- Legacy Compatibility Endpoints ---

@router.post("/register/start", response_model=APIResponse)
def start_registration(req: FlexibleModel):
    p_id = getattr(req, "person_id", "P_001")
    name = getattr(req, "name", "Person")
    parts = name.split(" ")
    res = registration_engine.start_session(
        person_id=p_id, first_name=parts[0], last_name=" ".join(parts[1:])
    )
    return APIResponse(status="success", message=res["message"], data={"person_id": p_id, "name": name})


@router.post("/register/save", response_model=APIResponse)
def save_registration():
    success, msg, data = registration_engine.commit_registration()
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return APIResponse(status="success", message=msg, data=data)


@router.get("/register/status", response_model=APIResponse)
def get_registration_status():
    from app.config import settings
    from app.services.registration.gallery_service import gallery_service

    samples = gallery_service.get_formatted_gallery()
    state = getattr(registration_engine, "target_state", "WAITING_FOR_SELECTION")
    status_data = {
        "is_registering": registration_engine.is_registering,
        "session_id": registration_engine.session_id,
        "target_person_id": registration_engine.person_id,
        "target_name": registration_engine.person_name,
        "samples_collected": len(gallery_service.samples),
        "target_samples": registration_engine.target_samples,
        "min_samples": settings.REGISTRATION_MIN_SAMPLES,
        "max_samples": settings.REGISTRATION_MAX_SAMPLES,
        "gallery": samples,
        "state": state,
        # Keep locked_track_id null for UI — face-first does not expose track IDs
        "locked_track_id": None,
        "target_locked": registration_engine.target_locked,
        "active_camera_id": registration_engine.locked_camera_id,
        "pose_coverage": getattr(registration_engine, "pose_coverage", {}),
        "target": {
            "camera_id": registration_engine.locked_camera_id,
            "visible": bool(
                registration_engine.target_locked and state not in ("TARGET_LOST", "WAITING_FOR_SELECTION")
            ),
            "identity_verified": registration_engine.last_ai_assistant.get("identity_verified", False)
            if isinstance(registration_engine.last_ai_assistant, dict)
            else False,
            "bbox": registration_engine.target_face_bbox,
            "thumbnail": registration_engine.target_thumbnail,
            "similarity": getattr(registration_engine, "last_target_similarity", 0.0),
        },
        "progress": {
            "captured": len(gallery_service.samples),
            "target": registration_engine.target_samples,
            "percentage": int(
                min(1.0, len(gallery_service.samples) / max(1, registration_engine.target_samples)) * 100
            ),
        },
        "ai_assistant": getattr(
            registration_engine,
            "last_ai_assistant",
            {
                "face_detected": False,
                "centered": False,
                "sharp": False,
                "lighting": False,
                "eyes_visible": False,
                "guidance": "Click a face to begin registration",
                "status": "Ready for capture",
            },
        ),
    }
    return APIResponse(status="success", message="Registration status retrieved.", data=status_data)


def _nms_face_detections(faces: List[Dict[str, Any]], iou_thresh: float = 0.40) -> List[Dict[str, Any]]:
    """
    Keep a single box per physical face.
    Prefer higher confidence / larger face when boxes overlap.
    """
    valid = [f for f in faces if f.get("bbox") and len(f["bbox"]) == 4]
    if len(valid) <= 1:
        return valid

    def rank(f: Dict[str, Any]) -> float:
        b = f["bbox"]
        area = max(0.0, float(b[2] - b[0]) * float(b[3] - b[1]))
        conf = float(f.get("confidence", f.get("score", 0.5)) or 0.5)
        quality = float(f.get("quality", 0.0) or 0.0)
        return conf * 2.0 + quality + (area / 10000.0)

    ordered = sorted(valid, key=rank, reverse=True)
    kept: List[Dict[str, Any]] = []
    for face in ordered:
        if any(_bbox_iou(face["bbox"], k["bbox"]) >= iou_thresh for k in kept):
            continue
        kept.append(face)
    return kept


@router.get("/detected_faces", response_model=APIResponse)
def get_detected_faces():
    """
    Face detections for CCTV registration overlays.
    Returns ONE bounding box per face (IoU-NMS deduped).
    """
    from app.services.camera.camera_registry import camera_registry

    all_faces: List[Dict[str, Any]] = []
    try:
        with camera_registry.lock:
            workers = dict(camera_registry.workers)
        for cam_id, worker in workers.items():
            if not worker.is_active():
                continue
            try:
                meta = worker.orchestrator.get_active_tracks_metadata()
                cam_faces: List[Dict[str, Any]] = []
                for item in meta:
                    bbox = item.get("bbox")
                    if not bbox or len(bbox) != 4:
                        continue
                    tid = item.get("track_id", 0)
                    public = {
                        "detection_id": item.get("detection_id") or f"{cam_id}_face_{tid}",
                        "bbox": [float(v) for v in bbox],
                        "confidence": float(item.get("confidence", item.get("score", 0.95)) or 0.95),
                        "quality": item.get("quality"),
                        "camera_id": cam_id,
                        "landmarks": item.get("landmarks"),
                    }
                    if not registration_engine.target_locked:
                        public["crop_base64"] = item.get("crop_base64", "")
                    cam_faces.append(public)

                # One box per face for this camera
                all_faces.extend(_nms_face_detections(cam_faces, iou_thresh=0.40))
            except Exception:
                pass
    except Exception:
        pass

    if not all_faces:
        legacy = detection_service.get_recent_face_crops()
        legacy_faces = []
        for i, item in enumerate(legacy or []):
            bbox = item.get("bbox")
            if not bbox:
                continue
            legacy_faces.append(
                {
                    "detection_id": item.get("detection_id", f"legacy_face_{i}"),
                    "bbox": bbox,
                    "confidence": float(item.get("confidence", 0.9) or 0.9),
                    "quality": item.get("quality"),
                    "camera_id": item.get("camera_id"),
                    "crop_base64": item.get("crop_base64", ""),
                }
            )
        all_faces = _nms_face_detections(legacy_faces, iou_thresh=0.40)

    return APIResponse(
        status="success",
        message=f"Retrieved {len(all_faces)} face detections.",
        data=all_faces,
    )
