"""🧾 เรียกเก็บเงินเองรายบุคคล — ยอดต่างกันต่อคนในคำขอเดียว (Phase 6.5)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 รายการ = 1 แคมเปญซ่อนรายคน (kind='project')** — ยอดของบิลต้องเท่ายอดที่ครู
   ระบุให้คนนั้น เพื่อให้ทุก query AR เดิม (`FC.amount - paid_amount`) ถูกต้อง
2. **ลงบัญชีคงค้างครบ** — Dr 11001 ผู้ค้างชำระค่าโครงการ รวมเท่ายอดทั้งคำขอ
3. **กดซ้ำคีย์เดิม = ผลเดิม** — ไม่มีแคมเปญ/บิล/แจ้งเตือน/journl เพิ่มแม้แต่แถวเดียว
4. **all-or-nothing + สิทธิ์** — นักเรียนนอกห้อง ⇒ 400 และไม่มีอะไรถูกเขียน ·
   ไม่มี `MANAGE_FINANCE` ⇒ 403
5. **แจ้งเตือนในแอปถึงเจ้าของบิล** (ถ้าผูกบัญชี) ชี้ `/finance/my-debts`
"""
import random
import uuid

import pytest

from services.finance.constants import AR_PROJECT_CODE, COLLECTION_KIND_PROJECT

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
PATH = API_PREFIX + "/{room}/finance/custom-charges"


def _url(room_id: int) -> str:
    return PATH.format(room=room_id) + "?target_type=room"


def _key() -> str:
    return uuid.uuid4().hex


async def _make_student(pool, room_id: int, *, student_no: int | None = None) -> int:
    student_no = student_no if student_no is not None else random.randint(100, 9999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            "Kid", "Test", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


def _body(items, *, key=None, title="ค่าหนังสือที่เหลือ", due="2026-12-01"):
    return {
        "title": title,
        "due_date": due,
        "items": items,
        "idempotency_key": key or _key(),
        "user_name": "Tester",
    }


async def _count(pool, room_id: int, table: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE room_id = $1", room_id)


async def test_creates_one_collection_per_student_with_own_amount(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    a = await _make_student(db_pool, room_id, student_no=random.randint(100, 9999))
    b = await _make_student(db_pool, room_id, student_no=random.randint(100, 9999))

    resp = client.post(
        _url(room_id),
        json=_body([
            {"student_id": a, "amount": 150.0, "note": "เล่ม 1-3"},
            {"student_id": b, "amount": 100.0},
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["created"] is True
    assert round(data["total_amount"], 2) == 250.0
    assert len(data["collections"]) == 2

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT FC.id, FC.title, FC.amount, FC.collection_kind, FC.idempotency_key,
                      SP.status AS bill_status
               FROM fee_collections FC
               JOIN student_payments SP ON SP.collection_id = FC.id
               WHERE FC.room_id = $1 AND FC.deleted_at IS NULL
               ORDER BY FC.id""",
            room_id,
        )
        ar_debit = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_code = $2
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id, AR_PROJECT_CODE,
        )

    assert len(rows) == 2
    assert {float(r["amount"]) for r in rows} == {150.0, 100.0}
    assert all(r["collection_kind"] == COLLECTION_KIND_PROJECT for r in rows)
    assert all(r["bill_status"] == "pending" for r in rows)
    assert all(r["idempotency_key"] for r in rows)
    assert any("เล่ม 1-3" in r["title"] for r in rows)
    assert round(float(ar_debit), 2) == 250.0


async def test_duplicate_items_for_same_student_are_merged(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _make_student(db_pool, room_id, student_no=random.randint(100, 9999))

    resp = client.post(
        _url(room_id),
        json=_body([
            {"student_id": sid, "amount": 20.0},
            {"student_id": sid, "amount": 30.0},
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["collections"]) == 1

    async with db_pool.acquire() as conn:
        amount = await conn.fetchval(
            "SELECT amount FROM fee_collections WHERE room_id = $1 AND deleted_at IS NULL",
            room_id,
        )
    assert float(amount) == 50.0


async def test_same_idempotency_key_does_not_create_twice(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _make_student(db_pool, room_id, student_no=random.randint(100, 9999))
    key = _key()
    body = _body([{"student_id": sid, "amount": 42.0}], key=key)

    first = client.post(_url(room_id), json=body, headers=admin_headers)
    second = client.post(_url(room_id), json=body, headers=admin_headers)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert second.json()["collections"][0]["reused"] is True
    assert await _count(db_pool, room_id, "fee_collections") == 1
    async with db_pool.acquire() as conn:
        bills = await conn.fetchval(
            """SELECT COUNT(*) FROM student_payments SP
               JOIN fee_collections FC ON FC.id = SP.collection_id
               WHERE FC.room_id = $1""",
            room_id,
        )
    assert bills == 1

    async with db_pool.acquire() as conn:
        notes = await conn.fetchval(
            "SELECT COUNT(*) FROM notifications WHERE room_id = $1 AND type = 'collection_created'",
            room_id,
        )
    assert notes == 1


async def test_student_from_another_room_rejects_whole_request(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    async with db_pool.acquire() as conn:
        other_room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, server_id) VALUES ($1, $2) RETURNING id",
            f"room-{uuid.uuid4().hex[:6]}", random.randint(1_000_000, 9_999_999),
        )
    mine = await _make_student(db_pool, room_id, student_no=random.randint(100, 9999))
    alien = await _make_student(db_pool, other_room_id, student_no=random.randint(100, 9999))

    resp = client.post(
        _url(room_id),
        json=_body([
            {"student_id": mine, "amount": 10.0},
            {"student_id": alien, "amount": 10.0},
        ]),
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert await _count(db_pool, room_id, "fee_collections") == 0


async def test_requires_manage_finance(client, db_pool, member_headers):
    room_id = member_headers.room_id
    sid = await _make_student(db_pool, room_id, student_no=random.randint(100, 9999))

    resp = client.post(
        _url(room_id),
        json=_body([{"student_id": sid, "amount": 10.0}]),
        headers=member_headers,
    )
    assert resp.status_code == 403
    assert await _count(db_pool, room_id, "fee_collections") == 0
