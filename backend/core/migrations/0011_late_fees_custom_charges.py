"""ค่าปรับอัตโนมัติเมื่อจ่ายล่าช้า (late fee) + เรียกเก็บเงินเองรายบุคคล (Phase 6.5)

═══════════════════════════════════════════════════════════════════════════════
🎯 ขอบเขตของไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
1. `fee_collections` — นโยบายค่าปรับล่าช้าของ **แต่ละโปรเจกต์เก็บเงิน**:
   `late_fee_mode` (`none` | `fixed` | `percent`) · `late_fee_amount`
   (จำนวนเงิน หรือ % ตาม mode) · `late_fee_grace_days` (ผ่อนผันก่อนเริ่มปรับ)
   ⚠️ เก็บเป็นคอลัมน์แทนตารางแยก เพราะนโยบายผูกกับแคมเปญ 1:1 และโปรเจกต์ซ่อน
      ของค่าปรับเองก็ตั้งค่า `none` ไว้ ⇒ ไม่มีค่าปรับซ้อนค่าปรับ

2. `fines.source_payment_id` — บิลต้นทางที่ทำให้เกิดค่าปรับล่าช้า และ
   `fines.auto_late_fee` — ระบุว่ารายการนี้เกิดจากระบบ ไม่ใช่คน
   🔑 unique index `uq_fines_late_fee_source` = **1 ค่าปรับล่าช้าต่อ 1 บิล ตลอดชีพ**
      ⇒ worker รันซ้ำ/รีสตาร์ท/หลายรอบในวันเดียวไม่สร้างซ้ำ (ไม่ต้องมีตาราง log)
      ⚠️ ไม่ใส่เงื่อนไข `status <> 'cancelled'` โดยเจตนา: ถ้าครูยกเลิกค่าปรับล่าช้า
         ไปแล้ว ระบบ **ห้ามออกใหม่เองทุกวัน** — ต้องออกใหม่ผ่านหน้าค่าปรับ (ด้วยมือ)

3. `fee_collections.idempotency_key` — เรียกเก็บเองรายบุคคล: 1 คำขอ = หลายแคมเปญ
   ซ่อน (คนละยอด) ⇒ ใช้คีย์ `"{key}:{student_id}"` ต่อแถว + unique index
   ⇒ double-submit/retry ได้ผลเดิม ไม่สร้างบิลซ้ำ

⚠️ ไฟล์ migration **ห้ามแก้หลัง apply** (checksum ตรึง) — เพิ่มสคีมาอนาคต = ไฟล์ใหม่
"""

SQL: list[str] = [
    # ── 1. นโยบายค่าปรับล่าช้าต่อแคมเปญ ────────────────────────────────────
    """
    ALTER TABLE fee_collections
        ADD COLUMN IF NOT EXISTS late_fee_mode TEXT NOT NULL DEFAULT 'none'
    """,
    """
    ALTER TABLE fee_collections
        ADD COLUMN IF NOT EXISTS late_fee_amount NUMERIC(12,2) NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE fee_collections
        ADD COLUMN IF NOT EXISTS late_fee_grace_days INTEGER NOT NULL DEFAULT 0
    """,
    # 🔑 idempotency ของ "เรียกเก็บเองรายบุคคล" — NULL สำหรับแคมเปญปกติ (index เป็น partial)
    """
    ALTER TABLE fee_collections
        ADD COLUMN IF NOT EXISTS idempotency_key TEXT
    """,
    # index ช่วย worker: หาแคมเปญที่มีนโยบายค่าปรับล่าช้าเท่านั้น
    """
    CREATE INDEX IF NOT EXISTS idx_fee_collections_late_fee
        ON fee_collections (room_id)
        WHERE late_fee_mode <> 'none' AND deleted_at IS NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fee_collections_idempotency
        ON fee_collections (room_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL AND deleted_at IS NULL
    """,
    # ── 2. ลิงก์ค่าปรับล่าช้า → บิลต้นทาง (กันซ้ำถาวร) ──────────────────────
    """
    ALTER TABLE fines
        ADD COLUMN IF NOT EXISTS source_payment_id INTEGER
            REFERENCES student_payments(id) ON DELETE SET NULL
    """,
    """
    ALTER TABLE fines
        ADD COLUMN IF NOT EXISTS auto_late_fee BOOLEAN NOT NULL DEFAULT FALSE
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fines_late_fee_source
        ON fines (source_payment_id)
        WHERE source_payment_id IS NOT NULL AND deleted_at IS NULL
    """,
]
