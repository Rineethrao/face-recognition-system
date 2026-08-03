import logging
from typing import List, Optional, Tuple

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

# Full pose set for webcam / upload enrollment
REQUIRED_POSE_BINS = [
    "FRONTAL",
    "SLIGHT_LEFT",
    "SLIGHT_RIGHT",
    "LEFT_PROFILE",
    "RIGHT_PROFILE",
    "UP",
    "DOWN",
]

# CCTV enrollment prefers practical, non-extreme poses
CCTV_REQUIRED_POSE_BINS = [
    "FRONTAL",
    "SLIGHT_LEFT",
    "SLIGHT_RIGHT",
]

POSE_GUIDANCE_MAP = {
    "FRONTAL": "Look straight toward the camera",
    "SLIGHT_LEFT": "Turn slightly left",
    "SLIGHT_RIGHT": "Turn slightly right",
    "LEFT_PROFILE": "Turn head further to the left",
    "RIGHT_PROFILE": "Turn head further to the right",
    "UP": "Tilt head slightly upward",
    "DOWN": "Tilt head slightly downward",
}


class PoseService:
    """Head pose estimation and diversity guidance for registration."""

    def cctv_required_poses(self) -> List[str]:
        return list(CCTV_REQUIRED_POSE_BINS)

    def calculate_pose_angles(self, landmarks: List[List[float]]) -> Tuple[float, float, str]:
        if len(landmarks) < 5:
            return 0.0, 0.0, "FRONTAL"

        pts = np.array(landmarks, dtype=np.float32)
        left_eye, right_eye, nose = pts[0], pts[1], pts[2]
        left_mouth, right_mouth = pts[3], pts[4]

        left_to_nose = float(np.linalg.norm(nose - left_eye))
        right_to_nose = float(np.linalg.norm(nose - right_eye))
        denom_yaw = left_to_nose + right_to_nose + 1e-6
        yaw = float((right_to_nose - left_to_nose) / denom_yaw)

        eye_mid = (left_eye + right_eye) / 2.0
        mouth_mid = (left_mouth + right_mouth) / 2.0
        dist_eye_mouth = float(np.linalg.norm(mouth_mid - eye_mid)) + 1e-6
        dist_eye_nose = float(np.linalg.norm(nose - eye_mid))
        pitch = float((dist_eye_nose / dist_eye_mouth) - 0.44)

        pose_bin = self.classify_pose(yaw, pitch)
        return yaw, pitch, pose_bin

    def classify_pose(self, yaw: float, pitch: float) -> str:
        left_lo, left_hi = settings.REGISTRATION_LEFT_YAW_RANGE
        right_lo, right_hi = settings.REGISTRATION_RIGHT_YAW_RANGE
        front_lo, front_hi = settings.REGISTRATION_FRONTAL_YAW_RANGE

        if yaw <= left_lo:
            return "LEFT_PROFILE"
        if yaw >= right_hi:
            return "RIGHT_PROFILE"
        if left_lo < yaw <= left_hi:
            return "SLIGHT_LEFT"
        if right_lo <= yaw < right_hi:
            return "SLIGHT_RIGHT"
        if pitch > 0.18:
            return "UP"
        if pitch < -0.18:
            return "DOWN"
        if front_lo <= yaw <= front_hi:
            return "FRONTAL"
        return "FRONTAL"

    def normalize_cctv_pose(self, pose_bin: str, yaw: float, pitch: float) -> str:
        """Map extreme profiles into slight left/right for CCTV enrollment."""
        if pose_bin in ("LEFT_PROFILE", "SLIGHT_LEFT"):
            return "SLIGHT_LEFT"
        if pose_bin in ("RIGHT_PROFILE", "SLIGHT_RIGHT"):
            return "SLIGHT_RIGHT"
        if pose_bin in ("UP", "DOWN"):
            # Treat mild pitch as frontal for CCTV diversity goals
            return "FRONTAL"
        return "FRONTAL" if pose_bin == "FRONTAL" else pose_bin

    def get_pose_guidance(
        self, collected_pose_bins: List[str], mode: str = "WEBCAM"
    ) -> Tuple[str, Optional[str]]:
        required = CCTV_REQUIRED_POSE_BINS if mode == "CCTV" else REQUIRED_POSE_BINS
        collected_set = set(collected_pose_bins)

        for required_pose in required:
            if required_pose not in collected_set:
                instruction = POSE_GUIDANCE_MAP.get(required_pose, "Adjust face angle")
                return instruction, required_pose

        return "Great. All key poses captured.", None

    def has_minimum_cctv_coverage(self, collected_pose_bins: List[str]) -> bool:
        collected = set(collected_pose_bins)
        # Prefer all 3 CCTV poses; accept if at least frontal + one side angle
        if "FRONTAL" not in collected:
            return False
        return ("SLIGHT_LEFT" in collected) or ("SLIGHT_RIGHT" in collected)


pose_service = PoseService()
