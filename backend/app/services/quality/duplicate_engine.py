import numpy as np
from typing import List, Dict, Any, Tuple
from app.core.utils import l2_normalize

class DuplicateEngine:
    """
    Deduplicates consecutive or redundant face captures using embedding cosine similarity.
    Prevents cluttering galleries with near-identical adjacent frames.
    """
    def __init__(self, similarity_threshold: float = 0.90):
        self.similarity_threshold = similarity_threshold

    def is_duplicate(self, query_emb: np.ndarray, existing_embs: List[np.ndarray]) -> Tuple[bool, float]:
        """
        Compares query_emb against a list of existing embeddings.
        Returns (is_duplicate, max_similarity).
        """
        if not existing_embs or len(existing_embs) == 0:
            return False, 0.0

        q_norm = l2_normalize(query_emb)
        sims = [float(np.dot(q_norm, l2_normalize(emb).T)) for emb in existing_embs]
        max_sim = max(sims)

        return max_sim >= self.similarity_threshold, max_sim

    def deduplicate(self, captures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters a list of captures, retaining only non-duplicate, high-quality instances.
        """
        if not captures:
            return []

        # Sort by quality score descending so higher quality items are kept first
        sorted_caps = sorted(captures, key=lambda c: c.get("quality_score", 0.0), reverse=True)
        unique_caps: List[Dict[str, Any]] = []
        unique_embs: List[np.ndarray] = []

        for cap in sorted_caps:
            emb = cap.get("embedding")
            if emb is None:
                continue

            is_dup, _ = self.is_duplicate(emb, unique_embs)
            if not is_dup:
                unique_caps.append(cap)
                unique_embs.append(emb)

        return unique_caps

duplicate_engine = DuplicateEngine()
