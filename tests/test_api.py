import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app as api
from backend import database
from backend.app import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_database():
    with database.connect() as connection:
        connection.execute("TRUNCATE sessions, shots")
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")


@pytest.fixture
def uploaded_clip(monkeypatch):
    """Upload a fake clip and return its session id.

    The real detector takes minutes and ffmpeg needs a real video, so both are
    replaced: the fake detector writes a tiny annotated.mp4 and reports one make
    with two form numbers measured, and a picture for one of them.
    TestClient finishes the background processing job before the upload returns.
    """

    def fake_detector(input_path, output_directory, on_progress):
        (Path(output_directory) / "annotated.mp4").write_bytes(b"fake video")
        (Path(output_directory) / "form").mkdir()
        (Path(output_directory) / "form" / "1_knee_bend_deg.jpg").write_bytes(b"fake picture")
        form = {**dict.fromkeys(database.FORM_NUMBERS), "knee_bend_deg": 95.5, "flight_time_s": 1.0}
        return [{"result": "MAKE", "timestamp_s": 1.5, "form": form}]

    monkeypatch.setattr(api, "load_vision_processor", lambda: fake_detector)
    monkeypatch.setattr(api, "convert_to_h264", lambda path: None)

    files = {"file": ("clip.mov", b"fake upload", "video/quicktime")}
    session_id = client.post("/api/sessions", files=files).json()["id"]
    yield session_id

    shutil.rmtree(api.UPLOAD_ROOT / session_id, ignore_errors=True)
    shutil.rmtree(api.RESULT_ROOT / session_id, ignore_errors=True)


def test_sessions_can_be_filtered_to_one_month():
    for session_id, created_at in [("feb", "2026-02-10 12:00+00"), ("mar", "2026-03-10 12:00+00")]:
        database.create_session(session_id, "a.mov", f"/uploads/{session_id}/input.mov")
        with database.connect() as connection:
            connection.execute(
                "UPDATE sessions SET created_at = %s WHERE id = %s", (created_at, session_id)
            )

    response = client.get("/api/sessions", params={"month": "2026-03"})

    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == ["mar"]


def test_bad_month_is_rejected():
    response = client.get("/api/sessions", params={"month": "2026-13"})

    assert response.status_code == 400


def test_video_paths_are_saved_relative_to_the_project(uploaded_clip):
    # A full path like /Users/me/CourtIQ/storage/... breaks inside Docker, where the
    # same folder is /app/storage/...
    session = database.get_session(uploaded_clip)

    assert session["input_path"] == f"storage/uploads/{uploaded_clip}/input.mov"
    assert session["output_path"] == f"storage/results/{uploaded_clip}/annotated.mp4"


def test_video_is_found_whatever_folder_the_server_runs_from(uploaded_clip, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    response = client.get(f"/api/sessions/{uploaded_clip}/video")

    assert response.status_code == 200
    assert response.content == b"fake video"


def test_session_comes_with_form_numbers(uploaded_clip):
    session = client.get(f"/api/sessions/{uploaded_clip}").json()

    shot = session["shots"][0]
    assert (shot["knee_bend_deg"], shot["elbow_bend_deg"], shot["flight_time_s"]) == (95.5, None, 1.0)
    assert session["form"]["makes"]["knee_bend_deg"] == 95.5
    assert session["form"]["misses"] is None


def test_each_shot_lists_its_form_pictures(uploaded_clip):
    shot = client.get(f"/api/sessions/{uploaded_clip}").json()["shots"][0]

    assert shot["pictures"] == {
        "knee_bend_deg": f"/api/sessions/{uploaded_clip}/shots/1/form/knee_bend_deg.jpg",
    }


def test_a_form_picture_can_be_loaded(uploaded_clip):
    response = client.get(f"/api/sessions/{uploaded_clip}/shots/1/form/knee_bend_deg.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"fake picture"


@pytest.mark.parametrize("name", ["elbow_bend_deg", "annotated"])
def test_a_missing_or_unknown_picture_is_not_found(uploaded_clip, name):
    # "annotated" is not a form number, so it can never reach a file outside the form folder.
    response = client.get(f"/api/sessions/{uploaded_clip}/shots/1/form/{name}.jpg")

    assert response.status_code == 404


def test_a_running_job_reports_how_far_it_is(monkeypatch):
    # The fake detector says it is on frame 30 of 120, then asks the API about its own
    # session the way the page does while it waits.
    seen = []

    def fake_detector(input_path, output_directory, on_progress):
        on_progress("detect", 30, 120)
        session_id = Path(output_directory).name
        seen.append(client.get(f"/api/sessions/{session_id}").json()["progress"])
        (Path(output_directory) / "annotated.mp4").write_bytes(b"fake video")
        return []

    monkeypatch.setattr(api, "load_vision_processor", lambda: fake_detector)
    monkeypatch.setattr(api, "convert_to_h264", lambda path: None)

    files = {"file": ("clip.mov", b"fake upload", "video/quicktime")}
    session_id = client.post("/api/sessions", files=files).json()["id"]

    assert seen == [{"stage": "detect", "done": 30, "total": 120}]
    # A finished job has nothing left to report.
    assert client.get(f"/api/sessions/{session_id}").json()["progress"] is None
    shutil.rmtree(api.UPLOAD_ROOT / session_id, ignore_errors=True)
    shutil.rmtree(api.RESULT_ROOT / session_id, ignore_errors=True)


def test_form_trend_has_one_row_per_measured_session(uploaded_clip):
    response = client.get("/api/stats/form")

    assert response.status_code == 200
    assert [(row["id"], row["knee_bend_deg"], row["jump"]) for row in response.json()] == [
        (uploaded_clip, 95.5, None),
    ]


def test_deleting_a_session_removes_only_that_session(uploaded_clip):
    # A second session with one miss, which must survive the delete.
    database.create_session("keep", "keep.mov", "storage/uploads/keep/input.mov")
    database.mark_completed(
        "keep", "storage/results/keep/annotated.mp4", [{"result": "MISS", "timestamp_s": 2.0}]
    )

    response = client.delete(f"/api/sessions/{uploaded_clip}")

    assert response.status_code == 204
    assert [s["id"] for s in client.get("/api/sessions").json()] == ["keep"]
    # The deleted session's make is gone from the stats; only the kept miss is left.
    assert client.get("/api/stats").json()["overall"] == {
        "makes": 0,
        "misses": 1,
        "shooting_pct": 0.0,
    }
    with database.connect() as connection:
        shots = connection.execute("SELECT session_id FROM shots").fetchall()
    assert [shot["session_id"] for shot in shots] == ["keep"]
    assert not (api.UPLOAD_ROOT / uploaded_clip).exists()
    assert not (api.RESULT_ROOT / uploaded_clip).exists()


def test_deleting_an_unknown_session_returns_404():
    response = client.delete("/api/sessions/does-not-exist")

    assert response.status_code == 404
