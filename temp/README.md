# CourtIQ Temporary Full-Stack MVP

This disposable app uploads one basketball video, processes it with
`vision/offline_runner.py`, stores session and shot records in SQLite, and plays
the tracking video directly in React.

## Structure

```text
temp/
├── backend/                 FastAPI API and SQLite functions
├── frontend/                React and Vite frontend
├── storage/uploads/         Uploaded source videos
├── storage/results/         Vision output folders
└── courtiq_temp.db          Created automatically on backend startup
```

## Start The Backend

Run this from the CourtIQ project root:

```bash
.venv/bin/python -m uvicorn temp.backend.app:app --reload --port 8000
```

Useful URLs:

- Health check: http://127.0.0.1:8000/api/health
- Interactive API docs: http://127.0.0.1:8000/docs

## Start The Frontend

In a second terminal:

```bash
cd temp/frontend
npm install
npm run dev
```

Open http://localhost:5173 and upload a `.mov`, `.mp4`, or `.m4v` video.

### If Port 8000 Is Busy

Start the backend on 8010:

```bash
.venv/bin/python -m uvicorn temp.backend.app:app --reload --port 8010
```

Then start the frontend with its proxy pointed at that port:

```bash
cd temp/frontend
COURTIQ_API_PROXY=http://127.0.0.1:8010 npm run dev
```

## Processing Flow

```text
React POST /api/sessions
  -> FastAPI saves the upload
  -> FastAPI returns a session ID
  -> Background task calls offline_runner.process_vid
  -> SQLite stores makes, misses, and shots
  -> React polls GET /api/sessions/{id}
  -> React displays the finished tracking video
```

This local MVP intentionally handles one vision job at a time. The first job
also loads the YOLO and pose models, so its `PROCESSING` stage starts slowly.
The web backend uses the Output 6 quality profile: orientation-aware
`1280x720` bounds without stretching, `960` full-frame YOLO, `640` focused
crops, confidence `0.12`, and a full-frame scan on every frame. It also writes
H.264 MP4 output so the result plays in modern browsers; the standalone runner
keeps its existing `mp4v` default.

## Reset Everything

Stop both servers, then delete `temp`. Everything created by this experiment,
including its database and uploaded videos, stays inside that folder.
