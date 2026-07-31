import os
import cv2
import time
import logging
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.config import settings
from app.core.database import SessionLocal
from app.models.db_models import RecognitionLogModel, AuditLogModel
from app.models.schemas import RecognitionMatch

logger = logging.getLogger(__name__)

class RecognitionHistoryService:
    """
    Enterprise Recognition History & Audit Logging Service.
    Logs recognition events, saves face snapshot crops to disk, and queries history timelines.
    """
    def __init__(self):
        self.snapshot_dir = settings.STORAGE_DIR / "snapshots"
        os.makedirs(self.snapshot_dir, exist_ok=True)

    def log_recognition_event(
        self,
        match: RecognitionMatch,
        aligned_crop: Optional[np.ndarray] = None,
        quality_score: float = 0.0,
        embedding_version: int = 1
    ) -> Optional[int]:
        if match.person_id == "unknown":
            return None

        db = SessionLocal()
        try:
            # 5-second cooldown per person per camera per track
            recent = db.query(RecognitionLogModel).filter(
                RecognitionLogModel.person_id == match.person_id,
                RecognitionLogModel.camera_id == match.camera_id,
                RecognitionLogModel.track_id == str(match.track_id)
            ).order_by(RecognitionLogModel.timestamp.desc()).first()

            if recent:
                time_diff = (datetime.utcnow() - recent.timestamp).total_seconds()
                if time_diff < 5.0:
                    return recent.id

            snapshot_path = None
            if aligned_crop is not None and aligned_crop.size > 0:
                snap_name = f"{match.person_id}_{int(time.time())}.jpg"
                full_path = self.snapshot_dir / snap_name
                cv2.imwrite(str(full_path), aligned_crop)
                snapshot_path = str(full_path)

            log_entry = RecognitionLogModel(
                person_id=match.person_id,
                name=match.name,
                similarity=match.similarity,
                track_id=str(match.track_id),
                camera_id=match.camera_id,
                embedding_version=embedding_version,
                quality_score=quality_score,
                face_snapshot_path=snapshot_path,
                timestamp=datetime.utcnow()
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)

            logger.info(f"[HISTORY LOG] {match.name} ({match.person_id}) on camera '{match.camera_id}' | Sim: {match.similarity:.2f}")
            return log_entry.id

        except Exception as e:
            db.rollback()
            logger.error(f"Error logging recognition event: {e}")
            return None
        finally:
            db.close()

    def get_history(
        self,
        person_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            query = db.query(RecognitionLogModel)
            if person_id:
                query = query.filter(RecognitionLogModel.person_id == person_id)
            if camera_id:
                query = query.filter(RecognitionLogModel.camera_id == camera_id)

            logs = query.order_by(RecognitionLogModel.timestamp.desc()).offset(offset).limit(limit).all()

            results = []
            for l in logs:
                snap_url = None
                if l.face_snapshot_path and os.path.exists(l.face_snapshot_path):
                    filename = os.path.basename(l.face_snapshot_path)
                    snap_url = f"/faces/snapshots/{filename}"

                results.append({
                    "id": l.id,
                    "person_id": l.person_id,
                    "name": l.name,
                    "similarity": l.similarity,
                    "track_id": l.track_id,
                    "camera_id": l.camera_id,
                    "embedding_version": l.embedding_version,
                    "quality_score": l.quality_score,
                    "snapshot_url": snap_url,
                    "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                })
            return results
        finally:
            db.close()

recognition_history_service = RecognitionHistoryService()
