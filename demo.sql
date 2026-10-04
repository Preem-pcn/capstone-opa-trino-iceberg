#1
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


#3
python load_silver.py ~/Documents/capstone-qar/qar-data/decoded/A350_HS-THJ_20220322_TG0341_VTBS-OPKC

SHOW TABLES FROM iceberg.silver;

SELECT flight_id, tail, flight_no, origin, destination, dec_takeoff_s, dec_touchdown_s
FROM iceberg.silver.flights;

SHOW COLUMNS FROM iceberg.silver.rate_8hz LIKE 'vrtg';

SELECT f.flight_id, max(r.vrtg) AS peak_g
FROM iceberg.silver.rate_8hz r
JOIN iceberg.silver.flights f ON r.flight_id = f.flight_id
WHERE r.t_offset_s BETWEEN f.dec_touchdown_s - 5 AND f.dec_touchdown_s + 10
GROUP BY f.flight_id;