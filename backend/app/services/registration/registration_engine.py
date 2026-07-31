import os
import cv2
import base64
import logging
import numpy as np
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

from app.config import settings
from app.core.database import SessionLocal
from app.core.faiss_index import faiss_manager
from app.core.detector import detector_engine
from app.core.recognizer import arcface_recognizer
from app.core.utils import evaluate_face_quality, align_face
from app.models.db_models import (
    PersonModel, PersonImageModel, EmbeddingModel,
    CandidateModel, AuditLogModel, RecognitionLogModel
)
from app.models.schemas import DetectedFace

from app.services.quality.pose_diversity import pose_diversity_engine

logger = logging.getLogger(__name__)

class RegistrationEngine:
    """
    Unified Enterprise Person Registration & Gallery Lifecycle Engine.
    Handles all registration workflows:
    - Live camera stream sample collection session
    - Photo file uploads
    - Live face snapshot crops
    - Candidate profiles
    - Person profile updates & deletions
    """
    def __init__(self):
        self.is_registering: bool = False
        self.target_person_id: Optional[str] = None
        self.target_name: Optional[str] = None
        self.target_samples: int = settings.REGISTRATION_SAMPLE_COUNT
        self.collected_samples: List[Dict[str, Any]] = []

    # --- 1. Live Camera Stream Registration Session ---
    def start_registration(self, person_id: str, name: str) -> Tuple[bool, str]:
        """Starts live stream face registration session."""
        self.is_registering = True
        self.target_person_id = person_id
        self.target_name = name
        self.collected_samples.clear()
        logger.info(f"Started live stream face registration session for Person ID: {person_id}, Name: {name}")
        return True, f"Registration session started for {name} ({person_id}). Please look directly at the camera."

    def process_frame_registration(self, frame: np.ndarray, detected_faces: List[DetectedFace]) -> Dict[str, Any]:
        """Evaluates face frame quality during live stream registration."""
        if not self.is_registering:
            return {"is_registering": False, "message": "No active registration session."}

        if len(detected_faces) == 0:
            return {
                "is_registering": True,
                "samples_collected": len(self.collected_samples),
                "target_samples": self.target_samples,
                "message": "No face detected in frame. Please center your face."
            }

        if len(detected_faces) > 1:
            return {
                "is_registering": True,
                "samples_collected": len(self.collected_samples),
                "target_samples": self.target_samples,
                "message": "Multiple faces detected! Please ensure only one person is in front of the camera."
            }

        face = detected_faces[0]
        is_good, reason, blur_score = evaluate_face_quality(frame, face.bbox, face.landmarks)

        if not is_good:
            return {
                "is_registering": True,
                "samples_collected": len(self.collected_samples),
                "target_samples": self.target_samples,
                "message": f"Quality Check Failed: {reason}"
            }

        landmarks_np = np.array(face.landmarks)
        aligned_crop = align_face(frame, landmarks_np)
        embedding = arcface_recognizer.extract_embedding(aligned_crop)

        self.collected_samples.append({
            "frame": frame.copy(),
            "aligned": aligned_crop.copy(),
            "embedding": embedding
        })

        collected_count = len(self.collected_samples)
        logger.info(f"Captured registration sample {collected_count}/{self.target_samples} for {self.target_person_id}")

        if collected_count >= self.target_samples:
            return {
                "is_registering": True,
                "samples_collected": collected_count,
                "target_samples": self.target_samples,
                "ready_to_save": True,
                "message": f"Collected all {self.target_samples} required quality samples! Ready to save."
            }

        return {
            "is_registering": True,
            "samples_collected": collected_count,
            "target_samples": self.target_samples,
            "ready_to_save": False,
            "message": f"Sample {collected_count}/{self.target_samples} captured successfully! Hold still..."
        }

    def save_registration(self) -> Tuple[bool, str]:
        """Saves collected live stream samples into Person profile, FAISS, and disk."""
        if not self.is_registering or not self.target_person_id:
            return False, "No active registration session to save."

        if len(self.collected_samples) == 0:
            return False, "No valid face samples collected yet."

        person_id = self.target_person_id
        name = self.target_name

        db = SessionLocal()
        try:
            self._purge_person_resources_internal(person_id, db)

            person = PersonModel(
                person_id=person_id,
                name=name,
                gallery_version=1,
                registered_at=datetime.utcnow()
            )
            db.add(person)
            db.commit()

            person_dir = settings.FACES_DIR / person_id
            os.makedirs(person_dir, exist_ok=True)

            embeddings_matrix = np.array([sample["embedding"] for sample in self.collected_samples])
            faiss_ids = faiss_manager.add_vectors(person_id, name, embeddings_matrix)

            for idx, (sample, f_id) in enumerate(zip(self.collected_samples, faiss_ids)):
                image_filename = f"sample_{idx + 1}.jpg"
                image_path = person_dir / image_filename
                cv2.imwrite(str(image_path), sample["aligned"])

                pose_b = pose_diversity_engine.classify_pose(
                    0.0, 0.0,
                    aligned_crop=sample["aligned"],
                    landmarks=np.array([[38,51],[73,51],[56,71],[41,92],[70,92]])
                )
                p_img = PersonImageModel(
                    person_id=person_id,
                    image_path=str(image_path),
                    quality_score=0.90,
                    pose_bin=pose_b,
                    gallery_version=1,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(p_img)
                db.commit()
                db.refresh(p_img)

                emb_record = EmbeddingModel(
                    person_id=person_id,
                    faiss_id=f_id,
                    image_id=p_img.id,
                    image_path=str(image_path),
                    gallery_version=1,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(emb_record)

            db.commit()
            sample_count = len(self.collected_samples)
            logger.info(f"Successfully registered {name} ({person_id}) with {sample_count} face embeddings.")

            # Trigger hot-reload across all running camera workers so all visible faces are re-queried instantly
            try:
                from app.services.camera.camera_registry import camera_registry
                camera_registry.reload_all_recognitions()
            except Exception as r_err:
                logger.error(f"Error triggering hot-reload: {r_err}")

            self.stop_registration()
            return True, f"Successfully registered person '{name}' ({person_id}) with {sample_count} face samples."

        except Exception as e:
            db.rollback()
            logger.error(f"Error saving live registration for {person_id}: {e}", exc_info=True)
            return False, f"Database transaction failed: {str(e)}"
        finally:
            db.close()

    def stop_registration(self):
        """Stops live registration session."""
        self.is_registering = False
        self.target_person_id = None
        self.target_name = None
        self.collected_samples.clear()

    # --- 2. Photo Upload Registration ---
    def register_from_uploads(
        self,
        person_id: str,
        name: str,
        image_bytes_list: List[bytes],
        department: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        company: Optional[str] = None,
        notes: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> Tuple[bool, str, int]:
        """Registers a person by parsing 1 or more uploaded photo files."""
        db = SessionLocal()
        try:
            collected_embeddings = []
            collected_crops = []

            from app.services.quality.quality_engine import quality_engine

            for img_bytes in image_bytes_list:
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is None:
                    continue

                detected = detector_engine.detect(img)
                if detected:
                    best_face = max(detected, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
                    landmarks_np = np.array(best_face.landmarks)
                    aligned_crop = align_face(img, landmarks_np)
                    embedding = arcface_recognizer.extract_embedding(aligned_crop)
                    
                    eval_res = quality_engine.evaluate(img, best_face.bbox, best_face.landmarks)
                    q_score = float(eval_res.get("quality_score", 0.0))
                    yaw = float(eval_res.get("pose_yaw", 0.0))
                    pitch = float(eval_res.get("pose_pitch", 0.0))
                    brightness = float(eval_res.get("brightness", 0.0))
                    blur = float(eval_res.get("blur_score", 0.0))
                else:
                    # Fallback for tightly-cropped/pre-aligned crops
                    aligned_crop = cv2.resize(img, (112, 112))
                    embedding = arcface_recognizer.extract_embedding(aligned_crop)
                    q_score = 0.85
                    yaw = 0.0
                    pitch = 0.0
                    brightness = 127.0
                    blur = 80.0

                if embedding is not None:
                    collected_embeddings.append(embedding)
                    collected_crops.append({
                        "aligned": aligned_crop,
                        "quality_score": q_score,
                        "yaw": yaw,
                        "pitch": pitch,
                        "brightness": brightness,
                        "blur_score": blur
                    })

            if not collected_embeddings:
                return False, "No valid faces detected in uploaded photos. Please upload clearer face photos.", 0

            self._purge_person_resources_internal(person_id, db)

            person = PersonModel(
                person_id=person_id,
                name=name,
                first_name=first_name,
                last_name=last_name,
                department=department,
                role=role,
                phone=phone,
                email=email,
                company=company,
                notes=notes,
                gallery_version=1,
                registered_at=datetime.utcnow()
            )

            db.add(person)
            db.commit()

            person_dir = settings.FACES_DIR / person_id
            os.makedirs(person_dir, exist_ok=True)

            embeddings_matrix = np.array(collected_embeddings, dtype=np.float32)
            faiss_ids = faiss_manager.add_vectors(person_id, name, embeddings_matrix)

            for idx, (crop_info, f_id) in enumerate(zip(collected_crops, faiss_ids)):
                crop = crop_info["aligned"]
                img_path = person_dir / f"uploaded_{idx+1}.jpg"
                cv2.imwrite(str(img_path), crop)

                pose_b = pose_diversity_engine.classify_pose(
                    0.0, 0.0,
                    aligned_crop=crop,
                    landmarks=np.array([[38,51],[73,51],[56,71],[41,92],[70,92]])
                )
                p_img = PersonImageModel(
                    person_id=person_id,
                    image_path=str(img_path),
                    quality_score=crop_info["quality_score"],
                    yaw=crop_info["yaw"],
                    pitch=crop_info["pitch"],
                    brightness=crop_info["brightness"],
                    blur_score=crop_info["blur_score"],
                    pose_bin=pose_b,
                    gallery_version=1,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(p_img)
                db.commit()
                db.refresh(p_img)

                emb_record = EmbeddingModel(
                    person_id=person_id,
                    faiss_id=f_id,
                    image_id=p_img.id,
                    image_path=str(img_path),
                    gallery_version=1,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(emb_record)

            db.commit()

            try:
                from app.services.camera.camera_registry import camera_registry
                camera_registry.reload_all_recognitions()
            except Exception as r_err:
                logger.error(f"Error triggering hot-reload: {r_err}")

            return True, f"Successfully registered '{name}' ({person_id}) with {len(collected_embeddings)} face embeddings!", len(collected_embeddings)
        except Exception as e:
            db.rollback()
            logger.error(f"Error in upload registration: {e}", exc_info=True)
            return False, f"Upload registration failed: {str(e)}", 0
        finally:
            db.close()

    # --- 3. Live Snapshot Thumbnail Registration ---
    def register_from_snapshot(self, person_id: str, name: str, crop_base64: str) -> Tuple[bool, str]:
        """Registers a person from a base64 encoded face crop snapshot."""
        db = SessionLocal()
        try:
            b64_data = crop_base64.split(",")[-1]
            img_bytes = base64.b64decode(b64_data)
            nparr = np.frombuffer(img_bytes, np.uint8)
            crop_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if crop_img is None:
                return False, "Invalid image snapshot data."

            if crop_img.shape[:2] != (112, 112):
                crop_img = cv2.resize(crop_img, (112, 112))

            embedding = arcface_recognizer.extract_embedding(crop_img)

            self._purge_person_resources_internal(person_id, db)

            person = PersonModel(
                person_id=person_id,
                name=name,
                gallery_version=1,
                registered_at=datetime.utcnow()
            )
            db.add(person)
            db.commit()

            person_dir = settings.FACES_DIR / person_id
            os.makedirs(person_dir, exist_ok=True)
            img_path = person_dir / "snapshot_1.jpg"
            cv2.imwrite(str(img_path), crop_img)

            embeddings_matrix = np.array([embedding], dtype=np.float32)
            faiss_ids = faiss_manager.add_vectors(person_id, name, embeddings_matrix)

            p_img = PersonImageModel(
                person_id=person_id,
                image_path=str(img_path),
                quality_score=0.85,
                pose_bin="FRONTAL",
                gallery_version=1,
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.add(p_img)
            db.commit()
            db.refresh(p_img)

            emb_record = EmbeddingModel(
                person_id=person_id,
                faiss_id=faiss_ids[0],
                image_id=p_img.id,
                image_path=str(img_path),
                gallery_version=1,
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.add(emb_record)
            db.commit()

            return True, f"Successfully registered '{name}' ({person_id}) from live snapshot!"
        except Exception as e:
            db.rollback()
            logger.error(f"Error in snapshot registration: {e}", exc_info=True)
            return False, f"Snapshot registration failed: {str(e)}"
        finally:
            db.close()

    # --- 4. Candidate Registration ---
    def register_person_from_candidate(
        self,
        candidate_id: str,
        person_id: str,
        name: str,
        department: Optional[str] = None,
        role: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Registers a person from a curated candidate profile."""
        db = SessionLocal()
        try:
            candidate = db.query(CandidateModel).filter(CandidateModel.candidate_id == candidate_id).first()
            if not candidate:
                return False, f"Candidate '{candidate_id}' not found.", {}

            if not candidate.images:
                return False, f"Candidate '{candidate_id}' has no images.", {}

            self._purge_person_resources_internal(person_id, db)

            person = PersonModel(
                person_id=person_id,
                name=name,
                department=department,
                role=role,
                gallery_version=1,
                source_candidate_id=candidate_id,
                registered_at=datetime.utcnow()
            )
            db.add(person)
            db.commit()

            person_dir = settings.FACES_DIR / person_id
            os.makedirs(person_dir, exist_ok=True)

            collected_embeddings = []
            registered_images = []

            for idx, c_img in enumerate(candidate.images):
                if not c_img.image_path or not os.path.exists(c_img.image_path):
                    continue

                crop = cv2.imread(c_img.image_path)
                if crop is None:
                    continue

                img_name = f"gallery_v1_{idx+1}.jpg"
                dest_path = person_dir / img_name
                cv2.imwrite(str(dest_path), crop)

                emb = arcface_recognizer.extract_embedding(crop)
                collected_embeddings.append(emb)

                p_img = PersonImageModel(
                    person_id=person_id,
                    image_path=str(dest_path),
                    quality_score=c_img.quality_score,
                    pose_bin=c_img.pose_bin,
                    gallery_version=1,
                    is_active=True,
                    camera_id=c_img.camera_id,
                    created_at=datetime.utcnow()
                )
                db.add(p_img)
                registered_images.append(p_img)

            db.commit()

            if not collected_embeddings:
                return False, "Failed to extract embeddings from candidate images.", {}

            emb_matrix = np.array(collected_embeddings, dtype=np.float32)
            faiss_ids = faiss_manager.add_vectors(person_id, name, emb_matrix)

            for p_img, f_id in zip(registered_images, faiss_ids):
                emb_rec = EmbeddingModel(
                    person_id=person_id,
                    faiss_id=f_id,
                    image_id=p_img.id,
                    image_path=p_img.image_path,
                    gallery_version=1,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(emb_rec)

            candidate.status = "REGISTERED"

            audit = AuditLogModel(
                action="REGISTER_PERSON",
                entity_type="PERSON",
                entity_id=person_id,
                details=f"Registered '{name}' ({person_id}) from candidate '{candidate_id}' with {len(collected_embeddings)} samples.",
                performed_by="operator"
            )
            db.add(audit)
            db.commit()

            return True, f"Successfully registered '{name}' ({person_id})", {
                "person_id": person_id,
                "name": name,
                "gallery_version": 1,
                "samples_count": len(collected_embeddings)
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error registering person from candidate: {e}", exc_info=True)
            return False, f"Registration transaction failed: {str(e)}", {}
        finally:
            db.close()

    # --- 5. Deletion & Cleanup ---
    def delete_person(self, person_id: str) -> bool:
        """Cleanly deletes a person profile, database embeddings, FAISS vectors, and disk images."""
        db = SessionLocal()
        try:
            res = self._purge_person_resources_internal(person_id, db)
            db.commit()

            try:
                from app.services.camera.camera_registry import camera_registry
                camera_registry.reload_all_recognitions()
            except Exception as r_err:
                logger.error(f"Error triggering hot-reload after delete: {r_err}")

            return res
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting person '{person_id}': {e}")
            return False
        finally:
            db.close()

    def _purge_person_resources_internal(self, person_id: str, db) -> bool:
        """Internal helper to clean database, active events, FAISS index, and disk files before upsert/delete."""
        import shutil
        person = db.query(PersonModel).filter(PersonModel.person_id == person_id).first()
        if person:
            db.query(RecognitionLogModel).filter(RecognitionLogModel.person_id == person_id).delete()
            db.delete(person)
            db.commit()

            faiss_manager.remove_person(person_id)

            person_dir = settings.FACES_DIR / person_id
            if person_dir.exists():
                shutil.rmtree(person_dir, ignore_errors=True)
            return True
        return False

registration_engine = RegistrationEngine()
# Re-export alias for legacy code compatibility
registration_service = registration_engine
delete_existing_person_internal = registration_engine._purge_person_resources_internal
