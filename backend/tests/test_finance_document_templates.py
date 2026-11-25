"""💸 [FIN-V2 / P4.6] เทมเพลต PDF ของใบสำคัญจ่าย/ใบรับรอง/ใบรับเงิน (v2)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **dispatch ถูกไฟล์** — PV/CERT/INC ต้องได้ partial ของตัวเอง ไม่ใช่ `_receipt_body.html`
   (ใบสำคัญจ่ายที่หลุดไปใช้ partial ใบเสร็จจะขึ้นถ้อยคำ "ผู้ชำระเงิน"/"ยอดสะสม")
2. **คำอ่านเงินบนกระดาษมาจาก `d.amount`** — snapshot เป็น *หลักฐาน* ไม่ใช่แหล่งความจริง
   ⇒ snapshot ผิด/เก่าแล้วกระดาษต้องยังพิมพ์ยอดที่ระบบบันทึกจริง
3. **PV มีหลายบรรทัด + 3 ลายเซ็น**; **CERT รับรองเฉพาะบรรทัดที่ไม่มีหลักฐาน**;
   **INC 2 ลายเซ็น** (ผู้ออกเอกสาร · ผู้รับเงิน)
4. **ช่องลายมือชื่อที่ไม่มีชื่อต้องเว้นว่าง** — ห้ามพิมพ์ "-" (อ่านว่า "ไม่มีผู้อนุมัติ")
5. **ไฟล์ partial ห้ามมี `<style>`** — shell `receipt.html` ถือ `<style>` เดียว (ฟอนต์ 2 ไฟล์)
   และ PV/CERT ห้ามอ้างคีย์ธง "เป็นหลักฐานรับเงิน" (`is_receipt`)
6. **CERT ห้ามมีคำว่า "ใบเสร็จรับเงิน"** — ชื่อเอกสารเต็มถูกสงวนให้ใบเสร็จเท่านั้น
7. **snapshot ขาดคีย์/ผิดรูปต้องพิมพ์ได้** — คีย์ที่ partial ใช้ถูกตั้งครบเสมอ

⚠️ เทมเพลตทั้งหมดถูกเรนเดอร์ผ่าน `render_receipts_html` ตัวจริง (Jinja + ฟอนต์ฝัง)
   ⇒ เทสต์ยิงถึง TypeError ที่เกิดจาก `Undefined` ได้จริง
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.finance.baht_text import baht_text
from services.finance.pdf import render_receipts_html
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

_FIXED_AT = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "finance"


# ═══════════════════════════════════════════════════════════════ helpers
def _base_doc(doc_type: str, receipt_no: str, **over) -> dict:
    """dict ของเอกสาร v2 ในรูปที่ `_shape_receipt_detail` คืน (พอสำหรับ context)"""
    base = {
        "doc_type": doc_type,
        "doc_type_label": None,
        "receipt_no": receipt_no,
        "amount": 350.0,
        "paid_total_after": 0.0,
        "issued_to_name": "ร้านวัสดุทดสอบ",
        "issued_by_name": "ครูผู้จัดทำ",
        "event_at": _FIXED_AT,
        "issued_at": _FIXED_AT,
        "status": "active",
        "void_reason": None,
        "room_name": "ห้อง ป.5/1",
        "room_code": "P51",
        "student_no": None,
        "note": None,
        "layout_version": 2,
        "document_meta": {},
        "line_items": None,
        "voucher_snapshot": None,
    }
    base.update(over)
    return base


def _pv_doc(**over) -> dict:
    """ใบสำคัญจ่าย 2 บรรทัด (คนละหมวด/กระเป๋า) + 3 ลายเซ็น"""
    snapshot = {
        "layout_version": 2,
        "payee_name": "ร้านวัสดุทดสอบ",
        "payee_person_id": None,
        "voucher_date": "2026-11-20",
        "note": "ซื้อของเข้าห้อง",
        "total_amount": 350.0,
        "default_wallet": {"id": 11, "name": "เงินสดห้อง"},
        "lines": [
            {
                "line_no": 1, "description": "กระดาษ A4", "amount": 250.0,
                "category_name": "วัสดุสำนักงาน", "budget_label": "งบวัสดุ 2569",
                "wallet_name": "เงินสดห้อง", "receipt_status": "attached",
                "paper_bill_count": 1, "funding_source": "room_fund",
            },
            {
                "line_no": 2, "description": "ค่าขนส่ง", "amount": 100.0,
                "category_name": "ค่าขนส่ง", "budget_label": None,
                "wallet_name": "ธนาคารห้อง", "receipt_status": "none",
                "paper_bill_count": 0, "funding_source": "room_fund",
            },
        ],
        "signatures": [
            {"role": "prepared", "signer_name": "ครูผู้จัดทำ"},
            {"role": "approved", "signer_name": "ครูอนุมัติ"},
            {"role": "receiver", "signer_name": "ร้านวัสดุทดสอบ"},
        ],
        "total_paper_bill_count": 1,
    }
    doc = _base_doc(
        "payment_voucher", "PV-2569-0001",
        document_meta={
            "voucher_id": 1,
            "request_hash": "x",
            "line_count": 2,
            "signatures": snapshot["signatures"],
        },
        voucher_snapshot=snapshot,
    )
    doc.update(over)
    return doc


def _cert_doc(**over) -> dict:
    """CERT รับรองเฉพาะบรรทัดที่ 1 และ 3 ของ PV (line_items = บรรทัด none)"""
    doc = _base_doc(
        "certificate", "CERT-2569-0001",
        amount=350.0,
        document_meta={
            "voucher_id": 1,
            "pv_receipt_id": 1,
            "cert_amount": 350.0,
            "source_line_nos": [1, 3],
            "voucher_no": "PV-2569-0001",
            "signatures": [
                {"role": "prepared", "signer_name": "ครูผู้จัดทำ"},
                {"role": "approved", "signer_name": "ครูอนุมัติ"},
            ],
        },
        line_items=[
            {"title": "กระดาษ A4", "amount_applied": "250.00"},
            {"title": "ค่าขนส่ง", "amount_applied": "100.00"},
        ],
    )
    doc.update(over)
    return doc


def _inc_doc(**over) -> dict:
    """INC 2 บรรทัด — ผู้จ่ายเป็นข้อความอิสระ, กระเป๋า/ช่องทางจาก snapshot"""
    channel = {
        "channel_type": "cash", "label": "เงินสดหน้าร้าน",
        "account_name": None, "bank_name": None,
        "account_number_masked": None, "promptpay_id_masked": None,
    }
    signatures = [
        {"role": "prepared", "signer_name": "ครูผู้บันทึก"},
        {"role": "receiver", "signer_name": "ครูสมหญิง"},
    ]
    doc = _base_doc(
        "income", "INC-2569-0001",
        amount=2500.0,
        issued_to_name="ผู้ปกครองนักเรียน ม.2",
        issued_by_name="ครูผู้บันทึก",
        document_meta={
            "batch_id": 1,
            "receiver_name": "ครูสมหญิง",
            "channel": channel,
            "signatures": signatures,
        },
        voucher_snapshot={
            "layout_version": 2,
            "payer_name": "ผู้ปกครองนักเรียน ม.2",
            "wallet": {"id": 11, "name": "เงินสดหน้าร้าน", "is_custody": False},
            "channel": channel,
            "lines": [],
            "signatures": signatures,
        },
        line_items=[
            {"title": "เงินสนับสนุนกิจกรรม", "amount_applied": "2000.00"},
            {"title": "ขายของที่ระลึก", "amount_applied": "500.00"},
        ],
    )
    doc.update(over)
    return doc


def _render(doc: dict) -> str:
    return render_receipts_html([FinanceService._document_context(doc)])


# ═══════════════════════════════ 1. dispatch เลือก partial ของแต่ละชนิด
async def test_v2_dispatch_selects_spend_partials():
    assert FinanceService._document_context(
        _pv_doc()
    )["body_template"] == "_voucher_body_v2.html"
    assert FinanceService._document_context(
        _cert_doc()
    )["body_template"] == "_certificate_body_v2.html"
    assert FinanceService._document_context(
        _inc_doc()
    )["body_template"] == "_income_body_v2.html"


# ═══════════ 2. context ตั้งคีย์ที่ partial อ้างครบทุกตัว (ไม่มี Undefined)
async def test_context_keys_required_by_partials_are_always_set():
    pv = FinanceService._document_context(_pv_doc())
    assert {
        "doc_title", "doc_no_text", "receipt_no", "room_name", "room_code",
        "voucher_date_text", "document_date_text", "voucher_payee_name",
        "voucher_approver_name", "voucher_account_name", "voucher_channel_text",
        "voucher_attachment_count", "voucher_total_paper_bill_count",
        "voucher_lines", "voucher_prepared_name", "voucher_approved_name",
        "voucher_receiver_name", "cert_receipt_no", "cert_amount",
        "amount", "amount_text", "line_items_hidden", "note", "is_voided", "void_reason",
    } <= set(pv)

    cert = FinanceService._document_context(_cert_doc())
    assert {
        "pv_receipt_no", "voucher_payee_name", "cert_source_line_nos", "cert_lines",
        "cert_amount", "cert_amount_text", "cert_prepared_name", "cert_approved_name",
        "line_items_hidden", "amount", "amount_text", "note",
    } <= set(cert)

    inc = FinanceService._document_context(_inc_doc())
    assert {
        "payer_name", "income_receiver_name", "income_wallet_name", "income_channel_text",
        "income_lines", "income_prepared_name", "income_receiver_signer_name",
        "amount", "amount_text", "line_items_hidden", "note",
    } <= set(inc)


# ═══════════════ 3. PV: ตารางหลายบรรทัด + 3 ช่องลายเซ็น
async def test_voucher_html_prints_lines_and_three_signatures():
    html = _render(_pv_doc())
    assert "กระดาษ A4" in html and "ค่าขนส่ง" in html
    assert "วัสดุสำนักงาน" in html and "เงินสดห้อง" in html and "ธนาคารห้อง" in html
    assert "มีหลักฐาน" in html and "ไม่มีหลักฐาน" in html
    assert "250.00" in html and "100.00" in html and "350.00" in html
    # 3 ช่องของใบสั่งจ่าย — slot ต้องจัดวางแบบ 3 ช่อง
    # 🖨️ [A4] shell v2 ใช้แบนด์ลายเซ็นมาตรฐาน (`sig-band`); `.sign sign-3` เป็นของ legacy
    assert "sig-band sig-3" in html
    for role in ("ผู้จัดทำ", "ผู้อนุมัติ", "ผู้รับเงิน"):
        assert role in html
    for name in ("ครูผู้จัดทำ", "ครูอนุมัติ", "ร้านวัสดุทดสอบ"):
        assert name in html


# ═══════ 4. คำอ่านเงินมาจาก `d.amount` ไม่ใช่ snapshot.total_amount
async def test_voucher_amount_text_comes_from_row_amount_not_snapshot():
    snapshot = dict(_pv_doc()["voucher_snapshot"])
    snapshot["total_amount"] = 999999.0  # snapshot ผิด/เก่า
    doc = _pv_doc(voucher_snapshot=snapshot, amount=350.0)

    ctx = FinanceService._document_context(doc)
    assert ctx["amount"] == 350.0
    assert ctx["amount_text"] == baht_text(350.0)

    html = _render(doc)
    assert baht_text(350.0) in html
    assert "350.00" in html
    assert "999,999.00" not in html


# ═══════════ 5. CERT: เฉพาะบรรทัดที่รับรอง + ยอดรวมของ CERT
async def test_certificate_html_lists_only_certified_lines_and_amount():
    ctx = FinanceService._document_context(_cert_doc())
    assert [ln["line_no"] for ln in ctx["cert_lines"]] == [1, 3]
    assert [ln["title"] for ln in ctx["cert_lines"]] == ["กระดาษ A4", "ค่าขนส่ง"]
    assert ctx["cert_amount"] == 350.0
    assert ctx["cert_amount_text"] == baht_text(350.0)

    html = _render(_cert_doc())
    assert "กระดาษ A4" in html and "ค่าขนส่ง" in html
    assert "350.00" in html and "3,50" not in html


# ═══════════ 6. CERT อ้าง PV ต้นทาง + ลำดับบรรทัดที่รับรอง
async def test_certificate_prints_related_voucher_and_source_lines():
    html = _render(_cert_doc())
    assert "PV-2569-0001" in html
    assert "1, 3" in html


# ═══════════ 7. INC: ผู้รับ/กระเป๋า/ช่องทาง + 2 ลายเซ็น
async def test_income_html_prints_receiver_wallet_channel_and_two_signatures():
    html = _render(_inc_doc())
    assert "รับเงินจาก" in html and "ผู้ปกครองนักเรียน ม.2" in html
    assert "ครูสมหญิง" in html
    assert "เงินสดหน้าร้าน" in html
    assert "ช่องทาง" in html
    assert "เงินสนับสนุนกิจกรรม" in html and "ขายของที่ระลึก" in html
    assert "2,500.00" in html
    assert "ผู้ออกเอกสาร" in html and "ผู้รับเงิน" in html
    assert "ครูผู้บันทึก" in html


# ═══════════ 8. คีย์ธง "เป็นหลักฐานรับเงิน" ต่อชนิดเอกสาร
async def test_is_receipt_flag_per_document_type():
    assert FinanceService._document_context(_pv_doc())["is_receipt"] is False
    assert FinanceService._document_context(_cert_doc())["is_receipt"] is False
    assert FinanceService._document_context(_inc_doc())["is_receipt"] is True

    receipt = _base_doc(
        "receipt", "REC-2569-0001",
        line_items=[{"title": "ค่าเทอม", "amount_applied": "350.00", "source": "cash"}],
    )
    assert FinanceService._document_context(receipt)["is_receipt"] is True


# ═══════════ 9. ไฟล์ partial: ไม่มี `<style>`, ไม่มีคีย์ธง, ไม่มีชื่อเอกสารเต็ม
async def test_new_partials_have_no_style_and_no_forbidden_text():
    voucher_src = (_TEMPLATES_DIR / "_voucher_body_v2.html").read_text(encoding="utf-8")
    cert_src = (_TEMPLATES_DIR / "_certificate_body_v2.html").read_text(encoding="utf-8")
    income_src = (_TEMPLATES_DIR / "_income_body_v2.html").read_text(encoding="utf-8")

    for src, name in (
        (voucher_src, "_voucher_body_v2.html"),
        (cert_src, "_certificate_body_v2.html"),
        (income_src, "_income_body_v2.html"),
    ):
        assert "<style" not in src, f"{name} ห้ามมี <style> — shell ถือ style เดียว"

    # 🔴 PV/CERT ห้ามอ้างคีย์ธง "เป็นหลักฐานรับเงิน" (บทเรียน `_voucher_body.html`)
    assert "is_receipt" not in voucher_src
    assert "is_receipt" not in cert_src

    # 🔴 ชื่อเอกสารเต็ม ("ใบเสร็จรับเงิน") สงวนให้ใบเสร็จ — CERT/INC ห้ามมี
    assert "ใบเสร็จรับเงิน" not in cert_src
    assert "ใบเสร็จรับเงิน" not in income_src


# ═══════════ 10. เอกสาร minimal (มีแค่ doc_type/amount/layout) ต้องเรนเดอร์ได้
@pytest.mark.parametrize(
    "doc_type,receipt_no",
    [
        ("payment_voucher", "PV-2569-0099"),
        ("certificate", "CERT-2569-0099"),
        ("income", "INC-2569-0099"),
    ],
)
async def test_minimal_context_renders_without_crashing(doc_type, receipt_no):
    doc = {
        "doc_type": doc_type,
        "receipt_no": receipt_no,
        "amount": 350.0,
        "layout_version": 2,
    }
    html = _render(doc)
    assert receipt_no in html
    assert "350.00" in html, "ยอดรวมต้องพิมพ์ได้แม้ snapshot ว่าง"


# ═══════════ 11. PV ตัดที่ 30 บรรทัด + แถวสรุปจำนวนที่ถูกตัด
async def test_voucher_caps_lines_at_thirty_with_hidden_count():
    lines = [
        {
            "line_no": i + 1, "description": f"รายการที่ {i + 1}", "amount": 10.0,
            "category_name": "วัสดุ", "budget_label": None, "wallet_name": "เงินสดห้อง",
            "receipt_status": "none", "paper_bill_count": 0, "funding_source": "room_fund",
        }
        for i in range(32)
    ]
    snapshot = dict(_pv_doc()["voucher_snapshot"])
    snapshot["lines"] = lines
    doc = _pv_doc(voucher_snapshot=snapshot, amount=320.0)

    ctx = FinanceService._document_context(doc)
    assert len(ctx["voucher_lines"]) == 30
    assert ctx["line_items_hidden"] == 2
    # ยอดรวมยังต้องเป็นยอดจริงของใบ ไม่ใช่ผลบวกของ 30 บรรทัดที่แสดง
    assert ctx["amount"] == 320.0

    html = _render(doc)
    assert "และอีก 2 รายการ" in html
    assert "320.00" in html


# ═══════════ 12. ใบที่ยกเลิก: แบนเนอร์ VOID ต้องประทับทั้งสามชนิด
@pytest.mark.parametrize("factory", [_pv_doc, _cert_doc, _inc_doc])
async def test_void_banner_on_spend_documents(factory):
    html = _render(factory(status="voided", void_reason="บันทึกผิด"))
    assert "void-banner" in html
    assert "บันทึกผิด" in html


# ═══════════ 13. HTML ต้องมี `.doc` เดียวและฟอนต์ 2 ไฟล์ (shell เดียวยังใช้ร่วม)
@pytest.mark.parametrize("factory", [_pv_doc, _cert_doc, _inc_doc])
async def test_single_document_html_uses_shared_shell(factory):
    html = _render(factory())
    assert len(re.findall(r'<div class="doc(?: doc-break)?">', html)) == 1
    # 🔴 นับ `</style>` ไม่ใช่ `<style>` — คอมเมนต์ใน <style> ของ shell อ้างคำว่า `<style>`
    #    ⇒ การนับแท็กเปิดจะได้ 2 ทั้งที่ไฟล์มีบล็อกเดียว
    assert html.count("</style>") == 1
    assert html.count("data:font/ttf;base64,") == 2
