"""📎 ขยาย owner_type ของ `finance_attachments` ให้รองรับ `receipt`

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมี
═══════════════════════════════════════════════════════════════════════════════
ผู้ใช้ต้องการ **แนบไฟล์เพิ่มเติมเข้ากับใบเสร็จ/เอกสารภายหลัง** (ไม่ใช่แค่ตอนสร้าง
รายการ) — เอกสารบางใบ (INV/ACK/CERT) ไม่มี `transaction`/`student_payment`/
`payment_event` ต้นทางตรง ๆ ⇒ ต้องผูกไฟล์กับ `finance_receipts.id` โดยตรง

⇒ เพิ่ม `'receipt'` เข้า CHECK ของ `owner_type` (ตาราง/ไฟล์ยังใช้โครงเดิม)
   policy การเข้าถึง: `resolve_owner_room` อ่าน `finance_receipts.room_id`

⚠️ 0014 ถูก apply ไปแล้ว (checksum ตรึง) ⇒ ห้ามแก้ไฟล์เดิม ต้องขยายด้วยไฟล์นี้
⚠️ `ALTER TABLE ... DROP CONSTRAINT` ไม่ถูกจัดเป็น destructive ของ runner
   (runner ปฏิเสธเฉพาะ DROP TABLE/COLUMN/SCHEMA/DATABASE/TRUNCATE)
"""

SQL: list[str] = [
    "ALTER TABLE finance_attachments "
    "DROP CONSTRAINT IF EXISTS chk_finance_attachments_owner_type",
    """
    ALTER TABLE finance_attachments
        ADD CONSTRAINT chk_finance_attachments_owner_type
        CHECK (owner_type IN ('transaction', 'student_payment', 'payment_event', 'receipt'))
    """,
]
