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

duplicate_service = DuplicateService()
