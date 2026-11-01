"""หมวดกิจกรรม + กำหนดปิดรับ + ลิงก์แชร์ (P4.3)

═══════════════════════════════════════════════════════════════════════════════
🏷️ `activities.category`
═══════════════════════════════════════════════════════════════════════════════
slug ของหมวด (camp / competition / volunteer / training / ceremony / other)
— รายการจริงอยู่ใน `services/activity/constants.py` (`ACTIVITY_CATEGORIES`)
**ไม่ใส่ CHECK constraint** ด้วยเหตุผลเดียวกับ P4.2: การเพิ่ม CHECK บนตารางจริง
ต้องสแกนทั้งตารางใต้ ACCESS EXCLUSIVE และ দিনหนึ่งที่ต้องเพิ่มหมวดใหม่จะต้อง
migration ที่ DROP/ADD constraint ใหม่ ⇒ ตรวจที่ service แทน (400 พร้อมรายการที่รับได้)
NULL = ยังไม่จัดหมวด (แถวเดิมทั้งหมด) — หน้าจอต้องแสดง "ไม่ระบุ" ไม่ใช่ค่าว่าง

═══════════════════════════════════════════════════════════════════════════════
📅 `activities.registration_deadline`
═══════════════════════════════════════════════════════════════════════════════
วันที่ปิดรับลงทะเบียน (DATE ตามแบบ `activity_date` ของระบบนี้ — ไม่ใช่ TIMESTAMPTZ
เพื่อไม่ให้เกิดบั๊ก "ปิดรับตอนเที่ยงคืนของวันไหน" ตามโซนเวลา) กติกา
`registration_deadline <= activity_date` ถูกตรวจที่ service

═══════════════════════════════════════════════════════════════════════════════
🔗 `activities.share_token`
═══════════════════════════════════════════════════════════════════════════════
โทเคนสุ่ม (`secrets.token_urlsafe`) สำหรับหน้าอ่านอย่างเดียวที่ **ไม่ต้องล็อกอิน** —
เก็บในตารางแทนการเซ็นแบบ stateless เพราะต้อง "เพิกถอนได้" (ตั้ง NULL = ลิงก์ตายทันที)
โดยไม่ต้องหมุนกุญแจทั้งระบบ · partial unique index รับประกันว่าโทเคนหนึ่งชี้กิจกรรมเดียว
"""

SQL: list[str] = [
    "ALTER TABLE activities ADD COLUMN IF NOT EXISTS category TEXT",
    "ALTER TABLE activities ADD COLUMN IF NOT EXISTS registration_deadline DATE",
    "ALTER TABLE activities ADD COLUMN IF NOT EXISTS share_token TEXT",
    # 🔗 โทเคนต้องไม่ซ้ำข้ามห้อง — หน้าสาธารณะแปลงโทเคนเป็นกิจกรรมโดยไม่รู้ room_id
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_activities_share_token
        ON activities (share_token)
        WHERE share_token IS NOT NULL
    """,
]
