"""0005 — ความจุกิจกรรม + คิวสำรอง (P4.1)

บริบท:
- กิจกรรมเดิม "รับได้ไม่จำกัด" — ผู้ดูแลเพิ่มรายชื่อได้เรื่อย ๆ จนเกินที่สถานที่รับได้จริง
  (รถบัส/ห้องประชุม/จำนวนที่นั่ง) แล้วต้องมาไล่ตัดรายชื่อเองทีหลัง
- รอบนี้เพิ่มเพดานที่กิจกรรม (ไม่ใช่ที่ห้อง) + คิวสำรองเมื่อเพิ่มเกินเพดาน

═══════════════════════════════════════════════════════════════════════════════
🔑 สิ่งที่ "ไม่" ทำใน migration นี้ — และเหตุผล
═══════════════════════════════════════════════════════════════════════════════
1. **ไม่เพิ่ม CHECK บนความจุ** — `capacity` ของแถวเดิมเป็น NULL ทั้งหมดอยู่แล้ว
   ⇒ constraint จะผ่านก็จริง แต่การ ADD CONSTRAINT ต้องล็อกตารางแบบ ACCESS EXCLUSIVE
   และการถอด/แก้ constraint ทีหลังต้องเขียน migration ใหม่ ⇒ ตรวจช่วงค่าใน Pydantic + service แทน
2. **ไม่แตะ `UNIQUE (activity_id, student_id)` เดิม** — เป็น full unique ที่มีอยู่ก่อน
   ⇒ แถวที่ soft-delete ยังกิน key (ต้อง revive ไม่ใช่ INSERT ซ้ำ — มีโค้ดรองรับแล้ว)
   และ **ห้ามเพิ่ม partial unique ซ้ำ** เพราะ full unique เข้มกว่าอยู่แล้ว
3. **ไม่แก้ความหมายของ `status` เดิม** — เพิ่มค่า `waitlisted` เข้าไปเป็นค่าใหม่
   ไม่ได้แปลง `attended`/`confirmed` ของข้อมูลเก่า (การย้ายความหมายต้องมี dump + แผนย้อนกลับ)

คิวสำรองใช้ `queue_position` (เริ่มที่ 1) เรียงจากน้อยไปมาก — เลื่อนคิวเมื่อมีการยกเลิก/นำออก
"""

SQL: list[str] = [
    # ── 1. เพดานผู้เข้าร่วมของกิจกรรม (NULL = ไม่จำกัด — ค่าเริ่มต้นของทุกแถวเดิม) ──
    "ALTER TABLE activities ADD COLUMN IF NOT EXISTS capacity INTEGER",

    # ── 2. ตำแหน่งในคิวสำรอง (NULL = ไม่ได้อยู่ในคิว) ─────────────────────────
    "ALTER TABLE activity_participants ADD COLUMN IF NOT EXISTS queue_position INTEGER",

    # ── 3. index สำหรับนับ/เลื่อนคิว — partial เพราะอ่านเฉพาะแถวที่ยัง active ──
    """
    CREATE INDEX IF NOT EXISTS idx_activity_participants_queue
        ON activity_participants (activity_id, status, queue_position)
        WHERE deleted_at IS NULL
    """,
]
