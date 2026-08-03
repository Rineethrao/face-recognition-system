"""
Reports API
-----------
Aggregated analytics + downloadable reports (CSV and PDF) over recognition
history, with optional date range / camera / person filters.
"""
import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.db_models import RecognitionLogModel, PersonModel
from app.models.schemas import APIResponse

logger = logging.getLogger("Reports")
router = APIRouter(prefix="/reports", tags=["Analytics & Reports"])


def _parse_range(start_date: Optional[str], end_date: Optional[str]):
    """Defaults to the last 7 days when no range is supplied."""
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end_dt = datetime.utcnow() + timedelta(days=1)

    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        start_dt = end_dt - timedelta(days=7)

    return start_dt, end_dt


def _query_logs(db, start_dt, end_dt, camera_id: Optional[str], person_id: Optional[str]):
    q = db.query(RecognitionLogModel).filter(
        RecognitionLogModel.timestamp >= start_dt,
        RecognitionLogModel.timestamp < end_dt,
    )
    if camera_id:
        q = q.filter(RecognitionLogModel.camera_id == camera_id)
    if person_id:
        q = q.filter(RecognitionLogModel.person_id == person_id)
    return q.order_by(RecognitionLogModel.timestamp.asc()).all()


@router.get("/summary", response_model=APIResponse)
def get_report_summary(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    camera_id: Optional[str] = Query(None),
):
    """Aggregated stats for the Reports & Analytics dashboard."""
    db = SessionLocal()
    try:
        start_dt, end_dt = _parse_range(start_date, end_date)
        logs = _query_logs(db, start_dt, end_dt, camera_id, None)

        total_events = len(logs)
        known_events = [l for l in logs if l.person_id and l.person_id != "unknown"]
        unknown_events = total_events - len(known_events)
        unique_persons = len({l.person_id for l in known_events})

        by_camera: dict = {}
        by_day: dict = {}
        by_person: dict = {}

        for l in logs:
            cam = l.camera_id or "default"
            by_camera[cam] = by_camera.get(cam, 0) + 1

            day_key = l.timestamp.strftime("%Y-%m-%d") if l.timestamp else "unknown"
            by_day[day_key] = by_day.get(day_key, 0) + 1

            if l.person_id and l.person_id != "unknown":
                key = (l.person_id, l.name or l.person_id)
                by_person[key] = by_person.get(key, 0) + 1

        top_persons = sorted(
            [{"person_id": pid, "name": name, "count": count} for (pid, name), count in by_person.items()],
            key=lambda x: x["count"], reverse=True
        )[:10]

        total_persons_registered = db.query(func.count(PersonModel.id)).scalar() or 0

        return APIResponse(
            status="success",
            message="Report summary generated.",
            data={
                "range": {"start": start_dt.strftime("%Y-%m-%d"), "end": (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")},
                "total_events": total_events,
                "known_events": len(known_events),
                "unknown_events": unknown_events,
                "unique_persons_seen": unique_persons,
                "total_persons_registered": total_persons_registered,
                "by_camera": [{"camera_id": k, "count": v} for k, v in sorted(by_camera.items(), key=lambda x: -x[1])],
                "by_day": [{"date": k, "count": v} for k, v in sorted(by_day.items())],
                "top_persons": top_persons,
            }
        )
    finally:
        db.close()


@router.get("/export/csv")
def export_csv(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None),
):
    """Streams a CSV of recognition events for the given filters."""
    db = SessionLocal()
    try:
        start_dt, end_dt = _parse_range(start_date, end_date)
        logs = _query_logs(db, start_dt, end_dt, camera_id, person_id)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["ID", "Person ID", "Name", "Similarity", "Camera", "Track ID", "Timestamp"])
        for l in logs:
            writer.writerow([
                l.id,
                l.person_id or "unknown",
                l.name or "Unknown",
                f"{(l.similarity or 0):.4f}",
                l.camera_id or "default",
                l.track_id,
                l.timestamp.strftime("%Y-%m-%d %H:%M:%S") if l.timestamp else "",
            ])
        buffer.seek(0)

        filename = f"recognition_report_{start_dt.strftime('%Y%m%d')}_{(end_dt - timedelta(days=1)).strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        db.close()


@router.get("/export/pdf")
def export_pdf(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
):
    """Generates a summary PDF report (stats table + recent event log)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    db = SessionLocal()
    try:
        start_dt, end_dt = _parse_range(start_date, end_date)
        logs = _query_logs(db, start_dt, end_dt, camera_id, None)

        known_events = [l for l in logs if l.person_id and l.person_id != "unknown"]
        unique_persons = len({l.person_id for l in known_events})

        by_camera: dict = {}
        for l in logs:
            cam = l.camera_id or "default"
            by_camera[cam] = by_camera.get(cam, 0) + 1

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=15 * mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("TitleX", parent=styles["Title"], textColor=colors.HexColor("#1e3a5f"))
        elements = []

        elements.append(Paragraph("AI.Vision — Face Recognition Report", title_style))
        elements.append(Paragraph(
            f"Period: {start_dt.strftime('%Y-%m-%d')} to {(end_dt - timedelta(days=1)).strftime('%Y-%m-%d')}"
            + (f" &nbsp;|&nbsp; Camera: {camera_id}" if camera_id else ""),
            styles["Normal"]
        ))
        elements.append(Spacer(1, 10 * mm))

        summary_data = [
            ["Metric", "Value"],
            ["Total Recognition Events", str(len(logs))],
            ["Known / Recognized Events", str(len(known_events))],
            ["Unknown Face Detections", str(len(logs) - len(known_events))],
            ["Unique Persons Seen", str(unique_persons)],
        ]
        summary_table = Table(summary_data, colWidths=[80 * mm, 60 * mm])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 8 * mm))

        elements.append(Paragraph("Events by Camera", styles["Heading3"]))
        cam_rows = [["Camera ID", "Events"]] + [[k, str(v)] for k, v in sorted(by_camera.items(), key=lambda x: -x[1])]
        cam_table = Table(cam_rows, colWidths=[80 * mm, 60 * mm])
        cam_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f6690")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        elements.append(cam_table)
        elements.append(Spacer(1, 8 * mm))

        elements.append(Paragraph(f"Recent Events (latest {min(50, len(logs))} shown)", styles["Heading3"]))
        event_rows = [["Timestamp", "Person", "Camera", "Similarity"]]
        for l in list(reversed(logs))[:50]:
            event_rows.append([
                l.timestamp.strftime("%Y-%m-%d %H:%M:%S") if l.timestamp else "",
                l.name or "Unknown",
                l.camera_id or "default",
                f"{(l.similarity or 0) * 100:.1f}%",
            ])
        event_table = Table(event_rows, colWidths=[45 * mm, 45 * mm, 30 * mm, 25 * mm], repeatRows=1)
        event_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f6690")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f8")]),
        ]))
        elements.append(event_table)

        doc.build(elements)
        buffer.seek(0)

        filename = f"recognition_report_{start_dt.strftime('%Y%m%d')}_{(end_dt - timedelta(days=1)).strftime('%Y%m%d')}.pdf"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        db.close()
