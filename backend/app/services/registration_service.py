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

logger = logging.getLogger(__name__)

class FaceRegistrationService:
    """
    Unified Person Registration Service.
    Handles all registration workflows:
    - Live camera stream sample collection
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

    # --- 1. Live Camera Stream Registration ---
    def start_registration(self, person_id: str, name: str) -> Tuple[bool, str]:
        self.is_registering = True
        self.target_person_id = person_id
        self.target_name = name
        self.collected_samples.clear()
        logger.info(f"Started registration session for Person ID: {person_id}, Name: {name}")
        return True, f"Registration session started for {name} ({person_id}). Please look directly at the camera."

    def process_frame_registration(self, frame: np.ndarray, detected_faces: List[DetectedFace]) -> Dict[str, Any]:
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

                p_img = PersonImageModel(
                    person_id=person_id,
                    image_path=str(image_path),
                    quality_score=0.90,
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

            self.stop_registration()
            return True, f"Successfully registered person '{name}' ({person_id}) with {sample_count} face samples."

        except Exception as e:
            db.rollback()
            logger.error(f"Error saving live registration for {person_id}: {e}", exc_info=True)
            return False, f"Database transaction failed: {str(e)}"
        finally:
            db.close()

    def stop_registration(self):
        self.is_registering = False
        self.target_person_id = None
        self.target_name = None
        self.collected_samples.clear()

    # --- 2. Photo Upload Registration ---
    def register_from_uploads(self, person_id: str, name: str, image_bytes_list: List[bytes], department: Optional[str] = None, role: Optional[str] = None) -> Tuple[bool, str, int]:
        db = SessionLocal()
        try:
            collected_embeddings = []
            collected_crops = []

            for img_bytes in image_bytes_list:
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is None:
                    continue

                detected = detector_engine.detect(img)
                if not detected:
                    continue

                best_face = max(detected, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
                landmarks_np = np.array(best_face.landmarks)
                aligned_crop = align_face(img, landmarks_np)
                embedding = arcface_recognizer.extract_embedding(aligned_crop)

                collected_embeddings.append(embedding)
                collected_crops.append(aligned_crop)

            if not collected_embeddings:
                return False, "No valid faces detected in uploaded photos. Please upload clearer face photos.", 0

            self._purge_person_resources_internal(person_id, db)

            person = PersonModel(
                person_id=person_id,
                name=name,
                department=department,
                role=role,
                gallery_version=1,
                registered_at=datetime.utcnow()
            )
            db.add(person)
            db.commit()


            person_dir = settings.FACES_DIR / person_id
            os.makedirs(person_dir, exist_ok=True)

            embeddings_matrix = np.array(collected_embeddings, dtype=np.float32)
            faiss_ids = faiss_manager.add_vectors(person_id, name, embeddings_matrix)

            for idx, (crop, f_id) in enumerate(zip(collected_crops, faiss_ids)):
                img_path = person_dir / f"uploaded_{idx+1}.jpg"
                cv2.imwrite(str(img_path), crop)

                p_img = PersonImageModel(
                    person_id=person_id,
                    image_path=str(img_path),
                    quality_score=0.88,
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
                    faiss_id=f_id,
                    image_id=p_img.id,
                    image_path=str(img_path),
                    gallery_version=1,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                db.add(emb_record)

            db.commit()
            return True, f"Successfully registered '{name}' ({person_id}) with {len(collected_embeddings)} face embeddings!", len(collected_embeddings)
        except Exception as e:
            db.rollback()
            logger.error(f"Error in upload registration: {e}", exc_info=True)
            return False, f"Upload registration failed: {str(e)}", 0
        finally:
            db.close()

    # --- 3. Snapshot Registration ---
    def register_from_snapshot(self, person_id: str, name: str, crop_base64: str) -> Tuple[bool, str]:
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

    # --- 4. Deletion & Cleanup ---
    def delete_person(self, person_id: str) -> bool:
        db = SessionLocal()
        try:
            res = self._purge_person_resources_internal(person_id, db)
            db.commit()
            return res
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting person '{person_id}': {e}")
            return False
        finally:
            db.close()

    def _purge_person_resources_internal(self, person_id: str, db) -> bool:
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

registration_service = FaceRegistrationService()
registration_engine = registration_service
delete_existing_person_internal = registration_service._purge_person_resources_internal
