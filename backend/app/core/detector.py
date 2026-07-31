import os
import cv2
import numpy as np
import threading
import onnxruntime as ort
from typing import List, Tuple, Optional

from app.config import settings
from app.models.schemas import DetectedFace

class SCRFDDetector:
    """
    SCRFD Face Detector powered by ONNXRuntime (det_10g.onnx).
    Performs multi-scale face detection and 5-point facial landmark extraction.
    Shared across cameras — session.run is serialized via `_infer_lock`.
    """
    def __init__(
        self,
        model_path: str = str(settings.DETECTOR_MODEL_PATH),
        input_size: Tuple[int, int] = settings.DETECTOR_INPUT_SIZE,
        conf_thresh: float = settings.DET_SCORE_THRESHOLD,
        nms_thresh: float = settings.DET_NMS_THRESHOLD
    ):
        self.model_path = model_path
        self.input_size = input_size
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh

        self.fmc = 3
        self._feat_stride_fpn = [8, 16, 32]
        self._num_anchors = 2
        self.center_cache = {}
        self._infer_lock = threading.Lock()

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"SCRFD detector ONNX model file not found at: {self.model_path}")

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

    def _preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        img_h, img_w = image.shape[:2]
        target_w, target_h = self.input_size

        scale = min(target_w / img_w, target_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)

        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        det_img = np.full((target_h, target_w, 3), 127, dtype=np.uint8)
        pad_top = (target_h - new_h) // 2
        pad_left = (target_w - new_w) // 2
        det_img[pad_top:pad_top + new_h, pad_left:pad_left + new_w] = resized

        blob = cv2.dnn.blobFromImage(
            det_img,
            1.0 / 128.0,
            (target_w, target_h),
            (127.5, 127.5, 127.5),
            swapRB=True
        )
        return blob, scale, (pad_left, pad_top)

    def _generate_anchors(self, height: int, width: int, stride: int) -> np.ndarray:
        key = (height, width, stride)
        if key in self.center_cache:
            return self.center_cache[key]

        anchor_centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
        anchor_centers = (anchor_centers * stride).reshape((-1, 2))
        if self._num_anchors > 1:
            anchor_centers = np.stack([anchor_centers] * self._num_anchors, axis=1).reshape((-1, 2))

        self.center_cache[key] = anchor_centers
        return anchor_centers

    def _distance_to_bbox(self, points: np.ndarray, distance: np.ndarray) -> np.ndarray:
        x1 = points[:, 0] - distance[:, 0]
        y1 = points[:, 1] - distance[:, 1]
        x2 = points[:, 0] + distance[:, 2]
        y2 = points[:, 1] + distance[:, 3]
        return np.stack([x1, y1, x2, y2], axis=-1)

    def _distance_to_kps(self, points: np.ndarray, distance: np.ndarray) -> np.ndarray:
        kps = np.zeros((distance.shape[0], 5, 2), dtype=np.float32)
        for i in range(5):
            kps[:, i, 0] = points[:, 0] + distance[:, i * 2]
            kps[:, i, 1] = points[:, 1] + distance[:, i * 2 + 1]
        return kps

    def _nms(self, boxes: np.ndarray, scores: np.ndarray, conf_thresh: Optional[float] = None) -> List[int]:
        if len(boxes) == 0:
            return []
        c_thresh = conf_thresh if conf_thresh is not None else settings.DET_SCORE_THRESHOLD
        rects = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes]
        indices = cv2.dnn.NMSBoxes(rects, scores.tolist(), c_thresh, self.nms_thresh)
        if len(indices) == 0:
            return []
        return indices.flatten().tolist()

    def detect(self, image: np.ndarray) -> List[DetectedFace]:
        if image is None or image.size == 0:
            return []

        conf_thresh = settings.DET_SCORE_THRESHOLD
        min_size = settings.MIN_FACE_SIZE

        blob, scale, (pad_left, pad_top) = self._preprocess(image)
        with self._infer_lock:
            net_outs = self.session.run(self.output_names, {self.input_name: blob})

        scores_list = []
        bboxes_list = []
        kpss_list = []

        num_outputs = len(net_outs)
        stride_count = len(self._feat_stride_fpn)

        for idx, stride in enumerate(self._feat_stride_fpn):
            score_mat = net_outs[idx]
            bbox_mat = net_outs[idx + stride_count]
            kps_mat = net_outs[idx + stride_count * 2] if num_outputs > stride_count * 2 else None

            if score_mat.ndim == 4:
                height, width = score_mat.shape[2], score_mat.shape[3]
            else:
                target_w, target_h = self.input_size
                height, width = target_h // stride, target_w // stride

            anchor_centers = self._generate_anchors(height, width, stride)

            scores = score_mat.reshape((-1, 1))
            bboxes = bbox_mat.reshape((-1, 4)) * stride
            kpss = kps_mat.reshape((-1, 10)) * stride if kps_mat is not None else None

            pos_inds = np.where(scores >= conf_thresh)[0]
            if len(pos_inds) == 0:
                continue

            scores = scores[pos_inds]
            bboxes = bboxes[pos_inds]
            anchor_centers = anchor_centers[pos_inds]

            decoded_bboxes = self._distance_to_bbox(anchor_centers, bboxes)

            scores_list.append(scores)
            bboxes_list.append(decoded_bboxes)

            if kpss is not None:
                kpss = kpss[pos_inds]
                decoded_kpss = self._distance_to_kps(anchor_centers, kpss)
                kpss_list.append(decoded_kpss)

        if not scores_list:
            return []

        scores = np.vstack(scores_list).flatten()
        bboxes = np.vstack(bboxes_list)
        kpss = np.vstack(kpss_list) if kpss_list else None

        keep_indices = self._nms(bboxes, scores, conf_thresh)
        if not keep_indices:
            return []

        detected_faces: List[DetectedFace] = []
        img_h, img_w = image.shape[:2]

        for i in keep_indices:
            box = bboxes[i]
            score = float(scores[i])

            x1 = max(0.0, float((box[0] - pad_left) / scale))
            y1 = max(0.0, float((box[1] - pad_top) / scale))
            x2 = min(float(img_w), float((box[2] - pad_left) / scale))
            y2 = min(float(img_h), float((box[3] - pad_top) / scale))

            if (x2 - x1) < min_size or (y2 - y1) < min_size:
                continue

            landmarks = []
            if kpss is not None:
                for kp in kpss[i]:
                    kx = float((kp[0] - pad_left) / scale)
                    ky = float((kp[1] - pad_top) / scale)
                    landmarks.append([kx, ky])

            detected_faces.append(DetectedFace(
                bbox=[x1, y1, x2, y2],
                score=score,
                landmarks=landmarks
            ))

        return detected_faces

detector_engine = SCRFDDetector()
