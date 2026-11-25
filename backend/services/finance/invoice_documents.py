"""🧾 [FIN-V2 / P2.6] ใบแจ้งหนี้ v2 (snapshot ช่องทาง + QR) และใบรับทราบยอดค้าง (ACK)

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีไฟล์นี้
═══════════════════════════════════════════════════════════════════════════════
P2.2 ทำให้ **REC/DEP** เป็นเอกสาร `layout_version=2` ที่พิมพ์จาก snapshot
P2.4 ทำให้ช่องทางชำระเงินเป็นแถวจริง + สร้าง PromptPay QR ได้จากฝั่ง server

P2.6 ต่อสองอย่างนี้เข้าด้วยกัน:
1. **INV** (`invoice`) — ใบแจ้งหนี้ที่ `_issue_invoice_aggregate` เดิมออกเป็น layout 1
   ถูกยกระดับเป็น v2 โดย **override ผ่าน MRO** (ไม่คัดลอกตรรกะยอด/เลข/snapshot มาใหม่)
   แล้วเพิ่ม `document_meta.channels` (≤3, mask แล้ว) + `qr_payload` ของช่องทางหลัก
2. **ACK** (`acknowledgement`) — ใบรับทราบยอดค้าง 1 ใบต่อรอบ/ห้อง + `finance_ack_entries`
   1 แถว/นักเรียน · **ไม่แตะเงินเลย** (ไม่มี journal/กระเป๋า/เครดิต/บิล)

🔴 สัญญาของเอกสาร: ทุกอย่างที่พิมพ์มาจาก snapshot ใน `document_meta`/`line_items`
   ⇒ แก้ชื่อบิล/ปิดช่องทาง/เปลี่ยนเลขพร้อมเพย์ภายหลัง **ไม่เปลี่ยนกระดาษที่แจกไปแล้ว**

🔒 PromptPay: ตาราง `finance_payment_channels.promptpay_id_masked` เก็บ **canonical เต็ม**
   (ข้อจำกัด schema 0012) ⇒ snapshot ต้อง mask ด้วย `mask_promptpay_id` ทุกครั้ง
   และ `qr_payload` (ที่มีเลขเต็มอยู่ข้างใน) ห้ามออกจาก server — ฝั่งพิมพ์ได้แค่ data URI

⚠️ กติกา MRO: `InvoiceDocumentsMixin` ต้องอยู่ **ก่อน** `DocumentsMixin` และ
   `ReceiptsMixin` ใน `FinanceService` (mixin ที่อยู่บนชนะ) — ไม่งั้น INV จะกลับไป
   เป็น layout 1 เงียบ ๆ และ `_document_context` จะไม่ถูก dispatch มาที่นี่

⚠️ ขอบเขต: P2.6 ออก INV/ACK ได้เท่านั้น — GET/list/void ACK/RPT เป็นของ P5.4
   (P5.4 ต่อ tail เข้า router/service ไฟล์นี้ ไม่สร้างไฟล์ใหม่ทับ)

❌ ห้าม publish Discord ตอนออก ACK: ไม่มีเงินเข้า และการแจ้งเตือนซ้ำเป็นบั๊ก
   ที่ระบบนี้เคยแก้ไปแล้ว (เหตุผลเดียวกับหัวไฟล์ `receipts.py`)
"""
import base64
import json
import logging
import time
from datetime import date
from decimal import Decimal
from typing import List, Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_permission

from .acknowledgements import assert_ack_replay_matches
from .base import _lock_room_money, service_logger
from .constants import (
    BATCH_SOURCE_AUTO, BUDDHIST_ERA_OFFSET, DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_INVOICE, DOC_TYPE_PREFIXES, RECEIPT_NO_TEMPLATE, RECEIPT_SEQ_MAX,
    RECEIPT_SEQ_OVERFLOW_MSG, THAI_TZ,
)
from .documents import _as_dict, _as_float_or_none
from .qr import QrError, build_promptpay_payload, mask_account_number, mask_promptpay_id, render_qr_svg

logger = logging.getLogger(__name__)

# 🖨️ partial ของ shell `receipt.html` — ต้องเป็นชื่อไฟล์ที่อยู่ใน `templates/finance/`
_INVOICE_BODY_TEMPLATE = "_invoice_body_v2.html"
_ACK_BODY_TEMPLATE = "_acknowledgement_body_v2.html"

# 🔢 ช่องทางบน INV: กติกาเดียวกับ settings (P2.4) — ถ้าเลือกมากกว่านี้ต้องบอกผู้ใช้
_MAX_INVOICE_CHANNELS = 3

# 📋 จำนวนบรรทัดสูงสุดบน INV — ตรงกับ `_V2_MAX_PRINTED_LINE_ITEMS` ของ P2.2
#    (ยอดรวมยังพิมพ์ `amount` ที่พาดหัวเสมอ ⇒ การตัดบรรทัดไม่ทำให้ยอดผิด)
_MAX_PRINTED_LINE_ITEMS = 20

# 🗂️ คอลัมน์ของ INV/ACK ที่ต้องคืนให้ `_shape_receipt` — ครบชุดเดียวกับที่เอกสาร v2 ใช้
#    (ขาด `layout_version`/`document_meta` = `_shape_receipt` เห็นเป็น layout 1)
_DOC_COLUMNS = """
    id, room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
    legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
    issued_to_name, issued_by_name, note, event_at, status, voided_at, voided_by,
    void_reason, issued_at, line_items, layout_version, document_meta,
    payment_event_id, receiver_person_id, batch_id
"""

# 📡 ช่องทางที่ใช้ได้ของห้อง — `ORDER BY is_primary DESC` ทำให้ primary ขึ้นก่อนเสมอ
_CHANNEL_QUERY = """
    SELECT c.id, c.channel_type, c.label, c.account_name, c.bank_name,
           c.account_number_masked, c.promptpay_id_masked, c.qr_mode,
           c.is_primary, c.sort_order
    FROM finance_payment_channels c
    WHERE c.room_id = $1 AND c.is_active AND c.deleted_at IS NULL
    ORDER BY c.is_primary DESC, c.sort_order ASC, c.id ASC
"""


def _mask_stored_promptpay(value: Optional[str]) -> Optional[str]:
    """canonical เต็ม (ที่เก็บใน `promptpay_id_masked`) → รูปที่พิมพ์ได้

    ⚠️ ค่าที่เสียหายไม่ทำให้ออกเอกสารไม่ได้ — ถอยไปใช้ mask ทั่วไป (เหมือน P2.4)
    """
    if not value:
        return None
    try:
        return mask_promptpay_id(value)
    except QrError:
        return mask_account_number(value)


def _iso_date(value) -> Optional[date]:
    """ISO `YYYY-MM-DD` (จาก snapshot) → `date` หรือ None — ค่าผิดรูปต้องไม่ทำให้พิมพ์ไม่ได้"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class InvoiceDocumentsMixin:
    """INV v2 + ACK (ใช้ผ่าน MRO ของ `FinanceService`)"""

    # ──────────────────────────────────────────────────────────── ทางแยกเทมเพลต
    @classmethod
    def _body_template_for(cls, d: dict) -> str:
        """INV/ACK มี partial ของตัวเอง — ชนิดอื่นยังใช้ตรรกะของ `DocumentsMixin`"""
        doc_type = d.get("doc_type")
        if doc_type == DOC_TYPE_INVOICE:
            return _INVOICE_BODY_TEMPLATE
        if doc_type == DOC_TYPE_ACKNOWLEDGEMENT:
            return _ACK_BODY_TEMPLATE
        return super()._body_template_for(d)

    # ──────────────────────────────────────────────────────────── snapshot ช่องทาง
    @staticmethod
    def _channel_snapshot_row(row) -> dict:
        """แถวช่องทาง → dict ที่ลง `document_meta` ได้ (mask เท่านั้น)"""
        return {
            "channel_id": row["id"],
            "channel_type": row["channel_type"],
            "label": row["label"],
            "account_name": row["account_name"],
            "bank_name": row["bank_name"],
            # 🔒 คอลัมน์เลขบัญชีถูก mask ตั้งแต่ตอนสร้าง (P2.4) ⇒ ใช้ค่าที่มีอยู่ตรง ๆ
            "account_number_masked": row["account_number_masked"] or None,
            # 🔴 คอลัมน์นี้เก็บ **canonical เต็ม** ⇒ ต้อง mask ทุกครั้ง (ห้ามส่งค่าดิบ)
            "promptpay_id_masked": _mask_stored_promptpay(row["promptpay_id_masked"]),
            "qr_mode": row["qr_mode"],
            "is_primary": bool(row["is_primary"]),
        }

    @classmethod
    async def _invoice_channel_snapshot(
        cls, conn: asyncpg.Connection, room_id: int, channel_ids: Optional[List[int]],
    ) -> list:
        """ช่องทางที่พิมพ์บน INV — ≤3, primary อยู่ลำดับแรก, mask แล้ว

        Raises:
            ValueError: เลือกเกิน 3 / id ที่ไม่พบหรือปิดใช้งานหรืออยู่ต่างห้อง

        🔴 ต้องเรียก **ก่อน** จองเลขเอกสาร: คำขอที่ผิดต้องไม่เผาเลข INV ทิ้ง
        """
        rows = await conn.fetch(_CHANNEL_QUERY, room_id)

        if channel_ids:
            ids = list(dict.fromkeys(channel_ids))
            if len(ids) > _MAX_INVOICE_CHANNELS:
                raise ValueError(f"เลือกได้ไม่เกิน {_MAX_INVOICE_CHANNELS} ช่องทาง")
            by_id = {r["id"]: r for r in rows}
            selected = []
            for cid in ids:
                row = by_id.get(cid)
                if row is None:
                    raise ValueError(
                        "ไม่พบช่องทางชำระเงินที่เลือก (อาจถูกปิดใช้งานหรืออยู่ต่างห้อง)"
                    )
                selected.append(row)
            # 🔴 primary ต้องอยู่บน INV เสมอ — ถ้าผู้ใช้ไม่ได้เลือก ให้แทรกเป็นตัวแรก
            #    แล้วตัดตัวท้ายออกเพื่อคงเพดาน 3 ช่องทาง
            if not any(r["is_primary"] for r in selected):
                room_primary = next((r for r in rows if r["is_primary"]), None)
                if room_primary is not None:
                    selected = [room_primary] + selected
                    del selected[_MAX_INVOICE_CHANNELS:]
        else:
            # ไม่ระบุ = 3 ช่องทางแรกตามลำดับของ settings (primary มาก่อนจาก ORDER BY)
            selected = rows[:_MAX_INVOICE_CHANNELS]

        return [cls._channel_snapshot_row(r) for r in selected]

    # ──────────────────────────────────────────────────────────── INV override
    @classmethod
    async def _issue_invoice_aggregate(
        cls, conn: asyncpg.Connection, target_room_id: int, student_id: int,
        user_id: int, user_name: str, note: Optional[str], issued_at_db,
        channel_ids: Optional[List[int]] = None,
    ):
        """`ReceiptsMixin._issue_invoice_aggregate` + `document_meta` (ช่องทาง/QR)

        🔴 ใช้ `super()` แทนการคัดลอกตรรกะ: ยอดค้าง/`line_items`/sequence/INSERT
           ยังมีแหล่งความจริงเดียวที่ `receipts.py` (ถ้าคัดลอก จะมีสองที่ที่ต้องแก้พร้อมกัน)

        ⚠️ `super()` ใน classmethod ไล่ตาม `cls.__mro__` ⇒ ต้องมี `ReceiptsMixin`
           อยู่ถัดจาก mixin นี้ (ดูคอมเมนต์หัวไฟล์)
        """
        # 🔒 ยึดล็อกห้องก่อนอ่านช่องทาง — ชุด snapshot ต้องเห็นสถานะช่องทางเดียวกับ
        #    ที่ยอดค้างถูกอ่าน (P2.4 เขียนช่องทางใต้ล็อกตัวเดียวกัน)
        await _lock_room_money(conn, target_room_id)

        # 🚧 validate ช่องทาง **ก่อน** ที่ super() จะจองเลข — คำขอผิดห้ามเผาเลข INV
        channels = await cls._invoice_channel_snapshot(conn, target_room_id, channel_ids)

        row = await super()._issue_invoice_aggregate(
            conn, target_room_id, student_id, user_id, user_name, note, issued_at_db,
        )

        primary = channels[0] if channels else None
        primary_channel_id = primary["channel_id"] if primary else None

        # 🔐 QR สร้างจากเลข **เต็ม** ที่อยู่ใน DB เท่านั้น (ไม่เคยออกจาก server)
        qr_payload = None
        if primary and primary["channel_type"] == "promptpay" and primary["qr_mode"]:
            raw = await cls._load_channel(conn, target_room_id, primary_channel_id)
            if raw is not None and raw["promptpay_id_masked"]:
                amount = (
                    Decimal(str(row["amount"])) if raw["qr_mode"] == "fixed" else None
                )
                try:
                    qr_payload = build_promptpay_payload(
                        promptpay_id=raw["promptpay_id_masked"],
                        qr_mode=raw["qr_mode"],
                        amount=amount,
                    )
                except QrError as exc:
                    # เอกสารต้องพิมพ์ได้แม้ข้อมูลช่องทางเสีย — QR หายแต่ช่องทางยังแสดง
                    logger.warning(
                        "[FIN-V2] สร้าง QR ของ INV %s ไม่ได้: %s", row["receipt_no"], exc,
                    )

        items = cls._parse_line_items(row["line_items"]) or []
        dues = [it.get("due_date") for it in items if it.get("due_date")]
        due_date = min(dues) if dues else None

        document_meta = {
            "channels": channels,
            "primary_channel_id": primary_channel_id,
            "qr_payload": qr_payload,
            "due_date": due_date,
            "note": note,
        }

        updated = await conn.fetchrow(
            f"""UPDATE finance_receipts
                   SET layout_version = 2, document_meta = $2::jsonb
                 WHERE id = $1
              RETURNING {_DOC_COLUMNS}""",
            row["id"], json.dumps(document_meta, ensure_ascii=False),
        )
        return updated


    # ──────────────────────────────────────────────────────────── context เอกสาร
    @classmethod
    def _document_context_invoice_v2(cls, d: dict) -> dict:
        """INV/ACK → context ของ `_invoice_body_v2.html` / `_acknowledgement_body_v2.html`

        เริ่มจาก context ของ P2.2 (คีย์ legacy ครบ) แล้ว override เฉพาะส่วนที่ต่าง:
        `line_items` ของ INV มีรูป `{title, amount, due_date}` (ไม่ใช่ของ REC),
        ช่องทาง/QR/รายชื่อ ACK อยู่ใน `document_meta`
        """
        ctx = super()._document_context_v2(d)
        meta = _as_dict(d.get("document_meta"))
        doc_type = d.get("doc_type")

        # 📋 บรรทัดของ INV — snapshot ล้วน (ห้าม JOIN บิลสด: เอกสารที่แจกแล้วต้องพิมพ์ซ้ำได้เดิม)
        raw_items = cls._parse_line_items(d.get("line_items")) or []
        line_items, hidden = [], 0
        for it in raw_items:
            if len(line_items) >= _MAX_PRINTED_LINE_ITEMS:
                hidden += 1
                continue
            due = _iso_date(it.get("due_date"))
            line_items.append({
                "title": it.get("title") or "รายการ",
                "amount": _as_float_or_none(it.get("amount")) or 0.0,
                "due_date_text": cls._thai_date_text(due),
            })

        # 📅 วันครบกำหนดที่เร็วที่สุด — เก็บเป็น ISO ใน snapshot ตั้งแต่ตอนออกเอกสาร
        due_date = _iso_date(meta.get("due_date"))
        if due_date is None:
            dates = [c for c in (_iso_date(it.get("due_date")) for it in raw_items) if c]
            due_date = min(dates) if dates else None

        # 💳 ช่องทาง + QR (เฉพาะ INV — ACK ไม่มีช่องทาง/QR ตาม doc-matrix)
        channels = [c for c in (meta.get("channels") or []) if isinstance(c, dict)]
        channels = channels[:_MAX_INVOICE_CHANNELS]
        qr_data_uri = None
        payload = meta.get("qr_payload")
        if doc_type == DOC_TYPE_INVOICE and payload:
            try:
                svg = render_qr_svg(payload)
                qr_data_uri = (
                    "data:image/svg+xml;base64,"
                    + base64.b64encode(svg.encode("utf-8")).decode("ascii")
                )
            except Exception as exc:  # noqa: BLE001 — snapshot เสียต้องไม่ทำให้พิมพ์ไม่ได้
                logger.warning("[FIN-V2] เรนเดอร์ QR ของ %s ไม่ได้: %s", d.get("receipt_no"), exc)

        # 📝 รายชื่อ ACK (1 แถว/นักเรียน) — มาจาก snapshot เท่านั้น
        entries = []
        for e in (meta.get("entries") or []):
            if not isinstance(e, dict):
                continue
            entries.append({
                "student_id": e.get("student_id"),
                "student_no": e.get("student_no"),
                "student_name": e.get("student_name"),
                "outstanding_amount": _as_float_or_none(e.get("outstanding_amount")) or 0.0,
                "invoice_receipt_no": e.get("invoice_receipt_no"),
            })

        ctx.update({
            # 🔴 INV/ACK ไม่ใช่หลักฐานการรับเงิน — template ใช้ค่านี้ตัดถ้อยคำ "ใบเสร็จ"
            "is_receipt": False,
            "body_template": cls._body_template_for(d),
            "line_items": line_items,
            "line_items_hidden": hidden,
            # 📋 ชื่อสรุปของใบ ("ยอดค้างชำระรวม N โครงการ") มาจาก `_shape_receipt_detail`
            #    — P2.2 ตั้งคีย์นี้เป็น None เสมอ ⇒ ต้องหยิบจากแถวมาก่อน ใช่แล้วพิมพ์บนใบ
            #    (ยอด/N คำนวณจาก snapshot ณ ตอนออก ไม่ใช่ JOIN บิลสด)
            "collection_title": d.get("collection_title"),
            "due_date_text": cls._thai_date_text(due_date),
            "channels": channels,
            "primary_channel": channels[0] if channels else None,
            "primary_channel_id": meta.get("primary_channel_id"),
            "qr_data_uri": qr_data_uri,
            "ack_entries": entries,
            "entry_count": int(meta.get("entry_count") or len(entries)),
        })
        return ctx

    # ──────────────────────────────────────────────────────────── ACK
    @classmethod
    async def _load_ack_entries(cls, conn: asyncpg.Connection, ack_receipt_id: int) -> list:
        """`finance_ack_entries` + ชื่อ/เลขนักเรียน + เลข INV ที่ผูกอยู่ → ใช้ทั้งตอนออกและ replay"""
        rows = await conn.fetch(
            """SELECT E.student_id, E.outstanding_amount, E.invoice_receipt_id,
                      S.student_no, U.first_name, U.nickname, U.first_name_en,
                      I.receipt_no AS invoice_receipt_no
                 FROM finance_ack_entries E
                 JOIN students S ON S.id = E.student_id
                 LEFT JOIN v_student_profiles U ON U.student_id = S.id
                 LEFT JOIN finance_receipts I ON I.id = E.invoice_receipt_id
                WHERE E.ack_receipt_id = $1
                ORDER BY E.id""",
            ack_receipt_id,
        )
        return [
            {
                "student_id": r["student_id"],
                "student_no": r["student_no"],
                "student_name": cls._display_name(r),
                "outstanding_amount": float(r["outstanding_amount"]),
                "invoice_receipt_id": r["invoice_receipt_id"],
                "invoice_receipt_no": r["invoice_receipt_no"],
            }
            for r in rows
        ]

    @classmethod
    async def _ack_response(cls, conn: asyncpg.Connection, row, *, reused: bool) -> dict:
        entries = await cls._load_ack_entries(conn, row["id"])
        invoices = [e["invoice_receipt_no"] for e in entries if e["invoice_receipt_no"]]
        receipt = cls._shape_receipt(row)
        total = receipt["amount"]
        verb = "ใบรับทราบยอดค้างเดิม" if reused else "ออกใบรับทราบยอดค้าง"
        return {
            "status": "success",
            "message": f"{verb} {receipt['receipt_no']} — {len(entries)} คน · {total:,.2f} บาท",
            "receipt": receipt,
            "entries": entries,
            "invoice_receipt_nos": invoices,
            "reused": reused,
        }

    @classmethod
    async def issue_acknowledgements(
        cls, pool: asyncpg.Pool, *, req, user_id: int, client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """ออก **ใบรับทราบยอดค้าง 1 ใบต่อรอบ** (ทั้งห้อง หรือกลุ่มที่เลือก) — ไม่แตะเงิน

        🔴 ไม่เขียน `finance_transactions`/`journal_*`/`finance_accounts`/`student_credits`/
           `student_payments` แม้แต่แถวเดียว: ACK เป็นเอกสาร "รับทราบหนี้" ไม่ใช่การชำระ
           ⇒ ยอดกระเป๋า/บัญชี/credited ก่อน-หลังต้องเท่าเดิม (มีเทสต์บังคับ)

        🔁 Idempotent ด้วย `idempotency_key`: retry จาก SPA ต้องได้ใบเดิม
           (`reused=True`) ไม่ใช่ ACK ใหม่ที่กินเลขและมีรายชื่อซ้ำ
           ⚠️ partial unique index `idx_finance_receipts_idem` ⇒ ทางที่เลือกคือ
              `SELECT ... FOR UPDATE` ใต้ `_lock_room_money` แล้วคืนใบเดิม
              (ไม่ต้อง savepoint / ไม่ต้องกลืน `UniqueViolationError`)

        📚 ถ้า `include_invoice` — INV ของทุกคนถูกออกใน transaction เดียวกับ ACK
           ⇒ ถ้าใบใดล้ม ทั้งชุด rollback (ACK ที่อ้าง INV ที่ไม่มีอยู่ = เอกสารขัดแย้ง)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ การออกเอกสารการเงิน = การเขียน ต้องมี MANAGE_FINANCE
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องเป็นคำสั่งแรกหลัง RBAC — serialize ทั้งชุด + idempotency read
                    await _lock_room_money(conn, target_room_id)

                    existing = await conn.fetchrow(
                        f"""SELECT {_DOC_COLUMNS} FROM finance_receipts
                             WHERE room_id = $1 AND doc_type = $2
                               AND idempotency_key = $3 AND deleted_at IS NULL
                             FOR UPDATE""",
                        target_room_id, DOC_TYPE_ACKNOWLEDGEMENT, req.idempotency_key,
                    )
                    if existing is not None:
                        # 🧾 [P5.4] คีย์เดิม + payload ต่าง = 409 ไม่ใช่คืนใบเดิมเงียบ ๆ
                        #    (ลูกค้าจะเข้าใจว่าได้ใบใหม่ที่ครอบรายชื่อชุดใหม่ ทั้งที่กระดาษ
                        #    ที่พิมพ์ออกมาเป็นชุดเก่า)
                        assert_ack_replay_matches(existing, req)
                        return await cls._ack_response(conn, existing, reused=True)

                    # 🕐 เวลาเดียวทั้งชุด — ปี พ.ศ. บนเลข ACK และ `event_at` มาจากค่าเดียวกัน
                    issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
                    user_name = req.user_name or "—"

                    entries = await cls._collect_ack_entries(
                        conn, target_room_id, req.scope, req.student_ids,
                    )
                    if not entries:
                        raise ValueError("ไม่มีนักเรียนที่มียอดค้าง — ออกใบรับทราบไม่ได้")

                    total = round(sum(e["outstanding_amount"] for e in entries), 2)
                    if total <= 0:
                        raise ValueError("ไม่มีนักเรียนที่มียอดค้าง — ออกใบรับทราบไม่ได้")

                    # 🧾 INV ใหม่ (เฉพาะเมื่อขอ) — ก่อน ACK เพื่อให้ entry ผูกเลข INV ได้ทันที
                    issued_invoices = []
                    if req.include_invoice:
                        for e in entries:
                            inv = await cls._issue_invoice_aggregate(
                                conn, target_room_id, e["student_id"], user_id,
                                user_name, req.note, issued_at_db,
                                channel_ids=req.channel_ids,
                            )
                            shaped = cls._shape_receipt(inv)
                            issued_invoices.append(shaped)
                            e["invoice_receipt_id"] = shaped["id"]
                            e["invoice_receipt_no"] = shaped["receipt_no"]
                        if len(issued_invoices) >= 2:
                            await cls._attach_issuance_batch(
                                conn, room_id=target_room_id, issued=issued_invoices,
                                new_ids=[r["id"] for r in issued_invoices],
                                source=BATCH_SOURCE_AUTO, user_id=user_id,
                                user_name=user_name,
                            )

                    # 🗓️ ปี พ.ศ. จาก **เวลาของเหตุการณ์** (issued_at_db) ไม่ใช่ paid_at
                    year_be = issued_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET
                    seq = await conn.fetchval(
                        """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
                           VALUES ($1, $2, $3, 1)
                           ON CONFLICT (room_id, year_be, doc_type)
                           DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                                         updated_at = CURRENT_TIMESTAMP
                           RETURNING last_seq""",
                        target_room_id, year_be, DOC_TYPE_ACKNOWLEDGEMENT,
                    )
                    if seq > RECEIPT_SEQ_MAX:
                        raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
                    receipt_no = RECEIPT_NO_TEMPLATE.format(
                        prefix=DOC_TYPE_PREFIXES[DOC_TYPE_ACKNOWLEDGEMENT],
                        year_be=year_be, seq=seq,
                    )

                    document_meta = {
                        "scope": req.scope,
                        # 🧾 [P5.4] เก็บไว้เทียบตอน replay (คีย์เดิมต้องได้ payload เดิม)
                        "include_invoice": bool(req.include_invoice),
                        "entry_count": len(entries),
                        "total_outstanding": total,
                        "entries": [
                            {
                                "student_id": e["student_id"],
                                "student_no": e["student_no"],
                                "student_name": e["student_name"],
                                "outstanding_amount": e["outstanding_amount"],
                                "invoice_receipt_id": e.get("invoice_receipt_id"),
                                "invoice_receipt_no": e.get("invoice_receipt_no"),
                            }
                            for e in entries
                        ],
                        "note": req.note,
                    }

                    ack = await conn.fetchrow(
                        f"""INSERT INTO finance_receipts
                               (room_id, receipt_no, doc_type, year_be, seq,
                                student_payment_id, legacy_transaction_id, student_id,
                                collection_id, amount, paid_total_after, issued_to_name,
                                issued_by, issued_by_name, note, event_at, issued_at,
                                layout_version, document_meta, idempotency_key)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                                   2, $18::jsonb, $19)
                        RETURNING {_DOC_COLUMNS}""",
                        target_room_id, receipt_no, DOC_TYPE_ACKNOWLEDGEMENT, year_be, seq,
                        # 🔴 NULL ทั้งสาม: ACK เป็นเอกสารระดับห้อง/รอบ ไม่ผูกบิล/แคมเปญ/งวดเงิน
                        None, None, None, None,
                        total,
                        # 🚫 ไม่มีการรับเงิน ⇒ ยอดสะสมหลัง "ชำระ" = 0 (NOT NULL ตาม DDL)
                        0,
                        f"นักเรียน {len(entries)} คน",
                        user_id, user_name, req.note,
                        issued_at_db, issued_at_db,
                        json.dumps(document_meta, ensure_ascii=False),
                        req.idempotency_key,
                    )

                    await conn.executemany(
                        """INSERT INTO finance_ack_entries
                               (room_id, ack_receipt_id, student_id, invoice_receipt_id,
                                outstanding_amount, acknowledged_at, note)
                           VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                        [
                            (
                                target_room_id, ack["id"], e["student_id"],
                                e.get("invoice_receipt_id"), e["outstanding_amount"],
                                issued_at_db, req.note,
                            )
                            for e in entries
                        ],
                    )

                    links = [
                        (
                            target_room_id, DOC_TYPE_ACKNOWLEDGEMENT, ack["id"],
                            DOC_TYPE_INVOICE, e["invoice_receipt_id"], "invoice_for_ack",
                        )
                        for e in entries if e.get("invoice_receipt_id")
                    ]
                    if links:
                        await conn.executemany(
                            """INSERT INTO finance_document_links
                                   (room_id, from_doc_type, from_doc_id,
                                    to_doc_type, to_doc_id, link_type)
                               VALUES ($1,$2,$3,$4,$5,$6)
                               ON CONFLICT ON CONSTRAINT uq_finance_document_links
                               DO NOTHING""",
                            links,
                        )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="success",
                        new_values={
                            "doc_type": DOC_TYPE_ACKNOWLEDGEMENT,
                            "receipt_no": receipt_no,
                            "amount": total,
                            "scope": req.scope,
                            "entry_count": len(entries),
                            "invoice_nos": [r["receipt_no"] for r in issued_invoices],
                        },
                        endpoint_or_command="FinanceService.issue_acknowledgements",
                        execution_time_ms=exec_time,
                    )

                    return await cls._ack_response(conn, ack, reused=False)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.issue_acknowledgements",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _collect_ack_entries(
        cls, conn: asyncpg.Connection, room_id: int, scope: str,
        student_ids: Optional[List[int]],
    ) -> list:
        """รายชื่อผู้ค้างของ ACK → `{student_id, student_no, student_name, outstanding_amount}`

        - `selected`: ตามลำดับที่เลือก (dedupe) · คนที่ไม่อยู่ห้อง = 404 · ไม่ค้าง = 400
          🔴 ต่างจากโหมดทั้งห้องโดยเจตนา: "ระบุคนที่ไม่มีอะไรให้แจ้ง" = ผู้ใช้เข้าใจผิด
        - `room`: ทุกคนที่ค้าง เรียงตามเลขที่นักเรียน · คนที่ยอดปัดเป็น 0 ถูกข้ามเงียบ ๆ
          (ผู้ใช้ไม่ได้เลือกเขา และไม่มีอะไรให้ผู้ใช้แก้ — หลักเดียวกับ `issue_invoices_for_room`)
        """
        entries = []
        if scope == "selected":
            for sid in list(dict.fromkeys(student_ids or [])):
                rows = await cls._load_student_outstanding(conn, sid, room_id)
                if not rows:
                    in_room = await conn.fetchval(
                        "SELECT 1 FROM students WHERE id = $1 AND room_id = $2",
                        sid, room_id,
                    )
                    if not in_room:
                        raise RoomNotFoundError("ไม่พบนักเรียนคนนี้ในห้องของคุณ")
                    raise ValueError("นักเรียนคนนี้ไม่มีบิลค้างชำระ จึงไม่มีอะไรให้แจ้ง")
                amount = round(sum(float(r["outstanding"]) for r in rows), 2)
                if amount <= 0:
                    raise ValueError("นักเรียนคนนี้ไม่มีบิลค้างชำระ จึงไม่มีอะไรให้แจ้ง")
                entries.append({
                    "student_id": sid,
                    "student_no": rows[0]["student_no"],
                    "student_name": cls._display_name(rows[0]),
                    "outstanding_amount": amount,
                })
            return entries

        debtors = await cls._list_room_debtors(conn, room_id)
        for r in debtors:
            amount = round(float(r["outstanding"]), 2)
            if amount <= 0:
                continue
            entries.append({
                "student_id": r["student_id"],
                "student_no": r["student_no"],
                "student_name": cls._debtor_display_name(r),
                "outstanding_amount": amount,
            })
        return entries
