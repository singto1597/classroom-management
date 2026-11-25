"""👤 [FIN-V2 / P1.3] บัญชีรายบุคคล + statement

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **สูตรยอดค้างเดียวกับทั้งระบบ** — `amount - paid - written_off` ต่อบิล
   (ถ้าใครเผลอแก้สูตรที่จุดเดียว ยอดจะไม่ตรงกับผู้ค้างชำระ/AR)
2. **Written-off ถูกหักจริง** (P1.1 เพิ่มคอลัมน์ ยังไม่มีใครเขียน — API อ่านต้องถูก)
3. **เส้นแบ่ง overdue ใช้วันไทย** — `due_date < วันนี้ (Asia/Bangkok)` เท่านั้น
   (วันครบกำหนดวันนี้ = `upcoming` ไม่ใช่ overdue)
4. **เครดิตใช้ `balance_after` แถวล่าสุด ไม่ใช่ SUM** — SUM เพี้ยนเมื่อมี reverse
5. **ตัวกรอง status/fund_type** ทำงานและไม่ทำให้ยอดรวมผิด
6. **บิลเปิดเรียง `due_date NULLS LAST, id`**
7. **statement กรองช่วงวันที่ + เรียงจากเก่าไปใหม่ + เครื่องหมายถูก**
8. **กันข้ามห้อง** — นักเรียนห้องอื่น = 404, ยิง URL ห้องอื่น = 403
9. **สมาชิกธรรมดาอ่านได้** (read transparency) — ไม่ต้อง MANAGE_FINANCE

⚠️ ทุกอย่างยืนยันกับ Postgres จริงผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


def _accounts_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/individual-accounts"


def _detail_url(room_id: int, student_id: int) -> str:
    return f"{_accounts_url(room_id)}/{student_id}"


def _statement_url(room_id: int, student_id: int) -> str:
    return f"{_detail_url(room_id, student_id)}/statement"


# ═══════════════════════════════════════════════════════════════════ helpers
async def _insert_student(pool, room_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no,
        )


async def _insert_bill(
    pool, room_id: int, student_id: int, *,
    title: str = "ค่าเทอม", amount: float = 1000.0,
    due_date: date | None = None,
    paid: float = 0.0, written_off: float = 0.0,
    fund_type: str = "room_fund", collection_kind: str = "project",
) -> int:
    """สร้างบิล 1 ใบ (ยังไม่ลง journal — ใส่แยกในเทสต์ statement)"""
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, $4, 'active', $5, $6) RETURNING id""",
            room_id, title, amount, due_date, fund_type, collection_kind,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', $3, $4) RETURNING id""",
            collection_id, student_id, paid, written_off,
        )


async def _insert_credit(
    pool, room_id: int, student_id: int, entry_type: str,
    amount: float, balance_after: float, *, created_at: datetime | None = None,
) -> int:
    """สร้างแถว `student_credits` — `amount` บวกเสมอ ทิศทางมาจาก entry_type"""
    async with pool.acquire() as conn:
        if created_at is None:
            return await conn.fetchval(
                """INSERT INTO student_credits
                       (room_id, student_id, entry_type, amount, balance_after)
                   VALUES ($1, $2, $3, $4, $5) RETURNING id""",
                room_id, student_id, entry_type, amount, balance_after,
            )
        return await conn.fetchval(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after, created_at)
               VALUES ($1, $2, $3, $4, $5, $6::timestamptz) RETURNING id""",
            room_id, student_id, entry_type, amount, balance_after, created_at,
        )


async def _insert_bill_journal(pool, room_id: int, payment_id: int, when: datetime) -> None:
    """journal 'ออกบิล' — statement ใช้วันนี้เป็น anchored time ของบรรทัดบิล"""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO journal_entries
                   (room_id, reference_type, reference_id, description, status, transaction_date)
               VALUES ($1, 'student_payment_issue', $2, 'ออกบิลทดสอบ', 'posted', $3::timestamptz)""",
            room_id, str(payment_id), when,
        )


async def _insert_legacy_payment(
    pool, room_id: int, payment_id: int, amount: float, when_utc: datetime,
) -> int:
    """แถว `finance_transactions` แบบ legacy (ไม่มี payment_event_id)"""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_transactions
                   (room_id, amount, description, student_payment_id, created_at)
               VALUES ($1, $2, 'รับเงินทดสอบ', $3, $4::timestamp) RETURNING id""",
            room_id, amount, payment_id, when_utc,
        )


async def _thai_today(pool) -> date:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT (NOW() AT TIME ZONE 'Asia/Bangkok')::date")


def _item(body: dict, student_id: int) -> dict:
    matches = [i for i in body["items"] if i["student_id"] == student_id]
    assert matches, f"ไม่พบนักเรียน {student_id} ในผลลัพธ์"
    return matches[0]


# ═══════════════════════════════════════════════════════════════ 1. ยอดรวม/เครดิต
async def test_list_returns_outstanding_and_credit_per_student(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    first = admin_headers.student_id
    second = await _insert_student(db_pool, room_id, student_no=2)

    await _insert_bill(db_pool, room_id, first, amount=1000.0, paid=300.0)
    await _insert_bill(db_pool, room_id, second, amount=500.0)
    await _insert_credit(db_pool, room_id, second, "topup", 200.0, 200.0)

    res = client.get(_accounts_url(room_id), headers=admin_headers)
    assert res.status_code == 200, res.text

    body = res.json()
    a = _item(body, first)
    b = _item(body, second)

    assert a["outstanding_total"] == "700.00"
    assert a["credit_balance"] == "0.00"
    assert a["ready_to_apply"] == "0.00"
    assert b["outstanding_total"] == "500.00"
    assert b["credit_balance"] == "200.00"
    assert b["ready_to_apply"] == "200.00"
    assert body["as_of"] == str(await _thai_today(db_pool))


# ═══════════════════════════════════════════════════════════ 2. written-off
async def test_outstanding_subtracts_written_off_amount(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    await _insert_bill(db_pool, room_id, student, amount=1000.0, paid=200.0, written_off=100.0)

    res = client.get(_detail_url(room_id, student), headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["outstanding_total"] == "700.00"
    bill = body["open_bills"][0]
    assert bill["written_off_amount"] == "100.00"
    assert bill["outstanding"] == "700.00"


# ═══════════════════════════════════════════════════════════ 3. overdue boundary
@pytest.mark.parametrize("offset_days, expect_overdue", [
    (-1, True),   # เมื่อวาน → overdue
    (0, False),   # ครบกำหนดวันนี้ → ยังไม่ overdue
    (1, False),
])
async def test_overdue_boundary_uses_thai_today(
    client, db_pool, admin_headers, offset_days, expect_overdue
):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    today = await _thai_today(db_pool)
    due = date.fromordinal(today.toordinal() + offset_days)
    await _insert_bill(db_pool, room_id, student, amount=1000.0, due_date=due)

    body = client.get(_detail_url(room_id, student), headers=admin_headers).json()
    if expect_overdue:
        assert body["overdue_total"] == "1000.00"
        assert body["upcoming_total"] == "0.00"
    else:
        assert body["overdue_total"] == "0.00"
        assert body["upcoming_total"] == "1000.00"


# ═══════════════════════════════════════ 4. credit = latest balance_after (ไม่ใช่ SUM)
async def test_credit_balance_uses_latest_balance_after(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id

    await _insert_credit(db_pool, room_id, student, "topup", 200.0, 200.0)
    await _insert_credit(db_pool, room_id, student, "apply", 50.0, 150.0)

    body = client.get(_detail_url(room_id, student), headers=admin_headers).json()
    # SUM(amount) = 250 ≠ 150 ⇒ ตัวเลขนี้พิสูจน์ว่าใช้แถวล่าสุดจริง
    assert body["credit_balance"] == "150.00"


# ═══════════════════════════════════════════════════════════════ 5. status filter
async def test_status_filters(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    owing = admin_headers.student_id
    credited = await _insert_student(db_pool, room_id, student_no=2)
    settled = await _insert_student(db_pool, room_id, student_no=3)

    await _insert_bill(db_pool, room_id, owing, amount=100.0)
    await _insert_credit(db_pool, room_id, credited, "topup", 50.0, 50.0)

    def ids(status: str) -> set[int]:
        res = client.get(
            _accounts_url(room_id), params={"status": status}, headers=admin_headers
        )
        assert res.status_code == 200, res.text
        return {i["student_id"] for i in res.json()["items"]}

    assert ids("outstanding") == {owing}
    assert ids("credit") == {credited}
    assert ids("settled") == {settled}
    assert ids("all") == {owing, credited, settled}

    bad = client.get(_accounts_url(room_id), params={"status": "weird"}, headers=admin_headers)
    assert bad.status_code == 400


# ══════════════════════════════════════════════════════════ 6. fund_type filter
async def test_fund_type_filter_excludes_other_bills(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    await _insert_bill(db_pool, room_id, student, title="เงินห้อง", amount=100.0,
                       fund_type="room_fund")
    await _insert_bill(db_pool, room_id, student, title="เก็บแทน", amount=200.0,
                       fund_type="pass_through")

    body = client.get(
        _detail_url(room_id, student), headers=admin_headers
    ).json()
    # detail ไม่มีตัวกรอง fund_type — ต้องเห็นทั้งสองใบ
    assert len(body["open_bills"]) == 2

    filtered = client.get(
        _accounts_url(room_id), params={"fund_type": "room_fund"}, headers=admin_headers
    ).json()
    row = _item(filtered, student)
    assert len(row["open_bills"]) == 1
    assert row["open_bills"][0]["title"] == "เงินห้อง"
    assert row["outstanding_total"] == "100.00"

    bad = client.get(
        _accounts_url(room_id), params={"fund_type": "nope"}, headers=admin_headers
    )
    assert bad.status_code == 400


# ═══════════════════════════════════════════════════ 7. bill ordering
async def test_detail_returns_open_bills_sorted_by_due_date(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    # สร้างจากหลังไปหน้า เพื่อให้ id ไม่ตรงกับลำดับ due_date
    await _insert_bill(db_pool, room_id, student, title="ไม่กำหนด", amount=10.0, due_date=None)
    await _insert_bill(db_pool, room_id, student, title="ทีหลัง", amount=20.0,
                       due_date=date(2027, 3, 1))
    await _insert_bill(db_pool, room_id, student, title="ก่อน", amount=30.0,
                       due_date=date(2026, 12, 1))

    body = client.get(_detail_url(room_id, student), headers=admin_headers).json()
    titles = [b["title"] for b in body["open_bills"]]
    assert titles == ["ก่อน", "ทีหลัง", "ไม่กำหนด"]


# ═══════════════════════════════════════════════════ 8. statement range/order
async def test_statement_date_range_and_ordering(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    payment_id = await _insert_bill(db_pool, room_id, student, amount=1000.0)

    await _insert_bill_journal(db_pool, room_id, payment_id, datetime(2026, 1, 10, 9, 0, tzinfo=timezone(timedelta(hours=7))))
    await _insert_legacy_payment(db_pool, room_id, payment_id, 300.0, datetime(2026, 1, 12, 2, 0))
    await _insert_credit(db_pool, room_id, student, "topup", 100.0, 100.0,
                         created_at=datetime(2026, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=7))))

    # ── ทั้งช่วง: บิล → รับเงิน → เครดิต (เรียงตามเวลา) ──
    full = client.get(_statement_url(room_id, student), headers=admin_headers)
    assert full.status_code == 200, full.text
    entries = full.json()["entries"]
    assert [e["kind"] for e in entries] == ["bill", "payment", "credit_topup"]
    assert entries[0]["amount"] == "1000.00"
    assert entries[1]["amount"] == "-300.00"
    assert entries[2]["amount"] == "100.00"
    assert entries[2]["balance_after"] == "100.00"
    assert full.json()["documents"] == []

    # ── กรอง 11–16 ม.ค.: บิลหลุด รับเงิน+เครดิตอยู่ ──
    ranged = client.get(
        _statement_url(room_id, student),
        params={"from": "2026-01-11", "to": "2026-01-16"},
        headers=admin_headers,
    )
    assert ranged.status_code == 200, ranged.text
    kinds = [e["kind"] for e in ranged.json()["entries"]]
    assert kinds == ["payment", "credit_topup"]

    # ── ช่วงกลับด้าน = 400 ──
    bad = client.get(
        _statement_url(room_id, student),
        params={"from": "2026-01-20", "to": "2026-01-01"},
        headers=admin_headers,
    )
    assert bad.status_code == 400


# ═══════════════════════════════════════════════════════ 9/11. cross-room + RBAC
async def test_student_from_other_room_is_404(client, db_pool, admin_headers):
    async with db_pool.acquire() as conn:
        other_room = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('ห้องอื่น', 'OTHRM1', NULL) RETURNING id"
        )
    other_student = await _insert_student(db_pool, other_room, student_no=1)

    res = client.get(_detail_url(admin_headers.room_id, other_student), headers=admin_headers)
    assert res.status_code == 404

    res2 = client.get(
        _statement_url(admin_headers.room_id, other_student), headers=admin_headers
    )
    assert res2.status_code == 404


async def test_member_can_read_but_outsider_cannot(client, member_headers, admin_headers):
    # สมาชิกห้องตัวเองอ่านได้ (ไม่ต้อง MANAGE_FINANCE)
    own = client.get(_accounts_url(member_headers.room_id), headers=member_headers)
    assert own.status_code == 200

    # ยิง URL ของห้องที่ไม่ได้เป็นสมาชิก → 403
    foreign = client.get(_accounts_url(member_headers.room_id), headers=admin_headers)
    assert foreign.status_code == 403
