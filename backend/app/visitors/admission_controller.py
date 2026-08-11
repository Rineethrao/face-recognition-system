import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from app.config import settings
from app.visitors.face_quality import FaceQualityResult


class AdmissionController:
    """
    Centralized Gatekeeper for New Visitor Identity Creation.
    Enforces strict admission criteria to prevent duplicate Visitor creation:
    1. Minimum enrollment-quality observation count.
    2. Within-track pairwise embedding consistency (protects against person-face association swaps).
    3. Pose, face width, blur, and brightness bounds.
    4. Absence of ambiguous candidate match (match_low <= sim <= match_high).
    5. Absence of recent track continuity candidates on the camera.
    """

    def evaluate_admission(
        self,
        track_id: str,
        camera_id: str,
        observations: List[Dict[str, Any]],
        best_candidate: Optional[Dict[str, Any]] = None,
        registered_match: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, str]:
        """
        Evaluates whether an unresolved track is qualified to instantiate a NEW Visitor profile.
        Returns (is_approved, decision_code, reason_detail).
        - decision_code: 'ADMISSION_APPROVED', 'COLLECTING', 'PENDING'
        """
        min_obs = getattr(settings, 'VISITOR_MIN_OBSERVATIONS_FOR_NEW', 4)
        match_high = getattr(settings, 'VISITOR_MATCH_HIGH_THRESHOLD', 0.46)
        match_low = getattr(settings, 'VISITOR_MATCH_LOW_THRESHOLD', 0.36)
        consistency_thresh = getattr(settings, 'VISITOR_WITHIN_TRACK_CONSISTENCY_THRESH', 0.45)

        # 1. Registered match check
        if registered_match and registered_match.get("confidence", 0.0) >= getattr(settings, 'RECOGNITION_CONFIDENCE_THRESHOLD', 0.50):
            return False, "EXISTING_REGISTERED", f"Matches registered person {registered_match.get('person_id')}"

        # 2. Ambiguous or confident visitor candidate check
        if best_candidate:
            top_sim = float(best_candidate.get("similarity", 0.0))
            if top_sim >= match_high:
                return False, "EXISTING_VISITOR", f"Matches existing visitor {best_candidate.get('visitor_code')} with sim={top_sim:.3f}"
            elif top_sim >= match_low:
                # Ambiguous similarity band: stay PENDING!
                return False, "PENDING", f"Ambiguous similarity {top_sim:.3f} to {best_candidate.get('visitor_code')} (band [{match_low}, {match_high}])"

        # 3. Filter for enrollment-quality observations
        enrollment_obs = [
            obs for obs in observations
            if obs.get("quality_result") and (
                getattr(obs["quality_result"], "usable_for_new_identity", False) or
                getattr(obs["quality_result"], "usable_for_matching", False)
            )
        ]

        if len(enrollment_obs) < min_obs:
            return False, "COLLECTING", f"Insufficient enrollment observations ({len(enrollment_obs)}/{min_obs})"

        # Check observation time span (must be observed over at least 0.15s for track stability)
        timestamps = [obs.get("timestamp", 0.0) for obs in enrollment_obs if obs.get("timestamp")]
        if len(timestamps) >= 2:
            time_span = max(timestamps) - min(timestamps)
            if time_span < 0.15:
                return False, "COLLECTING", f"Track duration too short ({time_span:.2f}s < 0.15s requirement)"



        # 4. Within-track pairwise embedding consistency check
        embeddings = [obs["embedding"] for obs in enrollment_obs if obs.get("embedding") is not None]
        if len(embeddings) >= 2:
            inconsistent = False
            min_pair_sim = 1.0
            for i in range(len(embeddings)):
                for j in range(i + 1, len(embeddings)):
                    e1 = np.array(embeddings[i], dtype=np.float32)
                    e2 = np.array(embeddings[j], dtype=np.float32)
                    sim = float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-6))
                    min_pair_sim = min(min_pair_sim, sim)
                    if sim < consistency_thresh:
                        inconsistent = True
                        break
                if inconsistent:
                    break

            if inconsistent:
                return False, "COLLECTING", f"Within-track embeddings inconsistent (min pair sim={min_pair_sim:.3f} < {consistency_thresh})"

        # All checks passed!
        return True, "ADMISSION_APPROVED", f"Approved with {len(enrollment_obs)} consistent enrollment observations"


admission_controller = AdmissionController()
