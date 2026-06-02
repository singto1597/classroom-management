import pytest_asyncio  # 🚨 1. ห้ามลืม import ตัวนี้
import pytest
import asyncpg
import asyncio
import uuid
from urllib.parse import urlparse
from fastapi.testclient import TestClient

from core.config import settings
from main import app

@pytest_asyncio.fixture(scope="function")
async def db_pool(test_db_url):
    pool = await asyncpg.create_pool(test_db_url)
    yield pool
    await pool.close()

# 2. ฟิกซ์เจอร์สำหรับสร้างและทำลาย Test Database
# 🚨 2. เปลี่ยนตรงนี้จุดเดียว! จาก @pytest เป็น @pytest_asyncio
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

# 3. ฟิกซ์เจอร์ Client ที่ Override Database ไปใช้ Test DB
# 🚨 3. อันนี้เป็น def ธรรมดา ไม่ใช่ async def เลยใช้ @pytest.fixture ได้เหมือนเดิม!
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
    app.state.db_pool = None