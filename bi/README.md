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
ไม่ได้ย้ายตารางหรือคัดลอกข้อมูลจาก stack เก่า และไม่ได้สร้าง synthetic flight เพิ่ม
รอบนี้เรียก loader/SQL โดยตรง ไม่ได้รัน Dagster materialization

เที่ยวบินตัวอย่างทั้งสามมาจากโฟลเดอร์:

- `A350_HS-THJ_20220322_TG0341_VTBS-OPKC`
- `A350_HS-THE_20220826_TG0000_VTBS-RKSI`
- `A350_HS-THJ_20220921_TG0000_ESSA-VTBS`

หลังโหลดได้ Silver flights 3 แถว, Gold summaries 3 แถว, phases 15 แถว และ events 12 แถว
ตรวจ quality gates เดิมทั้ง 3 ข้อ: phase coverage, event order และ segmentation delta
การรันซ้ำข้าม recording ที่มี Silver flight metadata แล้ว และไม่ rebuild Gold หากครบอยู่แล้ว
ไม่ได้ตั้งให้ตรวจจับการแก้ไฟล์ decoded ที่โหลดสำเร็จไปแล้วโดยอัตโนมัติ

## Metabase และหน้าเว็บ

Metabase อยู่ใน network ของ stack ใหม่นี้ จึงเชื่อม `trino:8080` ไปยัง
`qar-capstone-bi-trino-1` ซึ่ง expose เป็น host port 8083
ใช้ Starburst driver, catalog `iceberg`, schema `gold`, user `safety_analyst`
ตาม role เดิมของ repo ที่อ่านข้อมูลได้และไม่มีสิทธิ์เขียน

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
Gold Reports แสดง dashboard จริง ส่วน Flight Explorer/Cockpit/SQL Workspace
ยังเป็น prototype เดิม ตัวเลือก Demo identity ไม่มีผลต่อ shared BI connection นี้

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
