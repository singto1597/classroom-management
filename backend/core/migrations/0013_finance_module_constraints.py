"""Finance v2 — ดัชนี/unique/partial index ทั้งหมดของโมดูลการเงินรอบใหม่

═══════════════════════════════════════════════════════════════════════════════
🎯 ขอบเขตของไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
1. ดัชนีของตารางใหม่ 15 ตัว (ค้นตามห้อง/นักเรียน/เวลา/รายการ)
2. unique แบบ partial ของ "เหตุการณ์/คีย์กันซ้ำ" ที่คอลัมน์เพิ่งถูกเพิ่มใน 0012:
   - 1 REC + 1 DEP ต่อ payment event  (`payment_event_id IS NOT NULL`)
   - idempotency ของเอกสารที่ไม่ผูก event (INV/ACK/PV/INC)
   - write-off/discount กันกดซ้ำ (P6.2)
   - custody 1 ใบต่อคน/ห้อง และ primary 1 ใบต่อ kind/ห้อง
3. ดัชนีค้นย้อนกลับ `finance_transactions` ตาม event/voucher/batch

📌 ทุกคำสั่งใช้ `IF NOT EXISTS` — รันซ้ำได้ และ **ห้ามแก้ predicate ของ index
   ชื่อเดิมภายหลัง** (Postgres จะไม่เปลี่ยนให้เงียบ ๆ) ถ้าต้องเปลี่ยนให้ใช้ชื่อใหม่
   ใน migration ไฟล์ใหม่เท่านั้น

⚠️ ไฟล์ migration **ห้ามแก้หลัง apply** (checksum ตรึง)
"""

SQL: list[str] = [
    # ═════════════════════════════════════════════════════════════════════
    # ดัชนีของตารางใหม่ (0012)
    # ═════════════════════════════════════════════════════════════════════
    # นักเรียน 1 คน = person 1 คน ต่อห้อง
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_people_student
        ON finance_people(room_id, student_id)
        WHERE student_id IS NOT NULL AND deleted_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_people_room_type
        ON finance_people(room_id, person_type, is_active)
        WHERE deleted_at IS NULL
    """,
    # primary ของห้องมีได้ 1 ตัว (ช่องทางหลัก/QR หลัก) — จำนวน active ≤ 3 บังคับใน service
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_payment_channels_primary
        ON finance_payment_channels(room_id)
        WHERE is_primary AND deleted_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_payment_channels_room
        ON finance_payment_channels(room_id, is_active, sort_order)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_document_signatures_doc
        ON finance_document_signatures(doc_type, doc_id, sort_order)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_document_links_from
        ON finance_document_links(from_doc_type, from_doc_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_document_links_to
        ON finance_document_links(to_doc_type, to_doc_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_payment_events_student
        ON finance_payment_events(room_id, student_id, event_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_payment_events_room_time
        ON finance_payment_events(room_id, status, event_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_payment_events_reference
        ON finance_payment_events(room_id, reference_no)
        WHERE reference_no IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_payment_event_lines_event
        ON finance_payment_event_lines(event_id)
    """,
    # บิล 1 ใบถูกปิดได้ครั้งเดียวต่อ event **ในฐานะบรรทัด `bill`**
    # ⚠️ ต้องมี `line_kind = 'bill'` — บิลเดียวกันต้องมีบรรทัด `credit_apply` ใน
    #    event เดียวกันได้ (จ่ายเงินสด + เครดิตพร้อมกัน)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_payment_event_lines_bill
        ON finance_payment_event_lines(event_id, student_payment_id)
        WHERE line_kind = 'bill' AND student_payment_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_custody_handovers_room
        ON finance_custody_handovers(room_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_expense_lines_voucher
        ON finance_expense_lines(voucher_id, line_no)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_income_lines_batch
        ON finance_income_lines(batch_id, line_no)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_monthly_reports_room
        ON finance_monthly_reports(room_id, year_be DESC, month DESC, version DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_ack_entries_student
        ON finance_ack_entries(room_id, student_id, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_bill_adjustments_payment
        ON finance_bill_adjustments(student_payment_id, status)
    """,

    # ═════════════════════════════════════════════════════════════════════
    # unique/index ที่อ้างคอลัมน์ใหม่บนตารางเดิม
    # ═════════════════════════════════════════════════════════════════════
    # เอกสาร v2: 1 REC และ 1 DEP ต่อ event
    # ⚠️ partial ต้องมี `payment_event_id IS NOT NULL` — ถ้าไม่มี แถว legacy ที่เป็น
    #    NULL ทั้งหมดจะไม่ถูกกัน (Postgres ถือ NULL แต่ละตัวไม่ซ้ำกัน)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_event_active
        ON finance_receipts(payment_event_id, doc_type)
        WHERE payment_event_id IS NOT NULL AND deleted_at IS NULL
    """,
    # idempotency ของเอกสารที่ไม่ได้ผูก event (INV/ACK/PV/INC/...)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_idem
        ON finance_receipts(room_id, doc_type, idempotency_key)
        WHERE idempotency_key IS NOT NULL AND deleted_at IS NULL
    """,
    # write-off/discount: 1 คำขอ = 1 แถว (กันกดซ้ำที่ DB ไม่พึ่ง journal metadata)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_bill_adjustments_idem
        ON finance_bill_adjustments(room_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """,
    # ทะเบียนเอกสาร v2 กรองเร็ว (legacy ยังใช้ index เดิม)
    """
    CREATE INDEX IF NOT EXISTS idx_finance_receipts_layout
        ON finance_receipts(room_id, layout_version, doc_type, issued_at DESC)
        WHERE deleted_at IS NULL
    """,
    # กระเป๋า: custody 1 ใบต่อคน/ห้อง และ primary 1 ใบต่อ kind/ห้อง
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_accounts_custody_owner
        ON finance_accounts(room_id, owner_person_id)
        WHERE is_custody AND owner_person_id IS NOT NULL AND deleted_at IS NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_accounts_primary
        ON finance_accounts(room_id, account_kind)
        WHERE is_primary AND deleted_at IS NULL
    """,
    # เอกสาร/รายการเงิน: ค้นย้อนกลับตามเหตุการณ์ต้นทาง
    """
    CREATE INDEX IF NOT EXISTS idx_finance_receipts_event
        ON finance_receipts(payment_event_id)
        WHERE payment_event_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_transactions_event
        ON finance_transactions(payment_event_id)
        WHERE payment_event_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_transactions_voucher
        ON finance_transactions(expense_voucher_id)
        WHERE expense_voucher_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finance_transactions_income_batch
        ON finance_transactions(income_batch_id)
        WHERE income_batch_id IS NOT NULL
    """,
]
