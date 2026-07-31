import cv2
import numpy as np
from typing import List, Tuple
from app.config import settings

class PersonDetector:
    """
    Lightweight Person Object Detector using OpenCV HOG/MobileNet SSD.
    Detects full-body person bounding boxes in camera frames.
    """
    def __init__(self):
        # OpenCV Default HOG Person Detector
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect_persons(self, image: np.ndarray) -> List[Tuple[List[float], float]]:
        """
        Detects person objects in image frame.
        Returns list of (bbox [x1, y1, x2, y2], score).
        """
        if image is None or image.size == 0:
            return []

        # Resize image for fast detection
        h, w = image.shape[:2]
        scale = 1.0
        if max(h, w) > 640:
            scale = 640.0 / max(h, w)
            small_img = cv2.resize(image, (int(w * scale), int(h * scale)))
        else:
            small_img = image

        rects, weights = self.hog.detectMultiScale(
            small_img,
            hitThreshold=0.0,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.08,
            groupThreshold=2
        )

        results = []
        for (rx, ry, rw, rh), weight in zip(rects, weights):
            x1 = float(rx / scale)
            y1 = float(ry / scale)
            x2 = float((rx + rw) / scale)
            y2 = float((ry + rh) / scale)
            results.append(([x1, y1, x2, y2], float(weight)))


        return results

person_detector = PersonDetector()
