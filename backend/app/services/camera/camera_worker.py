"""
camera_worker.py — Isolated Per-Camera Worker

Each camera gets its own:
  - CameraStreamManager (dedicated capture thread + LatestFrameBuffer)
  - PipelineOrchestrator (3 pipeline threads: Streaming, Detection, Recognition)
  - AnnotatedFrameBuffer (output: JPEG-ready annotated frames)
  - Health Monitor (restarts dead threads automatically)

Camera failures are completely isolated: Camera 5 crashing does not affect Camera 1-4.
"""

import time
import logging
import threading
from typing import Dict, Any, Optional, Tuple
import numpy as np

from app.core.stream import CameraStreamManager
from app.core.frame_buffer import AnnotatedFrameBuffer
from app.services.camera.pipeline_orchestrator import PipelineOrchestrator
from app.models.schemas import CameraConfigModel

logger = logging.getLogger(__name__)


class CameraWorker:
    """
    Self-contained execution unit for a single camera source.

    Lifecycle:
        start() → capture + pipeline threads begin
        stop()  → all threads terminated, resources freed

    Health Monitor:
        A background watchdog thread restarts dead pipeline workers.
    """

    def __init__(self, config: CameraConfigModel):
        self.config = config
        self.camera_id = config.camera_id
        self.name = config.name

        # Each camera has its own annotated frame buffer (output to MJPEG)
        self.annotated_buffer = AnnotatedFrameBuffer()

        # Camera capture manager — writes to its own LatestFrameBuffer
        self.stream_manager = CameraStreamManager(
            source=config.source,
            rotation=config.rotation,
            camera_id=config.camera_id
        )

        # The AI pipeline reads from the camera's raw buffer, writes to annotated buffer
        self.orchestrator = PipelineOrchestrator(
            camera_id=config.camera_id,
            raw_buffer=self.stream_manager.frame_buffer,
            annotated_buffer=self.annotated_buffer,
        )

        self._running = False
        self._watchdog_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Stats
        self.status: str = "DISCONNECTED"
        self.error_count: int = 0
        self.start_time: Optional[float] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the camera capture and all pipeline workers."""
        with self._lock:
            if self._running:
                return True

            logger.info(f"[CameraWorker:{self.camera_id}] Starting camera: {self.name}")

            # Start capture thread
            if not self.stream_manager.start():
                self.status = "ERROR"
                self.error_count += 1
                logger.error(f"[CameraWorker:{self.camera_id}] Failed to open camera stream.")
                return False

            # Start pipeline (Streaming + Detection + Recognition threads)
            self.orchestrator.start()

            self._running = True
            self.status = "CONNECTED"
            self.start_time = time.monotonic()

            # Start watchdog to recover from thread crashes
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                name=f"Watchdog-{self.camera_id}",
                daemon=True
            )
            self._watchdog_thread.start()

            logger.info(f"[CameraWorker:{self.camera_id}] All systems running.")
            return True

    def stop(self):
        """Stop all threads and release resources."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        logger.info(f"[CameraWorker:{self.camera_id}] Stopping...")
        try:
            self.orchestrator.stop()
        except Exception as e:
            logger.warning(f"[CameraWorker:{self.camera_id}] Orchestrator stop error: {e}")
        try:
            self.stream_manager.stop()
        except Exception as e:
            logger.warning(f"[CameraWorker:{self.camera_id}] Stream stop error: {e}")
        try:
            self.annotated_buffer.clear()
        except Exception:
            pass
        self.status = "DISCONNECTED"
        logger.info(f"[CameraWorker:{self.camera_id}] Stopped.")

    def restart(self) -> bool:
        """Restart the worker (used for reconnect recovery)."""
        logger.info(f"[CameraWorker:{self.camera_id}] Restarting...")
        self.stop()
        time.sleep(1.0)
        return self.start()

    # ─────────────────────────────────────────────────────────────────────────
    # Health Monitor (Watchdog)
    # ─────────────────────────────────────────────────────────────────────────

    def _watchdog_loop(self):
        """
        Periodically checks if the camera and pipeline are healthy.
        Prefers in-thread reconnect over stop()/start() to avoid racing
        VideoCapture.release() against a blocking FFmpeg read (SIGSEGV).
        """
        check_interval = 10.0  # Check every 10 seconds
        consecutive_stream_failures = 0

        while self._running:
            time.sleep(check_interval)

            if not self._running:
                break

            # Check camera health
            if not self.stream_manager.is_healthy():
                # Allow a grace period of 60 seconds from startup before triggering reconnect
                uptime = time.monotonic() - self.start_time if self.start_time else 0
                if uptime < 60.0:
                    logger.info(
                        f"[Watchdog:{self.camera_id}] Camera stream initializing "
                        f"(uptime: {uptime:.1f}s/60s grace)..."
                    )
                    continue

                consecutive_stream_failures += 1
                self.status = "RECONNECTING"
                self.error_count += 1
                logger.warning(
                    f"[Watchdog:{self.camera_id}] Camera appears dead "
                    f"(last frame: {self.stream_manager.frame_buffer.age_seconds:.1f}s ago, "
                    f"consecutive failures: {consecutive_stream_failures}). "
                    "Requesting in-thread reconnect..."
                )

                # Soft reconnect: keep the capture thread alive; it re-opens
                # VideoCapture under its own lock. Never release from this thread.
                try:
                    self.stream_manager.request_reconnect()
                except Exception as e:
                    logger.error(f"[Watchdog:{self.camera_id}] Soft reconnect error: {e}")

                # Only do a full restart after a long outage, and only if soft
                # reconnect has not recovered (frames still stale).
                if consecutive_stream_failures > 18:  # ~3 minutes
                    logger.warning(
                        f"[Watchdog:{self.camera_id}] Stream dead for >3min. "
                        "Full pipeline restart..."
                    )
                    try:
                        self.orchestrator.stop()
                        self.stream_manager.stop()
                        time.sleep(3.0)
                        if not self._running:
                            break
                        if self.stream_manager.start():
                            self.orchestrator.start()
                            self.status = "CONNECTED"
                            consecutive_stream_failures = 0
                            logger.info(
                                f"[Watchdog:{self.camera_id}] Full pipeline restart successful."
                            )
                        else:
                            self.status = "ERROR"
                            logger.error(
                                f"[Watchdog:{self.camera_id}] Full pipeline restart failed. "
                                "Will retry..."
                            )
                    except Exception as e:
                        self.status = "ERROR"
                        logger.error(f"[Watchdog:{self.camera_id}] Full restart error: {e}")
                continue

            # Stream is healthy — reset failure counter
            consecutive_stream_failures = 0

            # Check pipeline workers
            if not self.orchestrator.is_running():
                logger.warning(
                    f"[Watchdog:{self.camera_id}] Pipeline workers crashed. Restarting..."
                )
                try:
                    self.orchestrator.stop()
                    time.sleep(1.0)
                    if self._running:
                        self.orchestrator.start()
                except Exception as e:
                    logger.error(f"[Watchdog:{self.camera_id}] Pipeline restart error: {e}")

            self.status = "CONNECTED"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_annotated_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Get the latest annotated (overlay) frame for MJPEG streaming."""
        return self.annotated_buffer.get_frame(timeout=0.04)

    def get_raw_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Get the latest raw camera frame."""
        return self.stream_manager.read()

    def is_active(self) -> bool:
        return self._running and self.stream_manager.is_active()

    def get_health(self) -> Dict[str, Any]:
        fps = self.orchestrator.get_fps()
        uptime = round(time.monotonic() - self.start_time, 1) if self.start_time else 0
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "status": self.status,
            "is_active": self.is_active(),
            "stream_fps": fps.get("stream_fps", 0.0),
            "detect_fps": fps.get("detect_fps", 0.0),
            "error_count": self.error_count,
            "uptime_seconds": uptime,
            "last_frame_age_s": round(self.stream_manager.frame_buffer.age_seconds, 2),
            "camera_health": self.stream_manager.get_health(),
        }
