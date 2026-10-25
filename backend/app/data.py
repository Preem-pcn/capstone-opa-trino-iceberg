"""Trino access for the pages: flights, sensors, the catalog, SQL Workspace queries, and signed
Metabase links.

Every query runs as the session role's Trino user over HTTPS with that user's password, so OPA
filters rows and masks columns before anything reaches the browser. The signed-in person goes
along as a Trino client tag, so Trino's query log shows who asked, not only which role.
The browser never chooses the Trino user. SQL Workspace text runs as that same user; OPA allows
analyst users to read only approved tables and never to write.
"""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as QueryTimeout
from datetime import date, datetime
from datetime import time as clock_time
from decimal import Decimal

import jwt
import trino
from requests.exceptions import RequestException

from . import settings

SQL_MAX_ROWS = 500
SQL_SECONDS = 30
CATALOG_SCHEMAS = ("silver", "gold")


class DataError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _secret(name: str) -> dict:
    return json.loads((settings.SECRETS_DIR / name).read_text(encoding="utf-8"))


def connect(trino_user: str, person: str):
    return trino.dbapi.connect(
        host=settings.TRINO_HOST, port=settings.TRINO_PORT, user=trino_user, catalog="iceberg",
        http_scheme="https", verify=str(settings.SECRETS_DIR / "trino-public/trino.crt"),
        auth=trino.auth.BasicAuthentication(trino_user, _secret("trino-users.json")[trino_user]),
        source="qar-backend", client_tags=[f"person:{person}"], request_timeout=20, max_attempts=1)


def query(sql: str, trino_user: str, person: str, parameters=None) -> list[dict]:
    connection = connect(trino_user, person)
    try:
        cursor = connection.cursor()
        cursor.execute(sql, parameters)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except trino.exceptions.TrinoUserError as error:
        if error.error_name == "PERMISSION_DENIED":
            raise DataError(403, "Access denied by Trino/OPA.") from None
        raise DataError(502, "The flight data query could not be completed.") from None
    except (trino.exceptions.TrinoError, RequestException):
        raise DataError(502, "Flight data is unavailable. Check the Trino service.") from None
    finally:
        connection.close()


FLIGHT_COLUMNS = """flight_id, flight_date, flight_no, aircraft_type, tail, origin, destination,
                    start_time, duration_s, decoder_version,
                    coalesce(decoder_version LIKE 'synthetic-%', false) AS is_synthetic"""
SUMMARY_COLUMNS = ["airborne_min", "cruise_min", "max_alt_ft", "touchdown_peak_g", "built_at"]


def list_flights(trino_user: str, person: str) -> dict:
    # Bounded metadata only; sensor arrays are not fetched for the listing.
    rows = query(f"SELECT {FLIGHT_COLUMNS}, count(*) OVER () AS available_count "
                 "FROM iceberg.silver.flights ORDER BY flight_date DESC,start_time DESC,flight_id LIMIT 1000",
                 trino_user, person)
    total = rows[0]["available_count"] if rows else 0
    for row in rows:
        row.pop("available_count")
    return {"flights": rows, "total": total, "truncated": total > len(rows),
            "query_identity": trino_user, "source": "iceberg.silver.flights"}


def flight_detail(flight_id: str, trino_user: str, person: str) -> dict:
    if not flight_id or len(flight_id) > 240:
        raise DataError(400, "A valid flight ID is required.")
    rows = query(f"SELECT {FLIGHT_COLUMNS}, recording, fap, dec_takeoff_s, dec_touchdown_s "
                 "FROM iceberg.silver.flights WHERE flight_id = ?", trino_user, person, [flight_id])
    if not rows:
        raise DataError(404, "Flight not found or not visible to this identity.")
    # OPA hides denied columns (touchdown_peak_g for Operations) from information_schema,
    # so select only what this user may read instead of failing the whole summary.
    visible = {row["column_name"] for row in query(
        "SELECT column_name FROM iceberg.information_schema.columns "
        "WHERE table_schema = 'gold' AND table_name = 'flight_summary'", trino_user, person)}
    columns = [column for column in SUMMARY_COLUMNS if column in visible]
    summary = query(f"SELECT {','.join(columns)} FROM iceberg.gold.flight_summary WHERE flight_id = ?",
                    trino_user, person, [flight_id]) if columns else []
    phases = query("SELECT phase_order,phase,start_s,end_s,duration_s,detector_ver "
                   "FROM iceberg.gold.flight_phases WHERE flight_id = ? ORDER BY phase_order",
                   trino_user, person, [flight_id])
    events = query("SELECT event,t_offset_s,ts,value,unit,detector_ver "
                   "FROM iceberg.gold.flight_events WHERE flight_id = ? ORDER BY t_offset_s",
                   trino_user, person, [flight_id])
    return {"flight": rows[0], "summary": summary[0] if summary else None, "phases": phases,
            "events": events, "query_identity": trino_user}


def dashboard_link(role: str) -> tuple[int, str]:
    """The role's Metabase dashboard id and a static-embed URL for it.

    The HS256 token names the dashboard and nothing else (no user, no role); Metabase checks it
    with the shared embedding secret that setup_bi_demo.py wrote to metabase-embed.json.
    """
    try:
        config = _secret("metabase-embed.json")
        dashboard_id = int(config["dashboards"][role])
    except (FileNotFoundError, KeyError, ValueError):
        raise DataError(503, "Reports are not available yet. Please contact your administrator.") from None
    now = int(time.time())
    token = jwt.encode({"resource": {"dashboard": dashboard_id}, "params": {}, "iat": now,
                        "exp": now + settings.EMBED_SECONDS}, config["secret"], algorithm="HS256")
    return dashboard_id, config["metabase_url"].rstrip("/") + "/embed/dashboard/" + token + "#bordered=false&titled=false"


def plain(value):
    """A JSON-safe cell: Trino returns dates, decimals, arrays, maps and bytes; NaN is not JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, (datetime, date, clock_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return plain(float(value))
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    return str(value)


def run_sql(sql: str, trino_user: str, person: str) -> dict:
    """One statement typed in the SQL Workspace, run as the role's Trino user.

    OPA decides what it may read and refuses writes. The backend only caps the result at
    SQL_MAX_ROWS and the run time at SQL_SECONDS, cancelling the query in Trino past either.
    (OPA does not let analyst users set Trino session properties, so the time limit lives here.)
    """
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise DataError(400, "Query is empty. Write a SELECT or pick a saved example.")
    if len(text) > 20_000:
        raise DataError(400, "Query is too long.")
    started = time.monotonic()
    connection = connect(trino_user, person)
    cursor = connection.cursor()

    def execute():
        cursor.execute(text)
        return cursor.fetchmany(SQL_MAX_ROWS + 1), cursor.description or []

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        rows, description = pool.submit(execute).result(timeout=SQL_SECONDS)
        if len(rows) > SQL_MAX_ROWS:
            cursor.cancel()   # stop Trino producing rows nobody will see
        return {"columns": [{"name": column[0], "type": column[1]} for column in description],
                "rows": [[plain(value) for value in row] for row in rows[:SQL_MAX_ROWS]],
                "truncated": len(rows) > SQL_MAX_ROWS, "ms": round((time.monotonic() - started) * 1000),
                "query_identity": trino_user}
    except QueryTimeout:
        cursor.cancel()
        raise DataError(408, f"The query ran longer than {SQL_SECONDS} s and was cancelled.") from None
    except trino.exceptions.TrinoUserError as error:
        # Trino's own message: "Access Denied: …", "line 1:8: Column 'x' cannot be resolved", …
        raise DataError(403 if error.error_name == "PERMISSION_DENIED" else 400, error.message) from None
    except (trino.exceptions.TrinoError, RequestException):
        raise DataError(502, "Trino could not run the query. Check the Trino service.") from None
    finally:
        pool.shutdown(wait=False)
        connection.close()


def catalog(trino_user: str, person: str) -> dict:
    """Tables and columns this role may see. OPA filters information_schema the same way it
    filters queries, so denied tables and columns do not appear."""
    schemas = ", ".join(f"'{schema}'" for schema in CATALOG_SCHEMAS)
    rows = query("SELECT table_schema, table_name, column_name, data_type FROM iceberg.information_schema.columns "
                 f"WHERE table_schema IN ({schemas}) ORDER BY table_schema, table_name, ordinal_position",
                 trino_user, person)
    tables: dict[str, list[dict]] = {}
    for row in rows:
        tables.setdefault(f"iceberg.{row['table_schema']}.{row['table_name']}", []).append(
            {"name": row["column_name"], "type": row["data_type"]})
    return {"tables": tables, "query_identity": trino_user}


# One value per second from the native-rate Silver tables: the sample at the start of each second
# (min_by over the offset), plus the peak vertical acceleration within the second.
SENSOR_SQL = """
WITH r1 AS (SELECT CAST(floor(t_offset_s) AS integer) AS t, min_by(alt_std, t_offset_s) AS alt, min_by(ias, t_offset_s) AS ias
            FROM iceberg.silver.rate_1hz WHERE flight_id = ? GROUP BY 1),
     r4 AS (SELECT CAST(floor(t_offset_s) AS integer) AS t, min_by(gs, t_offset_s) AS gs, min_by(heading, t_offset_s) AS heading,
                   min_by(pitch_ang_cap, t_offset_s) AS pitch, min_by(rollangle_cpt, t_offset_s) AS roll
            FROM iceberg.silver.rate_4hz WHERE flight_id = ? GROUP BY 1),
     r8 AS (SELECT CAST(floor(t_offset_s) AS integer) AS t, min_by(vrtg, t_offset_s) AS vrtg, max(vrtg) AS vrtg_max
            FROM iceberg.silver.rate_8hz WHERE flight_id = ? GROUP BY 1)
SELECT coalesce(r1.t, r4.t, r8.t) AS t, alt, ias, gs, heading, pitch, roll, vrtg, vrtg_max
FROM r1 FULL JOIN r4 ON r4.t = r1.t FULL JOIN r8 ON r8.t = coalesce(r1.t, r4.t)
ORDER BY 1"""
SENSOR_DIGITS = {"alt": 0, "ias": 1, "gs": 1, "heading": 2, "pitch": 4, "roll": 4, "vrtg": 4, "vrtg_max": 4}


def flight_sensors(flight_id: str, trino_user: str, person: str) -> dict:
    """Sensor series for the cockpit and charts, aligned on whole seconds from 0; a missing sample is null."""
    if not flight_id or len(flight_id) > 240:
        raise DataError(400, "A valid flight ID is required.")
    rows = [row for row in query(SENSOR_SQL, trino_user, person, [flight_id] * 3) if row["t"] is not None and row["t"] >= 0]
    if not rows:
        raise DataError(404, "No sensor data for this flight, or it is not visible to this identity.")
    seconds = max(row["t"] for row in rows) + 1
    series = {key: [None] * seconds for key in SENSOR_DIGITS}
    for row in rows:
        for key, digits in SENSOR_DIGITS.items():
            value = plain(row[key])
            series[key][row["t"]] = None if value is None else round(value, digits)
    return {"seconds": seconds, "series": series, "query_identity": trino_user,
            "source": {"alt": "rate_1hz.alt_std", "ias": "rate_1hz.ias", "gs": "rate_4hz.gs",
                       "heading": "rate_4hz.heading", "pitch": "rate_4hz.pitch_ang_cap",
                       "roll": "rate_4hz.rollangle_cpt", "vrtg": "rate_8hz.vrtg"}}
