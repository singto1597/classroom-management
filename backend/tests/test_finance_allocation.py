"""🧮 [FIN-V2 / P1.5] เครื่องจัดสรรเงินรับ — pure engine + preview endpoint

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ผลลัพธ์ของ engine = สิ่งที่จอพรีวิวโชว์** — เทสต์ pure function ปิดพฤติกรรม
   ไว้ทุกเคส และมีเทสต์ parity ที่ยิง API จริงแล้วเทียบกับ `build_allocation_plan`
   (ถ้าวันหนึ่ง mixin กับ engine คำนวณคนละแบบ จะพังที่นี่ก่อนถึงมือครู)
2. **เงินสดก่อนเครดิต** — นโยบายที่เลือกต้องมี warning เมื่อเครดิตไม่ถูกใช้
3. **สตางค์จำนวนเต็ม** — 333.33 × 3 กับเงิน 1000.00 ต้องไม่เหลือหรือเกิน 1 สตางค์
4. **written_off_amount ถูกหักใน outstanding** — preview ต้องตรงกับ commit หลัง P6.2
5. **preview อ่านอย่างเดียว** — ไม่เขียน `finance_transactions` และไม่แตะ `paid_amount`
6. **MANAGE_FINANCE เท่านั้น** — สมาชิกทั่วไปได้ 403

⚠️ pure tests ไม่แตะ DB · 3 ตัวท้ายยิง HTTP จริง + ยืนยันกับ Postgres ผ่าน `db_pool`
"""
from datetime import date

import pytest

from services.finance.allocation import (
    AllocationError,
    assert_plan_equation,
    build_allocation_plan,
    from_satang,
    sort_open_bills,
    to_satang,
)

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


def _preview_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-events/preview"


# ═══════════════════════════════════════════════════════════════════ helpers
def _bill(
    payment_id: int,
    outstanding_baht: str,
    *,
    collection_id: int | None = None,
    title: str = "ค่าเทอม",
    due_date: date | None = None,
) -> dict:
    """บิลเปิด 1 ใบในรูปแบบที่ engine รับ — รับยอดเป็น **string** กัน float เพี้ยน"""
    return {
        "payment_id": payment_id,
        "collection_id": collection_id if collection_id is not None else payment_id,
        "title": title,
        "collection_kind": "project",
        "fund_type": "room_fund",
        "due_date": due_date,
        "outstanding_stang": to_satang(outstanding_baht),
    }


def _plan(bills, *, cash="0.00", credit="0.00", use_credit=False,
          excess_action="credit", bill_selection="auto", bill_ids=None):
    return build_allocation_plan(
        bills=bills,
        amount_received_stang=to_satang(cash),
        credit_available_stang=to_satang(credit),
        use_credit=use_credit,
        excess_action=excess_action,
        bill_selection=bill_selection,
        bill_ids=bill_ids,
    )


def _lines(plan):
    """(payment_id, source, amount_baht) ต่อบรรทัด — ใช้เทียบผลลัพธ์แบบอ่านง่าย"""
    return [
        (a["payment_id"], a["source"], from_satang(a["amount_stang"]))
        for a in plan["allocations"]
    ]


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
    due_date: date | None = None, paid: float = 0.0, written_off: float = 0.0,
) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, $4, 'active', 'room_fund', 'project') RETURNING id""",
            room_id, title, amount, due_date,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', $3, $4) RETURNING id""",
            collection_id, student_id, paid, written_off,
        )


async def _insert_credit(pool, room_id: int, student_id: int, amount: float) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO student_credits
                   (room_id, student_id, entry_type, amount, balance_after)
               VALUES ($1, $2, 'topup', $3, $3)""",
            room_id, student_id, amount,
        )


# ═════════════════════════════════════════════════════════════ 1. จ่ายเต็มจำนวน
async def test_case_full_payment():
    plan = _plan([_bill(1, "500.00"), _bill(2, "700.00")], cash="1200.00")

    assert _lines(plan) == [(1, "cash", 500.0), (2, "cash", 700.0)]
    assert plan["total_applied_stang"] == to_satang("1200.00")
    assert plan["credit_used_stang"] == 0
    assert plan["credit_added_stang"] == 0
    assert all(a["bill_after_stang"] == 0 for a in plan["allocations"])
    assert plan["warnings"] == []
    assert_plan_equation(plan)


# ═════════════════════════════════════════════════════════════ 2. จ่ายบางส่วน
async def test_case_partial_payment():
    plan = _plan([_bill(1, "500.00"), _bill(2, "700.00")], cash="600.00")

    assert _lines(plan) == [(1, "cash", 500.0), (2, "cash", 100.0)]
    assert plan["total_applied_stang"] == to_satang("600.00")
    assert "PARTIAL_PAYMENT" in plan["warnings"]
    # บิล 2 ยังเหลือ 600.00 — engine ต้องรายงานยอดหลังบรรทัดให้ P2.1 เขียน snapshot
    assert plan["allocations"][1]["bill_before_stang"] == to_satang("700.00")
    assert plan["allocations"][1]["bill_after_stang"] == to_satang("600.00")


# ═══════════════════════════════════════════ 3. เครดิตปิดบิลที่เงินสดไม่พอ
async def test_case_credit_closes_bill():
    plan = _plan(
        [_bill(1, "500.00")], cash="200.00", credit="300.00", use_credit=True
    )

    assert _lines(plan) == [(1, "cash", 200.0), (1, "credit", 300.0)]
    assert plan["total_applied_stang"] == to_satang("500.00")
    assert plan["credit_used_stang"] == to_satang("300.00")
    assert plan["credit_added_stang"] == 0
    assert plan["allocations"][1]["bill_before_stang"] == to_satang("300.00")
    assert plan["allocations"][1]["bill_after_stang"] == 0
    assert plan["warnings"] == []


# ═════════════════════════════════════════════════════════════ 4. เกิน → เครดิต
async def test_case_overpay_to_credit():
    plan = _plan([_bill(1, "500.00")], cash="1000.00")

    assert _lines(plan) == [(1, "cash", 500.0)]
    assert plan["total_applied_stang"] == to_satang("500.00")
    assert plan["credit_added_stang"] == to_satang("500.00")
    assert "EXCESS_TO_CREDIT" in plan["warnings"]
    assert_plan_equation(plan)


# ═══════════════════════════════════════════════ 5. เกิน + excess_action=none
async def test_case_overpay_none_raises():
    with pytest.raises(AllocationError) as exc:
        _plan([_bill(1, "500.00")], cash="1000.00", excess_action="none")

    assert exc.value.code == "EXCESS_NOT_ALLOWED"
    assert "500.00" in str(exc.value)


# ═══════════════════════════════════════════ 6. เงินสดก่อนเครดิต (นโยบาย)
async def test_credit_first_vs_cash_first_is_documented():
    # ── เงินสด 1000 ยังไม่พอ (ต้องใช้ 1200): เครดิตถูกใช้ปิดส่วนที่เหลือ ──
    used = _plan(
        [_bill(1, "500.00"), _bill(2, "700.00")],
        cash="1000.00", credit="200.00", use_credit=True,
    )
    assert _lines(used) == [
        (1, "cash", 500.0), (2, "cash", 500.0), (2, "credit", 200.0),
    ]
    assert used["credit_used_stang"] == to_satang("200.00")

    # ── เงินสด 1200 พอทั้งสองบิล: เครดิตไม่ถูกแตะ + ต้องมี warning ──
    # ⚠️ brief เขียน cash 1000 ในเคสนี้ แต่ตามอัลกอริทึมข้อ 5 (cash-first แล้วค่อย
    #    เติมเครดิตในบิลเดียวกัน) เงิน 1000 ยังไม่พอ ⇒ เครดิตย่อมถูกใช้ 200
    #    ⇒ ใช้ 1200 เพื่อทดสอบ "เครดิตไม่ถูกแตะ" ตามเจตนาของ warning
    unused = _plan(
        [_bill(1, "500.00"), _bill(2, "700.00")],
        cash="1200.00", credit="200.00", use_credit=True,
    )
    assert unused["credit_used_stang"] == 0
    assert unused["credit_added_stang"] == 0
    assert "CREDIT_UNUSED_BECAUSE_CASH_COVERED" in unused["warnings"]
    assert "CREDIT_REMAINS" in unused["warnings"]


# ═════════════════════════════════════════════════════ 7. เลือกบิลเอง (manual)
async def test_manual_selection_ignores_unselected_bills():
    bills = [_bill(1, "100.00"), _bill(2, "100.00"), _bill(3, "100.00")]
    # client ส่งลำดับกลับด้าน — engine ต้องคงลำดับของตัวเอง (1 แล้ว 2)
    plan = _plan(
        bills, cash="200.00",
        bill_selection="manual", bill_ids=[2, 1],
    )

    assert _lines(plan) == [(1, "cash", 100.0), (2, "cash", 100.0)]
    assert "UNSELECTED_OPEN_BILLS" in plan["warnings"]
    assert plan["total_applied_stang"] == to_satang("200.00")


# ═════════════════════════════════════════════ 8. เลือกบิลที่ไม่ได้เปิด → error
async def test_manual_bill_not_open_raises():
    bills = [_bill(1, "100.00"), _bill(2, "0.00")]  # บิล 2 จ่ายครบแล้ว
    with pytest.raises(AllocationError) as exc:
        _plan(bills, cash="100.00", bill_selection="manual", bill_ids=[2])
    assert exc.value.code == "BILL_NOT_OPEN"

    with pytest.raises(AllocationError) as dup:
        _plan(bills, cash="100.00", bill_selection="manual", bill_ids=[1, 1])
    assert dup.value.code == "INVALID_AMOUNT"

    # 🧾 [FIN-V2 / P3.3] `manual` + `[]` = เลือกไม่ปิดบิลสักใบ (ไม่ใช่ error) —
    #    เส้นทางเติมเครดิตล้วนใช้ท่านี้ ⇒ เงินทั้งก้อนเป็น `credit_added`
    plan = _plan(bills, cash="100.00", bill_selection="manual", bill_ids=[])
    assert plan["allocations"] == []
    assert plan["total_applied_stang"] == 0
    assert plan["credit_added_stang"] == to_satang("100.00")


# ═══════════════════════════════════════════════ 9. เศษสตางค์ไม่หาย/ไม่เกิน
async def test_rounding_never_loses_a_satang():
    bills = [_bill(i, "333.33") for i in (1, 2, 3)]
    plan = _plan(bills, cash="1000.00")

    # ⚠️ 333.33 × 3 = 999.99 ไม่ใช่ 1000.00 ⇒ เศษ 1 สตางค์ต้องไปเป็นเครดิต
    #    (ไม่ใช่หายไป และไม่ใช่ถูกยัดเข้าบิลจนเกินยอดค้าง)
    applied = sum(a["amount_stang"] for a in plan["allocations"])
    assert applied == to_satang("999.99")
    assert plan["total_applied_stang"] == applied
    assert plan["credit_added_stang"] == 1
    assert applied + plan["credit_added_stang"] == to_satang("1000.00")
    assert [a["amount_stang"] for a in plan["allocations"]] == [33333, 33333, 33333]
    assert plan["allocations"][-1]["bill_after_stang"] == 0
    assert_plan_equation(plan)


# ═══════════════════════════════════════════ 10. ลำดับ due_date แล้ว collection_id
async def test_sort_order_due_date_then_id():
    bills = [
        _bill(9, "10.00", collection_id=9, due_date=None),
        _bill(4, "10.00", collection_id=4, due_date=date(2026, 2, 1)),
        _bill(7, "10.00", collection_id=7, due_date=date(2026, 1, 10)),
        _bill(3, "10.00", collection_id=3, due_date=date(2026, 1, 10)),
    ]
    ordered = sort_open_bills(bills)
    assert [b["payment_id"] for b in ordered] == [3, 7, 4, 9]

    plan = _plan(bills, cash="10.00")
    assert plan["allocations"][0]["payment_id"] == 3


# ═══════════════════════════════════════════════════ 11. written_off ลดยอดค้าง
async def test_written_off_amount_reduces_outstanding(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    # 500 − 100 = 400 ⇒ เงิน 400 ต้องปิดบิลได้พอดี (ไม่เหลือเป็นเครดิต)
    await _insert_bill(db_pool, room_id, student, amount=500.0, written_off=100.0)

    res = client.post(
        _preview_url(room_id),
        json={"student_id": student, "amount_received": "400.00"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["allocations"][0]["bill_before"] == "400.00"
    assert body["allocations"][0]["bill_after"] == "0.00"
    assert body["credit_added"] == "0.00"


# ═══════════════════════════════════ 12. response ของ API = ผลของ pure function
async def test_preview_endpoint_matches_pure_function(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id

    await _insert_bill(db_pool, room_id, student, title="ค่าเทอม", amount=500.0,
                       due_date=date(2026, 1, 10))
    await _insert_bill(db_pool, room_id, student, title="ค่าทัศนศึกษา", amount=700.0,
                       due_date=date(2026, 2, 1))
    await _insert_credit(db_pool, room_id, student, 300.0)

    res = client.post(
        _preview_url(room_id),
        json={
            "student_id": student,
            "amount_received": "600.00",
            "use_credit": True,
        },
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    # สร้าง bills ชุดเดียวกันจาก DB (ไม่ใช้ค่าจาก response) แล้วเทียบทั้งก้อน
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT SP.id AS payment_id, FC.id AS collection_id, FC.title,
                      FC.amount, SP.paid_amount, COALESCE(SP.written_off_amount, 0) AS wo,
                      FC.due_date, FC.collection_kind, FC.fund_type
               FROM student_payments SP
               JOIN fee_collections FC ON FC.id = SP.collection_id
               WHERE SP.student_id = $1
               ORDER BY FC.due_date ASC NULLS LAST, FC.id ASC""",
            student,
        )
    bills = [{
        "payment_id": r["payment_id"],
        "collection_id": r["collection_id"],
        "title": r["title"],
        "collection_kind": r["collection_kind"],
        "fund_type": r["fund_type"],
        "due_date": r["due_date"],
        "outstanding_stang": (
            to_satang(r["amount"]) - to_satang(r["paid_amount"]) - to_satang(r["wo"])
        ),
    } for r in rows]

    expected = _plan(bills, cash="600.00", credit="300.00", use_credit=True)

    assert body["total_applied"] == f"{from_satang(expected['total_applied_stang']):.2f}"
    assert body["credit_used"] == f"{from_satang(expected['credit_used_stang']):.2f}"
    assert body["credit_added"] == f"{from_satang(expected['credit_added_stang']):.2f}"
    assert body["warnings"] == expected["warnings"]
    assert body["allocations"] == [
        {
            "student_payment_id": a["payment_id"],
            "collection_id": a["collection_id"],
            "title": a["title"],
            "collection_kind": a["collection_kind"],
            "fund_type": a["fund_type"],
            "due_date": a["due_date"].isoformat() if a["due_date"] else None,
            "source": a["source"],
            "amount": f"{from_satang(a['amount_stang']):.2f}",
            "bill_before": f"{from_satang(a['bill_before_stang']):.2f}",
            "bill_after": f"{from_satang(a['bill_after_stang']):.2f}",
        }
        for a in expected["allocations"]
    ]


# ═══════════════════════════════════════════════ 13. สมาชิกทั่วไป → 403
async def test_preview_requires_manage_finance(client, db_pool, member_headers):
    res = client.post(
        _preview_url(member_headers.room_id),
        json={"student_id": member_headers.student_id, "amount_received": "100.00"},
        headers=member_headers,
    )
    assert res.status_code == 403


# ═══════════════════════════════════════════════ 14. preview ไม่เขียนอะไรเลย
async def test_preview_does_not_write(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    await _insert_bill(db_pool, room_id, student, amount=500.0)
    await _insert_credit(db_pool, room_id, student, 100.0)

    async with db_pool.acquire() as conn:
        before_txns = await conn.fetchval("SELECT COUNT(*) FROM finance_transactions")
        before_paid = await conn.fetchval(
            "SELECT paid_amount FROM student_payments WHERE student_id = $1", student
        )
        before_credit = await conn.fetchval(
            "SELECT COUNT(*) FROM student_credits WHERE student_id = $1", student
        )

    res = client.post(
        _preview_url(room_id),
        json={
            "student_id": student,
            "amount_received": "600.00",
            "use_credit": True,
        },
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM finance_transactions") == before_txns
        assert await conn.fetchval(
            "SELECT paid_amount FROM student_payments WHERE student_id = $1", student
        ) == before_paid
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM student_credits WHERE student_id = $1", student
        ) == before_credit


# ═══════════════════════════════ 15. บิลของนักเรียนคนอื่นใน manual → 409
async def test_manual_bill_from_other_student_returns_409(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student = admin_headers.student_id
    other = await _insert_student(db_pool, room_id, student_no=2)

    await _insert_bill(db_pool, room_id, student, amount=100.0)
    other_bill = await _insert_bill(db_pool, room_id, other, amount=100.0)

    res = client.post(
        _preview_url(room_id),
        json={
            "student_id": student,
            "amount_received": "100.00",
            "bill_selection": "manual",
            "bill_ids": [other_bill],
        },
        headers=admin_headers,
    )
    assert res.status_code == 409, res.text
