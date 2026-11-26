"""🖨️ [A4] shell ของเอกสาร v2 — เลือกตามเนื้อใน + กระดาษมาตรฐาน + VOID เจ้าของเดียว

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ชุด legacy ล้วนยังได้ `receipt.html` เป๊ะ** — digest ของใบเก่าถูกล็อกไว้แยกแล้ว
   (`test_finance_legacy_pdf_regression.py`) ⇒ shell ใหม่ห้ามรั่วเข้าเส้นทางนั้น
2. **ชุดที่มีเอกสาร v2 อย่างน้อยหนึ่งใบใช้ `receipt_v2.html`** — รวม RPT ที่ไม่มี
   `layout_version` แต่มี `body_template` ลงท้าย `_v2.html`
3. **เอกสาร A4: `@page` เดียว · ฟอนต์ฝังครั้งเดียว · ระยะขอบ 13/15/11 ที่ `.doc`**
4. **แบนเนอร์ VOID เป็นของ shell** — partial v2 ทั้ง 8 ไฟล์ต้องไม่มีคำ `void-banner`
   ไม่งั้นใบที่ถูกยกเลิกจะได้แบนเนอร์ซ้ำ
5. **ชุดผสม: partial legacy ยังอยู่ใน `.legacy-doc`** — ไม่เสียหน้าตาเดิม
6. **หัวกระดาษขวาบน: โลโก้กล่องเปล่า (ไม่มีไทล์สีฟ้า) ชิดมุมบน แล้วบรรทัด
   SYNCROOM / ห้อง … / รหัสห้อง … / โดเมนเว็บ เรียงลงมาใต้โลโก้** (ผู้ใช้กำหนด 2026-11-26)
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from services.finance.pdf import render_receipts_html
from services.finance_service import FinanceService

_FIXED_AT = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "finance"

_V2_PARTIALS = (
    "_receipt_body_v2.html",
    "_invoice_body_v2.html",
    "_acknowledgement_body_v2.html",
    "_deposit_body_v2.html",
    "_voucher_body_v2.html",
    "_certificate_body_v2.html",
    "_income_body_v2.html",
    "_monthly_report_body_v2.html",
)


def _legacy_doc(**over) -> dict:
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


def _v2_receipt_doc(**over) -> dict:
    base = {
        "doc_type": "receipt",
        "doc_type_label": "ใบเสร็จรับเงิน",
        "receipt_no": "REC-2569-0001",
        "amount": 1200.0,
        "paid_total_after": 1200.0,
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
            "amount_received": "1200.00",
        },
        "line_items": [
            {"title": "ค่าเทอม", "bill_amount": "1200.00",
             "amount_applied": "1200.00", "bill_remaining": "0.00", "source": "cash"},
        ],
    }
    base.update(over)
    return base


def _rpt_context(**over) -> dict:
    """context ของ `_monthly_report_context` — มี `body_template` แต่ไม่มี layout_version"""
    base = {
        "body_template": "_monthly_report_body_v2.html",
        "doc_type": "monthly_report",
        "doc_type_label": "รายงานปิดงบ",
        "doc_title": "รายงานปิดงบ",
        "doc_no_text": "RPT-2569-11",
        "receipt_no": "RPT-2569-11",
        "report_no": "RPT-2569-11",
        "year_be": 2569,
        "month": 11,
        "month_text": "พฤศจิกายน",
        "period_start": "2026-11-01",
        "period_end": "2026-11-30",
        "period_start_text": "1 พ.ย. 2569",
        "period_end_text": "30 พ.ย. 2569",
        "version": 1,
        "status": "final",
        "status_text": "ปิดงบแล้ว",
        "is_voided": False,
        "void_reason": None,
        "room_name": "ห้อง ป.5/1",
        "room_code": "P51",
        "total_income": 100.0,
        "total_expense": 40.0,
        "opening_cash": 10.0,
        "closing_cash": 70.0,
        "counted_cash": 70.0,
        "variance": 0.0,
        "income_by_category": [],
        "expense_by_category": [],
        "cash": {"opening": 10.0, "income": 100.0, "expense": 40.0, "closing": 70.0},
        "cash_gap": None,
        "note": None,
        "finalized_at": _FIXED_AT,
        "finalized_date_text": "25 พ.ย. 2569",
        "finalized_time_text": "10:00 น.",
        "prepared_by": "ครูผู้จัดทำ",
        "approved_by": "ครูอนุมัติ",
        "checked_by": "ครูผู้ตรวจสอบ",
    }
    base.update(over)
    return base


# ═════════════════════════ 1. ชุด legacy ล้วน → shell เดิม (padding 14/14/10)
def test_legacy_only_bundle_uses_legacy_shell():
    html = render_receipts_html([FinanceService._document_context(_legacy_doc())])
    assert ".doc { padding: 14mm 14mm 10mm; }" in html
    assert "v2-doc" not in html
    assert 'class="legacy-doc"' not in html


# ═══════════════════════════ 2. ชุดที่มี v2 → shell A4 (padding 13/15/11)
def test_v2_bundle_uses_a4_shell():
    html = render_receipts_html([FinanceService._document_context(_v2_receipt_doc())])
    # กฎ `.doc` ของ shell v2 เขียนหลายบรรทัด ⇒ จับด้วย regex ไม่ใช่ substring ตรง ๆ
    assert re.search(r"\.doc\s*\{[^}]*padding:\s*13mm 15mm 11mm", html)
    assert 'class="v2-doc"' in html
    assert ".doc { padding: 14mm 14mm 10mm; }" not in html


# ═══════════════════════ 3. RPT (ไม่มี layout_version) ก็ได้ shell A4
def test_monthly_report_context_selects_v2_shell():
    html = render_receipts_html([_rpt_context()])
    assert re.search(r"\.doc\s*\{[^}]*padding:\s*13mm 15mm 11mm", html)
    assert "รายงานปิดงบ" in html
    assert "RPT-2569-11" in html


# ═══════════════════════ 4. กระดาษ/ฟอนต์: `@page` เดียว · ฟอนต์ฝังครั้งเดียว
def test_a4_shell_has_single_page_rule_and_fonts():
    html = render_receipts_html([FinanceService._document_context(_v2_receipt_doc())])
    assert html.count("@page { size: A4;") == 1
    assert html.count("@font-face") == 2
    assert html.count("data:font/ttf;base64,") == 2
    assert html.count("</style>") == 1


# ═══════════════════════ 5. VOID: shell เป็นเจ้าของแบนเนอร์ (ครั้งเดียวต่อใบ)
def test_void_banner_owned_by_shell_once_per_voided_doc():
    html = render_receipts_html([
        FinanceService._document_context(
            _v2_receipt_doc(status="voided", void_reason="บันทึกผิด")
        )
    ])
    assert html.count('class="void-banner"') == 1
    assert "บันทึกผิด" in html


# ═══════════════════════ 6. partial v2 ทั้ง 8 ห้ามมี void-banner
def test_no_v2_partial_draws_its_own_void_banner():
    for name in _V2_PARTIALS:
        path = _TEMPLATE_DIR / name
        assert path.is_file(), f"ไม่พบ partial: {path}"
        src = path.read_text(encoding="utf-8")
        assert "void-banner" not in src, f"{name} ต้องไม่วาดแบนเนอร์เอง (shell เป็นเจ้าของ)"


# ═══════════════════════ 7. ชุดผสม: ใบ legacy อยู่ใน `.legacy-doc` (หน้าตาเดิม)
def test_mixed_bundle_wraps_legacy_body_in_legacy_scope():
    html = render_receipts_html([
        FinanceService._document_context(_legacy_doc()),
        FinanceService._document_context(_v2_receipt_doc()),
    ])
    assert 'class="legacy-doc"' in html
    assert "amount-box" in html, "partial legacy ยังต้องวาด markup เดิมของมัน"
    assert 'class="v2-doc"' in html
    # 2 หน้า — legacy 1 + v2 1 · แบ่งหน้าเฉพาะใบแรก
    assert len(re.findall(r'class="doc(?: doc-break)?"', html)) == 2
    assert html.count('class="doc doc-break"') == 1


# ═══════════════════════ 8. กรอบตารางต้องเป็นมุมฉาก (ไม่ถูกหัวตารางทับมุม)
def test_table_frames_use_square_corners():
    """🔴 ผู้ใช้รายงาน 2026-11-26: ทุกมุมของตารางเส้นขาดเหมือนถูกลบ

    สาเหตุ: `.bill-frame` มี `border-radius` แต่ `overflow: visible` ⇒ หัวตาราง
    (พื้นขาวสี่เหลี่ยม) ทับส่วนโค้งของกรอบดำ ⇒ มุมดูเหมือนถูกกัดหาย
    ⇒ กรอบตารางทุกตัวต้องมุมฉาก
    """
    html = render_receipts_html([FinanceService._document_context(_v2_receipt_doc())])
    for selector in (".bill-frame", ".sub-frame"):
        blocks = re.findall(
            re.escape(selector) + r"\s*\{([^}]*)\}", html
        )
        assert blocks, f"ไม่พบกฎ CSS ของ {selector}"
        for block in blocks:
            assert "border-radius: 0" in block or "border-radius" not in block, (
                f"{selector} ต้องไม่ปัดมุม (เส้นกรอบจะถูกหัวตารางทับ)"
            )


# ═══════════════════════ 9. โลโก้จริงของแอป (box-fill) ไม่ใช่ mark ตัวแทน
def test_brand_mark_uses_the_real_app_logo():
    html = render_receipts_html([FinanceService._document_context(_v2_receipt_doc())])
    assert "brand-logo" in html
    # path ของ bootstrap-icons `box-fill` (= frontend/public/box-fill.svg)
    assert "M8.186 1.113" in html
    assert "#1D4ED8" in html, "โลโก้ใช้สีแบรนด์ของแอป (--brand)"
    # 🚫 ผู้ใช้สั่ง 2026-11-26: โลโก้เป็นกล่องเปล่า ๆ ไม่มีไทล์พื้นหลังสีฟ้า
    assert "background-color: #1D4ED8" not in html


# ═══════════════════════ 9. หัวกระดาษขวาบน: โลโก้ชิดมุมบน + ข้อความเรียงใต้โลโก้
def test_brand_block_stacks_logo_on_top_and_room_lines_below():
    html = render_receipts_html([FinanceService._document_context(_v2_receipt_doc())])
    # โลโก้อยู่บรรทัดแรกของก้อน แล้วข้อความเรียงลงมา (flex column, ชิดขวา, ยึดขอบบน)
    assert re.search(
        r"\.std-brand-mark\s*\{[^}]*flex-direction:\s*column", html
    ), "โลโก้ต้องอยู่เหนือข้อความ (เรียงแนวตั้ง)"
    assert re.search(r"\.std-brand-mark\s*\{[^}]*align-items:\s*flex-end", html)
    assert re.search(r"\.std-brand-mark\s*\{[^}]*align-self:\s*flex-start", html)
    # บรรทัดข้อความ: ชื่อระบบ / ห้อง / รหัสห้อง / ที่อยู่เว็บ (เรียงตามนี้)
    name_at = html.index("SYNCROOM")
    room_at = html.index("ห้อง ป.5/1")
    code_at = html.index("รหัสห้อง P51")
    url_at = html.index("class.singto1597.xyz")
    assert name_at < room_at < code_at < url_at
    # ไม่มีวลีแบรนด์เก่า และไม่เติม "ห้อง" ซ้ำเมื่อชื่อห้องมีอยู่แล้ว
    assert "Classroom Finance" not in html
    assert "ห้อง ห้อง" not in html
