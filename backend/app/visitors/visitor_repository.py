import os
import cv2
import json
import uuid
import logging
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from sqlalchemy.orm import Session

from app.config import settings
from app.visitors.models import VisitorModel, VisitorFaceSampleModel, VisitorSightingModel, VisitorVisitModel
from app.models.db_models import PersonModel, EmbeddingModel, PersonImageModel


logger = logging.getLogger(__name__)

def get_operational_date_key(dt: Optional[datetime] = None) -> str:
    """
    Computes business date key (YYYY-MM-DD) based on configured OPERATIONAL_DAY_START_HOUR.
    Overnight hours prior to start_hour belong to previous calendar day.
    """
    if dt is None:
        dt = datetime.now()
    start_hour = getattr(settings, 'VISITOR_OPERATIONAL_DAY_START_HOUR', 0)
    if dt.hour < start_hour:
        op_dt = dt - timedelta(days=1)
    else:
        op_dt = dt
    return op_dt.strftime("%Y-%m-%d")


def get_visitor_root() -> Path:
    """Returns root storage directory for visitors (storage/visitors/)."""
    root_dir = settings.STORAGE_DIR / "visitors"
    root_dir.mkdir(parents=True, exist_ok=True)
    return root_dir


def get_visitor_identity_folder(visitor_code: str, creation_date: Optional[str] = None) -> Path:
    """
    Returns canonical identity folder path: storage/visitors/YYYY-MM-DD/VISITOR_XXX/
    If creation_date is not provided, defaults to current operational date key.
    """
    if not creation_date:
        creation_date = get_operational_date_key()
    
    # Normalize 8-digit date strings (e.g. '20260810' -> '2026-08-10')
    if len(creation_date) == 8 and creation_date.isdigit():
        creation_date = f"{creation_date[:4]}-{creation_date[4:6]}-{creation_date[6:8]}"

    identity_dir = get_visitor_root() / creation_date / visitor_code
    identity_dir.mkdir(parents=True, exist_ok=True)
    return identity_dir


def get_visitor_samples_folder(visitor_code: str, creation_date: Optional[str] = None) -> Path:
    """Returns samples/ directory for high-quality recognition face samples."""
    samples_dir = get_visitor_identity_folder(visitor_code, creation_date) / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    return samples_dir


def get_visitor_sightings_folder(visitor_code: str, creation_date: Optional[str] = None) -> Path:
    """Returns sightings/ directory for CCTV observation images."""
    sightings_dir = get_visitor_identity_folder(visitor_code, creation_date) / "sightings"
    sightings_dir.mkdir(parents=True, exist_ok=True)
    return sightings_dir


def get_visitor_folder_paths(date_key: str, visitor_code: str) -> Tuple[Path, Path, Path]:
    """
    Centralized wrapper returning (visitor_dir, samples_dir, sightings_dir).
    All filesystem path construction must go through these helpers.
    """
    v_dir = get_visitor_identity_folder(visitor_code, date_key)
    s_dir = get_visitor_samples_folder(visitor_code, date_key)
    c_dir = get_visitor_sightings_folder(visitor_code, date_key)
    return v_dir, s_dir, c_dir


class VisitorRepository:
    """Repository for CRUD operations on Visitor, Face Sample, and Sighting Session models."""

    def generate_next_visitor_code(self, db: Session, date_key: Optional[str] = None) -> str:
        """
        Generates global monotonically increasing sequential visitor code (e.g. VISITOR_001, VISITOR_002).
        Sequence is global across all dates and does NOT reset daily.
        Inspects DB, sequence JSON files, and disk directories to determine highest global sequence.
        """
        import re
        max_seq = 0
        pattern = re.compile(r'VISITOR[-_](?:(?:\d{8})[-_])?(\d+)', re.IGNORECASE)

        # 1. Check persistent sequence tracker JSON file
        root_dir = get_visitor_root()
        seq_file = root_dir / "_sequence.json"
        if seq_file.exists():
            try:
                with open(seq_file, "r", encoding="utf-8") as f:
                    seq_data = json.load(f)
                    max_seq = max(max_seq, int(seq_data.get("max_seq", 0)))
            except Exception:
                pass

        # 2. Check all DB records in visitors table across all dates
        visitors = db.query(VisitorModel.visitor_code).all()
        for (v_code,) in visitors:
            if not v_code:
                continue
            m = pattern.search(str(v_code))
            if m:
                try:
                    seq_num = int(m.group(1))
                    if seq_num > max_seq:
                        max_seq = seq_num
                except Exception:
                    pass

        # 3. Check all disk directories across storage/visitors/
        if root_dir.exists():
            for d in root_dir.iterdir():
                if d.is_dir():
                    # Either date folder (YYYY-MM-DD or YYYYMMDD) or legacy folder
                    m_root = pattern.search(d.name)
                    if m_root:
                        try:
                            seq_num = int(m_root.group(1))
                            if seq_num > max_seq:
                                max_seq = seq_num
                        except Exception:
                            pass
                    for sub in d.iterdir():
                        if sub.is_dir():
                            m_sub = pattern.search(sub.name)
                            if m_sub:
                                try:
                                    seq_num = int(m_sub.group(1))
                                    if seq_num > max_seq:
                                        max_seq = seq_num
                                except Exception:
                                    pass

        next_seq = max_seq + 1

        # Save updated max_seq to persistent tracker file
        try:
            with open(seq_file, "w", encoding="utf-8") as f:
                json.dump({"max_seq": next_seq, "updated_at": str(datetime.now())}, f, indent=2)
        except Exception as e:
            logger.warning(f"[VisitorRepo] Failed to write sequence file: {e}")

        return f"VISITOR_{next_seq:03d}"

    def record_visit(self, db: Session, visitor_id: int, date_key: str, camera_id: str = "default") -> VisitorVisitModel:
        """
        Creates or updates a daily visit session in visitor_visits for today's date_key.
        Ensures persistent visitor identity retains multiple daily visit records.
        """
        from app.visitors.models import VisitorVisitModel
        now = datetime.now()

        # Normalize date key format to YYYY-MM-DD
        if len(date_key) == 8 and date_key.isdigit():
            date_key = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}"

        visit = db.query(VisitorVisitModel).filter(
            VisitorVisitModel.visitor_id == visitor_id,
            VisitorVisitModel.date_key == date_key
        ).first()

        if not visit:
            visit = VisitorVisitModel(
                visitor_id=visitor_id,
                date_key=date_key,
                first_seen_at=now,
                last_seen_at=now,
                duration_seconds=0.0,
                sighting_count=1,
                status='active'
            )
            db.add(visit)
        else:
            visit.last_seen_at = now
            visit.sighting_count = (visit.sighting_count or 0) + 1
            if visit.first_seen_at:
                visit.duration_seconds = max(0.0, (now - visit.first_seen_at).total_seconds())

        db.commit()
        db.refresh(visit)
        return visit

    def create_visitor(
        self,
        db: Session,
        camera_id: str,
        primary_crop: Optional[np.ndarray] = None,
        date_key: Optional[str] = None
    ) -> VisitorModel:
        """Creates a new visitor profile record in the database."""
        now = datetime.now()
        if not date_key:
            date_key = get_operational_date_key(now)

        code = self.generate_next_visitor_code(db, date_key)
        v_dir, _, _ = get_visitor_folder_paths(date_key, code)

        primary_snapshot_path = None
        if primary_crop is not None and primary_crop.size > 0:
            snapshot_full_path = v_dir / "primary_avatar.jpg"
            cv2.imwrite(str(snapshot_full_path), primary_crop)
            primary_snapshot_path = str(snapshot_full_path)

        visitor = VisitorModel(
            visitor_code=code,
            date_key=date_key,
            created_date=date_key,
            first_seen_at=now,
            last_seen_at=now,
            first_camera_id=camera_id,
            last_camera_id=camera_id,
            sighting_count=1,
            primary_snapshot_path=primary_snapshot_path,
            status='active'
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

        # Record initial visit session
        self.record_visit(db, visitor.id, date_key, camera_id)

        logger.info(f"[VisitorRepo] Created new visitor record: {visitor.visitor_code} (ID: {visitor.id})")
        return visitor

    def add_face_sample(
        self,
        db: Session,
        visitor_id: int,
        embedding: np.ndarray,
        camera_id: str,
        quality_score: float,
        yaw: float,
        pitch: float,
        blur_score: float,
        crop_img: Optional[np.ndarray] = None,
        gallery_eligible: bool = True
    ) -> VisitorFaceSampleModel:
        """Stores a high-quality 512-D face embedding sample in samples/ directory."""
        now = datetime.now()
        emb_bytes = embedding.astype(np.float32).tobytes()

        visitor = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
        if not visitor:
            raise ValueError(f"Visitor {visitor_id} not found")

        creation_date = visitor.created_date or visitor.date_key or get_operational_date_key(now)
        v_dir, samples_dir, _ = get_visitor_folder_paths(creation_date, visitor.visitor_code)

        # Enforce max sample limit per visitor (max 5-8)
        existing_samples = db.query(VisitorFaceSampleModel).filter(
            VisitorFaceSampleModel.visitor_id == visitor_id
        ).order_by(VisitorFaceSampleModel.id.asc()).all()

        # ── VISITOR PROFILE GUARD CONSISTENCY CHECK ──
        if existing_samples and embedding is not None:
            from app.core.utils import l2_normalize
            norm_new = l2_normalize(embedding)
            sims = []
            for s in existing_samples:
                if s.embedding_blob:
                    e_vec = l2_normalize(np.frombuffer(s.embedding_blob, dtype=np.float32))
                    sims.append(float(np.dot(norm_new, e_vec.T)))
            if sims:
                max_sim = max(sims)
                profile_thresh = getattr(settings, 'VISITOR_PROFILE_UPDATE_THRESHOLD', 0.65)
                if max_sim < profile_thresh:
                    logger.warning(
                        f"[PROFILE_GUARD_BLOCKED] Rejected inconsistent face sample for visitor {visitor.visitor_code} (ID: {visitor_id}). "
                        f"Max similarity {max_sim:.3f} < {profile_thresh}. Multi-person contamination prevented!"
                    )
                    return existing_samples[0]

        max_samples = getattr(settings, 'VISITOR_MAX_SAMPLES', 5)
        sample_idx = len(existing_samples) + 1

        sample = None
        snapshot_path = None

        if crop_img is not None and crop_img.size > 0:
            if len(existing_samples) < max_samples:
                filename = f"sample_{sample_idx:02d}_{int(now.timestamp())}.jpg"
                full_path = samples_dir / filename
                cv2.imwrite(str(full_path), crop_img)
                snapshot_path = str(full_path)
            else:
                lowest = min(existing_samples, key=lambda s: s.quality_score or 0.0)
                sample = lowest
                if quality_score > (lowest.quality_score or 0.0):
                    filename = f"sample_replace_{int(now.timestamp())}.jpg"
                    full_path = samples_dir / filename
                    cv2.imwrite(str(full_path), crop_img)
                    snapshot_path = str(full_path)
                    lowest.embedding_blob = emb_bytes
                    lowest.quality_score = quality_score
                    lowest.snapshot_path = snapshot_path
                    lowest.timestamp = now
                    lowest.gallery_eligible = gallery_eligible
                    db.commit()

        if sample is None and (crop_img is None or len(existing_samples) < max_samples):
            sample = VisitorFaceSampleModel(
                visitor_id=visitor_id,
                embedding_blob=emb_bytes,
                camera_id=camera_id,
                timestamp=now,
                quality_score=quality_score,
                yaw=yaw,
                pitch=pitch,
                blur_score=blur_score,
                snapshot_path=snapshot_path,
                gallery_eligible=gallery_eligible
            )
            db.add(sample)
            db.commit()
            db.refresh(sample)

        if sample is None and existing_samples:
            sample = existing_samples[0]

        # Dynamic primary avatar update if crop meets avatar criteria
        if crop_img is not None and crop_img.size > 0:
            if abs(yaw) <= 0.18 and abs(pitch) <= 0.15 and quality_score >= 0.60:
                primary_avatar_path = v_dir / "primary_avatar.jpg"

                cv2.imwrite(str(primary_avatar_path), crop_img)
                visitor.primary_snapshot_path = str(primary_avatar_path)
                visitor.last_seen_at = now
                db.commit()

        return sample

    def create_or_update_sighting(
        self,
        db: Session,
        visitor_id: int,
        camera_id: str,
        track_id: str,
        best_sim: float,
        second_best_sim: float,
        margin: float,
        confidence: float,
        crop_img: Optional[np.ndarray] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> VisitorSightingModel:
        """Creates or updates an active CCTV sighting session in sightings/ directory."""
        now = datetime.now()
        visitor = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
        date_key = get_operational_date_key(now)
        creation_date = visitor.created_date if (visitor and visitor.created_date) else (visitor.date_key if visitor else date_key)
        v_code = visitor.visitor_code if visitor else f"Visitor_{visitor_id}"

        sightings_dir = get_visitor_sightings_folder(v_code, creation_date)

        # Record/update daily visit tracking
        if visitor:
            self.record_visit(db, visitor_id, date_key, camera_id)

        # Check for recent active sighting on the same camera (within last 3 minutes)
        recent = db.query(VisitorSightingModel).filter(
            VisitorSightingModel.visitor_id == visitor_id,
            VisitorSightingModel.camera_id == camera_id
        ).order_by(VisitorSightingModel.id.desc()).first()

        if recent and (now - recent.last_seen_at).total_seconds() < 180.0:
            recent.last_seen_at = now
            recent.best_similarity = max(recent.best_similarity, best_sim)
            recent.second_best_similarity = max(recent.second_best_similarity, second_best_sim)
            recent.match_margin = max(recent.match_margin, margin)
            recent.identity_confidence = max(recent.identity_confidence, confidence)

            if crop_img is not None and crop_img.size > 0 and (recent.snapshot_path is None or confidence > recent.identity_confidence):
                filename = f"sighting_{camera_id}_{int(now.timestamp())}.jpg"
                path = sightings_dir / filename
                cv2.imwrite(str(path), crop_img)
                recent.snapshot_path = str(path)

            if metadata:
                recent.metadata_json = json.dumps(metadata)

            if visitor:
                visitor.last_seen_at = now
                visitor.last_camera_id = camera_id

            db.commit()
            db.refresh(recent)
            sighting = recent


            # Update presence tracking for active visitor sighting session
            if visitor and visitor.visitor_code:
                try:
                    from app.services.presence_service import presence_service
                    presence_service.on_person_detected(
                        db=db,
                        person_id=visitor.visitor_code,
                        person_name=visitor.visitor_code,
                        camera_id=camera_id,
                        visitor_id=visitor.id
                    )
                except Exception:
                    pass
        else:
            # Create new sighting session
            snapshot_path = None
            if crop_img is not None and crop_img.size > 0:
                filename = f"sighting_{camera_id}_{int(now.timestamp())}.jpg"
                path = sightings_dir / filename
                cv2.imwrite(str(path), crop_img)
                snapshot_path = str(path)

            sighting = VisitorSightingModel(
                visitor_id=visitor_id,
                camera_id=camera_id,
                track_id=track_id,
                entered_at=now,
                last_seen_at=now,
                best_similarity=best_sim,
                second_best_similarity=second_best_sim,
                match_margin=margin,
                identity_confidence=confidence,
                snapshot_path=snapshot_path,
                metadata_json=json.dumps(metadata) if metadata else None
            )
            db.add(sighting)

            # Update visitor total sighting count and timestamps
            if visitor:
                visitor.sighting_count += 1
                visitor.last_seen_at = now
                visitor.last_camera_id = camera_id

            db.commit()
            db.refresh(sighting)

            # Trigger presence session tracking for visitor
            if visitor and visitor.visitor_code:
                try:
                    from app.services.presence_service import presence_service
                    presence_service.on_person_detected(
                        db=db,
                        person_id=visitor.visitor_code,
                        person_name=visitor.visitor_code,
                        camera_id=camera_id,
                        timestamp=now,
                        visitor_id=visitor.id
                    )
                except Exception as pres_err:
                    logger.warning(f"Visitor presence hook warning: {pres_err}")

        return sighting


    def promote_visitor_to_person(
        self,
        db: Session,
        visitor_id: int,
        first_name: str,
        last_name: str,
        department: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        notes: Optional[str] = None
    ) -> PersonModel:
        """
        Transactionally promotes an unregistered visitor to a registered PersonModel.
        Copies high-quality face samples into permanent gallery & FAISS index,
        updates visitor status to 'promoted', and sets promoted_person_id.
        """
        visitor = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
        if not visitor:
            raise ValueError(f"Visitor ID {visitor_id} not found.")

        if visitor.status == 'promoted' and visitor.promoted_person_id:
            existing = db.query(PersonModel).filter(PersonModel.person_id == visitor.promoted_person_id).first()
            if existing:
                return existing

        now = datetime.now()
        person_id = f"person_{uuid.uuid4().hex[:8]}"
        full_name = f"{first_name} {last_name}".strip()

        # 1. Create registered Person record
        person = PersonModel(
            person_id=person_id,
            first_name=first_name,
            last_name=last_name,
            name=full_name,
            department=department,
            role=role,
            phone=phone,
            email=email,
            notes=notes or f"Promoted from visitor {visitor.visitor_code}",
            registered_at=now,
            updated_at=now
        )
        db.add(person)
        db.flush()

        # 2. Transfer high-quality face samples
        person_dir = settings.FACES_DIR / person_id
        os.makedirs(person_dir, exist_ok=True)

        samples = db.query(VisitorFaceSampleModel).filter(VisitorFaceSampleModel.visitor_id == visitor_id).all()
        from app.core.faiss_index import faiss_manager

        added_embeddings = []
        for idx, sample in enumerate(samples):
            emb_vec = np.frombuffer(sample.embedding_blob, dtype=np.float32)

            dest_filename = f"{person_id}_sample_{idx+1}.jpg"
            dest_img_path = str(person_dir / dest_filename)

            if sample.snapshot_path and os.path.exists(sample.snapshot_path):
                import shutil
                shutil.copy2(sample.snapshot_path, dest_img_path)
            else:
                dest_img_path = None

            # Add PersonImage record
            p_img = PersonImageModel(
                person_id=person_id,
                image_path=dest_img_path,
                quality_score=sample.quality_score,
                is_active=True,
                created_at=now,
                camera_id=sample.camera_id,
                yaw=sample.yaw,
                pitch=sample.pitch,
                blur_score=sample.blur_score
            )
            db.add(p_img)
            db.flush()

            # Add Embedding record
            emb_model = EmbeddingModel(
                person_id=person_id,
                image_id=p_img.id,
                image_path=dest_img_path,
                is_active=True,
                created_at=now
            )
            db.add(emb_model)
            added_embeddings.append(emb_vec)

        # 3. Add vectors to FAISS index
        for emb_vec in added_embeddings:
            faiss_manager.add_person_embedding(person_id=person_id, embedding=emb_vec, name=full_name)

        # 4. Update visitor status & FK
        visitor.status = 'promoted'
        visitor.promoted_person_id = person_id
        db.commit()
        db.refresh(person)

        logger.info(f"[VisitorRepo] Successfully promoted visitor {visitor.visitor_code} to registered Person {full_name} ({person_id}).")
        return person

    def delete_visitor(self, db: Session, visitor_id_or_code: Any) -> bool:
        """Deletes a visitor profile, all associated snapshot files, sightings, and in-memory gallery vectors."""
        if isinstance(visitor_id_or_code, int) or (isinstance(visitor_id_or_code, str) and visitor_id_or_code.isdigit()):
            visitor = db.query(VisitorModel).filter(VisitorModel.id == int(visitor_id_or_code)).first()
        else:
            visitor = db.query(VisitorModel).filter(VisitorModel.visitor_code == str(visitor_id_or_code)).first()

        if not visitor:
            return False

        vis_id = visitor.id

        # 1. Clean up snapshot image files on disk
        files_to_remove = set()
        if visitor.primary_snapshot_path:
            files_to_remove.add(visitor.primary_snapshot_path)

        for s in visitor.face_samples:
            if s.snapshot_path:
                files_to_remove.add(s.snapshot_path)

        for sg in visitor.sightings:
            if sg.snapshot_path:
                files_to_remove.add(sg.snapshot_path)

        for file_path in files_to_remove:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.warning(f"[VisitorRepo] Could not remove snapshot file {file_path}: {e}")

        # Also remove per-visitor subfolder if it exists
        try:
            visitor_dir = settings.VISITORS_DIR / visitor.date_key / visitor.visitor_code
            if visitor_dir.exists() and visitor_dir.is_dir():
                import shutil
                shutil.rmtree(visitor_dir, ignore_errors=True)
        except Exception as dir_err:
            logger.warning(f"[VisitorRepo] Could not remove visitor directory for {visitor.visitor_code}: {dir_err}")

        # 2. Remove from in-memory visitor gallery
        try:
            from app.visitors.visitor_gallery import visitor_gallery
            visitor_gallery.remove_visitor(vis_id)
        except Exception as g_err:
            logger.warning(f"[VisitorRepo] Could not remove visitor {vis_id} from gallery: {g_err}")

        # 3. Delete from DB
        db.delete(visitor)
        db.commit()
        logger.info(f"[VisitorRepo] Deleted visitor {vis_id} and all associated files.")
        return True

    def purge_all_visitors(self, db: Session) -> Dict[str, Any]:
        """
        Purges all visitor records, face samples, sighting timelines, on-disk JPEGs, sequence trackers,
        and resets auto-increment ID counters so new visitors start cleanly with fresh IDs.
        """
        import shutil
        from sqlalchemy import text

        # 1. Count records to be purged
        v_count = db.query(VisitorModel).count()
        s_count = db.query(VisitorFaceSampleModel).count()
        sg_count = db.query(VisitorSightingModel).count()

        # 2. Delete DB records
        db.query(VisitorSightingModel).delete()
        db.query(VisitorFaceSampleModel).delete()
        db.query(VisitorModel).delete()
        db.commit()

        # 3. Reset SQLite auto-increment primary key sequences
        try:
            db.execute(text("DELETE FROM sqlite_sequence WHERE name IN ('visitors', 'visitor_face_samples', 'visitor_sightings')"))
            db.commit()
        except Exception as seq_err:
            logger.warning(f"[VisitorRepo] Reset sqlite_sequence info: {seq_err}")

        # 4. Remove all files/folders in storage/visitors
        try:
            if settings.VISITORS_DIR.exists():
                for item in settings.VISITORS_DIR.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    elif item.is_file():
                        try:
                            item.unlink()
                        except Exception:
                            pass
        except Exception as dir_err:
            logger.warning(f"[VisitorRepo] Error cleaning visitors storage directory: {dir_err}")

        # 5. Flush in-memory visitor vector gallery and track caches
        try:
            from app.visitors.visitor_gallery import visitor_gallery
            from app.visitors.visitor_manager import visitor_manager
            with visitor_gallery.lock:
                visitor_gallery.gallery_embeddings.clear()
                visitor_gallery.visitor_codes.clear()
                visitor_gallery.visitor_snapshots.clear()
                visitor_gallery.current_date_key = ""

            with visitor_manager.lock:
                visitor_manager.track_identity_cache.clear()
                visitor_manager.track_observation_buffer.clear()
                visitor_manager.initialized_date_key = ""
        except Exception as cache_err:
            logger.warning(f"[VisitorRepo] Error flushing visitor memory caches: {cache_err}")

        logger.info(f"[VisitorRepo] Purged all visitor data: {v_count} visitors, {s_count} samples, {sg_count} sightings.")
        return {
            "purged_visitors": v_count,
            "purged_samples": s_count,
            "purged_sightings": sg_count
        }

    def purge_visitor_gallery_contamination(self, db: Session) -> Dict[str, int]:
        """
        Self-Healing Maintenance Engine.
        Scans all visitor profiles and removes face samples that do not match the primary/initial
        visitor embedding (similarity < 0.58), fixing existing contaminated galleries.
        """
        import os
        from app.core.utils import l2_normalize

        visitors = db.query(VisitorModel).all()
        purged_samples = 0
        cleaned_visitors = 0

        for v in visitors:
            samples = db.query(VisitorFaceSampleModel).filter(
                VisitorFaceSampleModel.visitor_id == v.id
            ).order_by(VisitorFaceSampleModel.id.asc()).all()

            if len(samples) < 2:
                continue

            ref_vec = None
            for s in samples:
                if s.embedding_blob:
                    ref_vec = l2_normalize(np.frombuffer(s.embedding_blob, dtype=np.float32))
                    break

            if ref_vec is None:
                continue

            contamination_found = False
            for s in samples[1:]:
                if not s.embedding_blob:
                    continue
                s_vec = l2_normalize(np.frombuffer(s.embedding_blob, dtype=np.float32))
                sim = float(np.dot(ref_vec, s_vec.T))
                # If sample similarity to visitor reference is < 0.58, it is a different person's face!
                if sim < 0.58:
                    logger.info(f"[SELF_HEAL] Purging contaminated face sample ID {s.id} from visitor {v.visitor_code} (Sim {sim:.3f} < 0.58).")
                    if s.snapshot_path and os.path.exists(s.snapshot_path):
                        try:
                            os.remove(s.snapshot_path)
                        except Exception:
                            pass
                    db.delete(s)
                    purged_samples += 1
                    contamination_found = True

            if contamination_found:
                db.commit()
                cleaned_visitors += 1

        # Purge low-confidence sightings recorded under legacy low threshold (< 0.58)
        purged_sightings = db.query(VisitorSightingModel).filter(
            VisitorSightingModel.best_similarity < 0.58
        ).delete(synchronize_session=False)

        if purged_sightings > 0:
            db.commit()

        logger.info(f"[SELF_HEAL_COMPLETE] Purged {purged_sightings} low-confidence sighting(s) (< 0.58) & {purged_samples} contaminated sample(s) across {cleaned_visitors} visitor profile(s).")
        return {"purged_samples": purged_samples, "purged_sightings": purged_sightings, "cleaned_visitors": cleaned_visitors}

    def self_heal_and_migrate_visitor_paths(self, db: Session):

        """
        Startup migration & self-healing routine:
        1. Harmonizes physical date directories (renames e.g. '20260810' to '2026-08-10').
        2. Repairs database image paths (primary_snapshot_path, snapshot_path) to point to valid files.
        """
        root_dir = get_visitor_root()
        # 1. Rename unhyphenated date folders in storage/visitors
        if root_dir.exists():
            for d in list(root_dir.iterdir()):
                if d.is_dir() and len(d.name) == 8 and d.name.isdigit():
                    formatted_date = f"{d.name[:4]}-{d.name[4:6]}-{d.name[6:8]}"
                    target_dir = root_dir / formatted_date
                    if not target_dir.exists():
                        try:
                            d.rename(target_dir)
                            logger.info(f"[Migration] Renamed folder {d.name} -> {formatted_date}")
                        except Exception as err:
                            logger.warning(f"[Migration] Error renaming {d.name}: {err}")
                    else:
                        for item in d.iterdir():
                            try:
                                dest = target_dir / item.name
                                if not dest.exists():
                                    item.rename(dest)
                            except Exception as err:
                                logger.warning(f"[Migration] Error moving {item.name}: {err}")

        # 2. Repair DB snapshot paths
        visitors = db.query(VisitorModel).all()
        repaired_count = 0
        for v in visitors:
            # Standardize date_key to YYYY-MM-DD
            if v.date_key and len(v.date_key) == 8 and v.date_key.isdigit():
                v.date_key = f"{v.date_key[:4]}-{v.date_key[4:6]}-{v.date_key[6:8]}"
            if not v.created_date:
                v.created_date = v.date_key

            if v.primary_snapshot_path:
                norm_path = str(v.primary_snapshot_path).replace("\\", "/")
                if not os.path.exists(v.primary_snapshot_path):
                    v_dir, _, _ = get_visitor_folder_paths(v.created_date or v.date_key, v.visitor_code)
                    cand_avatar = v_dir / "primary_avatar.jpg"
                    if cand_avatar.exists():
                        v.primary_snapshot_path = str(cand_avatar)
                        repaired_count += 1
                    else:
                        jpegs = list(v_dir.glob("*.jpg")) + list(v_dir.glob("samples/*.jpg")) + list(v_dir.glob("sightings/*.jpg"))
                        if jpegs:
                            v.primary_snapshot_path = str(jpegs[0])
                            repaired_count += 1

        if repaired_count > 0:
            db.commit()
            logger.info(f"[SelfHealing] Repaired {repaired_count} visitor primary snapshot paths.")


visitor_repository = VisitorRepository()


