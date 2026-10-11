# Gold publication experiment

Success: **True**

This is an observed local consistency experiment, not a throughput benchmark.

| Scenario | Checkpoint | Rows: events/phases/summary | Mixed | Active run |
|---|---|---|---|---|
| seed | complete | [4, 5, 1] | False | f0c332a321674c069acb087810ef84d7 |
| legacy_success | events_deleted | [0, 5, 1] | False | - |
| legacy_success | events_inserted | [4, 5, 1] | True | - |
| legacy_success | phases_deleted | [4, 0, 1] | True | - |
| legacy_success | phases_inserted | [4, 5, 1] | True | - |
| legacy_success | summary_deleted | [4, 5, 0] | False | - |
| legacy_success | summary_inserted | [4, 5, 1] | False | - |
| legacy_failure | stopped_after_events | [4, 5, 1] | True | - |
| publication_success | events_built | [4, 5, 1] | False | f0c332a321674c069acb087810ef84d7 |
| publication_success | phases_built | [4, 5, 1] | False | f0c332a321674c069acb087810ef84d7 |
| publication_success | summary_built | [4, 5, 1] | False | f0c332a321674c069acb087810ef84d7 |
| publication_success | published | [4, 5, 1] | False | 4191d47d8c8140d5bdb9aa87d58f5b02 |
| pinned_consumer | old_after_new_publish | [4, 5, 1] | False | f0c332a321674c069acb087810ef84d7 |
| publication_failure | dagster_stopped_after_events | [4, 5, 1] | False | a1375345c8e04ef2afa580249c7d70cd |

## Assertions

- seed_complete: PASS
- legacy_missing_observed: PASS
- legacy_mixed_observed: PASS
- legacy_failure_leaves_mixed: PASS
- old_visible_after_events: PASS
- old_visible_after_phases: PASS
- old_visible_after_summary: PASS
- new_release_visible: PASS
- old_run_still_readable: PASS
- incomplete_candidate_keeps_active: PASS
- stale_candidate_keeps_active: PASS
- dagster_success: PASS
- dagster_injected_failure: PASS
- dagster_failure_keeps_release: PASS
- continuous_publication_reads_complete: PASS

## Concurrent reader

| Protocol | Successful reads | Missing | Mixed | Errors | Median read seconds |
|---|---|---|---|---|---|
| legacy_success | 31 | 18 | 13 | 0 | 0.075 |
| publication_success | 22 | 0 | 0 | 0 | 0.093 |

## Scope

- One serialized publisher per flight; active_runs has no enforced unique key.
- Multi-query readers resolve run_id once; independently refreshed views can cross releases.
- Silver input snapshots are pinned independently after Silver finishes; concurrent Silver reload is out of scope.
- Old candidates must remain available while pinned readers use them; cleanup is not implemented.
- 180/300-second cruise rules are illustrative POC rules, not approved flight definitions.
- Baseline follows the original DELETE/INSERT sequence in isolated tables with run_id instrumentation.
- Current file metrics include delete files when returned by $files; not total bucket bytes or bytes scanned.
- Hold intervals deliberately expose commit boundaries; do not interpret elapsed time as ingest performance.
