"""Step 3 — load decoded QAR recordings into the Silver Iceberg tables.

Usage (from your project folder, with the venv active):
    python load_silver.py ~/Documents/capstone-qar/qar-data/decoded/A350_*

One recording folder = one flight (the POC expects exactly one segment).
Re-running is safe: each table's rows for that flight are replaced, not added.
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import EqualTo
from pyiceberg.transforms import IdentityTransform

NAMESPACE = "silver"

# The first load of a flight has nothing to replace yet, so the delete half
# of overwrite() matches no rows and PyIceberg warns. That's expected here.
warnings.filterwarnings("ignore", message="Delete operation did not match any records")

# Decoder metadata that describes a parameter's native identity.
# It goes into the column comment. fap / decoder_version are left out on
# purpose: they can change from flight to flight, so they live on every row.
NATIVE_KEYS = (
    "mnemonic", "native_name", "unit", "rate_hz", "samples_per_frame",
    "bits", "signed", "encoding", "superframe", "digit_widths",
    "locations", "labels",
)


def get_catalog() -> Catalog:
    """Connect to the Iceberg REST catalog.

    This script runs on your Mac, outside Docker's private network, so it
    uses localhost -- not the container names (iceberg-rest, rustfs) that
    Trino uses from inside the network.
    """
    return load_catalog(
        "lake",
        **{
            "type": "rest",
            "uri": "http://localhost:8181",          # catalog: table name -> metadata file
            "s3.endpoint": "http://localhost:9000",  # RustFS: where data files get written
            "s3.access-key-id": "rustfsadmin",
            "s3.secret-access-key": "rustfsadmin",
            "s3.region": "us-east-1",
        },
    )


# ---------------------------------------------------------------------------
# 1. Flight-level facts: report.json + folder name -> one silver.flights row
# ---------------------------------------------------------------------------

def read_flight(folder: Path) -> dict:
    report = json.loads((folder / "report.json").read_text())
    meta = report.get("metadata", {})

    # Folder name: <type>_<tail>_<yyyymmdd>[_<flight no>]_<origin>-<destination>
    parts = folder.name.split("_")
    aircraft_type, folder_tail = parts[0], parts[1]
    route = parts[-1].split("-") if "-" in parts[-1] else [None, None]
    folder_flight_no = parts[3] if len(parts) == 5 else None

    segments = report.get("segments", [])
    if len(segments) != 1:
        raise ValueError(f"{folder.name}: {len(segments)} segments; the POC handles exactly 1")
    seg = segments[0]

    start = datetime.fromisoformat(meta["start_time"]).astimezone(timezone.utc)
    tail = meta.get("tail_number") or folder_tail

    return {
        # Flight numbers can be placeholders (TG0000) or missing, so the ID
        # is built from tail + recorded start time + segment instead.
        "flight_id": f"{tail}_{start:%Y%m%dT%H%M%S}_{seg['flight_id']}",
        "recording": folder.name,
        "aircraft_type": aircraft_type,
        "tail": tail,
        "flight_no": meta.get("flight_number") or folder_flight_no,
        "origin": meta.get("origin") or route[0],
        "destination": meta.get("destination") or route[1],
        "flight_date": start.date(),
        "start_time": start,
        "duration_s": float(report["duration_s"]),
        "fap": report["fap"],
        "decoder_version": report["decoder_version"],
        "frame_integrity": float(report["frame_integrity"]),
        "suspect_params": list(report.get("suspect", [])),
        "segmentation_signal": report.get("segmentation_signal"),
        "dec_takeoff_s": int(seg["takeoff_second"]),
        "dec_touchdown_s": int(seg["touchdown_second"]),
        "source_file": report.get("source"),
        "loaded_at": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# 2. Time series: one rate file -> an Arrow table shaped for Silver
# ---------------------------------------------------------------------------

def column_doc(field: pa.Field) -> str | None:
    """Turn the decoder's per-column metadata into a compact JSON comment."""
    md = {k.decode(): v.decode() for k, v in (field.metadata or {}).items()}
    native = {k: md[k] for k in NATIVE_KEYS if md.get(k)}
    return json.dumps(native, separators=(",", ":")) if native else None


def prepare(path: Path, flight: dict) -> pa.Table:
    raw = pq.read_table(path)
    n = raw.num_rows

    # Timestamps: nanoseconds -> microseconds (Iceberg v2's precision).
    # ROUND, don't truncate: the decoder writes some instants as
    # ...10.999999999 instead of 11.000000000 (floating-point error), and
    # truncating would push them off the whole second.
    ns = raw.column("timestamp").cast(pa.int64())
    ts = pc.divide(pc.add(ns, 500), 1000).cast(pa.timestamp("us", tz="UTC"))

    def const(value, typ):  # the same value on every row (nearly free in Parquet)
        return pa.array([value] * n, typ)

    fields = [
        pa.field("flight_id", pa.string()),
        pa.field("aircraft_type", pa.string()),
        pa.field("flight_date", pa.date32()),
        pa.field("ts", pa.timestamp("us", tz="UTC"), metadata={"doc": "sample time, UTC"}),
        pa.field("t_offset_s", pa.float64(), metadata={"doc": "seconds since recording start"}),
        pa.field("frame", pa.int32(), metadata={"doc": "ARINC 717 frame index"}),
    ]
    arrays = [
        const(flight["flight_id"], pa.string()),
        const(flight["aircraft_type"], pa.string()),
        const(flight["flight_date"], pa.date32()),
        ts,
        raw.column("t_offset_s"),
        raw.column("frame"),
    ]

    # Parameter columns: lower-case name (Trino shows every name in lower
    # case anyway); the native mnemonic and the rest go in the comment.
    for field in raw.schema:
        if field.name in ("timestamp", "t_offset_s", "frame"):
            continue
        doc = column_doc(field)
        fields.append(pa.field(field.name.lower(), field.type,
                               metadata={"doc": doc} if doc else None))
        arrays.append(raw.column(field.name))

    # Versions on every row, so a mixed table can always be split by them.
    fields += [pa.field("fap", pa.string()), pa.field("decoder_version", pa.string())]
    arrays += [const(flight["fap"], pa.string()), const(flight["decoder_version"], pa.string())]

    names = [f.name for f in fields]
    if len(names) != len(set(names)):
        dupes = sorted({x for x in names if names.count(x) > 1})
        raise ValueError(f"{path.name}: names collide after lower-casing: {dupes}")

    # Iceberg doesn't sort for us when Python writes, so sort here.
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields)).sort_by("ts")


# ---------------------------------------------------------------------------
# 3. Iceberg: create a table on first sight, then replace one flight's rows
# ---------------------------------------------------------------------------

def ensure_table(catalog: Catalog, name: str, data: pa.Table):
    ident = (NAMESPACE, name)
    try:
        table = catalog.load_table(ident)
    except NoSuchTableError:
        # First load: schema comes from the data. Partitioning and sort order
        # are set in the same transaction, so the table never exists without them.
        with catalog.create_table_transaction(ident, schema=data.schema) as txn:
            with txn.update_spec() as spec:          # partition folders
                spec.add_identity("aircraft_type")
                spec.add_identity("flight_date")
            with txn.update_sort_order() as order:   # row order inside each file
                order.asc("flight_id", IdentityTransform())
                order.asc("ts", IdentityTransform())
        return catalog.load_table(ident)

    # Later loads: add only the columns the table doesn't have yet (schema
    # evolution). Existing columns keep the comment from their first load:
    # decoder metadata can differ slightly between recordings, and rewriting
    # comments on every load would create a new schema version each time.
    existing = {f.name for f in table.schema().fields}
    new_fields = [f for f in data.schema if f.name not in existing]
    if new_fields:
        with table.update_schema() as update:
            update.union_by_name(pa.schema(new_fields))
    return table


def replace_flight(table, data: pa.Table, flight_id: str) -> None:
    """Idempotent write: drop this flight's old rows, add the new ones."""
    table.overwrite(data, overwrite_filter=EqualTo("flight_id", flight_id))


def load_recording(catalog: Catalog, folder: Path) -> tuple[str, dict[str, int]]:
    """Load one recording. Returns its flight_id and the rows written per table."""
    # Check silver.flights exists before writing anything (Step 2 creates it in Trino).
    flights = catalog.load_table((NAMESPACE, "flights"))

    flight = read_flight(folder)
    fid = flight["flight_id"]
    counts: dict[str, int] = {}
    print(f"\n{folder.name}\n  flight_id = {fid}")

    # Time series: one Silver table per rate file (rate_1hz.parquet -> silver.rate_1hz)
    for path in sorted(folder.glob("rate_*.parquet")):
        data = prepare(path, flight)
        table = ensure_table(catalog, path.stem, data)
        replace_flight(table, data, fid)
        counts[path.stem] = data.num_rows
        print(f"  {NAMESPACE}.{path.stem:<12} {data.num_rows:>8,} rows  {data.num_columns:>5} cols")

    # Flight row last: if anything above failed, the flight isn't listed yet.
    row = pa.Table.from_pylist([flight], schema=flights.schema().as_arrow())
    replace_flight(flights, row, fid)
    counts["flights"] = 1
    print(f"  {NAMESPACE}.flights      1 row")
    return fid, counts


def main(folders: list[str]) -> None:
    if not folders:
        sys.exit(__doc__)
    catalog = get_catalog()
    for f in folders:
        load_recording(catalog, Path(f).expanduser())


if __name__ == "__main__":
    main(sys.argv[1:])