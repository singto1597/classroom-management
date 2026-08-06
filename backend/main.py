from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncpg
import logging

from core.config import settings
from core.init_db import init_db

from routers import classroom_sync_router
from routers import student_router
from routers import finance_router
from routers import auth_router
from routers import room_router
from routers import action_router

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
        
        # 🚀 เรียกใช้ Schema Setup จาก core.init_db
        await init_db(app.state.db_pool)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://127.0.0.1:5173",
        "https://classtestts.singto1597.xyz",
        "https://classts.singto1597.xyz",
        "https://class.singto1597.xyz"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(room_router.router, prefix="/api/classroom", tags=["Rooms"])
app.include_router(classroom_sync_router.router, prefix="/api/classroom", tags=["Classroom"])
app.include_router(student_router.router, prefix="/api/classroom", tags=["Students"])
app.include_router(finance_router.router, prefix="/api/classroom", tags=["Finance"])
app.include_router(action_router.router, prefix="/api/classroom", tags=["Actions"])


@app.get("/health", tags=["Health"])
async def health_check():
    try:
        # ถ้า Pool ทำงานได้ SELECT 1 จะคืนค่า 1
        async with app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": "disconnected"}
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
