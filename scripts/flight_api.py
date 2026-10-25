"""Fixed SELECT endpoints for Silver flights and their Gold details.

Every query runs as the caller's Trino user, so OPA filters and masks it.
"""
import trino
from requests.exceptions import RequestException
from bi_demo_settings import trino_connection


class FlightAPIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def query(sql, user, parameters=None):
    connection = trino_connection(user, request_timeout=20, max_attempts=1)
    try:
        cursor = connection.cursor()
        cursor.execute(sql, parameters)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except trino.exceptions.TrinoUserError as error:
        if error.error_name == "PERMISSION_DENIED":
            raise FlightAPIError(403, "Access denied by Trino/OPA.") from None
        raise FlightAPIError(502, "The flight data query could not be completed.") from None
    except (trino.exceptions.TrinoError, RequestException):
        raise FlightAPIError(502, "Flight data is unavailable. Check the capstone Trino service.") from None
    finally:
        connection.close()


FLIGHT_COLUMNS = """flight_id, flight_date, flight_no, aircraft_type, tail, origin, destination,
                    start_time, duration_s, decoder_version,
                    coalesce(decoder_version LIKE 'synthetic-%', false) AS is_synthetic"""
SUMMARY_COLUMNS = ["airborne_min", "cruise_min", "max_alt_ft", "touchdown_peak_g", "built_at"]


def list_flights(user):
    # Bounded metadata only; sensor arrays are not fetched for the listing.
    rows = query(f"SELECT {FLIGHT_COLUMNS}, count(*) OVER () AS available_count "
                 "FROM iceberg.silver.flights ORDER BY flight_date DESC,start_time DESC,flight_id LIMIT 1000", user)
    total = rows[0]["available_count"] if rows else 0
    for row in rows:
        row.pop("available_count")
    return {"flights": rows, "total": total, "truncated": total > len(rows),
            "query_identity": user, "source": "iceberg.silver.flights"}


def flight_detail(flight_id, user):
    if not flight_id or len(flight_id) > 240:
        raise FlightAPIError(400, "A valid flight ID is required.")
    rows = query(f"SELECT {FLIGHT_COLUMNS}, recording, fap, dec_takeoff_s, dec_touchdown_s "
                 "FROM iceberg.silver.flights WHERE flight_id = ?", user, [flight_id])
    if not rows:
        raise FlightAPIError(404, "Flight not found or not visible to this identity.")
    # OPA hides denied columns (touchdown_peak_g for Operations) from information_schema,
    # so select only what this user may read instead of failing the whole summary.
    visible = {row["column_name"] for row in query(
        "SELECT column_name FROM iceberg.information_schema.columns "
        "WHERE table_schema = 'gold' AND table_name = 'flight_summary'", user)}
    columns = [column for column in SUMMARY_COLUMNS if column in visible]
    summary = query(f"SELECT {','.join(columns)} FROM iceberg.gold.flight_summary WHERE flight_id = ?",
                    user, [flight_id]) if columns else []
    phases = query("SELECT phase_order,phase,start_s,end_s,duration_s,detector_ver "
                   "FROM iceberg.gold.flight_phases WHERE flight_id = ? ORDER BY phase_order", user, [flight_id])
    events = query("SELECT event,t_offset_s,ts,value,unit,detector_ver "
                   "FROM iceberg.gold.flight_events WHERE flight_id = ? ORDER BY t_offset_s", user, [flight_id])
    return {"flight": rows[0], "summary": summary[0] if summary else None, "phases": phases,
            "events": events, "query_identity": user}
