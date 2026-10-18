SELECT max(s.max_alt_ft) AS max_altitude_ft
FROM iceberg.gold.flight_summary s
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
