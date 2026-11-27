from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app as api
from backend import database
from backend.app import app


# Files these tests upload go to storage/test/ (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("test_storage")


def logged_in_browser(email):
    """A browser (its own cookie jar) that has signed up and is logged in."""
    browser = TestClient(app)
    browser.post("/api/signup", json={"email": email, "password": "correct horse"})
    return browser


def user_id(email):
    return database.get_user_by_email(email)["id"]


@pytest.fixture(autouse=True)
def empty_database():
    with database.connect() as connection:
        connection.execute("TRUNCATE sessions, shots, users, login_sessions")
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")


@pytest.fixture
def client():
    """Ann's browser. Every upload in these tests is hers unless it says otherwise."""
    return logged_in_browser("ann@example.com")


@pytest.fixture
def ben():
    """A second person's browser, who must never see or change Ann's data."""
    return logged_in_browser("ben@example.com")


@pytest.fixture
def uploaded_clip(client, monkeypatch):
    """Upload a fake clip and return its session id.

    The real detector takes minutes, so it is replaced: the fake detector writes a
    tiny annotated.mp4 and reports one make with two form numbers measured, and a
    picture for one of them.
    TestClient finishes the background processing job before the upload returns.
    """

    def fake_detector(input_path, output_directory, on_progress):
        (Path(output_directory) / "annotated.mp4").write_bytes(b"fake video")
        (Path(output_directory) / "form").mkdir()
        (Path(output_directory) / "form" / "1_knee_bend_deg.jpg").write_bytes(b"fake picture")
        form = {**dict.fromkeys(database.FORM_NUMBERS), "knee_bend_deg": 95.5, "flight_time_s": 1.0}
        return [{"result": "MAKE", "timestamp_s": 1.5, "form": form}]

    monkeypatch.setattr(api, "load_vision_processor", lambda: fake_detector)

    files = {"file": ("clip.mov", b"fake upload", "video/quicktime")}
    return client.post("/api/sessions", files=files).json()["id"]


def test_sessions_can_be_filtered_to_one_month(client):
    for session_id, created_at in [("feb", "2026-02-10 12:00+00"), ("mar", "2026-03-10 12:00+00")]:
        database.create_session(session_id, user_id("ann@example.com"), "a.mov", f"/uploads/{session_id}/input.mov")
        with database.connect() as connection:
            connection.execute(
                "UPDATE sessions SET created_at = %s WHERE id = %s", (created_at, session_id)
            )

    response = client.get("/api/sessions", params={"month": "2026-03"})

    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == ["mar"]


def test_bad_month_is_rejected(client):
    response = client.get("/api/sessions", params={"month": "2026-13"})

    assert response.status_code == 400


def test_files_are_saved_in_the_users_own_folder_relative_to_the_project(uploaded_clip):
    # A full path like /Users/me/CourtIQ/storage/... breaks inside Docker, where the
    # same folder is /app/storage/...
    ann = user_id("ann@example.com")
    session = database.get_session(uploaded_clip, ann)

    assert session["input_path"] == f"storage/test/uploads/{ann}/{uploaded_clip}/input.mov"
    assert session["output_path"] == f"storage/test/results/{ann}/{uploaded_clip}/annotated.mp4"
    assert (api.RESULT_ROOT / str(ann) / uploaded_clip / "form" / "1_knee_bend_deg.jpg").exists()


def test_video_is_found_whatever_folder_the_server_runs_from(client, uploaded_clip, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    response = client.get(f"/api/sessions/{uploaded_clip}/video")

    assert response.status_code == 200
    assert response.content == b"fake video"


def test_session_comes_with_form_numbers(client, uploaded_clip):
    session = client.get(f"/api/sessions/{uploaded_clip}").json()

    shot = session["shots"][0]
    assert (shot["knee_bend_deg"], shot["elbow_bend_deg"], shot["flight_time_s"]) == (95.5, None, 1.0)
    assert session["form"]["makes"]["knee_bend_deg"] == 95.5
    assert session["form"]["misses"] is None


def test_each_shot_lists_its_form_pictures(client, uploaded_clip):
    shot = client.get(f"/api/sessions/{uploaded_clip}").json()["shots"][0]

    assert shot["pictures"] == {
        "knee_bend_deg": f"/api/sessions/{uploaded_clip}/shots/1/form/knee_bend_deg.jpg",
    }


def test_a_form_picture_can_be_loaded(client, uploaded_clip):
    response = client.get(f"/api/sessions/{uploaded_clip}/shots/1/form/knee_bend_deg.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"fake picture"


@pytest.mark.parametrize("name", ["elbow_bend_deg", "annotated"])
def test_a_missing_or_unknown_picture_is_not_found(client, uploaded_clip, name):
    # "annotated" is not a form number, so it can never reach a file outside the form folder.
    response = client.get(f"/api/sessions/{uploaded_clip}/shots/1/form/{name}.jpg")

    assert response.status_code == 404


def test_a_running_job_reports_how_far_it_is(client, monkeypatch):
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

    files = {"file": ("clip.mov", b"fake upload", "video/quicktime")}
    session_id = client.post("/api/sessions", files=files).json()["id"]

    assert seen == [{"stage": "detect", "done": 30, "total": 120}]
    # A finished job has nothing left to report.
    assert client.get(f"/api/sessions/{session_id}").json()["progress"] is None


def test_form_trend_has_one_row_per_measured_session(client, uploaded_clip):
    response = client.get("/api/stats/form")

    assert response.status_code == 200
    assert [(row["id"], row["knee_bend_deg"], row["jump"]) for row in response.json()] == [
        (uploaded_clip, 95.5, None),
    ]


def test_fatigue_report_is_fitted_from_my_own_shots_only(client, ben, monkeypatch):
    # Three clips whose jump falls by 0.01 a shot, from a different start each time.
    starts = iter([0.30, 0.25, 0.28])

    def fake_detector(input_path, output_directory, on_progress):
        (Path(output_directory) / "annotated.mp4").write_bytes(b"fake video")
        start = next(starts)
        return [
            {"result": "MAKE", "timestamp_s": float(shot),
             "form": {**dict.fromkeys(database.FORM_NUMBERS), "jump": start - 0.01 * shot}}
            for shot in range(6)
        ]

    monkeypatch.setattr(api, "load_vision_processor", lambda: fake_detector)
    for _ in range(3):
        client.post("/api/sessions", files={"file": ("clip.mov", b"fake upload", "video/quicktime")})

    report = client.get("/api/stats/fatigue").json()

    assert report["model"]["per_shot"] == pytest.approx(-0.01, abs=1e-6)
    assert report["model"]["sessions"] == 3
    assert [len(session["shots"]) for session in report["sessions"]] == [6, 6, 6]
    assert ben.get("/api/stats/fatigue").json() == {"model": None, "sessions": [], "makes": None}


def test_deleting_a_session_removes_only_that_session(client, uploaded_clip):
    # A second session with one miss, which must survive the delete.
    database.create_session("keep", user_id("ann@example.com"), "keep.mov", "storage/uploads/keep/input.mov")
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
    folder = Path(str(user_id("ann@example.com"))) / uploaded_clip
    assert not (api.UPLOAD_ROOT / folder).exists()
    assert not (api.RESULT_ROOT / folder).exists()


def test_deleting_an_unknown_session_returns_404(client):
    response = client.delete("/api/sessions/does-not-exist")

    assert response.status_code == 404


def test_another_user_sees_none_of_my_sessions_or_stats(uploaded_clip, ben):
    assert ben.get("/api/sessions").json() == []
    assert ben.get("/api/stats/form").json() == []
    assert ben.get("/api/stats").json() == {
        "overall": {"makes": 0, "misses": 0, "shooting_pct": None},
        "months": [],
    }


@pytest.mark.parametrize(
    "path",
    ["", "/video", "/shots/1/form/knee_bend_deg.jpg"],
)
def test_another_user_cannot_open_my_session_by_its_id(uploaded_clip, ben, path):
    # 404, the same as a made-up id, so guessing ids tells nobody which ones exist.
    response = ben.get(f"/api/sessions/{uploaded_clip}{path}")

    assert response.status_code == 404


def test_another_user_cannot_delete_my_session(client, uploaded_clip, ben):
    assert ben.delete(f"/api/sessions/{uploaded_clip}").status_code == 404

    assert [s["id"] for s in client.get("/api/sessions").json()] == [uploaded_clip]
    assert client.get(f"/api/sessions/{uploaded_clip}/video").content == b"fake video"


def test_my_upload_is_listed_only_for_me(client, uploaded_clip, ben):
    assert [s["id"] for s in client.get("/api/sessions").json()] == [uploaded_clip]
    assert client.get("/api/stats").json()["overall"]["makes"] == 1
    assert ben.get("/api/stats").json()["overall"]["makes"] == 0


@pytest.mark.parametrize("path", ["/video", "/shots/1/form/knee_bend_deg.jpg"])
def test_browser_must_ask_the_server_again_before_reusing_a_file(client, uploaded_clip, path):
    # Otherwise the next person on the same browser could get a copy the browser kept,
    # without the server ever checking who is logged in.
    response = client.get(f"/api/sessions/{uploaded_clip}{path}")

    assert response.headers["cache-control"] == "private, no-cache"
