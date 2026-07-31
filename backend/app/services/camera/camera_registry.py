import json
import time
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from app.config import settings, CAMERAS_JSON_PATH
from app.models.schemas import CameraConfigModel
from app.core.database import SessionLocal
from app.models.db_models import CameraModel

logger = logging.getLogger(__name__)

class CameraRegistry:
    """
    Enterprise Camera Registry and Lifecycle Manager.
    Persists cameras in SQLite/cameras.json and coordinates per-camera execution threads.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.workers: Dict[str, Any] = {} # camera_id -> CameraWorker

    def load_cameras_from_db(self) -> List[CameraConfigModel]:
        """Loads camera configs from cameras.json and syncs SQLite database."""
        cams_list = []
        if CAMERAS_JSON_PATH.exists():
            try:
                with open(CAMERAS_JSON_PATH, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                    for idx, c in enumerate(raw_list):
                        cam_id = c.get("id") or c.get("camera_id") or f"cam_{idx+1:02d}"
                        cams_list.append(CameraConfigModel(
                            id=idx + 1,
                            camera_id=cam_id,
                            name=c.get("name", f"Camera {cam_id}"),
                            source=str(c.get("source", "0")),
                            location=c.get("location", "Default Location"),
                            brand=c.get("brand", "Custom"),
                            ip_address=c.get("ip_address", ""),
                            port=int(c.get("port", 554)) if c.get("port") else 554,
                            username=c.get("username", ""),
                            password=c.get("password", ""),
                            channel=int(c.get("channel", 1)) if c.get("channel") else 1,
                            stream_type=c.get("stream_type", "sub"),
                            enabled=bool(c.get("enabled", True)),
                            rotation=int(c.get("rotation", 0)),
                            fps_limit=int(c.get("fps_limit", 15)) if c.get("fps_limit") else 15,
                            status="ONLINE" if bool(c.get("enabled", True)) else "OFFLINE"
                        ))
            except Exception as j_err:
                logger.error(f"Error loading cameras.json: {j_err}")

        if not cams_list:
            cams_list = [
                CameraConfigModel(
                    id=1,
                    camera_id="default_cam",
                    name="Default Camera",
                    source=str(settings.DEFAULT_CAMERA_SOURCE),
                    location="Default Location",
                    enabled=True,
                    rotation=0,
                    fps_limit=15,
                    status="ONLINE"
                )
            ]

        # Sync SQLite DB
        db = SessionLocal()
        try:
            db.query(CameraModel).delete()
            for cam in cams_list:
                db_cam = CameraModel(
                    camera_id=cam.camera_id,
                    name=cam.name,
                    source=cam.source,
                    location=cam.location,
                    enabled=cam.enabled,
                    rotation=cam.rotation,
                    fps_limit=cam.fps_limit,
                    status=cam.status
                )
                db.add(db_cam)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Error syncing SQLite DB in load_cameras_from_db: {e}")
        finally:
            db.close()

        return cams_list

    def sync_db_from_json(self):
        """Initializes database camera records from cameras.json."""
        self.load_cameras_from_db()

    def get_camera_health(self, camera_id: str) -> Dict[str, Any]:
        """Returns live health and status metrics for a specific camera worker."""
        with self.lock:
            worker = self.workers.get(camera_id)
            if not worker:
                return {
                    "camera_id": camera_id,
                    "status": "DISCONNECTED",
                    "fps": 0.0,
                    "error_count": 0,
                    "is_active": False
                }
            return worker.get_health()

    def resolve_camera_source(self, input_source: Optional[str] = None) -> Tuple[str, str, int]:
        """
        Resolves input_source or camera_id to actual RTSP URL/source, name, and rotation.
        """
        cams = settings.get_cameras()
        if input_source:
            match = next((c for c in cams if c.get("id") == input_source or c.get("camera_id") == input_source), None)
            if match:
                return match["source"], match["name"], int(match.get("rotation", 0))
            return input_source, "Custom Source", 0

        enabled = [c for c in cams if c.get("enabled")]
        if enabled:
            return enabled[0]["source"], enabled[0]["name"], int(enabled[0].get("rotation", 0))
        if cams:
            return cams[0]["source"], cams[0]["name"], int(cams[0].get("rotation", 0))
        return settings.DEFAULT_CAMERA_SOURCE, "Default Camera", 0

    def get_all_cameras(self) -> List[Dict[str, Any]]:
        return settings.get_cameras()

    def add_or_update_camera(self, cam_dict: Dict[str, Any]) -> Dict[str, Any]:
        cams = settings.get_cameras()
        cam_id = cam_dict.get("id") or cam_dict.get("camera_id")
        existing_idx = next((i for i, c in enumerate(cams) if c.get("id") == cam_id or c.get("camera_id") == cam_id), None)
        if existing_idx is not None:
            cams[existing_idx] = cam_dict
        else:
            cams.append(cam_dict)
        settings.save_cameras(cams)

        # Sync to SQLite DB
        db = SessionLocal()
        try:
            db_cam = db.query(CameraModel).filter(CameraModel.camera_id == cam_id).first()
            if db_cam:
                db_cam.name = cam_dict.get("name")
                db_cam.source = cam_dict.get("source")
                db_cam.location = cam_dict.get("location")
                db_cam.enabled = bool(cam_dict.get("enabled", True))
                db_cam.rotation = int(cam_dict.get("rotation", 0))
                db_cam.fps_limit = int(cam_dict.get("fps_limit", 15))
                db_cam.status = "ONLINE" if bool(cam_dict.get("enabled", True)) else "OFFLINE"
            else:
                db_cam = CameraModel(
                    camera_id=cam_id,
                    name=cam_dict.get("name"),
                    source=cam_dict.get("source"),
                    location=cam_dict.get("location"),
                    enabled=bool(cam_dict.get("enabled", True)),
                    rotation=int(cam_dict.get("rotation", 0)),
                    fps_limit=int(cam_dict.get("fps_limit", 15)),
                    status="ONLINE" if bool(cam_dict.get("enabled", True)) else "OFFLINE"
                )
                db.add(db_cam)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Error syncing DB in add_or_update_camera: {e}")
        finally:
            db.close()

        return cam_dict


camera_registry = CameraRegistry()

# Top-level helper aliases for backward compatibility
resolve_camera_source = camera_registry.resolve_camera_source
get_all_cameras = camera_registry.get_all_cameras
add_or_update_camera = camera_registry.add_or_update_camera
