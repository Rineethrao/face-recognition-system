import logging
from typing import Dict, Any, List, Optional, Tuple
from app.config import settings
from app.visitors.visitor_gallery import VisitorCandidateMatch, visitor_gallery

logger = logging.getLogger(__name__)

class IdentityResolverResult:
    def __init__(
        self,
        decision: str,  # 'EXISTING', 'PENDING', 'NONE'
        visitor_id: Optional[int] = None,
        visitor_code: Optional[str] = None,
        best_similarity: float = 0.0,
        second_best_similarity: float = 0.0,
        match_margin: float = 0.0,
        confidence: float = 0.0,
        primary_snapshot_path: Optional[str] = None,
        reason: str = ""
    ):
        self.decision = decision
        self.visitor_id = visitor_id
        self.visitor_code = visitor_code
        self.best_similarity = best_similarity
        self.second_best_similarity = second_best_similarity
        self.match_margin = match_margin
        self.confidence = confidence
        self.primary_snapshot_path = primary_snapshot_path
        self.reason = reason


class VisitorIdentityResolver:
    """
    Identity Resolver Module for Unregistered Visitor Candidates.
    Applies candidate score aggregation, candidate margin checks, and decision bands:
    - EXISTING: Score >= match_high AND margin >= required_margin
    - PENDING: Ambiguous score (match_low <= Score < match_high) OR margin < required_margin
    - NONE: Score < match_low
    """

    def resolve_visitor_candidate(self, embedding: Any) -> IdentityResolverResult:
        """
        Searches active visitor gallery for best matching candidate and evaluates match confidence.
        """
        candidates, margin = visitor_gallery.search_candidates(embedding)

        if not candidates:
            return IdentityResolverResult(decision='NONE', reason="Gallery empty or no candidate found")

        best_cand = candidates[0]
        second_best_sim = candidates[1].composite_score if len(candidates) > 1 else 0.0

        match_high = getattr(settings, 'VISITOR_MATCH_HIGH_THRESHOLD', 0.58)
        required_margin = getattr(settings, 'VISITOR_CANDIDATE_MATCH_MARGIN', 0.015)

        # Check HIGH match condition with required margin
        if best_cand.composite_score >= match_high and margin >= required_margin:
            return IdentityResolverResult(
                decision='EXISTING',
                visitor_id=best_cand.visitor_id,
                visitor_code=best_cand.visitor_code,
                best_similarity=round(best_cand.composite_score, 4),
                second_best_similarity=round(second_best_sim, 4),
                match_margin=round(margin, 4),
                confidence=round(min(1.0, best_cand.composite_score + 0.1), 4),
                primary_snapshot_path=best_cand.primary_snapshot_path,
                reason=f"High match ({best_cand.composite_score:.3f} >= {match_high})"
            )

        # PENDING: Score >= match_high but margin insufficient (ambiguous between two visitors)
        match_low = getattr(settings, 'VISITOR_MATCH_LOW_THRESHOLD', 0.45)
        if best_cand.composite_score >= match_high and margin < required_margin:
            return IdentityResolverResult(
                decision='PENDING',
                visitor_id=best_cand.visitor_id,
                visitor_code=best_cand.visitor_code,
                best_similarity=round(best_cand.composite_score, 4),
                second_best_similarity=round(second_best_sim, 4),
                match_margin=round(margin, 4),
                confidence=round(best_cand.composite_score * 0.7, 4),
                primary_snapshot_path=best_cand.primary_snapshot_path,
                reason=f"Ambiguous: score {best_cand.composite_score:.3f} >= {match_high} but margin {margin:.3f} < {required_margin}"
            )

        # PENDING: Borderline similarity (between match_low and match_high)
        if best_cand.composite_score >= match_low:
            return IdentityResolverResult(
                decision='PENDING',
                visitor_id=best_cand.visitor_id,
                visitor_code=best_cand.visitor_code,
                best_similarity=round(best_cand.composite_score, 4),
                second_best_similarity=round(second_best_sim, 4),
                match_margin=round(margin, 4),
                confidence=round(best_cand.composite_score * 0.5, 4),
                primary_snapshot_path=best_cand.primary_snapshot_path,
                reason=f"Borderline: score {best_cand.composite_score:.3f} between {match_low} and {match_high}"
            )

        # Score < match_low: No existing visitor match candidate -> Proceed to NEW visitor evaluation
        return IdentityResolverResult(
            decision='NONE',
            best_similarity=round(best_cand.composite_score, 4),
            second_best_similarity=round(second_best_sim, 4),
            match_margin=round(margin, 4),
            reason=f"No match (best score {best_cand.composite_score:.3f} < {match_low})"
        )


visitor_identity_resolver = VisitorIdentityResolver()
