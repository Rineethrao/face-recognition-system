import time
import logging
import threading
import numpy as np
from queue import Queue, Empty
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import SessionLocal
from app.visitors.models import VisitorModel
from app.visitors.face_quality import visitor_quality_evaluator, FaceQualityResult
from app.visitors.visitor_repository import visitor_repository, get_operational_date_key
from app.visitors.visitor_gallery import visitor_gallery
from app.visitors.identity_resolver import visitor_identity_resolver, IdentityResolverResult
from app.visitors.admission_controller import admission_controller
from app.visitors.sighting_manager import sighting_manager

logger = logging.getLogger(__name__)


class VisitorResolutionResult:
    def __init__(
        self,
        is_resolved: bool,
        visitor_id: Optional[int] = None,
        visitor_code: str = "Identifying...",
        similarity: float = 0.0,
        decision: str = "COLLECTING",  # 'EXISTING', 'PENDING', 'COLLECTING', 'NEW'
        primary_snapshot_path: Optional[str] = None,
        reason: str = ""
    ):
        self.is_resolved = is_resolved
        self.visitor_id = visitor_id
        self.visitor_code = visitor_code
        self.similarity = similarity
        self.decision = decision
        self.primary_snapshot_path = primary_snapshot_path
        self.reason = reason


class PersistenceWorker(threading.Thread):
    """
    Dedicated Background Worker with a Bounded Queue to handle DB writes,
    image disk saving, and sighting sessions with backpressure safety.
    """
    def __init__(self, queue: Queue):
        super().__init__(name="VisitorPersistenceWorker", daemon=True)
        self.queue = queue
        self.running = True

    def run(self):
        while self.running:
            try:
                task = self.queue.get(timeout=1.0)
                if task is None:
                    continue
                func, args, kwargs = task
                try:
                    func(*args, **kwargs)
                except Exception as err:
                    logger.error(f"[PersistenceWorker] Error executing task {func.__name__}: {err}", exc_info=True)
                finally:
                    self.queue.task_done()
            except Empty:
                continue
            except Exception as e:
                logger.error(f"[PersistenceWorker] Unexpected queue exception: {e}")


class VisitorManager:
    """
    Facade Orchestrator for Unregistered Visitor Re-Identification Subsystem.
    Enforces track identity locking, face quality gating, strict admission control,
    bounded persistence queuing, and cross-camera track continuity.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.creation_lock = threading.RLock()
        # (camera_id, str_track_id) -> locked identity dict
        self.track_identity_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # (camera_id, str_track_id) -> observation buffer
        self.track_observation_buffer: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.initialized_date_key: str = ""

        # Bounded Queue (max 1000 tasks) + dedicated worker for backpressure safety
        self.persistence_queue: Queue = Queue(maxsize=1000)
        self.persistence_worker = PersistenceWorker(self.persistence_queue)
        self.persistence_worker.start()

    def ensure_gallery_loaded(self, db: Session):
        """Ensures active in-memory visitor vector gallery is loaded."""
        with self.lock:
            if not self.initialized_date_key:
                visitor_gallery.load_global_gallery(db)
                self.initialized_date_key = get_operational_date_key()

    def _enqueue_persistence_task(self, func, *args, **kwargs):
        """Enqueue persistence task into bounded queue without blocking video pipeline."""
        try:
            self.persistence_queue.put_nowait((func, args, kwargs))
        except Exception:
            logger.warning(f"[VisitorManager] Persistence queue full (max 1000 tasks). Dropping non-critical write.")

    def _async_save_new_visitor(
        self,
        visitor_id: int,
        visitor_code: str,
        camera_id: str,
        str_track_id: str,
        best_sample: Dict[str, Any],
        extra_samples: List[Dict[str, Any]]
    ):
        """Background task: persists visitor record, face samples, snapshot JPEGs, and sighting session."""
        db = SessionLocal()
        try:
            # 1. Update primary snapshot path if crop exists and meets quality gate
            if best_sample.get("crop") is not None and best_sample["crop"].size > 0:
                v_model = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
                if v_model:
                    from app.visitors.visitor_repository import get_visitor_folder_paths
                    c_date = v_model.created_date or v_model.date_key
                    v_dir, _, _ = get_visitor_folder_paths(c_date, visitor_code)
                    snapshot_full_path = v_dir / "primary_avatar.jpg"
                    try:
                        import cv2
                        cv2.imwrite(str(snapshot_full_path), best_sample["crop"])
                        v_model.primary_snapshot_path = str(snapshot_full_path)
                        db.commit()

                    except Exception as img_err:
                        logger.warning(f"[VisitorManager:Async] Failed to save primary snapshot: {img_err}")


            # 2. Add face samples to DB
            visitor_repository.add_face_sample(
                db=db,
                visitor_id=visitor_id,
                embedding=best_sample["embedding"],
                camera_id=camera_id,
                quality_score=best_sample["quality_score"],
                yaw=best_sample["yaw"],
                pitch=best_sample["pitch"],
                blur_score=best_sample["blur_score"],
                crop_img=best_sample.get("crop")
            )

            for extra_s in extra_samples:
                visitor_repository.add_face_sample(
                    db=db,
                    visitor_id=visitor_id,
                    embedding=extra_s["embedding"],
                    camera_id=camera_id,
                    quality_score=extra_s["quality_score"],
                    yaw=extra_s["yaw"],
                    pitch=extra_s["pitch"],
                    blur_score=extra_s["blur_score"],
                    crop_img=extra_s.get("crop")
                )

            # 3. Record Initial Sighting Session
            sighting_manager.record_sighting(
                db=db,
                visitor_id=visitor_id,
                camera_id=camera_id,
                track_id=str_track_id,
                best_sim=1.0,
                second_best_sim=0.0,
                margin=1.0,
                confidence=1.0,
                crop_img=best_sample.get("crop")
            )
            logger.debug(f"[VisitorManager:Async] Persisted visitor {visitor_code} to database & disk successfully.")
        except Exception as err:
            logger.error(f"[VisitorManager:Async] Error persisting visitor {visitor_code}: {err}", exc_info=True)
        finally:
            db.close()

    def _async_save_sighting(
        self,
        visitor_id: int,
        camera_id: str,
        str_track_id: str,
        best_sim: float,
        second_best_sim: float,
        margin: float,
        confidence: float,
        crop_img: Optional[np.ndarray],
        embedding: np.ndarray,
        quality_res: FaceQualityResult,
        visitor_code: str
    ):
        """Background task: updates sighting session and adds sample to DB if quality is ENROLLMENT or higher."""
        db = SessionLocal()
        try:
            sighting_manager.record_sighting(
                db=db,
                visitor_id=visitor_id,
                camera_id=camera_id,
                track_id=str_track_id,
                best_sim=best_sim,
                second_best_sim=second_best_sim,
                margin=margin,
                confidence=confidence,
                crop_img=crop_img
            )

            if quality_res.usable_for_gallery and embedding is not None:
                # Visitor Profile Guard Validation
                is_valid, guard_reason = visitor_gallery.validate_profile_sample(visitor_id, embedding)
                if not is_valid:
                    logger.debug(f"[ProfileGuard:{visitor_code}] Discarded sample persistence: {guard_reason}")
                else:
                    sample_rec = visitor_repository.add_face_sample(
                        db=db,
                        visitor_id=visitor_id,
                        embedding=embedding,
                        camera_id=camera_id,
                        quality_score=quality_res.quality_score,
                        yaw=quality_res.pose_yaw,
                        pitch=quality_res.pose_pitch,
                        blur_score=quality_res.blur_score,
                        crop_img=crop_img
                    )
                    visitor_gallery.add_visitor_sample(
                        visitor_id=visitor_id,
                        visitor_code=visitor_code,
                        embedding=embedding,
                        snapshot_path=sample_rec.snapshot_path
                    )
        except Exception as err:
            logger.error(f"[VisitorManager:Async] Error updating sighting for visitor {visitor_id}: {err}")
        finally:
            db.close()

    def resolve_unregistered_track(
        self,
        db: Session,
        camera_id: str,
        track_id: Any,
        embedding: Optional[np.ndarray],
        quality_res: Any = None,
        crop_img: Optional[np.ndarray] = None,
        **kwargs
    ) -> VisitorResolutionResult:
        """
        Orchestrates identity resolution for an unrecognized person track.
        Applies track identity locking, face quality filtering, observation buffering,
        strict admission control, and bounded persistence.
        """
        if quality_res is None and "quality_eval" in kwargs:
            quality_res = kwargs["quality_eval"]

        if isinstance(quality_res, dict):
            # Convert dict evaluation to FaceQualityResult with full enrollment gates
            from app.visitors.face_quality import FaceQualityResult
            q_score = float(quality_res.get("quality_score", 0.0))
            passed = bool(quality_res.get("passed", True))
            yaw = float(quality_res.get("pose_yaw", 0.0))
            pitch = float(quality_res.get("pose_pitch", 0.0))
            blur = float(quality_res.get("blur_score", 0.0))
            fw = float(quality_res.get("face_width", quality_res.get("face_size", 50.0)))
            fh = float(quality_res.get("face_height", fw))
            max_yaw = getattr(settings, 'VISITOR_MAX_ABS_YAW', 0.22)
            max_pitch = getattr(settings, 'VISITOR_MAX_ABS_PITCH', 0.18)
            min_blur = getattr(settings, 'VISITOR_MIN_BLUR_SCORE', 25.0)
            max_blur = getattr(settings, 'VISITOR_MAX_BLUR_SCORE', 800.0)
            min_w = getattr(settings, 'VISITOR_MIN_FACE_WIDTH', 40)
            pose_ok = abs(yaw) <= max_yaw and abs(pitch) <= max_pitch
            blur_ok = min_blur <= blur <= max_blur
            size_ok = fw >= min_w and fh >= min_w
            usable = passed and size_ok and q_score >= getattr(settings, 'VISITOR_QUALITY_MATCHING_THRESH', 0.42)
            usable_new = (
                usable and pose_ok and blur_ok and
                fw >= getattr(settings, 'VISITOR_ENROLLMENT_MIN_FACE_WIDTH', 50) and
                q_score >= getattr(settings, 'VISITOR_QUALITY_ENROLLMENT_THRESH', 0.62)
            )
            quality_res = FaceQualityResult(
                quality_score=q_score,
                quality_tier="ENROLLMENT" if usable_new else ("MATCHING" if usable else "POOR"),
                usable_for_matching=usable,
                usable_for_new_identity=usable_new,
                usable_for_gallery=usable_new,
                usable_for_primary_avatar=usable_new and q_score >= getattr(settings, 'VISITOR_QUALITY_AVATAR_THRESH', 0.70),
                face_width=fw,
                face_height=fh,
                blur_score=blur,
                brightness=float(quality_res.get("brightness", 128.0)),
                pose_yaw=yaw,
                pose_pitch=pitch,
                aligned_crop=quality_res.get("aligned_crop", crop_img),
                passed_basic_quality=passed,
                structure_score=float(quality_res.get("structure_score", 0.0)),
                det_score=float(quality_res.get("det_score", 1.0)),
                eye_distance=float(quality_res.get("eye_distance", 0.0)),
            )


        t_start = time.perf_counter()
        str_track_id = str(track_id)
        cache_key = (camera_id, str_track_id)
        now = time.time()

        with self.lock:
            self.ensure_gallery_loaded(db)

            # 1. PERSON-TRACK IDENTITY LOCK CHECK (RULE 1: Preservation on Poor / Missing Face)
            if cache_key in self.track_identity_cache:
                cached = self.track_identity_cache[cache_key]
                cached["last_seen"] = now

                # If face quality is POOR or embedding missing, DO NOT re-recognize, but KEEP locked identity!
                if not quality_res.usable_for_matching or embedding is None:
                    return VisitorResolutionResult(
                        is_resolved=True,
                        visitor_id=cached["visitor_id"],
                        visitor_code=cached["visitor_code"],
                        similarity=cached["similarity"],
                        decision="EXISTING",
                        primary_snapshot_path=cached.get("primary_snapshot_path"),
                        reason="Identity locked to person track (poor/missing face frame preserved)"
                    )

                # ByteTrack Identity-Switch Protection: Verify continuous embedding consistency
                conflict_thresh = getattr(settings, 'TRACK_CONFLICT_THRESHOLD', 0.35)
                v_embs = visitor_gallery.gallery_embeddings.get(cached["visitor_id"], [])
                if v_embs and embedding is not None:
                    from app.core.utils import l2_normalize
                    q_norm = l2_normalize(embedding)
                    track_sims = [float(np.dot(q_norm, g_emb.T)) for g_emb in v_embs]
                    max_track_sim = max(track_sims) if track_sims else 1.0

                    if max_track_sim < conflict_thresh:
                        logger.warning(
                            f"[IDENTITY_CONFLICT] Track {str_track_id} on {camera_id} embedding similarity "
                            f"{max_track_sim:.3f} < {conflict_thresh} relative to locked {cached['visitor_code']}. "
                            f"ByteTrack switch detected! Purging lock for re-evaluation."
                        )
                        del self.track_identity_cache[cache_key]
                        # Proceed to unlocked resolution flow below
                    else:
                        # Async heartbeat update every 5 seconds for sightings
                        if now - cached.get("last_sighting_heartbeat", 0) > 5.0:
                            cached["last_sighting_heartbeat"] = now
                            self._enqueue_persistence_task(
                                self._async_save_sighting,
                                cached["visitor_id"], camera_id, str_track_id,
                                cached["similarity"], cached.get("second_best_sim", 0.0),
                                cached.get("margin", 0.0), cached.get("confidence", 0.0),
                                crop_img, embedding, quality_res, cached["visitor_code"]
                            )

                        return VisitorResolutionResult(
                            is_resolved=True,
                            visitor_id=cached["visitor_id"],
                            visitor_code=cached["visitor_code"],
                            similarity=cached["similarity"],
                            decision="EXISTING",
                            primary_snapshot_path=cached.get("primary_snapshot_path"),
                            reason="Identity locked to active track"
                        )
                else:
                    return VisitorResolutionResult(
                        is_resolved=True,
                        visitor_id=cached["visitor_id"],
                        visitor_code=cached["visitor_code"],
                        similarity=cached["similarity"],
                        decision="EXISTING",
                        primary_snapshot_path=cached.get("primary_snapshot_path"),
                        reason="Identity locked to active track"
                    )

            # 2. POOR FACE QUALITY REJECTION FOR UNLOCKED TRACKS
            # If track has no identity locked yet and face quality is POOR, DO NOT search or create!
            if not quality_res.usable_for_matching or embedding is None:
                return VisitorResolutionResult(
                    is_resolved=False,
                    visitor_code="Identifying...",
                    similarity=0.0,
                    decision="COLLECTING",
                    reason=f"Face quality {quality_res.quality_tier} unusable for matching"
                )

            # 3. BUFFER OBSERVATION FOR UNRESOLVED TRACK
            if cache_key not in self.track_observation_buffer:
                found_prev = None
                for (prev_cam, prev_tid), prev_buf in list(self.track_observation_buffer.items()):
                    if prev_cam == camera_id and (now - prev_buf.get("last_seen", 0.0) < 3.0):
                        prev_samples = prev_buf.get("samples", [])
                        if prev_samples and embedding is not None:
                            from app.core.utils import l2_normalize
                            q_norm = l2_normalize(embedding)
                            p_embs = [l2_normalize(s["embedding"]) for s in prev_samples if s.get("embedding") is not None]
                            if p_embs:
                                max_p_sim = max([float(np.dot(q_norm, pe.T)) for pe in p_embs])
                                if max_p_sim >= 0.48:
                                    found_prev = prev_buf
                                    break
                if found_prev is not None:
                    self.track_observation_buffer[cache_key] = found_prev
                else:
                    self.track_observation_buffer[cache_key] = {
                        "first_seen": now,
                        "last_seen": now,
                        "samples": []
                    }

            buf = self.track_observation_buffer[cache_key]
            buf["last_seen"] = now


            if quality_res.usable_for_matching:
                new_sample = {
                    "embedding": embedding,
                    "quality_score": quality_res.quality_score,
                    "quality_result": quality_res,
                    "yaw": quality_res.pose_yaw,
                    "pitch": quality_res.pose_pitch,
                    "blur_score": quality_res.blur_score,
                    "crop": crop_img.copy() if crop_img is not None else None,
                    "timestamp": now
                }
                MAX_OBSERVATION_SAMPLES = 20
                min_gap = float(getattr(settings, 'VISITOR_MIN_SAMPLE_GAP_SECONDS', 0.20))

                # For enrollment-quality frames: enforce spacing so we collect distinct best frames
                if quality_res.usable_for_new_identity:
                    recent_enroll = [
                        s for s in buf["samples"]
                        if s.get("quality_result")
                        and getattr(s["quality_result"], "usable_for_new_identity", False)
                    ]
                    if recent_enroll and abs(now - float(recent_enroll[-1].get("timestamp", 0.0))) < min_gap:
                        # Replace last enrollment sample if this one is better quality
                        last = recent_enroll[-1]
                        if new_sample["quality_score"] > float(last.get("quality_score", 0.0)):
                            idx = buf["samples"].index(last)
                            buf["samples"][idx] = new_sample
                    else:
                        if len(buf["samples"]) < MAX_OBSERVATION_SAMPLES:
                            buf["samples"].append(new_sample)
                        else:
                            min_idx = min(range(len(buf["samples"])), key=lambda i: buf["samples"][i]["quality_score"])
                            if new_sample["quality_score"] > buf["samples"][min_idx]["quality_score"]:
                                buf["samples"][min_idx] = new_sample
                else:
                    # Matching-only: keep for gallery search, never counts toward create
                    if len(buf["samples"]) < MAX_OBSERVATION_SAMPLES:
                        buf["samples"].append(new_sample)
                    else:
                        min_idx = min(range(len(buf["samples"])), key=lambda i: buf["samples"][i]["quality_score"])
                        if new_sample["quality_score"] > buf["samples"][min_idx]["quality_score"]:
                            buf["samples"][min_idx] = new_sample

            # 4. EVALUATE VISITOR GALLERY MATCH
            res = visitor_identity_resolver.resolve_visitor_candidate(embedding)

            # 5. EXISTING VISITOR MATCH CONFIRMED
            if res.decision == 'EXISTING' and res.visitor_id:
                # Lock identity to track
                self.track_identity_cache[cache_key] = {
                    "visitor_id": res.visitor_id,
                    "visitor_code": res.visitor_code,
                    "similarity": res.best_similarity,
                    "second_best_sim": res.second_best_similarity,
                    "margin": res.match_margin,
                    "confidence": res.confidence,
                    "primary_snapshot_path": res.primary_snapshot_path,
                    "last_seen": now,
                    "last_sighting_heartbeat": now
                }

                # Async persistence
                self._enqueue_persistence_task(
                    self._async_save_sighting,
                    res.visitor_id, camera_id, str_track_id,
                    res.best_similarity, res.second_best_similarity,
                    res.match_margin, res.confidence, crop_img,
                    embedding, quality_res, res.visitor_code
                )

                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                logger.info(f"[Perf:{camera_id}] Track {str_track_id} matched EXISTING {res.visitor_code} ({res.best_similarity*100:.1f}%) in {elapsed_ms:.1f}ms")

                return VisitorResolutionResult(
                    is_resolved=True,
                    visitor_id=res.visitor_id,
                    visitor_code=res.visitor_code,
                    similarity=res.best_similarity,
                    decision="EXISTING",
                    primary_snapshot_path=res.primary_snapshot_path,
                    reason=res.reason
                )

            # 6. PENDING MATCH — soft-confirm after consistent votes to prevent duplicate IDs
            if res.decision == 'PENDING':
                if res.visitor_id:
                    votes = buf.setdefault("pending_votes", {})
                    votes[res.visitor_id] = votes.get(res.visitor_id, 0) + 1
                    confirm_votes = int(getattr(settings, 'VISITOR_PENDING_CONFIRM_VOTES', 3))
                    # Soft-attach when same candidate keeps winning the PENDING band
                    if votes[res.visitor_id] >= confirm_votes and res.best_similarity >= getattr(
                        settings, 'VISITOR_MATCH_LOW_THRESHOLD', 0.40
                    ):
                        self.track_identity_cache[cache_key] = {
                            "visitor_id": res.visitor_id,
                            "visitor_code": res.visitor_code,
                            "similarity": res.best_similarity,
                            "second_best_sim": res.second_best_similarity,
                            "margin": res.match_margin,
                            "confidence": res.confidence,
                            "primary_snapshot_path": res.primary_snapshot_path,
                            "last_seen": now,
                            "last_sighting_heartbeat": now
                        }
                        self._enqueue_persistence_task(
                            self._async_save_sighting,
                            res.visitor_id, camera_id, str_track_id,
                            res.best_similarity, res.second_best_similarity,
                            res.match_margin, res.confidence, crop_img,
                            embedding, quality_res, res.visitor_code
                        )
                        logger.info(
                            f"[PENDING_CONFIRM] Track {str_track_id} soft-attached to "
                            f"{res.visitor_code} after {votes[res.visitor_id]} votes "
                            f"(sim={res.best_similarity:.3f})"
                        )
                        return VisitorResolutionResult(
                            is_resolved=True,
                            visitor_id=res.visitor_id,
                            visitor_code=res.visitor_code,
                            similarity=res.best_similarity,
                            decision="EXISTING",
                            primary_snapshot_path=res.primary_snapshot_path,
                            reason=f"PENDING soft-confirmed to {res.visitor_code}"
                        )

                return VisitorResolutionResult(
                    is_resolved=False,
                    visitor_code="Identifying...",
                    similarity=res.best_similarity,
                    decision="PENDING",
                    reason=f"Ambiguous similarity {res.best_similarity:.3f} to {res.visitor_code}"
                )

            # 7. NO EXISTING VISITOR CANDIDATE MATCH FOUND (res.decision == 'NONE')
            # Evaluate strict AdmissionController before creating new visitor identity!
            best_cand_dict = None
            if res.best_similarity > 0.0:
                best_cand_dict = {"visitor_code": res.visitor_code, "similarity": res.best_similarity}

            is_approved, decision_code, reason_detail = admission_controller.evaluate_admission(
                track_id=str_track_id,
                camera_id=camera_id,
                observations=buf["samples"],
                best_candidate=best_cand_dict
            )

            if not is_approved:
                # Admission failed -> Stay in COLLECTING or PENDING!
                return VisitorResolutionResult(
                    is_resolved=False,
                    visitor_code="Identifying...",
                    similarity=res.best_similarity,
                    decision=decision_code,
                    reason=reason_detail
                )

            # 8. ADMISSION APPROVED -> ATOMIC VISITOR CREATION
            with self.creation_lock:
                # Pre-creation Registered Guard: Re-check FAISS registered embeddings under creation lock
                from app.core.faiss_index import faiss_manager
                from app.core.utils import l2_normalize
                if faiss_manager.index.ntotal > 0 and embedding is not None:
                    hits = faiss_manager.search(query_embedding=embedding, k=5, threshold=0.35)
                    q_norm = l2_normalize(embedding)
                    # Use the same threshold as the recognition engine to avoid dead zones
                    # where a face is rejected by recognition but blocked from visitor creation
                    reg_thresh = getattr(settings, 'RECOGNITION_SIMILARITY_THRESHOLD', 0.45)
                    for hit in hits:
                        pid = hit.get("person_id")
                        name = hit.get("name")
                        if not pid or pid == "unknown" or name in (None, "Unknown", "unknown"):
                            continue  # Ignore orphan/unregistered entries in FAISS mapping
                        cached_embs = faiss_manager.embeddings_cache.get(pid, [])
                        if cached_embs:
                            max_sim = max([float(np.dot(q_norm, l2_normalize(e))) for e in cached_embs])
                            if max_sim >= reg_thresh:
                                logger.info(f"[PreCreationGuard] Track {str_track_id} matched Registered Person {name} ({max_sim:.3f}). Aborting visitor creation.")
                                return VisitorResolutionResult(
                                    is_resolved=False,
                                    visitor_code="Identifying...",
                                    similarity=max_sim,
                                    decision="EXISTING_REGISTERED",
                                    reason=f"Pre-creation check matched registered person {name}"
                                )

                # Double-check RAM gallery search under creation lock to prevent race conditions
                re_res = visitor_identity_resolver.resolve_visitor_candidate(embedding)
                if re_res.decision == 'EXISTING' and re_res.visitor_id:
                    self.track_identity_cache[cache_key] = {
                        "visitor_id": re_res.visitor_id,
                        "visitor_code": re_res.visitor_code,
                        "similarity": re_res.best_similarity,
                        "primary_snapshot_path": re_res.primary_snapshot_path,
                        "last_seen": now,
                        "last_sighting_heartbeat": now
                    }
                    return VisitorResolutionResult(
                        is_resolved=True,
                        visitor_id=re_res.visitor_id,
                        visitor_code=re_res.visitor_code,
                        similarity=re_res.best_similarity,
                        decision="EXISTING",
                        primary_snapshot_path=re_res.primary_snapshot_path,
                        reason="Matched under creation lock"
                    )
                # Also abort create if PENDING near-match appears under the lock
                if re_res.decision == 'PENDING' and re_res.visitor_id:
                    return VisitorResolutionResult(
                        is_resolved=False,
                        visitor_code="Identifying...",
                        similarity=re_res.best_similarity,
                        decision="PENDING",
                        reason=f"Near-match under creation lock to {re_res.visitor_code}"
                    )

                # Prefer enrollment-quality samples for primary profile; require enough best frames
                min_obs = int(getattr(settings, 'VISITOR_MIN_OBSERVATIONS_FOR_NEW', 6))
                enrollment_samples = [
                    s for s in buf["samples"]
                    if s.get("quality_result")
                    and getattr(s["quality_result"], "usable_for_new_identity", False)
                    and s.get("crop") is not None
                    and s.get("embedding") is not None
                ]
                if len(enrollment_samples) < min_obs:
                    return VisitorResolutionResult(
                        is_resolved=False,
                        visitor_code="Identifying...",
                        similarity=res.best_similarity,
                        decision="COLLECTING",
                        reason=f"Need {min_obs} best-quality frames (have {len(enrollment_samples)}) — not saving visitor"
                    )

                sorted_samples = sorted(
                    enrollment_samples,
                    key=lambda s: (
                        1 if getattr(s.get("quality_result"), "usable_for_primary_avatar", False) else 0,
                        s["quality_score"]
                    ),
                    reverse=True
                )
                # Persist only the best N enrollment frames
                sorted_samples = sorted_samples[:max(min_obs, 6)]
                best_sample = sorted_samples[0]
                min_best_q = float(getattr(settings, 'VISITOR_MIN_BEST_FRAME_QUALITY', 0.68))
                if float(best_sample.get("quality_score", 0.0)) < min_best_q:
                    return VisitorResolutionResult(
                        is_resolved=False,
                        visitor_code="Identifying...",
                        similarity=res.best_similarity,
                        decision="COLLECTING",
                        reason=f"Best frame quality {best_sample['quality_score']:.3f} < {min_best_q:.3f} — not saving"
                    )

                # Create New Visitor record in DB
                visitor = visitor_repository.create_visitor(
                    db=db,
                    camera_id=camera_id,
                    primary_crop=None
                )

                # Seed RAM gallery with multiple best embeddings immediately
                seeded = 0
                for sample in sorted_samples[:6]:
                    if sample.get("embedding") is None:
                        continue
                    visitor_gallery.add_visitor_sample(
                        visitor_id=visitor.id,
                        visitor_code=visitor.visitor_code,
                        embedding=sample["embedding"],
                        snapshot_path=None
                    )
                    seeded += 1
                if seeded == 0:
                    visitor_gallery.add_visitor_sample(
                        visitor_id=visitor.id,
                        visitor_code=visitor.visitor_code,
                        embedding=best_sample["embedding"],
                        snapshot_path=None
                    )

                # Lock track identity
                self.track_identity_cache[cache_key] = {
                    "visitor_id": visitor.id,
                    "visitor_code": visitor.visitor_code,
                    "similarity": 1.0,
                    "second_best_sim": 0.0,
                    "margin": 1.0,
                    "confidence": 1.0,
                    "primary_snapshot_path": None,
                    "last_seen": now,
                    "last_sighting_heartbeat": now
                }

                # Submit disk saves and DB insertions to bounded persistence queue (persist all 4-5 collected quality samples)
                extra_s_list = sorted_samples[1:] if len(sorted_samples) > 1 else []
                self._enqueue_persistence_task(
                    self._async_save_new_visitor,
                    visitor.id, visitor.visitor_code, camera_id, str_track_id, best_sample, extra_s_list
                )

                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                logger.info(f"[NEW_VISITOR] Created {visitor.visitor_code} for track {str_track_id} on {camera_id} in {elapsed_ms:.1f}ms. Reason: {reason_detail}")

                return VisitorResolutionResult(
                    is_resolved=True,
                    visitor_id=visitor.id,
                    visitor_code=visitor.visitor_code,
                    similarity=1.0,
                    decision="NEW",
                    primary_snapshot_path=None,
                    reason=reason_detail
                )

    def cleanup_stale_tracks(self, timeout_seconds: float = 30.0):
        """Cleans up stale track identity caches and observation buffers for terminated tracks."""
        with self.lock:
            now = time.time()
            stale_cache = [k for k, c in self.track_identity_cache.items() if now - c.get("last_seen", 0) > timeout_seconds]
            for k in stale_cache:
                del self.track_identity_cache[k]

            stale_buf = [k for k, b in self.track_observation_buffer.items() if now - b.get("last_seen", 0) > timeout_seconds]
            for k in stale_buf:
                del self.track_observation_buffer[k]


visitor_manager = VisitorManager()
