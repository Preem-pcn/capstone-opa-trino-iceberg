"""Create the OPA test fixtures in this stack and check what each role sees in them.

python scripts/load_opa_fixtures.py           # create (if missing) and check
python scripts/load_opa_fixtures.py --check   # check only

Three synthetic flights, not QAR recordings: the same rows and tables verify_opa.py creates in the
pipeline stack, here in iceberg.opa_demo_silver / opa_demo_gold of the app stack. They are written
through Trino as the privileged `dagster` user. The web app's OPA fixtures page and SQL Workspace
query them live as the signed-in role.
"""
import argparse

import trino

from bi_demo_settings import trino_connection

SILVER, GOLD = "iceberg.opa_demo_silver", "iceberg.opa_demo_gold"
STATEMENTS = [
    f"CREATE SCHEMA IF NOT EXISTS {SILVER}",
    f"CREATE SCHEMA IF NOT EXISTS {GOLD}",
    f"""CREATE TABLE IF NOT EXISTS {SILVER}.flights AS
        SELECT * FROM (VALUES
          ('HS-THJ_DEMO_01', 'HS-THJ', 'VTBS', 'OPKC', 'TG_DEMO_01', 'demo_01', 'raw/demo_01'),
          ('HS-THE_DEMO_02', 'HS-THE', 'RKSI', 'VTBS', 'TG_DEMO_02', 'demo_02', 'raw/demo_02'),
          ('HS-TKN_DEMO_03', 'HS-TKN', 'EGLL', 'ESSA', 'TG_DEMO_03', 'demo_03', 'raw/demo_03')
        ) AS t(flight_id, tail, origin, destination, flight_no, recording, source_file)""",
    f"""CREATE TABLE IF NOT EXISTS {SILVER}.rate_1hz AS
        SELECT flight_id, 0.0 AS t_offset_s, 1000.0 AS alt_std FROM {SILVER}.flights""",
    f"""CREATE TABLE IF NOT EXISTS {GOLD}.flight_summary AS
        SELECT flight_id, tail, origin, destination, flight_no, 1.2 AS touchdown_peak_g FROM {SILVER}.flights""",
    f"""CREATE TABLE IF NOT EXISTS {GOLD}.flight_events AS
        SELECT flight_id, 'touchdown' AS event, 120.0 AS t_offset_s FROM {SILVER}.flights""",
    f"""CREATE TABLE IF NOT EXISTS {GOLD}.flight_phases AS
        SELECT flight_id, 'cruise' AS phase, 60.0 AS duration_s FROM {SILVER}.flights""",
    # Not on the OPA allowlist: analysts must not see it, even in SHOW TABLES.
    f"CREATE TABLE IF NOT EXISTS {SILVER}.unlisted_demo AS SELECT * FROM {SILVER}.flights",
]
# Rows each role sees, and the columns OPA masks to REDACTED for it (opa/trino.rego).
EXPECTED = {
    "safety_analyst": (3, {"recording", "source_file"}),
    "operations_analyst": (2, {"tail", "recording", "source_file"}),
    "engineering_analyst": (1, {"flight_no", "origin", "destination"}),
}


def run(user, sql):
    connection = trino_connection(user)
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        return [dict(zip([c[0] for c in cursor.description], row)) for row in rows]
    finally:
        connection.close()


def denied(user, sql):
    try:
        run(user, sql)
    except trino.exceptions.TrinoUserError as error:
        return error.error_name == "PERMISSION_DENIED"
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the existing fixtures without creating them")
    if not parser.parse_args().check:
        for statement in STATEMENTS:
            run("dagster", statement)
    for user, (count, masked) in EXPECTED.items():
        rows = run(user, f"SELECT * FROM {SILVER}.flights")
        assert len(rows) == count, f"{user} sees {len(rows)} fixture rows, expected {count}"
        shown = {column for row in rows for column, value in row.items() if value == "REDACTED"}
        assert shown == masked, f"{user}: REDACTED columns {sorted(shown)}, expected {sorted(masked)}"
        print(f"PASS {user}: {count} fixture row(s), masked {', '.join(sorted(masked))}", flush=True)
    assert denied("operations_analyst", f"SELECT touchdown_peak_g FROM {GOLD}.flight_summary")
    assert denied("blocked_user", f"SELECT count(*) FROM {SILVER}.flights")
    assert denied("safety_analyst", f"SELECT * FROM {SILVER}.unlisted_demo")
    print("PASS denied: touchdown_peak_g for operations, every query for blocked_user, unlisted tables", flush=True)


if __name__ == "__main__":
    main()
