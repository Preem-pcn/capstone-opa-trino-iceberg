SELECT concat(s.origin, ' → ', s.destination) AS route,
       count(*) AS flight_count
FROM iceberg.gold.flight_summary s
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
GROUP BY s.origin, s.destination
-- Fixed category order matches the Gaussian-weighted demo route configuration.
ORDER BY CASE concat(s.origin, ' → ', s.destination)
    WHEN 'EGLL → ESSA' THEN 1
    WHEN 'VTBS → WSSS' THEN 2
    WHEN 'VHHH → VTBS' THEN 3
    WHEN 'VTBS → OPKC' THEN 4
    WHEN 'RKSI → VTBS' THEN 5
    WHEN 'VTBS → RKSI' THEN 6
    WHEN 'VTBS → RJAA' THEN 7
    WHEN 'ESSA → VTBS' THEN 8
    WHEN 'VTBS → YSSY' THEN 9
    ELSE 10 END, route
