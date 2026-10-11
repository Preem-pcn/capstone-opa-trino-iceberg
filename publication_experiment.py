"""Controlled interleavings plus a concurrent reader on real Trino/Iceberg.

python publication_experiment.py --recording A350_HS-THJ_20220322_TG0341_VTBS-OPKC
Only gold_publication* schemas are written. Missing sample Silver is loaded.
Evidence is saved even when a run fails. Injected delays expose commit boundaries;
elapsed times are an experiment trace, not a throughput benchmark.
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from gold_publication import BASELINE, KINDS, ROOT, SCHEMA, Publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", default="A350_HS-THJ_20220322_TG0341_VTBS-OPKC")
    parser.add_argument("--hold-seconds", type=float, default=0.5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.hold_seconds < 0:
        parser.error("hold-seconds must be nonnegative")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or ROOT / "results" / "publication" / stamp
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
                "recording": args.recording, "checkpoints": [], "continuous_reads": [],
                "assertions": {}, "hold_seconds": args.hold_seconds,
                "contract": "One publisher per flight; immutable candidates; consumers pin run_id once."}
    store = Publication()
    started = time.perf_counter()

    def checkpoint(scenario, stage, *, baseline=False, pinned=None):
        before = time.perf_counter()
        row = {"scenario": scenario, "stage": stage, "elapsed_seconds": before-started,
               **store.observe(flight_id, baseline=baseline, pinned_run_id=pinned)}
        row["read_seconds"] = time.perf_counter()-before
        evidence["checkpoints"].append(row)
        print(f"{scenario:20} {stage:24} counts={row['counts']} mixed={row['mixed']} active={row['active_run_id']}", flush=True)
        time.sleep(args.hold_seconds)
        return row

    def assert_that(name, condition):
        evidence["assertions"][name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def run_observed(scenario, writer, *, baseline=False):
        stop = threading.Event()
        ready = threading.Event()
        def read_loop():
            observer = Publication()
            while not stop.is_set():
                before = time.perf_counter()
                try:
                    row = observer.observe(flight_id, baseline=baseline)
                    row.update(scenario=scenario, elapsed_seconds=before-started,
                               read_seconds=time.perf_counter()-before)
                    evidence["continuous_reads"].append(row)
                except Exception as error:
                    evidence["continuous_reads"].append({"scenario": scenario, "error": str(error)})
                finally:
                    ready.set()
                stop.wait(0.1)
        thread = threading.Thread(target=read_loop, daemon=True)
        thread.start()
        if not ready.wait(70):
            raise TimeoutError("Observer could not complete the initial query")
        try:
            return writer()
        finally:
            stop.set()
            thread.join(timeout=70)
            if thread.is_alive():
                raise TimeoutError("Observer did not finish")

    def metrics(schema):
        result = {}
        for kind in KINDS:
            table = f"flight_{kind}" + ("_history" if schema == SCHEMA else "")
            files, size, records = store.sql.execute(
                f'SELECT count(*), coalesce(sum(file_size_in_bytes),0), coalesce(sum(record_count),0) '
                f'FROM iceberg.{schema}."{table}$files"'
            )[0]
            snapshots = store.sql.scalar(f'SELECT count(*) FROM iceberg.{schema}."{table}$snapshots"')
            result[kind] = {"current_file_count": files, "current_file_bytes": size,
                            "file_record_count": records, "snapshot_count": snapshots}
        return result

    try:
        flight_id = store.prepare_silver(args.recording)
        evidence["flight_id"] = flight_id
        store.initialize(flight_id)
        evidence["storage_before"] = {SCHEMA: metrics(SCHEMA), BASELINE: metrics(BASELINE)}
        # Seed a complete old release using the real Gold SQL for this sample.
        old = store.begin(flight_id, 300)
        for kind in KINDS:
            store.build(old, kind)
            store.delete_baseline(flight_id, kind)
            store.build(old, kind, baseline=True)
        store.publish(old)
        evidence["seed"] = asdict(old)
        assert_that("seed_complete", checkpoint("seed", "complete")["complete"])

        # Existing protocol: each DELETE and INSERT commits independently.
        legacy = store.begin(flight_id, 180)
        def legacy_writer():
            for kind in KINDS:
                store.delete_baseline(flight_id, kind)
                checkpoint("legacy_success", f"{kind}_deleted", baseline=True)
                store.build(legacy, kind, baseline=True)
                checkpoint("legacy_success", f"{kind}_inserted", baseline=True)
        run_observed("legacy_success", legacy_writer, baseline=True)
        legacy_rows = [r for r in evidence["checkpoints"] if r["scenario"] == "legacy_success"]
        assert_that("legacy_missing_observed", any(not r["complete"] for r in legacy_rows))
        assert_that("legacy_mixed_observed", any(r["mixed"] for r in legacy_rows))

        # Restore only the isolated baseline before the intentional failed rebuild.
        for kind in KINDS:
            store.delete_baseline(flight_id, kind)
            store.build(old, kind, baseline=True)
        failed_legacy = store.begin(flight_id, 180)
        store.delete_baseline(flight_id, "events")
        store.build(failed_legacy, "events", baseline=True)
        failed_row = checkpoint("legacy_failure", "stopped_after_events", baseline=True)
        assert_that("legacy_failure_leaves_mixed", failed_row["mixed"])

        # Proposed protocol: no active pointer changes until every candidate is valid.
        candidate = store.begin(flight_id, 180)
        view_run_before = store.sql.scalar(
            f"SELECT DISTINCT run_id FROM iceberg.{SCHEMA}.flight_events WHERE flight_id = '{flight_id}'"
        )
        def candidate_writer():
            for kind in KINDS:
                store.build(candidate, kind)
                row = checkpoint("publication_success", f"{kind}_built")
                assert_that(f"old_visible_after_{kind}", row["active_run_id"] == old.run_id and row["complete"] and not row["mixed"])
            evidence["candidate_checks"] = store.validate(candidate)
            store.publish(candidate)
            return checkpoint("publication_success", "published")
        published = run_observed("publication_success", candidate_writer)
        assert_that("new_release_visible", published["active_run_id"] == candidate.run_id and published["complete"])
        evidence["candidate"] = asdict(candidate)

        view_run_after = store.sql.scalar(
            f"SELECT DISTINCT run_id FROM iceberg.{SCHEMA}.flight_phases WHERE flight_id = '{flight_id}'"
        )
        evidence["independent_view_reads"] = {
            "events_before_publish": view_run_before,
            "phases_after_publish": view_run_after,
            "crossed_release": view_run_before != view_run_after,
        }
        assert_that("independent_view_reads_can_cross_releases", view_run_before != view_run_after)

        # A consumer that started on old keeps old across multiple SQL statements.
        pinned = checkpoint("pinned_consumer", "old_after_new_publish", pinned=old.run_id)
        assert_that("old_run_still_readable", pinned["complete"] and pinned["runs"] == [old.run_id])

        # Incomplete candidates cannot be published, even when called outside Dagster.
        incomplete = store.begin(flight_id)
        store.build(incomplete, "events")
        try:
            store.publish(incomplete)
        except ValueError as error:
            evidence["incomplete_candidate_rejection"] = str(error)
        else:
            raise AssertionError("Incomplete candidate was published")
        assert_that("incomplete_candidate_keeps_active", store.active(flight_id) == candidate.run_id)

        # Count completeness alone is insufficient. Corrupt only an unpublished
        # test candidate to prove that cross-table semantic validation rejects it.
        invalid = store.begin(flight_id)
        for kind in KINDS:
            store.build(invalid, kind)
        store.sql.execute(
            f"UPDATE iceberg.{SCHEMA}.flight_summary_history SET cruise_min = cruise_min + 1 "
            f"WHERE flight_id = '{flight_id}' AND run_id = '{invalid.run_id}'"
        )
        try:
            store.publish(invalid)
        except ValueError as error:
            evidence["invalid_candidate_rejection"] = str(error)
        else:
            raise AssertionError("Semantically inconsistent candidate was published")
        assert_that("invalid_candidate_keeps_active", store.active(flight_id) == candidate.run_id)

        # Reject a complete but stale candidate built against an older active release.
        stale = store.begin(flight_id)
        stale.previous_run_id = old.run_id
        for kind in KINDS:
            store.build(stale, kind)
        try:
            store.publish(stale)
        except ValueError as error:
            evidence["stale_candidate_rejection"] = str(error)
        else:
            raise AssertionError("Stale candidate was published")
        assert_that("stale_candidate_keeps_active", store.active(flight_id) == candidate.run_id)

        # Actually execute the proposed asset graph, then inject a real Dagster failure.
        from publication_pipeline import materialize
        success = materialize(args.recording)
        assert_that("dagster_success", success.success)
        dagster_candidate = success.output_for_node("published_flight")
        before_failure = store.active(flight_id)
        failure = materialize(args.recording, simulate_failure=True, raise_on_error=False)
        assert_that("dagster_injected_failure", not failure.success)
        failure_row = checkpoint("publication_failure", "dagster_stopped_after_events")
        assert_that("dagster_failure_keeps_release", failure_row["active_run_id"] == before_failure and failure_row["complete"] and not failure_row["mixed"])
        evidence["dagster"] = {"successful_run_id": success.run_id, "failed_run_id": failure.run_id,
                               "published_candidate": asdict(dagster_candidate)}
        retry = materialize(args.recording)
        assert_that("dagster_retry_succeeds", retry.success)
        retry_candidate = retry.output_for_node("published_flight")
        assert_that("retry_uses_new_candidate", retry_candidate.run_id != dagster_candidate.run_id)
        retry_row = checkpoint("publication_retry", "new_run_published")
        assert_that("retry_publishes_complete_release", retry_row["active_run_id"] == retry_candidate.run_id and retry_row["complete"])
        evidence["dagster"]["retry_run_id"] = retry.run_id
        proposed_reads = [r for r in evidence["continuous_reads"] if r["scenario"] == "publication_success"]
        assert_that("continuous_publication_reads_complete", bool(proposed_reads) and all(
            "error" not in r and r["complete"] and not r["mixed"] for r in proposed_reads
        ))
        evidence["storage_after"] = {SCHEMA: metrics(SCHEMA), BASELINE: metrics(BASELINE)}
        evidence["success"] = True
    except Exception as error:
        evidence["success"] = False
        evidence["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        evidence["elapsed_seconds"] = time.perf_counter()-started
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2, default=str))
        lines = ["# Gold publication experiment", "", f"Success: **{evidence.get('success', False)}**", "",
                 "This is an observed local consistency experiment, not a throughput benchmark.", "",
                 "| Scenario | Checkpoint | Rows: events/phases/summary | Mixed | Active run |",
                 "|---|---|---|---|---|"]
        for row in evidence["checkpoints"]:
            lines.append(f"| {row['scenario']} | {row['stage']} | {row['counts']} | {row['mixed']} | {row['active_run_id'] or '-'} |")
        lines += ["", "## Assertions", ""] + [f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in evidence["assertions"].items()]
        lines += ["", "## Concurrent reader", "", "| Protocol | Successful reads | Missing | Mixed | Errors | Median read seconds |", "|---|---|---|---|---|---|"]
        for scenario in ("legacy_success", "publication_success"):
            rows = [r for r in evidence["continuous_reads"] if r["scenario"] == scenario]
            good = [r for r in rows if "error" not in r]
            median = statistics.median(r["read_seconds"] for r in good) if good else 0
            lines.append(f"| {scenario} | {len(good)} | {sum(not r['complete'] for r in good)} | {sum(r['mixed'] for r in good)} | {len(rows)-len(good)} | {median:.3f} |")
        lines += ["", "## Scope", "", "- One serialized publisher per flight; active_runs has no enforced unique key.",
                  "- Multi-query readers resolve run_id once; independently refreshed views can cross releases.",
                  "- Silver input snapshots are pinned independently after Silver finishes; concurrent Silver reload is out of scope.",
                  "- Old candidates must remain available while pinned readers use them; cleanup is not implemented.",
                  "- 180/300-second cruise rules are illustrative POC rules, not approved flight definitions.",
                  "- Baseline follows the original DELETE/INSERT sequence in isolated tables with run_id instrumentation.",
                  "- Current file metrics include delete files when returned by $files; not total bucket bytes or bytes scanned.",
                  "- Hold intervals deliberately expose commit boundaries; do not interpret elapsed time as ingest performance."]
        if "error" in evidence:
            lines += ["", "## Error", "", evidence["error"]]
        (output / "report.md").write_text("\n".join(lines) + "\n")
        print(f"Evidence: {output / 'evidence.json'}", flush=True)
        print(f"Report: {output / 'report.md'}", flush=True)


if __name__ == "__main__":
    main()
