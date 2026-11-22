-- Fake data for measuring queries: 20,000 sessions over one year, 50 shots each (1M shots).
-- Load it into its own database, never the real one. Steps are in docs/query-optimization.md.

-- One session about every 26 minutes, from 2025-12-01 to 2026-11-30.
INSERT INTO sessions (id, original_filename, input_path, status, created_at, completed_at)
SELECT 'bench-' || n,
       'clip-' || n || '.mov',
       '/bench/clip-' || n || '.mov',
       'COMPLETED',
       timestamptz '2025-12-01 00:00+00' + (n - 1) * interval '365 days' / 20000,
       timestamptz '2025-12-01 00:10+00' + (n - 1) * interval '365 days' / 20000
FROM generate_series(1, 20000) AS n;

-- The make rate climbs from 40% to 55% over the year, so the monthly trend shows growth.
INSERT INTO shots (session_id, shot_number, result, timestamp_s)
SELECT 'bench-' || s,
       shot,
       CASE WHEN random() < 0.40 + 0.15 * s / 20000.0 THEN 'MAKE' ELSE 'MISS' END,
       shot * 6.0
FROM generate_series(1, 20000) AS s, generate_series(1, 50) AS shot
ORDER BY s, shot;

REFRESH MATERIALIZED VIEW monthly_stats;

-- Update the planner's row counts so EXPLAIN picks plans for 1M rows, not an empty table.
VACUUM ANALYZE sessions, shots;
