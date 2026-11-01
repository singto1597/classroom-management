"""สิทธิ์การดูบันทึกกิจกรรม (`VIEW_AUDIT_LOGS`) + index ที่หน้าดูใช้จริง (P6.2)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมี migration นี้ ไม่ใช่แค่เพิ่มค่าคงที่ในโค้ด
═══════════════════════════════════════════════════════════════════════════════
`students.permissions` เป็น **snapshot** ที่ถูกเขียนลงแถวตอนมอบหมายบทบาท
ไม่ใช่ค่าที่คำนวณสดจาก `class_role` ทุกครั้ง ⇒ การเพิ่มสิทธิ์ใหม่ไว้ใน
`config/roles.json` / `AVAILABLE_PERMISSIONS` **ไม่ทำให้คนที่มีบทบาทอยู่แล้วได้สิทธิ์**
สมาชิกปัจจุบันจะยังได้ 403 จนกว่าจะมีคนไปแก้ทีละคน ⇒ ต้อง backfill ที่นี่

⚠️ รายชื่อบทบาทถูก **ตรึงไว้ ณ วันนี้** โดยเจตนา: ถ้าอนาคตแก้ `roles.json`
แถวที่ backfill ไปแล้วจะไม่เปลี่ยนตาม (นั่นคือความหมายของ snapshot)
การให้สิทธิ์เพิ่มในอนาคตต้องเขียน migration ใหม่ ไม่ใช่แก้ไฟล์นี้ — เพราะ
ไฟล์ที่ apply แล้วถูกตรวจ checksum ไว้ (แก้แล้ว runner จะฟ้อง `MigrationDriftError`)

═══════════════════════════════════════════════════════════════════════════════
🔁 idempotent
═══════════════════════════════════════════════════════════════════════════════
`NOT ... ? 'VIEW_AUDIT_LOGS'` กันการต่อค่าซ้ำ ถ้าไฟล์นี้ถูกรันซ้ำ (เช่น migration
ถูกลบจากตารางแล้วรันใหม่) ผลลัพธ์จะเท่าเดิมไม่ว่าเริ่มจากสถานะไหน

═══════════════════════════════════════════════════════════════════════════════
🧭 index สำหรับหน้าดู
═══════════════════════════════════════════════════════════════════════════════
หน้าดูอ่านแบบ keyset: `WHERE room_id = $1 AND (created_at, id) < (...)
ORDER BY created_at DESC, id DESC` ⇒ ต้องมี index ที่เรียงตาม (room_id, created_at DESC, id DESC)
มิฉะนั้นทุกครั้งที่เลื่อนหน้าจะยิง seq scan ทั้งตาราง audit
"""
from __future__ import annotations

SQL: list[str] = [
    # ── 1. สิทธิ์ใหม่สำหรับสมาชิกที่มีอยู่แล้ว ────────────────────────────
    """
    UPDATE students
       SET permissions = COALESCE(permissions, '[]'::jsonb)
                         || '["VIEW_AUDIT_LOGS"]'::jsonb
     WHERE deleted_at IS NULL
       AND class_role IN ('president', 'vice_president', 'secretary')
       AND NOT COALESCE(permissions, '[]'::jsonb) ? 'VIEW_AUDIT_LOGS'
    """,
    # ── 2. index ของการเลื่อนหน้า (keyset) ───────────────────────────────
    """
    CREATE INDEX IF NOT EXISTS idx_audit_logs_room_created
        ON audit_logs (room_id, created_at DESC, id DESC)
    """,
]
