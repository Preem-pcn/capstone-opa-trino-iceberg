# Gold Reports จาก capstone-opa-trino-iceberg

เดโมนี้ใช้ข้อมูล `decoded/` และ Gold SQL ของ checkout นี้โดยตรง
เปิด stack ด้วย `docker-compose.app.yaml` (แยกจาก `docker-compose.yaml` ของ pipeline)
ชื่อ project คือ `qar-capstone-sso` (ชื่อเดิม จึงใช้ volumes เดิมของ stack นี้ต่อได้) ไม่ใช้ container, catalog หรือ object storage ของ
`C:\QAR\trino-iceberg-poc` และไม่แก้ policy OPA เดิม
stack รุ่นก่อนที่ไม่มี login (project `qar-capstone-bi`) และ volumes ของมันไม่ถูกแตะ
ครั้งแรกที่เปิด stack นี้จะได้ volumes ใหม่ startup script โหลดข้อมูลตัวอย่างให้เอง

ผู้ใช้ login ด้วยบัญชี Google (OIDC) ผ่าน backend (`backend/`, FastAPI) แล้วเห็น dashboard ของ role ตัวเอง
Google ไม่ส่ง role มา backend จึงจับคู่ email ที่ยืนยันแล้วกับ role จาก `.secrets/role-assignments.json`
แต่ละ role มี Trino login (HTTPS + password) ของตัวเอง OPA จึงกรองทุกกราฟตาม role
แนวคิดทั้งหมดอยู่ใน `METABASE_ROLE_DESIGN.md` ที่ root ของ repo

## เปิดใช้งาน

เปิด Docker Desktop แล้วรัน PowerShell:

ใช้ Python environment ที่มี dependencies ของ loader เดิม (`pyarrow`, `pyiceberg`, `trino`)
นำไฟล์ decoded ของตัวเองไว้ใน `decoded/` เพราะข้อมูลเหล่านี้ไม่ได้เก็บใน Git

```powershell
cd C:\QAR\capstone-opa-trino-iceberg
powershell -File scripts/start_bi_demo.ps1
```

บน macOS/Linux ใช้ `scripts/start_bi_demo.sh` (ขั้นตอนเดียวกัน) กำหนด Python ที่มี dependencies ด้วย `PYTHON`:

```sh
PYTHON="conda run -n qar python" scripts/start_bi_demo.sh
PYTHON="conda run -n qar python" scripts/start_bi_demo.sh --check-only
```

### ตั้งค่า login ด้วย Google (ครั้งแรก)

1. เปิด https://console.cloud.google.com/ สร้างหรือเลือก project
2. Google Auth Platform → Branding: ตั้งชื่อแอปและ support email
3. Audience: เลือก External ปล่อยไว้ที่ Testing แล้วเพิ่ม test users คือบัญชี Google ที่จะใช้ login
4. Clients → Create client → ชนิด Web application
   ใส่ Authorized redirect URI เป็น `http://localhost:8766/callback`
5. ใส่ client ID และ secret ใน `.secrets/oidc.env` (`init_bi_secrets.py` สร้าง template ไว้ให้):
   ```
   OIDC_CLIENT_ID=xxxx.apps.googleusercontent.com
   OIDC_CLIENT_SECRET=xxxx
   ```
6. กำหนด role ให้แต่ละ email ใน `.secrets/role-assignments.json` (คนละหนึ่ง role;
   email ที่ไม่อยู่ในไฟล์ login ได้แต่ไม่เห็นข้อมูล):
   ```json
   {"somchai@gmail.com": "safety", "nok@gmail.com": "operations", "pim@gmail.com": "engineering"}
   ```
7. รัน `docker compose -f docker-compose.app.yaml up -d backend` ให้ backend อ่าน `oidc.env` ใหม่
   ส่วน `role-assignments.json` ถูกอ่านใหม่ทุกครั้งที่มีคน login จึงไม่ต้อง restart

ถ้าใช้ Google Workspace และต้องการรับเฉพาะบัญชีขององค์กร ให้ตั้ง `ALLOWED_DOMAIN` ใน `oidc.env`

เปิดเว็บ **http://localhost:8766/** ระบบจะพาไปหน้าเลือกบัญชี Google
พอร์ต 8765 คือเดโมเก่าจากอีก repo ไม่ใช่หน้าใหม่นี้

| Role | เห็นอะไร |
| --- | --- |
| safety | ทุกเที่ยวบิน, recording/source file ถูก mask |
| operations | เฉพาะเที่ยวบินเข้า/ออก VTBS, tail ถูก mask, ไม่มี touchdown g |
| engineering | เฉพาะเครื่อง HS-THJ, flight number/route ถูก mask |
| ไม่มี role หรือมีหลาย role | login ได้ แต่ไม่มี dashboard และไม่มีข้อมูล |

| Service | URL / port ฝั่งเครื่อง |
| --- | --- |
| เว็บ QAR (backend) | http://localhost:8766/ |
| Metabase | http://localhost:3002 |
| Trino (HTTPS + password เท่านั้น) | https://localhost:8443 |
| Iceberg REST | http://localhost:9181 |
| RustFS S3 / console | 9100 / 9101 |
| OPA | http://localhost:9282 |

พอร์ตทั้งหมด bind เฉพาะ loopback มี named volumes แยกสำหรับ RustFS,
SQLite catalog และ Metabase H2 พร้อมกำหนด memory limits สำหรับเครื่องเดโม
secrets ทั้งหมดอยู่ใน `.secrets/` ที่ Git ignore ไม่ใส่ credentials หรือ key ใดๆ ลง HTML

| ไฟล์ใน `.secrets/` | ใช้ทำอะไร |
| --- | --- |
| `trino-users.json`, `trino/password.db` | password ของ Trino ต่อ user (`password.db` เป็น PBKDF2 hash ที่ Trino อ่าน) |
| `trino/keystore.jks`, `trino-public/trino.crt` | TLS certificate ของ Trino (self-signed); client trust ไฟล์ `.crt` |
| `trino.env`, `service-secrets.json` | shared secret ของ Trino และ password ของ keystore |
| `oidc.env` | client ID/secret ของ Google ที่ backend ใช้ (ใส่เอง) |
| `role-assignments.json` | email → role (ใส่เอง) |
| `metabase-demo.json`, `metabase-sso-state.json`, `metabase-embed.json` | Metabase admin, id ของ objects ที่สร้าง และ embedding secret |

`scripts/init_bi_secrets.py` สร้างไฟล์เหล่านี้ (startup script เรียกให้) รันซ้ำได้โดยไม่เปลี่ยนค่าเดิม
`oidc.env` และ `role-assignments.json` ถูกสร้างเป็น template ครั้งแรกเท่านั้น และไม่ถูกเขียนทับ
backend mount `.secrets/` แบบ read-only จึงไม่มี secret อยู่ใน image

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

`scripts/setup_bi_demo.py` สร้างของใน Metabase แยกตาม role (ตาม `ROLES` ใน `scripts/bi_demo_settings.py`)

| Role | Trino connection (user) | Collection / dashboard |
| --- | --- | --- |
| safety | `safety_analyst` | `QAR · Safety` |
| operations | `operations_analyst` | `QAR · Operations` |
| engineering | `engineering_analyst` | `QAR · Engineering` |

ทุก connection ใช้ Starburst driver ต่อ `trino:8443` แบบ HTTPS ด้วย password ของ user นั้น
และ trust certificate ที่ mount ไว้ที่ `/tls/trino.crt` (`additional-options: SSLTrustStorePath=/tls/trino.crt`)
กราฟแต่ละอันผูกกับ connection ของ role ตัวเอง จึงส่ง Trino user ของ role นั้นทุก query
การตรวจใช้ `SELECT current_user` ผ่านแต่ละ connection เพื่อยืนยัน user ที่ถึง Trino จริง

Trino ของ stack นี้ปิด plain HTTP สำหรับ client (ตอบ `Authentication over HTTP is not enabled`)
และไม่ publish port 8080 ออกนอก container ใช้ file password authenticator
(`bi/trino/password-authenticator.properties`) login ของ role หนึ่งสวมเป็น user อื่นไม่ได้
เพราะ OPA ไม่อนุญาต impersonation ไม่ได้เปลี่ยน OPA ให้เปิดสิทธิ์เพิ่ม บัญชี `operations_analyst`
ยังคงอ่าน `touchdown_peak_g` ไม่ได้ และ `blocked_user` ยังถูกปฏิเสธ

กราฟทั้งหมดมาจาก `bi/dashboard.json` และ `bi/queries/*.sql` ชุดเดียว แต่ละ card มี key เสริมได้:
- `"roles"`: role ที่ได้ card นี้ (ไม่ใส่ = ทุก role)
- `"layout"`: ตำแหน่ง/ขนาดเฉพาะ role เช่น `{"engineering": {"col": 0, "size_x": 24}}`

ตั้งไว้ให้เข้ากับ policy ของ OPA:
- Engineering ไม่มีกราฟ Flights by route เพราะ origin/destination ถูก mask เหลือแท่ง REDACTED แท่งเดียว
  กราฟ phase จึงขยายเต็มแถว
- Operations ใช้ `flight_summary_ops.sql` ที่ไม่มี `touchdown_peak_g` เพราะ OPA ปฏิเสธ column นี้
- ป้าย `data_source` อ่านจาก `silver.flights.decoder_version` เพราะ flight_id ของ Operations ถูก pseudonymize

ถ้าแก้กราฟในหน้า Metabase แล้วรัน `setup_bi_demo.py` ซ้ำ ค่าจาก json จะเขียนทับ
ให้แก้ที่ json/SQL เป็นหลัก

Safety และ Operations มี 7 cards, Engineering มี 6 cards: จำนวนเที่ยวบิน, airborne minutes รวม,
ความสูงสูงสุด, จำนวนเที่ยวบินตามเส้นทาง (ไม่มีใน Engineering), เวลาตาม phase รวม ground,
ตาราง summary และตาราง events พร้อมตัวกรองวันบิน/ชนิดเครื่อง
ตัวชี้วัดเป็น POC รอเก็บ requirement ไม่ใช้ placeholder hard landing threshold เป็น KPI
ตารางจำกัด 200 แถว ส่วน KPI/กราฟคำนวณทุกแถวที่ตรงตัวกรอง
reference ของ flight ในรายงานเป็น SHA-256 prefix 12 ตัวเพื่อแยกแต่ละเที่ยวบิน
ไม่ใช่การรับรอง anonymization หรือ policy masking ของ safety role
เวลาใน Metabase ตั้งเป็น UTC

หน้าเว็บคือ React client ใน `client/` ซึ่งถูก build อยู่ใน image ของ backend (`backend/Dockerfile`) จึงไม่ต้องมี Node บนเครื่อง
backend ส่งไฟล์ของ client และส่ง `index.html` ให้ทุก route ของ client (`/flights`, `/reports`, ...)
Gold Reports แสดง dashboard จริง และ Flight Explorer อ่านรายการจาก Silver ผ่าน Trino
พร้อมเปิดรายละเอียดจาก Silver และ metrics/phases/events จาก Gold ตาม flight ID ที่เลือก
ส่วน Cockpit และ SQL Workspace ยังใช้ข้อมูล prototype เดิม
แถบบนแสดงผู้ใช้ที่ login และ role พร้อมปุ่ม Sign out
หน้า prototype (SQL Workspace, OPA fixtures) เริ่มจาก Trino user ของ role ที่ login
ปุ่มในหน้า OPA fixtures ยังสลับ identity ได้เพราะใช้ข้อมูล mock ไม่ได้ query Trino
หลังแก้ client หรือ backend ให้ build ใหม่ด้วย `docker compose -f docker-compose.app.yaml up -d --build backend` แล้ว reload
endpoint และโครงสร้างของ client อยู่ใน `client/README.md`

### Flight Explorer

เปิด **http://localhost:8766/flights** เพื่อดูข้อมูล `iceberg.silver.flights`
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
ไม่มี endpoint รับ SQL หรือเปลี่ยน identity จาก browser; query ด้วย Trino user ของ role ที่ login
(HTTPS + password ของ user นั้น) OPA จึงกรองแถวและ mask เหมือน dashboard
ถ้า OPA ปฏิเสธบาง column ของ summary (เช่น `touchdown_peak_g` ของ Operations) API อ่านรายชื่อ column
ที่ role นั้นเห็นจาก `information_schema.columns` แล้วเลือกเฉพาะ column เหล่านั้น หน้าเว็บแสดงเป็น `—`
เวลาแสดงเป็น UTC

### Login และ backend (`backend/`)

FastAPI + uvicorn ใน container ของตัวเอง (`backend/Dockerfile`, service `backend` ใน `docker-compose.app.yaml`)
รันเป็น user ที่ไม่ใช่ root

| Endpoint | ทำอะไร |
| --- | --- |
| `/login` | เริ่ม OIDC authorization code flow + PKCE แล้ว redirect ไปหน้าเลือกบัญชีของ Google |
| `/callback` | รับ code, แลกเป็น ID token ทาง back-channel, ตรวจลายเซ็น/issuer/audience/nonce และ email ที่ยืนยันแล้ว แล้วสร้าง session |
| `/logout` | ลบ session ของเว็บ (Google ไม่มี endpoint สำหรับ logout จึงไม่ได้ออกจาก Google; login ครั้งถัดไปจะให้เลือกบัญชี) |
| `/api/me` | ผู้ใช้, role, Trino user ของ session นี้ |
| `/api/bi/embed`, `/metabase` | เซ็น JWT อายุ 10 นาทีสำหรับ dashboard ของ role นี้เท่านั้น |
| `/api/flights`, `/api/flights/detail` | Flight API ด้วย Trino user ของ role นี้ |

- ยังไม่ login: หน้าเว็บ redirect ไป `/login` ส่วน API ตอบ 401 (หน้าเว็บพาไป login ให้)
- login แล้วแต่ไม่มี role หรือมีหลาย role: API ข้อมูลตอบ 403 และหน้าเว็บแสดงข้อความ
- role มาจาก `.secrets/role-assignments.json` ตาม email (`ROLES_FROM=assignments`, ค่าเริ่มต้น)
  หรือจาก claim `roles` ใน ID token (`ROLES_FROM=claim` สำหรับ app roles ของ Entra ID)
- session เก็บใน memory ของ backend (worker เดียว) cookie เป็น HttpOnly + SameSite=Lax
  (และ Secure เมื่อ `PUBLIC_URL` เป็น https) อายุ 8 ชั่วโมง restart แล้วต้อง login ใหม่
- audit log เป็น JSON บรรทัดละเหตุการณ์ใน `docker compose -f docker-compose.app.yaml logs backend`
  (login, role, dashboard, flight API) และทุก query ที่ส่งไป Trino มี client tag `person:<email>`
- เว็บต่ออายุ embed token ทุก 8 นาที มีปุ่ม refresh และเปิด dashboard แยกแท็บ
- ใช้ signed/static embedding ที่ Metabase OSS รองรับ ไม่มี public link
- test ของ backend ใช้ OIDC provider จำลอง รันด้วย `docker build -f backend/Dockerfile --target test .`

เปลี่ยนไปใช้ Entra ID (หรือ OIDC provider อื่น) ไม่ต้องแก้ code:
1. ให้ IT ลงทะเบียนแอป redirect URI `<เว็บ>/callback` และสร้าง app roles `safety`, `operations`, `engineering`
2. ใน `.secrets/oidc.env` ใส่ client id/secret, `OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0`
   และ `ROLES_FROM=claim`
3. รัน `docker compose -f docker-compose.app.yaml up -d backend`

## ตรวจซ้ำและหยุด

```powershell
powershell -File scripts/start_bi_demo.ps1 -CheckOnly
```

```sh
PYTHON="conda run -n qar python" scripts/start_bi_demo.sh --check-only
```

ตรวจจำนวนข้อมูล/quality gates/OPA denials และทุก Metabase card ของทุก role รวม filters,
no-match case, signed metadata และการปฏิเสธ token ที่ถูกแก้ รัน test ของ backend
แล้วรัน `scripts/check_sso_flow.py` ซึ่งตรวจว่า
- backend ทำงาน ส่งหน้าเว็บได้ และมี dashboard links
- ผู้ที่ยังไม่ login ได้ 401 จาก API และถูกพาไปหน้า login
- `/login` ส่งไป Google พร้อม callback ของเว็บนี้, PKCE และ state cookie (ข้ามถ้ายังไม่ได้ตั้ง `oidc.env`)
- callback จาก browser ที่ไม่ได้เริ่ม login (ไม่มี state cookie) ถูกปฏิเสธ
- Metabase ปฏิเสธ token ที่ถูกแก้เลข dashboard
- Trino ปฏิเสธ password ผิด/ไม่มี password และ login ของ role สวมเป็น admin ไม่ได้

การ login ด้วย Google จริงต้องทำเองใน browser สคริปต์ทำแทนไม่ได้

หยุด containers ของเดโมนี้โดยเก็บข้อมูลไว้:

```powershell
docker compose -f docker-compose.app.yaml stop
```

อย่าใช้ `down -v` หากต้องการเก็บข้อมูลเดโม เพราะจะลบ volumes ของ stack นี้
ก่อนเปิดให้ผู้ใช้อื่นนอกเครื่องเดโม ยังต้องทำเพิ่ม:
- backend ต้องอยู่หลัง HTTPS: ตั้ง `PUBLIC_URL` เป็น https (cookie จะเป็น `Secure`) และเพิ่ม redirect URI นั้นใน Google
- เก็บ session นอก memory (เช่น Redis) ถ้าจะรัน backend หลาย instance
- Google OAuth app ยังอยู่ในโหมด Testing (ผู้ใช้ต้องอยู่ในรายชื่อ test users) ตอนใช้จริงเปลี่ยนเป็น Entra ID ของ TG (`ROLES_FROM=claim`)
- Trino ใช้ certificate จาก CA ขององค์กรแทน self-signed และใช้ Metabase application database (เช่น Postgres) แทน H2
- สิทธิ์ role editor ใน Metabase (กลุ่มที่แก้ได้เฉพาะ collection ของ role ตัวเอง) ยังไม่ได้ตั้ง ตอนนี้มีแต่ admin
