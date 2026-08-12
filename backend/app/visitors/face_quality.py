import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from app.config import settings
from app.services.quality.quality_engine import quality_engine


@dataclass
class FaceQualityResult:
    quality_score: float                # 0.0 to 1.0
    quality_tier: str                   # 'POOR', 'MATCHING', 'ENROLLMENT', 'PRIMARY_AVATAR'
    usable_for_matching: bool           # Can search registered/visitor gallery
    usable_for_new_identity: bool      # Best-quality enrollment frame for new visitor creation
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
    structure_score: float = 0.0
    det_score: float = 1.0
    eye_distance: float = 0.0


class VisitorFaceQualityEvaluator:
    """
    Multi-Tier Quality Evaluator for Visitor Detection, Re-Identification & Admission Control.
    - POOR: tracking only
    - MATCHING: gallery search only (never creates visitor)
    - ENROLLMENT: counts toward the 5–6 best-quality frames required to create a visitor
    - PRIMARY_AVATAR: strictest — preferred for profile picture
    """

    def evaluate_quality(
        self,
        frame: np.ndarray,
        bbox: List[float],
        landmarks: List[List[float]],
        det_score: float = 0.90
    ) -> FaceQualityResult:
        """Evaluates face crop and returns structured FaceQualityResult."""
        eval_res = quality_engine.evaluate(frame, bbox, landmarks, det_score=det_score)

        q_score = float(eval_res.get("quality_score", 0.0))
        blur_score = float(eval_res.get("blur_score", 0.0))
        brightness = float(eval_res.get("brightness", 0.0))
        yaw = float(eval_res.get("pose_yaw", 0.0))
        pitch = float(eval_res.get("pose_pitch", 0.0))
        crop = eval_res.get("aligned_crop")
        passed = bool(eval_res.get("passed", True))
        structure_score = float(eval_res.get("structure_score", 0.0))
        det = float(eval_res.get("det_score", det_score))
        eye_distance = float(eval_res.get("eye_distance", 0.0))

        x1, y1, x2, y2 = bbox
        w = max(0.0, float(x2 - x1))
        h = max(0.0, float(y2 - y1))

        min_width = getattr(settings, 'VISITOR_MIN_FACE_WIDTH', 28)
        min_height = getattr(settings, 'VISITOR_MIN_FACE_HEIGHT', 28)
        # Enrollment needs a larger, clearer face than matching
        enroll_min_w = getattr(settings, 'VISITOR_ENROLLMENT_MIN_FACE_WIDTH', 50)
        enroll_min_h = getattr(settings, 'VISITOR_ENROLLMENT_MIN_FACE_HEIGHT', 50)
        min_blur = getattr(settings, 'VISITOR_MIN_BLUR_SCORE', 40.0)
        enroll_min_blur = getattr(settings, 'VISITOR_ENROLLMENT_MIN_BLUR_SCORE', 55.0)
        max_blur = getattr(settings, 'VISITOR_MAX_BLUR_SCORE', 800.0)
        max_yaw = getattr(settings, 'VISITOR_MAX_ABS_YAW', 0.18)
        max_pitch = getattr(settings, 'VISITOR_MAX_ABS_PITCH', 0.15)
        min_det = getattr(settings, 'VISITOR_MIN_DET_SCORE', 0.50)
        enroll_min_det = getattr(settings, 'VISITOR_ENROLLMENT_MIN_DET_SCORE', 0.60)
        min_structure = getattr(settings, 'VISITOR_MIN_STRUCTURE_SCORE', 0.45)
        enroll_min_structure = getattr(settings, 'VISITOR_ENROLLMENT_MIN_STRUCTURE_SCORE', 0.55)
        min_eye = getattr(settings, 'VISITOR_ENROLLMENT_MIN_EYE_DISTANCE', 18.0)

        q_matching_thresh = getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.42)
        q_enrollment_thresh = getattr(settings, 'VISITOR_QUALITY_ENROLLMENT_THRESH', 0.62)
        q_avatar_thresh = getattr(settings, 'VISITOR_QUALITY_AVATAR_THRESH', 0.70)

        size_ok = (w >= min_width and h >= min_height)
        enroll_size_ok = (w >= enroll_min_w and h >= enroll_min_h)
        pose_ok = (abs(yaw) <= max_yaw and abs(pitch) <= max_pitch)
        blur_ok = (blur_score >= min_blur and blur_score <= max_blur)
        enroll_blur_ok = (blur_score >= enroll_min_blur and blur_score <= max_blur)
        det_ok = (det >= min_det)
        enroll_det_ok = (det >= enroll_min_det)
        structure_ok = (structure_score >= min_structure)
        enroll_structure_ok = (structure_score >= enroll_min_structure)
        eye_ok = (eye_distance >= min_eye)

        usable_for_matching = (
            passed and
            q_score >= q_matching_thresh and
            size_ok and
            structure_ok and
            det_ok and
            crop is not None
        )

        # BEST-QUALITY enrollment frame — only these count toward visitor creation
        usable_for_new = (
            passed and
            q_score >= q_enrollment_thresh and
            enroll_size_ok and
            pose_ok and
            enroll_blur_ok and
            enroll_structure_ok and
            enroll_det_ok and
            eye_ok and
            crop is not None
        )
        usable_for_gallery = usable_for_new
        usable_for_primary = (
            usable_for_new and
            q_score >= q_avatar_thresh and
            pose_ok and
            enroll_blur_ok
        )

        if usable_for_primary:
            tier = "PRIMARY_AVATAR"
        elif usable_for_new:
            tier = "ENROLLMENT"
        elif usable_for_matching:
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
            passed_basic_quality=passed,
            structure_score=structure_score,
            det_score=det,
            eye_distance=eye_distance,
        )

    def is_usable_observation(self, quality_score: float) -> bool:
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.42)

    def meets_confirmation_gate(self, quality_score: float) -> bool:
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.42)

    def meets_sample_enrollment_gate(self, quality_score: float) -> bool:
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_ENROLLMENT_THRESH', 0.62)

    def meets_primary_snapshot_gate(self, quality_score: float) -> bool:
        return quality_score >= getattr(settings, 'VISITOR_QUALITY_AVATAR_THRESH', 0.70)


visitor_quality_evaluator = VisitorFaceQualityEvaluator()
