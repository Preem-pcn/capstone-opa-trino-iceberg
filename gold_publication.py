"""Build immutable per-flight Gold candidates, validate, then publish one pointer.

Experimental schemas only; the existing iceberg.gold tables are not modified.
One publisher per flight is required. Readers spanning multiple SQL statements
must resolve the active run once and pass that run_id to every read.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import trino

ROOT = Path(__file__).resolve().parent
SCHEMA = "gold_publication"
BASELINE = "gold_publication_baseline"
KINDS = ("events", "phases", "summary")
SILVER_TABLES = ("flights", "rate_1hz", "rate_4hz", "rate_8hz")
EVENTS = ["liftoff", "top_of_climb", "top_of_descent", "touchdown"]


def literal(value: str | None) -> str:
    return "CAST(NULL AS varchar)" if value is None else "'" + value.replace("'", "''") + "'"


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


class SQL:
    def __init__(self, user: str | None = None):
        self.host = os.environ.get("QAR_TRINO_HOST", "localhost")
        self.port = int(os.environ.get("QAR_TRINO_PORT", "8080"))
        self.user = user or os.environ.get("QAR_TRINO_USER", "publication_lab")

    def execute(self, statement: str) -> list[tuple]:
        conn = trino.dbapi.connect(
            host=self.host, port=self.port, user=self.user, catalog="iceberg",
            request_timeout=60, max_attempts=3,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(statement)
            return [tuple(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def scalar(self, statement: str):
        return self.execute(statement)[0][0]


@dataclass
class Candidate:
    flight_id: str
    run_id: str
    previous_run_id: str | None
    source_snapshots: dict[str, int]
    cruise_seconds: int = 300
    stage_seconds: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict) -> "Candidate":
        return cls(**value)


class Publication:
    def __init__(self, sql: SQL | None = None):
        self.sql = sql or SQL()

    def prepare_silver(self, recording: str) -> str:
        # Only populate missing sample flights; never reload existing Silver.
        import load_silver as loader

        folder = (ROOT / "decoded" / recording).resolve()
        if folder.parent != (ROOT / "decoded").resolve():
            raise ValueError("recording must be a direct child of decoded/")
        flight = loader.read_flight(folder)
        self.sql.execute("CREATE SCHEMA IF NOT EXISTS iceberg.silver")
        demo = (ROOT / "demo.sql").read_text()
        ddl = re.search(r"CREATE TABLE iceberg\.silver\.flights \(.*?;", demo, re.S)
        if not ddl:
            raise ValueError("Cannot locate the existing Silver flights DDL")
        self.sql.execute(ddl.group().rstrip(";").replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
        exists = self.sql.scalar(
            f"SELECT count(*) FROM iceberg.silver.flights WHERE flight_id = {literal(flight['flight_id'])}"
        )
        if exists != 1:
            if exists:
                raise ValueError("Duplicate Silver flight metadata")
            loader.load_recording(loader.get_catalog(), folder)
        return flight["flight_id"]

    def snapshot(self, schema: str, table: str) -> int:
        schema, table = identifier(schema), identifier(table)
        return int(self.sql.scalar(
            f'SELECT snapshot_id FROM iceberg.{schema}."{table}$history" '
            "WHERE is_current_ancestor ORDER BY made_current_at DESC LIMIT 1"
        ))

    def active(self, flight_id: str) -> str | None:
        rows = self.sql.execute(
            f"SELECT run_id FROM iceberg.{SCHEMA}.active_runs WHERE flight_id = {literal(flight_id)}"
        )
        if len(rows) > 1:
            raise ValueError("Multiple active pointers: stop publication")
        return rows[0][0] if rows else None

    def begin(self, flight_id: str, cruise_seconds: int = 300) -> Candidate:
        if not isinstance(cruise_seconds, int) or not 1 <= cruise_seconds <= 3600:
            raise ValueError("cruise_seconds must be an integer in [1, 3600]")
        snapshots = {name: self.snapshot("silver", name) for name in SILVER_TABLES}
        # Inputs are pinned independently, not an atomic multi-table Silver snapshot.
        # Run after the Silver loader completes; no simultaneous reload of this flight.
        return Candidate(flight_id, uuid4().hex, self.active(flight_id), snapshots, cruise_seconds)

    def select(self, kind: str, candidate: Candidate, *, baseline: bool = False) -> str:
        if kind not in KINDS:
            raise ValueError(kind)
        text = (ROOT / "sql" / f"05_gold_{kind}.sql").read_text()
        marker = f"INSERT INTO iceberg.gold.flight_{kind}"
        if text.count(marker) != 1:
            raise ValueError("Gold SQL template changed: inspect before continuing")
        query = text.split(marker, 1)[1].strip().rstrip(";")
        query = query.replace("'{flight_id}'", literal(candidate.flight_id))
        for name, snapshot in candidate.source_snapshots.items():
            query = re.sub(
                rf"\biceberg\.silver\.{name}\b",
                f"iceberg.silver.{name} FOR VERSION AS OF {int(snapshot)}", query,
            )
        for dependency in KINDS:
            source = f"iceberg.gold.flight_{dependency}"
            if baseline:
                replacement = f"iceberg.{BASELINE}.flight_{dependency}"
            else:
                replacement = (
                    f"(SELECT * FROM iceberg.{SCHEMA}.flight_{dependency}_history "
                    f"WHERE run_id = {literal(candidate.run_id)} "
                    f"AND flight_id = {literal(candidate.flight_id)})"
                )
            query = query.replace(source, replacement)
        query = query.replace("HAVING count(*) >= 300", f"HAVING count(*) >= {candidate.cruise_seconds}")
        query = query.replace("'events-v0.1'", literal(f"events-cruise-{candidate.cruise_seconds}s"))
        return query

    def initialize(self, flight_id: str) -> None:
        self.sql.execute(f"CREATE SCHEMA IF NOT EXISTS iceberg.{SCHEMA}")
        self.sql.execute(f"CREATE SCHEMA IF NOT EXISTS iceberg.{BASELINE}")
        self.sql.execute(f"""CREATE TABLE IF NOT EXISTS iceberg.{SCHEMA}.active_runs (
            flight_id varchar, run_id varchar, previous_run_id varchar,
            input_snapshots varchar, cruise_seconds integer,
            published_at timestamp(6) with time zone
        ) WITH (format = 'PARQUET', format_version = 2)""")
        candidate = self.begin(flight_id)
        for kind in KINDS:
            query = self.select(kind, candidate)
            self.sql.execute(f"""CREATE TABLE IF NOT EXISTS iceberg.{SCHEMA}.flight_{kind}_history
                WITH (format = 'PARQUET', format_version = 2)
                AS SELECT CAST(NULL AS varchar) AS run_id, q.* FROM ({query}) q WHERE false""")
            self.sql.execute(f"""CREATE TABLE IF NOT EXISTS iceberg.{BASELINE}.flight_{kind}
                WITH (format = 'PARQUET', format_version = 2)
                AS SELECT * FROM iceberg.{SCHEMA}.flight_{kind}_history WHERE false""")
        # Convenience for individual queries. Multi-query consumers pin active() once.
        for kind in KINDS:
            self.sql.execute(f"""CREATE OR REPLACE VIEW iceberg.{SCHEMA}.flight_{kind} AS
                SELECT h.* FROM iceberg.{SCHEMA}.flight_{kind}_history h
                JOIN iceberg.{SCHEMA}.active_runs a
                  ON h.flight_id = a.flight_id AND h.run_id = a.run_id""")

    def build(self, candidate: Candidate, kind: str, *, baseline: bool = False) -> None:
        table = (f"iceberg.{BASELINE}.flight_{kind}" if baseline else
                 f"iceberg.{SCHEMA}.flight_{kind}_history")
        if self.sql.scalar(f"SELECT count(*) FROM {table} WHERE run_id = {literal(candidate.run_id)}"):
            raise ValueError("A candidate stage is immutable; retry with a new run_id")
        started = perf_counter()
        self.sql.execute(
            f"INSERT INTO {table} SELECT {literal(candidate.run_id)} AS run_id, q.* "
            f"FROM ({self.select(kind, candidate, baseline=baseline)}) q"
        )
        candidate.stage_seconds[kind] = perf_counter() - started

    def delete_baseline(self, flight_id: str, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(kind)
        self.sql.execute(f"DELETE FROM iceberg.{BASELINE}.flight_{kind} WHERE flight_id = {literal(flight_id)}")

    def source(self, kind: str, flight_id: str, run_id: str, *, baseline: bool = False) -> str:
        if kind not in KINDS:
            raise ValueError(kind)
        table = (f"iceberg.{BASELINE}.flight_{kind}" if baseline else
                 f"iceberg.{SCHEMA}.flight_{kind}_history")
        return f"(SELECT * FROM {table} WHERE flight_id = {literal(flight_id)} AND run_id = {literal(run_id)})"

    def validate(self, candidate: Candidate) -> dict:
        src = lambda kind: self.source(kind, candidate.flight_id, candidate.run_id)
        events = self.sql.execute(f"SELECT event, t_offset_s, value FROM {src('events')} ORDER BY t_offset_s")
        if [row[0] for row in events] != EVENTS or not all(
            events[i][1] < events[i + 1][1] for i in range(3)
        ) or any(row[2] is None for row in events):
            raise ValueError("Events incomplete, out of order, or missing measurements")
        phases = self.sql.execute(f"SELECT phase_order, start_s, end_s, duration_s FROM {src('phases')} ORDER BY phase_order")
        duration = self.sql.scalar(
            "SELECT duration_s FROM iceberg.silver.flights "
            f"FOR VERSION AS OF {candidate.source_snapshots['flights']} "
            f"WHERE flight_id = {literal(candidate.flight_id)}"
        )
        if len(phases) != 5 or [p[0] for p in phases] != list(range(1, 6)):
            raise ValueError("Missing or duplicate phases")
        if phases[0][1] != 0 or phases[-1][2] != duration - 1:
            raise ValueError("Phases do not span the recording")
        if any(p[3] <= 0 or p[3] != p[2] - p[1] + 1 for p in phases) or any(
            phases[i][2] + 1 != phases[i + 1][1] for i in range(4)
        ):
            raise ValueError("Phase gap, overlap, or invalid duration")
        bounds = [row[1] for row in events]
        expected = [(0, bounds[0]-1), (bounds[0], bounds[1]-1),
                    (bounds[1], bounds[2]-1), (bounds[2], bounds[3]), (bounds[3]+1, duration-1)]
        if [(p[1], p[2]) for p in phases] != expected:
            raise ValueError("Phase boundaries disagree with events")
        summaries = self.sql.execute(f"""SELECT airborne_min, cruise_min, touchdown_peak_g,
            liftoff_delta_s, touchdown_delta_s FROM {src('summary')}""")
        if len(summaries) != 1 or any(v is None for v in summaries[0]):
            raise ValueError("Summary missing, duplicated, or incomplete")
        airborne, cruise, peak, d_lift, d_touch = summaries[0]
        if abs(d_lift) > 1 or abs(d_touch) > 1:
            raise ValueError("Segmentation delta exceeds the POC tolerance")
        if abs(float(airborne) - round((bounds[3]-bounds[0]+1)/60, 1)) > 0.051:
            raise ValueError("Summary airborne duration disagrees with events")
        if abs(float(cruise) - round(phases[2][3]/60, 1)) > 0.051 or abs(float(peak) - float(events[-1][2])) > 1e-9:
            raise ValueError("Summary disagrees with phases/events")
        return {"events": len(events), "phases": len(phases), "summaries": len(summaries),
                "phase_seconds": sum(p[3] for p in phases), "checks_passed": True}

    def publish(self, candidate: Candidate) -> dict:
        # Revalidate at the publication boundary, even if Dagster checks passed earlier.
        checks = self.validate(candidate)
        current = self.active(candidate.flight_id)
        if current == candidate.run_id:
            return {**checks, "already_published": True}
        if current != candidate.previous_run_id:
            raise ValueError("Active run changed while building; refuse a stale publication")
        expected = literal(candidate.previous_run_id)
        self.sql.execute(f"""MERGE INTO iceberg.{SCHEMA}.active_runs a
            USING (SELECT {literal(candidate.flight_id)} AS flight_id,
                          {literal(candidate.run_id)} AS run_id) n
            ON a.flight_id = n.flight_id
            WHEN MATCHED AND a.run_id = {expected} THEN UPDATE SET
                run_id = n.run_id, previous_run_id = {expected},
                input_snapshots = {literal(json.dumps(candidate.source_snapshots, sort_keys=True))},
                cruise_seconds = {candidate.cruise_seconds}, published_at = current_timestamp
            WHEN NOT MATCHED AND {expected} IS NULL THEN INSERT
                (flight_id, run_id, previous_run_id, input_snapshots, cruise_seconds, published_at)
                VALUES (n.flight_id, n.run_id, {expected},
                    {literal(json.dumps(candidate.source_snapshots, sort_keys=True))},
                    {candidate.cruise_seconds}, current_timestamp)""")
        if self.active(candidate.flight_id) != candidate.run_id:
            raise ValueError("Publication lost the pointer update")
        return checks

    def observe(self, flight_id: str, *, baseline: bool = False,
                pinned_run_id: str | None = None) -> dict:
        # Explicit one-time resolution. All three tables use this exact generation.
        run_id = pinned_run_id if pinned_run_id is not None else (None if baseline else self.active(flight_id))
        if not baseline and run_id is None:
            return {"active_run_id": None, "complete": False, "mixed": False, "counts": [0, 0, 0]}
        parts = []
        for kind in KINDS:
            table = (f"iceberg.{BASELINE}.flight_{kind}" if baseline else
                     f"iceberg.{SCHEMA}.flight_{kind}_history")
            predicate = f"flight_id = {literal(flight_id)}"
            if not baseline:
                predicate += f" AND run_id = {literal(run_id)}"
            parts.append(f"SELECT {literal(kind)} AS kind, run_id, count(*) AS n FROM {table} WHERE {predicate} GROUP BY run_id")
        rows = self.sql.execute(" UNION ALL ".join(parts))
        counts = [sum(row[2] for row in rows if row[0] == kind) for kind in KINDS]
        runs = {row[1] for row in rows}
        return {"active_run_id": run_id, "complete": counts == [4, 5, 1],
                "mixed": len(runs) > 1, "counts": counts,
                "runs": sorted(runs), "rows": rows}
