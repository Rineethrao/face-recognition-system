# AI Vision — Face Recognition System

Enterprise multi-camera CCTV face recognition platform: live RTSP/USB ingest, SCRFD detection, ByteTrack tracking, ArcFace embeddings, FAISS matching, person enrollment, and an operator web UI.

## Requirements

- **Python** 3.10+
- **Node.js** 18+ and npm
- **ONNX models** (not shipped in git; download into `backend/Ai-models/` — see Quick start):
  - `det_10g.onnx` — SCRFD face detector (~17 MB)
  - `w600k_r50.onnx` — ArcFace recognizer (~166 MB)
- Optional: a webcam (`0`) or RTSP cameras configured in `backend/cameras.json`

## Project layout

```
backend/          FastAPI API + ML pipeline (default port 8000)
frontend_src/     React + Vite UI (dev port 3000; builds to frontend/)
docs/             Architecture notes
```

## Quick start — macOS

Paths assume the repo is at `~/Desktop/REPO/face-recognition-system` (adjust if yours differs). Use **zsh** / **Terminal**.

### Prerequisites

```bash
brew install python@3.12 node
```

### Terminal 1 — Backend (uvicorn)

```bash
cd ~/Desktop/REPO/face-recognition-system/backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

mkdir -p Ai-models storage/faces storage/embeddings

# Download InsightFace buffalo_l ONNX weights (required)
curl -L -o Ai-models/det_10g.onnx \
  "https://huggingface.co/public-data/insightface/resolve/main/models/buffalo_l/det_10g.onnx"
curl -L -o Ai-models/w600k_r50.onnx \
  "https://huggingface.co/public-data/insightface/resolve/main/models/buffalo_l/w600k_r50.onnx"

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Dev with auto-reload:

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Or:

```bash
source venv/bin/activate
python main.py
```

Check the API:

```bash
curl http://127.0.0.1:8000/health
open http://127.0.0.1:8000/docs
```

### Terminal 2 — Frontend (dev)

```bash
cd ~/Desktop/REPO/face-recognition-system/frontend_src
npm install
npm run dev
open http://127.0.0.1:3000
```

### macOS — production-style (single server)

```bash
cd ~/Desktop/REPO/face-recognition-system/frontend_src
npm install
npm run build

cd ../backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
open http://127.0.0.1:8000
```

| What | URL |
|------|-----|
| **Web app (dev)** | [http://127.0.0.1:3000](http://127.0.0.1:3000) |
| **Web app (built / uvicorn)** | [http://127.0.0.1:8000](http://127.0.0.1:8000) |
| **Health** | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |
| **Swagger** | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |

---

## Quick start — Linux

### Prerequisites

Debian / Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm
```

Fedora:

```bash
sudo dnf install -y python3 python3-pip nodejs npm
```

### Terminal 1 — Backend (uvicorn)

```bash
cd /path/to/face-recognition-system/backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

mkdir -p Ai-models storage/faces storage/embeddings

# Download InsightFace buffalo_l ONNX weights (required)
curl -L -o Ai-models/det_10g.onnx \
  "https://huggingface.co/public-data/insightface/resolve/main/models/buffalo_l/det_10g.onnx"
curl -L -o Ai-models/w600k_r50.onnx \
  "https://huggingface.co/public-data/insightface/resolve/main/models/buffalo_l/w600k_r50.onnx"

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
curl http://127.0.0.1:8000/health
xdg-open http://127.0.0.1:8000/docs
```

### Terminal 2 — Frontend (dev)

```bash
cd /path/to/face-recognition-system/frontend_src
npm install
npm run dev
xdg-open http://127.0.0.1:3000
```

### Linux — production-style (single server)

```bash
cd /path/to/face-recognition-system/frontend_src
npm install
npm run build

cd ../backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
xdg-open http://127.0.0.1:8000
```

---

## Quick start — Windows (optional)

```bat
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bat
cd frontend_src
npm install
npm run dev
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000) in your browser.

## UI routes

After opening the app:

| Path | Page |
|------|------|
| `/dashboard` | Overview |
| `/live` | Live recognition + video |
| `/cameras` | Camera management |
| `/persons` | Enrolled gallery |
| `/register` | Register a person |
| `/events` | Recognition events |
| `/analytics` | Analytics |
| `/settings` | Settings |

## Configuration

| File | Purpose |
|------|---------|
| `backend/config.json` | Model paths, detection/recognition thresholds, pipeline FPS, plugins |
| `backend/cameras.json` | Camera list (USB index or RTSP URL, enabled flag, rotation) |

Example: enable a local webcam by setting a camera `"source": "0"` and `"enabled": true` in `cameras.json`.

## Typical workflow

1. Start backend (`uvicorn app.main:app --host 0.0.0.0 --port 8000`).
2. Start frontend (`npm run dev`) **or** open the built UI on port 8000.
3. Open **Cameras**, add/enable a source, confirm video on **Live**.
4. Enroll people under **Register** / **Persons**.
5. Watch matches on **Live** and **Events**.

## Tech stack

- **Backend:** FastAPI, Uvicorn, OpenCV, ONNX Runtime, FAISS, SQLAlchemy (SQLite)
- **Frontend:** React 18, TypeScript, Vite, Tailwind, Zustand
- **ML:** SCRFD → ByteTrack → ArcFace → FAISS (`IndexFlatIP`)
