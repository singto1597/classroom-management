import asyncpg
import asyncio
import logging
import sys
import os
import json

# 🛠️ ตั้งค่า Path ให้รันเป็น Standalone ได้
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.config import settings
except ImportError:
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
logger = logging.getLogger("PHASE2.5_OPENING_BALANCE")

async def migrate_opening_balances(pool: asyncpg.Pool):
    """
    ฟังก์ชันดึงยอดคงเหลือปัจจุบันจาก finance_accounts 
    มาตั้งเป็น 'ยอดยกมา' ในระบบ Double-Entry (journal_entries/journal_lines)
    """
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                logger.info("🚀 เริ่มกระบวนการตั้งยอดยกมา (Opening Balance) สู่ระบบ Double-Entry...")

                # ดึงรายการห้องทั้งหมดที่มีอยู่ในระบบ
                rooms = await conn.fetch("SELECT id, room_name FROM rooms WHERE deleted_at IS NULL")
                
                for room in rooms:
                    room_id = room['id']
                    
                    # 1. เช็คว่าห้องนี้เคยทำยอดยกมาไปหรือยัง (ป้องกันยอดเบิ้ล!)
                    already_migrated = await conn.fetchval("""
                        SELECT 1 FROM journal_entries 
                        WHERE room_id = $1 AND reference_type = 'opening_balance' AND status != 'voided'
                    """, room_id)
                    
                    if already_migrated:
                        logger.info(f"⏭️ ข้ามห้อง {room['room_name']} (เคยตั้งยอดยกมาไปแล้ว)")
                        continue

                    # 2. ดึงกระเป๋าเงินทั้งหมดของห้องนี้ ที่มียอดคงเหลือ (ไม่เท่ากับ 0)
                    accounts = await conn.fetch("""
                        SELECT id, account_name, balance 
                        FROM finance_accounts 
                        WHERE room_id = $1 AND balance != 0 AND deleted_at IS NULL
                    """, room_id)

                    if not accounts:
                        logger.info(f"⏭️ ข้ามห้อง {room['room_name']} (ไม่มียอดเงินคงเหลือให้ยกมา)")
                        continue

                    logger.info(f"⚙️ กำลังประมวลผลยอดยกมาให้ห้อง: {room['room_name']} (พบ {len(accounts)} กระเป๋า)")

                    # 3. เตรียมบัญชีหมวด "ทุน (Equity)" สำหรับยอดยกมา
                    equity_ledger_id = await conn.fetchval("""
                        SELECT id FROM accounting_ledgers 
                        WHERE room_id = $1 AND account_type = 'equity' AND account_code = '3000'
                    """, room_id)

                    if not equity_ledger_id:
                        # สร้างบัญชีทุนให้ห้องนี้ถ้ายงไม่มี
                        equity_ledger_id = await conn.fetchval("""
                            INSERT INTO accounting_ledgers 
                            (room_id, account_code, account_name, account_type, description)
                            VALUES ($1, '3000', 'ทุน-ยอดยกมา (Opening Balance)', 'equity', 'บัญชีพักสำหรับตั้งยอดยกมาจากระบบ Single-Entry')
                            RETURNING id
                        """, room_id)

                    # 4. สร้างหัวบิล (Journal Entry) สำหรับการตั้งยอดยกมา
                    metadata = {"note": "Migrated from Single-Entry balances"}
                    entry_id = await conn.fetchval("""
                        INSERT INTO journal_entries 
                        (room_id, reference_type, description, recorded_by, metadata)
                        VALUES ($1, 'opening_balance', 'ตั้งยอดยกมา (ระบบบัญชีคู่)', 'SYSTEM', $2::jsonb)
                        RETURNING id
                    """, room_id, json.dumps(metadata))

                    total_debit = 0.0
                    total_credit = 0.0

                    # 5. สร้างรายละเอียดบรรทัด (Journal Lines) ให้กระเป๋าเงินแต่ละใบ
                    for acc in accounts:
                        balance = float(acc['balance'])
                        
                        # หา ledger_id ของกระเป๋าเงินใบนี้
                        asset_ledger_id = await conn.fetchval("""
                            SELECT id FROM accounting_ledgers 
                            WHERE room_id = $1 AND legacy_account_id = $2
                        """, room_id, acc['id'])

                        if not asset_ledger_id:
                            logger.warning(f"⚠️ ไม่พบ Ledger สำหรับบัญชี '{acc['account_name']}' (ID: {acc['id']}) ข้ามการยกยอดของกระเป๋านี้")
                            continue

                        # ถ้าเงินเป็นบวก -> เดบิต สินทรัพย์
                        if balance > 0:
                            await conn.execute("""
                                INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                                VALUES ($1, $2, $3, 0, $4)
                            """, entry_id, asset_ledger_id, balance, f"ยอดยกมาบัญชี: {acc['account_name']}")
                            total_credit += balance # เอาไปสะสมเป็นยอดเครดิตฝั่งทุน
                            
                        # ถ้าเงินติดลบ (เช่น ห้องเป็นหนี้) -> เครดิต สินทรัพย์
                        elif balance < 0:
                            abs_balance = abs(balance)
                            await conn.execute("""
                                INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                                VALUES ($1, $2, 0, $3, $4)
                            """, entry_id, asset_ledger_id, abs_balance, f"ยอดยกมาบัญชี (ติดลบ): {acc['account_name']}")
                            total_debit += abs_balance # เอาไปสะสมเป็นยอดเดบิตฝั่งทุน

                    # 6. บันทึกบรรทัดยอดดุล (Balancing Line) ลงบัญชีทุน (Equity) ให้ Dr = Cr
                    net_equity = total_credit - total_debit
                    if net_equity > 0:
                        # ห้องมีกำไรสะสม -> เครดิต บัญชีทุน
                        await conn.execute("""
                            INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                            VALUES ($1, $2, 0, $3, 'ยอดรวมทุนยกมาสุทธิ (สุทธิบวก)')
                        """, entry_id, equity_ledger_id, net_equity)
                    elif net_equity < 0:
                        # ห้องขาดทุนสะสม -> เดบิต บัญชีทุน
                        await conn.execute("""
                            INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                            VALUES ($1, $2, $3, 0, 'ยอดรวมทุนยกมาสุทธิ (สุทธิติดลบ)')
                        """, entry_id, equity_ledger_id, abs(net_equity))

                    logger.info(f"✅ ตั้งยอดยกมาห้อง {room['room_name']} สำเร็จ (มูลค่าสุทธิ: {net_equity} บาท)")

                logger.info("🎉 สิ้นสุดกระบวนการตั้งยอดยกมาอย่างสมบูรณ์! ตอนนี้ยอดเงินสองระบบตรงกันแล้ว")

    except Exception as e:
        logger.error(f"❌ เกิดข้อผิดพลาดระหว่างตั้งยอดยกมา: {e}")
        raise e

async def main():
    if not hasattr(settings, 'DATABASE_URL') or not settings.DATABASE_URL:
        logger.error("❌ ไม่พบ DATABASE_URL ใน Environment Variables!")
        sys.exit(1)
        
    pool = None
    try:
        pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=5)
        if pool:
            await migrate_opening_balances(pool)
        else:
            logger.error("❌ ไม่สามารถเชื่อมต่อฐานข้อมูลได้")
    finally:
        if pool:
            await pool.close()
            logger.info("🛑 ปิดการเชื่อมต่อ Database")

if __name__ == "__main__":
    asyncio.run(main())