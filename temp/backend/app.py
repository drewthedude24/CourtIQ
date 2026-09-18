import shutil
import sys
import traceback
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .database import (
    create_session,
    get_session,
    initialize_database,
    mark_completed,
    mark_failed,
    mark_processing,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_ROOT = TEMP_ROOT / "storage" / "uploads"
RESULT_ROOT = TEMP_ROOT / "storage" / "results"
ALLOWED_EXTENSIONS = {".mov", ".mp4", ".m4v"}
MAX_UPLOAD_BYTES = 1_000_000_000
WEB_INFERENCE_SIZE = (1280, 720)
WEB_FULL_IMAGE_SIZE = 960
WEB_FOCUS_IMAGE_SIZE = 640
WEB_FULL_FRAME_INTERVAL = 1
WEB_CONFIDENCE_THRESHOLD = 0.12
WEB_VIDEO_CODEC = "avc1"

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
RESULT_ROOT.mkdir(parents=True, exist_ok=True)
initialize_database()

app = FastAPI(title="CourtIQ Temporary MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

vision_lock = Lock()
process_video = None


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
        "shots": session["shots"],
    }


def run_processing_job(session_id, input_path, output_directory):
    mark_processing(session_id)
    try:
        processor = load_vision_processor()
        # The model objects are shared, so this temporary MVP handles one job at a time.
        with vision_lock:
            events = processor(str(input_path), str(output_directory))
        output_path = Path(output_directory) / "annotated.mp4"
        if not output_path.exists():
            raise RuntimeError("Vision processing finished without creating annotated.mp4")
        mark_completed(session_id, output_path, events)
    except Exception as error:
        traceback.print_exc()
        mark_failed(session_id, str(error))


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

    create_session(session_id, original_filename, input_path)
    background_tasks.add_task(
        run_processing_job,
        session_id,
        input_path,
        output_directory,
    )
    return public_session(get_session(session_id))


@app.get("/api/sessions/{session_id}")
def session_status(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return public_session(session)


@app.get("/api/sessions/{session_id}/video")
def session_video(session_id: str, download: bool = False):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] != "COMPLETED" or not session["output_path"]:
        raise HTTPException(status_code=409, detail="Video is not ready")

    output_path = Path(session["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Processed video file is missing")

    filename = f"courtiq-{session_id}.mp4" if download else None
    return FileResponse(output_path, media_type="video/mp4", filename=filename)
