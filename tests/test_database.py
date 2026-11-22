import os
from datetime import date

import psycopg
import pytest

from backend import database


EVENTS = [
    {"result": "MAKE", "timestamp_s": 1.5, "reason": "through rim"},
    {"result": "MISS", "timestamp_s": 3.0},
    {"result": "MAKE", "timestamp_s": 4.25, "reason": "swish"},
]


def run_sql(sql, params=()):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(sql, params)


@pytest.fixture(autouse=True)
def empty_database():
    database.initialize_database()
    run_sql("TRUNCATE sessions, shots")
    run_sql("REFRESH MATERIALIZED VIEW monthly_stats")


def test_new_session_is_queued_with_no_shots():
    database.create_session("s1", "clip.mov", "/uploads/s1/input.mov")

    session = database.get_session("s1")

    assert session["status"] == "QUEUED"
    assert session["original_filename"] == "clip.mov"
    assert session["created_at"].tzinfo is not None
    assert (session["makes"], session["misses"], session["shots"]) == (0, 0, [])


def test_unknown_session_is_none():
    assert database.get_session("nope") is None


def test_completed_session_has_ordered_shots_and_counts():
    database.create_session("s1", "clip.mov", "/uploads/s1/input.mov")
    database.mark_processing("s1")
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS)

    session = database.get_session("s1")

    assert session["status"] == "COMPLETED"
    assert session["output_path"] == "/results/s1/annotated.mp4"
    assert session["completed_at"] is not None
    assert (session["makes"], session["misses"]) == (2, 1)
    assert session["shots"] == [
        {"shot_number": 1, "result": "MAKE", "timestamp_s": 1.5, "reason": "through rim"},
        {"shot_number": 2, "result": "MISS", "timestamp_s": 3.0, "reason": None},
        {"shot_number": 3, "result": "MAKE", "timestamp_s": 4.25, "reason": "swish"},
    ]


def test_completing_again_replaces_old_shots():
    database.create_session("s1", "clip.mov", "/uploads/s1/input.mov")
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS)
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS[:1])

    assert len(database.get_session("s1")["shots"]) == 1


def test_failed_session_keeps_error_message():
    database.create_session("s1", "clip.mov", "/uploads/s1/input.mov")
    database.mark_failed("s1", "model crashed")

    session = database.get_session("s1")

    assert session["status"] == "FAILED"
    assert session["error_message"] == "model crashed"


def test_schema_rejects_unknown_status():
    database.create_session("s1", "clip.mov", "/uploads/s1/input.mov")

    with pytest.raises(psycopg.errors.CheckViolation):
        run_sql("UPDATE sessions SET status = 'DONE' WHERE id = 's1'")


def test_schema_rejects_shot_without_session():
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        run_sql(
            "INSERT INTO shots (session_id, shot_number, result, timestamp_s)"
            " VALUES ('ghost', 1, 'MAKE', 1.0)"
        )


def test_list_sessions_newest_first_with_shooting_pct():
    database.create_session("old", "a.mov", "/uploads/old/input.mov")
    database.mark_completed("old", "/results/old/annotated.mp4", EVENTS)
    database.create_session("new", "b.mov", "/uploads/new/input.mov")
    run_sql("UPDATE sessions SET created_at = now() - interval '1 day' WHERE id = 'old'")

    sessions = database.list_sessions()

    assert [s["id"] for s in sessions] == ["new", "old"]
    assert (sessions[0]["makes"], sessions[0]["misses"], sessions[0]["shooting_pct"]) == (0, 0, None)
    assert (sessions[1]["makes"], sessions[1]["misses"], sessions[1]["shooting_pct"]) == (2, 1, 66.7)


def test_list_sessions_for_one_month_only():
    # The last second of February, the first and last moments of March, and the first of April.
    for session_id, created_at in [
        ("feb", "2026-02-28 23:59:59+00"),
        ("mar_start", "2026-03-01 00:00+00"),
        ("mar_end", "2026-03-31 23:59:59+00"),
        ("apr", "2026-04-01 00:00+00"),
    ]:
        database.create_session(session_id, "a.mov", f"/uploads/{session_id}/input.mov")
        run_sql("UPDATE sessions SET created_at = %s WHERE id = %s", (created_at, session_id))
    database.mark_completed("mar_end", "/results/mar_end/annotated.mp4", EVENTS)

    sessions = database.list_sessions(month=date(2026, 3, 1))

    assert [(s["id"], s["makes"], s["misses"]) for s in sessions] == [
        ("mar_end", 2, 1),
        ("mar_start", 0, 0),
    ]


def test_stats_overall_and_per_month():
    database.create_session("m1", "a.mov", "/uploads/m1/input.mov")
    database.create_session("m3", "b.mov", "/uploads/m3/input.mov")
    run_sql("UPDATE sessions SET created_at = '2026-01-31 23:00+00' WHERE id = 'm1'")
    run_sql("UPDATE sessions SET created_at = '2026-03-01 01:00+00' WHERE id = 'm3'")
    database.mark_completed("m1", "/results/m1/annotated.mp4", EVENTS)
    database.mark_completed("m3", "/results/m3/annotated.mp4", EVENTS[:1])

    stats = database.get_stats()

    assert stats["overall"] == {"makes": 3, "misses": 1, "shooting_pct": 75.0}
    assert [(m["month"].isoformat(), m["makes"], m["misses"], m["shooting_pct"]) for m in stats["months"]] == [
        ("2026-01-01", 2, 1, 66.7),
        ("2026-03-01", 1, 0, 100.0),
    ]


def test_stats_follow_replaced_shots():
    database.create_session("s1", "a.mov", "/uploads/s1/input.mov")
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS)
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS[1:2])

    assert database.get_stats()["overall"] == {"makes": 0, "misses": 1, "shooting_pct": 0.0}


def test_stats_with_no_shots():
    assert database.get_stats() == {
        "overall": {"makes": 0, "misses": 0, "shooting_pct": None},
        "months": [],
    }
