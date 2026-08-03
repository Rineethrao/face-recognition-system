# Analytics System — How It Works

## Architecture: Backend-Heavy, Frontend = Display Only

The analytics in this system are **entirely driven by backend logic**. The frontend only **polls** the backend and **renders** what it receives. Here's the full pipeline:

---

## 🔴 Backend Pipeline (The Real Engine)

### Stage 1 — Camera Stream (`app/core/stream.py`)
- `camera_manager` reads raw video frames in a background thread.
- Supports RTSP, USB webcams, and video files.

### Stage 2 — SCRFD Face Detection (`app/core/detector.py`)
- Every frame is passed to `SCRFDDetector` (ONNX model: `det_10g.onnx`).
- Returns bounding boxes + **5 facial landmarks** per detected face.
- Automatically uses **CUDA** if a GPU is available via `CUDAExecutionProvider`, otherwise falls back to CPU.

```python
# detector.py – line 35-37
providers = ort.get_available_providers()
selected_providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if 'CUDAExecutionProvider' in providers else ['CPUExecutionProvider']
self.session = ort.InferenceSession(self.model_path, providers=selected_providers)
```

### Stage 3 — ByteTrack Face Tracking (`app/core/tracker.py`)
- Custom **ByteTrack** implementation using IoU + Hungarian algorithm.
- Assigns a persistent `track_id` to each face across frames.
- Distinguishes **high-confidence** and **low-confidence** detections for robust multi-person tracking.

### Stage 4 — ArcFace Embedding (`app/core/recognizer.py`)
- Each tracked face is **aligned to 112×112** using the 5 landmarks.
- ArcFace model (`w600k_r50.onnx`) extracts a **512-dimensional embedding**.
- Also uses CUDA automatically if available.

### Stage 5 — FAISS Similarity Search (`app/core/faiss_index.py`)
- Uses `IndexFlatIP` (Inner Product = Cosine Similarity on L2-normalized vectors).
- Searches registered embeddings with a configurable **similarity threshold**.
- Returns matching `person_id`, `name`, and `similarity` score.

### Stage 6 — Recognition Consensus (`app/services/recognition_service.py`)
- A **2-4 second time window** is applied per `track_id`.
- Collects multiple FAISS match results for the same track, then:
  - Picks the person with the **highest average similarity** across votes.
  - Locks in a `final_match` for that track to stop re-processing.

### Stage 7 — Event Logging (`app/services/detection_service.py`)
- On a confirmed match, logs to **SQLite** via `RecognitionLogModel`.
- **5-second cooldown** per `(track_id, person_id)` pair to avoid duplicate entries.
- Dispatches events to project plugins (Attendance, Retail, Security).
- Caches Base64 JPEG face crops in memory (`recent_face_crops`).

---

## 🟢 Frontend Logic (Display Only)

The frontend in `frontend/js/app.js` does **zero AI computation**. It simply polls REST endpoints:

| Endpoint | Polling Interval | What it shows |
|---|---|---|
| `GET /recognitions?limit=15` | **every 3 seconds** | Recognition event log cards |
| `GET /detected_faces` | **every 1.5 seconds** | Live face thumbnails strip |
| `GET /health` | **every 10 seconds** | FAISS vector count, system status |
| `GET /video_feed` | **MJPEG stream** | Annotated live video (bboxes drawn by backend) |

> The bounding boxes, landmark dots, and name overlays you see on the live feed are **drawn by OpenCV on the backend** (`detection_service.py` lines 152–163) and streamed as JPEG frames — the frontend just shows a `<img>` tag.

---

## Analytics Flow Diagram

```
Camera Frame
     │
     ▼
[SCRFD Detector] ──ONNX (GPU/CPU)──► Bounding Boxes + Landmarks
     │
     ▼
[ByteTrack Tracker] ──IoU Hungarian Matching──► TrackedFace (track_id)
     │
     ▼
[ArcFace Recognizer] ──ONNX (GPU/CPU)──► 512D Embedding
     │
     ▼
[FAISS IndexFlatIP Search] ──Cosine Similarity──► person_id + similarity score
     │
     ▼
[Recognition Service] ──2-4s Consensus Window──► Final Match
     │
     ▼
[DB Log + Plugin Dispatch] ──5s cooldown──► RecognitionLogModel + Events
     │
     ▼
[Frontend polls /recognitions every 3s] ──REST──► Renders event cards
```

---

## Summary

| Layer | Role |
|---|---|
| **Backend** | All AI inference (detection, embedding, FAISS search), tracking, consensus, DB logging, frame annotation |
| **Frontend** | Polling REST APIs + rendering HTML cards + displaying MJPEG stream |

backend application to run :venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8002

frontend application link: http://127.0.0.1:8002/