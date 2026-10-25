# สรุปแนวคิด: Login + Dashboard แยกตาม role

สถานะ: ทำแล้วใน app stack (`docker-compose.app.yaml`): login ด้วย Google ผ่าน backend (`backend/`), บัตรตาม role 3 ใบ,
dashboard ต่อ role และ Trino แบบ HTTPS + password วิธีเปิดและตรวจอยู่ใน `bi/README.md`
`docker-compose.yaml` หลัก (pipeline Dagster) ยังไม่เปลี่ยน

## 1. ภาพรวม

```
ผู้ใช้ ──login──> IdP (Entra ID ของ TG / Google ตอนเดโม)
   │                 │ JWT ใบที่ 1: "คนนี้คือ somchai, role = operations"
   ▼                 ▼
เว็บเรา (backend) ── ดูตาราง role -> dashboard ── เซ็น JWT ใบที่ 2: "เปิด dashboard 12"
   │
   ▼ <iframe> ฝัง dashboard
Metabase ── ใช้ "บัตร" ของ role นั้น ──> Trino ──> OPA (กรองแถว / ปิด column ตาม rego)
                                           │
                                           ▼
                                   Iceberg (ตาราง Silver / Gold)
```

## 2. คำศัพท์

| คำ | ความหมายแบบง่าย |
| --- | --- |
| Trino | ห้องเก็บเอกสาร ทุก query ต้องผ่าน Trino |
| OPA | รปภ. หน้าห้อง ดูชื่อบนบัตรแล้วตัดสินว่าให้เห็นแถว/column ไหน (ไฟล์ `opa/trino.rego`) |
| Metabase | เลขาที่ไปหยิบข้อมูลแทนทุกคน แล้ววาดเป็นกราฟ |
| Connection (บัตร) | user/password ของ Trino ที่ admin ตั้งไว้ใน Metabase ครั้งเดียว Metabase ใช้บัตรนี้ทุกครั้งที่ query |
| IdP | ระบบที่ทำหน้าที่ login เก็บ user/password เช่น Microsoft Entra ID, Google, Keycloak |
| SSO | login ครั้งเดียวด้วยบัญชีองค์กร แล้วเข้าได้หลายระบบ |
| OIDC | มาตรฐานกลางที่เว็บใช้คุยกับ IdP ไม่ได้เก็บข้อมูลอะไร ถ้าเว็บทำตาม OIDC จะเปลี่ยน IdP ได้โดยแก้แค่ config |
| JWT | ข้อความที่มีลายเซ็นดิจิทัล อ่านได้แต่แก้ไม่ได้ (ดูข้อ 5) |
| Embed | ฝังหน้า dashboard ของ Metabase ไว้ในเว็บเราด้วย `<iframe>` เหมือนฝังคลิป YouTube |
| Gold table | ตารางสรุปที่ pipeline คำนวณไว้แล้ว (`flight_summary`, `flight_events`, `flight_phases`) |

## 3. ปัญหาหลัก: บัตรใบเดียว

Metabase ไม่ได้ส่งชื่อคนดูไปให้ Trino แต่ใช้บัตรที่ตั้งค่าไว้ ถ้าตั้งบัตรเป็น `admin` ใบเดียว ทุกคนจะเห็นข้อมูลทั้งหมด
และ OPA ไม่มีประโยชน์

**ตัดสินใจแล้ว: ใช้บัตรตาม role** สร้าง connection ใน Metabase 3 อัน

| Connection | Trino user | ใช้กับ |
| --- | --- | --- |
| Trino-Safety | `safety_analyst` | dashboard ของ Safety |
| Trino-Ops | `operations_analyst` | dashboard ของ Operations |
| Trino-Eng | `engineering_analyst` | dashboard ของ Engineering |

- ใช้ Metabase ฟรี (OSS) ได้ ไม่ต้องแก้ rego
- ข้อจำกัด: Trino เห็นแค่ role ไม่เห็นชื่อคน ชื่อคนเก็บใน log ของเว็บเราแทน
- ทางเลือกในอนาคต: บัตรรายคน ต้องใช้ Metabase Pro และต้องเช็คว่ารองรับ Trino หรือไม่ ใช้เมื่อต้องการกรองข้อมูลรายคน

## 4. Login ด้วย Entra ID ของ TG

- user/password ของพนักงานอยู่ที่ Microsoft ทีม IT ของ TG ดูแล เราไม่ได้เก็บ และแก้อะไรไม่ได้ ซึ่งถูกต้องแล้ว
- สิ่งที่ต้องขอจาก IT ของ TG:
  1. **App registration:** ลงทะเบียนเว็บเราในระบบ Entra ของ TG (ไม่ได้ทำในระบบเรา) เพื่อบอก Entra ว่า
     "เว็บนี้ขอให้ login ได้ และหลัง login ให้ส่งกลับมาที่ URL นี้"
  2. **App Roles:** กำหนดว่าพนักงานคนไหนอยู่ role ไหน ตอน login แล้ว role จะติดมาใน JWT
- สิ่งที่ได้กลับมาแล้วใส่ใน config ของเว็บเรา (ตัวแปร environment):
  - `client_id` เป็นรหัสประจำตัวของเว็บเรา เหมือน username ของแอป
  - `issuer` เป็น URL ของ Entra tenant ของ TG
  - `redirect_uri` เป็น URL ของเว็บเราที่ให้ส่งผู้ใช้กลับมา
- ขั้นตอนตอนใช้งาน: กด login บนเว็บเรา → ไปหน้า login ของ Microsoft (password และ MFA อยู่ที่นั่น) → ได้ JWT ใบที่ 1 กลับมา
- ตอนเดโมใช้ **บัญชี Google** แทน Entra ไปก่อน Google ไม่ส่ง role มา backend จึงจับคู่ email ที่ยืนยันแล้วกับ role
  ใน `.secrets/role-assignments.json` ตอนส่งมอบเปลี่ยนเป็น Entra ID แค่ config (`OIDC_ISSUER`, `ROLES_FROM=claim`)
- ข้อดีของการรันใน docker: สั่ง `docker compose up` ครั้งเดียวก็ได้ ทุกเครื่องได้เวอร์ชันเดียวกัน ส่งมอบง่าย

## 5. JWT มี 2 ใบ อย่าสับสน

รูปร่าง: `header.payload.signature`
- **payload** อ่านได้ทุกคน (ลองวางที่ jwt.io ดู) แต่แก้ไม่ได้ เพราะถ้าแก้ ลายเซ็นจะไม่ตรง
- มี `exp` บอกเวลาหมดอายุ

| | JWT ใบที่ 1 (login) | JWT ใบที่ 2 (embed) |
| --- | --- | --- |
| ใครสร้าง/เซ็น | IdP (Microsoft / Google) | backend ของเรา |
| ข้างในมีอะไร | ชื่อ, email, `roles: ["operations"]` | `{"resource": {"dashboard": 12}, "exp": ...}` |
| ส่งให้ใคร | เว็บเรา | Metabase |
| ตรวจลายเซ็นด้วย | public key ที่ IdP เปิดให้ดาวน์โหลด | embedding secret key ของ Metabase (ใช้ร่วมกันระหว่าง backend กับ Metabase) |

Microsoft เกี่ยวข้องแค่ใบที่ 1 ส่วนใบที่ 2 เป็นเรื่องระหว่างเรากับ Metabase

## 6. ขั้นตอนเปิด dashboard (embed)

1. ผู้ใช้ login แล้ว backend ได้ JWT ใบที่ 1
2. backend ตรวจลายเซ็น แล้วอ่าน role ได้ `operations`
3. backend ดูตาราง mapping: `operations → 12`, `engineering → 13`, `safety → 14`
4. backend สร้าง JWT ใบที่ 2 = "เปิด dashboard 12 ภายใน 10 นาที" เซ็นด้วย Metabase secret key
5. backend ส่งหน้าเว็บที่มี `<iframe src="http://metabase:3000/embed/dashboard/<JWT ใบที่ 2>">` กลับไป
6. browser โหลด iframe จาก Metabase แล้ว Metabase ตรวจลายเซ็น ถ้าถูกก็แสดง dashboard 12
7. กราฟใน dashboard 12 ใช้บัตร Trino-Ops ดังนั้น OPA จะกรองข้อมูลของ Operations ให้

**Metabase ตรวจ JWT ใบที่ 2 ยังไง:** ใช้ HS256 คือ backend เอา header และ payload มาคำนวณ HMAC-SHA256 ด้วย secret
ได้ออกมาเป็น signature (ดู `dashboard_link()` ใน `backend/app/data.py`) Metabase ซึ่งมี secret เดียวกันจะคำนวณซ้ำแล้วเทียบกับ signature
ถ้าตรงกันก็เชื่อ วิธีนี้ไม่ใช่การเข้ารหัส ข้างใน payload ทุกคนอ่านได้ แต่ถ้าไม่มี secret จะแก้ payload หรือปลอม signature ไม่ได้

**role ไปถึง Trino ทางไหน:** role ไม่ได้อยู่ใน JWT ใบที่ 2 แต่ส่งผ่านลำดับนี้
`role → (ตาราง mapping ใน backend) → dashboard id → กราฟใน dashboard → connection ของกราฟ → ช่อง user ของ connection → Trino`
ช่อง user และ password ถูกตั้งไว้ตอนสร้าง connection (ฟังก์ชัน `connection()` ใน `scripts/setup_bi_demo.py`)
driver ของ Metabase ส่งชื่อนี้ให้ Trino ทุก query และ OPA อ่านชื่อนี้ไปตัดสิน
setup เช็คด้วย `SELECT current_user` ผ่านแต่ละ connection (ฟังก์ชัน `verify()`)

**ทำไมต้องมี backend:** secret key ใช้เซ็น JWT ใบที่ 2 ถ้าใส่ไว้ใน html ใครก็เปิดดู source แล้วเอาไปเซ็นเปิด
dashboard ของ role อื่นได้ backend ตรวจ JWT ใบที่ 1 (`sign_in()` ใน `backend/app/auth.py`), เก็บ role ใน session
แล้วเลือก dashboard ของ role ก่อนเซ็น JWT ใบที่ 2 (`dashboard_link()` ใน `backend/app/data.py`)

## 7. Dashboard ต่อ role

- 1 role มี 1 dashboard (เรียกว่า Panel) และเก็บ mapping role → dashboard ไว้ใน backend
- Metabase ซ่อนกราฟบางตัวตามคนดูใน dashboard เดียวกันไม่ได้ จึงต้องแยก dashboard
- กราฟ 1 อันผูกกับบัตร 1 ใบ ถ้ากราฟ common (เช่น จำนวนเที่ยวบินต่อเดือน) ต้องมีทั้ง 3 role ให้กด
  Duplicate เป็น 3 อัน แล้วเปลี่ยนบัตรให้ตรง role แต่ละ role จะได้ตัวเลขต่างกัน ซึ่งถูกต้อง เพราะ OPA กรองแถวต่างกัน
- ถ้าวางกราฟอันเดียวกันทั้ง 3 dashboard ทุก role จะเห็นข้อมูลที่ถูกกรองด้วยบัตรเดียว ซึ่งผิด
- ออกแบบกราฟให้เข้ากับ policy:
  - column ที่ถูก mask จะแสดงเป็น `REDACTED` เช่น `tail` ของ Operations อย่าทำกราฟแยกตาม column นี้
  - column ที่ถูกห้าม (`touchdown_peak_g` ของ Operations) ถ้ากราฟไหนดึงไปด้วย กราฟนั้นจะ error

### dashboard เก็บที่ไหน

- **ต้นฉบับใน git:** `bi/dashboard.json` (รายการกราฟและตำแหน่ง) กับ `bi/queries/*.sql` (SQL ของแต่ละกราฟ)
  `scripts/setup_bi_demo.py` อ่านสองที่นี้แล้วสร้างกราฟผ่าน Metabase API
- **ตัวที่ใช้งานจริง:** เก็บใน database ภายในของ Metabase (H2 บน volume `metabase_data` ตาม `docker-compose.app.yaml`)
- ถ้าแก้กราฟในหน้า Metabase แล้วรัน `setup_bi_demo.py` ซ้ำ การแก้จะถูกทับ เพราะ script `PUT` กราฟกับ layout ใหม่จาก json
- script วนสร้าง connection และ dashboard ทีละ role จาก json ชุดเดียวกัน ไม่ต้องกด Duplicate เอง
  card ไหนไม่เหมาะกับ role ไหน กำหนดด้วย `"roles"` / `"layout"` ใน json (ดู `bi/README.md`)

## 8. ใครแก้ dashboard ได้ และแก้ที่ไหน

| ระดับ | ใคร | สิทธิ์ |
| --- | --- | --- |
| Admin | ทีม data | ทำได้ทุกอย่าง รวมถึงตั้งค่าบัตรและสิทธิ์ |
| Role editor | หัวหน้า role ละ 1–2 คน | แก้ dashboard ใน collection ของ role ตัวเองได้ ใช้ได้แค่บัตรของ role ตัวเอง |
| Viewer | คนอื่นทั้งหมด | ดูผ่านเว็บเราได้อย่างเดียว |

- การแก้ทำในหน้าเว็บของ Metabase (`localhost:3000`):
  - `+ New → Question/SQL` เพื่อสร้างกราฟ
  - เปิด dashboard แล้วกดรูปดินสอ (Edit) เพื่อลากวาง เพิ่ม filter หรือเพิ่ม tab
- หน้า embed บนเว็บเราดูได้อย่างเดียว
- การให้คนแก้กราฟได้ไม่ทำให้ข้อมูลรั่ว เพราะการตรวจสิทธิ์อยู่ที่ OPA กฎที่ห้ามพลาดคือบัตร admin ใช้ได้เฉพาะ admin

## 9. Performance

- จำนวน connection ไม่ขึ้นกับจำนวนผู้ใช้ ผู้ใช้ 30 หรือ 300 คนก็ยังมีบัตร 3 ใบ ตั้งค่าครั้งเดียว ไม่ต้องเปิดหรือปิดตอนผู้ใช้เข้าเว็บ
- ตัวที่หนักจริงคือจำนวน query: เปิด dashboard 1 ครั้งเท่ากับ 1 query ต่อ 1 กราฟ ถ้า 30 คนเปิดพร้อมกัน dashboard ละ 10 กราฟ ก็เป็น 300 query
- ทางแก้:
  - **ให้กราฟ query ตาราง Gold:** SQL ของกราฟเขียนเป็น `SELECT ... FROM iceberg.gold.flight_summary`
    ไม่ใช่คำนวณจาก `silver.rate_8hz` ที่มีหลายล้านแถวใหม่ทุกครั้ง Gold ถูกสรุปไว้ล่วงหน้าโดย pipeline (`sql/05_gold_*.sql`)
    Trino จึงอ่านตารางเล็กแค่นิดเดียว
  - **เปิด cache ใน Metabase:** คนใน role เดียวกันได้ผลลัพธ์ชุดเดียวกัน Trino ไม่ต้องคำนวณซ้ำ
    บัตรตาม role จึงใช้ cache ได้ดีกว่าบัตรรายคน

## 10. ความปลอดภัยที่ต้องแก้ก่อนส่งมอบ

ทำแล้วใน BI stack: Trino รับเฉพาะ HTTPS + password (port 8443) และ plain HTTP ไม่ publish ออกนอก container
บัตรแต่ละใบมี password ของตัวเองใน `.secrets/trino-users.json`
ยังเหลือ: certificate เป็น self-signed และ `docker-compose.yaml` หลักยังเชื่อชื่อ user ที่ส่งมาเอง

## 11. Stack

| ส่วน | ใช้อะไร |
| --- | --- |
| Login | OIDC: Google ตอนเดโม (role จาก email) และ Entra ID ของ TG ตอนใช้จริง (role จาก app roles) |
| Backend | `backend/` (FastAPI + PyJWT ใน container ของตัวเอง) ตรวจ JWT ใบที่ 1 และเซ็น JWT ใบที่ 2 ตอนส่งมอบต้องอยู่หลัง HTTPS |
| Dashboard | Metabase OSS ต่อ Trino ด้วย driver Starburst (driver ทางการของ Metabase) ใช้ static embedding |
| SQL engine | Trino ที่เปิด HTTPS และ password |
| สิทธิ์ข้อมูล | OPA และ `opa/trino.rego` เดิม |

## 12. ต้องถาม TG

1. ใช้ Microsoft 365 หรือ Entra ID อยู่หรือไม่ และ IT ของ TG ช่วยทำ App registration และ App Roles ให้ได้ไหม
2. มีงบซื้อ Metabase Pro ไหม (จะได้ SSO ในตัว Metabase, บัตรรายคน และ support)
3. ผู้ใช้ทั่วไปแค่ดู dashboard ผ่านเว็บเราก็พอ หรือต้องเข้าหน้า Metabase เองด้วย

## 13. ลำดับงาน

ทำแล้วทั้ง 4 ข้อ ตรวจได้ด้วย `powershell -File scripts/start_bi_demo.ps1 -CheckOnly`
1. ~~`setup_bi_demo.py` สร้าง connection 3 ใบ และ dashboard 3 อัน (1 ต่อ role) จากตาราง Gold~~
2. ~~login ในหน้าเว็บ (ตอนแรก Keycloak ปัจจุบันเป็น Google)~~
3. ~~backend ตรวจ JWT ใบที่ 1 อ่าน role แล้วเลือก dashboard id ก่อนเซ็น JWT ใบที่ 2~~
4. ~~Trino แบบ HTTPS และ password~~

ที่เหลือก่อนส่งมอบอยู่ท้าย `bi/README.md`
