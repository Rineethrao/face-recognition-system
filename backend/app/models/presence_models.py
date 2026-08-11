from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from datetime import datetime
from app.models.db_models import Base

class PersonSessionModel(Base):
    __tablename__ = 'person_sessions'
    
    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String(100), index=True)
    visitor_id = Column(Integer, nullable=True)
    camera_id = Column(String(100), default='default')
    session_start = Column(DateTime, default=datetime.now)
    session_end = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    closed_reason = Column(String(50), nullable=True) # TRACK_LOST, LEFT_SCENE, MIDNIGHT_SPLIT, SYSTEM_RESTART, MANUAL_CLOSE
    created_at = Column(DateTime, default=datetime.now)


class DailyReportModel(Base):
    __tablename__ = 'daily_reports'
    
    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(String(100), index=True)
    person_name = Column(String(200), nullable=True)
    report_date = Column(String(20), index=True) # YYYY-MM-DD
    first_seen = Column(DateTime, default=datetime.now)
    last_seen = Column(DateTime, default=datetime.now)
    total_duration_seconds = Column(Integer, default=0)
    visit_count = Column(Integer, default=0)
    is_currently_present = Column(Boolean, default=False)
    last_camera_id = Column(String(100), default='default')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
