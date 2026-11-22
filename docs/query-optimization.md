# Query optimization on 1M shots

Two queries the app runs, measured on 1,000,000 shots before and after a fix.

| Query | Fix | Before | After | Speedup |
|---|---|---|---|---|
| One month's sessions with makes, misses, shooting % | Composite index `shots (session_id, result)` | 62.8 ms | 17.3 ms | 3.6x |
| Month-by-month trend (all shots) | Summary table (materialized view `monthly_stats`) | 234.8 ms | 0.54 ms | about 430x |

Times are the median of 7 runs timed by `psql` (`\timing`), which is what a client waits for.
`EXPLAIN ANALYZE` reports higher numbers for the "before" plans, because timing every row
adds its own overhead. Its numbers are in each section below.

## Setup

- Data: `db/seed.sql` makes 20,000 sessions spread over one year (2025-12-01 to 2026-11-30),
  50 shots each, so 1,000,000 shots. The make rate climbs from 40% to 55% over the year.
- Postgres 17.12 in Docker (`docker-compose.yml`) on an Apple M5 Pro laptop.
- Every page was already in memory (`Buffers: shared hit` only), so these are warm-cache
  numbers. Each measurement is the median of 7 runs.
- Tables: `shots` is 65 MB, `sessions` is 2 MB.

## 1. One month's sessions: composite index

`GET /api/sessions?month=2026-03` runs `list_sessions()` in `backend/database.py`:

```sql
SELECT sessions.id, sessions.original_filename, sessions.status, sessions.created_at,
       count(shots.result) FILTER (WHERE shots.result = 'MAKE') AS makes,
       count(shots.result) FILTER (WHERE shots.result = 'MISS') AS misses
FROM sessions
LEFT JOIN shots ON shots.session_id = sessions.id
WHERE sessions.created_at >= '2026-03-01' AND sessions.created_at < '2026-04-01'
GROUP BY sessions.id
ORDER BY sessions.created_at DESC;
```

March has 1,699 sessions and 84,950 shots, which is 8.5% of the table.

### Before: reads all 1M shots

```
Hash Right Join  (actual time=26.413..109.871 rows=84950 loops=1)
  Hash Cond: (shots.session_id = sessions.id)
  ->  Seq Scan on shots  (actual time=0.005..42.512 rows=1000000 loops=1)
  ->  Hash
        ->  Seq Scan on sessions  (actual time=0.240..1.002 rows=1699 loops=1)
              Rows Removed by Filter: 18301
Execution Time: 120.855 ms        (median of 7: 121.7 ms)
```

Postgres reads every shot and matches each one against March's sessions in a hash table.
It keeps only 84,950 of the 1,000,000 rows.

`shots` already had an index starting with `session_id`, the one behind
`UNIQUE (session_id, shot_number)`. Postgres skipped it because it holds `shot_number`,
not `result`, so each of the 84,950 matches would also need a trip to the table to read
`result`. It judged one straight read of the whole table to be cheaper.

### After: reads only March's shots, from the index alone

```sql
CREATE INDEX shots_session_id_result_idx ON shots (session_id, result);
```

```
Nested Loop Left Join  (actual time=0.238..15.054 rows=84950 loops=1)
  ->  Seq Scan on sessions  (actual time=0.227..0.967 rows=1699 loops=1)
        Rows Removed by Filter: 18301
  ->  Index Only Scan using shots_session_id_result_idx on shots
        (actual time=0.002..0.004 rows=50 loops=1699)
        Index Cond: (session_id = sessions.id)
        Heap Fetches: 0
Execution Time: 25.827 ms         (median of 7: 25.8 ms)
```

For each of March's 1,699 sessions, Postgres looks up its 50 shots in the new index.
The index holds both columns the query needs, so it never opens the table.
That's what "Index Only Scan" and "Heap Fetches: 0" mean.
It handles 84,950 rows instead of 1,000,000.

Two details make it work:

- **The query counts `shots.result`, not `shots.id`.** Before, the query used `count(shots.id)`,
  and `id` is not in the index, so Postgres had to open the table anyway and the plan stayed
  slow. Counting `result` gives the same answer, because `result` is never NULL.
- **`VACUUM` has to run after big loads.** An index-only scan can skip the table only for
  pages Postgres has marked as fully visible, and `VACUUM` is what marks them. Autovacuum
  does this on its own over time.

### What didn't help: an index on the date

The obvious first idea was `CREATE INDEX ON sessions (created_at)`, to find March quickly.
Measured with `EXPLAIN ANALYZE`, it went from 121.7 ms to 121.4 ms, no real change.
`sessions` is only 2 MB, so scanning all 20,000 rows takes about 1 ms. The slow part was
reading 1M shots, and this index doesn't touch that. It was not added.

### What the index costs

- **Disk:** 8 MB. That's small, because Postgres stores each repeated `(session_id, result)`
  pair once (B-tree deduplication). The existing `(session_id, shot_number)` index is 42 MB.
- **Writes:** bulk-inserting all 1M shots took 10.0 s with the index and 7.6 s without it
  (one run each). A real upload adds only a few dozen shots, so the extra time per upload is tiny.

## 2. Month-by-month trend: summary table

`GET /api/stats` returns makes, misses and shooting % for each month, plus overall.
Computed from the raw tables, it has to touch every shot:

```sql
SELECT date_trunc('month', sessions.created_at)::date AS month,
       count(*) FILTER (WHERE shots.result = 'MAKE') AS makes,
       count(*) FILTER (WHERE shots.result = 'MISS') AS misses
FROM shots
JOIN sessions ON sessions.id = shots.session_id
GROUP BY ROLLUP (date_trunc('month', sessions.created_at))
ORDER BY month NULLS LAST;
```

### Why no index can fix this

An index helps a query skip rows. This query needs all 1,000,000 shots, so there is
nothing to skip. With the composite index above in place, it still took 234 ms.

```
Hash Join  (actual time=3.204..230.081 rows=1000000 loops=1)
  ->  Seq Scan on shots  (actual time=0.004..43.539 rows=1000000 loops=1)
  ->  Hash
        ->  Seq Scan on sessions  (actual time=0.004..1.442 rows=20000 loops=1)
Execution Time: 341.886 ms        (median of 7: 343.6 ms)
Buffers: shared hit=8594          (8,594 pages of 8 KB = 67 MB read)
```

### After: count once, save the answer

`db/schema.sql` adds a materialized view: a query whose result Postgres stores like a table.

```sql
CREATE MATERIALIZED VIEW monthly_stats AS
SELECT date_trunc('month', sessions.created_at)::date AS month,
       count(*) FILTER (WHERE shots.result = 'MAKE') AS makes,
       count(*) FILTER (WHERE shots.result = 'MISS') AS misses
FROM shots
JOIN sessions ON sessions.id = shots.session_id
GROUP BY 1;
```

`get_stats()` now reads its 12 rows instead of 1M shots:

```
Seq Scan on monthly_stats  (actual time=0.003..0.003 rows=12 loops=1)
Execution Time: 0.091 ms          (median of 7: 0.072 ms)
Buffers: shared hit=4             (4 pages)
```

### What the summary table costs

- **It has to be kept up to date.** `mark_completed()` in `backend/database.py` runs
  `REFRESH MATERIALIZED VIEW monthly_stats` in the same transaction that saves a session's
  shots, so the stats always match the shots.
- **Each refresh recounts every shot**, about 98 ms at 1M shots (median of 5). That runs once
  per upload, after video processing that takes minutes, so it's not noticeable. It grows with
  the table, though. At much larger sizes the next step would be keeping running totals
  per month (adding only the new session's shots) instead of recounting everything.
- **Stats requests wait during a refresh.** A plain refresh locks the view until it finishes,
  so a stats request arriving at that moment waits up to about 100 ms.
  `REFRESH ... CONCURRENTLY` avoids that, but it needs a unique index on the view and
  is slower. Not worth it at this size.

## Reproduce it

Start Postgres and make a separate database, so the fake rows never mix with real data:

```bash
docker compose up -d db
```

```bash
docker compose exec -T db psql -U courtiq -c "CREATE DATABASE courtiq_bench"
```

```bash
docker compose exec -T db psql -U courtiq -d courtiq_bench < db/schema.sql
```

```bash
docker compose exec -T db psql -U courtiq -d courtiq_bench < db/seed.sql
```

Open a shell on it:

```bash
docker compose exec db psql -U courtiq -d courtiq_bench
```

Inside `psql`, turn on timing and run the queries above, with `EXPLAIN (ANALYZE, BUFFERS)`
in front to see the plan:

```sql
\timing on
```

The schema creates the index, so you start with the "after" plan. For the "before" plan,
drop it, update visibility and statistics, and run the month query again:

```sql
DROP INDEX shots_session_id_result_idx;
VACUUM ANALYZE shots;
```

Then put it back:

```sql
CREATE INDEX shots_session_id_result_idx ON shots (session_id, result);
VACUUM ANALYZE shots;
```

Month boundaries are in UTC, which is the database's time zone in Docker and on RDS by default.
