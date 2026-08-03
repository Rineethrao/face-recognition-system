import logging
import importlib
from typing import Optional, List, Dict, Any
import numpy as np
from fastapi import APIRouter

from app.config import settings
from app.projects.base import BaseProjectPlugin
from app.models.schemas import RecognitionEvent

logger = logging.getLogger(__name__)

class PluginManager:
    """
    Plugin Manager for dynamically loading and orchestrating active domain projects
    based on settings in config.json.
    """
    def __init__(self):
        self.active_plugins: List[BaseProjectPlugin] = []
        self.load_plugins()

    def load_plugins(self):
        self.active_plugins.clear()
        raw = settings.raw_config
        active_project = raw.get("active_project", "office_attendance")
        projects_cfg = raw.get("projects", {})

        logger.info(f"Loading domain project plugins (Active Project: '{active_project}')...")

        # Map project names to module paths
        project_modules = {
            "office_attendance": ("app.projects.office_attendance.plugin", "OfficeAttendancePlugin"),
            "temple_security": ("app.projects.temple_security.plugin", "TempleSecurityPlugin"),
            "retail_analytics": ("app.projects.retail_analytics.plugin", "RetailAnalyticsPlugin")
        }

        for p_name, (mod_path, class_name) in project_modules.items():
            p_config = projects_cfg.get(p_name, {})
            # Enable if explicitly set enabled or if it is the active_project
            is_enabled = p_config.get("enabled", p_name == active_project)

            if is_enabled:
                try:
                    mod = importlib.import_module(mod_path)
                    plugin_class = getattr(mod, class_name)
                    plugin_instance: BaseProjectPlugin = plugin_class(p_name, p_config)
                    self.active_plugins.append(plugin_instance)
                    logger.info(f"[Plugin System] Loaded active project plugin: '{p_name}' ({class_name})")
                except Exception as e:
                    logger.error(f"[Plugin System] Failed to load plugin '{p_name}': {e}", exc_info=True)

    def dispatch_person_detected(self, frame: np.ndarray, track_id: int, bbox: List[float]):
        for plugin in self.active_plugins:
            try:
                plugin.on_person_detected(frame, track_id, bbox)
            except Exception as e:
                logger.error(f"Error dispatching person_detected to {plugin.project_name}: {e}")

    def dispatch_face_recognized(self, event: RecognitionEvent):
        for plugin in self.active_plugins:
            try:
                plugin.on_face_recognized(event)
            except Exception as e:
                logger.error(f"Error dispatching face_recognized to {plugin.project_name}: {e}")

    def get_project_routers(self) -> List[APIRouter]:
        routers = []
        for plugin in self.active_plugins:
            r = plugin.get_router()
            if r is not None:
                routers.append(r)
        return routers

plugin_manager = PluginManager()
