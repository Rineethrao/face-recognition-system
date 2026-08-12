import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from app.config import settings


class AdmissionController:
    """
    Gatekeeper for NEW visitor identity creation.

    A visitor is created ONLY when we have collected enough distinct BEST-QUALITY
    face frames (default 6). Fewer / weaker frames => stay in COLLECTING and
    do NOT save a visitor profile (prevents junk + duplicate IDs).
    """

    def _select_best_quality_frames(
        self,
        observations: List[Dict[str, Any]],
        min_gap: float,
    ) -> List[Dict[str, Any]]:
        """
        Keep only enrollment-quality samples, then enforce a minimum time gap
        so near-duplicate frames from the same instant do not count as 6.
        Prefer highest quality when choosing among close timestamps.
        """
        enrollment = [
            obs for obs in observations
            if obs.get("quality_result")
            and getattr(obs["quality_result"], "usable_for_new_identity", False)
            and obs.get("embedding") is not None
            and obs.get("crop") is not None
        ]
        if not enrollment:
            return []

        # Newest-first within same quality — then sort by quality desc for selection
        enrollment_sorted = sorted(
            enrollment,
            key=lambda o: (float(o.get("quality_score", 0.0)), float(o.get("timestamp", 0.0))),
            reverse=True,
        )

        selected: List[Dict[str, Any]] = []
        for obs in enrollment_sorted:
            ts = float(obs.get("timestamp", 0.0))
            if any(abs(ts - float(s.get("timestamp", 0.0))) < min_gap for s in selected):
                continue
            selected.append(obs)

        # Chronological for span / consistency checks
        selected.sort(key=lambda o: float(o.get("timestamp", 0.0)))
        return selected

    def evaluate_admission(
        self,
        track_id: str,
        camera_id: str,
        observations: List[Dict[str, Any]],
        best_candidate: Optional[Dict[str, Any]] = None,
        registered_match: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, str]:
        """
        Returns (is_approved, decision_code, reason_detail).
        decision_code: 'ADMISSION_APPROVED', 'COLLECTING', 'PENDING', 'EXISTING_*'
        """
        min_obs = int(getattr(settings, 'VISITOR_MIN_OBSERVATIONS_FOR_NEW', 6))
        min_avatar = int(getattr(settings, 'VISITOR_MIN_AVATAR_FRAMES_FOR_NEW', 2))
        min_mean_q = float(getattr(settings, 'VISITOR_MIN_MEAN_ENROLLMENT_QUALITY', 0.62))
        min_best_q = float(getattr(settings, 'VISITOR_MIN_BEST_FRAME_QUALITY', 0.68))
        match_high = getattr(settings, 'VISITOR_MATCH_HIGH_THRESHOLD', 0.48)
        match_low = getattr(settings, 'VISITOR_MATCH_LOW_THRESHOLD', 0.40)
        consistency_thresh = getattr(settings, 'VISITOR_WITHIN_TRACK_CONSISTENCY_THRESH', 0.58)
        min_span = float(getattr(settings, 'VISITOR_MIN_TRACK_SPAN_SECONDS', 1.20))
        min_gap = float(getattr(settings, 'VISITOR_MIN_SAMPLE_GAP_SECONDS', 0.20))

        # 1. Registered match check
        if registered_match and registered_match.get("confidence", 0.0) >= getattr(
            settings, 'RECOGNITION_CONFIDENCE_THRESHOLD', 0.55
        ):
            return False, "EXISTING_REGISTERED", f"Matches registered person {registered_match.get('person_id')}"

        # 2. Near-match visitor => never create a duplicate ID
        if best_candidate:
            top_sim = float(best_candidate.get("similarity", 0.0))
            if top_sim >= match_high:
                return False, "EXISTING_VISITOR", (
                    f"Matches existing visitor {best_candidate.get('visitor_code')} with sim={top_sim:.3f}"
                )
            if top_sim >= match_low:
                return False, "PENDING", (
                    f"Near-match to {best_candidate.get('visitor_code')} "
                    f"(sim={top_sim:.3f}) — refusing new ID"
                )

        # 3. Collect distinct BEST-QUALITY enrollment frames only
        best_frames = self._select_best_quality_frames(observations, min_gap=min_gap)
        if len(best_frames) < min_obs:
            return False, "COLLECTING", (
                f"Need {min_obs} best-quality frames before saving visitor "
                f"(have {len(best_frames)})"
            )

        # Use the top N by quality for the approval set
        ranked = sorted(best_frames, key=lambda o: float(o.get("quality_score", 0.0)), reverse=True)
        approval_set = ranked[:min_obs]
        approval_set.sort(key=lambda o: float(o.get("timestamp", 0.0)))

        qualities = [float(o.get("quality_score", 0.0)) for o in approval_set]
        mean_q = sum(qualities) / len(qualities)
        best_q = max(qualities)

        if best_q < min_best_q:
            return False, "COLLECTING", (
                f"Best frame quality too low ({best_q:.3f} < {min_best_q:.3f}) — waiting for clearer face"
            )
        if mean_q < min_mean_q:
            return False, "COLLECTING", (
                f"Mean enrollment quality too low ({mean_q:.3f} < {min_mean_q:.3f})"
            )

        avatar_count = sum(
            1 for o in approval_set
            if getattr(o.get("quality_result"), "usable_for_primary_avatar", False)
        )
        if avatar_count < min_avatar:
            return False, "COLLECTING", (
                f"Need {min_avatar} primary-avatar-quality frames (have {avatar_count}) — not saving yet"
            )

        timestamps = [float(o.get("timestamp", 0.0)) for o in approval_set]
        time_span = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0
        if time_span < min_span:
            return False, "COLLECTING", (
                f"Track duration too short ({time_span:.2f}s < {min_span:.2f}s) — keep collecting"
            )

        # 4. Within-track embedding consistency
        embeddings = [o["embedding"] for o in approval_set]
        min_pair_sim = 1.0
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                e1 = np.array(embeddings[i], dtype=np.float32)
                e2 = np.array(embeddings[j], dtype=np.float32)
                sim = float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-6))
                min_pair_sim = min(min_pair_sim, sim)
                if sim < consistency_thresh:
                    return False, "COLLECTING", (
                        f"Within-track embeddings inconsistent "
                        f"(min pair sim={min_pair_sim:.3f} < {consistency_thresh})"
                    )

        return True, "ADMISSION_APPROVED", (
            f"Approved with {len(approval_set)} best-quality frames "
            f"(mean_q={mean_q:.3f}, best_q={best_q:.3f}, avatar={avatar_count})"
        )


admission_controller = AdmissionController()
