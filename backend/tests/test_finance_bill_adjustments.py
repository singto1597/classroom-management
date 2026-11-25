"""✂️ [FIN-V2 / P6.2] ตัดจำหน่าย/ให้ส่วนลดบิล + fund_type + เตือนชื่อซ้ำ

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **`written_off_amount` คือที่เดียว** — ไม่แตะ `paid_amount` และไม่ลด
   `fee_collections.amount` (ยอดบิลต้นฉบับที่ใช้บนเอกสาร/สัญญา)
2. **journal ถูกคู่** — write_off Dr 59002 / discount Dr 49002 · Cr 11001 AR
   (resolve ผ่าน `_resolve_system_ledger` ไม่ใช่ SELECT เอง ⇒ collision guard ทำงาน)
3. **ตัดครบ ⇒ `status='waived'`** — หลุดจาก `_open_bill_predicate` (predicate ไม่มีเงื่อนไขยอด)
4. **idempotency สองชั้น** — คีย์เดิม + payload เดิม = ผลเดิม (ไม่ลงซ้ำ);
   คีย์เดิม + payload ต่าง = 409
5. **บิลค่าปรับ → 409 ชี้หน้าค่าปรับ** — ไม่เปิดทางเขียนยอดซ้ำกับ waiver
6. **guard จำนวนเงิน** — เกินยอดคงเหลือ / ≤ 0 / ไม่มีเหตุผล = 400 และไม่มีอะไรถูกแตะ
7. **INV รวมยอดถูก void** — snapshot ยอดค้างเก่าไม่จริงแล้ว (ไม่ออกใบใหม่ให้เอง)
8. **fund_type = มิติรายงาน** — UPDATE + audit เท่านั้น ไม่แตะเงิน/journal; มี audit
9. **เตือนชื่อซ้ำไม่บล็อก** — endpoint อ่านล้วนและสร้างซ้ำได้จริง

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


# ═══════════════════════════════════════════════════════════════════ helpers
def _key() -> str:
    return uuid.uuid4().hex


def _write_off_url(room_id: int, payment_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payments/{payment_id}/write-off"


def _discount_url(room_id: int, payment_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payments/{payment_id}/discount"


def _adjustments_url(room_id: int, payment_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payments/{payment_id}/adjustments"


def _fund_type_url(room_id: int, collection_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/fee-collections/{collection_id}/fund-type"


def _duplicate_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/fee-collections/duplicate-check"


def _payload(*, amount, reason: str = "ตัดหนี้สูญทดสอบ", key=None) -> dict:
    return {
        "amount": amount,
        "reason": reason,
        "idempotency_key": key or _key(),
    }


async def _insert_collection(
    pool, room_id: int, *, title: str = "ค่าเทอม 1/2569",
    amount: float = 1000.0, kind: str = "project",
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO fee_collections
                   (room_id, title, amount, due_date, status, fund_type, collection_kind)
               VALUES ($1, $2, $3, $4, 'active', 'room_fund', $5)
               RETURNING id""",
            room_id, title, amount, date(2026, 11, 30), kind,
        )


async def _insert_bill(
    pool, room_id: int, *, student_id: int, amount: float = 1000.0,
    paid: float = 0.0, written: float = 0.0, title: str = "ค่าเทอม 1/2569",
    kind: str = "project",
) -> tuple[int, int]:
    """คืน `(collection_id, student_payment_id)` — บิลเปล่าไม่ต้องมี accrual journal"""
    collection_id = await _insert_collection(
        pool, room_id, title=title, amount=amount, kind=kind,
    )
    async with pool.acquire() as conn:
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, written_off_amount)
               VALUES ($1, $2, 'pending', $3, $4) RETURNING id""",
            collection_id, student_id, paid, written,
        )
    return collection_id, payment_id


async def _sp_row(pool, payment_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT paid_amount, written_off_amount, status FROM student_payments WHERE id = $1",
            payment_id,
        )


async def _journal_lines(pool, journal_id: str):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT L.account_code, L.account_name, JL.debit, JL.credit
               FROM journal_lines JL
               JOIN accounting_ledgers L ON L.id = JL.ledger_id
               WHERE JL.journal_entry_id = $1
               ORDER BY L.account_code""",
            journal_id,
        )


async def _adjustment_count(pool, payment_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM finance_bill_adjustments WHERE student_payment_id = $1",
            payment_id,
        )


async def _insert_aggregate_invoice(pool, room_id: int, student_id: int) -> int:
    """INV รวมยอด (student_payment_id NULL) — ใบที่ snapshot ยอดค้างของนักเรียน"""
    async with pool.acquire() as conn:
        seq = await conn.fetchval(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM finance_receipts WHERE room_id = $1 AND doc_type = 'invoice'",
            room_id,
        )
        return await conn.fetchval(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, student_id,
                    amount, paid_total_after, status)
               VALUES ($1, $2, 'invoice', 2569, $3, $4, 1000.00, 0, 'active')
               RETURNING id""",
            room_id, f"INV-2569-{seq:04d}", seq, student_id,
        )


# ═══════════════════════ 1. ตัดบางส่วน — written_off + paid เดิม + ยัง pending
async def test_write_off_project_bill_updates_written_off_and_status(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=500.0), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["adjustment"]["amount"] == "500.00"
    assert data["adjustment"]["remaining"] == "500.00"
    assert data["adjustment"]["written_off_total"] == "500.00"
    assert data["adjustment"]["bill_status"] == "pending"

    row = await _sp_row(db_pool, payment_id)
    assert float(row["written_off_amount"]) == 500.0
    assert float(row["paid_amount"]) == 0.0          # 💡 ไม่แตะเงินที่รับจริง
    assert row["status"] == "pending"                 # ยังเหลือค้าง

    # ยอดบิลต้นฉบับไม่ถูกแตะ
    async with db_pool.acquire() as conn:
        fc_amount = await conn.fetchval(
            """SELECT FC.amount FROM fee_collections FC
               JOIN student_payments SP ON SP.collection_id = FC.id WHERE SP.id = $1""",
            payment_id,
        )
    assert float(fc_amount) == 1000.0


# ══════════════════════ 2. ตัดครบ — status='waived' และหลุด predicate บิลเปิด
async def test_write_off_full_amount_sets_status_waived(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=1000.0), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["adjustment"]["bill_status"] == "waived"
    assert res.json()["adjustment"]["remaining"] == "0.00"

    row = await _sp_row(db_pool, payment_id)
    assert row["status"] == "waived"
    async with db_pool.acquire() as conn:
        open_count = await conn.fetchval(
            """SELECT COUNT(*) FROM student_payments
               WHERE id = $1 AND status = 'pending' AND deleted_at IS NULL""",
            payment_id,
        )
    assert open_count == 0                            # ไม่ถูกนับเป็น "บิลค้าง" อีก


# ═════════════════ 3. journal write_off — Dr 59002 / Cr 11001 และยอดดุลกัน
async def test_write_off_creates_journal_59002_cr_ar_project(
    client, db_pool, admin_headers,
):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=400.0), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    journal_id = res.json()["adjustment"]["journal_entry_id"]
    assert journal_id

    lines = await _journal_lines(db_pool, journal_id)
    assert len(lines) == 2
    codes = {r["account_code"] for r in lines}
    assert codes == {"59002", "11001"}
    debit = next(r for r in lines if r["account_code"] == "59002")
    credit = next(r for r in lines if r["account_code"] == "11001")
    assert float(debit["debit"]) == 400.0 and float(debit["credit"]) == 0.0
    assert float(credit["credit"]) == 400.0 and float(credit["debit"]) == 0.0


# ═══════════════════ 4. journal discount — Dr 49002 และยอดwritten_off ขึ้นเท่ากัน
async def test_discount_creates_journal_49002(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)

    res = client.post(
        _discount_url(room, payment_id),
        json=_payload(amount=250.0, reason="ส่วนลดลูกนักเรียน"), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["adjustment"]["adjustment_type"] == "discount"

    lines = await _journal_lines(db_pool, data["adjustment"]["journal_entry_id"])
    codes = {r["account_code"] for r in lines}
    assert codes == {"49002", "11001"}
    debit = next(r for r in lines if r["account_code"] == "49002")
    assert float(debit["debit"]) == 250.0

    row = await _sp_row(db_pool, payment_id)
    assert float(row["written_off_amount"]) == 250.0
    assert float(row["paid_amount"]) == 0.0


# ═════════════════════ 5. ตัดเกินยอดคงเหลือ — 400 และไม่มีอะไรถูกแตะ
async def test_amount_cannot_exceed_outstanding(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(
        db_pool, room, student_id=student, amount=1000.0, paid=300.0,
    )

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=700.01), headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "700.01" in detail and "700.00" in detail

    row = await _sp_row(db_pool, payment_id)
    assert float(row["written_off_amount"]) == 0.0
    assert await _adjustment_count(db_pool, payment_id) == 0


# ═══════════════════════ 6. ยอดต้องมากกว่า 0 (0 / ติดลบ / "0.00" → 400)
@pytest.mark.parametrize("amount", [0, -1, "0.00"])
async def test_amount_must_be_positive(client, db_pool, admin_headers, amount):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student)

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=amount), headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert await _adjustment_count(db_pool, payment_id) == 0


# ═════════════════════════════════ 7. เหตุผลบังคับ (ว่าง/ช่องว่างล้วน)
@pytest.mark.parametrize("reason", ["", "   "])
async def test_reason_required(client, db_pool, admin_headers, reason):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student)

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=100.0, reason=reason), headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert await _adjustment_count(db_pool, payment_id) == 0


# ═════════════════ 8. บิลค่าปรับ — 409 ชี้หน้าค่าปรับ (ไม่ใช่ 400)
async def test_write_off_on_fine_bill_refused_409(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(
        db_pool, room, student_id=student, title="ค่าปรับมาสาย", kind="fine",
    )

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=100.0), headers=admin_headers,
    )
    assert res.status_code == 409, res.text
    assert "หน้าค่าปรับ" in res.json()["detail"]
    assert await _adjustment_count(db_pool, payment_id) == 0


# ═════════════ 9. คีย์เดิม + payload เดิม — คืนผลเดิม ไม่ลงซ้ำ
async def test_idempotent_same_key_returns_existing(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)
    key = _key()
    body = _payload(amount=300.0, key=key)

    first = client.post(_write_off_url(room, payment_id), json=body, headers=admin_headers)
    assert first.status_code == 200, first.text

    second = client.post(_write_off_url(room, payment_id), json=body, headers=admin_headers)
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["reused"] is True
    assert second_data["adjustment"]["id"] == first.json()["adjustment"]["id"]

    row = await _sp_row(db_pool, payment_id)
    assert float(row["written_off_amount"]) == 300.0     # ไม่บวกซ้ำ
    assert await _adjustment_count(db_pool, payment_id) == 1


# ═════════════ 10. คีย์เดิมแต่ยอดต่าง — 409 (ไม่ทับรายการเดิม)
async def test_same_key_different_amount_conflicts_409(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)
    key = _key()

    first = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=100.0, key=key), headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    second = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=200.0, key=key), headers=admin_headers,
    )
    assert second.status_code == 409, second.text
    assert "คีย์นี้ถูกใช้" in second.json()["detail"]

    row = await _sp_row(db_pool, payment_id)
    assert float(row["written_off_amount"]) == 100.0


# ══════════════ 11. INV รวมยอดของนักเรียนถูก void (snapshot เก่าไม่จริงแล้ว)
async def test_write_off_voids_aggregate_invoice(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_id = await _insert_bill(db_pool, room, student_id=student, amount=1000.0)
    invoice_id = await _insert_aggregate_invoice(db_pool, room, student)

    res = client.post(
        _write_off_url(room, payment_id),
        json=_payload(amount=400.0), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["voided_invoices"] == 1

    async with db_pool.acquire() as conn:
        inv = await conn.fetchrow(
            "SELECT status, deleted_at, void_reason FROM finance_receipts WHERE id = $1",
            invoice_id,
        )
    assert inv["status"] == "voided"
    assert inv["deleted_at"] is not None
    assert inv["void_reason"]


# ═════════════════ 12. รายการปรับบิลแสดงเฉพาะบิลที่ขอ (ไม่ปนบิลอื่น)
async def test_adjustments_list_only_this_payment(client, db_pool, admin_headers):
    room, student = admin_headers.room_id, admin_headers.student_id
    _, payment_a = await _insert_bill(db_pool, room, student_id=student, title="ค่าเทอม A")
    _, payment_b = await _insert_bill(db_pool, room, student_id=student, title="ค่าเทอม B")

    assert client.post(
        _write_off_url(room, payment_a),
        json=_payload(amount=100.0), headers=admin_headers,
    ).status_code == 200
    assert client.post(
        _discount_url(room, payment_b),
        json=_payload(amount=50.0), headers=admin_headers,
    ).status_code == 200

    res = client.get(_adjustments_url(room, payment_a), headers=admin_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["adjustment_type"] == "write_off"
    assert all(i["student_payment_id"] == payment_a for i in data["items"])


# ═══════════════ 13. fund_type — UPDATE + audit เท่านั้น ไม่แตะเงิน/journal
async def test_fund_type_set_and_audited(client, db_pool, admin_headers):
    room = admin_headers.room_id
    collection_id = await _insert_collection(db_pool, room, title="เงินผ่านมือ")

    async with db_pool.acquire() as conn:
        before_journals = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room,
        )

    res = client.patch(
        _fund_type_url(room, collection_id),
        json={"fund_type": "pass_through"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["fund_type"] == "pass_through"

    async with db_pool.acquire() as conn:
        fund_type = await conn.fetchval(
            "SELECT fund_type FROM fee_collections WHERE id = $1", collection_id,
        )
        audit = await conn.fetchrow(
            """SELECT action, old_values, new_values FROM audit_logs
               WHERE room_id = $1 AND entity_type = 'FINANCE_FEE_COLLECTION'
                 AND entity_id = $2 ORDER BY id DESC LIMIT 1""",
            room, str(collection_id),
        )
        after_journals = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room,
        )
    assert fund_type == "pass_through"
    assert audit is not None and audit["action"] == "UPDATE"
    assert after_journals == before_journals            # ไม่มี journal ใหม่

    # ค่าเดิม = ส่งซ้ำไม่สร้าง audit ซ้ำ
    again = client.patch(
        _fund_type_url(room, collection_id),
        json={"fund_type": "pass_through"}, headers=admin_headers,
    )
    assert again.status_code == 200, again.text
    async with db_pool.acquire() as conn:
        audits = await conn.fetchval(
            """SELECT COUNT(*) FROM audit_logs
               WHERE room_id = $1 AND entity_type = 'FINANCE_FEE_COLLECTION'
                 AND entity_id = $2""",
            room, str(collection_id),
        )
    assert audits == 1


# ═════════════ 14. เตือนชื่อซ้ำ — ไม่สนตัวพิมพ์/ช่องว่างหัวท้าย
async def test_duplicate_title_check_finds_case_insensitive_matches(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    await _insert_collection(db_pool, room, title="ค่ายลูกเสือ")
    await _insert_collection(db_pool, room, title="  ค่ายลูกเสือ  ")

    res = client.get(
        _duplicate_url(room), params={"title": "ค่ายลูกเสือ"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["duplicates"]) == 2
    assert "2 รายการ" in data["warning"]

    none = client.get(
        _duplicate_url(room), params={"title": "ไม่มีจริง"}, headers=admin_headers,
    )
    assert none.status_code == 200, none.text
    assert none.json()["duplicates"] == []
    assert none.json()["warning"] is None


# ═════════════ 15. เตือนชื่อซ้ำเป็น non-blocking — สร้างชื่อเดิมได้จริง
async def test_duplicate_title_is_non_blocking(client, db_pool, admin_headers):
    room = admin_headers.room_id
    await _insert_collection(db_pool, room, title="ทัศนศึกษา")

    check = client.get(
        _duplicate_url(room), params={"title": "ทัศนศึกษา"}, headers=admin_headers,
    )
    assert check.status_code == 200, check.text
    assert check.json()["duplicates"]

    created = client.post(
        f"{API_PREFIX}/{room}/finance/collections",
        json={
            "title": "ทัศนศึกษา",
            "amount": 500.0,
            "due_date": (date.today() + timedelta(days=30)).isoformat(),
            "student_ids": [admin_headers.student_id],
        },
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            """SELECT COUNT(*) FROM fee_collections
               WHERE room_id = $1 AND title = 'ทัศนศึกษา' AND deleted_at IS NULL""",
            room,
        )
    assert count == 2
