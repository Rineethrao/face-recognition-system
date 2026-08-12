import os
import time
import threading
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
from app.api.visitors import router as visitors_router

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

def self_heal_visitor_avatars():
    """
    Startup self-healing routine for visitors:
    1. Reconstructs missing VisitorModel records from RecognitionLogModel if purged.
    2. Ensures every VisitorModel in database has a valid primary_snapshot_path.
    """
    import os
    import shutil
    import logging
    from datetime import datetime
    from app.core.database import SessionLocal
    from app.visitors.models import VisitorModel, VisitorSightingModel, VisitorFaceSampleModel
    from app.models.db_models import RecognitionLogModel
    from app.visitors.visitor_repository import get_visitor_folder_paths

    logger = logging.getLogger("VisitorSelfHealing")
    db = SessionLocal()
    try:
        # Step 1: Reconstruct missing visitor profiles from RecognitionLogModel
        vis_logs = db.query(RecognitionLogModel).filter(RecognitionLogModel.person_id.like('VISITOR-%')).all()
        by_code = {}
        for log in vis_logs:
            code = log.person_id
            if code not in by_code:
                by_code[code] = []
            by_code[code].append(log)

        reconstructed = 0
        for code, logs in by_code.items():
            existing = db.query(VisitorModel).filter(VisitorModel.visitor_code == code).first()
            if not existing:
                parts = code.split('-')
                date_key = parts[1] if len(parts) >= 2 else '20260807'
                sorted_logs = sorted(logs, key=lambda l: l.timestamp or datetime.now())
                first_log, last_log = sorted_logs[0], sorted_logs[-1]

                snap_path = None
                for l in reversed(sorted_logs):
                    if l.face_snapshot_path and os.path.exists(l.face_snapshot_path):
                        snap_path = l.face_snapshot_path
                        break

                v_dir, _, _ = get_visitor_folder_paths(date_key, code)
                dest_avatar = v_dir / 'primary_avatar.jpg'

                if snap_path:
                    try:
                        shutil.copy2(snap_path, str(dest_avatar))
                        primary_path = str(dest_avatar)
                    except Exception:
                        primary_path = snap_path
                else:
                    primary_path = None

                visitor = VisitorModel(
                    visitor_code=code,
                    date_key=date_key,
                    first_seen_at=first_log.timestamp or datetime.now(),
                    last_seen_at=last_log.timestamp or datetime.now(),
                    first_camera_id=first_log.camera_id or 'default',
                    last_camera_id=last_log.camera_id or 'default',
                    sighting_count=len(logs),
                    primary_snapshot_path=primary_path,
                    status='active'
                )
                db.add(visitor)
                db.flush()

                sighting = VisitorSightingModel(
                    visitor_id=visitor.id,
                    camera_id=last_log.camera_id or 'default',
                    track_id=str(last_log.track_id or '1'),
                    entered_at=first_log.timestamp or datetime.now(),
                    last_seen_at=last_log.timestamp or datetime.now(),
                    best_similarity=last_log.similarity or 1.0,
                    second_best_similarity=0.0,
                    match_margin=1.0,
                    identity_confidence=1.0,
                    snapshot_path=primary_path
                )
                db.add(sighting)
                reconstructed += 1

        if reconstructed > 0:
            db.commit()
            logger.info(f"Reconstructed {reconstructed} missing visitor profiles from recognition logs.")

        # Step 2: Ensure all primary_snapshot_path entries are populated and point to valid files
        visitors = db.query(VisitorModel).all()
        repaired = 0
        for v in visitors:
            if not v.primary_snapshot_path or not os.path.exists(v.primary_snapshot_path):
                img_source = None

                sighting = db.query(VisitorSightingModel).filter(
                    VisitorSightingModel.visitor_id == v.id,
                    VisitorSightingModel.snapshot_path.isnot(None)
                ).order_by(VisitorSightingModel.id.desc()).first()
                if sighting and sighting.snapshot_path and os.path.exists(sighting.snapshot_path):
                    img_source = sighting.snapshot_path

                if not img_source:
                    sample = db.query(VisitorFaceSampleModel).filter(
                        VisitorFaceSampleModel.visitor_id == v.id,
                        VisitorFaceSampleModel.snapshot_path.isnot(None)
                    ).order_by(VisitorFaceSampleModel.id.desc()).first()
                    if sample and sample.snapshot_path and os.path.exists(sample.snapshot_path):
                        img_source = sample.snapshot_path

                if not img_source:
                    log = db.query(RecognitionLogModel).filter(
                        RecognitionLogModel.person_id == v.visitor_code,
                        RecognitionLogModel.face_snapshot_path.isnot(None)
                    ).order_by(RecognitionLogModel.id.desc()).first()
                    if log and log.face_snapshot_path and os.path.exists(log.face_snapshot_path):
                        img_source = log.face_snapshot_path

                if img_source:
                    v_dir, _, _ = get_visitor_folder_paths(v.date_key, v.visitor_code)
                    dest_path = v_dir / 'primary_avatar.jpg'
                    shutil.copy2(img_source, str(dest_path))
                    v.primary_snapshot_path = str(dest_path)
                    repaired += 1

        if repaired > 0:
            db.commit()
            logger.info(f"Self-healed primary avatars for {repaired} visitor profile(s).")
    except Exception as e:
        db.rollback()
        logger.error(f"Error during visitor avatar self-healing: {e}")
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

    # Run self-healing database prune to clean manually deleted files & contaminated visitor galleries
    try:
        prune_database_orphans()
        self_heal_visitor_avatars()
        from app.visitors.visitor_repository import visitor_repository
        from app.core.database import SessionLocal
        db_heal = SessionLocal()
        try:
            visitor_repository.self_heal_and_migrate_visitor_paths(db_heal)
            visitor_repository.purge_visitor_gallery_contamination(db_heal)
        finally:
            db_heal.close()
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

    # Start Presence Duration Session Sweeper background thread
    presence_sweeper_active = True
    def _presence_sweeper_loop():
        from app.services.presence_service import presence_service
        from app.core.database import SessionLocal
        while presence_sweeper_active:
            try:
                db_sub = SessionLocal()
                try:
                    presence_service.sweep_expired_sessions(db_sub)
                    presence_service.split_midnight_sessions(db_sub)
                finally:
                    db_sub.close()
            except Exception as sweep_err:
                logger.error(f"Presence sweeper error: {sweep_err}")
            time.sleep(5)

    presence_thread = threading.Thread(target=_presence_sweeper_loop, daemon=True, name="PresenceSweeper")
    presence_thread.start()
    logger.info("Presence Session Sweeper background thread started.")

    logger.info(f"Enterprise Face Recognition Backend started. {cameras_started} camera pipeline(s) active.")
    yield

    logger.info("Shutting down application...")
    presence_sweeper_active = False
    try:
        from app.services.presence_service import presence_service
        from app.core.database import SessionLocal
        db_shut = SessionLocal()
        try:
            presence_service.close_all_sessions_on_shutdown(db_shut)
        finally:
            db_shut.close()
        logger.info("Closed active presence sessions for server shutdown.")
    except Exception as pres_err:
        logger.error(f"Error closing presence sessions on shutdown: {pres_err}")

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
app.include_router(visitors_router)

# Serve Plugin Routers
from app.projects.manager import plugin_manager
for proj_router in plugin_manager.get_project_routers():
    app.include_router(proj_router)

# Serve storage/visitors folder for visitor face crops & primary snapshots
visitors_dir = settings.STORAGE_DIR / "visitors"
os.makedirs(visitors_dir, exist_ok=True)
app.mount("/faces/visitors", StaticFiles(directory=str(visitors_dir)), name="visitor_faces")

# Serve storage/candidates folder for candidate snapshots
candidates_dir = settings.STORAGE_DIR / "candidates"
os.makedirs(candidates_dir, exist_ok=True)
app.mount("/faces/candidates", StaticFiles(directory=str(candidates_dir)), name="candidate_faces")

# Serve storage/snapshots folder for history snapshots
snapshots_dir = settings.STORAGE_DIR / "snapshots"
os.makedirs(snapshots_dir, exist_ok=True)
app.mount("/faces/snapshots", StaticFiles(directory=str(snapshots_dir)), name="snapshot_faces")

# Serve storage/faces folder as static mount for frontend access to registered face sample thumbnails
faces_dir = settings.FACES_DIR
if faces_dir.exists():
    app.mount("/faces", StaticFiles(directory=str(faces_dir)), name="faces")

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
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", SPAStaticFiles(directory=str(frontend_dir), html=True), name="frontend")
