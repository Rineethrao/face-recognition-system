import cv2
import numpy as np
from typing import List, Dict, Any
from app.config import settings
from app.core.utils import calculate_blur, align_face, evaluate_face_quality, validate_landmark_geometry


class QualityEngine:
    """
    Quality Evaluation Engine for Face Crops.
    Checks face dimensions, sharpness/blur, brightness, pose ratios (yaw/pitch),
    and landmark geometry to calculate a unified quality score and reject non-faces.
    """
    def calculate_blur(self, image: np.ndarray) -> float:
        """Calculates image sharpness score using Laplacian variance."""
        return calculate_blur(image)

    def evaluate(
        self,
        image: np.ndarray,
        bbox: List[float],
        landmarks: List[List[float]],
        det_score: float = 1.0
    ) -> Dict[str, Any]:
        """
        Evaluates a face image (either full frame or aligned crop) and returns
        comprehensive quality metrics and alignment validation.
        """
        landmarks_np = np.array(landmarks, dtype=np.float32)

        # 1. Landmark geometry early reject (shelves / background FPs)
        geom_ok, structure_score, geom_reason = validate_landmark_geometry(landmarks, bbox)

        # 2. Dimensions first (needed for raw crop sharpness)
        x1, y1, x2, y2 = bbox
        w, h = float(x2 - x1), float(y2 - y1)
        face_size = float(w)

        # 3. Generate aligned crop (which automatically enhances the crop if enabled)
        aligned_crop = align_face(image, landmarks_np) if landmarks_np.size > 0 else None

        # Raw (unenhanced) sharpness on bbox crop — enhancement inflates Laplacian and
        # lets blurry faces look "sharp" enough to enroll.
        ih, iw = image.shape[:2]
        cx1 = max(0, int(x1)); cy1 = max(0, int(y1))
        cx2 = min(iw, int(x2)); cy2 = min(ih, int(y2))
        if cx2 > cx1 and cy2 > cy1:
            raw_crop = image[cy1:cy2, cx1:cx2]
            raw_blur_score = float(calculate_blur(raw_crop))
        else:
            raw_blur_score = 0.0

        # Inter-pupillary distance (eye resolution proxy)
        eye_distance = 0.0
        if len(landmarks_np) >= 2:
            eye_distance = float(np.linalg.norm(landmarks_np[1] - landmarks_np[0]))

        # 4. Evaluate basic quality checks (size, eye distance, pose symmetry, blur, geometry)
        is_good_quality, reason, enhanced_blur = evaluate_face_quality(image, bbox, landmarks)
        if not geom_ok:
            is_good_quality = False
            reason = f"Non-face landmark geometry: {geom_reason}"

        # Prefer raw sharpness for gating decisions when available
        gate_blur = raw_blur_score if raw_blur_score > 0 else float(enhanced_blur)

        # 5. Brightness check on the aligned crop
        if aligned_crop is not None and aligned_crop.size > 0:
            gray = cv2.cvtColor(aligned_crop, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
        else:
            brightness = 0.0

        # 6. Pose Estimation (Yaw & Pitch)
        if len(landmarks_np) >= 3:
            left_eye = landmarks_np[0]
            right_eye = landmarks_np[1]
            nose = landmarks_np[2]

            left_to_nose = np.linalg.norm(nose - left_eye)
            right_to_nose = np.linalg.norm(nose - right_eye)
            pose_yaw = float((left_to_nose - right_to_nose) / (left_to_nose + right_to_nose + 1e-6))
        else:
            pose_yaw = 0.0

        if len(landmarks_np) >= 5:
            left_eye = landmarks_np[0]
            right_eye = landmarks_np[1]
            nose = landmarks_np[2]
            left_mouth = landmarks_np[3]
            right_mouth = landmarks_np[4]

            eye_mid = (left_eye + right_eye) / 2.0
            mouth_mid = (left_mouth + right_mouth) / 2.0
            dist_eye_mouth = np.linalg.norm(mouth_mid - eye_mid)
            dist_eye_nose = np.linalg.norm(nose - eye_mid)

            pose_pitch = float((dist_eye_nose / (dist_eye_mouth + 1e-6)) - 0.45)
        else:
            pose_pitch = 0.0

        # 7. Overall Quality Score — must reflect face-ness, not only frontal pose
        yaw_penalty = abs(pose_yaw)
        pitch_penalty = abs(pose_pitch)

        # Use RAW sharpness so blurry CCTV faces cannot score as "best quality"
        blur_factor = min(max(gate_blur, 0.0) / 100.0, 1.0)
        max_blur = float(getattr(settings, 'VISITOR_MAX_BLUR_SCORE', 800.0))
        if gate_blur > max_blur:
            blur_factor *= max(0.15, max_blur / (gate_blur + 1e-6))

        brightness_penalty = 0.0
        if brightness < 40.0:
            brightness_penalty = (40.0 - brightness) / 40.0
        elif brightness > 220.0:
            brightness_penalty = (brightness - 220.0) / 35.0

        det_factor = float(max(0.0, min(1.0, det_score)))
        size_factor = min(face_size / 100.0, 1.0)
        eye_factor = min(eye_distance / 30.0, 1.0)

        pose_component = max(0.0, 1.0 - (0.55 * yaw_penalty) - (0.35 * pitch_penalty))
        quality_score = (
            0.25 * structure_score +
            0.18 * det_factor +
            0.18 * pose_component +
            0.18 * blur_factor +
            0.12 * size_factor +
            0.05 * eye_factor +
            0.04 * max(0.0, 1.0 - brightness_penalty)
        )
        quality_score = float(max(0.0, min(1.0, quality_score)))

        # Hard fail non-faces and extreme exposure
        passed = bool(is_good_quality and geom_ok)
        if brightness < 30.0 or brightness > 240.0:
            passed = False
        if det_score < float(getattr(settings, 'VISITOR_MIN_DET_SCORE', 0.45)):
            if det_score < 0.35:
                passed = False
                reason = f"Detection confidence too low ({det_score:.2f})"

        if not passed:
            quality_score = min(quality_score, 0.35)

        return {
            "passed": passed,
            "aligned_crop": aligned_crop,
            "quality_score": float(round(quality_score, 4)),
            "blur_score": float(gate_blur),
            "raw_blur_score": float(raw_blur_score),
            "enhanced_blur_score": float(enhanced_blur),
            "brightness": brightness,
            "sharpness": float(gate_blur),
            "pose_yaw": pose_yaw,
            "pose_pitch": pose_pitch,
            "face_size": face_size,
            "eye_distance": float(eye_distance),
            "structure_score": float(round(structure_score, 4)),
            "det_score": float(det_score),
            "reason": reason,
        }


quality_engine = QualityEngine()
