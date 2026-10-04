-- Step 5 — per-flight version of 04_gold.sql (phases).
-- Same logic, but for ONE flight: Dagster replaces '{flight_id}' and runs
-- the statements in order. DELETE + INSERT = replace this flight's rows.
-- Note: that's two commits, so for a moment the flight is missing. MERGE
-- would make it atomic; for the POC this is fine.

DELETE FROM iceberg.gold.flight_phases WHERE flight_id = '{flight_id}';

INSERT INTO iceberg.gold.flight_phases
WITH b AS (
  SELECT e.flight_id,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'liftoff')        AS integer) AS liftoff_s,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'top_of_climb')   AS integer) AS toc_s,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'top_of_descent') AS integer) AS tod_s,
         CAST(max(e.t_offset_s) FILTER (WHERE e.event = 'touchdown')      AS integer) AS touchdown_s,
         CAST(max(f.duration_s) AS integer) - 1                                       AS last_s
  FROM iceberg.gold.flight_events e
  JOIN iceberg.silver.flights f ON f.flight_id = e.flight_id
  WHERE e.flight_id = '{flight_id}'
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