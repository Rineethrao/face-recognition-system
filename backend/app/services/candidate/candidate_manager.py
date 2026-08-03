import os
import cv2
import json
import time
import uuid
import logging
import numpy as np
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

from app.config import settings
from app.core.database import SessionLocal
from app.models.db_models import CandidateModel, CandidateImageModel
from app.core.utils import evaluate_face_quality
from app.core.recognizer import arcface_recognizer
from app.services.quality.quality_engine import quality_engine
from app.services.quality.pose_diversity import pose_diversity_engine
from app.services.quality.duplicate_engine import duplicate_engine

logger = logging.getLogger(__name__)

class CandidateManager:
    """
    Enterprise Candidate Aggregation Engine.
    Manages operator-initiated face candidate collection across multiple cameras.
    Aggregates best quality multi-pose images before final person registration.
    """
    def __init__(self):
        self.candidate_dir = settings.STORAGE_DIR / "candidates"
        os.makedirs(self.candidate_dir, exist_ok=True)

    def create_candidate_from_crop(
        self,
        crop_image: np.ndarray,
        camera_id: str = "default",
        track_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Creates a new candidate from an operator-selected face snapshot.
        Extracts embedding, computes quality metrics, saves snapshot to disk and DB.
        """
        if crop_image is None or crop_image.size == 0:
            return False, "Invalid face image crop", {}

        if crop_image.shape[:2] != (112, 112):
            crop_image = cv2.resize(crop_image, (112, 112))

        embedding = arcface_recognizer.extract_embedding(crop_image)
        blur_score = quality_engine.calculate_blur(crop_image)

        candidate_id = f"cand_{uuid.uuid4().hex[:8]}"
        c_dir = self.candidate_dir / candidate_id
        os.makedirs(c_dir, exist_ok=True)

        img_path = c_dir / "sample_1.jpg"
        cv2.imwrite(str(img_path), crop_image)

        db = SessionLocal()
        try:
            now = datetime.utcnow()
            candidate = CandidateModel(
                candidate_id=candidate_id,
                status="READY",
                avg_quality=0.85,
                seen_cameras=json.dumps([camera_id]),
                first_seen=now,
                last_seen=now,
                created_at=now
            )
            db.add(candidate)

            c_image = CandidateImageModel(
                candidate_id=candidate_id,
                image_path=str(img_path),
                embedding_blob=embedding.tobytes(),
                quality_score=0.85,
                pose_bin="FRONTAL",
                camera_id=camera_id,
                created_at=now
            )
            db.add(c_image)
            db.commit()

            logger.info(f"Candidate {candidate_id} created successfully from camera {camera_id}.")
            return True, f"Candidate {candidate_id} created successfully", {
                "candidate_id": candidate_id,
                "status": "READY",
                "image_path": str(img_path)
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating candidate: {e}", exc_info=True)
            return False, f"Failed to create candidate: {str(e)}", {}
        finally:
            db.close()

    def list_candidates(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all candidates and their metadata."""
        db = SessionLocal()
        try:
            query = db.query(CandidateModel)
            if status:
                query = query.filter(CandidateModel.status == status)
            candidates = query.order_by(CandidateModel.created_at.desc()).all()

            results = []
            for c in candidates:
                images = []
                for img in c.images:
                    filename = os.path.basename(img.image_path)
                    web_url = f"/faces/candidates/{c.candidate_id}/{filename}"
                    images.append({
                        "id": img.id,
                        "image_path": img.image_path,
                        "image_url": web_url,
                        "quality_score": img.quality_score,
                        "pose_bin": img.pose_bin,
                        "camera_id": img.camera_id,
                        "created_at": img.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    })

                cameras_list = json.loads(c.seen_cameras) if c.seen_cameras else []
                results.append({
                    "candidate_id": c.candidate_id,
                    "status": c.status,
                    "avg_quality": c.avg_quality,
                    "seen_cameras": cameras_list,
                    "image_count": len(c.images),
                    "first_seen": c.first_seen.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_seen": c.last_seen.strftime("%Y-%m-%d %H:%M:%S"),
                    "created_at": c.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "images": images
                })
            return results
        finally:
            db.close()

candidate_manager = CandidateManager()
