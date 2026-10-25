-- data_source reads silver.flights.decoder_version: flight_id is pseudonymized for Operations.
SELECT s.flight_date,
       substr(lower(to_hex(sha256(to_utf8(s.flight_id)))), 1, 12) AS flight_reference,
       s.aircraft_type,
       CASE WHEN f.decoder_version LIKE 'synthetic-%' THEN 'Synthetic demo' ELSE 'Decoded recording' END AS data_source,
       s.origin,
       s.destination,
       s.airborne_min,
       s.cruise_min,
       s.max_alt_ft,
       round(s.touchdown_peak_g, 3) AS touchdown_peak_g,
       s.built_at AS gold_built_at
FROM iceberg.gold.flight_summary s
JOIN iceberg.silver.flights f ON f.flight_id = s.flight_id
WHERE TRUE
[[AND s.flight_date = {{flight_date}}]]
[[AND s.aircraft_type = {{aircraft_type}}]]
ORDER BY s.flight_date DESC, s.aircraft_type, s.flight_id
LIMIT 200
