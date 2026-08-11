import logging
import numpy as np
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.visitors.models import VisitorSightingModel
from app.visitors.visitor_repository import visitor_repository

logger = logging.getLogger(__name__)

class SightingManager:
    """
    Sighting Manager Module.
    Manages active camera sighting sessions for visitors and persists entrance, exit, and margin audit data.
    """

    def record_sighting(
        self,
        db: Session,
        visitor_id: int,
        camera_id: str,
        track_id: str,
        best_sim: float,
        second_best_sim: float,
        margin: float,
        confidence: float,
        crop_img: Optional[np.ndarray] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> VisitorSightingModel:
        """Records or updates a continuous sighting session for a visitor on a camera."""
        return visitor_repository.create_or_update_sighting(
            db=db,
            visitor_id=visitor_id,
            camera_id=camera_id,
            track_id=str(track_id),
            best_sim=best_sim,
            second_best_sim=second_best_sim,
            margin=margin,
            confidence=confidence,
            crop_img=crop_img,
            metadata=metadata
        )

sighting_manager = SightingManager()
