import os
import cv2
import numpy as np
import threading
import onnxruntime as ort

from app.config import settings
from app.core.utils import l2_normalize

class ArcFaceRecognizer:
    """
    ArcFace Face Embedding Feature Extractor (w600k_r50.onnx).
    Generates 512-dimensional normalized face embeddings.
    Shared across cameras — session.run is serialized via `_infer_lock`.
    """
    def __init__(self, model_path: str = str(settings.RECOGNITION_MODEL_PATH)):
        self.model_path = model_path
        self._infer_lock = threading.Lock()
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"ArcFace model file not found at: {self.model_path}")

        providers = ort.get_available_providers()
        selected_providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in providers else ['CPUExecutionProvider']

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(self.model_path, sess_options=so, providers=selected_providers)

        input_cfg = self.session.get_inputs()[0]
        self.input_name = input_cfg.name
        self.output_names = [o.name for o in self.session.get_outputs()]

    def extract_embedding(self, aligned_face_112: np.ndarray) -> np.ndarray:
        if aligned_face_112 is None or aligned_face_112.shape[:2] != (112, 112):
            raise ValueError("Input to ArcFace must be a valid 112x112 aligned image.")

        rgb = cv2.cvtColor(aligned_face_112, cv2.COLOR_BGR2RGB)
        blob = np.transpose(rgb, (2, 0, 1)).astype(np.float32)
        blob = (blob - 127.5) / 128.0
        blob = np.expand_dims(blob, axis=0)

        with self._infer_lock:
            outputs = self.session.run(self.output_names, {self.input_name: blob})
        embedding = outputs[0][0]
        return l2_normalize(embedding)

arcface_recognizer = ArcFaceRecognizer()
