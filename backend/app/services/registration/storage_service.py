import os
import cv2
import numpy as np
import logging
from pathlib import Path
from typing import Tuple, Optional
from app.config import settings

logger = logging.getLogger(__name__)

class StorageService:
    """
    Storage Service for writing raw face images, aligned crops, and thumbnails to disk.
    """

    def ensure_person_directory(self, person_id: str) -> Path:
        """Ensures storage directory for a specific person exists."""
        person_dir = settings.FACES_DIR / person_id
        os.makedirs(person_dir, exist_ok=True)
        return person_dir

    def save_face_image(self, person_id: str, image_filename: str, image_mat: np.ndarray) -> str:
        """Saves image matrix to disk and returns absolute path string."""
        person_dir = self.ensure_person_directory(person_id)
        file_path = person_dir / image_filename
        cv2.imwrite(str(file_path), image_mat)
        return str(file_path)

storage_service = StorageService()
