"""Load this checkout's decoded recordings into the isolated BI stack only.

Uses the repository loader and Gold SQL without changing their defaults.
Never connects to the original stack on ports 8080/8181/9000.
"""
import argparse
import re
import sys
from pathlib import Path

import trino
from pyiceberg.catalog import load_catalog

from bi_demo_settings import trino_connection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
import load_silver as loader


def execute(statement, user="dagster"):
    connection = trino_connection(user, request_timeout=180)
    try:
        cursor = connection.cursor()
        cursor.execute(statement)
        return cursor.fetchall()
    finally:
        connection.close()


def statements(filename):
    content = (ROOT / filename).read_text(encoding="utf-8")
    for statement in re.split(r";\s*(?:\n|$)", content):
        if any(line.strip() and not line.strip().startswith("--") for line in statement.splitlines()):
            yield statement


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def verify(folders):
    expected_ids = {loader.read_flight(folder)["flight_id"] for folder in folders}
    for table, per_flight in [("silver.flights", 1), ("gold.flight_summary", 1),
                              ("gold.flight_phases", 5), ("gold.flight_events", 4)]:
        rows = execute(f"SELECT flight_id, count(*) FROM iceberg.{table} GROUP BY flight_id")
        if {row[0] for row in rows} != expected_ids or any(row[1] != per_flight for row in rows):
            raise RuntimeError(f"Unexpected flights or row counts in {table}")
        print(f"PASS {table}: {sum(row[1] for row in rows)} rows", flush=True)
    for index, statement in enumerate(statements("sql/04_gold_checks.sql"), 1):
        failures = execute(statement)
        if failures:
            raise RuntimeError(f"Gold quality gate {index} failed for {len(failures)} flight(s)")
        print(f"PASS existing Gold quality gate {index}", flush=True)
    if execute("SELECT count(*) FROM iceberg.gold.flight_summary", "safety_analyst") != [[len(folders)]]:
        raise RuntimeError("Safety analyst cannot read all sample summaries")
    for user, query in [
        ("blocked_user", "SELECT count(*) FROM iceberg.gold.flight_summary"),
        ("operations_analyst", "SELECT touchdown_peak_g FROM iceberg.gold.flight_summary"),
        ("safety_analyst", "DELETE FROM iceberg.gold.flight_summary WHERE false"),
    ]:
        try:
            execute(query, user)
        except trino.exceptions.TrinoUserError as error:
            if error.error_name != "PERMISSION_DENIED":
                raise
        else:
            raise RuntimeError(f"Expected OPA denial for {user}")
        print(f"PASS OPA denial: {user}", flush=True)
    print("PASS source: capstone-opa-trino-iceberg / Trino HTTPS 8443 / local decoded", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    folders = sorted(path.parent for path in (ROOT / "decoded").glob("*/report.json"))
    if not folders:
        raise RuntimeError("No decoded recordings found in this checkout")
    if args.check:
        verify(folders)
        return
    execute("CREATE SCHEMA IF NOT EXISTS iceberg.silver")
    ddl = re.search(r"CREATE TABLE iceberg\.silver\.flights \(.*?;",
                    (ROOT / "demo.sql").read_text(encoding="utf-8"), re.S)
    if not ddl:
        raise RuntimeError("Cannot find existing Silver flights DDL")
    execute(ddl.group().rstrip(";").replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
    catalog = load_catalog("capstone_bi", **{
        "type": "rest", "uri": "http://127.0.0.1:9181",
        "s3.endpoint": "http://127.0.0.1:9100", "s3.access-key-id": "rustfsadmin",
        "s3.secret-access-key": "rustfsadmin", "s3.region": "us-east-1",
    })
    changed = False
    existing_counts = dict(execute("SELECT flight_id,count(*) FROM iceberg.silver.flights GROUP BY flight_id"))
    for folder in folders:
        fid = loader.read_flight(folder)["flight_id"]
        count = existing_counts.get(fid, 0)
        if count == 1:
            print("Already loaded:", folder.name, flush=True)
        elif count == 0:
            print("Loading:", folder.name, flush=True)
            loader.load_recording(catalog, folder)
            existing_counts[fid] = 1
            changed = True
        else:
            raise RuntimeError("Duplicate Silver flight metadata")
    for table in ["flight_events", "flight_phases", "flight_summary"]:
        try:
            rows = execute(f"SELECT count(DISTINCT flight_id) FROM iceberg.gold.{table}")[0][0]
            changed = changed or rows != len(folders)
        except trino.exceptions.TrinoUserError as error:
            if error.error_name not in {"TABLE_NOT_FOUND", "SCHEMA_NOT_FOUND"}:
                raise
            changed = True
    if changed:
        print("Building Gold with this repository sql/04_gold.sql", flush=True)
        for index, statement in enumerate(statements("sql/04_gold.sql"), 1):
            execute(statement)
            print(f"Gold statement {index} complete", flush=True)
    verify(folders)


if __name__ == "__main__":
    main()
