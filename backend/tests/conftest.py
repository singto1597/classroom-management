import pytest_asyncio
import pytest
import asyncpg
import asyncio
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
        await conn.execute("""
            TRUNCATE TABLE users, rooms, mtn_locations CASCADE;
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