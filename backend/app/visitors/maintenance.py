"""
maintenance.py — Offline Maintenance & Duplicate Analysis Engine

Operates strictly in REPORT-ONLY mode outside the live frame inference loop.
Analyzes active visitor galleries to detect:
1. Potential duplicate visitor clusters (e.g. Visitors 9, 12, 13).
2. Visitors corresponding to existing Registered Persons (e.g. Visitors 7, 10, 19).
3. Polluted visitor profiles containing outlier face samples (e.g. Visitor 5).
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.config import settings
from app.core.utils import l2_normalize
from app.visitors.models import VisitorModel, VisitorFaceSampleModel
from app.core.faiss_index import faiss_manager

logger = logging.getLogger(__name__)


class VisitorDuplicateAnalyzer:
    """
    Offline Maintenance Analyzer.
    Provides diagnostic reports for database consolidation without live mutation.
    """

    def analyze_duplicates(self, db: Session) -> Dict[str, Any]:
        """
        Scans all active visitors and generates a full diagnostic report containing:
        - duplicate_visitor_clusters
        - registered_person_matches
        - contaminated_profiles
        """
        visitors = db.query(VisitorModel).filter(VisitorModel.status == 'active').all()
        if not visitors:
            return {
                "status": "success",
                "total_active_visitors": 0,
                "duplicate_clusters": [],
                "registered_matches": [],
                "contaminated_profiles": []
            }

        # Build in-memory core embeddings map for active visitors
        visitor_embeddings: Dict[int, List[np.ndarray]] = {}
        visitor_meta: Dict[int, Dict[str, Any]] = {}

        for v in visitors:
            samples = db.query(VisitorFaceSampleModel).filter(
                VisitorFaceSampleModel.visitor_id == v.id
            ).all()

            embs = []
            for s in samples:
                if s.embedding_blob:
                    vec = np.frombuffer(s.embedding_blob, dtype=np.float32)
                    embs.append(l2_normalize(vec))

            if embs:
                visitor_embeddings[v.id] = embs
                visitor_meta[v.id] = {
                    "id": v.id,
                    "visitor_code": v.visitor_code,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "sample_count": len(embs),
                    "primary_snapshot": v.primary_snapshot_path
                }

        duplicate_threshold = getattr(settings, 'VISITOR_DUPLICATE_FLAG_THRESHOLD', 0.44)

        # 1. Detect Duplicate Visitor Clusters
        clusters = []
        visited = set()
        v_ids = list(visitor_embeddings.keys())

        for i in range(len(v_ids)):
            vid_a = v_ids[i]
            if vid_a in visited:
                continue

            embs_a = visitor_embeddings[vid_a]
            cluster = [visitor_meta[vid_a]]

            for j in range(i + 1, len(v_ids)):
                vid_b = v_ids[j]
                if vid_b in visited:
                    continue

                embs_b = visitor_embeddings[vid_b]

                # Pairwise max similarity between Visitor A and Visitor B
                max_sim = 0.0
                for ea in embs_a:
                    for eb in embs_b:
                        sim = float(np.dot(ea, eb))
                        if sim > max_sim:
                            max_sim = sim

                if max_sim >= duplicate_threshold:
                    cluster.append({
                        **visitor_meta[vid_b],
                        "similarity_to_primary": round(max_sim, 4)
                    })
                    visited.add(vid_b)

            if len(cluster) > 1:
                visited.add(vid_a)
                clusters.append({
                    "primary_visitor": visitor_meta[vid_a]["visitor_code"],
                    "member_count": len(cluster),
                    "members": cluster
                })

        # 2. Registered Person Reconciliation Analysis
        registered_matches = []
        registered_threshold = getattr(settings, 'REGISTERED_CONFIRMED_THRESHOLD', 0.50)

        if faiss_manager.index.ntotal > 0:
            for vid, embs in visitor_embeddings.items():
                meta = visitor_meta[vid]
                best_match = None
                highest_sim = 0.0

                for emb in embs:
                    hits = faiss_manager.search(query_embedding=emb, k=5, threshold=0.35)
                    for hit in hits:
                        pid = hit["person_id"]
                        name = hit["name"]
                        cached_embs = faiss_manager.embeddings_cache.get(pid, [])
                        for reg_e in cached_embs:
                            sim = float(np.dot(l2_normalize(emb), l2_normalize(reg_e)))
                            if sim > highest_sim:
                                highest_sim = sim
                                best_match = {"person_id": pid, "name": name}

                if best_match and highest_sim >= registered_threshold:
                    registered_matches.append({
                        "visitor_id": vid,
                        "visitor_code": meta["visitor_code"],
                        "matched_registered_id": best_match["person_id"],
                        "registered_name": best_match["name"],
                        "similarity": round(highest_sim, 4)
                    })

        # 3. Profile Contamination Analysis (Outlier Sample Detection)
        contaminated_profiles = []

        for vid, embs in visitor_embeddings.items():
            if len(embs) < 3:
                continue

            meta = visitor_meta[vid]
            # Calculate pairwise matrix
            n = len(embs)
            sim_matrix = np.zeros((n, n), dtype=np.float32)
            for i in range(n):
                for j in range(n):
                    sim_matrix[i, j] = float(np.dot(embs[i], embs[j]))

            mean_sims = [float(np.mean(sim_matrix[i])) for i in range(n)]
            min_mean = min(mean_sims)
            outlier_idx = int(np.argmin(mean_sims))

            if min_mean < 0.40:
                contaminated_profiles.append({
                    "visitor_id": vid,
                    "visitor_code": meta["visitor_code"],
                    "total_samples": n,
                    "lowest_cohesion_sample_idx": outlier_idx,
                    "mean_cohesion_score": round(min_mean, 4),
                    "reason": "Profile contains outlier embedding with low cohesion"
                })

        return {
            "status": "success",
            "total_active_visitors": len(visitors),
            "duplicate_clusters_count": len(clusters),
            "duplicate_clusters": clusters,
            "registered_matches_count": len(registered_matches),
            "registered_matches": registered_matches,
            "contaminated_profiles_count": len(contaminated_profiles),
            "contaminated_profiles": contaminated_profiles
        }


visitor_duplicate_analyzer = VisitorDuplicateAnalyzer()
