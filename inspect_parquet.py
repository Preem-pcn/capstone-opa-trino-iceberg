# Look inside one decoded rate file: size, columns, and metadata
import sys
import pyarrow.parquet as pq

path = sys.argv[1]
pf = pq.ParquetFile(path)
schema = pf.schema_arrow

print("rows:", pf.metadata.num_rows, "| columns:", len(schema))

# file-level metadata (tail, fap, start_time, ...)
print("\n-- file metadata --")
for k, v in (schema.metadata or {}).items():
    if k != b"ARROW:schema":
        print(f"{k.decode()}: {v.decode()[:80]}")

# the first few columns and their types
print("\n-- first 8 columns --")
for field in list(schema)[:8]:
    print(f"{field.name:28} {field.type}")

# metadata on one column, if a name was given
if len(sys.argv) > 2:
    f = schema.field(sys.argv[2])
    print(f"\n-- metadata on {f.name} --")
    for k, v in (f.metadata or {}).items():
        print(f"{k.decode()}: {v.decode()}")