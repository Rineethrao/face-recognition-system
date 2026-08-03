from typing import Optional
from fastapi import APIRouter, Query

from app.models.schemas import APIResponse
from app.core.database import SessionLocal
from app.models.db_models import RecognitionLogModel, AuditLogModel

router = APIRouter(prefix="/history", tags=["Recognition History & Audit"])

@router.get("", response_model=APIResponse)
def get_recognition_history(
    person_id: Optional[str] = Query(None, description="Filter history by person ID"),
    camera_id: Optional[str] = Query(None, description="Filter history by camera ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Retrieves paginated recognition history events."""
    db = SessionLocal()
    try:
        query = db.query(RecognitionLogModel)
        if person_id:
            query = query.filter(RecognitionLogModel.person_id == person_id)
        if camera_id:
            query = query.filter(RecognitionLogModel.camera_id == camera_id)

        logs = query.order_by(RecognitionLogModel.id.desc()).offset(offset).limit(limit).all()
        events = [
            {
                "id": l.id,
                "person_id": l.person_id,
                "name": l.name,
                "similarity": l.similarity,
                "track_id": l.track_id,
                "camera_id": getattr(l, 'camera_id', 'default') or 'default',
                "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S") if l.timestamp else ""
            }
            for l in logs
        ]
        return APIResponse(
            status="success",
            message=f"Retrieved {len(events)} history records.",
            data=events
        )
    finally:
        db.close()

@router.get("/audit", response_model=APIResponse)
def get_audit_logs(limit: int = Query(50, ge=1, le=200)):
    """Retrieves system audit logs (registrations, gallery updates, candidate actions)."""
    db = SessionLocal()
    try:
        # NOTE: AuditLogModel only has action/person_id/details/created_at columns.
        # (Previous version referenced entity_type/entity_id/performed_by/timestamp,
        # which don't exist on the model and raised an AttributeError on every call.)
        logs = db.query(AuditLogModel).order_by(AuditLogModel.created_at.desc()).limit(limit).all()
        results = [
            {
                "id": l.id,
                "action": l.action,
                "person_id": l.person_id,
                "details": l.details,
                "timestamp": l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else ""
            }
            for l in logs
        ]
        return APIResponse(status="success", message="Audit logs retrieved.", data=results)
    finally:
        db.close()
