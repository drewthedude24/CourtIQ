import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
# The default matches docker-compose.yml, so local runs need no setup.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://courtiq:courtiq@localhost:5432/courtiq"
)


# The form numbers measured on each shot (vision/shot_form.py). Each is a column of `shots`.
FORM_NUMBERS = ("knee_bend_deg", "elbow_bend_deg", "arm_angle_deg", "jump", "flight_time_s")


# For a group of shots: how many there are, then for each form number its average, its spread
# (how much it changes from shot to shot) and how many shots it was measured on.
FORM_AGGREGATES = """
    count(*)                    AS shots,
    avg(knee_bend_deg)          AS knee_bend_deg,
    stddev_samp(knee_bend_deg)  AS knee_bend_deg_spread,
    count(knee_bend_deg)        AS knee_bend_deg_shots,
    avg(elbow_bend_deg)         AS elbow_bend_deg,
    stddev_samp(elbow_bend_deg) AS elbow_bend_deg_spread,
    count(elbow_bend_deg)       AS elbow_bend_deg_shots,
    avg(arm_angle_deg)          AS arm_angle_deg,
    stddev_samp(arm_angle_deg)  AS arm_angle_deg_spread,
    count(arm_angle_deg)        AS arm_angle_deg_shots,
    avg(jump)                   AS jump,
    stddev_samp(jump)           AS jump_spread,
    count(jump)                 AS jump_shots,
    avg(flight_time_s)          AS flight_time_s,
    stddev_samp(flight_time_s)  AS flight_time_s_spread,
    count(flight_time_s)        AS flight_time_s_shots
"""


def connect():
    # Leaving a `with connect()` block commits, or rolls back on an error.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def initialize_database():
    with connect() as connection:
        connection.execute(SCHEMA_PATH.read_text())


def get_or_create_user(email):
    # The id of the account with this email, made first if it's a new email.
    with connect() as connection:
        connection.execute(
            "INSERT INTO users (email) VALUES (%s) ON CONFLICT (email) DO NOTHING", (email,)
        )
        return connection.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()["id"]


def get_user_by_email(email):
    with connect() as connection:
        return connection.execute("SELECT id, email FROM users WHERE email = %s", (email,)).fetchone()


def create_login(user_id, token_hash, days):
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO login_sessions (token_hash, user_id, expires_at)
            VALUES (%s, %s, now() + make_interval(days => %s))
            """,
            (token_hash, user_id, days),
        )


def get_login_user(token_hash):
    # The user a browser's login belongs to, or None if it was never made, has expired,
    # or was logged out.
    with connect() as connection:
        return connection.execute(
            """
            SELECT users.id, users.email
            FROM login_sessions
            JOIN users ON users.id = login_sessions.user_id
            WHERE login_sessions.token_hash = %s AND login_sessions.expires_at > now()
            """,
            (token_hash,),
        ).fetchone()


def delete_login(token_hash):
    with connect() as connection:
        connection.execute("DELETE FROM login_sessions WHERE token_hash = %s", (token_hash,))


def create_session(session_id, user_id, original_filename, input_path):
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO sessions (id, user_id, original_filename, input_path, status)
            VALUES (%s, %s, %s, %s, 'QUEUED')
            """,
            (session_id, user_id, original_filename, str(input_path)),
        )


def mark_processing(session_id):
    with connect() as connection:
        connection.execute(
            "UPDATE sessions SET status = 'PROCESSING', error_message = NULL WHERE id = %s",
            (session_id,),
        )


def mark_completed(session_id, output_path, events):
    with connect() as connection:
        connection.execute("DELETE FROM shots WHERE session_id = %s", (session_id,))
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO shots (session_id, shot_number, result, timestamp_s, reason,
                                   knee_bend_deg, elbow_bend_deg, arm_angle_deg, jump, flight_time_s)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        session_id,
                        index,
                        event["result"],
                        float(event["timestamp_s"]),
                        event.get("reason"),
                        # A number the detector could not measure is None, which is saved as NULL.
                        *(event.get("form", {}).get(name) for name in FORM_NUMBERS),
                    )
                    for index, event in enumerate(events, start=1)
                ],
            )
        connection.execute(
            """
            UPDATE sessions
            SET status = 'COMPLETED', output_path = %s, completed_at = now(),
                error_message = NULL
            WHERE id = %s
            """,
            (str(output_path), session_id),
        )
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")


def mark_failed(session_id, error_message):
    with connect() as connection:
        connection.execute(
            """
            UPDATE sessions
            SET status = 'FAILED', error_message = %s, completed_at = now()
            WHERE id = %s
            """,
            (error_message, session_id),
        )


def delete_session(session_id, user_id):
    # Its shots go too: their foreign key has ON DELETE CASCADE (db/schema.sql).
    # Returns False when this user has no such session.
    with connect() as connection:
        deleted = connection.execute(
            "DELETE FROM sessions WHERE id = %s AND user_id = %s RETURNING id",
            (session_id, user_id),
        ).fetchone()
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")
    return deleted is not None


def get_session(session_id, user_id):
    # None when this user has no such session, even if someone else does.
    with connect() as connection:
        session = connection.execute(
            """
            SELECT sessions.*,
                   count(shots.id) FILTER (WHERE shots.result = 'MAKE') AS makes,
                   count(shots.id) FILTER (WHERE shots.result = 'MISS') AS misses
            FROM sessions
            LEFT JOIN shots ON shots.session_id = sessions.id
            WHERE sessions.id = %s AND sessions.user_id = %s
            GROUP BY sessions.id
            """,
            (session_id, user_id),
        ).fetchone()
        if session is None:
            return None

        session["shots"] = connection.execute(
            """
            SELECT shot_number, result, timestamp_s, reason,
                   knee_bend_deg, elbow_bend_deg, arm_angle_deg, jump, flight_time_s
            FROM shots
            WHERE session_id = %s
            ORDER BY shot_number
            """,
            (session_id,),
        ).fetchall()

        # The average and the spread (how much it changes from shot to shot) of each form
        # number: one row for makes, one for misses, and ROLLUP adds one for all shots.
        rows = connection.execute(
            f"""
            SELECT result, {FORM_AGGREGATES}
            FROM shots
            WHERE session_id = %s
            GROUP BY ROLLUP (result)
            """,
            (session_id,),
        ).fetchall()

    # The ROLLUP row's result is NULL. A session with no makes has no MAKE row.
    by_result = {row.pop("result"): row for row in rows}
    session["form"] = {
        "makes": by_result.get("MAKE"),
        "misses": by_result.get("MISS"),
        "all": by_result[None],
    }
    return session


def list_sessions(user_id, month=None):
    # `month` is the first day of a month (a date), or None for every session.
    # Counting shots.result, not shots.id, lets Postgres read only the
    # shots (session_id, result) index (see docs/query-optimization.md).
    with connect() as connection:
        return connection.execute(
            """
            SELECT sessions.id, sessions.original_filename, sessions.status,
                   sessions.created_at,
                   count(shots.result) FILTER (WHERE shots.result = 'MAKE') AS makes,
                   count(shots.result) FILTER (WHERE shots.result = 'MISS') AS misses,
                   round(100.0 * count(shots.result) FILTER (WHERE shots.result = 'MAKE')
                         / nullif(count(shots.result), 0), 1)::float AS shooting_pct
            FROM sessions
            LEFT JOIN shots ON shots.session_id = sessions.id
            WHERE sessions.user_id = %(user_id)s
              AND (%(month)s::date IS NULL
                   OR (sessions.created_at >= %(month)s::date
                       AND sessions.created_at < %(month)s::date + interval '1 month'))
            GROUP BY sessions.id
            ORDER BY sessions.created_at DESC
            """,
            {"user_id": user_id, "month": month},
        ).fetchall()


def get_form_trend(user_id):
    # Each session's average form numbers, oldest first, to see them change over time.
    # The spread says how much a number changed from shot to shot inside the session, so a
    # gap between two sessions can be compared with it.
    with connect() as connection:
        return connection.execute(
            f"""
            SELECT sessions.id, sessions.original_filename, sessions.created_at,
                   round(100.0 * count(*) FILTER (WHERE shots.result = 'MAKE') / count(*), 1)::float
                       AS shooting_pct,
                   {FORM_AGGREGATES}
            FROM sessions
            JOIN shots ON shots.session_id = sessions.id
            WHERE sessions.user_id = %s
            GROUP BY sessions.id
            -- Every measured shot has a flight time, so this leaves out sessions
            -- that were processed before form was measured.
            HAVING count(shots.flight_time_s) > 0
            ORDER BY sessions.created_at
            """,
            (user_id,),
        ).fetchall()


def get_jump_shots(user_id):
    # Every shot of every finished session, oldest session first and in the order the shots
    # were taken. backend/fatigue.py fits its model from these rows.
    with connect() as connection:
        return connection.execute(
            """
            SELECT sessions.id AS session_id, sessions.original_filename, sessions.created_at,
                   shots.shot_number, shots.jump, shots.result
            FROM sessions
            JOIN shots ON shots.session_id = sessions.id
            WHERE sessions.user_id = %s
            ORDER BY sessions.created_at, shots.shot_number
            """,
            (user_id,),
        ).fetchall()


def get_stats(user_id):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT month,
                   coalesce(sum(makes), 0)::int AS makes,
                   coalesce(sum(misses), 0)::int AS misses,
                   round(100.0 * sum(makes) / nullif(sum(makes + misses), 0), 1)::float
                       AS shooting_pct
            FROM monthly_stats
            WHERE user_id = %s
            GROUP BY ROLLUP (month)
            ORDER BY month NULLS LAST
            """,
            (user_id,),
        ).fetchall()

    # ROLLUP adds one extra row for all months together. Its month is NULL, so it sorts last.
    overall = rows.pop()
    del overall["month"]
    return {"overall": overall, "months": rows}
