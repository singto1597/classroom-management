"""📎 ไฟล์หลักฐานการเงิน — รูปภาพ + PDF ผูกกับรายการ/การรับเงิน/event

═══════════════════════════════════════════════════════════════════════════════
🎯 ขอบเขต
═══════════════════════════════════════════════════════════════════════════════
ตารางใหม่ 1 ตัว `finance_attachments` — metadata ของไฟล์ที่เก็บอยู่บน named volume
(`${ENV_NAME}_media_data` → `/data/media`) ตัวไฟล์เองไม่อยู่ในฐานข้อมูล

**ทำไม polymorphic `(owner_type, owner_id)` ไม่ใช่ FK หลายคอลัมน์:**
  - เจ้าของ 3 ชนิด (`finance_transactions`, `student_payments`, `finance_payment_events`)
    เป็น INTEGER ทั้งหมด ⇒ คอลัมน์เดียวรับได้
  - FK ไปเจ้าของทำไม่ได้ (polymorphic) ⇒ **ความปลอดภัยตอนเจ้าของถูกลบ/ซ่อนมาจาก
    policy ที่ตรวจทุกครั้งที่เสิร์ฟ** (`services/finance_attachments.resolve_owner_room`)
    ไม่ใช่ FK
  - `owner_type` ถูกบังคับด้วย CHECK ให้ตรงกับ registry ใน Python (fail-closed)

**ไฟล์สองชนิด:**
  - `image` → `{uuid}.webp` (+ `{uuid}_thumb.webp`) · มี width/height · ไม่มี page_count
  - `pdf`   → `{uuid}.pdf` · ไม่มี thumbnail · มี page_count

⛔ **ไม่แตะ `init_db.py`** — ตารางใหม่ต้องมาจาก migration เท่านั้น (ดู `runner.py` หัวไฟล์)

⚠️ ไฟล์ migration **ห้ามแก้หลัง apply** (checksum ตรึง) — เพิ่มสคีมาอนาคต = ไฟล์ใหม่
"""

SQL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS finance_attachments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        -- เจ้าของแบบ polymorphic — ชนิดที่รู้จักอยู่ใน CHECK (ตรงกับ registry ใน Python)
        owner_type VARCHAR(24) NOT NULL,
        owner_id INTEGER NOT NULL,
        -- image | pdf
        file_kind VARCHAR(8) NOT NULL,
        -- ความหมายของหลักฐาน: รับเงิน / รายจ่าย / เบิกจ่าย / อื่น ๆ
        kind VARCHAR(24) NOT NULL DEFAULT 'other',
        -- ชื่อไฟล์เดิมไว้แสดงผลเท่านั้น — ห้ามใช้เป็น path หรือต่อ URL
        original_name TEXT,
        uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        storage_path TEXT NOT NULL,
        thumb_path TEXT,
        -- sha256 ของไฟล์ **หลังประมวลผลแล้ว** — ใช้ตรวจความถูกต้องตอน restore/verify
        sha256 VARCHAR(64) NOT NULL,
        thumb_sha256 VARCHAR(64),
        mime VARCHAR(40) NOT NULL,
        bytes BIGINT NOT NULL,
        width INTEGER,
        height INTEGER,
        page_count INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMPTZ,
        CONSTRAINT chk_finance_attachments_owner_type
            CHECK (owner_type IN ('transaction', 'student_payment', 'payment_event')),
        CONSTRAINT chk_finance_attachments_file_kind
            CHECK (file_kind IN ('image', 'pdf')),
        CONSTRAINT chk_finance_attachments_kind
            CHECK (kind IN ('payment_proof', 'expense_evidence',
                            'withdrawal_evidence', 'other')),
        CONSTRAINT chk_finance_attachments_bytes CHECK (bytes > 0),
        CONSTRAINT chk_finance_attachments_dims
            CHECK ((width IS NULL OR width > 0) AND (height IS NULL OR height > 0)),
        CONSTRAINT chk_finance_attachments_pages
            CHECK (page_count IS NULL OR page_count > 0),
        -- ชนิดไฟล์ต้องสอดคล้องกับข้อมูลที่เก็บ
        CONSTRAINT chk_finance_attachments_image_meta
            CHECK (file_kind <> 'image'
                   OR (thumb_path IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL)),
        CONSTRAINT chk_finance_attachments_pdf_meta
            CHECK (file_kind <> 'pdf'
                   OR (thumb_path IS NULL AND page_count IS NOT NULL))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_attachments_owner
        ON finance_attachments(owner_type, owner_id, created_at)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_attachments_uploader
        ON finance_attachments(uploaded_by, created_at DESC)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_attachments_storage_path
        ON finance_attachments(storage_path)
    """,
]
