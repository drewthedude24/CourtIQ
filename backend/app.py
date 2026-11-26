import shutil
import subprocess
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import (
    FORM_NUMBERS,
    create_session,
    delete_session,
    get_form_trend,
    get_session,
    get_stats,
    initialize_database,
    list_sessions,
    mark_completed,
    mark_failed,
    mark_processing,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_ROOT = PROJECT_ROOT / "storage" / "uploads"
RESULT_ROOT = PROJECT_ROOT / "storage" / "results"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ALLOWED_EXTENSIONS = {".mov", ".mp4", ".m4v"}
MAX_UPLOAD_BYTES = 1_000_000_000
WEB_INFERENCE_SIZE = (1280, 720)
WEB_FULL_IMAGE_SIZE = 640
# Focus crops are about 300x430 pixels, so 448 runs them near their real size
# instead of blowing them up to 640, which cost more than the full frame.
WEB_FOCUS_IMAGE_SIZE = 448
WEB_FULL_FRAME_INTERVAL = 1
WEB_CONFIDENCE_THRESHOLD = 0.12
# OpenCV on Linux can't write H.264, so write mp4v and let ffmpeg convert it.
WEB_VIDEO_CODEC = "mp4v"

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
RESULT_ROOT.mkdir(parents=True, exist_ok=True)
initialize_database()

app = FastAPI(title="CourtIQ")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

vision_lock = Lock()
process_video = None
# How far each running job is, for the page's progress bar: session id -> stage, done, total.
# "detect" counts video frames, "form" counts the frames the pose model runs on, and
# "encode" (the H.264 conversion) has no count. Kept in memory, since it only matters
# while the job runs and the job runs inside this same process.
progress = {}


def load_vision_processor():
    global process_video
    if process_video is None:
        vision_directory = str(PROJECT_ROOT / "vision")
        if vision_directory not in sys.path:
            sys.path.insert(0, vision_directory)
        import offline_runner

        # Keep the standalone defaults unchanged while the website uses the
        # higher-accuracy Output 6 profile.
        offline_runner.OFFLINE_INFERENCE_SIZE = WEB_INFERENCE_SIZE
        offline_runner.OFFLINE_YOLO_IMAGE_SIZE = WEB_FULL_IMAGE_SIZE
        offline_runner.OFFLINE_FOCUS_IMAGE_SIZE = WEB_FOCUS_IMAGE_SIZE
        offline_runner.OFFLINE_FULL_FRAME_INTERVAL = WEB_FULL_FRAME_INTERVAL
        offline_runner.OFFLINE_CONFIDENCE_THRESHOLD = WEB_CONFIDENCE_THRESHOLD
        offline_runner.OFFLINE_VIDEO_CODEC = WEB_VIDEO_CODEC
        offline_runner.yolo_detector.image_size = WEB_FULL_IMAGE_SIZE
        offline_runner.yolo_detector.focus_image_size = WEB_FOCUS_IMAGE_SIZE
        offline_runner.yolo_detector.conf = WEB_CONFIDENCE_THRESHOLD
        process_video = offline_runner.process_vid
    return process_video


def convert_to_h264(video_path):
    """Re-encode a video to H.264 in place, the codec every browser can play."""
    video_path = Path(video_path)
    converted_path = video_path.with_name("h264_" + video_path.name)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(converted_path)],
        check=True,
    )
    converted_path.replace(video_path)


def form_picture(session_id, shot_number, name):
    """Where a shot's picture for one form number is saved (vision/form_pictures.py)."""
    return RESULT_ROOT / session_id / "form" / f"{shot_number}_{name}.jpg"


def public_session(session):
    video_url = None
    if session["status"] == "COMPLETED" and session["output_path"]:
        video_url = f"/api/sessions/{session['id']}/video"

    return {
        "id": session["id"],
        "original_filename": session["original_filename"],
        "status": session["status"],
        "makes": session["makes"],
        "misses": session["misses"],
        "created_at": session["created_at"],
        "completed_at": session["completed_at"],
        "error_message": session["error_message"],
        "video_url": video_url,
        # A number that wasn't measured has no picture, so it isn't listed.
        "shots": [
            {**shot, "pictures": {
                name: f"/api/sessions/{session['id']}/shots/{shot['shot_number']}/form/{name}.jpg"
                for name in FORM_NUMBERS
                if form_picture(session["id"], shot["shot_number"], name).exists()
            }}
            for shot in session["shots"]
        ],
        "form": session["form"],
        "progress": progress.get(session["id"]),
    }


def run_processing_job(session_id, input_path, output_directory):
    mark_processing(session_id)

    def report(stage, done, total):
        progress[session_id] = {"stage": stage, "done": done, "total": total}

    try:
        processor = load_vision_processor()
        # The model objects are shared, so this temporary MVP handles one job at a time.
        with vision_lock:
            events = processor(str(input_path), str(output_directory), on_progress=report)
        output_path = Path(output_directory) / "annotated.mp4"
        if not output_path.exists():
            raise RuntimeError("Vision processing finished without creating annotated.mp4")
        report("encode", 0, 0)
        start = time.perf_counter()
        convert_to_h264(output_path)
        print(f"[{session_id}] H.264 conversion took {time.perf_counter() - start:.1f} s", flush=True)
        mark_completed(session_id, output_path.relative_to(PROJECT_ROOT), events)
    except Exception as error:
        traceback.print_exc()
        mark_failed(session_id, str(error))
    finally:
        progress.pop(session_id, None)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/sessions", status_code=202)
async def upload_video(file: UploadFile, background_tasks: BackgroundTasks):
    original_filename = file.filename or "upload.mp4"
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Upload a .mov, .mp4, or .m4v video.",
        )

    session_id = uuid4().hex
    upload_directory = UPLOAD_ROOT / session_id
    output_directory = RESULT_ROOT / session_id
    upload_directory.mkdir(parents=True, exist_ok=False)
    output_directory.mkdir(parents=True, exist_ok=False)
    input_path = upload_directory / f"input{extension}"

    bytes_written = 0
    try:
        with input_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Video exceeds the temporary 1 GB upload limit.",
                    )
                destination.write(chunk)
    except Exception:
        shutil.rmtree(upload_directory, ignore_errors=True)
        shutil.rmtree(output_directory, ignore_errors=True)
        raise
    finally:
        await file.close()

    # Save paths relative to the project, so they still work when the project folder
    # lives somewhere else (/app inside Docker, a different folder on EC2).
    create_session(session_id, original_filename, input_path.relative_to(PROJECT_ROOT))
    background_tasks.add_task(
        run_processing_job,
        session_id,
        input_path,
        output_directory,
    )
    return public_session(get_session(session_id))


@app.get("/api/sessions")
def sessions_list(month: str | None = None):
    # `month` looks like "2026-03". Without it, every session is listed.
    if month is None:
        return list_sessions()
    try:
        first_day = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(status_code=400, detail="month must look like 2026-03")
    return list_sessions(month=first_day)


@app.get("/api/stats")
def stats():
    return get_stats()


@app.get("/api/stats/form")
def form_trend():
    return get_form_trend()


@app.get("/api/sessions/{session_id}")
def session_status(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return public_session(session)


@app.delete("/api/sessions/{session_id}", status_code=204)
def remove_session(session_id: str):
    # The database check comes first, so only a real session id (never something
    # like "../..") is ever used to build a folder path to delete.
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    shutil.rmtree(UPLOAD_ROOT / session_id, ignore_errors=True)
    shutil.rmtree(RESULT_ROOT / session_id, ignore_errors=True)


@app.get("/api/sessions/{session_id}/video")
def session_video(session_id: str, download: bool = False):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] != "COMPLETED" or not session["output_path"]:
        raise HTTPException(status_code=409, detail="Video is not ready")

    output_path = PROJECT_ROOT / session["output_path"]
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Processed video file is missing")

    filename = f"courtiq-{session_id}.mp4" if download else None
    return FileResponse(output_path, media_type="video/mp4", filename=filename)


@app.get("/api/sessions/{session_id}/shots/{shot_number}/form/{name}.jpg")
def form_picture_file(session_id: str, shot_number: int, name: str):
    # Checking both first means only a real session id and a real form number (never
    # something like "../..") are used to build the file path.
    if name not in FORM_NUMBERS or get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Picture not found")
    path = form_picture(session_id, shot_number, name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Picture not found")
    return FileResponse(path, media_type="image/jpeg")


# The built React page (`npm run build`). Mounted last so the /api routes above match first.
# Skipped when there is no build, so `npm run dev` and the tests work without one.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
