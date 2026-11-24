"""⚖️ ออกค่าปรับ — บิลซ่อน + INV- 1 ใบ/คน + journal Dr 11002 / Cr 49001 + idempotency

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ค่าปรับต้องเกิดเป็นบิลจริงในระบบเดิม** — 1 คน = 1 hidden collection (`kind='fine'`)
   + 1 `student_payments` pending ⇒ ไม่งั้นยอดค้าง/เครดิต/ใบเสร็จใช้ด้วยไม่ได้เลย
2. **เกณฑ์คงค้างตอนออกบิล** — Dr 11002 ผู้ค้างชำระค่าปรับ / Cr 49001 รายได้ค่าปรับ
   ต่อบิล · ยอดรวมต้องเท่ากับผลรวมยอดที่ออก
3. **INV- 1 ใบต่อ 1 ค่าปรับ** — ใบ récord ต้องผูก `student_payment_id` ของบิลนั้น
   (ใบรวมยอดมี `student_payment_id IS NULL` จึงไม่ชนกับ unique index ของค่าปรับ)
4. **กดซ้ำด้วย idempotency key เดิม = ผลเดิม** — ไม่สร้างบิล/ใบ/journl ซ้ำแม้แต่แถวเดียว
5. **all-or-nothing** — มีนักเรียนที่ไม่ใช่ของห้องติดมาก้อนเดียว ⇒ ไม่มีอะไรถูกเขียนเลย
6. **"อื่น ๆ" ที่อัตรา 0 ต้องกรอกยอดเอง** — ปล่อย 0 ต้อง 400 (บิล 0 บาทไร้ความหมาย)
"""
import uuid
from datetime import date

import pytest

from services.finance.constants import (
    AR_FINE_CODE, COLLECTION_KIND_FINE, DOC_TYPE_INVOICE,
    FINE_REVENUE_CODE, FINE_STATUS_ISSUED,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
FINES_PATH = API_PREFIX + "/{room}/finance/fines"
TYPES_PATH = API_PREFIX + "/{room}/finance/fine-types"


def _url(template: str, room_id: int, **kwargs) -> str:
    return template.format(room=room_id, **kwargs) + "?target_type=room"


class _H(dict):
    """headers + room_id (เหมือน `_AuthContext` ของ conftest แต่สร้างเองในเทสต์นี้)"""

    def __init__(self, headers: dict, room_id: int):
        super().__init__(headers)
        self.room_id = room_id


def _key() -> str:
    return uuid.uuid4().hex


async def _make_student(pool, room_id: int, *, student_no: int = 90,
                        first_name: str = "เด็กชายทดสอบ") -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "ทดลอง", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _seed_types(pool, room_id: int):
    async with pool.acquire() as conn:
        await FinanceService.ensure_default_fine_types(conn, room_id)


async def _type_id(pool, room_id: int, name: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM fine_types WHERE room_id = $1 AND name = $2 AND deleted_at IS NULL",
            room_id, name,
        )


def _issue(client, headers, body):
    return client.post(_url(FINES_PATH, headers.room_id), json=body, headers=headers)


def _issue_body(fine_type_id: int, students, *, key=None, amount=None, due=None, reason="ทดสอบ"):
    payload = {
        "fine_type_id": fine_type_id,
        "students": [
            {"student_id": int(s), **({} if amount is None else {"amount": amount})}
            if isinstance(s, int) else s
            for s in students
        ],
        "incident_date": "2026-11-20",
        "reason": reason,
        "idempotency_key": key or _key(),
        "user_name": "Tester",
    }
    if due is not None:
        payload["due_date"] = due
    return payload


async def _credit_net(pool, room_id: int, code: str) -> float:
    """ยอด credit−debit ของบัญชี (รายได้/ส่วนลด) — ตัดใบ void/soft-delete ออก"""
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.credit - L.debit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_code = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, code,
        )
    return round(float(val), 2)


async def _debit_net(pool, room_id: int, code: str) -> float:
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_code = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, code,
        )
    return round(float(val), 2)


async def test_issue_two_students_creates_bills_invoices_and_accrual(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    late_type = await _type_id(db_pool, room_id, "มาสาย / ไม่ทำเวร")
    s1 = await _make_student(db_pool, room_id, student_no=90, first_name="ก")
    s2 = await _make_student(db_pool, room_id, student_no=91, first_name="ข")

    res = _issue(client, admin_headers, _issue_body(late_type, [s1, s2], due="2026-11-27"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reused"] is False
    assert body["totals"]["student_count"] == 2
    assert body["totals"]["total_amount"] == 40.0
    assert len(body["fines"]) == 2 and len(body["invoice_nos"]) == 2
    assert all(n.startswith("INV-") for n in body["invoice_nos"])

    async with db_pool.acquire() as conn:
        collections = await conn.fetch(
            "SELECT amount, collection_kind FROM fee_collections WHERE room_id = $1 AND deleted_at IS NULL",
            room_id,
        )
        assert len(collections) == 2
        assert all(c["collection_kind"] == COLLECTION_KIND_FINE for c in collections)

        bills = await conn.fetch(
            """SELECT SP.id, SP.status, SP.paid_amount FROM student_payments SP
               JOIN fee_collections FC ON FC.id = SP.collection_id
               WHERE FC.room_id = $1 AND FC.collection_kind = $2""",
            room_id, COLLECTION_KIND_FINE,
        )
        assert len(bills) == 2
        assert all(b["status"] == "pending" and float(b["paid_amount"]) == 0 for b in bills)

        fines = await conn.fetch(
            "SELECT * FROM fines WHERE room_id = $1 AND deleted_at IS NULL", room_id
        )
        assert len(fines) == 2
        assert all(f["status"] == FINE_STATUS_ISSUED for f in fines)
        assert all(f["invoice_receipt_id"] is not None for f in fines)
        assert float(fines[0]["original_amount"]) == 20.0

        invoices = await conn.fetch(
            """SELECT student_payment_id, amount, doc_type FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2 AND deleted_at IS NULL""",
            room_id, DOC_TYPE_INVOICE,
        )
        assert len(invoices) == 2
        assert all(i["student_payment_id"] in {b["id"] for b in bills} for i in invoices)
        assert all(float(i["amount"]) == 20.0 for i in invoices)

        batch = await conn.fetchrow("SELECT * FROM fine_batches WHERE room_id = $1", room_id)
        assert batch["student_count"] == 2 and float(batch["total_amount"]) == 40.0

    assert await _debit_net(db_pool, room_id, AR_FINE_CODE) == 40.0
    assert await _credit_net(db_pool, room_id, FINE_REVENUE_CODE) == 40.0


async def test_same_idempotency_key_returns_original_without_new_rows(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    late_type = await _type_id(db_pool, room_id, "มาสาย / ไม่ทำเวร")
    s1 = await _make_student(db_pool, room_id, student_no=90)

    body = _issue_body(late_type, [s1])
    first = _issue(client, admin_headers, body)
    assert first.status_code == 200, first.text

    second = _issue(client, admin_headers, body)
    assert second.status_code == 200, second.text
    data = second.json()
    assert data["reused"] is True
    assert data["fines"][0]["id"] == first.json()["fines"][0]["id"]

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM fines WHERE room_id = $1", room_id) == 1
        assert await conn.fetchval("SELECT COUNT(*) FROM fine_batches WHERE room_id = $1", room_id) == 1
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM fee_collections WHERE room_id = $1 AND collection_kind = $2",
            room_id, COLLECTION_KIND_FINE,
        ) == 1
    # journal ต้องมีใบเดียว (unique index `uq_journal_bill_issue` เป็นด่านสอง)
    assert await _debit_net(db_pool, room_id, AR_FINE_CODE) == 20.0


async def test_override_amount_per_student(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    other_type = await _type_id(db_pool, room_id, "อื่น ๆ (กรอกยอดเอง)")
    s1 = await _make_student(db_pool, room_id, student_no=90)

    res = _issue(client, admin_headers, _issue_body(other_type, [{"student_id": s1, "amount": 55.5}]))
    assert res.status_code == 200, res.text
    assert res.json()["fines"][0]["amount"] == 55.5
    assert await _debit_net(db_pool, room_id, AR_FINE_CODE) == 55.5


async def test_zero_default_amount_without_override_is_rejected(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    other_type = await _type_id(db_pool, room_id, "อื่น ๆ (กรอกยอดเอง)")
    s1 = await _make_student(db_pool, room_id, student_no=90)

    res = _issue(client, admin_headers, _issue_body(other_type, [s1]))
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM fines WHERE room_id = $1", room_id) == 0


async def test_invalid_student_rolls_back_entire_batch(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    late_type = await _type_id(db_pool, room_id, "มาสาย / ไม่ทำเวร")
    good = await _make_student(db_pool, room_id, student_no=90)

    res = _issue(client, admin_headers, _issue_body(late_type, [good, 9_999_999]))
    assert res.status_code == 400, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM fine_batches WHERE room_id = $1", room_id) == 0
        assert await conn.fetchval("SELECT COUNT(*) FROM fines WHERE room_id = $1", room_id) == 0
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM fee_collections WHERE room_id = $1", room_id
        ) == 0
    assert await _debit_net(db_pool, room_id, AR_FINE_CODE) == 0.0


async def test_due_date_before_incident_date_is_rejected(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    late_type = await _type_id(db_pool, room_id, "มาสาย / ไม่ทำเวร")
    s1 = await _make_student(db_pool, room_id, student_no=90)

    res = _issue(client, admin_headers, _issue_body(late_type, [s1], due="2026-11-01"))
    assert res.status_code == 400, res.text


async def test_member_cannot_issue(client, db_pool, admin_headers):
    import random

    from core.config import settings

    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    late_type = await _type_id(db_pool, room_id, "มาสาย / ไม่ทำเวร")

    discord_id = random.randint(1_000_000, 9_999_999)
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ('สมาชิก', 'ทดสอบ', $1, $2) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        member_student = await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 90, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id,
        )
    member = {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}

    res = _issue(client, _H(member, room_id), _issue_body(late_type, [member_student]))
    assert res.status_code == 403, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM fines WHERE room_id = $1", room_id) == 0


async def test_student_sees_only_own_fines_in_list(client, db_pool, admin_headers):
    """นักเรียน (มี students row ในห้อง) เห็นรายการค่าปรับเฉพาะของตัวเอง แม้ query ไม่กรอง"""
    import random

    from core.config import settings

    room_id = admin_headers.room_id
    await _seed_types(db_pool, room_id)
    late_type = await _type_id(db_pool, room_id, "มาสาย / ไม่ทำเวร")

    # นักเรียน 2 คน + ผูก user กับคนแรก
    discord_id = random.randint(1_000_000, 9_999_999)
    async with db_pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ('นักเรียน', 'ทดสอบ', $1, $2) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        own_student = await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 90, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id,
        )
    other = await _make_student(db_pool, room_id, student_no=91, first_name="เพื่อน")

    res = _issue(client, admin_headers, _issue_body(late_type, [own_student, other]))
    assert res.status_code == 200, res.text

    student_headers = {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}
    listing = client.get(_url(FINES_PATH, room_id), headers=student_headers)
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["total"] == 1
    assert data["fines"][0]["student_id"] == own_student
