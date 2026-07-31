import os
import cv2
import time
import logging
import threading
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional

from app.config import settings
from app.core.database import SessionLocal
from app.core.faiss_index import faiss_manager
from app.core.recognizer import arcface_recognizer
from app.models.db_models import PersonModel, PersonImageModel, EmbeddingModel, AuditLogModel
from app.services.quality.quality_engine import quality_engine
from app.services.quality.duplicate_engine import duplicate_engine
from app.services.quality.pose_diversity import pose_diversity_engine

logger = logging.getLogger(__name__)

class ProgressiveLearningEngine:
    """
    Asynchronous Progressive Learning & Self-Improving Gallery Engine.
    Executes in background daemon threads to auto-enrich person galleries
    without blocking real-time camera streaming or face recognition loops.
    """
    def queue_profile_auto_improvement(
        self,
        person_id: str,
        name: str,
        aligned_crop: np.ndarray,
        new_embedding: np.ndarray,
        match_score: float,
        camera_id: str = "default"
    ):
        """Dispatches progressive learning evaluation to a background thread."""
        # Only evaluate when identity confidence is very high (>= 0.85)
        if match_score < 0.85:
            return

        thread = threading.Thread(
            target=self._process_auto_improve,
            args=(person_id, name, aligned_crop.copy(), new_embedding.copy(), match_score, camera_id),
            daemon=True
        )
        thread.start()

    def _process_auto_improve(
        self,
        person_id: str,
        name: str,
        aligned_crop: np.ndarray,
        new_embedding: np.ndarray,
        match_score: float,
        camera_id: str
    ):
        db = SessionLocal()
        try:
            person = db.query(PersonModel).filter(PersonModel.person_id == person_id).first()
            if not person:
                return

            active_images = db.query(PersonImageModel).filter(
                PersonImageModel.person_id == person_id,
                PersonImageModel.is_active == True
            ).all()

            # 1. Quality Check (Must be high quality >= 0.80)
            eval_res = quality_engine.evaluate(aligned_crop, [0, 0, 112, 112], [[38,51],[73,51],[56,71],[41,92],[70,92]])
            quality_score = eval_res.get("quality_score", 0.70)
            if quality_score < 0.80:
                logger.debug(f"Progressive learning skipped for {person_id}: low quality ({quality_score:.2f} < 0.80)")
                return

            # 2. Duplicate Check against active gallery
            cached_embs = faiss_manager.embeddings_cache.get(person_id, [])
            if len(cached_embs) > 0:
                is_dup, max_sim = duplicate_engine.is_duplicate(new_embedding, cached_embs)
                if is_dup:
                    logger.debug(f"Progressive learning skipped for {person_id}: near-duplicate sample (sim: {max_sim:.2f})")
                    return

            pose_bin = pose_diversity_engine.classify_pose(
                eval_res.get("pose_yaw", 0.0),
                eval_res.get("pose_pitch", 0.0),
                aligned_crop=aligned_crop,
                landmarks=np.array([[38,51],[73,51],[56,71],[41,92],[70,92]])
            )
            max_gallery_samples = 10

            person_dir = settings.FACES_DIR / person_id
            os.makedirs(person_dir, exist_ok=True)

            if len(active_images) < max_gallery_samples:
                # Option A: Add new active image to gallery
                person.gallery_version += 1
                person.updated_at = datetime.utcnow()

                filename = f"gallery_v{person.gallery_version}_auto_{int(time.time())}.jpg"
                dest_path = person_dir / filename
                cv2.imwrite(str(dest_path), aligned_crop)

                new_p_img = PersonImageModel(
                    person_id=person_id,
                    image_path=str(dest_path),
                    quality_score=quality_score,
                    pose_bin=pose_bin,
                    gallery_version=person.gallery_version,
                    is_active=True,
                    camera_id=camera_id,
                    created_at=datetime.utcnow()
                )
                db.add(new_p_img)
                db.commit()

                # Add to FAISS
                faiss_ids = faiss_manager.add_vectors(person_id, name, np.array([new_embedding], dtype=np.float32))
                emb_rec = EmbeddingModel(
                    person_id=person_id,
                    faiss_id=faiss_ids[0],
                    image_id=new_p_img.id,
                    image_path=str(dest_path),
                    gallery_version=person.gallery_version,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(emb_rec)

                audit = AuditLogModel(
                    action="PROGRESSIVE_LEARNING_ADD",
                    entity_type="PERSON",
                    entity_id=person_id,
                    details=f"Added new {pose_bin} capture to {name}'s profile (version {person.gallery_version}).",
                    performed_by="auto_learning"
                )
                db.add(audit)
                db.commit()

                # Async FAISS rebuild
                threading.Thread(target=faiss_manager.rebuild_index, daemon=True).start()
                logger.info(f"[ProgressiveLearning] Added new active image v{person.gallery_version} to {person_id} ({name}).")

        except Exception as e:
            db.rollback()
            logger.error(f"Error in progressive learning worker for {person_id}: {e}", exc_info=True)
        finally:
            db.close()

progressive_learning_engine = ProgressiveLearningEngine()
