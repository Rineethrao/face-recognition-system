import logging
from typing import Optional, List, Dict, Any
import numpy as np
from fastapi import APIRouter
from app.projects.base import BaseProjectPlugin
from app.models.schemas import RecognitionEvent, APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/retail", tags=["Project: Retail Analytics"])

customer_analytics: List[Dict[str, Any]] = []

@router.get("/analytics", response_model=APIResponse)
def get_retail_analytics():
    """GET /retail/analytics - Project API: Returns retail store staff vs customer analytics."""
    return APIResponse(
        status="success",
        message=f"Retrieved retail analytics for {len(customer_analytics)} store visits.",
        data=customer_analytics
    )

class RetailAnalyticsPlugin(BaseProjectPlugin):
    """
    Retail Analytics Domain Plugin:
    Tracks store visitor footfall and VIP staff/customer identification.
    """
    def __init__(self, project_name: str, config: Dict[str, Any]):
        super().__init__(project_name, config)

    def on_person_detected(self, frame: np.ndarray, track_id: int, bbox: List[float]):
        pass

    def on_face_recognized(self, event: RecognitionEvent):
        visit = {
            "person_id": event.person_id,
            "name": event.name,
            "category": "VIP_CUSTOMER",
            "timestamp": event.recognized_at
        }
        customer_analytics.append(visit)
        logger.info(f"[Retail Analytics Plugin] VIP Visitor Spotted: {event.name}")

    def get_router(self) -> Optional[APIRouter]:
        return router
