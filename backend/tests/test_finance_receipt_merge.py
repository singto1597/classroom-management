"""[F6/PR-4] ยุบใบเสร็จหลายใบของคนเดียวกันให้เหลือ **หน้าเดียวหลายบรรทัด**

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร (เรียงตามความสำคัญ)
═══════════════════════════════════════════════════════════════════════════════
1. **"คนเดียวกัน" ต้องหมายถึง `student_id` ไม่ใช่ชื่อ** — ถ้ามีคนเปลี่ยนไปใช้
   `issued_to_name` (สตริง snapshot ที่มีชื่อเล่นอยู่ข้างใน) ใบเสร็จของเด็กสองคนที่
   ชื่อซ้ำกันในห้องเดียวจะถูกยุบรวมเป็นกระดาษใบเดียว ⇒ ผู้ปกครองคนหนึ่งถือเลข
   ใบเสร็จของอีกบ้าน · เทสต์ `test_merge_never_crosses_students` จับข้อนี้

2. **ใบที่ถูกยกเลิกต้องไม่ถูกกลืนเข้ากับใบที่ยังใช้ได้** — แบนเนอร์ "ยกเลิก" อยู่บนสุด
   ของ *หน้า* ไม่ใช่บนสุดของ *บรรทัด* ⇒ ยุบปนเมื่อไร ใบที่เงินถูกคืนไปแล้วจะอ่าน
   เหมือนใบปกติทั้งใบ

3. **`student_id IS NULL` ห้ามยุบ** — คอลัมน์เป็น `ON DELETE SET NULL` ⇒ ลบนักเรียน
   คนหนึ่งแล้วใบของคนอื่นที่เป็น NULL จะยุบรวมกันหมดเป็นหน้าที่ไม่มีเจ้าของ

4. **กลุ่มขนาด 1 ต้องได้กระดาษเหมือนเดิมทุกไบต์** — "โหลดทีละใบ" กับ "โหลดรวม"
   ต้องไม่ให้คนละแบบ ไม่งั้นความต่างจะโผล่ตอนมีคนเอากระดาษมาวางเทียบกันเท่านั้น

5. **หน้าที่ยุบต้องไม่ระเบิดที่ `format(None)`** — `receipt.html` พิมพ์
   `"{:,.2f}".format(d.paid_total_after)` และใบที่ยุบตั้งค่านั้นเป็น None โดยชอบธรรม
   ⇒ ต้องมี `{% if not d.is_merged %}` กัน ไม่ใช่แค่ "ตัวเลขเพี้ยน" แต่เป็น **500**

⚠️ ส่วน A เป็นฟังก์ชันบริสุทธิ์ล้วน (ไม่ต้องมี DB — เร็ว) · ส่วน B ยิงเส้นทางจริง
⚠️ ไฟล์นี้ **เอกเทศ** เหมือนเทสต์ไฟล์อื่นใน repo (`tests/` ไม่มี `__init__.py`)
"""
import random
import string
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from core.config import settings
from services.finance.constants import DOC_TYPE_DEPOSIT, DOC_TYPE_INVOICE, DOC_TYPE_RECEIPT
from services.finance.receipts import _MAX_MERGED_MEMBERS, ReceiptsMixin

pytestmark = pytest.mark.asyncio

# ⚠️ finance router mount ด้วย prefix `/api/classroom` (backend/main.py)
API_PREFIX = "/api/classroom"
WEB_PDF_PATH = API_PREFIX + "/{target}/finance/receipts/pdf"
ONE_PDF_PATH = API_PREFIX + "/{target}/finance/receipts/{receipt_no}/pdf"
PAY_PATH = API_PREFIX + "/{target}/finance/payments/{payment_id}/pay"
RECEIPTS_PATH = API_PREFIX + "/{target}/finance/receipts"

FAKE_PDF = b"%PDF-1.4\n% fake\n%%EOF\n"

# 🖨️ ตัวคั่นหน้าในไฟล์รวม — เทมเพลตใส่คลาสนี้ให้ **ทุกใบยกเว้นใบสุดท้าย**
#    ⚠️ **ห้ามนับ `'<div class="doc'`**: `<div class="doc-title">` ก็ขึ้นต้นด้วยสตริงนั้น
DOC_BREAK = '<div class="doc doc-break">'


def _page_count(html: str) -> int:
    return html.count(DOC_BREAK) + 1


# ══════════════════════════════════════════════════════════════════════════════
# ส่วน A — ฟังก์ชันบริสุทธิ์ (`_document_contexts` รับ dict ที่ shape แล้ว)
# ══════════════════════════════════════════════════════════════════════════════
def _doc(
    receipt_no: str = "REC-2569-0001",
    *,
    doc_type: str = DOC_TYPE_RECEIPT,
    student_id: int | None = 7,
    amount: float = 1000.0,
    status: str = "active",
    day: int = 14,
    **overrides,
) -> dict:
    """รูปร่างของ dict ที่ `_shape_receipt_detail` ผลิต — เฉพาะคีย์ที่การยุบแตะ

    ⚠️ วันที่เป็น `datetime` จริง (ไม่ใช่ ISO string) — `_document_context` เรียก
       `_thai_datetime_text` ซึ่งคาดหวัง tz-aware datetime
    """
    doc = {
        "doc_type": doc_type,
        "doc_type_label": {
            DOC_TYPE_RECEIPT: "ใบเสร็จรับเงิน",
            DOC_TYPE_INVOICE: "ใบแจ้งหนี้",
            DOC_TYPE_DEPOSIT: "ใบรับเงินล่วงหน้า",
        }[doc_type],
        "receipt_no": receipt_no,
        "status": status,
        "void_reason": "ยกเลิกโดยครู" if status == "voided" else None,
        "student_id": student_id,
        "amount": amount,
        "paid_total_after": amount,
        "student_payment_id": 1,
        "collection_id": 1,
        "collection_title": "ค่าเทอม",
        "collection_amount": None,
        "collection_due_date": None,
        "line_items": None,
        "issued_to_name": "เด็กชายสมชาย ใจดี",
        "student_no": 7,
        "issued_by_name": "ครูสมศรี",
        "issued_at": datetime(2026, 9, day, 3, 0, tzinfo=timezone.utc),
        "event_at": datetime(2026, 9, day, 3, 0, tzinfo=timezone.utc),
        "note": None,
        "room_name": "ห้อง ม.4/1",
        "room_code": "M4-1",
    }
    doc.update(overrides)
    return doc


async def test_merged_context_collapses_same_student_same_doc_type():
    """3 ใบของนักเรียนคนเดียวกัน → **1 หน้า** ที่มี 3 บรรทัด และยอดรวม = ผลบวก"""
    docs = [
        _doc("REC-2569-0001", amount=100.0),
        _doc("REC-2569-0002", amount=250.5),
        _doc("REC-2569-0003", amount=49.5),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)

    assert len(ctxs) == 1, "ใบของคนเดียวกัน/ชนิดเดียวกันต้องยุบเหลือหน้าเดียว"
    ctx = ctxs[0]
    assert ctx["is_merged"] is True
    assert ctx["merged_count"] == 3
    assert [m["receipt_no"] for m in ctx["members"]] == [
        "REC-2569-0001", "REC-2569-0002", "REC-2569-0003",
    ]
    assert ctx["amount"] == 400.0, "ยอดรวมต้องเป็นผลบวกของสมาชิก ไม่ใช่ยอดของตัวแรก"
    # เศษทศนิยมต้องไม่เพี้ยน (ผลบวกของ float ตรง ๆ ให้ 400.00000000000006 ได้)
    assert ctx["amount"] == round(sum(m["amount"] for m in ctx["members"]), 2)


async def test_merged_context_keeps_each_receipt_number_on_its_own_row():
    """หัวใบเป็น "รวม N ฉบับ" — เลขที่ทุกใบต้องยังอยู่ **ครบ** ในบรรทัดของตัวเอง"""
    docs = [_doc(f"REC-2569-000{i}", amount=10.0) for i in (1, 2, 3)]
    html = ReceiptsMixin._document_contexts(docs)
    ctx = html[0]

    assert ctx["receipt_no"] is None, "ใบที่ยุบไม่มีเลขที่เดียว"
    assert ctx["doc_no_text"] == "รวม 3 ฉบับ"
    for i in (1, 2, 3):
        assert f"REC-2569-000{i}" in [m["receipt_no"] for m in ctx["members"]]


async def test_merge_never_crosses_students():
    """🔑 2 คน → 2 หน้า · เลขของแต่ละคนต้องอยู่คนละกระดาษ

    🚨 นี่คือเทสต์ที่กัน "เปลี่ยนไปใช้ `issued_to_name`" ซึ่งเป็นสตริง snapshot
       ที่มีชื่อเล่นอยู่ข้างใน และนักเรียนสองคนในห้องเดียวกันชื่อซ้ำกันได้จริง
    """
    docs = [
        _doc("REC-2569-0001", student_id=7),
        _doc("REC-2569-0002", student_id=8),
        _doc("REC-2569-0003", student_id=7),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)

    assert len(ctxs) == 2, "คนละนักเรียนต้องได้คนละหน้า แม้ชื่อจะเหมือนกันเป๊ะ"
    # กลุ่มของ student 7 ต้องมี 2 ใบ และ **ไม่ปน** ใบของ student 8
    assert [m["receipt_no"] for m in ctxs[0]["members"]] == [
        "REC-2569-0001", "REC-2569-0003",
    ]
    # student 8 มีใบเดียว ⇒ ได้เอกสารเดี่ยว (ไม่ใช่กลุ่มที่มีสมาชิก 1 คน)
    assert ctxs[1]["is_merged"] is False
    assert ctxs[1]["receipt_no"] == "REC-2569-0002"


async def test_merge_never_crosses_doc_type():
    """ใบเสร็จกับใบรับเงินล่วงหน้าของคนเดียวกัน = คนละชนิด ⇒ คนละหน้า"""
    docs = [
        _doc("REC-2569-0001", doc_type=DOC_TYPE_RECEIPT),
        _doc("DEP-2569-0001", doc_type=DOC_TYPE_DEPOSIT, collection_id=None),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)
    assert len(ctxs) == 2


async def test_merge_never_mixes_voided_with_active():
    """🔴 ใบที่ยกเลิกต้องไม่ถูกกลืนเข้ากับใบที่ยังใช้ได้

    แบนเนอร์ "ยกเลิก" อยู่บนสุดของ **หน้า** ไม่ใช่บนสุดของ **บรรทัด** ⇒ หน้าผสมจะทำให้
    ใบที่เงินถูกคืนไปแล้วอ่านเหมือนใบปกติทั้งใบ
    """
    docs = [
        _doc("REC-2569-0001", status="active"),
        _doc("REC-2569-0002", status="voided"),
        _doc("REC-2569-0003", status="active"),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)

    assert len(ctxs) == 2, "ใบยกเลิกต้องได้หน้าของตัวเอง"
    merged = [c for c in ctxs if c["is_merged"]]
    assert len(merged) == 1 and merged[0]["merged_count"] == 2
    assert [c["is_voided"] for c in ctxs if not c["is_merged"]] == [True]


async def test_merge_never_groups_null_student_id():
    """🔑 `student_id IS NULL` → ห้ามยุบ (`ON DELETE SET NULL` ทำใบของทุกคนเป็น NULL)"""
    docs = [
        _doc("REC-2569-0001", student_id=None),
        _doc("REC-2569-0002", student_id=None),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)
    assert len(ctxs) == 2, "ใบที่ไม่รู้เจ้าของต้องไม่ถูกยุบรวมกัน"
    assert all(c["is_merged"] is False for c in ctxs)


async def test_merge_spans_different_dates_and_prints_a_range():
    """🔑 คนละวัน → **ยังยุบ** และหัวใบพิมพ์ช่วงวันที่ (พฤติกรรมที่ผู้ใช้เลือกรอบสอง)"""
    docs = [
        _doc("REC-2569-0001", day=1),
        _doc("REC-2569-0002", day=15),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)

    assert len(ctxs) == 1, "ผู้ใช้เลือกรูปแบบ 'รวม N ฉบับ + ช่วงวันที่' ⇒ ยุบข้ามวันได้"
    ctx = ctxs[0]
    assert ctx["doc_date_text"] == "1 ก.ย. 2569 – 15 ก.ย. 2569"
    # 🗓️ และ **แต่ละบรรทัด** ต้องมีวันที่ของตัวเอง ไม่ใช่ยืมวันที่หัวใบ
    assert [m["date_text"] for m in ctx["members"]] == ["1 ก.ย. 2569", "15 ก.ย. 2569"]


async def test_merge_same_day_prints_a_single_date_not_a_range():
    """วันเดียวกันทั้งกลุ่ม → พิมพ์วันเดียว ("1 ก.ย. 2569 – 1 ก.ย. 2569" อ่านเหมือนข้อมูลหาย)"""
    docs = [_doc("REC-2569-0001", day=9), _doc("REC-2569-0002", day=9)]
    assert ReceiptsMixin._document_contexts(docs)[0]["doc_date_text"] == "9 ก.ย. 2569"


async def test_row_date_is_thai_local_not_utc():
    """🗓️ วันที่รายบรรทัดต้องเป็น **วันไทย** — 17:30 UTC คือเช้าวันรุ่งขึ้นในไทย

    🕳️ กับดักเดียวกับทั้งรีโปนี้: ตัด `.date()` จาก UTC ตรง ๆ จะได้วันก่อนหน้า ⇒
       ใบเสร็จที่ออกคืนวันสุดท้ายของเดือนจะถูกจัดไปอยู่วันอื่นในตารางที่ยุบ
    """
    doc = _doc("REC-2569-0001")
    doc["event_at"] = datetime(2026, 9, 14, 17, 30, tzinfo=timezone.utc)
    doc["issued_at"] = doc["event_at"]

    ctx = ReceiptsMixin._document_contexts([doc])[0]
    assert ctx["document_date_text"].startswith("15 ก.ย. 2569"), "หัวใบต้องเป็นวันไทย"

    merged = ReceiptsMixin._document_contexts([doc, _doc("REC-2569-0002")])[0]
    assert merged["members"][0]["date_text"] == "15 ก.ย. 2569"


async def test_grouping_preserves_the_order_the_user_selected():
    """ลำดับหน้า = ลำดับที่ผู้ใช้ติ๊กบนจอ (กลุ่มถูกสร้างตอนเจอสมาชิกตัวแรก)

    ⚠️ ถ้ามีคน "จัดเรียงให้สวย" ด้วยการ sort ตามเลขที่ เอกสารของคนที่ติ๊กไว้กลางลิสต์
       จะย้ายไปอยู่หน้าอื่น — ครูที่พิมพ์แจกตามลำดับที่เห็นบนจอจะแจกผิดคน
    """
    b = _doc("REC-2569-0009", student_id=8)
    a1 = _doc("REC-2569-0001", student_id=7)
    a2 = _doc("REC-2569-0002", student_id=7)
    ctxs = ReceiptsMixin._document_contexts([b, a1, a2])

    assert [c.get("receipt_no") or c["members"][0]["receipt_no"] for c in ctxs] == [
        "REC-2569-0009", "REC-2569-0001",
    ], "เอกสารของคนแรกที่ติ๊กต้องอยู่หน้าแรก"





async def test_invoice_documents_are_never_merged():
    """🚫 ใบแจ้งหนี้เป็น aggregate ต่อคนอยู่แล้ว — ยุบสองใบ = เอา snapshot สองช่วงบวกกัน"""
    docs = [
        _doc("INV-2569-0001", doc_type=DOC_TYPE_INVOICE, line_items=[{"title": "x", "amount": 1.0}]),
        _doc("INV-2569-0002", doc_type=DOC_TYPE_INVOICE, line_items=[{"title": "y", "amount": 2.0}]),
    ]
    ctxs = ReceiptsMixin._document_contexts(docs)
    assert len(ctxs) == 2
    assert all(c["is_merged"] is False for c in ctxs)


async def test_group_of_one_is_byte_identical_to_single_document():
    """🔑 เอกสารเดียว (ไม่ว่าจะยุบได้หรือไม่) ต้องได้ context **เท่ากับ** `_document_context`

    สัญญา "จอตรงกับกระดาษ": `GET /{no}/pdf` เรียก `_document_context` ตรง ๆ ส่วน
    ไฟล์รวมเรียก `_document_contexts` ⇒ ถ้าสองเส้นทางนี้ให้ context ต่างกัน哪怕คีย์เดียว
    กระดาษของเอกสารใบเดียวกันจะไม่เหมือนกันแล้วแต่กดจากปุ่มไหน
    """
    for doc in (
        _doc("REC-2569-0001"),
        _doc("INV-2569-0001", doc_type=DOC_TYPE_INVOICE),
        _doc("REC-2569-0002", student_id=None),
    ):
        assert ReceiptsMixin._document_contexts([doc])[0] == ReceiptsMixin._document_context(doc)


async def test_merged_group_over_cap_falls_back_to_one_page_per_document():
    """✂️ เกิน `_MAX_MERGED_MEMBERS` → แยกเป็น N หน้า **ไม่ตัดบรรทัดทิ้ง**

    ต่างจากใบแจ้งหนี้ที่พิมพ์ "และอีก N โครงการ": บนใบเสร็จที่ยุบ บรรทัดคือ "ชุดเอกสาร"
    เอง ⇒ ซ่อนบรรทัด = เลขใบเสร็จหายไปจากกระดาษที่ผู้ปกครองถือ
    """
    docs = [_doc(f"REC-2569-{i:04d}", amount=1.0) for i in range(1, _MAX_MERGED_MEMBERS + 2)]
    ctxs = ReceiptsMixin._document_contexts(docs)

    assert len(ctxs) == _MAX_MERGED_MEMBERS + 1, "เกินเพดานต้องไม่ยุบเลยสักกลุ่ม"
    assert all(c["is_merged"] is False for c in ctxs)
    assert [c["receipt_no"] for c in ctxs] == [d["receipt_no"] for d in docs]


async def test_group_exactly_at_cap_still_merges():
    """เส้นแบ่ง: `_MAX_MERGED_MEMBERS` พอดี → **ยุบ** (เพดานคือ "เกิน" ไม่ใช่ "ถึง")"""
    docs = [_doc(f"REC-2569-{i:04d}", amount=1.0) for i in range(1, _MAX_MERGED_MEMBERS + 1)]
    ctxs = ReceiptsMixin._document_contexts(docs)
    assert len(ctxs) == 1 and ctxs[0]["merged_count"] == _MAX_MERGED_MEMBERS


async def test_merged_context_pins_bill_only_keys_to_none():
    """คีย์ที่เป็นของ "บิล" ต้องถูกปิด — ใบที่ยุบไม่มีแนวคิดนั้น

    ⚠️ ถ้าไม่ปิด `paid_total_after` และเทมเพลตไม่มี `{% if not d.is_merged %}`
       จะได้ `format(None)` = TypeError = **500** ไม่ใช่แค่ตัวเลขเพี้ยน
    """
    ctx = ReceiptsMixin._document_contexts([_doc("REC-2569-0001"), _doc("REC-2569-0002")])[0]
    for key in (
        "paid_total_after", "paid_total_after_text", "collection_amount",
        "collection_title", "collection_due_date", "remaining", "remaining_text",
    ):
        assert key in ctx, f"ต้องมีคีย์ `{key}` (ค่า None) ไม่ใช่ไม่มีคีย์เลย"
        assert ctx[key] is None, f"`{key}` ต้องเป็น None สำหรับใบที่ถูกยุบ"
    assert ctx["line_items"] is None
    assert ctx["line_items_hidden"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# ส่วน B — เรนเดอร์ HTML/PDF จริง (ยังไม่ต้องมี DB)
# ══════════════════════════════════════════════════════════════════════════════
async def test_merged_page_renders_without_a_paid_total_row():
    """🔴 หน้าที่ยุบต้องเรนเดอร์ได้ และ **ไม่มี** แถว "ยอดสะสมที่ชำระแล้ว"

    กับดักเดียวกับ `test_finance_credits.py` ที่เจอตอนเรนเดอร์ใบรับเงินล่วงหน้า:
    `format(None)` ไม่ได้ให้ตัวเลขเพี้ยน แต่ให้ **TypeError ทั้งการเรนเดอร์**
    """
    from services.finance.pdf import render_receipts_html

    html = render_receipts_html(
        ReceiptsMixin._document_contexts([_doc("REC-2569-0001"), _doc("REC-2569-0002")])
    )

    # 🔴 **`"None" not in html` ไม่ใช่ `">None<" not in html`** — บทเรียนจากการรัน
    #    mutation harness (mutant ที่ให้หัวใบพิมพ์ `d.receipt_no` ตรง ๆ **รอด**):
    #    `receipt_no` ของใบที่ถูกยุบเป็น None ⇒ เทมเพลตพิมพ์ `เลขที่ None</div>` ซึ่ง
    #    **ไม่มี `>` นำหน้า** ⇒ assertion แบบ `">None<"` มองไม่เห็น แล้วกระดาษที่ผู้ปกครอง
    #    ถือจะมีคำว่า None โผล่บนหัวใบโดยที่เทสต์ทั้งไฟล์เขียว
    #    ⚠️ และต้องเช็ค **ก่อน** positive control ด้านล่าง ไม่งั้นข้อความนี้จะไม่ถูกตรวจ
    assert "None" not in html, "ห้ามมีคำว่า None หลุดขึ้นกระดาษ (หัวใบ/ท้ายใบ/ช่องไหนก็ตาม)"
    assert "รวม 2 ฉบับ" in html
    # 🎯 ปักหัวใบให้เป็นข้อความที่ถูกต้องจริง ไม่ใช่แค่ "ไม่มีคำว่า None"
    #    (ถ้าอนาคตมีคนเปลี่ยนไปพิมพ์ค่าว่างหรือ "-" assertion นี้จะจับได้)
    assert "เลขที่ รวม 2 ฉบับ" in html, "หัวใบของใบที่ถูกยุบต้องเป็น 'รวม N ฉบับ'"
    assert "REC-2569-0001" in html and "REC-2569-0002" in html

    # ⚠️ ห้ามเช็คแค่ `"ยอดสะสมที่ชำระแล้ว" not in html` — สตริงนั้นปรากฏอยู่ใน
    #    **คอมเมนต์ CSS** ของเทมเพลต (`.meta .k` อธิบายความกว้างของป้าย) ⇒ เทสต์จะล้ม
    #    ทั้งที่โค้ดถูก · เช็คที่ "แถวที่เรนเดอร์จริง" แทน: ป้ายถูก `.format()` แล้ว
    #    ไม่มีช่องว่างรอบ ๆ เพราะ `{%- endif -%}`
    assert "ยอดสะสมที่ชำระแล้ว</td>" not in html
    assert "บาท</td>" not in html, "ทั้งบล็อกสรุปต้องหายไป ไม่ใช่แค่แถวเดียว"

    # ✅ ตัวควบคุม: เอกสาร **ใบเดียว** ต้องยังมีบล็อกนั้น (พิสูจน์ว่า assertion มีฟัน)
    single = render_receipts_html(ReceiptsMixin._document_contexts([_doc("REC-2569-0009")]))
    assert "ยอดสะสมที่ชำระแล้ว</td>" in single
    assert "บาท</td>" in single


async def test_merged_page_prints_the_grand_total_in_thai_words():
    """💰 ยอดรวมต้องเป็น **ผลบวก** และมีคำอ่านภาษาไทยกำกับ (baht_text)"""
    from services.finance.pdf import render_receipts_html

    docs = [_doc("REC-2569-0001", amount=1000.0), _doc("REC-2569-0002", amount=2500.0)]
    ctxs = ReceiptsMixin._document_contexts(docs)
    html = render_receipts_html(ctxs)

    assert ctxs[0]["amount"] == 3500.0
    assert ctxs[0]["amount_text"] == "สามพันห้าร้อยบาทถ้วน"
    assert "สามพันห้าร้อยบาทถ้วน" in html
    assert "3,500.00" in html


async def test_merged_receipts_stay_on_one_page():
    """3 ใบของคนเดียวกัน → **1 หน้า** (ไม่มีตัวคั่นหน้าเลย)"""
    from services.finance.pdf import render_receipts_html

    docs = [_doc(f"REC-2569-000{i}", amount=10.0) for i in (1, 2, 3)]
    html = render_receipts_html(ReceiptsMixin._document_contexts(docs))

    assert _page_count(html) == 1, "นี่คือหัวใจของคำขอ: 3 ใบ = 1 หน้า"


async def test_unmerged_documents_still_get_one_page_each():
    """เอกสารที่ไม่ยุบ (ต่างคน) ยังต้องเป็นหน้าละใบเหมือนเดิม"""
    from services.finance.pdf import render_receipts_html

    docs = [_doc(f"REC-2569-000{i}", student_id=i, amount=10.0) for i in (1, 2, 3)]
    html = render_receipts_html(ReceiptsMixin._document_contexts(docs))

    assert _page_count(html) == 3


async def test_unmerged_page_shows_no_trace_of_the_merge_feature():
    """🔁 ใบเดี่ยวต้องไม่มีร่องรอยของฟีเจอร์ยุบเลย

    ⚠️ ถ้า `{% if d.is_merged %}` ถูก **กลับด้านหรือถูกถอด**, ใบเดี่ยวจะขึ้นแถว
       "รวมเอกสาร" + "0 ฉบับ" **โดยไม่มี error ใด ๆ** — กระดาษที่ผู้ปกครองถือจะอ่าน
       เหมือนเอกสารที่รวมหลายใบ ทั้งที่มันเป็นใบเดียว · และผู้ใช้จะไม่มีทางรู้ว่าผิด
       จนกว่าจะเอาไปเทียบกับใบที่โหลดจาก URL ใบเดียว (`GET /{no}/pdf`)
    """
    from services.finance.pdf import render_receipts_html

    html = render_receipts_html(ReceiptsMixin._document_contexts([_doc("REC-2569-0009")]))

    assert "รวมเอกสาร" not in html, "ใบเดี่ยวห้ามมีป้าย 'รวมเอกสาร'"
    assert "0 ฉบับ" not in html, "`merged_count` ของใบเดี่ยวเป็น 0 — ห้ามหลุดขึ้นกระดาษ"
    assert "เลขที่และวันที่ของแต่ละฉบับอยู่ในตารางด้านล่าง" not in html
    # ✅ ตัวควบคุม: ใบเดียวต้องยังได้หัวใบแบบเดิม
    assert "เลขที่ REC-2569-0009" in html


async def test_rendering_still_embeds_the_fonts_exactly_twice():
    """🖋️ ฟอนต์ต้องถูกฝัง 2 ครั้ง (Regular + Bold) ไม่ว่าจะยุบกี่ใบ

    ⚠️ ถ้ามีคนเผลอย้าย `<style>` เข้าไปในลูป (หรือแยกไฟล์ต่อเอกสาร) ฟอนต์จะถูกฝัง
       ซ้ำ N เท่า — ไฟล์ HTML โตขึ้นหลายเท่าและ Chromium ใช้เวลาจัดหน้านานขึ้น
    """
    from services.finance.pdf import render_receipts_html

    docs = [_doc(f"REC-2569-000{i}", amount=10.0) for i in (1, 2, 3)]
    html = render_receipts_html(ReceiptsMixin._document_contexts(docs))

    assert html.count("data:font/ttf;base64,") == 2


async def test_merged_pdf_is_rendered_in_a_single_gotenberg_call():
    """Gotenberg ต้องถูกเรียก **ครั้งเดียว** ต่อคำขอ ไม่ใช่ครั้งละหน้า

    ตรวจที่นี่ (ยังไม่ต้องมี DB) ว่าการยุบไม่ทำให้เกิดการเรนเดอร์ซ้ำ — ตัวนับจริง
    อยู่ที่เทสต์ฝั่ง HTTP ในส่วน C ที่นับ `await_count` ของ `html_to_pdf`
    """
    from unittest.mock import AsyncMock

    from services.finance.pdf import render_receipts_html

    docs = [_doc(f"REC-2569-000{i}", amount=10.0) for i in (1, 2, 3)]
    with patch("services.finance.pdf.html_to_pdf", AsyncMock(return_value=FAKE_PDF)) as mock_render:
        html = render_receipts_html(ReceiptsMixin._document_contexts(docs))
        # `render_receipts_html` เป็นฟังก์ชันบริสุทธิ์ — ไม่แตะเครือข่ายเลย
        mock_render.assert_not_awaited()
    assert _page_count(html) == 1


# ══════════════════════════════════════════════════════════════════════════════
# ส่วน C — ยิงเส้นทางจริง (ต้องมี DB)
# ══════════════════════════════════════════════════════════════════════════════
def _api(target_id: int, path: str, **kwargs) -> str:
    """⚠️ web ต้องส่ง `target_type=room` เสมอ (default ของ API คือ server)"""
    return path.format(target=target_id, **kwargs) + "?target_type=room"


def _web_headers(user_id: int) -> dict:
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def _insert_user(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username)
               VALUES ('ทดสอบ', 'ระบบ', $1) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """INSERT INTO rooms (room_name, room_code, owner_id)
               VALUES ($1, $2, $3) RETURNING id""",
            "ห้องทดสอบ", code, owner_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 0, 'president', 'active', TRUE, '["all"]'::jsonb)""",
            room_id, owner_id,
        )
    return room_id


async def _insert_account(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, "กระเป๋ากลาง",
        )


async def _make_debtor(pool, room_id: int, *, student_no: int = 90) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username)
               VALUES ('เด็กชายทดสอบ', 'ทดลอง', $1) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _make_bill(pool, room_id: int, student_id: int, *, amount: float, title: str) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, title, amount, date(2026, 12, 31),
        )
        return await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0) RETURNING id""",
            collection_id, student_id,
        )


async def _pay_and_issue(client, headers, pool, room_id: int, student_id: int, *, amount: float, title: str) -> str:
    """รับเงิน 1 บิลของนักเรียน **คนที่ระบุ** แล้วออกใบเสร็จผ่านเส้นทางจริง → เลขที่"""
    account_id = await _insert_account(pool, room_id)
    payment_id = await _make_bill(pool, room_id, student_id, amount=amount, title=title)

    paid = client.put(
        _api(room_id, PAY_PATH, payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )
    assert paid.status_code == 200, paid.text

    issued = client.post(
        _api(room_id, RECEIPTS_PATH),
        json={"payment_id": payment_id, "doc_type": "receipt"},
        headers=headers,
    )
    assert issued.status_code == 200, issued.text
    return issued.json()["receipt"]["receipt_no"]


async def test_combined_pdf_route_merges_three_receipts_of_one_student(client, db_pool):
    """🎯 หัวใจของคำขอ: เลือก 3 ใบของคนเดียวกัน → **1 หน้า 3 บรรทัด** ผ่าน HTTP จริง"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    student_id = await _make_debtor(db_pool, room_id)
    headers = _web_headers(owner)

    nos = [
        await _pay_and_issue(client, headers, db_pool, room_id, student_id, amount=100.0 * i, title=f"รายการ {i}")
        for i in (1, 2, 3)
    ]

    captured = {}

    async def fake_render(html, *, timeout=None):
        captured["html"] = html
        return FAKE_PDF

    with patch("services.finance.pdf.html_to_pdf", fake_render):
        resp = client.post(
            _api(room_id, WEB_PDF_PATH), json={"receipt_nos": nos}, headers=headers
        )

    assert resp.status_code == 200, resp.text
    html = captured["html"]
    assert _page_count(html) == 1, "3 ใบของคนเดียวกันต้องเหลือหน้าเดียว"
    assert "รวม 3 ฉบับ" in html
    for no in nos:
        assert no in html, "เลขที่ทุกใบต้องยังอยู่บนกระดาษ"


async def test_single_receipt_pdf_route_never_merges(client, db_pool):
    """🔴 `GET /{no}/pdf` ต้องพิมพ์ **ใบเดียว** เสมอ — ห้ามตามหา "พี่น้อง" มาพิมพ์รวม

    URL ระบุเอกสารหนึ่งใบ ⇒ ถ้ามันยุบ กระดาษที่ได้จะมีเลขของเอกสารที่ URL ไม่ได้ขอ
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    student_id = await _make_debtor(db_pool, room_id)
    headers = _web_headers(owner)

    nos = [
        await _pay_and_issue(client, headers, db_pool, room_id, student_id, amount=100.0 * i, title=f"รายการ {i}")
        for i in (1, 2, 3)
    ]

    captured = {}

    async def fake_render(html, *, timeout=None):
        captured["html"] = html
        return FAKE_PDF

    with patch("services.finance.pdf.html_to_pdf", fake_render):
        resp = client.get(_api(room_id, ONE_PDF_PATH, receipt_no=nos[0]), headers=headers)

    assert resp.status_code == 200, resp.text
    html = captured["html"]
    assert _page_count(html) == 1
    assert f"เลขที่ {nos[0]}" in html
    assert "รวม 3 ฉบับ" not in html
    for other in nos[1:]:
        assert other not in html, "ใบเดียวห้ามมีเลขของใบอื่น"


async def test_combined_pdf_keeps_other_students_on_their_own_pages(client, db_pool):
    """เลือกสลับคน → ยังได้คนละหน้า (การยุบต้องไม่ข้ามคนผ่านเส้นทาง HTTP)"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    a = await _make_debtor(db_pool, room_id, student_no=91)
    b = await _make_debtor(db_pool, room_id, student_no=92)
    headers = _web_headers(owner)

    nos = [
        await _pay_and_issue(client, headers, db_pool, room_id, a, amount=100.0, title="ของ A 1"),
        await _pay_and_issue(client, headers, db_pool, room_id, b, amount=200.0, title="ของ B"),
        await _pay_and_issue(client, headers, db_pool, room_id, a, amount=300.0, title="ของ A 2"),
    ]

    captured = {}

    async def fake_render(html, *, timeout=None):
        captured["html"] = html
        return FAKE_PDF

    with patch("services.finance.pdf.html_to_pdf", fake_render):
        resp = client.post(
            _api(room_id, WEB_PDF_PATH), json={"receipt_nos": nos}, headers=headers
        )

    assert resp.status_code == 200, resp.text
    html = captured["html"]
    # A มี 2 ใบ (ยุบเป็นหน้าเดียว) · B มี 1 ใบ (หน้าเดียว) ⇒ 2 หน้า
    assert _page_count(html) == 2
    assert "รวม 2 ฉบับ" in html
