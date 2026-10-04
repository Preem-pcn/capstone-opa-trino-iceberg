"""Step 5 — the QAR POC as a Dagster pipeline.

Run from your project folder (venv active, Docker stack up):
    export DAGSTER_HOME=$PWD/dagster_home
    dagster dev -f qar_pipeline.py
Then open http://localhost:3000

What's here:
  - one PARTITION per recording folder (added automatically by a sensor)
  - four ASSETS per partition: silver/flight_data -> gold/flight_events
    -> gold/flight_phases -> gold/flight_summary
  - the Step 4 quality gates as ASSET CHECKS (a failed gate stops what's downstream)
  - a nightly SCHEDULE for Iceberg maintenance
"""

import os
import re
from pathlib import Path

import dagster as dg
import trino

import load_silver as L

DECODED = Path(os.environ.get("QAR_DECODED", "~/Documents/capstone-qar/qar-data/decoded")).expanduser()
RECORDING_GLOB = os.environ.get("QAR_RECORDING_GLOB", "A350_*")   # A350 only, for now
SQL_DIR = Path(__file__).parent / "sql"


# ---------------------------------------------------------------------------
# Resources: connections the assets share
# ---------------------------------------------------------------------------

class TrinoResource(dg.ConfigurableResource):
    """Runs SQL on Trino. Dagster runs on your Mac, so it's localhost:8080."""

    host: str = "localhost"
    port: int = 8080
    user: str = "dagster"

    def execute(self, sql: str) -> list[tuple]:
        conn = trino.dbapi.connect(host=self.host, port=self.port, user=self.user, catalog="iceberg")
        try:
            cur = conn.cursor()
            cur.execute(sql)
            return [tuple(r) for r in cur.fetchall()]   # fetching also waits for writes to finish
        finally:
            conn.close()


def run_sql_file(trino_res: TrinoResource, name: str, flight_id: str) -> None:
    """Run every statement in sql/<name> for one flight, in order."""
    sql = (SQL_DIR / name).read_text().replace("{flight_id}", flight_id)
    for stmt in re.split(r";\s*(?:\n|$)", sql):
        # skip blocks that are only comments or blank
        if any(line.strip() and not line.strip().startswith("--") for line in stmt.splitlines()):
            trino_res.execute(stmt)


def flight_id_for(recording: str) -> str:
    """Partition key (folder name) -> flight_id, checked before it goes into SQL."""
    fid = L.read_flight(DECODED / recording)["flight_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", fid):
        raise ValueError(f"unexpected characters in flight_id {fid!r}")
    return fid


# ---------------------------------------------------------------------------
# Partitions: one per recording folder. "Dynamic" = the list grows at runtime.
# ---------------------------------------------------------------------------

recordings = dg.DynamicPartitionsDefinition(name="recording")


# ---------------------------------------------------------------------------
# Assets: each one is a table (or set of tables) for ONE recording
# ---------------------------------------------------------------------------

@dg.asset(
    key=["silver", "flight_data"],
    partitions_def=recordings,
    group_name="silver",
    description="All Silver tables for one recording: 7 rate tables + its silver.flights row (Step 3 loader).",
)
def silver_flight_data(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    fid, counts = L.load_recording(L.get_catalog(), DECODED / context.partition_key)
    return dg.MaterializeResult(metadata={"flight_id": fid, **{f"rows_{t}": n for t, n in counts.items()}})


EVENT_ORDER = ["liftoff", "top_of_climb", "top_of_descent", "touchdown"]


@dg.asset(
    key=["gold", "flight_events"],
    partitions_def=recordings,
    group_name="gold",
    deps=[silver_flight_data],
    check_specs=[dg.AssetCheckSpec("events_in_order", asset=["gold", "flight_events"], blocking=True)],
    description="Lift-off, top of climb, top of descent, touchdown (with peak g).",
)
def gold_flight_events(context: dg.AssetExecutionContext, trino: TrinoResource) -> dg.MaterializeResult:
    fid = flight_id_for(context.partition_key)
    run_sql_file(trino, "05_gold_events.sql", fid)

    # Gate 2: exactly the four events, in time order
    rows = trino.execute(
        f"SELECT event, t_offset_s FROM iceberg.gold.flight_events "
        f"WHERE flight_id = '{fid}' ORDER BY t_offset_s"
    )
    order = [r[0] for r in rows]
    return dg.MaterializeResult(
        metadata={"flight_id": fid, **{e: float(t) for e, t in rows}},
        check_results=[dg.AssetCheckResult(
            check_name="events_in_order",
            passed=order == EVENT_ORDER,
            metadata={"found": ", ".join(order)},
        )],
    )


@dg.asset(
    key=["gold", "flight_phases"],
    partitions_def=recordings,
    group_name="gold",
    deps=[gold_flight_events],
    check_specs=[dg.AssetCheckSpec("phases_cover_recording", asset=["gold", "flight_phases"], blocking=True)],
    description="Five phases between the events, covering every second of the recording.",
)
def gold_flight_phases(context: dg.AssetExecutionContext, trino: TrinoResource) -> dg.MaterializeResult:
    fid = flight_id_for(context.partition_key)
    run_sql_file(trino, "05_gold_phases.sql", fid)

    # Gate 1: phases add up to the recording, none empty, exactly five
    phase_s, recording_s, shortest, n = trino.execute(
        f"SELECT sum(p.duration_s), max(f.duration_s), min(p.duration_s), count(*) "
        f"FROM iceberg.gold.flight_phases p JOIN iceberg.silver.flights f ON f.flight_id = p.flight_id "
        f"WHERE p.flight_id = '{fid}'"
    )[0]
    return dg.MaterializeResult(
        metadata={"flight_id": fid, "phases": int(n)},
        check_results=[dg.AssetCheckResult(
            check_name="phases_cover_recording",
            passed=n == 5 and shortest > 0 and phase_s == recording_s,
            metadata={"phase_seconds": int(phase_s), "recording_seconds": int(recording_s),
                      "shortest_phase_s": int(shortest)},
        )],
    )


@dg.asset(
    key=["gold", "flight_summary"],
    partitions_def=recordings,
    group_name="gold",
    deps=[gold_flight_events, gold_flight_phases, silver_flight_data],
    check_specs=[dg.AssetCheckSpec("matches_decoder_segmentation", asset=["gold", "flight_summary"])],
    description="One row per flight. Compared against the decoder's own segmentation.",
)
def gold_flight_summary(context: dg.AssetExecutionContext, trino: TrinoResource) -> dg.MaterializeResult:
    fid = flight_id_for(context.partition_key)
    run_sql_file(trino, "05_gold_summary.sql", fid)

    # Gate 3: our lift-off and touchdown within 1 s of the decoder's
    airborne, peak_g, d_lift, d_touch = trino.execute(
        f"SELECT airborne_min, touchdown_peak_g, liftoff_delta_s, touchdown_delta_s "
        f"FROM iceberg.gold.flight_summary WHERE flight_id = '{fid}'"
    )[0]
    return dg.MaterializeResult(
        metadata={"flight_id": fid, "airborne_min": float(airborne), "touchdown_peak_g": float(peak_g)},
        check_results=[dg.AssetCheckResult(
            check_name="matches_decoder_segmentation",
            passed=abs(d_lift) <= 1 and abs(d_touch) <= 1,
            metadata={"liftoff_delta_s": int(d_lift), "touchdown_delta_s": int(d_touch)},
        )],
    )


# One job = run all four assets for one partition, in dependency order.
flight_pipeline = dg.define_asset_job(
    "flight_pipeline",
    selection=dg.AssetSelection.groups("silver", "gold"),
    partitions_def=recordings,
)


# ---------------------------------------------------------------------------
# Sensor: notice new recording folders, add them as partitions, start a run
# ---------------------------------------------------------------------------

@dg.sensor(job=flight_pipeline, minimum_interval_seconds=30)
def new_recordings(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    """Every 30 s: any recording folder Dagster hasn't seen yet gets a partition and a run."""
    found = sorted(p.name for p in DECODED.glob(RECORDING_GLOB) if (p / "report.json").exists())
    known = set(context.instance.get_dynamic_partitions(recordings.name))
    new = [name for name in found if name not in known]
    return dg.SensorResult(
        run_requests=[dg.RunRequest(partition_key=name) for name in new],
        dynamic_partitions_requests=[recordings.build_add_request(new)] if new else [],
    )


# ---------------------------------------------------------------------------
# Nightly Iceberg maintenance (Step 1 notes) — order matters
# ---------------------------------------------------------------------------

MAINTENANCE = [
    "ALTER TABLE {t} EXECUTE optimize",                                             # merge small files
    "ALTER TABLE {t} EXECUTE optimize_manifests",                                   # merge small manifests
    "ALTER TABLE {t} EXECUTE expire_snapshots(retention_threshold => '7d')",        # old snapshots + their files
    "ALTER TABLE {t} EXECUTE remove_orphan_files(retention_threshold => '7d')",     # leftovers from crashed writes
]


@dg.op
def iceberg_maintenance(context: dg.OpExecutionContext, trino: TrinoResource) -> None:
    tables = trino.execute(
        "SELECT table_schema, table_name FROM iceberg.information_schema.tables "
        "WHERE table_schema IN ('silver', 'gold') ORDER BY 1, 2"
    )
    for schema, table in tables:
        t = f"iceberg.{schema}.{table}"
        for stmt in MAINTENANCE:
            trino.execute(stmt.format(t=t))
        context.log.info(f"maintained {t}")


@dg.job
def maintenance():
    iceberg_maintenance()


nightly_maintenance = dg.ScheduleDefinition(
    job=maintenance,
    cron_schedule="0 2 * * *",          # 02:00 every night
    execution_timezone="Asia/Bangkok",
)


defs = dg.Definitions(
    assets=[silver_flight_data, gold_flight_events, gold_flight_phases, gold_flight_summary],
    jobs=[flight_pipeline, maintenance],
    sensors=[new_recordings],
    schedules=[nightly_maintenance],
    resources={"trino": TrinoResource()},
)