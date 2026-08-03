import cv2
import numpy as np
from typing import List, Dict, Any, Optional

class PoseDiversityEngine:
    """
    Classifies face poses into distinct spatial and attribute bins:
    FRONTAL, LEFT_30, RIGHT_30, LEFT_60, RIGHT_60, UP, DOWN, GLASSES, SMILE.
    Ensures registered person galleries maintain rich multi-angle & attribute representation.
    """
    def detect_smile(self, landmarks: np.ndarray) -> bool:
        """Heuristic smile detection using mouth-to-eye width ratio."""
        if landmarks is None or len(landmarks) < 5:
            return False
        # landmarks indices: 0: left eye, 1: right eye, 2: nose, 3: left mouth, 4: right mouth
        eye_dist = np.linalg.norm(landmarks[1] - landmarks[0])
        mouth_dist = np.linalg.norm(landmarks[4] - landmarks[3])
        ratio = mouth_dist / (eye_dist + 1e-6)
        return ratio > 0.62

    def detect_glasses(self, aligned_crop: np.ndarray) -> bool:
        """Heuristic glasses frame detection using edge variance in the eye/bridge region of aligned crop."""
        if aligned_crop is None or aligned_crop.size == 0:
            return False
        # standard ArcFace aligned crop is 112x112. Crop region around the eyes/bridge.
        roi = aligned_crop[35:65, 25:87]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sob_var = np.var(sobel_x)
        # High edge variance indicates presence of frames/glasses
        return float(sob_var) > 800.0

    def classify_pose(
        self,
        yaw_ratio: float,
        pitch_ratio: float,
        aligned_crop: Optional[np.ndarray] = None,
        landmarks: Optional[np.ndarray] = None
    ) -> str:
        """Classifies face pose and attributes into distinct bins."""
        if aligned_crop is not None and self.detect_glasses(aligned_crop):
            return "GLASSES"
        
        if landmarks is not None and self.detect_smile(landmarks):
            return "SMILE"

        if yaw_ratio < -0.40:
            return "LEFT_60"
        elif yaw_ratio > 0.40:
            return "RIGHT_60"
        elif yaw_ratio < -0.15:
            return "LEFT_30"
        elif yaw_ratio > 0.15:
            return "RIGHT_30"
        elif pitch_ratio > 0.18:
            return "UP"
        elif pitch_ratio < -0.18:
            return "DOWN"
        else:
            return "FRONTAL"

    def filter_diverse_captures(self, captures: List[Dict[str, Any]], max_output: int = 6) -> List[Dict[str, Any]]:
        """
        Groups captures by pose bin and selects the highest quality capture per bin,
        producing a balanced multi-angle dataset.
        """
        bins: Dict[str, Dict[str, Any]] = {}

        for cap in captures:
            p_bin = cap.get("pose_bin", self.classify_pose(cap.get("pose_yaw", 0.0), cap.get("pose_pitch", 0.0)))
            cap["pose_bin"] = p_bin

            # If bin is empty or this capture has higher quality, store it
            if p_bin not in bins or cap.get("quality_score", 0.0) > bins[p_bin].get("quality_score", 0.0):
                bins[p_bin] = cap

        # Collect best capture from each bin
        diverse = list(bins.values())
        # Sort by quality score descending
        diverse.sort(key=lambda c: c.get("quality_score", 0.0), reverse=True)

        return diverse[:max_output]

pose_diversity_engine = PoseDiversityEngine()
