import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from app.config import settings
from app.models.presence_models import PersonSessionModel, DailyReportModel

logger = logging.getLogger("PresenceService")


def format_duration_human(seconds: int, is_live: bool = False) -> str:
    """Format seconds into human readable duration e.g. 7h 05m, 32m, 1h 18m (Live)."""
    if seconds <= 0:
        return "0m (Live)" if is_live else "0m"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        base = f"{hours}h {minutes:02d}m"
    else:
        base = f"{minutes}m"

    return f"{base} (Live)" if is_live else base


class ActiveSessionState:
    def __init__(self, session_db_id: int, person_id: str, person_name: Optional[str], camera_id: str, start_dt: datetime):
        self.session_db_id: int = session_db_id
        self.person_id: str = person_id
        self.person_name: Optional[str] = person_name
        self.camera_id: str = camera_id
        self.session_start: datetime = start_dt
        self.last_seen: datetime = start_dt
        self.last_seen_timestamp: float = time.time()


class PresenceService:
    """
    Enterprise Thread-Safe Person Presence & Session Tracking Engine.
    Tracks session intervals, maintains incremental daily reports, handles midnight splits,
    and calculates live durations on demand.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._active_sessions: Dict[str, ActiveSessionState] = {}  # key: person_id
        self._last_midnight_check_date: str = datetime.now().strftime("%Y-%m-%d")

    def format_duration(self, seconds: int, is_live: bool = False) -> str:
        return format_duration_human(seconds, is_live)

    def on_person_detected(
        self,
        db: Session,
        person_id: str,
        person_name: Optional[str] = None,
        camera_id: str = "default",
        timestamp: Optional[datetime] = None,
        visitor_id: Optional[int] = None
    ):
        """
        Record a person detection.
        If no active session exists for this person, starts a new session in DB.
        If an active session exists, updates last_seen timestamp in memory.
        """
        if not person_id or person_id == "unknown":
            return

        now_dt = timestamp or datetime.now()
        now_ts = time.time()
        today_date_str = now_dt.strftime("%Y-%m-%d")

        with self._lock:
            active = self._active_sessions.get(person_id)

            if active is None:
                # Create new session in DB
                session = PersonSessionModel(
                    person_id=person_id,
                    visitor_id=visitor_id,
                    camera_id=camera_id,
                    session_start=now_dt,
                    closed_reason=None,
                    created_at=now_dt
                )
                db.add(session)
                db.flush()  # populate session.id

                # Upsert DailyReportModel
                report = db.query(DailyReportModel).filter(
                    DailyReportModel.person_id == person_id,
                    DailyReportModel.report_date == today_date_str
                ).first()

                if not report:
                    report = DailyReportModel(
                        person_id=person_id,
                        person_name=person_name or person_id,
                        report_date=today_date_str,
                        first_seen=now_dt,
                        last_seen=now_dt,
                        total_duration_seconds=0,
                        visit_count=0,
                        is_currently_present=True,
                        last_camera_id=camera_id
                    )
                    db.add(report)
                else:
                    report.last_seen = now_dt
                    report.is_currently_present = True
                    report.last_camera_id = camera_id
                    if person_name:
                        report.person_name = person_name

                db.commit()

                self._active_sessions[person_id] = ActiveSessionState(
                    session_db_id=session.id,
                    person_id=person_id,
                    person_name=person_name,
                    camera_id=camera_id,
                    start_dt=now_dt
                )

                logger.info(
                    "[SESSION_START] person_id=%s camera_id=%s time=%s session_id=%d",
                    person_id, camera_id, now_dt.strftime("%H:%M:%S"), session.id
                )
            else:
                # Session already active — update memory buffer AND update DB DailyReportModel last_seen!
                active.last_seen = now_dt
                active.last_seen_timestamp = now_ts
                active.camera_id = camera_id
                if person_name:
                    active.person_name = person_name

                report = db.query(DailyReportModel).filter(
                    DailyReportModel.person_id == person_id,
                    DailyReportModel.report_date == today_date_str
                ).first()
                if report:
                    report.last_seen = now_dt
                    report.is_currently_present = True
                    report.last_camera_id = camera_id
                    if person_name:
                        report.person_name = person_name
                    db.commit()

    def sweep_expired_sessions(self, db: Session):
        """
        Sweeps active sessions that have exceeded the timeout (default 30s).
        Closes expired sessions in DB and updates daily reports.
        """
        timeout_sec = settings.PRESENCE_SESSION_TIMEOUT_SECONDS
        now_ts = time.time()
        expired_ids: List[str] = []

        with self._lock:
            for pid, active in self._active_sessions.items():
                if (now_ts - active.last_seen_timestamp) > timeout_sec:
                    expired_ids.append(pid)

            for pid in expired_ids:
                active = self._active_sessions.pop(pid, None)
                if not active:
                    continue

                session_end = active.last_seen
                duration = int(max(0, (session_end - active.session_start).total_seconds()))

                # Update session DB record
                sess_record = db.query(PersonSessionModel).filter(
                    PersonSessionModel.id == active.session_db_id
                ).first()

                if sess_record:
                    sess_record.session_end = session_end
                    sess_record.duration_seconds = duration
                    sess_record.closed_reason = "TRACK_LOST"

                # Update DailyReportModel
                date_str = active.session_start.strftime("%Y-%m-%d")
                report = db.query(DailyReportModel).filter(
                    DailyReportModel.person_id == pid,
                    DailyReportModel.report_date == date_str
                ).first()

                if report:
                    report.last_seen = session_end
                    report.total_duration_seconds = (report.total_duration_seconds or 0) + duration
                    report.visit_count = (report.visit_count or 0) + 1
                    report.is_currently_present = False

                db.commit()

                logger.info(
                    "[SESSION_END] person_id=%s duration=%ds reason=TRACK_LOST",
                    pid, duration
                )
                if report:
                    logger.info(
                        "[REPORT_UPDATE] person_id=%s daily_duration=%ds visit_count=%d",
                        pid, report.total_duration_seconds, report.visit_count
                    )

    def split_midnight_sessions(self, db: Session):
        """
        Executes daily at 00:00: closes all active sessions at 23:59:59 with MIDNIGHT_SPLIT
        and re-opens sessions starting at 00:00:00 for currently present individuals.
        """
        now = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")

        with self._lock:
            if current_date_str == self._last_midnight_check_date:
                return

            yesterday_date_str = self._last_midnight_check_date
            self._last_midnight_check_date = current_date_str

            active_pids = list(self._active_sessions.keys())
            if not active_pids:
                return

            midnight_dt = datetime.strptime(current_date_str, "%Y-%m-%d")
            split_end = midnight_dt - timedelta(seconds=1)

            for pid in active_pids:
                active = self._active_sessions.get(pid)
                if not active:
                    continue

                # Close yesterday's part of the session
                duration = int(max(0, (split_end - active.session_start).total_seconds()))
                sess_record = db.query(PersonSessionModel).filter(
                    PersonSessionModel.id == active.session_db_id
                ).first()

                if sess_record:
                    sess_record.session_end = split_end
                    sess_record.duration_seconds = duration
                    sess_record.closed_reason = "MIDNIGHT_SPLIT"

                report = db.query(DailyReportModel).filter(
                    DailyReportModel.person_id == pid,
                    DailyReportModel.report_date == yesterday_date_str
                ).first()

                if report:
                    report.last_seen = split_end
                    report.total_duration_seconds = (report.total_duration_seconds or 0) + duration
                    report.visit_count = (report.visit_count or 0) + 1
                    report.is_currently_present = False

                db.commit()

                logger.info(
                    "[MIDNIGHT_SPLIT] person_id=%s old_report=%s new_report=%s duration=%ds",
                    pid, yesterday_date_str, current_date_str, duration
                )

                # Re-open fresh session for today's date
                new_session = PersonSessionModel(
                    person_id=pid,
                    camera_id=active.camera_id,
                    session_start=midnight_dt,
                    closed_reason=None,
                    created_at=midnight_dt
                )
                db.add(new_session)
                db.flush()

                new_report = DailyReportModel(
                    person_id=pid,
                    person_name=active.person_name or pid,
                    report_date=current_date_str,
                    first_seen=midnight_dt,
                    last_seen=midnight_dt,
                    total_duration_seconds=0,
                    visit_count=0,
                    is_currently_present=True,
                    last_camera_id=active.camera_id
                )
                db.add(new_report)
                db.commit()

                # Update in-memory reference
                active.session_db_id = new_session.id
                active.session_start = midnight_dt

    def close_all_sessions_on_shutdown(self, db: Session):
        """Cleanly close all active sessions during server shutdown."""
        now = datetime.now()
        with self._lock:
            for pid, active in list(self._active_sessions.items()):
                duration = int(max(0, (now - active.session_start).total_seconds()))
                sess_record = db.query(PersonSessionModel).filter(
                    PersonSessionModel.id == active.session_db_id
                ).first()
                if sess_record:
                    sess_record.session_end = now
                    sess_record.duration_seconds = duration
                    sess_record.closed_reason = "SYSTEM_RESTART"

                date_str = active.session_start.strftime("%Y-%m-%d")
                report = db.query(DailyReportModel).filter(
                    DailyReportModel.person_id == pid,
                    DailyReportModel.report_date == date_str
                ).first()
                if report:
                    report.last_seen = now
                    report.total_duration_seconds = (report.total_duration_seconds or 0) + duration
                    report.visit_count = (report.visit_count or 0) + 1
                    report.is_currently_present = False

            db.commit()
            self._active_sessions.clear()

    def get_live_presence(self, db: Session, person_id: str, date_str: str) -> Dict[str, Any]:
        """
        Retrieve live presence details for a person on a given report date.
        Dynamically calculates active session elapsed time if currently present.
        """
        with self._lock:
            active = self._active_sessions.get(person_id)
            report = db.query(DailyReportModel).filter(
                DailyReportModel.person_id == person_id,
                DailyReportModel.report_date == date_str
            ).first()

            stored_sec = report.total_duration_seconds if report else 0
            visits = report.visit_count if report else 0
            first_seen = report.first_seen if report else None
            last_seen = report.last_seen if report else None

            is_present = active is not None
            live_elapsed = 0
            if is_present and active:
                live_elapsed = int(max(0, (datetime.now() - active.session_start).total_seconds()))
                if not first_seen:
                    first_seen = active.session_start
                last_seen = active.last_seen

            total_sec = stored_sec + live_elapsed
            effective_visits = visits if not is_present else max(1, visits + 1)

            return {
                "person_id": person_id,
                "report_date": date_str,
                "is_currently_present": is_present,
                "total_duration_seconds": total_sec,
                "total_duration": self.format_duration(total_sec, is_live=is_present),
                "visit_count": effective_visits,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "status": "Live" if is_present else "Offline"
            }


presence_service = PresenceService()
