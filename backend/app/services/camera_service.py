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

class CameraService:
    """
    Enterprise Camera Management & Lifecycle Service.
    Persists cameras in SQLite/cameras.json and provides camera resolution.
    """
    def __init__(self):
        self.lock = threading.Lock()

    def load_cameras_from_db(self) -> List[CameraConfigModel]:
        """Loads camera configs from DB or fallback cameras.json."""
        db = SessionLocal()
        try:
            db_cams = db.query(CameraModel).all()
            if db_cams:
                return [
                    CameraConfigModel(
                        id=c.id,
                        camera_id=c.camera_id,
                        name=c.name,
                        source=c.source,
                        location=c.location,
                        enabled=c.enabled,
                        rotation=c.rotation,
                        fps_limit=c.fps_limit,
                        status=c.status,
                        last_heartbeat=c.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S") if c.last_heartbeat else None,
                        error_count=c.error_count
                    )
                    for c in db_cams
                ]
        except Exception as e:
            logger.error(f"Error loading cameras from DB: {e}")
        finally:
            db.close()

        # Fallback to cameras.json
        if CAMERAS_JSON_PATH.exists():
            try:
                with open(CAMERAS_JSON_PATH, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                    res = []
                    for idx, c in enumerate(raw_list):
                        cam_id = c.get("id", f"cam_{idx+1:02d}")
                        res.append(CameraConfigModel(
                            camera_id=cam_id,
                            name=c.get("name", f"Camera {cam_id}"),
                            source=str(c.get("source", "0")),
                            location=c.get("location", "Default Location"),
                            enabled=bool(c.get("enabled", True)),
                            rotation=int(c.get("rotation", 0)),
                            fps_limit=15
                        ))
                    return res
            except Exception as j_err:
                logger.error(f"Error loading cameras.json: {j_err}")

        return [
            CameraConfigModel(
                camera_id="default_cam",
                name="Default Camera",
                source=str(settings.DEFAULT_CAMERA_SOURCE),
                location="Default Location",
                enabled=True,
                rotation=0,
                fps_limit=15
            )
        ]

    def sync_db_from_json(self):
        """Initializes database camera records from cameras.json if DB is empty."""
        db = SessionLocal()
        try:
            count = db.query(CameraModel).count()
            if count == 0 and CAMERAS_JSON_PATH.exists():
                with open(CAMERAS_JSON_PATH, "r", encoding="utf-8") as f:
                    raw_list = json.load(f)
                    for idx, c in enumerate(raw_list):
                        cam_id = c.get("id", f"cam_{idx+1:02d}")
                        c_model = CameraModel(
                            camera_id=cam_id,
                            name=c.get("name", f"Camera {cam_id}"),
                            source=str(c.get("source", "0")),
                            location=c.get("location", "Default Location"),
                            enabled=bool(c.get("enabled", True)),
                            rotation=int(c.get("rotation", 0)),
                            fps_limit=15,
                            status="DISCONNECTED"
                        )
                        db.add(c_model)
                    db.commit()
                    logger.info("Synchronized initial cameras.json into cameras table.")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to sync cameras to DB: {e}")
        finally:
            db.close()

    def resolve_camera_source(self, input_source: Optional[str] = None) -> Tuple[str, str, int]:
        """
        Resolves input_source or camera_id (e.g. 'cam_03') to actual RTSP URL/source, name, and rotation.
        If input_source is None/empty, selects the first enabled camera in cameras.json.
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
        return cam_dict

camera_service = CameraService()
camera_registry = camera_service

# Top-level helper functions for direct calls
def resolve_camera_source(input_source: Optional[str] = None) -> Tuple[str, str, int]:
    return camera_service.resolve_camera_source(input_source)

def get_all_cameras() -> List[Dict[str, Any]]:
    return camera_service.get_all_cameras()

def add_or_update_camera(cam_dict: Dict[str, Any]) -> Dict[str, Any]:
    return camera_service.add_or_update_camera(cam_dict)
