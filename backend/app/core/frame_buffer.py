"""
frame_buffer.py — Lock-Free Latest-Frame Buffer

Provides thread-safe, non-blocking frame exchange between threads.
The producer (camera capture) never waits on the consumer (AI pipeline / stream).
The consumer always gets the most recent frame available.

Architecture:
    CaptureThread  --(put)-->  LatestFrameBuffer  --(get)-->  DetectionThread
    DetectionThread --(put)--> AnnotatedFrameBuffer --(get)--> MJPEGStream
"""

import threading
import time
import numpy as np
from typing import Optional, Tuple


class LatestFrameBuffer:
    """
    Lock-free (low-contention) single-slot frame buffer.

    - put(): Always overwrites the stored frame. Never blocks. O(1).
    - get(): Returns a safe copy of the latest frame. O(1).
    - Consumers never starve producers; old frames are silently dropped.
    """

    def __init__(self):
        self._frame: Optional[np.ndarray] = None
        self._timestamp: float = 0.0
        self._lock = threading.Lock()
        self._event = threading.Event()  # Signals new frame available

    def put(self, frame: np.ndarray) -> None:
        """Store the latest frame. Overwrites any unread previous frame."""
        with self._lock:
            self._frame = frame
            self._timestamp = time.monotonic()
        self._event.set()

    def get(self, timeout: float = 0.1) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Get the latest frame as a safe copy.
        Returns (True, frame) if a frame is available, else (False, None).
        Blocks up to `timeout` seconds waiting for a new frame.
        """
        signaled = self._event.wait(timeout=timeout)
        if not signaled:
            return False, None

        with self._lock:
            if self._frame is None:
                return False, None
            frame_copy = self._frame.copy()
            ts = self._timestamp

        return True, frame_copy

    def peek(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Non-blocking check. Returns (True, copy) if frame available, else (False, None)."""
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def clear(self) -> None:
        """Reset the buffer."""
        with self._lock:
            self._frame = None
            self._timestamp = 0.0
        self._event.clear()

    @property
    def has_frame(self) -> bool:
        """True if at least one frame has been stored."""
        with self._lock:
            return self._frame is not None

    @property
    def age_seconds(self) -> float:
        """Time in seconds since the last frame was stored. Returns inf if empty."""
        with self._lock:
            if self._timestamp == 0.0:
                return float('inf')
            return time.monotonic() - self._timestamp

    @property
    def timestamp(self) -> float:
        """Return the monotonic timestamp of the latest frame."""
        with self._lock:
            return self._timestamp


class AnnotatedFrameBuffer:
    """
    Buffer for annotated (overlay-rendered) frames ready for MJPEG streaming.
    Same semantics as LatestFrameBuffer but also stores JPEG bytes for zero-copy streaming.
    """

    def __init__(self):
        self._frame: Optional[np.ndarray] = None
        self._jpeg: Optional[bytes] = None
        self._timestamp: float = 0.0
        self._lock = threading.Lock()
        self._event = threading.Event()

    def get_jpeg_with_timestamp(self) -> Tuple[Optional[bytes], float]:
        """Return the latest JPEG bytes and its Monotonic timestamp."""
        with self._lock:
            return self._jpeg, self._timestamp

    def put(self, frame: np.ndarray, jpeg_bytes: Optional[bytes] = None) -> None:
        """Store annotated frame and optionally pre-encoded JPEG bytes."""
        with self._lock:
            self._frame = frame
            self._jpeg = jpeg_bytes
            self._timestamp = time.monotonic()
        self._event.set()

    def get_jpeg(self, timeout: float = 0.05) -> Optional[bytes]:
        """
        Get the pre-encoded JPEG bytes for streaming.
        Returns None if no frame is available within timeout.
        """
        signaled = self._event.wait(timeout=timeout)
        if not signaled:
            return None

        with self._lock:
            return self._jpeg

    def get_frame(self, timeout: float = 0.05) -> Tuple[bool, Optional[np.ndarray]]:
        """Get the annotated frame as a safe copy."""
        signaled = self._event.wait(timeout=timeout)
        if not signaled:
            return False, None

        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def clear(self) -> None:
        with self._lock:
            self._frame = None
            self._jpeg = None
            self._timestamp = 0.0
        self._event.clear()

    @property
    def has_frame(self) -> bool:
        with self._lock:
            return self._frame is not None

    @property
    def age_seconds(self) -> float:
        with self._lock:
            if self._timestamp == 0.0:
                return float('inf')
            return time.monotonic() - self._timestamp
