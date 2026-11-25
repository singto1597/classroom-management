"""🧾 [FIN-V2 / P5.4] ACK — วงจรชีวิตใบรับทราบยอดค้าง (ออก/อ่าน/ยกเลิก)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 รอบ = 1 ใบ + N entries** — ยอด ACK = ผลรวมยอดค้าง, ไม่มี INV ก็ยังออกได้
2. **ไม่แตะเงินเลย** — `finance_accounts.balance`/`finance_transactions`/journal/
   `student_payments.paid_amount`/`student_credits` เท่าเดิมก่อน-หลัง
3. **idempotency** — คีย์เดิม + payload เดิม = ใบเดิม (`reused=true`) ไม่กินเลขซ้ำ;
   คีย์เดิม + payload ต่าง = **409** ไม่ใช่คืนใบเงียบ ๆ
4. **เลขจาก `receipt_sequences`** — ไม่ใช่ MAX()+1 และรูป `ACK-2569-0001`
5. **void เก็บ entries ไว้** — `status='voided'` + `deleted_at` ไปด้วยกัน (CHECK)
   แต่ `finance_ack_entries` ยังอยู่ครบ (ประวัติว่าเคยแจ้งใคร)

⚠️ ยืนยันกับ DB จริงผ่าน `db_pool` ตาม `docs/rules/testing.md`
"""
import json
import re
import uuid
from datetime import date, datetime

import pytest

from services.finance.constants import BUDDHIST_ERA_OFFSET, THAI_TZ

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
ACKS_PATH = API_PREFIX + "/{room}/finance/acknowledgements"


def _url(template: str, room_id: int, suffix: str = "") -> str:
    """`?target_type=room` ต้องอยู่ **ท้าย URL จริง** — suffix ต่อก่อน query เสมอ"""
    return template.format(room=room_id) + suffix + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _make_debtor(pool, room_id: int, *, student_no: int,
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


async def _make_bill(pool, room_id: int, student_id: int, *,
                     title: str = "ค่าเทอม", amount: float = 1000.0,
                     due_date: date = date(2026, 12, 31)) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, title, amount, due_date,
        )
        await conn.execute(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0)""",
            collection_id, student_id,
        )
    return collection_id


async def _pay_bill(pool, collection_id: int, student_id: int, amount: float) -> None:
    """ปิดบิลทั้งใบ — predicate `SP.status='pending'` จะไม่เห็นบิลนี้อีก"""
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE student_payments
                  SET status = 'paid', paid_amount = $3
                WHERE collection_id = $1 AND student_id = $2""",
            collection_id, student_id, amount,
        )


async def _insert_account(pool, room_id: int, balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, "กระเป๋ากลาง", balance,
        )


# ═══════════════════════════════════════════════════════════════════ HTTP helper
def _ack_body(**over) -> dict:
    body = {
        "scope": "room",
        # 📌 ปริยายของเทสต์ = ไม่ผูก INV — เฉพาะเทสต์ที่ต้องการ INV จึงเปิดเอง
        "include_invoice": False,
        "idempotency_key": f"ack-{uuid.uuid4().hex[:16]}",
    }
    body.update(over)
    return body


def _issue_ack(client, headers, *, room_id=None, **over):
    return client.post(
        _url(ACKS_PATH, room_id if room_id is not None else headers.room_id),
        json=_ack_body(**over), headers=headers,
    )


# ═══════════════════════════════════════════════════════════════════ DB helpers
async def _doc_row(pool, receipt_no: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, receipt_no, doc_type, year_be, seq, amount, paid_total_after,
                      layout_version, document_meta, idempotency_key, status,
                      voided_at, void_reason, deleted_at
               FROM finance_receipts WHERE receipt_no = $1""",
            receipt_no,
        )


async def _entries_of(pool, ack_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT student_id, invoice_receipt_id, outstanding_amount
               FROM finance_ack_entries WHERE ack_receipt_id = $1 ORDER BY id""",
            ack_id,
        )


async def _count(pool, sql: str, *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def _ack_rows(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, receipt_no, seq, amount, status, deleted_at
               FROM finance_receipts
              WHERE room_id = $1 AND doc_type = 'acknowledgement'
              ORDER BY id""",
            room_id,
        )


async def _money_snapshot(pool, room_id: int) -> dict:
    """ยอดของ **ทุกตารางที่เงินอยู่ในนั้น** — ACK ต้องไม่ขยับสักช่อง"""
    async with pool.acquire() as conn:
        balances = await conn.fetchval(
            """SELECT COALESCE(SUM(balance), 0) FROM finance_accounts
                WHERE room_id = $1 AND deleted_at IS NULL""",
            room_id,
        )
        txn_count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id,
        )
        je_count = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id,
        )
        jl_count = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_lines L
                 JOIN journal_entries JE ON L.journal_entry_id = JE.id
                WHERE JE.room_id = $1""",
            room_id,
        )
        paid_total = await conn.fetchval(
            """SELECT COALESCE(SUM(SP.paid_amount), 0) FROM student_payments SP
                 JOIN students S ON SP.student_id = S.id
                WHERE S.room_id = $1""",
            room_id,
        )
        credit_count = await conn.fetchval(
            "SELECT COUNT(*) FROM student_credits WHERE room_id = $1", room_id,
        )
    return {
        "balances": float(balances or 0),
        "transactions": int(txn_count),
        "journal_entries": int(je_count),
        "journal_lines": int(jl_count),
        "paid_total": float(paid_total or 0),
        "credits": int(credit_count),
    }


def _today_year_be() -> int:
    return datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET


# ═══════════════════════════════════════ 1. 1 ใบ + N entries + ยอดรวมถูก
async def test_issue_ack_creates_one_receipt_and_n_entries(
    client, db_pool, admin_headers
):
    a = await _make_debtor(db_pool, admin_headers.room_id, student_no=11)
    b = await _make_debtor(db_pool, admin_headers.room_id, student_no=12)
    await _make_bill(db_pool, admin_headers.room_id, a, amount=1000.0)
    await _make_bill(db_pool, admin_headers.room_id, b, amount=2500.5)

    res = _issue_ack(client, admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["reused"] is False
    assert body["receipt"]["doc_type"] == "acknowledgement"
    assert body["receipt"]["amount"] == 3500.5
    assert body["receipt"]["paid_total_after"] == 0
    assert len(body["entries"]) == 2

    rows = await _ack_rows(db_pool, admin_headers.room_id)
    assert len(rows) == 1, "1 รอบต้องออกใบเดียว"
    entries = await _entries_of(db_pool, rows[0]["id"])
    assert len(entries) == 2
    assert sum(float(e["outstanding_amount"]) for e in entries) == 3500.5
    assert {e["student_id"] for e in entries} == {a, b}
    layout = await db_pool.fetchval(
        "SELECT layout_version FROM finance_receipts WHERE id = $1", rows[0]["id"],
    )
    assert layout == 2, "ACK ใหม่ต้องเป็น layout v2"


# ═══════════════════════════════════════ 2. ไม่มีใครค้าง = ปฏิเสธ
async def test_issue_ack_rejects_when_no_outstanding(client, db_pool, admin_headers):
    # ห้องมีแค่ admin (student_no 1) และไม่มีบิลเลย
    res = _issue_ack(client, admin_headers)
    assert res.status_code == 400, res.text
    assert await _ack_rows(db_pool, admin_headers.room_id) == []


# ═══════════════════════════════════════ 3. บิลจ่ายครบแล้ว = ไม่มีอะไรให้ออก
async def test_issue_ack_amount_must_be_positive(client, db_pool, admin_headers):
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=21)
    collection_id = await _make_bill(db_pool, admin_headers.room_id, sid, amount=800.0)
    await _pay_bill(db_pool, collection_id, sid, 800.0)

    res = _issue_ack(client, admin_headers)
    assert res.status_code == 400, res.text
    assert "ยอดค้าง" in res.json()["detail"]
    assert await _ack_rows(db_pool, admin_headers.room_id) == []


# ═══════════════════════════════════════ 4. idempotent — คีย์เดิมได้ใบเดิม
async def test_issue_ack_is_idempotent_same_payload(client, db_pool, admin_headers):
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=31)
    await _make_bill(db_pool, admin_headers.room_id, sid, amount=1200.0)

    first = _issue_ack(client, admin_headers, idempotency_key="same-key-1")
    assert first.status_code == 200, first.text

    second = _issue_ack(client, admin_headers, idempotency_key="same-key-1")
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert second.json()["receipt"]["receipt_no"] == first.json()["receipt"]["receipt_no"]

    rows = await _ack_rows(db_pool, admin_headers.room_id)
    assert len(rows) == 1, "replay ต้องไม่สร้างใบใหม่"
    seq = await db_pool.fetchval(
        """SELECT last_seq FROM receipt_sequences
            WHERE room_id = $1 AND doc_type = 'acknowledgement'""",
        admin_headers.room_id,
    )
    assert seq == 1, "replay ต้องไม่กินเลข"


# ═══════════════════════════════════════ 5. คีย์เดิม + payload ต่าง = 409
async def test_issue_ack_same_key_different_payload_conflicts(
    client, db_pool, admin_headers
):
    a = await _make_debtor(db_pool, admin_headers.room_id, student_no=41)
    b = await _make_debtor(db_pool, admin_headers.room_id, student_no=42)
    await _make_bill(db_pool, admin_headers.room_id, a, amount=500.0)
    await _make_bill(db_pool, admin_headers.room_id, b, amount=700.0)

    first = _issue_ack(
        client, admin_headers, scope="selected", student_ids=[a],
        idempotency_key="conflict-key",
    )
    assert first.status_code == 200, first.text

    # payload ต่าง (คนละนักเรียน) แต่คีย์เดิม
    second = _issue_ack(
        client, admin_headers, scope="selected", student_ids=[b],
        idempotency_key="conflict-key",
    )
    assert second.status_code == 409, second.text
    assert "idempotency" in second.json()["detail"].lower()

    rows = await _ack_rows(db_pool, admin_headers.room_id)
    assert len(rows) == 1


# ═══════════════════════════════════════ 6. ไม่แตะเงินแม้แต่ช่องเดียว
async def test_issue_ack_does_not_touch_money(client, db_pool, admin_headers):
    await _insert_account(db_pool, admin_headers.room_id, balance=5000.0)
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=51)
    collection_id = await _make_bill(db_pool, admin_headers.room_id, sid, amount=1000.0)

    before = await _money_snapshot(db_pool, admin_headers.room_id)

    # เปิด include_invoice=True — ลองเส้นทางหนักสุด: INV ถูกออกในชุดเดียวกับ ACK
    res = _issue_ack(client, admin_headers, include_invoice=True)
    assert res.status_code == 200, res.text

    after = await _money_snapshot(db_pool, admin_headers.room_id)
    assert after == before, "ACK/INV ต้องไม่แตะเงิน กระเป๋า journal บิล หรือเครดิต"

    paid = await db_pool.fetchval(
        "SELECT paid_amount FROM student_payments WHERE collection_id = $1",
        collection_id,
    )
    assert float(paid) == 0.0


# ═══════════════════════════════════════ 7. selected scope = เฉพาะที่เลือก
async def test_issue_ack_selected_scope_only_includes_listed_students(
    client, db_pool, admin_headers
):
    a = await _make_debtor(db_pool, admin_headers.room_id, student_no=61)
    b = await _make_debtor(db_pool, admin_headers.room_id, student_no=62)
    c = await _make_debtor(db_pool, admin_headers.room_id, student_no=63)
    for sid, amount in ((a, 100.0), (b, 200.0), (c, 300.0)):
        await _make_bill(db_pool, admin_headers.room_id, sid, amount=amount)

    res = _issue_ack(
        client, admin_headers, scope="selected", student_ids=[a, c],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert {e["student_id"] for e in body["entries"]} == {a, c}
    assert body["receipt"]["amount"] == 400.0
    assert b not in {e["student_id"] for e in body["entries"]}


# ═══════════════════════════════════════ 8. ทั้งห้องข้ามคนที่จ่ายครบเงียบ ๆ
async def test_issue_ack_excludes_fully_paid_student(client, db_pool, admin_headers):
    debtor = await _make_debtor(db_pool, admin_headers.room_id, student_no=71)
    paid = await _make_debtor(db_pool, admin_headers.room_id, student_no=72)
    await _make_bill(db_pool, admin_headers.room_id, debtor, amount=900.0)
    collection_id = await _make_bill(db_pool, admin_headers.room_id, paid, amount=400.0)
    await _pay_bill(db_pool, collection_id, paid, 400.0)

    res = _issue_ack(client, admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert [e["student_id"] for e in body["entries"]] == [debtor]
    assert body["receipt"]["amount"] == 900.0


# ═══════════════════════════════════════ 9. void — status + deleted_at + entries อยู่ครบ
async def test_ack_void_keeps_entries_and_sets_deleted_at(
    client, db_pool, admin_headers
):
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=81)
    await _make_bill(db_pool, admin_headers.room_id, sid, amount=1500.0)

    issued = _issue_ack(client, admin_headers)
    assert issued.status_code == 200, issued.text
    receipt_no = issued.json()["receipt"]["receipt_no"]

    res = client.post(
        _url(ACKS_PATH, admin_headers.room_id, suffix=f"/{receipt_no}/void"),
        json={"reason": "พิมพ์ผิดเลขที่นักเรียน"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    row = await _doc_row(db_pool, receipt_no)
    assert row["status"] == "voided"
    assert row["deleted_at"] is not None
    assert row["voided_at"] is not None
    assert row["void_reason"] == "พิมพ์ผิดเลขที่นักเรียน"

    entries = await _entries_of(db_pool, row["id"])
    assert len(entries) == 1, "void ต้องไม่ลบประวัติว่าเคยแจ้งใคร"


# ═══════════════════════════════════════ 10. void ต้องมีเหตุผลจริง (ไม่ใช่ช่องว่าง)
async def test_ack_void_requires_reason(client, db_pool, admin_headers):
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=82)
    await _make_bill(db_pool, admin_headers.room_id, sid, amount=600.0)
    issued = _issue_ack(client, admin_headers)
    assert issued.status_code == 200, issued.text
    receipt_no = issued.json()["receipt"]["receipt_no"]

    # "  " ผ่าน Pydantic (min_length=1) แต่ service strip แล้วว่าง → 400
    res = client.post(
        _url(ACKS_PATH, admin_headers.room_id, suffix=f"/{receipt_no}/void"),
        json={"reason": "   "},
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    row = await _doc_row(db_pool, receipt_no)
    assert row["status"] != "voided"


# ═══════════════════════════════════════ 11. เลขมาจาก receipt_sequences
async def test_ack_seq_uses_receipt_sequences(client, db_pool, admin_headers):
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=91)
    await _make_bill(db_pool, admin_headers.room_id, sid, amount=750.0)

    first = _issue_ack(client, admin_headers, idempotency_key="seq-key-1")
    assert first.status_code == 200, first.text
    second = _issue_ack(client, admin_headers, idempotency_key="seq-key-2")
    assert second.status_code == 200, second.text

    rows = await _ack_rows(db_pool, admin_headers.room_id)
    assert [r["seq"] for r in rows] == [1, 2]
    assert len({r["receipt_no"] for r in rows}) == 2, "เลขต้องไม่ซ้ำ"

    year_be = _today_year_be()
    seq_row = await db_pool.fetchrow(
        """SELECT last_seq FROM receipt_sequences
            WHERE room_id = $1 AND year_be = $2 AND doc_type = 'acknowledgement'""",
        admin_headers.room_id, year_be,
    )
    assert seq_row is not None
    assert seq_row["last_seq"] == 2


# ═══════════════════════════════════════ 12. รูปแบบเลข ACK-2569-0001
async def test_ack_number_format_matches_pattern(client, db_pool, admin_headers):
    sid = await _make_debtor(db_pool, admin_headers.room_id, student_no=99)
    await _make_bill(db_pool, admin_headers.room_id, sid, amount=333.0)

    res = _issue_ack(client, admin_headers)
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipt"]["receipt_no"]

    assert re.fullmatch(r"ACK-\d{4}-\d{4}", receipt_no), receipt_no
    assert receipt_no == f"ACK-{_today_year_be()}-0001"


# ═══════════════════════════════════════ 13. meta เก็บ scope/entry_count/total
async def test_ack_document_meta_records_scope_and_entries(
    client, db_pool, admin_headers
):
    a = await _make_debtor(db_pool, admin_headers.room_id, student_no=101)
    await _make_bill(db_pool, admin_headers.room_id, a, amount=450.0)

    res = _issue_ack(client, admin_headers, scope="selected", student_ids=[a])
    assert res.status_code == 200, res.text

    row = await _doc_row(db_pool, res.json()["receipt"]["receipt_no"])
    meta = row["document_meta"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta["scope"] == "selected"
    assert meta["entry_count"] == 1
    assert meta["total_outstanding"] == 450.0
    assert meta["include_invoice"] is False
