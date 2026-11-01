"""เช็คอินด้วย QR (P4.2) — บันทึกเวลา + ผู้กดเช็คอินรายคน

═══════════════════════════════════════════════════════════════════════════════
🎯 เพิ่มอะไร
═══════════════════════════════════════════════════════════════════════════════
`activity_participants.checked_in_at` / `checked_in_by` — เวลาและผู้ทำรายการตอนที่คนหนึ่ง
ถูกยืนยันว่า "มาแล้ว" ผ่าน QR (หรือปุ่มเช็คอิน) ก่อนหน้านี้มีแต่ `status = 'attended'`
ซึ่งบอกได้แค่ว่า "มา" ไม่ได้บอกว่า "เมื่อไร/ใครกด" ⇒ รายงานย้อนหลังตอบไม่ได้

═══════════════════════════════════════════════════════════════════════════════
⚠️ ทำไม **ไม่** ใส่ CHECK (attended) = (checked_in_at IS NOT NULL)
═══════════════════════════════════════════════════════════════════════════════
มีแถวเดิมจำนวนหนึ่งที่ `status = 'attended'` อยู่ก่อนคอลัมน์นี้จะเกิด (นำเข้าจากแผ่นเช็คชื่อ
หรือแก้สถานะเอง) — เวลาจริงของมันไม่มีใครรู้ `ALTER TABLE … ADD CONSTRAINT` บนตารางจริง
ต้องสแกนทั้งตารางใต้ ACCESS EXCLUSIVE lock และถ้าจะให้ผ่านต้อง **แต่งเวลา** ให้แถวเก่า
ด้วยการเดา ⇒ เลือกไม่ใส่ constraint แล้วประกาศกติกาใน service แทน:

    `checked_in_at` = เวลาที่ "ยืนยันการมา" ผ่านทางที่บันทึกเวลาได้ (QR / ปุ่มเช็คอิน)
    แถวที่ถูกตั้ง `attended` ตั้งแต่ import/สร้างกิจกรรม = NULL โดยเจตนา (ไม่เดาเวลา)

ฝั่ง service แก้สถานะเป็น `attended` ผ่าน PATCH จะเติม `checked_in_at` ให้เอง
(ผู้กดคือคนที่กด — รู้เวลาแน่) ⇒ เหลือ NULL เฉพาะข้อมูลที่มาก่อนยุคนี้เท่านั้น
"""

SQL: list[str] = [
    "ALTER TABLE activity_participants ADD COLUMN IF NOT EXISTS checked_in_at TIMESTAMPTZ",
    "ALTER TABLE activity_participants ADD COLUMN IF NOT EXISTS checked_in_by TEXT",
    # 🎟️ หน้าเช็คอิน/สรุป "มาแล้วกี่คน" อ่านตามกิจกรรม — partial index เก็บเฉพาะแถวที่เช็คอินแล้ว
    """
    CREATE INDEX IF NOT EXISTS idx_activity_participants_checked_in
        ON activity_participants (activity_id, checked_in_at)
        WHERE deleted_at IS NULL AND checked_in_at IS NOT NULL
    """,
]
