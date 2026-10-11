#1
docker compose up -d       
docker exec -it trino trino

SHOW CATALOGS;
CREATE SCHEMA iceberg.sandbox;
CREATE TABLE iceberg.sandbox.hello (id INTEGER, msg VARCHAR);
INSERT INTO iceberg.sandbox.hello VALUES (1, 'first'), (2, 'second');
INSERT INTO iceberg.sandbox.hello VALUES (3, 'third');
SELECT * FROM iceberg.sandbox.hello;

SELECT snapshot_id, operation, committed_at
FROM iceberg.sandbox."hello$snapshots";

SELECT * FROM iceberg.sandbox.hello FOR VERSION AS OF <paste_id>;

# 2
CREATE SCHEMA IF NOT EXISTS iceberg.silver;

CREATE TABLE iceberg.silver.flights (
  flight_id            VARCHAR COMMENT '<tail>_<start yyyymmddThhmmss>_<segment>',
  recording            VARCHAR COMMENT 'decoded folder name',
  aircraft_type        VARCHAR COMMENT 'A350 / B777, from folder name',
  tail                 VARCHAR,
  flight_no            VARCHAR COMMENT 'may be a placeholder (TG0000) or missing',
  origin               VARCHAR COMMENT 'from report, else folder name',
  destination          VARCHAR,
  flight_date          DATE    COMMENT 'start_time date, UTC',
  start_time           TIMESTAMP(6) WITH TIME ZONE,
  duration_s           DOUBLE,
  fap                  VARCHAR,
  decoder_version      VARCHAR,
  frame_integrity      DOUBLE,
  suspect_params       ARRAY(VARCHAR) COMMENT 'parameter-level quality from report.json',
  segmentation_signal  VARCHAR,
  dec_takeoff_s        INTEGER COMMENT 'decoder segmentation: oracle for Gold',
  dec_touchdown_s      INTEGER,
  source_file          VARCHAR,
  loaded_at            TIMESTAMP(6) WITH TIME ZONE
)
COMMENT 'One row per flight, built from report.json';


SHOW TABLES FROM iceberg.silver;


#3
-- python load_silver.py ~/Documents/capstone-qar/qar-data/decoded/A350_HS-THJ_20220322_TG0341_VTBS-OPKC
python load_silver.py decoded/A350_HS-THJ_20220322_TG0341_VTBS-OPKC


SHOW TABLES FROM iceberg.silver;

SELECT flight_id, tail, flight_no, origin, destination, dec_takeoff_s, dec_touchdown_s
FROM iceberg.silver.flights;

SELECT flight_id, count(*) AS rows
FROM iceberg.silver.rate_1hz
GROUP BY flight_id
ORDER BY flight_id;

--load all flight
python load_silver.py decoded/A350_*

SELECT flight_id, count(*) AS rows
FROM iceberg.silver.rate_1hz
GROUP BY flight_id;

SELECT committed_at, operation,
       element_at(summary, 'added-records')   AS added,
       element_at(summary, 'deleted-records') AS deleted
FROM iceberg.silver."rate_1hz$snapshots"
ORDER BY committed_at;


# 4
docker cp sql/04_gold.sql trino:/tmp/04_gold.sql
docker exec trino trino --file /tmp/04_gold.sql

SHOW TABLES FROM iceberg.gold;

SELECT flight_id, event, t_offset_s, value, unit
FROM iceberg.gold.flight_events ORDER BY flight_id, t_offset_s;

SELECT flight_id, phase, start_s, end_s, round(duration_s / 60.0, 1) AS minutes
FROM iceberg.gold.flight_phases ORDER BY flight_id, phase_order;

SELECT flight_id, airborne_min, cruise_min, max_alt_ft, touchdown_peak_g,
       hard_landing, liftoff_delta_s, touchdown_delta_s
FROM iceberg.gold.flight_summary ORDER BY flight_id;


docker cp sql/04_gold_checks.sql trino:/tmp/04_gold_checks.sql
docker exec trino trino --file /tmp/04_gold_checks.sql --output-format ALIGNED

# 5
export DAGSTER_HOME=$PWD/dagster_home
dagster dev -f qar_pipeline.py

SELECT flight_id, airborne_min, touchdown_peak_g, liftoff_delta_s, touchdown_delta_s
FROM iceberg.gold.flight_summary ORDER BY flight_id;