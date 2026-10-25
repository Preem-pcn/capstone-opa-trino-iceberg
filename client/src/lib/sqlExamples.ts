// Statements executed by the backend as the signed-in role. No fixture identity overrides.
export const SQL_EXAMPLES = [
  { k: 'flights', name: 'Flights visible to my role', sql:
`SELECT flight_id, tail, flight_no, origin, destination, flight_date
FROM iceberg.silver.flights
ORDER BY flight_date DESC
LIMIT 100;` },
  { k: 'summary', name: 'Gold flight summaries', sql:
`SELECT flight_id, airborne_min, cruise_min, max_alt_ft
FROM iceberg.gold.flight_summary
LIMIT 100;` },
  { k: 'phases', name: 'Gold flight phases', sql:
`SELECT flight_id, phase_order, phase, start_s, end_s, duration_s
FROM iceberg.gold.flight_phases
ORDER BY flight_id, phase_order
LIMIT 100;` },
  { k: 'events', name: 'Gold flight events', sql:
`SELECT flight_id, event, t_offset_s, ts
FROM iceberg.gold.flight_events
ORDER BY flight_id, t_offset_s
LIMIT 100;` },
];
