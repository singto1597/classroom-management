"""Finance v2 — ฐานสคีมาของโมดูลการเงินรอบใหม่ (ตารางใหม่ + คอลัมน์บนตารางเดิม)

═══════════════════════════════════════════════════════════════════════════════
🎯 ขอบเขตของไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
1. ตารางใหม่ 15 ตัว — payment event (1 ครั้งรับเงิน = 1 event หลายบรรทัด),
   ผู้เกี่ยวข้องการเงิน (`finance_people`), ช่องทางชำระ + PromptPay,
   ลายเซ็น/ลิงก์เอกสาร, เงินสดรอส่งมอบ (handover), ใบสำคัญจ่ายหลายบรรทัด,
   รายรับอื่นหลายบรรทัด, รายงานปิดงบ, ACK entries, bill adjustments
2. คอลัมน์ใหม่บนตารางเดิม — `finance_receipts` (layout_version/event/document_meta/
   idempotency/receiver/related), `finance_accounts` (custody/primary/owner),
   `fee_collections.fund_type`, `student_payments.written_off_amount`,
   `finance_transactions` (event/voucher/income + funding_source),
   `student_credits.payment_event_id`

⛔ **ไม่แตะ `init_db.py`** — ตารางที่เพิ่มในบล็อก `CREATE TABLE IF NOT EXISTS`
   ของ `init_db` บน DB ที่มีอยู่แล้วจะไม่ถูกสร้าง (no-op) ⇒ สคีมาใหม่ทั้งหมด
   ต้องมาจาก migration เท่านั้น (ดู `runner.py` หัวไฟล์)

📌 ดัชนี/unique ทั้งหมดอยู่ไฟล์ถัดไป `0013_finance_module_constraints.py`
   เพื่อให้ทุกคอลัมน์มีอยู่ก่อนสร้าง index (กติกาเดียวกับ migration ก่อน ๆ)

⚠️ ไฟล์ migration **ห้ามแก้หลัง apply** (checksum ตรึง) — เพิ่มสคีมาอนาคต = ไฟล์ใหม่
"""

SQL: list[str] = [
    # ═════════════════════════════════════════════════════════════════════
    # 1) ผู้เกี่ยวข้องกับการเงิน (students / teachers / external)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_people (
        id              BIGSERIAL PRIMARY KEY,
        room_id         INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        person_type     TEXT NOT NULL CHECK (person_type IN ('student', 'teacher', 'external')),
        student_id      INTEGER REFERENCES students(id) ON DELETE SET NULL,
        linked_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
        display_name    TEXT NOT NULL,
        phone           TEXT,
        -- บทบาท: receive = ผู้รับเงิน, pay = ผู้จ่าย/ผู้เบิก, approve = ผู้อนุมัติ
        roles           TEXT[] NOT NULL DEFAULT ARRAY['receive']::TEXT[],
        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
        note            TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted_at      TIMESTAMPTZ,
        CONSTRAINT chk_finance_people_roles
            CHECK (roles <@ ARRAY['receive', 'pay', 'approve']::TEXT[]),
        -- student ต้องมี student_id; teacher/external ต้องไม่มี
        CONSTRAINT chk_finance_people_student_link
            CHECK ((person_type = 'student' AND student_id IS NOT NULL)
                OR (person_type <> 'student' AND student_id IS NULL))
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 2) ตั้งค่าการเงินของห้อง (typed settings)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_settings (
        room_id                    INTEGER PRIMARY KEY REFERENCES rooms(id) ON DELETE CASCADE,
        default_receiver_person_id BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        default_wallet_account_id  INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
        require_receiver           BOOLEAN NOT NULL DEFAULT TRUE,
        receipt_note               TEXT,
        updated_at                 TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 3) ช่องทางการชำระเงิน + PromptPay QR
    #    ℹ️ "active ≤ 3" และ "primary QR 1 ตัว" บังคับใน service ภายใต้
    #       `_lock_room_money` (partial unique นับจำนวนไม่ได้ และ repo ไม่ใช้ trigger)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_payment_channels (
        id                    BIGSERIAL PRIMARY KEY,
        room_id               INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        channel_type          TEXT NOT NULL
                              CHECK (channel_type IN ('cash', 'bank_transfer', 'promptpay', 'custom_qr')),
        label                 TEXT NOT NULL,
        -- กระเป๋าปลายทางเมื่อเลือกช่องทางนี้ (NULL = ให้ผู้รับเลือก)
        wallet_account_id     INTEGER REFERENCES finance_accounts(id) ON DELETE SET NULL,
        account_name          TEXT,
        bank_name             TEXT,
        account_number_masked TEXT,
        promptpay_id_masked   TEXT,
        qr_mode               TEXT CHECK (qr_mode IN ('open', 'fixed')),
        is_primary            BOOLEAN NOT NULL DEFAULT FALSE,
        is_active             BOOLEAN NOT NULL DEFAULT TRUE,
        sort_order            INTEGER NOT NULL DEFAULT 0,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted_at            TIMESTAMPTZ,
        CONSTRAINT chk_channel_promptpay_fields
            CHECK (channel_type <> 'promptpay'
                OR (account_name IS NOT NULL AND promptpay_id_masked IS NOT NULL AND qr_mode IS NOT NULL)),
        CONSTRAINT chk_channel_qr_mode
            CHECK (channel_type NOT IN ('promptpay', 'custom_qr') OR qr_mode IS NOT NULL),
        CONSTRAINT chk_channel_bank_fields
            CHECK (channel_type <> 'bank_transfer'
                OR (bank_name IS NOT NULL AND account_name IS NOT NULL))
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 4) ลายเซ็นบนเอกสาร (snapshot ชื่อ ณ เวลาออกเอกสาร)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_document_signatures (
        id          BIGSERIAL PRIMARY KEY,
        room_id     INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        doc_type    TEXT NOT NULL,
        doc_id      BIGINT NOT NULL,
        role        TEXT NOT NULL CHECK (role IN ('prepared', 'approved', 'receiver', 'acknowledged_by')),
        person_id   BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        signer_name TEXT NOT NULL,
        signed_at   TIMESTAMPTZ,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 5) ลิงก์ระหว่างเอกสาร (PV↔CERT, REC↔DEP, ACK↔INV, event→docs)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_document_links (
        id            BIGSERIAL PRIMARY KEY,
        room_id       INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        from_doc_type TEXT NOT NULL,
        from_doc_id   BIGINT NOT NULL,
        to_doc_type   TEXT NOT NULL,
        to_doc_id     BIGINT NOT NULL,
        link_type     TEXT NOT NULL CHECK (link_type IN (
                          'cert_for_voucher', 'receipt_for_deposit', 'invoice_for_ack',
                          'event_document', 'void_replacement')),
        created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_finance_document_links UNIQUE
            (from_doc_type, from_doc_id, to_doc_type, to_doc_id, link_type)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 6) 1 ครั้งรับเงินของนักเรียน 1 คน = 1 payment event
    #    amount_received + credit_used = total_applied + credit_added
    #    ⇒ บังคับที่ DB ด้วย CHECK (ยอดเงินที่ผิดสมดุลห้ามถูกบันทึกเลย)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_payment_events (
        id                   BIGSERIAL PRIMARY KEY,
        room_id              INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        student_id           INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        payer_person_id      BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        payer_name           TEXT NOT NULL,
        receiver_person_id   BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        receiver_name        TEXT NOT NULL,
        wallet_account_id    INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        channel_id           BIGINT REFERENCES finance_payment_channels(id) ON DELETE SET NULL,
        channel_snapshot     JSONB NOT NULL DEFAULT '{}'::jsonb,
        amount_received      NUMERIC(15,2) NOT NULL DEFAULT 0,
        credit_used          NUMERIC(15,2) NOT NULL DEFAULT 0,
        credit_added         NUMERIC(15,2) NOT NULL DEFAULT 0,
        total_applied        NUMERIC(15,2) NOT NULL DEFAULT 0,
        excess_action        TEXT NOT NULL DEFAULT 'none' CHECK (excess_action IN ('credit', 'none')),
        reference_no         TEXT,
        note                 TEXT,
        idempotency_key      TEXT NOT NULL,
        event_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'voided')),
        voided_at            TIMESTAMPTZ,
        voided_by            INTEGER REFERENCES users(id) ON DELETE SET NULL,
        void_reason          TEXT,
        created_by_discord_id TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_event_amounts_nonneg
            CHECK (amount_received >= 0 AND credit_used >= 0 AND credit_added >= 0 AND total_applied >= 0),
        CONSTRAINT chk_event_balanced
            CHECK (amount_received + credit_used = total_applied + credit_added),
        CONSTRAINT chk_event_not_empty
            CHECK (total_applied + credit_added > 0),
        CONSTRAINT chk_event_excess_action
            CHECK ((credit_added = 0 AND excess_action = 'none')
                OR (credit_added > 0 AND excess_action = 'credit')),
        CONSTRAINT uq_finance_payment_events_idem UNIQUE (room_id, idempotency_key)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 7) บรรทัดของ event — bill / credit_apply / credit_topup
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_payment_event_lines (
        id                     BIGSERIAL PRIMARY KEY,
        event_id               BIGINT NOT NULL REFERENCES finance_payment_events(id) ON DELETE CASCADE,
        line_kind              TEXT NOT NULL CHECK (line_kind IN ('bill', 'credit_apply', 'credit_topup')),
        student_payment_id     INTEGER REFERENCES student_payments(id) ON DELETE RESTRICT,
        finance_transaction_id INTEGER REFERENCES finance_transactions(id) ON DELETE RESTRICT,
        credit_entry_id        INTEGER REFERENCES student_credits(id) ON DELETE RESTRICT,
        amount                 NUMERIC(15,2) NOT NULL,
        bill_amount_before     NUMERIC(15,2),
        bill_amount_after      NUMERIC(15,2),
        meta                   JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_event_line_amount_positive CHECK (amount > 0),
        CONSTRAINT chk_event_line_shape CHECK (
            (line_kind = 'bill'
                AND student_payment_id IS NOT NULL
                AND finance_transaction_id IS NOT NULL
                AND credit_entry_id IS NULL)
            OR (line_kind = 'credit_apply'
                AND student_payment_id IS NOT NULL
                AND credit_entry_id IS NOT NULL
                AND finance_transaction_id IS NULL)
            OR (line_kind = 'credit_topup'
                AND student_payment_id IS NULL
                AND credit_entry_id IS NOT NULL
                AND finance_transaction_id IS NOT NULL)
        )
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 8) เงินสดรอส่งมอบ — บันทึกการส่งมอบ (custody = finance_accounts.is_custody)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_custody_handovers (
        id                       BIGSERIAL PRIMARY KEY,
        room_id                  INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        from_account_id          INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        to_account_id            INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        amount                   NUMERIC(15,2) NOT NULL,
        handed_over_by_person_id BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        received_by_person_id    BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        journal_entry_id         UUID REFERENCES journal_entries(id) ON DELETE SET NULL,
        note                     TEXT,
        status                   TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'voided')),
        voided_at                TIMESTAMPTZ,
        void_reason              TEXT,
        created_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_custody_handover_amount_positive CHECK (amount > 0),
        CONSTRAINT chk_custody_handover_distinct CHECK (from_account_id <> to_account_id)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 9) ใบสำคัญจ่ายหลายรายการ (PV ออกเสมอ; CERT พ่วงเมื่อมีบรรทัด receipt_status='none')
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_expense_vouchers (
        id                        BIGSERIAL PRIMARY KEY,
        room_id                   INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        default_wallet_account_id INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        payee_person_id           BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        payee_name                TEXT NOT NULL,
        voucher_date              DATE NOT NULL DEFAULT CURRENT_DATE,
        note                      TEXT,
        total_amount              NUMERIC(15,2) NOT NULL,
        pv_receipt_id             INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL,
        cert_receipt_id           INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL,
        idempotency_key           TEXT NOT NULL,
        status                    TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'voided')),
        voided_at                 TIMESTAMPTZ,
        voided_by                 INTEGER REFERENCES users(id) ON DELETE SET NULL,
        void_reason               TEXT,
        created_at                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_expense_voucher_total_positive CHECK (total_amount > 0),
        CONSTRAINT uq_finance_expense_vouchers_idem UNIQUE (room_id, idempotency_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_expense_lines (
        id                     BIGSERIAL PRIMARY KEY,
        voucher_id             BIGINT NOT NULL REFERENCES finance_expense_vouchers(id) ON DELETE CASCADE,
        line_no                INTEGER NOT NULL,
        description            TEXT NOT NULL,
        amount                 NUMERIC(15,2) NOT NULL,
        category_id            INTEGER REFERENCES finance_categories(id) ON DELETE RESTRICT,
        budget_id              INTEGER REFERENCES finance_budgets(id) ON DELETE SET NULL,
        wallet_account_id      INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        finance_transaction_id INTEGER REFERENCES finance_transactions(id) ON DELETE SET NULL,
        receipt_status         TEXT NOT NULL DEFAULT 'none'
                               CHECK (receipt_status IN ('attached', 'paper', 'none')),
        paper_bill_count       INTEGER NOT NULL DEFAULT 0 CHECK (paper_bill_count >= 0),
        attachment_placeholder TEXT,
        funding_source         TEXT NOT NULL DEFAULT 'room_fund'
                               CHECK (funding_source IN ('room_fund', 'pass_through')),
        meta                   JSONB NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT chk_expense_line_amount_positive CHECK (amount > 0),
        CONSTRAINT uq_finance_expense_lines_no UNIQUE (voucher_id, line_no)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 10) รายรับอื่น ๆ หลายรายการ (INC 1 ใบ)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_income_batches (
        id                    BIGSERIAL PRIMARY KEY,
        room_id               INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        payer_name            TEXT NOT NULL,
        receiver_person_id    BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        receiver_name         TEXT NOT NULL,
        wallet_account_id     INTEGER NOT NULL REFERENCES finance_accounts(id) ON DELETE RESTRICT,
        channel_id            BIGINT REFERENCES finance_payment_channels(id) ON DELETE SET NULL,
        channel_snapshot      JSONB NOT NULL DEFAULT '{}'::jsonb,
        income_date           DATE NOT NULL DEFAULT CURRENT_DATE,
        note                  TEXT,
        total_amount          NUMERIC(15,2) NOT NULL,
        inc_receipt_id        INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL,
        idempotency_key       TEXT NOT NULL,
        status                TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'voided')),
        voided_at             TIMESTAMPTZ,
        void_reason           TEXT,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_income_batch_total_positive CHECK (total_amount > 0),
        CONSTRAINT uq_finance_income_batches_idem UNIQUE (room_id, idempotency_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_income_lines (
        id                     BIGSERIAL PRIMARY KEY,
        batch_id               BIGINT NOT NULL REFERENCES finance_income_batches(id) ON DELETE CASCADE,
        line_no                INTEGER NOT NULL,
        description            TEXT NOT NULL,
        amount                 NUMERIC(15,2) NOT NULL,
        category_id            INTEGER REFERENCES finance_categories(id) ON DELETE RESTRICT,
        finance_transaction_id INTEGER REFERENCES finance_transactions(id) ON DELETE SET NULL,
        meta                   JSONB NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT chk_income_line_amount_positive CHECK (amount > 0),
        CONSTRAINT uq_finance_income_lines_no UNIQUE (batch_id, line_no)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 11) รายงานปิดงบรายเดือน (RPT) — เวอร์ชันได้
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_monthly_reports (
        id             BIGSERIAL PRIMARY KEY,
        room_id        INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        year_be        INTEGER NOT NULL,
        month          INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
        version        INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
        report_no      TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'final', 'voided')),
        snapshot       JSONB NOT NULL,
        total_income   NUMERIC(15,2) NOT NULL,
        total_expense  NUMERIC(15,2) NOT NULL,
        opening_cash   NUMERIC(15,2) NOT NULL,
        closing_cash   NUMERIC(15,2) NOT NULL,
        counted_cash   NUMERIC(15,2),
        variance       NUMERIC(15,2),
        finalized_at   TIMESTAMPTZ,
        finalized_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
        voided_at      TIMESTAMPTZ,
        void_reason    TEXT,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_finance_monthly_reports_version UNIQUE (room_id, year_be, month, version),
        CONSTRAINT uq_finance_monthly_reports_no UNIQUE (room_id, report_no)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 12) ACK — รายชื่อผู้ค้างชำระที่แจ้ง/รับทราบ (1 ใบต่อรอบ)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_ack_entries (
        id                  BIGSERIAL PRIMARY KEY,
        room_id             INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        ack_receipt_id      INTEGER NOT NULL REFERENCES finance_receipts(id) ON DELETE CASCADE,
        student_id          INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
        invoice_receipt_id  INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL,
        outstanding_amount  NUMERIC(15,2) NOT NULL,
        acknowledged_at     TIMESTAMPTZ,
        note                TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_ack_entry_amount_positive CHECK (outstanding_amount > 0),
        CONSTRAINT uq_finance_ack_entries_student UNIQUE (ack_receipt_id, student_id)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # 13) การปรับยอดบิล — เศษสตางค์/ส่วนลด/หนี้สูญ
    #     idempotency_key unique ต่อห้องอยู่ใน 0013 (partial index)
    # ═════════════════════════════════════════════════════════════════════
    """
    CREATE TABLE IF NOT EXISTS finance_bill_adjustments (
        id                 BIGSERIAL PRIMARY KEY,
        room_id            INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        student_payment_id INTEGER NOT NULL REFERENCES student_payments(id) ON DELETE RESTRICT,
        adjustment_type    TEXT NOT NULL CHECK (adjustment_type IN ('write_off', 'discount')),
        amount             NUMERIC(15,2) NOT NULL,
        reason             TEXT NOT NULL,
        journal_entry_id   UUID REFERENCES journal_entries(id) ON DELETE SET NULL,
        idempotency_key    TEXT,
        status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'voided')),
        voided_at          TIMESTAMPTZ,
        void_reason        TEXT,
        created_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_bill_adjustment_amount_positive CHECK (amount > 0)
    )
    """,

    # ═════════════════════════════════════════════════════════════════════
    # คอลัมน์บนตารางเดิม (ADD COLUMN IF NOT EXISTS เท่านั้น)
    # ═════════════════════════════════════════════════════════════════════
    # เอกสาร: v2 dispatch + event + snapshot + idempotency + ผู้รับ
    # ℹ️ ACK เก็บในตารางนี้ ⇒ ต้องส่ง `paid_total_after` (NOT NULL) = 0 และ
    #    `amount` = ยอดค้างรวม (>0 ตาม chk_receipt_amount_positive)
    """
    ALTER TABLE finance_receipts
        ADD COLUMN IF NOT EXISTS layout_version SMALLINT NOT NULL DEFAULT 1,
        ADD COLUMN IF NOT EXISTS payment_event_id BIGINT REFERENCES finance_payment_events(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS document_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
        ADD COLUMN IF NOT EXISTS receiver_person_id BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS related_receipt_id INTEGER REFERENCES finance_receipts(id) ON DELETE SET NULL
    """,
    # กระเป๋า: custody + primary + เจ้าของ
    """
    ALTER TABLE finance_accounts
        ADD COLUMN IF NOT EXISTS owner_person_id BIGINT REFERENCES finance_people(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS is_custody BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE
    """,
    # โครงการ: มิติเงินห้อง vs เงินผ่านมือ (รายงานเท่านั้น — ไม่เพิ่ม liability ledger)
    """
    ALTER TABLE fee_collections
        ADD COLUMN IF NOT EXISTS fund_type TEXT NOT NULL DEFAULT 'room_fund'
            CHECK (fund_type IN ('room_fund', 'pass_through'))
    """,
    # บิล: ยอดที่ตัดจำหน่าย — สูตรค้าง = amount - paid_amount - written_off_amount
    """
    ALTER TABLE student_payments
        ADD COLUMN IF NOT EXISTS written_off_amount NUMERIC(15,2) NOT NULL DEFAULT 0
            CHECK (written_off_amount >= 0)
    """,
    # รายการเงิน: ผูก event / batch / voucher + แหล่งเงิน
    """
    ALTER TABLE finance_transactions
        ADD COLUMN IF NOT EXISTS payment_event_id BIGINT REFERENCES finance_payment_events(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS expense_voucher_id BIGINT REFERENCES finance_expense_vouchers(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS income_batch_id BIGINT REFERENCES finance_income_batches(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS funding_source TEXT
            CHECK (funding_source IS NULL OR funding_source IN ('room_fund', 'pass_through'))
    """,
    # เครดิต: ผูก event (topup/apply ที่เกิดใน event)
    """
    ALTER TABLE student_credits
        ADD COLUMN IF NOT EXISTS payment_event_id BIGINT REFERENCES finance_payment_events(id) ON DELETE SET NULL
    """,
]
