SELECT count(*) AS flight_count
FROM iceberg.gold.flight_summary s
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
