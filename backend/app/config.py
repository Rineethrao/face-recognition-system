import json
import os
from pathlib import Path
from typing import Any, Dict, List

# BASE_DIR points to backend/ directory (parent of app/)
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_JSON_PATH = BASE_DIR / "config.json"
CAMERAS_JSON_PATH = BASE_DIR / "cameras.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "name": "Core Face Recognition Engine",
        "debug": False
    },
    "database": {
        "url": f"sqlite:///{BASE_DIR / 'storage' / 'database.db'}",
        "faiss_index_path": "storage/embeddings/faiss_index.bin",
        "faiss_mapping_path": "storage/embeddings/id_mapping.json"
    },
    "models": {
        "detector_path": "models/det_10g.onnx",
        "recognition_path": "models/w600k_r50.onnx"
    },
    "storage": {
        "faces_dir": "storage/faces",
        "embeddings_dir": "storage/embeddings"
    },
    "camera": {
        "default_source": "0",
        "frame_width": 1280,
        "frame_height": 720,
        "rtsp_buffer_size": 1
    },
    "detector": {
        "input_width": 640,
        "input_height": 640,
        "score_threshold": 0.30,
        "nms_threshold": 0.40,
        "min_face_size": 15
    },
    "quality": {
        "blur_threshold": 40.0,
        "min_eye_distance": 10.0,
        "max_pose_ratio": 0.50,
        "enhance_enabled": True,
        "enhance_contrast": True,
        "enhance_sharpness": True,
        "enhance_denoise": True
    },
    "tracker": {
        "track_high_thresh": 0.35,
        "track_low_thresh": 0.10,
        "new_track_thresh": 0.40,
        "track_buffer": 30,
        "match_thresh": 0.80
    },
    "recognition": {
        "embedding_dim": 512,
        "similarity_threshold": 0.55,
        "time_window": 2.0
    },
    "registration": {
        "sample_count": 6,
        "min_samples": 5,
        "preferred_samples": 6,
        "max_samples": 8,
        "identity_guard_enabled": True,
        "identity_threshold": 0.60,
        "target_similarity_threshold": 0.55,
        "target_reacquire_threshold": 0.60,
        "duplicate_similarity_threshold": 0.88,
        "duplicate_warning_threshold": 0.52,
        "target_lost_timeout": 3.0,
        "capture_interval": 1.0,
        "processing_fps": 8,
        "min_detection_confidence": 0.45,
        "min_face_width": 45,
        "min_face_height": 45,
        "min_sharpness": 18.0,
        "min_brightness": 25.0,
        "max_brightness": 235.0,
        "spatial_weight": 0.20,
        "identity_weight": 0.70,
        "confidence_weight": 0.10,
        "max_reference_embeddings": 5,
        "frontal_yaw_range": [-0.12, 0.12],
        "left_yaw_range": [-0.35, -0.12],
        "right_yaw_range": [0.12, 0.35]
    },
    "pipeline": {
        "capture_fps": 30,
        "stream_fps": 25,
        "detection_fps": 8,
        "recognition_fps": 3,
        "jpeg_quality": 95,
        "adaptive_quality": True,
        "camera_timeout": 10,
        "reconnect_interval": 5,
        "max_reconnect_attempts": 20,
        "gpu_enabled": "auto"
    },
    "visitors": {
        "match_high": 0.45,
        "match_low": 0.35,
        "registered_match_threshold": 0.55,
        "candidate_match_margin": 0.002,
        "min_observations_for_new_visitor": 4,
        "min_observation_quality": 0.55,
        "max_samples_per_visitor": 10,
        "operational_day_start_hour": 0
    }
}

class Settings:
    def __init__(self, json_path: Path = CONFIG_JSON_PATH):
        self.json_path = json_path
        self.raw_config = self.load_config()

        # App & Paths
        self.BASE_DIR: Path = BASE_DIR
        self.APP_NAME: str = self.raw_config["app"].get("name", "Core Face Recognition Engine")

        self.DEBUG: bool = self.raw_config["app"].get("debug", False)

        # Directory Paths
        self.STORAGE_DIR: Path = BASE_DIR / "storage"
        self.FACES_DIR: Path = BASE_DIR / self.raw_config["storage"].get("faces_dir", "storage/faces")
        self.EMBEDDINGS_DIR: Path = BASE_DIR / self.raw_config["storage"].get("embeddings_dir", "storage/embeddings")
        self.MODELS_DIR: Path = BASE_DIR / "models"

        # Database & FAISS
        raw_db_url = self.raw_config["database"].get("url")
        if not raw_db_url or "storage/database.db" in raw_db_url:
            self.DATABASE_URL: str = f"sqlite:///{self.STORAGE_DIR / 'database.db'}"
        else:
            self.DATABASE_URL: str = raw_db_url

        self.FAISS_INDEX_PATH: Path = BASE_DIR / self.raw_config["database"].get("faiss_index_path", "storage/embeddings/faiss_index.bin")
        self.FAISS_MAPPING_PATH: Path = BASE_DIR / self.raw_config["database"].get("faiss_mapping_path", "storage/embeddings/id_mapping.json")

        # Models
        det_path = BASE_DIR / self.raw_config["models"].get("detector_path", "Ai-models/det_10g.onnx")
        if not det_path.exists():
            det_path = BASE_DIR / "Ai-models" / "det_10g.onnx"
        self.DETECTOR_MODEL_PATH: Path = det_path

        rec_path = BASE_DIR / self.raw_config["models"].get("recognition_path", "Ai-models/w600k_r50.onnx")
        if not rec_path.exists():
            rec_path = BASE_DIR / "Ai-models" / "w600k_r50.onnx"
        self.RECOGNITION_MODEL_PATH: Path = rec_path

        # Camera
        self.DEFAULT_CAMERA_SOURCE: str = str(self.raw_config["camera"].get("default_source", "0"))
        self.FRAME_WIDTH: int = int(self.raw_config["camera"].get("frame_width", 1280))
        self.FRAME_HEIGHT: int = int(self.raw_config["camera"].get("frame_height", 720))
        self.RTSP_BUFFER_SIZE: int = int(self.raw_config["camera"].get("rtsp_buffer_size", 1))

        # Detector
        det_w = int(self.raw_config["detector"].get("input_width", 640))
        det_h = int(self.raw_config["detector"].get("input_height", 640))
        self.DETECTOR_INPUT_SIZE: tuple = (det_w, det_h)
        self.DET_SCORE_THRESHOLD: float = float(self.raw_config["detector"].get("score_threshold", 0.35))
        self.DET_NMS_THRESHOLD: float = float(self.raw_config["detector"].get("nms_threshold", 0.40))
        self.MIN_FACE_SIZE: int = int(self.raw_config["detector"].get("min_face_size", 15))

        # Quality
        self.QUALITY_BLUR_THRESHOLD: float = float(self.raw_config["quality"].get("blur_threshold", 40.0))
        self.QUALITY_MIN_EYE_DISTANCE: float = float(self.raw_config["quality"].get("min_eye_distance", 10.0))
        self.QUALITY_MAX_POSE_RATIO: float = float(self.raw_config["quality"].get("max_pose_ratio", 0.50))
        self.QUALITY_ENHANCE_ENABLED: bool = bool(self.raw_config["quality"].get("enhance_enabled", True))
        self.QUALITY_ENHANCE_CONTRAST: bool = bool(self.raw_config["quality"].get("enhance_contrast", True))
        self.QUALITY_ENHANCE_SHARPNESS: bool = bool(self.raw_config["quality"].get("enhance_sharpness", True))
        self.QUALITY_ENHANCE_DENOISE: bool = bool(self.raw_config["quality"].get("enhance_denoise", True))

        # Tracker
        self.TRACK_HIGH_THRESH: float = float(self.raw_config["tracker"].get("track_high_thresh", 0.35))
        self.TRACK_LOW_THRESH: float = float(self.raw_config["tracker"].get("track_low_thresh", 0.10))
        self.NEW_TRACK_THRESH: float = float(self.raw_config["tracker"].get("new_track_thresh", 0.40))
        self.TRACK_BUFFER: int = int(self.raw_config["tracker"].get("track_buffer", 30))
        self.MATCH_THRESH: float = float(self.raw_config["tracker"].get("match_thresh", 0.80))

        # Recognition
        self.EMBEDDING_DIM: int = int(self.raw_config["recognition"].get("embedding_dim", 512))
        self.RECOGNITION_SIMILARITY_THRESHOLD: float = float(self.raw_config["recognition"].get("similarity_threshold", 0.45))
        self.RECOGNITION_TIME_WINDOW: float = float(self.raw_config["recognition"].get("time_window", 3.0))

        # Registration (face-first enrollment)
        _reg = self.raw_config.get("registration", {})
        self.REGISTRATION_SAMPLE_COUNT: int = int(_reg.get("preferred_samples", _reg.get("sample_count", 6)))
        self.REGISTRATION_MIN_SAMPLES: int = int(_reg.get("min_samples", 5))
        self.REGISTRATION_PREFERRED_SAMPLES: int = int(_reg.get("preferred_samples", 6))
        self.REGISTRATION_MAX_SAMPLES: int = int(_reg.get("max_samples", 8))
        self.REGISTRATION_IDENTITY_GUARD_ENABLED: bool = bool(_reg.get("identity_guard_enabled", True))
        self.REGISTRATION_IDENTITY_THRESHOLD: float = float(_reg.get("identity_threshold", 0.60))
        self.REGISTRATION_TARGET_SIMILARITY_THRESHOLD: float = float(_reg.get("target_similarity_threshold", 0.55))
        self.REGISTRATION_TARGET_REACQUIRE_THRESHOLD: float = float(_reg.get("target_reacquire_threshold", 0.60))
        self.REGISTRATION_DUPLICATE_SIMILARITY_THRESHOLD: float = float(_reg.get("duplicate_similarity_threshold", 0.88))
        self.REGISTRATION_DUPLICATE_WARNING_THRESHOLD: float = float(_reg.get("duplicate_warning_threshold", 0.52))
        self.REGISTRATION_TARGET_LOST_TIMEOUT: float = float(_reg.get("target_lost_timeout", 3.0))
        self.REGISTRATION_CAPTURE_INTERVAL: float = float(_reg.get("capture_interval", 1.0))
        self.REGISTRATION_PROCESSING_FPS: int = int(_reg.get("processing_fps", 8))
        self.REGISTRATION_MIN_DETECTION_CONFIDENCE: float = float(_reg.get("min_detection_confidence", 0.45))
        self.REGISTRATION_MIN_FACE_WIDTH: int = int(_reg.get("min_face_width", 45))
        self.REGISTRATION_MIN_FACE_HEIGHT: int = int(_reg.get("min_face_height", 45))
        self.REGISTRATION_MIN_SHARPNESS: float = float(_reg.get("min_sharpness", 18.0))
        self.REGISTRATION_MIN_BRIGHTNESS: float = float(_reg.get("min_brightness", 25.0))
        self.REGISTRATION_MAX_BRIGHTNESS: float = float(_reg.get("max_brightness", 235.0))
        self.REGISTRATION_SPATIAL_WEIGHT: float = float(_reg.get("spatial_weight", 0.20))
        self.REGISTRATION_IDENTITY_WEIGHT: float = float(_reg.get("identity_weight", 0.70))
        self.REGISTRATION_CONFIDENCE_WEIGHT: float = float(_reg.get("confidence_weight", 0.10))
        self.REGISTRATION_MAX_REFERENCE_EMBEDDINGS: int = int(_reg.get("max_reference_embeddings", 5))
        self.REGISTRATION_FRONTAL_YAW_RANGE = list(_reg.get("frontal_yaw_range", [-0.12, 0.12]))
        self.REGISTRATION_LEFT_YAW_RANGE = list(_reg.get("left_yaw_range", [-0.35, -0.12]))
        self.REGISTRATION_RIGHT_YAW_RANGE = list(_reg.get("right_yaw_range", [0.12, 0.35]))

        # ── Pipeline Configuration ──────────────────────────────────────────
        _pipeline = self.raw_config.get("pipeline", {})

        self.CAPTURE_FPS: int = int(_pipeline.get("capture_fps", 30))
        self.STREAM_FPS: int = int(_pipeline.get("stream_fps", 25))
        self.DETECTION_FPS: int = int(_pipeline.get("detection_fps", 8))
        self.RECOGNITION_FPS: int = int(_pipeline.get("recognition_fps", 3))
        self.JPEG_QUALITY: int = int(_pipeline.get("jpeg_quality", 95))
        self.ADAPTIVE_QUALITY: bool = bool(_pipeline.get("adaptive_quality", True))
        self.CAMERA_TIMEOUT: int = int(_pipeline.get("camera_timeout", 10))
        self.RECONNECT_INTERVAL: int = int(_pipeline.get("reconnect_interval", 5))
        self.MAX_RECONNECT_ATTEMPTS: int = int(_pipeline.get("max_reconnect_attempts", 20))

        # Auto-detect GPU and upgrade FPS targets if CUDA is available
        gpu_setting = _pipeline.get("gpu_enabled", "auto")
        self.GPU_ENABLED: bool = self._detect_gpu(gpu_setting)
        if self.GPU_ENABLED:
            # GPU can handle higher throughput — boost detection & recognition FPS
            self.DETECTION_FPS = max(self.DETECTION_FPS, 15)
            self.STREAM_FPS = max(self.STREAM_FPS, 30)

        # Ensure storage directories exist
        self.VISITORS_DIR: Path = BASE_DIR / "storage" / "visitors"
        os.makedirs(self.FACES_DIR, exist_ok=True)
        os.makedirs(self.EMBEDDINGS_DIR, exist_ok=True)
        os.makedirs(self.VISITORS_DIR, exist_ok=True)

        # ── Visitor Re-ID Configuration ─────────────────────────────────────
        _vis = self.raw_config.get("visitors", {})
        self.VISITOR_MATCH_HIGH_THRESHOLD: float = float(_vis.get("match_high", 0.58))
        self.VISITOR_MATCH_LOW_THRESHOLD: float = float(_vis.get("match_low", 0.45))
        self.VISITOR_MATCH_HIGH: float = self.VISITOR_MATCH_HIGH_THRESHOLD
        self.VISITOR_MATCH_LOW: float = self.VISITOR_MATCH_LOW_THRESHOLD
        self.REGISTERED_CONFIRMED_THRESHOLD: float = float(_vis.get("registered_confirmed_threshold", 0.40))
        self.VISITOR_REGISTERED_MATCH_THRESHOLD: float = self.REGISTERED_CONFIRMED_THRESHOLD
        self.VISITOR_CONFIRMED_THRESHOLD: float = float(_vis.get("visitor_confirmed_threshold", 0.58))
        self.VISITOR_PENDING_THRESHOLD: float = float(_vis.get("visitor_pending_threshold", 0.45))
        self.VISITOR_PROFILE_UPDATE_THRESHOLD: float = float(_vis.get("visitor_profile_update_threshold", 0.60))
        self.TRACK_CONFLICT_THRESHOLD: float = float(_vis.get("track_conflict_threshold", 0.45))
        self.NEW_VISITOR_INTERNAL_CONSISTENCY_THRESHOLD: float = float(_vis.get("new_visitor_internal_consistency", 0.58))
        self.AVATAR_IMPROVEMENT_MARGIN: float = float(_vis.get("avatar_improvement_margin", 0.08))
        self.VISITOR_CANDIDATE_MATCH_MARGIN: float = float(_vis.get("candidate_match_margin", 0.020))


        self.VISITOR_QUALITY_POOR_THRESH: float = float(_vis.get("quality_poor_threshold", 0.35))
        self.VISITOR_QUALITY_MATCHING_THRESH: float = float(_vis.get("quality_matching_threshold", 0.45))
        self.VISITOR_QUALITY_ENROLLMENT_THRESH: float = float(_vis.get("quality_enrollment_threshold", 0.52))
        self.VISITOR_QUALITY_AVATAR_THRESH: float = float(_vis.get("quality_avatar_threshold", 0.65))

        self.VISITOR_MIN_FACE_WIDTH: int = int(_vis.get("min_face_width", 22))
        self.VISITOR_MIN_FACE_HEIGHT: int = int(_vis.get("min_face_height", 22))
        self.VISITOR_MAX_ABS_YAW: float = float(_vis.get("max_abs_yaw", 0.22))
        self.VISITOR_MAX_ABS_PITCH: float = float(_vis.get("max_abs_pitch", 0.18))
        self.VISITOR_MIN_BLUR_SCORE: float = float(_vis.get("min_blur_score", 15.0))

        self.VISITOR_MIN_OBSERVATIONS_FOR_NEW: int = int(_vis.get("min_observations_for_new_visitor", 4))
        self.VISITOR_WITHIN_TRACK_CONSISTENCY_THRESH: float = float(_vis.get("within_track_consistency_thresh", 0.48))
        self.VISITOR_MAX_SAMPLES: int = int(_vis.get("max_samples_per_visitor", 8))
        self.VISITOR_OPERATIONAL_DAY_START_HOUR: int = int(_vis.get("operational_day_start_hour", 0))
        self.VISITOR_DUPLICATE_FLAG_THRESHOLD: float = float(_vis.get("duplicate_flag_threshold", 0.44))

        # Presence duration tracking
        _pres = self.raw_config.get("presence", {})
        self.PRESENCE_SESSION_TIMEOUT_SECONDS: int = int(_pres.get("session_timeout_seconds", 30))
        self.PRESENCE_REPORT_BOUNDARY: str = str(_pres.get("report_boundary", "00:00"))
        self.PRESENCE_ENABLE_LIVE_DURATION: bool = bool(_pres.get("enable_live_duration", True))



    @staticmethod
    def _detect_gpu(setting) -> bool:
        """Auto-detect CUDA availability or use explicit setting."""
        if isinstance(setting, bool):
            return setting
        if str(setting).lower() == "true":
            return True
        if str(setting).lower() == "false":
            return False
        # "auto" — check ONNX Runtime providers
        try:
            # pyrefly: ignore [missing-import]
            import onnxruntime as ort
            providers = ort.get_available_providers()
            has_cuda = 'CUDAExecutionProvider' in providers
            if has_cuda:
                import logging
                logging.getLogger("Settings").info("CUDA detected — enabling GPU acceleration mode.")
            return has_cuda
        except Exception:
            return False


    def load_config(self) -> Dict[str, Any]:
        if not self.json_path.exists():
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            return DEFAULT_CONFIG
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"[Warning] Failed to load {self.json_path}: {e}. Falling back to default settings.")
            return DEFAULT_CONFIG

    def get_cameras(self) -> List[Dict[str, Any]]:
        if not CAMERAS_JSON_PATH.exists():
            default_cams = [
                {"id": "cam_01", "name": "Default Camera", "source": self.DEFAULT_CAMERA_SOURCE, "location": "Main Entrance", "enabled": True}
            ]
            with open(CAMERAS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(default_cams, f, indent=2)
            return default_cams
        try:
            with open(CAMERAS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to load cameras.json: {e}")
            return []

    def save_cameras(self, cameras_list: List[Dict[str, Any]]):
        with open(CAMERAS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(cameras_list, f, indent=2)

settings = Settings()
