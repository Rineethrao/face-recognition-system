import os
import sys
import numpy as np
import logging

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.registration.registration_engine import registration_engine
from app.services.registration.capture_service import capture_service
from app.services.registration.gallery_service import gallery_service
from app.models.schemas import DetectedFace
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestFaceFirstRegistration")


def create_mock_face(track_id, bbox, landmarks, score=0.98):
    face = DetectedFace()
    face.bbox = bbox
    face.landmarks = landmarks
    face.score = score
    face.track_id = track_id
    return face


def run_tests():
    logger.info("Initializing Face-First Registration State Machine Tests...")

    # 1. Start session
    registration_engine.start_session("P_TEST_101", "John", "Doe")
    assert registration_engine.target_state == "WAITING_FOR_SELECTION"
    assert registration_engine.target_locked is False
    logger.info("TEST 1 PASSED: Start session sets WAITING_FOR_SELECTION.")

    # 2. Process frame without face lock — no capture
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    face_1 = create_mock_face(
        101, [100, 100, 200, 200],
        [[120, 140], [180, 140], [150, 160], [130, 180], [170, 180]],
    )
    face_2 = create_mock_face(
        102, [300, 100, 400, 200],
        [[320, 140], [380, 140], [350, 160], [330, 180], [370, 180]],
    )

    res = registration_engine.process_frame(frame, [face_1, face_2], method="CCTV")
    assert res["state"] == "WAITING_FOR_SELECTION"
    assert len(gallery_service.samples) == 0
    logger.info("TEST 2 PASSED: Process frame without face lock ignores capturing.")

    # Mock quality / embedding
    from app.services.registration.quality_service import quality_service
    from app.services.registration.embedding_service import embedding_service

    original_evaluate = quality_service.evaluate_quality
    original_align = embedding_service.generate_aligned_crop
    original_extract = embedding_service.extract_embedding

    quality_service.evaluate_quality = lambda *args, **kwargs: {
        "passed": True,
        "score": 0.95,
        "reasons": [],
        "checks": {
            "detected": True,
            "centered": True,
            "sharp": True,
            "lighting": True,
            "eyes_visible": True,
            "face_size": True,
        },
        "metrics": {},
    }

    embedding_service.generate_aligned_crop = lambda *args, **kwargs: np.zeros(
        (112, 112, 3), dtype=np.uint8
    )

    # Distinct embeddings for person A vs B
    emb_a = np.zeros(512, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = np.zeros(512, dtype=np.float32)
    emb_b[1] = 1.0

    call_count = {"n": 0}

    def mock_extract(crop):
        # Alternate? No — use face bbox X position heuristic via call order isn't reliable.
        # Instead: registration_engine.select_face already set centroid to emb_a.
        # For process_frame we need extract to return emb based on which face.
        # We'll patch by wrapping select then controlling return via side channel.
        return emb_a.copy()

    embedding_service.extract_embedding = mock_extract

    try:
        # 3. Select face (click) — locks via embedding reference
        sel = registration_engine.select_face(frame, face_1, camera_id="cam_test")
        assert sel["status"] == "success"
        assert registration_engine.target_locked is True
        assert registration_engine.target_state == "TARGET_LOCKED"
        assert registration_engine.temporary_target_centroid is not None
        logger.info("TEST 3 PASSED: Face click locks temporary reference embedding.")

        # Force capture interval elapsed
        registration_engine.last_capture_time = 0.0

        # 4. Process with matching identity — should capture
        res = registration_engine.process_frame(frame, [face_1, face_2], method="CCTV")
        assert registration_engine.target_state in ("TARGET_LOCKED", "CAPTURING", "TARGET_ACQUIRING", "READY_FOR_REVIEW")
        assert len(gallery_service.samples) >= 1
        logger.info("TEST 4 PASSED: Locked face auto-captures quality sample.")

        # 5. Duplicate filter
        before = len(gallery_service.samples)
        registration_engine.last_capture_time = 0.0
        res = registration_engine.process_frame(frame, [face_1, face_2], method="CCTV")
        assert len(gallery_service.samples) == before
        logger.info("TEST 5 PASSED: Duplicate embedding rejected.")

        # 6. Target lost when only mismatched identity present
        embedding_service.extract_embedding = lambda *args, **kwargs: emb_b.copy()
        res = registration_engine.process_frame(frame, [face_2], method="CCTV")
        assert res["state"] == "TARGET_LOST"
        assert res["target"]["visible"] is False
        logger.info("TEST 6 PASSED: Different person at previous location → TARGET_LOST (no switch).")

        # 7. Reacquire when matching identity returns
        embedding_service.extract_embedding = lambda *args, **kwargs: emb_a.copy()
        face_3 = create_mock_face(
            999, [110, 110, 210, 210],
            [[130, 150], [190, 150], [160, 170], [140, 190], [180, 190]],
        )
        res = registration_engine.process_frame(frame, [face_3], method="CCTV")
        assert registration_engine.target_state in ("TARGET_LOCKED", "CAPTURING", "READY_FOR_REVIEW")
        assert res["target"]["visible"] is True
        logger.info("TEST 7 PASSED: Matching identity reacquires target without Track ID.")

        # 8. Unlock
        registration_engine.unlock_target()
        assert registration_engine.target_state == "WAITING_FOR_SELECTION"
        assert registration_engine.target_locked is False
        logger.info("TEST 8 PASSED: Unlock returns to WAITING_FOR_SELECTION.")

    finally:
        quality_service.evaluate_quality = original_evaluate
        embedding_service.generate_aligned_crop = original_align
        embedding_service.extract_embedding = original_extract
        gallery_service.clear()
        capture_service.unlock_track()

    logger.info("All Face-First Registration tests passed successfully!")


if __name__ == "__main__":
    run_tests()
