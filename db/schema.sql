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

-- People with an account. An account is just an email, with no password (backend/accounts.py).
CREATE TABLE IF NOT EXISTS users (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email      text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- The first accounts version also kept a password hash. RDS ran it, so this removes it there.
ALTER TABLE users DROP COLUMN IF EXISTS password_hash;

-- One row per logged-in browser. The browser holds a random token in a cookie and this
-- table holds only its SHA-256 hash. Logging out deletes the row. Named login_sessions
-- because `sessions` already means shooting sessions.
CREATE TABLE IF NOT EXISTS login_sessions (
    token_hash text PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL
);

-- Whose session this is. Added with ALTER so a database made before accounts gets it too.
-- Sessions from before accounts have no owner (NULL), so nobody sees them until
-- backend/give_old_sessions.py hands them to someone.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id bigint REFERENCES users (id);

-- One person's sessions, newest first: the sessions list reads this index in order.
CREATE INDEX IF NOT EXISTS sessions_user_id_created_at_idx ON sessions (user_id, created_at);

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

-- The shooter's form on each shot (vision/shot_form.py). NULL when a number could not be
-- measured. Added with ALTER, not inside CREATE TABLE above, so a database made before
-- these columns existed gets them too.
ALTER TABLE shots
    ADD COLUMN IF NOT EXISTS knee_bend_deg  real,
    ADD COLUMN IF NOT EXISTS elbow_bend_deg real,
    ADD COLUMN IF NOT EXISTS arm_angle_deg  real,
    ADD COLUMN IF NOT EXISTS jump           real,
    ADD COLUMN IF NOT EXISTS flight_time_s  real;

-- Holds every column a per-session make/miss count needs, so Postgres can answer
-- from this index alone and never open the table (see docs/query-optimization.md).
CREATE INDEX IF NOT EXISTS shots_session_id_result_idx ON shots (session_id, result);

-- Makes and misses per person per month, saved so the trend chart reads 12 rows instead of
-- every shot. backend/database.py refreshes it whenever a session's shots are saved.
-- Dropped and made again on every start, so a change here (like adding user_id) reaches
-- databases that already have the old version. Making it costs the same as one refresh.
DROP MATERIALIZED VIEW IF EXISTS monthly_stats;
CREATE MATERIALIZED VIEW monthly_stats AS
SELECT sessions.user_id,
       date_trunc('month', sessions.created_at)::date AS month,
       count(*) FILTER (WHERE shots.result = 'MAKE') AS makes,
       count(*) FILTER (WHERE shots.result = 'MISS') AS misses
FROM shots
JOIN sessions ON sessions.id = shots.session_id
GROUP BY 1, 2;
