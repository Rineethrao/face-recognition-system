import os
import json
import threading
from typing import List, Dict, Any, Tuple

import faiss  # type: ignore # pyright: ignore
import numpy as np

from app.config import settings
from app.core.utils import l2_normalize

class FAISSIndexManager:
    """
    FAISS Vector Index Manager (IndexFlatIP for Cosine Similarity).
    Handles 512D face embeddings vector search and disk persistence.
    """
    def __init__(
        self,
        dim: int = settings.EMBEDDING_DIM,
        index_path: str = str(settings.FAISS_INDEX_PATH),
        mapping_path: str = str(settings.FAISS_MAPPING_PATH)
    ):
        self.dim = dim
        self.index_path = index_path
        self.mapping_path = mapping_path
        self.lock = threading.Lock()

        self.index = faiss.IndexFlatIP(self.dim)
        self.id_map: Dict[int, Dict[str, Any]] = {}
        self.embeddings_cache: Dict[str, List[np.ndarray]] = {}

        self.load()

    def add_vectors(self, person_id: str, name: str, embeddings: np.ndarray) -> List[int]:
        with self.lock:
            if embeddings.ndim == 1:
                embeddings = np.expand_dims(embeddings, axis=0)

            normalized = l2_normalize(embeddings).astype(np.float32)
            start_id = self.index.ntotal
            num_vectors = normalized.shape[0]

            self.index.add(normalized)

            added_ids = []
            for i in range(num_vectors):
                faiss_id = start_id + i
                self.id_map[faiss_id] = {
                    "person_id": person_id,
                    "name": name,
                    "embedding": normalized[i].tolist()
                }
                # Update in-memory cache
                self.embeddings_cache.setdefault(person_id, []).append(normalized[i])
                added_ids.append(faiss_id)

            self.save()
            return added_ids

    def search(self, query_embedding: np.ndarray, k: int = 1, threshold: float = settings.RECOGNITION_SIMILARITY_THRESHOLD) -> List[Dict[str, Any]]:
        with self.lock:
            if self.index.ntotal == 0:
                return []

            if query_embedding.ndim == 1:
                query_embedding = np.expand_dims(query_embedding, axis=0)

            normalized_query = l2_normalize(query_embedding).astype(np.float32)
            distances, indices = self.index.search(normalized_query, k)

            results = []
            for sim, idx in zip(distances[0], indices[0]):
                if idx != -1 and idx in self.id_map:
                    sim_score = float(sim)
                    if sim_score >= threshold:
                        person_info = self.id_map[idx]
                        results.append({
                            "person_id": person_info["person_id"],
                            "name": person_info["name"],
                            "similarity": sim_score,
                            "faiss_id": int(idx)
                        })
            return results

    def remove_person(self, person_id: str):
        """Removes a person's vectors from memory and rebuilds the FAISS index cleanly, preserving all other people."""
        with self.lock:
            new_id_map: Dict[int, Dict[str, Any]] = {}
            new_cache: Dict[str, List[np.ndarray]] = {}
            remaining_vectors: List[np.ndarray] = []

            for old_id, info in sorted(self.id_map.items()):
                if info.get("person_id") != person_id:
                    emb = info.get("embedding")
                    if emb:
                        emb_arr = np.array(emb, dtype=np.float32)
                        new_faiss_id = len(remaining_vectors)
                        new_id_map[new_faiss_id] = info
                        remaining_vectors.append(emb_arr)
                        new_cache.setdefault(info["person_id"], []).append(emb_arr)

            new_index = faiss.IndexFlatIP(self.dim)
            if remaining_vectors:
                embeddings_matrix = np.vstack(remaining_vectors)
                normalized = l2_normalize(embeddings_matrix).astype(np.float32)
                new_index.add(normalized)

            self.index = new_index
            self.id_map = new_id_map
            self.embeddings_cache = new_cache
            self.save()

    def update_person_name(self, person_id: str, name: str):
        """Update display name for all FAISS mapping entries belonging to a person."""
        with self.lock:
            updated = False
            for info in self.id_map.values():
                if info.get("person_id") == person_id:
                    info["name"] = name
                    updated = True
            if updated:
                self.save()
            return updated

    def rebuild_index(self, db_session=None):
        """
        Rebuilds the FAISS index entirely from registered faces stored in the DB & disk.
        This avoids ID gaps and completely clears out deleted or updated profiles.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        with self.lock:
            logger.info("Rebuilding FAISS index from database and disk files...")
            new_index = faiss.IndexFlatIP(self.dim)
            new_id_map = {}
            
            close_db = False
            if db_session is None:
                from app.core.database import SessionLocal
                db_session = SessionLocal()
                close_db = True
                
            try:
                from app.models.db_models import EmbeddingModel, PersonModel
                from app.core.recognizer import arcface_recognizer
                import cv2
                
                embeddings = db_session.query(EmbeddingModel).all()
                persons = db_session.query(PersonModel).all()
                person_names = {p.person_id: p.name for p in persons}
                
                collected_embeddings = []
                temp_map_entries = []
                
                for emb in embeddings:
                    if not emb.image_path or not os.path.exists(emb.image_path):
                        logger.warning(f"Embedding image path does not exist: {emb.image_path}")
                        continue
                    
                    img = cv2.imread(emb.image_path)
                    if img is None:
                        logger.warning(f"Could not load image: {emb.image_path}")
                        continue
                        
                    try:
                        embedding = arcface_recognizer.extract_embedding(img)
                        collected_embeddings.append(embedding)
                        temp_map_entries.append({
                            "person_id": emb.person_id,
                            "name": person_names.get(emb.person_id, "Unknown"),
                            "embedding": embedding.tolist(),
                            "emb_record": emb
                        })
                    except Exception as ext_err:
                        logger.error(f"Error extracting embedding during rebuild for {emb.image_path}: {ext_err}")
                
                self.embeddings_cache = {}
                
                if collected_embeddings:
                    embeddings_matrix = np.vstack(collected_embeddings)
                    normalized = l2_normalize(embeddings_matrix).astype(np.float32)
                    new_index.add(normalized)
                    
                    for i, entry in enumerate(temp_map_entries):
                        new_id_map[i] = {
                            "person_id": entry["person_id"],
                            "name": entry["name"],
                            "embedding": entry["embedding"]
                        }
                        # Update cache
                        self.embeddings_cache.setdefault(entry["person_id"], []).append(np.array(entry["embedding"], dtype=np.float32))
                        entry["emb_record"].faiss_id = i
                    
                    db_session.commit()
                    
                self.index = new_index
                self.id_map = new_id_map
                self.save()
                logger.info(f"FAISS index successfully rebuilt with {self.index.ntotal} vectors.")
                
            except Exception as e:
                db_session.rollback()
                logger.error(f"Failed to rebuild FAISS index: {e}", exc_info=True)
            finally:
                if close_db:
                    db_session.close()

    def save(self):
        faiss.write_index(self.index, self.index_path)
        with open(self.mapping_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in self.id_map.items()}, f, indent=2)

    def load(self):
        self.embeddings_cache = {}
        if os.path.exists(self.index_path) and os.path.exists(self.mapping_path):
            try:
                self.index = faiss.read_index(self.index_path)
                with open(self.mapping_path, "r", encoding="utf-8") as f:
                    raw_map = json.load(f)
                    self.id_map = {int(k): v for k, v in raw_map.items()}
                
                # Rebuild embeddings cache from id_map
                for faiss_id, info in self.id_map.items():
                    pid = info.get("person_id")
                    emb_list = info.get("embedding")
                    if pid and emb_list:
                        emb_arr = np.array(emb_list, dtype=np.float32)
                        self.embeddings_cache.setdefault(pid, []).append(emb_arr)
            except Exception as e:
                print(f"[Warning] Error loading FAISS index: {e}. Initializing clean index.")
                self.index = faiss.IndexFlatIP(self.dim)
                self.id_map = {}
                self.embeddings_cache = {}

faiss_manager = FAISSIndexManager()
