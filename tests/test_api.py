import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.app import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_database():
    with database.connect() as connection:
        connection.execute("TRUNCATE sessions, shots")
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")


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
