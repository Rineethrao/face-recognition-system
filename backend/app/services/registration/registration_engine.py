import base64
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.config import settings
from app.core.database import SessionLocal
from app.core.faiss_index import faiss_manager
from app.models.db_models import (
    AuditLogModel,
    EmbeddingModel,
    PersonImageModel,
    PersonModel,
)
from app.models.schemas import DetectedFace
from app.services.registration.capture_service import capture_service
from app.services.registration.duplicate_service import duplicate_service
from app.services.registration.embedding_service import embedding_service
from app.services.registration.gallery_service import gallery_service
from app.services.registration.pose_service import pose_service
from app.services.registration.quality_service import quality_service
from app.services.registration.storage_service import storage_service

logger = logging.getLogger(__name__)


def _bbox_iou(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _bbox_center_distance_norm(a: List[float], b: List[float], frame_wh: Tuple[int, int]) -> float:
    """Normalized center distance in [0, 1+] where 0 is identical centers."""
    if not a or not b:
        return 1.0
    aw, ah = max(1.0, frame_wh[0]), max(1.0, frame_wh[1])
    acx, acy = (a[0] + a[2]) / 2.0, (a[1] + a[3]) / 2.0
    bcx, bcy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    dist = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
    diag = (aw ** 2 + ah ** 2) ** 0.5
    return float(dist / max(diag, 1.0))


class RegistrationEngine:
    """
    Enterprise face-first registration engine.

    CCTV enrollment flow:
      Face Detection → Operator clicks FACE → Temporary reference embedding
      → TARGET_LOCKED → Identity association → Quality/Pose/Dedup → Review → Commit
    """

    def __init__(self):
        self.is_registering: bool = False
        self.person_id: Optional[str] = None
        self.person_name: Optional[str] = None
        self.person_info: Dict[str, Any] = {}
        self.target_samples: int = settings.REGISTRATION_PREFERRED_SAMPLES
        self.capture_method: str = "WEBCAM"
        self.last_ai_assistant: Dict[str, Any] = {
            "face_detected": False,
            "centered": False,
            "sharp": False,
            "lighting": False,
            "eyes_visible": False,
            "identity_verified": False,
            "guidance": "Position face inside frame",
            "status": "Ready for capture",
        }
        # Face-first session state
        self.session_id: Optional[str] = None
        self.target_state: str = "WAITING_FOR_SELECTION"
        self.target_track_id: Optional[int] = None  # internal continuity only
        self.locked_camera_id: Optional[str] = None
        self.target_locked: bool = False
        self.target_last_seen: Optional[float] = None
        self.target_face_bbox: Optional[List[float]] = None
        self.target_thumbnail: Optional[str] = None
        self.temporary_target_embeddings: List[np.ndarray] = []
        self.temporary_target_centroid: Optional[np.ndarray] = None
        self.target_lost_since: Optional[float] = None
        self.last_capture_time: float = 0.0
        self.last_target_similarity: float = 0.0
        self.pose_coverage: Dict[str, bool] = {}
        self._last_process_ts: float = 0.0

    # ── Session lifecycle ────────────────────────────────────────────────────

    def start_session(self, person_id: str, first_name: str, last_name: str, **kwargs) -> Dict[str, Any]:
        self.is_registering = True
        self.session_id = f"reg_{person_id}_{int(datetime.utcnow().timestamp())}"
        self.person_id = person_id
        full_name = f"{first_name} {last_name}".strip()
        self.person_name = full_name
        self.person_info = {
            "person_id": person_id,
            "first_name": first_name,
            "last_name": last_name,
            "name": full_name,
            "employee_id": kwargs.get("employee_id", person_id),
            "department": kwargs.get("department"),
            "designation": kwargs.get("designation"),
            "role": kwargs.get("role", "Employee"),
            "phone": kwargs.get("phone"),
            "email": kwargs.get("email"),
            "notes": kwargs.get("notes"),
        }
        self.target_samples = settings.REGISTRATION_PREFERRED_SAMPLES
        self._reset_target_state()
        gallery_service.clear()
        capture_service.unlock_track()
        logger.info("REG_SESSION_CREATED session=%s person=%s (%s)", self.session_id, full_name, person_id)
        return {
            "status": "success",
            "message": f"Session started for {full_name}",
            "session_id": self.session_id,
            "target_samples": self.target_samples,
        }

    def _reset_target_state(self):
        self.target_state = "WAITING_FOR_SELECTION"
        self.target_track_id = None
        self.locked_camera_id = None
        self.target_locked = False
        self.target_last_seen = None
        self.target_face_bbox = None
        self.target_thumbnail = None
        if not gallery_service.samples:
            self.temporary_target_embeddings = []
            self.temporary_target_centroid = None
            self.pose_coverage = {p: False for p in pose_service.cctv_required_poses()}
        self.target_lost_since = None
        self.last_capture_time = 0.0
        self.last_target_similarity = 0.0

    def unlock_target(self) -> Dict[str, Any]:
        self.target_state = "WAITING_FOR_SELECTION"
        self.target_locked = False
        self.target_track_id = None
        self.target_face_bbox = None
        capture_service.unlock_track()
        logger.info("REG_TARGET_UNLOCKED (retaining %d gallery samples)", len(gallery_service.samples))
        return {"status": "success", "message": "Target unlocked", "state": self.target_state}

    # ── Face selection (click-to-lock) ───────────────────────────────────────

    def select_face(
        self,
        frame: np.ndarray,
        face: Any,
        camera_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Operator clicked a face. Extract reference embedding and enter TARGET_LOCKED.
        Preserves existing gallery samples if the selected face matches current target identity.
        """
        if not self.is_registering:
            return {"status": "error", "message": "No active registration session"}

        landmarks = getattr(face, "landmarks", None)
        if landmarks is None:
            return {"status": "error", "message": "Selected face has no landmarks"}

        aligned = embedding_service.generate_aligned_crop(frame, landmarks)
        if aligned is None or aligned.size == 0:
            return {"status": "error", "message": "Could not align selected face"}

        embedding = embedding_service.extract_embedding(aligned)
        if embedding is None:
            return {"status": "error", "message": "Could not extract face embedding"}

        # Check if re-selecting the SAME identity or a DIFFERENT identity
        ref_centroid = self.temporary_target_centroid
        if ref_centroid is None and gallery_service.samples:
            sample_embs = [s["embedding"] for s in gallery_service.samples if s.get("embedding") is not None]
            if sample_embs:
                mean_vec = np.mean(sample_embs, axis=0)
                ref_centroid = mean_vec / (np.linalg.norm(mean_vec) + 1e-8)

        is_same_identity = False
        if ref_centroid is not None and embedding is not None:
            sim = float(np.dot(embedding, ref_centroid))
            if sim >= 0.55:  # Permissive similarity for CCTV re-locking angles
                is_same_identity = True

        if not is_same_identity and gallery_service.samples:
            # Different identity selected — clear previous gallery for new person
            gallery_service.clear()
            self.temporary_target_embeddings = [embedding.copy()]
            self.pose_coverage = {p: False for p in pose_service.cctv_required_poses()}
            logger.info("DIFFERENT_TARGET_SELECTED: Cleared previous gallery samples.")
        elif is_same_identity or gallery_service.samples:
            # Same target re-selected / re-acquired — KEEP existing gallery samples!
            self.temporary_target_embeddings.append(embedding.copy())
            logger.info("SAME_TARGET_REACQUIRED: Preserved %d existing gallery samples.", len(gallery_service.samples))
        else:
            self.temporary_target_embeddings = [embedding.copy()]
            self.pose_coverage = {p: False for p in pose_service.cctv_required_poses()}

        # Update centroid reference vector
        embs_arr = np.array(self.temporary_target_embeddings)
        mean_emb = np.mean(embs_arr, axis=0)
        self.temporary_target_centroid = mean_emb / (np.linalg.norm(mean_emb) + 1e-8)

        self.target_face_bbox = [float(v) for v in face.bbox]
        self.target_track_id = getattr(face, "track_id", None)  # internal continuity hint only
        self.locked_camera_id = camera_id
        self.target_locked = True
        self.target_state = "TARGET_LOCKED"
        self.capture_method = "CCTV"
        self.target_lost_since = None
        self.target_last_seen = time.time()
        self.last_target_similarity = 1.0

        capture_service.lock_face(camera_id=camera_id, internal_track_id=self.target_track_id)

        ret_enc, buf = cv2.imencode(".jpg", aligned)
        if ret_enc:
            self.target_thumbnail = "data:image/jpeg;base64," + base64.b64encode(buf).decode("utf-8")

        logger.info(
            "FACE_SELECTED camera=%s bbox=%s TARGET_LOCKED (samples preserved: %d)",
            camera_id,
            self.target_face_bbox,
            len(gallery_service.samples)
        )


        return {
            "status": "success",
            "message": "Face selected. Target locked.",
            "state": self.target_state,
            "target": self._target_payload(visible=True, identity_verified=True),
        }

    def unlock_target(self) -> Dict[str, Any]:
        self._reset_target_state()
        capture_service.unlock_track()
        logger.info("REG_TARGET_UNLOCKED")
        return {"status": "success", "message": "Target unlocked", "state": self.target_state}

    # ── Target association ───────────────────────────────────────────────────

    def _similarity_to_reference(self, embedding: np.ndarray) -> float:
        if self.temporary_target_centroid is None:
            return -1.0
        return float(np.dot(embedding, self.temporary_target_centroid))

    def _association_score(
        self,
        identity_sim: float,
        face_bbox: List[float],
        detection_conf: float,
        frame_shape: Tuple[int, int],
    ) -> float:
        """Identity-primary association score with spatial continuity support."""
        w_id = settings.REGISTRATION_IDENTITY_WEIGHT
        w_sp = settings.REGISTRATION_SPATIAL_WEIGHT
        w_cf = settings.REGISTRATION_CONFIDENCE_WEIGHT

        spatial = 0.0
        if self.target_face_bbox is not None:
            iou = _bbox_iou(face_bbox, self.target_face_bbox)
            dist = _bbox_center_distance_norm(
                face_bbox, self.target_face_bbox, (frame_shape[1], frame_shape[0])
            )
            spatial = 0.6 * iou + 0.4 * max(0.0, 1.0 - dist * 4.0)

        conf = max(0.0, min(1.0, float(detection_conf)))
        return float(w_id * identity_sim + w_sp * spatial + w_cf * conf)

    def _find_target_face(
        self, frame: np.ndarray, detected_faces: List[Any]
    ) -> Tuple[Optional[Any], Optional[np.ndarray], Optional[np.ndarray], float]:
        """
        Find the locked target among detected faces using embedding similarity
        as the primary signal. Spatial continuity is supporting only.
        Returns (face, aligned_crop, embedding, identity_similarity).
        """
        if self.temporary_target_centroid is None or not detected_faces:
            return None, None, None, -1.0

        best_face = None
        best_aligned = None
        best_emb = None
        best_score = -1.0
        best_sim = -1.0
        min_conf = settings.REGISTRATION_MIN_DETECTION_CONFIDENCE

        for face in detected_faces:
            conf = float(getattr(face, "score", 0.95))
            if conf < min_conf:
                continue
            landmarks = getattr(face, "landmarks", None)
            if landmarks is None:
                continue
            bbox = [float(v) for v in face.bbox]
            fw = bbox[2] - bbox[0]
            fh = bbox[3] - bbox[1]
            if fw < settings.REGISTRATION_MIN_FACE_WIDTH or fh < settings.REGISTRATION_MIN_FACE_HEIGHT:
                continue

            aligned = embedding_service.generate_aligned_crop(frame, landmarks)
            if aligned is None or aligned.size == 0:
                continue
            emb = embedding_service.extract_embedding(aligned)
            if emb is None:
                continue

            sim = self._similarity_to_reference(emb)
            score = self._association_score(sim, bbox, conf, frame.shape[:2])
            if score > best_score:
                best_score = score
                best_sim = sim
                best_face = face
                best_aligned = aligned
                best_emb = emb

        # Identity confidence gate — never accept spatial-only matches
        threshold = (
            settings.REGISTRATION_TARGET_REACQUIRE_THRESHOLD
            if self.target_state == "TARGET_LOST"
            else settings.REGISTRATION_TARGET_SIMILARITY_THRESHOLD
        )
        if best_face is None or best_sim < threshold:
            return None, None, None, best_sim

        return best_face, best_aligned, best_emb, best_sim

    def _maybe_update_reference(self, embedding: np.ndarray, quality_passed: bool, similarity: float):
        """Conservative reference template update — only high-confidence matches."""
        max_refs = settings.REGISTRATION_MAX_REFERENCE_EMBEDDINGS
        if not quality_passed:
            return
        if similarity < settings.REGISTRATION_TARGET_REACQUIRE_THRESHOLD:
            return
        if len(self.temporary_target_embeddings) >= max_refs:
            return
        self.temporary_target_embeddings.append(embedding.copy())
        mean_vec = np.mean(self.temporary_target_embeddings, axis=0)
        self.temporary_target_centroid = mean_vec / (np.linalg.norm(mean_vec) + 1e-8)

    # ── Frame processing ─────────────────────────────────────────────────────

    def process_frame(
        self, frame: np.ndarray, detected_faces: List[DetectedFace], method: str = "WEBCAM"
    ) -> Dict[str, Any]:
        self.capture_method = method

        if not self.is_registering:
            self.is_registering = True
            if not self.person_id:
                self.person_id = f"P_{int(datetime.utcnow().timestamp())}"
                self.person_name = "New Registration"

        if method == "CCTV":
            return self._process_cctv_frame(frame, detected_faces)

        return self._process_webcam_frame(frame, detected_faces, method)

    def _waiting_payload(self, face_count: int) -> Dict[str, Any]:
        return {
            "is_registering": True,
            "state": "WAITING_FOR_SELECTION",
            "target": None,
            "samples_collected": len(gallery_service.samples),
            "target_samples": self.target_samples,
            "min_samples": settings.REGISTRATION_MIN_SAMPLES,
            "max_samples": settings.REGISTRATION_MAX_SAMPLES,
            "progress_percent": int(
                min(1.0, len(gallery_service.samples) / max(1, self.target_samples)) * 100
            ),
            "pose_coverage": dict(self.pose_coverage),
            "ai_assistant": {
                "face_detected": face_count > 0,
                "centered": False,
                "sharp": False,
                "lighting": False,
                "eyes_visible": False,
                "identity_verified": False,
                "guidance": "Click a face to begin registration",
                "status": "Awaiting face selection...",
            },
            "gallery": gallery_service.get_formatted_gallery(),
        }

    def _lost_payload(self) -> Dict[str, Any]:
        return {
            "is_registering": True,
            "state": "TARGET_LOST",
            "target": self._target_payload(visible=False, identity_verified=False),
            "samples_collected": len(gallery_service.samples),
            "target_samples": self.target_samples,
            "min_samples": settings.REGISTRATION_MIN_SAMPLES,
            "max_samples": settings.REGISTRATION_MAX_SAMPLES,
            "progress_percent": int(
                min(1.0, len(gallery_service.samples) / max(1, self.target_samples)) * 100
            ),
            "pose_coverage": dict(self.pose_coverage),
            "ai_assistant": {
                "face_detected": False,
                "centered": False,
                "sharp": False,
                "lighting": False,
                "eyes_visible": False,
                "identity_verified": False,
                "guidance": "Waiting for the selected face...",
                "status": "Target temporarily lost. Capture paused.",
            },
            "gallery": gallery_service.get_formatted_gallery(),
        }

    def _target_payload(self, visible: bool, identity_verified: bool) -> Dict[str, Any]:
        return {
            "camera_id": self.locked_camera_id,
            "visible": visible,
            "identity_verified": identity_verified,
            "bbox": self.target_face_bbox,
            "thumbnail": self.target_thumbnail,
            "similarity": round(self.last_target_similarity, 3),
        }

    def _process_cctv_frame(self, frame: np.ndarray, detected_faces: List[Any]) -> Dict[str, Any]:
        # Throttle expensive registration work
        now = time.time()
        min_interval = 1.0 / max(1, settings.REGISTRATION_PROCESSING_FPS)
        if (now - self._last_process_ts) < min_interval and self.target_locked:
            # Still return current status quickly without re-embedding everyone
            pass
        self._last_process_ts = now

        # 1. Waiting for operator to click a face
        if not self.target_locked or self.temporary_target_centroid is None:
            self.target_state = "WAITING_FOR_SELECTION"
            return self._waiting_payload(len(detected_faces))

        # 2. Associate target via identity similarity (primary)
        target_face, aligned_crop, embedding, identity_sim = self._find_target_face(frame, detected_faces)
        self.last_target_similarity = float(identity_sim) if identity_sim is not None else -1.0

        if target_face is None:
            if self.target_lost_since is None:
                self.target_lost_since = now
                logger.info("TARGET_LOST_BUFFERING camera=%s similarity=%.3f", self.locked_camera_id, identity_sim)

            # Allow 3.5 seconds grace period before marking target LOST
            grace_sec = 3.5
            if (now - self.target_lost_since) > grace_sec:
                self.target_state = "TARGET_LOST"
                return self._lost_payload()
            else:
                # Retain TARGET_LOCKED status during brief head turns/occlusions
                return {
                    "is_registering": True,
                    "state": "TARGET_LOCKED",
                    "target": self._target_payload(visible=False, identity_verified=False),
                    "samples_collected": len(gallery_service.samples),
                    "target_samples": self.target_samples,
                    "min_samples": settings.REGISTRATION_MIN_SAMPLES,
                    "max_samples": settings.REGISTRATION_MAX_SAMPLES,
                    "progress_percent": int(
                        min(1.0, len(gallery_service.samples) / max(1, self.target_samples)) * 100
                    ),
                    "pose_coverage": dict(self.pose_coverage),
                    "ai_assistant": {
                        "face_detected": False,
                        "centered": False,
                        "sharp": False,
                        "lighting": False,
                        "eyes_visible": False,
                        "identity_verified": False,
                        "guidance": "Tracking target face... Hold steady",
                        "status": "Tracking target face...",
                    },
                    "gallery": gallery_service.get_formatted_gallery(),
                }

        # Reacquired or still locked
        was_lost = self.target_state == "TARGET_LOST"
        if was_lost:
            logger.info(
                "TARGET_REACQUIRED camera=%s similarity=%.3f (retaining %d gallery samples)",
                self.locked_camera_id,
                identity_sim,
                len(gallery_service.samples)
            )

        self.target_lost_since = None
        new_bbox = [float(v) for v in target_face.bbox]
        if self.target_face_bbox is not None and len(self.target_face_bbox) == 4:
            alpha = 0.65  # 65% new, 35% previous for smooth visual continuity
            self.target_face_bbox = [
                alpha * new_bbox[i] + (1.0 - alpha) * self.target_face_bbox[i]
                for i in range(4)
            ]
        else:
            self.target_face_bbox = new_bbox

        self.target_track_id = getattr(target_face, "track_id", self.target_track_id)
        self.target_last_seen = now
        self.target_state = "TARGET_LOCKED"


        # 3. Quality gates (only for selected target)
        quality_res = quality_service.evaluate_quality(
            frame, target_face.bbox, target_face.landmarks, method="CCTV"
        )
        checks = quality_res["checks"]
        metrics = quality_res.get("metrics", {})

        # 4. Identity verification gate
        identity_verified = identity_sim >= settings.REGISTRATION_TARGET_SIMILARITY_THRESHOLD
        identity_reason = None
        if settings.REGISTRATION_IDENTITY_GUARD_ENABLED and not identity_verified:
            identity_reason = (
                f"Identity mismatch (similarity={identity_sim:.3f} "
                f"< threshold={settings.REGISTRATION_TARGET_SIMILARITY_THRESHOLD})"
            )
            logger.debug("FRAME_REJECTED reason=identity_mismatch similarity=%.3f", identity_sim)

        # 5. Conservative reference update
        if embedding is not None and identity_verified:
            self._maybe_update_reference(embedding, quality_res["passed"], identity_sim)

        # 6. Pose
        yaw, pitch, pose_bin = pose_service.calculate_pose_angles(target_face.landmarks)
        pose_bin = pose_service.normalize_cctv_pose(pose_bin, yaw, pitch)
        guidance_msg, next_needed_pose = pose_service.get_pose_guidance(
            gallery_service.get_collected_poses(), mode="CCTV"
        )

        # 7. Duplicate filter
        is_duplicate = False
        if embedding is not None:
            dup_thresh = settings.REGISTRATION_DUPLICATE_SIMILARITY_THRESHOLD
            for sample in gallery_service.samples:
                if float(np.dot(embedding, sample["embedding"])) >= dup_thresh:
                    is_duplicate = True
                    break

        cooldown_passed = (now - self.last_capture_time) >= settings.REGISTRATION_CAPTURE_INTERVAL
        collected_poses = set(gallery_service.get_collected_poses())
        is_new_pose = pose_bin not in collected_poses
        current_count = len(gallery_service.samples)
        under_max = current_count < settings.REGISTRATION_MAX_SAMPLES

        auto_captured = False
        capture_rejected_reason = None

        if quality_res["passed"] and identity_verified and under_max:
            if is_duplicate:
                capture_rejected_reason = "duplicate"
                logger.debug("FRAME_REJECTED reason=duplicate")
            elif not cooldown_passed:
                capture_rejected_reason = "capture_cooldown"
            elif is_new_pose or current_count < self.target_samples:
                if aligned_crop is not None and embedding is not None:
                    gallery_service.add_sample(
                        frame=frame,
                        aligned_crop=aligned_crop,
                        embedding=embedding,
                        quality_score=quality_res["score"],
                        pose_bin=pose_bin,
                        yaw=yaw,
                        pitch=pitch,
                        method="CCTV",
                    )
                    auto_captured = True
                    self.last_capture_time = now
                    self.pose_coverage[pose_bin] = True
                    self.target_state = "CAPTURING"
                    logger.info(
                        "SAMPLE_ACCEPTED pose=%s quality=%.2f similarity=%.3f count=%d",
                        pose_bin,
                        quality_res["score"],
                        identity_sim,
                        len(gallery_service.samples),
                    )
        elif not quality_res["passed"]:
            reason = (quality_res.get("reasons") or ["quality"])[0]
            logger.debug("FRAME_REJECTED reason=%s", reason)
            capture_rejected_reason = reason
        elif not identity_verified:
            capture_rejected_reason = identity_reason

        current_count = len(gallery_service.samples)
        progress_pct = int(min(1.0, current_count / max(1, self.target_samples)) * 100)

        # Pose coverage snapshot
        for p in pose_service.cctv_required_poses():
            self.pose_coverage[p] = p in set(gallery_service.get_collected_poses())

        ready = (
            current_count >= settings.REGISTRATION_MIN_SAMPLES
            and pose_service.has_minimum_cctv_coverage(gallery_service.get_collected_poses())
        ) or current_count >= self.target_samples

        if ready and current_count >= settings.REGISTRATION_MIN_SAMPLES:
            self.target_state = "READY_FOR_REVIEW"
            status_text = "Enough quality samples collected. Ready to review."
            logger.info("REGISTRATION_READY samples=%d", current_count)
        elif auto_captured:
            status_text = f"Captured {pose_bin.replace('_', ' ').title()} ({current_count}/{self.target_samples})"
            self.target_state = "CAPTURING"
        elif not quality_res["passed"]:
            status_text = quality_res["reasons"][0] if quality_res["reasons"] else "Adjust position"
        elif not identity_verified:
            status_text = "Target identity could not be verified"
        elif is_duplicate:
            status_text = "Near-duplicate ignored. Slightly change pose."
        else:
            status_text = guidance_msg

        if not self.target_thumbnail and aligned_crop is not None:
            ret_enc, buf = cv2.imencode(".jpg", aligned_crop)
            if ret_enc:
                self.target_thumbnail = "data:image/jpeg;base64," + base64.b64encode(buf).decode("utf-8")

        ai_assistant_res = {
            "face_detected": checks.get("detected", True),
            "centered": checks.get("centered", False),
            "sharp": checks.get("sharp", False),
            "lighting": checks.get("lighting", False),
            "eyes_visible": checks.get("eyes_visible", False),
            "face_size_ok": checks.get("face_size", True),
            "identity_verified": identity_verified,
            "current_pose": pose_bin,
            "next_needed_pose": next_needed_pose,
            "guidance": guidance_msg if next_needed_pose else status_text,
            "status": status_text,
            "quality_score": quality_res["score"],
        }
        self.last_ai_assistant = ai_assistant_res

        return {
            "is_registering": True,
            "state": self.target_state,
            "target": self._target_payload(visible=True, identity_verified=identity_verified),
            "quality": {
                "passed": quality_res["passed"],
                "score": quality_res["score"],
                "sharp": checks.get("sharp", False),
                "lighting": checks.get("lighting", False),
                "eyes_visible": checks.get("eyes_visible", False),
                "centered": checks.get("centered", False),
                "face_size": checks.get("face_size", True),
                "metrics": metrics,
            },
            "pose": {
                "current": pose_bin,
                "required": next_needed_pose,
                "accepted": auto_captured,
                "coverage": dict(self.pose_coverage),
            },
            "pose_coverage": dict(self.pose_coverage),
            "capture": {
                "accepted": auto_captured,
                "sample_id": gallery_service.samples[-1]["id"] if auto_captured and gallery_service.samples else None,
                "reason": capture_rejected_reason,
            },
            "samples_collected": current_count,
            "target_samples": self.target_samples,
            "min_samples": settings.REGISTRATION_MIN_SAMPLES,
            "max_samples": settings.REGISTRATION_MAX_SAMPLES,
            "progress_percent": progress_pct,
            "ai_assistant": ai_assistant_res,
            "gallery": gallery_service.get_formatted_gallery(),
        }

    def _process_webcam_frame(
        self, frame: np.ndarray, detected_faces: List[Any], method: str
    ) -> Dict[str, Any]:
        target_face = capture_service.filter_target_face(detected_faces)

        if len(detected_faces) == 0 or target_face is None:
            guidance_msg, _ = pose_service.get_pose_guidance(gallery_service.get_collected_poses())
            return {
                "is_registering": True,
                "samples_collected": len(gallery_service.samples),
                "target_samples": self.target_samples,
                "progress_percent": int(
                    (len(gallery_service.samples) / max(1, self.target_samples)) * 100
                ),
                "ai_assistant": {
                    "face_detected": False,
                    "centered": False,
                    "sharp": False,
                    "lighting": False,
                    "eyes_visible": False,
                    "guidance": "Please position yourself in front of the camera",
                    "status": "Searching for face...",
                },
                "gallery": gallery_service.get_formatted_gallery(),
            }

        if len(detected_faces) > 1 and capture_service.locked_track_id is None:
            return {
                "is_registering": True,
                "samples_collected": len(gallery_service.samples),
                "target_samples": self.target_samples,
                "progress_percent": int(
                    (len(gallery_service.samples) / max(1, self.target_samples)) * 100
                ),
                "ai_assistant": {
                    "face_detected": True,
                    "centered": False,
                    "sharp": False,
                    "lighting": False,
                    "eyes_visible": False,
                    "guidance": "Multiple faces detected. Please ensure only one person is visible.",
                    "status": "Multiple faces detected",
                },
                "gallery": gallery_service.get_formatted_gallery(),
            }

        quality_res = quality_service.evaluate_quality(
            frame, target_face.bbox, target_face.landmarks, method=method
        )
        checks = quality_res["checks"]
        yaw, pitch, pose_bin = pose_service.calculate_pose_angles(target_face.landmarks)
        guidance_msg, next_needed_pose = pose_service.get_pose_guidance(
            gallery_service.get_collected_poses()
        )

        collected_poses = gallery_service.get_collected_poses()
        is_new_pose = pose_bin not in collected_poses
        auto_captured = False

        if quality_res["passed"] and (
            is_new_pose or len(gallery_service.samples) < self.target_samples
        ):
            aligned_crop = embedding_service.generate_aligned_crop(frame, target_face.landmarks)
            if aligned_crop is not None:
                embedding = embedding_service.extract_embedding(aligned_crop)
                if embedding is not None:
                    # Duplicate gate for webcam too
                    is_dup = any(
                        float(np.dot(embedding, s["embedding"]))
                        >= settings.REGISTRATION_DUPLICATE_SIMILARITY_THRESHOLD
                        for s in gallery_service.samples
                    )
                    if not is_dup and len(gallery_service.samples) < settings.REGISTRATION_MAX_SAMPLES:
                        gallery_service.add_sample(
                            frame=frame,
                            aligned_crop=aligned_crop,
                            embedding=embedding,
                            quality_score=quality_res["score"],
                            pose_bin=pose_bin,
                            yaw=yaw,
                            pitch=pitch,
                            method=method,
                        )
                        auto_captured = True

        current_count = len(gallery_service.samples)
        progress_pct = int(min(1.0, current_count / max(1, self.target_samples)) * 100)

        if auto_captured:
            status_text = f"Captured {pose_bin} pose sample! ({current_count}/{self.target_samples})"
        elif not quality_res["passed"]:
            status_text = quality_res["reasons"][0] if quality_res["reasons"] else "Adjust position"
        else:
            status_text = f"{pose_bin} pose already captured. {guidance_msg}"

        ai_assistant_res = {
            "face_detected": checks["detected"],
            "centered": checks["centered"],
            "sharp": checks["sharp"],
            "lighting": checks["lighting"],
            "eyes_visible": checks["eyes_visible"],
            "current_pose": pose_bin,
            "next_needed_pose": next_needed_pose,
            "guidance": guidance_msg,
            "status": status_text,
            "quality_score": quality_res["score"],
        }
        self.last_ai_assistant = ai_assistant_res

        return {
            "is_registering": True,
            "samples_collected": current_count,
            "target_samples": self.target_samples,
            "progress_percent": progress_pct,
            "auto_captured": auto_captured,
            "ai_assistant": ai_assistant_res,
            "gallery": gallery_service.get_formatted_gallery(),
        }

    def remove_sample(self, sample_id: str) -> Dict[str, Any]:
        removed = gallery_service.remove_sample(sample_id)
        for p in pose_service.cctv_required_poses():
            self.pose_coverage[p] = p in set(gallery_service.get_collected_poses())
        return {
            "status": "success" if removed else "error",
            "message": "Sample removed" if removed else "Sample ID not found",
            "gallery": gallery_service.get_formatted_gallery(),
            "pose_coverage": dict(self.pose_coverage),
        }

    def assess_duplicate_status(self) -> Dict[str, Any]:
        """
        Non-destructive duplicate assessment for gallery review warning UI.
        Does not write to DB or FAISS.
        """
        if not self.is_registering or not self.person_id:
            return {
                "level": "none",
                "matched_person_id": None,
                "matched_name": None,
                "similarity": 0.0,
                "error": "No active registration session",
            }

        if len(gallery_service.samples) == 0:
            return {
                "level": "none",
                "matched_person_id": None,
                "matched_name": None,
                "similarity": 0.0,
                "error": "Gallery is empty",
            }

        all_embeddings = [s["embedding"] for s in gallery_service.samples]
        return duplicate_service.assess_duplicate(
            all_embeddings,
            current_person_id=self.person_id,
        )

    def commit_registration(self) -> Tuple[bool, str, Dict[str, Any]]:
        if not self.is_registering or not self.person_id:
            return False, "No active registration session to commit.", {}

        if len(gallery_service.samples) == 0:
            return False, "Gallery is empty. Please capture face images before submitting.", {}

        if len(gallery_service.samples) < settings.REGISTRATION_MIN_SAMPLES:
            return (
                False,
                f"Need at least {settings.REGISTRATION_MIN_SAMPLES} quality samples "
                f"(have {len(gallery_service.samples)}).",
                {},
            )

        person_id = self.person_id
        person_name = self.person_name

        all_embeddings = [s["embedding"] for s in gallery_service.samples]
        is_dup, dup_info = duplicate_service.check_duplicate(all_embeddings, current_person_id=person_id)
        if is_dup and dup_info:
            return (
                False,
                f"Duplicate Face Alert: Matching face already registered for "
                f"'{dup_info['matched_name']}' (ID: {dup_info['matched_person_id']}).",
                {},
            )

        db = SessionLocal()
        try:
            existing_person = db.query(PersonModel).filter(PersonModel.person_id == person_id).first()
            if existing_person:
                existing_person.first_name = self.person_info.get("first_name")
                existing_person.last_name = self.person_info.get("last_name")
                existing_person.name = person_name
                existing_person.department = self.person_info.get("department")
                existing_person.role = self.person_info.get("role")
                existing_person.phone = self.person_info.get("phone")
                existing_person.email = self.person_info.get("email")
                existing_person.notes = self.person_info.get("notes")
                existing_person.gallery_version = (existing_person.gallery_version or 1) + 1
                person_model = existing_person
            else:
                person_model = PersonModel(
                    person_id=person_id,
                    first_name=self.person_info.get("first_name"),
                    last_name=self.person_info.get("last_name"),
                    name=person_name,
                    department=self.person_info.get("department"),
                    role=self.person_info.get("role"),
                    phone=self.person_info.get("phone"),
                    email=self.person_info.get("email"),
                    notes=self.person_info.get("notes"),
                    gallery_version=1,
                    registered_at=datetime.utcnow(),
                )
                db.add(person_model)

            db.commit()

            embeddings_matrix = np.array(all_embeddings, dtype=np.float32)
            faiss_ids = faiss_manager.add_vectors(person_id, person_name, embeddings_matrix)

            sample_count = len(gallery_service.samples)
            for idx, (sample, f_id) in enumerate(zip(gallery_service.samples, faiss_ids)):
                file_name = f"sample_{idx + 1}_{sample['pose_bin'].lower()}.jpg"
                saved_path = storage_service.save_face_image(person_id, file_name, sample["aligned"])

                img_rec = PersonImageModel(
                    person_id=person_id,
                    image_path=saved_path,
                    quality_score=sample["quality_score"],
                    pose_bin=sample["pose_bin"],
                    yaw=sample["yaw"],
                    pitch=sample["pitch"],
                    gallery_version=person_model.gallery_version,
                )
                db.add(img_rec)
                db.flush()

                emb_rec = EmbeddingModel(
                    person_id=person_id,
                    faiss_id=f_id,
                    image_id=img_rec.id,
                    image_path=saved_path,
                    gallery_version=person_model.gallery_version,
                )
                db.add(emb_rec)

            db.commit()

            audit = AuditLogModel(
                action="REGISTER_PERSON",
                person_id=person_id,
                details=f"Registered {person_name} with {sample_count} gallery face samples.",
            )
            db.add(audit)
            db.commit()

            self.is_registering = False
            self.target_state = "COMPLETED"
            result_data = {
                "person_id": person_id,
                "name": person_name,
                "samples_count": sample_count,
                "gallery_version": person_model.gallery_version,
            }
            gallery_service.clear()
            capture_service.unlock_track()
            logger.info("REGISTRATION_COMPLETED person=%s samples=%d", person_id, sample_count)
            return True, f"Successfully registered {person_name} with {sample_count} quality samples!", result_data

        except Exception as e:
            db.rollback()
            logger.error("Commit registration failed: %s", e, exc_info=True)
            return False, f"Database error during registration commit: {str(e)}", {}
        finally:
            db.close()


registration_engine = RegistrationEngine()
