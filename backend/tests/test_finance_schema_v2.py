"""🏗️ [FIN-V2 / P1.1] สคีมา Finance v2 จาก migration 0012 + 0013

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ตาราง/คอลัมน์ใหม่ครบจริง** — ทุก package ถัดไป (P1.2–P6.5) อ้างตารางเหล่านี้
   ⇒ ถ้า 0012 ลืมตารางเดียว โค้ดที่ merge ทีหลังจะพังตอนบูต ไม่ใช่ตอนเทสต์
2. **unique/index ที่เป็นด่านกันเงินซ้ำ** — 1 REC + 1 DEP ต่อ event,
   idempotency ของเอกสาร/การตัดหนี้, custody 1 ใบต่อคน, primary 1 ใบต่อ kind
3. **predicate ของ `idx_finance_payment_event_lines_bill` ต้องมี `line_kind='bill'`**
   — ถ้ากรองแค่ `student_payment_id` การจ่าย "เงินสด + เครดิต" พร้อมกันในครั้งเดียว
   จะชน unique ทั้งที่ถูกต้อง (บิล 1 ใบมีได้ทั้งบรรทัด bill และ credit_apply)
4. **migration รันซ้ำได้** — `apply_migrations` คืน 0 และไม่เพิ่มแถวใน `schema_migrations`
5. **ค่าคงที่ใหม่** — `RECEIPT_NO_PATTERN` รับ `CERT` (4 ตัว), ACK/CERT มีคำนำหน้า,
   ledger `59002` สร้างได้ผ่าน `_resolve_system_ledger` (ชื่อ/ประเภท/ไม่ผูก legacy)
6. **`init_db.py` ยังไม่มี DDL ของ v2** — สคีมาใหม่ต้องมาจาก migration เท่านั้น
   (กันคนเผลอแก้ init_db ซึ่งเป็น no-op บน DB เดิมแต่ทำให้เทสต์ DB ใหม่เขียวหลอก)

⚠️ ทุกอย่างยืนยันกับ Postgres จริงผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
from pathlib import Path

import asyncpg
import pytest

from services.finance.constants import (
    DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_CERTIFICATE,
    DOC_TYPE_LABELS,
    DOC_TYPE_MONTHLY_REPORT,
    DOC_TYPE_PREFIXES,
    PROJECT_BAD_DEBT_CODE,
    PROJECT_BAD_DEBT_NAME,
    RECEIPT_NO_PATTERN,
    SYSTEM_LEDGER_SPECS,
)
from services.finance_service import FinanceService
from core.migrations.runner import apply_migrations

pytestmark = pytest.mark.asyncio

# ตารางใหม่ทั้งหมดของ 0012 — เพิ่ม/ลบต้องแก้ทั้ง migration และที่นี่พร้อมกัน
NEW_TABLES = (
    "finance_people",
    "finance_settings",
    "finance_payment_channels",
    "finance_document_signatures",
    "finance_document_links",
    "finance_payment_events",
    "finance_payment_event_lines",
    "finance_custody_handovers",
    "finance_expense_vouchers",
    "finance_expense_lines",
    "finance_income_batches",
    "finance_income_lines",
    "finance_monthly_reports",
    "finance_ack_entries",
    "finance_bill_adjustments",
)

# คอลัมน์ใหม่บนตารางเดิม: (table, [(column, expected_default_or_None), ...])
NEW_COLUMNS = {
    "finance_receipts": [
        "layout_version", "payment_event_id", "document_meta",
        "idempotency_key", "receiver_person_id", "related_receipt_id",
    ],
    "finance_accounts": ["owner_person_id", "is_custody", "is_primary"],
    "fee_collections": ["fund_type"],
    "student_payments": ["written_off_amount"],
    "finance_transactions": [
        "payment_event_id", "expense_voucher_id", "income_batch_id", "funding_source",
    ],
    "student_credits": ["payment_event_id"],
}

NEW_INDEXES = (
    "idx_finance_receipts_event_active",
    "idx_finance_receipts_idem",
    "idx_finance_bill_adjustments_idem",
    "idx_finance_receipts_layout",
    "idx_finance_payment_event_lines_bill",
    "idx_finance_accounts_custody_owner",
    "idx_finance_accounts_primary",
    "idx_finance_transactions_event",
    "idx_finance_transactions_voucher",
    "idx_finance_transactions_income_batch",
)


async def _insert_room(pool, *, name: str = "ห้องทดสอบสคีมา") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            name, f"R{name[:2]}",
        )


async def _insert_student(pool, room_id: int, *, student_no: int = 1) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no,
        )


async def _insert_bill(pool, room_id: int, student_id: int, *, amount: float = 100.0) -> tuple[int, int]:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, status)
               VALUES ($1, 'ค่าโครงการทดสอบ', $2, 'active') RETURNING id""",
            room_id, amount,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0) RETURNING id""",
            collection_id, student_id,
        )
    return collection_id, payment_id


async def _insert_event(pool, room_id: int, student_id: int, *, key: str,
                        amount: float = 100.0) -> int:
    """สร้าง event ที่ผ่าน CHECK สมการ (เงินสด 100 ไปปิดบิล 100)"""
    async with pool.acquire() as conn:
        account_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'กระเป๋า', 0) RETURNING id",
            room_id,
        )
        return await conn.fetchval(
            """INSERT INTO finance_payment_events
                   (room_id, student_id, payer_name, receiver_name, wallet_account_id,
                    amount_received, total_applied, idempotency_key)
               VALUES ($1, $2, 'ผู้ปกครอง', 'ครู', $3, $4, $4, $5)
               RETURNING id""",
            room_id, student_id, account_id, amount, key,
        )


# ═══════════════════════════════════════════════════════════════════ 1. schema
async def test_migration_0012_creates_schema(db_pool):
    async with db_pool.acquire() as conn:
        tables = {
            row["table_name"]
            for row in await conn.fetch(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = ANY($1::text[])""",
                list(NEW_TABLES),
            )
        }
        assert tables == set(NEW_TABLES), f"ตารางหาย: {set(NEW_TABLES) - tables}"

        for table, columns in NEW_COLUMNS.items():
            existing = {
                row["column_name"]
                for row in await conn.fetch(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = $1""",
                    table,
                )
            }
            missing = set(columns) - existing
            assert not missing, f"{table} ขาดคอลัมน์: {sorted(missing)}"

        # legacy ต้องยังอ่านได้: ค่า default ชอง layout_version = 1 (ไม่ใช่ 2)
        default = await conn.fetchval(
            """SELECT column_default FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'finance_receipts'
                 AND column_name = 'layout_version'"""
        )
        assert default == "1", f"layout_version default ต้องเป็น 1 (ได้ {default!r})"


async def test_migration_0013_creates_indexes(db_pool):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT indexname, indexdef FROM pg_indexes
               WHERE schemaname = 'public' AND indexname = ANY($1::text[])""",
            list(NEW_INDEXES),
        )
        found = {row["indexname"]: row["indexdef"] for row in rows}
        missing = set(NEW_INDEXES) - set(found)
        assert not missing, f"index หาย: {sorted(missing)}"

        # 🔑 predicate ต้องกรอง line_kind ด้วย (จ่ายเงินสด+เครดิตพร้อมกันได้)
        lines_bill = found["idx_finance_payment_event_lines_bill"]
        assert "line_kind" in lines_bill and "'bill'" in lines_bill

        # partial unique ของ event ต้องไม่กันแถว legacy ที่ payment_event_id IS NULL
        event_active = found["idx_finance_receipts_event_active"]
        assert "payment_event_id IS NOT NULL" in event_active
        assert "deleted_at IS NULL" in event_active


async def test_migrations_are_idempotent(db_pool):
    async with db_pool.acquire() as conn:
        before = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")

    # conftest apply ครบแล้ว ⇒ รอบนี้ต้องไม่มีไฟล์ใหม่ให้รัน
    assert await apply_migrations(db_pool) == 0

    async with db_pool.acquire() as conn:
        after = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
        versions = {
            row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")
        }
    assert after == before
    assert {"0012_finance_module_foundation", "0013_finance_module_constraints"} <= versions


# ═══════════════════════════════════════════════════════════════════ 2. constants
async def test_receipt_no_pattern_accepts_four_letter_prefix():
    import re

    assert re.fullmatch(RECEIPT_NO_PATTERN, "CERT-2569-0001")
    assert re.fullmatch(RECEIPT_NO_PATTERN, "ACK-2569-0001")
    assert re.fullmatch(RECEIPT_NO_PATTERN, "REC-2569-0042")
    assert re.fullmatch(RECEIPT_NO_PATTERN, "PV-2569-0007")
    # 5 ตัว / ตัวเล็ก / ไม่มีลำดับ 4 หลัก ต้องไม่ผ่าน
    assert not re.fullmatch(RECEIPT_NO_PATTERN, "CERTT-2569-0001")
    assert not re.fullmatch(RECEIPT_NO_PATTERN, "cert-2569-0001")
    assert not re.fullmatch(RECEIPT_NO_PATTERN, "CERT-2569-00012")


async def test_doc_type_prefixes_cover_ack_and_cert():
    assert DOC_TYPE_PREFIXES[DOC_TYPE_ACKNOWLEDGEMENT] == "ACK"
    assert DOC_TYPE_PREFIXES[DOC_TYPE_CERTIFICATE] == "CERT"
    assert DOC_TYPE_LABELS[DOC_TYPE_ACKNOWLEDGEMENT] == "ใบรับทราบยอดค้าง"
    assert DOC_TYPE_LABELS[DOC_TYPE_CERTIFICATE] == "ใบรับรองแทนใบเสร็จ"
    assert DOC_TYPE_LABELS[DOC_TYPE_MONTHLY_REPORT] == "รายงานปิดงบ"
    # RPT ใช้ receipt_sequences ไม่ได้ — ต้องไม่มี prefix
    assert DOC_TYPE_MONTHLY_REPORT not in DOC_TYPE_PREFIXES


async def test_system_ledger_59002_provisioned(db_pool):
    room_id = await _insert_room(db_pool)
    async with db_pool.acquire() as conn:
        ledger_id = await FinanceService._resolve_system_ledger(
            conn, room_id,
            code=PROJECT_BAD_DEBT_CODE,
            name=PROJECT_BAD_DEBT_NAME,
            account_type="expense",
        )
        row = await conn.fetchrow(
            """SELECT account_code, account_name, account_type,
                      legacy_account_id, legacy_category_id
               FROM accounting_ledgers WHERE id = $1""",
            ledger_id,
        )

    assert row["account_code"] == "59002"
    assert row["account_name"] == PROJECT_BAD_DEBT_NAME
    assert row["account_type"] == "expense"
    assert row["legacy_account_id"] is None
    assert row["legacy_category_id"] is None
    assert SYSTEM_LEDGER_SPECS["59002"] == (PROJECT_BAD_DEBT_NAME, "expense")

    # เรียกซ้ำต้องได้ ledger ใบเดิม (ไม่สร้างซ้ำ)
    async with db_pool.acquire() as conn:
        again = await FinanceService._resolve_system_ledger(
            conn, room_id,
            code=PROJECT_BAD_DEBT_CODE,
            name=PROJECT_BAD_DEBT_NAME,
            account_type="expense",
        )
    assert again == ledger_id


# ═══════════════════════════════════════════════════════════════════ 3. กันเงินซ้ำ
async def test_event_line_unique_allows_cash_and_credit_for_same_bill(db_pool):
    """บิล 1 ใบมีได้ทั้งบรรทัด `bill` และ `credit_apply` ใน event เดียวกัน

    นี่คือเหตุผลที่ `idx_finance_payment_event_lines_bill` ต้องมี `line_kind = 'bill'`
    ใน predicate — ถ้าไม่มี การจ่ายเงินสด+เครดิตพร้อมกันจะชน unique ผิด ๆ
    """
    room_id = await _insert_room(db_pool)
    student_id = await _insert_student(db_pool, room_id)
    _, payment_id = await _insert_bill(db_pool, room_id, student_id)

    # event ยอด 100: เงินสด 60 + เครดิต 40 ไปปิดบิลใบเดียวกัน
    async with db_pool.acquire() as conn:
        account_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'กระเป๋า', 0) RETURNING id",
            room_id,
        )
        tx_id = await conn.fetchval(
            """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type)
               VALUES ($1, $2, 60, 'รับเงินสด', 'income') RETURNING id""",
            room_id, account_id,
        )
        credit_id = await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after)
               VALUES ($1, $2, 'apply', 40, 0) RETURNING id""",
            room_id, student_id,
        )
        event_id = await conn.fetchval(
            """INSERT INTO finance_payment_events
                   (room_id, student_id, payer_name, receiver_name, wallet_account_id,
                    amount_received, credit_used, total_applied, idempotency_key)
               VALUES ($1, $2, 'ผู้ปกครอง', 'ครู', $3, 60, 40, 100, 'evt-cash-credit')
               RETURNING id""",
            room_id, student_id, account_id,
        )

        await conn.execute(
            """INSERT INTO finance_payment_event_lines
                   (event_id, line_kind, student_payment_id, finance_transaction_id, amount)
               VALUES ($1, 'bill', $2, $3, 60)""",
            event_id, payment_id, tx_id,
        )
        await conn.execute(
            """INSERT INTO finance_payment_event_lines
                   (event_id, line_kind, student_payment_id, credit_entry_id, amount)
               VALUES ($1, 'credit_apply', $2, $3, 40)""",
            event_id, payment_id, credit_id,
        )
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_payment_event_lines WHERE event_id = $1", event_id,
        )

        # บรรทัด `bill` ที่สองของบิลเดิมใน event เดียวกัน ต้องถูกกัน
        with pytest.raises(asyncpg.UniqueViolationError):
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO finance_payment_event_lines
                           (event_id, line_kind, student_payment_id, finance_transaction_id, amount)
                       VALUES ($1, 'bill', $2, $3, 10)""",
                    event_id, payment_id, tx_id,
                )

    assert count == 2


async def test_event_check_rejects_unbalanced_amounts(db_pool):
    room_id = await _insert_room(db_pool)
    student_id = await _insert_student(db_pool, room_id)

    async with db_pool.acquire() as conn:
        account_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'กระเป๋า', 0) RETURNING id",
            room_id,
        )
        # 100 ≠ 90 + 20 ⇒ ต้องผิด CHECK (amount_received + credit_used = total + added)
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO finance_payment_events
                           (room_id, student_id, payer_name, receiver_name, wallet_account_id,
                            amount_received, total_applied, credit_added, excess_action, idempotency_key)
                       VALUES ($1, $2, 'ผู้ปกครอง', 'ครู', $3, 100, 90, 20, 'credit', 'evt-bad')""",
                    room_id, student_id, account_id,
                )


async def test_event_idempotency_key_unique_per_room(db_pool):
    room_id = await _insert_room(db_pool)
    student_id = await _insert_student(db_pool, room_id)
    event_id = await _insert_event(db_pool, room_id, student_id, key="same-key")

    async with db_pool.acquire() as conn:
        with pytest.raises(asyncpg.UniqueViolationError):
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO finance_payment_events
                           (room_id, student_id, payer_name, receiver_name, wallet_account_id,
                            amount_received, total_applied, idempotency_key)
                       VALUES ($1, $2, 'ผู้ปกครอง', 'ครู',
                               (SELECT wallet_account_id FROM finance_payment_events WHERE id = $3),
                               10, 10, 'same-key')""",
                    room_id, student_id, event_id,
                )


# ═══════════════════════════════════════════════════════════════════ 4. init_db
async def test_init_db_plus_migrations_boot_without_init_db_edits():
    """สคีมา v2 ต้องมาจาก migration เท่านั้น — `init_db.py` ห้ามมี DDL ของตารางใหม่

    ⚠️ เหตุผล: บน DB จริงที่มีตารางอยู่แล้ว บล็อก `CREATE TABLE IF NOT EXISTS`
    ของ `init_db` เป็น no-op ⇒ ถ้าใส่ DDL ใหม่ไว้ที่นั่น เทสต์บน DB ใหม่จะเขียว
    แต่โปรดักชันจะพังตอนบูต (`column ... does not exist`)
    """
    init_db_path = Path(__file__).resolve().parents[1] / "core" / "init_db.py"
    source = init_db_path.read_text(encoding="utf-8")
    for marker in ("finance_payment_events", "finance_people", "finance_monthly_reports"):
        assert marker not in source, f"init_db.py มี DDL ของ v2 ({marker}) — ต้องอยู่ใน migration เท่านั้น"
