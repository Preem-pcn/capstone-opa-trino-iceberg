-- Step 4 — Gold quality gates. Each query should return ZERO rows.
-- A row back means that flight failed the check.

-- Gate 1: phases cover every second of the recording, exactly once, none empty.
SELECT p.flight_id,
       sum(p.duration_s)  AS phase_seconds,
       max(f.duration_s)  AS recording_seconds,
       min(p.duration_s)  AS shortest_phase
FROM iceberg.gold.flight_phases p
JOIN iceberg.silver.flights f ON f.flight_id = p.flight_id
GROUP BY p.flight_id
HAVING sum(p.duration_s) <> max(f.duration_s)
    OR min(p.duration_s) <= 0
    OR count(*) <> 5;

-- Gate 2: events happen in the right order.
SELECT flight_id
FROM iceberg.gold.flight_events
GROUP BY flight_id
HAVING NOT (
      max(t_offset_s) FILTER (WHERE event = 'liftoff')
    < max(t_offset_s) FILTER (WHERE event = 'top_of_climb')
  AND max(t_offset_s) FILTER (WHERE event = 'top_of_climb')
    < max(t_offset_s) FILTER (WHERE event = 'top_of_descent')
  AND max(t_offset_s) FILTER (WHERE event = 'top_of_descent')
    < max(t_offset_s) FILTER (WHERE event = 'touchdown'))
  OR count(*) <> 4;

-- Gate 3: answer key. Our lift-off and touchdown agree with the decoder's
-- segmentation to within 1 second.
SELECT flight_id, liftoff_delta_s, touchdown_delta_s
FROM iceberg.gold.flight_summary
WHERE abs(liftoff_delta_s) > 1
   OR abs(touchdown_delta_s) > 1;
