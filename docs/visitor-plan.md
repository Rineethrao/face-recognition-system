# Walkthrough — Visitor Tracking & Re-Identification (Re-ID) Subsystem

Implemented an enterprise-grade Visitor Tracking & Re-Identification Subsystem inside `face-recognition-system-new`.

---

## Key Achievements

### 1. Hierarchy & Separation Enforced
- **Track ID**: `ByteTrack: CAM01_track_47` (camera-local tracking).
- **Global Visitor ID**: `VISITOR-YYYYMMDD-XXX` (temporary unregistered daily identity across cameras).
- **Permanent Registered Identity**: `John | Staff` (registered person profile).

### 2. Isolated Visitor Backend Module (`backend/app/visitors/`)
- [`models.py`](file:///c:/face-recognition-system-new/backend/app/visitors/models.py): SQLAlchemy models `VisitorModel`, `VisitorFaceSampleModel` (3–10 embeddings per visitor), and `VisitorSightingModel` (continuous camera session logs).
- [`face_quality.py`](file:///c:/face-recognition-system-new/backend/app/visitors/face_quality.py): Multi-tier face quality evaluator enforcing size, blur/sharpness, yaw, pitch, brightness, and exposure gates.
- [`visitor_repository.py`](file:///c:/face-recognition-system-new/backend/app/visitors/visitor_repository.py): DB operations for visitor CRUD, face sample storage, continuous sighting session updates, and transactional registration promotion.
- [`visitor_gallery.py`](file:///c:/face-recognition-system-new/backend/app/visitors/visitor_gallery.py): In-memory multi-sample vector gallery with top-K match aggregation and candidate score calculations.
- [`identity_resolver.py`](file:///c:/face-recognition-system-new/backend/app/visitors/identity_resolver.py): Candidate margin evaluation (`Best_Score - Second_Best_Score >= CANDIDATE_MATCH_MARGIN`) and confidence bands (`existing_visitor`, `uncertain`, `no_match`).
- [`sighting_manager.py`](file:///c:/face-recognition-system-new/backend/app/visitors/sighting_manager.py): Session-based sighting manager capturing entrance/exit timestamps, durations, best similarity scores, margins, and snapshots.
- [`visitor_manager.py`](file:///c:/face-recognition-system-new/backend/app/visitors/visitor_manager.py): High-level orchestrator enforcing sticky track identity caching, track observation accumulation (requiring 3–5 usable samples before new visitor creation), and gallery updates.
- [`api/visitors.py`](file:///c:/face-recognition-system-new/backend/app/api/visitors.py): REST API router providing endpoints:
  - `GET /api/visitors` (paginated & filterable list)
  - `GET /api/visitors/stats` (visitors today, active, online cameras, sightings)
  - `GET /api/visitors/{id}` (visitor details)
  - `GET /api/visitors/{id}/timeline` (sighting history with entrance/exit times & margins)
  - `GET /api/visitors/{id}/snapshots` (multi-angle face sample crops)
  - `POST /api/visitors/{id}/promote` (transactional promotion to registered person)
  - `GET /api/visitors/{id}/export` (journey report JSON export)

### 3. Configurable Identity Thresholds (`backend/app/config.py`)
- Configured settings:
  - `VISITOR_MATCH_HIGH = 0.70`
  - `VISITOR_MATCH_LOW = 0.50`
  - `VISITOR_REGISTERED_MATCH_THRESHOLD = 0.60`
  - `VISITOR_CANDIDATE_MATCH_MARGIN = 0.04`
  - `VISITOR_MIN_OBSERVATIONS = 3`
  - `VISITOR_MIN_OBSERVATION_QUALITY = 0.65`
  - `VISITOR_MAX_SAMPLES = 10`
  - `VISITOR_OPERATIONAL_DAY_START_HOUR = 0`

### 4. Recognition Pipeline Integration
- Priority 1: Registered recognition via FAISS in `recognition_service.py` & `pipeline_orchestrator.py`.
- Priority 2: Unrecognized tracks routed to `VisitorManager`.
- Overlay labels updated:
  - Registered: `ID:47 | John (85%)` (Green)
  - Resolved Visitor: `ID:47 | VISITOR-20260806-001` (Gold/Cyan)
  - Identifying: `ID:47 | Identifying...` (Amber/Orange)

### 5. High-End Visitor Tracking Dashboard UI
- [`VisitorTracking.tsx`](file:///c:/face-recognition-system-new/frontend_src/src/pages/VisitorTracking.tsx): Split-view layout featuring summary stats, search & camera filters, unregistered visitor list, detailed profile card, and interactive journey timeline.
- [`VisitorPromotionModal.tsx`](file:///c:/face-recognition-system-new/frontend_src/src/components/visitors/VisitorPromotionModal.tsx): Modal dialog for promoting an unregistered visitor into a permanent system person record while automatically transferring their best face samples.
- Integrated `/visitors` route into [`App.tsx`](file:///c:/face-recognition-system-new/frontend_src/src/App.tsx) and navigation link into [`Sidebar.tsx`](file:///c:/face-recognition-system-new/frontend_src/src/components/Sidebar.tsx).

---

## Verification Results

### Frontend Compilation
- Executed `npm run build` inside `frontend_src`.
- **Result**: `✓ 2273 modules transformed. Built in 20.61s` with **0 errors**.

### Backend Verification
- Executed automated backend test script validating ORM schemas, DB table creation, config settings, VisitorManager orchestrator, and API router.
- **Result**: All visitor backend tests passed cleanly (`Exit code: 0`).
