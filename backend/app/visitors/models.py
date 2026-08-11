from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, LargeBinary, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.models.db_models import Base

class VisitorModel(Base):
    __tablename__ = 'visitors'

    id = Column(Integer, primary_key=True, index=True)
    visitor_code = Column(String(100), unique=True, index=True, nullable=False)
    date_key = Column(String(20), index=True, nullable=False)
    created_date = Column(String(20), index=True, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    first_camera_id = Column(String(100), default='default')
    last_camera_id = Column(String(100), default='default')
    sighting_count = Column(Integer, default=1)
    primary_snapshot_path = Column(String(500), nullable=True)
    status = Column(String(50), default='active', index=True)  # active, inactive, promoted
    promoted_person_id = Column(String(100), ForeignKey('persons.person_id'), nullable=True)

    face_samples = relationship("VisitorFaceSampleModel", back_populates="visitor", cascade="all, delete-orphan")
    sightings = relationship("VisitorSightingModel", back_populates="visitor", cascade="all, delete-orphan")
    visits = relationship("VisitorVisitModel", back_populates="visitor", cascade="all, delete-orphan")


class VisitorVisitModel(Base):
    __tablename__ = 'visitor_visits'

    id = Column(Integer, primary_key=True, index=True)
    visitor_id = Column(Integer, ForeignKey('visitors.id'), nullable=False, index=True)
    date_key = Column(String(20), index=True, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    duration_seconds = Column(Float, default=0.0)
    sighting_count = Column(Integer, default=1)
    status = Column(String(50), default='active')

    visitor = relationship("VisitorModel", back_populates="visits")


class VisitorFaceSampleModel(Base):
    __tablename__ = 'visitor_face_samples'

    id = Column(Integer, primary_key=True, index=True)
    visitor_id = Column(Integer, ForeignKey('visitors.id'), nullable=False, index=True)
    embedding_blob = Column(LargeBinary, nullable=False)
    camera_id = Column(String(100), default='default')
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    quality_score = Column(Float, default=0.0)
    yaw = Column(Float, default=0.0)
    pitch = Column(Float, default=0.0)
    blur_score = Column(Float, default=0.0)
    snapshot_path = Column(String(500), nullable=True)
    gallery_eligible = Column(Boolean, default=True, index=True)

    visitor = relationship("VisitorModel", back_populates="face_samples")


class VisitorSightingModel(Base):
    __tablename__ = 'visitor_sightings'

    id = Column(Integer, primary_key=True, index=True)
    visitor_id = Column(Integer, ForeignKey('visitors.id'), nullable=False, index=True)
    camera_id = Column(String(100), default='default', index=True)
    track_id = Column(String(100), nullable=False)
    entered_at = Column(DateTime, default=datetime.now, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    best_similarity = Column(Float, default=0.0)
    second_best_similarity = Column(Float, default=0.0)
    match_margin = Column(Float, default=0.0)
    identity_confidence = Column(Float, default=0.0)
    snapshot_path = Column(String(500), nullable=True)
    metadata_json = Column(Text, nullable=True)

    visitor = relationship("VisitorModel", back_populates="sightings")

