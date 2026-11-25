"""🧾 [FIN-V2 / P5.3] Legacy PDF ต้องไม่เปลี่ยนไบต์ — regression ด้วย SHA-256

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องล็อกด้วย digest
═══════════════════════════════════════════════════════════════════════════════
P5.3 ย้ายทางแยก `body_template` จาก ternary ใน `_document_context` ไปเป็น
`resolve_adapter(1, doc_type)` ⇒ ถ้า registry ผิดคีย์เดียว ใบเก่าจะเปลี่ยนไป
พิมพ์ด้วยเทมเพลตอื่น **โดยไม่มี exception ฟ้อง** (ใบยังออกได้ แค่ผิดใบ)

📌 เก็บ digest ของ HTML ที่ **มาสก์ฟอนต์ base64 แล้ว** (ไม่เก็บ HTML ทั้งก้อน):
   - ฟอนต์คือ data URI ~45KB × 2 ไฟล์ ⇒ baseline จะใหญ่กว่าโค้ดจริงหลายเท่า
   - ฟอนต์ถูก pin ไว้ใน `constants.py` อยู่แล้ว ไม่ใช่สิ่งที่เทสต์นี้ต้องคุม
   ⇒ เทสต์นี้คุม **โครง/ถ้อยคำ/ตัวเลข** ซึ่งเป็นสิ่งที่ regression จริงจะกระทบ

➕ เทสต์ชุดผสม (legacy + v2 ในคำขอเดียว) พิสูจน์ว่า shell เดียว + `{% include %}`
   ต่อใบทำงานได้: `<style>` (ฟอนต์) ต้องปรากฏครั้งเดียว ไม่ใช่ต่อหน้า
"""
import hashlib
import re
from datetime import datetime, timezone

import pytest

from services.finance.pdf import render_receipts_html
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

_FIXED_AT = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)

# 🔒 baseline digest ของ HTML legacy (มาสก์ฟอนต์แล้ว) — ถ้าเทสต์แดงอย่าเพิ่ง
#    "อัปเดตค่า": ตรวจก่อนว่าไบต์ที่เปลี่ยนเป็นเพราะเจตนา (เช่น แก้ถ้อยคำที่อนุมัติแล้ว)
#    หรือเพราะ adapter ชี้ผิดไฟล์ — หลังบ้านของ P5.3 ต้องการกรณีหลัง
_LEGACY_RECEIPT_SHA256 = (
    "f9cb46fb4b15ad9a210e1ae4f1cc24e8c90c048e9c1fc8b322dff86035f32e1f"
)
_LEGACY_VOUCHER_SHA256 = (
    "d93ca3a405b2fbff4c389a935dc90133be018b8f953ef21032a50ebebdfc3f0b"
)

_FONT_URI_RE = re.compile(r"url\('data:font/[^']+'\)")


def _mask_fonts(html: str) -> str:
    return _FONT_URI_RE.sub("url('<FONT>')", html)


def _sha(html: str) -> str:
    return hashlib.sha256(_mask_fonts(html).encode("utf-8")).hexdigest()


def _legacy_doc(**over) -> dict:
    """แถว legacy (layout 1) ในรูปที่ `_shape_receipt_detail` คืน"""
    base = {
        "doc_type": "receipt",
        "doc_type_label": "ใบเสร็จรับเงิน",
        "receipt_no": "REC-2569-0099",
        "amount": 500.0,
        "paid_total_after": 500.0,
        "issued_to_name": "เด็กชายเก่า",
        "issued_by_name": "ครูเก่า",
        "event_at": _FIXED_AT,
        "issued_at": _FIXED_AT,
        "status": "active",
        "void_reason": None,
        "room_name": "ห้อง ป.5/1",
        "room_code": "P51",
        "student_no": 3,
        "note": None,
        "layout_version": 1,
        "collection_title": "ค่าเทอม",
        "collection_due_date": None,
        "collection_amount": None,
        "line_items": None,
        "approver_name": None,
        "attachment_count": 0,
        "account_name": None,
        "category_name": None,
        "budgets": [],
    }
    base.update(over)
    return base


def _legacy_voucher_doc() -> dict:
    return _legacy_doc(
        doc_type="payment_voucher",
        doc_type_label="ใบสำคัญจ่าย",
        receipt_no="PV-2569-0003",
        amount=1250.0,
        paid_total_after=1250.0,
        issued_to_name="ร้านค้าวัสดุ",
        note="ซื้ออุปกรณ์การเรียน",
        account_kind="cash",
    )


def _v2_deposit_doc(**over) -> dict:
    base = {
        "doc_type": "deposit",
        "doc_type_label": "ใบรับเงินล่วงหน้า",
        "receipt_no": "DEP-2569-0001",
        "amount": 500.0,
        "paid_total_after": 500.0,
        "issued_to_name": "เด็กชายทดสอบ",
        "issued_by_name": "ครูทดสอบ",
        "event_at": _FIXED_AT,
        "issued_at": _FIXED_AT,
        "status": "active",
        "void_reason": None,
        "room_name": "ห้อง ป.5/1",
        "room_code": "P51",
        "student_no": 7,
        # 🔑 ใส่ `student_id` เดียวกันสองใบ — ถ้าไม่มี P5.3 guard มันจะถูกยุบเป็นหน้าเดียว
        "student_id": 7,
        "note": None,
        "layout_version": 2,
        "document_meta": {
            "payer_name": "เด็กชายทดสอบ",
            "receiver_name": "ครูทดสอบ",
            "balance_before": "100.00",
            "balance_after": "600.00",
        },
        "line_items": None,
    }
    base.update(over)
    return base


# ═══════════════════════════════════════════ 8. legacy receipt ไบต์เดิม
async def test_legacy_receipt_html_unchanged():
    context = FinanceService._document_context(_legacy_doc())
    html = render_receipts_html([context])
    assert context["body_template"] == "_receipt_body.html"
    assert _sha(html) == _LEGACY_RECEIPT_SHA256


# ═══════════════════════════════════════════ 9. legacy voucher ไบต์เดิม
async def test_legacy_voucher_html_unchanged():
    context = FinanceService._document_context(_legacy_voucher_doc())
    html = render_receipts_html([context])
    assert context["body_template"] == "_voucher_body.html"
    assert _sha(html) == _LEGACY_VOUCHER_SHA256


# ═══════════════════════════════════ 10. ชุดผสม: legacy 2 ใบ + v2 1 ใบ
async def test_mixed_bundle_renders_two_body_templates():
    docs = [
        FinanceService._document_context(_legacy_doc()),
        # ใบที่สองต่างเลข/คน เพื่อไม่ให้ถูกยุบรวมกับใบแรก
        FinanceService._document_context(
            _legacy_doc(receipt_no="REC-2569-0100", issued_to_name="เด็กหญิงเก่า")
        ),
        FinanceService._document_context(_v2_deposit_doc()),
    ]
    html = render_receipts_html(docs)

    # marker ของ partial legacy (ถ้อยคำใบเสร็จ) ปรากฏ 2 ครั้ง = 2 ใบ
    assert html.count("ได้รับเงินจาก") == 2
    # marker ที่มีเฉพาะ `_deposit_body_v2.html`
    assert "ยังไม่ถูกหักปิดบิลใด" in html
    # 🔴 ฟอนต์ base64 (~45KB/ไฟล์) ต้องถูกฝังครั้งเดียวต่อไฟล์ — ไม่ใช่ต่อ `.doc`
    # ⚠️ ห้ามนับ `<style>` — CSS comment ใน shell เขียนคำนั้นไว้อีกครั้ง
    assert html.count("@page { size: A4;") == 1
    assert html.count("data:font/ttf;base64,") == 2


# ═══════════════════════════ 11. layout_version/event_at NULL ยังพิมพ์ได้
async def test_legacy_pdf_no_500_when_layout_version_null():
    doc = _legacy_doc(layout_version=None, event_at=None)
    context = FinanceService._document_context(doc)
    html = render_receipts_html([context])

    # `layout_version` NULL → ถือเป็น legacy (1) และวันที่ถอยไปใช้ `issued_at`
    assert context["body_template"] == "_receipt_body.html"
    assert "REC-2569-0099" in html
    assert "25 พ.ย. 2569" in html
    assert _sha(html) == _LEGACY_RECEIPT_SHA256


# ═══════════════════════════ 12. v2 ติดกันหลายใบไม่ถูกยุบรวมหน้าข้ามเทมเพลต
async def test_v2_documents_are_never_merged_into_one_page():
    docs = [
        FinanceService._document_context(_v2_deposit_doc()),
        FinanceService._document_context(
            _v2_deposit_doc(receipt_no="DEP-2569-0002", amount=250.0)
        ),
    ]
    contexts = FinanceService._document_contexts(docs)

    assert len(contexts) == 2
    assert all(ctx["is_merged"] is False for ctx in contexts)
