"""📥 [FIN-V2 / P2.7] รับเงินหลายคนในรอบเดียว (bulk receive)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 คำขอ = 1 transaction = all-or-nothing** — ถ้าคนใดล้ม ไม่มี event/REC/DEP/
   transaction/journal/เลขใบเสร็จของใครค้างเลย (sequence ต้องไม่ขยับ)
2. **1 นักเรียน = 1 event + REC/DEP ของตัวเอง** (ไม่ยุบข้ามคน) และ
   event ทุกรายการใช้ `reference_no` + `event_at` เดียวกัน (ปี พ.ศ. เดียวกัน)
3. **idempotency ของ bulk** — คีย์อนุพันธ์ `{key[:48]}:{student_id}`; replay คืนผลเดิม
   `reused=true` ไม่ write และ **ไม่ notify** · reference ซ้ำคนละคีย์ → 409
4. **notify ครั้งเดียวหลัง commit** — ไม่ใช่ N ข้อความ และไม่ใช่เงินปลอมตอน rollback
5. **เครดิตไม่ใช่เงินสด** — event ที่ใช้เครดิตล้วนไม่มี REC/ไม่มี transaction เงินสด
6. **RBAC + shared validation** — MANAGE_FINANCE, กระเป๋าห้องเดียวกัน, นักเรียนในห้อง

⚠️ เงินทุกก้อน assert เป็นสตริง 2 ตำแหน่ง; อ่านกลับจาก Postgres ตรง ๆ ผ่าน `db_pool`
"""
import json
import random
import string
import uuid

import pytest
from unittest.mock import AsyncMock, patch

from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RECEIVER = "ครูสมศรี"


# ═══════════════════════════════════════════════════════════════════ helpers
def _bulk_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events/bulk"


def _new_key() -> str:
    return uuid.uuid4().hex


def _money(value) -> str:
    return f"{float(value):.2f}"


def _item(
    student_id: int, cash: str = "0.00", *,
    use_credit: bool = False, excess_action: str = "none",
    note: str | None = None,
) -> dict:
    body = {
        "student_id": student_id,
        "amount_received": cash,
        "use_credit": use_credit,
        "excess_action": excess_action,
    }
    if note is not None:
        body["note"] = note
    return body


def _bulk_payload(
    account_id: int, items: list[dict], *, key: str | None = None,
    reference: str | None = None, receiver_name: str = RECEIVER,
    note: str | None = None, event_at: str | None = None,
    channel_id: int | None = None,
) -> dict:
    body = {
        "idempotency_key": key or _new_key(),
        "reference_no": reference or f"BULK-{uuid.uuid4().hex[:10]}",
        "wallet_account_id": account_id,
        "receiver_name": receiver_name,
        "items": items,
    }
    if note is not None:
        body["note"] = note
    if event_at is not None:
        body["event_at"] = event_at
    if channel_id is not None:
        body["channel_id"] = channel_id
    return body


async def _insert_student(pool, room_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no,
        )


async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, name,
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


async def _insert_credit(pool, room_id: int, student_id: int, amount: float) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after)
               VALUES ($1, $2, 'topup', $3, $3)""",
            room_id, student_id, amount,
        )


async def _events(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM finance_payment_events WHERE room_id = $1 ORDER BY id",
            room_id,
        )


async def _receipts(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM finance_receipts
               WHERE room_id = $1 AND doc_type = 'receipt' AND deleted_at IS NULL
               ORDER BY id""",
            room_id,
        )


async def _count(pool, sql: str, *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def _set_server(pool, room_id: int) -> int:
    server_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE rooms SET server_id = $1 WHERE id = $2", server_id, room_id
        )
    return server_id


# ══════════════════════════════════════ 1. N คน → N event + N REC (ของใครของมัน)
async def test_bulk_creates_one_event_and_receipt_per_student(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    bill1 = await _insert_bill(db_pool, room, s1, title="ค่าเทอม", amount=500.0)
    bill2 = await _insert_bill(db_pool, room, s2, title="ค่ากิจกรรม", amount=700.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "500.00"),
            _item(s2, "700.00"),
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["status"] == "success"
    assert data["reused"] is False
    assert data["total_amount_received"] == "1200.00"
    assert [e["student_id"] for e in data["events"]] == [s1, s2]
    assert all(e["event"]["reused"] is False for e in data["events"])
    assert data["events"][0]["event"]["amount_received"] == "500.00"
    assert data["events"][1]["event"]["amount_received"] == "700.00"

    events = await _events(db_pool, room)
    assert len(events) == 2
    receipts = await _receipts(db_pool, room)
    assert len(receipts) == 2
    assert {r["payment_event_id"] for r in receipts} == {e["id"] for e in events}

    # REC ของใครมี line_items ของบิลตัวเองคนเดียว
    by_sp = {}
    for rec in receipts:
        items = rec["line_items"]
        if isinstance(items, str):
            items = json.loads(items)
        by_sp[rec["payment_event_id"]] = {li["student_payment_id"] for li in items}
    event_by_student = {e["student_id"]: e["id"] for e in events}
    assert by_sp[event_by_student[s1]] == {bill1}
    assert by_sp[event_by_student[s2]] == {bill2}

    # transaction ต่อคนผูก payment_event_id ของตัวเอง
    for ev in events:
        tx = await _count(
            db_pool,
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1 AND payment_event_id = $2",
            room, ev["id"],
        )
        assert tx == 1

    async with db_pool.acquire() as conn:
        paid = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill2
        )
    assert paid["status"] == "paid"
    assert _money(paid["paid_amount"]) == "700.00"


# ══════════════════════════════════════════ 2. reference_no/event_at เดียวทั้งรอบ
async def test_bulk_sets_one_reference_no_and_one_event_at(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=100.0)
    await _insert_bill(db_pool, room, s2, amount=200.0)

    reference = f"BULK-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(
            account,
            [_item(s1, "100.00"), _item(s2, "200.00")],
            reference=reference,
        ),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reference_no"] == reference

    events = await _events(db_pool, room)
    assert {e["reference_no"] for e in events} == {reference}
    assert len({e["event_at"] for e in events}) == 1

    receipts = await _receipts(db_pool, room)
    assert len({r["year_be"] for r in receipts}) == 1


# ══════════════════════════════════ 3. all-or-nothing เมื่อ item ใดล้ม (ไม่มีบิล+none)
async def test_bulk_is_all_or_nothing_on_item_failure(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    # s2 ไม่มีบิล และไม่ยอมรับเงินเกิน ⇒ EXCESS_NOT_ALLOWED ตอน item ที่ 2
    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "500.00"),
            _item(s2, "100.00", excess_action="none"),
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["student_id"] == s2
    assert detail["item_code"] == "EXCESS_NOT_ALLOWED"

    assert await _events(db_pool, room) == []
    assert await _receipts(db_pool, room) == []
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room,
    ) == 0
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room,
    ) == 0
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1", room,
    ) == 0


# ═══════════════════════════ 4. เลขใบเสร็จต้องไม่ขยับเมื่อรอบล้มหลัง event แรกออก REC
async def test_bulk_rolls_back_numbering(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    await _insert_bill(db_pool, room, s2, amount=700.0)

    # ผูกกับ FinanceService (ไม่ใช่ mixin เดี่ยว) — core เรียก cls._display_name
    # ซึ่งอยู่บน MRO ของ FinanceService เท่านั้น
    original = FinanceService._commit_payment_event_locked
    calls = {"n": 0}

    async def flaky(conn, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("ทดสอบ: ล้มหลัง event แรกออก REC แล้ว")
        return await original(conn, **kwargs)

    with patch.object(FinanceService, "_commit_payment_event_locked", flaky):
        resp = client.post(
            _bulk_url(room),
            json=_bulk_payload(account, [
                _item(s1, "500.00"),
                _item(s2, "700.00"),
            ]),
            headers=admin_headers,
        )

    assert calls["n"] == 2
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["student_id"] == s2

    assert await _events(db_pool, room) == []
    assert await _receipts(db_pool, room) == []
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1", room,
    ) == 0


# ═════════════════════════════════════════════════════ 5. นักเรียนซ้ำ → 400 ก่อนเขียน
async def test_bulk_duplicate_student_rejected(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "500.00"),
            _item(s1, "500.00"),
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "DUPLICATE_STUDENT" in str(resp.json()["detail"])
    assert await _events(db_pool, room) == []


# ═══════════════════════════════════════ 6. replay คีย์/เลขอ้างอิงเดิม → ผลเดิม reused
async def test_bulk_replay_returns_same_events(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    await _insert_bill(db_pool, room, s2, amount=700.0)
    await _set_server(db_pool, room)

    payload = _bulk_payload(
        account, [_item(s1, "500.00"), _item(s2, "700.00")],
        key=_new_key(), reference=f"BULK-{uuid.uuid4().hex[:8]}",
    )
    with patch(
        "services.finance.bulk_receive.ActionService.notify_payments_confirmed",
        new_callable=AsyncMock,
    ) as notify:
        first = client.post(_bulk_url(room), json=payload, headers=admin_headers)
        second = client.post(_bulk_url(room), json=payload, headers=admin_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True

    first_events = {e["student_id"]: e["event"] for e in first.json()["events"]}
    second_events = {e["student_id"]: e["event"] for e in second.json()["events"]}
    assert first_events.keys() == second_events.keys()
    for sid in first_events:
        assert second_events[sid]["event_id"] == first_events[sid]["event_id"]
        assert second_events[sid]["receipt_no"] == first_events[sid]["receipt_no"]
        assert second_events[sid]["reused"] is True

    assert second.json()["total_amount_received"] == "1200.00"
    assert len(await _events(db_pool, room)) == 2
    assert len(await _receipts(db_pool, room)) == 2
    assert notify.await_count == 1


# ═══════════════════════════════ 7. reference เดิม + คีย์ใหม่ → 409 ไม่มี event เพิ่ม
async def test_bulk_reference_conflict_with_different_key(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)

    reference = f"BULK-{uuid.uuid4().hex[:8]}"
    first = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [_item(s1, "500.00")], reference=reference),
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [_item(s1, "500.00")], reference=reference),
        headers=admin_headers,
    )
    assert second.status_code == 409, second.text
    assert "REFERENCE_NO_CONFLICT" in str(second.json()["detail"])
    assert len(await _events(db_pool, room)) == 1


# ═════════════════════════════════════ 8. notify ครั้งเดียวพร้อม receipt_nos ครบ
async def test_bulk_notifies_once_with_all_receipts(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    await _insert_bill(db_pool, room, s2, amount=700.0)
    server_id = await _set_server(db_pool, room)

    with patch(
        "services.finance.bulk_receive.ActionService.notify_payments_confirmed",
        new_callable=AsyncMock,
    ) as notify:
        resp = client.post(
            _bulk_url(room),
            json=_bulk_payload(account, [
                _item(s1, "500.00"), _item(s2, "700.00"),
            ]),
            headers=admin_headers,
        )

    assert resp.status_code == 200, resp.text
    assert notify.await_count == 1
    kwargs = notify.await_args.kwargs
    assert kwargs["server_id"] == server_id
    assert kwargs["total_amount"] == 1200.0
    assert kwargs["payer_name"] == "นักเรียน 2 คน"
    assert sorted(kwargs["receipt_nos"]) == sorted(
        e["event"]["receipt_no"] for e in resp.json()["events"]
    )
    assert len(kwargs["receipt_nos"]) == 2
    assert sorted(item["amount"] for item in kwargs["items"]) == [500.0, 700.0]


# ═════════════════════════════════════════════════════ 9. replay ต้องไม่ notify ซ้ำ
async def test_bulk_does_not_notify_on_replay(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    await _set_server(db_pool, room)

    payload = _bulk_payload(account, [_item(s1, "500.00")])
    with patch(
        "services.finance.bulk_receive.ActionService.notify_payments_confirmed",
        new_callable=AsyncMock,
    ) as notify:
        first = client.post(_bulk_url(room), json=payload, headers=admin_headers)
        second = client.post(_bulk_url(room), json=payload, headers=admin_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert notify.await_count == 1


# ══════════════════════════════════════ 10. เครดิตล้วนในรอบ bulk → ไม่มี REC/เงินสด
async def test_bulk_credit_only_item_has_no_receipt(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    bill1 = await _insert_bill(db_pool, room, s1, amount=500.0)
    await _insert_bill(db_pool, room, s2, amount=700.0)
    await _insert_credit(db_pool, room, s1, 500.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "0.00", use_credit=True),
            _item(s2, "700.00"),
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    by_student = {e["student_id"]: e["event"] for e in data["events"]}

    credit_event = by_student[s1]
    assert credit_event["amount_received"] == "0.00"
    assert credit_event["credit_used"] == "500.00"
    assert credit_event["total_applied"] == "500.00"
    assert credit_event["receipt_no"] is None
    assert credit_event["deposit_no"] is None

    cash_event = by_student[s2]
    assert cash_event["receipt_no"] and cash_event["receipt_no"].startswith("REC-")

    async with db_pool.acquire() as conn:
        cash_tx = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_transactions
               WHERE room_id = $1 AND payment_event_id = $2""",
            room, credit_event["event_id"],
        )
        sp = await conn.fetchrow(
            "SELECT status, paid_amount FROM student_payments WHERE id = $1", bill1
        )
        dep = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_receipts
               WHERE payment_event_id = $1 AND doc_type = 'deposit'""",
            credit_event["event_id"],
        )
    assert cash_tx == 0
    assert dep == 0
    assert sp["status"] == "paid"
    assert _money(sp["paid_amount"]) == "500.00"

    # ทั้งรอบมี REC ใบเดียว (ของ s2)
    assert len(await _receipts(db_pool, room)) == 1


# ═════════════════════════════════════════════════════ 11. เงินสด + เครดิตผสม
async def test_bulk_mixed_cash_and_credit(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)
    await _insert_credit(db_pool, room, s1, 300.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "200.00", use_credit=True),
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    event = resp.json()["events"][0]["event"]

    assert event["amount_received"] == "200.00"
    assert event["credit_used"] == "300.00"
    assert event["total_applied"] == "500.00"
    assert event["credit_added"] == "0.00"
    assert event["receipt_no"].startswith("REC-")

    row = (await _events(db_pool, room))[0]
    assert (
        float(row["amount_received"]) + float(row["credit_used"])
        == float(row["total_applied"]) + float(row["credit_added"])
    )


# ═════════════════════════════════════ 12. ยอด 0 และไม่ใช้เครดิต → 400 ก่อนเขียน
async def test_bulk_rejects_zero_amount_without_credit(
    client, db_pool, admin_headers,
):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "0.00", use_credit=False),
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "INVALID_AMOUNT" in str(resp.json()["detail"])
    assert await _events(db_pool, room) == []


# ═══════════════════════════════════════════════ 13. RBAC — ต้อง MANAGE_FINANCE
async def test_bulk_requires_manage_finance(client, db_pool, member_headers):
    room, s1 = member_headers.room_id, member_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [_item(s1, "500.00")]),
        headers=member_headers,
    )
    assert resp.status_code == 403, resp.text
    assert await _events(db_pool, room) == []


# ══════════════════════════════════════════ 14. channel_id=null → snapshot ว่าง ไม่ error
async def test_bulk_channel_null_and_snapshot_empty(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [_item(s1, "500.00")]),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    event = (await _events(db_pool, room))[0]
    snapshot = event["channel_snapshot"]
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    assert snapshot == {}
    assert event["channel_id"] is None


# ═══════════════════════════════════════════════ 15. กระเป๋าห้องอื่น → 404 ก่อนเขียน
async def test_bulk_cross_room_wallet_rejected(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    await _insert_bill(db_pool, room, s1, amount=500.0)
    other_room = await _insert_room(db_pool, admin_headers.user_id)
    foreign_account = await _insert_account(db_pool, other_room)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(foreign_account, [_item(s1, "500.00")]),
        headers=admin_headers,
    )
    assert resp.status_code == 404, resp.text
    assert await _events(db_pool, room) == []


# ═══════════════════════════════════════════════════════════ 16. เกิน 100 คน → 422
async def test_bulk_max_100_items(client, db_pool, admin_headers):
    room = admin_headers.room_id
    account = await _insert_account(db_pool, room)
    items = [_item(1_000_000 + i, "1.00") for i in range(101)]

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, items),
        headers=admin_headers,
    )
    assert resp.status_code == 422, resp.text
    assert await _events(db_pool, room) == []


# ═══════════════════════════════ 17. error ของ item ต้องระบุ student_id + item_code
async def test_bulk_item_error_reports_student_id(client, db_pool, admin_headers):
    room, s1 = admin_headers.room_id, admin_headers.student_id
    s2 = await _insert_student(db_pool, room, student_no=2)
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, s1, amount=500.0)

    resp = client.post(
        _bulk_url(room),
        json=_bulk_payload(account, [
            _item(s1, "500.00"),
            _item(s2, "250.00", excess_action="none"),   # ไม่มีบิล ⇒ ล้ม
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["code"] == "BULK_ITEM_FAILED"
    assert detail["student_id"] == s2
    assert detail["item_code"] == "EXCESS_NOT_ALLOWED"
    assert detail["message"]

    # ไม่มีใครถูกบันทึก — ไม่ใช่แค่คนที่ล้ม
    assert await _events(db_pool, room) == []
