import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.core.database import SessionLocal
from app.models.db_models import RecognitionLogModel

logger = logging.getLogger(__name__)

class MultiCameraMergeService:
    """
    Enterprise Multi-Camera Person Timeline Aggregator.
    Merges independent camera recognition events into unified cross-camera person movement timelines.
    """
    def get_person_timeline(self, person_id: str, limit: int = 50) -> Dict[str, Any]:
        """Returns consolidated camera timeline for a specific person."""
        db = SessionLocal()
        try:
            logs = db.query(RecognitionLogModel).filter(
                RecognitionLogModel.person_id == person_id
            ).order_by(RecognitionLogModel.timestamp.desc()).limit(limit).all()

            if not logs:
                return {
                    "person_id": person_id,
                    "last_seen": None,
                    "active_cameras": [],
                    "timeline": []
                }

            timeline = []
            seen_cameras = set()
            now = time.time()

            for log in logs:
                cam_id = log.camera_id or "default"
                seen_cameras.add(cam_id)
                timeline.append({
                    "id": log.id,
                    "camera_id": cam_id,
                    "similarity": log.similarity,
                    "track_id": log.track_id,
                    "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                })

            last_seen = logs[0].timestamp.strftime("%Y-%m-%d %H:%M:%S")

            return {
                "person_id": person_id,
                "name": logs[0].name,
                "last_seen": last_seen,
                "total_detections": len(logs),
                "unique_cameras": list(seen_cameras),
                "timeline": timeline
            }
        finally:
            db.close()

multi_camera_merge_service = MultiCameraMergeService()
