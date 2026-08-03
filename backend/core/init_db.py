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
                
                # 🚨 [SMART MIGRATION] จัดการตาราง audit_logs เก่า
                logger.info("Checking for legacy audit_logs table...")
                await conn.execute("""
                    DO $$ 
                    BEGIN
                        -- เช็คว่ามีตาราง audit_logs ไหม และดูว่าไม่มีคอลัมน์ trace_id ใช่หรือไม่
                        -- ถ้าใช่ แปลว่าเป็นตารางเก่า ให้เปลี่ยนชื่อหลบไปเป็น audit_logs_legacy
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_logs'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns WHERE table_name = 'audit_logs' AND column_name = 'trace_id'
                        ) THEN
                            ALTER TABLE audit_logs RENAME TO audit_logs_legacy;
                        END IF;
                    END $$;
                """)

                # --- 1. สร้างตาราง Users กลาง (ศูนย์รวมตัวตนสากล) ---
                await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT UNIQUE,
                    discord_username TEXT,
                    google_id VARCHAR(255) UNIQUE,

                    username VARCHAR(100) UNIQUE,
                    password_hash TEXT,
                    avatar_url TEXT,              

                    prefix TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    nickname TEXT,
                    birthday DATE,                

                    blood_group VARCHAR(3),
                    shirt_size TEXT,
                    food_allergy TEXT,            
                    congenital_disease TEXT,      

                    phone_number TEXT,
                    email TEXT UNIQUE,            
                    line_id TEXT,
                    ig_username TEXT,

                    phone_number_parent TEXT,     
                    phone_number_parent_relation TEXT, 

                    address_house_no TEXT,
                    address_road TEXT,
                    address_sub_district TEXT,
                    address_district TEXT,
                    address_province TEXT,
                    address_post_code VARCHAR(10),

                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL
                );
                """)

                # --- 2. Core / Classroom Modules ---
                await conn.execute("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id SERIAL PRIMARY KEY,
                    server_id BIGINT UNIQUE,  
                    room_code VARCHAR(10) UNIQUE, 
                    room_name TEXT NOT NULL,
                    announcement_channel_id BIGINT,
                    notify_time VARCHAR(5) DEFAULT '19:00',
                    owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
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

                -- 🚨 ตาราง audit_logs โครงสร้างใหม่ 🚨
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    trace_id VARCHAR(50),               
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, 
                    actor_identifier VARCHAR(100) NOT NULL, 
                    client_source VARCHAR(20) NOT NULL, 
                    service_name VARCHAR(50) NOT NULL,  
                    action VARCHAR(50) NOT NULL,        
                    entity_type VARCHAR(50),            
                    entity_id VARCHAR(50),              
                    status VARCHAR(20) DEFAULT 'success', 
                    error_detail TEXT,                  
                    old_values JSONB,                   
                    new_values JSONB,                   
                    endpoint_or_command TEXT,           
                    ip_address VARCHAR(45),             
                    user_agent TEXT,                    
                    execution_time_ms INTEGER,          
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, 
                    student_no INTEGER NOT NULL,
                    student_id VARCHAR(10),
                    
                    class_role TEXT DEFAULT 'student', 
                    cleaning_duty TEXT, 
                    olympic_camp TEXT,
                    portfolio TEXT,
                    target_faculty TEXT,
                    
                    is_admin BOOLEAN DEFAULT FALSE,
                    permissions JSONB DEFAULT '[]'::jsonb,
                    
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL
                );
            """)

            # --- 3. Maintenance Module ---
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

            # --- 4. Finance Module ---
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
            
            # --- 5. Extra Alterations & Smart Constraints ---
            await conn.execute("ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS student_payment_id INTEGER REFERENCES student_payments(id) ON DELETE SET NULL;")
            
            # การเพิ่ม Constraint อย่างปลอดภัย
            await conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;")
            await conn.execute("ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email);")

            # DROP กฎเกณฑ์เก่าที่งี่เง่าทิ้ง
            await conn.execute("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_student_id_key CASCADE;")
            await conn.execute("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_room_id_student_no_key CASCADE;")
            await conn.execute("ALTER TABLE student_payments DROP CONSTRAINT IF EXISTS student_payments_collection_id_student_id_key CASCADE;")
            await conn.execute("DROP INDEX IF EXISTS idx_students_student_id_active;")

            # สร้าง PARTIAL UNIQUE INDEX (ผูกกับ room_id ทั้งหมด)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_students_room_student_id_active 
                ON students(room_id, student_id) 
                WHERE deleted_at IS NULL AND student_id IS NOT NULL;
            """)
            
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_students_room_no_active 
                ON students(room_id, student_no) 
                WHERE deleted_at IS NULL;
            """)
            
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_student_payments_active 
                ON student_payments(collection_id, student_id) 
                WHERE deleted_at IS NULL;
            """)

            # 🚨 สร้าง Index สำหรับการค้นหา Log ความเร็วสูง
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_new_values ON audit_logs USING GIN (new_values);
            """)

            await conn.execute("""
                ALTER TABLE students
                    DROP COLUMN IF EXISTS discord_id,
                    DROP COLUMN IF EXISTS prefix,
                    DROP COLUMN IF EXISTS first_name,
                    DROP COLUMN IF EXISTS last_name,
                    DROP COLUMN IF EXISTS nickname,
                    DROP COLUMN IF EXISTS birthday,
                    DROP COLUMN IF EXISTS blood_group,
                    DROP COLUMN IF EXISTS shirt_size,
                    DROP COLUMN IF EXISTS food_allergy,
                    DROP COLUMN IF EXISTS congenital_disease,
                    DROP COLUMN IF EXISTS phone_number,
                    DROP COLUMN IF EXISTS phone_number_parent,
                    DROP COLUMN IF EXISTS phone_number_parent_relation,
                    DROP COLUMN IF EXISTS line_id,
                    DROP COLUMN IF EXISTS ig_username,
                    DROP COLUMN IF EXISTS email,
                    DROP COLUMN IF EXISTS address_house_no,
                    DROP COLUMN IF EXISTS address_road,
                    DROP COLUMN IF EXISTS address_sub_district,
                    DROP COLUMN IF EXISTS address_district,
                    DROP COLUMN IF EXISTS address_province,
                    DROP COLUMN IF EXISTS address_post_code;
            """)
            
            # อัปเดตข้อมูลเก่า (Migration) ให้คนที่เคยเป็น president เป็น admin 
            await conn.execute("""
                UPDATE students 
                SET is_admin = TRUE 
                WHERE class_role = 'president' AND is_admin = FALSE;
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