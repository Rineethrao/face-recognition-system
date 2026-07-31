import logging
import time
from typing import Optional, List, Dict, Any
import numpy as np
from fastapi import APIRouter
from app.projects.base import BaseProjectPlugin
from app.models.schemas import RecognitionEvent, APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/security", tags=["Project: Temple/Police Security"])

security_alerts: List[Dict[str, Any]] = []

@router.get("/alerts", response_model=APIResponse)
def get_security_alerts():
    """GET /security/alerts - Project API: Returns watchlist & missing/criminal detection alerts."""
    return APIResponse(
        status="success",
        message=f"Retrieved {len(security_alerts)} security alerts.",
        data=security_alerts
    )

class TempleSecurityPlugin(BaseProjectPlugin):
    """
    Temple / Police Security Domain Plugin:
    Triggers instant high-priority alerts when a person on the watchlist (criminal / missing) is recognized.
    """
    def __init__(self, project_name: str, config: Dict[str, Any]):
        super().__init__(project_name, config)
        self.alert_webhook = config.get("alert_webhook")

    def on_person_detected(self, frame: np.ndarray, track_id: int, bbox: List[float]):
        pass

    def on_face_recognized(self, event: RecognitionEvent):
        alert = {
            "alert_id": len(security_alerts) + 1,
            "person_id": event.person_id,
            "name": event.name,
            "alert_type": "WATCHLIST_MATCH",
            "timestamp": event.recognized_at,
            "match_similarity": event.similarity,
            "status": "ACTIVE_ALERT"
        }
        security_alerts.append(alert)
        logger.warning(f"[Temple Security Plugin] 🚨 ALERT! Watchlist Person Detected: {event.name} ({event.person_id}) | Similarity: {event.similarity:.2f}")

    def get_router(self) -> Optional[APIRouter]:
        return router
