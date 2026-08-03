import numpy as np
import logging
from typing import List, Tuple, Optional
from app.core.utils import align_face
from app.core.recognizer import arcface_recognizer

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    Service for face alignment and 512-dimensional embedding extraction using ArcFace.
    """

    def generate_aligned_crop(self, frame: np.ndarray, landmarks: List[List[float]]) -> Optional[np.ndarray]:
        """Warps and crops face into standard 112x112 ArcFace aligned image."""
        if frame is None or frame.size == 0 or len(landmarks) < 5:
            return None
        landmarks_np = np.array(landmarks, dtype=np.float32)
        return align_face(frame, landmarks_np)

    def extract_embedding(self, aligned_crop: np.ndarray) -> Optional[np.ndarray]:
        """Extracts L2-normalized 512-D vector from 112x112 aligned face crop."""
        if aligned_crop is None or aligned_crop.shape[:2] != (112, 112):
            return None
        try:
            return arcface_recognizer.extract_embedding(aligned_crop)
        except Exception as e:
            logger.error(f"EmbeddingService extraction error: {e}")
            return None

embedding_service = EmbeddingService()
