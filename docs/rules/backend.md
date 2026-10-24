# ⚙️ Backend Rules (FastAPI + asyncpg)

คุณคือ Senior Backend Engineer ที่ดูแลระบบ Classroom Management System กฎเหล่านี้คือมาตรฐานที่ต้องปฏิบัติตามอย่างเคร่งครัด

## 1. Stack & Core Technologies
- **Framework:** FastAPI (Python 3.12+)
- **Database:** `asyncpg` สำหรับ PostgreSQL (**ห้ามใช้ ORM/SQLAlchemy เด็ดขาด**)
- **Validation:** `Pydantic` v2 (ใช้ `model_dump()` แทน `dict()`)
- **Logging:** `AuditLogger` (จาก `core.logger`) สำหรับบันทึกพฤติกรรมผู้ใช้

## 2. โครงสร้างและการแยก Layer (Strict MVC-like)
- **Routers (`backend/routers/`):**
  - หน้าที่: รับ Request, จัดการ Dependency Injection, และจัดการ Exception เป็น `HTTPException`
  - **กฎเหล็ก:** ห้ามมี SQL Query หรือ Business Logic ซับซ้อนใน Router
  - **Header Extraction:** ดึง Discord ID ผ่าน `x_discord_id: str = Header(...)` แล้วโยนเข้า Service เสมอ
  - ต้องมีฟังก์ชัน `get_audit_context` เพื่อดึง `client_source` และ `actor_identifier`
- **Services (`backend/services/`):**
  - หน้าที่: บรรจุ Business Logic ทั้งหมด, จัดการ Transaction, และเขียน Raw SQL ที่นี่
  - การเรียกใช้: รับ `pool: asyncpg.Pool` มาจาก Dependency Injection
- **Models (`backend/models/`):**
  - ใช้ Pydantic Models สำหรับ Request และ Response
  - **Date Params:** ตัวแปรรับค่าวันที่ต้องใช้ Type `date` หรือ `datetime` เท่านั้น ห้ามใช้ `str` ป้องกันบั๊ก `toordinal()`
  - ใน Router ต้องบังคับใส่ `response_model=...` ทุกครั้ง เพื่อกรองฟิลด์ลับออกก่อนส่งหา Client

## 3. Database & SQL Standard (asyncpg Best Practices)
- **Raw SQL Only:** ใช้ Parameterized Query (`$1, $2, ...`) ป้องกัน SQL Injection เสมอ
- **Transaction:** ถ้ามี Mutation ต่อเนื่อง (Insert/Update หลายตาราง) ต้องครอบด้วย `async with conn.transaction():` เสมอ
- **Dynamic Updates (PATCH):** ใช้ `req.model_dump(exclude_unset=True)` เอาเฉพาะฟิลด์ที่ส่งมาไปอัปเดต ป้องกันค่า None ทับของเดิม
- **Row Locking (ป้องกัน Race Condition):** ข้อมูลการเงินหรือตัดสต๊อก ต้องดึงยอดด้วย `SELECT ... FOR UPDATE` เสมอ
- **Data Limits:** การดึงข้อมูล List ยาวๆ ต้องทำ Pagination หรือใส่ `LIMIT` ห้ามดึงทั้งตาราง
- **Type Casting Quirk:** คอลัมน์ `NUMERIC/DECIMAL` ใน DB จะถูกดึงมาเป็น `decimal.Decimal` **ห้ามนำไปบวก/ลบกับ float ตรงๆ** ให้ใช้ `float(row['amount'])` แปลงก่อนคำนวณ

## 4. Deletion & Audit Logging (กฎเหล็ก)
- **Soft Delete:** ห้ามลบข้อมูลสำคัญ (เช่น ประวัติการเงิน, งานที่ส่ง) ออกจาก Disk ให้ใช้ `UPDATE ... SET deleted_at = NOW()`
- **Hard Delete:** อนุญาตเฉพาะฟังก์ชัน `permanent` และ **ต้องเช็ค Foreign Key Dependency ก่อนเสมอ** หากถูกใช้งานอยู่ให้ `raise ValueError`
- **Audit Logs:** ทุก Action ที่เปลี่ยนสถานะข้อมูล (CREATE, UPDATE, DELETE) **ต้อง** เรียกใช้ `service_logger.log(...)` ภายใน Transaction เดียวกับข้อมูลหลัก พร้อมเก็บ `old_values` และ `new_values` ให้ครบถ้วน

## 5. Security & Error Handling
- **Assume Identity (God Mode):** หาก Admin สลับสิทธิ์ผ่าน Client ส่ง `room_id` และ `x_discord_id` เข้ามา ให้ Backend เชื่อใจค่าที่ส่งมา (หากผ่าน verify_api_key แล้ว)
- **Error in Service:** หากหาข้อมูลไม่พบ หรือ Query พัง ให้ Raise Exception เฉพาะทางจาก `core.exceptions` (เช่น `StudentNotFoundError`)
- **Error in Router:** ครอบ `try...except` ดัก Exception จาก Service แล้วแปลงเป็น `HTTPException` พร้อม Status Code (400, 403, 404) ที่ถูกต้อง

## 6. Coding Standards
- **Naming:** ใช้ `snake_case` สำหรับตัวแปร/ฟังก์ชัน, `PascalCase` สำหรับ Classes
- **Type Hinting:** ต้องระบุ Type Hint ให้ครบถ้วนทั้ง Parameter และ Return Type
- **Bangkok Time:** การจัดการเวลาให้ยึดตาม `Asia/Bangkok` (UTC+7) เสมอ

## 7. Schema Migration (กฎเหล็ก — เริ่มใช้ 2026-10-24)
- **เปลี่ยนสคีมา = เขียนไฟล์ migration ใหม่ใน `backend/core/migrations/` เท่านั้น** — ห้ามเพิ่มคอลัมน์ใหม่ "ข้างในบล็อก `CREATE TABLE IF NOT EXISTS`" ของ `init_db.py` เพราะบน DB จริงบล็อกนั้นเป็น no-op ⇒ คอลัมน์ไม่ถูกสร้างเลย (เจอจริงกับ `finance_receipts.batch_id`)
- **ห้ามแก้ไฟล์ migration ที่ apply ไปแล้ว** — checksum ถูกตรึงใน `schema_migrations` ⇒ แก้แล้วบูตไม่ขึ้นด้วย `MigrationDriftError` (โดยเจตนา) ให้เขียนเลขถัดไปต่อท้ายแทน
- **Additive เท่านั้น:** `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` — `DROP TABLE`, `DROP COLUMN`, `TRUNCATE` ถูก loader ปฏิเสธ (ถ้าจำเป็นจริงต้องประกาศ `DESTRUCTIVE = True` พร้อมสำรองข้อมูลก่อน deploy)
- **รูปแบบไฟล์:** `NNNN_<ชื่อสั้นอังกฤษ>.py` (เลข 4 หลัก) ประกาศ `SQL: list[str]` — แต่ละสมาชิกคือหนึ่งคำสั่ง; ลำดับในลิสต์มีผล
- **ตรวจความ additive ของงาน:** `git diff --numstat` ของไฟล์ migration ต้องมีแต่ไฟล์ใหม่ (`+N  -0`); ถ้าเห็น `-` ในไฟล์ที่เคย apply แปลว่าแก้ของเก่า ให้ย้อน
- **จังหวะบูต:** `main.py` เรียก `init_db()` แล้วต่อด้วย `apply_migrations()`; runner ถือ advisory lock จึงปลอดภัยกับ backend 3 replica ที่บูตพร้อมกัน และคืน `0` เมื่อไม่มีไฟล์ใหม่ (ค่าที่ assert ได้ ไม่ใช่สัญญาณว่าโค้ดไม่เคยรัน)
