import cv2
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from app.config import settings
from app.services.quality.quality_engine import quality_engine


@dataclass
class FaceQualityResult:
    quality_score: float                # 0.0 to 1.0 (or 0-100)
    quality_tier: str                   # 'POOR', 'MATCHING', 'ENROLLMENT', 'PRIMARY_AVATAR'
    usable_for_matching: bool           # Can search registered/visitor gallery
    usable_for_new_identity: bool      # Meets enrollment quality + pose/size bounds for new visitor creation
    usable_for_gallery: bool            # Can be added to multi-sample visitor gallery
    usable_for_primary_avatar: bool     # Can become the primary avatar of a visitor
    face_width: float
    face_height: float
    blur_score: float
    brightness: float
    pose_yaw: float
    pose_pitch: float
    aligned_crop: Optional[np.ndarray] = None
    passed_basic_quality: bool = True


class VisitorFaceQualityEvaluator:
    """
    Multi-Tier Quality Evaluator for Visitor Detection, Re-Identification & Admission Control.
    Categorizes face crops into 4 configuration-driven quality tiers:
    - POOR: tracking only, do not save, cannot search, cannot create Visitor.
    - MATCHING: may search registered/visitor galleries, cannot create new Visitor.
    - ENROLLMENT: may support new Visitor creation, may be stored in gallery.
    - PRIMARY_AVATAR: strictest quality, candidate for primary profile picture.
    """

    def evaluate_quality(
        self,
        frame: np.ndarray,
        bbox: List[float],
        landmarks: List[List[float]],
        det_score: float = 0.90
    ) -> FaceQualityResult:
        """Evaluates face crop and returns structured FaceQualityResult."""
        eval_res = quality_engine.evaluate(frame, bbox, landmarks)

        q_score = float(eval_res.get("quality_score", 0.0))
        blur_score = float(eval_res.get("blur_score", 0.0))
        brightness = float(eval_res.get("brightness", 0.0))
        yaw = float(eval_res.get("pose_yaw", 0.0))
        pitch = float(eval_res.get("pose_pitch", 0.0))
        crop = eval_res.get("aligned_crop")
        passed = bool(eval_res.get("passed", True))

        x1, y1, x2, y2 = bbox
        w = max(0.0, float(x2 - x1))
        h = max(0.0, float(y2 - y1))

        # Configurable thresholds
        min_width = getattr(settings, 'VISITOR_MIN_FACE_WIDTH', 20)
        min_blur = getattr(settings, 'VISITOR_MIN_BLUR_SCORE', 10.0)
        max_yaw = getattr(settings, 'VISITOR_MAX_ABS_YAW', 0.38)
        max_pitch = getattr(settings, 'VISITOR_MAX_ABS_PITCH', 0.35)

        q_poor_thresh = getattr(settings, 'VISITOR_QUALITY_POOR_THRESH', 0.30)
        q_matching_thresh = getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.38)
        q_enrollment_thresh = getattr(settings, 'VISITOR_QUALITY_ENROLLMENT_THRESH', 0.42)
        q_avatar_thresh = getattr(settings, 'VISITOR_QUALITY_AVATAR_THRESH', 0.60)

        # Dimension and pose checks for new identity creation
        size_ok = (w >= min_width and h >= min_width)
        pose_ok = (abs(yaw) <= max_yaw and abs(pitch) <= max_pitch)
        blur_ok = (blur_score >= min_blur)

        usable_for_matching = passed and q_score >= q_matching_thresh and size_ok
        usable_for_new = (
            passed and
            q_score >= q_enrollment_thresh and
            size_ok and
            crop is not None
        )
        usable_for_gallery = (passed and q_score >= q_enrollment_thresh and size_ok)
        usable_for_primary = (passed and q_score >= q_avatar_thresh and size_ok and pose_ok and blur_ok)


        if q_score >= q_avatar_thresh and size_ok and pose_ok:
            tier = "PRIMARY_AVATAR"
        elif q_score >= q_enrollment_thresh and size_ok:
            tier = "ENROLLMENT"
        elif q_score >= q_matching_thresh and size_ok:
            tier = "MATCHING"
        else:
            tier = "POOR"

        return FaceQualityResult(
            quality_score=q_score,
            quality_tier=tier,
            usable_for_matching=usable_for_matching,
            usable_for_new_identity=usable_for_new,
            usable_for_gallery=usable_for_gallery,
            usable_for_primary_avatar=usable_for_primary,
            face_width=w,
            face_height=h,
            blur_score=blur_score,
            brightness=brightness,
            pose_yaw=yaw,
            pose_pitch=pitch,
            aligned_crop=crop,
            passed_basic_quality=passed
        )

    def is_usable_observation(self, quality_score: float) -> bool:
        """Determines if face sample quality meets minimum usable observation threshold."""
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.50)

    def meets_confirmation_gate(self, quality_score: float) -> bool:
        """Threshold for confirming existing visitor identity."""
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.50)

    def meets_sample_enrollment_gate(self, quality_score: float) -> bool:
        """Threshold for storing extra embedding in multi-sample visitor gallery."""
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_ENROLLMENT_THRESH', 0.65)

    def meets_primary_snapshot_gate(self, quality_score: float) -> bool:
        """Threshold for updating visitor primary profile snapshot."""
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_AVATAR_THRESH', 0.75)


visitor_quality_evaluator = VisitorFaceQualityEvaluator()
