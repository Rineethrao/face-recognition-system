from typing import Optional
from fastapi import APIRouter, Depends, Query
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session

from app.models.schemas import RecognitionStartRequest, RecognitionEvent, PersonResponse, APIResponse
from app.models.db_models import PersonModel, RecognitionLogModel
from app.core.database import get_db
from app.core.stream import camera_manager
from app.services.camera.camera_registry import resolve_camera_source
from app.services.detection_service import detection_service

router = APIRouter(tags=["Face Recognition"])

@router.post("/recognition/start", response_model=APIResponse)
def start_recognition(req: Optional[RecognitionStartRequest] = None):
    """Starts real-time face detection, tracking, and FAISS recognition loop."""
    from app.services.camera.camera_registry import camera_registry
    with camera_registry.lock:
        active_workers = [w for w in camera_registry.workers.values() if w.is_active()]

    if req and req.source:
        resolved_src, _, rotation = resolve_camera_source(req.source)
        camera_manager.stop()
        camera_manager.source = camera_manager._parse_source(resolved_src)
        camera_manager.set_rotation(rotation)

    if not active_workers:
        if not camera_manager.is_active():
            camera_manager.start()
        detection_service.start_recognition()

    return APIResponse(
        status="success",
        message="Face recognition pipeline started successfully.",
        data={"is_recognizing": True, "camera_source": camera_manager.source}
    )

@router.post("/recognition/stop", response_model=APIResponse)
def stop_recognition():
    """Stops real-time face recognition loop."""
    detection_service.stop_recognition()
    return APIResponse(
        status="success",
        message="Face recognition pipeline stopped.",
        data={"is_recognizing": False}
    )

@router.get("/recognitions", response_model=APIResponse)
def get_recognitions(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    """Returns list of recognized person events."""
    logs = db.query(RecognitionLogModel).order_by(RecognitionLogModel.id.desc()).limit(limit).all()
    events = [
        RecognitionEvent(
            id=log.id,
            person_id=log.person_id,
            name=log.name,
            similarity=log.similarity,
            track_id=log.track_id,
            camera_id=getattr(log, 'camera_id', 'default') or 'default',
            embedding_version=getattr(log, 'embedding_version', 1) or 1,
            quality_score=getattr(log, 'quality_score', 0.0) or 0.0,
            recognized_at=log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        )
        for log in logs
    ]
    return APIResponse(
        status="success",
        message=f"Retrieved {len(events)} recent recognition events.",
        data=events
    )

@router.get("/persons", response_model=APIResponse)
def get_persons(db: Session = Depends(get_db)):
    """Returns list of registered persons and their embedding counts."""
    import os
    persons = db.query(PersonModel).all()
    result = []
    for p in persons:
        emb_count = len(p.embeddings)
        face_images = []
        for emb in p.embeddings:
            if emb.image_path:
                filename = os.path.basename(emb.image_path)
                face_images.append(f"/faces/{p.person_id}/{filename}")

        result.append(PersonResponse(
            person_id=p.person_id,
            name=p.name,
            first_name=getattr(p, 'first_name', None),
            last_name=getattr(p, 'last_name', None),
            department=p.department,
            role=p.role,
            phone=getattr(p, 'phone', None),
            email=getattr(p, 'email', None),
            notes=getattr(p, 'notes', None),
            embedding_count=emb_count,
            registered_at=p.registered_at.strftime("%Y-%m-%d %H:%M:%S") if p.registered_at else "",
            face_images=face_images
        ))


    return APIResponse(
        status="success",
        message=f"Retrieved {len(result)} registered persons.",
        data=result
    )

@router.delete("/persons/{person_id}", response_model=APIResponse)
def delete_person(person_id: str, db: Session = Depends(get_db)):
    """Deletes a registered person, stored face crops, and FAISS vector index records."""
    import shutil
    from fastapi import HTTPException
    from app.config import settings
    from app.core.faiss_index import faiss_manager

    person = db.query(PersonModel).filter(PersonModel.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found.")

    person_name = person.name

    # 1. Delete DB records (person, embeddings, recognition logs)
    db.query(RecognitionLogModel).filter(RecognitionLogModel.person_id == person_id).delete()
    db.delete(person)
    db.commit()

    # 2. Clear recognition service track cache and recent events
    from app.services.recognition_service import recognition_service
    from app.services.detection_service import detection_service
    
    recognition_service.track_cache.clear()
    detection_service.recent_events = [e for e in detection_service.recent_events if e.person_id != person_id]

    # 3. Delete FAISS vectors
    faiss_manager.remove_person(person_id)

    # 4. Delete stored face image directory from disk
    person_dir = settings.FACES_DIR / person_id
    if person_dir.exists():
        shutil.rmtree(person_dir, ignore_errors=True)

    return APIResponse(
        status="success",
        message=f"Successfully deleted person '{person_name}' ({person_id}) and all associated logs."
    )


