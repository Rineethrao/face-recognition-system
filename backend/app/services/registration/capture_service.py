import logging
from typing import Optional, Any, List

logger = logging.getLogger(__name__)


class CaptureService:
    """
    Manages registration capture source locking.

    Face-first enrollment locks onto a temporary identity template
    (embedding reference), not a visible Track ID.
    """

    def __init__(self):
        self.locked_track_id: Optional[int] = None  # internal only; never shown in UI
        self.active_camera_id: Optional[str] = None
        self.target_locked: bool = False

    def lock_face(self, camera_id: Optional[str] = None, internal_track_id: Optional[int] = None):
        """Locks capture to the selected face identity on a camera."""
        self.target_locked = True
        self.locked_track_id = internal_track_id
        if camera_id:
            self.active_camera_id = camera_id
        logger.info(
            "REG_TARGET_LOCKED camera=%s internal_track=%s",
            camera_id,
            internal_track_id,
        )

    def lock_track(self, track_id: int, camera_id: Optional[str] = None):
        """Legacy compatibility wrapper — prefer lock_face()."""
        if track_id is not None and track_id >= 0:
            self.lock_face(camera_id=camera_id, internal_track_id=track_id)
        else:
            self.unlock_track()

    def unlock_track(self):
        """Clears target face lock."""
        self.locked_track_id = None
        self.active_camera_id = None
        self.target_locked = False
        logger.info("REG_TARGET_UNLOCKED")

    def filter_target_face(self, detected_faces: List[Any]) -> Optional[Any]:
        """
        Webcam / upload helper: if an internal track is locked, return that face;
        otherwise return the largest face.
        CCTV face-first association is handled in RegistrationEngine.
        """
        if not detected_faces:
            return None

        if self.locked_track_id is not None and self.locked_track_id >= 0:
            for face in detected_faces:
                if getattr(face, "track_id", None) == self.locked_track_id:
                    return face
            return None

        if len(detected_faces) == 1:
            return detected_faces[0]

        def get_face_area(f):
            bbox = getattr(f, "bbox", None)
            if bbox and len(bbox) == 4:
                return max(0.0, float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
            return 0.0

        sorted_faces = sorted(detected_faces, key=get_face_area, reverse=True)
        return sorted_faces[0] if sorted_faces else None


capture_service = CaptureService()
