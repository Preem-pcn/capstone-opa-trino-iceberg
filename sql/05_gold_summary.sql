-- Step 5 — per-flight version of 04_gold.sql (summary).
-- Same logic, but for ONE flight: Dagster replaces '{flight_id}' and runs
-- the statements in order. DELETE + INSERT = replace this flight's rows.
-- Note: that's two commits, so for a moment the flight is missing. MERGE
-- would make it atomic; for the POC this is fine.

DELETE FROM iceberg.gold.flight_summary WHERE flight_id = '{flight_id}';

INSERT INTO iceberg.gold.flight_summary
WITH ev AS (
  SELECT flight_id,
         max(t_offset_s) FILTER (WHERE event = 'liftoff')   AS liftoff_s,
         max(t_offset_s) FILTER (WHERE event = 'touchdown') AS touchdown_s,
         max(value)      FILTER (WHERE event = 'touchdown') AS touchdown_peak_g
  FROM iceberg.gold.flight_events
  WHERE flight_id = '{flight_id}'
  GROUP BY flight_id
),
ph AS (
  SELECT flight_id,
         CAST(sum(duration_s) FILTER (WHERE phase = 'cruise') AS double) / 60 AS cruise_min
  FROM iceberg.gold.flight_phases
  WHERE flight_id = '{flight_id}'
  GROUP BY flight_id
),
alt AS (
  SELECT flight_id, max(alt_std) AS max_alt_ft
  FROM iceberg.silver.rate_1hz
  WHERE flight_id = '{flight_id}'
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
JOIN alt ON alt.flight_id = f.flight_id
WHERE f.flight_id = '{flight_id}';