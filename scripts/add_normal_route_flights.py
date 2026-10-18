"""Add a repeatable batch of 100 NEW synthetic flights with bell-shaped route counts.

python scripts/add_normal_route_flights.py
python scripts/add_normal_route_flights.py --generate-only

Routes are categories: Gaussian weights apply to the declared route order,
not airport coordinates or flight paths. Existing flights are preserved.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.expressions import In

sys.dont_write_bytecode = True
from add_demo_flights import generate
from load_bi_samples import ROOT, execute, literal, loader, statements, verify

CONFIG = json.loads((ROOT / "bi/normal_routes.json").read_text(encoding="utf-8"))
COUNT = 100
BATCH_SIZE = 10


def plan():
    routes = CONFIG["routes"]
    positions = np.arange(len(routes)) - (len(routes) - 1) / 2
    weights = np.exp(-0.5 * (positions / CONFIG["sigma_in_route_positions"]) ** 2)
    quotas = COUNT * weights / weights.sum()
    counts = np.floor(quotas).astype(int)
    for index in np.argsort(-(quotas - counts), kind="stable")[:COUNT - int(counts.sum())]:
        counts[index] += 1
    rng = np.random.default_rng(CONFIG["seed"])
    assignments = np.repeat(np.arange(len(routes)), counts)
    rng.shuffle(assignments)
    result = []
    for index, route_index in enumerate(assignments):
        route = routes[int(route_index)]
        aircraft = "A350" if rng.random() < 0.62 else "B777"
        minutes = int(np.clip(round(rng.normal(route["airborne_min"], route["airborne_min"] * 0.04)), 55, 800))
        altitude = int(np.clip(round(rng.normal(37000, 1500) / 1000) * 1000, 32000, 41000))
        peak_g = round(float(np.clip(rng.normal(1.22, 0.08), 1.05, 1.50)), 3)
        start = datetime(2022, 10, 1, tzinfo=timezone.utc) + timedelta(days=index // 4, hours=(index % 4) * 6)
        spec = (aircraft, f"DEMO-N{index + 1:04d}", route["origin"], route["destination"], minutes, altitude, peak_g)
        result.append((index, spec, start, f"NORM{index + 1:04d}"))
    return result, counts


def previous_summaries():
    return execute("""SELECT flight_id, aircraft_type, origin, destination, flight_date,
                      airborne_min, cruise_min, max_alt_ft, touchdown_peak_g, built_at
                      FROM iceberg.gold.flight_summary
                      WHERE flight_id NOT LIKE 'DEMO-N%' ORDER BY flight_id""")


def load_silver_batches(folders):
    catalog = load_catalog("capstone_bi", **{
        "type": "rest", "uri": "http://127.0.0.1:9181", "s3.endpoint": "http://127.0.0.1:9100",
        "s3.access-key-id": "rustfsadmin", "s3.secret-access-key": "rustfsadmin", "s3.region": "us-east-1",
    })
    existing = {row[0] for row in execute("SELECT flight_id FROM iceberg.silver.flights")}
    pending = [(folder, loader.read_flight(folder)) for folder in folders
               if loader.read_flight(folder)["flight_id"] not in existing]
    for offset in range(0, len(pending), BATCH_SIZE):
        batch = pending[offset:offset + BATCH_SIZE]
        ids = [flight["flight_id"] for _, flight in batch]
        for rate in (1, 4, 8):
            name = f"rate_{rate}hz"
            data = pa.concat_tables([loader.prepare(folder / f"{name}.parquet", flight) for folder, flight in batch])
            table = loader.ensure_table(catalog, name, data)
            table.overwrite(data, overwrite_filter=In("flight_id", ids))
        flights = catalog.load_table(("silver", "flights"))
        data = pa.Table.from_pylist([flight for _, flight in batch], schema=flights.schema().as_arrow())
        # Metadata is published last, so retry repairs partially loaded batches.
        flights.overwrite(data, overwrite_filter=In("flight_id", ids))
        print(f"Silver: {min(offset + BATCH_SIZE, len(pending))}/{len(pending)} new flights loaded", flush=True)
    if not pending:
        print("Silver: all 100 flights already loaded", flush=True)


def load_gold_batches(ids):
    # Reuse the per-flight SQL, widening only its equality predicates to a batch.
    # Limit the event-detection window to 10 flights for the 1 GB demo JVM.
    tables = [("flight_events", 4), ("flight_phases", 5), ("flight_summary", 1)]
    existing = {name: dict(execute(f"SELECT flight_id,count(*) FROM iceberg.gold.{name} WHERE flight_id LIKE 'DEMO-N%' GROUP BY flight_id"))
                for name, _ in tables}
    for offset in range(0, len(ids), BATCH_SIZE):
        batch = ids[offset:offset + BATCH_SIZE]
        selected = ",".join(literal(fid) for fid in batch)
        complete = all(existing[name].get(fid) == expected for name, expected in tables for fid in batch)
        if not complete:
            for name in ("events", "phases", "summary"):
                for statement in statements(f"sql/05_gold_{name}.sql"):
                    if "= '{flight_id}'" not in statement:
                        raise RuntimeError("Gold SQL template changed; review batch scoping before running")
                    scoped = statement.replace("= '{flight_id}'", "IN (" + selected + ")")
                    execute(scoped)
        print(f"Gold: {min(offset + BATCH_SIZE, len(ids))}/{len(ids)} new flights ready", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()
    planned, expected_counts = plan()
    for route, count in zip(CONFIG["routes"], expected_counts):
        print(f'Route {route["origin"]}-{route["destination"]}: {count}', flush=True)
    folders = [generate(index, spec, start=start, number=number) for index, spec, start, number in planned]
    if args.generate_only:
        print("Generated the repeatable batch of 100 synthetic flights", flush=True)
        return
    previous = previous_summaries()
    load_silver_batches(folders)
    ids = [loader.read_flight(folder)["flight_id"] for folder in folders]
    load_gold_batches(ids)
    all_folders = sorted(path.parent for path in (ROOT / "decoded").glob("*/report.json"))
    verify(all_folders)
    selected = ",".join(literal(fid) for fid in ids)
    actual = Counter({(row[0], row[1]): row[2] for row in execute(
        f"SELECT origin,destination,count(*) FROM iceberg.gold.flight_summary WHERE flight_id IN ({selected}) GROUP BY origin,destination")})
    expected = Counter({(route["origin"], route["destination"]): int(count)
                        for route, count in zip(CONFIG["routes"], expected_counts)})
    if actual != expected or sum(actual.values()) != COUNT:
        raise RuntimeError("Gold route distribution differs from the planned Gaussian weights")
    if previous_summaries() != previous:
        raise RuntimeError("An existing flight summary changed unexpectedly")
    print("PASS 100 new flights, exact planned route counts, and existing summaries unchanged", flush=True)


if __name__ == "__main__":
    main()
