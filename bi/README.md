# Gold Reports จาก capstone-opa-trino-iceberg

เดโมนี้ใช้ข้อมูล `decoded/` และ Gold SQL ของ checkout นี้โดยตรง
เปิด stack แยกด้วย `docker-compose.bi-local.yaml` (ไม่ merge กับ compose เดิม)
ชื่อ project คือ `qar-capstone-bi` ไม่ใช้ container, catalog หรือ object storage ของ
`C:\QAR\trino-iceberg-poc` และไม่แก้ policy OPA เดิม

## เปิดใช้งาน

เปิด Docker Desktop แล้วรัน PowerShell:

ใช้ Python environment ที่มี dependencies ของ loader เดิม (`pyarrow`, `pyiceberg`, `trino`)
นำไฟล์ decoded ของตัวเองไว้ใน `decoded/` เพราะข้อมูลเหล่านี้ไม่ได้เก็บใน Git

```powershell
cd C:\QAR\capstone-opa-trino-iceberg
powershell -File scripts/start_bi_demo.ps1
```

เปิดเว็บ **http://localhost:8766/#gold**
พอร์ต 8765 คือเดโมเก่าจากอีก repo ไม่ใช่หน้าใหม่นี้

| Service | URL / port ฝั่งเครื่อง |
| --- | --- |
| เว็บ QAR | http://localhost:8766/#gold |
| Metabase | http://localhost:3002 |
| Trino | http://localhost:8083 |
| Iceberg REST | http://localhost:9181 |
| RustFS S3 / console | 9100 / 9101 |
| OPA | http://localhost:9282 |

พอร์ตทั้งหมด bind เฉพาะ loopback มี named volumes แยกสำหรับ RustFS,
SQLite catalog และ Metabase H2 พร้อมกำหนด memory limits สำหรับเครื่องเดโม
บัญชี admin ของ Metabase และ embedding key อยู่ใน `.secrets/` ที่ Git ignore
ไม่ใส่ credentials หรือ embedding key ลง HTML

## ข้อมูลที่ใช้

`scripts/load_bi_samples.py` อ่าน recording ที่มี `report.json` ใน `decoded/` ของ repo นี้
ใช้ `load_silver.load_recording()` เดิมสร้าง Silver และใช้ `sql/04_gold.sql` เดิมสร้าง Gold
ไม่ได้ย้ายตารางหรือคัดลอกข้อมูลจาก stack เก่า ตัว loader ไม่สร้าง synthetic flight ขึ้นเอง
รอบนี้เรียก loader/SQL โดยตรง ไม่ได้รัน Dagster materialization

เที่ยวบินตัวอย่างทั้งสามมาจากโฟลเดอร์:

- `A350_HS-THJ_20220322_TG0341_VTBS-OPKC`
- `A350_HS-THE_20220826_TG0000_VTBS-RKSI`
- `A350_HS-THJ_20220921_TG0000_ESSA-VTBS`

เมื่อโหลดเฉพาะข้อมูลจริงข้างต้น จะได้ Silver flights 3 แถว, Gold summaries 3 แถว, phases 15 แถว และ events 12 แถว
ตรวจ quality gates เดิมทั้ง 3 ข้อ: phase coverage, event order และ segmentation delta
การรันซ้ำข้าม recording ที่มี Silver flight metadata แล้ว และไม่ rebuild Gold หากครบอยู่แล้ว
ไม่ได้ตั้งให้ตรวจจับการแก้ไฟล์ decoded ที่โหลดสำเร็จไปแล้วโดยอัตโนมัติ

### เพิ่มเที่ยวบินจำลองอีก 5 เที่ยวบิน

เมื่อเปิด stack แล้ว รัน:

สคริปต์จำลองใช้ `numpy` เพิ่มจาก dependencies ของ loader เดิม

```powershell
python scripts/add_demo_flights.py
python scripts/setup_bi_demo.py
```

คำสั่งแรกสร้าง recording จำลองที่มีชื่อ tail `DEMO-*` และ flight number `DEMO001`–`DEMO005`
ใน `decoded/` แล้วโหลดผ่าน Silver → Gold ด้วย loader/SQL เดิม คำสั่งที่สองอัปเดต cards
เพื่อแสดงคอลัมน์ `data_source` แยก `Synthetic demo` กับ `Decoded recording`
จากนั้นกด Refresh dashboard ในหน้าเว็บ

เพิ่ม A350 3 เที่ยวบินและ B777 2 เที่ยวบิน วันที่ 22–26 กันยายน 2022
เส้นทาง VTBS–RJAA, RKSI–VTBS, VTBS–WSSS, VHHH–VTBS และ EGLL–ESSA
รวมกับข้อมูลจริงเป็น 8 summaries, 40 phases และ 32 events
ข้อมูลจำลองมีเฉพาะ ALT_STD 1 Hz, AC_GROUND 4 Hz และ VRTG 8 Hz
ซึ่งจำเป็นสำหรับ Gold SQL นี้ คอลัมน์ sensor อื่นในสาม rate tables นี้เป็น null
และไม่ได้สร้างข้อมูล rate อื่น ไม่ใช่การจำลอง QAR ครบทุก parameter
รายงาน JSON/Parquet ระบุแหล่งข้อมูล synthetic ชัดเจน ค่าเวลา/ความสูง/g สร้างขึ้นเพื่อทดสอบ UI
ไม่ใช่ค่าที่วัดจากเที่ยวบินจริงหรือข้อมูลสำหรับวิเคราะห์ความปลอดภัย

ใช้ ID และวันที่คงที่ รันซ้ำไม่เพิ่มเที่ยวบินซ้ำ ไม่เขียนทับ recording จริง
สคริปต์ตรวจ quality gates เดิม, จำนวนแถวจำลอง และค่าของ summary เที่ยวบินจริงว่าไม่เปลี่ยน
ไฟล์จำลองถูก Git ignore เหมือน decoded อื่น ผู้ที่ clone repo สามารถสร้างใหม่ด้วยสคริปต์นี้
ใช้ `--generate-only` หากต้องการสร้างไฟล์ก่อนโดยยังไม่เชื่อมฐานข้อมูล
เมื่อรัน startup/loader ครั้งถัดไป ระบบจะพบ report.json เหล่านี้และโหลดตามปกติ

### เพิ่มอีก 100 เที่ยวบินโดยให้จำนวนต่อ route เป็นโค้งระฆัง

```powershell
python scripts/add_normal_route_flights.py
python scripts/setup_bi_demo.py
```

เป็นชุดใหม่ 100 เที่ยวบิน (`NORM0001`–`NORM0100`, tail `DEMO-N*`)
เพิ่มจาก 8 เที่ยวบินเดิม รวมเป็น 108 summaries, 540 phases และ 432 events
วันที่ 1–25 ตุลาคม 2022 ใช้ seed 42 เพื่อให้สร้างซ้ำได้เหมือนเดิม
จำนวนเที่ยวบินตามลำดับ routes ใน `normal_routes.json` คือ
`1, 4, 12, 21, 25, 21, 11, 4, 1` รวม 100
คำนวณจาก Gaussian weights ที่ sigma = 1.6 ตำแหน่ง route แล้วปัดจำนวนให้รวมครบ 100
route เป็นหมวดหมู่ จึงเป็นการกระจายตามลำดับที่กำหนด ไม่ใช่ normal distribution ของพิกัดสนามบิน
ลำดับนี้จัดเพื่อทดสอบกราฟ ไม่ใช่อันดับความนิยมจริงหรืออันดับระยะทาง

กราฟ Flights by route เรียงตามลำดับนี้เพื่อให้เห็นรูปโค้งระฆัง
เมื่อรวมเที่ยวบินเดิมอีก 8 รายการ แต่ละ route จะมีจำนวนต่างจากชุด 100 ใหม่นี้เล็กน้อย
ไฟล์ config มี 9 routes และเวลา airborne อ้างอิงสำหรับสร้างสัญญาณจำลอง
เวลา airborne, aircraft type, altitude และ peak g มี variation แบบ deterministic
ค่าเหล่านี้เป็นข้อมูลสร้างขึ้นสำหรับเดโมเช่นเดียวกับชุด 5 เที่ยวบิน

สคริปต์โหลด Silver ทีละ 10 เที่ยวบิน และใช้ SQL per-flight เดิมใน `sql/05_gold_*.sql`
โดยเปลี่ยนเงื่อนไขเท่ากับ ID เดียวเป็น IN ของ ID ใน batch เท่านั้น
events → phases → summary ยังใช้กฎเดิม แต่ประมวลผลทีละ batch เพื่อจำกัด memory
ไม่ rebuild Gold ของเที่ยวบินเดิม และตรวจว่าค่ากับ built_at ของ summary เดิมไม่เปลี่ยน
รันซ้ำไม่เพิ่มแถวซ้ำ; batch ที่ยังเขียน Gold ไม่ครบจะถูกสร้างใหม่เฉพาะ ID ใน batch นั้น
ห้ามรัน loader หรือ generator หลายตัวพร้อมกันบน stack เดียวกัน
`--generate-only` ใช้สร้างไฟล์โดยยังไม่โหลด เช่นเดียวกับสคริปต์ชุดเล็ก
ต้องเปิด stack และมีตาราง Silver/Gold จาก startup script ก่อนรันชุด 100 นี้

## Metabase และหน้าเว็บ

Metabase อยู่ใน network ของ stack ใหม่นี้ จึงเชื่อม `trino:8080` ไปยัง
`qar-capstone-bi-trino-1` ซึ่ง expose เป็น host port 8083
ใช้ Starburst driver, catalog `iceberg`, schema `gold`, user `safety_analyst`
ตาม role เดิมของ repo ที่อ่านข้อมูลได้และไม่มีสิทธิ์เขียน

สำหรับเดโม สามารถเปลี่ยน fixed identity ของ connection เป็น admin ได้:

```powershell
python scripts/setup_bi_demo.py --identity admin
python scripts/build_bi_page.py
```

ค่าที่เลือกเก็บเฉพาะเครื่องใน `.secrets/bi-demo-settings.json` รัน startup ซ้ำจะใช้ค่านี้ต่อ
และหน้า Gold Reports แสดง identity ที่ใช้อยู่ admin มีสิทธิ์กว้างตาม policy เดิมของ repo
หากเว็บ server เปิดอยู่ให้ restart หลังอัปเดตโค้ดเพื่อให้โหลดค่าจาก settings
กลับไปใช้สิทธิ์อ่านข้อมูลด้วย `python scripts/setup_bi_demo.py --identity safety_analyst`
แล้ว build หน้าเว็บอีกครั้ง ค่าเริ่มต้นของเครื่องที่ยังไม่มี settings ยังคงเป็น safety_analyst
การตรวจรายงานใช้ `SELECT current_user` ผ่าน Metabase เพื่อยืนยัน user ที่ถึง Trino จริง

repo นี้เป็น local HTTP authorization POC ที่ผู้เรียกส่งชื่อ user เอง ไม่มี password login
ไม่เท่ากับระบบยืนยันตัวตนรายบุคคล และไม่ได้ใช้ TLS/password configuration ของ repo เก่า
ไม่ได้เปลี่ยน OPA ให้เปิดสิทธิ์เพิ่ม บัญชี `operations_analyst` ยังคงอ่าน
`touchdown_peak_g` ไม่ได้ และ `blocked_user` ยังถูกปฏิเสธ

มี 7 cards: จำนวนเที่ยวบิน, airborne minutes รวม, ความสูงสูงสุด, จำนวนเที่ยวบินตามเส้นทาง,
เวลาตาม phase รวม ground, ตาราง summary และตาราง events พร้อมตัวกรองวันบิน/ชนิดเครื่อง
ตัวชี้วัดเป็น POC รอเก็บ requirement ไม่ใช้ placeholder hard landing threshold เป็น KPI
ตารางจำกัด 200 แถว ส่วน KPI/กราฟคำนวณทุกแถวที่ตรงตัวกรอง
reference ของ flight ในรายงานเป็น SHA-256 prefix 12 ตัวเพื่อแยกแต่ละเที่ยวบิน
ไม่ใช่การรับรอง anonymization หรือ policy masking ของ safety role
เวลาใน Metabase ตั้งเป็น UTC

เก็บสำเนาต้นแบบ `_3` ไว้ใน `bi/web/qar-flight-analytics_3.html` เพื่อให้ clone repo แล้ว build ได้
โดยไม่ต้องมีโฟลเดอร์ visualization ภายนอก ไฟล์ต้นฉบับในเครื่องยังอยู่เหมือนเดิม
`scripts/build_bi_page.py` สร้างเว็บที่ `bi/web/qar-flight-analytics-capstone-metabase.html`
ไฟล์ที่สร้างนี้ถูก Git ignore และ startup script จะ build ให้อัตโนมัติ
Gold Reports แสดง dashboard จริง และ Flight Explorer อ่านรายการจาก Silver ผ่าน Trino
พร้อมเปิดรายละเอียดจาก Silver และ metrics/phases/events จาก Gold ตาม flight ID ที่เลือก
ส่วน Cockpit และ SQL Workspace ยังใช้ข้อมูล prototype เดิม
ตัวเลือก Demo identity ใช้กับ OPA fixtures ไม่มีผลต่อ shared BI connection หรือ Flight API

### Flight Explorer

เปิด **http://localhost:8766/#explorer** เพื่อดูข้อมูล `iceberg.silver.flights`
รวมเที่ยวบินจริงและเที่ยวบินจำลองที่โหลดเข้ามาแล้ว (ชุดเดโมปัจจุบัน 108 เที่ยวบิน:
ข้อมูลจริง 3 และจำลอง 105) มีป้าย Recorded / Synthetic demo ให้แยกแหล่งข้อมูล
เลขเที่ยวบินแสดงตามที่เก็บใน Silver เช่น `TG0000` ของ decoded บาง recording
ไม่ได้แทนที่ด้วยเลขเที่ยวบินตัวอย่างจากต้นแบบ

ค้นหาด้วยเลขเที่ยวบิน, flight ID หรือ tail และกรองวันบิน/ชนิดเครื่อง/ต้นทาง/ปลายทาง/แหล่งข้อมูล
แบ่งหน้าครั้งละ 20 รายการ เรียงวันที่ใหม่ก่อน ปุ่ม Refresh flights อ่านข้อมูลจาก Trino ใหม่
API อ่าน metadata สูงสุด 1,000 เที่ยวบินและแสดงข้อความหากมีข้อมูลเกินขอบเขตนี้
ตัวกรองและการแบ่งหน้าทำใน browser บนรายการที่โหลดมา ไม่ดึง sensor arrays ในหน้ารายการ

`GET /api/flights` ใช้ SELECT ที่กำหนดไว้ และ `GET /api/flights/detail?id=...`
ใช้ parameterized query ของ flight ID เพื่ออ่าน metadata, summary, phases และ events
ไม่มี endpoint รับ SQL หรือเปลี่ยน identity จาก browser; ใช้ fixed identity จาก settings
เดียวกับ BI (เครื่องเดโมนี้เป็น admin) เวลาแสดงเป็น UTC
หลังแก้ Python server ให้ restart `scripts/serve_bi_demo.py` และ reload หน้าเว็บ

`serve_bi_demo.py` ให้บริการเว็บเฉพาะ loopback และออก JWT อายุ 10 นาทีสำหรับ dashboard เดียว
เว็บต่ออายุทุก 8 นาที มีปุ่ม refresh และเปิด dashboard แยกแท็บ
ไม่มี public link หรือการเปลี่ยนสิทธิ์ตามผู้ชม ใช้ signed/static embedding ที่ Metabase เวอร์ชันนี้รองรับ

## ตรวจซ้ำและหยุด

```powershell
powershell -File scripts/start_bi_demo.ps1 -CheckOnly
```

ตรวจจำนวนข้อมูล/quality gates/OPA denials และทุก Metabase card รวม filters,
no-match case, signed metadata และการปฏิเสธ token ปลอม
`-NoWeb` ใช้เปิด stack และเตรียม BI โดยไม่เปิดเว็บ server
หากจะเปิดเว็บใน terminal เองใช้ `python scripts/serve_bi_demo.py` และหยุดด้วย Ctrl+C

หยุด containers ของเดโมนี้โดยเก็บข้อมูลไว้:

```powershell
docker compose -f docker-compose.bi-local.yaml stop
```

อย่าใช้ `down -v` หากต้องการเก็บข้อมูลเดโม เพราะจะลบ volumes ของ stack นี้
ไฟล์ compose เดิมของ repo ยังใช้ชื่อ container/port เดิม จึงให้ใช้ไฟล์ bi-local สำหรับเดโมนี้
Metabase H2 และชื่อ user ที่ส่งเองเหมาะสำหรับ local POC; ก่อนเปิดให้ผู้ใช้อื่นต้องออกแบบ
application authentication, identity mapping และ application database สำหรับการใช้งานจริง
