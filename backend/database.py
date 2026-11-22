import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
# The default matches docker-compose.yml, so local runs need no setup.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://courtiq:courtiq@localhost:5432/courtiq"
)


def connect():
    # Leaving a `with connect()` block commits, or rolls back on an error.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def initialize_database():
    with connect() as connection:
        connection.execute(SCHEMA_PATH.read_text())


def create_session(session_id, original_filename, input_path):
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO sessions (id, original_filename, input_path, status)
            VALUES (%s, %s, %s, 'QUEUED')
            """,
            (session_id, original_filename, str(input_path)),
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
                INSERT INTO shots (session_id, shot_number, result, timestamp_s, reason)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        session_id,
                        index,
                        event["result"],
                        float(event["timestamp_s"]),
                        event.get("reason"),
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


def delete_session(session_id):
    # Its shots go too: their foreign key has ON DELETE CASCADE (db/schema.sql).
    # Returns False when there was no such session.
    with connect() as connection:
        deleted = connection.execute(
            "DELETE FROM sessions WHERE id = %s RETURNING id", (session_id,)
        ).fetchone()
        connection.execute("REFRESH MATERIALIZED VIEW monthly_stats")
    return deleted is not None


def get_session(session_id):
    with connect() as connection:
        session = connection.execute(
            """
            SELECT sessions.*,
                   count(shots.id) FILTER (WHERE shots.result = 'MAKE') AS makes,
                   count(shots.id) FILTER (WHERE shots.result = 'MISS') AS misses
            FROM sessions
            LEFT JOIN shots ON shots.session_id = sessions.id
            WHERE sessions.id = %s
            GROUP BY sessions.id
            """,
            (session_id,),
        ).fetchone()
        if session is None:
            return None

        session["shots"] = connection.execute(
            """
            SELECT shot_number, result, timestamp_s, reason
            FROM shots
            WHERE session_id = %s
            ORDER BY shot_number
            """,
            (session_id,),
        ).fetchall()

    return session


def list_sessions(month=None):
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
            WHERE %(month)s::date IS NULL
               OR (sessions.created_at >= %(month)s::date
                   AND sessions.created_at < %(month)s::date + interval '1 month')
            GROUP BY sessions.id
            ORDER BY sessions.created_at DESC
            """,
            {"month": month},
        ).fetchall()


def get_stats():
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT month,
                   coalesce(sum(makes), 0)::int AS makes,
                   coalesce(sum(misses), 0)::int AS misses,
                   round(100.0 * sum(makes) / nullif(sum(makes + misses), 0), 1)::float
                       AS shooting_pct
            FROM monthly_stats
            GROUP BY ROLLUP (month)
            ORDER BY month NULLS LAST
            """
        ).fetchall()

    # ROLLUP adds one extra row for all months together. Its month is NULL, so it sorts last.
    overall = rows.pop()
    del overall["month"]
    return {"overall": overall, "months": rows}
