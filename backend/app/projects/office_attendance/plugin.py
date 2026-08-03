import logging
import time
from typing import Optional, List, Dict, Any
import numpy as np
from fastapi import APIRouter
from app.projects.base import BaseProjectPlugin
from app.models.schemas import RecognitionEvent, APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/attendance", tags=["Project: Office Attendance"])

# Attendance log memory cache
attendance_records: List[Dict[str, Any]] = []

@router.get("/logs", response_model=APIResponse)
def get_attendance_logs():
    """GET /attendance/logs - Project API: Returns staff in/out attendance log records."""
    return APIResponse(
        status="success",
        message=f"Retrieved {len(attendance_records)} staff attendance records.",
        data=attendance_records
    )

class OfficeAttendancePlugin(BaseProjectPlugin):
    """
    Office Attendance Domain Plugin:
    Logs employee IN/OUT attendance events when registered faces are recognized.
    """
    def __init__(self, project_name: str, config: Dict[str, Any]):
        super().__init__(project_name, config)
        self.last_log_time: Dict[str, float] = {}
        self.cooldown_seconds = config.get("cooldown_seconds", 60)

    def on_person_detected(self, frame: np.ndarray, track_id: int, bbox: List[float]):
        pass  # Core person detection active

    def on_face_recognized(self, event: RecognitionEvent):
        now = time.time()
        last = self.last_log_time.get(event.person_id, 0.0)

        # Log attendance event if cooldown has elapsed
        if now - last > self.cooldown_seconds:
            self.last_log_time[event.person_id] = now
            record = {
                "person_id": event.person_id,
                "name": event.name,
                "type": "ENTRY_LOG",
                "timestamp": event.recognized_at,
                "confidence": event.similarity
            }
            attendance_records.append(record)
            logger.info(f"[Office Attendance Plugin] Recorded Entry for Employee: {event.name} ({event.person_id})")

    def get_router(self) -> Optional[APIRouter]:
        return router
