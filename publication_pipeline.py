"""An opt-in Dagster Gold publication job; no sensor or maintenance schedule.

dagster dev -f publication_pipeline.py
Configure candidate_input with recording=<folder under decoded/>.
"""

import dagster as dg

from gold_publication import Candidate, Publication


@dg.asset(group_name="publication", config_schema={
    "recording": str,
    "cruise_seconds": dg.Field(int, default_value=300),
})
def candidate_input(context):
    store = Publication()
    flight_id = store.prepare_silver(context.op_config["recording"])
    store.initialize(flight_id)
    candidate = store.begin(flight_id, context.op_config["cruise_seconds"])
    return dg.Output(candidate, metadata={
        "flight_id": flight_id, "candidate_run_id": candidate.run_id,
        "previous_run_id": candidate.previous_run_id or "none",
        "input_snapshots": dg.MetadataValue.json(candidate.source_snapshots),
    })


@dg.asset(group_name="publication")
def candidate_events(candidate_input: Candidate):
    Publication().build(candidate_input, "events")
    return dg.Output(candidate_input, metadata={"candidate_run_id": candidate_input.run_id})


@dg.asset(group_name="publication", config_schema={
    "simulate_failure": dg.Field(bool, default_value=False),
})
def candidate_phases(context, candidate_events: Candidate):
    if context.op_config["simulate_failure"]:
        raise RuntimeError("Injected failure after events; active release must stay unchanged")
    Publication().build(candidate_events, "phases")
    return dg.Output(candidate_events, metadata={"candidate_run_id": candidate_events.run_id})


@dg.asset(group_name="publication", check_specs=[
    dg.AssetCheckSpec("candidate_consistent", asset="candidate_summary", blocking=True),
])
def candidate_summary(candidate_phases: Candidate):
    store = Publication()
    store.build(candidate_phases, "summary")
    checks = store.validate(candidate_phases)
    yield dg.Output(candidate_phases, metadata={
        "candidate_run_id": candidate_phases.run_id,
        "checks": dg.MetadataValue.json(checks),
    })
    yield dg.AssetCheckResult(
        passed=True, check_name="candidate_consistent",
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"candidate_run_id": candidate_phases.run_id},
    )


@dg.asset(group_name="publication")
def published_flight(context, candidate_summary: Candidate):
    Publication().publish(candidate_summary)
    context.add_output_metadata({
        "flight_id": candidate_summary.flight_id,
        "published_run_id": candidate_summary.run_id,
        "stage_seconds": dg.MetadataValue.json(candidate_summary.stage_seconds),
    })
    return candidate_summary


ASSETS = [candidate_input, candidate_events, candidate_phases, candidate_summary, published_flight]
publication_job = dg.define_asset_job(
    "publish_flight", selection=dg.AssetSelection.groups("publication"),
    executor_def=dg.in_process_executor,
)
defs = dg.Definitions(assets=ASSETS, jobs=[publication_job], resources={"io_manager": dg.mem_io_manager})


def materialize(recording: str, *, cruise_seconds: int = 300,
                simulate_failure: bool = False, raise_on_error: bool = True):
    return dg.materialize(
        ASSETS,
        resources={"io_manager": dg.mem_io_manager},
        run_config={"ops": {
            "candidate_input": {"config": {"recording": recording, "cruise_seconds": cruise_seconds}},
            "candidate_phases": {"config": {"simulate_failure": simulate_failure}},
        }},
        raise_on_error=raise_on_error,
    )
