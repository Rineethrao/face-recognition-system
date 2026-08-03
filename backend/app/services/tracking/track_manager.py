import time
import threading
import logging
from typing import Dict, List, Optional, Any

from app.services.quality.face_buffer import FaceBuffer

logger = logging.getLogger(__name__)

class TrackState:
    TRACKING = "TRACKING"
    RECOGNIZED = "RECOGNIZED"
    CANDIDATE = "CANDIDATE"
    LOST = "LOST"

class ManagedTrack:
    """Represents a single active camera-namespaced track."""
    def __init__(self, track_id: str, camera_id: str):
        self.track_id = track_id # e.g. "cam_01:42"
        self.camera_id = camera_id
        self.state = TrackState.TRACKING
        self.start_time = time.time()
        self.last_seen = time.time()
        self.buffer = FaceBuffer(track_id=track_id, camera_id=camera_id)
        
        self.recognition_info: Optional[Dict[str, Any]] = None
        self.candidate_id: Optional[str] = None

    def update_seen(self):
        self.last_seen = time.time()

class TrackManager:
    """
    Per-Camera Track State & Buffer Manager.
    Namespaces tracks per camera (camera_id:bytetrack_id) to isolate track histories.
    """
    def __init__(self, camera_id: str = "default"):
        self.camera_id = camera_id
        self.lock = threading.Lock()
        self.tracks: Dict[str, ManagedTrack] = {}

    def get_namespaced_id(self, local_bytetrack_id: int) -> str:
        return f"{self.camera_id}:{local_bytetrack_id}"

    def get_or_create_track(self, local_bytetrack_id: int) -> ManagedTrack:
        namespaced_id = self.get_namespaced_id(local_bytetrack_id)
        with self.lock:
            if namespaced_id not in self.tracks:
                self.tracks[namespaced_id] = ManagedTrack(track_id=namespaced_id, camera_id=self.camera_id)
            else:
                self.tracks[namespaced_id].update_seen()
            return self.tracks[namespaced_id]

    def update_track_frame(
        self,
        local_bytetrack_id: int,
        frame: Any,
        bbox: List[float],
        landmarks: List[List[float]]
    ) -> Optional[Dict[str, Any]]:
        """Updates track seen time and buffers face crop if it passes quality checks."""
        track = self.get_or_create_track(local_bytetrack_id)
        return track.buffer.add_frame(frame, bbox, landmarks)

    def mark_recognized(self, local_bytetrack_id: int, person_id: str, name: str, similarity: float):
        namespaced_id = self.get_namespaced_id(local_bytetrack_id)
        with self.lock:
            if namespaced_id in self.tracks:
                track = self.tracks[namespaced_id]
                track.state = TrackState.RECOGNIZED
                track.recognition_info = {
                    "person_id": person_id,
                    "name": name,
                    "similarity": similarity,
                    "timestamp": time.time()
                }

    def cleanup_stale_tracks(self, timeout_seconds: float = 30.0) -> List[ManagedTrack]:
        """Removes and returns tracks not seen within timeout_seconds."""
        now = time.time()
        stale: List[ManagedTrack] = []
        with self.lock:
            to_remove = [tid for tid, t in self.tracks.items() if (now - t.last_seen) > timeout_seconds]
            for tid in to_remove:
                stale.append(self.tracks.pop(tid))
        return stale
