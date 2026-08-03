import time
import numpy as np
from typing import List, Dict, Any, Optional

from app.services.quality.quality_engine import quality_engine
from app.services.quality.duplicate_engine import duplicate_engine
from app.services.quality.pose_diversity import pose_diversity_engine
from app.core.recognizer import arcface_recognizer

class FaceBuffer:
    """
    Temporal Face Buffer associated with a single track (camera_id + track_id).
    Buffers face crops, evaluates 6-factor quality, deduplicates embeddings,
    and maintains best quality pose diversity.
    """
    def __init__(self, track_id: str, camera_id: str, max_capacity: int = 30, expiry_seconds: float = 10.0):
        self.track_id = track_id
        self.camera_id = camera_id
        self.max_capacity = max_capacity
        self.expiry_seconds = expiry_seconds

        self.start_time = time.time()
        self.last_updated = time.time()
        self.captures: List[Dict[str, Any]] = []

    def is_expired(self) -> bool:
        return (time.time() - self.last_updated) > self.expiry_seconds

    def add_frame(
        self,
        frame: np.ndarray,
        bbox: List[float],
        landmarks: List[List[float]]
    ) -> Optional[Dict[str, Any]]:
        """
        Processes a live frame for this track:
        1. Evaluates quality (blur, size, pose, brightness)
        2. Extracts 512D ArcFace embedding
        3. Checks for near-duplicates in current buffer
        4. Classifies pose bin
        5. Appends capture if valid
        """
        self.last_updated = time.time()

        if len(self.captures) >= self.max_capacity:
            return None

        eval_res = quality_engine.evaluate(frame, bbox, landmarks)
        if not eval_res["passed"]:
            return None

        aligned_crop = eval_res["aligned_crop"]
        embedding = arcface_recognizer.extract_embedding(aligned_crop)

        # Duplicate check against existing buffered embeddings
        existing_embs = [c["embedding"] for c in self.captures if "embedding" in c]
        is_dup, max_sim = duplicate_engine.is_duplicate(embedding, existing_embs)
        if is_dup:
            return None

        pose_bin = pose_diversity_engine.classify_pose(eval_res["pose_yaw"], eval_res["pose_pitch"])

        capture = {
            "track_id": self.track_id,
            "camera_id": self.camera_id,
            "aligned_crop": aligned_crop,
            "embedding": embedding,
            "quality_score": eval_res["quality_score"],
            "blur_score": eval_res["blur_score"],
            "brightness": eval_res["brightness"],
            "sharpness": eval_res["sharpness"],
            "pose_yaw": eval_res["pose_yaw"],
            "pose_pitch": eval_res["pose_pitch"],
            "pose_bin": pose_bin,
            "face_size": eval_res["face_size"],
            "timestamp": self.last_updated
        }

        self.captures.append(capture)
        return capture

    def get_best_capture(self) -> Optional[Dict[str, Any]]:
        """Returns single highest quality capture in buffer."""
        if not self.captures:
            return None
        return max(self.captures, key=lambda c: c.get("quality_score", 0.0))

    def get_diverse_best_captures(self, max_output: int = 6) -> List[Dict[str, Any]]:
        """Returns top quality diverse pose captures."""
        return pose_diversity_engine.filter_diverse_captures(self.captures, max_output=max_output)
