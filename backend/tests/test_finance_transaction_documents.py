"""[F6] เอกสารที่ออกให้ **รายการที่บันทึกเอง** — ใบรับเงิน (income) + ใบสำคัญจ่าย (payment_voucher)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **การบันทึกรายการต้องมีเอกสารคู่เสมอ** — ผู้ใช้ขอว่า *"ตอนที่บันทึกรายการว่าได้รายรับมา
   ก็เอาให้มีใบเหมือนกับกดรับเงินห้องจากเพื่อนมา"* และ *"ตอนที่บันทึกรายการของเงินห้อง
   ให้มีการสร้างใบสำคัญจ่ายมาด้วย"* ⇒ รายรับได้ `income` · รายจ่ายได้ `payment_voucher`
   · **โอนเงินระหว่างกระเป๋าไม่ได้อะไรเลย** (โอนเป็น net-zero ภายในห้อง ไม่มีผู้เบิก
   ไม่มีหมวดงบ ⇒ เอกสารที่ออกมาจะยืนยันเหตุการณ์ที่ไม่ได้เกิดขึ้น)

2. **เอกสารต้องไม่ทำให้รายการพัง** — ออกใน transaction เดียวกัน ⇒ รายการที่บันทึกไม่สำเร็จ
   ต้องไม่มีเอกสารค้าง และกลับกัน

3. **เลขเอกสารต้องมาจาก "เหตุการณ์" ไม่ใช่วันที่พิมพ์** — `PV-2569-0001` / `INC-2569-0001`
   ปี พ.ศ. มาจาก `finance_transactions.created_at` (naive UTC ⇒ ต้องติดป้ายก่อนแปลงไทย)
   ไม่ใช่ `issued_at` · รายการ 17:30 UTC = 00:30 ของวันรุ่งขึ้นในไทย ⇒ **ข้ามปีได้จริง**

4. **ตัวนับเลขแยกต่อชนิด** — `PV` กับ `INC` กับ `REC` ของห้อง/ปีเดียวกัน ต่างคนต่างเริ่ม 0001
   (`receipt_sequences` PK = (room, year_be, doc_type)) และ **กดซ้ำต้องได้เลขเดิม**
   ไม่ใช่กินเลขใหม่

5. 🔴 **การรับคืนรายการต้องยกเลิกเอกสารของรายการนั้นด้วย** — `revert_transaction` กรอง
   `doc_type = ANY($5)` ⇒ ถ้าลืมใส่ชนิดใหม่ ใบสำคัญ/ใบรับเงินจะค้าง `active` ตลอดกาล
   ทั้งที่เงินถูกคืนไปแล้ว = เอกสารขัดกับฐานข้อมูล (ไม่มีอะไรฟ้องนอกจากเทสต์นี้)

6. 🔴 **เลขเอกสารต้องรอดถึงหน้าจอ** — `response_model` ตัดฟิลด์ที่ service คืนทิ้ง *เงียบ ๆ*
   ⇒ ถ้าไม่ประกาศ `TransactionCreateResponse` ผู้ใช้บันทึกสำเร็จแต่ไม่รู้เลขที่เพิ่งออก

7. **`RECEIPT_NO_PATTERN` ต้องรับ `PV-`** — pattern นี้เป็น path param ของ
   `GET /finance/receipts/{no}/pdf` ⇒ ถ้ายังบังคับ `[A-Z]{3}` ใบสำคัญจะ **ออกได้แต่เปิดไม่ได้**

⚠️ ทุกเทสต์ยืนยันกับ DB จริงผ่าน `db_pool` ไม่เชื่อแค่ HTTP status (กฎ docs/rules/testing.md)
⚠️ ห้าม hardcode id — ทุกอย่างมาจาก fixture ของเทสต์ตัวเอง
"""
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import json

import pytest

from services.finance.constants import (
    DOC_TYPE_INCOME, DOC_TYPE_LABELS, DOC_TYPE_PAYMENT_VOUCHER, DOC_TYPE_PREFIXES,
    DOC_TYPE_RECEIPT, THAI_TZ,
)
from services.finance.pdf import pdf_filename, render_receipt_html
from services.finance.receipts import ReceiptsMixin

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
TRANSACTIONS_PATH = API_PREFIX + "/{room}/finance/transactions"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"
RECEIPTS_PATH = API_PREFIX + "/{room}/finance/receipts"
RECEIPT_PATH = API_PREFIX + "/{room}/finance/receipts/{receipt_no}"
# ⚠️ `PDF_PATH` กับ `RECEIPT_PATH` ต่างกันแค่ `/pdf` ท้ายสุด **แต่ไม่ใช่เส้นทางเดียวกัน**:
#    `PDF_PATH` ไม่ประกาศ `response_model` (คืน binary stream) ส่วน `RECEIPT_PATH` ประกาศ
#    `ReceiptDetailResponse` ⇒ คีย์ที่โมเดลไม่ได้ประกาศจะถูกตัดทิ้งเงียบ ๆ **เฉพาะเส้นทางหลัง**
#    นี่คือสาเหตุที่เทสต์ใบสำคัญทุกตัวก่อนหน้านี้เขียวทั้งที่หน้าจอพัง (ดูเทสต์ข้อ 8)
PDF_PATH = API_PREFIX + "/{room}/finance/receipts/{receipt_no}/pdf"


def _url(template: str, room_id: int, **kwargs) -> str:
    """web ต้องส่ง `target_type=room` เสมอ (default ของ backend คือ server)"""
    return template.format(room=room_id, **kwargs) + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง",
                          balance: float = 0.0, **extra) -> int:
    cols, vals = ["room_id", "account_name", "balance"], [room_id, name, balance]
    for k, v in extra.items():
        cols.append(k)
        vals.append(v)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))
    async with pool.acquire() as conn:
        return await conn.fetchval(
            f"INSERT INTO finance_accounts ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            *vals,
        )


async def _insert_category(pool, room_id: int, name: str, kind: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, kind,
        )


async def _add_tx(client, headers, *, account_id: int, category_id: int, amount: float,
                  tx_type: str, description: str = "รายการทดสอบ",
                  payee_name: str | None = "คู่กรณีทดสอบ", **extra):
    body = {
        "account_id": account_id,
        "category_id": category_id,
        "amount": amount,
        "description": description,
        "transaction_type": tx_type,
        "user_name": "เหรัญญิก",
    }
    if payee_name is not None:
        body["payee_name"] = payee_name
    body.update(extra)
    return client.post(_url(TRANSACTIONS_PATH, headers.room_id), json=body, headers=headers)


def _revert(client, headers, transaction_id: int):
    """⚠️ ต้องใช้ `client.request("DELETE", ...)` — `TestClient.delete()` ไม่รับ `json=`"""
    return client.request(
        "DELETE", _url(TRANSACTION_PATH, headers.room_id, tx_id=transaction_id),
        json={"user_name": "เหรัญญิก"}, headers=headers,
    )


# ═══════════════════════════════════════════════════════════════════ DB helpers
async def _tx_row(pool, tx_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, transaction_type, amount, payee_name, approver_name,
                      attachment_count, description, created_at
               FROM finance_transactions WHERE id = $1""",
            tx_id,
        )
    return dict(row) if row else {}


async def _latest_tx_id(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM finance_transactions WHERE room_id = $1 ORDER BY id DESC LIMIT 1",
            room_id,
        )


async def _docs(pool, room_id: int, doc_type: str) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, receipt_no, doc_type, year_be, seq, amount, paid_total_after,
                      legacy_transaction_id, student_payment_id, student_id, collection_id,
                      issued_to_name, issued_by_name, note, status, voided_at, deleted_at,
                      event_at, issued_at, voucher_snapshot
               FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2 ORDER BY id""",
            room_id, doc_type,
        )
    return [dict(r) for r in rows]


async def _count(pool, table: str, where: str = "TRUE", *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE {where}", *args)


# ═══════════════════════════════════════════════════════════════ 1. "อีกฝ่าย" บังคับ
@pytest.mark.parametrize("tx_type", ["income", "expense"])
@pytest.mark.parametrize("bad_payee", [None, "", "   "])
async def test_transaction_without_a_counterparty_is_rejected_with_a_thai_400(
    client, db_pool, admin_headers, tx_type, bad_payee,
):
    """ทั้งรายรับและรายจ่ายต้องระบุ "อีกฝ่าย" — เอกสารพิมพ์ชื่อนั้นลงกระดาษจริง

    🔴 ต้องเป็น **400 ภาษาไทยที่บอกทางออก** ไม่ใช่ 422 ดิบของ Pydantic — นั่นคือเหตุผล
       ที่ `TransactionCreate.payee_name` เป็น `Optional` แล้วไปบังคับใน service

    🔴 และต้อง **ไม่ทิ้งร่องรอยอะไรลงฐานข้อมูลเลย** — ด่านอยู่ก่อนคำสั่งเขียนทุกคำสั่ง
       (เทสต์เช็ค `finance_transactions` = 0 ไม่ใช่แค่ status code)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, balance=1000.0)
    cat_id = await _insert_category(db_pool, room_id, "หมวดทดสอบ", tx_type)

    res = await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                        amount=100.0, tx_type=tx_type, payee_name=bad_payee)

    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "ผู้เบิก" in detail and "ผู้จ่ายเงิน" in detail, (
        f"ข้อความต้องบอกทางออกทั้งสองทิศ (ได้: {detail!r})"
    )
    assert await _count(db_pool, "finance_transactions", "room_id = $1", room_id) == 0
    assert await _count(db_pool, "finance_receipts", "room_id = $1", room_id) == 0


async def test_counterparty_is_stored_on_the_transaction_row(client, db_pool, admin_headers):
    """ชื่อ + ผู้อนุมัติ + จำนวนเอกสารแนบ ถูกเก็บที่ `finance_transactions` (แหล่งความจริงของรายการ)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, balance=1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    res = await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                        amount=250.0, tx_type="expense", payee_name="  ร้านป้าแดง  ",
                        approver_name="ครูสมศรี", attachment_count=2)
    assert res.status_code == 200, res.text

    row = await _tx_row(db_pool, await _latest_tx_id(db_pool, room_id))
    assert row["payee_name"] == "ร้านป้าแดง", "ต้อง strip ช่องว่างหัวท้ายก่อนเก็บ"
    assert row["approver_name"] == "ครูสมศรี"
    assert row["attachment_count"] == 2


# ═══════════════════════════════════════════════════ 2. รายรับ → ใบรับเงิน (income)
async def test_income_creates_exactly_one_income_document(client, db_pool, admin_headers):
    """รายรับที่บันทึกเอง ⇒ ใบรับเงิน 1 ใบ · ไม่ผูกบิล ไม่ผูกแคมเปญ ไม่ผูกนักเรียน"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    res = await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                        amount=1234.5, tx_type="income", description="ขายของที่ระลึก",
                        payee_name="ผู้ปกครองสมชาย")
    assert res.status_code == 200, res.text

    tx_id = await _latest_tx_id(db_pool, room_id)
    docs = await _docs(db_pool, room_id, DOC_TYPE_INCOME)
    assert len(docs) == 1, "ต้องออกใบรับเงิน **หนึ่ง** ใบต่อรายการ"

    doc = docs[0]
    assert doc["legacy_transaction_id"] == tx_id
    assert doc["student_payment_id"] is None, "ใบนี้ไม่มีบิล"
    assert doc["collection_id"] is None, "ใบนี้ไม่มีแคมเปญ"
    assert doc["student_id"] is None, (
        "🔴 ต้องเป็น NULL ไม่ใช่ 0 — `_merge_key` คืน None ให้ `student_id is None` "
        "⇒ ใบรับเงินทุกใบได้หน้าของตัวเอง ไม่ถูกยุบรวมเป็นหน้าไร้เจ้าของ"
    )
    assert float(doc["amount"]) == pytest.approx(1234.5)
    assert doc["issued_to_name"] == "ผู้ปกครองสมชาย", "ผู้จ่ายเงินคือ 'อีกฝ่าย' ของใบรับเงิน"
    assert doc["status"] == "active" and doc["deleted_at"] is None


async def test_income_document_renders_with_receipt_wording(client, db_pool, admin_headers):
    """ใบรับเงินต้องพูดแบบ **ใบเสร็จ** ไม่ใช่ใบแจ้งหนี้ — และไม่มี `None` หลุดขึ้นกระดาษ

    ← ล้มถ้า `DOC_TYPE_INCOME` หลุดจาก tuple `is_receipt` ใน `_document_context`
      (จะได้ "เรียกเก็บจาก"/"ยอดค้างชำระ" ผิดทั้งใบโดยไม่มี error ให้เห็น)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=500.0, tx_type="income", description="ขายขยะรีไซเคิล",
                          payee_name="ร้านรับซื้อของเก่า")).status_code == 200
    receipt_no = (await _docs(db_pool, room_id, DOC_TYPE_INCOME))[0]["receipt_no"]

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n% fake\n%%EOF\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text

    html = mock_render.await_args.args[0]
    assert ">None<" not in html and " None " not in html, "มี None หลุดขึ้นกระดาษ"
    for invoice_word in ("เรียกเก็บจาก", "ยอดค้างชำระ", "ผู้รับแจ้ง"):
        assert invoice_word not in html, (
            f"พบคำของ **ใบแจ้งหนี้** ('{invoice_word}') บนใบรับเงิน ⇒ "
            "เทมเพลตไม่ได้ branch ด้วย `is_receipt`"
        )
    assert "ได้รับเงินจาก" in html
    assert "ผู้ชำระเงิน" in html
    assert receipt_no in html
    assert "ร้านรับซื้อของเก่า" in html
    # 📝 คำอธิบายรายการต้องขึ้นกระดาษ (มิฉะนั้นใบนี้บอกไม่ได้ว่าเงินก้อนนี้คืออะไร)
    assert "ขายขยะรีไซเคิล" in html
    # 🚫 ห้ามตกไปที่คำกลาง ๆ ที่สื่อว่ามีบิลให้ชำระ
    assert "รายการชำระเงิน" not in html
    assert "ยอดค้างชำระรวม" not in html


async def test_income_context_is_a_receipt_but_a_voucher_is_not():
    """สัญญาที่เทมเพลตใช้ branch — ตรวจที่ `_document_context` ตรง ๆ (ไม่ต้องมี DB)"""
    income_ctx = ReceiptsMixin._document_context(_doc(DOC_TYPE_INCOME, "INC-2569-0001"))
    voucher_ctx = ReceiptsMixin._document_context(
        _doc(DOC_TYPE_PAYMENT_VOUCHER, "PV-2569-0001")
    )
    assert income_ctx["is_receipt"] is True
    assert voucher_ctx["is_receipt"] is False, (
        "ใบสำคัญจ่ายเป็น **เอกสารสั่งจ่าย** ไม่ใช่หลักฐานว่ารับเงิน ⇒ ต้องไม่เป็น receipt "
        "ไม่งั้นเทมเพลตจะพิมพ์ 'ได้รับเงินจาก' บนใบที่ยังไม่ได้จ่าย"
    )


def _doc(doc_type: str, receipt_no: str, *, amount: float = 100.0, **overrides) -> dict:
    """รูปร่างที่ `_shape_receipt_detail` ผลิตให้เอกสารที่ไม่มีบิล/แคมเปญ"""
    doc = {
        "doc_type": doc_type,
        "doc_type_label": DOC_TYPE_LABELS[doc_type],
        "receipt_no": receipt_no,
        "status": "active",
        "void_reason": None,
        "amount": amount,
        "paid_total_after": amount,
        "student_payment_id": None,
        "student_id": None,
        "collection_id": None,
        "collection_title": None,
        "collection_amount": None,
        "collection_due_date": None,
        "line_items": None,
        "issued_to_name": "คู่กรณีทดสอบ",
        "student_no": None,
        "issued_by_name": "เหรัญญิก",
        "issued_at": datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc),
        "event_at": datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc),
        "note": None,
        "room_name": "ห้อง ม.4/1",
        "room_code": "M4-1",
    }
    doc.update(overrides)
    return doc


# ═════════════════════════════════════════ 3. เลขเอกสาร: ปี พ.ศ. + ตัวนับแยก + กดซ้ำ
async def test_income_prefix_and_pattern_are_usable_as_a_path_parameter():
    """`INC-2569-0001` ต้องผ่าน `RECEIPT_NO_PATTERN` — pattern นั้นเป็น path param ของ PDF"""
    from services.finance.constants import RECEIPT_NO_PATTERN

    import re
    for doc_type in (DOC_TYPE_INCOME, DOC_TYPE_PAYMENT_VOUCHER):
        no = f"{DOC_TYPE_PREFIXES[doc_type]}-2569-0001"
        assert re.fullmatch(RECEIPT_NO_PATTERN, no), (
            f"เลข `{no}` ไม่ผ่าน pattern ⇒ ออกเอกสารได้แต่เปิดกลับไม่ได้ (422 ที่ GET {{no}}/pdf)"
        )


async def test_income_number_carries_the_event_year_be(client, db_pool, admin_headers):
    """ปี พ.ศ. บนเลข = ปีของ **เหตุการณ์** (created_at) ไม่ใช่วันที่พิมพ์

    🔴 และเลขต้องขึ้นต้นด้วย `INC-` (ไม่ใช่ `REC-`) — ตัวนับแยกต่อ `doc_type`
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=10.0, tx_type="income")).status_code == 200

    doc = (await _docs(db_pool, room_id, DOC_TYPE_INCOME))[0]
    created = doc["event_at"] or doc["issued_at"]
    expected_year = created.astimezone(THAI_TZ).year + 543
    assert doc["receipt_no"] == f"INC-{expected_year:04d}-0001", doc["receipt_no"]


async def test_income_sequence_is_independent_from_the_receipt_sequence(client, db_pool, admin_headers):
    """ห้อง/ปีเดียวกัน: ใบรับเงินเริ่มที่ 0001 ของตัวเอง ไม่ได้ต่อจากใบเสร็จ

    🔑 มาจาก PK ของ `receipt_sequences` = (room_id, year_be, doc_type) ⇒ ไม่ต้องมีตารางใหม่
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    # จองเลขใบเสร็จไปก่อนหนึ่งหมายเลข (เขียนแถว sequence ตรง ๆ — เทสต์นี้สนใจตัวนับ)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, 2569, $2, 7)
               ON CONFLICT (room_id, year_be, doc_type) DO UPDATE SET last_seq = 7""",
            room_id, DOC_TYPE_RECEIPT,
        )
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=10.0, tx_type="income")).status_code == 200
    doc = (await _docs(db_pool, room_id, DOC_TYPE_INCOME))[0]
    assert doc["receipt_no"].endswith("-0001"), (
        f"ตัวนับของ income ต้องเริ่มที่ 1 ของตัวเอง (ได้ {doc['receipt_no']})"
    )


async def _bare_transaction(pool, room_id: int, account_id: int, category_id: int,
                            amount: float = 99.0, kind: str = "income") -> tuple:
    """สร้าง `finance_transactions` **ตรง ๆ โดยไม่ออกเอกสาร** → (tx_id, created_at)

    🔴 จำเป็นสำหรับเทสต์ที่เล็ง **issuer** โดยตรง: ถ้าสร้างผ่าน `add_transaction` เอกสาร
       จะถูกออกไปแล้ว ⇒ เรียก issuer ซ้ำจะเจอ `_find_existing_income` แล้ว **return เร็ว
       ก่อนถึงโค้ดที่ต้องการทดสอบ** (ทั้งด่านเกินเลขและ SAVEPOINT) = เทสต์ที่เขียวโดย
       ไม่ได้ทดสอบอะไรเลย — กับดักเดียวกับ mutant ที่ไม่คอมไพล์ใน `docs/skills.md`
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO finance_transactions
                   (room_id, account_id, category_id, amount, description,
                    transaction_type, recorded_by)
               VALUES ($1, $2, $3, $4, 'รายการทดสอบ issuer', $5, 'Tester')
               RETURNING id, created_at""",
            room_id, account_id, category_id, amount, kind,
        )
    return row["id"], row["created_at"]


async def _issue_income(pool, room_id: int, tx_id: int, amount: float, user_id: int,
                        **overrides):
    """เรียก issuer หนึ่งครั้งใน transaction ของตัวเอง (ผู้เรียกเป็นเจ้าของ transaction)

    ⚠️ `event_at_db`/`issued_at_db` รับ override ได้ **โดยเจตนา**: ถ้าเทสต์ส่งค่าทั้งสอง
       เป็น instant เดียวกันเสมอ จะ **แยกไม่ออก** ว่าเลขมาจากตัวไหน ⇒ mutant ที่สลับแหล่ง
       ที่มาของปี พ.ศ. จะรอดทั้งที่โค้ดผิด (บทเรียนจาก M6 — ดู `docs/skills.md`)
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            now = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
            return await ReceiptsMixin._issue_income_doc(
                conn, room_id, tx_id, amount, "ผู้จ่ายทดสอบ", user_id, "เหรัญญิก", None,
                event_at_db=overrides.pop("event_at_db", now),
                issued_at_db=overrides.pop("issued_at_db", now),
                **overrides,
            )


async def test_issuing_twice_for_the_same_transaction_reuses_the_number(db_pool, admin_headers):
    """idempotency ของ issuer — เรียกซ้ำด้วย transaction เดิมต้องได้ **เลขเดิม** และไม่กินเลข

    ⚠️ ทดสอบที่ระดับ issuer โดยตรง เพราะผ่าน API ไม่มีทางเรียกซ้ำได้ (`add_transaction`
       สร้าง `finance_transactions` แถวใหม่ทุกครั้ง ⇒ `transaction_id` ใหม่เสมอ)
       — เหตุผลเดียวกับที่ mutant ของ `_issue_deposit` เป็น equivalent (ดู `docs/skills.md`)

    🔴 และนี่คือเทสต์ที่จับกับดัก **"จับ `UniqueViolationError` แล้วอ่าน `conn` ต่อ
       ใน transaction ที่ aborted"** (`25P02`) — ถ้า issuer ไม่มี SAVEPOINT ครอบ INSERT
       การเรียกครั้งที่สองจะไม่ได้ `reused=True` แต่ได้ 500 (เว้นแต่ `_find_existing`
       ชั้นแรกจะเจอก่อน ซึ่งจะจริงเฉพาะเส้นทางที่ไม่มีอะไรแข่ง)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id)

    first = await _issue_income(db_pool, room_id, tx_id, 99.0, admin_headers.user_id)
    second = await _issue_income(db_pool, room_id, tx_id, 99.0, admin_headers.user_id)

    assert first["reused"] is False, "การออกครั้งแรกต้องเป็นการสร้างใหม่"
    assert second["reused"] is True, (
        "เรียกซ้ำต้องคืนใบเดิมด้วย `reused=True` ไม่ใช่ระเบิด — ถ้าได้ exception "
        "แปลว่า INSERT ไม่มี SAVEPOINT ครอบ"
    )
    assert first["receipt"]["receipt_no"] == second["receipt"]["receipt_no"]
    assert len(await _docs(db_pool, room_id, DOC_TYPE_INCOME)) == 1
    async with db_pool.acquire() as conn:
        last_seq = await conn.fetchval(
            "SELECT last_seq FROM receipt_sequences WHERE room_id = $1 AND doc_type = $2",
            room_id, DOC_TYPE_INCOME,
        )
    assert last_seq == 1, f"กดซ้ำต้องไม่กินเลข (last_seq = {last_seq})"


async def test_income_seq_overflow_is_rejected_before_writing(db_pool, admin_headers):
    """เกิน 4 หลัก = เลขยาวจน path param ไม่รับ ⇒ ต้องปฏิเสธ **ก่อน** เขียนแถว

    ที่ต้องปฏิเสธคือตอนจองเลข: ถ้าปล่อยให้ INSERT สำเร็จแล้วเปิดเอกสารกลับไม่ได้
    จะได้ใบที่อยู่ในระบบตลอดกาลแต่ไม่มีทางเปิดดู (และเลขถูกเผาไปแล้ว)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id)

    from services.finance.constants import RECEIPT_SEQ_MAX
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, 2569, $2, $3)
               ON CONFLICT (room_id, year_be, doc_type) DO UPDATE SET last_seq = $3""",
            room_id, DOC_TYPE_INCOME, RECEIPT_SEQ_MAX,
        )

    with pytest.raises(ValueError):
        await _issue_income(db_pool, room_id, tx_id, 10.0, admin_headers.user_id)

    assert await _docs(db_pool, room_id, DOC_TYPE_INCOME) == [], "ต้องไม่มีแถวถูกเขียน"


# ══════════════════════════════════════════════ 4. โอนเงิน / ชนิดอื่นไม่ผลิตเอกสาร
async def test_transfer_money_creates_no_document(client, db_pool, admin_headers):
    """โอนระหว่างกระเป๋า = net-zero ภายในห้อง · ไม่มีผู้เบิก ไม่มีหมวดงบ ⇒ ห้ามออกเอกสาร

    (วันนี้ก็ไม่ออก — เทสต์นี้ล็อกเจตนาไว้ไม่ให้มีคน 'เพิ่มความสม่ำเสมอ' ทีหลัง)
    """
    room_id = admin_headers.room_id
    src = await _insert_account(db_pool, room_id, "ต้นทาง", 1000.0)
    dst = await _insert_account(db_pool, room_id, "ปลายทาง", 0.0)

    res = client.post(
        _url(API_PREFIX + "/{room}/finance/transfer", room_id),
        json={"from_account_id": src, "to_account_id": dst, "amount": 300.0,
              "description": "โอนเข้าบัญชีกลาง", "user_name": "เหรัญญิก"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert await _count(db_pool, "finance_receipts", "room_id = $1", room_id) == 0


# ══════════════════════════════════════════════ 5. รับคืนรายการ → เอกสารต้องถูกยกเลิก
async def test_revert_of_an_income_voids_its_income_document(client, db_pool, admin_headers):
    """🔴 ตัวที่จับ `revert_transaction` ที่ลืมเพิ่ม `income` เข้า `$5`

    ถ้าลืม: ใบรับเงินยัง `active` + `deleted_at IS NULL` ทั้งที่เงินถูกคืนจากกระเป๋าแล้ว
    ⇒ เอกสารยืนยันเงินที่ไม่มีอยู่ — และ **ไม่มี error อะไรเกิดขึ้นเลย**
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=400.0, tx_type="income")).status_code == 200
    tx_id = await _latest_tx_id(db_pool, room_id)
    assert len(await _docs(db_pool, room_id, DOC_TYPE_INCOME)) == 1

    res = _revert(client, admin_headers, tx_id)
    assert res.status_code == 200, res.text

    doc = (await _docs(db_pool, room_id, DOC_TYPE_INCOME))[0]
    assert doc["status"] == "voided", "ใบรับเงินของรายการที่ถูกรับคืนต้องถูกยกเลิก"
    assert doc["voided_at"] is not None
    assert doc["deleted_at"] is not None, (
        "ต้องเป็น soft-delete ด้วย — `chk_receipt_voided_is_deleted` บังคับว่าสถานะยกเลิก "
        "ต้องมาคู่กับ `deleted_at`"
    )


async def test_voided_income_document_is_not_reissued_by_a_later_topup(client, db_pool, admin_headers):
    """หลัง revert ใบที่ถูกยกเลิกต้อง **ไม่นับว่า 'ออกไปแล้ว'** ⇒ บันทึกใหม่ได้ใบใหม่"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                  amount=400.0, tx_type="income")
    first_no = (await _docs(db_pool, room_id, DOC_TYPE_INCOME))[0]["receipt_no"]
    assert _revert(client, admin_headers, await _latest_tx_id(db_pool, room_id)).status_code == 200

    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=400.0, tx_type="income")).status_code == 200
    docs = await _docs(db_pool, room_id, DOC_TYPE_INCOME)
    assert len(docs) == 2
    active = [d for d in docs if d["status"] == "active"]
    assert len(active) == 1 and active[0]["receipt_no"] != first_no


# ══════════════════════════════════════════ 6. เลขเอกสารต้องรอดถึงหน้าจอ + ทะเบียน + ชื่อไฟล์
async def test_add_transaction_response_carries_the_document_number(client, db_pool, admin_headers):
    """🔴 ตัวที่จับ `response_model` ที่ตัดฟิลด์ทิ้งเงียบ ๆ

    ก่อนมี `TransactionCreateResponse` ผู้ใช้บันทึกรายจ่ายสำเร็จ แต่ **ไม่รู้เลขเอกสาร**
    ทั้งที่มันถูกเขียนลง DB แล้ว และไม่มีอะไรฟ้องเลย
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")

    res = await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                        amount=77.0, tx_type="income")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("receipt_no"), f"เลขเอกสารถูกตัดทิ้ง: {body}"
    assert body["doc_type"] == DOC_TYPE_INCOME
    assert body["doc_type_label"] == DOC_TYPE_LABELS[DOC_TYPE_INCOME]
    assert body["receipt_no"] in body["message"], "ข้อความต้องบอกเลขที่ออกให้ด้วย"


@pytest.mark.parametrize("doc_type", sorted(DOC_TYPE_LABELS))
async def test_pdf_filename_covers_every_doc_type(doc_type):
    """ชื่อไฟล์ต้องไม่ตกไปที่ default `document-…` ของชนิดใด ๆ ที่ประกาศไว้

    🔑 parametrize บน `DOC_TYPE_LABELS` ⇒ **ชนิดใหม่ในอนาคตได้เทสต์ฟรี**
       (เพิ่มป้ายแต่ลืมเพิ่มชื่อไฟล์ = เทสต์นี้ล้มทันที)
    """
    name = pdf_filename(f"{DOC_TYPE_PREFIXES[doc_type]}-2569-0001", doc_type)
    assert not name.startswith("document-"), (
        f"ชนิด '{doc_type}' ไม่มีคีย์ใน dict ของ `pdf_filename` ⇒ ชื่อไฟล์โกหก"
    )
    assert name == f"{doc_type}-{DOC_TYPE_PREFIXES[doc_type]}-2569-0001.pdf"


async def test_receipts_registry_accepts_the_new_doc_type_filters(client, db_pool, admin_headers):
    """chip ตัวกรองบนหน้าทะเบียนต้องไม่ 422 — router เป็น **whitelist เดียว** ของ `doc_type`"""
    room_id = admin_headers.room_id
    for doc_type in (DOC_TYPE_INCOME, DOC_TYPE_PAYMENT_VOUCHER):
        res = client.get(
            _url(RECEIPTS_PATH, room_id) + f"&doc_type={doc_type}", headers=admin_headers,
        )
        assert res.status_code == 200, f"doc_type={doc_type} → {res.status_code}: {res.text}"


async def test_income_documents_never_merge_into_one_page(client, db_pool, admin_headers):
    """ใบรับเงินทุกใบมี `student_id = NULL` ⇒ **ห้ามยุบรวมกัน** เด็ดขาด

    ถ้ายุบ: ใบรับเงินของหลายรายการจะกองเป็นหน้าเดียวที่ไม่มีเจ้าของ และยอดรวมเดียว
    ที่ไม่ตรงกับเอกสารใด ๆ (การยุบต้องใช้ `student_id` เป็นคีย์ ไม่ใช่ชื่อ)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    for amount in (100.0, 200.0, 300.0):
        assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                              amount=amount, tx_type="income")).status_code == 200

    docs = await _docs(db_pool, room_id, DOC_TYPE_INCOME)
    assert len(docs) == 3
    shaped = [ReceiptsMixin._shape_receipt(r) for r in docs]
    contexts = ReceiptsMixin._document_contexts(shaped)
    assert len(contexts) == 3, (
        "ใบรับเงินทุกใบต้องได้หน้าของตัวเอง (student_id NULL ⇒ `_merge_key` ต้องคืน None)"
    )
    assert all(c["is_merged"] is False for c in contexts)


async def test_income_document_renders_as_a_receipt_body():
    """เรนเดอร์จริงผ่าน Jinja — กันเทมเพลตพังเงียบ ๆ ตอนเพิ่มสาขาของ `income`"""
    html = render_receipt_html(ReceiptsMixin._document_context(_doc(DOC_TYPE_INCOME, "INC-2569-0001")))
    assert "{{" not in html and "{%" not in html
    assert "INC-2569-0001" in html
    assert "รับเงินเข้าห้อง" in html
    assert "ยังไม่หักปิดบิลใด" not in html, (
        "ถ้อยคำนั้นเป็นของใบ DEP (มีบิลรออยู่จริง) — รายรับที่บันทึกเองจะไม่มีวันมีบิล"
    )


# ══════════════════════════════════════════ 7. รายจ่าย → ใบสำคัญจ่าย (payment_voucher)
async def _insert_budget(pool, room_id: int, category_id: int, *, start: str, end: str,
                         amount: float, period_type: str = "monthly") -> int:
    """งบหนึ่งก้อน — `finance_budgets` ไม่มี FK ไปหารายการ ผูกด้วยช่วงวันที่เท่านั้น

    🔴 ต้องส่ง `date` object ไม่ใช่สตริง ISO: Postgres อนุมานชนิดของ `$5` เป็น DATE
       (จากคอลัมน์ปลายทาง) ⇒ asyncpg จะเรียก `.toordinal()` บนค่าที่ส่งมา และสตริง
       จะพังด้วย `DataError: 'str' object has no attribute 'toordinal'`
       (กฎเดียวกับ `docs/rules/backend.md`: "Date params must be typed `date`/`datetime`,
        never `str`" — และนี่คือเทสต์ที่พิสูจน์ว่าทำไมกฎนั้นถึงมี)
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_budgets
                   (room_id, category_id, period_type, period_year, start_date, end_date, amount)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            room_id, category_id, period_type,
            date.fromisoformat(start).year, date.fromisoformat(start), date.fromisoformat(end),
            amount,
        )


# 🔭 ช่วงกว้างพอครอบ "วันนี้" เสมอ — เทสต์ไม่ควรผูกกับนาฬิกาของวันที่รัน
#    (และไม่ใช้ `date.today()` ฝั่งเทสต์เทียบกับ `CURRENT_TIMESTAMP` ฝั่ง DB:
#     สองนาฬิกาคนละเรือน และเทสต์จะพังเฉพาะตอนรันข้ามเที่ยงคืน)
_WIDE_START, _WIDE_END = "2020-01-01", "2035-12-31"


async def _issue_voucher(pool, room_id: int, tx_id: int, amount: float, user_id: int,
                         account_id: int, category_id: int, **overrides):
    """เรียก issuer ใบสำคัญหนึ่งครั้งใน transaction ของตัวเอง (`_issue_income` ของฝั่งจ่าย)"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            now = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
            return await ReceiptsMixin._issue_payment_voucher(
                conn, room_id, tx_id, amount, overrides.pop("payee_name", "ผู้เบิกทดสอบ"),
                user_id, "เหรัญญิก", overrides.pop("note", None),
                event_at_db=overrides.pop("event_at_db", now),
                issued_at_db=overrides.pop("issued_at_db", now),
                account_id=account_id, category_id=category_id,
                approver_name=overrides.pop("approver_name", None),
                attachment_count=overrides.pop("attachment_count", 0),
                **overrides,
            )


async def _voucher_html(client, db_pool, headers, room_id: int, receipt_no: str) -> str:
    """เรนเดอร์ใบสำคัญเป็น HTML จริง (ดัก `html_to_pdf` — ไม่ต้องมี Gotenberg)

    🔴 ใช้เส้นทาง **HTTP จริง** ไม่เรียก `_document_context` ตรง ๆ โดยเจตนา: สิ่งที่ต้อง
       พิสูจน์คือ "ข้อมูลจาก `voucher_snapshot` วิ่งถึงกระดาษครบ" ซึ่งต้องผ่านทั้ง
       `get_receipt` (SELECT) → `_shape_receipt_detail` (คลี่ jsonb) → เทมเพลต
       ⇒ เทสต์ที่เรียก `_document_context` ตรง ๆ จะข้ามสองจุดแรกไปทั้งหมด
    """
    mock_render = AsyncMock(return_value=b"%PDF-1.4\n% fake\n%%EOF\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=headers)
    assert res.status_code == 200, res.text
    return mock_render.await_args.args[0]


async def test_expense_creates_exactly_one_payment_voucher(client, db_pool, admin_headers):
    """รายจ่ายที่บันทึกเอง ⇒ ใบสำคัญจ่าย 1 ใบ พร้อมข้อมูล 3 ตัวที่ผู้ใช้ขอ (สเปก 5 ส่วน)

    🔴 `student_id` ต้องเป็น NULL — ถ้าเผลอใส่อะไรลงไป ใบสำคัญจะถูก `_document_contexts`
       ยุบรวมกับเอกสารอื่นของนักเรียนคนนั้นเป็นหน้าเดียว (เอกสารสั่งจ่ายปนกับใบเสร็จ)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    res = await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                        amount=250.0, tx_type="expense", description="ซื้อของเข้าห้อง",
                        payee_name="ร้านป้าแดง", approver_name="ครูสมศรี", attachment_count=2)
    assert res.status_code == 200, res.text

    tx_id = await _latest_tx_id(db_pool, room_id)
    docs = await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER)
    assert len(docs) == 1, "ต้องออกใบสำคัญจ่าย **หนึ่ง** ใบต่อรายการ"

    doc = docs[0]
    assert doc["legacy_transaction_id"] == tx_id
    assert doc["student_payment_id"] is None, "ใบนี้ไม่มีบิล"
    assert doc["collection_id"] is None
    assert doc["student_id"] is None, (
        "NULL ⇒ `_merge_key` คืน None ⇒ ใบสำคัญไม่ถูกยุบรวมกับเอกสารใด"
    )
    assert float(doc["amount"]) == pytest.approx(250.0)
    assert doc["issued_to_name"] == "ร้านป้าแดง", "ผู้เบิก/ผู้รับเงิน คือ 'อีกฝ่าย' ของรายจ่าย"
    assert doc["note"] == "ซื้อของเข้าห้อง"
    assert doc["status"] == "active" and doc["deleted_at"] is None

    snapshot = ReceiptsMixin._parse_voucher_snapshot(doc["voucher_snapshot"])
    assert snapshot is not None, "`voucher_snapshot` ต้องเป็น dict หลัง `json.loads`"
    assert snapshot["approver_name"] == "ครูสมศรี"
    assert snapshot["attachment_count"] == 2, "จำนวนเอกสารแนบต้องถูกเก็บเป็น snapshot"
    assert snapshot["category_name"] == "ค่าอาหาร"
    assert snapshot["account_name"] == "กองกลาง"
    assert snapshot["channel"] == "cash", "กระเป๋าที่ไม่ได้ตั้งค่า = เงินสด (default ของคอลัมน์)"

    # 🧾 เลขเอกสารต้องรอดถึงหน้าจอ (response_model ไม่ตัดทิ้ง)
    body = res.json()
    assert body["receipt_no"] == doc["receipt_no"]
    assert body["doc_type"] == DOC_TYPE_PAYMENT_VOUCHER
    assert body["doc_type_label"] == DOC_TYPE_LABELS[DOC_TYPE_PAYMENT_VOUCHER]


async def test_revert_of_an_expense_voids_its_voucher(client, db_pool, admin_headers):
    """🔴 ตัวที่จับ `revert_transaction` ที่ลืมเพิ่ม `payment_voucher` เข้า `$5`

    ถ้าลืม: ใบสำคัญยัง `active` ทั้งที่รายการถูกยกเลิกและเงินถูกคืนเข้าถระเป๋าแล้ว
    ⇒ ระบบถือ "หลักฐานการจ่าย" ที่ขัดกับยอดเงินจริง และไม่มี error อะไรฟ้องเลย
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=400.0, tx_type="expense")).status_code == 200
    tx_id = await _latest_tx_id(db_pool, room_id)
    assert len(await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER)) == 1

    res = _revert(client, admin_headers, tx_id)
    assert res.status_code == 200, res.text

    doc = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]
    assert doc["status"] == "voided", "ใบสำคัญของรายการที่ถูกรับคืนต้องถูกยกเลิก"
    assert doc["voided_at"] is not None
    assert doc["deleted_at"] is not None, (
        "ต้องเป็น soft-delete ด้วย — `chk_receipt_voided_is_deleted` บังคับว่า "
        "สถานะยกเลิกต้องมาคู่กับ `deleted_at`"
    )


async def test_voucher_number_carries_the_event_year_be(client, db_pool, admin_headers):
    """เลขใบสำคัญขึ้นต้น `PV-` และปี พ.ศ. มาจาก **เหตุการณ์** ไม่ใช่วันที่พิมพ์"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=10.0, tx_type="expense")).status_code == 200

    doc = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]
    expected_year = doc["event_at"].astimezone(THAI_TZ).year + 543
    assert doc["receipt_no"] == f"PV-{expected_year:04d}-0001", doc["receipt_no"]


async def test_voucher_timezone_year_comes_from_the_thai_calendar_day(db_pool, admin_headers):
    """🔴 17:30 UTC ของ 31 ธ.ค. = 00:30 ไทยของ 1 ม.ค. ปีถัดไป ⇒ เลขต้องข้ามปีตามไทย

    ← ล้มถ้า issuer คิดปีจาก **วัน UTC** (จะได้ 2569) ⇒ พิสูจน์ว่าวันไทยถูกใช้จริง

    🔴 **เทสต์นี้พิสูจน์ "แหล่งที่มาของปี" ไม่ได้** — มันส่ง `event_at_db` กับ
       `issued_at_db` เป็น instant เดียวกัน ⇒ สลับแหล่งแล้วผลเท่าเดิม · เดิม docstring
       อ้างว่าจับ "ใช้ `issued_at_db`" ซึ่ง **ไม่จริง** (mutation harness จับได้: M6 รอด)
       ⇒ แยกหน้าที่: ตัวนี้คุม "วันไทย" · ตัวถัดไปคุม "แหล่งที่มา"
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id, kind="expense")

    crossed = datetime(2026, 12, 31, 17, 30, tzinfo=timezone.utc)
    issued = await _issue_voucher(
        db_pool, room_id, tx_id, 50.0, admin_headers.user_id, account_id, cat_id,
        event_at_db=crossed, issued_at_db=crossed,
    )
    assert issued["receipt"]["receipt_no"] == "PV-2570-0001", (
        f"ต้องเป็นปีไทย (2570) ไม่ใช่วัน UTC (2569) — ได้ {issued['receipt']['receipt_no']}"
    )


async def test_voucher_year_comes_from_the_event_not_the_issue_time(db_pool, admin_headers):
    """🔴 ปี พ.ศ. ต้องมาจาก **เหตุการณ์** ไม่ใช่วันที่พิมพ์เอกสาร

    🎯 นี่คือเทสต์ที่ **แยกสองแหล่งออกจากกันได้จริง** — เป็นคู่ของตัวบน:
      • `event_at_db` = 10:00 UTC ของ 31 ธ.ค. → ไทย 17:00 ของ 31 ธ.ค. → **2569**
      • `issued_at_db` = 17:30 UTC ของ 31 ธ.ค. → ไทย 00:30 ของ 1 ม.ค. → **2570**
    ⇒ ถ้า issuer เผลอใช้ `issued_at_db` จะได้ `PV-2570-0001` **ไม่ใช่** `PV-2569-0001`
      (mutation M6 ตายที่นี่ — ก่อนหน้านี้รอดเพราะไม่มีเทสต์ใดแยกสองแหล่งได้)

    ⚠️ ลำดับที่สมจริง: รายการเกิดเวลา 17:00 ไทย แล้ว **ออกเอกสารข้ามเที่ยงคืนไทย**
       (เช่น พิมพ์ซ้ำ/คิวตกหล่น) ⇒ `issued_at` มาก่อน— หลัง `event_at` ไม่สำคัญต่อสัญญานี้
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id, kind="expense")

    issued = await _issue_voucher(
        db_pool, room_id, tx_id, 50.0, admin_headers.user_id, account_id, cat_id,
        # ไทย 31 ธ.ค. 2569 17:00 → ปีของเหตุการณ์คือ 2569
        event_at_db=datetime(2026, 12, 31, 10, 0, tzinfo=timezone.utc),
        # ไทย 1 ม.ค. 2570 00:30 → ปีของ "วันที่พิมพ์" คือ 2570 (ต้องไม่ถูกใช้)
        issued_at_db=datetime(2026, 12, 31, 17, 30, tzinfo=timezone.utc),
    )
    assert issued["receipt"]["receipt_no"] == "PV-2569-0001", (
        "เลขต้องใช้ปีของ **เหตุการณ์** (2569) ไม่ใช่ปีของวันที่พิมพ์ (2570) — ได้ "
        f"{issued['receipt']['receipt_no']}"
    )


async def test_income_year_comes_from_the_event_not_the_issue_time(db_pool, admin_headers):
    """คู่แฝดของใบสำคัญ — ปีของ `INC-…` ต้องมาจาก `event_at_db` เช่นกัน

    🔴 เขียนคู่กันโดยเจตนา: `_issue_income_doc` เป็นฟังก์ชัน **คนละตัว** กับ
       `_issue_payment_voucher` ⇒ เทสต์ของตัวหนึ่งไม่ได้คุมอีกตัว (ต่างจากที่มักเข้าใจผิด
       ว่า "issuer พี่น้องกัน ย่อมเหมือนกัน") · ตรรกะเดียวกับ
       `test_income_sequence_is_independent_from_the_receipt_sequence`
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id)

    issued = await _issue_income(
        db_pool, room_id, tx_id, 50.0, admin_headers.user_id,
        event_at_db=datetime(2026, 12, 31, 10, 0, tzinfo=timezone.utc),   # ไทย 2569
        issued_at_db=datetime(2026, 12, 31, 17, 30, tzinfo=timezone.utc),  # ไทย 2570
    )
    assert issued["receipt"]["receipt_no"] == "INC-2569-0001", (
        "เลขต้องใช้ปีของ **เหตุการณ์** (2569) ไม่ใช่ปีของวันที่พิมพ์ (2570) — ได้ "
        f"{issued['receipt']['receipt_no']}"
    )


async def test_voucher_reprint_is_idempotent_and_returns_the_same_number(db_pool, admin_headers):
    """กดซ้ำต้องได้เลขเดิม (`reused=True`) และ **ไม่กินเลข** ใน `receipt_sequences`

    🔴 นี่คือเทสต์ที่จับกับดัก "จับ `UniqueViolationError` แล้วอ่าน `conn` ต่อใน
       transaction ที่ aborted" ⇒ ต้องได้ `reused=True` ไม่ใช่ 500
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id, kind="expense")

    first = await _issue_voucher(db_pool, room_id, tx_id, 99.0, admin_headers.user_id,
                                 account_id, cat_id)
    second = await _issue_voucher(db_pool, room_id, tx_id, 99.0, admin_headers.user_id,
                                  account_id, cat_id)

    assert first["reused"] is False
    assert second["reused"] is True, "เรียกซ้ำต้องคืนใบเดิม ไม่ใช่ระเบิด"
    assert first["receipt"]["receipt_no"] == second["receipt"]["receipt_no"]
    assert len(await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER)) == 1
    async with db_pool.acquire() as conn:
        last_seq = await conn.fetchval(
            "SELECT last_seq FROM receipt_sequences WHERE room_id = $1 AND doc_type = $2",
            room_id, DOC_TYPE_PAYMENT_VOUCHER,
        )
    assert last_seq == 1, f"กดซ้ำต้องไม่กินเลข (last_seq = {last_seq})"


async def test_voucher_sequence_is_independent_per_doc_type(client, db_pool, admin_headers):
    """ห้อง/ปีเดียวกัน: ใบเสร็จกับใบสำคัญต่างคนต่างเริ่ม 0001 (`receipt_sequences` PK แยกชนิด)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")

    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, 2569, $2, 7)
               ON CONFLICT (room_id, year_be, doc_type) DO UPDATE SET last_seq = 7""",
            room_id, DOC_TYPE_RECEIPT,
        )
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=10.0, tx_type="expense")).status_code == 200

    doc = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]
    assert doc["receipt_no"].endswith("-0001"), (
        f"ตัวนับของใบสำคัญต้องเริ่มที่ 1 ของตัวเอง (ได้ {doc['receipt_no']})"
    )


async def test_voucher_seq_overflow_is_rejected_before_writing(db_pool, admin_headers):
    """เกิน 4 หลัก = path param ไม่รับ ⇒ ปฏิเสธ **ก่อน** เขียนแถว (ไม่เผาเลขทิ้ง)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    tx_id, _ = await _bare_transaction(db_pool, room_id, account_id, cat_id, kind="expense")

    from services.finance.constants import RECEIPT_SEQ_MAX
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, 2569, $2, $3)
               ON CONFLICT (room_id, year_be, doc_type) DO UPDATE SET last_seq = $3""",
            room_id, DOC_TYPE_PAYMENT_VOUCHER, RECEIPT_SEQ_MAX,
        )

    with pytest.raises(ValueError):
        await _issue_voucher(db_pool, room_id, tx_id, 10.0, admin_headers.user_id,
                             account_id, cat_id)

    assert await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER) == [], "ต้องไม่มีแถวถูกเขียน"


# ───────────────────────────────────── บล็อก "หมวดหมู่งบประมาณ" (F2) บนใบสำคัญ
async def test_voucher_prints_a_covering_budget(client, db_pool, admin_headers):
    """งบที่ครอบวันจ่าย ⇒ ตารางงบของใบสำคัญมีบรรทัดของงบนั้น (ดึงจากระบบงบ F2)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_budget(db_pool, room_id, cat_id, start=_WIDE_START, end=_WIDE_END,
                         amount=5000.0)

    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense")).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "งบประมาณที่รองรับรายการนี้" in html
    assert "5,000.00" in html, "วงเงินของงบต้องขึ้นกระดาษ"
    assert "1 ม.ค. 2563" in html and "31 ธ.ค. 2578" in html, (
        "ช่วงงบต้องเป็นวันที่ไทยแบบเดียวกับวันที่อื่นทั้งใบ"
    )
    assert "ไม่อยู่ในงบประมาณที่ตั้งไว้" not in html
    assert "มากกว่าหนึ่งช่วง" not in html, "งบก้อนเดียวต้องไม่ขึ้นคำเตือนนับซ้ำ"
    assert ">None<" not in html


async def test_voucher_prints_explicit_text_when_no_budget_covers_it(client, db_pool, admin_headers):
    """🔴 ไม่ตรงงบ = **พิมพ์ออกมาว่าไม่ตรง** ห้ามเว้นว่าง

    ช่องว่างในตารางงบอ่านได้ว่า "มีงบและใช้ได้" ทั้งที่ความจริงคือ "ยังไม่ได้ตั้งงบ"
    ⇒ เอกสารที่โกหกในทิศทางที่อันตรายกว่า (อนุมัติรายจ่ายที่ไม่มีงบรองรับ)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    # งบที่มีอยู่แต่ **ไม่ครอบ** วันจ่าย (ช่วงปี 2020 ล้วน)
    await _insert_budget(db_pool, room_id, cat_id, start="2020-01-01", end="2020-12-31",
                         amount=5000.0)

    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense")).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "⚠️ ไม่อยู่ในงบประมาณที่ตั้งไว้" in html
    assert "ค่าอาหาร" in html, "ต้องบอกด้วยว่าหมวดไหนที่ไม่มีงบ"
    assert "5,000.00" not in html, "งบที่ไม่ครอบต้องไม่ถูกพิมพ์เป็นงบของรายการนี้"


async def test_voucher_prints_all_covering_budgets_when_periods_overlap(client, db_pool,
                                                                        admin_headers):
    """งบซ้อนช่วงกันได้จริง (unique index คือ `(room, category, start, end)`) ⇒ พิมพ์ **ทุกก้อน**

    🔴 เลือกพิมพ์ก้อนแรก = โกหก: ผู้อนุมัติเห็นวงเงินเดียวทั้งที่มีสองก้อนรองรับ
       และยอดเดียวกันจะถูกนับซ้ำในการสรุปรวมโดยไม่มีใครรู้
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_budget(db_pool, room_id, cat_id, start="2020-01-01", end="2035-12-31",
                         amount=5000.0)
    await _insert_budget(db_pool, room_id, cat_id, start="2021-01-01", end="2034-12-31",
                         amount=3000.0)

    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense")).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "5,000.00" in html and "3,000.00" in html, "ต้องพิมพ์ทั้งสองก้อน"
    assert "มากกว่าหนึ่งช่วง" in html, "ต้องเตือนเรื่องการนับซ้ำ"
    assert "ไม่อยู่ในงบประมาณที่ตั้งไว้" not in html


async def test_voucher_budget_block_is_a_snapshot_not_recomputed(client, db_pool, admin_headers):
    """🔴 งบที่ถูกแก้/ลบ **หลัง** ออกเอกสาร ต้องไม่ย้อนไปเปลี่ยนกระดาษที่พิมพ์ไปแล้ว

    (สัญญาเดียวกับ `line_items` ของใบแจ้งหนี้ — `docs/skills.md`: เอกสารที่แจกแจง
     รายการต้อง snapshot ห้าม recompute ตอนพิมพ์)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    budget_id = await _insert_budget(db_pool, room_id, cat_id, start=_WIDE_START,
                                     end=_WIDE_END, amount=5000.0)

    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense")).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]

    before = await _voucher_html(client, db_pool, admin_headers, room_id, no)
    assert "5,000.00" in before

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE finance_budgets SET amount = 999999 WHERE id = $1", budget_id)
        await conn.execute(
            "UPDATE finance_budgets SET deleted_at = CURRENT_TIMESTAMP WHERE id = $1", budget_id,
        )

    after = await _voucher_html(client, db_pool, admin_headers, room_id, no)
    assert after == before, "กระดาษเปลี่ยนตามงบที่ถูกแก้ทีหลัง = snapshot ไม่ทำงาน"
    assert "999,999.00" not in after


# ─────────────────────────────────────────────── เทมเพลต + ช่องทางจ่าย
async def test_voucher_renders_with_voucher_wording(client, db_pool, admin_headers):
    """ใบสำคัญจ่ายต้องพูดแบบ **เอกสารสั่งจ่าย** พร้อมลายมือชื่อ 3 ฝ่ายตามสเปกของผู้ใช้"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense", description="ซื้อของเข้าห้อง",
                          payee_name="ร้านป้าแดง", approver_name="ครูสมศรี",
                          attachment_count=2)).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "{{" not in html and "{%" not in html, "เทมเพลตยังไม่ถูกเรนเดอร์"
    assert ">None<" not in html and " None " not in html, "มี None หลุดขึ้นกระดาษ"

    # 1. ส่วนหัว + 2. ผู้เบิก + 3. รายละเอียด + 4. เอกสารแนบ + 5. ลายมือชื่อ 3 ฝ่าย
    assert "ใบสำคัญจ่าย" in html
    assert no in html
    assert "ผู้เบิก/ผู้รับเงิน" in html and "ร้านป้าแดง" in html
    assert "จ่ายเงินผ่าน" in html and "เงินสด" in html
    assert "หมวดหมู่งบประมาณ" in html and "ค่าอาหาร" in html
    assert "แนบหลักฐานมาแล้ว 2 ใบ" in html
    assert "ซื้อของเข้าห้อง" in html
    for role in ("ผู้เบิกรับเงิน", "ผู้จ่ายเงิน (เหรัญญิก)", "ผู้อนุมัติ (หัวหน้าห้อง)"):
        assert role in html, f"ขาดช่องลายมือชื่อฝ่าย '{role}'"
    assert "ครูสมศรี" in html, "ชื่อผู้อนุมัติ (ถ้ามี) ต้องขึ้นช่องที่สาม"

    # 🚫 ถ้อยคำของ **ใบเสร็จ/ใบแจ้งหนี้** ต้องไม่หลุดมาบนใบสั่งจ่าย
    for wrong in ("ได้รับเงินจาก", "เรียกเก็บจาก", "ยอดค้างชำระ", "ผู้รับแจ้ง", "ผู้ชำระเงิน"):
        assert wrong not in html, (
            f"พบ '{wrong}' บนใบสำคัญจ่าย ⇒ เทมเพลตตกไปใช้เนื้อในของเอกสารชนิดอื่น"
        )


async def test_voucher_without_an_approver_leaves_the_slot_blank(client, db_pool, admin_headers):
    """ผู้อนุมัติไม่บังคับ (สเปก: "อาจจะมีหรือไม่มีก็ได้") ⇒ ช่องว่าง ไม่ใช่ `-`

    ⚠️ ขีดกลางในช่องลายมือชื่ออ่านว่า "ไม่มีผู้อนุมัติ" ซึ่งเป็นข้อความทางกฎหมาย
       ที่ระบบไม่ได้ตั้งใจประกาศ — ต่างจากช่องข้อมูลที่ `-` แปลว่า "ไม่รู้"
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=50.0, tx_type="expense", payee_name="ร้านป้าแดง",
                          approver_name=None, attachment_count=0)).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "ไม่ได้แนบหลักฐานมา" in html
    slot = html.split("ผู้อนุมัติ (หัวหน้าห้อง)")[0].rsplit('<div class="who">', 1)[1]
    assert slot.strip().startswith("</div>"), f"ช่องผู้อนุมัติต้องว่าง (ได้ {slot[:40]!r})"


async def test_voucher_account_kind_transfer_prints_the_bank_block(client, db_pool, admin_headers):
    """กระเป๋าที่ตั้งเป็น "โอน" ⇒ ใบสำคัญพิมพ์ธนาคาร/เลขที่บัญชี/ชื่อบัญชี ครบ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(
        db_pool, room_id, "🏦 บัญชีธนาคารห้อง", 1000.0, account_kind="transfer",
        bank_name="ธ.ไทยพาณิชย์", bank_account_no="123-4-56789-0",
        bank_account_name="นายสมชาย ใจดี",
    )
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense")).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "โอนเข้าบัญชี" in html
    for part in ("ธ.ไทยพาณิชย์", "123-4-56789-0", "นายสมชาย ใจดี", "บัญชีธนาคารห้อง"):
        assert part in html, f"ช่องทางจ่ายขาด '{part}'"


async def test_voucher_account_kind_cash_prints_cash_not_a_bank(client, db_pool, admin_headers):
    """กระเป๋าเงินสดต้องพิมพ์ "เงินสด" เฉย ๆ — ห้ามมีชื่อธนาคาร (ไม่มี = ไม่ต้องเดา)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0,
                                       account_kind="cash")
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=250.0, tx_type="expense")).status_code == 200
    no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]
    html = await _voucher_html(client, db_pool, admin_headers, room_id, no)

    assert "เงินสด" in html
    assert "โอนเข้าบัญชี" not in html


async def test_voucher_channel_text_never_invents_a_channel():
    """ชั้นบริสุทธิ์: ไม่รู้ช่องทาง ⇒ `None` (เทมเพลตพิมพ์ `-`) ห้ามเดาว่า "เงินสด"

    ใบที่ออกก่อนฟีเจอร์นี้มี snapshot ที่ไม่มี `channel` — การเดาว่าเป็นเงินสดคือ
    การกล่าวหาว่าจ่ายเป็นเงินสดบนเอกสารการเงิน
    """
    assert ReceiptsMixin._voucher_channel_text({}) is None
    assert ReceiptsMixin._voucher_channel_text({"account_kind": None}) is None
    assert ReceiptsMixin._voucher_channel_text({"account_kind": "cash"}) == "เงินสด"
    assert ReceiptsMixin._voucher_channel_text({"account_kind": "transfer"}) == "โอนเข้าบัญชี", (
        "ธนาคารที่ยังไม่ได้กรอกรายละเอียด = 'โอนเข้าบัญชี' เฉย ๆ ไม่ใช่ช่องว่าง"
    )
    assert ReceiptsMixin._voucher_channel_text(
        {"account_kind": "transfer", "bank_name": "ธ.กรุงไทย"}
    ) == "โอนเข้าบัญชี — ธ.กรุงไทย"


async def test_voucher_context_never_references_income_wording():
    """เทมเพลตใบสำคัญต้องไม่แตะ `is_receipt` เลย — เนื้อในต้องเป็นไฟล์ของตัวเอง"""
    voucher_ctx = ReceiptsMixin._document_context(_doc(DOC_TYPE_PAYMENT_VOUCHER, "PV-2569-0001"))
    assert voucher_ctx["body_template"] == "_voucher_body.html"
    html = render_receipt_html(voucher_ctx)
    assert 'class="sign sign-3"' in html, "ต้องเป็นบล็อกลายมือชื่อ 3 ฝ่าย"
    assert 'class="sign"' not in html.replace('class="sign sign-3"', ""), (
        "ต้องไม่เหลือบล็อกลายมือชื่อ 2 ฝ่ายของใบเสร็จ"
    )


async def test_mixed_selection_of_receipt_and_voucher_renders_in_one_request(
    client, db_pool, admin_headers,
):
    """ติ๊กใบรับเงินปนกับใบสำคัญจ่ายในคำขอเดียว ⇒ ไฟล์เดียว หน้าละใบ และ `<style>` ชุดเดียว

    🔴 `<style>` (ฟอนต์ base64) ต้องอยู่นอกลูป ⇒ จำนวนคำนำหน้า data URI ต้องเป็น 2 เสมอ
       ไม่ว่าจะกี่ใบ (ถ้าย้ายเข้าไปในลูป ไฟล์จะโตเป็น N เท่าและ assertion นี้จะพัง)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    income_cat = await _insert_category(db_pool, room_id, "เงินบริจาค", "income")
    expense_cat = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=income_cat,
                          amount=100.0, tx_type="income")).status_code == 200
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=expense_cat,
                          amount=50.0, tx_type="expense")).status_code == 200
    income_no = (await _docs(db_pool, room_id, DOC_TYPE_INCOME))[0]["receipt_no"]
    voucher_no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n% fake\n%%EOF\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.post(
            _url(API_PREFIX + "/{room}/finance/receipts/pdf", room_id),
            json={"receipt_nos": [income_no, voucher_no]}, headers=admin_headers,
        )
    assert res.status_code == 200, res.text

    html = mock_render.await_args.args[0]
    assert html.count('<div class="doc"') + html.count('<div class="doc doc-break"') == 2
    assert html.count("data:font/ttf;base64,") == 2, (
        "ฟอนต์ต้องถูกฝังครั้งเดียวต่อน้ำหนัก ไม่ใช่ต่อเอกสาร"
    )
    assert income_no in html and voucher_no in html
    assert "ผู้เบิก/ผู้รับเงิน" in html and "ผู้ชำระเงิน" in html, (
        "เนื้อในของทั้งสองชนิดต้องอยู่ครบในไฟล์เดียว"
    )
    assert ">None<" not in html


# ═══════════════════ 8. 🔴 เส้นทาง JSON ที่หน้าจอใช้จริง — `GET /finance/receipts/{no}`
#
# 💥 บั๊กจริงที่ผู้ใช้รายงาน (2026-09, มือถือ Android/Chrome): "กดดูใบสำคัญจ่ายแล้วได้หน้าขาว ๆ
#    แปลก ๆ" — หน้าค้างที่ skeleton "กำลังโหลดข้อมูล" บนพื้นขาว ไม่มี error ฝั่งเซิร์ฟเวอร์
#
# 🔎 กลไก: `ReceiptDetailResponse` ไม่ได้ประกาศฟิลด์ของใบสำคัญ (ทั้ง 9 ตัว) ⇒
#    `response_model=` ซึ่งเป็น **ตัวกรองขาออก** ตัด `budgets` ทิ้งเงียบ ๆ ⇒ ฝั่งหน้าจอ
#    `detail.budgets` เป็น `undefined` ⇒ `ReceiptDetail.vue:364` เข้าถึง `.length`
#    **throw ตอน render** ⇒ Vue ทิ้ง subtree ทั้งหน้า เหลือแต่ skeleton ค้าง
#
# 🔴 ทำไมเทสต์ทั้ง 1160 บรรทัดข้างบนจับไม่ได้: ทุกตัววิ่งผ่าน `_voucher_html` → `PDF_PATH`
#    ซึ่ง **ไม่ประกาศ `response_model`** (คืน binary stream) ⇒ ไม่มีเทสต์ใดในไฟล์นี้
#    (และในโปรเจกต์) แตะเส้นทาง JSON ที่หน้าจอเรียกจริงเลย
#
# ⇒ เทสต์ในบล็อกนี้ต้องยิง **`RECEIPT_PATH`** เท่านั้น ห้ามยิง `PDF_PATH`
#   มิฉะนั้นจะกลับไปเป็นเทสต์ที่พิสูจน์อะไรไม่ได้อีก

#: ฟิลด์ที่ `VoucherFields` (models/finance_schemas.py) **ต้อง** ประกาศ — ตรงกับที่
#: `_shape_receipt_detail` ตั้งให้ทุกแถว และตรงกับที่ `ReceiptDetail.vue` อ่าน
#: ⚠️ รายการนี้คือสัญญาระหว่าง 3 ไฟล์ — เพิ่มฟิลด์ให้ใบสำคัญแล้วไม่อัปเดตที่นี่ = ลืม
VOUCHER_DETAIL_FIELDS = (
    "approver_name", "attachment_count", "account_name", "account_kind",
    "bank_name", "bank_account_no", "bank_account_name", "category_name", "budgets",
)


async def test_voucher_detail_json_carries_every_snapshot_field(client, db_pool, admin_headers):
    """🔴 เทสต์ที่จับ "response_model ตัดฟิลด์ใบสำคัญทิ้ง" — ตัวเดียวที่จับได้

    ถ้าลบฟิลด์ใดออกจาก `VoucherFields` (หรือถอด `VoucherFields` ออกจาก
    `ReceiptDetailResponse`) เทสต์นี้ **ต้อง** ล้มที่ `missing` — ไม่ใช่เขียวเหมือนเดิม
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(
        db_pool, room_id, "บัญชีธนาคารห้อง", 1000.0,
        account_kind="transfer", bank_name="ธ.ไทยพาณิชย์",
        bank_account_no="123-4-56789-0", bank_account_name="นายสมชาย ใจดี",
    )
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    await _insert_budget(db_pool, room_id, cat_id,
                         start=_WIDE_START, end=_WIDE_END, amount=5000.0)

    res = await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                        amount=250.0, tx_type="expense", description="ซื้อของเข้าห้อง",
                        payee_name="ร้านป้าแดง", approver_name="ครูสมศรี", attachment_count=2)
    assert res.status_code == 200, res.text
    receipt_no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]

    # ⚠️ `RECEIPT_PATH` (JSON) — **ไม่ใช่** `PDF_PATH` (binary, ไม่มี response_model)
    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                        headers=admin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()

    missing = [k for k in VOUCHER_DETAIL_FIELDS if k not in body]
    assert not missing, (
        f"`response_model=ReceiptDetailResponse` ตัดฟิลด์เหล่านี้ออก: {missing} — "
        "หน้าจอจะได้ `undefined` แล้ว `v-if=\"detail.budgets.length\"` จะ throw ตอน render "
        "(จอขาว ไม่มี error ฝั่งเซิร์ฟเวอร์) — ต้องประกาศใน `VoucherFields` เสมอ"
    )

    assert body["doc_type"] == DOC_TYPE_PAYMENT_VOUCHER
    assert body["approver_name"] == "ครูสมศรี"
    assert body["attachment_count"] == 2
    assert body["account_name"] == "บัญชีธนาคารห้อง"
    assert body["account_kind"] == "transfer"
    assert body["bank_name"] == "ธ.ไทยพาณิชย์"
    assert body["bank_account_no"] == "123-4-56789-0"
    assert body["bank_account_name"] == "นายสมชาย ใจดี"
    assert body["category_name"] == "ค่าอาหาร"

    # 📋 `budgets` ต้องเป็น **ลิสต์** เสมอ — `null` ก็ทำให้ `.length` throw เหมือน `undefined`
    budgets = body["budgets"]
    assert isinstance(budgets, list) and len(budgets) == 1, (
        "งบที่ครอบวันของรายการต้องถูกส่งถึงหน้าจอ ไม่ใช่ถูกตัดทิ้ง"
    )
    assert set(budgets[0]) == {"id", "amount", "start_date", "end_date", "period_type"}, (
        "`VoucherBudget` ต้องประกาศครบ 5 คีย์ — คีย์ที่หายไปจะถูกตัดเงียบ ๆ ที่ชั้นนี้"
    )
    assert float(budgets[0]["amount"]) == pytest.approx(5000.0), (
        "DECIMAL ต้องถูก cast เป็น float มาแล้วจาก service (ไม่ใช่สตริง \"5000.00\")"
    )
    assert budgets[0]["start_date"] == _WIDE_START and budgets[0]["end_date"] == _WIDE_END, (
        "วันที่ของงบต้องเป็น ISO `YYYY-MM-DD` ตามสัญญาของ `VoucherBudget`"
    )


@pytest.mark.parametrize("tx_type,doc_type", [
    ("income", DOC_TYPE_INCOME),
    ("expense", DOC_TYPE_PAYMENT_VOUCHER),
])
async def test_detail_json_keeps_the_voucher_keys_on_every_document_type(
    client, db_pool, admin_headers, tx_type, doc_type,
):
    """เอกสาร **ทุกชนิด** ต้องมีคีย์ชุดนี้ครบ (เป็น `None`/`[]` เมื่อไม่มีค่า) ตามสัญญาของ service

    🔴 ทำไมต้องบังคับ: `_shape_receipt_detail` ตั้งทุกคีย์เสมอทั้งสองสาขา แต่
       `response_model=` จะตัดทิ้งถ้าไม่ได้ประกาศ ⇒ "คีย์ที่ไม่มีค่า" กับ "คีย์ที่ลืมประกาศ"
       แยกกันไม่ออกเลยจากฝั่งหน้าจอ (ทั้งคู่กลายเป็น `undefined`) ต่างจาก `null` ที่แยกออก
       ⇒ เทสต์นี้ผูกสัญญาไว้ว่า "ไม่มีค่า" ต้องหมายถึง `null`/`[]` เท่านั้น

    ⚠️ `receipt` (ที่ออกผ่าน `confirm_payment`) ไม่ได้อยู่ในพารามิเตอร์นี้เพราะสร้างผ่าน
       `add_transaction` ไม่ได้ — แต่เส้นทางที่มันใช้ (`get_receipt` → `_shape_receipt_detail`
       → `response_model=ReceiptDetailResponse`) เป็นเส้นเดียวกันทั้งหมด ⇒ สัญญาที่พิสูจน์
       ที่นี่ครอบมันด้วย
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กองกลาง", 1000.0)
    cat_id = await _insert_category(db_pool, room_id, "หมวดทดสอบ", tx_type)
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=100.0, tx_type=tx_type)).status_code == 200
    receipt_no = (await _docs(db_pool, room_id, doc_type))[0]["receipt_no"]

    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                        headers=admin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()

    missing = [k for k in VOUCHER_DETAIL_FIELDS if k not in body]
    assert not missing, f"เอกสารชนิด {doc_type} ต้องมีคีย์ครบ (ขาด: {missing})"
    assert isinstance(body["budgets"], list), (
        "`budgets` ต้องเป็นลิสต์เสมอ — `null` ก็ทำให้ `detail.budgets.length` throw"
    )

    if tx_type == "income":
        # 🧾 ใบรับเงินไม่มี `voucher_snapshot` ⇒ ต้องเป็นค่าปริยาย ไม่ใช่คีย์ที่หายไป
        assert body["budgets"] == []
        assert body["account_kind"] is None
        assert body["attachment_count"] == 0
        assert body["approver_name"] is None
        assert body["category_name"] is None


async def test_voucher_detail_json_reports_an_unknown_account_kind_verbatim(
    client, db_pool, admin_headers,
):
    """`account_kind` ที่ไม่รู้จักต้อง **รอดถึงหน้าจอ** ไม่ทำให้หน้า detail เป็น 500

    🔴 `VoucherFields.account_kind` เป็น `str` ไม่ใช่ `Literal['cash','transfer']` โดยเจตนา:
       ค่าที่เพิ่มเข้ามาทีหลัง (หรือพิมพ์ผิดใน DB) ต้องทำให้ช่องนั้น **ว่าง** บนหน้าจอ
       (`voucherChannel` คืน `null`) — ไม่ใช่พังทั้งหน้า ซึ่งเป็นความผิดพลาดเดียวกับ
       ที่ทำให้เกิดบั๊กจอขาว (การตีความค่าที่ไม่รู้จักว่าเป็นอย่างอื่นเงียบ ๆ แย่กว่าระเบิด)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, "กระเป๋าใหม่", 1000.0,
                                       account_kind="cash")
    cat_id = await _insert_category(db_pool, room_id, "ค่าอาหาร", "expense")
    assert (await _add_tx(client, admin_headers, account_id=account_id, category_id=cat_id,
                          amount=100.0, tx_type="expense")).status_code == 200
    receipt_no = (await _docs(db_pool, room_id, DOC_TYPE_PAYMENT_VOUCHER))[0]["receipt_no"]

    # 🧪 เขียนค่าที่ constraint ไม่อนุญาตผ่านไม่ได้ ⇒ แก้ snapshot ตรง ๆ แทน
    #    (จำลอง "ค่าใหม่ที่โค้ดรุ่นก่อนไม่รู้จัก" ซึ่งเป็นสถานการณ์จริงของการ deploy แบบ rolling)
    async with db_pool.acquire() as conn:
        snapshot = await conn.fetchval(
            "SELECT voucher_snapshot FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )
        snapshot = ReceiptsMixin._parse_voucher_snapshot(snapshot)
        snapshot["channel"] = "e_wallet"
        await conn.execute(
            "UPDATE finance_receipts SET voucher_snapshot = $2::jsonb WHERE receipt_no = $1",
            receipt_no, json.dumps(snapshot, ensure_ascii=False),
        )

    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                        headers=admin_headers)
    assert detail.status_code == 200, (
        f"ค่าที่ไม่รู้จักต้องไม่ทำให้หน้า detail พัง — ได้ {detail.status_code}: {detail.text}"
    )
    assert detail.json()["account_kind"] == "e_wallet", (
        "ต้องส่งค่าตามจริงให้หน้าจอตัดสินใจเอง (frontend แสดงช่องทางเฉพาะที่รู้จัก)"
    )
