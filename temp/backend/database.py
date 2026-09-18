import sqlite3
from datetime import datetime, timezone
from pathlib import Path


TEMP_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = TEMP_ROOT / "courtiq_temp.db"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                input_path TEXT NOT NULL,
                output_path TEXT,
                status TEXT NOT NULL,
                makes INTEGER NOT NULL DEFAULT 0,
                misses INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS shots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                shot_number INTEGER NOT NULL,
                result TEXT NOT NULL,
                timestamp_s REAL NOT NULL,
                reason TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            """
        )


def create_session(session_id, original_filename, input_path):
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO sessions (
                id, original_filename, input_path, status, created_at
            ) VALUES (?, ?, ?, 'QUEUED', ?)
            """,
            (session_id, original_filename, str(input_path), utc_now()),
        )


def mark_processing(session_id):
    with connect() as connection:
        connection.execute(
            "UPDATE sessions SET status = 'PROCESSING', error_message = NULL WHERE id = ?",
            (session_id,),
        )


def mark_completed(session_id, output_path, events):
    makes = sum(event["result"] == "MAKE" for event in events)
    misses = sum(event["result"] == "MISS" for event in events)

    with connect() as connection:
        connection.execute("DELETE FROM shots WHERE session_id = ?", (session_id,))
        connection.executemany(
            """
            INSERT INTO shots (
                session_id, shot_number, result, timestamp_s, reason
            ) VALUES (?, ?, ?, ?, ?)
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
            SET status = 'COMPLETED', output_path = ?, makes = ?, misses = ?,
                completed_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (str(output_path), makes, misses, utc_now(), session_id),
        )


def mark_failed(session_id, error_message):
    with connect() as connection:
        connection.execute(
            """
            UPDATE sessions
            SET status = 'FAILED', error_message = ?, completed_at = ?
            WHERE id = ?
            """,
            (error_message, utc_now(), session_id),
        )


def get_session(session_id):
    with connect() as connection:
        session_row = connection.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            return None

        shot_rows = connection.execute(
            """
            SELECT shot_number, result, timestamp_s, reason
            FROM shots
            WHERE session_id = ?
            ORDER BY shot_number
            """,
            (session_id,),
        ).fetchall()

    session = dict(session_row)
    session["shots"] = [dict(row) for row in shot_rows]
    return session
