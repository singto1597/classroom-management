"""💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว (bulk credit offset)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 นักเรียน = 1 payment event แบบ credit-only** — ไม่มี REC/DEP และ
   **ไม่มี `finance_transactions`/การเปลี่ยนยอดกระเป๋าเลย** (เครดิตไม่ใช่เงินสด)
2. **all-or-nothing** — ล้มคนเดียว = ไม่มีใครถูกหัก, ไม่มี event ค้าง, ยอดเครดิตเดิม
3. **idempotency** — คีย์เดิม + ชุดเดิม ⇒ `reused=true` ผลเท่าเดิม ไม่เขียนซ้ำ;
   คีย์เดิม + ชุดต่าง ⇒ **409** (ไม่ใช่ 400 เพราะข้อมูลของผู้ใช้ไม่ได้ผิด)
4. **ข้ามคนที่ไม่มีบิลค้าง** — คืนใน `skipped` ไม่สร้าง event ให้คนนั้น
5. **RBAC + ขอบเขตห้อง** — MANAGE_FINANCE เท่านั้น; นักเรียนต่างห้อง ⇒ 404
6. **ล็อกห้องก่อนคำสั่งเขียนใด ๆ** และเมธอดถูกขึ้นทะเบียนใน `_MONEY_PATHS`

⚠️ ยอดเงินทุกก้อน assert เป็นสตริง 2 ตำแหน่ง และอ่านกลับจาก Postgres ตรง ๆ ผ่าน `db_pool`
"""
import importlib.util
import inspect
import pathlib
import random
import string
import uuid
from unittest.mock import patch

import pytest

from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RECEIVER = "ครูสมศรี"


# ═══════════════════════════════════════════════════════════════════ helpers
def _rounds_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/credits/rounds"


def _new_key() -> str:
    return uuid.uuid4().hex


def _money(value) -> str:
    return f"{float(value):.2f}"


def _payload(
    student_ids: list[int], *, key: str | None = None, account_id: int | None = None,
    reference: str | None = None, user_name: str = RECEIVER,
    receiver_person_id: int | None = None, note: str | None = None,
) -> dict:
    body = {
        "idempotency_key": key or _new_key(),
        "student_ids": student_ids,
        "user_name": user_name,
    }
    if account_id is not None:
        body["wallet_account_id"] = account_id
    if reference is not None:
        body["reference_no"] = reference
    if receiver_person_id is not None:
        body["receiver_person_id"] = receiver_person_id
    if note is not None:
        body["note"] = note
    return body


async def _insert_student(pool, room_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no,
        )


async def _insert_account(
    pool, room_id: int, name: str = "กระเป๋ากลาง", balance: float = 0.0,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts (room_id, account_name, balance)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, balance,
        )


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        return await conn.fetchval(
            """INSERT INTO rooms (room_name, room_code, owner_id)
               VALUES ('Other Room', $1, $2) RETURNING id""",
            code, owner_id,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *,
    title: str = "ค่าเทอม", amount: float = 1000.0,
) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, NULL, 'active', 'room_fund', 'project') RETURNING id""",
            room_id, title, amount,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', 0, 0) RETURNING id""",
            collection_id, student_id,
        )


async def _insert_credit(pool, room_id: int, student_id: int, amount: float):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after)
               VALUES ($1, $2, 'topup', $3, $3) RETURNING id""",
            room_id, student_id, amount,
        )


async def _insert_pending_fine(pool, room_id: int, student_id: int, payment_id: int) -> None:
    """บิลที่มีคำขอยกเว้น pending — `_apply_plan_locked` ต้องปฏิเสธการใช้เครดิต"""
    async with pool.acquire() as conn:
        fine_id = await conn.fetchval(
            """INSERT INTO fines
                   (room_id, fine_type_name, student_id, student_payment_id,
                    incident_date, due_date, reason, original_amount, amount)
               VALUES ($1, 'มาสาย', $2, $3, CURRENT_DATE, CURRENT_DATE,
                       'ทดสอบชุด all-or-nothing', 100, 100)
               RETURNING id""",
            room_id, student_id, payment_id,
        )
        await conn.execute(
            """INSERT INTO fine_waivers
                   (room_id, fine_id, amount, reason_category, reason, status)
               VALUES ($1, $2, 100, 'discount', 'คำขอค้างอนุมัติ', 'pending')""",
            room_id, fine_id,
        )


async def _events(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM finance_payment_events WHERE room_id = $1 ORDER BY id",
            room_id,
        )


async def _count(pool, sql: str, *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def _latest_credit(pool, room_id: int, student_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT entry_type, amount, balance_after
               FROM student_credits
               WHERE room_id = $1 AND student_id = $2
               ORDER BY id DESC LIMIT 1""",
            room_id, student_id,
        )


def _money_lock_tests():
    """โหลด `test_finance_money_lock.py` เป็นโมดูล เพื่อใช้ `_MONEY_PATHS`/`_resolve_method`
    (tests/ ไม่ใช่ package — import ตรงไม่ได้)"""
    path = pathlib.Path(__file__).with_name("test_finance_money_lock.py")
    spec = importlib.util.spec_from_file_location("_money_lock_tests_for_p35", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ═══════════════════════════════════════ 1. N คน → N credit-only event
async def test_credit_round_creates_one_credit_only_event_per_student(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room, balance=1000.0)
    bill1 = await _insert_bill(db_pool, room, s1, title="ค่าเทอม", amount=500.0)
    bill2 = await _insert_bill(db_pool, room, s2, title="ค่ากิจกรรม", amount=700.0)
    await _insert_credit(db_pool, room, s1, 500.0)
    await _insert_credit(db_pool, room, s2, 300.0)

    resp = client.post(
        _rounds_url(room),
        json=_payload([s1, s2], account_id=account, reference="CR-ROUND-1"),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["reused"] is False
    assert data["reference_no"] == "CR-ROUND-1"
    assert [e["student_id"] for e in data["events"]] == [s1, s2]
    assert _money(data["events"][0]["total_applied"]) == "500.00"
    assert _money(data["events"][1]["total_applied"]) == "300.00"
    assert _money(data["total_applied"]) == "800.00"
    assert data["skipped"] == []

    events = await _events(db_pool, room)
    assert len(events) == 2
    by_student = {e["student_id"]: e for e in events}
    for sid, expected in ((s1, "500.00"), (s2, "300.00")):
        ev = by_student[sid]
        assert _money(ev["amount_received"]) == "0.00"
        assert _money(ev["credit_used"]) == expected
        assert _money(ev["credit_added"]) == "0.00"
        assert _money(ev["total_applied"]) == expected
        assert ev["excess_action"] == "none"
        assert ev["payer_name"] == "ใช้เครดิต"
        assert ev["wallet_account_id"] == account
        assert ev["reference_no"] == "CR-ROUND-1"

    # บิลปิดครบตามยอดเครดิต
    async with db_pool.acquire() as conn:
        paid = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill1
        )
        partial = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill2
        )
    assert paid["status"] == "paid"
    assert _money(paid["paid_amount"]) == "500.00"
    assert partial["status"] == "pending"
    assert _money(partial["paid_amount"]) == "300.00"


# ═══════════════════ 2. ไม่มี REC/transaction และไม่แตะยอดกระเป๋า
async def test_credit_round_creates_no_receipts_or_transactions_and_keeps_wallet(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room, balance=1234.56)
    bill = await _insert_bill(db_pool, room, s1, amount=400.0)
    await _insert_credit(db_pool, room, s1, 400.0)

    resp = client.post(
        _rounds_url(room), json=_payload([s1], account_id=account), headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    event_id = resp.json()["events"][0]["event_id"]
    assert bill > 0

    assert await _count(
        db_pool, "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room,
    ) == 0
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND payment_event_id = $2",
        room, event_id,
    ) == 0
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account
        )
    assert _money(balance) == "1234.56", "เครดิตไม่ใช่เงินสด — ยอดกระเป๋าต้องไม่ขยับ"

    # บรรทัดของ event เป็น credit_apply ทั้งหมด (ไม่มี bill line = ไม่มีเงินสด)
    kinds = await _count(
        db_pool,
        """SELECT COUNT(*) FROM finance_payment_event_lines
           WHERE event_id = $1 AND line_kind <> 'credit_apply'""",
        event_id,
    )
    assert kinds == 0


# ═══════════════════════════ 3. บรรทัดตรงกับบิลที่ถูกหัก
async def test_credit_round_lines_match_the_bills_they_close(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    bill1 = await _insert_bill(db_pool, room, s1, title="บิลแรก", amount=300.0)
    bill2 = await _insert_bill(db_pool, room, s1, title="บิลที่สอง", amount=400.0)
    await _insert_credit(db_pool, room, s1, 500.0)

    resp = client.post(
        _rounds_url(room), json=_payload([s1], account_id=account), headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    event_id = resp.json()["events"][0]["event_id"]

    async with db_pool.acquire() as conn:
        lines = await conn.fetch(
            """SELECT student_payment_id, credit_entry_id, amount,
                      bill_amount_before, bill_amount_after
               FROM finance_payment_event_lines
               WHERE event_id = $1 ORDER BY id""",
            event_id,
        )
    assert len(lines) == 2
    by_bill = {int(line["student_payment_id"]): line for line in lines}
    assert _money(by_bill[bill1]["amount"]) == "300.00"
    assert _money(by_bill[bill1]["bill_amount_before"]) == "300.00"
    assert _money(by_bill[bill1]["bill_amount_after"]) == "0.00"
    assert _money(by_bill[bill2]["amount"]) == "200.00"
    assert _money(by_bill[bill2]["bill_amount_before"]) == "400.00"
    assert _money(by_bill[bill2]["bill_amount_after"]) == "200.00"

    # แต่ละบรรทัดชี้กลับแถวเครดิตที่ `_apply_plan_locked` เพิ่งเขียน
    entry_ids = [int(line["credit_entry_id"]) for line in lines]
    assert all(entry_ids)
    async with db_pool.acquire() as conn:
        entries = await conn.fetch(
            """SELECT id, entry_type, amount, balance_after, payment_event_id,
                      student_payment_id
               FROM student_credits WHERE id = ANY($1::int[]) ORDER BY id""",
            entry_ids,
        )
    assert len(entries) == 2
    assert [e["entry_type"] for e in entries] == ["apply", "apply"]
    assert [e["payment_event_id"] for e in entries] == [event_id, event_id]
    assert {int(e["student_payment_id"]) for e in entries} == {bill1, bill2}
    assert _money(entries[0]["amount"]) == "300.00"
    assert _money(entries[0]["balance_after"]) == "200.00"
    assert _money(entries[1]["amount"]) == "200.00"
    assert _money(entries[1]["balance_after"]) == "0.00"

    # ยอดคงเหลือของคนนี้ = 0 (ตรงกับผลของ event)
    latest = await _latest_credit(db_pool, room, s1)
    assert _money(latest["balance_after"]) == "0.00"


# ══════════════════════════ 4. all-or-nothing
async def test_credit_round_rolls_back_everything_when_one_student_fails(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room, balance=999.0)
    bill1 = await _insert_bill(db_pool, room, s1, amount=500.0)
    bill2 = await _insert_bill(db_pool, room, s2, amount=500.0)
    topup1 = await _insert_credit(db_pool, room, s1, 500.0)
    topup2 = await _insert_credit(db_pool, room, s2, 500.0)
    # s2 มีคำขอยกเว้นค่าปรับรออนุมัติ ⇒ `_apply_plan_locked` ของ s2 โยน ValueError
    # หลัง s1 ถูกเขียนไปแล้ว ⇒ transaction ต้อง rollback ทั้งหมด
    await _insert_pending_fine(db_pool, room, s2, bill2)

    resp = client.post(
        _rounds_url(room), json=_payload([s1, s2], account_id=account), headers=admin_headers,
    )
    assert resp.status_code == 400, resp.text

    assert await _events(db_pool, room) == []
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM finance_payment_event_lines WHERE event_id IN "
        "(SELECT id FROM finance_payment_events WHERE room_id = $1)",
        room,
    ) == 0
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM student_credits WHERE room_id = $1 AND entry_type = 'apply'",
        room,
    ) == 0
    async with db_pool.acquire() as conn:
        for bill_id in (bill1, bill2):
            row = await conn.fetchrow(
                "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill_id
            )
            assert row["status"] == "pending"
            assert _money(row["paid_amount"]) == "0.00"
        latest1 = await conn.fetchval(
            "SELECT id FROM student_credits WHERE student_id = $1 ORDER BY id DESC LIMIT 1",
            s1,
        )
        latest2 = await conn.fetchval(
            "SELECT id FROM student_credits WHERE student_id = $1 ORDER BY id DESC LIMIT 1",
            s2,
        )
    assert latest1 == topup1 and latest2 == topup2, "ยอดเครดิตต้องไม่ถูกแตะเลย"


# ═══════════════════════════════ 5. replay คืนผลเดิม
async def test_credit_round_replay_returns_the_same_round(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    await _insert_bill(db_pool, room, s2, amount=300.0)
    await _insert_credit(db_pool, room, s1, 500.0)
    await _insert_credit(db_pool, room, s2, 300.0)
    key = _new_key()
    body = _payload([s1, s2], key=key, account_id=account, reference="CR-REPLAY")

    first = client.post(_rounds_url(room), json=body, headers=admin_headers)
    assert first.status_code == 200, first.text
    first_data = first.json()

    second = client.post(_rounds_url(room), json=body, headers=admin_headers)
    assert second.status_code == 200, second.text
    second_data = second.json()

    assert first_data["reused"] is False
    assert second_data["reused"] is True
    assert second_data["reference_no"] == "CR-REPLAY"
    assert _money(second_data["total_applied"]) == _money(first_data["total_applied"]) == "800.00"
    assert [e["event_id"] for e in second_data["events"]] == [
        e["event_id"] for e in first_data["events"]
    ]
    assert [e["credit_entry_ids"] for e in second_data["events"]] == [
        e["credit_entry_ids"] for e in first_data["events"]
    ]
    # replay ไม่เขียนอะไรเพิ่ม
    assert len(await _events(db_pool, room)) == 2
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM student_credits WHERE room_id = $1 AND entry_type = 'apply'",
        room,
    ) == 2


# ═══════════════ 6. คีย์เดิม + ชุดนักเรียนต่าง → 409
async def test_credit_round_same_key_different_student_set_is_409(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=200.0)
    await _insert_bill(db_pool, room, s2, amount=200.0)
    await _insert_credit(db_pool, room, s1, 200.0)
    await _insert_credit(db_pool, room, s2, 200.0)
    key = _new_key()

    first = client.post(
        _rounds_url(room),
        json=_payload([s1, s2], key=key, account_id=account),
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        _rounds_url(room),
        json=_payload([s1], key=key, account_id=account),
        headers=admin_headers,
    )
    assert second.status_code == 409, second.text
    assert "ชุดนักเรียนอื่น" in second.json()["detail"]

    # ไม่มีอะไรถูกเขียนเพิ่มและไม่มีใครถูกหักซ้ำ
    events = await _events(db_pool, room)
    assert len(events) == 2
    assert {e["idempotency_key"] for e in events} == {f"{key}:{s1}", f"{key}:{s2}"}
    latest = await _latest_credit(db_pool, room, s1)
    assert _money(latest["balance_after"]) == "0.00"


# ═══════════════ 7. ข้ามคนที่ไม่มีบิลค้าง (ไม่สร้าง event)
async def test_credit_round_skips_students_without_open_bills(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=250.0)
    await _insert_credit(db_pool, room, s1, 250.0)
    # s2 มีเครดิตแต่ไม่มีบิลค้าง ⇒ ต้องถูกข้าม ไม่ใช่ error
    await _insert_credit(db_pool, room, s2, 900.0)

    resp = client.post(
        _rounds_url(room),
        json=_payload([s1, s2], account_id=account),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert [e["student_id"] for e in data["events"]] == [s1]
    assert [s["student_id"] for s in data["skipped"]] == [s2]
    assert data["skipped"][0]["reason"] == "ไม่มีบิลค้างหรือเครดิตไม่พอ"
    assert _money(data["total_applied"]) == "250.00"

    events = await _events(db_pool, room)
    assert [e["student_id"] for e in events] == [s1]
    # เครดิตของคนที่ถูกข้ามไม่ถูกแตะ
    latest = await _latest_credit(db_pool, room, s2)
    assert _money(latest["balance_after"]) == "900.00"


# ═══════════════════════════ 8. เกิน 100 คน → 400
async def test_credit_round_rejects_more_than_100_students(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    account = await _insert_account(db_pool, room)

    too_many = client.post(
        _rounds_url(room),
        json=_payload(list(range(1, 102)), account_id=account),
        headers=admin_headers,
    )
    assert too_many.status_code == 400, too_many.text
    assert "100" in too_many.json()["detail"]

    duplicated = client.post(
        _rounds_url(room),
        json=_payload([admin_headers.student_id, admin_headers.student_id], account_id=account),
        headers=admin_headers,
    )
    assert duplicated.status_code == 400, duplicated.text
    assert "ซ้ำ" in duplicated.json()["detail"]

    empty = client.post(
        _rounds_url(room), json=_payload([], account_id=account), headers=admin_headers,
    )
    assert empty.status_code == 400, empty.text

    assert await _events(db_pool, room) == []


# ═══════════════════════ 9. ขอบเขตห้อง: 403 / 404
async def test_credit_round_room_scope_is_enforced(
    client, db_pool, admin_headers, finance_manager_headers,
):
    other_room = await _insert_room(db_pool, admin_headers.user_id)
    other_student = await _insert_student(db_pool, other_room, student_no=1)

    # เหรัญญิกของห้อง A ยิงเข้าห้อง B ⇒ ไม่มีสิทธิ์ในห้องนั้น
    forbidden = client.post(
        _rounds_url(admin_headers.room_id),
        json=_payload([admin_headers.student_id]),
        headers=finance_manager_headers,
    )
    assert forbidden.status_code == 403, forbidden.text

    # admin ของห้อง A อ้างนักเรียนของห้อง B ⇒ ไม่พบในห้อง ⇒ 404
    account = await _insert_account(db_pool, admin_headers.room_id)
    not_found = client.post(
        _rounds_url(admin_headers.room_id),
        json=_payload([other_student], account_id=account),
        headers=admin_headers,
    )
    assert not_found.status_code == 404, not_found.text

    assert await _events(db_pool, admin_headers.room_id) == []
    assert await _events(db_pool, other_room) == []


# ══════════════ 10. ล็อกห้องก่อนคำสั่งเขียน (เชิงโครงสร้าง)
async def test_credit_round_takes_room_lock_before_first_write():
    money_lock = _money_lock_tests()
    method = money_lock._resolve_method(
        "credit_rounds", "CreditRoundsMixin", "create_credit_round",
    )
    src = inspect.getsource(method)
    lines = src.splitlines()

    lock_at = money_lock._first_line_with(lines, "await _lock_room_money(")
    assert lock_at is not None, (
        "create_credit_round ต้องยึด advisory lock ของห้องเอง (contract อ่านซอร์สเมธอดนี้)"
    )
    for marker in ("INSERT INTO", "UPDATE ", "DELETE FROM"):
        write_at = money_lock._first_line_with(lines, marker)
        assert write_at is None or lock_at < write_at, (
            f"พบ '{marker}' ก่อนการยึดล็อกห้อง — ล็อกต้องเป็นอย่างแรกใน transaction"
        )
    rbac_at = money_lock._first_line_with(lines, "await require_permission(")
    assert rbac_at is not None and rbac_at < lock_at


# ══════════════ 11. ขึ้นทะเบียนใน _MONEY_PATHS
async def test_credit_round_is_registered_as_a_money_path():
    money_lock = _money_lock_tests()
    assert ("credit_rounds", "CreditRoundsMixin", "create_credit_round") in money_lock._MONEY_PATHS


# ══════════════ 12. ไม่เรียกเส้นทาง legacy `apply_credit`
async def test_credit_round_does_not_call_legacy_apply_credit(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=150.0)
    await _insert_credit(db_pool, room, s1, 150.0)

    async def _boom(*args, **kwargs):
        raise AssertionError("create_credit_round ต้องไม่เรียก apply_credit (เส้น legacy)")

    with patch.object(FinanceService, "apply_credit", new=_boom):
        resp = client.post(
            _rounds_url(room),
            json=_payload([s1], account_id=account),
            headers=admin_headers,
        )
    assert resp.status_code == 200, resp.text
    assert _money(resp.json()["events"][0]["total_applied"]) == "150.00"
