import os
from datetime import date, datetime, timezone

import psycopg
import pytest

from backend import database


EVENTS = [
    {"result": "MAKE", "timestamp_s": 1.5, "reason": "through rim"},
    {"result": "MISS", "timestamp_s": 3.0},
    {"result": "MAKE", "timestamp_s": 4.25, "reason": "swish"},
]
NO_FORM = dict.fromkeys(database.FORM_NUMBERS)


def shot_with_form(result, **numbers):
    """A detector event whose form block holds the given numbers and leaves the rest empty."""
    # The detector's form block also carries these three, which are not saved.
    form = {**NO_FORM, **numbers, "release_s": 1.0, "bend_s": 0.7, "arm": "right"}
    return {"result": result, "timestamp_s": 2.0, "form": form}


def run_sql(sql, params=()):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(sql, params)


@pytest.fixture(autouse=True)
def empty_database():
    database.initialize_database()
    run_sql("TRUNCATE sessions, shots, users, login_sessions")
    run_sql("REFRESH MATERIALIZED VIEW monthly_stats")


@pytest.fixture
def user():
    """The id of the person whose sessions a test makes."""
    return database.create_user("ann@example.com", "not a real hash")


@pytest.fixture
def other_user():
    return database.create_user("ben@example.com", "not a real hash")


def test_new_session_is_queued_with_no_shots(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")

    session = database.get_session("s1", user)

    assert session["status"] == "QUEUED"
    assert session["original_filename"] == "clip.mov"
    assert session["created_at"].tzinfo is not None
    assert (session["makes"], session["misses"], session["shots"]) == (0, 0, [])


def test_unknown_session_is_none(user):
    assert database.get_session("nope", user) is None


def test_completed_session_has_ordered_shots_and_counts(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")
    database.mark_processing("s1")
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS)

    session = database.get_session("s1", user)

    assert session["status"] == "COMPLETED"
    assert session["output_path"] == "/results/s1/annotated.mp4"
    assert session["completed_at"] is not None
    assert (session["makes"], session["misses"]) == (2, 1)
    assert session["shots"] == [
        {"shot_number": 1, "result": "MAKE", "timestamp_s": 1.5, "reason": "through rim", **NO_FORM},
        {"shot_number": 2, "result": "MISS", "timestamp_s": 3.0, "reason": None, **NO_FORM},
        {"shot_number": 3, "result": "MAKE", "timestamp_s": 4.25, "reason": "swish", **NO_FORM},
    ]


def test_form_numbers_are_saved_with_each_shot(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")
    measured = shot_with_form("MAKE", knee_bend_deg=95.5, arm_angle_deg=48.25, jump=0.25, flight_time_s=1.0)
    database.mark_completed("s1", "/results/s1/annotated.mp4", [measured, EVENTS[1]])

    first, second = database.get_session("s1", user)["shots"]

    # The elbow was hidden on the first shot, and the second shot has no form block at all.
    assert {name: first[name] for name in database.FORM_NUMBERS} == {
        "knee_bend_deg": 95.5, "elbow_bend_deg": None, "arm_angle_deg": 48.25,
        "jump": 0.25, "flight_time_s": 1.0,
    }
    assert {name: second[name] for name in database.FORM_NUMBERS} == NO_FORM


def test_completing_again_replaces_old_shots(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS)
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS[:1])

    assert len(database.get_session("s1", user)["shots"]) == 1


def test_failed_session_keeps_error_message(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")
    database.mark_failed("s1", "model crashed")

    session = database.get_session("s1", user)

    assert session["status"] == "FAILED"
    assert session["error_message"] == "model crashed"


def test_schema_rejects_unknown_status(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")

    with pytest.raises(psycopg.errors.CheckViolation):
        run_sql("UPDATE sessions SET status = 'DONE' WHERE id = 's1'")


def test_schema_rejects_shot_without_session():
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        run_sql(
            "INSERT INTO shots (session_id, shot_number, result, timestamp_s)"
            " VALUES ('ghost', 1, 'MAKE', 1.0)"
        )


def test_list_sessions_newest_first_with_shooting_pct(user):
    database.create_session("old", user, "a.mov", "/uploads/old/input.mov")
    database.mark_completed("old", "/results/old/annotated.mp4", EVENTS)
    database.create_session("new", user, "b.mov", "/uploads/new/input.mov")
    run_sql("UPDATE sessions SET created_at = now() - interval '1 day' WHERE id = 'old'")

    sessions = database.list_sessions(user)

    assert [s["id"] for s in sessions] == ["new", "old"]
    assert (sessions[0]["makes"], sessions[0]["misses"], sessions[0]["shooting_pct"]) == (0, 0, None)
    assert (sessions[1]["makes"], sessions[1]["misses"], sessions[1]["shooting_pct"]) == (2, 1, 66.7)


def test_list_sessions_for_one_month_only(user):
    # The last second of February, the first and last moments of March, and the first of April.
    for session_id, created_at in [
        ("feb", "2026-02-28 23:59:59+00"),
        ("mar_start", "2026-03-01 00:00+00"),
        ("mar_end", "2026-03-31 23:59:59+00"),
        ("apr", "2026-04-01 00:00+00"),
    ]:
        database.create_session(session_id, user, "a.mov", f"/uploads/{session_id}/input.mov")
        run_sql("UPDATE sessions SET created_at = %s WHERE id = %s", (created_at, session_id))
    database.mark_completed("mar_end", "/results/mar_end/annotated.mp4", EVENTS)

    sessions = database.list_sessions(user, month=date(2026, 3, 1))

    assert [(s["id"], s["makes"], s["misses"]) for s in sessions] == [
        ("mar_end", 2, 1),
        ("mar_start", 0, 0),
    ]


def test_stats_overall_and_per_month(user):
    database.create_session("m1", user, "a.mov", "/uploads/m1/input.mov")
    database.create_session("m3", user, "b.mov", "/uploads/m3/input.mov")
    run_sql("UPDATE sessions SET created_at = '2026-01-31 23:00+00' WHERE id = 'm1'")
    run_sql("UPDATE sessions SET created_at = '2026-03-01 01:00+00' WHERE id = 'm3'")
    database.mark_completed("m1", "/results/m1/annotated.mp4", EVENTS)
    database.mark_completed("m3", "/results/m3/annotated.mp4", EVENTS[:1])

    stats = database.get_stats(user)

    assert stats["overall"] == {"makes": 3, "misses": 1, "shooting_pct": 75.0}
    assert [(m["month"].isoformat(), m["makes"], m["misses"], m["shooting_pct"]) for m in stats["months"]] == [
        ("2026-01-01", 2, 1, 66.7),
        ("2026-03-01", 1, 0, 100.0),
    ]


def test_stats_follow_replaced_shots(user):
    database.create_session("s1", user, "a.mov", "/uploads/s1/input.mov")
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS)
    database.mark_completed("s1", "/results/s1/annotated.mp4", EVENTS[1:2])

    assert database.get_stats(user)["overall"] == {"makes": 0, "misses": 1, "shooting_pct": 0.0}


def test_stats_with_no_shots(user):
    assert database.get_stats(user) == {
        "overall": {"makes": 0, "misses": 0, "shooting_pct": None},
        "months": [],
    }


def test_session_form_compares_makes_with_misses(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")
    database.mark_completed("s1", "/results/s1/annotated.mp4", [
        shot_with_form("MAKE", knee_bend_deg=90, jump=0.25),
        shot_with_form("MAKE", knee_bend_deg=100),
        shot_with_form("MISS", knee_bend_deg=110),
    ])

    form = database.get_session("s1", user)["form"]

    assert form["makes"]["knee_bend_deg"] == 95.0
    assert form["misses"]["knee_bend_deg"] == 110.0
    assert form["all"]["knee_bend_deg"] == 100.0
    # Spread is how much the number changes from shot to shot (the standard deviation).
    assert form["makes"]["knee_bend_deg_spread"] == pytest.approx(7.07, abs=0.01)
    assert form["all"]["knee_bend_deg_spread"] == pytest.approx(10.0)
    # One shot has no spread, and a number measured on no shot has no average.
    assert form["misses"]["knee_bend_deg_spread"] is None
    assert form["makes"]["jump"] == 0.25
    assert form["misses"]["jump"] is None
    # How many shots each average is based on.
    assert (form["all"]["shots"], form["all"]["knee_bend_deg_shots"], form["all"]["jump_shots"]) == (3, 3, 1)
    assert (form["misses"]["shots"], form["misses"]["jump_shots"]) == (1, 0)


def test_session_form_without_any_makes(user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")
    database.mark_completed("s1", "/results/s1/annotated.mp4", [shot_with_form("MISS", jump=0.5)])

    form = database.get_session("s1", user)["form"]

    assert form["makes"] is None
    assert form["misses"]["jump"] == 0.5
    assert form["all"]["jump"] == 0.5


def test_form_trend_lists_measured_sessions_oldest_first(user):
    for session_id, created_at, events in [
        ("newer", "2026-03-02 12:00+00", [shot_with_form("MAKE", knee_bend_deg=100, flight_time_s=1.0)]),
        ("older", "2026-03-01 12:00+00", [
            shot_with_form("MAKE", knee_bend_deg=90, flight_time_s=1.0),
            shot_with_form("MISS", knee_bend_deg=96, flight_time_s=1.5),
        ]),
        # Processed before form was measured: its shots have no numbers, so it is left out.
        ("no_form", "2026-03-03 12:00+00", EVENTS),
    ]:
        database.create_session(session_id, user, "a.mov", f"/uploads/{session_id}/input.mov")
        run_sql("UPDATE sessions SET created_at = %s WHERE id = %s", (created_at, session_id))
        database.mark_completed(session_id, f"/results/{session_id}/annotated.mp4", events)

    trend = database.get_form_trend(user)

    assert [(row["id"], row["knee_bend_deg"], row["flight_time_s"], row["jump"]) for row in trend] == [
        ("older", 93.0, 1.25, None),
        ("newer", 100.0, 1.0, None),
    ]
    assert trend[0]["created_at"] == datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    assert trend[0]["original_filename"] == "a.mov"
    # The spread is how much a number changed from shot to shot inside that session.
    assert trend[0]["knee_bend_deg_spread"] == pytest.approx(4.24, abs=0.01)
    assert trend[1]["knee_bend_deg_spread"] is None
    # "older" has one make and one miss, and neither shot has a jump measured.
    assert (trend[0]["shots"], trend[0]["knee_bend_deg_shots"], trend[0]["jump_shots"]) == (2, 2, 0)
    assert (trend[0]["shooting_pct"], trend[1]["shooting_pct"]) == (50.0, 100.0)


def test_unknown_email_is_none():
    assert database.get_user_by_email("nobody@example.com") is None


def test_an_email_has_only_one_account(user):
    assert database.create_user("ann@example.com", "another hash") is None


def test_schema_rejects_session_of_unknown_user():
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        database.create_session("s1", 999, "clip.mov", "/uploads/s1/input.mov")


def test_someone_elses_session_is_none(user, other_user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")

    assert database.get_session("s1", other_user) is None


def test_list_stats_and_trend_hold_only_your_own_sessions(user, other_user):
    database.create_session("mine", user, "a.mov", "/uploads/mine/input.mov")
    database.mark_completed("mine", "/results/mine/annotated.mp4", [shot_with_form("MAKE", flight_time_s=1.0)])
    database.create_session("theirs", other_user, "b.mov", "/uploads/theirs/input.mov")
    database.mark_completed("theirs", "/results/theirs/annotated.mp4", [shot_with_form("MISS", flight_time_s=2.0)])

    assert [s["id"] for s in database.list_sessions(user)] == ["mine"]
    assert database.get_stats(user)["overall"] == {"makes": 1, "misses": 0, "shooting_pct": 100.0}
    assert [row["id"] for row in database.get_form_trend(user)] == ["mine"]


def test_cannot_delete_someone_elses_session(user, other_user):
    database.create_session("s1", user, "clip.mov", "/uploads/s1/input.mov")

    assert database.delete_session("s1", other_user) is False
    assert database.get_session("s1", user) is not None


def test_sessions_from_before_accounts_belong_to_nobody(user):
    # Old rows have no user_id until backend/give_old_sessions.py hands them out.
    run_sql(
        "INSERT INTO sessions (id, original_filename, input_path, status)"
        " VALUES ('old', 'a.mov', 'storage/uploads/old/input.mov', 'COMPLETED')"
    )

    assert database.list_sessions(user) == []
    assert database.get_session("old", user) is None


def test_jump_shots_are_every_shot_of_your_sessions_oldest_session_first(user, other_user):
    for session_id, owner, created_at, events in [
        ("newer", user, "2026-03-02 12:00+00", [shot_with_form("MISS", jump=0.25)]),
        ("older", user, "2026-03-01 12:00+00", [shot_with_form("MAKE", jump=0.5), shot_with_form("MISS")]),
        ("theirs", other_user, "2026-03-01 12:00+00", [shot_with_form("MAKE", jump=0.9)]),
    ]:
        database.create_session(session_id, owner, f"{session_id}.mov", f"/uploads/{session_id}/input.mov")
        run_sql("UPDATE sessions SET created_at = %s WHERE id = %s", (created_at, session_id))
        database.mark_completed(session_id, f"/results/{session_id}/annotated.mp4", events)

    rows = database.get_jump_shots(user)

    assert [(row["session_id"], row["shot_number"], row["jump"], row["result"]) for row in rows] == [
        ("older", 1, 0.5, "MAKE"), ("older", 2, None, "MISS"), ("newer", 1, 0.25, "MISS"),
    ]
    assert rows[0]["original_filename"] == "older.mov"
    assert rows[0]["created_at"] == datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
