from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import asyncpg
import logging

from core.config import settings

from routers import classroom_sync_router

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("API_MAIN")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    ส่วนก่อน yield = ทำตอนเปิด
    ส่วนหลัง yield = ทำตอนปิด
    """
    logger.info("🚀 Starting Central API...")
    
    try:
        app.state.db_pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=1,
            max_size=10 
        )
        logger.info("✅ Database Connection Pool Created Successfully!")
        
        async with app.state.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id SERIAL PRIMARY KEY,
                    server_id BIGINT UNIQUE NOT NULL,
                    room_name TEXT NOT NULL,
                    announcement_channel_id BIGINT,
                    notify_time VARCHAR(5) DEFAULT '19:00'
                );
                CREATE TABLE IF NOT EXISTS default_schedules (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    day_of_week TEXT NOT NULL,
                    attire TEXT,
                    subjects TEXT
                );
                CREATE TABLE IF NOT EXISTS schedule_overrides (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    target_date DATE NOT NULL,
                    new_attire TEXT,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    task_name TEXT NOT NULL,
                    task_detail TEXT,
                    due_date DATE NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL 
                );
                CREATE TABLE IF NOT EXISTS daily_notes (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    target_date DATE NOT NULL,
                    bring_items TEXT,
                    announcement TEXT,
                    deleted_at TIMESTAMP DEFAULT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    user_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info("✅ Database Tables Initialized/Verified!")

    except Exception as e:
        logger.error(f"❌ Failed to connect to Database: {e}")
        raise e
    
    yield 
    
    logger.info("🛑 Shutting down... Closing Database Pool.")
    await app.state.db_pool.close()
    logger.info("✅ Database Pool Closed.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="ระบบศูนย์กลางเชื่อมต่อ Database สำหรับ Discord Bot และ Web PHP",
    lifespan=lifespan
)

app.include_router(classroom_sync_router.router, prefix="/api/classroom", tags=["Classroom"])


@app.get("/health", tags=["Health"])
async def health_check():
    try:
        # ถ้า Pool ทำงานได้ SELECT 1 จะคืนค่า 1
        async with app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": "disconnected"}