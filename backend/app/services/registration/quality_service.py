import logging
from typing import Any, Dict, List

import cv2
import numpy as np

from app.config import settings
from app.core.utils import calculate_blur

logger = logging.getLogger(__name__)


class QualityService:
    """
    Per-metric face quality gates for registration.
    Keeps individual measurements available for debugging — no single magic score gate.
    """

    def evaluate_quality(
        self,
        frame: np.ndarray,
        bbox: List[float],
        landmarks: List[List[float]],
        method: str = "WEBCAM",
    ) -> Dict[str, Any]:
        empty_checks = {
            "detected": False,
            "centered": False,
            "sharp": False,
            "lighting": False,
            "eyes_visible": False,
            "face_size": False,
        }
        if frame is None or frame.size == 0 or not bbox or len(landmarks) < 5:
            return {
                "passed": False,
                "score": 0.0,
                "reasons": ["Invalid image data or missing landmarks."],
                "checks": empty_checks,
                "metrics": {},
            }

        img_h, img_w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        face_w, face_h = float(x2 - x1), float(y2 - y1)
        face_cx, face_cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

        # A. Detection present
        detected = True

        # B. Face size
        min_w = settings.REGISTRATION_MIN_FACE_WIDTH
        min_h = settings.REGISTRATION_MIN_FACE_HEIGHT
        face_size_ok = face_w >= min_w and face_h >= min_h

        # C. Centered / in-frame
        if method == "CCTV":
            is_centered = x1 >= 0 and y1 >= 0 and x2 <= img_w and y2 <= img_h
        else:
            margin_x = img_w * 0.05
            margin_y = img_h * 0.05
            is_centered = (margin_x <= face_cx <= img_w - margin_x) and (
                margin_y <= face_cy <= img_h - margin_y
            )

        # D. Landmarks / eyes
        landmarks_np = np.array(landmarks, dtype=np.float32)
        left_eye, right_eye = landmarks_np[0], landmarks_np[1]
        ipd = float(np.linalg.norm(right_eye - left_eye))
        eyes_visible = ipd >= settings.QUALITY_MIN_EYE_DISTANCE

        # E. Sharpness
        crop = frame[max(0, int(y1)) : min(img_h, int(y2)), max(0, int(x1)) : min(img_w, int(x2))]
        blur_score = float(calculate_blur(crop)) if crop.size > 0 else 0.0
        is_sharp = blur_score >= settings.REGISTRATION_MIN_SHARPNESS

        # F. Lighting / exposure
        if crop.size > 0:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
        else:
            brightness = 0.0
        is_good_lighting = (
            settings.REGISTRATION_MIN_BRIGHTNESS <= brightness <= settings.REGISTRATION_MAX_BRIGHTNESS
        )

        reasons = []
        if not face_size_ok:
            reasons.append("Face too small — move closer or choose a clearer face")
        if not is_centered:
            reasons.append("Keep the face fully inside the frame")
        if not eyes_visible:
            reasons.append("Ensure eyes are visible")
        if not is_sharp:
            reasons.append("Image blurry — hold still")
        if not is_good_lighting:
            reasons.append("Adjust lighting")

        passed = (
            detected
            and face_size_ok
            and is_centered
            and eyes_visible
            and is_sharp
            and is_good_lighting
        )

        sharpness_norm = min(blur_score / 100.0, 1.0)
        brightness_norm = 1.0 - abs(brightness - 128.0) / 128.0
        size_norm = min(ipd / 60.0, 1.0)
        quality_score = float(
            round(max(0.0, min(1.0, 0.4 * sharpness_norm + 0.3 * brightness_norm + 0.3 * size_norm)), 3)
        )

        return {
            "passed": passed,
            "score": quality_score,
            "blur_score": round(blur_score, 1),
            "brightness": round(brightness, 1),
            "ipd": round(ipd, 1),
            "reasons": reasons,
            "checks": {
                "detected": detected,
                "centered": is_centered,
                "sharp": is_sharp,
                "lighting": is_good_lighting,
                "eyes_visible": eyes_visible,
                "face_size": face_size_ok,
            },
            "metrics": {
                "detection_confidence": 1.0,
                "face_width": round(face_w, 1),
                "face_height": round(face_h, 1),
                "sharpness": round(blur_score, 1),
                "brightness": round(brightness, 1),
                "ipd": round(ipd, 1),
            },
        }


quality_service = QualityService()
