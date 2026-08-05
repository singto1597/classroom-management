import asyncpg
import asyncio
import logging
import sys
import os

# 🛠️ ตั้งค่า Path ให้รันเป็น Standalone ได้ (ดึง config จาก core.config)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.config import settings
except ImportError:
    # เผื่อกรณีรันจากโฟลเดอร์อื่น
    sys.path.append(os.path.join(os.getcwd(), 'classroom-backend'))
    try:
        from core.config import settings
    except ImportError:
        print("❌ ไม่สามารถโหลด core.config ได้ กรุณาตรวจสอบ Path")
        sys.exit(1)

# 🛠️ ตั้งค่า Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - MIGRATION - %(levelname)s - %(message)s"
)
logger = logging.getLogger("PHASE2_MIGRATION")

async def migrate_ledgers(pool: asyncpg.Pool):
    """
    ฟังก์ชันคัดลอกบัญชีและหมวดหมู่เดิม เข้าสู่ตาราง accounting_ledgers ใหม่
    """
    try:
        async with pool.acquire() as conn:
            # 🛡️ ใช้ Transaction: ถ้ามีพังตรงกลาง จะ Rollback กลับทั้งหมดทันที
            async with conn.transaction():
                logger.info("🚀 เริ่มกระบวนการ Migration ไปยัง Double-Entry Schema...")

                # ==============================================================
                # 1. ย้ายบัญชีการเงิน (finance_accounts) -> หมวดสินทรัพย์ (Asset)
                # ==============================================================
                logger.info("กำลังประมวลผลตาราง finance_accounts...")
                accounts = await conn.fetch("SELECT * FROM finance_accounts ORDER BY id ASC")
                
                account_count = 0
                for acc in accounts:
                    # เช็คว่าเคยก็อปปี้มารึยัง (Idempotency)
                    exists = await conn.fetchval(
                        "SELECT 1 FROM accounting_ledgers WHERE legacy_account_id = $1", 
                        acc['id']
                    )
                    
                    if not exists:
                        # สร้างรหัสบัญชีหมวดสินทรัพย์ (1xxxx)
                        account_code = f"1{acc['id']:04d}" 
                        is_active = acc['deleted_at'] is None
                        
                        await conn.execute("""
                            INSERT INTO accounting_ledgers 
                            (room_id, account_code, account_name, account_type, is_active, legacy_account_id, description)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """, 
                        acc['room_id'], account_code, acc['account_name'], 'asset', is_active, acc['id'], "Migrated from finance_accounts")
                        account_count += 1
                        
                logger.info(f"✅ คัดลอกกระเป๋าเงินสำเร็จ {account_count} รายการ (ข้ามรายการที่เคยทำไปแล้ว {len(accounts) - account_count} รายการ)")

                # ==============================================================
                # 2. ย้ายหมวดหมู่ (finance_categories) -> หมวดรายได้/ค่าใช้จ่าย (Revenue/Expense)
                # ==============================================================
                logger.info("กำลังประมวลผลตาราง finance_categories...")
                categories = await conn.fetch("SELECT * FROM finance_categories ORDER BY id ASC")
                
                category_count = 0
                for cat in categories:
                    exists = await conn.fetchval(
                        "SELECT 1 FROM accounting_ledgers WHERE legacy_category_id = $1", 
                        cat['id']
                    )
                    
                    if not exists:
                        is_active = cat['deleted_at'] is None
                        
                        # แยกประเภทบัญชีตาม Category Type
                        if cat['category_type'] == 'income':
                            account_type = 'revenue'
                            account_code = f"4{cat['id']:04d}" # หมวดรายได้ (4xxxx)
                        else:
                            account_type = 'expense'
                            account_code = f"5{cat['id']:04d}" # หมวดค่าใช้จ่าย (5xxxx)
                            
                        await conn.execute("""
                            INSERT INTO accounting_ledgers 
                            (room_id, account_code, account_name, account_type, is_active, legacy_category_id, description)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """, 
                        cat['room_id'], account_code, cat['category_name'], account_type, is_active, cat['id'], f"Migrated from finance_categories ({cat['category_type']})")
                        category_count += 1

                logger.info(f"✅ คัดลอกหมวดหมู่สำเร็จ {category_count} รายการ (ข้ามรายการที่เคยทำไปแล้ว {len(categories) - category_count} รายการ)")

                logger.info("🎉 สิ้นสุดกระบวนการ Migration Phase 2 อย่างสมบูรณ์!")

    except Exception as e:
        logger.error(f"❌ เกิดข้อผิดพลาดระหว่าง Migration: {e}")
        raise e

async def main():
    if not hasattr(settings, 'DATABASE_URL') or not settings.DATABASE_URL:
        logger.error("❌ ไม่พบ DATABASE_URL ใน Environment Variables!")
        sys.exit(1)
        
    pool = None
    try:
        pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=5)
        if pool:
            await migrate_ledgers(pool)
        else:
            logger.error("❌ ไม่สามารถเชื่อมต่อฐานข้อมูลได้")
    finally:
        if pool:
            await pool.close()
            logger.info("🛑 ปิดการเชื่อมต่อ Database")

if __name__ == "__main__":
    asyncio.run(main())