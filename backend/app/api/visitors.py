import os
import csv
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Path
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.schemas import APIResponse, FlexibleModel
from app.visitors.models import VisitorModel, VisitorFaceSampleModel, VisitorSightingModel
from app.visitors.visitor_repository import visitor_repository, get_operational_date_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visitors", tags=["Visitor Tracking"])


class VisitorPromoteRequest(FlexibleModel):
    first_name: str
    last_name: str
    department: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


def format_snapshot_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    normalized = str(path).replace("\\", "/")
    if "storage/visitors/" in normalized:
        rel = normalized.split("storage/visitors/")[-1]
        return f"/faces/visitors/{rel}"
    elif "visitors/" in normalized:
        rel = normalized.split("visitors/")[-1]
        return f"/faces/visitors/{rel}"
    elif "storage/snapshots/" in normalized:
        rel = normalized.split("storage/snapshots/")[-1]
        return f"/faces/snapshots/{rel}"
    elif "snapshots/" in normalized:
        rel = normalized.split("snapshots/")[-1]
        return f"/faces/snapshots/{rel}"
    filename = os.path.basename(path)
    return f"/faces/visitors/{filename}"


def resolve_visitor_primary_snapshot_url(v: VisitorModel, db: Session) -> Optional[str]:
    """Resolves primary face snapshot URL for a visitor with robust fallbacks across DB and disk storage."""
    if v.primary_snapshot_path and os.path.exists(v.primary_snapshot_path):
        url = format_snapshot_url(v.primary_snapshot_path)
        if url:
            return url

    sighting = db.query(VisitorSightingModel).filter(
        VisitorSightingModel.visitor_id == v.id,
        VisitorSightingModel.snapshot_path.isnot(None)
    ).order_by(VisitorSightingModel.id.desc()).first()
    if sighting and sighting.snapshot_path and os.path.exists(sighting.snapshot_path):
        return format_snapshot_url(sighting.snapshot_path)

    sample = db.query(VisitorFaceSampleModel).filter(
        VisitorFaceSampleModel.visitor_id == v.id,
        VisitorFaceSampleModel.snapshot_path.isnot(None)
    ).order_by(VisitorFaceSampleModel.id.desc()).first()
    if sample and sample.snapshot_path and os.path.exists(sample.snapshot_path):
        return format_snapshot_url(sample.snapshot_path)

    from app.models.db_models import RecognitionLogModel
    log = db.query(RecognitionLogModel).filter(
        RecognitionLogModel.person_id == v.visitor_code,
        RecognitionLogModel.face_snapshot_path.isnot(None)
    ).order_by(RecognitionLogModel.id.desc()).first()
    if log and log.face_snapshot_path and os.path.exists(log.face_snapshot_path):
        return format_snapshot_url(log.face_snapshot_path)

    try:
        from app.visitors.visitor_repository import get_visitor_folder_paths
        creation_date = v.created_date or v.date_key
        v_dir, _, _ = get_visitor_folder_paths(creation_date, v.visitor_code)
        
        if v_dir.exists():
            jpegs = list(v_dir.glob('*.jpg')) + list(v_dir.glob('samples/*.jpg')) + list(v_dir.glob('sightings/*.jpg'))
            if jpegs:
                return format_snapshot_url(str(jpegs[0]))

        try:
            import re
            m = re.search(r'(\d+)$', v.visitor_code)
            if m:
                seq_num = int(m.group(1))
                legacy_dir = v_dir.parent / f"Visitor_{seq_num}"
                if legacy_dir.exists():
                    legacy_jpegs = list(legacy_dir.glob('*.jpg')) + list(legacy_dir.glob('samples/*.jpg')) + list(legacy_dir.glob('sightings/*.jpg'))
                    if legacy_jpegs:
                        return format_snapshot_url(str(legacy_jpegs[0]))
        except Exception:
            pass
    except Exception:
        pass

    return None




@router.get("/dates", response_model=APIResponse)
def get_visitor_dates(db: Session = Depends(get_db)):
    """Retrieves list of distinct operational dates with visitor counts."""
    records = db.query(
        VisitorModel.date_key,
        func.count(VisitorModel.id).label("count")
    ).group_by(VisitorModel.date_key).order_by(VisitorModel.date_key.desc()).all()

    today_key = get_operational_date_key()
    found_keys = {r[0] for r in records}

    items = []
    if today_key not in found_keys:
        formatted = today_key
        try:
            if "-" in today_key:
                today_dt = datetime.strptime(today_key, "%Y-%m-%d")
            else:
                today_dt = datetime.strptime(today_key, "%Y%m%d")
            formatted = today_dt.strftime("%d-%m-%Y")
        except Exception:
            pass
        items.append({
            "date_key": today_key,
            "date_formatted": formatted,
            "count": 0,
            "is_today": True
        })

    for date_key, count in records:
        formatted = date_key
        try:
            if "-" in date_key:
                dt = datetime.strptime(date_key, "%Y-%m-%d")
            else:
                dt = datetime.strptime(date_key, "%Y%m%d")
            formatted = dt.strftime("%d-%m-%Y")
        except Exception:
            pass
        items.append({
            "date_key": date_key,
            "date_formatted": formatted,
            "count": count,
            "is_today": (date_key == today_key)
        })

    return APIResponse(
        status="success",
        message=f"Retrieved {len(items)} visitor operational dates.",
        data=items
    )


    return APIResponse(
        status="success",
        message=f"Retrieved {len(items)} visitor operational dates.",
        data=items
    )


@router.get("/export/csv")
def export_visitors_csv(
    date_key: Optional[str] = Query(None, description="YYYYMMDD or 'all'"),
    status: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Streams a CSV export of visitor profiles."""
    query = db.query(VisitorModel)
    if date_key and date_key.lower() != "all":
        query = query.filter(VisitorModel.date_key == date_key)
    elif not date_key:
        query = query.filter(VisitorModel.date_key == get_operational_date_key())

    if status:
        query = query.filter(VisitorModel.status == status)
    if camera_id:
        query = query.filter((VisitorModel.first_camera_id == camera_id) | (VisitorModel.last_camera_id == camera_id))

    visitors = query.order_by(VisitorModel.last_seen_at.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "ID", "Visitor Code", "Date Key", "First Seen", "Last Seen",
        "First Camera", "Last Camera", "Sightings Count", "Status", "Promoted Person ID"
    ])

    for v in visitors:
        writer.writerow([
            v.id,
            v.visitor_code,
            v.date_key,
            v.first_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.first_seen_at else "",
            v.last_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.last_seen_at else "",
            v.first_camera_id or "default",
            v.last_camera_id or "default",
            v.sighting_count,
            v.status,
            v.promoted_person_id or ""
        ])

    buffer.seek(0)
    filename = f"visitor_report_{(date_key or get_operational_date_key())}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/pdf")
def export_visitors_pdf(
    date_key: Optional[str] = Query(None, description="YYYYMMDD or 'all'"),
    status: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Generates a summary PDF report of visitors using ReportLab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    query = db.query(VisitorModel)
    if date_key and date_key.lower() != "all":
        query = query.filter(VisitorModel.date_key == date_key)
    elif not date_key:
        key_str = get_operational_date_key()
        query = query.filter(VisitorModel.date_key == key_str)
        date_key = key_str
    else:
        date_key = "All Dates"

    if status:
        query = query.filter(VisitorModel.status == status)
    if camera_id:
        query = query.filter((VisitorModel.first_camera_id == camera_id) | (VisitorModel.last_camera_id == camera_id))

    visitors = query.order_by(VisitorModel.last_seen_at.desc()).all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleX", parent=styles["Title"], textColor=colors.HexColor("#0f172a"))
    elements = []

    elements.append(Paragraph("AI.Vision — Visitor Analytics Report", title_style))
    elements.append(Paragraph(
        f"Operational Date: {date_key}" + (f" &nbsp;|&nbsp; Camera: {camera_id}" if camera_id else ""),
        styles["Normal"]
    ))
    elements.append(Spacer(1, 8 * mm))

    active_cnt = sum(1 for v in visitors if v.status == 'active')
    promoted_cnt = sum(1 for v in visitors if v.status == 'promoted')
    total_sightings = sum(v.sighting_count for v in visitors)

    summary_data = [
        ["Metric", "Value"],
        ["Total Visitors", str(len(visitors))],
        ["Active Unregistered Visitors", str(active_cnt)],
        ["Promoted Visitors", str(promoted_cnt)],
        ["Total Camera Sightings", str(total_sightings)],
    ]
    summary_table = Table(summary_data, colWidths=[80 * mm, 60 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 8 * mm))

    elements.append(Paragraph(f"Visitor Records ({len(visitors)} shown)", styles["Heading3"]))
    event_rows = [["Visitor Code", "First Seen", "Last Seen", "Sightings", "Status"]]
    for v in visitors[:100]:
        event_rows.append([
            v.visitor_code,
            v.first_seen_at.strftime("%H:%M:%S") if v.first_seen_at else "",
            v.last_seen_at.strftime("%H:%M:%S") if v.last_seen_at else "",
            str(v.sighting_count),
            v.status.capitalize(),
        ])

    event_table = Table(event_rows, colWidths=[50 * mm, 30 * mm, 30 * mm, 25 * mm, 25 * mm], repeatRows=1)
    event_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elements.append(event_table)

    doc.build(elements)
    buffer.seek(0)

    filename = f"visitor_report_{date_key}.pdf"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def build_visitor_date_query(db: Session, date_key: Optional[str] = None):
    """
    Builds a query for VisitorModel matching visitors active on target date_key
    (including created on date_key, visited on date_key, or sighted on date_key).
    Supports both YYYY-MM-DD and YYYYMMDD formats.
    """
    if not date_key or date_key.lower() == "all":
        return db.query(VisitorModel)

    clean_key = date_key.strip()
    if "-" in clean_key:
        key_dash = clean_key
        key_nodash = clean_key.replace("-", "")
    else:
        key_nodash = clean_key
        key_dash = f"{clean_key[:4]}-{clean_key[4:6]}-{clean_key[6:8]}" if len(clean_key) == 8 and clean_key.isdigit() else clean_key

    from app.visitors.models import VisitorVisitModel

    visit_subq = db.query(VisitorVisitModel.visitor_id).filter(
        VisitorVisitModel.date_key.in_([key_dash, key_nodash])
    ).scalar_subquery()

    sighting_subq = db.query(VisitorSightingModel.visitor_id).filter(
        (func.strftime("%Y-%m-%d", VisitorSightingModel.entered_at) == key_dash) |
        (func.strftime("%Y%m%d", VisitorSightingModel.entered_at) == key_nodash)
    ).scalar_subquery()


    return db.query(VisitorModel).filter(
        (VisitorModel.date_key.in_([key_dash, key_nodash])) |
        (VisitorModel.created_date.in_([key_dash, key_nodash])) |
        (VisitorModel.id.in_(visit_subq)) |
        (VisitorModel.id.in_(sighting_subq))
    )


@router.get("", response_model=APIResponse)
def get_visitors(
    date_key: Optional[str] = Query(default=None, description="Operational date key (YYYY-MM-DD or 'all')"),
    camera_id: Optional[str] = Query(default=None, description="Filter by camera ID"),
    status: Optional[str] = Query(default=None, description="active, inactive, promoted"),
    search: Optional[str] = Query(default=None, description="Filter by visitor code"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Retrieves paginated visitor profiles active on target date, camera, status, or visitor code."""
    if date_key and date_key.lower() == "all":
        query = db.query(VisitorModel)
    elif date_key and date_key.strip():
        query = build_visitor_date_query(db, date_key.strip())
    else:
        date_key = get_operational_date_key()
        query = build_visitor_date_query(db, date_key)

    if camera_id and isinstance(camera_id, str):
        query = query.filter((VisitorModel.first_camera_id == camera_id) | (VisitorModel.last_camera_id == camera_id))

    if status and isinstance(status, str):
        query = query.filter(VisitorModel.status == status)

    if search and isinstance(search, str) and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(VisitorModel.visitor_code.ilike(s))

    if not isinstance(page, int):
        page = 1
    if not isinstance(page_size, int):
        page_size = 50

    total = query.count()
    visitors = query.order_by(VisitorModel.last_seen_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for v in visitors:
        items.append({
            "id": v.id,
            "visitor_code": v.visitor_code,
            "date_key": v.date_key,
            "created_date": v.created_date or v.date_key,
            "first_seen_at": v.first_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.first_seen_at else "",
            "last_seen_at": v.last_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.last_seen_at else "",
            "first_camera_id": v.first_camera_id,
            "last_camera_id": v.last_camera_id,
            "sighting_count": v.sighting_count,
            "status": v.status,
            "promoted_person_id": v.promoted_person_id,
            "primary_snapshot_url": resolve_visitor_primary_snapshot_url(v, db)
        })

    return APIResponse(
        status="success",
        message=f"Retrieved {len(items)} visitors (Total: {total}).",
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "date_key": date_key,
            "visitors": items
        }
    )


@router.get("/stats", response_model=APIResponse)
def get_visitor_stats(
    date_key: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    """Returns dashboard summary stats for visitor tracking."""
    if date_key and date_key.lower() == 'all':
        total_visitors = db.query(VisitorModel).count()
        active_count = db.query(VisitorModel).filter(VisitorModel.status == 'active').count()
        promoted_count = db.query(VisitorModel).filter(VisitorModel.status == 'promoted').count()
        total_sightings = db.query(func.count(VisitorSightingModel.id)).scalar() or 0
        date_key_val = "all"
    else:
        if not isinstance(date_key, str) or not date_key:
            date_key_val = get_operational_date_key()
        else:
            date_key_val = date_key

        date_query = build_visitor_date_query(db, date_key_val)
        total_visitors = date_query.count()
        active_count = date_query.filter(VisitorModel.status == 'active').count()
        promoted_count = date_query.filter(VisitorModel.status == 'promoted').count()

        matched_v_ids = [v.id for v in date_query.all()]
        if matched_v_ids:
            total_sightings = db.query(func.count(VisitorSightingModel.id)).filter(VisitorSightingModel.visitor_id.in_(matched_v_ids)).scalar() or 0
        else:
            total_sightings = 0

    from app.services.camera.camera_registry import camera_registry
    with camera_registry.lock:
        online_cameras = len([w for w in camera_registry.workers.values() if w.is_active()])

    return APIResponse(
        status="success",
        message="Visitor tracking statistics retrieved.",
        data={
            "date_key": date_key_val,
            "total_visitors_today": total_visitors,
            "active_visitors": active_count,
            "promoted_visitors": promoted_count,
            "online_cameras": max(1, online_cameras),
            "total_sightings": total_sightings
        }
    )




@router.get("/{visitor_id}", response_model=APIResponse)
def get_visitor_detail(
    visitor_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """Retrieves detailed visitor profile metadata."""
    v = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"Visitor ID {visitor_id} not found.")

    samples_count = db.query(VisitorFaceSampleModel).filter(VisitorFaceSampleModel.visitor_id == visitor_id).count()

    return APIResponse(
        status="success",
        message=f"Retrieved details for {v.visitor_code}.",
        data={
            "id": v.id,
            "visitor_code": v.visitor_code,
            "date_key": v.date_key,
            "first_seen_at": v.first_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.first_seen_at else "",
            "last_seen_at": v.last_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.last_seen_at else "",
            "first_camera_id": v.first_camera_id,
            "last_camera_id": v.last_camera_id,
            "sighting_count": v.sighting_count,
            "samples_count": samples_count,
            "status": v.status,
            "promoted_person_id": v.promoted_person_id,
            "primary_snapshot_url": resolve_visitor_primary_snapshot_url(v, db)
        }
    )


@router.get("/{visitor_id}/timeline", response_model=APIResponse)
def get_visitor_timeline(
    visitor_id: int = Path(...),
    date_key: Optional[str] = Query(default=None, description="YYYY-MM-DD or 'all'"),
    db: Session = Depends(get_db)
):
    """Retrieves chronological journey timeline sightings for a visitor."""
    v = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"Visitor ID {visitor_id} not found.")

    if hasattr(date_key, "default"):
        date_key = date_key.default

    query = db.query(VisitorSightingModel).filter(
        VisitorSightingModel.visitor_id == visitor_id
    )

    if isinstance(date_key, str) and date_key and date_key.lower() != "all":
        clean_key = date_key.strip()
        if "-" in clean_key:
            key_dash = clean_key
            key_nodash = clean_key.replace("-", "")
        else:
            key_nodash = clean_key
            key_dash = f"{clean_key[:4]}-{clean_key[4:6]}-{clean_key[6:8]}" if len(clean_key) == 8 and clean_key.isdigit() else clean_key

        query = query.filter(
            (func.strftime("%Y-%m-%d", VisitorSightingModel.entered_at) == key_dash) |
            (func.strftime("%Y%m%d", VisitorSightingModel.entered_at) == key_nodash)
        )

    sightings = query.order_by(VisitorSightingModel.entered_at.asc()).all()

    from app.services.camera.camera_registry import camera_registry
    cams_by_id = {c.camera_id: c.name for c in camera_registry.load_cameras_from_db()}

    events = []
    primary_fallback = resolve_visitor_primary_snapshot_url(v, db)

    for s in sightings:
        entered_str = s.entered_at.strftime("%d-%m-%Y %H:%M:%S") if s.entered_at else ""
        last_str = s.last_seen_at.strftime("%d-%m-%Y %H:%M:%S") if s.last_seen_at else ""

        duration_sec = 0
        if s.entered_at and s.last_seen_at:
            duration_sec = max(1, int((s.last_seen_at - s.entered_at).total_seconds()))

        dur_fmt = f"{duration_sec}s"
        if duration_sec >= 60:
            dur_fmt = f"{duration_sec // 60}m {duration_sec % 60}s"

        cam_name = cams_by_id.get(s.camera_id, f"Camera {s.camera_id}")

        meta = {}
        if s.metadata_json:
            try:
                meta = json.loads(s.metadata_json)
            except Exception:
                pass

        snap_url = format_snapshot_url(s.snapshot_path) or primary_fallback

        events.append({
            "id": s.id,
            "camera_id": s.camera_id,
            "camera_name": cam_name,
            "track_id": s.track_id,
            "entered_at": entered_str,
            "last_seen_at": last_str,
            "duration_formatted": dur_fmt,
            "best_similarity": s.best_similarity,
            "second_best_similarity": s.second_best_similarity,
            "match_margin": s.match_margin,
            "identity_confidence": s.identity_confidence,
            "snapshot_url": snap_url,
            "metadata": meta
        })

    return APIResponse(
        status="success",
        message=f"Retrieved {len(events)} timeline events for {v.visitor_code}.",
        data={
            "visitor_code": v.visitor_code,
            "date_key": v.date_key,
            "first_seen_at": v.first_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.first_seen_at else "",
            "last_seen_at": v.last_seen_at.strftime("%d-%m-%Y %H:%M:%S") if v.last_seen_at else "",
            "status": v.status,
            "primary_snapshot_url": primary_fallback,
            "sightings": events
        }
    )


@router.get("/{visitor_id}/snapshots", response_model=APIResponse)
def get_visitor_snapshots(
    visitor_id: int = Path(...),
    date_key: Optional[str] = Query(default=None, description="YYYY-MM-DD or 'all'"),
    db: Session = Depends(get_db)
):
    """Retrieves all stored face crop samples collected for a visitor."""
    v = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"Visitor ID {visitor_id} not found.")

    if hasattr(date_key, "default"):
        date_key = date_key.default

    query = db.query(VisitorFaceSampleModel).filter(
        VisitorFaceSampleModel.visitor_id == visitor_id
    )

    if isinstance(date_key, str) and date_key and date_key.lower() != "all":
        clean_key = date_key.strip()
        if "-" in clean_key:
            key_dash = clean_key
            key_nodash = clean_key.replace("-", "")
        else:
            key_nodash = clean_key
            key_dash = f"{clean_key[:4]}-{clean_key[4:6]}-{clean_key[6:8]}" if len(clean_key) == 8 and clean_key.isdigit() else clean_key

        query = query.filter(
            (func.strftime("%Y-%m-%d", VisitorFaceSampleModel.timestamp) == key_dash) |
            (func.strftime("%Y%m%d", VisitorFaceSampleModel.timestamp) == key_nodash)
        )

    samples = query.order_by(VisitorFaceSampleModel.quality_score.desc()).all()

    items = []
    for s in samples:
        items.append({
            "id": s.id,
            "camera_id": s.camera_id,
            "timestamp": s.timestamp.strftime("%d-%m-%Y %H:%M:%S") if s.timestamp else "",
            "quality_score": s.quality_score,
            "yaw": s.yaw,
            "pitch": s.pitch,
            "blur_score": s.blur_score,
            "snapshot_url": format_snapshot_url(s.snapshot_path)
        })

    return APIResponse(
        status="success",
        message=f"Retrieved {len(items)} face sample snapshots.",
        data=items
    )



@router.post("/{visitor_id}/promote", response_model=APIResponse)
def promote_visitor(
    visitor_id: int = Path(...),
    req: VisitorPromoteRequest = ...,
    db: Session = Depends(get_db)
):
    """Promotes an unregistered visitor into a permanent registered person profile."""
    v = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"Visitor ID {visitor_id} not found.")

    try:
        person = visitor_repository.promote_visitor_to_person(
            db=db,
            visitor_id=visitor_id,
            first_name=req.first_name,
            last_name=req.last_name,
            department=req.department,
            role=req.role,
            phone=req.phone,
            email=req.email,
            notes=req.notes
        )

        return APIResponse(
            status="success",
            message=f"Successfully promoted visitor {v.visitor_code} to registered Person '{person.name}'.",
            data={
                "visitor_code": v.visitor_code,
                "person_id": person.person_id,
                "name": person.name,
                "department": person.department,
                "role": person.role,
                "status": "promoted"
            }
        )
    except Exception as e:
        logger.error(f"Failed to promote visitor {visitor_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{visitor_id}/export", response_model=APIResponse)
def export_visitor_journey(
    visitor_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """Exports comprehensive JSON record of visitor profile and journey timeline."""
    v = db.query(VisitorModel).filter(VisitorModel.id == visitor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"Visitor ID {visitor_id} not found.")

    sightings = db.query(VisitorSightingModel).filter(VisitorSightingModel.visitor_id == visitor_id).order_by(VisitorSightingModel.entered_at.asc()).all()
    samples = db.query(VisitorFaceSampleModel).filter(VisitorFaceSampleModel.visitor_id == visitor_id).all()

    from app.services.camera.camera_registry import camera_registry
    cams_by_id = {c.camera_id: c.name for c in camera_registry.load_cameras_from_db()}

    export_data = {
        "visitor_code": v.visitor_code,
        "date_key": v.date_key,
        "first_seen_at": v.first_seen_at.isoformat() if v.first_seen_at else None,
        "last_seen_at": v.last_seen_at.isoformat() if v.last_seen_at else None,
        "first_camera": v.first_camera_id,
        "last_camera": v.last_camera_id,
        "total_sightings": v.sighting_count,
        "status": v.status,
        "promoted_person_id": v.promoted_person_id,
        "samples_collected": len(samples),
        "journey": [
            {
                "sighting_id": s.id,
                "camera_id": s.camera_id,
                "camera_name": cams_by_id.get(s.camera_id, s.camera_id),
                "entered_at": s.entered_at.isoformat() if s.entered_at else None,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "best_similarity": s.best_similarity,
                "second_best_similarity": s.second_best_similarity,
                "match_margin": s.match_margin,
                "identity_confidence": s.identity_confidence
            }
            for s in sightings
        ]
    }

    return APIResponse(
        status="success",
        message=f"Exported journey for visitor {v.visitor_code}",
        data=export_data
    )


@router.delete("/{visitor_id}", response_model=APIResponse)
def delete_visitor(
    visitor_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """Deletes a visitor profile, all associated snapshot files, sightings, and gallery embeddings."""
    success = visitor_repository.delete_visitor(db, visitor_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Visitor ID {visitor_id} not found.")

    return APIResponse(
        status="success",
        message=f"Visitor ID {visitor_id} successfully deleted.",
        data={"visitor_id": visitor_id}
    )


@router.delete("/purge_all", response_model=APIResponse)
@router.delete("", response_model=APIResponse)
def purge_all_visitors(
    db: Session = Depends(get_db)
):
    """Purges all visitor records, face samples, sightings, image files, and resets visitor sequence counters."""
    res = visitor_repository.purge_all_visitors(db)
    return APIResponse(
        status="success",
        message="All previous visitor profiles, snapshots, and sightings deleted successfully.",
        data=res
    )


@router.get("/maintenance/duplicates", response_model=APIResponse)
def get_duplicate_analysis(db: Session = Depends(get_db)):
    """Runs offline diagnostic analysis for duplicate visitor clusters and registered matches."""
    from app.visitors.maintenance import visitor_duplicate_analyzer
    report = visitor_duplicate_analyzer.analyze_duplicates(db)
    return APIResponse(
        status="success",
        message=f"Duplicate analysis complete. Found {report.get('duplicate_clusters_count', 0)} clusters.",
        data=report
    )


