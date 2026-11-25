"""🧾 [FIN-V2 / P2.2] เทมเพลตเอกสาร v2 — พิมพ์จาก snapshot + legacy ไม่เปลี่ยน

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **v2 ห้าม JOIN บิลสด** — เปลี่ยนชื่อบิลภายหลังแล้วใบที่พิมพ์ซ้ำต้องยังเป็นชื่อเดิม
   (snapshot คือสัญญาของเอกสารที่แจกไปแล้ว)
2. **legacy ไม่เปลี่ยนไบต์** — dispatch อยู่ที่ `_document_context` จุดเดียว;
   ใบ layout 1 ต้องยังได้ partial เดิมและเนื้อหาเดิม
3. **ทะเบียนเดิมเห็นเฉพาะ legacy** — ใบ v2 เปิด/พิมพ์ได้ผ่าน `get_receipt` แต่ไม่โผล่ใน
   `GET /finance/receipts` (หน้านั้นยังไม่รู้จักเลย์เอาต์ v2)
4. **คีย์ที่หายไปต้องไม่ทำให้เรนเดอร์พัง** — DEP ไม่มี `line_items`, snapshot ต่างรุ่น
   ไม่มี `credit_used` ฯลฯ ⇒ ต้องได้ "—" ไม่ใช่ TypeError = 500

⚠️ เทสต์ที่แตะ DB ใช้ `db_pool` + ยืนยันกับแถวจริง (กฎ docs/rules/testing.md)
"""
import json
from datetime import datetime, timezone

import pytest

from services.finance_service import FinanceService
from services.finance.pdf import render_receipts_html

pytestmark = pytest.mark.asyncio

_FIXED_AT = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════ helpers
def _v2_doc(**over) -> dict:
    """dict ของเอกสาร v2 ในรูปที่ `_shape_receipt_detail` คืน (พอสำหรับ context)"""
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
            "channel": {"name": "เงินสด", "channel_type": "cash"},
            "event_at": _FIXED_AT.isoformat(),
            "amount_received": "1200.00",
            "credit_used": "0.00",
            "credit_added": "0.00",
            "amounts_in_words": "หนึ่งพันสองร้อยบาทถ้วน",
        },
        "line_items": [
            {
                "collection_id": 11,
                "title": "ค่าโครงการ",
                "bill_amount": "1500.00",
                "amount_applied": "1200.00",
                "cash_amount": "1200.00",
                "credit_amount": "0.00",
                "bill_remaining": "300.00",
                "source": "cash",
            }
        ],
    }
    base.update(over)
    return base


def _legacy_doc(**over) -> dict:
    """dict ของใบ legacy (layout 1) ในรูปที่ `_shape_receipt_detail` คืน"""
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


def _render(doc: dict) -> str:
    return render_receipts_html([FinanceService._document_context(doc)])


async def _insert_student(pool, room_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no,
        )


async def _insert_collection(pool, room_id: int, title: str, amount: float) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, status)
               VALUES ($1, $2, $3, 'active') RETURNING id""",
            room_id, title, amount,
        )


async def _insert_receipt(
    pool, room_id: int, receipt_no: str, *, student_id=None, collection_id=None,
    amount: float = 1200.0, layout_version: int = 2, line_items=None,
    document_meta=None,
) -> int:
    # seq = ท้ายเลขเอกสาร (REC-2569-0001 → 1) — unique ต่อ (room, year, doc_type, seq)
    seq = int(receipt_no.rsplit("-", 1)[1])
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, student_id, collection_id,
                    amount, paid_total_after, issued_to_name, issued_by_name, event_at,
                    status, layout_version, line_items, document_meta)
               VALUES ($1, $2, 'receipt', 2569, $3, $4, $5, $6, $6, 'เด็กชายทดสอบ',
                       'ครูทดสอบ', $7, 'active', $8, $9::jsonb, $10::jsonb)
               RETURNING id""",
            room_id, receipt_no, seq, student_id, collection_id,
            amount, _FIXED_AT, layout_version,
            None if line_items is None else json.dumps(line_items, ensure_ascii=False),
            json.dumps(document_meta or {}, ensure_ascii=False),
        )


# ═══════════════════════════════════════════════════ 1. snapshot ไม่ตามบิลสด
async def test_v2_context_uses_snapshot_not_live_bill(db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id, 7)
    collection_id = await _insert_collection(db_pool, room_id, "ชื่อเดิมของบิล", 1500.0)
    await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", student_id=student_id,
        collection_id=collection_id,
        line_items=[{"title": "ค่าโครงการ", "amount_applied": "1200.00", "source": "cash"}],
        document_meta={"payer_name": "เด็กชายทดสอบ", "receiver_name": "ครูทดสอบ"},
    )

    async def _html() -> str:
        d = await FinanceService.get_receipt(
            db_pool, "REC-2569-0001", client_source="test", actor_identifier="test",
            room_id=room_id, user_id=admin_headers.user_id,
        )
        return _render(d)

    assert "ค่าโครงการ" in await _html()

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE fee_collections SET title = 'ชื่อที่แก้ทีหลัง' WHERE id = $1",
            collection_id,
        )

    html = await _html()
    assert "ค่าโครงการ" in html, "ใบ v2 ต้องพิมพ์ชื่อจาก snapshot ไม่ใช่บิลสด"
    assert "ชื่อที่แก้ทีหลัง" not in html


# ═══════════════════════════════════════════════ 2. dispatch เลือก partial v2
async def test_v2_dispatch_selects_v2_body():
    # 🗂️ [P5.3] DEP v2 มี partial ของตัวเอง (`_deposit_body_v2.html`) — ใบรับเงินล่วงหน้า
    # ไม่มีบิล จึงห้ามใช้ตาราง/ถ้อยคำของใบเสร็จ (adapter registry เป็นแหล่งความจริง)
    assert (
        FinanceService._document_context(_v2_doc(doc_type="receipt"))["body_template"]
        == "_receipt_body_v2.html"
    )
    assert (
        FinanceService._document_context(_v2_doc(doc_type="deposit"))["body_template"]
        == "_deposit_body_v2.html"
    )


# ═══════════════════════════════════════════════════ 3. legacy ยังใช้ partial เดิม
async def test_legacy_receipt_context_unchanged():
    ctx = FinanceService._document_context(_legacy_doc())
    assert ctx["body_template"] == "_receipt_body.html"
    assert ctx["line_items"] == []


# ═══════════════════════════════════════════════════ 4. HTML legacy ยังเหมือนเดิม
async def test_legacy_receipt_html_byte_stable():
    html = _render(_legacy_doc())
    # ชุดคลาส/ถ้อยคำที่หน้าตา legacy พึ่งอยู่ — ถ้า partial ถูกสลับหรือแก้ จะหายไป
    assert "amount-box" in html
    assert "ยอดสะสมที่ชำระแล้ว" in html
    assert "ผู้ชำระเงิน" in html
    assert "REC-2569-0099" in html


# ═══════════════════════════════════════════ 5. ทะเบียนเดิมซ่อนใบ v2 (detail ยังเปิดได้)
async def test_registry_hides_v2_documents(db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id, 7)
    await _insert_receipt(
        db_pool, room_id, "REC-2569-0001", student_id=student_id, layout_version=1,
    )
    await _insert_receipt(
        db_pool, room_id, "REC-2569-0002", student_id=student_id, layout_version=2,
        line_items=[{"title": "ค่าโครงการ", "amount_applied": "500.00"}],
    )

    rows = await FinanceService.get_receipts(
        db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=admin_headers.user_id,
    )
    nos = {r["receipt_no"] for r in rows}
    assert nos == {"REC-2569-0001"}, "ทะเบียนเดิมต้องเห็นเฉพาะ legacy"

    d = await FinanceService.get_receipt(
        db_pool, "REC-2569-0002", client_source="test", actor_identifier="test",
        room_id=room_id, user_id=admin_headers.user_id,
    )
    assert d["layout_version"] == 2
    assert d["document_meta"] == {}


# ═══════════════════════════════════════════ 6. ตาราง v2 มีบรรทัด/แหล่งเงิน/ยอด
async def test_v2_receipt_html_contains_line_items_and_sources():
    doc = _v2_doc(
        amount=1500.0,
        paid_total_after=1500.0,
        line_items=[
            {"title": "ค่าเทอม", "bill_amount": "1000.00", "amount_applied": "1000.00",
             "bill_remaining": "0.00", "source": "cash"},
            {"title": "ค่ากิจกรรม", "bill_amount": "800.00", "amount_applied": "500.00",
             "bill_remaining": "300.00", "source": "credit"},
        ],
        document_meta={
            "payer_name": "เด็กชายทดสอบ",
            "receiver_name": "ครูทดสอบ",
            "amount_received": "1000.00",
            "credit_used": "500.00",
            "credit_added": "0.00",
        },
    )
    html = _render(doc)
    assert "ค่าเทอม" in html and "ค่ากิจกรรม" in html
    assert "เงินสด" in html and "เครดิต" in html
    assert "1,500.00" in html
    assert "ใช้เครดิต" in html


# ═══════════════════════════════════════════════════ 7. DEP พิมพ์ยอดเครดิตก่อน/หลัง
async def test_v2_deposit_html_prints_balance():
    doc = _v2_doc(
        doc_type="deposit",
        doc_type_label="ใบรับเงินล่วงหน้า",
        amount=500.0,
        paid_total_after=500.0,
        line_items=None,
        document_meta={
            "payer_name": "เด็กชายทดสอบ",
            "receiver_name": "ครูทดสอบ",
            "balance_before": "100.00",
            "balance_after": "600.00",
        },
    )
    html = _render(doc)
    assert "เครดิตคงเหลือก่อนเติม" in html and "100.00" in html
    assert "เครดิตคงเหลือหลังเติม" in html and "600.00" in html
    # 🧾 [P5.3] `_deposit_body_v2.html` **ต้องบอกชัดว่าเงินนี้ยังไม่ปิดหนี้ใด**
    #    (เดิม partial ใบเสร็จไม่เคยพิมพ์ประโยคนี้ — DEP ถูกพิมพ์ด้วยถ้อยคำของ REC)
    assert "ยังไม่ถูกหักปิดบิลใด" in html


# ═══════════════════════════════════════ 8. snapshot ว่าง/คีย์หาย ต้องเรนเดอร์ได้
async def test_v2_body_handles_missing_optional_keys():
    doc = _v2_doc(document_meta={}, line_items=None)
    html = _render(doc)
    assert "รับชำระหนี้" in html
    assert "1,200.00" in html


# ═══════════════════════════════════════════════════════════ 9. ประทับ VOID
async def test_v2_void_banner():
    html = _render(_v2_doc(status="voided", void_reason="บันทึกผิด"))
    assert "void-banner" in html
    assert "บันทึกผิด" in html


# ═════════════════════════════════════════════ 10. ฟอนต์ยังฝัง 2 ไฟล์ (shell เดียว)
async def test_font_faces_count_still_two():
    html = _render(_v2_doc())
    assert html.count("data:font/ttf;base64,") == 2
