-- Step 4 — Gold: events -> phases -> flight summary
-- Run each statement in the Trino shell, in order. Re-running is safe:
-- CREATE OR REPLACE rebuilds each table from Silver in one atomic commit.

CREATE SCHEMA IF NOT EXISTS iceberg.gold;


-- ---------------------------------------------------------------------------
-- 1. EVENTS — the vocabulary. Four moments per flight, each with a value.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE iceberg.gold.flight_events AS
WITH
-- 4 Hz ground flag -> one row per second.
-- A second counts as airborne only if all 4 samples say "not on ground".
ground AS (
  SELECT flight_id,
         floor(t_offset_s)   AS sec,
         max(ac_ground) = 0  AS airborne
  FROM iceberg.silver.rate_4hz
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


-- ---------------------------------------------------------------------------
-- 2. PHASES — the gaps between events. Five intervals that cover every second.
--    Seconds are inclusive: [start_s, end_s], duration = end - start + 1.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE iceberg.gold.flight_phases AS
WITH b AS (
  SELECT e.flight_id,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'liftoff')        AS integer) AS liftoff_s,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'top_of_climb')   AS integer) AS toc_s,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'top_of_descent') AS integer) AS tod_s,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'touchdown')      AS integer) AS touchdown_s,
         CAST(max(f.duration_s) AS integer) - 1                                       AS last_s
  FROM iceberg.gold.flight_events e
  JOIN iceberg.silver.flights f ON f.flight_id = e.flight_id
  GROUP BY e.flight_id
),
p AS (
  SELECT flight_id, 1 AS phase_order, 'ground_out' AS phase, 0               AS start_s, liftoff_s - 1 AS end_s FROM b
  UNION ALL
  SELECT flight_id, 2 AS phase_order, 'climb'      AS phase, liftoff_s       AS start_s, toc_s - 1     AS end_s FROM b
  UNION ALL
  SELECT flight_id, 3 AS phase_order, 'cruise'     AS phase, toc_s           AS start_s, tod_s - 1     AS end_s FROM b
  UNION ALL
  SELECT flight_id, 4 AS phase_order, 'descent'    AS phase, tod_s           AS start_s, touchdown_s   AS end_s FROM b
  UNION ALL
  SELECT flight_id, 5 AS phase_order, 'ground_in'  AS phase, touchdown_s + 1 AS start_s, last_s        AS end_s FROM b
)
SELECT flight_id,
       phase_order,
       CAST(phase AS varchar)                                 AS phase,
       start_s,
       end_s,
       end_s - start_s + 1                                    AS duration_s,
       CAST('phase-v0.1' AS varchar)                          AS detector_ver,
       CAST(current_timestamp AS timestamp(6) with time zone) AS built_at
FROM p;


-- ---------------------------------------------------------------------------
-- 3. FLIGHT SUMMARY — one row per flight, built from Silver + the two above.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE iceberg.gold.flight_summary AS
WITH ev AS (
  SELECT flight_id,
         max(t_offset_s) FILTER (WHERE event = 'liftoff')   AS liftoff_s,
         max(t_offset_s) FILTER (WHERE event = 'touchdown') AS touchdown_s,
         max(value)      FILTER (WHERE event = 'touchdown') AS touchdown_peak_g
  FROM iceberg.gold.flight_events
  GROUP BY flight_id
),
ph AS (
  SELECT flight_id,
         CAST(sum(duration_s) FILTER (WHERE phase = 'cruise') AS double) / 60 AS cruise_min
  FROM iceberg.gold.flight_phases
  GROUP BY flight_id
),
alt AS (
  SELECT flight_id, max(alt_std) AS max_alt_ft
  FROM iceberg.silver.rate_1hz
  GROUP BY flight_id
)
SELECT f.flight_id,
       f.tail,
       f.aircraft_type,
       f.flight_no,
       f.origin,
       f.destination,
       f.flight_date,
       round((ev.touchdown_s - ev.liftoff_s + 1) / 60, 1)   AS airborne_min,
       round(ph.cruise_min, 1)                              AS cruise_min,
       alt.max_alt_ft,
       ev.touchdown_peak_g,
       -- PLACEHOLDER threshold: take the real limit from your FOQA event set
       ev.touchdown_peak_g >= 1.6                           AS hard_landing,
       -- answer key: our detection minus the decoder's segmentation (0 = agree)
       CAST(ev.liftoff_s   - f.dec_takeoff_s   AS integer)  AS liftoff_delta_s,
       CAST(ev.touchdown_s - f.dec_touchdown_s AS integer)  AS touchdown_delta_s,
       CAST(current_timestamp AS timestamp(6) with time zone) AS built_at
FROM iceberg.silver.flights f
JOIN ev  ON ev.flight_id  = f.flight_id
JOIN ph  ON ph.flight_id  = f.flight_id
JOIN alt ON alt.flight_id = f.flight_id;
