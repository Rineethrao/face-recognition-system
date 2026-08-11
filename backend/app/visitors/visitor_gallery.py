import logging
import threading
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from sqlalchemy.orm import Session

from app.config import settings
from app.core.utils import l2_normalize
from app.visitors.models import VisitorModel, VisitorFaceSampleModel
from app.visitors.visitor_repository import get_operational_date_key

logger = logging.getLogger(__name__)

class VisitorCandidateMatch:
    def __init__(
        self,
        visitor_id: int,
        visitor_code: str,
        max_similarity: float,
        top_k_mean_similarity: float,
        composite_score: float,
        sample_count: int,
        primary_snapshot_path: Optional[str] = None
    ):
        self.visitor_id = visitor_id
        self.visitor_code = visitor_code
        self.max_similarity = max_similarity
        self.top_k_mean_similarity = top_k_mean_similarity
        self.composite_score = composite_score
        self.sample_count = sample_count
        self.primary_snapshot_path = primary_snapshot_path


class VisitorGallery:
    """
    In-Memory Visitor Vector Gallery supporting multi-sample embedding matching.
    Accelerates Re-ID searches across today's active visitors.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.current_date_key: str = ""
        # visitor_id -> list of normalized 512-D float32 arrays
        self.gallery_embeddings: Dict[int, List[np.ndarray]] = {}
        # visitor_id -> visitor_code
        self.visitor_codes: Dict[int, str] = {}
        # visitor_id -> primary snapshot path
        self.visitor_snapshots: Dict[int, Optional[str]] = {}

    def load_global_gallery(self, db: Session):
        """Loads all active visitor identities and high-quality gallery-eligible embeddings globally across all dates."""
        with self.lock:
            self.gallery_embeddings.clear()
            self.visitor_codes.clear()
            self.visitor_snapshots.clear()

            visitors = db.query(VisitorModel).filter(
                VisitorModel.status == 'active'
            ).all()

            loaded_samples_count = 0
            for v in visitors:
                self.visitor_codes[v.id] = v.visitor_code
                self.visitor_snapshots[v.id] = v.primary_snapshot_path
                self.gallery_embeddings[v.id] = []

                samples = db.query(VisitorFaceSampleModel).filter(
                    VisitorFaceSampleModel.visitor_id == v.id,
                    (VisitorFaceSampleModel.gallery_eligible == True) | (VisitorFaceSampleModel.gallery_eligible == None)
                ).all()

                for sample in samples:
                    if sample.embedding_blob:
                        vec = np.frombuffer(sample.embedding_blob, dtype=np.float32)
                        norm_vec = l2_normalize(vec)
                        self.gallery_embeddings[v.id].append(norm_vec)
                        loaded_samples_count += 1

            logger.info(f"[VisitorGallery] Loaded global vector gallery: {len(visitors)} active visitors, {loaded_samples_count} embeddings.")

    def load_daily_gallery(self, db: Session, date_key: Optional[str] = None):
        """Backward compatible wrapper loading the global visitor vector gallery."""
        self.load_global_gallery(db)


    def validate_profile_sample(self, visitor_id: int, embedding: np.ndarray) -> Tuple[bool, str]:
        """
        Visitor Profile Guard: Evaluates if a candidate face sample is authorized to be persisted.
        Rejects:
        1. Inconsistent / Contaminated samples (similarity < VISITOR_PROFILE_UPDATE_THRESHOLD 0.62).
        2. Redundant duplicate samples when visitor already has sufficient gallery samples (>= 5 samples and sim >= 0.85).
        """
        with self.lock:
            existing = self.gallery_embeddings.get(visitor_id, [])
            if not existing:
                return True, "Initial sample"

            norm_vec = l2_normalize(embedding)
            sims = [float(np.dot(norm_vec, g_emb.T)) for g_emb in existing]
            max_sim = max(sims)
            update_thresh = getattr(settings, 'VISITOR_PROFILE_UPDATE_THRESHOLD', 0.62)

            if max_sim < update_thresh:
                return False, f"Profile Guard Rejection: similarity {max_sim:.3f} < threshold {update_thresh}"

            max_samples = getattr(settings, 'VISITOR_MAX_SAMPLES', 5)
            if len(existing) >= max_samples and max_sim >= 0.85:
                return False, f"Sample Redundancy Rejection: gallery has {len(existing)} samples and new sample is redundant (sim {max_sim:.3f} >= 0.85)"

            return True, "Valid sample"

    def add_visitor_sample(
        self,
        visitor_id: int,
        visitor_code: str,
        embedding: np.ndarray,
        snapshot_path: Optional[str] = None
    ) -> bool:
        """
        Dynamically appends a new face embedding sample to the active in-memory gallery.
        Applies Visitor Profile Guard to reject outlier/inconsistent samples.
        """
        with self.lock:
            norm_vec = l2_normalize(embedding)
            if visitor_id not in self.gallery_embeddings:
                self.gallery_embeddings[visitor_id] = []
                self.visitor_codes[visitor_id] = visitor_code
                self.visitor_snapshots[visitor_id] = snapshot_path

            existing = self.gallery_embeddings[visitor_id]
            if existing:
                sims = [float(np.dot(norm_vec, g_emb.T)) for g_emb in existing]
                max_sim = max(sims)
                update_thresh = getattr(settings, 'VISITOR_PROFILE_UPDATE_THRESHOLD', 0.62)
                if max_sim < update_thresh:
                    logger.warning(
                        f"[PROFILE_GUARD_REJECTION] Rejecting sample for visitor {visitor_code} (ID: {visitor_id}). "
                        f"Max similarity {max_sim:.3f} < threshold {update_thresh}. Inconsistency guarded."
                    )
                    return False

            # Enforce max sample limit per visitor (keep latest/best max_samples)
            max_samples = getattr(settings, 'VISITOR_MAX_SAMPLES', 5)
            if len(self.gallery_embeddings[visitor_id]) >= max_samples:
                # Remove oldest extra sample
                self.gallery_embeddings[visitor_id].pop(0)

            self.gallery_embeddings[visitor_id].append(norm_vec)
            if snapshot_path:
                self.visitor_snapshots[visitor_id] = snapshot_path
            return True

    def search_candidates(self, query_embedding: np.ndarray) -> Tuple[List[VisitorCandidateMatch], float]:
        """
        Searches all active visitor samples against query embedding.
        Returns candidate matches sorted by score and match_margin (difference between top 2 candidates).
        """
        with self.lock:
            if not self.gallery_embeddings:
                return [], 0.0

            q_norm = l2_normalize(query_embedding)
            candidates: List[VisitorCandidateMatch] = []

            for visitor_id, emb_list in self.gallery_embeddings.items():
                if not emb_list:
                    continue

                sims = [float(np.dot(q_norm, g_emb.T)) for g_emb in emb_list]
                sims.sort(reverse=True)

                max_sim = sims[0]
                top_k = sims[:3]
                top_k_mean = float(np.mean(top_k))
                composite = (0.7 * max_sim) + (0.3 * top_k_mean)

                candidates.append(VisitorCandidateMatch(
                    visitor_id=visitor_id,
                    visitor_code=self.visitor_codes.get(visitor_id, f"Visitor_{visitor_id}"),
                    max_similarity=max_sim,
                    top_k_mean_similarity=top_k_mean,
                    composite_score=composite,
                    sample_count=len(emb_list),
                    primary_snapshot_path=self.visitor_snapshots.get(visitor_id)
                ))

            if not candidates:
                return [], 0.0

            candidates.sort(key=lambda c: c.composite_score, reverse=True)

            # Compute margin between best and second best candidate
            best_score = candidates[0].composite_score
            second_score = candidates[1].composite_score if len(candidates) > 1 else 0.0
            margin = best_score - second_score

            return candidates, round(margin, 4)

    def remove_visitor(self, visitor_id: int):
        """Removes a visitor from the in-memory vector gallery."""
        with self.lock:
            if visitor_id in self.gallery_embeddings:
                del self.gallery_embeddings[visitor_id]
            if visitor_id in self.visitor_codes:
                del self.visitor_codes[visitor_id]
            if visitor_id in self.visitor_snapshots:
                del self.visitor_snapshots[visitor_id]
            logger.info(f"[VisitorGallery] Removed visitor {visitor_id} from in-memory gallery.")

visitor_gallery = VisitorGallery()
