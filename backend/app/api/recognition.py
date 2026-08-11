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

def apply_recognition_log_filters(query, date_key: Optional[str] = None, category: Optional[str] = None):
    from sqlalchemy import func
    if hasattr(date_key, "default"):
        date_key = date_key.default
    if hasattr(category, "default"):
        category = category.default

    if isinstance(date_key, str) and date_key and date_key.lower() != "all":
        clean_key = date_key.strip()
        if "-" in clean_key:
            key_dash = clean_key
            key_nodash = clean_key.replace("-", "")
        else:
            key_nodash = clean_key
            key_dash = f"{clean_key[:4]}-{clean_key[4:6]}-{clean_key[6:8]}" if len(clean_key) == 8 and clean_key.isdigit() else clean_key

        query = query.filter(
            (func.strftime("%Y-%m-%d", RecognitionLogModel.timestamp) == key_dash) |
            (func.strftime("%Y%m%d", RecognitionLogModel.timestamp) == key_nodash)
        )

    if isinstance(category, str) and category and category.lower() != "all":
        cat = category.lower().strip()
        if cat in ["registered", "person", "persons"]:
            query = query.filter(
                ~RecognitionLogModel.person_id.like("VISITOR%"),
                RecognitionLogModel.person_id != "unknown"
            )
        elif cat in ["visitor", "visitors"]:
            query = query.filter(RecognitionLogModel.person_id.like("VISITOR%"))
        elif cat in ["unknown", "unregistered"]:
            query = query.filter(RecognitionLogModel.person_id == "unknown")

    return query



@router.get("/recognitions/dates", response_model=APIResponse)
def get_recognition_dates(db: Session = Depends(get_db)):
    """Returns available operational dates with recognition counts per date."""
    from sqlalchemy import func
    from datetime import datetime

    today_dash = datetime.now().strftime("%Y-%m-%d")

    rows = db.query(
        func.strftime("%Y-%m-%d", RecognitionLogModel.timestamp).label("date_key"),
        func.count(RecognitionLogModel.id).label("count")
    ).group_by(
        func.strftime("%Y-%m-%d", RecognitionLogModel.timestamp)
    ).all()

    items = []
    seen_dates = set()
    for row in rows:
        if not row.date_key:
            continue
        seen_dates.add(row.date_key)
        try:
            dt = datetime.strptime(row.date_key, "%Y-%m-%d")
            formatted = dt.strftime("%d-%m-%Y")
        except Exception:
            formatted = row.date_key

        items.append({
            "date_key": row.date_key,
            "date_formatted": formatted,
            "count": int(row.count or 0),
            "is_today": row.date_key == today_dash
        })

    if today_dash not in seen_dates:
        items.insert(0, {
            "date_key": today_dash,
            "date_formatted": datetime.now().strftime("%d-%m-%Y"),
            "count": 0,
            "is_today": True
        })

    items.sort(key=lambda x: x["date_key"], reverse=True)
    return APIResponse(
        status="success",
        message=f"Retrieved {len(items)} recognition dates.",
        data=items
    )


def resolve_log_snapshot_url(log: RecognitionLogModel, db: Session) -> Optional[str]:
    import os
    if log.face_snapshot_path and os.path.exists(log.face_snapshot_path):
        return f"/faces/snapshots/{os.path.basename(log.face_snapshot_path)}"

    pid = log.person_id
    if not pid or pid == "unknown":
        return None

    if pid.startswith("VISITOR"):
        from app.visitors.models import VisitorModel
        from app.api.visitors import resolve_visitor_primary_snapshot_url
        v = db.query(VisitorModel).filter(VisitorModel.visitor_code == pid).first()
        if v:
            return resolve_visitor_primary_snapshot_url(v, db)

    from app.models.db_models import PersonModel, PersonImageModel
    p = db.query(PersonModel).filter(PersonModel.person_id == pid).first()
    if p:
        img = db.query(PersonImageModel).filter(PersonImageModel.person_id == pid).order_by(PersonImageModel.id.asc()).first()
        if img and img.image_path:
            return f"/faces/{pid}/{os.path.basename(img.image_path)}"
        return f"/faces/{pid}/sample_1_frontal.jpg"

    return None


@router.get("/recognitions", response_model=APIResponse)
def get_recognitions(
    limit: int = Query(default=200, ge=1, le=2000),
    person_id: Optional[str] = Query(default=None),
    date_key: Optional[str] = Query(default=None, description="YYYY-MM-DD or 'all'"),
    category: Optional[str] = Query(default=None, description="'all', 'registered', 'visitor', 'unknown'"),
    db: Session = Depends(get_db),
):
    """Returns recognition events filtered by person, date, or category."""
    import os

    if hasattr(person_id, "default"):
        person_id = person_id.default
    if hasattr(date_key, "default"):
        date_key = date_key.default
    if hasattr(category, "default"):
        category = category.default

    query = db.query(RecognitionLogModel)
    if isinstance(person_id, str) and person_id.strip():
        query = query.filter(RecognitionLogModel.person_id == person_id.strip())

    query = apply_recognition_log_filters(query, date_key=date_key, category=category)

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
            "recognized_at": log.timestamp.strftime("%d-%m-%Y %H:%M:%S") if log.timestamp else "",
            "face_snapshot_url": resolve_log_snapshot_url(log, db)
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
    date_key: Optional[str] = Query(default=None, description="YYYY-MM-DD or 'all'"),
    category: Optional[str] = Query(default=None, description="'all', 'registered', 'visitor', 'unknown'"),
    db: Session = Depends(get_db),
):
    """
    Person-level recognition history summaries filtered by date and category.
    """
    from sqlalchemy import func

    if hasattr(search, "default"):
        search = search.default
    if hasattr(date_key, "default"):
        date_key = date_key.default
    if hasattr(category, "default"):
        category = category.default

    filtered_logs = apply_recognition_log_filters(db.query(RecognitionLogModel), date_key=date_key, category=category)

    filtered_subq = filtered_logs.subquery()

    rows = (
        db.query(
            filtered_subq.c.person_id,
            func.count(filtered_subq.c.id).label("total_count"),
            func.avg(filtered_subq.c.similarity).label("avg_similarity"),
            func.max(filtered_subq.c.id).label("last_log_id"),
            func.min(filtered_subq.c.id).label("first_log_id"),
        )
        .group_by(filtered_subq.c.person_id)
        .all()
    )

    if not rows:
        return APIResponse(status="success", message="No recognition history for the selected filters.", data=[])

    last_ids = [r.last_log_id for r in rows if r.last_log_id is not None]
    first_ids = [r.first_log_id for r in rows if r.first_log_id is not None]
    lookup_ids = list({*last_ids, *first_ids})
    logs_by_id = {
        log.id: log
        for log in db.query(RecognitionLogModel).filter(RecognitionLogModel.id.in_(lookup_ids)).all()
    }

    person_names = {
        p.person_id: p.name
        for p in db.query(PersonModel).all()
    }

    summaries = []
    for row in rows:
        last = logs_by_id.get(row.last_log_id)
        first = logs_by_id.get(row.first_log_id)
        pid = row.person_id
        name = person_names.get(pid) or (last.name if last else pid)
        camera_id = (last.camera_id if last and last.camera_id else "default")
        last_seen = last.timestamp.strftime("%d-%m-%Y %H:%M:%S") if last and last.timestamp else ""
        first_seen = first.timestamp.strftime("%d-%m-%Y %H:%M:%S") if first and first.timestamp else ""
        first_camera = (first.camera_id if first and first.camera_id else "default")

        today_date_str = datetime.now().strftime("%Y-%m-%d")
        from app.services.presence_service import presence_service
        pres = presence_service.get_live_presence(db, pid, today_date_str)

        item = {
            "person_id": pid,
            "name": "Unknown Person" if pid == "unknown" else name,
            "total_count": int(row.total_count or 0),
            "avg_confidence": float(row.avg_similarity or 0.0),
            "last_seen_time": last_seen,
            "last_seen_camera": camera_id,
            "first_seen_time": first_seen,
            "first_seen_camera": first_camera,
            "total_duration_seconds": pres["total_duration_seconds"],
            "total_duration": pres["total_duration"],
            "visit_count": pres["visit_count"],
            "is_currently_present": pres["is_currently_present"],
            "status": pres["status"],
            "face_snapshot_url": resolve_log_snapshot_url(last, db) if last else None
        }


        if search:
            q = search.lower().strip()
            hay = f"{item['name']} {item['person_id']} {item['last_seen_camera']} {item['first_seen_camera']} {item['status']}".lower()
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
    person.updated_at = datetime.now()
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

