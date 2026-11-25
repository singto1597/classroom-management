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
from datetime import date, datetime
from typing import Optional

from .baht_text import baht_text
from .constants import (
    DOC_STATUS_VOIDED, DOC_TYPE_CERTIFICATE, DOC_TYPE_DEPOSIT, DOC_TYPE_INCOME,
    DOC_TYPE_LABELS, DOC_TYPE_PAYMENT_VOUCHER, DOC_TYPE_RECEIPT,
)

logger = logging.getLogger(__name__)

# 🖨️ ทางแยกของ `body_template` — shell `receipt.html` ใช้ร่วมทุก layout
_V2_RECEIPT_BODY_TEMPLATE = "_receipt_body_v2.html"
# 💸 [P4.6] เอกสารจ่าย/รับรอง/รายรับอื่น — partial แยกไฟล์ตามชนิด (ไม่อัด `{% if %}`)
_VOUCHER_BODY_V2_TEMPLATE = "_voucher_body_v2.html"
_CERTIFICATE_BODY_V2_TEMPLATE = "_certificate_body_v2.html"
_INCOME_BODY_V2_TEMPLATE = "_income_body_v2.html"
_LEGACY_RECEIPT_BODY_TEMPLATE = "_receipt_body.html"

# ✂️ v2 ตั้งใจให้เห็นครบกว่า legacy (12) เพราะ 1 ใบ = 1 ครั้งรับเงินของบิลหลายใบ
#    ⚠️ ยอดรวมยังพิมพ์จาก `amount` เสมอ ไม่ใช่ผลบวกของบรรทัดที่แสดง
_V2_MAX_PRINTED_LINE_ITEMS = 20
# 💸 PV/CERT/INC เป็นใบที่ "หลายบรรทัดคือเรื่องปกติ" (ใบสำคัญจ่าย 1 ใบ = หลายรายการเบิก)
#    ⇒ เปิดให้เห็นได้ถึง 30 บรรทัดก่อนตัดสรุป (ยังพิมพ์ยอดรวมครบจาก `amount`)
_V2_MAX_SPEND_LINE_ITEMS = 30

# 💰 ป้าย "แหล่งเงิน" ของแต่ละบรรทัด (ตรงกับ `source` ที่ P2.1 เขียนลง snapshot)
_SOURCE_LABELS = {"cash": "เงินสด", "credit": "เครดิต", "mixed": "เงินสด + เครดิต"}

# 📎 สถานะหลักฐานต่อบรรทัดของ PV (ตรงกับ CHECK ของ `finance_expense_lines`)
_RECEIPT_STATUS_LABELS = {
    "attached": "มีหลักฐาน",
    "paper": "บิลกระดาษ",
    "none": "ไม่มีหลักฐาน",
}
# 💼 แหล่งเงินของบรรทัด PV (ตรงกับ CHECK ของ `funding_source`)
_FUNDING_SOURCE_LABELS = {"room_fund": "เงินกองกลาง", "pass_through": "เงินผ่านมือ"}

# 🚨 เตือนครั้งเดียวต่อ doc_type — ไม่ให้ log ท่วมตอนพิมพ์ชุดใหญ่
_warned_unsupported: set = set()


class DocumentsMixin:
    """ตัวประกอบ context ของเอกสาร v2 (ใช้ผ่าน MRO ของ `FinanceService`)"""

    # ─────────────────────────────────────────────────────────────── ทางแยกเทมเพลต
    @classmethod
    def _body_template_for(cls, d: dict) -> str:
        """เอกสารนี้ใช้ partial ไหนของ shell

        - REC/DEP (layout 2) → `_receipt_body_v2.html`
        - PV / CERT / INC (layout 2) → partial ของชนิดนั้น (P4.6)
        - layout 2 ชนิดอื่นที่ยังไม่มีเทมเพลต → ถอยไป partial เดิม + เตือนครั้งเดียว
          (พิมพ์ได้ ดีกว่า 500)
        """
        layout = int(d.get("layout_version") or 1)
        doc_type = d.get("doc_type")
        if layout >= 2:
            if doc_type in (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT):
                return _V2_RECEIPT_BODY_TEMPLATE
            if doc_type == DOC_TYPE_PAYMENT_VOUCHER:
                return _VOUCHER_BODY_V2_TEMPLATE
            if doc_type == DOC_TYPE_CERTIFICATE:
                return _CERTIFICATE_BODY_V2_TEMPLATE
            if doc_type == DOC_TYPE_INCOME:
                return _INCOME_BODY_V2_TEMPLATE
            if doc_type not in _warned_unsupported:
                _warned_unsupported.add(doc_type)
                logger.warning(
                    "[FIN-V2] ยังไม่มีเทมเพลต v2 สำหรับ doc_type=%s — ใช้ partial เดิมชั่วคราว",
                    doc_type,
                )
        return _LEGACY_RECEIPT_BODY_TEMPLATE

    # ─────────────────────────────────────────────────────────────── บรรทัดรายการ
    @classmethod
    def _v2_line_items(cls, d: dict) -> tuple:
        """`line_items` ของ snapshot → (บรรทัดที่พิมพ์, จำนวนที่ถูกตัด)

        - REC/DEP: `line_items` สูงสุด 20 (ของ P2.2 — ไม่เปลี่ยน)
        - CERT/INC: `line_items` สูงสุด 30 (P4.6)
        - PV: อ่าน `voucher_snapshot.lines` (รูปของ P4.1) สูงสุด 30

        🔴 แปลงทุกยอดเป็น `float` ที่นี่ — `Decimal` ที่หลุดถึง `"{:,.2f}".format()`
           จะพังตอนเรนเดอร์ และ jsonb ที่ asyncpg คืนมาเป็น **สตริง** ต้อง parse ก่อน
        """
        doc_type = d.get("doc_type")
        if doc_type == DOC_TYPE_PAYMENT_VOUCHER:
            return cls._voucher_lines(d)

        cap = (
            _V2_MAX_SPEND_LINE_ITEMS
            if doc_type in (DOC_TYPE_CERTIFICATE, DOC_TYPE_INCOME)
            else _V2_MAX_PRINTED_LINE_ITEMS
        )
        items = cls._parse_line_items(d.get("line_items")) or []
        printed, hidden = [], 0
        for it in items:
            title = it.get("title")
            applied = it.get("amount_applied")
            if not title and applied is None:
                continue
            if len(printed) >= cap:
                hidden += 1
                continue
            source = it.get("source")
            printed.append({
                "title": title or "รายการ",
                "bill_amount": _as_float_or_none(it.get("bill_amount")),
                "amount_applied": _as_float_or_none(applied) or 0.0,
                "bill_remaining": _as_float_or_none(it.get("bill_remaining")),
                "source_text": _SOURCE_LABELS.get(source),
            })

        if not printed:
            # 🧾 เอกสารที่ไม่มี `line_items` โดยเจตนา (เช่น DEP = เงินยังไม่ผูกบิล)
            #    ต้องได้ถ้อยคำของ **ชนิดนั้น** ไม่ใช่ "รับชำระหนี้" ที่สื่อว่ามีหนี้อยู่
            amount = _as_float_or_none(d.get("amount")) or 0.0
            if doc_type == DOC_TYPE_DEPOSIT:
                title = "รับเงินล่วงหน้า"
            elif doc_type == DOC_TYPE_CERTIFICATE:
                title = "รายการที่ไม่มีหลักฐาน"
            elif doc_type == DOC_TYPE_INCOME:
                title = "รายรับอื่น"
            else:
                title = "รับชำระหนี้"
            printed = [{
                "title": title,
                "bill_amount": None,
                "amount_applied": amount,
                "bill_remaining": None,
                "source_text": None,
            }]
        return printed, hidden

    # ─────────────────────────────────────────────────────────────── บรรทัด PV (P4.6)
    @classmethod
    def _voucher_lines(cls, d: dict) -> tuple:
        """`voucher_snapshot.lines` (P4.1) → (บรรทัดที่พิมพ์, จำนวนที่ถูกตัด) สูงสุด 30

        🔴 snapshot เป็น `str` จาก jsonb ได้ ⇒ parse ก่อน; ผิดรูปให้ `{}` ไม่ raise
           (กระดาษที่พิมพ์ซ้ำได้แค่หัวกับยอดรวม ยังดีกว่าดาวน์โหลดไม่ได้ทั้งใบ)
        """
        snapshot = _as_dict(d.get("voucher_snapshot"))
        raw_lines = snapshot.get("lines")
        if not isinstance(raw_lines, list):
            raw_lines = []

        printed, hidden = [], 0
        for idx, ln in enumerate(raw_lines):
            if not isinstance(ln, dict):
                continue
            title = ln.get("description") or ln.get("title")
            amount = _as_float_or_none(ln.get("amount"))
            if amount is None:
                amount = _as_float_or_none(ln.get("amount_applied"))
            if not title and amount is None:
                continue
            if len(printed) >= _V2_MAX_SPEND_LINE_ITEMS:
                hidden += 1
                continue
            status = ln.get("receipt_status")
            funding = ln.get("funding_source")
            printed.append({
                "line_no": ln.get("line_no") or (idx + 1),
                "title": title or "รายจ่ายของห้อง",
                "amount_applied": amount or 0.0,
                "category_name": ln.get("category_name"),
                "budget_label": ln.get("budget_label"),
                "wallet_name": ln.get("wallet_name"),
                "receipt_status": status,
                "receipt_status_text": _RECEIPT_STATUS_LABELS.get(status, status),
                "paper_bill_count": int(ln.get("paper_bill_count") or 0),
                "funding_source": funding,
                "funding_source_text": _FUNDING_SOURCE_LABELS.get(funding, funding),
                # 🔑 คีย์ชุดเดียวกับ REC — กัน partial ที่แชร์การ์ดใช้ `is not none`
                "bill_amount": None,
                "bill_remaining": None,
                "source_text": None,
            })

        if not printed:
            amount = _as_float_or_none(d.get("amount")) or 0.0
            printed = [{
                "line_no": 1,
                "title": (d.get("note") or "").strip() or "รายจ่ายของห้อง",
                "amount_applied": amount,
                "category_name": None,
                "budget_label": None,
                "wallet_name": None,
                "receipt_status": None,
                "receipt_status_text": None,
                "paper_bill_count": 0,
                "funding_source": None,
                "funding_source_text": None,
                "bill_amount": None,
                "bill_remaining": None,
                "source_text": None,
            }]
        return printed, hidden

    # ─────────────────────────────────────────────────────────────── context
    @classmethod
    def _document_context_v2(cls, d: dict) -> dict:
        """dict ของเอกสาร v2 → context ที่ partial ของ shell อ่าน

        🔴 ตั้งคีย์ให้ครบตามสัญญาของ `_document_context` เดิม (คีย์ที่ template
           ใช้ `{{ }}` ต้องมีเสมอ — `Undefined` ที่ถูก `format()` = TypeError = 500)
        🔴 ชนิด PV/CERT/INC ต่อท้ายด้วย helper ของตัวเอง (P4.6) — helper รับ base
           context แล้วทับเฉพาะคีย์ของตน ⇒ ชนิดที่ไม่รู้จักยังได้ base ครบชุด
        """
        meta = _as_dict(d.get("document_meta"))
        amount = _as_float_or_none(d.get("amount")) or 0.0
        paid_total = _as_float_or_none(d.get("paid_total_after")) or 0.0
        line_items, line_items_hidden = cls._v2_line_items(d)
        doc_type = d.get("doc_type")

        context = {
            "doc_title": DOC_TYPE_LABELS.get(doc_type) or d.get("doc_type_label"),
            "doc_type": doc_type,
            # 🧾 base = เอกสารรับเงิน (REC/DEP/INC) — PV/CERT ต้องทับเป็น False
            #    เองใน helper ของตน (บทเรียน `_voucher_body.html`: True = ถ้อยคำใบเสร็จหลุด)
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
        if doc_type == DOC_TYPE_PAYMENT_VOUCHER:
            return cls._voucher_context_v2(d, context)
        if doc_type == DOC_TYPE_CERTIFICATE:
            return cls._certificate_context_v2(d, context)
        if doc_type == DOC_TYPE_INCOME:
            return cls._income_context_v2(d, context)
        return context

    # ─────────────────────────────────────────────────────────────── PV (P4.6)
    @classmethod
    def _voucher_context_v2(cls, d: dict, context: dict) -> dict:
        """ใบสำคัญจ่าย (PV) — เอกสาร **สั่งจ่าย** ไม่ใช่หลักฐานรับเงิน

        🔴 `is_receipt=False`: partial ของ PV ไม่มีสาขา `is_receipt` เลย แต่ถ้าวันหนึ่ง
           มีคนเผลอใช้คีย์นี้ ค่าที่ถูกต้องคือ False (บทเรียน `_voucher_body.html`)
        🔴 คำอ่านเงินต้องมาจาก `d.amount` ไม่ใช่ `snapshot.total_amount` — snapshot
           เป็นหลักฐาน ไม่ใช่แหล่งความจริงที่พิมพ์
        """
        snapshot = _as_dict(d.get("voucher_snapshot"))
        meta = _as_dict(d.get("document_meta"))
        # ✍️ P4.1 เขียนลายเซ็นทั้งใน snapshot และ document_meta — ใช้ตัวแรกที่มี
        signatures = snapshot.get("signatures") or meta.get("signatures") or []
        signatures = [s for s in signatures if isinstance(s, dict)]
        lines = context["line_items"]
        amount = context["amount"]

        context.update({
            "doc_title": DOC_TYPE_LABELS.get(DOC_TYPE_PAYMENT_VOUCHER) or "ใบสำคัญจ่าย",
            "is_receipt": False,
            "voucher_payee_name": (
                snapshot.get("payee_name") or d.get("issued_to_name")
            ),
            "voucher_payee_person_id": (
                snapshot.get("payee_person_id") or d.get("receiver_person_id")
            ),
            # 🗓️ snapshot เก็บ `voucher_date` เป็น ISO string (DATE) — parse ก่อนจัดรูป
            "voucher_date_text": (
                cls._thai_date_text(_as_date_or_none(snapshot.get("voucher_date")))
                or context.get("document_date_text")
            ),
            "voucher_prepared_name": _signer_name(signatures, "prepared"),
            "voucher_approved_name": _signer_name(signatures, "approved"),
            "voucher_approver_name": _signer_name(signatures, "approved"),
            "voucher_receiver_name": _signer_name(signatures, "receiver"),
            "voucher_signatures": signatures,
            "voucher_account_name": _voucher_wallet_name(snapshot),
            # 🏦 PV ไม่มีช่องทางชำระแยกจากกระเป๋า — คิงก์ไว้ให้ partial อื่นอ่านได้
            "voucher_channel_text": None,
            "voucher_attachment_count": sum(
                1 for it in lines if it.get("receipt_status") == "attached"
            ),
            "voucher_total_paper_bill_count": (
                int(snapshot.get("total_paper_bill_count") or 0)
                or sum(int(it.get("paper_bill_count") or 0) for it in lines)
            ),
            "voucher_lines": lines,
            "voucher_budgets": [],
            "voucher_category_name": None,
            # 🧾 อ้าง CERT (ถ้า document_meta มีคีย์นี้ — ปกติ PV ออกก่อน CERT จึงว่าง)
            "cert_receipt_no": meta.get("cert_receipt_no"),
            "cert_amount": _as_float_or_none(meta.get("cert_amount")),
            # 🔴 PV/ไม่มี "ยอดสะสม" — ใส่ 0 เพื่อไม่ให้มีใคร SUM แล้วนับซ้ำ
            "paid_total_after": 0.0,
            "paid_total_after_text": baht_text(0),
            "line_items": lines,
            "collection_amount": None,
            "remaining": None,
            "remaining_text": None,
        })
        # 🧮 กันอาการ "no-op ที่ดูเหมือนทำงาน": context ต้องสะท้อนยอดบนกระดาษจริง
        context["amount"] = amount
        context["amount_text"] = baht_text(amount)
        return context

    # ─────────────────────────────────────────────────────────────── CERT (P4.6)
    @classmethod
    def _certificate_context_v2(cls, d: dict, context: dict) -> dict:
        """ใบรับรองแทนใบเสร็จ — รับรอง **เฉพาะบรรทัดที่ไม่มีหลักฐาน** (`receipt_status='none'`)

        🔴 `is_receipt=False`: CERT เป็นเอกสารรับรองการจ่าย ไม่ใช่หลักฐานรับเงิน
        🔴 ไฟล์ partial ห้ามมีถ้อยคำ "ใบเสร็จรับเงิน" (ชื่อเอกสารเต็ม) — ใช้
           "ใบรับรองแทนใบเสร็จ" เท่านั้น (เทสต์ grep ไฟล์)
        """
        meta = _as_dict(d.get("document_meta"))
        amount = context["amount"]
        items = context["line_items"]
        source_nos = meta.get("source_line_nos") or []
        if not isinstance(source_nos, list):
            source_nos = []

        cert_lines = []
        for idx, it in enumerate(items):
            line_no = source_nos[idx] if idx < len(source_nos) else idx + 1
            cert_lines.append({
                "line_no": line_no,
                "title": it.get("title") or "รายจ่ายของห้อง",
                "amount": it.get("amount_applied") or 0.0,
            })

        signatures = meta.get("signatures") or []
        signatures = [s for s in signatures if isinstance(s, dict)]

        context.update({
            "doc_title": DOC_TYPE_LABELS.get(DOC_TYPE_CERTIFICATE) or "ใบรับรองแทนใบเสร็จ",
            "is_receipt": False,
            "cert_lines": cert_lines,
            "cert_amount": amount,
            "cert_amount_text": baht_text(amount),
            "cert_source_line_nos": source_nos,
            "cert_prepared_name": _signer_name(signatures, "prepared"),
            "cert_approved_name": _signer_name(signatures, "approved"),
            "cert_signatures": signatures,
            # 🔗 อ้าง PV ต้นทาง (P4.2 เก็บ `voucher_no` ไว้ใน document_meta)
            "pv_receipt_no": meta.get("voucher_no"),
            "voucher_payee_name": d.get("issued_to_name"),
            "paid_total_after": 0.0,
            "paid_total_after_text": baht_text(0),
            "voucher_lines": [],
            "voucher_signatures": [],
            "voucher_budgets": [],
            "voucher_attachment_count": 0,
            "voucher_total_paper_bill_count": 0,
            "collection_amount": None,
            "remaining": None,
            "remaining_text": None,
        })
        context["amount"] = amount
        context["amount_text"] = baht_text(amount)
        return context

    # ─────────────────────────────────────────────────────────────── INC (P4.6)
    @classmethod
    def _income_context_v2(cls, d: dict, context: dict) -> dict:
        """ใบรับเงิน (INC) — รายรับอื่น ผู้จ่ายเป็นข้อความอิสระ ไม่ผูกบิลนักเรียน"""
        meta = _as_dict(d.get("document_meta"))
        snapshot = _as_dict(d.get("voucher_snapshot"))
        amount = context["amount"]
        lines = context["line_items"]

        signatures = meta.get("signatures") or snapshot.get("signatures") or []
        signatures = [s for s in signatures if isinstance(s, dict)]
        wallet = snapshot.get("wallet")
        wallet_name = wallet.get("name") if isinstance(wallet, dict) else None

        context.update({
            "doc_title": DOC_TYPE_LABELS.get(DOC_TYPE_INCOME) or "ใบรับเงิน",
            # 🧾 INC เป็นหลักฐานรับเงินจริง ⇒ True (ต่างจาก PV/CERT)
            "is_receipt": True,
            "payer_name": d.get("issued_to_name"),
            # 🖊️ "ผู้ออก" = คนที่บันทึก (ไม่ใช่ผู้รับเงิน) ⇒ อ่านจากคอลัมน์ตรง ๆ
            "issuer_name": d.get("issued_by_name"),
            "income_lines": lines,
            "income_receiver_name": (
                meta.get("receiver_name") or d.get("issued_by_name")
            ),
            "income_wallet_name": wallet_name,
            "income_channel_text": _income_channel_text(
                meta.get("channel") or snapshot.get("channel")
            ),
            "income_prepared_name": _signer_name(signatures, "prepared"),
            "income_receiver_signer_name": _signer_name(signatures, "receiver"),
            "income_signatures": signatures,
            # 💰 INC คือยอดรับจริง ⇒ `paid_total_after` สะท้อนยอดนี้ได้ (ไม่ซ้ำกับใคร)
            "paid_total_after": amount,
            "paid_total_after_text": baht_text(amount),
            "voucher_lines": [],
            "voucher_signatures": [],
            "voucher_budgets": [],
            "voucher_attachment_count": 0,
            "voucher_total_paper_bill_count": 0,
            "collection_amount": None,
            "remaining": None,
            "remaining_text": None,
        })
        context["amount"] = amount
        context["amount_text"] = baht_text(amount)
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


def _income_channel_text(channel) -> Optional[str]:
    """snapshot ช่องทางของ INC → ข้อความบรรทัดเดียว

    🔑 รูปคีย์ของ INC (P4.4) ต่างจาก INV (P2.6): ใช้ `label` +
       `account_number_masked`/`promptpay_id_masked` ⇒ ประกอบแยก ไม่ยืม `_channel_text`
       (ถ้ายืมจะได้แค่คำว่า "cash"/"bank_transfer" โดยไม่มีชื่อช่องทาง)
    """
    if not isinstance(channel, dict):
        return None
    parts = [
        channel.get("label") or channel.get("channel_type") or channel.get("name"),
        channel.get("bank_name"),
        channel.get("account_number_masked") or channel.get("promptpay_id_masked"),
        channel.get("account_name"),
    ]
    text = " · ".join(str(p) for p in parts if p)
    return text or None


def _signer_name(signatures, role: str) -> Optional[str]:
    """หา `signer_name` ของ role ที่ระบุจาก list ลายเซ็นของ snapshot

    🔴 ช่องที่ไม่มีชื่อต้องคืน None (partial จะเว้นว่างให้เซ็นมือ) — ห้ามคืน "-"
       เพราะขีดกลางในช่องลายมือชื่ออ่านว่า "ไม่มีผู้อนุมัติ" ซึ่งระบบไม่ได้ประกาศ
    """
    for sig in signatures or []:
        if isinstance(sig, dict) and sig.get("role") == role:
            name = sig.get("signer_name")
            return str(name) if name else None
    return None


def _voucher_wallet_name(snapshot: dict) -> Optional[str]:
    """`voucher_snapshot.default_wallet` → ชื่อกระเป๋า (ทนรูปเก่า/ผิดรูป)"""
    wallet = snapshot.get("default_wallet") if isinstance(snapshot, dict) else None
    if not isinstance(wallet, dict):
        return None
    name = wallet.get("name")
    return str(name) if name else None


def _as_date_or_none(value) -> Optional[date]:
    """ค่า DATE จาก snapshot (`date` / ISO string) → `date` หรือ None

    ⚠️ `voucher_date` ผ่าน jsonb มาเป็น **สตริง ISO** ⇒ `_thai_date_text` ซึ่งอ่าน
       `.day/.month/.year` จะระเบิดถ้าได้สตริง ⇒ แปลงที่นี่ก่อนแล้วค่อยส่งต่อ
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None
