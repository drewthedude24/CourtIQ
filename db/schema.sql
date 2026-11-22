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
