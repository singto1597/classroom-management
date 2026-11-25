"""🧾 [FIN-V2 / P2.2] context ของเอกสาร `layout_version=2` — พิมพ์จาก snapshot

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
P2.1 เริ่มออกเอกสารระดับ **event**: REC 1 ใบต่อ 1 รายการรับเงิน (หลาย `line_items`)
และ DEP ของเงินส่วนเกิน — เอกสารพวกนี้มี `layout_version=2` และเก็บ snapshot
(`line_items` + `document_meta`) ไว้เอง

`_document_context` ใน `receipts.py` ถูกสร้างรอบ **บิล** (`collection_id`,
`student_payment_id`) ⇒ อ่าน snapshot คนละรูป และถ้าเอาไปใช้กับ v2 ตรง ๆ
จะได้ "-" ในช่องรายการแทนที่จะเป็นตารางหลายบรรทัด

⚠️ ขอบเขตของ package นี้: REC/DEP เท่านั้น — INV/ACK/CERT/RPT เป็นของเฟสถัดไป
   (`_body_template_for` จึงถอยไปใช้ partial เดิมพร้อม log เตือน ไม่ raise
   เพื่อไม่ให้ "พิมพ์ไม่ได้" กลายเป็น 500)

🔴 สัญญา snapshot: v2 **ห้าม JOIN บิลสด** — ชื่อบิล/ยอดที่พิมพ์ต้องมาจาก
   `line_items` ที่บันทึกตอนออกเอกสารเท่านั้น ⇒ แก้ `fee_collections.title`
   ภายหลังไม่เปลี่ยนกระดาษที่แจกไปแล้ว
"""
import json
import logging
from typing import Optional

from .baht_text import baht_text
from .constants import (
    DOC_STATUS_VOIDED, DOC_TYPE_DEPOSIT, DOC_TYPE_LABELS, DOC_TYPE_RECEIPT,
)

logger = logging.getLogger(__name__)

# 🖨️ ทางแยกของ `body_template` — shell `receipt.html` ใช้ร่วมทุก layout
_V2_RECEIPT_BODY_TEMPLATE = "_receipt_body_v2.html"
_LEGACY_RECEIPT_BODY_TEMPLATE = "_receipt_body.html"

# ✂️ v2 ตั้งใจให้เห็นครบกว่า legacy (12) เพราะ 1 ใบ = 1 ครั้งรับเงินของบิลหลายใบ
#    ⚠️ ยอดรวมยังพิมพ์จาก `amount` เสมอ ไม่ใช่ผลบวกของบรรทัดที่แสดง
_V2_MAX_PRINTED_LINE_ITEMS = 20

# 💰 ป้าย "แหล่งเงิน" ของแต่ละบรรทัด (ตรงกับ `source` ที่ P2.1 เขียนลง snapshot)
_SOURCE_LABELS = {"cash": "เงินสด", "credit": "เครดิต", "mixed": "เงินสด + เครดิต"}

# 🚨 เตือนครั้งเดียวต่อ doc_type — ไม่ให้ log ท่วมตอนพิมพ์ชุดใหญ่
_warned_unsupported: set = set()


class DocumentsMixin:
    """ตัวประกอบ context ของเอกสาร v2 (ใช้ผ่าน MRO ของ `FinanceService`)"""

    # ─────────────────────────────────────────────────────────────── ทางแยกเทมเพลต
    @classmethod
    def _body_template_for(cls, d: dict) -> str:
        """เอกสารนี้ใช้ partial ไหนของ shell

        - REC/DEP (layout 2) → `_receipt_body_v2.html`
        - layout 2 ชนิดอื่นที่ยังไม่มีเทมเพลต (INV/ACK/CERT/PV/INC ในเฟสนี้)
          → ถอยไป partial เดิม + เตือนครั้งเดียว (พิมพ์ได้ ดีกว่า 500)
        """
        layout = int(d.get("layout_version") or 1)
        doc_type = d.get("doc_type")
        if layout >= 2 and doc_type in (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT):
            return _V2_RECEIPT_BODY_TEMPLATE
        if layout >= 2 and doc_type not in _warned_unsupported:
            _warned_unsupported.add(doc_type)
            logger.warning(
                "[FIN-V2] ยังไม่มีเทมเพลต v2 สำหรับ doc_type=%s — ใช้ partial เดิมชั่วคราว",
                doc_type,
            )
        return _LEGACY_RECEIPT_BODY_TEMPLATE

    # ─────────────────────────────────────────────────────────────── บรรทัดรายการ
    @classmethod
    def _v2_line_items(cls, d: dict) -> tuple:
        """`line_items` ของ snapshot → (บรรทัดที่พิมพ์, จำนวนที่ถูกตัด) สูงสุด 20

        🔴 แปลงทุกยอดเป็น `float` ที่นี่ — `Decimal` ที่หลุดถึง `"{:,.2f}".format()`
           จะพังตอนเรนเดอร์ และ jsonb ที่ asyncpg คืนมาเป็น **สตริง** ต้อง parse ก่อน
        """
        items = cls._parse_line_items(d.get("line_items")) or []
        printed, hidden = [], 0
        for it in items:
            title = it.get("title")
            applied = it.get("amount_applied")
            if not title and applied is None:
                continue
            if len(printed) >= _V2_MAX_PRINTED_LINE_ITEMS:
                hidden += 1
                continue
            source = it.get("source")
            printed.append({
                "title": title or "รายการชำระเงิน",
                "bill_amount": _as_float_or_none(it.get("bill_amount")),
                "amount_applied": _as_float_or_none(applied) or 0.0,
                "bill_remaining": _as_float_or_none(it.get("bill_remaining")),
                "source_text": _SOURCE_LABELS.get(source),
            })

        if not printed:
            # 🧾 DEP ไม่มี `line_items` โดยเจตนา (เงินยังไม่ผูกบิล) — ใช้ถ้อยคำของ
            #    ใบรับเงินล่วงหน้า ไม่ใช่ "รับชำระหนี้" ที่สื่อว่ามีหนี้อยู่
            amount = _as_float_or_none(d.get("amount")) or 0.0
            title = (
                "รับเงินล่วงหน้า" if d.get("doc_type") == DOC_TYPE_DEPOSIT
                else "รับชำระหนี้"
            )
            printed = [{
                "title": title,
                "bill_amount": None,
                "amount_applied": amount,
                "bill_remaining": None,
                "source_text": None,
            }]
        return printed, hidden

    # ─────────────────────────────────────────────────────────────── context
    @classmethod
    def _document_context_v2(cls, d: dict) -> dict:
        """dict ของเอกสาร v2 → context ที่ `_receipt_body_v2.html` อ่าน

        🔴 ตั้งคีย์ให้ครบตามสัญญาของ `_document_context` เดิม (คีย์ที่ template
           ใช้ `{{ }}` ต้องมีเสมอ — `Undefined` ที่ถูก `format()` = TypeError = 500)
        """
        meta = _as_dict(d.get("document_meta"))
        amount = _as_float_or_none(d.get("amount")) or 0.0
        paid_total = _as_float_or_none(d.get("paid_total_after")) or 0.0
        line_items, line_items_hidden = cls._v2_line_items(d)
        doc_type = d.get("doc_type")

        context = {
            "doc_title": DOC_TYPE_LABELS.get(doc_type) or d.get("doc_type_label"),
            "doc_type": doc_type,
            # 🧾 v2 body แยกไฟล์สำหรับ REC/DEP เท่านั้น ⇒ คำว่า "ใบเสร็จ" ใช้ได้ทั้งคู่
            "is_receipt": True,
            "receipt_no": d.get("receipt_no"),
            "document_date_text": cls._thai_datetime_text(
                d.get("event_at") or d.get("issued_at")
            ),
            "is_voided": d.get("status") == DOC_STATUS_VOIDED,
            "void_reason": d.get("void_reason"),
            "room_name": d.get("room_name"),
            "room_code": d.get("room_code"),
            "student_no": d.get("student_no"),
            # 👤 snapshot ชนะชื่อที่ผูกกับแถวเสมอ (P2.1 เขียนทั้ง `payer_name`
            #    และชื่อแบบสั้น `payer` — รองรับทั้งสองรูปเพื่อกัน snapshot ต่างรุ่น)
            "payer_name": (
                meta.get("payer") or meta.get("payer_name") or d.get("issued_to_name")
            ),
            "issuer_name": (
                meta.get("receiver") or meta.get("receiver_name")
                or d.get("issued_by_name")
            ),
            "channel_text": _channel_text(meta.get("channel")),
            "note": d.get("note"),
            "amount": amount,
            # 🔴 คำนวณใหม่จาก `amount` — `amounts_in_words` ใน snapshot ใช้เป็นหลักฐาน
            #    ตรวจสอบ (test assert ว่าตรงกัน) ไม่ใช่แหล่งความจริงของกระดาษ
            "amount_text": baht_text(amount),
            "paid_total_after": paid_total,
            "paid_total_after_text": baht_text(paid_total),
            "line_items": line_items,
            "line_items_hidden": line_items_hidden,
            # 🔴 คีย์ชุด legacy — ต้องถูกตั้งเสมอ (บทเรียน Jinja `is not none`)
            "collection_title": None,
            "collection_due_date": None,
            "collection_amount": None,
            "remaining": None,
            "remaining_text": None,
            "is_merged": False,
            "doc_no_text": None,
            "doc_date_text": None,
            "merged_count": 0,
            "members": [],
            # ══ v2-only ═════════════════════════════════════════════════════
            "event_meta": meta,
            "credit_used": _as_float_or_none(meta.get("credit_used")) or 0.0,
            "credit_added": _as_float_or_none(meta.get("credit_added")) or 0.0,
            "amount_received": _as_float_or_none(meta.get("amount_received")),
            # DEP: ยอดเครดิตก่อน/หลังเติม (REC ไม่มีคีย์นี้ → None)
            "balance_before": _as_float_or_none(meta.get("balance_before")),
            "balance_after": _as_float_or_none(meta.get("balance_after")),
            "body_template": cls._body_template_for(d),
        }
        return context


# ─────────────────────────────────────────────────────────────────── ตัวช่วย
def _as_float_or_none(value) -> Optional[float]:
    """ตัวเลขจาก snapshot (float / str / Decimal) → float หรือ None

    ⚠️ ค่าที่ผิดรูปคืน None ไม่ raise: snapshot เก่าที่เขียนด้วยโค้ดคนละรุ่นต้องพิมพ์ได้
       (กระดาษจะพิมพ์ "—" แทนตัวเลขที่หาย ดีกว่าดาวน์โหลดไม่ได้ทั้งใบ)
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value) -> dict:
    """`document_meta` (jsonb → str) → dict — ผิดรูปคืน {}"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _channel_text(channel) -> Optional[str]:
    """snapshot ช่องทาง → ข้อความบรรทัดเดียว เช่น "เงินสด · ธนาคารกรุงไทย · xxx-x-x1234-5"

    🔒 พิมพ์เฉพาะเลขที่ปิดบังแล้ว — snapshot ห้ามเก็บเลขเต็มตั้งแต่ P2.1
    """
    if not isinstance(channel, dict):
        return None
    parts = [
        channel.get("name") or channel.get("channel_type"),
        channel.get("bank_name"),
        channel.get("account_no_masked"),
    ]
    text = " · ".join(str(p) for p in parts if p)
    return text or None
