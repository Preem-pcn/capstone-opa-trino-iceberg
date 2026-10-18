SELECT round(sum(s.airborne_min), 1) AS airborne_minutes
FROM iceberg.gold.flight_summary s
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
