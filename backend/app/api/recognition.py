from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Session

from app.models.schemas import RecognitionStartRequest, RecognitionEvent, PersonResponse, APIResponse, FlexibleModel
from app.models.db_models import PersonModel, RecognitionLogModel
from app.core.database import get_db
from app.core.stream import camera_manager
from app.services.camera.camera_registry import resolve_camera_source
from app.services.detection_service import detection_service

router = APIRouter(tags=["Face Recognition"])


class PersonUpdateRequest(FlexibleModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None

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
def get_recognitions(
    limit: int = Query(default=200, ge=1, le=2000),
    person_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Returns recognition events from persistent history (not only live buffer)."""
    import os

    query = db.query(RecognitionLogModel)
    if person_id:
        query = query.filter(RecognitionLogModel.person_id == person_id)

    logs = query.order_by(RecognitionLogModel.id.desc()).limit(limit).all()
    events = [
        {
            "id": log.id,
            "person_id": log.person_id,
            "name": log.name,
            "similarity": log.similarity,
            "track_id": log.track_id,
            "camera_id": getattr(log, "camera_id", "default") or "default",
            "embedding_version": getattr(log, "embedding_version", 1) or 1,
            "quality_score": getattr(log, "quality_score", 0.0) or 0.0,
            "recognized_at": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
            "face_snapshot_url": (
                f"/faces/snapshots/{os.path.basename(log.face_snapshot_path)}"
                if log.face_snapshot_path
                else None
            ),
        }
        for log in logs
    ]
    return APIResponse(
        status="success",
        message=f"Retrieved {len(events)} recognition events.",
        data=events,
    )


@router.get("/recognitions/summary", response_model=APIResponse)
def get_recognition_summaries(
    search: Optional[str] = Query(default=None, description="Filter by name, person_id, or camera"),
    db: Session = Depends(get_db),
):
    """
    Person-level recognition history summaries across ALL stored detections.
    Used by Events grouped view so previously detected people (not only live) appear.
    """
    from sqlalchemy import func

    # Aggregate full history per person
    rows = (
        db.query(
            RecognitionLogModel.person_id,
            func.count(RecognitionLogModel.id).label("total_count"),
            func.avg(RecognitionLogModel.similarity).label("avg_similarity"),
            func.max(RecognitionLogModel.id).label("last_log_id"),
        )
        .group_by(RecognitionLogModel.person_id)
        .all()
    )

    if not rows:
        return APIResponse(status="success", message="No recognition history.", data=[])

    last_ids = [r.last_log_id for r in rows if r.last_log_id is not None]
    last_logs = {
        log.id: log
        for log in db.query(RecognitionLogModel).filter(RecognitionLogModel.id.in_(last_ids)).all()
    }

    # Prefer current registered display name when available
    person_names = {
        p.person_id: p.name
        for p in db.query(PersonModel).all()
    }

    summaries = []
    for row in rows:
        last = last_logs.get(row.last_log_id)
        pid = row.person_id
        name = person_names.get(pid) or (last.name if last else pid)
        camera_id = (last.camera_id if last and last.camera_id else "default")
        last_seen = last.timestamp.strftime("%Y-%m-%d %H:%M:%S") if last and last.timestamp else ""

        item = {
            "person_id": pid,
            "name": "Unknown Person" if pid == "unknown" else name,
            "total_count": int(row.total_count or 0),
            "avg_confidence": float(row.avg_similarity or 0.0),
            "last_seen_time": last_seen,
            "last_seen_camera": camera_id,
        }

        if search:
            q = search.lower().strip()
            hay = f"{item['name']} {item['person_id']} {item['last_seen_camera']}".lower()
            if q not in hay:
                continue

        summaries.append(item)

    summaries.sort(key=lambda s: s["last_seen_time"] or "", reverse=True)

    return APIResponse(
        status="success",
        message=f"Retrieved {len(summaries)} person recognition summaries.",
        data=summaries,
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


@router.put("/persons/{person_id}", response_model=APIResponse)
def update_person(person_id: str, req: PersonUpdateRequest, db: Session = Depends(get_db)):
    """Update registered person metadata (name, department, role, contact, notes)."""
    from app.core.faiss_index import faiss_manager

    person = db.query(PersonModel).filter(PersonModel.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found.")

    first_name = (req.first_name or "").strip()
    last_name = (req.last_name or "").strip()
    full_name = (req.name or "").strip()
    if first_name or last_name:
        full_name = f"{first_name} {last_name}".strip()
    elif not full_name:
        full_name = person.name or ""

    if not full_name:
        raise HTTPException(status_code=400, detail="Name is required.")

    person.first_name = first_name or full_name.split(" ")[0]
    person.last_name = last_name if last_name or req.last_name is not None else (
        " ".join(full_name.split(" ")[1:]) if " " in full_name else (person.last_name or "")
    )
    person.name = full_name
    if req.department is not None:
        person.department = req.department or None
    if req.role is not None:
        person.role = req.role or None
    if req.phone is not None:
        person.phone = req.phone or None
    if req.email is not None:
        person.email = req.email or None
    if req.notes is not None:
        person.notes = req.notes or None
    person.updated_at = datetime.utcnow()
    db.commit()

    try:
        faiss_manager.update_person_name(person_id, full_name)
    except Exception:
        pass

    return APIResponse(
        status="success",
        message=f"Updated person '{full_name}' ({person_id}).",
        data={
            "person_id": person.person_id,
            "name": person.name,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "department": person.department,
            "role": person.role,
            "phone": person.phone,
            "email": person.email,
            "notes": person.notes,
        },
    )

