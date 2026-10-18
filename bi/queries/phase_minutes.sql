-- Join at flight grain before aggregation; do not multiply summary metrics.
-- Includes ground phases; this is not the same as airborne time.
SELECT p.phase,
       round(sum(p.duration_s) / 60.0, 2) AS duration_minutes
FROM iceberg.gold.flight_phases p
JOIN iceberg.gold.flight_summary s ON s.flight_id = p.flight_id
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
GROUP BY p.phase
ORDER BY min(p.phase_order)
