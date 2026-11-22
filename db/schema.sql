CREATE TABLE IF NOT EXISTS sessions (
    id                text PRIMARY KEY,
    original_filename text NOT NULL,
    input_path        text NOT NULL,
    output_path       text,
    status            text NOT NULL
                      CHECK (status IN ('QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED')),
    created_at        timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz,
    error_message     text
);

-- Makes and misses are not stored on sessions; they are counted from this table.
CREATE TABLE IF NOT EXISTS shots (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  text NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    shot_number integer NOT NULL,
    result      text NOT NULL CHECK (result IN ('MAKE', 'MISS')),
    timestamp_s double precision NOT NULL,
    reason      text,
    UNIQUE (session_id, shot_number)
);

-- Holds every column a per-session make/miss count needs, so Postgres can answer
-- from this index alone and never open the table (see docs/query-optimization.md).
CREATE INDEX IF NOT EXISTS shots_session_id_result_idx ON shots (session_id, result);

-- Makes and misses per month, saved so the trend chart reads 12 rows instead of
-- every shot. backend/database.py refreshes it whenever a session's shots are saved.
CREATE MATERIALIZED VIEW IF NOT EXISTS monthly_stats AS
SELECT date_trunc('month', sessions.created_at)::date AS month,
       count(*) FILTER (WHERE shots.result = 'MAKE') AS makes,
       count(*) FILTER (WHERE shots.result = 'MISS') AS misses
FROM shots
JOIN sessions ON sessions.id = shots.session_id
GROUP BY 1;
