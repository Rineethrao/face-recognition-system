import time
import logging
import numpy as np
from typing import List, Dict, Tuple, Optional, Any

from app.config import settings
from app.core.utils import l2_normalize, align_face
from app.core.faiss_index import faiss_manager
from app.core.recognizer import arcface_recognizer
from app.models.schemas import RecognitionMatch, TrackedFace

logger = logging.getLogger(__name__)

class RecognitionService:
    """
    Consolidated Recognition Service.
    Handles ArcFace embedding extraction, Top-K FAISS vector search,
    track consensus window, and identification matching.
    """
    def __init__(self, top_k: int = 10, threshold: float = settings.RECOGNITION_SIMILARITY_THRESHOLD):
        self.arcface = arcface_recognizer
        self.top_k = top_k
        self.threshold = threshold
        self.track_cache: Dict[Any, Dict[str, Any]] = {}

    def recognize_embedding(
        self,
        embedding: np.ndarray,
        track_id: Any,
        camera_id: str = "default"
    ) -> RecognitionMatch:
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        if faiss_manager.index.ntotal == 0:
            return RecognitionMatch(
                person_id="unknown",
                name="Unknown",
                similarity=0.0,
                track_id=track_id,
                camera_id=camera_id,
                timestamp=now_str
            )

        top_k_hits = faiss_manager.search(
            query_embedding=embedding,
            k=self.top_k,
            threshold=0.35
        )

        if not top_k_hits:
            return RecognitionMatch(
                person_id="unknown",
                name="Unknown",
                similarity=0.0,
                track_id=track_id,
                camera_id=camera_id,
                timestamp=now_str
            )

        candidate_pids: Dict[str, str] = {}
        for hit in top_k_hits:
            pid = hit["person_id"]
            candidate_pids[pid] = hit["name"]

        best_person_id: Optional[str] = None
        best_person_name: str = "Unknown"
        highest_similarity: float = 0.0

        q_norm = l2_normalize(embedding)

        for pid, name in candidate_pids.items():
            cached_embs = faiss_manager.embeddings_cache.get(pid, [])
            if not cached_embs:
                continue

            sims = [float(np.dot(q_norm, l2_normalize(g_emb).T)) for g_emb in cached_embs]
            max_sim_for_person = max(sims)

            if max_sim_for_person > highest_similarity:
                highest_similarity = max_sim_for_person
                best_person_id = pid
                best_person_name = name

        if best_person_id and highest_similarity >= self.threshold:
            return RecognitionMatch(
                person_id=best_person_id,
                name=best_person_name,
                similarity=round(highest_similarity, 4),
                track_id=track_id,
                camera_id=camera_id,
                timestamp=now_str
            )

        return RecognitionMatch(
            person_id="unknown",
            name="Unknown",
            similarity=round(highest_similarity, 4) if best_person_id else 0.0,
            track_id=track_id,
            camera_id=camera_id,
            timestamp=now_str
        )

    def process_tracked_faces(
        self,
        frame: np.ndarray,
        tracked_faces: List[TrackedFace],
        camera_id: str = "default"
    ) -> List[RecognitionMatch]:
        from app.services.quality.quality_engine import quality_engine
        from app.core.utils import calculate_blur

        results: List[RecognitionMatch] = []
        now = time.time()

        for face in tracked_faces:
            track_id = face.track_id
            landmarks = np.array(face.landmarks)

            # Initialize track cache if it is new
            if track_id not in self.track_cache:
                self.track_cache[track_id] = {
                    "first_seen": now,
                    "last_seen": now,
                    "frames_collected": 0,
                    "best_frame": None,
                    "best_quality_est": -1.0,
                    "best_landmarks": None,
                    "best_bbox": None,
                    "final_match": None,
                    "recognition_attempted": False
                }

            cache = self.track_cache[track_id]
            cache["last_seen"] = now

            # 1. Cache Reuse (Return immediately if already recognized or low quality determined)
            if cache["final_match"] is not None:
                match_info = cache["final_match"]
                results.append(RecognitionMatch(
                    person_id=match_info["person_id"],
                    name=match_info["name"],
                    similarity=match_info["similarity"],
                    track_id=track_id,
                    camera_id=camera_id,
                    timestamp=time.strftime("%H:%M:%S")
                ))
                continue

            # 2. Accumulate frames & select best frame
            # Buffer frames for 1.2 seconds or 12 frames to find the best candidate frame
            time_elapsed = now - cache["first_seen"]
            if not cache["recognition_attempted"] and (cache["frames_collected"] < 12 and time_elapsed < 1.2):
                # Calculate simple quick quality estimator: face size * sharpness
                x1, y1, x2, y2 = face.bbox
                face_w = max(0, x2 - x1)
                face_h = max(0, y2 - y1)
                face_size = min(face_w, face_h)

                # Rough crop to compute blur (extremely fast on CPU)
                ih, iw = frame.shape[:2]
                cx1, cy1, cx2, cy2 = int(max(0, x1)), int(max(0, y1)), int(min(iw, x2)), int(min(ih, y2))
                if cx2 > cx1 and cy2 > cy1:
                    crop_rough = frame[cy1:cy2, cx1:cx2]
                    blur_score = calculate_blur(crop_rough)
                else:
                    blur_score = 0.0

                quality_est = face_size * blur_score

                # Save if this is the best quality frame yet
                if quality_est > cache["best_quality_est"]:
                    cache["best_quality_est"] = quality_est
                    cache["best_frame"] = frame.copy()
                    cache["best_landmarks"] = landmarks.copy()
                    cache["best_bbox"] = face.bbox

                cache["frames_collected"] += 1

                # Display "Analyzing..." on the screen while collecting best frame
                results.append(RecognitionMatch(
                    person_id="unknown",
                    name="Analyzing...",
                    similarity=0.0,
                    track_id=track_id,
                    camera_id=camera_id,
                    timestamp=time.strftime("%H:%M:%S")
                ))
                continue

            # 3. Perform single-inference recognition once window closes
            if not cache["recognition_attempted"]:
                cache["recognition_attempted"] = True

                best_f = cache["best_frame"]
                best_box = cache["best_bbox"]
                best_lms = cache["best_landmarks"]

                if best_f is None or best_box is None or best_lms is None:
                    # Fallback to current frame if buffer is empty
                    best_f = frame
                    best_box = face.bbox
                    best_lms = landmarks

                # Run full quality engine check
                eval_res = quality_engine.evaluate(best_f, best_box, best_lms)

                # Check quality score threshold (map 0-1.0 to 0-100 scale, threshold: 60)
                quality_score_100 = eval_res["quality_score"] * 100.0
                if quality_score_100 < 60:
                    logger.debug(f"[Recognition Engine] Skip recognition for track {track_id}: Quality too low ({quality_score_100:.1f} < 60)")
                    cache["final_match"] = {
                        "person_id": "unknown",
                        "name": "Unknown",
                        "similarity": 0.0
                    }
                else:
                    # Extract ArcFace embedding on the aligned crop (which is already enhanced)
                    aligned_crop = eval_res["aligned_crop"]
                    embedding = self.arcface.extract_embedding(aligned_crop)

                    # Step 1: Registered recognition via FAISS
                    match = self.recognize_embedding(embedding, track_id=track_id, camera_id=camera_id)

                    if match.person_id != "unknown":
                        cache["final_match"] = {
                            "person_id": match.person_id,
                            "name": match.name,
                            "similarity": match.similarity
                        }
                        try:
                            from app.services.learning.progressive_learning import progressive_learning_engine
                            progressive_learning_engine.queue_profile_auto_improvement(
                                person_id=match.person_id,
                                name=match.name,
                                aligned_crop=aligned_crop,
                                new_embedding=embedding,
                                match_score=match.similarity,
                                camera_id=camera_id
                            )
                        except Exception as pl_err:
                            logger.error(f"Error triggering progressive learning: {pl_err}")
                    else:
                        # Step 2: Unregistered track handling via VisitorManager
                        try:
                            from app.core.database import SessionLocal
                            from app.visitors.visitor_manager import visitor_manager
                            from app.visitors.face_quality import visitor_quality_evaluator
                            db = SessionLocal()
                            try:
                                fq_res = visitor_quality_evaluator.evaluate_quality(best_f, best_box, best_lms)
                                vis_res = visitor_manager.resolve_unregistered_track(
                                    db=db,
                                    camera_id=camera_id,
                                    track_id=track_id,
                                    embedding=embedding,
                                    quality_res=fq_res,
                                    crop_img=aligned_crop
                                )
                                if vis_res.is_resolved:
                                    cache["final_match"] = {
                                        "person_id": vis_res.visitor_code,
                                        "name": vis_res.visitor_code,
                                        "similarity": vis_res.similarity
                                    }
                                    cache["recognition_attempted"] = True
                                else:
                                    # Still identifying — do not lock final_match yet so next quality frames accumulate
                                    cache["recognition_attempted"] = False
                                    cache["frames_collected"] = 0
                                    cache["best_quality_est"] = -1.0
                                    cache["best_frame"] = None
                                    cache["final_match"] = None
                                    results.append(RecognitionMatch(
                                        person_id="unknown",
                                        name=vis_res.visitor_code,
                                        similarity=0.0,
                                        track_id=track_id,
                                        camera_id=camera_id,
                                        timestamp=time.strftime("%H:%M:%S")
                                    ))
                                    continue
                            finally:
                                db.close()
                        except Exception as vis_err:
                            logger.error(f"Error in visitor track resolution: {vis_err}", exc_info=True)
                            cache["final_match"] = {
                                "person_id": "unknown",
                                "name": "Identifying...",
                                "similarity": 0.0
                            }

            # Return the finalized match
            match_info = cache["final_match"] or {
                "person_id": "unknown",
                "name": "Unknown",
                "similarity": 0.0
            }
            results.append(RecognitionMatch(
                person_id=match_info["person_id"],
                name=match_info["name"],
                similarity=match_info["similarity"],
                track_id=track_id,
                camera_id=camera_id,
                timestamp=time.strftime("%H:%M:%S")
            ))

        # Cleanup stale tracks from cache (older than 30 seconds)
        stale_ids = [tid for tid, c in self.track_cache.items() if now - c["last_seen"] > 30.0]
        for tid in stale_ids:
            del self.track_cache[tid]

        return results

recognition_service = RecognitionService()
recognition_engine = recognition_service
