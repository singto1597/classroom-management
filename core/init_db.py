import asyncpg
import asyncio
import logging
import sys
import os

# 🛠️ ตั้งค่า Path เพื่อให้รันสคริปต์นี้ตรงๆ ได้ผ่าน CLI (สำหรับเรียกใช้ core.config)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.config import settings
except ImportError:
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
                    server_id BIGINT UNIQUE,  -- 🚨 ปลด NOT NULL ออกเพื่อรองรับ Web-Centric
                    room_code VARCHAR(10) UNIQUE, -- 🚨 เพิ่มรหัสเข้าห้องสำหรับเว็บ
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
                    student_id VARCHAR(10),  -- 🚨 ลบ UNIQUE ออกจากตรงนี้แล้ว
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
                    deleted_at TIMESTAMP DEFAULT NULL
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
                    deleted_at TIMESTAMP DEFAULT NULL
                );
            """)
            await conn.execute("""
                -- 1. สร้างตาราง Users กลาง (ศูนย์รวมตัวตนสากล)
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT UNIQUE,
                    google_id VARCHAR(255) UNIQUE, -- 🚨 รองรับ Google Login สำหรับเว็บ
                    
                    -- ระบบ Login (รองรับอนาคต)
                    username VARCHAR(100) UNIQUE,
                    password_hash TEXT,
                    avatar_url TEXT,              -- เผื่อเก็บลิงก์รูปโปรไฟล์

                    -- ข้อมูลส่วนตัวพื้นฐาน
                    prefix TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    nickname TEXT,
                    birthday DATE,                

                    -- ข้อมูลทางกายภาพและสุขภาพ
                    blood_group VARCHAR(3),
                    shirt_size TEXT,
                    food_allergy TEXT,            
                    congenital_disease TEXT,      

                    -- ข้อมูลติดต่อ (ส่วนตัว)
                    phone_number TEXT,
                    email TEXT UNIQUE,            -- 🚨 อัปเดตให้บังคับ UNIQUE       
                    line_id TEXT,
                    ig_username TEXT,

                    -- ข้อมูลติดต่อ (ผู้ปกครอง)
                    phone_number_parent TEXT,     
                    phone_number_parent_relation TEXT, 

                    -- ที่อยู่ (ตามทะเบียนบ้าน / ปัจจุบัน)
                    address_house_no TEXT,
                    address_road TEXT,
                    address_sub_district TEXT,
                    address_district TEXT,
                    address_province TEXT,
                    address_post_code VARCHAR(10),

                    -- Metadata ระบบ
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                -- 2. เพิ่ม Foreign Key กลับไปที่ตาราง students เดิม
                ALTER TABLE students ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
            """)
            
            # --- 4. Extra Alterations & Smart Constraints ---
            await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS portfolio TEXT;")
            await conn.execute("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE default_schedules ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE schedule_overrides ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE finance_categories ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE fee_collections ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE student_payments ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS student_payment_id INTEGER REFERENCES student_payments(id) ON DELETE SET NULL;")
            await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            await conn.execute("ALTER TABLE daily_notes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP DEFAULT NULL;")
            
            # 🚨 5. Big Refactoring Alterations (Migration Update)
            await conn.execute("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS room_code VARCHAR(10) UNIQUE;")
            await conn.execute("ALTER TABLE rooms ALTER COLUMN server_id DROP NOT NULL;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE;")
            
            # การเพิ่ม Constraint อย่างปลอดภัย (กัน Error กรณีมีคีย์นี้อยู่แล้ว)
            await conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;")
            await conn.execute("ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email);")

            # 🚨 6. DROP กฎเกณฑ์เก่าที่งี่เง่าทิ้ง
            await conn.execute("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_student_id_key CASCADE;")
            await conn.execute("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_room_id_student_no_key CASCADE;")
            await conn.execute("ALTER TABLE student_payments DROP CONSTRAINT IF EXISTS student_payments_collection_id_student_id_key CASCADE;")
            # ดรอป Index เก่าที่ผมให้ไปเมื่อกี้ (เผื่อคุณเผลอรันไปแล้ว)
            await conn.execute("DROP INDEX IF EXISTS idx_students_student_id_active;")

            # 🚨 7. สร้าง PARTIAL UNIQUE INDEX (ผูกกับ room_id ทั้งหมด)
            
            # - รหัส นร. ห้ามซ้ำ "ภายในห้องเดียวกัน" (ถ้ายังไม่ถูกลบ)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_students_room_student_id_active 
                ON students(room_id, student_id) 
                WHERE deleted_at IS NULL AND student_id IS NOT NULL;
            """)
            
            # - เลขที่ ห้ามซ้ำ "ภายในห้องเดียวกัน" (ถ้ายังไม่ถูกลบ)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_students_room_no_active 
                ON students(room_id, student_no) 
                WHERE deleted_at IS NULL;
            """)
            
            # - บิลเก็บเงิน 1 บิลต่อ 1 นักเรียน ห้ามสร้างซ้ำ (ถ้ายังไม่ถูกยกเลิก)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_student_payments_active 
                ON student_payments(collection_id, student_id) 
                WHERE deleted_at IS NULL;
            """)

            logger.info("✅ Database Tables & Smart Constraints Initialized Successfully!")

    except Exception as e:
        logger.error(f"❌ Failed to initialize Database: {e}")
        raise e

async def run_setup():
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
    if not settings.DATABASE_URL:
        logger.error("❌ DATABASE_URL not found in .env file!")
        sys.exit(1)
        
    asyncio.run(run_setup())