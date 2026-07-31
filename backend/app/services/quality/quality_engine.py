import cv2
import numpy as np
from typing import List, Dict, Any
from app.config import settings
from app.core.utils import calculate_blur, align_face, evaluate_face_quality

class QualityEngine:
    """
    Quality Evaluation Engine for Face Crops.
    Checks face dimensions, sharpness/blur, brightness, and pose ratios (yaw/pitch)
    to calculate a unified quality score and determine validity.
    """
    def calculate_blur(self, image: np.ndarray) -> float:
        """Calculates image sharpness score using Laplacian variance."""
        return calculate_blur(image)

    def evaluate(
        self,
        image: np.ndarray,
        bbox: List[float],
        landmarks: List[List[float]]
    ) -> Dict[str, Any]:
        """
        Evaluates a face image (either full frame or aligned crop) and returns
        comprehensive quality metrics and alignment validation.
        """
        landmarks_np = np.array(landmarks, dtype=np.float32)
        
        # 1. Generate aligned crop (which automatically enhances the crop if enabled)
        aligned_crop = align_face(image, landmarks_np)

        # 2. Check dimensions and sizes
        x1, y1, x2, y2 = bbox
        w, h = x2 - x1, y2 - y1
        face_size = float(w)

        # 3. Evaluate basic quality checks (size, eye distance, pose symmetry, blur)
        is_good_quality, reason, blur_score = evaluate_face_quality(image, bbox, landmarks)

        # 4. Brightness check on the aligned crop
        if aligned_crop is not None and aligned_crop.size > 0:
            gray = cv2.cvtColor(aligned_crop, cv2.COLOR_BGR2GRAY)
            brightness = float(np.mean(gray))
        else:
            brightness = 0.0

        # 5. Pose Estimation (Yaw & Pitch)
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
            
            # Calibrate pitch ratio
            pose_pitch = float((dist_eye_nose / (dist_eye_mouth + 1e-6)) - 0.45)
        else:
            pose_pitch = 0.0

        # 6. Overall Quality Score formulation
        yaw_penalty = abs(pose_yaw)
        pitch_penalty = abs(pose_pitch)
        
        # Blur normalization: 0 to 100+ mapped to 0 to 1
        blur_factor = min(blur_score / 100.0, 1.0)

        # Brightness penalty if extreme
        brightness_penalty = 0.0
        if brightness < 40.0:
            brightness_penalty = (40.0 - brightness) / 40.0
        elif brightness > 220.0:
            brightness_penalty = (brightness - 220.0) / 35.0

        quality_score = 1.0 - (0.4 * yaw_penalty) - (0.2 * pitch_penalty) - (0.2 * brightness_penalty)
        quality_score = max(0.0, min(1.0, quality_score * (0.8 + 0.2 * blur_factor)))

        passed = is_good_quality
        if brightness < 30.0 or brightness > 240.0:
            passed = False

        return {
            "passed": passed,
            "aligned_crop": aligned_crop,
            "quality_score": float(round(quality_score, 4)),
            "blur_score": blur_score,
            "brightness": brightness,
            "sharpness": blur_score,
            "pose_yaw": pose_yaw,
            "pose_pitch": pose_pitch,
            "face_size": face_size
        }

quality_engine = QualityEngine()
