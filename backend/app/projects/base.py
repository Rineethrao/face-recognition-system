from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import numpy as np
from fastapi import APIRouter
from app.models.schemas import RecognitionEvent

class BaseProjectPlugin(ABC):
    """
    Abstract Base Class for domain-specific project plugins
    (e.g. Office Attendance, Temple Security, Retail Analytics).
    """
    def __init__(self, project_name: str, config: Dict[str, Any]):
        self.project_name = project_name
        self.config = config

    @abstractmethod
    def on_person_detected(self, frame: np.ndarray, track_id: int, bbox: List[float]):
        """Callback hook triggered when a person object is detected."""
        pass

    @abstractmethod
    def on_face_recognized(self, event: RecognitionEvent):
        """Callback hook triggered when a registered face is recognized."""
        pass

    def get_router(self) -> Optional[APIRouter]:
        """Returns optional project-specific APIRouter to register domain REST APIs."""
        return None
