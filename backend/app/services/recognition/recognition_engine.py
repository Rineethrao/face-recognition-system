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

class RecognitionEngine:
    """
    Consolidated Enterprise Recognition Engine.
    Combines ArcFace embedding extraction, Top-K FAISS vector verification,
    track consensus caching, and auto-profile enrichment triggers.
    """
    def __init__(self, top_k: int = 10, threshold: float = settings.RECOGNITION_SIMILARITY_THRESHOLD):
        self.arcface = arcface_recognizer
        self.top_k = top_k
        self.threshold = threshold
        # Track Cache: track_id -> {"matches": [], "first_seen": float, "last_seen": float, "final_match": Optional[Dict]}
        self.track_cache: Dict[Any, Dict[str, Any]] = {}

    def recognize_embedding(
        self,
        embedding: np.ndarray,
        track_id: Any,
        camera_id: str = "default"
    ) -> RecognitionMatch:
        """
        Executes Top-K FAISS search and full-gallery verification.
        Returns RecognitionMatch object (recognized person or unknown).
        """
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
        """
        Processes tracked faces through alignment, ArcFace embedding extraction,
        consensus tracking window, and profile auto-enrichment.
        """
        results: List[RecognitionMatch] = []
        now = time.time()

        for face in tracked_faces:
            track_id = face.track_id
            landmarks = np.array(face.landmarks)

            if track_id not in self.track_cache:
                self.track_cache[track_id] = {
                    "matches": [],
                    "first_seen": now,
                    "last_seen": now,
                    "final_match": None
                }

            cache = self.track_cache[track_id]
            cache["last_seen"] = now

            if cache["final_match"] is not None:
                match_info = cache["final_match"]
                results.append(RecognitionMatch(
                    person_id=match_info["person_id"],
                    name=match_info["name"],
                    similarity=match_info["similarity"],
                    track_id=track_id,
                    camera_id=camera_id,
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
                ))
                continue

            aligned_crop = align_face(frame, landmarks)
            embedding = self.arcface.extract_embedding(aligned_crop)

            match = self.recognize_embedding(embedding, track_id=track_id, camera_id=camera_id)

            if match.person_id != "unknown":
                cache["matches"].append({
                    "person_id": match.person_id,
                    "name": match.name,
                    "similarity": match.similarity
                })

            time_elapsed = now - cache["first_seen"]

            # Consensus Decision Point
            if time_elapsed >= settings.RECOGNITION_TIME_WINDOW or len(cache["matches"]) >= 5:
                if cache["matches"]:
                    person_scores: Dict[str, List[float]] = {}
                    person_names: Dict[str, str] = {}

                    for m in cache["matches"]:
                        pid = m["person_id"]
                        person_scores.setdefault(pid, []).append(m["similarity"])
                        person_names[pid] = m["name"]

                    best_pid = max(person_scores.keys(), key=lambda k: max(person_scores[k]))
                    max_score = float(max(person_scores[best_pid]))

                    final_match = {
                        "person_id": best_pid,
                        "name": person_names[best_pid],
                        "similarity": max_score
                    }
                    cache["final_match"] = final_match

                    final_res = RecognitionMatch(
                        person_id=best_pid,
                        name=person_names[best_pid],
                        similarity=max_score,
                        track_id=track_id,
                        camera_id=camera_id,
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
                    )
                    results.append(final_res)

                    # Trigger async progressive learning auto-enrichment
                    try:
                        from app.services.learning.progressive_learning import progressive_learning_engine
                        progressive_learning_engine.queue_profile_auto_improvement(
                            person_id=best_pid,
                            name=person_names[best_pid],
                            aligned_crop=aligned_crop,
                            new_embedding=embedding,
                            match_score=max_score,
                            camera_id=camera_id
                        )
                    except Exception as learn_err:
                        logger.debug(f"Progressive learning trigger note: {learn_err}")
                else:
                    final_match = {
                        "person_id": "unknown",
                        "name": "Unknown",
                        "similarity": 0.0
                    }
                    cache["final_match"] = final_match
                    results.append(RecognitionMatch(
                        person_id="unknown",
                        name="Unknown",
                        similarity=0.0,
                        track_id=track_id,
                        camera_id=camera_id,
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
                    ))
            else:
                results.append(match)

        # Clean stale tracks older than 30s
        stale_ids = [tid for tid, c in self.track_cache.items() if now - c["last_seen"] > 30.0]
        for tid in stale_ids:
            del self.track_cache[tid]

        return results

recognition_engine = RecognitionEngine()

# Re-export aliases for backward compatibility
RecognitionService = RecognitionEngine
recognition_service = recognition_engine
RecognitionEngineV2 = RecognitionEngine
recognition_engine_v2 = recognition_engine
