import pytest_asyncio
import pytest
import asyncpg
import asyncio
import random
import string
import uuid
from urllib.parse import urlparse
from fastapi.testclient import TestClient

from core.config import settings
from main import app
# 👇 Import ฟังก์ชันสร้างตารางของมึงมา
from core.init_db import init_db 

@pytest_asyncio.fixture(scope="session")
async def test_db_url():
    """
    สร้าง PostgreSQL Database ใหม่แบบสุ่มชื่อ และคืนค่า URL กลับไป
    เมื่อเทสต์เสร็จสิ้น จะทำการ Drop Database ทิ้ง
    """
    db_name = f"test_db_{uuid.uuid4().hex}"
    
    parsed_url = urlparse(settings.DATABASE_URL)
    base_url = f"{parsed_url.scheme}://{parsed_url.username}:{parsed_url.password}@{parsed_url.hostname}:{parsed_url.port}"
    sys_db_url = f"{base_url}/postgres"

    sys_conn = await asyncpg.connect(sys_db_url)
    try:
        await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await sys_conn.close()

    new_db_url = f"{base_url}/{db_name}"
    
    # 👇 เปลี่ยน URL ชั่วคราว แล้วสั่งสร้างตารางให้ครบทุกตาราง
    original_db_url = settings.DATABASE_URL
    settings.DATABASE_URL = new_db_url
    
    temp_pool = None
    try:
        # 🚨 สร้าง Pool ชั่วคราวเพื่อส่งให้ init_db ของมึงทำงานได้
        temp_pool = await asyncpg.create_pool(new_db_url)
        await init_db(temp_pool)
    except Exception as e:
        print(f"Error initializing test database schema: {e}")
    finally:
        if temp_pool:
            await temp_pool.close()
        settings.DATABASE_URL = original_db_url

    yield new_db_url  

    sys_conn = await asyncpg.connect(sys_db_url)
    try:
        await sys_conn.execute(f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
            AND pid <> pg_backend_pid();
        """)
        await sys_conn.execute(f'DROP DATABASE "{db_name}"')
    finally:
        await sys_conn.close()


@pytest_asyncio.fixture(scope="function")
async def db_pool(test_db_url):
    pool = await asyncpg.create_pool(test_db_url)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def clean_database(db_pool):
    """
    ล้างข้อมูลทุกตารางในฐานข้อมูลก่อนที่แต่ละฟังก์ชัน Test จะทำงาน
    (ใช้ CASCADE เพื่อเคลียร์ Foreign Key ทะลุลงไปถึงตารางลูก)
    """
    async with db_pool.acquire() as conn:
        # 🚨 ล้างแค่ Master Tables หลักๆ CASCADE จะจัดการตารางลูกให้เอง
        # (mtn_locations ถูกถอดออกจากลิสต์ 2026-09-25 พร้อมกับ DDL ของมันใน init_db.py)
        await conn.execute("""
            TRUNCATE TABLE users, rooms CASCADE;
        """)
    yield


@pytest.fixture(scope="function")
def client(test_db_url):
    """
    สร้าง TestClient ของ FastAPI
    โดยเปลี่ยน settings.DATABASE_URL ให้ชี้ไปที่ Test DB ชั่วคราว
    """
    original_db_url = settings.DATABASE_URL
    settings.DATABASE_URL = test_db_url

    with TestClient(app) as test_client:
        yield test_client

    settings.DATABASE_URL = original_db_url


# =============================================================================
# 🔑 Auth fixtures — ห้อง + ผู้ใช้ 3 ระดับสิทธิ์ (ใช้กับ endpoint การเงิน)
# =============================================================================
# docs/rules/testing.md อ้างถึง `admin_headers` มาตลอดแต่ของจริงไม่เคยมี — ชุดนี้คือของจริง
#
# ข้อบังคับ 3 ข้อที่ห้ามละเมิด:
#   1. **function-scoped เท่านั้น** — `clean_database` เป็น autouse และ TRUNCATE
#      users/rooms CASCADE ก่อนทุกเทสต์ → fixture ระดับ session/module
#      จะถูกล้างทิ้งตั้งแต่เทสต์แรก แล้วเทสต์ถัด ๆ ไปจะได้ 404 (หา users ไม่เจอ) แทน 403
#   2. **ต้องสร้างห้อง+ผู้ใช้ของตัวเองทุกครั้ง** — ห้าม hardcode id
#   3. **ใช้เส้นทาง API key** (`X-API-Key` + `X-Discord-Id`) เหมือนบอท → `get_current_user`
#      resolve discord_id → user_id ให้เอง ไม่ต้อง mint JWT


class _AuthContext(dict):
    """dict ของ headers ที่พา room_id/user_id/student_id มาด้วย.

    ใช้เป็น headers ได้ตรง ๆ — `client.get(url, headers=admin_headers)`
    แต่ทุก endpoint การเงินต้องมี `{target_id}` อยู่ใน URL จึงต้องรู้ว่าตัวเองผูกกับห้องไหน
    (ถ้าให้แค่ headers เปล่า ๆ จะเอาไปยิง API ไม่ได้เลย)
    """

    def __init__(self, headers: dict, *, room_id: int, user_id: int, student_id: int, discord_id: int):
        super().__init__(headers)
        self.room_id = room_id
        self.user_id = user_id
        self.student_id = student_id
        self.discord_id = discord_id


async def _provision_auth_context(pool, *, is_admin: bool, permissions: str) -> _AuthContext:
    """สร้าง user + room + students row แล้วคืน _AuthContext ที่ยิง API ได้ทันที."""
    # สุ่ม discord_id ตามกฎ "ห้าม hardcode ID" (ช่วง 7 หลัก)
    # ⚠️ discord_id ไม่ related กับ SUPER_ADMIN_ID — โค้ดทุกจุดเทียบ SUPER_ADMIN_ID กับ
    # `users.id` (ดู core/rbac.py) ไม่ใช่ discord_id ดังนั้นการสุ่มช่วงนี้ไม่ได้ "กัน" อะไร
    # กับ SUPER_ADMIN_ID=999999999999999 ใน docker-compose.test.yml และไม่จำเป็นต้องกัน
    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            None, "Test", "User", f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        # ไม่ส่ง server_id → ห้องนี้ไม่ผูก Discord จึงไม่มีการเรียก Redis เลย
        # (ActionService._add_transaction guard ด้วย `if room_server_id:`) → ไม่ต้อง mock
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            "Test Room", code, user_id,
        )
        student_id = await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 1, $3, 'active', $4, $5::jsonb)
            RETURNING id
            """,
            room_id, user_id, "president" if is_admin else "student", is_admin, permissions,
        )
    return _AuthContext(
        {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)},
        room_id=room_id, user_id=user_id, student_id=student_id, discord_id=discord_id,
    )


@pytest_asyncio.fixture(scope="function")
async def admin_headers(db_pool) -> _AuthContext:
    """ห้อง + ผู้ใช้ที่เป็น admin (is_admin=TRUE) — bypass RBAC ได้ทุกด่าน."""
    return await _provision_auth_context(db_pool, is_admin=True, permissions="[]")


@pytest_asyncio.fixture(scope="function")
async def member_headers(db_pool) -> _AuthContext:
    """สมาชิกธรรมดา — ไม่ใช่ admin และไม่ถือสิทธิ์ใด ๆ (อ่านได้ / เขียนไม่ได้)."""
    return await _provision_auth_context(db_pool, is_admin=False, permissions="[]")


@pytest_asyncio.fixture(scope="function")
async def finance_manager_headers(db_pool) -> _AuthContext:
    """เหรัญญิก — สมาชิกธรรมดาที่ถือ `MANAGE_FINANCE` (ไม่ใช่ admin).

    แยกจาก admin โดยเจตนา เพื่อพิสูจน์ว่า `require_permission` ทำงานจริง
    ไม่ได้ผ่านเพราะ is_admin bypass
    """
    return await _provision_auth_context(db_pool, is_admin=False, permissions='["MANAGE_FINANCE"]')