from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Form, File, UploadFile
from app.models.schemas import RegisterStartRequest, SnapshotRegisterRequest, APIResponse

from app.core.stream import camera_manager
from app.services.registration.registration_engine import registration_engine
from app.services.detection_service import detection_service

router = APIRouter(tags=["Face Registration"])

@router.post("/register/start", response_model=APIResponse)
def start_registration(req: RegisterStartRequest):
    """Begins face registration session for a person."""
    from app.services.camera.camera_registry import camera_registry
    with camera_registry.lock:
        active_workers = [w for w in camera_registry.workers.values() if w.is_active()]

    if not active_workers and not camera_manager.is_active():
        camera_manager.start()

    success, msg = registration_engine.start_registration(req.person_id, req.name)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    if not active_workers:
        detection_service.start_recognition()

    return APIResponse(
        status="success",
        message=msg,
        data={"person_id": req.person_id, "name": req.name}
    )

@router.post("/register/save", response_model=APIResponse)
def save_registration():
    """Saves captured quality face samples and updates FAISS and Database."""
    success, msg = registration_engine.save_registration()
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return APIResponse(
        status="success",
        message=msg
    )

@router.get("/register/status", response_model=APIResponse)
def get_registration_status():
    """Returns live registration session status, sample count, and status feedback."""
    status_data = {
        "is_registering": registration_engine.is_registering,
        "target_person_id": registration_engine.target_person_id,
        "target_name": registration_engine.target_name,
        "samples_collected": len(registration_engine.collected_samples),
        "target_samples": registration_engine.target_samples,
    }
    return APIResponse(
        status="success",
        message="Registration status retrieved.",
        data=status_data
    )

@router.post("/register/upload", response_model=APIResponse)
async def upload_registration(
    person_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    department: Optional[str] = Form(default=None),
    role: Optional[str] = Form(default=None),
    phone: Optional[str] = Form(default=None),
    email: Optional[str] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(...)
):
    """Registers a person by uploading 1 or more face photo files."""
    bytes_list = []
    for upload in files:
        contents = await upload.read()
        if contents:
            bytes_list.append(contents)

    success, msg, count = registration_engine.register_from_uploads(
        person_id=person_id,
        name=f"{first_name} {last_name}".strip(),
        first_name=first_name,
        last_name=last_name,
        image_bytes_list=bytes_list,
        department=department,
        role=role,
        phone=phone,
        email=email,
        notes=notes
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return APIResponse(
        status="success",
        message=msg,
        data={"sample_count": count}
    )



@router.get("/detected_faces", response_model=APIResponse)
def get_detected_faces():
    """Returns list of active detected face thumbnails from all running camera pipelines."""
    from app.services.camera.camera_registry import camera_registry
    all_crops = []
    try:
        with camera_registry.lock:
            workers = dict(camera_registry.workers)
        for cam_id, worker in workers.items():
            if worker.is_active():
                try:
                    meta = worker.orchestrator.get_active_tracks_metadata()
                    for item in meta:
                        item.setdefault("camera_id", cam_id)
                    all_crops.extend(meta)
                except Exception:
                    pass
    except Exception:
        pass

    # Fallback to legacy detection_service if no new-style workers returned anything
    if not all_crops:
        all_crops = detection_service.get_recent_face_crops()

    return APIResponse(
        status="success",
        message=f"Retrieved {len(all_crops)} active face crops from stream.",
        data=all_crops
    )

@router.get("/cameras/{camera_id}/detected_faces", response_model=APIResponse)
def get_camera_detected_faces(camera_id: str):
    """Returns list of active tracked faces with metadata from the camera's pipeline worker."""
    from app.services.camera.camera_registry import camera_registry
    worker = camera_registry.workers.get(camera_id)
    if not worker:
        return APIResponse(status="success", message="Camera worker not active.", data=[])
    
    metadata = worker.orchestrator.get_active_tracks_metadata()
    return APIResponse(
        status="success",
        message=f"Retrieved {len(metadata)} active face metadata items from camera {camera_id}.",
        data=metadata
    )

@router.post("/register/snapshot", response_model=APIResponse)
def register_snapshot(req: SnapshotRegisterRequest):
    """Registers a person directly from a clicked face snapshot thumbnail."""
    success, msg = registration_engine.register_from_snapshot(req.person_id, req.name, req.crop_base64)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return APIResponse(
        status="success",
        message=msg
    )
