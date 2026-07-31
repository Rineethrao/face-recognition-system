import os
# Silence FFmpeg console logging pollution (harmless H.264 packet loss warnings)
os.environ["AV_LOG_LEVEL"] = "fatal"

# Optimized FFmpeg RTSP Capture Options for H.264 and H.265 (HEVC)
# NOTE: Do NOT enable FFmpeg's built-in reconnect flags here — they free the
# AVFormatContext under OpenCV's feet and cause SIGSEGV in av_read_frame.
# Reconnection is handled safely by CameraStreamManager._do_reconnect().
# rtsp_transport;tcp       — Use TCP instead of UDP to eliminate packet drops
# rw_timeout;5000000       — 5s socket I/O timeout (avoids infinite blocking reads)
# stimeout;5000000         — 5s RTSP socket timeout
# max_delay;500000         — Lower jitter buffer for live streams
# buffer_size;2097152      — 2MB socket buffer
# fflags;nobuffer          — Prefer low latency over deep buffering
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp"
    "|rw_timeout;5000000"
    "|stimeout;5000000"
    "|max_delay;500000"
    "|buffer_size;2097152"
    "|fflags;nobuffer"
    "|flags;low_delay"
)


import cv2
import time
import logging
import threading
import numpy as np
from typing import Tuple, Optional, Union

from app.core.frame_buffer import LatestFrameBuffer
from app.config import settings

logger = logging.getLogger(__name__)


class CameraStreamManager:
    """
    High-Performance, Thread-Safe OpenCV Camera Stream Manager.

    The capture thread writes frames into a LatestFrameBuffer (lock-free).
    AI pipeline threads and the MJPEG stream read from the buffer independently.
    This completely decouples camera capture from AI inference speed.

    Critical safety rule:
        ALL VideoCapture open / read / release operations are serialized via
        `_cap_lock`. Never release a capture while another thread may be inside
        `cap.read()` — that produces SIGSEGV in FFmpeg's av_read_frame.
    """

    def __init__(
        self,
        source: Union[str, int] = settings.DEFAULT_CAMERA_SOURCE,
        rotation: int = 0,
        camera_id: str = "default"
    ):
        self.source = self._parse_source(source)
        self.rotation: int = rotation
        self.camera_id = camera_id

        self.cap: Optional[cv2.VideoCapture] = None
        self._capture_thread: Optional[threading.Thread] = None
        self.running: bool = False
        self._lock = threading.Lock()          # lifecycle (start/stop)
        self._cap_lock = threading.RLock()     # VideoCapture open/read/release

        # Lock-free frame buffer — camera writes here, everyone else reads
        self.frame_buffer = LatestFrameBuffer()

        # Health tracking
        self._frame_count: int = 0
        self._error_count: int = 0
        self._last_frame_time: float = 0.0
        self._reconnect_attempts: int = 0
        self._max_reconnect_attempts: int = getattr(settings, 'MAX_RECONNECT_ATTEMPTS', 20)
        self._reconnect_in_progress = False
        self._force_reconnect = False

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Open the camera and start the capture thread."""
        with self._lock:
            if self.running:
                return True

            logger.info(f"[Camera:{self.camera_id}] Opening stream: {self.source}")
            with self._cap_lock:
                self.cap = self._open_capture(self.source)
                opened = self.cap is not None and self.cap.isOpened()

            if not opened:
                logger.error(f"[Camera:{self.camera_id}] Failed to open: {self.source}")
                with self._cap_lock:
                    self.cap = None
                return False

            self.running = True
            self._reconnect_attempts = 0
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                name=f"CaptureThread-{self.camera_id}",
                daemon=True
            )
            self._capture_thread.start()
            logger.info(f"[Camera:{self.camera_id}] Capture thread started.")
            return True

    def stop(self):
        """
        Stop the capture thread and release resources.

        Order is critical:
          1. Signal running=False so the loop exits after the current read.
          2. Join the capture thread (wait past FFmpeg I/O timeout).
          3. Only then release VideoCapture under `_cap_lock`.
        Never release while the capture thread may still call read().
        """
        with self._lock:
            self.running = False

        thread = self._capture_thread
        if thread and thread.is_alive():
            # FFmpeg rw_timeout is 5s; wait a bit longer so read() can return.
            thread.join(timeout=8.0)
            if thread.is_alive():
                logger.warning(
                    f"[Camera:{self.camera_id}] Capture thread still alive after join; "
                    "deferring VideoCapture.release() to avoid SIGSEGV."
                )
                # Do NOT release while the thread may still be inside av_read_frame.
                # The daemon thread will exit on its own once the blocking read returns
                # and sees running=False; _safe_release is called at loop exit.
                self._capture_thread = None
                self.frame_buffer.clear()
                logger.info(f"[Camera:{self.camera_id}] Stop requested (release deferred).")
                return

        self._safe_release()
        self._capture_thread = None
        self.frame_buffer.clear()
        logger.info(f"[Camera:{self.camera_id}] Stopped.")

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read the latest captured frame (safe copy). Non-blocking."""
        return self.frame_buffer.peek()

    def is_active(self) -> bool:
        """True if capture thread is running and frames are arriving."""
        if not self.running:
            return False
        return self.frame_buffer.has_frame and self.frame_buffer.age_seconds < 5.0

    def is_healthy(self) -> bool:
        """True if the last frame was received within the camera timeout window."""
        timeout = getattr(settings, 'CAMERA_TIMEOUT', 10)
        return self.running and self.frame_buffer.age_seconds < timeout

    def set_rotation(self, rotation: int):
        with self._lock:
            self.rotation = rotation

    def request_reconnect(self):
        """
        Ask the capture loop to reconnect without tearing down the thread.
        Safer than stop()/start() from the watchdog — never releases VideoCapture
        from another thread (that races with FFmpeg and causes SIGSEGV).
        """
        self._force_reconnect = True
        logger.info(f"[Camera:{self.camera_id}] Reconnect requested by watchdog.")

    def get_health(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "running": self.running,
            "is_active": self.is_active(),
            "frame_count": self._frame_count,
            "error_count": self._error_count,
            "last_frame_age_s": round(self.frame_buffer.age_seconds, 2),
            "reconnect_attempts": self._reconnect_attempts,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────────────────

    def _safe_read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Thread-safe VideoCapture.read(). Holds `_cap_lock` for the whole call."""
        with self._cap_lock:
            cap = self.cap
            if cap is None:
                return False, None
            try:
                if not cap.isOpened():
                    return False, None
                return cap.read()
            except Exception as e:
                logger.error(f"[Camera:{self.camera_id}] cap.read() exception: {e}")
                return False, None

    def _safe_release(self):
        """Thread-safe VideoCapture.release()."""
        with self._cap_lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception as e:
                    logger.debug(f"[Camera:{self.camera_id}] release() error: {e}")
                self.cap = None

    def _capture_loop(self):
        """
        Main capture loop. Runs in a dedicated daemon thread.
        Writes valid frames into frame_buffer. Never blocks on AI inference.
        """
        consecutive_failures = 0
        target_interval = 1.0 / max(1, getattr(settings, 'CAPTURE_FPS', 30))

        try:
            while self.running:
                loop_start = time.monotonic()

                if self._force_reconnect:
                    self._force_reconnect = False
                    self._do_reconnect()
                    consecutive_failures = 0
                    continue

                with self._cap_lock:
                    needs_open = self.cap is None or not self.cap.isOpened()

                if needs_open:
                    self._do_reconnect()
                    continue

                ret, frame = self._safe_read()

                if not self.running:
                    break

                if not ret or frame is None:
                    consecutive_failures += 1
                    self._error_count += 1

                    # Loop video files
                    is_file = (
                        isinstance(self.source, str)
                        and not self.source.startswith("rtsp")
                        and not str(self.source).isdigit()
                    )
                    if is_file:
                        with self._cap_lock:
                            if self.cap is not None:
                                try:
                                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                                except Exception:
                                    pass
                        consecutive_failures = 0
                        continue

                    if consecutive_failures >= 5:
                        logger.warning(
                            f"[Camera:{self.camera_id}] {consecutive_failures} consecutive "
                            "read failures. Reconnecting..."
                        )
                        self._do_reconnect()
                        consecutive_failures = 0
                    else:
                        time.sleep(0.05)
                    continue

                # ── Corrupt frame filter ──────────────────────────────────────
                # Gray macroblock artifacts (from H.264 packet loss) have very low
                # pixel std-dev. Reject frames that are near-uniform gray.
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if float(np.std(gray)) < 5.0:
                        consecutive_failures += 1
                        time.sleep(0.01)
                        continue
                except Exception:
                    consecutive_failures += 1
                    continue

                consecutive_failures = 0
                self._frame_count += 1
                self._last_frame_time = time.monotonic()

                processed = self._apply_rotation(frame)
                self.frame_buffer.put(processed)

                elapsed = time.monotonic() - loop_start
                sleep_time = target_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            # Always release on thread exit so stop() can safely defer release.
            self._safe_release()
            logger.info(f"[Camera:{self.camera_id}] Capture loop exited.")

    def _do_reconnect(self):
        """Reconnect with exponential backoff. Never gives up — cameras must stay alive."""
        if not self.running:
            return

        if self._reconnect_in_progress:
            time.sleep(0.5)
            return

        self._reconnect_in_progress = True
        try:
            self._reconnect_attempts += 1
            backoff = min(2.0 ** min(self._reconnect_attempts, 4), 10.0)  # Cap at 10s

            logger.info(
                f"[Camera:{self.camera_id}] Reconnect attempt "
                f"#{self._reconnect_attempts} in {backoff:.1f}s..."
            )
            time.sleep(backoff)

            if not self.running:
                return

            # Release + reopen under the same lock so no concurrent read can race.
            with self._cap_lock:
                if self.cap is not None:
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None

                if not self.running:
                    return

                self.cap = self._open_capture(self.source)
                ok = self.cap is not None and self.cap.isOpened()

            if ok:
                self._reconnect_attempts = 0
                logger.info(f"[Camera:{self.camera_id}] Reconnected successfully.")
            else:
                with self._cap_lock:
                    self.cap = None
                logger.warning(
                    f"[Camera:{self.camera_id}] Reconnect failed "
                    f"(attempt #{self._reconnect_attempts}). Will retry..."
                )
        finally:
            self._reconnect_in_progress = False

    def _open_capture(self, source) -> Optional[cv2.VideoCapture]:
        """Open a cv2.VideoCapture with RTSP TCP keepalive settings."""
        try:
            if isinstance(source, str) and source.startswith("rtsp"):
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
                # Single-frame internal buffer: always return the newest frame
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                # Soft open timeout hint (ignored by some backends, harmless)
                try:
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                except Exception:
                    pass
            else:
                cap = cv2.VideoCapture(source)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass

            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                return None
            return cap
        except Exception as e:
            logger.error(f"[Camera:{self.camera_id}] Exception opening capture: {e}")
            return None

    def _apply_rotation(self, frame: np.ndarray) -> np.ndarray:
        if self.rotation == 0:
            return frame
        if self.rotation == 90:
            rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            rotated = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            return frame

        # Letterbox vertical frames into 16:9 aspect ratio for clean browser display
        h, w = rotated.shape[:2]
        if h > w:
            target_w = int(h * (16 / 9))
            pad_total = max(0, target_w - w)
            pad_left = pad_total // 2
            pad_right = pad_total - pad_left
            rotated = cv2.copyMakeBorder(
                rotated, 0, 0, pad_left, pad_right,
                cv2.BORDER_CONSTANT, value=[18, 18, 24]
            )
        return rotated

    @staticmethod
    def _parse_source(src: Union[str, int]) -> Union[str, int]:
        if isinstance(src, int):
            return src
        if isinstance(src, str):
            src = src.strip("'\"").strip()
            if src.isdigit():
                return int(src)
            if src.startswith("rtsp://"):
                src = CameraStreamManager._encode_rtsp_credentials(src)
        return src

    @staticmethod
    def _encode_rtsp_credentials(url: str) -> str:
        from urllib.parse import urlparse, urlunparse, quote
        try:
            parsed = urlparse(url)
            if parsed.username and parsed.password:
                encoded_user = quote(parsed.username, safe="")
                encoded_pass = quote(parsed.password, safe="")
                host_port = parsed.hostname
                if parsed.port:
                    host_port = f"{parsed.hostname}:{parsed.port}"
                new_netloc = f"{encoded_user}:{encoded_pass}@{host_port}"
                return urlunparse(parsed._replace(netloc=new_netloc))
        except Exception as e:
            logger.debug(f"Could not encode RTSP URL credentials: {e}")
        return url


# ── Legacy singleton (backward-compat with api/camera.py and detection_service.py) ──
camera_manager = CameraStreamManager()
