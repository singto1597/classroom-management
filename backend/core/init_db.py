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

                    -- 🌟 ชื่อภาษาอังกฤษ — "กุญแจตัวตน" หลัก (identity/dedupe/search)
                    -- ชื่อไทย (first_name/last_name) เป็นของแสดงผล; อังกฤษ nullable จนกว่าจะกรอก
                    first_name_en TEXT,
                    last_name_en TEXT,
                    nickname_en TEXT,


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
                    birthday_channel_id BIGINT,
                    minor_notify_channel_id BIGINT,
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

                    identity_claimed BOOLEAN NOT NULL DEFAULT FALSE,
                    added_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    claim_meta JSONB DEFAULT '{}'::jsonb,

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

                -- 1. ผังบัญชีกลาง (Chart of Accounts)
                CREATE TABLE IF NOT EXISTS accounting_ledgers (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    account_code VARCHAR(20), -- รหัสบัญชี (เช่น 1001, 4001)
                    account_name TEXT NOT NULL,
                    account_type VARCHAR(20) NOT NULL, -- 'asset', 'liability', 'equity', 'revenue', 'expense'
                    is_active BOOLEAN DEFAULT TRUE,
                    
                    -- 🔗 ฟิลด์สำหรับทำ Mapping (Phase 2) ถ้าระบบเก่าพังหรือต้องการย้อนดู
                    legacy_account_id INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
                    legacy_category_id INTEGER REFERENCES finance_categories(id) ON DELETE SET NULL,
                    
                    description TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );

                -- 2. สมุดรายวันทั่วไป (Journal Entries - หัวบิล)
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), -- ใช้ UUID ป้องกันการเดาเลขบิล (เหมือนตาราง audit_logs)
                    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
                    
                    -- 🔗 การเชื่อมโยงกับระบบห้องเรียน
                    reference_type VARCHAR(50), -- เช่น 'fee_collection', 'transfer', 'manual_adjustment'
                    reference_id VARCHAR(50), -- เก็บ ID อ้างอิง (เช่น student_payment_id)
                    
                    -- 📝 รายละเอียดการทำรายการ
                    description TEXT NOT NULL,
                    slip_image_url TEXT,
                    recorded_by TEXT,
                    
                    -- ⚙️ สถานะและข้อมูลเชิงลึก
                    status VARCHAR(20) DEFAULT 'posted', -- 'draft', 'posted', 'voided' (รองรับการ Revert)
                    transaction_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- วันที่เกิดรายการจริง
                    
                    -- 💡 จุดซ่อนสเปค "เก็บให้เยอะที่สุด"
                    metadata JSONB DEFAULT '{}'::jsonb, 
                    
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL
                );

                -- 3. รายการบันทึกบัญชี (Journal Lines - รายละเอียดเดบิต/เครดิต)
                CREATE TABLE IF NOT EXISTS journal_lines (
                    id BIGSERIAL PRIMARY KEY,
                    journal_entry_id UUID REFERENCES journal_entries(id) ON DELETE CASCADE,
                    ledger_id INTEGER REFERENCES accounting_ledgers(id) ON DELETE RESTRICT,
                    
                    debit DECIMAL(15,4) DEFAULT 0.0000,
                    credit DECIMAL(15,4) DEFAULT 0.0000,
                    
                    -- 📝 รายละเอียดเสริมเฉพาะบรรทัด
                    line_description TEXT,
                    
                    -- 🛡️ ป้องกันการใส่ค่าติดลบ
                    CONSTRAINT chk_positive_amounts CHECK (debit >= 0 AND credit >= 0),
                    -- 🛡️ ป้องกันการใส่ข้อมูลซ้ำซ้อน (ต้องมีแค่ฝั่งใดฝั่งหนึ่ง หรือศูนย์ทั้งคู่)
                    CONSTRAINT chk_mutually_exclusive CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0) OR (debit = 0 AND credit = 0)),
                    
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );

                -- 🚀 สร้าง Index เพื่อความเร็วในการ Query งบการเงิน
                CREATE INDEX IF NOT EXISTS idx_journal_lines_ledger ON journal_lines(ledger_id);
                CREATE INDEX IF NOT EXISTS idx_journal_entries_room_date ON journal_entries(room_id, transaction_date);
                CREATE INDEX IF NOT EXISTS idx_journal_entries_metadata ON journal_entries USING GIN (metadata);

                -- 💰 งบประมาณรายหมวด/รายงวด (Budget) — F2
                -- เก็บ "ทั้ง" ฟิลด์แสดงผล (period_type/year/month) และ start_date/end_date ที่
                -- materialize ไว้ เพราะยอด "ใช้ไป" ต้องเป็น range predicate บนคอลัมน์ DATE ธรรมดา
                -- (ถ้าคำนวณจาก year/month ตอน query จะเสีย index และรองรับ period_type='custom' ไม่ได้)
                CREATE TABLE IF NOT EXISTS finance_budgets (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    -- ⚠️ RESTRICT เจตนา: กันการลบหมวดที่ยังมีงบผูกอยู่
                    -- (delete_category เป็น hard delete + ไม่มี guard จะได้ ForeignKeyViolationError ดิบ → 500)
                    category_id INTEGER NOT NULL REFERENCES finance_categories(id) ON DELETE RESTRICT,
                    period_type VARCHAR(10) NOT NULL DEFAULT 'monthly',   -- monthly | yearly | custom
                    period_year INTEGER NOT NULL,                          -- ปี ค.ศ.
                    period_month INTEGER,                                  -- 1-12 (NULL เมื่อ yearly/custom)
                    start_date DATE NOT NULL,                              -- ขอบเขตที่ใช้คิดจริง (inclusive)
                    end_date DATE NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    note TEXT,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL,
                    CONSTRAINT chk_budget_amount_positive CHECK (amount > 0),
                    CONSTRAINT chk_budget_period_order CHECK (end_date >= start_date)
                );

                -- ทำหน้าที่ 2 อย่างพร้อมกัน: (ก) กันเขียนงบซ้ำช่วง/ซ้ำหมวดชนกัน
                -- (ข) เป็น index ของเงื่อนไข `deleted_at IS NULL` ที่ทุก query ใช้
                CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_budgets_active
                    ON finance_budgets(room_id, category_id, start_date, end_date)
                    WHERE deleted_at IS NULL;

                CREATE INDEX IF NOT EXISTS idx_finance_budgets_room_period
                    ON finance_budgets(room_id, start_date, end_date)
                    WHERE deleted_at IS NULL;

                -- 🧾 เลขรันเอกสาร รายห้อง/รายปี พ.ศ. — F3
                -- เก็บ "ตัวนับ" ไม่ใช่คำนวณจาก ROW_NUMBER() ตอนอ่าน เพราะเลขที่ derive
                -- จะเปลี่ยนย้อนหลังทันทีที่มีการ revert รายการก่อนหน้า (revert_transaction
                -- reset paid_amount/paid_at/transaction_id ของ student_payments) ⇒
                -- ใบเสร็จที่พิมพ์ออกไปแล้วจะเปลี่ยนเลข = เอกสารทางบัญชีใช้ไม่ได้
                CREATE TABLE IF NOT EXISTS receipt_sequences (
                    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    year_be INTEGER NOT NULL,                              -- ปี พ.ศ. (ค.ศ. + 543)
                    doc_type VARCHAR(20) NOT NULL DEFAULT 'receipt',       -- receipt | invoice
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    -- PK ผสมทำหน้าที่เป็นเป้า ON CONFLICT ของการจองเลขแบบอะตอมมิก
                    PRIMARY KEY (room_id, year_be, doc_type)
                );

                -- 🧾 ใบเสร็จ / ใบแจ้งหนี้ (Receipt / Invoice) — F3
                -- เก็บ "snapshot" ชื่อผู้ชำระ/ผู้ออกเอกสาร ณ เวลาที่ออก เพราะเอกสารที่พิมพ์
                -- ออกไปแล้วต้องไม่ย้อนเปลี่ยนตามการแก้ชื่อในอนาคต
                CREATE TABLE IF NOT EXISTS finance_receipts (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    receipt_no VARCHAR(40) NOT NULL,                       -- เช่น REC-2569-0042
                    doc_type VARCHAR(20) NOT NULL DEFAULT 'receipt',       -- receipt | invoice
                    year_be INTEGER NOT NULL,
                    seq INTEGER NOT NULL,                                  -- ลำดับภายใน (room, year_be, doc_type)
                    student_payment_id INTEGER REFERENCES student_payments(id) ON DELETE SET NULL,
                    -- 🎯 ชี้ "งวดที่รับเงิน" ไม่ใช่บิล — student_payments.transaction_id ถูกทับ
                    --    ทุกครั้งที่จ่ายงวดใหม่ จึงใช้ระบุเหตุการณ์รับเงินไม่ได้
                    legacy_transaction_id INTEGER REFERENCES finance_transactions(id) ON DELETE SET NULL,
                    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
                    collection_id INTEGER REFERENCES fee_collections(id) ON DELETE SET NULL,
                    amount DECIMAL(15,2) NOT NULL,                         -- ยอดที่ออกเอกสารครั้งนี้
                    paid_total_after DECIMAL(15,2) NOT NULL,               -- ยอดสะสมหลังรับครั้งนี้
                    issued_to_name TEXT,                                   -- snapshot ชื่อผู้ชำระ
                    issued_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    issued_by_name TEXT,
                    note TEXT,
                    -- 🗓️ "เวลาของเหตุการณ์" ที่เอกสารนี้พูดถึง = **แหล่งความจริงเพียงหนึ่งเดียว**
                    --    ของทั้งปี พ.ศ. บนเลขเอกสาร และวันที่ที่พิมพ์บนกระดาษ
                    --    ใบเสร็จ → เวลาที่รับเงินงวดนั้น / ใบแจ้งหนี้ → เวลาที่ออกเอกสาร
                    --    ⇒ พิมพ์ซ้ำหรือเปิดดูเมื่อไรก็ได้วันที่เดิมเสมอ ไม่ขึ้นกับว่าดูตอนไหน
                    event_at TIMESTAMP WITH TIME ZONE,
                    -- 📋 รายการย่อยที่เอกสารนี้แจกแจง (ใบแจ้งหนี้รวมยอดหลายโครงการ)
                    --    🔴 **snapshot** ไม่ใช่คำนวณใหม่ตอนพิมพ์: ยอดบรรทัดต้องรวมได้เท่ากับ
                    --    `amount` ที่พาดหัวเสมอ ⇒ ถ้า recompute ตอนพิมพ์ ใบที่พิมพ์ซ้ำหลังนักเรียน
                    --    จ่ายบางส่วนจะได้บรรทัดรวม ≠ ยอดพาดหัว = เอกสารขัดแย้งตัวเอง
                    --    NULL = เอกสารใบเดียวต่อหนึ่งบิล (ใบเสร็จทุกใบ / ใบแจ้งหนี้แบบเก่า)
                    line_items JSONB,
                    -- 🚫 active | voided — รายการที่ถูกยกเลิกต้องไม่ทิ้งใบเสร็จค้างเป็น active
                    --    (void ตั้ง `deleted_at` คู่กัน ⇒ ทุกจุดอ่านเดิมกรองออกให้เอง — ดู transactions.py)
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    voided_at TIMESTAMP WITH TIME ZONE,
                    voided_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    void_reason TEXT,
                    issued_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL,
                    CONSTRAINT chk_receipt_amount_positive CHECK (amount > 0),
                    CONSTRAINT chk_receipt_status CHECK (status IN ('active', 'voided')),
                    -- 🔒 "ใบที่ยกเลิกแล้วต้องถูก soft delete ด้วยเสมอ" — บังคับทิศทางเดียว
                    --    ร่วมกับ `chk_receipt_status` ไม่ได้ (ตัวนั้นแค่จำกัดโดเมนของค่า)
                    --
                    -- ⚠️ ทำไมต้องบังคับที่ DB ไม่ใช่แค่เขียนในโค้ด: `deleted_at` **ไม่ใช่แค่ธง**
                    --    มันคือ predicate ของ `idx_finance_receipts_tx_active` และของทุกจุดอ่าน
                    --    ⇒ แถวที่ `status='voided'` แต่ `deleted_at IS NULL` จะ
                    --      (ก) ยังถูก partial unique index นับว่ามีอยู่ ⇒ ออกใบใหม่ของงวดเดิมไม่ได้ (400)
                    --      (ข) ถูก `_find_existing` ปฏิเสธเพราะกรอง status ⇒ งอก็ไม่กลับมา
                    --      = สถานะที่ **ตันทั้งสองทาง** และข้อความ error ก็โกหก ("เลขเอกสารซ้ำ")
                    --    ปล่อยเป็นความเชื่อในหัวคนเขียนไม่ได้ เพราะไม่มีเทสต์ไหนพิสูจน์ได้
                    --    ว่าทุกเส้นทางเขียนจะตั้งสองคอลัมน์คู่กันจริง
                    CONSTRAINT chk_receipt_voided_is_deleted
                        CHECK (status = 'active' OR deleted_at IS NOT NULL)
                );

                -- กันเลขเอกสารซ้ำภายในห้องเดียวกัน (ต่อ doc_type) — เป็นด่านสองของการจองเลข
                CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_doc_active
                    ON finance_receipts(room_id, doc_type, receipt_no) WHERE deleted_at IS NULL;

                -- 🔒 ใบเสร็จผูกกับ "เหตุการณ์รับเงิน" 1 ครั้ง → ออกซ้ำไม่ได้ (idempotent)
                --    ใบแจ้งหนี้ "ไม่อยู่ใน predicate นี้" โดยเจตนา — ยอดค้างของนักเรียนเปลี่ยน
                --    ได้เมื่อจ่ายเพิ่ม ใบเดิมจึงออกซ้ำได้ตามธรรมชาติ (point-in-time, กินเลขใหม่)
                --
                -- ⚠️ COALESCE(..., 0) แทน `IS NOT NULL` ใน predicate: ถ้ากรองด้วย IS NOT NULL
                --    ใบเสร็จของบิลที่ยืนยันก่อนยุค dual-write (ไม่มีแถว finance_transactions)
                --    จะ "หลุด" ออกจาก unique index ทั้งที่ student_payment_id มีค่า ⇒ สองคำขอ
                --    พร้อมกันสร้างใบเสร็จซ้ำได้ ตัว app-level SELECT ยังกันไว้ชั้นหนึ่ง แต่ไม่พอ
                --    สำหรับเอกสารการเงิน ⇒ ให้ index บังคับด้วยคีย์ที่ normalize แล้ว
                CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_tx_active
                    ON finance_receipts(student_payment_id, COALESCE(legacy_transaction_id, 0), doc_type)
                    WHERE deleted_at IS NULL AND doc_type = 'receipt';

                -- ครอบ query หลักของ get_receipts: WHERE room_id = $1 AND deleted_at IS NULL ...
                CREATE INDEX IF NOT EXISTS idx_finance_receipts_room_year
                    ON finance_receipts(room_id, year_be, doc_type);

                -- ครอบเส้นทาง "เอกสารของนักเรียนคนนี้" (กรองรายคน + กรองชนิดเอกสาร)
                -- เดิมไม่มี index บน student_id เลย — รับได้ตอนข้อมูลน้อย แต่เป็นคีย์ที่
                -- หน้าลูกหนี้/รายละเอียดนักเรียนใช้บ่อยที่สุดของการอ่านเอกสาร
                CREATE INDEX IF NOT EXISTS idx_finance_receipts_room_student
                    ON finance_receipts(room_id, student_id, doc_type) WHERE deleted_at IS NULL;

                -- 🔒 ใบรับเงินล่วงหน้า (doc_type = 'deposit') — กันซ้ำด้วย index ของตัวเอง
                --
                -- ⚠️ **ทำไมใช้ `idx_finance_receipts_tx_active` ไม่ได้**: index นั้นมี
                --    `student_payment_id` เป็นคอลัมน์แรก และใบรับเงินล่วงหน้า **ไม่มีบิล**
                --    ⇒ `student_payment_id IS NULL`
                --    ⇒ Postgres ถือว่า NULL แต่ละตัว "ไม่ซ้ำกัน" (NULLs are distinct) ⇒
                --      **ไม่มีการกันซ้ำเกิดขึ้นเลย** ยิงพร้อมกันได้เอกสารซ้ำโดยที่ index
                --      ดูเหมือนครอบอยู่แล้ว — อันตรายเพราะอ่านโค้ดแล้วเข้าใจผิดได้ง่าย
                --
                -- ⇒ ใช้คีย์ที่ normalize แล้ว (COALESCE) เหมือนบทเรียนเดียวกับ index ข้างบน
                --   และเป็น **ชื่อใหม่** ⇒ `IF NOT EXISTS` ซื่อสัตย์ที่นี่
                --   (index เก่าที่มีอยู่แล้วเปลี่ยน predicate ไม่ได้ — IF NOT EXISTS จะข้ามเงียบ ๆ)
                CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_deposit_active
                    ON finance_receipts(COALESCE(legacy_transaction_id, 0), doc_type)
                    WHERE deleted_at IS NULL AND doc_type = 'deposit';

                -- 💰 เครดิตคงเหลือรายนักเรียน (เงินรับล่วงหน้า) — F4
                --    append-only ledger: ทุกรายการเป็น "เหตุการณ์" ห้าม UPDATE ยอดเดิม
                --    ⇒ ยอดปัจจุบัน = `balance_after` ของแถวล่าสุด (ดู index ข้างล่าง)
                --
                -- 🔴 ทำไมต้องมีตารางนี้แทนการใช้ `journal_lines` ตรง ๆ:
                --    ขา liability ของเงินรับล่วงหน้าต้องแยกได้ **รายคน** แต่
                --    `journal_lines` ไม่มี `student_id` (มีแต่ ledger_id) และการยัด
                --    student_id ลง `metadata` (JSONB) ก็อ่านยอดด้วย GIN scan ไม่ได้จริง
                --    ⇒ repo นี้หลีกเลี่ยงการใช้ JSONB กับ "เงิน" ⇒ ตารางของตัวเอง
                CREATE TABLE IF NOT EXISTS student_credits (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    -- topup = รับเงินเข้ามาพัก / apply = หักไปปิดบิล / reverse = ยกเลิกการหัก
                    entry_type VARCHAR(15) NOT NULL,
                    -- 🔑 เก็บเป็น **ค่าบวกเสมอ** — ทิศทางมาจาก `entry_type` ไม่ใช่เครื่องหมาย
                    --    ⇒ `chk_student_credit_amount_positive` จับ "ลบ" ได้ทุกกรณี
                    amount DECIMAL(15,2) NOT NULL,
                    -- 📸 ยอดคงเหลือ **หลัง** รายการนี้ — snapshot ตามสไตล์ `paid_total_after`
                    --    และ `receipt_sequences.last_seq`: repo นี้เก็บ snapshot ไม่คำนวณย้อนหลัง
                    --    ⇒ อ่านยอดปัจจุบัน = แถวล่าสุด (indexed) ไม่ใช่ SUM() ที่เพี้ยนได้เมื่อมี reverse
                    --    ⚠️ เก็บ snapshot เพราะยอด "ที่ถูกต้อง ณ ตอนนั้น" เป็นข้อเท็จจริงทางบัญชี
                    --       ส่วน SUM() ตอนอ่านจะให้ยอดที่ "คำนวณใหม่ตามความเชื่อปัจจุบัน"
                    balance_after DECIMAL(15,2) NOT NULL,
                    -- เหตุการณ์รับเงินที่ทำให้เกิดรายการนี้ (มีค่าเฉพาะ entry_type = 'topup')
                    finance_transaction_id INTEGER REFERENCES finance_transactions(id) ON DELETE SET NULL,
                    -- 🔗 journal entry ที่รายการนี้ลงไว้ — **มีค่าเฉพาะ 'apply'/'reverse'**
                    --
                    -- ⚠️ ทำไมต้องมีคอลัมน์นี้แทนการค้นด้วย `metadata->>'student_credit_id'`:
                    --    (ก) เส้นทาง `undo_credit_application` ต้อง "ตามกลับไป void journal ให้ได้"
                    --        ซึ่งเป็นการเขียน — การพึ่ง JSONB ที่ไม่มีดัชนีตรง ๆ เปิดช่องให้ช้ากัง
                    --        โดยไม่มีใครรู้ และ repo นี้เลี่ยงใช้ JSONB กับ "เงิน" อยู่แล้ว
                    --        (ดูเหตุผลเดียวกับที่ตารางนี้มีอยู่แทนที่จะยัด student_id ลง metadata)
                    --    (ข) `finance_transaction_id` ใช้กับการเติมเครดิต (มีแถว legacy)
                    --        ส่วนการหักเครดิต **ไม่มีแถว legacy เลย** ⇒ คอลัมน์เดิมเป็น NULL
                    --        ⇒ ถ้าไม่มีคอลัมน์นี้ รายการหักจะไม่เหลือร่องรอยว่าไปลง journal ใบไหน
                    journal_entry_id UUID REFERENCES journal_entries(id) ON DELETE SET NULL,
                    -- บิลที่ถูกหักปิด (มีค่าเฉพาะ 'apply' / 'reverse' ของ apply)
                    student_payment_id INTEGER REFERENCES student_payments(id) ON DELETE SET NULL,
                    collection_id INTEGER REFERENCES fee_collections(id) ON DELETE SET NULL,
                    note TEXT,
                    recorded_by TEXT,
                    -- 🔑 คีย์กันส่งซ้ำจากฝั่งผู้ใช้ (client-generated UUID ต่อ "หนึ่งการกดบันทึก")
                    --    ดูเหตุผลว่าทำไมต้องมีที่ index `idx_student_credits_idem` ด้านล่าง
                    idempotency_key VARCHAR(64),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP DEFAULT NULL,
                    CONSTRAINT chk_student_credit_amount_positive CHECK (amount > 0),
                    CONSTRAINT chk_student_credit_balance_not_negative CHECK (balance_after >= 0),
                    CONSTRAINT chk_student_credit_entry_type
                        CHECK (entry_type IN ('topup', 'apply', 'reverse'))
                );

                -- ครอบ "ยอดคงเหลือของนักเรียนคนนี้" — query ที่วิ่งบ่อยที่สุดของตารางนี้
                -- เรียง `id DESC` ให้ตรงกับท่า "เอาแถวล่าสุด" ⇒ ไม่ต้อง sort
                CREATE INDEX IF NOT EXISTS idx_student_credits_student
                    ON student_credits(room_id, student_id, id DESC) WHERE deleted_at IS NULL;

                -- ครอบเส้นทาง "รายการนี้มาจากเหตุการณ์รับเงินไหน" (revert ต้องตามกลับมาเจอ)
                CREATE INDEX IF NOT EXISTS idx_student_credits_tx
                    ON student_credits(finance_transaction_id);

                -- 🔑 กัน "เติมเครดิตซ้ำ" จากกดบันทึกสองครั้ง (double-click / retry หลัง timeout)
                --
                -- 🔴 ทำไม `idx_finance_receipts_deposit_active` กันให้ไม่ได้:
                --    index นั้นคีย์ที่ `legacy_transaction_id` ซึ่ง **ถูกสร้างใหม่ทุกครั้งที่กด**
                --    (การเติมเครดิต 1 ครั้ง = INSERT แถวใหม่ใน `finance_transactions` 1 แถว)
                --    ⇒ กด 2 ครั้ง = 2 transaction = 2 เลข DEP = เครดิตเพิ่ม 2 เท่า = **เงินใน
                --      กระเป๋าเกินจริง 2 เท่า** โดยที่ทุก index/constraint ดูเหมือนครอบอยู่หมด
                --    ต่างจากใบเสร็จที่ anchor ด้วย `student_payment_id` (บิลเป็นตัวระบุเหตุการณ์
                --    ที่ client ส่งมา) — การเติมเครดิต **ไม่มีเหตุการณ์ต้นทางให้ยึด** เพราะเงิน
                --    มาก่อนบิล ⇒ ต้องให้ client เป็นคนระบุ "นี่คือการกดครั้งเดียวกัน" เอง
                --
                -- ⇒ `WHERE idempotency_key IS NOT NULL` กัน NULL หลายแถวในห้องเดียวกัน
                --   (Postgres ถือ NULL แต่ละตัวไม่ซ้ำกัน ⇒ ถ้าไม่กรอง แถวที่ไม่มีคีย์จะไม่ถูกกันเลย
                --    ซึ่งเป็นกับดักตัวเดียวกับที่เขียนเตือนไว้ที่ `idx_finance_receipts_deposit_active`)
                --   ⚠️ ช่องโหว่ที่เหลือ: ถ้า client **ไม่ส่ง** `idempotency_key` มา จะไม่มีอะไรกัน
                --      ⇒ schema บังคับส่ง (required) และ service raise ถ้าว่าง — ดู `CreditsMixin`
                CREATE UNIQUE INDEX IF NOT EXISTS idx_student_credits_idem
                    ON student_credits(room_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL AND deleted_at IS NULL;
            """)

            # --- 6. Activity & Role Management Module ---
            await conn.execute("""
                -- 1. ตารางเก็บหัวข้อกิจกรรม (Activities)
                -- 🌟 metadata (JSONB) เก็บพิกัด, กำหนดการ, ลิ้งก์รูป, อ้างอิงงบประมาณ ฯลฯ เพื่อต่อยอด Dynamic
                CREATE TABLE IF NOT EXISTS activities (
                    id SERIAL PRIMARY KEY,
                    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL, -- ชื่อกิจกรรม
                    description TEXT, -- รายละเอียดทั่วไป
                    activity_date DATE NOT NULL,
                    base_hours NUMERIC(5,2) DEFAULT 0.00,
                    status VARCHAR(50) DEFAULT 'upcoming', -- upcoming, ongoing, completed, cancelled
                    metadata JSONB DEFAULT '{}'::jsonb, -- 🌟 เก็บพิกัด, กำหนดการ, ลิ้งก์รูป, อ้างอิงงบประมาณ
                    created_by VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP WITH TIME ZONE NULL
                );
                CREATE INDEX IF NOT EXISTS idx_activities_room_id ON activities(room_id);
                CREATE INDEX IF NOT EXISTS idx_activities_metadata ON activities USING GIN (metadata);

                -- 2. ตารางเก็บรายชื่อผู้เข้าร่วมและหน้าที่ (Activity Participants)
                -- 🌟 metadata (JSONB) เก็บเบอร์รถบัส, ห้องพัก, เวลาเช็คอิน, ไซส์เสื้อเฉพาะกิจ ฯลฯ
                CREATE TABLE IF NOT EXISTS activity_participants (
                    id SERIAL PRIMARY KEY,
                    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                    role_type VARCHAR(100) DEFAULT 'participant', -- participant, staff, leader
                    role_detail VARCHAR(255), -- "ถือป้าย", "สวัสดิการ"
                    earned_hours NUMERIC(5,2) DEFAULT 0.00,
                    status VARCHAR(50) DEFAULT 'confirmed', -- confirmed, cancelled, attended
                    metadata JSONB DEFAULT '{}'::jsonb, -- 🌟 เก็บเบอร์รถบัส, ห้องพัก, เวลาเช็คอิน, ไซส์เสื้อเฉพาะกิจ
                    recorded_by VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP WITH TIME ZONE NULL,
                    UNIQUE (activity_id, student_id)
                );
                CREATE INDEX IF NOT EXISTS idx_activity_participants_activity_id ON activity_participants(activity_id);
                CREATE INDEX IF NOT EXISTS idx_activity_participants_metadata ON activity_participants USING GIN (metadata);

                -- 7. ระบบเช็คชื่อแยกแผ่น (Multiple Attendance Sheets)
                -- แผ่นเช็คชื่อหนึ่งแผ่นต่อจุดเช็ค เช่น 'เช็คขึ้นรถ' 'เช็คเข้าฐาน' — แยกจากสถานะ participants.status เดิม
                -- (additive: สถานะ overall ของผู้เข้าร่วมยังอยู่ที่ activity_participants.status)
                CREATE TABLE IF NOT EXISTS activity_checkin_sheets (
                    id SERIAL PRIMARY KEY,
                    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                    title VARCHAR(255) NOT NULL,                     -- ชื่อแผ่น เช่น 'เช็คขึ้นรถ'
                    event_date DATE,                                 -- วันที่ทำเหตุการณ์เช็ค (nullable)
                    created_by VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP WITH TIME ZONE NULL
                );
                CREATE INDEX IF NOT EXISTS idx_checkin_sheets_activity_id ON activity_checkin_sheets(activity_id);

                -- บันทึกการเช็คของแต่ละคนในแต่ละแผ่น (1 แถวต่อ (sheet, participant) ที่ยัง active)
                CREATE TABLE IF NOT EXISTS activity_checkin_records (
                    id SERIAL PRIMARY KEY,
                    sheet_id INTEGER NOT NULL REFERENCES activity_checkin_sheets(id) ON DELETE CASCADE,
                    participant_id INTEGER NOT NULL REFERENCES activity_participants(id) ON DELETE CASCADE,
                    is_present BOOLEAN NOT NULL DEFAULT FALSE,
                    checked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,  -- เวลาที่เช็คล่าสุด
                    recorded_by VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP WITH TIME ZONE NULL
                );
                CREATE INDEX IF NOT EXISTS idx_checkin_records_sheet_id ON activity_checkin_records(sheet_id);
                -- กันเช็คซ้ำในแผ่นเดียวกัน (เฉพาะแถวที่ยัง active) — upsert ผ่าน ON CONFLICT ตัวนี้
                -- ห้ามมี full-table UNIQUE (sheet_id, participant_id) — ต้องการเก็บ history ของ soft-deleted rows
                CREATE UNIQUE INDEX IF NOT EXISTS idx_checkin_records_active
                    ON activity_checkin_records(sheet_id, participant_id)
                    WHERE deleted_at IS NULL;
            """)

            # --- 5. Extra Alterations & Smart Constraints ---
            await conn.execute("ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS student_payment_id INTEGER REFERENCES student_payments(id) ON DELETE SET NULL;")

            # 🧾 F3 — คอลัมน์ของ finance_receipts ที่เพิ่มทีหลัง (event_at + สถานะการยกเลิก)
            # ⚠️ **ต้องมี ALTER ตรงนี้ ไม่ใช่พึ่ง `CREATE TABLE IF NOT EXISTS` ด้านบน**:
            #    บน DB ที่ deploy F3 ไปแล้ว ตารางมีอยู่จริง ⇒ CREATE TABLE IF NOT EXISTS เป็น no-op
            #    ⇒ คอลัมน์ใหม่ไม่ถูกเพิ่ม และทุก query ที่ `SELECT R.status` จะพังเป็น 500 ทันที
            #    (กับดักตระกูลเดียวกับ `CREATE UNIQUE INDEX IF NOT EXISTS` ที่แก้ predicate ไม่ได้)
            await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS event_at TIMESTAMP WITH TIME ZONE;")
            await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';")
            await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS voided_at TIMESTAMP WITH TIME ZONE;")
            await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS voided_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
            await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS void_reason TEXT;")
            # 📋 F3.1 — รายการย่อยของใบแจ้งหนี้รวมยอด (ดูเหตุผลว่า "snapshot" ไม่ใช่ recompute
            #    ในคอมเมนต์ของ CREATE TABLE ด้านบน) — ALTER ตัวนี้คือตัวที่ทำให้ DB ที่ deploy
            #    ไปแล้วได้คอลัมน์จริง ส่วน CREATE TABLE ด้านบนเป็น no-op กับ DB นั้น
            await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS line_items JSONB;")
            # (index `idx_finance_receipts_room_student` สร้างในบล็อก DDL ด้านบนแล้ว — บล็อกนั้น
            #  รันทุกครั้งที่ start เช่นกัน และคอลัมน์ที่ index อ้างมีอยู่บน DB เก่าครบ ⇒ ไม่ต้องซ้ำที่นี่)
            # Constraint ที่เพิ่มทีหลังใช้รูปแบบเดียวกับ `users_email_key` ด้านล่าง (DROP IF EXISTS + ADD)
            await conn.execute("ALTER TABLE finance_receipts DROP CONSTRAINT IF EXISTS chk_receipt_status;")
            await conn.execute("ALTER TABLE finance_receipts ADD CONSTRAINT chk_receipt_status CHECK (status IN ('active', 'voided'));")
            # 🔒 "voided ⇒ ต้องมี deleted_at" — แถวที่ฝ่าฝืนไม่ได้มีอยู่จริงบน DB ที่ deploy แล้ว
            #    (คอลัมน์ status เพิ่งถูกเพิ่มด้วย DEFAULT 'active' ทั้งหมด) ⇒ ADD CONSTRAINT
            #    ผ่านเสมอ ไม่มีโอกาส deploy ล้มเพราะข้อมูลเก่า
            await conn.execute("ALTER TABLE finance_receipts DROP CONSTRAINT IF EXISTS chk_receipt_voided_is_deleted;")
            await conn.execute(
                "ALTER TABLE finance_receipts ADD CONSTRAINT chk_receipt_voided_is_deleted"
                " CHECK (status = 'active' OR deleted_at IS NOT NULL);"
            )

            # 💰 F4 — `student_credits` เป็นตารางใหม่ ⇒ `CREATE TABLE IF NOT EXISTS` สร้างให้ครบ
            #    รวม `idempotency_key` อยู่แล้วบน DB ที่ยังไม่เคยมีตารางนี้
            #    ⚠️ ALTER บรรทัดนี้มีไว้เพื่อ DB ที่ **รัน init_db ของ branch นี้ไปแล้วรอบหนึ่ง**
            #       (ก่อนคอลัมน์นี้ถูกเพิ่ม) — ณ จุดนั้นคอลัมน์ยังไม่มี. กฎของ repo คือ
            #       "คอลัมน์ใหม่ทุกตัวต้องมี ALTER คู่เสมอ" เพราะ CREATE TABLE ที่มีอยู่แล้ว = no-op
            await conn.execute("ALTER TABLE student_credits ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);")
            await conn.execute("ALTER TABLE student_credits ADD COLUMN IF NOT EXISTS journal_entry_id UUID REFERENCES journal_entries(id) ON DELETE SET NULL;")

            # 🎂 ห้องแฮปปี้เบิร์ดเดย์ + 🔔 ห้องแจ้งเตือนงานเล็กๆน้อยๆ
            # (เพิ่มคอลัมน์ให้ตาราง rooms ที่สร้างไว้แล้ว — บังคับใช้กับ DB ที่ deploy ไปแล้วด้วย)
            await conn.execute("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS birthday_channel_id BIGINT;")
            await conn.execute("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS minor_notify_channel_id BIGINT;")

            # 🌟 ชื่อภาษาอังกฤษ (identity/dedupe/search) — เพิ่มให้ users ที่ deploy ไปแล้ว
            # (ต้องมีทั้งใน CREATE TABLE ด้านบน และ ALTER ตรงนี้ ตามกฎ skills.md)
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name_en TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name_en TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS nickname_en TEXT;")
            
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

            # 🌟 Consent Model — PII ของสมาชิกต้องผ่าน "การยืนยันตัวตน" (identity_claimed) ก่อนเปิดให้ห้องดู
            # (กันแฮ็กเกอร์สร้างห้องแล้วแอดชื่อคนอื่นเข้าห้องเพื่อเก็บข้อมูลส่วนตัว — ดู docs/skills.md)
            # ต้องมีทั้งใน CREATE TABLE ด้านบน และ ALTER ตรงนี้ ตามกฎ skills.md
            await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS identity_claimed BOOLEAN NOT NULL DEFAULT FALSE;")
            await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS added_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
            await conn.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS claim_meta JSONB DEFAULT '{}'::jsonb;")

            # Backfill: ห้องเดิมที่มีสมาชิก active อยู่แล้วให้ identity_claimed = TRUE (คงพฤติกรรมเดิม)
            # — ปิดช่องโหว่สำหรับการแอดใหม่เป็นต้นไป โดยไม่ล็อกข้อมูลห้องเดิมทั้งระบบ
            await conn.execute("""
                UPDATE students SET identity_claimed = TRUE
                WHERE status = 'active' AND deleted_at IS NULL AND identity_claimed = FALSE;
            """)

            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_student_payments_active
                ON student_payments(collection_id, student_id)
                WHERE deleted_at IS NULL;
            """)

            # 🎯 กันผู้เข้าร่วมซ้ำแบบ soft-delete aware — เดิม UNIQUE(activity_id, student_id) บังคับทั้งตาราง
            # ถ้า soft-delete แล้ว re-add คนเดิมจะชน UNIQUE constraint → ใช้ partial index แทน (เฉพาะแถวที่ยัง active)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_participants_active
                ON activity_participants(activity_id, student_id)
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