"""🗂️ [FIN-V2 / P5.3] Document adapter registry — หนึ่งคู่ (layout, ชนิด) หนึ่งตัว

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ล็อกสัญญา 7 ข้อของ `document_adapters.py` (ตาม brief P5.3)
═══════════════════════════════════════════════════════════════════════════════
1. legacy (layout 1) แยกไฟล์ตามชนิด — ใบสำคัญ ≠ ใบเสร็จ
2. v2 deposit มี partial ของตัวเอง (`_deposit_body_v2.html`)
3. ไม่มี v2 → ถอยไป legacy + warning `finance.document_adapter.missing` (ไม่ 500)
4. ไม่มีทั้งคู่ → `ValueError` ข้อความไทยระบุ doc_type + layout_version (router → 400)
5. legacy/v2 ของชนิดเดียวกันไม่ชนกัน (คนละคีย์)
6. DEP v2 **ไม่มีคีย์ของบิล** ที่มีความหมาย — ไม่มีตารางยอดเต็ม/คงเหลือรายบิล
7. คีย์ snapshot ที่หายไปต้องเรนเดอร์ได้ ( `is mapping` กัน `Undefined` )

➕ เทสต์เพิ่มเพื่อกันกับดักที่ brief ระบุว่า "TemplateNotFound จะเกิดตอนกดพิมพ์":
   - ทุก `body_template` ที่ลงทะเบียนต้องมีไฟล์จริงใน `templates/finance/`
   - registry ต้องตรงกับ `_body_template_for` ของ layout 2 (ไม่มีทางแยกคู่ขนาน)
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.finance import document_adapters as da
from services.finance.pdf import render_receipts_html
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

_FIXED_AT = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "finance"


# ═══════════════════════════════════════════════════════════════════ helpers
def _v2_deposit_doc(**over) -> dict:
    """แถว DEP v2 ในรูปที่ `_shape_receipt_detail` คืน (คีย์ครบตาม `_document_context_v2`)"""
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
        "note": None,
        "layout_version": 2,
        "document_meta": {
            "payer_name": "เด็กชายทดสอบ",
            "receiver_name": "ครูทดสอบ",
            "channel": {"name": "เงินสด", "channel_type": "cash"},
            "balance_before": "100.00",
            "balance_after": "600.00",
        },
        # 🔴 DEP ไม่มีรายการย่อยรายบิล — NULL โดยเจตนาที่ `_issue_event_deposit`
        "line_items": None,
    }
    base.update(over)
    return base


def _render(doc: dict) -> str:
    return render_receipts_html([FinanceService._document_context(doc)])


# ═══════════════════════════════════════════ 1. legacy แยกไฟล์ตามชนิด
async def test_resolve_adapter_returns_legacy_for_layout_1():
    receipt = da.resolve_adapter(1, "receipt")
    assert receipt.body_template == "_receipt_body.html"
    assert receipt.layout_version == 1
    voucher = da.resolve_adapter(1, "payment_voucher")
    assert voucher.body_template == "_voucher_body.html"


# ═══════════════════════════════════════════ 2. v2 deposit
async def test_resolve_adapter_returns_v2_deposit():
    adapter = da.resolve_adapter(2, "deposit")
    assert adapter.layout_version == 2
    assert adapter.doc_type == "deposit"
    assert adapter.body_template == "_deposit_body_v2.html"
    assert adapter.can_print is True


# ═══════════════════════════════════════════ 3. fallback + warning
async def test_resolve_adapter_falls_back_to_legacy_when_v2_missing(monkeypatch, caplog):
    # ใช้ชนิดสมมติลงทะเบียนเฉพาะในเทสต์ — ไม่แตะ registry จริงของโมดูล
    probe = da.DocumentAdapter(
        layout_version=1,
        doc_type="legacy_probe",
        body_template=da.LEGACY_RECEIPT_BODY,
        build_context=lambda d: d,
    )
    monkeypatch.setitem(da._ADAPTERS, (1, "legacy_probe"), probe)

    with caplog.at_level(logging.WARNING):
        got = da.resolve_adapter(2, "legacy_probe")

    assert got.body_template == da.LEGACY_RECEIPT_BODY
    # คง layout ที่ผู้ขอไว้ — ผู้เรียกใช้ตัดสินใจเองว่าจะพิมพ์แบบไหน
    assert got.layout_version == 2
    assert "finance.document_adapter.missing" in caplog.text


# ═══════════════════════════════════════════ 4. ไม่มีทั้งคู่ → ValueError
async def test_resolve_adapter_raises_when_nothing_registered():
    with pytest.raises(ValueError) as excinfo:
        da.resolve_adapter(2, "no_such_doc_type")
    message = str(excinfo.value)
    assert "no_such_doc_type" in message
    assert "2" in message


# ═══════════════════════════════════════════ 5. legacy/v2 ไม่ชนกัน
async def test_legacy_and_v2_registry_do_not_collide():
    keys = da.registered_keys()
    assert (1, "receipt") in keys
    assert (2, "receipt") in keys
    assert da.resolve_adapter(1, "receipt").body_template != (
        da.resolve_adapter(2, "receipt").body_template
    )


# ═══════════════════════════════════════════ 6. DEP v2 ไม่มีคีย์ของบิล
async def test_deposit_v2_context_has_no_bill_keys():
    ctx = FinanceService._document_context(_v2_deposit_doc())

    assert ctx["body_template"] == "_deposit_body_v2.html"
    assert ctx["layout_version"] == 2
    # 🔴 ใบนี้ไม่ผูกบิล ⇒ คีย์ของบิลต้อง "ไม่มีความหมาย" (None) ไม่ใช่ 0.00
    assert ctx["collection_amount"] is None
    assert ctx["remaining"] is None

    html = _render(_v2_deposit_doc())
    assert "ยังไม่ถูกหักปิดบิลใด" in html
    # ตารางของใบเสร็จ (ยอดเต็ม/รับครั้งนี้/คงเหลือรายบิล) ต้องไม่หลุดมาบนใบนี้
    # ⚠️ ห้ามเทียบด้วยข้อความ "ยอดเต็ม" — shell มี CSS comment ที่พูดถึงป้ายนั้น
    #    ⇒ ใช้โครงสร้าง: partial ใบเสร็จมี `<table class="items">` เสมอ
    assert '<table class="items"' not in html
    assert "รับครั้งนี้" not in html


# ═══════════════════════════════════════════ 7. คีย์หาย → ยังเรนเดอร์ได้
async def test_deposit_v2_body_renders_with_missing_optional_keys():
    ctx = FinanceService._document_context(_v2_deposit_doc(document_meta={}))
    # `event_meta` ถูกตั้งเสมอโดย `_document_context_v2` — ตัดทิ้งเพื่อพิสูจน์ว่า
    # partial ใช้ `is mapping` ก่อน `.get()` ไม่ใช่พึ่ง `is not none`
    ctx.pop("event_meta")
    html = render_receipts_html([ctx])

    assert "500.00" in html
    assert "ยังไม่ถูกหักปิดบิลใด" in html
    assert ">None<" not in html and ">None " not in html


# ═══════════════════════════════════════ ➕ ไฟล์เทมเพลตต้องมีจริง
async def test_registered_templates_exist_on_disk():
    for layout, doc_type in da.registered_keys():
        adapter = da.resolve_adapter(layout, doc_type)
        path = _TEMPLATE_DIR / adapter.body_template
        assert path.is_file(), f"adapter {(layout, doc_type)} ชี้ไฟล์ที่ไม่มี: {path}"


# ═══════════════════════════════════ ➕ registry ตรงกับ _body_template_for
async def test_registry_agrees_with_body_template_for_for_layout_2():
    """ทางแยกคู่ขนาน = ใบที่ adapter บอกไฟล์หนึ่งแต่พิมพ์อีกไฟล์ (ไม่มีอะไรฟ้อง)

    ⚠️ ตรวจเฉพาะ layout 2 — layout 1 ใน `_body_template_for` ยุบทุกชนิดที่ไม่ใช่
       ใบสำคัญเป็น `_receipt_body.html` ซึ่ง *ถูก* แล้วสำหรับทางเดิม
    """
    checked = 0
    for layout, doc_type in da.registered_keys():
        if layout < 2:
            continue
        adapter = da.resolve_adapter(layout, doc_type)
        dispatch = FinanceService._body_template_for(
            {"doc_type": doc_type, "layout_version": layout}
        )
        assert dispatch == adapter.body_template, f"drift ที่ {(layout, doc_type)}"
        checked += 1
    # กันเทสต์กลวง — ต้องมีชนิด v2 ให้ตรวจจริงอย่างน้อย 5 ชนิดในสาขานี้
    assert checked >= 5
