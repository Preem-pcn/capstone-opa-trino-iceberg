-- Values have different units. Display as a table, not one mixed-unit chart.
SELECT s.flight_date,
       substr(lower(to_hex(sha256(to_utf8(e.flight_id)))), 1, 12) AS flight_reference,
       s.aircraft_type,
       e.event,
       e.t_offset_s AS seconds_from_recording_start,
       e.ts AS event_time,
       round(e.value, 3) AS event_value,
       e.unit,
       e.detector_ver
FROM iceberg.gold.flight_events e
JOIN iceberg.gold.flight_summary s ON s.flight_id = e.flight_id
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
ORDER BY s.flight_date DESC, e.flight_id, e.t_offset_s
LIMIT 200
