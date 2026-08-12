import cv2
import numpy as np
from typing import Tuple, List, Optional
from app.config import settings

# ArcFace standard 112x112 5-landmark target template
ARC_FACE_REF_LANDMARKS = np.array([
    [38.2946, 51.6963],  # Left Eye
    [73.5318, 51.5014],  # Right Eye
    [56.0252, 71.7366],  # Nose Tip
    [41.5493, 92.3655],  # Left Mouth Corner
    [70.7299, 92.2041]   # Right Mouth Corner
], dtype=np.float32)

def l2_normalize(vec: np.ndarray, axis: int = -1, eps: float = 1e-10) -> np.ndarray:
    """Normalize embedding vector(s) to unit length (L2 norm = 1.0)."""
    norm = np.linalg.norm(vec, axis=axis, keepdims=True)
    norm = np.maximum(norm, eps)
    return vec / norm

def calculate_blur(image: np.ndarray, bbox: Optional[List[float]] = None) -> float:
    """Calculate image sharpness score using Laplacian variance."""
    if image is None or image.size == 0:
        return 0.0
    if bbox and len(bbox) == 4:
        h, w = image.shape[:2]
        x1, y1, x2, y2 = bbox
        crop = image[max(0, int(y1)):min(h, int(y2)), max(0, int(x1)):min(w, int(x2))]
        if crop.size > 0:
            image = crop
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def enhance_face_image(img: np.ndarray) -> np.ndarray:
    """
    Enhance visual quality of a face crop image.
    Applies bilateral denoising, CLAHE contrast/illumination normalization,
    and smart unsharp mask sharpening based on config settings.
    """
    if img is None or img.size == 0:
        return img

    enhanced = img.copy()

    # 1. Bilateral Denoising (noise reduction while keeping edges sharp)
    if getattr(settings, 'QUALITY_ENHANCE_DENOISE', True):
        enhanced = cv2.bilateralFilter(enhanced, d=5, sigmaColor=25, sigmaSpace=25)

    # 2. Contrast & Illumination Enhancement via CLAHE (LAB space)
    if getattr(settings, 'QUALITY_ENHANCE_CONTRAST', True):
        lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        enhanced = cv2.merge((cl, a, b))
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    # 3. Sharpness Enhancement via Unsharp Masking
    if getattr(settings, 'QUALITY_ENHANCE_SHARPNESS', True):
        gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.5)
        enhanced = cv2.addWeighted(enhanced, 1.4, gaussian, -0.4, 0)

    return enhanced

def align_face(image: np.ndarray, landmarks: np.ndarray, output_size: Tuple[int, int] = (112, 112)) -> np.ndarray:
    """
    Align face image using 5 facial landmarks via 2D Partial Affine Transformation.
    Returns standard 112x112 aligned face crop for ArcFace feature extractor.
    """
    landmarks = np.array(landmarks, dtype=np.float32)
    tfm, _ = cv2.estimateAffinePartial2D(landmarks, ARC_FACE_REF_LANDMARKS)
    if tfm is None:
        tfm = cv2.getAffineTransform(landmarks[:3], ARC_FACE_REF_LANDMARKS[:3])

    aligned = cv2.warpAffine(
        image,
        tfm,
        output_size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT
    )

    if getattr(settings, 'QUALITY_ENHANCE_ENABLED', True):
        aligned = enhance_face_image(aligned)

    return aligned

def validate_landmark_geometry(
    landmarks: List[List[float]],
    bbox: Optional[List[float]] = None
) -> Tuple[bool, float, str]:
    """
    Validates that 5-point landmarks form a plausible human face structure.
    Rejects SCRFD false positives on shelves/objects/background texture.

    Returns (is_valid, structure_score 0-1, reason).
    """
    if landmarks is None or len(landmarks) < 5:
        return False, 0.0, "Missing landmarks"

    lm = np.array(landmarks, dtype=np.float32)
    left_eye, right_eye, nose, left_mouth, right_mouth = lm[0], lm[1], lm[2], lm[3], lm[4]

    eye_dist = float(np.linalg.norm(right_eye - left_eye))
    if eye_dist < 1e-3:
        return False, 0.0, "Degenerate eye distance"

    # Eyes should be roughly horizontal (false positives often have extreme roll)
    eye_dy = abs(float(right_eye[1] - left_eye[1]))
    roll_ratio = eye_dy / eye_dist
    if roll_ratio > 0.45:
        return False, 0.0, f"Extreme landmark roll ({roll_ratio:.2f})"

    # Nose should sit between the eyes horizontally
    eye_min_x = min(float(left_eye[0]), float(right_eye[0]))
    eye_max_x = max(float(left_eye[0]), float(right_eye[0]))
    nose_x = float(nose[0])
    if not (eye_min_x - 0.15 * eye_dist <= nose_x <= eye_max_x + 0.15 * eye_dist):
        return False, 0.0, "Nose not between eyes"

    # Nose should be below the eye midline
    eye_mid_y = (float(left_eye[1]) + float(right_eye[1])) / 2.0
    if float(nose[1]) < eye_mid_y + 0.05 * eye_dist:
        return False, 0.0, "Nose above eyes"

    # Mouth midline should be below the nose
    mouth_mid = (left_mouth + right_mouth) / 2.0
    if float(mouth_mid[1]) < float(nose[1]) + 0.05 * eye_dist:
        return False, 0.0, "Mouth above nose"

    mouth_width = float(np.linalg.norm(right_mouth - left_mouth))
    if mouth_width < 0.35 * eye_dist or mouth_width > 2.2 * eye_dist:
        return False, 0.0, f"Implausible mouth width ({mouth_width:.1f} vs eyes {eye_dist:.1f})"

    # Vertical face proportions: eye→mouth distance should relate to IPD
    vert_span = float(mouth_mid[1] - eye_mid_y)
    if vert_span < 0.45 * eye_dist or vert_span > 2.8 * eye_dist:
        return False, 0.0, f"Implausible vertical face proportions ({vert_span:.1f})"

    # BBox aspect / landmark fit when available
    aspect_score = 1.0
    if bbox is not None and len(bbox) >= 4:
        x1, y1, x2, y2 = bbox
        w = max(1.0, float(x2 - x1))
        h = max(1.0, float(y2 - y1))
        aspect = w / h
        # Human face boxes are typically near-square; reject extreme strips
        if aspect < 0.55 or aspect > 1.55:
            return False, 0.0, f"Implausible face aspect ratio ({aspect:.2f})"
        # Landmark span should occupy a meaningful portion of the box
        if eye_dist < 0.18 * w or eye_dist > 0.95 * w:
            return False, 0.0, "Eye distance vs bbox width out of range"
        aspect_score = 1.0 - min(abs(aspect - 1.0), 0.5)

    roll_score = max(0.0, 1.0 - roll_ratio / 0.45)
    proportion_score = max(0.0, 1.0 - abs(vert_span / eye_dist - 1.2) / 1.5)
    structure_score = float(max(0.0, min(1.0, 0.4 * roll_score + 0.35 * proportion_score + 0.25 * aspect_score)))
    return True, structure_score, "Valid face geometry"


def evaluate_face_quality(
    image: np.ndarray,
    bbox: List[float],
    landmarks: List[List[float]]
) -> Tuple[bool, str, float]:
    """
    Evaluates quality of detected face based on size, pose alignment, blur,
    and landmark geometry (rejects non-face false positives).
    Returns (is_good_quality, status_reason, blur_score).
    """
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1

    # 1. Size Check
    if w < settings.MIN_FACE_SIZE or h < settings.MIN_FACE_SIZE:
        return False, f"Face size too small ({int(w)}x{int(h)}px < {settings.MIN_FACE_SIZE}px)", 0.0

    landmarks_np = np.array(landmarks)
    left_eye = landmarks_np[0]
    right_eye = landmarks_np[1]
    nose = landmarks_np[2]

    # 2. Landmark geometry (anti false-positive)
    geom_ok, _, geom_reason = validate_landmark_geometry(landmarks, bbox)
    if not geom_ok:
        return False, f"Non-face landmark geometry: {geom_reason}", 0.0

    # 3. Eye Distance Check
    eye_dist = np.linalg.norm(right_eye - left_eye)
    if eye_dist < settings.QUALITY_MIN_EYE_DISTANCE:
        return False, f"Low eye resolution ({eye_dist:.1f}px)", 0.0

    # 4. Pose / Yaw Symmetry Check
    left_to_nose = np.linalg.norm(nose - left_eye)
    right_to_nose = np.linalg.norm(nose - right_eye)
    symmetry_diff = abs(left_to_nose - right_to_nose) / (left_to_nose + right_to_nose + 1e-6)
    if symmetry_diff > settings.QUALITY_MAX_POSE_RATIO:
        return False, f"Extreme head yaw/turn (symmetry diff {symmetry_diff:.2f})", 0.0

    # 5. Blur Check on Aligned Face Crop
    aligned_crop = align_face(image, landmarks_np)
    blur_score = calculate_blur(aligned_crop)

    if blur_score < settings.QUALITY_BLUR_THRESHOLD:
        return False, f"Blurry image (score: {blur_score:.1f} < threshold: {settings.QUALITY_BLUR_THRESHOLD})", blur_score

    return True, "Good Quality Face", blur_score
