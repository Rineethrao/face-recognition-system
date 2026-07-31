import os
from typing import Optional
from fastapi import APIRouter, HTTPException, status

from app.models.schemas import APIResponse, PersonDetailResponse, PersonGalleryImage
from app.core.database import SessionLocal
from app.models.db_models import PersonModel, PersonImageModel, RecognitionLogModel
from app.services.registration_service import registration_service

router = APIRouter(prefix="/persons", tags=["Person Gallery & Versioning"])

@router.get("/{person_id}/detail", response_model=APIResponse)
def get_person_detail(person_id: str):
    """Retrieves full person profile details including active and archived versioned gallery images."""
    db = SessionLocal()
    try:
        person = db.query(PersonModel).filter(PersonModel.person_id == person_id).first()
        if not person:
            raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found.")

        active_imgs = []
        archived_imgs = []

        for img in person.images:
            filename = os.path.basename(img.image_path)
            web_url = f"/faces/{person_id}/{filename}"
            g_img = PersonGalleryImage(
                id=img.id,
                image_url=web_url,
                quality_score=img.quality_score or 0.85,
                pose_bin=img.pose_bin or "FRONTAL",
                gallery_version=img.gallery_version or 1,
                is_active=img.is_active if img.is_active is not None else True,
                created_at=img.created_at.strftime("%Y-%m-%d %H:%M:%S") if img.created_at else ""
            )
            if img.is_active:
                active_imgs.append(g_img)
            else:
                archived_imgs.append(g_img)

        data = PersonDetailResponse(
            person_id=person.person_id,
            name=person.name,
            department=person.department,
            role=person.role,
            gallery_version=person.gallery_version or 1,
            registered_at=person.registered_at.strftime("%Y-%m-%d %H:%M:%S") if person.registered_at else "",
            active_images=active_imgs,
            archived_images=archived_imgs
        )
        return APIResponse(status="success", message="Person details retrieved.", data=data)
    finally:
        db.close()

@router.get("/{person_id}/timeline", response_model=APIResponse)
def get_person_timeline(person_id: str):
    """Retrieves movement timeline for a registered person."""
    db = SessionLocal()
    try:
        logs = db.query(RecognitionLogModel).filter(
            RecognitionLogModel.person_id == person_id
        ).order_by(RecognitionLogModel.id.desc()).limit(50).all()

        events = [
            {
                "id": log.id,
                "camera_id": getattr(log, 'camera_id', 'default') or 'default',
                "similarity": log.similarity,
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else ""
            }
            for log in logs
        ]
        return APIResponse(status="success", message="Person timeline retrieved.", data=events)
    finally:
        db.close()

@router.delete("/{person_id}", response_model=APIResponse)
def delete_person(person_id: str):
    """Deletes a person profile, database embeddings, FAISS index vectors, and disk images."""
    success = registration_service.delete_person(person_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Person '{person_id}' not found or deletion failed.")
    return APIResponse(status="success", message=f"Person '{person_id}' deleted successfully.")
