import os
from fastapi import APIRouter
from app.config import settings
from app.core.stream import camera_manager
from app.core.faiss_index import faiss_manager
from app.models.schemas import APIResponse

router = APIRouter(tags=["Health & Status"])

@router.get("/health", response_model=APIResponse)
def health_check():
    """Returns system health, ONNX models availability, FAISS index status, and camera connection status."""
    import os
    from app.core.database import SessionLocal
    from app.models.db_models import PersonModel, EmbeddingModel
    
    detector_exists = os.path.exists(settings.DETECTOR_MODEL_PATH)
    recognizer_exists = os.path.exists(settings.RECOGNITION_MODEL_PATH)

    db = SessionLocal()
    diagnostics = {}
    try:
        persons = db.query(PersonModel).all()
        embeddings = db.query(EmbeddingModel).all()
        
        diagnostics = {
            "total_persons_in_db": len(persons),
            "total_embeddings_in_db": len(embeddings),
            "embedding_paths_check": []
        }
        
        # Check first 10 embeddings as samples
        for emb in embeddings[:10]:
            path_exists = os.path.exists(emb.image_path) if emb.image_path else False
            diagnostics["embedding_paths_check"].append({
                "person_id": emb.person_id,
                "image_path": emb.image_path,
                "exists_on_disk": path_exists,
                "resolved_absolute": os.path.abspath(emb.image_path) if emb.image_path else None
            })
    except Exception as db_err:
        diagnostics = {"error": str(db_err)}
    finally:
        db.close()

    health_status = {
        "status": "healthy" if detector_exists and recognizer_exists else "degraded",
        "models": {
            "scrfd_detector": "available" if detector_exists else "missing",
            "arcface_recognizer": "available" if recognizer_exists else "missing"
        },
        "camera": {
            "is_active": camera_manager.is_active(),
            "source": str(camera_manager.source)
        },
        "faiss": {
            "total_registered_vectors": faiss_manager.index.ntotal,
            "dimension": faiss_manager.dim,
            "cached_persons": list(faiss_manager.embeddings_cache.keys()),
            "id_map_size": len(faiss_manager.id_map)
        },
        "diagnostics": diagnostics
    }

    return APIResponse(
        status="success",
        message="System health status retrieved.",
        data=health_status
    )
