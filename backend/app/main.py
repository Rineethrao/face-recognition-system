import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.database import init_db
from app.core.stream import camera_manager
from app.services.camera_service import resolve_camera_source, camera_registry
from app.services.detection_service import detection_service

from app.api.camera import router as camera_router
from app.api.registration import router as registration_router
from app.api.recognition import router as recognition_router
from app.api.health import router as health_router
from app.api.websocket import router as websocket_router
from app.api.candidate import router as candidate_router
from app.api.person_gallery import router as person_gallery_router
from app.api.history import router as history_router
from app.api.browser_camera import router as browser_camera_router
from app.api.reports import router as reports_router

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("App")

def prune_database_orphans():
    """
    Startup self-healing routine:
    - Deletes database embedding records if their corresponding disk image file is missing.
    - Deletes person records if they have 0 associated embeddings remaining.
    - Rebuilds the FAISS index to ensure it is in perfect sync.
    """
    import os
    import logging
    from app.core.database import SessionLocal
    from app.models.db_models import PersonModel, EmbeddingModel
    from app.core.faiss_index import faiss_manager
    
    logger = logging.getLogger("DatabaseCleanup")
    logger.info("Running database self-healing and orphan pruning routine...")
    
    db = SessionLocal()
    try:
        # 1. Prune missing embeddings
        embeddings = db.query(EmbeddingModel).all()
        pruned_embeddings_count = 0
        for emb in embeddings:
            if not emb.image_path or not os.path.exists(emb.image_path):
                db.delete(emb)
                pruned_embeddings_count += 1
        
        if pruned_embeddings_count > 0:
            db.commit()
            logger.info(f"Pruned {pruned_embeddings_count} orphaned embedding records (missing files on disk).")
            
        # 2. Prune persons with 0 embeddings
        persons = db.query(PersonModel).all()
        pruned_persons_count = 0
        for person in persons:
            if len(person.embeddings) == 0:
                db.delete(person)
                pruned_persons_count += 1
                
        if pruned_persons_count > 0:
            db.commit()
            logger.info(f"Pruned {pruned_persons_count} person profiles with 0 embeddings.")
            
        # 3. Rebuild FAISS index
        faiss_manager.rebuild_index(db)
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during database self-healing: {e}", exc_info=True)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Database Tables...")
    init_db()

    # Copy uploaded logo from artifacts to frontend asset paths
    try:
        import shutil
        logo_src = r"C:\Users\user\.gemini\antigravity-ide\brain\fa62efac-e4b0-45c5-b006-6bd75da1afe9\media__1785665098224.png"
        if os.path.exists(logo_src):
            dest1_dir = BASE_DIR.parent / "frontend_src" / "src" / "assets"
            os.makedirs(dest1_dir, exist_ok=True)
            shutil.copy2(logo_src, dest1_dir / "logo.png")
            
            dest2_dir = BASE_DIR.parent / "frontend" / "assets"
            os.makedirs(dest2_dir, exist_ok=True)
            shutil.copy2(logo_src, dest2_dir / "logo.png")
            logger.info("Successfully copied custom logo to frontend assets.")
    except Exception as logo_err:
        logger.error(f"Failed to copy logo: {logo_err}")

    # Run self-healing database prune to clean manually deleted files
    try:
        prune_database_orphans()
    except Exception as cleanup_err:
        logger.error(f"Failed to complete database pruning on startup: {cleanup_err}")

    # Synchronize camera registry DB table
    try:
        from app.services.camera.camera_registry import camera_registry
        camera_registry.sync_db_from_json()
    except Exception as cam_sync_err:
        logger.error(f"Camera DB sync warning: {cam_sync_err}")

    # ── New Pipeline: Start a CameraWorker per enabled camera ────────────────
    # Each camera gets its own isolated Capture + Detection + Recognition + Streaming threads.
    cameras_started = 0
    try:
        from app.services.camera.camera_registry import camera_registry
        from app.services.camera.camera_worker import CameraWorker
        from app.models.schemas import CameraConfigModel

        all_cams = camera_registry.load_cameras_from_db()
        enabled_cams = [c for c in all_cams if c.enabled]

        if enabled_cams:
            logger.info(f"Starting {len(enabled_cams)} enabled camera pipeline(s)...")
            for cam_config in enabled_cams:
                try:
                    worker = CameraWorker(cam_config)
                    if worker.start():
                        with camera_registry.lock:
                            camera_registry.workers[cam_config.camera_id] = worker
                        cameras_started += 1
                        logger.info(f"  ✓ Camera [{cam_config.camera_id}] '{cam_config.name}' pipeline started.")
                    else:
                        logger.warning(f"  ✗ Camera [{cam_config.camera_id}] '{cam_config.name}' failed to start.")
                except Exception as cam_err:
                    logger.error(f"  ✗ Error starting camera [{cam_config.camera_id}]: {cam_err}")
        else:
            logger.warning("No enabled cameras found in cameras.json.")

    except Exception as pipeline_err:
        logger.error(f"New pipeline startup failed: {pipeline_err}. Falling back to legacy mode.")

    # ── Legacy Fallback: Single-camera detection_service ─────────────────────
    # ONLY used when no CameraWorker started. Never open the same RTSP source
    # twice — dual VideoCapture on one stream causes FFmpeg SIGSEGV crashes.
    if cameras_started == 0:
        src, name, rotation = resolve_camera_source()
        if src and str(src) != "0":
            logger.info(f"Auto-starting enabled CCTV camera: '{name}' ({src}) | Rotation: {rotation}°")
            camera_manager.source = camera_manager._parse_source(src)
            camera_manager.set_rotation(rotation)
            if camera_manager.start():
                detection_service.start_recognition()
        else:
            logger.info("No enabled RTSP/CCTV streams configured. Webcams will be acquired on-demand by the browser.")
    else:
        logger.info(
            f"CameraWorker pipeline active ({cameras_started} cam(s)). "
            "Skipping legacy camera_manager to avoid dual RTSP capture."
        )

    logger.info(f"Enterprise Face Recognition Backend started. {cameras_started} camera pipeline(s) active.")
    yield

    logger.info("Shutting down application...")
    # Stop all camera workers
    try:
        from app.services.camera.camera_registry import camera_registry
        with camera_registry.lock:
            workers = dict(camera_registry.workers)
            camera_registry.workers.clear()
        for wid, worker in workers.items():
            try:
                worker.stop()
            except Exception as stop_err:
                logger.warning(f"Error stopping worker {wid}: {stop_err}")
    except Exception:
        pass

    try:
        detection_service.stop_recognition()
    except Exception:
        pass
    try:
        camera_manager.stop()
    except Exception:
        pass


# Initialize FastAPI Application
app = FastAPI(
    title=settings.APP_NAME,
    description="Enterprise Multi-Camera AI CCTV Face Recognition & Candidate Registration Platform",
    version="2.0.0",
    lifespan=lifespan
)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Core API Routers
app.include_router(health_router)
app.include_router(camera_router)
app.include_router(registration_router)
app.include_router(recognition_router)
app.include_router(websocket_router)
app.include_router(candidate_router)
app.include_router(person_gallery_router)
app.include_router(history_router)
app.include_router(browser_camera_router)
app.include_router(reports_router)

# Serve Plugin Routers
from app.projects.manager import plugin_manager
for proj_router in plugin_manager.get_project_routers():
    app.include_router(proj_router)

# Serve storage/faces folder as static mount for frontend access to face sample thumbnails
faces_dir = settings.FACES_DIR
if faces_dir.exists():
    app.mount("/faces", StaticFiles(directory=str(faces_dir)), name="faces")

# Serve storage/candidates folder for candidate snapshots
candidates_dir = settings.STORAGE_DIR / "candidates"
os.makedirs(candidates_dir, exist_ok=True)
app.mount("/faces/candidates", StaticFiles(directory=str(candidates_dir)), name="candidate_faces")

# Serve storage/snapshots folder for history snapshots
snapshots_dir = settings.STORAGE_DIR / "snapshots"
os.makedirs(snapshots_dir, exist_ok=True)
app.mount("/faces/snapshots", StaticFiles(directory=str(snapshots_dir)), name="snapshot_faces")

# Serve Frontend Web Application (with SPA fallback support)
from app.config import BASE_DIR
from starlette.responses import FileResponse, Response
import os

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        try:
            response = await super().get_response(path, scope)
            if response.status_code == 404:
                filename = path.split("/")[-1]
                if "." not in filename and filename != "":
                    index_path = os.path.join(self.directory, "index.html")
                    if os.path.exists(index_path):
                        return FileResponse(index_path, status_code=200)
            return response
        except Exception as e:
            if "." in path.split("/")[-1]:
                raise e
            index_path = os.path.join(self.directory, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path, status_code=200)
            raise e

frontend_dir = BASE_DIR.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", SPAStaticFiles(directory=str(frontend_dir), html=True), name="frontend")
