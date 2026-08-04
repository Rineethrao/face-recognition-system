import numpy as np
import logging
from typing import Tuple, Optional, List, Dict, Any
from app.core.faiss_index import faiss_manager
from app.config import settings

logger = logging.getLogger(__name__)

class DuplicateService:
    """
    Duplicate Detection Service.
    Queries incoming embeddings against the active FAISS index to ensure the target person is not already registered under a different ID.
    """

    def check_duplicate(
        self,
        embeddings: List[np.ndarray],
        current_person_id: Optional[str] = None,
        threshold: float = settings.RECOGNITION_SIMILARITY_THRESHOLD
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Checks if any of the provided embeddings closely match a person already in FAISS.
        Returns (is_duplicate, matched_info_dict)
        """
        if not embeddings or faiss_manager.index.ntotal == 0:
            return False, None

        for emb in embeddings:
            matches = faiss_manager.search(emb, k=1, threshold=threshold)
            if matches:
                top_match = matches[0]
                matched_id = top_match.get("person_id")
                matched_name = top_match.get("name")
                similarity = top_match.get("similarity", 0.0)

                # Ignore matches to the person being re-registered/updated
                if current_person_id and matched_id == current_person_id:
                    continue

                logger.warning(
                    f"Duplicate check hit! Matched existing Person '{matched_name}' ({matched_id}) with {similarity:.3f} similarity."
                )
                return True, {
                    "matched_person_id": matched_id,
                    "matched_name": matched_name,
                    "similarity": similarity
                }

        return False, None

    def assess_duplicate(
        self,
        embeddings: List[np.ndarray],
        current_person_id: Optional[str] = None,
        hard_threshold: Optional[float] = None,
        warning_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Find the best FAISS match across gallery embeddings (excluding current_person_id)
        and classify as none / soft / hard for operator warning UX.

        Soft: warning_threshold <= sim < hard_threshold
        Hard: sim >= hard_threshold
        """
        hard_threshold = (
            settings.RECOGNITION_SIMILARITY_THRESHOLD
            if hard_threshold is None
            else hard_threshold
        )
        warning_threshold = (
            settings.REGISTRATION_DUPLICATE_WARNING_THRESHOLD
            if warning_threshold is None
            else warning_threshold
        )

        empty = {
            "level": "none",
            "matched_person_id": None,
            "matched_name": None,
            "similarity": 0.0,
            "hard_threshold": hard_threshold,
            "warning_threshold": warning_threshold,
        }

        if not embeddings or faiss_manager.index.ntotal == 0:
            return empty

        best: Optional[Dict[str, Any]] = None

        for emb in embeddings:
            # Search at soft floor so glasses-level matches are visible
            matches = faiss_manager.search(emb, k=5, threshold=warning_threshold)
            for match in matches:
                matched_id = match.get("person_id")
                if current_person_id and matched_id == current_person_id:
                    continue
                sim = float(match.get("similarity", 0.0))
                if best is None or sim > float(best.get("similarity", 0.0)):
                    best = {
                        "matched_person_id": matched_id,
                        "matched_name": match.get("name"),
                        "similarity": sim,
                    }

        if best is None:
            return empty

        sim = float(best["similarity"])
        if sim >= hard_threshold:
            level = "hard"
        elif sim >= warning_threshold:
            level = "soft"
        else:
            level = "none"

        if level != "none":
            logger.info(
                "Duplicate assessment level=%s matched=%s (%s) similarity=%.3f",
                level,
                best.get("matched_name"),
                best.get("matched_person_id"),
                sim,
            )

        return {
            "level": level,
            "matched_person_id": best.get("matched_person_id"),
            "matched_name": best.get("matched_name"),
            "similarity": round(sim, 4),
            "hard_threshold": hard_threshold,
            "warning_threshold": warning_threshold,
        }

duplicate_service = DuplicateService()
