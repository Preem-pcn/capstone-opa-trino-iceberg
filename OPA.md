# OPA governance PoC

Trino 483 asks OPA whether an operation is permitted, which rows the caller can
read, and which column expressions to return. Iceberg and RustFS keep the original
data; masks and filters apply at query time.

```text
User / Dagster -> Trino -> OPA policy decision
                   |
                   +-> Iceberg REST catalog -> RustFS data files
```

This is a local authorization PoC. Usernames are supplied by the caller; there
is no login. Direct PyIceberg, REST catalog, and RustFS access does not pass
through Trino and is outside this policy.

## Mock users and departments

| User | Visible rows | Column behavior | Writes |
| --- | --- | --- | --- |
| admin | All | Original values | Yes |
| dagster | All | Original values | Yes (existing pipeline identity) |
| publication_lab | All | Original values | Yes (existing publication experiment identity) |
| safety_analyst | All approved Silver/Gold tables | recording/source_file masked | No |
| operations_analyst | Flights arriving at or departing from VTBS | tail/recording/source_file masked; flight_id pseudonymized; touchdown_peak_g denied in flight_summary | No |
| engineering_analyst | Flights from aircraft HS-THJ | flight_no/origin/destination masked | No |
| blocked_user or any unknown user | None | Query denied | No |

These assignments are mock requirements, not real airline access rules. Each
department maps to a flight scope. The source data does not have a department
column.

The three privileged users have broad permissions for this PoC. OPA preserves
the existing Dagster and publication experiment identities. Calls through
PyIceberg still write directly to Iceberg without an OPA decision.

## Allowed tables

Analysts can read the following tables in the real silver/gold schemas and
equivalent isolated opa_demo_silver/opa_demo_gold schemas:

- Silver: flights, rate_0p25hz, rate_0p5hz, rate_1hz, rate_2hz, rate_4hz, rate_7hz, rate_8hz
- Gold: flight_events, flight_phases, flight_summary

Other schemas, unlisted tables, Iceberg metadata tables such as flights$files
and flights$snapshots are denied. Only information_schema.schemata/tables/columns
are permitted for filtered discovery; other information_schema tables are denied.
Hidden system columns ($path, $partition, $file_modified_time) are also denied,
so analysts cannot recover storage paths through those columns.
New tables must be added to the policy explicitly. SHOW TABLES and SHOW SCHEMAS
only list approved objects. SHOW CREATE TABLE is privileged-user-only.

Bronze is currently an archive of original files rather than a Trino table.
Control its file access in the storage system; there are no Bronze columns for
this Trino policy to filter.

Column masks are consistent across approved Silver and Gold tables.
flight_id contains the aircraft tail in this dataset, so Operations receives a
stable SHA-256 pseudonym. The same flight returns the same pseudonym in each
table, allowing joins. This is pseudonymization, not guaranteed anonymization.
Operations must select approved columns explicitly: SELECT * on flight_summary
is denied because touchdown_peak_g is blocked.

Both column masking and object/column discovery use Trino's batch OPA endpoints.
QAR tables can contain thousands of columns; requesting each mask separately can
overflow Trino's HTTP request queue. Batch requests retain the same restrictions
without sending one HTTP request per column.

## Start and verify

From the project directory, with Docker running:

```sh
cd /Users/preem/4term1/capstone/trino-iceberg-poc
docker compose up -d opa trino
docker compose ps
python3 verify_opa.py
```

Wait for Trino to become healthy before running verification. The verifier only
needs Python 3 and Docker, using the Trino CLI inside the container.

The verifier creates three synthetic flights in isolated demo schemas:

| Flight ID | Aircraft | Route | Engineering | Operations |
| --- | --- | --- | --- | --- |
| HS-THJ_DEMO_01 | HS-THJ | VTBS -> OPKC | Visible | Visible |
| HS-THE_DEMO_02 | HS-THE | RKSI -> VTBS | Hidden | Visible |
| HS-TKN_DEMO_03 | HS-TKN | EGLL -> ESSA | Hidden | Hidden |

The fixtures remain available for demonstrations. The script never builds or
replaces real Silver/Gold tables. It checks any existing real QAR tables
read-only and reports which tables were available.

Evidence is written to results/opa_policy_evidence.json, with exact expected and
actual rows, masks, stable joins, time-travel filtering, denied metadata/history
access, filtered discovery, wide-table queries, analyst write denials, and service
writes. Only an actual Access Denied
error counts as a successful denial; syntax or connection errors fail the run.
Each run replaces this evidence file. Use --output to preserve separate runs:

```sh
python3 verify_opa.py --output results/opa_review_r2.json
```

## Demonstrate the same SQL under different identities

Open an interactive SQL session as a department:

```sh
docker exec -it trino trino --user operations_analyst --catalog iceberg
```

Or run one query at a time:

```sh
docker exec trino trino --user admin --output-format ALIGNED \
  --execute "SELECT flight_id, tail, origin, destination FROM iceberg.opa_demo_silver.flights"

docker exec trino trino --user operations_analyst --output-format ALIGNED \
  --execute "SELECT flight_id, tail, origin, destination FROM iceberg.opa_demo_silver.flights"

docker exec trino trino --user engineering_analyst --output-format ALIGNED \
  --execute "SELECT flight_id, tail, origin, destination FROM iceberg.opa_demo_silver.flights"

docker exec trino trino --user safety_analyst --output-format ALIGNED \
  --execute "SELECT flight_id, source_file FROM iceberg.opa_demo_silver.flights"

docker exec trino trino --user operations_analyst \
  --execute "SELECT touchdown_peak_g FROM iceberg.opa_demo_gold.flight_summary"

docker exec trino trino --user blocked_user \
  --execute "SELECT count(*) FROM iceberg.opa_demo_gold.flight_summary"
```

Expected: admin sees 3 flights; Operations sees 2 with masked tail and
pseudonymized IDs; Engineering sees 1 with masked route; Safety sees 3 with
masked source paths; the last two queries return Access Denied.

Use iceberg.silver.flights or iceberg.gold.flight_summary instead of the demo
table names to query real data. All policies still apply.

## Change a policy or stop

Edit opa/trino.rego, validate it, then restart OPA to load changes:

```sh
docker compose exec -T opa /opa check /policies/trino.rego
docker compose restart opa
python3 verify_opa.py
```

For a Trino access-control.properties change, restart Trino as well.

Stop without removing the containers:

```sh
docker compose stop
```

The existing stack stores the REST catalog's SQLite database inside the container
and has no persistent storage volume for RustFS. Do not use docker compose down
to preserve this PoC's current data; removing those containers can lose it.

## Files

- opa/trino.rego: allowed objects, row scopes, masks, and denied columns
- trino/access-control.properties: allow/filter/mask endpoints
- docker-compose.yaml: OPA service and mounted Trino configuration
- verify_opa.py: isolated fixtures, real-table checks, and JSON evidence

Reference: [Trino 483 OPA documentation](https://trino.io/docs/current/security/opa-access-control.html).
