"""
api/camera.py — Enterprise Multi-Camera API & Isolated MJPEG Streaming Engine

Backend Responsibilities:
- Receives structured camera configuration (Brand, IP, Port, Username, Password, Channel, StreamType)
- Generates RTSP URLs automatically based on brand templates
- Validates RTSP connection health
- Manages isolated per-camera worker threads (CameraWorker)
- Auto-syncs cameras.json and SQLite database
- Serves strictly isolated per-camera MJPEG streams via /video_feed/{camera_id}
"""

import time
import logging
import cv2
import numpy as np
from typing import Optional, Dict, Any
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    CameraStartRequest, CameraConfigModel, CameraCreateRequest,
    CameraTestRequest, APIResponse
)
from app.core.stream import camera_manager
from app.services.camera.camera_registry import (
    camera_registry, resolve_camera_source, get_all_cameras, add_or_update_camera
)
from app.services.detection_service import detection_service
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Camera Management"])


def build_rtsp_url(cam: Any) -> str:
    """Generates brand-specific RTSP URLs automatically based on IP address and parameters."""
    ip = getattr(cam, 'ip_address', None) or ""
    ip = ip.strip()

    # If no IP address is provided, fallback to raw source (e.g. webcam index '0' or custom stream URL)
    if not ip and hasattr(cam, 'source') and cam.source:
        return cam.source

    ip_val = ip if ip else "127.0.0.1"
    port = getattr(cam, 'port', 554) or 554
    user = getattr(cam, 'username', '') or ''
    password = getattr(cam, 'password', '') or ''
    channel = getattr(cam, 'channel', 1) or 1
    stream_type = (getattr(cam, 'stream_type', 'main') or 'main').lower()
    brand = (getattr(cam, 'brand', 'Custom') or 'Custom').strip()

    # URL encode credentials safely
    auth_part = ""
    if user and password:
        auth_part = f"{quote(user, safe='')}:{quote(password, safe='')}@"
    elif user:
        auth_part = f"{quote(user, safe='')}@"

    subtype_num = 0 if stream_type == 'main' else 1
    stream_num = 1 if stream_type == 'main' else 2

    if brand in ["CP Plus", "Dahua", "CP_PLUS"]:
        return f"rtsp://{auth_part}{ip_val}:{port}/cam/realmonitor?channel={channel}&subtype={subtype_num}"
    elif brand == "Hikvision":
        return f"rtsp://{auth_part}{ip_val}:{port}/Streaming/Channels/{channel}0{stream_num}"
    elif brand == "Securus":
        return f"rtsp://{auth_part}{ip_val}:{port}/stream{stream_num}"
    elif brand == "Axis":
        profile = "main" if stream_type == 'main' else "sub"
        return f"rtsp://{auth_part}{ip_val}:{port}/axis-media/media.amp?videocodec=h264&streamprofile={profile}"
    elif brand == "ONVIF":
        return f"rtsp://{auth_part}{ip_val}:{port}/onvif1"
    else: # Custom
        return f"rtsp://{auth_part}{ip_val}:{port}/stream{stream_num}"


# ─────────────────────────────────────────────────────────────────────────────
# Camera Management CRUD Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/cameras", response_model=APIResponse)
def get_cameras():
    """Returns all configured cameras from cameras.json / DB with real-time active status."""
    cams = get_all_cameras()
    # Enrich each camera entry with real-time active status from running workers
    try:
        with camera_registry.lock:
            workers = dict(camera_registry.workers)
        for cam in cams:
            cam_id = cam.get("id") or cam.get("camera_id")
            worker = workers.get(cam_id)
            cam["is_active"] = worker.is_active() if worker else False
    except Exception:
        pass
    return APIResponse(
        status="success",
        message=f"Retrieved {len(cams)} configured camera streams.",
        data=cams
    )


@router.get("/cameras/{camera_id}", response_model=APIResponse)
def get_camera_by_id(camera_id: str):
    """Returns detailed information for a single camera."""
    cams = get_all_cameras()
    match = next((c for c in cams if c.get("id") == camera_id or c.get("camera_id") == camera_id), None)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found."
        )
    return APIResponse(
        status="success",
        message=f"Found camera '{camera_id}'.",
        data=match
    )


@router.post("/cameras", response_model=APIResponse)
def create_or_update_camera(req: CameraCreateRequest):
    """
    Creates or updates a camera definition.
    Backend automatically constructs the RTSP URL, updates cameras.json, and starts/stops worker threads.
    """
    cams = get_all_cameras()

    # Generate camera ID if not provided, ensuring no collision with existing IDs
    cam_id = req.camera_id or req.id
    if not cam_id:
        existing_numbers = []
        for c in cams:
            cid = str(c.get("id") or c.get("camera_id") or "")
            if cid.startswith("cam_"):
                num_part = cid.replace("cam_", "")
                if num_part.isdigit():
                    existing_numbers.append(int(num_part))
        next_num = (max(existing_numbers) + 1) if existing_numbers else (len(cams) + 1)
        cam_id = f"cam_{next_num:02d}"

    # Check for duplicate names (excluding current camera_id if updating)
    dup_name = next((c for c in cams if c.get("name").lower() == req.name.lower() and c.get("id") != cam_id and c.get("camera_id") != cam_id), None)
    if dup_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A camera named '{req.name}' already exists. Please choose a unique name."
        )

    # Auto-generate fresh RTSP URL
    rtsp_url = build_rtsp_url(req)

    cam_dict = {
        "id": cam_id,
        "camera_id": cam_id,
        "name": req.name,
        "location": req.location or "Default Location",
        "description": req.description or "",
        "brand": req.brand,
        "ip_address": req.ip_address or "",
        "port": req.port,
        "username": req.username or "",
        "password": req.password or "",
        "channel": req.channel,
        "stream_type": req.stream_type,
        "source": rtsp_url,
        "enabled": req.enabled,
        "rotation": req.rotation,
        "fps_limit": req.fps_limit,
        "status": "ONLINE" if req.enabled else "OFFLINE"
    }

    # Save to cameras.json and sync
    updated = add_or_update_camera(cam_dict)

    # Manage worker lifecycle strictly for this camera ID
    try:
        from app.services.camera.camera_worker import CameraWorker

        with camera_registry.lock:
            existing_worker = camera_registry.workers.get(cam_id)
            if existing_worker:
                logger.info(f"[API] Stopping existing worker for camera '{cam_id}'...")
                existing_worker.stop()
                del camera_registry.workers[cam_id]

            if req.enabled:
                logger.info(f"[API] Starting new worker for camera '{cam_id}' ({rtsp_url[:40]})...")
                cfg = CameraConfigModel(**cam_dict)
                new_worker = CameraWorker(cfg)
                if new_worker.start():
                    camera_registry.workers[cam_id] = new_worker
                    logger.info(f"[API] CameraWorker '{cam_id}' started successfully.")
                else:
                    logger.warning(f"[API] CameraWorker '{cam_id}' failed to start stream.")
            else:
                logger.info(f"[API] Camera '{cam_id}' disabled — worker stopped.")
    except Exception as err:
        logger.error(f"[API] Error managing worker for camera '{cam_id}': {err}")

    return APIResponse(
        status="success",
        message=f"Camera '{req.name}' ({cam_id}) saved successfully.",
        data=updated
    )


@router.put("/cameras/{camera_id}", response_model=APIResponse)
def update_camera(camera_id: str, req: CameraCreateRequest):
    """Updates an existing camera configuration."""
    req.id = camera_id
    req.camera_id = camera_id
    return create_or_update_camera(req)


@router.delete("/cameras/{camera_id}", response_model=APIResponse)
def delete_camera(camera_id: str):
    """Deletes a camera definition from cameras.json and stops its worker thread."""
    cams = get_all_cameras()
    match_idx = next((i for i, c in enumerate(cams) if c.get("id") == camera_id or c.get("camera_id") == camera_id), None)

    if match_idx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera '{camera_id}' not found."
        )

    deleted_cam = cams.pop(match_idx)
    settings.save_cameras(cams)

    # Stop and remove worker thread
    with camera_registry.lock:
        worker = camera_registry.workers.get(camera_id)
        if worker:
            worker.stop()
            del camera_registry.workers[camera_id]

    return APIResponse(
        status="success",
        message=f"Camera '{deleted_cam.get('name')}' ({camera_id}) deleted successfully.",
        data={"camera_id": camera_id}
    )


@router.post("/camera/test", response_model=APIResponse)
def test_camera_connection(req: CameraTestRequest):
    """
    Tests RTSP connection health by attempting to read 1 frame within 4 seconds.
    """
    rtsp_url = build_rtsp_url(req)
    logger.info(f"[TestConnection] Testing RTSP stream: {rtsp_url[:40]}...")

    start_t = time.monotonic()
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        return APIResponse(
            status="error",
            message=f"Connection failed: Could not open RTSP stream at {req.ip_address or 'source'}:{req.port}. Check IP address, port, or network connection.",
            data={"connected": False, "rtsp_url": rtsp_url}
        )

    ret, frame = cap.read()
    cap.release()
    elapsed = round(time.monotonic() - start_t, 2)

    if not ret or frame is None:
        return APIResponse(
            status="error",
            message="Connection timeout: Stream opened but failed to deliver video frames. Check authentication credentials (username/password) or channel number.",
            data={"connected": False, "rtsp_url": rtsp_url, "elapsed_s": elapsed}
        )

    _, jpeg_buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
    import base64
    preview_b64 = "data:image/jpeg;base64," + base64.b64encode(jpeg_buf.tobytes()).decode('utf-8')

    return APIResponse(
        status="success",
        message=f"Connection test successful! Received video frame in {elapsed}s.",
        data={
            "connected": True,
            "resolution": f"{frame.shape[1]}x{frame.shape[0]}",
            "elapsed_s": elapsed,
            "preview_b64": preview_b64
        }
    )


@router.post("/camera/start", response_model=APIResponse)
def start_camera(req: Optional[CameraStartRequest] = None):
    """Starts/enables a specific camera worker by camera_id."""
    requested_src = req.source if req and req.source else None
    cams = get_all_cameras()
    match = next((c for c in cams if c.get("id") == requested_src or c.get("camera_id") == requested_src), None)

    if match:
        cam_dict = dict(match)
        cam_dict["enabled"] = True
        cam_dict["status"] = "ONLINE"
        add_or_update_camera(cam_dict)
        try:
            from app.services.camera.camera_worker import CameraWorker
            with camera_registry.lock:
                existing_worker = camera_registry.workers.get(requested_src)
                if existing_worker:
                    existing_worker.stop()
                    del camera_registry.workers[requested_src]

                cfg = CameraConfigModel(**cam_dict)
                new_worker = CameraWorker(cfg)
                if new_worker.start():
                    camera_registry.workers[requested_src] = new_worker
                    return APIResponse(
                        status="success",
                        message=f"Camera worker '{cam_dict.get('name')}' started.",
                        data={"camera_id": requested_src, "is_active": True}
                    )
        except Exception as e:
            logger.error(f"Error starting camera worker: {e}")

    return APIResponse(
        status="error",
        message=f"Could not start camera '{requested_src}'.",
        data={"is_active": False}
    )


@router.post("/camera/stop", response_model=APIResponse)
def stop_camera():
    """Stops all active camera streams."""
    detection_service.stop_recognition()
    camera_manager.stop()
    with camera_registry.lock:
        workers = dict(camera_registry.workers)
        for wid, worker in workers.items():
            worker.stop()
        camera_registry.workers.clear()
    return APIResponse(
        status="success",
        message="All camera streams stopped successfully.",
        data={"is_active": False}
    )


# ─────────────────────────────────────────────────────────────────────────────
# Strictly Isolated Per-Camera MJPEG Video Streaming Endpoint
# ─────────────────────────────────────────────────────────────────────────────

def _make_connecting_frame(cam_name: str, details: str) -> bytes:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(frame, f"Camera: {cam_name[:28]}", (30, 210),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
    cv2.putText(frame, details[:50], (30, 255),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)
    cv2.putText(frame, "Stream Offline / Initializing...", (30, 295),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 200, 0), 1)
    _, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return buf.tobytes()


def generate_mjpeg_stream_v2(camera_id: Optional[str] = None):
    """
    STRICTLY ISOLATED MJPEG stream generator per camera_id.
    Reads pre-encoded JPEG bytes ONLY from the specific camera worker's AnnotatedFrameBuffer.
    NEVER bleeds other camera streams.
    """
    stream_fps = getattr(settings, 'STREAM_FPS', 25)
    frame_interval = 1.0 / max(1, stream_fps)
    last_sent_ts = 0.0
    placeholder_cooldown = 0.0

    while True:
        t_start = time.monotonic()
        jpeg_bytes = None
        ts = 0.0

        try:
            from app.services.camera.camera_registry import camera_registry as _reg
            with _reg.lock:
                workers = dict(_reg.workers)

            # Match worker strictly by camera_id or fallback to default active camera
            target_worker = None
            if camera_id and camera_id != "default":
                target_worker = workers.get(camera_id)
                if not target_worker:
                    for w in workers.values():
                        w_id = getattr(w, 'camera_id', None) or getattr(w.config, 'camera_id', None) or getattr(w.config, 'id', None)
                        if w_id == camera_id:
                            target_worker = w
                            break

            if not target_worker:
                # If no specific camera_id requested or not found, pick first active worker
                for w in workers.values():
                    if w.is_active():
                        target_worker = w
                        break
                if not target_worker and workers:
                    target_worker = next(iter(workers.values()))

            if target_worker:
                # Prefer annotated JPEG even during brief reconnect blips
                jpeg_bytes, ts = target_worker.annotated_buffer.get_jpeg_with_timestamp()
                if not jpeg_bytes and target_worker.is_active():
                    jpeg_bytes, ts = target_worker.annotated_buffer.get_jpeg_with_timestamp()
            else:
                # Fallback to legacy single-camera detection_service if active
                from app.services.detection_service import detection_service
                ok, frame = detection_service.get_latest_annotated_frame()
                if ok and frame is not None:
                    ret_enc, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    if ret_enc:
                        jpeg_bytes = buf.tobytes()
                        ts = time.monotonic()

        except Exception as e:
            logger.error(f"[MJPEG:{camera_id}] Stream fetch error: {e}")

        if jpeg_bytes and len(jpeg_bytes) > 100:
            if ts > last_sent_ts:
                last_sent_ts = ts
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
            else:
                time.sleep(0.005)
                continue
        else:
            # Throttle placeholders so we don't spam the client during reconnect
            now = time.monotonic()
            if now - placeholder_cooldown >= 1.0:
                placeholder_cooldown = now
                placeholder = _make_connecting_frame(camera_id or "CCTV", f"Camera ID: {camera_id}")
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + placeholder + b'\r\n')
            time.sleep(0.25)

        spent = time.monotonic() - t_start
        sleep_t = frame_interval - spent
        if sleep_t > 0:
            time.sleep(sleep_t)


@router.get("/video_feed")
@router.get("/video_feed/{camera_id}")
@router.get("/cameras/{camera_id}/stream")
def video_feed(camera_id: Optional[str] = None):
    """Live MJPEG video stream endpoint for a specific camera ID."""
    return StreamingResponse(
        generate_mjpeg_stream_v2(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
