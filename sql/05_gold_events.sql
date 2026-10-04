-- Step 5 — per-flight version of 04_gold.sql (events).
-- Same logic, but for ONE flight: Dagster replaces '{flight_id}' and runs
-- the statements in order. DELETE + INSERT = replace this flight's rows.
-- Note: that's two commits, so for a moment the flight is missing. MERGE
-- would make it atomic; for the POC this is fine.

DELETE FROM iceberg.gold.flight_events WHERE flight_id = '{flight_id}';

INSERT INTO iceberg.gold.flight_events
WITH
-- 4 Hz ground flag -> one row per second.
-- A second counts as airborne only if all 4 samples say "not on ground".
ground AS (
  SELECT flight_id,
         floor(t_offset_s)   AS sec,
         max(ac_ground) = 0  AS airborne
  FROM iceberg.silver.rate_4hz
  WHERE flight_id = '{flight_id}'
  GROUP BY flight_id, floor(t_offset_s)
),
-- One row per second: pressure altitude (1 Hz) + the ground flag.
-- alt_change_60s = altitude 30 s later minus 30 s earlier: near 0 means level flight.
seconds AS (
  SELECT h.flight_id,
         h.t_offset_s AS sec,
         h.ts,
         h.alt_std,
         g.airborne,
         lead(h.alt_std, 30) OVER (PARTITION BY h.flight_id ORDER BY h.t_offset_s)
       - lag(h.alt_std, 30)  OVER (PARTITION BY h.flight_id ORDER BY h.t_offset_s) AS alt_change_60s
  FROM iceberg.silver.rate_1hz h
  JOIN ground g ON g.flight_id = h.flight_id AND g.sec = h.t_offset_s
  WHERE h.flight_id = '{flight_id}'
),
-- Level flight above 20,000 ft, second by second.
flags AS (
  SELECT flight_id, sec, airborne,
         coalesce(airborne AND alt_std >= 20000 AND abs(alt_change_60s) < 300, false) AS level
  FROM seconds
),
-- Gaps-and-islands: consecutive seconds with the same flag get the same run_id
-- (the two row numbers grow together inside a run, so their difference is constant).
runs AS (
  SELECT flight_id, sec, level,
         row_number() OVER (PARTITION BY flight_id ORDER BY sec)
       - row_number() OVER (PARTITION BY flight_id, level ORDER BY sec) AS run_id
  FROM flags
),
-- Only level runs lasting 5+ minutes count as cruise. A slow climb that is
-- briefly "nearly level" doesn't qualify (debounce).
cruise_runs AS (
  SELECT flight_id, min(sec) AS run_start, max(sec) AS run_end
  FROM runs
  WHERE level
  GROUP BY flight_id, run_id
  HAVING count(*) >= 300
),
-- Per flight: when each of the four events happens.
bounds AS (
  SELECT s.flight_id,
         min(s.sec) FILTER (WHERE s.airborne) AS liftoff_s,    -- first fully airborne second
         max(s.sec) FILTER (WHERE s.airborne) AS touchdown_s,  -- last fully airborne second (decoder's convention)
         max(c.toc_s)                         AS toc_s,        -- first second of cruise
         max(c.tod_s)                         AS tod_s         -- first second of descent
  FROM seconds s
  JOIN (SELECT flight_id, min(run_start) AS toc_s, max(run_end) + 1 AS tod_s
        FROM cruise_runs GROUP BY flight_id) c
    ON c.flight_id = s.flight_id
  GROUP BY s.flight_id
),
-- Peak vertical g around touchdown (8 Hz). The window starts 8 s early because
-- the ground flag switches a few seconds AFTER the wheels actually hit.
touchdown_g AS (
  SELECT b.flight_id, max(e.vrtg) AS peak_g
  FROM bounds b
  JOIN iceberg.silver.rate_8hz e
    ON e.flight_id = b.flight_id
   AND e.t_offset_s BETWEEN b.touchdown_s - 8 AND b.touchdown_s + 4
  WHERE e.flight_id = '{flight_id}'
  GROUP BY b.flight_id
),
-- One row per (flight, event).
ev AS (
  SELECT flight_id, 'liftoff'        AS event, liftoff_s   AS sec FROM bounds
  UNION ALL
  SELECT flight_id, 'top_of_climb'   AS event, toc_s       AS sec FROM bounds
  UNION ALL
  SELECT flight_id, 'top_of_descent' AS event, tod_s       AS sec FROM bounds
  UNION ALL
  SELECT flight_id, 'touchdown'      AS event, touchdown_s AS sec FROM bounds
)
SELECT ev.flight_id,
       CAST(ev.event AS varchar) AS event,
       ev.sec                    AS t_offset_s,
       s.ts,
       CASE WHEN ev.event = 'touchdown' THEN g.peak_g ELSE s.alt_std END AS value,
       CAST(CASE WHEN ev.event = 'touchdown' THEN 'g, peak from -8 s to +4 s'
                 ELSE 'ft, pressure altitude' END AS varchar)            AS unit,
       CAST('events-v0.1' AS varchar)                                    AS detector_ver,
       CAST(current_timestamp AS timestamp(6) with time zone)            AS built_at
FROM ev
JOIN seconds s           ON s.flight_id = ev.flight_id AND s.sec = ev.sec
LEFT JOIN touchdown_g g  ON g.flight_id = ev.flight_id;