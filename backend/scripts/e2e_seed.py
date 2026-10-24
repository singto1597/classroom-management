"""สร้างข้อมูลเริ่มต้น + session สำหรับ E2E (รันครั้งเดียวหลัง API ขึ้นแล้ว)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมีสคริปต์นี้
═══════════════════════════════════════════════════════════════════════════════
ระบบนี้ล็อกอินได้ทาง **Discord/Google OAuth เท่านั้น** — ไม่มี username/password
⇒ E2E ที่กดปุ่ม "เข้าสู่ระบบ" จะต้องพึ่ง provider จริง (เปราะ + ต้องมี secret)

ทางที่ตรงไปตรงมาคือ **ข้ามเฉพาะขั้น OAuth**: สร้าง user/room/สมาชิกใน DB ของ E2E
แล้วออก JWT ด้วย `create_access_token` ตัวเดียวกับที่ login ใช้จริง จากนั้นเขียน
ไฟล์ session ให้ Playwright เอาไปใส่ localStorage ก่อนแอปโหลด
⇒ ทุกอย่างหลัง login (router guard, room bootstrap, API call, ฟอร์ม) ยังถูกทดสอบจริง

ข้อมูลที่สร้างเป็น **idempotent** — รันซ้ำได้ (ใช้ room_code/username เป็นกุญแจ)
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import asyncpg

from core.config import settings
from services.auth_service import create_access_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s - E2E_SEED - %(levelname)s - %(message)s")
logger = logging.getLogger("E2E_SEED")

E2E_USERNAME = "e2e-seed"
E2E_EMAIL = "e2e@example.test"
E2E_ROOM_CODE = "E2ETEST"
E2E_ROOM_NAME = "ห้องทดสอบ E2E"
E2E_PREFIX = "นาย"
E2E_FIRST_NAME = "ทดสอบ"
E2E_LAST_NAME = "ระบบ"
E2E_PHONE = "0800000000"


async def _seed(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await conn.fetchval(
                """
                INSERT INTO users
                    (username, email, prefix, first_name, last_name, phone_number)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (username) DO UPDATE
                    SET first_name = EXCLUDED.first_name,
                        last_name  = EXCLUDED.last_name
                RETURNING id
                """,
                E2E_USERNAME, E2E_EMAIL, E2E_PREFIX, E2E_FIRST_NAME, E2E_LAST_NAME, E2E_PHONE,
            )

            room_id = await conn.fetchval(
                "SELECT id FROM rooms WHERE room_code = $1 AND deleted_at IS NULL",
                E2E_ROOM_CODE,
            )
            if room_id is None:
                room_id = await conn.fetchval(
                    "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
                    E2E_ROOM_NAME, E2E_ROOM_CODE, user_id,
                )

            student_id = await conn.fetchval(
                """
                SELECT id FROM students
                WHERE room_id = $1 AND user_id = $2 AND deleted_at IS NULL
                """,
                room_id, user_id,
            )
            if student_id is None:
                # is_admin = TRUE ⇒ ผ่านทุกด่าน RBAC เพื่อให้เทสต์สร้างงานได้
                student_id = await conn.fetchval(
                    """
                    INSERT INTO students
                        (room_id, user_id, student_no, class_role, status,
                         is_admin, permissions, identity_claimed)
                    VALUES ($1, $2, 1, 'president', 'active', TRUE, '[]'::jsonb, TRUE)
                    RETURNING id
                    """,
                    room_id, user_id,
                )

    token = create_access_token({"user_id": str(user_id)})
    logger.info("seed สำเร็จ: user=%s room=%s student=%s", user_id, room_id, student_id)

    return {
        "token": token,
        "user": {
            "id": user_id,
            "prefix": E2E_PREFIX,
            "first_name": E2E_FIRST_NAME,
            "last_name": E2E_LAST_NAME,
            "phone_number": E2E_PHONE,
        },
        "room": {
            "id": room_id,
            "name": E2E_ROOM_NAME,
            "code": E2E_ROOM_CODE,
        },
    }


async def main(output: str) -> None:
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=2)
    try:
        session = await _seed(pool)
    finally:
        await pool.close()

    payload = json.dumps(session, ensure_ascii=False, indent=2)

    # `-` = พิมพ์ JSON ทาง stdout (log ทั้งหมดไป stderr แล้ว) ⇒ CI เก็บด้วย shell redirect
    # ไม่ต้อง bind mount เข้า repo และไม่ติดปัญหา user ในคอนเทนเนอร์เขียนโฟลเดอร์ของ runner ไม่ได้
    if output == "-":
        print(payload)
        return

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    logger.info("เขียน session ไปที่ %s", path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        logger.error("ใช้: python scripts/e2e_seed.py <path ของ session.json | ->")
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
