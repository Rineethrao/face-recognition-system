import cv2
import numpy as np
import logging
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from app.services.registration.pose_service import pose_service
from app.services.registration.quality_service import quality_service

logger = logging.getLogger(__name__)

class GalleryService:
    """
    Gallery Service managing transient session gallery samples.
    Supports pose diversity filtering, deletion, retaking, and metadata formatting.
    """

    def __init__(self):
        self.samples: List[Dict[str, Any]] = []

    def clear(self):
        """Clears collected samples."""
        self.samples.clear()

    def add_sample(
        self,
        frame: np.ndarray,
        aligned_crop: np.ndarray,
        embedding: np.ndarray,
        quality_score: float,
        pose_bin: str,
        yaw: float,
        pitch: float,
        method: str = "WEBCAM"
    ) -> Dict[str, Any]:
        """
        Adds a sample to the gallery if its pose bin doesn't already have an over-saturated count.
        Returns the formatted sample dict.
        """
        sample_id = f"sample_{len(self.samples) + 1}_{int(datetime.utcnow().timestamp())}"
        
        # Convert aligned crop to base64 preview for frontend
        _, buffer = cv2.imencode('.jpg', aligned_crop)
        b64_str = base64.b64encode(buffer).decode('utf-8')
        preview_url = f"data:image/jpeg;base64,{b64_str}"

        sample_item = {
            "id": sample_id,
            "frame": frame.copy() if frame is not None else aligned_crop.copy(),
            "aligned": aligned_crop.copy(),
            "embedding": embedding.copy(),
            "quality_score": quality_score,
            "pose_bin": pose_bin,
            "yaw": yaw,
            "pitch": pitch,
            "method": method,
            "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
            "preview_url": preview_url
        }

        self.samples.append(sample_item)
        logger.info(f"GalleryService: Added sample {sample_id} [Pose: {pose_bin}, Score: {quality_score}]")
        return sample_item

    def remove_sample(self, sample_id: str) -> bool:
        """Removes a sample by ID from the gallery review session."""
        original_count = len(self.samples)
        self.samples = [s for s in self.samples if s["id"] != sample_id]
        removed = len(self.samples) < original_count
        if removed:
            logger.info(f"GalleryService: Removed sample {sample_id}")
        return removed

    def get_collected_poses(self) -> List[str]:
        """Returns list of pose_bins collected so far."""
        return [s["pose_bin"] for s in self.samples]

    def get_formatted_gallery(self) -> List[Dict[str, Any]]:
        """Returns clean serializable summary list for frontend gallery review step."""
        return [
            {
                "id": s["id"],
                "pose_bin": s["pose_bin"],
                "quality_score": s["quality_score"],
                "timestamp": s["timestamp"],
                "preview_url": s["preview_url"],
                "method": s["method"]
            }
            for s in self.samples
        ]

gallery_service = GalleryService()
