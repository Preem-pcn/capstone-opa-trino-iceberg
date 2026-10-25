# Gold Reports จาก capstone-opa-trino-iceberg

เดโมนี้ใช้ข้อมูล `decoded/` และ Gold SQL ของ checkout นี้โดยตรง
เปิด stack แยกด้วย `docker-compose.bi-local.yaml` (ไม่ merge กับ compose เดิม)
ชื่อ project คือ `qar-capstone-sso` ไม่ใช้ container, catalog หรือ object storage ของ
`C:\QAR\trino-iceberg-poc` และไม่แก้ policy OPA เดิม
stack รุ่นก่อนที่ไม่มี login (project `qar-capstone-bi`) และ volumes ของมันไม่ถูกแตะ
ครั้งแรกที่เปิด stack นี้จะได้ volumes ใหม่ startup script โหลดข้อมูลตัวอย่างให้เอง

ผู้ใช้ login ผ่าน Keycloak (OIDC) แล้วเห็น dashboard ของ role ตัวเอง
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

เปิดเว็บ **http://localhost:8766/** ระบบจะพาไปหน้า login ของ Keycloak
พอร์ต 8765 คือเดโมเก่าจากอีก repo ไม่ใช่หน้าใหม่นี้

| ผู้ใช้เดโม | Role | เห็นอะไร |
| --- | --- | --- |
| `safety.demo` | safety | ทุกเที่ยวบิน, recording/source file ถูก mask |
| `ops.demo` | operations | เฉพาะเที่ยวบินเข้า/ออก VTBS, tail ถูก mask, ไม่มี touchdown g |
| `eng.demo` | engineering | เฉพาะเครื่อง HS-THJ, flight number/route ถูก mask |
| `norole.demo` | ไม่มี | login ได้ แต่ไม่มี dashboard และไม่มีข้อมูล |

password สุ่มตอนสร้าง อยู่ใน `.secrets/demo-logins.json`

| Service | URL / port ฝั่งเครื่อง |
| --- | --- |
| เว็บ QAR | http://localhost:8766/ |
| Keycloak (login, admin console) | http://localhost:8180 |
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
| `trino.env`, `keycloak.env`, `service-secrets.json` | shared secret ของ Trino, password ของ keystore และ Keycloak admin |
| `oidc-client.json` | client id/secret ที่ backend ใช้คุยกับ Keycloak |
| `demo-logins.json`, `keycloak/qar-realm.json` | ผู้ใช้เดโมและ realm ที่ Keycloak import ทุกครั้งที่ start |
| `metabase-demo.json`, `metabase-sso-state.json`, `metabase-embed.json` | Metabase admin, id ของ objects ที่สร้าง และ embedding secret |

`scripts/init_bi_secrets.py` สร้างไฟล์เหล่านี้ (startup script เรียกให้) รันซ้ำได้โดยไม่เปลี่ยนค่าเดิม
Keycloak admin console ใช้ user `admin` และ password ใน `.secrets/keycloak.env`
Keycloak รันแบบ dev mode โดยไม่มี volume: realm ถูก import ใหม่จากไฟล์เมื่อสร้าง container ใหม่
ผู้ใช้ที่เพิ่มผ่าน console จะหายเมื่อสร้าง container ใหม่ ให้เพิ่มใน `DEMO_USERS` ของ `scripts/bi_demo_settings.py` แทน
แล้วรัน `python scripts/init_bi_secrets.py` และ `docker compose -f docker-compose.bi-local.yaml up -d --force-recreate keycloak`

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

เก็บสำเนาต้นแบบ `_3` ไว้ใน `bi/web/qar-flight-analytics_3.html` เพื่อให้ clone repo แล้ว build ได้
โดยไม่ต้องมีโฟลเดอร์ visualization ภายนอก ไฟล์ต้นฉบับในเครื่องยังอยู่เหมือนเดิม
`scripts/build_bi_page.py` สร้างเว็บที่ `bi/web/qar-flight-analytics-capstone-metabase.html`
ไฟล์ที่สร้างนี้ถูก Git ignore และ startup script จะ build ให้อัตโนมัติ
Gold Reports แสดง dashboard จริง และ Flight Explorer อ่านรายการจาก Silver ผ่าน Trino
พร้อมเปิดรายละเอียดจาก Silver และ metrics/phases/events จาก Gold ตาม flight ID ที่เลือก
ส่วน Cockpit และ SQL Workspace ยังใช้ข้อมูล prototype เดิม
แถบบนแสดงผู้ใช้ที่ login และ role พร้อมปุ่ม Sign out (แทนตัวเลือก Demo identity เดิม)
หน้า prototype (SQL Workspace, OPA fixtures) เริ่มจาก Trino user ของ role ที่ login
ปุ่มในหน้า OPA fixtures ยังสลับ identity ได้เพราะใช้ข้อมูล mock ไม่ได้ query Trino

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
ไม่มี endpoint รับ SQL หรือเปลี่ยน identity จาก browser; query ด้วย Trino user ของ role ที่ login
(HTTPS + password ของ user นั้น) OPA จึงกรองแถวและ mask เหมือน dashboard
ถ้า OPA ปฏิเสธบาง column ของ summary (เช่น `touchdown_peak_g` ของ Operations) API อ่านรายชื่อ column
ที่ role นั้นเห็นจาก `information_schema.columns` แล้วเลือกเฉพาะ column เหล่านั้น หน้าเว็บแสดงเป็น `—`
เวลาแสดงเป็น UTC
เว็บ server รันเป็น service `bi-web` ใน `docker-compose.bi-local.yaml` (build หน้าเว็บใหม่ทุกครั้งที่ start)
หลังแก้ไฟล์ใน `scripts/` หรือ `bi/web/qar-flight-analytics_3.html` ให้รัน
`docker compose -f docker-compose.bi-local.yaml restart bi-web` แล้ว reload หน้าเว็บ

### Login และ backend (`serve_bi_demo.py`)

| Endpoint | ทำอะไร |
| --- | --- |
| `/login` | เริ่ม OIDC authorization code flow + PKCE แล้ว redirect ไป Keycloak |
| `/callback` | รับ code, แลกเป็น ID token ทาง back-channel, ตรวจลายเซ็น/issuer/audience/nonce แล้วสร้าง session |
| `/logout` | ลบ session ของเว็บ และจบ session ที่ Keycloak (login ครั้งต่อไปต้องใส่ password ใหม่) |
| `/api/me` | ผู้ใช้, role, Trino user ของ session นี้ |
| `/api/bi/embed`, `/metabase` | เซ็น JWT อายุ 10 นาทีสำหรับ dashboard ของ role นี้เท่านั้น |
| `/api/flights`, `/api/flights/detail` | Flight API ด้วย Trino user ของ role นี้ |

- ยังไม่ login: หน้าเว็บ redirect ไป `/login` ส่วน API ตอบ 401 (หน้าเว็บพาไป login ให้)
- login แล้วแต่ไม่มี role หรือมีหลาย role: API ข้อมูลตอบ 403 และหน้า Gold Reports แสดงข้อความ
- role อ่านจาก claim `roles` ใน ID token ซึ่งเป็นชื่อเดียวกับ app roles ของ Entra ID
- session เก็บใน memory ของ server, cookie เป็น HttpOnly + SameSite=Lax, อายุ 8 ชั่วโมง restart server แล้วต้อง login ใหม่
- เว็บต่ออายุ embed token ทุก 8 นาที มีปุ่ม refresh และเปิด dashboard แยกแท็บ
- ใช้ signed/static embedding ที่ Metabase OSS รองรับ ไม่มี public link

เปลี่ยนไปใช้ Entra ID (หรือ OIDC provider อื่น) ไม่ต้องแก้ code:
1. ให้ IT ลงทะเบียนแอป redirect URI `<เว็บ>/callback` และสร้าง app roles `safety`, `operations`, `engineering`
2. ใส่ client id/secret ใน `.secrets/oidc-client.json`
3. ตั้ง `OIDC_ISSUER` (เช่น `https://login.microsoftonline.com/<tenant-id>/v2.0`) และ `BI_PUBLIC_URL` ให้ service `bi-web`
   และลบ `OIDC_DISCOVERY_URL` (ค่านั้นชี้ Keycloak ใน docker network)

## ตรวจซ้ำและหยุด

```powershell
powershell -File scripts/start_bi_demo.ps1 -CheckOnly
```

ตรวจจำนวนข้อมูล/quality gates/OPA denials และทุก Metabase card ของทุก role รวม filters,
no-match case, signed metadata และการปฏิเสธ token ที่ถูกแก้
แล้วรัน `scripts/check_sso_flow.py` ซึ่ง login ผ่านฟอร์มจริงของ Keycloak ทีละผู้ใช้เดโม และตรวจว่า
- แต่ละ role ได้ dashboard ของตัวเอง และตัวเลขใน dashboard/Flight API ตรงกับที่ Trino ตอบให้ role นั้น
- Operations เห็น tail เป็น REDACTED
- `norole.demo` ได้ 403, ผู้ที่ยังไม่ login ได้ 401, sign out แล้วต้องใส่ password ใหม่
- Metabase ปฏิเสธ token ที่ถูกแก้เลข dashboard
- Trino ปฏิเสธ password ผิด/ไม่มี password และ login ของ role สวมเป็น admin ไม่ได้

`-NoWeb` ใช้เปิด stack และเตรียม BI โดยไม่เปิดเว็บ server
หากจะเปิดเว็บใน terminal เองแทน container ให้ `docker compose -f docker-compose.bi-local.yaml stop bi-web` ก่อน
แล้ว `pip install "pyjwt[crypto]"` ใช้ `python scripts/serve_bi_demo.py` และหยุดด้วย Ctrl+C

หยุด containers ของเดโมนี้โดยเก็บข้อมูลไว้:

```powershell
docker compose -f docker-compose.bi-local.yaml stop
```

อย่าใช้ `down -v` หากต้องการเก็บข้อมูลเดโม เพราะจะลบ volumes ของ stack นี้
ไฟล์ compose เดิมของ repo ยังใช้ชื่อ container/port เดิม จึงให้ใช้ไฟล์ bi-local สำหรับเดโมนี้
ก่อนเปิดให้ผู้ใช้อื่นนอกเครื่องเดโม ยังต้องทำเพิ่ม:
- เว็บและ Keycloak ต้องอยู่หลัง HTTPS แล้วเพิ่ม flag `Secure` ให้ cookie (มี `ponytail:` comment ใน `serve_bi_demo.py`)
- ย้ายเว็บจาก `http.server` ไปใช้ server สำหรับ production และเก็บ session นอก memory ถ้ามีหลาย instance
- Keycloak โหมด production พร้อม database หรือใช้ Entra ID ของ TG
- Trino ใช้ certificate จาก CA ขององค์กรแทน self-signed และใช้ Metabase application database (เช่น Postgres) แทน H2
- สิทธิ์ role editor ใน Metabase (กลุ่มที่แก้ได้เฉพาะ collection ของ role ตัวเอง) ยังไม่ได้ตั้ง ตอนนี้มีแต่ admin
