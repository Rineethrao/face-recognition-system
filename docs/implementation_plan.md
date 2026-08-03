# Enterprise AI CCTV Face Recognition — Architecture Document

## Executive Summary

This document defines the enterprise architecture to scale your existing AI Face Recognition backend from **1 camera** to **400+ simultaneous RTSP cameras** without replacing any AI models (SCRFD, ByteTrack, ArcFace, FAISS).

Your current pipeline is preserved as the **atomic processing unit**. The enterprise layers wrap around it to provide camera management, candidate aggregation, quality-gated registration, multi-camera recognition merging, and progressive learning.

---

## 1. Current Architecture — Gap Analysis

### What Works Today (Preserve)

| Component | File | Status |
|---|---|---|
| SCRFD Face Detection | [detector.py](file:///c:/face_recognition/backend/app/core/detector.py) | ✅ Keep |
| ByteTrack Tracking | [tracker.py](file:///c:/face_recognition/backend/app/core/tracker.py) | ✅ Keep |
| ArcFace Embeddings | [recognizer.py](file:///c:/face_recognition/backend/app/core/recognizer.py) | ✅ Keep |
| FAISS Vector Search | [faiss_index.py](file:///c:/face_recognition/backend/app/core/faiss_index.py) | ✅ Keep |
| Face Alignment | [utils.py](file:///c:/face_recognition/backend/app/core/utils.py) | ✅ Keep |
| Quality Evaluation | [utils.py](file:///c:/face_recognition/backend/app/core/utils.py#L47-L87) | ✅ Keep |
| Plugin System | [projects/](file:///c:/face_recognition/backend/app/projects) | ✅ Keep |

### What Must Be Built (Enterprise Gaps)

| Gap | Current State | Enterprise Target |
|---|---|---|
| **Camera Management** | Single `CameraStreamManager` global singleton | Per-camera independent lifecycle with health monitoring |
| **Track Scope** | Global track IDs across one camera | Per-camera track namespacing (`cam_05:track_42`) |
| **Face Buffer** | No buffer — single frame used | Multi-frame temporal buffer with quality scoring |
| **Candidate System** | None — registration is immediate | Cross-camera candidate aggregation before registration |
| **Registration Queue** | Direct popup → register | Operator review queue with quality metrics |
| **Recognition** | Single FAISS hit → consensus | Top-K → per-person gallery verification → decision |
| **Progressive Learning** | Basic `auto_improve_profile` | Formal versioned gallery management with archival |
| **Recognition History** | Minimal `RecognitionLogModel` | Full audit trail: camera, track, snapshot, embedding version |
| **Multi-Camera Merge** | Not supported | Person timeline merging across all cameras |
| **Database** | 3 tables (persons, embeddings, recognition_logs) | 14 normalized tables |
| **Scalability** | Single-threaded processing loop | Thread-per-camera + GPU worker pool + message queue ready |

---

## 2. Enterprise Module Architecture

### Module Dependency Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        API Layer (FastAPI)                        │
│  camera/ | candidate/ | registration/ | recognition/ | health/   │
└─────────────────────────────┬────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                      Service Layer                                │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐       │
│  │ Camera      │  │ Pipeline     │  │ Candidate          │       │
│  │ Manager     │──│ Orchestrator │──│ Manager            │       │
│  │ Service     │  │ (per camera) │  │ (cross-camera)     │       │
│  └─────────────┘  └──────┬───────┘  └────────┬───────────┘       │
│                          │                    │                    │
│  ┌─────────────┐  ┌──────▼───────┐  ┌────────▼───────────┐       │
│  │ Track       │  │ Face Buffer  │  │ Registration       │       │
│  │ Manager     │  │ + Quality    │  │ Queue              │       │
│  │ (per camera)│  │ Engine       │  │ + Engine           │       │
│  └─────────────┘  └──────┬───────┘  └────────────────────┘       │
│                          │                                        │
│  ┌─────────────┐  ┌──────▼───────┐  ┌────────────────────┐       │
│  │ Duplicate   │  │ Pose         │  │ Progressive        │       │
│  │ Removal     │  │ Diversity    │  │ Learning           │       │
│  │ Engine      │  │ Engine       │  │ Engine             │       │
│  └─────────────┘  └──────────────┘  └────────────────────┘       │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐       │
│  │ Recognition │  │ Recognition  │  │ Multi-Camera       │       │
│  │ Engine v2   │  │ History      │  │ Merge Service      │       │
│  │ (Top-K+     │  │ Service      │  │                    │       │
│  │  Gallery)   │  │              │  │                    │       │
│  └─────────────┘  └──────────────┘  └────────────────────┘       │
└──────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                        Core Layer (UNCHANGED)                     │
│  SCRFD │ ByteTrack │ ArcFace │ FAISS │ Alignment │ Quality       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Module Responsibilities

### Module 1: Camera Management Service

> **File**: `app/services/camera/camera_manager_service.py`

| Responsibility | Detail |
|---|---|
| Camera Registry | CRUD for camera configurations in `cameras` DB table |
| Stream Lifecycle | Start/stop/restart individual camera streams |
| Health Monitoring | Per-camera FPS, last frame time, error count, reconnect count |
| Auto-Reconnect | Exponential backoff reconnection on stream failure |
| FPS Throttling | Configurable processing FPS per camera (e.g., 5 FPS for 400 cameras) |
| Dynamic Enable/Disable | Hot enable/disable without server restart |

**Current**: One global `CameraStreamManager` in [stream.py](file:///c:/face_recognition/backend/app/core/stream.py)
**Enterprise**: `CameraRegistry` holds N `CameraStreamWorker` instances, each running in its own thread.

---

### Module 2: Pipeline Orchestrator (Per-Camera)

> **File**: `app/services/camera/pipeline_orchestrator.py`

Each camera gets its own independent pipeline orchestrator that wraps your existing processing loop:

```
CameraStreamWorker.read_frame()
    → SCRFD detect()           # EXISTING
    → ByteTrack update()       # EXISTING
    → TrackManager.update()    # NEW — per-camera track state
    → FaceBuffer.collect()     # NEW — temporal buffer
    → QualityEngine.score()    # NEW — extended scoring
    → RecognitionEngine.recognize()  # UPGRADED
    → CandidateManager.evaluate()    # NEW
    → AnnotationRenderer.draw()      # EXISTING overlay logic
```

---

### Module 3: Track Manager

> **File**: `app/services/tracking/track_manager.py`

| Field | Type | Description |
|---|---|---|
| `track_id` | str | Namespaced: `{camera_id}:{bytetrack_id}` |
| `camera_id` | str | Source camera |
| `start_time` | datetime | First detection |
| `last_seen` | datetime | Last frame update |
| `state` | enum | `TRACKING`, `RECOGNIZED`, `CANDIDATE`, `LOST` |
| `captured_faces` | list | All buffered face captures |
| `best_face` | FaceCapture | Highest quality capture |
| `recognition_state` | dict | Current consensus window state |
| `candidate_id` | str | Linked candidate (if any) |

**Stale Cleanup**: Tracks not seen for 30s are archived to DB and removed from memory.

---

### Module 4: Face Buffer + Quality Engine

> **File**: `app/services/quality/face_buffer.py`, `app/services/quality/quality_engine.py`

Each track maintains a **temporal face buffer** (configurable max: 30 frames, timeout: 10s).

#### Face Capture Object

| Field | Type | Source |
|---|---|---|
| `image` | np.ndarray | Aligned 112×112 crop |
| `embedding` | np.ndarray | 512D ArcFace vector |
| `blur_score` | float | Laplacian variance (existing `calculate_blur`) |
| `brightness` | float | Mean pixel intensity |
| `sharpness` | float | Tenengrad gradient magnitude |
| `pose_yaw` | float | Estimated from landmark symmetry (existing) |
| `pose_pitch` | float | Estimated from nose-to-eye vertical ratio |
| `face_size` | int | Bounding box area in pixels |
| `occlusion_score` | float | Face-to-bbox coverage ratio |
| `timestamp` | datetime | Capture time |
| `camera_id` | str | Source camera |
| `track_id` | str | Associated track |

#### Quality Engine Scoring

Extends existing [evaluate_face_quality](file:///c:/face_recognition/backend/app/core/utils.py#L47-L87):

```python
quality_score = (
    0.30 * normalize(blur_score, 0, 500) +      # Sharpness weight
    0.20 * normalize(face_size, 1000, 50000) +   # Resolution weight
    0.15 * (1.0 - abs(pose_yaw)) +               # Frontal preference
    0.15 * normalize(brightness, 40, 220) +       # Lighting weight
    0.10 * (1.0 - occlusion_score) +              # Visibility weight
    0.10 * normalize(sharpness, 0, 1000)          # Tenengrad weight
)
```

**Rejection thresholds** (configurable in `config.json`):
- `blur_score < 30` → Reject
- `face_size < 900px²` → Reject
- `abs(pose_yaw) > 0.6` → Reject
- `brightness < 30 or > 240` → Reject
- `occlusion_score > 0.4` → Reject

---

### Module 5: Duplicate Removal Engine

> **File**: `app/services/quality/duplicate_engine.py`

Within a track's face buffer, many consecutive frames are near-identical.

**Strategy**:
1. Compute pairwise cosine similarity between all buffered embeddings.
2. If `similarity > 0.92`, keep only the one with the higher `quality_score`.
3. Run after every 5 new captures or on buffer flush.

**Output**: Deduplicated buffer with only distinct, high-quality captures.

---

### Module 6: Pose Diversity Engine

> **File**: `app/services/quality/pose_diversity_engine.py`

Instead of keeping 8 near-identical frontal shots:

**Pose Bins**:
| Bin | Yaw Range | Pitch Range |
|---|---|---|
| `FRONTAL` | -15° to +15° | -10° to +10° |
| `LEFT_30` | -45° to -15° | any |
| `RIGHT_30` | +15° to +45° | any |
| `LEFT_60` | -75° to -45° | any |
| `RIGHT_60` | +45° to +75° | any |
| `UP` | any | +10° to +30° |
| `DOWN` | any | -30° to -10° |

**Algorithm**:
1. Classify each capture into a pose bin.
2. Keep the best-quality capture per bin.
3. When selecting images for registration/gallery, prefer diversity across bins.

---

### Module 7: Candidate Manager ⭐ (Core Enterprise Module)

> **File**: `app/services/candidate/candidate_manager.py`

This is the bridge between raw tracks and registered persons.

#### Lifecycle

```
Track (Camera A)  ──┐
Track (Camera B)  ──┼──► Candidate #42 ──► Registration Queue ──► Person
Track (Camera F)  ──┘
```

#### Candidate Object

| Field | Type | Description |
|---|---|---|
| `candidate_id` | str | UUID |
| `status` | enum | `COLLECTING`, `READY`, `IN_REVIEW`, `REGISTERED`, `REJECTED` |
| `seen_cameras` | list[str] | All cameras that contributed |
| `seen_times` | list[datetime] | Detection timestamps |
| `face_captures` | list[FaceCapture] | Best quality captures (max 20) |
| `best_images` | list[FaceCapture] | Top 6-8 curated by quality + diversity |
| `embeddings` | list[np.ndarray] | Extracted embeddings |
| `avg_quality` | float | Mean quality score |
| `first_seen` | datetime | Earliest detection |
| `last_seen` | datetime | Latest detection |
| `created_at` | datetime | Candidate creation time |

#### Cross-Camera Matching

When a new unknown track appears on Camera B:
1. Extract embedding from best face.
2. Compare against all **active candidates** using cosine similarity.
3. If `similarity > 0.75` → merge into existing candidate.
4. If no match → create new candidate.

This allows the system to aggregate face data across cameras for the same unknown person **before** any registration happens.

---

### Module 8: Registration Queue

> **File**: `app/services/registration/registration_queue.py`

Candidates meeting quality thresholds automatically enter the review queue.

**Auto-queue criteria**:
- `total_captures >= 10`
- `best_images >= 4`
- `avg_quality >= 0.65`
- `seen_cameras >= 1`

**Queue Item Display** (for operator):
```
┌─────────────────────────────────────┐
│ Candidate #42                       │
│ Quality: ████████░░ 82%             │
│ Captures: 18 total → 6 best        │
│ Cameras: cam_01, cam_03, cam_05     │
│ First Seen: 09:15 AM                │
│ Last Seen: 09:23 AM                 │
│                                     │
│ [Best Face Grid: 6 thumbnails]      │
│                                     │
│ [Register]  [Reject]  [Skip]        │
└─────────────────────────────────────┘
```

---

### Module 9: Registration Engine

> **File**: `app/services/registration/registration_engine.py`

Replaces the simple "save 5 samples" approach with a versioned gallery system.

**Registration stores**:
| Field | Description |
|---|---|
| Person metadata | ID, name, department, role |
| Gallery images | 6-8 curated face crops (versioned) |
| Embeddings | One per gallery image (versioned) |
| Registration camera | Which camera triggered |
| Registration quality | Quality metrics at registration time |
| Gallery version | Auto-incremented on progressive learning updates |
| Source candidate | Original candidate ID |

---

### Module 10: Recognition Engine v2

> **File**: `app/services/recognition/recognition_engine_v2.py`

#### Current Flow (Keep as Fallback)
```
Embedding → FAISS Top-1 → Threshold → Match
```

#### Enterprise Flow
```
Embedding
    │
    ▼
FAISS Top-K (k=10)
    │
    ▼
Group results by person_id
    │
    ▼
For each candidate person:
    Compare incoming embedding against ALL gallery embeddings
    Use MAX similarity across gallery
    │
    ▼
Rank persons by max similarity
    │
    ▼
Apply threshold (0.70)
    │
    ▼
If best_person similarity > threshold → MATCH
If best_person similarity > 0.55 but < 0.70 → UNCERTAIN (need more frames)
If no person above 0.55 → UNKNOWN
```

This eliminates false positives caused by a single weak embedding in the gallery matching by coincidence.

---

### Module 11: Progressive Learning Engine

> **File**: `app/services/learning/progressive_learning.py`

After registration, when a recognized person appears on camera with `match_score > 0.85`:

1. **Quality Gate**: New capture must pass quality engine.
2. **Duplicate Gate**: Must not be a near-duplicate of existing gallery (`similarity < 0.92`).
3. **Diversity Gate**: Must fill an unoccupied pose bin or replace a lower-quality image in an existing bin.
4. **Version Gate**: Gallery update increments version counter.
5. **Archive Gate**: Replaced images are archived, not deleted.

**Gallery Size**: 8 active images + unlimited archived images.

---

### Module 12: Recognition History Service

> **File**: `app/services/history/recognition_history_service.py`

Every recognition event stores:

| Field | Description |
|---|---|
| `camera_id` | Which camera detected |
| `track_id` | Namespaced track |
| `person_id` | Matched person |
| `similarity` | Match score |
| `embedding_version` | Gallery version used |
| `quality_score` | Quality of the detected face |
| `face_snapshot_path` | Saved JPEG of the detected face |
| `recognized_at` | Timestamp |

---

### Module 13: Multi-Camera Merge Service

> **File**: `app/services/recognition/multi_camera_merge.py`

When the same person is recognized on Camera A at 09:15 and Camera C at 09:17:

1. Both events are logged independently.
2. The merge service creates a **Person Timeline** aggregating all events.
3. The person profile shows:
   - **Current cameras**: Which cameras currently see this person
   - **Last seen**: Most recent detection across all cameras
   - **Camera history**: Timeline of all camera appearances

---

## 4. Database Schema (14 Tables)

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   cameras    │     │     tracks       │     │  face_buffers    │
│──────────────│     │──────────────────│     │──────────────────│
│ id (PK)      │◄────│ camera_id (FK)   │     │ track_id (FK)    │
│ camera_id    │     │ track_id (PK)    │────►│ id (PK)          │
│ name         │     │ state            │     │ embedding (BLOB) │
│ source       │     │ start_time       │     │ quality_score    │
│ location     │     │ last_seen        │     │ blur_score       │
│ enabled      │     │ candidate_id(FK) │     │ pose_bin         │
│ rotation     │     │ recognition_state│     │ image_path       │
│ fps_limit    │     └──────────────────┘     │ timestamp        │
│ status       │                              └──────────────────┘
│ last_heartbeat│
│ error_count  │     ┌──────────────────┐     ┌──────────────────┐
│ created_at   │     │   candidates     │     │ candidate_images │
└──────────────┘     │──────────────────│     │──────────────────│
                     │ id (PK)          │◄────│ candidate_id(FK) │
                     │ candidate_id     │     │ id (PK)          │
                     │ status           │     │ image_path       │
                     │ avg_quality      │     │ embedding (BLOB) │
                     │ seen_cameras     │     │ quality_score    │
                     │ first_seen       │     │ pose_bin         │
                     │ last_seen        │     │ camera_id        │
                     │ created_at       │     │ created_at       │
                     └──────────────────┘     └──────────────────┘

┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    persons       │     │  person_images   │     │   embeddings     │
│──────────────────│     │──────────────────│     │──────────────────│
│ id (PK)          │◄────│ person_id (FK)   │     │ id (PK)          │
│ person_id        │     │ id (PK)          │     │ person_id (FK)   │
│ name             │     │ image_path       │     │ faiss_id         │
│ department       │     │ quality_score    │     │ image_id (FK)    │
│ role             │     │ pose_bin         │     │ gallery_version  │
│ gallery_version  │     │ gallery_version  │     │ is_active        │
│ source_candidate │     │ is_active        │     │ created_at       │
│ registered_at    │     │ camera_id        │     │ archived_at      │
│ updated_at       │     │ created_at       │     └──────────────────┘
└──────────────────┘     │ archived_at      │
                         └──────────────────┘

┌──────────────────────┐     ┌──────────────────┐
│  recognition_history │     │   audit_logs     │
│──────────────────────│     │──────────────────│
│ id (PK)              │     │ id (PK)          │
│ person_id (FK)       │     │ action           │
│ camera_id (FK)       │     │ entity_type      │
│ track_id             │     │ entity_id        │
│ similarity           │     │ details (JSON)   │
│ embedding_version    │     │ performed_by     │
│ quality_score        │     │ timestamp        │
│ face_snapshot_path   │     └──────────────────┘
│ recognized_at        │
│ created_at           │
└──────────────────────┘
```

> [!NOTE]
> The existing 3 tables (`persons`, `embeddings`, `recognition_logs`) will be **migrated** to the new schema using Alembic migrations. No data loss.

---

## 5. Folder Structure

Extends your existing structure without breaking any imports:

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                          # MODIFIED — register new routers
│   ├── config.py                        # MODIFIED — new config sections
│   │
│   ├── core/                            # UNCHANGED
│   │   ├── detector.py                  # SCRFD — untouched
│   │   ├── tracker.py                   # ByteTrack — untouched
│   │   ├── recognizer.py               # ArcFace — untouched
│   │   ├── faiss_index.py              # FAISS — untouched
│   │   ├── stream.py                   # CameraStreamManager — kept as base class
│   │   ├── utils.py                    # Alignment + quality — untouched
│   │   └── database.py                 # SessionLocal — untouched
│   │
│   ├── models/
│   │   ├── db_models.py                # EXTENDED — new tables added
│   │   └── schemas.py                  # EXTENDED — new Pydantic models
│   │
│   ├── api/                            # EXTENDED — new route modules
│   │   ├── camera.py                   # EXISTING — extended
│   │   ├── registration.py            # EXISTING — extended
│   │   ├── recognition.py             # EXISTING — extended
│   │   ├── health.py                  # EXISTING — extended
│   │   ├── websocket.py               # EXISTING — untouched
│   │   ├── candidate.py               # NEW
│   │   ├── person_gallery.py          # NEW
│   │   └── history.py                 # NEW
│   │
│   ├── services/
│   │   ├── detection_service.py        # EXISTING — refactored to use orchestrator
│   │   ├── recognition_service.py      # EXISTING — kept as fallback
│   │   ├── registration_service.py     # EXISTING — kept for live registration
│   │   ├── camera_service.py           # EXISTING — extended
│   │   │
│   │   ├── camera/                     # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   ├── camera_registry.py      # Camera CRUD + health
│   │   │   ├── camera_worker.py        # Per-camera thread worker
│   │   │   └── pipeline_orchestrator.py # Per-camera pipeline
│   │   │
│   │   ├── tracking/                   # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   └── track_manager.py        # Per-camera track state
│   │   │
│   │   ├── quality/                    # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   ├── face_buffer.py          # Temporal face buffer
│   │   │   ├── quality_engine.py       # Extended quality scoring
│   │   │   ├── duplicate_engine.py     # Embedding dedup
│   │   │   └── pose_diversity.py       # Pose bin management
│   │   │
│   │   ├── candidate/                  # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   ├── candidate_manager.py    # Cross-camera aggregation
│   │   │   └── candidate_matcher.py    # Embedding similarity matching
│   │   │
│   │   ├── registration/              # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   ├── registration_queue.py   # Operator review queue
│   │   │   └── registration_engine.py  # Versioned gallery creation
│   │   │
│   │   ├── recognition/              # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   ├── recognition_engine_v2.py # Top-K + gallery verification
│   │   │   └── multi_camera_merge.py    # Cross-camera person timeline
│   │   │
│   │   ├── learning/                  # NEW MODULE
│   │   │   ├── __init__.py
│   │   │   └── progressive_learning.py # Auto gallery improvement
│   │   │
│   │   └── history/                   # NEW MODULE
│   │       ├── __init__.py
│   │       └── recognition_history.py  # Full audit logging
│   │
│   ├── projects/                       # UNCHANGED
│   │   ├── office_attendance/
│   │   ├── temple_security/
│   │   └── retail_analytics/
│   │
│   └── static/                         # UNCHANGED
│
├── storage/
│   ├── database.db                     # EXISTING
│   ├── faces/                          # EXISTING — person gallery images
│   ├── embeddings/                     # EXISTING — FAISS index files
│   ├── candidates/                     # NEW — candidate face crops
│   ├── snapshots/                      # NEW — recognition snapshots
│   └── archive/                        # NEW — archived gallery images
│
├── models/                             # EXISTING — ONNX models
├── config.json                         # EXISTING — extended
├── cameras.json                        # EXISTING — extended
└── main.py                            # EXISTING — uvicorn entrypoint
```

---

## 6. Thread / Async Processing Model

### Current (Single Camera)

```
Main Thread → uvicorn
    └── DetectionService._processing_loop (1 daemon thread)
        └── Reads from 1 CameraStreamManager
```

### Enterprise (N Cameras)

```
Main Thread → uvicorn (async FastAPI)
    │
    ├── CameraRegistry (coordinator)
    │   ├── CameraWorker[cam_01] (daemon thread)
    │   │   ├── StreamReader thread (frame grabbing)
    │   │   └── PipelineOrchestrator (detection + tracking + recognition)
    │   ├── CameraWorker[cam_02] (daemon thread)
    │   │   ├── StreamReader thread
    │   │   └── PipelineOrchestrator
    │   ├── CameraWorker[cam_03] ...
    │   └── CameraWorker[cam_N] ...
    │
    ├── CandidateManager (background thread)
    │   └── Polls active candidates, merges tracks, evaluates queue readiness
    │
    ├── ProgressiveLearning (background thread)
    │   └── Processes gallery update requests asynchronously
    │
    └── HealthMonitor (background thread)
        └── Checks camera heartbeats, triggers reconnects
```

### GPU Worker Pool (Future — 50+ Cameras)

```
┌─────────────────────────────────────────────┐
│            Frame Queue (Thread-safe)         │
│  CameraWorker[1..N] ──push──► Queue         │
└──────────────────────┬──────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │     GPU Worker Pool        │
         │  Worker 1 (GPU:0, batch)   │
         │  Worker 2 (GPU:0, batch)   │
         │  Worker 3 (GPU:1, batch)   │
         │  Worker 4 (GPU:1, batch)   │
         └─────────────┬──────────────┘
                       │
         ┌─────────────▼──────────────┐
         │   Results returned to      │
         │   originating camera's     │
         │   PipelineOrchestrator     │
         └────────────────────────────┘
```

**Batch processing**: Instead of 1 face at a time through ONNX, batch 8-16 faces from multiple cameras into a single GPU inference call.

---

## 7. Key Workflows

### Registration Workflow (Enterprise)

```
Unknown face on Camera A
    │
    ▼
TrackManager creates Track(cam_01:t42, state=TRACKING)
    │
    ▼
FaceBuffer collects 15 frames over 5 seconds
    │
    ▼
QualityEngine scores each → 15 captures, 9 pass quality
    │
    ▼
DuplicateEngine deduplicates → 6 unique captures
    │
    ▼
PoseDiversity selects → 4 diverse poses
    │
    ▼
RecognitionEngine: No match in FAISS → UNKNOWN
    │
    ▼
CandidateManager: No existing candidate matches
    → Creates Candidate #42 (status=COLLECTING)
    │
    ▼
Same person appears on Camera C 2 minutes later
    → CandidateManager: embedding matches Candidate #42 (sim=0.81)
    → Merges new captures into Candidate #42
    │
    ▼
Candidate #42 now has 8 best images from 2 cameras
    → avg_quality=0.78, seen_cameras=[cam_01, cam_03]
    → Auto-queued for registration (status=READY)
    │
    ▼
Operator reviews on dashboard
    → Enters name, department
    → Clicks [Register]
    │
    ▼
RegistrationEngine:
    → Creates PersonModel
    → Stores 8 gallery images (versioned)
    → Generates 8 embeddings → FAISS
    → Links to source candidate
    → Gallery version = 1
    │
    ▼
Person is now recognized on all cameras
```

### Recognition Workflow (Enterprise)

```
Face detected on Camera B
    │
    ▼
ArcFace embedding extracted (EXISTING)
    │
    ▼
FAISS Top-10 search (k=10)
    │
    ▼
Results: [PersonA: 0.78, 0.72, 0.65], [PersonB: 0.71], [PersonC: 0.68]
    │
    ▼
Gallery Verification:
    PersonA: max(0.78, 0.72, 0.65) = 0.78 ✓ (above 0.70)
    PersonB: max(0.71) = 0.71 ✓
    PersonC: max(0.68) = 0.68 ✗ (below 0.70)
    │
    ▼
Consensus Window (2-4 seconds of matching):
    Frame 1: PersonA 0.78
    Frame 2: PersonA 0.76
    Frame 3: PersonA 0.80
    → PersonA wins with avg 0.78
    │
    ▼
Final Decision: MATCH PersonA (similarity: 0.80)
    │
    ▼
RecognitionHistory: Log with camera_id, track_id, snapshot, embedding_version
MultiCameraMerge: Update person timeline
ProgressiveLearning: Evaluate if this capture improves gallery
```

### Progressive Learning Workflow

```
Recognized person (match_score=0.88) on Camera D
    │
    ▼
QualityEngine: score = 0.85 (excellent lighting, frontal pose)
    │
    ▼
DuplicateCheck: max similarity to existing gallery = 0.87
    → Not a duplicate (< 0.92) ✓
    │
    ▼
PoseDiversity: Current gallery has no LEFT_30 bin
    → New capture fills LEFT_30 ✓
    │
    ▼
GalleryUpdate:
    → Add new image to gallery
    → Generate embedding → add to FAISS
    → If gallery > 8 active images:
        → Archive lowest quality image
        → Remove its embedding from FAISS
    → Increment gallery_version
    │
    ▼
AuditLog: "Gallery updated for PersonA, version 1 → 2, added LEFT_30 pose"
```

---

## 8. API Specifications

### Camera Management

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/cameras` | List all cameras with status |
| `POST` | `/api/cameras` | Add new camera |
| `PUT` | `/api/cameras/{id}` | Update camera config |
| `DELETE` | `/api/cameras/{id}` | Remove camera |
| `POST` | `/api/cameras/{id}/start` | Start camera stream |
| `POST` | `/api/cameras/{id}/stop` | Stop camera stream |
| `GET` | `/api/cameras/{id}/health` | Camera health metrics |
| `GET` | `/api/cameras/{id}/feed` | MJPEG stream for specific camera |

### Candidate Queue

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/candidates` | List all candidates (filterable by status) |
| `GET` | `/api/candidates/{id}` | Candidate detail with images |
| `POST` | `/api/candidates/{id}/register` | Register candidate as person |
| `POST` | `/api/candidates/{id}/reject` | Reject candidate |
| `DELETE` | `/api/candidates/{id}` | Delete candidate |

### Person Gallery

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/persons` | List all registered persons |
| `GET` | `/api/persons/{id}` | Person detail with gallery |
| `GET` | `/api/persons/{id}/gallery` | Gallery images with quality metadata |
| `GET` | `/api/persons/{id}/timeline` | Recognition timeline across all cameras |
| `PUT` | `/api/persons/{id}` | Update person metadata |
| `DELETE` | `/api/persons/{id}` | Delete person + gallery + embeddings |

### Recognition History

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/history` | Paginated recognition history |
| `GET` | `/api/history/person/{id}` | History for specific person |
| `GET` | `/api/history/camera/{id}` | History for specific camera |
| `GET` | `/api/history/live` | Real-time recognition events (SSE) |

### System Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | System health with all cameras |
| `GET` | `/api/health/gpu` | GPU utilization metrics |
| `GET` | `/api/health/faiss` | FAISS index statistics |
| `GET` | `/api/health/queues` | Queue depths and processing rates |

---

## 9. Production Deployment Architecture

### Single Server (10-50 Cameras)

```
┌────────────────────────────────────┐
│         Single Server              │
│  CPU: 16-32 cores                  │
│  RAM: 64 GB                        │
│  GPU: 1x RTX 4090 / A4000         │
│                                    │
│  ┌──────────────────────────────┐  │
│  │  FastAPI + Uvicorn (4 workers)│  │
│  │  Camera Workers (N threads)   │  │
│  │  GPU Worker Pool (2 workers)  │  │
│  │  SQLite / PostgreSQL          │  │
│  │  FAISS Index (in-memory)      │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
```

### Distributed (100-400+ Cameras)

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Camera Node 1│  │ Camera Node 2│  │ Camera Node N│
│ 50 cameras   │  │ 50 cameras   │  │ 50 cameras   │
│ 1x GPU       │  │ 1x GPU       │  │ 1x GPU       │
│ FastAPI      │  │ FastAPI      │  │ FastAPI      │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └────────┬────────┘─────────────────┘
                │
      ┌─────────▼─────────┐
      │  Redis / RabbitMQ  │
      │  (message broker)  │
      └─────────┬─────────┘
                │
      ┌─────────▼─────────┐
      │  Central API       │
      │  PostgreSQL        │
      │  FAISS Cluster     │
      │  Dashboard         │
      └───────────────────┘
```

---

## 10. GPU Scaling Strategy

| Camera Count | Hardware | Strategy |
|---|---|---|
| 1-10 | CPU only | Current architecture, single thread |
| 10-30 | 1x GPU | Thread-per-camera, shared GPU inference |
| 30-100 | 1x GPU | GPU batch worker pool (batch 8-16 faces) + FPS throttling (3-5 FPS) |
| 100-200 | 2x GPU | Split cameras across GPUs, batch processing |
| 200-400+ | Multi-node | Distributed nodes, each handling 50 cameras with 1 GPU |

**FPS Throttling Guide**:
| Camera Count | Processing FPS | Detection FPS | Recognition FPS |
|---|---|---|---|
| 1-5 | 15-25 | Every frame | Every frame |
| 5-20 | 8-12 | Every frame | Every 2nd frame |
| 20-50 | 5-8 | Every 2nd frame | Every 3rd frame |
| 50-100 | 3-5 | Every 3rd frame | Every 5th frame |
| 100-400 | 1-3 | Every 5th frame | Every 10th frame |

---

## 11. Phased Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Database schema migration (14 tables)
- [ ] Camera Registry + Per-Camera Workers
- [ ] Track Manager with camera namespacing
- [ ] Extended quality scoring engine

### Phase 2: Candidate System (Week 3-4)
- [ ] Face Buffer with temporal collection
- [ ] Duplicate Removal Engine
- [ ] Pose Diversity Engine
- [ ] Candidate Manager + cross-camera matching
- [ ] Registration Queue UI

### Phase 3: Recognition Upgrade (Week 5-6)
- [ ] Recognition Engine v2 (Top-K + gallery verification)
- [ ] Progressive Learning Engine
- [ ] Full Recognition History + audit logging
- [ ] Multi-Camera Person Timeline

### Phase 4: Scale & Production (Week 7-8)
- [ ] GPU batch worker pool
- [ ] FPS throttling per camera
- [ ] Redis integration for message queuing
- [ ] PostgreSQL migration
- [ ] Production monitoring + alerting

---

## Open Questions

> [!IMPORTANT]
> **Q1**: For the candidate system, should unknown persons be auto-queued for registration, or should the operator manually initiate candidate collection? Auto-queuing could flood the queue in high-traffic environments.

> [!IMPORTANT]
> **Q2**: For progressive learning, should gallery updates happen synchronously (blocking the camera loop) or asynchronously (background thread with eventual consistency)?

> [!IMPORTANT]
> **Q3**: Should we implement Phase 1 (Foundation + Camera Management) first and validate before proceeding, or do you want the full 4-phase implementation planned at once?

> [!WARNING]
> **Q4**: Your current FAISS index uses `IndexFlatIP` which is exact search. At 400+ cameras generating millions of embeddings, this will slow down. Should we plan for `IndexIVFFlat` (approximate search) or `IndexHNSW` in the scalability phase?
