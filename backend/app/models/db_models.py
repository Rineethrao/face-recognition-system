from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, LargeBinary, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class PersonModel(Base):
    __tablename__ = 'persons'
    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String, unique=True, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    name = Column(String(200))
    department = Column(String(100))
    role = Column(String(100))
    phone = Column(String(50))
    email = Column(String(100))
    company = Column(String(200))
    notes = Column(String(1000))
    gallery_version = Column(Integer, default=1)
    source_candidate_id = Column(String(100))
    registered_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime)
    
    embeddings = relationship("EmbeddingModel", back_populates="person")
    images = relationship("PersonImageModel", back_populates="person")

class PersonImageModel(Base):
    __tablename__ = 'person_images'
    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String, ForeignKey('persons.person_id'))
    image_path = Column(String)
    quality_score = Column(Float)
    pose_bin = Column(String)
    gallery_version = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    camera_id = Column(String(100), default='default')
    yaw = Column(Float, default=0.0)
    pitch = Column(Float, default=0.0)
    brightness = Column(Float, default=0.0)
    blur_score = Column(Float, default=0.0)
    
    person = relationship("PersonModel", back_populates="images")

class EmbeddingModel(Base):
    __tablename__ = 'embeddings'
    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String, ForeignKey('persons.person_id'))
    faiss_id = Column(Integer)
    image_id = Column(Integer, ForeignKey('person_images.id'))
    image_path = Column(String)
    gallery_version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime)
    
    person = relationship("PersonModel", back_populates="embeddings")

class CandidateModel(Base):
    __tablename__ = 'candidates'
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(String, unique=True, index=True)
    status = Column(String)
    avg_quality = Column(Float)
    seen_cameras = Column(Text)
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    images = relationship("CandidateImageModel", back_populates="candidate")

class CandidateImageModel(Base):
    __tablename__ = 'candidate_images'
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(String, ForeignKey('candidates.candidate_id'))
    image_path = Column(String)
    embedding_blob = Column(LargeBinary)
    quality_score = Column(Float)
    pose_bin = Column(String)
    camera_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    candidate = relationship("CandidateModel", back_populates="images")

class AuditLogModel(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String)
    person_id = Column(String)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class RecognitionLogModel(Base):
    __tablename__ = 'recognition_logs'
    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String, ForeignKey('persons.person_id'))
    name = Column(String(200))
    similarity = Column(Float)
    track_id = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    camera_id = Column(String(100), default='default')
    embedding_version = Column(Integer, default=1)
    quality_score = Column(Float, default=0.0)
    face_snapshot_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

class CameraModel(Base):
    __tablename__ = 'cameras'
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String(100), unique=True, index=True)
    name = Column(String(100))
    source = Column(String(500))
    location = Column(String(200))
    enabled = Column(Boolean, default=True)
    rotation = Column(Integer, default=0)
    fps_limit = Column(Integer, default=30)
    status = Column(String(50), default="DISCONNECTED")
    last_heartbeat = Column(DateTime)
    error_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
