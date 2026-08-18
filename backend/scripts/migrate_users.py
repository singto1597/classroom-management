import asyncio
import asyncpg
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import settings
from core.name_utils import normalize_nfc

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("MIGRATION")

async def migrate_data():
    logger.info("🚀 Starting Data Migration: Students -> Users")

    # ดึงฟิลด์ทั้งหมดที่ต้องการย้ายไป users (รวมชื่ออังกฤษ — identity หลักในระบบใหม่)
    global_fields = [
        "discord_id", "prefix", "first_name", "last_name", "first_name_en", "last_name_en", "nickname", "birthday",
        "blood_group", "shirt_size", "food_allergy", "congenital_disease",
        "phone_number", "email", "line_id", "ig_username",
        "phone_number_parent", "phone_number_parent_relation",
        "address_house_no", "address_road", "address_sub_district",
        "address_district", "address_province", "address_post_code"
    ]
    # ฟิลด์ชื่อไทยที่ต้อง NFC-normalize ก่อนเขียน (แก้ อำ/อํา ฯลฯ)
    name_nfc_fields = {"prefix", "first_name", "last_name", "nickname"}
    
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL)
        
        # 🛡️ เปิด Transaction ควบคุมความปลอดภัย (พัง = ยกเลิกทั้งหมด)
        async with conn.transaction():
            
            # 1. ดึงข้อมูลนักเรียนทั้งหมดที่ยังมีชีวิตอยู่ (ยังไม่ถูกลบ)
            students = await conn.fetch("SELECT * FROM students WHERE deleted_at IS NULL AND user_id IS NULL")
            logger.info(f"🔍 Found {len(students)} students to migrate.")
            
            success_count = 0
            
            for student in students:
                # 2. เช็คว่ามี User นี้อยู่ในระบบหรือยัง (discord_id → ชื่ออังกฤษ → ชื่อไทย NFC)
                existing_user = None

                if student['discord_id']:
                    existing_user = await conn.fetchrow("SELECT id FROM users WHERE discord_id = $1", student['discord_id'])

                if not existing_user:
                    if student.get('first_name_en') or student.get('last_name_en'):
                        existing_user = await conn.fetchrow(
                            "SELECT id FROM users WHERE first_name_en = $1 AND last_name_en = $2",
                            normalize_nfc(student.get('first_name_en')), normalize_nfc(student.get('last_name_en')),
                        )
                    if not existing_user:
                        existing_user = await conn.fetchrow(
                            "SELECT id FROM users WHERE first_name = $1 AND last_name = $2",
                            normalize_nfc(student['first_name']), normalize_nfc(student['last_name']),
                        )

                if existing_user:
                    # ถ้ามี User อยู่แล้ว เอา ID มาใช้เลย (เช่น เผื่อเด็กคนนี้อยู่หลายห้อง)
                    user_id = existing_user['id']
                    logger.info(f"🔗 Linking existing user_id {user_id} for {student['first_name']} {student['last_name']}")
                else:
                    # 3. ถ้ายังไม่มี ให้ Insert สร้าง User ใหม่ (NFC-normalize ชื่อไทย)
                    insert_query = f"""
                        INSERT INTO users ({', '.join(global_fields)})
                        VALUES ({', '.join([f'${i+1}' for i in range(len(global_fields))])})
                        RETURNING id
                    """
                    values = [
                        normalize_nfc(student.get(field)) if field in name_nfc_fields else student.get(field)
                        for field in global_fields
                    ]
                    user_id = await conn.fetchval(insert_query, *values)
                    logger.info(f"✨ Created new user_id {user_id} for {student['first_name']} {student['last_name']}")
                
                # 4. อัปเดต user_id กลับไปที่ตาราง students
                await conn.execute("UPDATE students SET user_id = $1 WHERE id = $2", user_id, student['id'])
                success_count += 1
                
            logger.info(f"✅ Migration Completed! Successfully migrated {success_count} records.")
            
            # 🚨 เอาคอมเมนต์บรรทัดล่างออก ถ้าต้องการทดสอบรันดูเฉยๆ (Dry Run) โดยไม่บันทึกจริง
            # raise Exception("🛑 DRY RUN TRIGGERED: Rollback everything!")

    except Exception as e:
        logger.error(f"❌ Migration Failed: {e}. All changes have been rolled back.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate_data())