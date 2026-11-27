import pytest
from fastapi.testclient import TestClient

import backend.app as api
from backend import database
from backend.app import app
from backend.give_old_sessions import give_old_sessions


# The files moved in these tests live in storage/test/ (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("test_storage")


@pytest.fixture(autouse=True)
def empty_database():
    with database.connect() as connection:
        connection.execute("TRUNCATE sessions, shots, users, login_sessions")


def log_in(email):
    browser = TestClient(app)
    browser.post("/api/login", json={"email": email})
    return browser


def make_old_session(session_id):
    """A session the way it was saved before accounts: no owner, and its files right under
    storage/uploads/ and storage/results/ (no user folder)."""
    upload = api.UPLOAD_ROOT / session_id / "input.mov"
    video = api.RESULT_ROOT / session_id / "annotated.mp4"
    for path, content in [(upload, b"old upload"), (video, b"old video")]:
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sessions (id, original_filename, input_path, status) VALUES (%s, 'a.mov', %s, 'QUEUED')",
            (session_id, str(upload.relative_to(api.PROJECT_ROOT))),
        )
    database.mark_completed(
        session_id, video.relative_to(api.PROJECT_ROOT), [{"result": "MAKE", "timestamp_s": 1.0}]
    )


def test_old_sessions_become_yours_with_their_files_in_your_folder():
    andrew = log_in("andrew@example.com")
    make_old_session("old1")
    make_old_session("old2")

    assert give_old_sessions("Andrew@example.com") == 2

    assert sorted(s["id"] for s in andrew.get("/api/sessions").json()) == ["old1", "old2"]
    assert andrew.get("/api/sessions/old1/video").content == b"old video"
    assert andrew.get("/api/stats").json()["overall"]["makes"] == 2
    user_id = database.get_user_by_email("andrew@example.com")["id"]
    assert (api.UPLOAD_ROOT / str(user_id) / "old1" / "input.mov").read_bytes() == b"old upload"
    assert not (api.UPLOAD_ROOT / "old1").exists()
    assert not (api.RESULT_ROOT / "old1").exists()


def test_sessions_that_already_have_an_owner_are_left_alone():
    log_in("andrew@example.com")
    ben = log_in("ben@example.com")
    ben_id = database.get_user_by_email("ben@example.com")["id"]
    database.create_session("bens", ben_id, "b.mov", f"storage/test/uploads/{ben_id}/bens/input.mov")

    assert give_old_sessions("andrew@example.com") == 0

    assert [s["id"] for s in ben.get("/api/sessions").json()] == ["bens"]


def test_unknown_email_changes_nothing():
    make_old_session("old1")

    with pytest.raises(SystemExit):
        give_old_sessions("nobody@example.com")

    assert (api.UPLOAD_ROOT / "old1" / "input.mov").exists()
    with database.connect() as connection:
        assert connection.execute("SELECT user_id FROM sessions").fetchone()["user_id"] is None
