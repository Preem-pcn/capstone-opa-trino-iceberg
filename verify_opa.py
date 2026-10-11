"""Verify OPA with isolated fixtures and read-only checks on real QAR tables."""

import argparse
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SILVER = "iceberg.opa_demo_silver"
GOLD = "iceberg.opa_demo_gold"
IDS = {"HS-THJ_DEMO_01", "HS-THE_DEMO_02", "HS-TKN_DEMO_03"}
SCOPES = {
    "admin": IDS,
    "safety_analyst": IDS,
    "engineering_analyst": {"HS-THJ_DEMO_01"},
    "operations_analyst": {"HS-THJ_DEMO_01", "HS-THE_DEMO_02"},
}


def run_query(user, sql):
    return subprocess.run(
        ["docker", "exec", "trino", "trino", "--user", user,
         "--catalog", "iceberg", "--output-format", "JSON", "--execute", sql],
        capture_output=True, text=True, timeout=120, check=False,
    )


def query(user, sql):
    result = run_query(user, sql)
    if result.returncode:
        raise RuntimeError(f"{user}: {sql}\n{result.stderr or result.stdout}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def scalar(user, sql):
    rows = query(user, sql)
    return next(iter(rows[0].values()))


def denial(user, sql):
    result = run_query(user, sql)
    message = result.stderr.strip() or result.stdout.strip()
    # A missing table, connection error, or syntax error is not a policy denial.
    if result.returncode and "Access Denied:" not in message:
        raise RuntimeError(f"Unexpected error, not an OPA denial: {message}")
    return result.returncode != 0 and "Access Denied:" in message, message


def setup_fixtures():
    query("admin", f"CREATE SCHEMA IF NOT EXISTS {SILVER}")
    query("admin", f"CREATE SCHEMA IF NOT EXISTS {GOLD}")
    query("admin", f"""CREATE TABLE IF NOT EXISTS {SILVER}.flights AS
        SELECT * FROM (VALUES
          ('HS-THJ_DEMO_01', 'HS-THJ', 'VTBS', 'OPKC', 'TG_DEMO_01', 'demo_01', 'raw/demo_01'),
          ('HS-THE_DEMO_02', 'HS-THE', 'RKSI', 'VTBS', 'TG_DEMO_02', 'demo_02', 'raw/demo_02'),
          ('HS-TKN_DEMO_03', 'HS-TKN', 'EGLL', 'ESSA', 'TG_DEMO_03', 'demo_03', 'raw/demo_03')
        ) AS t(flight_id, tail, origin, destination, flight_no, recording, source_file)""")
    query("admin", f"""CREATE TABLE IF NOT EXISTS {SILVER}.rate_1hz AS
        SELECT flight_id, 0.0 AS t_offset_s, 1000.0 AS alt_std
        FROM {SILVER}.flights""")
    query("admin", f"""CREATE TABLE IF NOT EXISTS {GOLD}.flight_summary AS
        SELECT flight_id, tail, origin, destination, flight_no,
               1.2 AS touchdown_peak_g FROM {SILVER}.flights""")
    query("admin", f"""CREATE TABLE IF NOT EXISTS {GOLD}.flight_events AS
        SELECT flight_id, 'touchdown' AS event, 120.0 AS t_offset_s
        FROM {SILVER}.flights""")
    query("admin", f"""CREATE TABLE IF NOT EXISTS {GOLD}.flight_phases AS
        SELECT flight_id, 'cruise' AS phase, 60.0 AS duration_s
        FROM {SILVER}.flights""")
    query("admin", f"""CREATE TABLE IF NOT EXISTS {SILVER}.unlisted_demo AS
        SELECT * FROM {SILVER}.flights""")
    actual = {r["flight_id"] for r in query("admin", f"SELECT flight_id FROM {SILVER}.flights")}
    if actual != IDS:
        raise RuntimeError("OPA demo fixture differs from the expected three flights")


def expected_ids(user):
    if user == "operations_analyst":
        rows = query("admin", f"""SELECT lower(to_hex(sha256(to_utf8(flight_id)))) AS flight_id
            FROM {SILVER}.flights WHERE origin = 'VTBS' OR destination = 'VTBS'""")
        return {r["flight_id"] for r in rows}
    return SCOPES[user]


def verify(checks):
    schemas = {next(iter(row.values())) for row in query("operations_analyst", "SHOW SCHEMAS FROM iceberg")}
    checks.append({"name": "discovery:approved_schemas_only",
                   "passed": schemas == {"silver", "gold", "opa_demo_silver", "opa_demo_gold"}})
    tables = {next(iter(row.values())) for row in query("operations_analyst", f"SHOW TABLES FROM {SILVER}")}
    checks.append({"name": "discovery:unlisted_table_hidden",
                   "passed": tables == {"flights", "rate_1hz"}})
    columns = {row["Column"] for row in query("operations_analyst", f"DESCRIBE {GOLD}.flight_summary")}
    checks.append({"name": "discovery:denied_column_hidden",
                   "passed": "touchdown_peak_g" not in columns and "flight_id" in columns})
    metadata = query("operations_analyst", "SELECT table_schema, table_name FROM iceberg.information_schema.tables")
    checks.append({"name": "discovery:information_schema_filtered",
                   "passed": bool(metadata) and all(
                       row["table_schema"] in schemas and row["table_name"] != "unlisted_demo"
                       for row in metadata)})

    for table in (
        f"{SILVER}.flights", f"{SILVER}.rate_1hz",
        f"{GOLD}.flight_summary", f"{GOLD}.flight_events", f"{GOLD}.flight_phases",
    ):
        for user in SCOPES:
            actual = {r["flight_id"] for r in query(user, f"SELECT flight_id FROM {table}")}
            checks.append({"name": f"rows:{user}:{table}",
                           "passed": actual == expected_ids(user),
                           "expected_rows": len(SCOPES[user]), "actual_rows": len(actual)})

    for user, columns in (
        ("operations_analyst", ["tail"]),
        ("engineering_analyst", ["origin", "destination", "flight_no"]),
    ):
        for table in (f"{SILVER}.flights", f"{GOLD}.flight_summary"):
            rows = query(user, f"SELECT {', '.join(columns)} FROM {table}")
            checks.append({"name": f"mask:{user}:{table}",
                           "passed": bool(rows) and all(
                               value == "REDACTED" for row in rows for value in row.values())})
    rows = query("safety_analyst", f"SELECT recording, source_file FROM {SILVER}.flights")
    checks.append({"name": "mask:safety:source_locations",
                   "passed": all(v == "REDACTED" for row in rows for v in row.values())})

    joined = query("operations_analyst", f"""SELECT f.flight_id
        FROM {SILVER}.flights f JOIN {GOLD}.flight_events e ON f.flight_id = e.flight_id""")
    checks.append({"name": "pseudonym:stable_across_layers",
                   "passed": {r["flight_id"] for r in joined} == expected_ids("operations_analyst")})

    for user in ("blocked_user", "unknown_user"):
        passed, error = denial(user, f"SELECT flight_id FROM {GOLD}.flight_summary")
        checks.append({"name": f"deny:{user}", "passed": passed, "message": error})

    for user in ("safety_analyst", "operations_analyst", "engineering_analyst"):
        for label, sql in (
            ("unlisted_table", f"SELECT flight_id FROM {SILVER}.unlisted_demo"),
            ("metadata_files", f'SELECT file_path FROM {SILVER}."flights$files"'),
            ("metadata_snapshots", f'SELECT snapshot_id FROM {SILVER}."flights$snapshots"'),
            ("hidden_file_path", f'SELECT "$path" FROM {SILVER}.flights'),
            ("hidden_partition", f'SELECT "$partition" FROM {SILVER}.flights'),
            ("hidden_file_time", f'SELECT "$file_modified_time" FROM {SILVER}.flights'),
            ("restricted_information_schema", "SELECT grantee FROM iceberg.information_schema.table_privileges"),
            ("insert", f"INSERT INTO {SILVER}.flights SELECT * FROM {SILVER}.flights WHERE false"),
            ("delete", f"DELETE FROM {SILVER}.flights WHERE false"),
            ("update", f"UPDATE {SILVER}.flights SET tail = 'DEMO' WHERE false"),
        ):
            passed, error = denial(user, sql)
            checks.append({"name": f"deny:{user}:{label}", "passed": passed, "message": error})

    passed, error = denial("operations_analyst", f"SELECT touchdown_peak_g FROM {GOLD}.flight_summary")
    checks.append({"name": "deny:operations:safety_column", "passed": passed, "message": error})
    passed, error = denial("operations_analyst", f"SELECT * FROM {GOLD}.flight_summary")
    checks.append({"name": "deny:operations:star_includes_safety_column", "passed": passed, "message": error})
    checks.append({"name": "allow:safety:safety_column",
                   "passed": len(query("safety_analyst", f"SELECT touchdown_peak_g FROM {GOLD}.flight_summary")) == 3})

    snapshot = scalar("admin", f'SELECT snapshot_id FROM {SILVER}."flights$snapshots" ORDER BY committed_at DESC LIMIT 1')
    for user in ("engineering_analyst", "operations_analyst"):
        rows = query(user, f"SELECT flight_id FROM {SILVER}.flights FOR VERSION AS OF {snapshot}")
        checks.append({"name": f"rows:{user}:time_travel",
                       "passed": {r["flight_id"] for r in rows} == expected_ids(user)})

    # Use a fresh table so repeated checks never drop a pre-existing object.
    for user in ("dagster", "publication_lab"):
        table = f"{GOLD}.service_check_{uuid.uuid4().hex}"
        created = False
        try:
            query(user, f"CREATE TABLE {table} (id integer)")
            created = True
            query(user, f"INSERT INTO {table} VALUES (1)")
            checks.append({"name": f"allow:{user}:write", "passed": scalar(user, f"SELECT count(*) FROM {table}") == 1})
        finally:
            if created:
                query(user, f"DROP TABLE {table}")


def verify_real_tables(checks):
    real_tables = ["silver.flights", "silver.rate_1hz", "gold.flight_summary",
                   "gold.flight_events", "gold.flight_phases"]
    available = []
    for name in real_tables:
        # Existing real tables are inspected but never created or rebuilt here.
        schema, table = name.split(".")
        exists = scalar("admin", f"""SELECT count(*) FROM iceberg.information_schema.tables
            WHERE table_schema = '{schema}' AND table_name = '{table}'""")
        if not exists:
            continue
        available.append(name)
        if name == "silver.rate_1hz":
            columns = query("engineering_analyst", "DESCRIBE iceberg.silver.rate_1hz")
            checks.append({"name": "real:wide_table:column_discovery", "passed": bool(columns),
                           "column_count": len(columns)})
        for user, predicate in (
            ("engineering_analyst", "tail = 'HS-THJ'"),
            ("operations_analyst", "origin = 'VTBS' OR destination = 'VTBS'"),
        ):
            actual = scalar(user, f"SELECT count(*) FROM iceberg.{name}")
            expected = scalar("admin", f"""SELECT count(*) FROM iceberg.{name}
                WHERE flight_id IN (SELECT flight_id FROM iceberg.silver.flights WHERE {predicate})""")
            checks.append({"name": f"real:{user}:{name}", "passed": actual == expected,
                           "expected_rows": expected, "actual_rows": actual})
        if name in {"silver.flights", "gold.flight_summary"}:
            rows = query("operations_analyst", f"SELECT flight_id, tail FROM iceberg.{name}")
            checks.append({"name": f"real:operations:mask:{name}",
                           "passed": bool(rows) and all(
                               row["tail"] == "REDACTED" and len(row["flight_id"]) == 64
                               for row in rows)})
    exists = scalar("admin", """SELECT count(*) FROM iceberg.information_schema.tables
        WHERE table_schema = 'gold_publication' AND table_name = 'flight_summary_history'""")
    if exists:
        passed, error = denial("operations_analyst",
                               "SELECT flight_id FROM iceberg.gold_publication.flight_summary_history")
        checks.append({"name": "deny:real:publication_history", "passed": passed, "message": error})
    return available


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/opa_policy_evidence.json")
    args = parser.parse_args()
    checks = []
    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Authorization PoC: self-asserted users; direct Iceberg/RustFS access bypasses Trino",
        "fixtures": {"schemas": ["opa_demo_silver", "opa_demo_gold"],
                     "flights": 3, "engineering_visible": 1, "operations_visible": 2},
        "checks": checks,
    }
    try:
        setup_fixtures()
        verify(checks)
        evidence["real_tables_checked"] = verify_real_tables(checks)
    except Exception as error:
        checks.append({"name": "verification_error", "passed": False, "message": str(error)})
    evidence["passed"] = bool(checks) and all(c["passed"] for c in checks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    for check in checks:
        print(f"{'PASS' if check['passed'] else 'FAIL'} {check['name']}")
    print(f"Evidence: {args.output}")
    if not evidence["passed"]:
        raise SystemExit("OPA verification failed; see evidence JSON")


if __name__ == "__main__":
    main()
