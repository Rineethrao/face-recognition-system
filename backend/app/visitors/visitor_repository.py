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

    def _collect_transferable_samples(
        self,
        db: Session,
        visitor_id: int,
        visitor: VisitorModel,
    ) -> Tuple[List[VisitorFaceSampleModel], List[np.ndarray]]:
        """Returns ranked visitor face samples and normalized embeddings for registration."""
        from app.core.utils import l2_normalize

        samples = (
            db.query(VisitorFaceSampleModel)
            .filter(VisitorFaceSampleModel.visitor_id == visitor_id)
            .all()
        )
        if not samples:
            raise ValueError(
                f"Visitor {visitor.visitor_code} has no face samples to transfer. "
                "Wait for clearer face captures before registering."
            )

        max_transfer = int(getattr(settings, 'VISITOR_MAX_SAMPLES', 6))
        ranked = sorted(samples, key=lambda s: float(s.quality_score or 0.0), reverse=True)
        transferable: List[VisitorFaceSampleModel] = []
        emb_list: List[np.ndarray] = []
        for s in ranked:
            if s.embedding_blob is None:
                continue
            emb = np.frombuffer(s.embedding_blob, dtype=np.float32)
            if emb.size != 512:
                continue
            transferable.append(s)
            emb_list.append(l2_normalize(emb.astype(np.float32)))
            if len(transferable) >= max_transfer:
                break

        if not transferable:
            raise ValueError(f"Visitor {visitor.visitor_code} has no usable embeddings to register.")
        return transferable, emb_list

    def _find_duplicate_registered(
        self,
        emb_list: List[np.ndarray],
    ) -> Tuple[Optional[Dict[str, Any]], float, str]:
        """
        Returns best registered-person match for visitor embeddings.
        Uses the same duplicate thresholds as manual registration.
        Returns (match_dict_or_none, similarity, level) where level is none|soft|hard.
        """
        from app.services.registration.duplicate_service import duplicate_service

        assessment = duplicate_service.assess_duplicate(
            emb_list,
            hard_threshold=float(getattr(settings, 'VISITOR_REGISTERED_MATCH_THRESHOLD', 0.55)),
            warning_threshold=float(getattr(settings, 'REGISTRATION_DUPLICATE_WARNING_THRESHOLD', 0.52)),
        )
        level = str(assessment.get("level") or "none")
        sim = float(assessment.get("similarity") or 0.0)
        pid = assessment.get("matched_person_id")
        if level == "none" or not pid:
            return None, sim, level

        return {
            "person_id": pid,
            "name": assessment.get("matched_name") or pid,
            "similarity": sim,
        }, sim, level

    def _transfer_samples_to_person(
        self,
        db: Session,
        person: PersonModel,
        visitor: VisitorModel,
        transferable: List[VisitorFaceSampleModel],
        *,
        skip_near_duplicate: bool = True,
    ) -> int:
        """
        Copies visitor face sample images + embeddings into a registered person gallery.
        Returns number of samples actually added.
        """
        from app.core.faiss_index import faiss_manager
        from app.core.utils import l2_normalize

        person_id = person.person_id
        person_dir = settings.FACES_DIR / person_id
        os.makedirs(person_dir, exist_ok=True)
        now = datetime.now()

        existing_count = (
            db.query(PersonImageModel)
            .filter(PersonImageModel.person_id == person_id, PersonImageModel.is_active == True)
            .count()
        )
        max_gallery = int(getattr(settings, 'REGISTRATION_MAX_SAMPLES', 10))
        dup_sim_thresh = float(getattr(settings, 'VISITOR_PROFILE_UPDATE_THRESHOLD', 0.65))
        cached = faiss_manager.embeddings_cache.get(person_id, [])

        prepared = []
        for idx, sample in enumerate(transferable):
            emb_vec = np.frombuffer(sample.embedding_blob, dtype=np.float32)
            if emb_vec.size != 512:
                continue
            emb_norm = l2_normalize(emb_vec.astype(np.float32))

            if skip_near_duplicate and cached:
                max_sim = max(float(np.dot(emb_norm, l2_normalize(c))) for c in cached)
                if max_sim >= dup_sim_thresh:
                    continue

            dest_filename = f"{person_id}_from_{visitor.visitor_code}_{idx+1}.jpg"
            dest_img_path = str(person_dir / dest_filename)
            if sample.snapshot_path and os.path.exists(sample.snapshot_path):
                import shutil
                shutil.copy2(sample.snapshot_path, dest_img_path)
            elif visitor.primary_snapshot_path and os.path.exists(visitor.primary_snapshot_path) and idx == 0:
                import shutil
                shutil.copy2(visitor.primary_snapshot_path, dest_img_path)
            else:
                dest_img_path = None

            prepared.append((emb_norm, dest_img_path, sample))

        if existing_count + len(prepared) > max_gallery:
            prepared = prepared[: max(0, max_gallery - existing_count)]

        if not prepared:
            return 0

        embeddings_matrix = np.vstack([p[0] for p in prepared]).astype(np.float32)
        faiss_ids = faiss_manager.add_vectors(person_id, person.name or person_id, embeddings_matrix)
        person.gallery_version = int(person.gallery_version or 1) + 1

        added = 0
        for (emb_vec, dest_img_path, sample), f_id in zip(prepared, faiss_ids):
            p_img = PersonImageModel(
                person_id=person_id,
                image_path=dest_img_path,
                quality_score=sample.quality_score,
                pose_bin="FRONTAL",
                gallery_version=person.gallery_version,
                is_active=True,
                created_at=now,
                camera_id=sample.camera_id,
                yaw=sample.yaw,
                pitch=sample.pitch,
                blur_score=sample.blur_score,
            )
            db.add(p_img)
            db.flush()

            emb_model = EmbeddingModel(
                person_id=person_id,
                faiss_id=f_id,
                image_id=p_img.id,
                image_path=dest_img_path,
                gallery_version=person.gallery_version,
                is_active=True,
                created_at=now,
            )
            db.add(emb_model)
            cached.append(emb_vec)
            added += 1

        person.updated_at = now
        return added

    def _link_duplicate_visitors_to_person(
        self,
        db: Session,
        visitor_id: int,
        visitor: VisitorModel,
        person_id: str,
        probe_emb: np.ndarray,
        full_name: str,
    ) -> None:
        from app.core.utils import l2_normalize
        from app.visitors.visitor_gallery import visitor_gallery

        try:
            merge_thresh = float(getattr(settings, 'VISITOR_DUPLICATE_FLAG_THRESHOLD', 0.48))
            probe = l2_normalize(probe_emb.astype(np.float32))
            other_visitors = (
                db.query(VisitorModel)
                .filter(
                    VisitorModel.id != visitor_id,
                    VisitorModel.status != 'promoted',
                    VisitorModel.date_key == visitor.date_key,
                )
                .all()
            )
            for ov in other_visitors:
                ov_samples = (
                    db.query(VisitorFaceSampleModel)
                    .filter(VisitorFaceSampleModel.visitor_id == ov.id)
                    .all()
                )
                best_sim = 0.0
                for osamp in ov_samples:
                    if not osamp.embedding_blob:
                        continue
                    oe = np.frombuffer(osamp.embedding_blob, dtype=np.float32)
                    if oe.size != 512:
                        continue
                    best_sim = max(best_sim, float(np.dot(probe, l2_normalize(oe))))
                if best_sim >= merge_thresh:
                    ov.status = 'promoted'
                    ov.promoted_person_id = person_id
                    try:
                        visitor_gallery.remove_visitor(ov.id)
                    except Exception:
                        pass
                    logger.info(
                        f"[VisitorRepo] Linked duplicate visitor {ov.visitor_code} "
                        f"(sim={best_sim:.3f}) to registered {full_name}"
                    )
        except Exception as merge_err:
            logger.warning(f"[VisitorRepo] Duplicate visitor link step skipped: {merge_err}")

    def get_promote_preview(self, db: Session, visitor_id: int) -> Dict[str, Any]:
        """Preview visitor registration: samples to transfer + any existing registered match."""
        from app.core.utils import l2_normalize

        visitor = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
        if not visitor:
            raise ValueError(f"Visitor ID {visitor_id} not found.")

        transferable, emb_list = self._collect_transferable_samples(db, visitor_id, visitor)
        best_dup, best_dup_sim, match_level = self._find_duplicate_registered(emb_list)

        visitor_samples = []
        for s in transferable:
            visitor_samples.append({
                "id": s.id,
                "quality_score": round(float(s.quality_score or 0.0), 4),
                "blur_score": round(float(s.blur_score or 0.0), 1),
                "yaw": round(float(s.yaw or 0.0), 3),
                "pitch": round(float(s.pitch or 0.0), 3),
                "camera_id": s.camera_id,
                "snapshot_url": self._format_person_or_visitor_url(s.snapshot_path),
            })

        matched_person = None
        if best_dup:
            pid = best_dup.get("person_id")
            person = db.query(PersonModel).filter(PersonModel.person_id == pid).first()
            existing_images = []
            if person:
                for img in person.images:
                    if not img.is_active:
                        continue
                    if not img.image_path or not os.path.exists(img.image_path):
                        continue
                    filename = os.path.basename(img.image_path)
                    existing_images.append({
                        "id": img.id,
                        "image_url": f"/faces/{pid}/{filename}",
                        "quality_score": round(float(img.quality_score or 0.0), 4),
                    })
            matched_person = {
                "person_id": pid,
                "name": best_dup.get("name") or (person.name if person else pid),
                "similarity": round(best_dup_sim, 4),
                "match_level": match_level,
                "first_name": person.first_name if person else None,
                "last_name": person.last_name if person else None,
                "department": person.department if person else None,
                "role": person.role if person else None,
                "phone": person.phone if person else None,
                "email": person.email if person else None,
                "existing_images": existing_images[:8],
                "existing_image_count": len(existing_images),
            }

        is_hard_match = match_level == "hard"
        return {
            "visitor_id": visitor_id,
            "visitor_code": visitor.visitor_code,
            "primary_snapshot_url": self._format_person_or_visitor_url(visitor.primary_snapshot_path),
            "samples_to_transfer": visitor_samples,
            "sample_count": len(visitor_samples),
            "matched_registered_person": matched_person,
            "match_level": match_level,
            "can_create_new": not is_hard_match,
            "can_merge_existing": is_hard_match,
        }

    @staticmethod
    def _max_cross_similarity(embs_a: List[np.ndarray], embs_b: List[np.ndarray]) -> float:
        if not embs_a or not embs_b:
            return 0.0
        best = 0.0
        for a in embs_a:
            for b in embs_b:
                best = max(best, float(np.dot(a, b)))
        return best

    def _format_visitor_samples(
        self,
        visitor: VisitorModel,
        transferable: List[VisitorFaceSampleModel],
    ) -> List[Dict[str, Any]]:
        samples = []
        for s in transferable:
            samples.append({
                "id": s.id,
                "visitor_id": visitor.id,
                "visitor_code": visitor.visitor_code,
                "quality_score": round(float(s.quality_score or 0.0), 4),
                "blur_score": round(float(s.blur_score or 0.0), 1),
                "yaw": round(float(s.yaw or 0.0), 3),
                "pitch": round(float(s.pitch or 0.0), 3),
                "camera_id": s.camera_id,
                "snapshot_url": self._format_person_or_visitor_url(s.snapshot_path),
            })
        return samples

    def get_bulk_promote_preview(self, db: Session, visitor_ids: List[int]) -> Dict[str, Any]:
        """Preview merging multiple duplicate visitors into one registered person."""
        if not visitor_ids:
            raise ValueError("Select at least one visitor to register.")
        if len(visitor_ids) < 2:
            raise ValueError("Select at least two visitors to merge into one registered person.")

        unique_ids: List[int] = []
        seen = set()
        for vid in visitor_ids:
            if vid not in seen:
                unique_ids.append(vid)
                seen.add(vid)

        visitors_bundle: List[Tuple[VisitorModel, List[VisitorFaceSampleModel], List[np.ndarray]]] = []
        all_embs: List[np.ndarray] = []
        visitors_info: List[Dict[str, Any]] = []
        combined_samples: List[Dict[str, Any]] = []

        for vid in unique_ids:
            visitor = db.query(VisitorModel).filter(VisitorModel.id == vid).first()
            if not visitor:
                raise ValueError(f"Visitor ID {vid} not found.")
            if visitor.status == 'promoted':
                raise ValueError(
                    f"{visitor.visitor_code} is already registered "
                    f"as {visitor.promoted_person_id}. Remove it from selection."
                )
            transferable, emb_list = self._collect_transferable_samples(db, vid, visitor)
            visitors_bundle.append((visitor, transferable, emb_list))
            all_embs.extend(emb_list)
            formatted = self._format_visitor_samples(visitor, transferable)
            visitors_info.append({
                "visitor_id": visitor.id,
                "visitor_code": visitor.visitor_code,
                "primary_snapshot_url": self._format_person_or_visitor_url(visitor.primary_snapshot_path),
                "samples": formatted,
                "sample_count": len(formatted),
                "status": visitor.status,
            })
            combined_samples.extend(formatted)

        pairwise: List[Dict[str, Any]] = []
        for i in range(len(visitors_bundle)):
            for j in range(i + 1, len(visitors_bundle)):
                va, _, embs_a = visitors_bundle[i]
                vb, _, embs_b = visitors_bundle[j]
                sim = self._max_cross_similarity(embs_a, embs_b)
                pairwise.append({
                    "visitor_a_id": va.id,
                    "visitor_a_code": va.visitor_code,
                    "visitor_b_id": vb.id,
                    "visitor_b_code": vb.visitor_code,
                    "similarity": round(sim, 4),
                    "same_person_likely": sim >= float(
                        getattr(settings, 'VISITOR_DUPLICATE_FLAG_THRESHOLD', 0.48)
                    ),
                })

        best_dup, best_dup_sim, match_level = self._find_duplicate_registered(all_embs)
        matched_person = None
        if best_dup:
            pid = best_dup.get("person_id")
            person = db.query(PersonModel).filter(PersonModel.person_id == pid).first()
            existing_images = []
            if person:
                for img in person.images:
                    if not img.is_active:
                        continue
                    if not img.image_path or not os.path.exists(img.image_path):
                        continue
                    filename = os.path.basename(img.image_path)
                    existing_images.append({
                        "id": img.id,
                        "image_url": f"/faces/{pid}/{filename}",
                        "quality_score": round(float(img.quality_score or 0.0), 4),
                    })
            matched_person = {
                "person_id": pid,
                "name": best_dup.get("name") or (person.name if person else pid),
                "similarity": round(best_dup_sim, 4),
                "match_level": match_level,
                "first_name": person.first_name if person else None,
                "last_name": person.last_name if person else None,
                "department": person.department if person else None,
                "role": person.role if person else None,
                "phone": person.phone if person else None,
                "email": person.email if person else None,
                "existing_images": existing_images[:8],
                "existing_image_count": len(existing_images),
            }

        min_pair_sim = min((p["similarity"] for p in pairwise), default=1.0)
        is_hard_match = match_level == "hard"
        return {
            "visitor_ids": unique_ids,
            "visitor_count": len(unique_ids),
            "visitors": visitors_info,
            "pairwise_similarities": pairwise,
            "min_pairwise_similarity": round(min_pair_sim, 4),
            "samples_to_transfer": combined_samples,
            "sample_count": len(combined_samples),
            "matched_registered_person": matched_person,
            "match_level": match_level,
            "can_create_new": not is_hard_match,
            "can_merge_existing": is_hard_match,
        }

    def promote_visitors_to_person(
        self,
        db: Session,
        visitor_ids: List[int],
        first_name: str,
        last_name: str,
        department: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        notes: Optional[str] = None,
        merge_into_existing: bool = False,
        target_person_id: Optional[str] = None,
        primary_visitor_id: Optional[int] = None,
    ) -> PersonModel:
        """Register one or more duplicate visitors as a single registered person."""
        from app.visitors.visitor_gallery import visitor_gallery

        if not visitor_ids:
            raise ValueError("No visitors selected for registration.")

        unique_ids: List[int] = []
        seen = set()
        for vid in visitor_ids:
            if vid not in seen:
                unique_ids.append(vid)
                seen.add(vid)

        if len(unique_ids) == 1:
            only = db.query(VisitorModel).filter(VisitorModel.id == unique_ids[0]).first()
            if only and only.status == 'promoted' and only.promoted_person_id:
                existing = db.query(PersonModel).filter(
                    PersonModel.person_id == only.promoted_person_id
                ).first()
                if existing:
                    return existing

        primary_id = primary_visitor_id or unique_ids[0]
        if primary_id not in unique_ids:
            unique_ids.insert(0, primary_id)
        else:
            unique_ids = [primary_id] + [vid for vid in unique_ids if vid != primary_id]

        visitors_bundle: List[Tuple[VisitorModel, List[VisitorFaceSampleModel], List[np.ndarray]]] = []
        all_embs: List[np.ndarray] = []
        codes: List[str] = []

        for vid in unique_ids:
            visitor = db.query(VisitorModel).filter(VisitorModel.id == vid).first()
            if not visitor:
                raise ValueError(f"Visitor ID {vid} not found.")
            if visitor.status == 'promoted' and visitor.promoted_person_id:
                if merge_into_existing and target_person_id == visitor.promoted_person_id:
                    continue
                raise ValueError(
                    f"{visitor.visitor_code} is already registered as {visitor.promoted_person_id}."
                )
            transferable, emb_list = self._collect_transferable_samples(db, vid, visitor)
            visitors_bundle.append((visitor, transferable, emb_list))
            all_embs.extend(emb_list)
            codes.append(visitor.visitor_code)

        if not visitors_bundle:
            raise ValueError("No active visitors available to register.")

        best_dup, best_dup_sim, match_level = self._find_duplicate_registered(all_embs)
        full_name = f"{first_name} {last_name}".strip()
        codes_label = ", ".join(codes)
        merge_notes = notes or (
            f"Merged duplicate visitors: {codes_label}" if len(codes) > 1
            else f"Promoted from visitor {codes[0]}"
        )

        # --- Merge into existing registered person ---
        if merge_into_existing or (best_dup and target_person_id):
            pid = target_person_id or (best_dup.get("person_id") if best_dup else None)
            if not pid:
                raise ValueError("No existing registered person specified for merge.")
            person = db.query(PersonModel).filter(PersonModel.person_id == pid).first()
            if not person:
                raise ValueError(f"Registered person '{pid}' not found.")

            if first_name.strip():
                person.first_name = first_name.strip()
            if last_name.strip():
                person.last_name = last_name.strip()
            if first_name.strip() or last_name.strip():
                person.name = full_name or person.name
            if department:
                person.department = department
            if role:
                person.role = role
            if phone:
                person.phone = phone
            if email:
                person.email = email
            if merge_notes:
                person.notes = (person.notes or "") + f"\n{merge_notes}" if person.notes else merge_notes

            total_added = 0
            primary_visitor, _, primary_embs = visitors_bundle[0]
            for visitor, transferable, _ in visitors_bundle:
                total_added += self._transfer_samples_to_person(
                    db, person, visitor, transferable, skip_near_duplicate=True
                )
                visitor.status = 'promoted'
                visitor.promoted_person_id = pid
                try:
                    visitor_gallery.remove_visitor(visitor.id)
                except Exception:
                    pass

            self._link_duplicate_visitors_to_person(
                db, primary_visitor.id, primary_visitor, pid,
                primary_embs[0], person.name or full_name
            )
            db.commit()
            db.refresh(person)
            logger.info(
                f"[VisitorRepo] Merged {len(visitors_bundle)} visitor(s) [{codes_label}] "
                f"into existing {person.name} ({pid}) — added {total_added} face sample(s)."
            )
            return person

        if match_level == "hard" and best_dup:
            raise ValueError(
                f"These visitors already match registered person "
                f"'{best_dup.get('name')}' ({best_dup.get('person_id')}) "
                f"at {best_dup_sim*100:.1f}% similarity. "
                f"Use 'Add photos to existing profile' to merge all selected visitors."
            )

        now = datetime.now()
        person_id = f"person_{uuid.uuid4().hex[:8]}"
        person = PersonModel(
            person_id=person_id,
            first_name=first_name,
            last_name=last_name,
            name=full_name,
            department=department,
            role=role,
            phone=phone,
            email=email,
            notes=merge_notes,
            registered_at=now,
            updated_at=now,
        )
        db.add(person)
        db.flush()

        total_added = 0
        primary_visitor, _, primary_embs = visitors_bundle[0]
        for idx, (visitor, transferable, _) in enumerate(visitors_bundle):
            total_added += self._transfer_samples_to_person(
                db,
                person,
                visitor,
                transferable,
                skip_near_duplicate=idx > 0,
            )
            visitor.status = 'promoted'
            visitor.promoted_person_id = person_id
            try:
                visitor_gallery.remove_visitor(visitor.id)
            except Exception:
                pass

        if total_added == 0:
            db.rollback()
            raise ValueError("No valid face samples available to seed the registered profile.")

        self._link_duplicate_visitors_to_person(
            db, primary_visitor.id, primary_visitor, person_id,
            primary_embs[0], full_name
        )
        db.commit()
        db.refresh(person)
        logger.info(
            f"[VisitorRepo] Registered {len(visitors_bundle)} visitor(s) [{codes_label}] "
            f"as Person {full_name} ({person_id}) with {total_added} face sample(s)."
        )
        return person

    def _sync_visitor_to_gallery(self, db: Session, visitor: VisitorModel) -> None:
        """Rebuild in-memory gallery embeddings for one visitor from DB samples."""
        from app.core.utils import l2_normalize
        from app.visitors.visitor_gallery import visitor_gallery

        visitor_gallery.remove_visitor(visitor.id)
        samples = (
            db.query(VisitorFaceSampleModel)
            .filter(VisitorFaceSampleModel.visitor_id == visitor.id)
            .order_by(VisitorFaceSampleModel.quality_score.desc())
            .all()
        )
        for sample in samples:
            if not sample.embedding_blob:
                continue
            emb = np.frombuffer(sample.embedding_blob, dtype=np.float32)
            if emb.size != 512:
                continue
            visitor_gallery.add_visitor_sample(
                visitor.id,
                visitor.visitor_code,
                emb,
                sample.snapshot_path or visitor.primary_snapshot_path,
            )

    def get_merge_preview(self, db: Session, visitor_ids: List[int]) -> Dict[str, Any]:
        """Preview merging duplicate visitors into one tracking profile (no registration)."""
        preview = self.get_bulk_promote_preview(db, visitor_ids)
        preview["action"] = "merge_tracking"
        return preview

    def merge_visitors_into_one(
        self,
        db: Session,
        visitor_ids: List[int],
        primary_visitor_id: Optional[int] = None,
    ) -> VisitorModel:
        """
        Merge multiple duplicate visitor profiles into a single active visitor for tracking.
        Source visitors are marked status=merged and hidden from the active list.
        """
        from app.visitors.visitor_gallery import visitor_gallery

        if len(visitor_ids) < 2:
            raise ValueError("Select at least two visitors to merge for tracking.")

        unique_ids: List[int] = []
        seen = set()
        for vid in visitor_ids:
            if vid not in seen:
                unique_ids.append(vid)
                seen.add(vid)

        primary_id = primary_visitor_id or unique_ids[0]
        if primary_id not in unique_ids:
            unique_ids.insert(0, primary_id)
        else:
            unique_ids = [primary_id] + [vid for vid in unique_ids if vid != primary_id]

        source_ids = [vid for vid in unique_ids if vid != primary_id]
        primary = db.query(VisitorModel).filter(VisitorModel.id == primary_id).first()
        if not primary:
            raise ValueError(f"Primary visitor ID {primary_id} not found.")
        if primary.status == 'promoted':
            raise ValueError(f"{primary.visitor_code} is already registered and cannot absorb merges.")
        if primary.status == 'merged':
            raise ValueError(f"{primary.visitor_code} was merged into another profile. Pick a different primary.")

        merged_codes: List[str] = []
        moved_samples = 0
        moved_sightings = 0

        for sid in source_ids:
            source = db.query(VisitorModel).filter(VisitorModel.id == sid).first()
            if not source:
                raise ValueError(f"Visitor ID {sid} not found.")
            if source.status == 'promoted':
                raise ValueError(f"{source.visitor_code} is already registered — use register flow instead.")
            if source.status == 'merged':
                raise ValueError(f"{source.visitor_code} is already merged into another visitor.")

            sample_count = (
                db.query(VisitorFaceSampleModel)
                .filter(VisitorFaceSampleModel.visitor_id == sid)
                .update({VisitorFaceSampleModel.visitor_id: primary_id})
            )
            moved_samples += sample_count

            sighting_count = (
                db.query(VisitorSightingModel)
                .filter(VisitorSightingModel.visitor_id == sid)
                .update({VisitorSightingModel.visitor_id: primary_id})
            )
            moved_sightings += sighting_count

            source_visits = (
                db.query(VisitorVisitModel)
                .filter(VisitorVisitModel.visitor_id == sid)
                .all()
            )
            for visit in source_visits:
                existing = db.query(VisitorVisitModel).filter(
                    VisitorVisitModel.visitor_id == primary_id,
                    VisitorVisitModel.date_key == visit.date_key,
                ).first()
                if existing:
                    existing.sighting_count = (existing.sighting_count or 0) + (visit.sighting_count or 0)
                    if visit.first_seen_at and (
                        not existing.first_seen_at or visit.first_seen_at < existing.first_seen_at
                    ):
                        existing.first_seen_at = visit.first_seen_at
                    if visit.last_seen_at and (
                        not existing.last_seen_at or visit.last_seen_at > existing.last_seen_at
                    ):
                        existing.last_seen_at = visit.last_seen_at
                    if existing.first_seen_at and existing.last_seen_at:
                        existing.duration_seconds = max(
                            0.0,
                            (existing.last_seen_at - existing.first_seen_at).total_seconds(),
                        )
                    db.delete(visit)
                else:
                    visit.visitor_id = primary_id

            primary.sighting_count = (primary.sighting_count or 0) + (source.sighting_count or 0)
            if source.first_seen_at and (
                not primary.first_seen_at or source.first_seen_at < primary.first_seen_at
            ):
                primary.first_seen_at = source.first_seen_at
                primary.first_camera_id = source.first_camera_id or primary.first_camera_id
            if source.last_seen_at and (
                not primary.last_seen_at or source.last_seen_at > primary.last_seen_at
            ):
                primary.last_seen_at = source.last_seen_at
                primary.last_camera_id = source.last_camera_id or primary.last_camera_id

            source.status = 'merged'
            source.merged_into_visitor_id = primary_id
            merged_codes.append(source.visitor_code)
            visitor_gallery.remove_visitor(sid)

        max_samples = int(getattr(settings, 'VISITOR_MAX_SAMPLES', 6))
        all_samples = (
            db.query(VisitorFaceSampleModel)
            .filter(VisitorFaceSampleModel.visitor_id == primary_id)
            .order_by(VisitorFaceSampleModel.quality_score.desc())
            .all()
        )
        if len(all_samples) > max_samples:
            for extra in all_samples[max_samples:]:
                db.delete(extra)
            all_samples = all_samples[:max_samples]

        if all_samples:
            best = all_samples[0]
            if best.snapshot_path:
                primary.primary_snapshot_path = best.snapshot_path

        primary.status = 'active'
        db.commit()
        db.refresh(primary)

        self._sync_visitor_to_gallery(db, primary)

        logger.info(
            f"[VisitorRepo] Merged {len(merged_codes)} visitor(s) [{', '.join(merged_codes)}] "
            f"into {primary.visitor_code} (ID {primary.id}) — "
            f"{moved_samples} samples, {moved_sightings} sightings combined."
        )
        return primary

    @staticmethod
    def _format_person_or_visitor_url(path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        normalized = str(path).replace("\\", "/")
        if "storage/visitors/" in normalized:
            rel = normalized.split("storage/visitors/")[-1]
            return f"/faces/visitors/{rel}"
        if "storage/faces/" in normalized:
            rel = normalized.split("storage/faces/")[-1]
            return f"/faces/{rel}"
        if "faces/" in normalized:
            rel = normalized.split("faces/")[-1]
            return f"/faces/{rel}"
        return f"/faces/{os.path.basename(path)}"

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
        notes: Optional[str] = None,
        merge_into_existing: bool = False,
        target_person_id: Optional[str] = None,
        additional_visitor_ids: Optional[List[int]] = None,
    ) -> PersonModel:
        """Promotes one visitor (and optional duplicates) into a registered person."""
        extra = [vid for vid in (additional_visitor_ids or []) if vid != visitor_id]
        all_ids = [visitor_id] + extra
        return self.promote_visitors_to_person(
            db=db,
            visitor_ids=all_ids,
            primary_visitor_id=visitor_id,
            first_name=first_name,
            last_name=last_name,
            department=department,
            role=role,
            phone=phone,
            email=email,
            notes=notes,
            merge_into_existing=merge_into_existing,
            target_person_id=target_person_id,
        )

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

        # 3. Cascade delete matching recognition logs & presence records from DB
        try:
            from app.models.db_models import RecognitionLogModel
            from app.models.presence_models import PersonSessionModel, DailyReportModel
            v_code = visitor.visitor_code
            v_code_alt = f"VISITOR_{vis_id:03d}"
            db.query(RecognitionLogModel).filter(
                (RecognitionLogModel.person_id == v_code) |
                (RecognitionLogModel.person_id == v_code_alt) |
                (RecognitionLogModel.name == v_code)
            ).delete(synchronize_session=False)

            db.query(PersonSessionModel).filter(
                (PersonSessionModel.person_id == v_code) | (PersonSessionModel.person_id == v_code_alt)
            ).delete(synchronize_session=False)

            db.query(DailyReportModel).filter(
                (DailyReportModel.person_id == v_code) | (DailyReportModel.person_id == v_code_alt)
            ).delete(synchronize_session=False)
        except Exception as log_del_err:
            logger.warning(f"[VisitorRepo] Error deleting recognition/presence logs for {visitor.visitor_code}: {log_del_err}")

        # 4. Delete visitor from DB
        db.delete(visitor)
        db.commit()

        # 5. Reset camera worker track recognitions
        try:
            from app.services.camera.camera_registry import camera_registry
            with camera_registry.lock:
                for w in camera_registry.workers.values():
                    if hasattr(w, "orchestrator") and w.orchestrator:
                        w.orchestrator.reset_track_recognitions()
        except Exception:
            pass

        logger.info(f"[VisitorRepo] Deleted visitor {vis_id} and all associated files/logs.")
        return True

    def purge_all_visitors(self, db: Session) -> Dict[str, Any]:
        """
        Purges all visitor records, face samples, sighting timelines, on-disk JPEGs, sequence trackers,
        recognition logs, presence entries, and resets auto-increment ID counters so new visitors start cleanly with fresh IDs.
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
        try:
            from app.visitors.models import VisitorVisitModel
            db.query(VisitorVisitModel).delete()
        except Exception:
            pass

        # Cascade delete all visitor recognition logs & presence records
        try:
            from app.models.db_models import RecognitionLogModel
            from app.models.presence_models import PersonSessionModel, DailyReportModel
            db.query(RecognitionLogModel).filter(
                (RecognitionLogModel.person_id.like("VISITOR%")) |
                (RecognitionLogModel.name.like("VISITOR%"))
            ).delete(synchronize_session=False)

            db.query(PersonSessionModel).filter(PersonSessionModel.person_id.like("VISITOR%")).delete(synchronize_session=False)
            db.query(DailyReportModel).filter(DailyReportModel.person_id.like("VISITOR%")).delete(synchronize_session=False)
        except Exception as log_purge_err:
            logger.warning(f"[VisitorRepo] Error purging recognition logs: {log_purge_err}")

        db.query(VisitorModel).delete()
        db.commit()


        # 3. Reset SQLite auto-increment primary key sequences
        try:
            db.execute(text("DELETE FROM sqlite_sequence WHERE name IN ('visitors', 'visitor_face_samples', 'visitor_sightings', 'visitor_visits')"))
            db.commit()
        except Exception as seq_err:
            logger.warning(f"[VisitorRepo] Reset sqlite_sequence info: {seq_err}")

        # 4. Remove all files/folders in storage/visitors and visitor snapshots
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

            snaps_dir = settings.STORAGE_DIR / "snapshots"
            if snaps_dir.exists():
                for snap_f in snaps_dir.glob("snap_VISITOR*"):
                    try:
                        snap_f.unlink()
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

        # 6. Reset camera worker track recognitions across all cameras
        try:
            from app.services.camera.camera_registry import camera_registry
            with camera_registry.lock:
                for w in camera_registry.workers.values():
                    if hasattr(w, "orchestrator") and w.orchestrator:
                        w.orchestrator.reset_track_recognitions()
        except Exception:
            pass

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


