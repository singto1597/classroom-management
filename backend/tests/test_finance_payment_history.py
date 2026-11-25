"""📜 [FIN-V2 / P3.4] ประวัติการรับเงิน — event + การส่งมอบเงินสด (อ่านล้วน)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. ไทม์ไลน์รวม event + handover เรียงใหม่→เก่า
2. เอกสาร/bรรทัดโหลดแบบ batch และยอดตรงกับ DB
3. cursor 3 คีย์ `(occurred_at, kind, id)` ไม่ซ้ำ/ไม่ข้าม แม้เวลาเท่ากัน
4. ตัวกรองวันที่ใช้วันไทย (Asia/Bangkok) ไม่ใช่ UTC
5. รายการที่ยกเลิกยังแสดงพร้อมสถานะ
6. สมาชิกอ่านได้ · คนนอก 403 · cursor ผิดรูป 400
7. ไฟล์นี้ไม่แตะเส้นทางเงิน (ไม่มี `_lock_room_money` / `_MONEY_PATHS`)
"""
import inspect
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services.finance.payment_history import PaymentHistoryService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RECEIVER = "ครูสมศรี"
TZ_BKK = timezone(timedelta(hours=7))


# ═══════════════════════════════════════════════════════════════════ helpers
def _history_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-history"


def _events_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events"


def _payload(
    student_id: int, account_id: int, *, cash: str = "0.00",
    use_credit: bool = False, excess_action: str = "credit",
    bill_selection: str = "auto", bill_ids: list[int] | None = None,
    payer_name: str = "ผู้ปกครองทดสอบ", event_at: str | None = None,
) -> dict:
    body = {
        "idempotency_key": uuid.uuid4().hex,
        "student_id": student_id,
        "wallet_account_id": account_id,
        "payer_name": payer_name,
        "receiver_name": RECEIVER,
        "amount_received": cash,
        "use_credit": use_credit,
        "excess_action": excess_action,
        "bill_selection": bill_selection,
    }
    if bill_ids is not None:
        body["bill_ids"] = bill_ids
    if event_at is not None:
        body["event_at"] = event_at
    return body


async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, name,
        )


async def _insert_bill(pool, room_id: int, student_id: int, *, title: str = "ค่าเทอม",
                       amount: float = 1000.0) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, 'active', 'room_fund', 'project') RETURNING id""",
            room_id, title, amount,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', 0, 0) RETURNING id""",
            collection_id, student_id,
        )


async def _insert_person(pool, room_id: int, name: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_people (room_id, person_type, display_name)
               VALUES ($1, 'teacher', $2) RETURNING id""",
            room_id, name,
        )


async def _insert_custody_account(pool, room_id: int, name: str, owner_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts
                   (room_id, account_name, balance, account_kind, is_custody, owner_person_id)
               VALUES ($1, $2, 0, 'cash', TRUE, $3) RETURNING id""",
            room_id, name, owner_id,
        )


async def _insert_handover(
    pool, room_id: int, from_account: int, to_account: int, *,
    amount: float = 500.0, by_person: int | None = None,
    received_person: int | None = None, note: str | None = None,
    created_at: datetime | None = None, status: str = "active",
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_custody_handovers
                   (room_id, from_account_id, to_account_id, amount,
                    handed_over_by_person_id, received_by_person_id, note,
                    status, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, COALESCE($9, CURRENT_TIMESTAMP))
               RETURNING id""",
            room_id, from_account, to_account, amount, by_person,
            received_person, note, status, created_at,
        )


async def _user_headers(pool, *, room_owner_id: int) -> dict:
    """สร้าง user ใหม่ (ไม่ใช่สมาชิกของห้องทดสอบ) — ใช้อ้าง 403"""
    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO users (email, first_name, last_name, username, discord_id)
               VALUES (NULL, 'Out', 'Sider', $1, $2)""",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
    from core.config import settings
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


def _get(client, room_id: int, headers, **params):
    return client.get(_history_url(room_id), params=params, headers=headers)


# ══════════════════════════════════════════════════════════ 1. รวมสองแหล่ง
async def test_history_merges_events_and_handovers_in_desc_order(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=100.0)

    resp1 = client.post(
        _events_url(room),
        json=_payload(student, account, cash="100.00",
                      event_at="2026-11-20T09:00:00+07:00"),
        headers=admin_headers,
    )
    assert resp1.status_code == 200, resp1.text
    resp2 = client.post(
        _events_url(room),
        json=_payload(student, account, cash="100.00",
                      event_at="2026-11-20T10:00:00+07:00"),
        headers=admin_headers,
    )
    assert resp2.status_code == 200, resp2.text

    account_b = await _insert_account(db_pool, room, "กระเป๋าที่สอง")
    handover = await _insert_handover(
        db_pool, room, account, account_b,
        created_at=datetime(2026, 11, 20, 11, 0, tzinfo=TZ_BKK),
    )

    data = _get(client, room, admin_headers).json()
    assert len(data["items"]) == 3
    assert [it["kind"] for it in data["items"]] == ["handover", "event", "event"]
    times = [datetime.fromisoformat(it["occurred_at"]) for it in data["items"]]
    assert times == sorted(times, reverse=True)
    assert data["items"][0]["id"] == handover


# ══════════════════════════════════════════════════════ 2. บรรทัด + เอกสาร
async def test_history_event_includes_lines_and_documents(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, title="ค่าโครงการ", amount=700.0)

    cash_resp = client.post(
        _events_url(room), json=_payload(student, account, cash="700.00"),
        headers=admin_headers,
    )
    assert cash_resp.status_code == 200, cash_resp.text
    topup_resp = client.post(
        _events_url(room),
        json=_payload(student, account, cash="250.00", bill_selection="manual",
                      bill_ids=[], excess_action="credit"),
        headers=admin_headers,
    )
    assert topup_resp.status_code == 200, topup_resp.text
    topup_id = topup_resp.json()["event_id"]

    data = _get(client, room, admin_headers).json()
    by_id = {it["id"]: it for it in data["items"]}

    cash_item = by_id[cash_resp.json()["event_id"]]["event"]
    assert len(cash_item["lines"]) == 1
    assert cash_item["lines"][0]["line_kind"] == "bill"
    assert cash_item["lines"][0]["amount"] == 700.0
    assert cash_item["lines"][0]["collection_title"] == "ค่าโครงการ"
    assert [d["doc_type"] for d in cash_item["documents"]] == ["receipt"]
    assert cash_item["documents"][0]["receipt_no"].startswith("REC-")

    topup_item = by_id[topup_id]["event"]
    assert [ln["line_kind"] for ln in topup_item["lines"]] == ["credit_topup"]
    assert [d["doc_type"] for d in topup_item["documents"]] == ["deposit"]

    async with db_pool.acquire() as conn:
        db_line_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_payment_event_lines WHERE event_id = $1",
            topup_id,
        )
    assert db_line_count == 1


# ═════════════════════════════════════════════════ 3. handover ในไทม์ไลน์
async def test_history_handover_includes_account_and_people_names(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    owner = await _insert_person(db_pool, room, "ครูสมหญิง")
    receiver = await _insert_person(db_pool, room, "ครูสมชาย")
    custody = await _insert_custody_account(db_pool, room, "ครูสมหญิง (เงินสดรอส่งมอบ)", owner)
    main = await _insert_account(db_pool, room, "เงินสดห้อง")
    await _insert_handover(
        db_pool, room, custody, main, amount=1500.0,
        by_person=owner, received_person=receiver, note="ส่งรอบเช้า",
    )

    data = _get(client, room, admin_headers, kind="handover").json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["kind"] == "handover"
    assert item["event"] is None
    ho = item["handover"]
    assert ho["from_account_name"] == "ครูสมหญิง (เงินสดรอส่งมอบ)"
    assert ho["to_account_name"] == "เงินสดห้อง"
    assert ho["amount"] == 1500.0
    assert ho["handed_over_by_name"] == "ครูสมหญิง"
    assert ho["received_by_name"] == "ครูสมชาย"
    assert ho["note"] == "ส่งรอบเช้า"


# ═══════════════════════════════════════════════════════ 4. ตัวกรอง kind/student
async def test_history_filters_by_kind_and_student(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    account_b = await _insert_account(db_pool, room, "กระเป๋าที่สอง")
    await _insert_bill(db_pool, room, student, amount=100.0)
    client.post(_events_url(room), json=_payload(student, account, cash="100.00"),
                headers=admin_headers)
    await _insert_handover(db_pool, room, account, account_b, amount=50.0)

    only_events = _get(client, room, admin_headers, kind="event",
                       student_id=student).json()
    assert len(only_events["items"]) == 1
    assert only_events["items"][0]["kind"] == "event"

    only_handovers = _get(client, room, admin_headers, kind="handover").json()
    assert len(only_handovers["items"]) == 1
    assert only_handovers["items"][0]["kind"] == "handover"

    # student filter ตัด handover ออกแม้ kind=all
    by_student = _get(client, room, admin_headers, student_id=student).json()
    assert {it["kind"] for it in by_student["items"]} == {"event"}


# ═══════════════════════════════════════════════════════ 5. ตัวกรอง person
async def test_history_person_filter_matches_custody_owner(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    owner = await _insert_person(db_pool, room, "ครูสมหญิง")
    other = await _insert_person(db_pool, room, "ครูสมชาย")
    custody = await _insert_custody_account(db_pool, room, "ครูสมหญิง (ถือ)", owner)
    main = await _insert_account(db_pool, room, "เงินสดห้อง")
    await _insert_handover(db_pool, room, custody, main, amount=100.0, by_person=owner)
    await _insert_handover(db_pool, room, main, custody, amount=40.0, by_person=other)
    other_main = await _insert_account(db_pool, room, "กระเป๋าที่สาม")
    await _insert_handover(db_pool, room, main, other_main, amount=999.0)

    # "person" = ผู้ถือเงินที่เกี่ยวข้องกับ handover ฝั่งใดฝั่งหนึ่ง (from หรือ to)
    data = _get(client, room, admin_headers, kind="handover", person_id=owner).json()
    assert len(data["items"]) == 2
    assert {it["handover"]["amount"] for it in data["items"]} == {100.0, 40.0}
    assert all(it["handover"]["amount"] != 999.0 for it in data["items"])


# ═══════════════════════════════════════════════ 6. cursor ไม่ซ้ำ/ไม่ข้าม
async def test_history_cursor_pagination_has_no_duplicates_or_gaps(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    account = await _insert_account(db_pool, room)
    account_b = await _insert_account(db_pool, room, "กระเป๋าที่สอง")
    ids = [
        await _insert_handover(
            db_pool, room, account, account_b, amount=10.0 + i,
            created_at=datetime(2026, 11, 1, 10, i, tzinfo=TZ_BKK),
        )
        for i in range(5)
    ]

    collected: list[int] = []
    cursor = None
    pages = 0
    while True:
        params = {"kind": "handover", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        data = _get(client, room, admin_headers, **params).json()
        collected.extend(it["id"] for it in data["items"])
        pages += 1
        cursor = data["next_cursor"]
        if not cursor:
            break
        assert pages < 10

    assert pages == 3
    assert collected == ids[::-1]          # ใหม่ → เก่า
    assert len(set(collected)) == 5


# ═══════════════════════════════════════════ 7. เวลาเท่ากันก็ไม่ซ้ำ/ไม่ข้าม
async def test_history_cursor_stable_when_timestamps_equal(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    account = await _insert_account(db_pool, room)
    account_b = await _insert_account(db_pool, room, "กระเป๋าที่สอง")
    same = datetime(2026, 11, 2, 9, 0, tzinfo=TZ_BKK)
    ids = [
        await _insert_handover(db_pool, room, account, account_b,
                               amount=10.0 + i, created_at=same)
        for i in range(3)
    ]

    first = _get(client, room, admin_headers, kind="handover", limit=2).json()
    assert first["next_cursor"]
    second = _get(client, room, admin_headers, kind="handover", limit=2,
                  cursor=first["next_cursor"]).json()

    got = [it["id"] for it in first["items"]] + [it["id"] for it in second["items"]]
    assert got == sorted(ids, reverse=True)
    assert len(set(got)) == 3


# ═══════════════════════════════════════════════ 8. วันไทย ไม่ใช่ UTC
async def test_history_date_filter_uses_thai_day_boundaries(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=100.0)

    late_20th = client.post(
        _events_url(room),
        json=_payload(student, account, cash="100.00",
                      event_at="2026-11-20T16:30:00+00:00"),   # 23:30 ไทย 20
        headers=admin_headers,
    )
    assert late_20th.status_code == 200, late_20th.text
    early_21st = client.post(
        _events_url(room),
        json=_payload(student, account, cash="100.00",
                      event_at="2026-11-20T17:30:00+00:00"),   # 00:30 ไทย 21
        headers=admin_headers,
    )
    assert early_21st.status_code == 200, early_21st.text

    data = _get(client, room, admin_headers,
                **{"from": "2026-11-21", "to": "2026-11-21"}).json()
    ids = [it["id"] for it in data["items"]]
    assert ids == [early_21st.json()["event_id"]]

    data20 = _get(client, room, admin_headers,
                  **{"from": "2026-11-20", "to": "2026-11-20"}).json()
    assert [it["id"] for it in data20["items"]] == [late_20th.json()["event_id"]]


# ═════════════════════════════════════════════════ 9. รายการยกเลิกต้องเห็น
async def test_history_includes_voided_event_with_status(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    account = await _insert_account(db_pool, room)
    await _insert_bill(db_pool, room, student, amount=100.0)
    resp = client.post(_events_url(room), json=_payload(student, account, cash="100.00"),
                       headers=admin_headers)
    assert resp.status_code == 200, resp.text
    event_id = resp.json()["event_id"]

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE finance_payment_events SET status = 'voided' WHERE id = $1",
            event_id,
        )

    data = _get(client, room, admin_headers).json()
    item = next(it for it in data["items"] if it["id"] == event_id)
    assert item["status"] == "voided"


# ══════════════════════════════════════════ 10. สมาชิกอ่านได้ · คนนอก 403
async def test_history_member_can_read_but_outsider_gets_403(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    assert _get(client, room, admin_headers).status_code == 200

    outsider = await _user_headers(db_pool, room_owner_id=admin_headers.user_id)
    assert _get(client, room, outsider).status_code == 403


# ═══════════════════════════════════════════════════ 11. cursor ผิดรูป = 400
async def test_history_rejects_malformed_cursor_400(client, admin_headers):
    room = admin_headers.room_id
    assert _get(client, room, admin_headers, cursor="not-a-cursor").status_code == 400
    assert _get(client, room, admin_headers, kind="weird").status_code == 400
    assert _get(client, room, admin_headers, limit=0).status_code == 400
    assert _get(client, room, admin_headers, limit=101).status_code == 400


# ═══════════════════════════════════════════ 12. ไม่แตะเส้นทางเงิน/journal
async def test_history_does_not_touch_money_paths():
    source = inspect.getsource(PaymentHistoryService)
    assert "_lock_room_money" not in source
    assert "conn.transaction()" not in source
    assert not hasattr(PaymentHistoryService, "_insert_journal_entry")
