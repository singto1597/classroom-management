"""📊 รายงานอายุหนี้ + สรุปแดชบอร์ดค่าปรับ (Phase 5)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ขอบถังต้องไม่กำกวม** — overdue 1/30/31/60/61/90/91 วันต้องตกถังถูกตัว
   และบิลครบกำหนด *วันนี้* ต้องเป็น "ยังไม่ครบกำหนด" (overdue 0) ไม่ใช่ "ค้าง 1–30"
   (นี่คือบั๊กคลาสสิกของการใช้ `>` แทน `>=` ใน aging report)
2. **ไม่ระบุกำหนด ≠ ยังไม่ครบกำหนด** — ต้องแยกถัง (`no_due`) ไม่ปนกับ `not_due`
   ไม่งั้นตัวเลขถังแรกพองและผู้ใช้เข้าใจผิดว่าใกล้ครบกำหนด
3. **ยอดรวมต้องมาจากบิลเปิดตัวเดียวกับทั้งระบบ** — ใช้ `_open_bill_predicate()`
   ⇒ จ่ายแล้ว/soft-deleted/โปรเจกต์ถูกลบ ต้องหลุดออก; โปรเจกต์ที่ **ปิด** (`status='closed'`)
   ยังต้องนับ (ปิด = หยุดเพิ่มคน ไม่ใช่ล้างหนี้)
4. **แยกโปรเจกต์/ค่าปรับ** — ยอดและจำนวนต้องแยกสองกอง และ `fine_id` ต้องติดมา
   เพื่อให้ frontend ลิงก์ไป `/finance/fines/{id}` ได้ (ไม่พาไปหน้าโปรเจกต์ซ่อน)
5. **สรุปค่าปรับคำนวณฝั่ง backend** — ยอดค้าง/เลยกำหนด/ครบกำหนดใน 3 วัน/ตามประเภท/
   top ผู้ค้างชำระ ต้องตรงกับข้อมูลจริง และ **นักเรียนเห็นเฉพาะของตัวเอง**
6. **RBAC** — คนนอกห้องได้ 403 ไม่ใช่ลิสต์ว่าง (ลิสต์ว่างหลอกว่า "ไม่มีหนี้")
"""
import uuid
from datetime import date, timedelta

import pytest

from services.finance.constants import COLLECTION_KIND_FINE
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
AGING_PATH = API_PREFIX + "/{room}/finance/receivables/aging"
SUMMARY_PATH = API_PREFIX + "/{room}/finance/fines/summary"
FINES_PATH = API_PREFIX + "/{room}/finance/fines"
TYPES_PATH = API_PREFIX + "/{room}/finance/fine-types"

AS_OF = date(2026, 11, 24)


def _url(template: str, room_id: int, **kwargs) -> str:
    return template.format(room=room_id, **kwargs) + "?target_type=room"


def _key() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------- seeding

async def _insert_user(pool, first_name: str = "Kid") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "Test", f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_student(pool, room_id: int, *, student_no: int,
                          user_id=None, first_name="Kid") -> int:
    if user_id is None:
        user_id = await _insert_user(pool, first_name)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _insert_bill(pool, room_id: int, student_id: int, *, due: date | None,
                       amount: float = 100.0, paid: float = 0.0,
                       status: str = "pending", deleted: bool = False,
                       coll_deleted: bool = False,
                       coll_status: str = "active") -> tuple[int, int]:
    """สร้างโปรเจกต์เก็บเงิน + บิล 1 ใบ (due_date อยู่ที่ fee_collections)"""
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status, deleted_at)
               VALUES ($1, $2, $3, $4, $5, CASE WHEN $6 THEN NOW() ELSE NULL END) RETURNING id""",
            room_id, f"ค่าห้อง {uuid.uuid4().hex[:4]}", amount, due, coll_status, coll_deleted,
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, deleted_at)
               VALUES ($1, $2, $3, $4, CASE WHEN $5 THEN NOW() ELSE NULL END) RETURNING id""",
            collection_id, student_id, status, paid, deleted,
        )
    return collection_id, payment_id


async def _seed_fine_type(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        await FinanceService.ensure_default_fine_types(conn, room_id)
        return await conn.fetchval(
            """SELECT id FROM fine_types
               WHERE room_id = $1 AND deleted_at IS NULL ORDER BY sort_order, id LIMIT 1""",
            room_id,
        )


def _issue_fine(client, headers, *, type_id: int, student_id: int,
                amount: float = 20.0, incident: str = "2026-01-05",
                due: str | None = None):
    payload = {
        "fine_type_id": type_id,
        "students": [{"student_id": student_id, "amount": amount}],
        "incident_date": incident,
        "reason": "ทดสอบ aging",
        "idempotency_key": _key(),
        "user_name": "Tester",
    }
    if due is not None:
        payload["due_date"] = due
    return client.post(_url(FINES_PATH, headers.room_id), json=payload, headers=headers)


# ---------------------------------------------------------------- aging

async def test_aging_bucket_boundaries_and_no_due(client, db_pool, admin_headers):
    """ขอบถัง: 0/1/30/31/60/61/90/91 วัน + ไม่ระบุ + อนาคต"""
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id, student_no=90)

    # (due_date, bucket คาดหวัง, overdue คาดหวัง)
    cases = [
        (AS_OF, "not_due", 0),                        # ครบกำหนดวันนี้ = ยังไม่เลยกำหนด
        (AS_OF - timedelta(days=1), "1_30", 1),
        (AS_OF - timedelta(days=30), "1_30", 30),
        (AS_OF - timedelta(days=31), "31_60", 31),
        (AS_OF - timedelta(days=60), "31_60", 60),
        (AS_OF - timedelta(days=61), "61_90", 61),
        (AS_OF - timedelta(days=90), "61_90", 90),
        (AS_OF - timedelta(days=91), "over_90", 91),
        (None, "no_due", 0),
        (AS_OF + timedelta(days=10), "not_due", 0),
    ]
    expected_by_payment: dict[int, tuple[str, int]] = {}
    for due, bucket, overdue in cases:
        _, payment_id = await _insert_bill(db_pool, room_id, student_id, due=due, amount=100.0)
        expected_by_payment[payment_id] = (bucket, overdue)

    res = client.get(
        _url(AGING_PATH, room_id) + "&as_of=" + AS_OF.isoformat(), headers=admin_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["as_of"] == AS_OF.isoformat()
    actual = {r["payment_id"]: (r["bucket"], r["overdue_days"]) for r in body["rows"]}
    assert actual == expected_by_payment
    # การจัดเรียงสำหรับแสดงผล: due_date ขึ้นก่อน, ไม่ระบุกำหนดท้ายสุด
    due_dates = [r["due_date"] for r in body["rows"]]
    non_null = [d for d in due_dates if d is not None]
    assert non_null == sorted(non_null)
    assert due_dates[-1] is None

    buckets = {b["bucket"]: b for b in body["buckets"]}
    assert set(buckets) == {"no_due", "not_due", "1_30", "31_60", "61_90", "over_90"}
    # แต่ละบิล 100 บาท
    assert buckets["not_due"]["count"] == 2 and buckets["not_due"]["amount"] == 200.0
    assert buckets["1_30"]["count"] == 2 and buckets["1_30"]["amount"] == 200.0
    assert buckets["31_60"]["count"] == 2
    assert buckets["61_90"]["count"] == 2
    assert buckets["over_90"]["count"] == 1 and buckets["over_90"]["amount"] == 100.0
    assert buckets["no_due"]["count"] == 1 and buckets["no_due"]["amount"] == 100.0
    # ลำดับถังคงที่ตามที่ประกาศ (ใช้แสดงผล)
    assert [b["bucket"] for b in body["buckets"]] == [
        "no_due", "not_due", "1_30", "31_60", "61_90", "over_90",
    ]

    assert body["grand_total"] == 1000.0
    assert body["project_total"] == 1000.0
    assert body["fine_total"] == 0.0


async def test_aging_excludes_paid_voided_but_keeps_closed_projects(client, db_pool, admin_headers):
    """บิลเปิดเท่านั้น — จ่ายแล้ว/ลบแล้ว หลุด; โปรเจกต์ปิดยังนับ (ปิด ≠ ล้างหนี้)"""
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id, student_no=90)

    _, keep_id = await _insert_bill(db_pool, room_id, student_id, due=None, amount=500.0)
    _, closed_id = await _insert_bill(
        db_pool, room_id, student_id, due=None, amount=250.0, coll_status="closed"
    )
    await _insert_bill(db_pool, room_id, student_id, due=None, amount=999.0, paid=999.0)
    await _insert_bill(db_pool, room_id, student_id, due=None, amount=999.0, deleted=True)
    await _insert_bill(db_pool, room_id, student_id, due=None, amount=999.0, coll_deleted=True)
    await _insert_bill(
        db_pool, room_id, student_id, due=None, amount=999.0, status="confirmed"
    )

    res = client.get(
        _url(AGING_PATH, room_id) + "&as_of=" + AS_OF.isoformat(), headers=admin_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()
    returned = {r["payment_id"] for r in body["rows"]}
    assert returned == {keep_id, closed_id}
    assert body["grand_total"] == 750.0


async def test_aging_splits_project_and_fine_rows(client, db_pool, admin_headers):
    """ค่าปรับต้องแยกกอง มี fine_id ติดมา และยอดรวมไม่ปนกัน"""
    room_id = admin_headers.room_id
    type_id = await _seed_fine_type(db_pool, room_id)
    student_id = await _insert_student(db_pool, room_id, student_no=90)

    _, project_payment = await _insert_bill(
        db_pool, room_id, student_id, due=AS_OF - timedelta(days=5), amount=300.0
    )
    issued = _issue_fine(
        client, admin_headers, type_id=type_id, student_id=student_id,
        amount=20.0, due=(AS_OF - timedelta(days=40)).isoformat(),
    )
    assert issued.status_code == 200, issued.text
    fine_id = issued.json()["fines"][0]["id"]
    fine_payment = issued.json()["fines"][0]["student_payment_id"]

    res = client.get(
        _url(AGING_PATH, room_id) + "&as_of=" + AS_OF.isoformat(), headers=admin_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()

    rows = {r["payment_id"]: r for r in body["rows"]}
    assert rows[project_payment]["collection_kind"] == "project"
    assert rows[project_payment]["fine_id"] is None
    assert rows[fine_payment]["collection_kind"] == COLLECTION_KIND_FINE
    assert rows[fine_payment]["fine_id"] == fine_id
    assert rows[fine_payment]["bucket"] == "31_60"

    assert body["project_total"] == 300.0
    assert body["fine_total"] == 20.0
    assert body["grand_total"] == 320.0

    buckets = {b["bucket"]: b for b in body["buckets"]}
    assert buckets["1_30"]["project_amount"] == 300.0
    assert buckets["1_30"]["fine_amount"] == 0.0
    assert buckets["31_60"]["fine_amount"] == 20.0
    assert buckets["31_60"]["project_amount"] == 0.0


async def test_aging_requires_membership(client, db_pool, admin_headers, member_headers):
    """คนนอกห้องได้ 403 ไม่ใช่ลิสต์ว่าง"""
    res = client.get(_url(AGING_PATH, admin_headers.room_id), headers=member_headers)
    assert res.status_code == 403, res.text


# ---------------------------------------------------------------- fine summary

async def test_fine_summary_totals_types_and_top_debtors(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    type_id = await _seed_fine_type(db_pool, room_id)
    s1 = await _insert_student(db_pool, room_id, student_no=90, first_name="ก้อง")
    s2 = await _insert_student(db_pool, room_id, student_no=91, first_name="บีม")

    r1 = _issue_fine(client, admin_headers, type_id=type_id, student_id=s1, amount=20.0)
    r2 = _issue_fine(client, admin_headers, type_id=type_id, student_id=s2, amount=40.0)
    assert r1.status_code == 200 and r2.status_code == 200

    # ชำระบางส่วน 30 บาทของใบที่ 2 (ตรงกับที่ระบบจริงทำกับ paid_amount)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET paid_amount = 30.0 WHERE id = $1",
            r2.json()["fines"][0]["student_payment_id"],
        )

    res = client.get(
        _url(SUMMARY_PATH, room_id) + "&as_of=" + AS_OF.isoformat(), headers=admin_headers
    )
    assert res.status_code == 200, res.text
    body = res.json()

    totals = body["totals"]
    assert totals["count"] == 2
    assert totals["original_total"] == 60.0
    assert totals["outstanding_total"] == 30.0   # 20 + (40 - 30)
    assert totals["paid_total"] == 30.0
    assert totals["waived_total"] == 0.0
    assert totals["refunded_total"] == 0.0

    by_status = {r["status"]: r for r in body["by_status"]}
    assert by_status["issued"]["count"] == 2
    assert by_status["issued"]["outstanding"] == 30.0

    assert len(body["by_type"]) == 1
    assert body["by_type"][0]["count"] == 2
    assert body["by_type"][0]["amount"] == 60.0
    assert body["by_type"][0]["outstanding"] == 30.0

    top = body["top_debtors"]
    assert [d["student_id"] for d in top] == [s1, s2]   # 20 > 10
    assert [d["outstanding"] for d in top] == [20.0, 10.0]


async def test_fine_summary_overdue_and_due_soon(client, db_pool, admin_headers):
    """เลยกำหนด / ครบใน 3 วัน นับเฉพาะใบที่ยังมียอดค้าง"""
    room_id = admin_headers.room_id
    type_id = await _seed_fine_type(db_pool, room_id)
    overdue_s = await _insert_student(db_pool, room_id, student_no=90, first_name="เลย")
    soon_s = await _insert_student(db_pool, room_id, student_no=91, first_name="ใกล้")
    far_s = await _insert_student(db_pool, room_id, student_no=92, first_name="ไกล")

    assert _issue_fine(client, admin_headers, type_id=type_id, student_id=overdue_s,
                       amount=20.0, due="2026-11-10").status_code == 200
    assert _issue_fine(client, admin_headers, type_id=type_id, student_id=soon_s,
                       amount=25.0, due="2026-11-26").status_code == 200       # +2 วัน
    assert _issue_fine(client, admin_headers, type_id=type_id, student_id=far_s,
                       amount=30.0, due="2026-12-30").status_code == 200

    res = client.get(
        _url(SUMMARY_PATH, room_id) + "&as_of=" + AS_OF.isoformat(), headers=admin_headers
    )
    assert res.status_code == 200, res.text
    totals = res.json()["totals"]
    assert totals["overdue_count"] == 1 and totals["overdue_amount"] == 20.0
    assert totals["due_soon_count"] == 1 and totals["due_soon_amount"] == 25.0


async def test_fine_summary_student_sees_only_own_fines(client, db_pool, admin_headers, member_headers):
    """นักเรียนที่ผูกกับห้องเห็นเฉพาะค่าปรับของตัวเอง (เหมือน list_fines)"""
    room_id = admin_headers.room_id
    type_id = await _seed_fine_type(db_pool, room_id)

    # ผูกผู้ใช้ของ member_headers เข้าเป็นนักเรียนของห้อง admin ด้วย
    mine = await _insert_student(
        db_pool, room_id, student_no=95, user_id=member_headers.user_id, first_name="自分の"
    )
    other = await _insert_student(db_pool, room_id, student_no=96, first_name="คนอื่น")

    assert _issue_fine(client, admin_headers, type_id=type_id, student_id=mine,
                       amount=20.0).status_code == 200
    assert _issue_fine(client, admin_headers, type_id=type_id, student_id=other,
                       amount=40.0).status_code == 200

    admin_view = client.get(_url(SUMMARY_PATH, room_id), headers=admin_headers).json()
    assert admin_view["totals"]["count"] == 2
    assert len(admin_view["top_debtors"]) == 2

    student_view = client.get(_url(SUMMARY_PATH, room_id), headers=member_headers).json()
    assert student_view["totals"]["count"] == 1
    assert student_view["totals"]["outstanding_total"] == 20.0
    assert [d["student_id"] for d in student_view["top_debtors"]] == [mine]


async def test_fine_summary_requires_membership(client, admin_headers, member_headers):
    res = client.get(_url(SUMMARY_PATH, admin_headers.room_id), headers=member_headers)
    assert res.status_code == 403, res.text
