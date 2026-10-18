"""Add five clearly synthetic recordings to the isolated capstone BI stack.

python scripts/add_demo_flights.py
python scripts/add_demo_flights.py --generate-only

Deterministic IDs make reruns idempotent. Creates only DEMO-* recordings and
uses the existing Silver loader and Gold SQL, not fabricated Gold summaries.
Only ALT_STD (1 Hz), AC_GROUND (4 Hz), and VRTG (8 Hz) are synthesized.
These simplified signals are for testing dashboards, not flight analysis.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.dont_write_bytecode = True
from load_bi_samples import ROOT, execute, literal, main as load_samples, loader

VERSION = "synthetic-bi-v1"
SPECS = [
    ("A350", "DEMO-A01", "VTBS", "RJAA", 330, 39000, 1.18),
    ("B777", "DEMO-B02", "RKSI", "VTBS", 310, 37000, 1.32),
    ("A350", "DEMO-A03", "VTBS", "WSSS", 125, 35000, 1.12),
    ("B777", "DEMO-B04", "VHHH", "VTBS", 160, 36000, 1.42),
    ("A350", "DEMO-A05", "EGLL", "ESSA", 140, 38000, 1.24),
]


def write_rate(folder, start, duration, rate, parameter, values, unit):
    samples = np.arange(duration * rate, dtype=np.int64)
    epoch_ns = int(start.timestamp()) * 1_000_000_000
    timestamps = epoch_ns + samples * (1_000_000_000 // rate)
    schema = pa.schema([
        pa.field("timestamp", pa.timestamp("ns", tz="UTC")),
        pa.field("t_offset_s", pa.float64()),
        pa.field("frame", pa.int32()),
        pa.field(parameter, pa.float64(), metadata={
            b"mnemonic": parameter.encode(), b"unit": unit.encode(),
            b"rate_hz": str(rate).encode(), b"native_name": b"SYNTHETIC DEMO SIGNAL",
        }),
    ], metadata={b"data_source": b"synthetic-demo", b"generator": VERSION.encode()})
    data = pa.Table.from_arrays([
        pa.array(timestamps, type=pa.timestamp("ns", tz="UTC")),
        pa.array(samples.astype(np.float64) / rate),
        pa.array((samples // (rate * 4)).astype(np.int32)),
        pa.array(values, type=pa.float64()),
    ], schema=schema)
    pq.write_table(data, folder / f"rate_{rate}hz.parquet", compression="zstd")


def generate(index, spec, *, start=None, number=None):
    aircraft, tail, origin, destination, airborne_min, altitude, peak_g = spec
    start = start or datetime(2022, 9, 22, 6, tzinfo=timezone.utc) + timedelta(days=index)
    number = number or f"DEMO{index + 1:03d}"
    folder = ROOT / "decoded" / f"{aircraft}_{tail}_{start:%Y%m%d}_{number}_{origin}-{destination}"
    marker = folder / ".synthetic-bi-demo.json"
    specification = {"generator": VERSION, "flight_no": number, "specification": list(spec),
                     "start_time": start.isoformat(), "synthetic": True}
    if folder.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != specification:
            raise RuntimeError(f"Refusing to overwrite an unrecognized recording: {folder.name}")
        if (folder / "report.json").is_file() and all((folder / f"rate_{rate}hz.parquet").is_file() for rate in (1, 4, 8)):
            print("Already generated:", folder.name, flush=True)
            return folder
    folder.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(specification, indent=2) + "\n", encoding="utf-8")
    liftoff = 240
    airborne_s = airborne_min * 60
    touchdown = liftoff + airborne_s - 1
    duration = touchdown + 241
    climb_end = liftoff + 18 * 60
    descent_start = touchdown - 20 * 60
    seconds = np.arange(duration, dtype=np.float64)
    alt = np.interp(seconds, [0, liftoff, climb_end, descent_start, touchdown, duration - 1],
                    [100, 164, altitude, altitude, 164, 100])
    write_rate(folder, start, duration, 1, "ALT_STD", alt, "ft")
    ground_time = np.arange(duration * 4, dtype=np.float64) / 4
    ground = ((ground_time < liftoff) | (ground_time >= touchdown + 1)).astype(np.float64)
    write_rate(folder, start, duration, 4, "AC_GROUND", ground, "boolean")
    g_time = np.arange(duration * 8, dtype=np.float64) / 8
    vertical_g = 1 + (peak_g - 1) * np.exp(-((g_time - (touchdown - 2)) / 0.5) ** 2)
    write_rate(folder, start, duration, 8, "VRTG", vertical_g, "g")
    report = {
        "source": f"synthetic://qar-bi-demo/{VERSION}/{number}",
        "fap": "SYNTHETIC-BI-DEMO", "decoder_version": VERSION,
        "duration_s": duration, "frame_integrity": 1.0,
        "segmentation_signal": "SYNTHETIC_AC_GROUND",
        "metadata": {"start_time": start.isoformat(), "tail_number": tail,
                     "flight_number": number, "origin": origin, "destination": destination},
        "segments": [{"flight_id": "F01", "takeoff_second": liftoff,
                      "touchdown_second": touchdown, "airborne_s": airborne_s}],
        "synthetic": True, "notes": ["GENERATED DEMO DATA. Not a decoded flight recording.",
                                      "Only three signals required by the POC Gold SQL are populated."],
    }
    # Publish report last: interrupted generation is not discovered by the loader.
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Generated:", folder.name, flush=True)
    return folder


def original_summaries():
    try:
        return execute("""SELECT flight_id, aircraft_type, origin, destination, flight_date,
                          airborne_min, cruise_min, max_alt_ft, touchdown_peak_g
                          FROM iceberg.gold.flight_summary
                          WHERE flight_id NOT LIKE 'DEMO-%' ORDER BY flight_id""")
    except Exception as error:
        if getattr(error, "error_name", None) in {"TABLE_NOT_FOUND", "SCHEMA_NOT_FOUND"}:
            return None
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-only", action="store_true", help="Create local decoded-shaped files without loading the database")
    args = parser.parse_args()
    folders = [generate(index, spec) for index, spec in enumerate(SPECS)]
    if args.generate_only:
        print("Generated 5 synthetic recordings. Run scripts/load_bi_samples.py to load them.")
        return
    previous = original_summaries()
    load_samples([])
    ids = [loader.read_flight(folder)["flight_id"] for folder in folders]
    selected = ",".join(literal(fid) for fid in ids)
    for name, expected in [("silver.flights", 5), ("gold.flight_summary", 5),
                           ("gold.flight_phases", 25), ("gold.flight_events", 20)]:
        count = execute(f"SELECT count(*) FROM iceberg.{name} WHERE flight_id IN ({selected})")[0][0]
        if count != expected:
            raise RuntimeError(f"Unexpected synthetic row count in {name}: {count}")
        print(f"PASS synthetic {name}: {count} rows", flush=True)
    if previous is not None and original_summaries() != previous:
        raise RuntimeError("Original flight summary values changed unexpectedly")
    print("PASS original flight summary values preserved; five synthetic flights available", flush=True)


if __name__ == "__main__":
    main()
