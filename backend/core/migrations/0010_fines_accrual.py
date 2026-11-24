"""ระบบค่าปรับ + เกณฑ์คงค้าง (accrual AR) — สคีมาพื้นฐาน

═══════════════════════════════════════════════════════════════════════════════
🎯 ขอบเขตของไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
1. `fee_collections.collection_kind` — แยก "โปรเจกต์เก็บเงินจริง" ออกจาก
   "โปรเจกต์ซ่อนของค่าปรับ" (ค่าปรับ 1 ครั้ง = 1 บิล + 1 โปรเจกต์ซ่อน ไม่ให้รั่ว
   ไปหน้าแคมเปญหรือใบแจ้งหนี้แบบรวมยอด)
2. ตารางโดเมนค่าปรับ: `fine_types`, `fine_batches`, `fines`, `fine_waivers`,
   `fine_refunds`
3. `reminder_dispatch_log` — กัน worker เตือนซ้ำในวันเดียว
4. unique index ที่ทำให้ accrual/ใบแจ้งหนี้/คำขอ pending "มีได้อย่างละใบ"
5. seed ประเภทความผิด 5 รายการให้ห้องที่มีอยู่แล้ว (ห้องใหม่ seed ตอน create_room)

⚠️ ไฟล์ migration **ห้ามแก้หลัง apply** (checksum ตรึง) — การเปลี่ยนสคีมาเพิ่มเติม
   ต้องเขียนไฟล์ใหม่ต่อท้าย

═══════════════════════════════════════════════════════════════════════════════
🔒 Preflight สองด่าน — ล้มดัง ๆ ก่อนสร้าง index
═══════════════════════════════════════════════════════════════════════════════
(n) ใบแจ้งหนี้รายบิลซ้ำ: ถ้ามีอยู่ `CREATE UNIQUE INDEX` จะล้มด้วยข้อความของ Postgres
    ที่อ่านไม่รู้เรื่อง ⇒ DO block ด้านล่างตรวจก่อนแล้ว raise ข้อความภาษาไทย
(o) รหัสบัญชี 5 หลัก (`11001` ฯลฯ) อาจชนกับรหัสที่ระบบสร้างอัตโนมัติ:
      สินทรัพย์ = '1' || LPAD(finance_accounts.id, 4, '0')
      รายได้/ค่าใช้จ่าย = '4'/'5' || LPAD(finance_categories.id, 4, '0')
    ถ้าเจอแถวที่ใช้รหัสชุดนี้อยู่แล้ว **ห้าม rename อัตโนมัติ** — ให้เจ้าของเลือก
    ชุดรหัสใหม่ (เช่น 11011/11012/31012/49011/49012/49013/59011) แล้ว deploy ใหม่
"""

SQL: list[str] = [
    # ── 1. แยกชนิดของ fee_collections ─────────────────────────────────────
    """
    ALTER TABLE fee_collections
        ADD COLUMN IF NOT EXISTS collection_kind TEXT NOT NULL DEFAULT 'project'
    """,
    # ── 2. ประเภทความผิด (ตั้งได้ต่อห้อง) ─────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS fine_types (
        id               SERIAL PRIMARY KEY,
        room_id          INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        name             TEXT NOT NULL,
        default_amount   NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (default_amount >= 0),
        default_due_days INTEGER NOT NULL DEFAULT 7 CHECK (default_due_days BETWEEN 0 AND 365),
        description      TEXT,
        is_active        BOOLEAN NOT NULL DEFAULT TRUE,
        sort_order       INTEGER NOT NULL DEFAULT 0,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at       TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fine_types_room_active
        ON fine_types (room_id, is_active, sort_order)
        WHERE deleted_at IS NULL
    """,
    # ── 3. รอบการออกค่าปรับ (หลายคน ความผิดเดียวกัน) ─────────────────────
    """
    CREATE TABLE IF NOT EXISTS fine_batches (
        id                 SERIAL PRIMARY KEY,
        room_id            INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        fine_type_id       INTEGER REFERENCES fine_types(id) ON DELETE SET NULL,
        fine_type_name     TEXT NOT NULL,
        incident_date      DATE NOT NULL,
        due_date           DATE NOT NULL,
        reason             TEXT NOT NULL,
        amount_per_student NUMERIC(12,2) NOT NULL,
        student_count      INTEGER NOT NULL,
        total_amount       NUMERIC(12,2) NOT NULL,
        idempotency_key    TEXT,
        created_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at         TIMESTAMPTZ
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fine_batches_idempotency
        ON fine_batches (room_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL AND deleted_at IS NULL
    """,
    # ── 4. ค่าปรับรายคน (1 ค่าปรับ = 1 บิล + 1 ใบ INV-) ──────────────────
    """
    CREATE TABLE IF NOT EXISTS fines (
        id                  SERIAL PRIMARY KEY,
        room_id             INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        batch_id            INTEGER REFERENCES fine_batches(id) ON DELETE SET NULL,
        fine_type_id        INTEGER REFERENCES fine_types(id) ON DELETE SET NULL,
        fine_type_name      TEXT NOT NULL,
        student_id          INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        hidden_collection_id INTEGER REFERENCES fee_collections(id) ON DELETE SET NULL,
        student_payment_id  INTEGER NOT NULL REFERENCES student_payments(id) ON DELETE RESTRICT,
        invoice_receipt_id  INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL,
        incident_date       DATE NOT NULL,
        due_date            DATE NOT NULL,
        reason              TEXT NOT NULL,
        original_amount     NUMERIC(12,2) NOT NULL CHECK (original_amount >= 0),
        amount              NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
        waived_amount       NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (waived_amount >= 0),
        refunded_amount     NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0),
        status              TEXT NOT NULL DEFAULT 'issued'
                            CHECK (status IN ('issued', 'partially_paid', 'paid',
                                              'waived', 'cancelled', 'refunded')),
        evidence_url        TEXT,
        note                TEXT,
        created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fines_student_payment
        ON fines (student_payment_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fines_room_status_due
        ON fines (room_id, status, due_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fines_room_student
        ON fines (room_id, student_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fines_batch
        ON fines (batch_id)
    """,
    # ── 5. คำขอยกเว้น/ลด (ต้องอนุมัติ + ห้ามอนุมัติตัวเอง) ────────────────
    """
    CREATE TABLE IF NOT EXISTS fine_waivers (
        id              SERIAL PRIMARY KEY,
        room_id         INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        fine_id         INTEGER NOT NULL REFERENCES fines(id) ON DELETE CASCADE,
        amount          NUMERIC(12,2) NOT NULL CHECK (amount > 0),
        reason_category TEXT NOT NULL
                        CHECK (reason_category IN ('discount', 'uncollectible')),
        reason          TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
        requested_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
        requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        decided_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
        decided_at      TIMESTAMPTZ,
        decision_note   TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at      TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fine_waivers_room_status
        ON fine_waivers (room_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fine_waivers_fine
        ON fine_waivers (fine_id)
    """,
    # 🔒 คำขอ pending ได้ค่าปรับละใบ — กัน double-submit จากคำขอซ้ำ
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fine_waivers_pending
        ON fine_waivers (fine_id)
        WHERE status = 'pending' AND deleted_at IS NULL
    """,
    # ── 6. คำขอคืนเงิน ───────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS fine_refunds (
        id              SERIAL PRIMARY KEY,
        room_id         INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        fine_id         INTEGER NOT NULL REFERENCES fines(id) ON DELETE CASCADE,
        account_id      INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        amount          NUMERIC(12,2) NOT NULL CHECK (amount > 0),
        reason          TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
        requested_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
        requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        decided_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
        decided_at      TIMESTAMPTZ,
        decision_note   TEXT,
        transaction_id  INTEGER REFERENCES finance_transactions(id) ON DELETE SET NULL,
        document_id     INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at      TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fine_refunds_room_status
        ON fine_refunds (room_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fine_refunds_fine
        ON fine_refunds (fine_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_fine_refunds_pending
        ON fine_refunds (fine_id)
        WHERE status = 'pending' AND deleted_at IS NULL
    """,
    # ── 7. Log ของ worker เตือนรายวัน (dedupe) ───────────────────────────
    """
    CREATE TABLE IF NOT EXISTS reminder_dispatch_log (
        id           SERIAL PRIMARY KEY,
        room_id      INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        dispatch_key TEXT NOT NULL,
        channel      TEXT NOT NULL,
        payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
        sent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_reminder_dispatch
        ON reminder_dispatch_log (room_id, dispatch_key, channel)
    """,
    # ── 8. Preflight: ใบแจ้งหนี้รายบิลซ้ำ ────────────────────────────────
    """
    DO $$
    DECLARE
        bad TEXT;
    BEGIN
        SELECT string_agg(student_payment_id::text || ' x' || cnt, ', ')
          INTO bad
          FROM (
              SELECT student_payment_id, COUNT(*) AS cnt
                FROM finance_receipts
               WHERE doc_type = 'invoice'
                 AND student_payment_id IS NOT NULL
                 AND deleted_at IS NULL
               GROUP BY student_payment_id
              HAVING COUNT(*) > 1
          ) dup;

        IF bad IS NOT NULL THEN
            RAISE EXCEPTION 'พบใบแจ้งหนี้รายบิลซ้ำ (%) — ต้อง void ใบเก่าให้เหลือใบเดียวต่อบิลก่อน deploy', bad;
        END IF;
    END $$
    """,
    # ── 9. Preflight: รหัสบัญชีค่าปรับชนกับ ledger เดิม ──────────────────
    """
    DO $$
    DECLARE
        bad TEXT;
    BEGIN
        SELECT string_agg(DISTINCT room_id::text || ':' || account_code, ', ')
          INTO bad
          FROM accounting_ledgers
         WHERE account_code IN ('11001', '11002', '31002', '49001', '49002', '49003', '59001');

        IF bad IS NOT NULL THEN
            RAISE EXCEPTION
                'พบรหัสบัญชีค่าปรับชนกับ ledger เดิม (%) — ต้องเลือกชุดรหัสใหม่ก่อน deploy (ห้าม renumber อัตโนมัติ)', bad;
        END IF;
    END $$
    """,
    # ── 10. Index กันซ้ำของใบแจ้งหนี้/accrual ─────────────────────────────
    # 1 ใบ INV- ต่อบิลค่าปรับ — ใบแจ้งหนี้แบบรวมยอดมี student_payment_id = NULL จึงไม่ชน
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_fine_invoice_active
        ON finance_receipts (student_payment_id)
        WHERE doc_type = 'invoice' AND student_payment_id IS NOT NULL AND deleted_at IS NULL
    """,
    # 1 บิลมี accrual ได้ครั้งเดียว — ไม่ว่าจะมาจากการออกบิล (issue) หรือยอดยกมา (opening)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_bill_issue
        ON journal_entries (reference_type, reference_id)
        WHERE reference_type IN ('student_payment_issue', 'opening_receivable')
          AND deleted_at IS NULL
    """,
    # ── 11. Seed ประเภทความผิด 5 รายการ (เฉพาะห้องที่ยังไม่มีเลย) ─────────
    """
    INSERT INTO fine_types (room_id, name, default_amount, default_due_days, description, sort_order)
    SELECT r.id, v.name, v.amount, 7, v.description, v.sort_order
      FROM rooms r
     CROSS JOIN (VALUES
         ('มาสาย / ไม่ทำเวร',            20::numeric, 'มาสายหรือไม่ทำเวรตามที่ได้รับมอบหมาย', 10),
         ('ขาดเวรทำความสะอาด',           20::numeric, 'ไม่มาทำความสะอาดตามเวรที่จัดไว้', 20),
         ('ไม่ส่งงาน',                   20::numeric, 'ไม่ส่งงานหรือการบ้านตามกำหนด', 30),
         ('ใช้โทรศัพท์ในเวลาเรียน',      20::numeric, 'ใช้โทรศัพท์ระหว่างเรียนโดยไม่ได้รับอนุญาต', 40),
         ('อื่น ๆ (กรอกยอดเอง)',          0::numeric, 'ใช้เมื่อไม่ตรงกับประเภทที่มี — ต้องกรอกจำนวนเงินเอง', 50)
     ) AS v(name, amount, description, sort_order)
     WHERE r.deleted_at IS NULL
       AND NOT EXISTS (SELECT 1 FROM fine_types ft WHERE ft.room_id = r.id)
    """,
]
