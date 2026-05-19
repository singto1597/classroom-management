import asyncpg
import asyncio
import logging
import sys
import os

# 🛠️ ตั้งค่า Path เพื่อให้รันสคริปต์นี้ตรงๆ ได้ผ่าน CLI (สำหรับเรียกใช้ core.config)
# สมมติรันจากห้อง classroom-backend: python core/init_db.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.config import settings
except ImportError:
    # เผื่อกรณีรันจาก Root Project: python classroom-backend/core/init_db.py
    sys.path.append(os.path.join(os.getcwd(), 'classroom-backend'))
    from core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("API_INIT_DB")

async def init_db(pool: asyncpg.Pool):
    """
    สร้าง Table ทั้งหมดในระบบ หากยังไม่มี (Schema Setup)
    ฟังก์ชันนี้ถูกเรียกใช้ทั้งจาก main.py (Startup) และ run_setup (Manual CLI)
    """
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # --- 1. Core / Classroom Modules ---
                await conn.execute("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id SERIAL PRIMARY KEY,
                    server_id BIGINT UNIQUE NOT NULL,
                    room_name TEXT NOT NULL,
                    announcement_channel_id BIGINT,
                    notify_time VARCHAR(5) DEFAULT '19:00',
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS default_schedules (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    day_of_week TEXT NOT NULL,
                    attire TEXT,
                    subjects TEXT,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_overrides (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    target_date DATE NOT NULL,
                    new_attire TEXT,
                    note TEXT,
                    deleted_at TIMESTAMP DEFAULT NULL
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    discord_id BIGINT,
                    student_no INTEGER NOT NULL,
                    student_id VARCHAR(10) UNIQUE, 
                    prefix TEXT, 
                    first_name TEXT NOT NULL, 
                    last_name TEXT NOT NULL,
                    nickname TEXT,
                    birthday DATE,
                    class_role TEXT DEFAULT 'student', 
                    cleaning_duty TEXT, 
                    olympic_camp TEXT,
                    portfolio TEXT,
                    target_faculty TEXT,
                    blood_group VARCHAR(3),
                    shirt_size TEXT,
                    food_allergy TEXT,
                    congenital_disease TEXT, 
                    phone_number TEXT,
                    phone_number_parent TEXT,
                    phone_number_parent_relation TEXT, 
                    line_id TEXT,
                    ig_username TEXT,
                    email TEXT,
                    address_house_no TEXT,
                    address_road TEXT,
                    address_sub_district TEXT,
                    address_district TEXT,
                    address_province TEXT,
                    address_post_code VARCHAR(10), 
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL,
                    UNIQUE(room_id, student_no) 
                );
            """)

            # --- 2. Maintenance Module ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mtn_locations (
                    id SERIAL PRIMARY KEY,
                    building TEXT NOT NULL,
                    room TEXT NOT NULL,
                    UNIQUE(building, room)
                );

                CREATE TABLE IF NOT EXISTS mtn_tickets (
                    id VARCHAR(50) PRIMARY KEY,
                    location_id INTEGER REFERENCES mtn_locations(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    image_url TEXT,
                    priority TEXT DEFAULT 'Low',
                    status TEXT DEFAULT 'pending',
                    parent_ticket_id VARCHAR(50) REFERENCES mtn_tickets(id) ON DELETE SET NULL,
                    reporter_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS mtn_logs (
                    id SERIAL PRIMARY KEY,
                    ticket_id VARCHAR(50) REFERENCES mtn_tickets(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # --- 3. Finance Module ---
            await conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS transfer_group_id_seq;

                CREATE TABLE IF NOT EXISTS finance_categories (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    category_name TEXT NOT NULL,
                    category_type TEXT NOT NULL,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_accounts (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    account_name TEXT NOT NULL,
                    balance DECIMAL DEFAULT 0.0,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS fee_collections (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    amount DECIMAL NOT NULL,
                    due_date DATE,
                    status TEXT DEFAULT 'active',
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS finance_transactions (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
                    category_id INTEGER REFERENCES finance_categories(id) ON DELETE SET NULL,
                    amount DECIMAL NOT NULL,
                    description TEXT,
                    transaction_type TEXT,
                    slip_image_url TEXT,
                    transfer_group_id INTEGER,
                    recorded_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS student_payments (
                    id SERIAL PRIMARY KEY,
                    collection_id INTEGER REFERENCES fee_collections(id) ON DELETE CASCADE,
                    student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
                    status TEXT DEFAULT 'pending',
                    paid_amount DECIMAL DEFAULT 0.0,
                    paid_to_account_id INTEGER REFERENCES finance_accounts(id),
                    slip_image_url TEXT,
                    recorded_by TEXT,
                    paid_at TIMESTAMP DEFAULT NULL,
                    transaction_id INTEGER REFERENCES finance_transactions(id) ON DELETE SET NULL,
                    deleted_at TIMESTAMP DEFAULT NULL,
                    
                    UNIQUE(collection_id, student_id)
                );
            """)

            # --- 4. Extra Alterations (เพื่อรองรับ Database เดิมที่สร้างไปก่อนแล้ว) ---
            await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS portfolio TEXT;")
            await conn.execute("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE default_schedules ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE schedule_overrides ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE finance_categories ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE fee_collections ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE student_payments ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS student_payment_id INTEGER REFERENCES student_payments(id) ON DELETE SET NULL;")
            
            logger.info("✅ Database Tables Initialized/Verified Successfully!")

    except Exception as e:
        logger.error(f"❌ Failed to initialize Database: {e}")
        raise e

async def run_setup():
    """
    ฟังก์ชันสำหรับรัน Setup ผ่าน Command Line (Manual Setup)
    """
    logger.info("🚀 Starting Manual Database Setup...")
    pool = None
    try:
        pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=1,
            max_size=5
        )
        if pool:
            await init_db(pool)
            logger.info("✨ Database Setup Process Finished!")
        else:
            logger.error("❌ Could not create database connection pool.")
    except Exception as e:
        logger.error(f"💥 Fatal Error during manual setup: {e}")
    finally:
        if pool:
            await pool.close()
            logger.info("🛑 Database pool closed.")

if __name__ == "__main__":
    # ตรวจสอบว่ามี .env หรือยังก่อนรัน
    if not settings.DATABASE_URL:
        logger.error("❌ DATABASE_URL not found in .env file!")
        sys.exit(1)
        
    asyncio.run(run_setup())
