"""ใบเสร็จ / ใบแจ้งหนี้ (finance_receipts + receipt_sequences) — F3

═══════════════════════════════════════════════════════════════════════════════
[ASYMMETRY] ใบเสร็จ idempotent — ใบแจ้งหนี้ point-in-time  (โดยเจตนา)
═══════════════════════════════════════════════════════════════════════════════
• ใบเสร็จ (receipt) ใช้คู่กับ **เหตุการณ์รับเงิน 1 ครั้ง** ⇒ 1 เหตุการณ์ = 1 ใบ
  กดออกซ้ำได้ **เลขเดิม** ไม่กินเลขใหม่ (การพิมพ์ซ้ำต้องถูกและปลอดภัย ไม่ใช่ error)
  บังคับด้วย partial unique index `idx_finance_receipts_tx_active`
  บน (student_payment_id, COALESCE(legacy_transaction_id,0), doc_type) WHERE doc_type='receipt'

• ใบแจ้งหนี้ (invoice) เป็น **ภาพ ณ เวลาหนึ่ง** — ยอดค้างของนักเรียนเปลี่ยนเมื่อจ่ายเพิ่ม
  ใบเดิมจึง "หมดอายุ" ตามธรรมชาติ ⇒ ออกซ้ำได้ และ **กินเลขใหม่ทุกครั้ง**
  (เจตนาไม่ใส่ doc_type='invoice' ลงใน unique index ข้างบน — มีเทสต์ยืนยันเจตนานี้)

═══════════════════════════════════════════════════════════════════════════════
🔴 ทำไม `year_be` ต้องมาจาก "เหตุการณ์รับเงิน" ไม่ใช่ `student_payments.paid_at`
═══════════════════════════════════════════════════════════════════════════════
`_confirm_single_payment` **ทับ** `paid_at`/`paid_amount`/`transaction_id` ของ
`student_payments` ทุกครั้งที่รับเงินงวดใหม่ ⇒ `paid_at` คือ "เวลาของงวดล่าสุด" เสมอ
ไม่ใช่เวลาของงวดที่กำลังออกใบเสร็จ

ถ้าออกใบเสร็จของงวดที่ 1 (ธ.ค. 2569) หลังจากรับงวดที่ 2 แล้ว (ม.ค. 2570) การอ่าน `paid_at`
จะได้ปี 2570 → **เลขใบเสร็จเป็น REC-2570-xxxx ทั้งที่เอกสารเป็นของปี 2569** ซึ่งไปขัดกับ
รายงานภาษี/สรุปประจำปี ⇒ ใช้ `finance_transactions.created_at` ของ **งวดนั้น ๆ** แทน

🔴 `created_at` เป็น TIMESTAMP **naive ที่เก็บเวลา UTC** — ห้ามเรียก `.astimezone()` ตรง ๆ
   (จะได้ TypeError หรือเวลาเพี้ยน) ต้อง `.replace(tzinfo=timezone.utc)` ก่อนเสมอ
   ⇒ ใช้ `_thai_year_be()` ด้านล่างซึ่งทำถูกอยู่ที่เดียว
   (UTC+7 ทำให้รายการช่วง 17:00–24:00 UTC ตกเป็นวันรุ่งขึ้นของไทย → ข้ามปี พ.ศ. ได้จริง)

═══════════════════════════════════════════════════════════════════════════════
❌ ห้าม publish Discord ตอนออกใบเสร็จ
═══════════════════════════════════════════════════════════════════════════════
เงินก้อนนั้นแจ้งเตือนไปแล้วตอน `confirm_payment` (event FINANCE_PAYMENT)
การเพิ่ม embed อีกใบ = ping ซ้ำ ซึ่งเป็นความผิดพลาดที่โปรเจกต์นี้เคยแก้ไปแล้วครั้งหนึ่ง
(batch endpoint ถูกสร้างมาเพื่อยุบ N การแจ้งเตือนให้เหลือ 1) ⇒ ที่นี่จึงไม่มี ActionService เลย
"""
import asyncpg
import json
import time
from datetime import date, datetime, timezone
from typing import List, Optional

from core.exceptions import PaymentNotFoundError, RoomNotFoundError
from core.rbac import require_permission, require_member

from .base import _lock_payments_in_order, _lock_room_money, service_logger
from .baht_text import baht_text
from .constants import (
    BATCH_SOURCE_AUTO, BATCH_SOURCE_ROOM,
    BUDDHIST_ERA_OFFSET, DOC_STATUS_ACTIVE, DOC_STATUS_VOIDED, DOC_TYPE_DEPOSIT,
    DOC_TYPE_INCOME, DOC_TYPE_INVOICE, DOC_TYPE_LABELS, DOC_TYPE_PREFIXES,
    DOC_TYPE_PAYMENT_VOUCHER, DOC_TYPE_RECEIPT,
    PDF_BATCH_TIMEOUT, RECEIPTS_PER_PDF_MAX, RECEIPT_LIKE_DOC_TYPES,
    RECEIPT_NO_TEMPLATE, RECEIPT_SEQ_BUDGET_MSG, RECEIPT_SEQ_MAX,
    RECEIPT_SEQ_OVERFLOW_MSG, THAI_MONTHS_SHORT, THAI_TZ,
)
from .helpers import _as_utc

# คอลัมน์ที่ SELECT จาก finance_receipts ซ้ำ ๆ — รวมไว้ที่เดียวกันลืมเพิ่มที่ใดที่หนึ่ง
_RECEIPT_COLUMNS = """
    R.id, R.room_id, R.receipt_no, R.doc_type, R.year_be, R.seq,
    R.student_payment_id, R.legacy_transaction_id, R.student_id, R.collection_id,
    R.amount, R.paid_total_after, R.issued_to_name, R.issued_by_name, R.note,
    R.event_at, R.status, R.voided_at, R.voided_by, R.void_reason, R.issued_at,
    R.batch_id
"""

# 🗓️ "วันที่ของเอกสาร" — ใช้ `event_at` ถ้ามี ไม่งั้นถอยไปใช้ `issued_at`
#    ⚠️ ต้องเป็น **นิพจน์เดียวกัน** ทั้งการกรองช่วง การเรียงลำดับ และการพิมพ์
#       ถ้าจอกรองด้วย issued_at แต่กระดาษพิมพ์ event_at เอกสารจะ "อยู่คนละวัน" กับที่ค้นเจอ
_DOC_DATE = "COALESCE(R.event_at, R.issued_at)"

# 🚫 `_ACTIVE_DOC_TYPES = (receipt, invoice)` ถูก **ลบทิ้ง** เมื่อใบแจ้งหนี้ย้ายไปเส้นทาง
#    "ยอดค้างรวมต่อคน" — ตัวแปรนั้นเคยใช้เป็นประตูของ `issue_receipt`/`issue_receipts_batch`
#    ⇒ ถ้าปล่อยไว้จะอ่านเหมือน "สองเส้นทางนี้ยังรับ invoice อยู่" ทั้งที่ไม่รับแล้ว
#    (กับดักชนิดเดียวกับ index ที่ predicate ไม่ตรงกับความเชื่อของคนอ่าน)

# 📋 ใบแจ้งหนี้ "รวมยอดต่อคน" — 1 ใบต่อ 1 นักเรียน (ยอดค้างรวมทุกโครงการ) ไม่ใช่ 1 ใบต่อ 1 บิล
#    ⇒ ใบพวกนี้มี `collection_id = NULL` จึงไม่มีชื่อแคมเปญให้แสดง ต้องสร้างชื่อจาก snapshot
_AGGREGATE_TITLE_TEMPLATE = "ยอดค้างชำระรวม {count} โครงการ"

# 🖨️ จำนวนบรรทัดสูงสุดในตารางรายการ — กันใบที่ค้าง 30 โครงการล้นไปหน้า 2
#    สัญญาของ PDF รวมคือ "หน้าละคน" ⇒ ใบที่ล้นหน้าทำให้สัญญานั้นเป็นเท็จ
#    (ยอดยังครบถ้วนเสมอ เพราะแถว "รวมทั้งสิ้น" พิมพ์ `amount` ที่พาดหัว ไม่ใช่ผลบวกของบรรทัด)
_MAX_PRINTED_LINE_ITEMS = 12

# 🗂️ ชนิดเอกสารที่ **ยุบรวมได้** เมื่อผู้ใช้เลือกหลายใบพร้อมกัน (F6/PR-4)
#    ⚠️ `invoice` **ไม่อยู่ในลิสต์นี้โดยเจตนา** — ใบแจ้งหนี้เป็น "ยอดค้างรวมต่อคน" อยู่แล้ว
#       โดยตัวสร้าง (`_issue_invoice_aggregate`) และ `line_items` ของมันเป็น snapshot
#       หลายบรรทัดที่มีบรรทัด "รวมทั้งสิ้น" ของตัวเอง ⇒ ยุบสองใบจะเอา snapshot สองช่วงเวลา
#       มาบวกกันบนหน้าเดียว ยอดรวมที่ได้จะไม่ใช่ยอดค้าง ณ เวลาใดเวลาหนึ่งเลย
_MERGEABLE_DOC_TYPES = (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT)

# 👥 จำนวนสมาชิกสูงสุดของกลุ่มที่ยุบ — **คนละตัวกับ `_MAX_PRINTED_LINE_ITEMS` โดยเจตนา**
#    (สัญญาต่างกัน: นั่นคือ "บรรทัดย่อยของใบเดียว" นี่คือ "จำนวนเอกสารในหนึ่งหน้า")
#
#    🔄 เกินเพดานแล้ว **แยกเป็น N หน้า** ไม่ใช่ตัดบรรทัดทิ้ง (ตรงข้ามกับใบแจ้งหนี้ที่พิมพ์
#       "และอีก N โครงการ"): บนใบเสร็จที่ยุบ **บรรทัดคือ "ชุดเอกสาร" เอง** ⇒ ซ่อนบรรทัด
#       = ผู้ปกครองถือใบเสร็จที่เลขไม่อยู่บนกระดาษ = audit trail หายไปจากหลักฐาน
#       ส่วนบนใบแจ้งหนี้ บรรทัดเป็นแค่รายการย่อยและยอดรวมยังถูกต้องจาก snapshot
#       ⇒ การแยกหน้า "ถูกเสมอ" แค่ยาวขึ้น · 12 เหลือเฟือ (การรับเงินจริง 2–5 บิล)
_MAX_MERGED_MEMBERS = 12

# 🧾 [F6] ทางแยกของเทมเพลต — `_document_context` เลือกไฟล์ที่ `receipt.html` จะ `{% include %}`
#    🔴 เอกสารทั้ง 5 ชนิดใช้ **shell เดียวกัน** (`receipt.html` ถือ `<style>` + `.doc`) และ
#       เนื้อในแยกเป็น 2 partial: ใบเสร็จ/ใบแจ้งหนี้/ใบรับเงิน ใช้ `_receipt_body.html`,
#       ใบสำคัญจ่ายใช้ `_voucher_body.html`
#    ⚠️ ชื่อไฟล์ต้องตรงกับไฟล์จริงใน `backend/templates/finance/` — พิมพ์ผิดจะได้
#       `TemplateNotFound` **ตอนกดพิมพ์** ไม่ใช่ตอน import (เทสต์ที่เรนเดอร์ทุกชนิดจึงจำเป็น)
_RECEIPT_BODY_TEMPLATE = "_receipt_body.html"
_VOUCHER_BODY_TEMPLATE = "_voucher_body.html"

# 🔒 ข้อความบอกทางออกเมื่อมีคนยิงเส้นทางใบแจ้งหนี้ **แบบเก่า** (ใบละบิล) มา
#    ⚠️ ต้องบอก "ย้ายไปไหน" ไม่ใช่แค่ปฏิเสธ: หน้าจอที่ค้างเปิดอยู่ (SPA คนละ replica)
#       จะยิง `doc_type='invoice'` มาที่เดิมได้อีกหลายวันหลัง deploy
_STALE_INVOICE_PATH_MSG = (
    "ใบแจ้งหนี้เปลี่ยนวิธีออกแล้ว — ตอนนี้ออกเป็น 'ยอดค้างรวมต่อคน' "
    "กรุณาใช้ปุ่มออกใบแจ้งหนี้ที่หน้าลูกหนี้ (POST /finance/receipts/invoices)"
)

# 🔒 advisory lock ของงานนี้ย้ายไปอยู่ที่ `base._MONEY_LOCK_NAMESPACE` แล้ว
#    (namespace เดียวกันทั้งระบบ — ดูเหตุผลใน `base._lock_room_money`)
#    ⇒ ห้ามนิยาม namespace ใหม่ในไฟล์นี้ มันจะกลายเป็นล็อกคนละดอกกับเส้นทางเงินอื่น


class ReceiptsMixin:
    # ================================================================= helpers
    @staticmethod
    def _thai_year_be(naive_utc: datetime) -> int:
        """ปี พ.ศ. ของเวลาไทย จาก TIMESTAMP naive ที่เก็บเป็น UTC wall-clock

        ใช้ `.replace(tzinfo=timezone.utc)` **ไม่ใช่** `.astimezone()` ตรง ๆ
        (naive ไม่มี tz ให้ astimezone อ้างอิง — Python จะตีเป็นเวลาท้องถิ่นของเครื่อง)
        """
        if naive_utc.tzinfo is None:
            aware = naive_utc.replace(tzinfo=timezone.utc)
        else:
            aware = naive_utc
        return aware.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

    @staticmethod
    def _thai_datetime_text(aware_dt: Optional[datetime]) -> Optional[str]:
        """วัน+เวลาที่จะ **พิมพ์บนเอกสาร** — timestamptz → "13 ก.ย. 2569 19:41 น."

        🚨 ห้ามเปลี่ยนกลับไปเป็น `strftime("%Y-%m-%d %H:%M")` (ค.ศ. / ISO)
        เอกสารใบเดียวกันมีเลขที่เป็น พ.ศ. อยู่แล้ว (`REC-2569-0042`) ⇒ ถ้าบรรทัดวันที่เป็น
        ค.ศ. เอกสารจะ **ขัดแย้งกับตัวเอง** ("วันที่ 2026-09-13" ใต้ "เลขที่ REC-2569-0042")
        และไม่ตรงกับหน้าจอที่แสดง "13 ก.ย. 2569 19:41 น." (period.ts `formatThaiDateTime`)
        ⇒ รูปแบบต้องประกอบที่ backend ที่เดียว แล้วทั้งกระดาษและจอใช้สตริงเดียวกัน
        """
        if aware_dt is None:
            return None
        if aware_dt.tzinfo is None:
            aware_dt = aware_dt.replace(tzinfo=timezone.utc)
        thai = aware_dt.astimezone(THAI_TZ)
        month = THAI_MONTHS_SHORT[thai.month - 1]
        return (f"{thai.day} {month} {thai.year + BUDDHIST_ERA_OFFSET} "
                f"{thai.strftime('%H:%M')} น.")

    @staticmethod
    def _thai_date_text(d: Optional[date]) -> Optional[str]:
        """วันที่ล้วน (DATE) → "15 ต.ค. 2569" — คู่กับ `formatThaiDate` ฝั่ง frontend

        ⚠️ ใช้กับค่าที่เป็น **DATE จริง** เท่านั้น (เช่น `fee_collections.due_date`)
        ห้ามใช้กับ timestamp — จะเสียเวลาและเข้าใจผิดว่าเป็นเที่ยงคืน
        """
        if d is None:
            return None
        return f"{d.day} {THAI_MONTHS_SHORT[d.month - 1]} {d.year + BUDDHIST_ERA_OFFSET}"

    @classmethod
    def _thai_day_text(cls, aware_dt: Optional[datetime]) -> Optional[str]:
        """timestamptz → **วันไทยล้วน** "15 ต.ค. 2569" — ใช้ในตารางของใบที่ถูกยุบ

        ⚠️ ต่างจาก `_thai_datetime_text` (ที่พิมพ์วัน **และ** เวลา) — ในตารางที่ยุบ
           คอลัมน์วันที่ต้องสั้นพอให้ "@ | วันที่ | รายการ | เลขที่ | จำนวน" อยู่ครบใน A4
           และ "วัน" คือสิ่งที่ต้องเทียบกับช่วงวันที่บนหัวใบ ⇒ ตัดเวลาออกที่คอลัมน์นี้เท่านั้น
           (ใบเดี่ยวที่พิมพ์แยกยังคงมีเวลาครบตามเดิม)

        ⚠️ ต้องแปลงเป็น **เวลาไทยก่อน** แล้วจึง `.date()` — ตัดวันที่จาก UTC ตรง ๆ
           จะได้วันผิดสำหรับรายการที่เกิดก่อน 07:00 น. เวลาไทย
        """
        if aware_dt is None:
            return None
        if aware_dt.tzinfo is None:
            aware_dt = aware_dt.replace(tzinfo=timezone.utc)
        return cls._thai_date_text(aware_dt.astimezone(THAI_TZ).date())

    @staticmethod
    def _display_name(row) -> str:
        """ชื่อผู้ชำระแบบเดียวกับที่ `_confirm_single_payment` ใช้ (ให้ตรงกันทั้งระบบ)"""
        name = row["first_name"] or row["first_name_en"] or "Unknown"
        if row["nickname"]:
            name += f" ({row['nickname']})"
        return name

    @classmethod
    def _shape_receipt(cls, row) -> dict:
        """แถว finance_receipts → dict สำหรับ response (cast Decimal → float ตามกฎ)"""
        d = dict(row)
        if d.get("amount") is not None:
            d["amount"] = float(d["amount"])
        if d.get("paid_total_after") is not None:
            d["paid_total_after"] = float(d["paid_total_after"])
        d["amount_text"] = baht_text(d["amount"]) if d.get("amount") is not None else None
        d["doc_type_label"] = DOC_TYPE_LABELS.get(d.get("doc_type"), d.get("doc_type"))
        # 🧾 "เอกสารนี้พูดด้วยถ้อยคำของใบเสร็จหรือใบแจ้งหนี้" — ส่งออกไปให้หน้าจอด้วย
        #    🔴 เดิมหน้าจอคำนวณเองจาก `doc_type` ⇒ มีสองแหล่งของคำตอบเดียวกัน และ
        #       `ReceiptDetail.vue` ก็เขียนเตือนกับดักนี้ไว้เองแล้ว · ตอนนี้เหลือแหล่งเดียว
        #       (`RECEIPT_LIKE_DOC_TYPES` ใน constants.py) ที่ทั้งกระดาษและจออ่านร่วมกัน
        d["is_receipt"] = d.get("doc_type") in RECEIPT_LIKE_DOC_TYPES
        # issued_at / event_at / voided_at เป็น timestamptz (aware) อยู่แล้ว → ส่งออกได้ตรง ๆ
        #    `_as_utc` เป็น no-op กับค่า aware แต่กันกรณีที่ driver/คอลัมน์เปลี่ยนชนิดในอนาคต
        d["issued_at"] = _as_utc(d.get("issued_at"))
        # 🗓️ `event_at` = "วันที่ของเอกสาร" แหล่งเดียวกับที่พิมพ์บนกระดาษ
        #    ⇒ frontend ต้องโชว์ค่านี้ (ไม่ใช่ issued_at) ไม่งั้นจอกับกระดาษลงคนละวัน
        d["event_at"] = _as_utc(d.get("event_at"))
        d["voided_at"] = _as_utc(d.get("voided_at"))
        d["line_items"] = cls._parse_line_items(d.get("line_items"))
        return d

    @staticmethod
    def _parse_line_items(raw):
        """`finance_receipts.line_items` (jsonb) → list ของ dict หรือ None

        ⚠️ asyncpg คืน jsonb เป็น **`str`** — ไม่มี codec ลงทะเบียนไว้ที่ไหนในโปรเจกต์นี้
           ⇒ ถ้าลืม `json.loads` ฝั่ง frontend จะได้สตริงยาว ๆ แทนที่จะได้ตาราง
           (ไม่ error ให้เห็น แค่แสดงผลผิด — แบบเดียวกับบทเรียนที่ `room_service.py:309`)

        🔒 คืน **list ของ dict เท่านั้น** (ไม่ใช่ "อะไรก็ได้ที่ json.loads ผ่าน"):
           ค่าที่หลุดรูปจะไม่ error ตอนอ่าน แต่จะไปพังคนละที่คนละเวลา —
           dict หนึ่งก้อนทำให้ `response_model` ValidationError = 500 ที่หน้า detail,
           สมาชิกที่ไม่ใช่ dict ทำให้เทมเพลตเรียก `.get()` ไม่ได้ = 500 ที่หน้า PDF
           ⇒ กรองให้เหลือแต่รูปที่ทุกปลายทางรับได้ ตั้งแต่จุดเดียวที่ข้อมูลเข้ามา
           (ค่าที่ถูกเขียนจริงมาจาก `_issue_invoice_aggregate` ที่ประกอบรูปนี้เสมอ
            ⇒ การกรองนี้ไม่เคยตัดข้อมูลจริงทิ้ง มีไว้กันข้อมูลที่ถูกแก้มือ)
        """
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return None
        if not isinstance(raw, list):
            return None
        items = [it for it in raw if isinstance(it, dict)]
        return items or None

    @classmethod
    def _shape_receipt_detail(cls, row) -> dict:
        """แถว detail (JOIN แคมเปญ/นักเรียน/ห้อง มาแล้ว) → dict สำหรับ response **และ** สำหรับสร้าง PDF

        🔴 ทำไมต้องเป็นฟังก์ชันเดียว: เส้นทาง `get_receipt` (ที่ frontend เรียก) กับเส้นทาง
           `_document_context` (ที่พิมพ์กระดาษ) ต้องเห็นข้อมูลชุดเดียวกันเป๊ะ ถ้าต่างคนต่าง
           ประกอบ dict เอง วันหนึ่งจะมีคนแก้ข้างเดียวแล้ว "จอไม่ตรงกับกระดาษ"

        🔴 ใบแจ้งหนี้รวมยอดมี `collection_id = NULL` ⇒ LEFT JOIN ไม่เจอแคมเปญ ⇒
           `collection_title`/`collection_amount`/`collection_due_date` เป็น NULL ทั้งชุด
           ทั้งที่เอกสารต้องบอกว่าเรียกเก็บอะไรและเป็นเงินเท่าไร ⇒ เติมจาก **snapshot** แทน

           ค่านิยามที่ทำให้เอกสารสอดคล้องตัวเอง:
             `collection_amount = amount + paid_total_after`  (ยอดเต็ม = ที่ยังค้าง + ที่จ่ายแล้ว)
           ⇒ `remaining = collection_amount - paid_total_after` = `amount` พอดี
             ตรงกับแถว "รวมทั้งสิ้น" และกับ `remaining` ที่ frontend คำนวณเอง
        """
        d = cls._shape_receipt(row)
        d["collection_title"] = row["collection_title"]
        d["collection_due_date"] = row["collection_due_date"]
        d["student_no"] = row["student_no"]
        d["room_name"] = row["room_name"]
        d["room_code"] = row["room_code"]
        if row["collection_amount"] is not None:
            d["collection_amount"] = float(row["collection_amount"])

        items = d.get("line_items") or []
        if d.get("collection_id") is None and items:
            d["collection_title"] = _AGGREGATE_TITLE_TEMPLATE.format(count=len(items))
            d["collection_amount"] = round(
                float(d["amount"]) + float(d["paid_total_after"]), 2
            )

        # 💸 [F6] ใบสำคัญจ่าย — คลี่ `voucher_snapshot` ออกเป็นฟิลด์แบนให้ frontend ใช้ตรง ๆ
        #
        # 🔴 ทำไมต้องแบน ไม่ส่ง jsonb ดิบขึ้นไป: `VoucherFields` ฝั่ง TS ประกาศเป็นฟิลด์
        #    ชัดเจน (ไม่ใช่ `Record<string, unknown>`) ⇒ จอไม่ต้องรู้จักรูปภายในของ snapshot
        #    และวันที่ถูกจัดรูปเป็น ISO ที่นี่ที่เดียว (สัญญาเดียวกับ `collection_due_date`)
        #
        # ⚠️ ทุกคีย์ถูกตั้ง **เสมอ** แม้ไม่ใช่ใบสำคัญจ่าย (เป็น `None`/`[]`) — ตามสัญญาที่
        #    ไฟล์นี้เขียนไว้สำหรับ `collection_amount`/`remaining`: คีย์ที่หายไปเรนเดอร์ว่าง
        #    แต่ `{{ }}` บน `undefined` ที่ฝั่ง TS คือ `undefined` ไม่ใช่ `null` ⇒
        #    `v-if="detail.budgets.length"` จะ **throw** ตอน render (จอขาว ไม่มี error ฝั่งเซิร์ฟเวอร์)
        snapshot = cls._parse_voucher_snapshot(d.get("voucher_snapshot"))
        if snapshot:
            d["approver_name"] = snapshot.get("approver_name")
            d["attachment_count"] = int(snapshot.get("attachment_count") or 0)
            d["account_name"] = snapshot.get("account_name")
            d["account_kind"] = snapshot.get("channel")
            d["bank_name"] = snapshot.get("bank_name")
            d["bank_account_no"] = snapshot.get("bank_account_no")
            d["bank_account_name"] = snapshot.get("bank_account_name")
            d["category_name"] = snapshot.get("category_name")
            d["budgets"] = [
                b for b in (snapshot.get("budgets") or []) if isinstance(b, dict)
            ]
        else:
            d["approver_name"] = None
            d["attachment_count"] = 0
            d["account_name"] = None
            d["account_kind"] = None
            d["bank_name"] = None
            d["bank_account_no"] = None
            d["bank_account_name"] = None
            d["category_name"] = None
            d["budgets"] = []
        return d

    # ============================================================ อ่านบิลเป้าหมาย
    @classmethod
    async def _load_payment(cls, conn: asyncpg.Connection, payment_id: int, room_id: int):
        """อ่านบิล + แคมเปญ + นักเรียน + ชื่อ พร้อมล็อกแถว

        ⚠️ `FOR UPDATE OF SP` จำเป็น ไม่ใช่ `FOR UPDATE` เฉย ๆ: `students`/`users` ถูก
        LEFT JOIN (เป็น nullable side) และ PostgreSQL ห้ามล็อกแถวฝั่ง nullable ของ outer join
        → `FOR UPDATE` เปล่า ๆ จะได้ error 0A000 ทันที

        ⚠️ **ไม่** บังคับ `FC.status = 'active'` เหมือน `_confirm_single_payment` —
        ใบเสร็จพิมพ์ย้อนหลังได้หลังปิดแคมเปญแล้ว (ต่างจาก "การรับเงิน" ที่ต้องห้าม)
        """
        return await conn.fetchrow(
            """
            SELECT SP.id AS payment_id, SP.paid_amount, SP.paid_at, SP.status AS payment_status,
                   SP.deleted_at AS payment_deleted_at,
                   FC.id AS collection_id, FC.title AS collection_title,
                   FC.amount AS collection_amount, FC.status AS collection_status,
                   S.id AS student_id, S.student_no,
                   U.first_name, U.last_name, U.nickname, U.first_name_en,
                   R.room_name, R.room_code
            FROM student_payments SP
            JOIN fee_collections FC ON SP.collection_id = FC.id
            JOIN rooms R ON FC.room_id = R.id
            LEFT JOIN students S ON SP.student_id = S.id
            LEFT JOIN users U ON S.user_id = U.id
            WHERE SP.id = $1 AND FC.room_id = $2
            FOR UPDATE OF SP
            """,
            payment_id, room_id,
        )

    @classmethod
    async def _resolve_event(cls, conn: asyncpg.Connection, payment_id: int,
                             transaction_id: Optional[int], paid_amount, paid_at):
        """หา "เหตุการณ์รับเงิน" ที่จะออกใบเสร็จ พร้อมยอดสะสมถึงงวดนั้น

        คืน dict: {legacy_transaction_id, amount, paid_total_after, event_at} หรือ None

        🎯 ตัดสินใจ: ระบุ `transaction_id` มา → ใช้งวดนั้น / ไม่ระบุ → ใช่งวด **ล่าสุด**
        (ตรงกับ `student_payments.transaction_id` ที่ถูกทับให้ชี้งวดล่าสุดเสมอ)
        """
        rows = await conn.fetch(
            """SELECT id, amount, created_at FROM finance_transactions
               WHERE student_payment_id = $1 AND deleted_at IS NULL
               ORDER BY id""",
            payment_id,
        )

        if rows:
            cumulative = 0.0
            events = []
            for r in rows:
                cumulative += float(r["amount"])
                events.append({
                    "legacy_transaction_id": r["id"],
                    "amount": float(r["amount"]),
                    "paid_total_after": cumulative,
                    "event_at": r["created_at"],
                })
            if transaction_id is not None:
                for ev in events:
                    if ev["legacy_transaction_id"] == transaction_id:
                        return ev
                # ระบุ id ที่ไม่ใช่ของบิลนี้ (หรือถูกลบไปแล้ว) → ห้ามเงียบ ๆ ใช้อันอื่นแทน
                # ไม่งั้นผู้ใช้อาจได้ใบเสร็จของ "งวดอื่น" โดยไม่รู้ตัว
                return None
            return events[-1]

        # ── fallback: บิลที่ถูกทำเป็น 'จ่ายแล้ว' โดยไม่มีแถว finance_transactions ──
        # (ข้อมูลนำเข้าจากยุคก่อน dual-write / แก้ DB ตรง) — ยอมให้ออกใบเสร็จด้วยยอดสะสม
        # แทนที่จะตันไม่ให้ออกเลย โดยไม่มี legacy_transaction_id ให้ผูก
        if transaction_id is not None:
            return None
        if float(paid_amount or 0) <= 0:
            return None
        return {
            "legacy_transaction_id": None,
            "amount": float(paid_amount),
            "paid_total_after": float(paid_amount),
            "event_at": paid_at,
        }

    @classmethod
    async def _find_existing(cls, conn: asyncpg.Connection, payment_id: int,
                             legacy_transaction_id: Optional[int]):
        """ใบเสร็จที่ออกไปแล้วของเหตุการณ์รับเงินนี้ (idempotency — เฉพาะ doc_type='receipt')

        🚫 กรอง `status = 'active'`: ใบที่ถูก void ไปแล้ว (เพราะรายการถูกรับคืน) **ไม่นับว่า
           "ออกไปแล้ว"** มิฉะนั้นบิลที่ revert แล้วจ่ายใหม่จะได้ใบที่ถูกยกเลิกไปแล้วกลับมา
           (จริงอยู่ที่การ void ตั้ง `deleted_at` ด้วย ⇒ เงื่อนไขนั้นกันให้ชั้นหนึ่งแล้ว
            แต่ใส่ทั้งสองเงื่อนไขเพราะที่นี่คือด่าน idempotency ของเอกสารการเงิน)
        """
        return await conn.fetchrow(
            f"""SELECT {_RECEIPT_COLUMNS} FROM finance_receipts R
                WHERE R.student_payment_id = $1
                  AND COALESCE(R.legacy_transaction_id, 0) = $2
                  AND R.doc_type = $3 AND R.deleted_at IS NULL
                  AND R.status = '{DOC_STATUS_ACTIVE}'
                LIMIT 1""",
            payment_id, legacy_transaction_id or 0, DOC_TYPE_RECEIPT,
        )

    # ================================================== ยอดค้างรวมต่อคน (ใบแจ้งหนี้รวม)
    @classmethod
    async def _load_student_outstanding(
        cls, conn: asyncpg.Connection, student_id: int, room_id: int,
    ) -> List:
        """บิลที่ยังค้างของนักเรียน 1 คน — **ทีละแถวต่อบิล** พร้อมยอดที่ต้องใช้คำนวณ

        🔴 predicate ต้อง **เหมือน `CollectionsMixin.get_all_debtors` เป๊ะ**:
              `S.room_id = $1 AND SP.status = 'pending'`
              ไม่กรอง `FC.status`  ·  ไม่กรอง `SP.deleted_at`
           หน้าลูกหนี้โชว์ยอดด้วย predicate ชุดนี้ ⇒ ถ้าที่นี่กรองต่างออกไป ใบแจ้งหนี้
           จะมียอดไม่เท่ากับตัวเลขที่ครูเพิ่งเห็นบนจอ แล้วครูเถียงกับผู้ปกครองไม่ได้
           (มีเทสต์บังคับความเท่ากันนี้ตรง ๆ — ดู `test_finance_invoices.py`)
           ⚠️ `SP.deleted_at` **ไม่มีใครตั้งค่าเลยทั้งโปรเจกต์** (`remove_student_from_collection`
              ใช้ `DELETE FROM student_payments` จริง) ⇒ ใส่ `IS NULL` เพิ่มจะไม่เปลี่ยนผล
              แต่จะทำให้ predicate หลุดจากหน้าจอ = เสี่ยงโดยไม่ได้อะไร

        🎯 ไม่มี `HAVING` ⇒ นักเรียนที่ไม่ค้างเลยได้ **0 แถว** (ไม่ใช่แถวที่ยอด 0)
           ⇒ ผู้เรียกแยก "ไม่มีอะไรให้แจ้งหนี้" ออกจาก "ยอด 0" ได้ตรง ๆ

        ⚠️ อ่านหลายแถว `student_payments` — ปลอดภัยเพราะ **caller ถือ advisory lock ของห้องอยู่**
           (ทุกเส้นทางที่แก้ `paid_amount` ก็ยึดล็อกเดียวกันก่อน ⇒ ระหว่างอ่านกับเขียนไม่มีใครแทรก)
           ⇒ ไม่ต้อง `FOR UPDATE` ที่นี่ และ **ห้ามใส่**: `FOR UPDATE` จะล็อกตามลำดับที่ planner
           เลือก ซึ่งเป็นสิ่งเดียวกับที่ `_lock_payments_in_order` ถูกเขียนขึ้นมาป้องกัน
        """
        return await conn.fetch("""
            SELECT SP.id AS payment_id, FC.id AS collection_id, FC.title,
                   FC.amount AS bill_amount, COALESCE(SP.paid_amount, 0) AS paid_amount,
                   (FC.amount - COALESCE(SP.paid_amount, 0)) AS outstanding,
                   FC.due_date,
                   S.student_no, U.first_name, U.nickname, U.first_name_en
            FROM students S
            LEFT JOIN users U ON S.user_id = U.id
            JOIN student_payments SP ON S.id = SP.student_id
            JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE S.id = $1 AND S.room_id = $2 AND SP.status = 'pending'
            ORDER BY FC.status ASC, FC.due_date ASC
        """, student_id, room_id)

    @classmethod
    async def _list_room_debtors(cls, conn: asyncpg.Connection, room_id: int) -> List:
        """นักเรียนทุกคนที่ **มียอดค้าง** ในห้อง + ยอดค้างรวมต่อคน (query เดียว)

        🎯 ยอดรวมต่อคนคำนวณใน SQL ที่นี่ (ไม่ดึงบิลทุกแถวมากองใน Python) เพราะเส้นทาง
           "ออกทั้งห้อง" ต้องการแค่ยอดต่อคนเพื่อตัดสินว่าใครออกได้/ใครถูกข้าม
           ส่วนรายละเอียดรายบรรทัดถูกอ่านอีกครั้งต่อคนใน `_issue_invoice_aggregate`
           ⇒ predicate ยังเป็นชุดเดียวกับ `get_all_debtors` ตามกฎด้านบน
        """
        return await conn.fetch("""
            SELECT S.id AS student_id, S.student_no,
                   U.first_name, U.nickname, U.first_name_en,
                   SUM(FC.amount - COALESCE(SP.paid_amount, 0)) AS outstanding
            FROM students S
            LEFT JOIN users U ON S.user_id = U.id
            JOIN student_payments SP ON S.id = SP.student_id
            JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE S.room_id = $1 AND SP.status = 'pending'
            GROUP BY S.id, S.student_no, U.first_name, U.nickname, U.first_name_en
            ORDER BY S.student_no ASC
        """, room_id)

    @staticmethod
    def _debtor_display_name(row) -> str:
        """ชื่อนักเรียนแบบเดียวกับ `get_all_debtors` (ให้ข้อความ "ข้ามใคร" ตรงกับหน้าจอ)"""
        name = row["first_name"] or row["first_name_en"] or "Unknown"
        if row["nickname"]:
            name += f" ({row['nickname']})"
        return name

    # ================================================================== core
    @staticmethod
    async def _attach_issuance_batch(
        conn: asyncpg.Connection, *, room_id: int, issued: List[dict], new_ids: List[int],
        source: str, user_id: int, user_name: str,
    ) -> Optional[int]:
        """📚 จัดชุดให้เอกสารที่เพิ่งออกในรอบนี้ + ประทับ `batch_id` กลับเข้า dict ที่จะคืน

        🔴 **นับเฉพาะ `new_ids` = ใบที่ออกใหม่จริง (`reused == False`)** — ใบที่ถูก reuse
           คือใบที่ออกไปก่อนหน้านี้แล้ว การลากเข้าชุดใหม่จะทำให้ชุดเดียวมีใบที่ "ออกคนละเวลา"
           ปนกัน และกดออกซ้ำหลายรอบจะได้ชุดใหญ่ขึ้นเรื่อย ๆ โดยไม่มีเหตุผล
           (ผู้เรียกเป็นคนคัด `new_ids` เพราะมีแต่มันที่รู้ว่าใบไหนถูก reuse)

        ⚠️ **import ในฟังก์ชัน ไม่ใช่ที่หัวไฟล์**: `receipt_batches` import `_RECEIPT_COLUMNS`/
           `_DOC_DATE` จากไฟล์นี้ที่ระดับโมดูล ⇒ ถ้าไฟล์นี้ import กลับที่ระดับโมดูลจะได้
           module ที่ initialize ไม่จบ (`ImportError` แบบวงกลมจริง ไม่ใช่ความระแวง)
           — ทางเลือกอื่น (คัดลอก `_RECEIPT_COLUMNS` ไว้สองที่) ขัดกับคอมเมนต์บนหัวไฟล์นั้น

        ⚠️ **ผู้เรียกต้องอยู่ใน transaction ของการออกเอกสารแล้ว** และยึด `_lock_room_money`
           มาแล้ว (ชุดต้องเกิดพร้อมเอกสาร — ไม่มี background job มาปิดให้ทีหลัง)
        """
        if not new_ids:
            return None
        from .receipt_batches import attach_issuance_batch
        batch_id = await attach_issuance_batch(
            conn, room_id=room_id, receipt_ids=new_ids, source=source,
            user_id=user_id, user_name=user_name,
        )
        if batch_id is not None:
            # ประทับกลับเข้า dict ที่จะคืนให้ผู้ใช้ — ไม่งั้นผู้ใช้ได้เลขที่เอกสารแต่ไม่รู้ว่า
            # มันอยู่ในชุดไหน (จอจะโชว์ "ไม่ได้จัดกลุ่ม" ทั้งที่เพิ่งจัดให้) และต้องยิง GET ซ้ำ
            attached = set(new_ids)
            for r in issued:
                if r["id"] in attached:
                    r["batch_id"] = batch_id
        return batch_id

    # ==================================================== ด่านล่วงหน้าของเลขเอกสาร
    @classmethod
    async def _assert_receipt_seq_budget(
        cls, conn: asyncpg.Connection, room_id: int, doc_type: str, count: int,
    ) -> None:
        """🔎 เช็ค **ก่อนลงมือ** ว่าเลขเอกสารของ (ห้อง, ปีนี้, ชนิดนี้) เหลือพอสำหรับ `count` ใบ

        ใช้โดยเส้นทางที่ **รับเงินก่อน แล้วค่อยออกเอกสาร** (`batch_confirm_payments`)
        ซึ่งเป็นเส้นทางเดียวที่ความล้มเหลวเรื่องเลขเอกสารไปเกิด *หลัง* เงินถูกเขียน

        ─────────────────────────────────────────────────────────────────────────
        🎯 ทำไมต้องมี ทั้งที่ `_issue_one` ตรวจอยู่แล้ว (`seq > RECEIPT_SEQ_MAX`)
        ─────────────────────────────────────────────────────────────────────────
        `_issue_one` ตรวจตอน "จองเลขใบนั้น" ⇒ ในลูป 20 บิลมันจะไปตายที่ใบสุดท้าย
        หลังใบก่อนหน้าถูกเขียนครบแล้ว (แล้ว rollback ทั้งหมด) ⇒ ครูได้ข้อความกว้าง ๆ
        ที่ไม่บอกว่าติดอะไร และไม่รู้ว่ารับเงินไปหรือยัง — ซึ่งเป็นความกังวลอันดับหนึ่ง
        ของคนที่กำลังถือเงินสดอยู่หน้าห้อง

        ด่านนี้ยิงก่อนเข้าลูป ⇒ ยังไม่มีเงินถูกเขียนแม้แต่บาทเดียว ⇒ ข้อความบอกได้ตรง ๆ
        และบอกได้ว่า "ยังไม่มีรายการใดถูกบันทึก"

        ─────────────────────────────────────────────────────────────────────────
        ⚠️ ขอบเขตของด่านนี้ — อ่านให้ครบก่อนเชื่อ
        ─────────────────────────────────────────────────────────────────────────
        • **ไม่ใช่ด่านความปลอดภัย** — ระหว่างที่อ่าน (`SELECT` ไม่ล็อก) กับตอนที่ `_issue_one`
          จองเลขจริง มีช่องให้ replica อื่นแย่งเลขไปได้ ⇒ ด่านนี้ "อาจพลาด" ได้
          แต่ด่านจริงใน `_issue_one` ยังอยู่ครบ ⇒ ผลลัพธ์แย่สุดคือ **400 เหมือนเดิม**
          ไม่ใช่เลขซ้ำ/ข้อมูลพัง (ทั้งคู่ raise ใน transaction เดียวกัน ⇒ rollback ทั้งคู่)
        • **ไม่กินเลข** — เป็น `SELECT` ล้วน ไม่แตะ `receipt_sequences`
        • จำนวนที่ต้องใช้ **แม่นเท่ากับจำนวนใบที่จะออกจริง** เพราะทุกลูปเรียก
          `_confirm_single_payment` ที่ INSERT `finance_transactions` แถวใหม่ ⇒
          `_find_existing` ไม่มีทางเจอใบเดิม ⇒ ไม่มีใบไหนถูก reuse ในเส้นทางนี้
          (ถ้าวันหนึ่งมีใบ reuse ปน ด่านนี้จะ **เข้มเกินจริง** — ยังปลอดภัย แค่ปฏิเสธเร็วไป)
        • ปี พ.ศ. ใช้สูตรเดียวกับ `_issue_one` ฝั่ง fallback: `CURRENT_TIMESTAMP` ของ DB
          (transaction timestamp — คงที่ทั้ง transaction) แปลงเป็นเวลาไทย
          ⇒ ตรงกับปีของ `finance_transactions.created_at` ที่เพิ่ง INSERT ในธุรกรรมนี้
            เพราะทั้งคู่มาจากนาฬิกาเรือนเดียวกัน และ `created_at` เก็บ UTC wall-clock
        """
        if count <= 0:
            return
        # 🕐 อ่านจาก DB ไม่ใช่ `datetime.now()` — 3 replica มีนาฬิกาคนละเรือน
        #    (เหตุผลเดียวกับ `issued_at_db` ใน `_issue_one`)
        now_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
        year_be = now_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET
        last_seq = await conn.fetchval(
            """SELECT last_seq FROM receipt_sequences
               WHERE room_id = $1 AND year_be = $2 AND doc_type = $3""",
            room_id, year_be, doc_type,
        ) or 0
        left = RECEIPT_SEQ_MAX - last_seq
        if count <= left:
            return
        raise ValueError(
            RECEIPT_SEQ_BUDGET_MSG.format(need=count, left=max(left, 0))
        )

    @classmethod
    async def _issue_one(
        cls, conn: asyncpg.Connection, target_room_id: int, payment_id: int,
        doc_type: str, transaction_id: Optional[int], user_id: int,
        user_name: str, note: Optional[str],
    ) -> dict:
        """ออกเอกสาร 1 ใบ — **caller เป็นเจ้าของ transaction** (batch เรียกซ้ำในลูป)

        คืน dict: {"receipt": <row dict>, "reused": bool}
        """
        # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ — **ห้ามย้ายตำแหน่งนี้**
        #
        # ปัญหาที่มันแก้ (deadlock 40P01 → 500 ที่ผู้ใช้เห็น):
        #   เส้นทางนี้ล็อกสองทรัพยากรคนละระดับ คือ (ก) แถว student_payments ของบิลนั้น
        #   (`FOR UPDATE OF SP` ใน `_load_payment`) และ (ข) แถว receipt_sequences
        #   ของ (ห้อง, ปี, ชนิด) ซึ่ง **ใช้ร่วมกันทุกใบของห้อง/ปีนั้น**
        #   ⇒ ถ้าล็อกบิลก่อนแล้วค่อยล็อก sequence ลำดับจะ "สลับกันได้" ระหว่างสองคำขอ:
        #     batch trạng thái [P1..P20] ยึดบิล P1 แล้วยึด sequence ไว้จนจบ transaction
        #     ขณะที่คำขอเดี่ยวของ P5 ยึดบิล P5 แล้วไปรอ sequence → batch ไปต่อที่ P5
        #     แล้วไปรอ P5 ที่คำขอเดี่ยวยึดอยู่ ⇒ วนกลับมาที่เดิม = deadlock
        #   asyncpg โยน DeadlockDetectedError ซึ่ง **ไม่อยู่ในรายการ exception ของ router**
        #   ⇒ กลายเป็น 500 และถ้า batch เป็นผู้แพ้ ใบทั้ง 20 ใบ rollback หมด
        #
        # วิธีแก้: บังคับ "ลำดับการล็อก" ให้เป็นลำดับเดียวเสมอ — advisory lock ระดับ transaction
        #   บน room_id ก่อน แล้วค่อยล็อกบิล/sequence ⇒ เอาลำดับที่สลับได้ออกไปทั้งคลาส
        #   `_xact_` ปล่อยเองเมื่อจบ transaction และ **เรียกซ้ำใน transaction เดียวกันไม่บล็อก**
        #   ⇒ batch ที่เรียกในลูปจึงได้ล็อกครั้งเดียวที่ item แรก แล้วถือไปจน commit
        #
        # ราคาที่จ่าย: การออกเอกสารในห้องเดียวกันถูกจัดคิวเป็นเส้นเดียว ซึ่งแทบไม่ต่างจากเดิม
        #   เพราะแถว sequence ก็ serialize อยู่แล้ว — และการออกเอกสารเป็นการกระทำที่คนกด ไม่ใช่ bulk job
        await _lock_room_money(conn, target_room_id)

        # 🕐 "เวลาที่ออกเอกสาร" อ่านจาก **ฐานข้อมูล** ครั้งเดียวต่อ transaction
        #    `CURRENT_TIMESTAMP` = transaction_timestamp ⇒ **คงที่ทั้ง transaction**
        #    ⇒ ใบทั้งชุดของ batch ได้ `issued_at` เดียวกันเป๊ะ และเท่ากับที่ DEFAULT จะเขียน
        #    ⚠️ ห้ามเปลี่ยนไปใช้ `datetime.now()` ของแอป: 3 replica มีนาฬิกาคนละเรือน
        #       แล้ว `event_at` ของใบแจ้งหนี้จะไม่เท่ากับ `issued_at` ของตัวเองอีก
        issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")

        pay = await cls._load_payment(conn, payment_id, target_room_id)

        # ผู้ใช้อาจส่ง payment_id ของห้องอื่นมา — รวมเป็น 404 เดียวกับ "ไม่มีบิลนี้"
        # (ไม่ใช่ 403 เพื่อไม่ยืนยันว่ามี id นั้นอยู่จริงในระบบ)
        if not pay:
            raise PaymentNotFoundError("ไม่พบรายการชำระเงินนี้ในห้องของคุณ")
        if pay["payment_deleted_at"] is not None:
            raise PaymentNotFoundError("บิลนี้ถูกลบไปแล้ว")

        # 💰 ยอดสะสมที่จ่ายแล้วของบิลนี้ — ใช้ตัดสินว่า "ออกใบเสร็จได้หรือยัง"
        #    (เดิมมี `outstanding = collection_amount - paid_amount` ตรงนี้ด้วย แต่มีแต่
        #     สาขาใบแจ้งหนี้ใช้ ⇒ ย้ายไปคิดที่ `_issue_invoice_aggregate` ที่รวมทุกบิล)
        paid_amount = float(pay["paid_amount"] or 0)

        # ---------------------------------------------------------- ใบเสร็จ
        if doc_type == DOC_TYPE_RECEIPT:
            if paid_amount <= 0:
                raise ValueError("บิลนี้ยังไม่ได้รับการชำระเงิน จึงออกใบเสร็จไม่ได้")
            event = await cls._resolve_event(conn, payment_id, transaction_id,
                                             paid_amount, pay["paid_at"])
            if event is None:
                raise ValueError("ไม่พบรายการรับเงินงวดที่ระบุสำหรับบิลนี้")

            # 🔁 idempotency ชั้นที่ 1 (อ่านก่อนเขียน)
            existing = await cls._find_existing(conn, payment_id, event["legacy_transaction_id"])
            if existing:
                return {"receipt": cls._shape_receipt(existing), "reused": True}

        # ------------------------------------------------------ ใบแจ้งหนี้
        # 🚫 **ไม่มีสาขานี้แล้ว** — ใบแจ้งหนี้ย้ายไปเป็น "ยอดค้างรวมต่อคน"
        #    (`_issue_invoice_aggregate` + `POST /finance/receipts/invoices[/room]`)
        #    ⇒ ตัวนี้รับเฉพาะใบเสร็จ และผู้เรียกที่ยังส่ง doc_type='invoice' มาจะถูกปฏิเสธ
        #      ก่อนถึงบรรทัดนี้ (ดู `issue_receipt`/`issue_receipts_batch`)
        #    ⚠️ ห้ามคืนสาขาใบแจ้งหนี้กลับมาที่นี่: มันจะกลายเป็นทางที่สองที่เขียนแถว
        #       ใบแจ้งหนี้แบบ "ใบละบิล" (`student_payment_id` มีค่า) ซึ่งไม่มีเทสต์คุ้มอยู่
        #       ⇒ "ใบแจ้งหนี้ใบละบิล" จะกลับมาโดยไม่มีใครรู้

        # 💰 ยอดที่จะเขียนลงเอกสารต้อง > 0 **หลังปัดเป็นสตางค์** ไม่ใช่ก่อนปัด
        #    ด่าน `paid_amount <= 0` ข้างบนเช็คค่าดิบ ⇒ จ่าย 0.004 บาทผ่านด่านมาได้
        #    แต่พอ round(0.004, 2) = 0.00 ไปชน `chk_receipt_amount_positive (amount > 0)`
        #    → asyncpg โยน CheckViolationError ซึ่งไม่มีชั้นไหนแปลง ⇒ **500** แทนที่จะเป็น 400
        #      (ผู้ใช้เห็นว่า "ระบบพัง" ทั้งที่ปัญหาคือยอดที่กรอก)
        #    ทิศกลับกันก็เพี้ยนเงียบ ๆ: จ่าย 100.004 → บิลพิมพ์ 100.00 แต่บัญชีถือ 100.004
        #    ⇒ ตรวจที่ "ค่าที่ CHECK จะเห็น" ให้ตรงกัน แล้วใช้ค่าที่ตรวจแล้วเขียนจริง
        document_amount = round(event["amount"], 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดรับเงินน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "
                "(ปัดเป็นสตางค์แล้วเหลือ 0) — กรุณาตรวจสอบยอดที่บันทึกไว้"
            )

        # 🗓️ ปี พ.ศ. ของ **เหตุการณ์รับเงิน** ไม่ใช่ของ paid_at ปัจจุบัน (ดู docstring บนสุด)
        #    ใบเสร็จ → ปีของงวดที่ออกใบนั้น (แหล่งความจริงคือ finance_transactions.created_at)
        #    ใบแจ้งหนี้ (event_at = None) → ปีของ **วันออกเอกสาร**
        #
        # 🔑 และ `event_at` ที่จะเก็บลงตารางคือค่า **ตัวเดียวกัน** กับที่มาของ `year_be`
        #    ⇒ วันที่ที่พิมพ์บนกระดาษกับปีบนเลขเอกสารมาจากวินาทีเดียวกันเสมอ
        #      (เดิมวันที่พิมพ์มาจาก `issued_at` ⇒ ใบเสร็จของงวดเดือน ธ.ค. ที่ออกใน ม.ค.
        #       ได้เลข REC-2569-xxxx แต่บรรทัดวันที่เป็น "ม.ค. 2570" = เอกสารขัดแย้งตัวเอง)
        raw_event_at = event["event_at"]
        if raw_event_at is not None:
            event_at = _as_utc(raw_event_at)
            year_be = cls._thai_year_be(raw_event_at)
        else:
            # ใบแจ้งหนี้ (ตั้งใจให้เป็น None) หรือใบเสร็จของข้อมูลนำเข้าที่ไม่มีเวลางวด
            # ⇒ ใช้ `issued_at` จาก DB ⇒ สองคอลัมน์เท่ากันเป๊ะ ไม่ใช่สองนาฬิกา
            event_at = issued_at_db
            year_be = issued_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        # 🎫 จองเลข — atomicity มาจาก `ON CONFLICT ... DO UPDATE` ที่ล็อกแถวให้เอง
        #    ⇒ ไม่ต้อง `SELECT ... FOR UPDATE` นำหน้า (และห้ามใช้ MAX(seq)+1 เด็ดขาด:
        #    สองคำขอที่อ่าน MAX พร้อมกันจะได้เลขเดียวกันแล้ว INSERT ชนกัน)
        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, doc_type,
        )
        # 🚧 เกิน 4 หลักแล้วเลขจะยาวขึ้นจน `RECEIPT_NO_PATTERN` (path param ของ GET) ไม่รับ
        #    ⇒ ต้องหยุดตรงนี้ ไม่ใช่ปล่อยให้ INSERT สำเร็จแล้วเปิดเอกสารกลับไม่ได้ตลอดกาล
        #    raise ใน transaction ⇒ เลขที่เพิ่งจองไปถูก rollback กลับ (ไม่มีเลขถูกเผา)
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[doc_type], year_be=year_be, seq=seq,
        )

        try:
            # 🔁 SAVEPOINT (`conn.transaction()` ที่ซ้อนใน transaction ที่มีอยู่ = SAVEPOINT)
            #    **จำเป็น ไม่ใช่ความสวยงาม**: Postgres ทำเครื่องหมาย transaction ว่า aborted
            #    ทันทีที่ statement หนึ่งล้มเหลว ⇒ ถ้าไม่มี savepoint คำสั่ง *ถัดไป* ในบล็อก
            #    `except` ข้างล่าง (การอ่าน "ใบที่ชนะ") จะได้ 25P02 InFailedSQLTransactionError
            #    ซึ่งไม่มีชั้นไหนแปลงเป็น HTTP ⇒ **ผู้ใช้ได้ 500 แทนที่จะได้ใบเดิมคืน**
            #    ⇒ ตัวจัดการการแข่ง (race) จะกลายเป็นโค้ดที่ทำให้แย่ลงกว่าไม่มีมันเลย
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO finance_receipts
                           (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                            legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                            issued_to_name, issued_by, issued_by_name, note, event_at, issued_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                       RETURNING id, room_id, receipt_no, doc_type, year_be, seq,
                                 student_payment_id, legacy_transaction_id, student_id, collection_id,
                                 amount, paid_total_after, issued_to_name, issued_by_name, note,
                                 event_at, status, voided_at, voided_by, void_reason, issued_at""",
                    target_room_id, receipt_no, doc_type, year_be, seq, payment_id,
                    event["legacy_transaction_id"], pay["student_id"], pay["collection_id"],
                    document_amount, round(event["paid_total_after"], 2),
                    cls._display_name(pay), user_id, user_name, note,
                    # ⚠️ ส่ง `issued_at` ตรง ๆ ไม่พึ่ง DEFAULT: ต้องเท่ากับ `event_at` ของใบแจ้งหนี้เป๊ะ
                    event_at, issued_at_db,
                )
        except asyncpg.UniqueViolationError:
            # 🔁 idempotency ชั้นที่ 2 — แพ้การแข่งขัน: คำขออื่นออกใบเสร็จของเหตุการณ์เดียวกัน
            #    ไปก่อนเสี้ยววินาที ⇒ **คืนใบที่ชนะ** ไม่ใช่ error (การพิมพ์ซ้ำต้องปลอดภัย)
            #    ⚠️ การจองเลขไปแล้ว 1 หมายเลขจะถูก "ใช้ฟรี" — ยอมรับได้ เพราะการยิงซ้ำ
            #    พร้อมกันเป็นกรณีหายาก และเลขที่ไม่ต่อเนื่องไม่มีผลทางบัญชี (แค่ไม่สวย)
            if doc_type == DOC_TYPE_RECEIPT:
                raced = await cls._find_existing(conn, payment_id, event["legacy_transaction_id"])
                if raced:
                    return {"receipt": cls._shape_receipt(raced), "reused": True}
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

        return {"receipt": cls._shape_receipt(row), "reused": False}

    @classmethod
    async def _issue_invoice_aggregate(
        cls, conn: asyncpg.Connection, target_room_id: int, student_id: int,
        user_id: int, user_name: str, note: Optional[str], issued_at_db: datetime,
    ):
        """ออกใบแจ้งหนี้ **1 ใบต่อ 1 นักเรียน** = ยอดค้างรวมทุกโครงการ — caller เป็นเจ้าของ transaction

        คืน **แถวดิบ** จาก INSERT (caller เป็นคน `_shape_receipt` + เก็บเข้ารายการ)

        🔴 ทำไมไม่ต่อยอด `_issue_one`: สัญญาของตัวนั้นคือ "ต่อ **บิล**" (รับ `payment_id`) การเพิ่ม
           โหมดเข้าไปต้องทำ `payment_id` เป็น Optional แล้วสาขาใบเสร็จ/ใบแจ้งหนี้จะกลายเป็น
           ตารางตัดกันไปกันมา ขณะที่เทสต์ราวสองพันบรรทัดผูกเส้นทางใบเสร็จไว้กับฟังก์ชันนั้น
           ⇒ แยกเป็นฟังก์ชันพี่น้อง และ **ลบสาขาใบแจ้งหนี้เดิมออกจาก `_issue_one` ทั้งก้อน**

        ⚠️ **ไม่มี** `UniqueViolationError` handler ที่นี่โดยเจตนา: `idx_finance_receipts_tx_active`
           มี predicate `doc_type = 'receipt'` ⇒ ใบแจ้งหนี้ไม่เคยเข้าไปยุ่งกับ index นั้น และ
           `idx_finance_receipts_doc_active` ชนไม่ได้เพราะ `receipt_no` มาจาก seq ที่ถูก
           serialize ด้วย `ON CONFLICT` แล้ว ⇒ handler ที่ใส่ไว้จะไม่มีวันทำงาน
           (เป็น savepoint ปลอมที่อ่านแล้วเข้าใจผิดว่ามีการแข่งกันอยู่)

        ⏱️ `issued_at_db` ส่งเข้ามาจาก caller **ตัวเดียวทั้งชุด** ⇒ ใบทุกใบของรอบเดียวกัน
           ได้ `issued_at`/`event_at`/`year_be` ชุดเดียวกันเป๊ะ (ตรงกับพฤติกรรมของ batch ใบเสร็จ)
        """
        # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ — เหตุผลเดียวกับ `_issue_one` (caller ยึดไปแล้ว ⇒ ฟรี)
        #    และเป็นตัวที่ทำให้ **การอ่านหลายแถว `student_payments` ข้างล่างปลอดภัย**
        #    ⇒ ถ้ามีใครถอดล็อกออก การอ่านนี้จะแข่งกับการรับเงินทันที (ยอดบนใบจะเพี้ยนเงียบ ๆ)
        await _lock_room_money(conn, target_room_id)

        rows = await cls._load_student_outstanding(conn, student_id, target_room_id)
        if not rows:
            # แยก "ไม่ใช่เด็กห้องนี้" (404) ออกจาก "เป็นเด็กห้องนี้แต่ไม่ค้าง" (400)
            # ⚠️ 404 ไม่ใช่ 403 โดยเจตนา — ห้ามยืนยันว่ามี student_id นั้นอยู่จริงในระบบ
            #    (หลักเดียวกับคอมเมนต์ใน `_load_payment`)
            in_room = await conn.fetchval(
                "SELECT 1 FROM students WHERE id = $1 AND room_id = $2",
                student_id, target_room_id,
            )
            if not in_room:
                raise RoomNotFoundError("ไม่พบนักเรียนคนนี้ในห้องของคุณ")
            raise ValueError("นักเรียนคนนี้ไม่มีบิลค้างชำระ จึงไม่มีอะไรให้แจ้งหนี้")

        # 💰 NUMERIC → Decimal เสมอ ⇒ `float()` ก่อนบวกทุกตัว (กฎเดียวกับที่อื่นในไฟล์นี้)
        outstanding = sum(float(r["outstanding"]) for r in rows)
        paid_total = sum(float(r["paid_amount"] or 0) for r in rows)

        # 💰 ด่านเดียวกับ `_issue_one`: ยอดต้อง > 0 **หลังปัดเป็นสตางค์** ไม่ใช่ก่อนปัด
        #    🔴 ต้องอยู่ **ก่อน** การจองเลข ไม่งั้นเลขจะถูกกินไปฟรี (มีเทสต์บังคับ)
        document_amount = round(outstanding, 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดค้างชำระน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "
                "(ปัดเป็นสตางค์แล้วเหลือ 0) — กรุณาตรวจสอบยอดที่บันทึกไว้"
            )

        # 🗓️ ปี พ.ศ. ของ **วันออกเอกสาร** — ใบแจ้งหนี้คือ "ภาพ ณ วันนี้" ไม่ผูกกับงวดรับเงิน
        #    🚨 ห้ามใช้ `student_payments.paid_at`: `_confirm_single_payment` ทับมันด้วย NOW()
        #       ทุกงวด ⇒ มันคือเวลาของ **งวดล่าสุด** ⇒ บิลที่ผ่อนจ่ายจะพาปีของงวดก่อนหน้ามา
        #       เป็นปีของวันที่ออกเอกสาร (บั๊กเดิม — เทสต์ F/G ยึดพฤติกรรมนี้ไว้)
        #    ⇒ `event_at` = `issued_at` เป๊ะ ⇒ วันที่บนกระดาษกับปีบนเลขมาจากวินาทีเดียวกัน
        year_be = issued_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        # 🎫 จองเลข — กลไกเดียวกับ `_issue_one` (atomicity มาจาก `ON CONFLICT ... DO UPDATE`)
        #    ⚠️ เขียนซ้ำตรงนี้แทนการดึงออกเป็น helper ร่วม **โดยเจตนา**: การไปตัดโค้ดจองเลข
        #       ออกจาก `_issue_one` คือการผ่าฟังก์ชันที่สำคัญที่สุดของโมดูลเพื่อประหยัด 12 บรรทัด
        #       และมันจะพา coverage เชิงโครงสร้างของ `INSERT INTO receipt_sequences`
        #       ออกจากเส้นทางใบเสร็จไปด้วย ⇒ ถ้าจะรวมในอนาคต ต้องปรับเทสต์โครงสร้างก่อน
        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, DOC_TYPE_INVOICE,
        )
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[DOC_TYPE_INVOICE], year_be=year_be, seq=seq,
        )

        # 📋 snapshot รายการย่อย — **ห้าม recompute ตอนพิมพ์** (เหตุผลเต็มอยู่ใน init_db.py):
        #    ถ้าคำนวณใหม่ ใบที่พิมพ์ซ้ำหลังนักเรียนจ่ายบางส่วนจะได้บรรทัดรวม ≠ ยอดพาดหัว
        #    `due_date` เก็บเป็น ISO เพราะ JSON ไม่มีชนิด DATE ⇒ round-trip ตรงเสมอ
        line_items = [
            {
                "title": r["title"],
                "amount": round(float(r["outstanding"]), 2),
                "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            }
            for r in rows
        ]

        return await conn.fetchrow(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                    legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                    issued_to_name, issued_by, issued_by_name, note, event_at, issued_at, line_items)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb)
               RETURNING id, room_id, receipt_no, doc_type, year_be, seq,
                         student_payment_id, legacy_transaction_id, student_id, collection_id,
                         amount, paid_total_after, issued_to_name, issued_by_name, note,
                         event_at, status, voided_at, voided_by, void_reason, issued_at, line_items""",
            target_room_id, receipt_no, DOC_TYPE_INVOICE, year_be, seq,
            # 🔴 NULL ทั้งสามตัวอย่างเจตนา: ใบนี้ไม่ผูกกับ "บิลเดียว / แคมเปญเดียว / งวดรับเงิน"
            #    ⇒ ยอดที่เก็บจึงเป็นผลรวมของหลายบิล และ `collection_id` ว่างทำให้ทุกจุดอ่าน
            #      ต้องเติมชื่อ/ยอดเต็มจาก snapshot เอง (ดู `_shape_receipt_detail`)
            None, None, student_id, None,
            document_amount, round(paid_total, 2),
            cls._display_name(rows[0]), user_id, user_name, note,
            # ⚠️ `event_at` = `issued_at` ตัวเดียวกันเป๊ะ (ไม่ใช่ None เหมือนใบแจ้งหนี้แบบเก่า)
            #    ⇒ `_DOC_DATE` ใช้ค่าเดียวกันทั้งกรอง/เรียง/พิมพ์ และปี พ.ศ. มาจากค่าเดียวกัน
            issued_at_db, issued_at_db,
            json.dumps(line_items, ensure_ascii=False),
        )

    @classmethod
    async def _issue_deposit(
        cls, conn: asyncpg.Connection, target_room_id: int, student_id: int,
        transaction_id: int, amount: float, user_id: int, user_name: str,
        note: Optional[str], event_at_db: datetime, issued_at_db: datetime,
    ) -> dict:
        """[F4] ออก **ใบรับเงินล่วงหน้า** (`doc_type='deposit'`) — caller เป็นเจ้าของ transaction

        คืน dict: {"receipt": <row dict>, "reused": bool}

        🔴 ทำไม **ห้าม** พยายาม reuse `_issue_one`: ฟังก์ชันนั้นถูกสร้างขึ้นรอบ **บิล** —
           เรียก `_load_payment` แล้ว `_resolve_event(conn, payment_id, ...)` ซึ่งอ่าน
           `student_payments`/`finance_transactions` ของบิลนั้น ใบรับเงินล่วงหน้า
           **ไม่มีบิล** ⇒ ใช้ไม่ได้จริง (เหตุผลเดียวกับที่ `_issue_invoice_aggregate`
           ต้องแยกออกมา — ดู docstring ของตัวนั้น)

        🔑 idempotency มาจาก `idx_finance_receipts_deposit_active` ซึ่งเป็น index **ของตัวเอง**
           เพราะ `idx_finance_receipts_tx_active` ใช้ไม่ได้กับใบนี้: มันมี
           `student_payment_id` เป็นคอลัมน์แรก และใบนี้มีค่าเป็น NULL ⇒ Postgres ถือว่า
           NULL แต่ละตัวไม่ซ้ำกัน ⇒ **ไม่มีการกันซ้ำเลย** ถ้าไปพึ่ง index นั้น

        🗓️ `event_at_db` = `created_at` ของแถว `finance_transactions` ที่เพิ่งเขียน
           (ไม่ใช่ `issued_at_db`) ⇒ **ปี พ.ศ. บนเลขเอกสารมาจากเหตุการณ์รับเงิน**
           ตรงกับกฎของใบเสร็จ ไม่ใช่ของใบแจ้งหนี้
        """
        await _lock_room_money(conn, target_room_id)

        # 💰 ยอดต้อง > 0 **หลังปัดเป็นสตางค์** — ด่านเดียวกับ `_issue_one`/`_issue_invoice_aggregate`
        #    และต้องอยู่ **ก่อน** การจองเลข ไม่งั้นเลขถูกกินไปฟรี
        document_amount = round(float(amount), 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดรับเงินล่วงหน้าน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "
                "(ปัดเป็นสตางค์แล้วเหลือ 0) — กรุณาตรวจสอบยอดที่บันทึกไว้"
            )

        # 🔁 idempotency ชั้นที่ 1 (อ่านก่อนเขียน) — คีย์คือ "เหตุการณ์รับเงิน" ตรง ๆ
        existing = await cls._find_existing_deposit(conn, transaction_id)
        if existing:
            return {"receipt": cls._shape_receipt(existing), "reused": True}

        # 👤 snapshot ชื่อผู้ฝาก ณ เวลาที่ออก (เอกสารที่พิมพ์แล้วต้องไม่ย้อนเปลี่ยนตามชื่อในอนาคต)
        payer = await conn.fetchrow(
            """SELECT U.first_name, U.nickname, U.first_name_en
               FROM students S LEFT JOIN users U ON S.user_id = U.id
               WHERE S.id = $1 AND S.room_id = $2""",
            student_id, target_room_id,
        )
        if not payer:
            raise RoomNotFoundError("ไม่พบนักเรียนคนนี้ในห้องของคุณ")

        year_be = event_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        # 🎫 จองเลข — แยกตัวนับจาก receipt/invoice เองเพราะ PK คือ (room, year_be, doc_type)
        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, DOC_TYPE_DEPOSIT,
        )
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[DOC_TYPE_DEPOSIT], year_be=year_be, seq=seq,
        )

        try:
            row = await conn.fetchrow(
                """INSERT INTO finance_receipts
                       (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                        legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                        issued_to_name, issued_by, issued_by_name, note, event_at, issued_at,
                        line_items)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,NULL)
                   RETURNING id, room_id, receipt_no, doc_type, year_be, seq,
                             student_payment_id, legacy_transaction_id, student_id, collection_id,
                             amount, paid_total_after, issued_to_name, issued_by_name, note,
                             event_at, status, voided_at, voided_by, void_reason, issued_at,
                             line_items""",
                target_room_id, receipt_no, DOC_TYPE_DEPOSIT, year_be, seq,
                # 🔴 NULL สองตัวอย่างเจตนา: ใบนี้ไม่ผูกกับบิลและไม่ผูกกับแคมเปญ
                #    ⇒ `_shape_receipt_detail` จะ **ไม่** แต่ง `collection_amount` ขึ้นมา
                #      (มันเข้าเงื่อนไข `collection_id IS NULL and items` ก็ต่อเมื่อมี
                #       `line_items` ด้วย — ซึ่งเราตั้ง NULL ⇒ บรรทัดนั้นไม่ทำงาน)
                None, transaction_id, student_id, None,
                # 💰 `paid_total_after` = ยอดที่รับเข้ามาพักเท่านั้น — ไม่ใช่ "ยอดสะสมของบิล"
                #    ความหมายจึงต่างจากใบเสร็จ (ซึ่งสะสมข้ามงวดของบิลเดียวกัน)
                document_amount, document_amount,
                cls._display_name(payer), user_id, user_name, note,
                event_at_db, issued_at_db,
            )
        except asyncpg.UniqueViolationError:
            # 🔁 idempotency ชั้นที่ 2 — แพ้การแข่งขัน: คืนใบที่ชนะ ไม่ใช่ error
            raced = await cls._find_existing_deposit(conn, transaction_id)
            if raced:
                return {"receipt": cls._shape_receipt(raced), "reused": True}
            # ชน `idx_finance_receipts_doc_active` (เลขซ้ำ) — ไม่ควรเกิดเพราะ seq ถูก serialize
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

        return {"receipt": cls._shape_receipt(row), "reused": False}

    @classmethod
    async def _find_existing_deposit(cls, conn: asyncpg.Connection, transaction_id: int):
        """ใบรับเงินล่วงหน้าที่ออกไปแล้วของเหตุการณ์รับเงินนี้ (idempotency ของ deposit)

        🚫 กรอง `status = 'active'` ด้วยเหตุผลเดียวกับ `_find_existing`: ใบที่ถูก void
           แล้ว (เพราะรายการถูกรับคืน) ไม่นับว่า "ออกไปแล้ว" มิฉะนั้นการเติมเครดิตใหม่
           หลัง revert จะได้ใบที่ถูกยกเลิกไปแล้วกลับมา

        ⚠️ **คีย์คือ `legacy_transaction_id` อย่างเดียว** ไม่มี `student_payment_id`
           (ใบนี้ไม่มีบิล) ⇒ ต้องมี index ของตัวเอง — ดู `idx_finance_receipts_deposit_active`
        """
        return await conn.fetchrow(
            f"""SELECT {_RECEIPT_COLUMNS} FROM finance_receipts R
                WHERE COALESCE(R.legacy_transaction_id, 0) = $1
                  AND R.doc_type = $2 AND R.deleted_at IS NULL
                  AND R.status = '{DOC_STATUS_ACTIVE}'
                LIMIT 1""",
            transaction_id or 0, DOC_TYPE_DEPOSIT,
        )

    # ──────────────────────────────────────────── [F6] ใบรับเงิน (รายรับที่บันทึกเอง)
    @classmethod
    async def _issue_income_doc(
        cls, conn: asyncpg.Connection, target_room_id: int, transaction_id: int,
        amount: float, payer_name: str, user_id: int, user_name: str,
        note: Optional[str], event_at_db: datetime, issued_at_db: datetime,
    ) -> dict:
        """[F6] ออก **ใบรับเงิน** (`doc_type='income'`) ให้รายรับที่บันทึกเอง — caller เป็นเจ้าของ transaction

        คืน dict: {"receipt": <row dict>, "reused": bool}

        🔴 ผู้ใช้ขอว่า *"ตอนที่บันทึกรายการว่าได้รายรับมา ก็เอาให้มีใบเหมือนกับกดรับเงินห้อง
           จากเพื่อนมา"* ⇒ ใบนี้คือ **หลักฐานว่ารับเงินมาแล้ว** จึงเป็น `is_receipt` (ดู
           `_document_context`) และใช้เทมเพลตใบเสร็จทั้งดุ้น

        🔴 ทำไม **ห้าม** พยายาม reuse `_issue_one`: ฟังก์ชันนั้นสร้างรอบ **บิล** — เรียก
           `_load_payment` แล้ว `_resolve_event(conn, payment_id, ...)` ซึ่งอ่าน
           `student_payments`/`finance_transactions` **ของบิลนั้น** · รายรับที่บันทึกเอง
           **ไม่มีบิล** (`student_payment_id` เป็น NULL) ⇒ ใช้ไม่ได้จริง เหตุผลเดียวกับที่
           `_issue_deposit` ต้องแยกออกมา

        🔑 idempotency มาจาก `idx_finance_receipts_income_active` ซึ่งเป็น index **ของตัวเอง**
           เหตุผลเดียวกับ deposit: `idx_finance_receipts_tx_active` มี `student_payment_id`
           เป็นคอลัมน์แรก และใบนี้มีค่า NULL ⇒ Postgres ถือ NULL แต่ละตัวไม่ซ้ำกัน
           ⇒ **ไม่มีการกันซ้ำเลย** ถ้าไปพึ่ง index นั้น

        🗓️ `event_at_db` = `created_at` ของแถว `finance_transactions` ที่เพิ่งเขียน
           ⇒ **ปี พ.ศ. บนเลขเอกสารมาจากเหตุการณ์รับเงิน** ไม่ใช่จากวันที่กดพิมพ์ซ้ำ

        ⚠️ `event_at_db` **ต้อง tz-aware แล้ว** (ผู้เรียกส่ง `_as_utc(row["created_at"])` มา)
           — `finance_transactions.created_at` เป็น TIMESTAMP **naive ที่เก็บ UTC**
           ⇒ เรียก `.astimezone()` บนค่าดิบจะเงียบ ๆ ใช้ TZ ของเครื่อง แล้วปี พ.ศ. จะเพี้ยน
        """
        await _lock_room_money(conn, target_room_id)

        # 💰 ยอดต้อง > 0 **หลังปัดเป็นสตางค์** และต้องอยู่ **ก่อน** การจองเลข
        #    ไม่งั้นเลขถูกกินไปฟรี (ด่านเดียวกับ `_issue_one`/`_issue_deposit`)
        document_amount = round(float(amount), 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดรับเงินน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "
                "(ปัดเป็นสตางค์แล้วเหลือ 0) — กรุณาตรวจสอบยอดที่บันทึกไว้"
            )

        # 🔁 idempotency ชั้นที่ 1 (อ่านก่อนเขียน) — คีย์คือ "รายการที่บันทึก" ตรง ๆ
        existing = await cls._find_existing_income(conn, transaction_id)
        if existing:
            return {"receipt": cls._shape_receipt(existing), "reused": True}

        year_be = event_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        # 🎫 จองเลข — ตัวนับเดิม (`receipt_sequences`) คนละแถวกับ receipt/invoice/deposit
        #    เพราะ PK คือ (room_id, year_be, doc_type) ⇒ ไม่ต้องมีตารางใหม่
        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, DOC_TYPE_INCOME,
        )
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[DOC_TYPE_INCOME], year_be=year_be, seq=seq,
        )

        try:
            # 🔁 SAVEPOINT — **คัดลอกรูปจาก `_issue_one` (:669) ไม่ใช่จาก `_issue_deposit` (:910)**
            #
            # 🔴 `_issue_deposit` จับ `UniqueViolationError` แล้ว **อ่าน `conn` ต่อทันที**
            #    ใน transaction ที่ Postgres ทำเครื่องหมาย aborted ไปแล้ว ⇒ คำสั่งถัดไป
            #    ได้ `25P02 InFailedSQLTransactionError` ⇒ ไม่มีชั้นไหนแปลงเป็น HTTP
            #    ⇒ **ผู้ใช้ได้ 500 แทนที่จะได้ใบเดิมคืน** — ตัวจัดการการแข่ง (race)
            #    กลับกลายเป็นโค้ดที่ทำให้แย่ลงกว่าไม่มีมันเลย
            #    (วันนี้ `_issue_deposit` รอดเพราะ `idx_student_credits_idem` ยิงก่อนถึงตรงนั้น
            #     — รอดเพราะด่านอื่น ไม่ใช่เพราะโค้ดนี้ถูก)
            #    ⚠️ ห้ามลอกรูปนั้นมาตรง ๆ เด็ดขาด: ที่นี่ไม่มีด่านอื่นอยู่ข้างหน้าอีกชั้น
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO finance_receipts
                           (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                            legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                            issued_to_name, issued_by, issued_by_name, note, event_at, issued_at,
                            line_items)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,NULL)
                       RETURNING id, room_id, receipt_no, doc_type, year_be, seq,
                                 student_payment_id, legacy_transaction_id, student_id, collection_id,
                                 amount, paid_total_after, issued_to_name, issued_by_name, note,
                                 event_at, status, voided_at, voided_by, void_reason, issued_at,
                                 line_items""",
                    target_room_id, receipt_no, DOC_TYPE_INCOME, year_be, seq,
                    # 🔴 NULL สามตัวอย่างเจตนา: ใบนี้ไม่ผูกกับบิล ไม่ผูกกับแคมเปญ
                    #    และไม่ผูกกับนักเรียน (`student_id` NULL ⇒ `_merge_key` คืน None
                    #    ⇒ ใบรับเงินทุกใบได้หน้าของตัวเอง ไม่ถูกยุบรวมกันเป็นหน้าไร้เจ้าของ)
                    #    ⇒ `_shape_receipt_detail` จะ **ไม่** แต่ง `collection_amount` ขึ้นมา
                    None, transaction_id, None, None,
                    # 💰 `paid_total_after` = ยอดที่รับเข้ามาพักเท่านั้น ไม่ใช่ "ยอดสะสมของบิล"
                    document_amount, document_amount,
                    payer_name, user_id, user_name, note,
                    event_at_db, issued_at_db,
                )
        except asyncpg.UniqueViolationError:
            # 🔁 idempotency ชั้นที่ 2 — แพ้การแข่งขัน: คืนใบที่ชนะ ไม่ใช่ error
            #    (ปลอดภัยเพราะมี SAVEPOINT ครอบ ⇒ transaction ยังใช้งานได้)
            raced = await cls._find_existing_income(conn, transaction_id)
            if raced:
                return {"receipt": cls._shape_receipt(raced), "reused": True}
            # ชน `idx_finance_receipts_doc_active` (เลขซ้ำ) — ไม่ควรเกิดเพราะ seq ถูก serialize
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

        return {"receipt": cls._shape_receipt(row), "reused": False}

    @classmethod
    async def _find_existing_income(cls, conn: asyncpg.Connection, transaction_id: int):
        """ใบรับเงินที่ออกไปแล้วของรายการนี้ (idempotency ของ income)

        🚫 กรอง `status = 'active'` ด้วยเหตุผลเดียวกับ `_find_existing`/`_find_existing_deposit`:
           ใบที่ถูก void แล้ว (เพราะรายการถูกรับคืน) ไม่นับว่า "ออกไปแล้ว" มิฉะนั้นรายการ
           ที่ถูก revert แล้วบันทึกใหม่จะได้ใบที่ถูกยกเลิกไปแล้วกลับมา

        ⚠️ **คีย์คือ `legacy_transaction_id` อย่างเดียว** ไม่มี `student_payment_id`
           (ใบนี้ไม่มีบิล) ⇒ ต้องมี index ของตัวเอง — ดู `idx_finance_receipts_income_active`
        """
        return await conn.fetchrow(
            f"""SELECT {_RECEIPT_COLUMNS} FROM finance_receipts R
                WHERE COALESCE(R.legacy_transaction_id, 0) = $1
                  AND R.doc_type = $2 AND R.deleted_at IS NULL
                  AND R.status = '{DOC_STATUS_ACTIVE}'
                LIMIT 1""",
            transaction_id or 0, DOC_TYPE_INCOME,
        )

    # ──────────────────────────────────────── [F6] ใบสำคัญจ่าย (รายจ่ายที่บันทึกเอง)
    @classmethod
    async def _issue_payment_voucher(
        cls, conn: asyncpg.Connection, target_room_id: int, transaction_id: int,
        amount: float, payee_name: str, user_id: int, user_name: str,
        note: Optional[str], event_at_db: datetime, issued_at_db: datetime,
        account_id: int, category_id: int, approver_name: Optional[str],
        attachment_count: int,
    ) -> dict:
        """[F6] ออก **ใบสำคัญจ่าย** (`doc_type='payment_voucher'`) ให้รายจ่ายที่บันทึกเอง

        คืน dict: {"receipt": <row dict>, "reused": bool}

        🔴 ผู้ใช้ขอว่า *"อยากให้ตอนที่บันทึกรายการของเงินห้อง ให้มีการสร้างใบสำคัญจ่ายมาด้วย"*
           พร้อมสเปก 5 ส่วน ⇒ ใบนี้ **ไม่ใช่ใบเสร็จ** (เงินออก ไม่ใช่เงินเข้า) จึง
           `is_receipt=False` และมีเทมเพลตของตัวเอง (`_voucher_body.html`)

        🔴 ทำไม **ห้าม** reuse `_issue_one`/`_issue_income_doc`: สามฟังก์ชันนี้เป็น
           **พี่น้อง** ไม่ใช่สาขากัน — `_issue_one` ผูกกับบิล (`_load_payment` →
           `_resolve_event`), `_issue_income_doc` เป็นเงินเข้า, และตัวนี้ต้องเขียน
           `voucher_snapshot` (jsonb) ที่อีกสองตัวไม่มี · การยัดสาขาเข้าไปในตัวใดตัวหนึ่ง
           จะทำให้ทุกจุดที่อ่าน `doc_type` ต้องคิดถึง 3 กรณี (กับดักที่ `docs/skills.md` บันทึกไว้)

        🔑 idempotency มาจาก `idx_finance_receipts_voucher_active` ซึ่งเป็น index ของตัวเอง
           (เหตุผลเดียวกับ income/deposit: `student_payment_id` เป็น NULL ⇒
           `idx_finance_receipts_tx_active` ไม่กันซ้ำให้เลย เพราะ Postgres ถือ NULL
            แต่ละตัวไม่ซ้ำกัน)

        🗓️ `event_at_db` = `created_at` ของแถว `finance_transactions` ที่เพิ่งเขียน
           ⇒ **ปี พ.ศ. บนเลขเอกสารมาจากวันจ่ายจริง** ไม่ใช่จากวันที่กดพิมพ์ซ้ำ
           ⚠️ ต้อง tz-aware แล้ว (ผู้เรียกส่ง `_as_utc(...)` มา) — ดู `_issue_income_doc`
        """
        await _lock_room_money(conn, target_room_id)

        document_amount = round(float(amount), 2)
        if document_amount <= 0:
            raise ValueError(
                "ยอดจ่ายน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ "
                "(ปัดเป็นสตางค์แล้วเหลือ 0) — กรุณาตรวจสอบยอดที่บันทึกไว้"
            )

        # 🔁 idempotency ชั้นที่ 1 (อ่านก่อนเขียน)
        existing = await cls._find_existing_voucher(conn, transaction_id)
        if existing:
            return {"receipt": cls._shape_receipt(existing), "reused": True}

        # 📸 snapshot **ก่อน** จองเลข — ถ้าประกอบไม่ได้ ต้องไม่กินเลขไปฟรี
        #    (และต้องเป็น snapshot ณ ตอนนี้จริง ๆ ไม่ใช่ตอน render — ดูเหตุผลใน docstring
        #     ของ `_build_voucher_snapshot`)
        snapshot = await cls._build_voucher_snapshot(
            conn, target_room_id, account_id, category_id, event_at_db,
            approver_name, attachment_count,
        )

        year_be = event_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

        seq = await conn.fetchval(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, $3, 1)
               ON CONFLICT (room_id, year_be, doc_type)
               DO UPDATE SET last_seq = receipt_sequences.last_seq + 1,
                             updated_at = CURRENT_TIMESTAMP
               RETURNING last_seq""",
            target_room_id, year_be, DOC_TYPE_PAYMENT_VOUCHER,
        )
        if seq > RECEIPT_SEQ_MAX:
            raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)
        receipt_no = RECEIPT_NO_TEMPLATE.format(
            prefix=DOC_TYPE_PREFIXES[DOC_TYPE_PAYMENT_VOUCHER], year_be=year_be, seq=seq,
        )

        try:
            # 🔁 SAVEPOINT — คัดลอกรูปจาก `_issue_one`/`_issue_income_doc`
            #    🔴 **ห้ามลอกรูปของ `_issue_deposit`** ที่จับ `UniqueViolationError`
            #       แล้วอ่าน `conn` ต่อใน transaction ที่ถูก abort (`25P02`) ⇒ 500
            async with conn.transaction():
                row = await conn.fetchrow(
                    """INSERT INTO finance_receipts
                           (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                            legacy_transaction_id, student_id, collection_id, amount, paid_total_after,
                            issued_to_name, issued_by, issued_by_name, note, event_at, issued_at,
                            line_items, voucher_snapshot)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,NULL,$18)
                       RETURNING id, room_id, receipt_no, doc_type, year_be, seq,
                                 student_payment_id, legacy_transaction_id, student_id, collection_id,
                                 amount, paid_total_after, issued_to_name, issued_by_name, note,
                                 event_at, status, voided_at, voided_by, void_reason, issued_at,
                                 line_items, voucher_snapshot""",
                    target_room_id, receipt_no, DOC_TYPE_PAYMENT_VOUCHER, year_be, seq,
                    # 🔴 NULL สามตัว: ไม่ผูกบิล ไม่ผูกแคมเปญ ไม่ผูกนักเรียน
                    #    (`student_id` NULL ⇒ `_merge_key` คืน None ⇒ ใบสำคัญจ่าย
                    #     ไม่ถูกยุบรวมกับใบของนักเรียนคนใด และไม่ยุบกันเอง)
                    None, transaction_id, None, None,
                    # 💰 `paid_total_after` = ยอดที่จ่ายออกครั้งนี้ (ไม่ใช่ "ยอดสะสมของบิล")
                    #    ⚠️ เทมเพลตใบสำคัญ **ไม่พิมพ์ค่านี้** — เป็นแนวคิดต่อบิล
                    document_amount, document_amount,
                    # 🙋 "ออกให้ใคร" = ผู้เบิก/ผู้รับเงิน ตรง ๆ ไม่ต้องเก็บซ้ำอีกคอลัมน์
                    payee_name, user_id, user_name, note,
                    event_at_db, issued_at_db, snapshot,
                )
        except asyncpg.UniqueViolationError:
            # 🔁 idempotency ชั้นที่ 2 — แพ้การแข่งขัน: คืนใบที่ชนะ ไม่ใช่ error
            raced = await cls._find_existing_voucher(conn, transaction_id)
            if raced:
                return {"receipt": cls._shape_receipt(raced), "reused": True}
            raise ValueError("เลขเอกสารซ้ำ กรุณาลองใหม่อีกครั้ง")

        return {"receipt": cls._shape_receipt(row), "reused": False}

    @classmethod
    async def _build_voucher_snapshot(
        cls, conn: asyncpg.Connection, room_id: int, account_id: int, category_id: int,
        event_at_db: datetime, approver_name: Optional[str], attachment_count: int,
    ) -> str:
        """ประกอบ `voucher_snapshot` (jsonb) ของใบสำคัญจ่าย — คืน **สตริง JSON**

        🔴 ทำไมต้อง snapshot ไม่ JOIN สดตอนพิมพ์:
           (ก) `docs/skills.md` — เอกสารที่แจกแจงรายการต้อง snapshot ห้าม recompute
               (แก้ชื่อหมวด/เลขบัญชี/งบทีหลัง ต้องไม่ย้อนไปเปลี่ยนกระดาษที่พิมพ์ไปแล้ว)
           (ข) `_render_documents_pdf` อ่านแค่ `finance_receipts` — JOIN จะผูกทุกใบ
               ที่พิมพ์เข้ากับ 3 ตารางใหม่ตลอดไป
           (ค) ทนต่อฟีเจอร์ "แก้รายการ" ในอนาคตที่จะเขียนใบทิ้งแล้วกลับมาเปลี่ยนข้อมูล

        🔴 คืน **สตริง** ไม่ใช่ dict: asyncpg ของโปรเจกต์นี้ไม่มี codec สำหรับ jsonb
           ⇒ ส่ง dict ตรงเข้า `$18` จะได้ `DataError` และตอนอ่านกลับได้ `str` เสมอ
           (รอยแผลเดียวกับคอมมิต `b8b541c` — ดู `_parse_line_items`)

        🗓️ วันที่ของ "งบที่ครอบ" ตัดสินด้วย **วันไทยของรายการ** ไม่ใช่ UTC
           (`finance_budgets.start_date`/`end_date` เป็น DATE ที่คนตั้งด้วยปฏิทินไทย)
           ⇒ รายการเวลา 23:30 UTC = 06:30 ไทยของวันถัดไป ต้องใช้งบของวันถัดไป
           ⚠️ `_as_utc(...).astimezone(THAI_TZ)` ทำใน Python (ไม่ใช่ SQL) ด้วยเหตุผลเดียวกับ
              `budgets.py` — ค่าที่เป็น "เวลาของเหตุการณ์" ต้องผ่านไปป์ไลน์เดียวทั้งระบบ
        """
        account = await conn.fetchrow(
            """SELECT account_name, account_kind, bank_name, bank_account_no, bank_account_name
               FROM finance_accounts
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
            account_id, room_id,
        )
        category = await conn.fetchrow(
            "SELECT category_name, category_type FROM finance_categories WHERE id = $1",
            category_id,
        )
        txn_day_thai = event_at_db.astimezone(THAI_TZ).date()
        # 🔎 งบเป็น **implicit** — ไม่มี FK ที่ไหนผูก (`finance_budgets` รู้จักแค่
        #    room_id + category_id + ช่วงวันที่) ⇒ ต้อง match เองด้วยเงื่อนไขช่วง
        #    ⚠️ งบซ้อนช่วงกันได้จริง (unique index คือ `(room_id, category_id,
        #       start_date, end_date)` เท่านั้น) ⇒ ลิสต์ยาวเกิน 1 ได้ **โดยชอบ**
        #       และเทมเพลตต้องเตือนเรื่องนับซ้ำ ไม่ใช่เงียบหรือเลือกก้อนแรก
        budgets = await conn.fetch(
            """SELECT B.id, B.amount, B.start_date, B.end_date, B.period_type
               FROM finance_budgets B
               WHERE B.room_id = $1 AND B.category_id = $2 AND B.deleted_at IS NULL
                 AND B.start_date <= $3::date AND B.end_date >= $3::date
               ORDER BY B.start_date, B.id""",
            room_id, category_id, txn_day_thai,
        )
        return json.dumps({
            # 🏦 ช่องทางจ่าย (ตั้งครั้งเดียวที่หน้าตั้งค่ากระเป๋าเงิน — ข้อตกลง #6)
            "account_name": account["account_name"] if account else None,
            "channel": account["account_kind"] if account else None,
            "bank_name": account["bank_name"] if account else None,
            "bank_account_no": account["bank_account_no"] if account else None,
            "bank_account_name": account["bank_account_name"] if account else None,
            # 🏷️ หมวดหมู่งบประมาณ (F2)
            "category_name": category["category_name"] if category else None,
            "category_type": category["category_type"] if category else None,
            "approver_name": approver_name,
            "attachment_count": int(attachment_count or 0),
            "budgets": [
                {
                    "id": b["id"],
                    # 💰 cast float ก่อนเสมอ — DECIMAL กลับมาเป็น `Decimal`
                    "amount": float(b["amount"]),
                    "start_date": b["start_date"].isoformat(),
                    "end_date": b["end_date"].isoformat(),
                    "period_type": b["period_type"],
                }
                for b in budgets
            ],
        }, ensure_ascii=False)

    @classmethod
    async def _find_existing_voucher(cls, conn: asyncpg.Connection, transaction_id: int):
        """ใบสำคัญจ่ายที่ออกไปแล้วของรายการนี้ (idempotency)

        🚫 กรอง `status = 'active'` — ใบที่ถูก void แล้ว (เพราะรายการถูกรับคืน) ไม่นับว่า
           "ออกไปแล้ว" มิฉะนั้นรายการที่ revert แล้วบันทึกใหม่จะได้ใบที่ถูกยกเลิกกลับมา

        ⚠️ คีย์คือ `legacy_transaction_id` อย่างเดียว ⇒ ต้องพึ่ง
           `idx_finance_receipts_voucher_active` (ดูเหตุผลเรื่อง NULL ใน issuer)
        """
        return await conn.fetchrow(
            f"""SELECT {_RECEIPT_COLUMNS} FROM finance_receipts R
                WHERE COALESCE(R.legacy_transaction_id, 0) = $1
                  AND R.doc_type = $2 AND R.deleted_at IS NULL
                  AND R.status = '{DOC_STATUS_ACTIVE}'
                LIMIT 1""",
            transaction_id or 0, DOC_TYPE_PAYMENT_VOUCHER,
        )

    @staticmethod
    def _parse_voucher_snapshot(raw) -> Optional[dict]:
        """`finance_receipts.voucher_snapshot` (jsonb) → dict หรือ None

        ⚠️ asyncpg คืน jsonb เป็น **`str`** (ไม่มี codec ลงทะเบียนไว้ที่ไหนในโปรเจกต์นี้)
           ⇒ ลืม `json.loads` = เทมเพลตได้สตริงยาว ๆ แทนที่จะได้ dict แล้ว
           `d.voucher_category_name` เรนเดอร์ว่าง **โดยไม่มี error** (กับดักเดียวกับ
           `_parse_line_items`)

        🔒 คืน **dict เท่านั้น** — ค่าที่หลุดรูป (list/สเกลาร์) จะทำให้เทมเพลตเรียก
           `.get()` ไม่ได้ = 500 ตอนพิมพ์ ⇒ กรองตั้งแต่จุดเดียวที่ข้อมูลเข้ามา
        """
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return None
        return raw if isinstance(raw, dict) else None

    # ============================================================== public API
    @classmethod
    async def issue_receipt(
        cls, pool: asyncpg.Pool, payment_id: int, user_id: int, client_source: str,
        actor_identifier: str, doc_type: str = DOC_TYPE_RECEIPT,
        transaction_id: Optional[int] = None, note: Optional[str] = None,
        user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ออก **ใบเสร็จ** 1 ใบ — POST แยกจาก confirm_payment โดยเจตนา

        ทำไมไม่ฝังใน `confirm_payment`: (ก) เส้นทางเงินต้องเร็วและมีรูปทรงเดิม
        (ข) การ "พิมพ์ซ้ำ" ต้องไม่ใช่การ "เก็บเงินซ้ำ" (ค) confirm_payment ยาวและมีเทสต์หนาแน่น

        🚫 รับเฉพาะ `doc_type='receipt'` แล้ว — ใบแจ้งหนี้ย้ายไป "ยอดค้างรวมต่อคน"
           ที่ `POST /finance/receipts/invoices` (`issue_invoices`)
           ⚠️ ยัง **ไม่** ตัด `'invoice'` ออกจาก pattern ของ Pydantic โดยเจตนา: หน้าจอที่ค้าง
              เปิดอยู่จะยิง `doc_type='invoice'` มาที่เดิมได้อีกหลายวันหลัง deploy
              ⇒ ถ้าปิดที่ schema ผู้ใช้จะได้ 422 ดิบ ๆ ของ Pydantic แทนข้อความไทยที่บอกว่า
                "ปุ่มย้ายไปไหน" ซึ่งเป็นสิ่งเดียวที่เขาต้องรู้
        """
        start_time = time.time()
        target_room_id = room_id
        if doc_type != DOC_TYPE_RECEIPT:
            raise ValueError(_STALE_INVOICE_PATH_MSG)
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ การออกเอกสารการเงิน = การเขียน ต้องมี MANAGE_FINANCE
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    result = await cls._issue_one(
                        conn, target_room_id, payment_id, doc_type,
                        transaction_id, user_id, user_name, note,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", entity_id=str(result["receipt"]["id"]),
                        status="success",
                        new_values={
                            "receipt_no": result["receipt"]["receipt_no"],
                            "doc_type": doc_type, "payment_id": payment_id,
                            "transaction_id": result["receipt"].get("legacy_transaction_id"),
                            "amount": result["receipt"]["amount"], "reused": result["reused"],
                        },
                        endpoint_or_command="FinanceService.issue_receipt",
                        execution_time_ms=exec_time,
                    )

                receipt = result["receipt"]
                if result["reused"]:
                    msg = f"ใบเสร็จถูกออกไปแล้ว (เลขที่ {receipt['receipt_no']}) — คืนใบเดิม"
                else:
                    msg = f"ออกใบเสร็จเลขที่ {receipt['receipt_no']} แล้ว"
                return {"status": "success", "message": msg,
                        "receipt": receipt, "reused": result["reused"]}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", entity_id=str(payment_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.issue_receipt",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def issue_receipts_batch(
        cls, pool: asyncpg.Pool, payment_ids: List[int], user_id: int, client_source: str,
        actor_identifier: str, doc_type: str = DOC_TYPE_RECEIPT, note: Optional[str] = None,
        user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ออกใบเสร็จหลายบิลใน **transaction เดียว** (all-or-nothing)

        ทำไม all-or-nothing: ครูเลือก 20 บิลแล้วกดครั้งเดียว ถ้าพลาดกลางทางแล้วสำเร็จไป 12 ใบ
        ผู้ใช้จะไม่รู้ว่าเหลือใบไหน และกดซ้ำจะได้ใบที่ซ้ำ/ไม่ซ้ำปนกัน — แย่กว่าให้ล้มทั้งชุด
        (ใบเสร็จ idempotent อยู่แล้ว การกดซ้ำหลังล้มจึงปลอดภัย)

        🚫 รับเฉพาะ `doc_type='receipt'` — เหตุผลเดียวกับ `issue_receipt`
        """
        start_time = time.time()
        target_room_id = room_id
        if doc_type != DOC_TYPE_RECEIPT:
            raise ValueError(_STALE_INVOICE_PATH_MSG)
        # dedupe แต่ **รักษาลำดับเดิม** — ผู้ใช้อาจส่ง payment_id ซ้ำจาก checkbox
        # (ถ้าไม่ dedupe จะได้ใบที่สองเป็น reused=True ปนเข้ามาโดยไม่จำเป็น)
        unique_ids = list(dict.fromkeys(payment_ids or []))
        if not unique_ids:
            raise ValueError("ต้องเลือกอย่างน้อย 1 บิล")
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ลำดับการล็อกของทั้งชุด ต้องเป็น "ห้อง → บิลทั้งชุดตาม id → รายใบ"
                    #    - ล็อกห้องก่อน เพื่อให้สอดคล้องกับ `_issue_one` (ดูคอมเมนต์ที่นั่น)
                    #      การเรียกซ้ำใน transaction เดียวกันไม่บล็อก ⇒ ลูปข้างล่างได้ฟรี
                    #    - แล้วล็อกบิล **ทั้งหมด** ตามลำดับ id ⇒ คำขอที่ส่งลำดับสลับกัน
                    #      ไม่ทำให้เกิดวงรอบรอ (เหตุผลเต็มอยู่ใน `_lock_payments_in_order`)
                    #    - และเพราะล็อกครบก่อนแตะกระเป๋าเงิน/sequence ⇒ การรับเงินบิลเดียว
                    #      ที่กำลังถือบิลใดอยู่ จะไม่กลายเป็นอีกครึ่งหนึ่งของวงรอบ
                    await _lock_room_money(conn, target_room_id)
                    await _lock_payments_in_order(conn, unique_ids)

                    issued, reused, new_ids = [], 0, []
                    for pid in unique_ids:
                        r = await cls._issue_one(
                            conn, target_room_id, pid, doc_type, None, user_id, user_name, note,
                        )
                        issued.append(r["receipt"])
                        if r["reused"]:
                            reused += 1
                        else:
                            new_ids.append(r["receipt"]["id"])

                    # 📚 จัดชุดให้ "ใบที่ออกรอบนี้" — ใบที่ reuse ไม่ถูกย้าย (เหตุผลใน `_attach_issuance_batch`)
                    batch_id = await cls._attach_issuance_batch(
                        conn, room_id=target_room_id, issued=issued, new_ids=new_ids,
                        source=BATCH_SOURCE_AUTO, user_id=user_id, user_name=user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="success",
                        new_values={"doc_type": doc_type, "payment_ids": unique_ids,
                                    "receipt_nos": [r["receipt_no"] for r in issued],
                                    "reused_count": reused, "batch_id": batch_id},
                        endpoint_or_command="FinanceService.issue_receipts_batch",
                        execution_time_ms=exec_time,
                    )

                new_count = len(issued) - reused
                return {
                    "status": "success",
                    "message": f"ออกเอกสารแล้ว {new_count} ใบ"
                               + (f" (มีอยู่แล้ว {reused} ใบ)" if reused else ""),
                    "receipts": issued, "issued_count": new_count, "reused_count": reused,
                    "batch_id": batch_id,
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.issue_receipts_batch",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ----------------------------------- ใบแจ้งหนี้ "ยอดค้างรวมต่อคน" (1 คน = 1 ใบ)
    @classmethod
    async def issue_invoices(
        cls, pool: asyncpg.Pool, student_ids: List[int], user_id: int, client_source: str,
        actor_identifier: str, note: Optional[str] = None, user_name: str = "—",
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ออกใบแจ้งหนี้ **ยอดค้างรวม** ให้นักเรียนที่เลือก — 1 คน = 1 ใบ (all-or-nothing)

        🎯 ยอดบนใบ = ยอดค้างรวม **ทุกบิลที่ยัง pending** ของคนนั้นในห้องนี้
           ไม่ใช่เฉพาะบิลที่ติ๊ก ⇒ ครูตอบคำถาม "คนนี้ค้างเท่าไร" ด้วยเอกสารใบเดียว
           (มีตารางแจกแจงรายโครงการกำกับอยู่ในใบ)

        🔴 ทำไม all-or-nothing ที่นี่ด้วย (ทั้งที่ใบเสร็จใช้เหตุผลว่า "retry ได้"):
           ใบแจ้งหนี้เป็น **point-in-time** ⇒ **กดซ้ำไม่ปลอดภัย** ผิดกับใบเสร็จที่กดซ้ำได้เลขเดิม
           ⇒ ถ้าสำเร็จไป 3 จาก 5 คน ผู้ใช้ไม่มีทางกู้นอกจากกดใหม่ แล้วได้ใบชุดใหม่ของ 3 คนแรก
             ทับซ้อนกับใบที่ออกไปแล้ว = ทะเบียนมีเอกสารซ้ำที่ยอดเดียวกันคนละเลข
           ⇒ ล้มทั้งชุดคือทางเดียวที่ "กดใหม่" ยังมีความหมาย

        ⚠️ ไม่จำกัดจำนวนคนต่อครั้งโดยเจตนา: เส้นทางนี้ **ไม่เรนเดอร์ PDF** (จึงไม่ผูกกับเวลา
           ของ Chromium) และครูเป็นคนกดต่อห้อง ⇒ จำนวนถูกจำกัดโดยขนาดห้องอยู่แล้ว
           เพดาน 100 อยู่ที่ `render_documents_pdf` ซึ่งเป็นที่ที่เวลาจริงถูกใช้
        """
        start_time = time.time()
        target_room_id = room_id
        # dedupe แต่ **รักษาลำดับเดิม** — checkbox อาจส่ง student_id ซ้ำมา
        # (ถ้าไม่ dedupe จะได้ใบที่สองของคนเดิม = เอกสารซ้ำคนละเลข)
        unique_ids = list(dict.fromkeys(student_ids or []))
        if not unique_ids:
            raise ValueError("ต้องเลือกนักเรียนอย่างน้อย 1 คน")
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ การออกเอกสารการเงิน = การเขียน ต้องมี MANAGE_FINANCE
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 ล็อกห้องก่อนแตะแถวใด ๆ — ลำดับเดียวกับ `issue_receipts_batch`
                    #    (`_issue_invoice_aggregate` ก็ยึดซ้ำ แต่ยึดที่นี่เพื่อให้อ่านแล้ว
                    #     เห็นว่าทั้งชุดถูก serialize ไว้ตั้งแต่ต้น ไม่ต้องไปไล่ใน helper)
                    await _lock_room_money(conn, target_room_id)
                    # 🕐 เวลาออกเอกสารอ่านครั้งเดียวต่อ transaction ⇒ ใบทั้งชุดได้ค่าชุดเดียวกัน
                    issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")

                    issued = []
                    for sid in unique_ids:
                        row = await cls._issue_invoice_aggregate(
                            conn, target_room_id, sid, user_id, user_name, note, issued_at_db,
                        )
                        issued.append(cls._shape_receipt(row))

                    # 📚 "กดออกรายคน" = รอบเดียวเหมือนกัน ⇒ จัดชุดให้เลย (คำขอของผู้ใช้ข้อ 2)
                    #    ⚠️ ที่นี่ไม่มีแนวคิด reuse: ใบแจ้งหนี้เป็น point-in-time ⇒ ออกใหม่ทุกใบ
                    batch_id = await cls._attach_issuance_batch(
                        conn, room_id=target_room_id, issued=issued,
                        new_ids=[r["id"] for r in issued],
                        source=BATCH_SOURCE_AUTO, user_id=user_id, user_name=user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="success",
                        new_values={"doc_type": DOC_TYPE_INVOICE, "student_ids": unique_ids,
                                    "receipt_nos": [r["receipt_no"] for r in issued],
                                    "batch_id": batch_id},
                        endpoint_or_command="FinanceService.issue_invoices",
                        execution_time_ms=exec_time,
                    )

                return {
                    "status": "success",
                    "message": f"ออกใบแจ้งหนี้ยอดค้างรวมแล้ว {len(issued)} ฉบับ",
                    "receipts": issued, "issued_count": len(issued), "skipped": [],
                    "batch_id": batch_id,
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.issue_invoices",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def issue_invoices_for_room(
        cls, pool: asyncpg.Pool, user_id: int, client_source: str, actor_identifier: str,
        note: Optional[str] = None, user_name: str = "—",
        server_id: Optional[int] = None, room_id: Optional[int] = None,
    ) -> dict:
        """ออกใบแจ้งหนี้ให้ **ทุกคนที่มียอดค้าง** ในห้อง — 1 คน = 1 ใบ (all-or-nothing)

        🔴 ต่างจาก `issue_invoices` ตรง "ใครได้ใบ" ไม่ใช่คำถามของผู้เรียก — ระบบเป็นคนหา
           ผู้ค้างเอง ⇒ คนที่ยอดค้างปัดเป็นสตางค์แล้วเหลือ 0 (บิลที่ `amount == paid_amount`
           แต่ยัง `status='pending'`) ถูก **ข้ามแล้วรายงาน** ไม่ใช่ทำให้ทั้งห้องล้ม:
           ผู้ใช้ไม่ได้เลือกเขา และเขาไม่ควรมีใบอยู่แล้ว ⇒ ไม่มีอะไรให้ผู้ใช้แก้
           (ต่างจากเส้นทางที่ติ๊กเลือกเอง ซึ่ง "ระบุคนที่ไม่มีอะไรให้แจ้งหนี้" = ผู้ใช้เข้าใจผิด
            จึงต้องเป็น 400 ให้รู้ตัว)

        📋 `skipped` ต้องประกาศใน `response_model` ด้วย ไม่งั้นมันจะถูกตัดทิ้งเงียบ ๆ
           แล้วผู้ใช้จะเห็น "ออก 38 ฉบับ" โดยไม่รู้ว่ามี 2 คนถูกข้าม
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    await _lock_room_money(conn, target_room_id)
                    issued_at_db = await conn.fetchval("SELECT CURRENT_TIMESTAMP")

                    debtor_rows = await cls._list_room_debtors(conn, target_room_id)

                    issuable, skipped = [], []
                    for r in debtor_rows:
                        # 🚧 ใช้ **กติกาการปัดตัวเดียวกับ `_issue_invoice_aggregate`** ตรงนี้
                        #    ถ้าตรงนี้กับที่นั่นตัดสินคนละอย่าง จะได้ ValueError ผุดกลางลูป
                        #    = ทั้งห้องล้มเพราะคนที่ผู้ใช้ไม่ได้เลือก (ปัญหาที่คอมเมนต์บนอธิบายไว้)
                        if round(float(r["outstanding"]), 2) <= 0:
                            skipped.append({
                                "student_id": r["student_id"],
                                "student_no": r["student_no"],
                                "student_name": cls._debtor_display_name(r),
                                "reason": "ยอดค้างน้อยกว่า 0.01 บาท (ปัดเป็นสตางค์แล้วเหลือ 0)",
                            })
                        else:
                            issuable.append(r["student_id"])

                    issued = []
                    for sid in issuable:
                        row = await cls._issue_invoice_aggregate(
                            conn, target_room_id, sid, user_id, user_name, note, issued_at_db,
                        )
                        issued.append(cls._shape_receipt(row))

                    # 📚 ทั้งห้องในคำสั่งเดียว = รอบที่ชัดเจนที่สุดของ "ออกพร้อมกัน"
                    #    ⇒ `source='room'` เพื่อให้หน้าจอแยกได้ว่า "ชุดนี้ระบบออกให้ทั้งห้อง"
                    #    ต่างจากชุดที่ครูกดติ๊กเลือกเอง (`auto`) หรือจับกลุ่มทีหลัง (`manual`)
                    batch_id = await cls._attach_issuance_batch(
                        conn, room_id=target_room_id, issued=issued,
                        new_ids=[r["id"] for r in issued],
                        source=BATCH_SOURCE_ROOM, user_id=user_id, user_name=user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="success",
                        new_values={"doc_type": DOC_TYPE_INVOICE,
                                    "student_ids": issuable,
                                    "receipt_nos": [r["receipt_no"] for r in issued],
                                    "skipped_count": len(skipped),
                                    "skipped_student_ids": [s["student_id"] for s in skipped],
                                    "batch_id": batch_id},
                        endpoint_or_command="FinanceService.issue_invoices_for_room",
                        execution_time_ms=exec_time,
                    )

                if not issued:
                    msg = "ไม่มีนักเรียนที่มียอดค้างชำระในห้องนี้ — จึงไม่มีใบแจ้งหนี้ที่ต้องออก"
                else:
                    msg = f"ออกใบแจ้งหนี้ยอดค้างรวมแล้ว {len(issued)} ฉบับ"
                    if skipped:
                        msg += f" (ข้าม {len(skipped)} คน ที่ยอดค้างน้อยกว่า 0.01 บาท)"
                return {
                    "status": "success", "message": msg,
                    "receipts": issued, "issued_count": len(issued), "skipped": skipped,
                    "batch_id": batch_id,
                }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.issue_invoices_for_room",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # -------------------------------------------------------------------- อ่าน
    @classmethod
    async def get_receipts(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        doc_type: Optional[str] = None, student_id: Optional[int] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None,
        include_voided: bool = False,
    ) -> List[dict]:
        """รายการเอกสารของห้อง — กรองช่วงด้วย **เวลาไทย** บน "วันที่ของเอกสาร"

        🗓️ วันที่ที่ใช้กรอง/เรียงคือ `_DOC_DATE` = `COALESCE(event_at, issued_at)` ตัวเดียวกับ
           ที่พิมพ์บนกระดาษ ⇒ ค้น "ธ.ค. 2569" แล้วเจอใบเสร็จของงวด ธ.ค. ที่ออกใน ม.ค. ด้วย
           (เดิมกรองด้วย `issued_at` ⇒ ใบนั้นตกไปอยู่เดือน ม.ค. ทั้งที่เอกสารบอก ธ.ค.)

        🚫 ค่าปริยาย **ไม่คืนใบที่ถูก void** — ดู `include_voided=True` สำหรับมุมมองตรวจสอบ
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                # 🔎 มุมมองตรวจสอบต้องเห็น "ทุกอย่าง" ของห้อง รวมใบที่ถูกลบ/ยกเลิก
                #    ⇒ ตัดทั้ง `deleted_at` และ `status` ออกพร้อมกัน (ตั้งใจ ไม่ใช่หลุด)
                if include_voided:
                    where = "WHERE R.room_id = $1"
                else:
                    where = f"WHERE R.room_id = $1 AND R.deleted_at IS NULL AND R.status = '{DOC_STATUS_ACTIVE}'"
                params: List = [target_room_id]
                idx = 2
                if doc_type:
                    where += f" AND R.doc_type = ${idx}"
                    params.append(doc_type); idx += 1
                if student_id is not None:
                    where += f" AND R.student_id = ${idx}"
                    params.append(student_id); idx += 1
                if start_date is not None:
                    # ขอบเขตวันไทยของ timestamptz คือ `AT TIME ZONE` ตัวเดียว
                    where += f" AND {_DOC_DATE} >= ((${idx}::date)::timestamp AT TIME ZONE 'Asia/Bangkok')"
                    params.append(start_date); idx += 1
                if end_date is not None:
                    # ขอบบนแบบ half-open (`+1 วัน` แล้ว `<`) — ไม่ให้รายการวินาทีสุดท้ายของวันหลุด
                    where += (f" AND {_DOC_DATE} < ((((${idx}::date) + 1)::timestamp)"
                              f" AT TIME ZONE 'Asia/Bangkok')")
                    params.append(end_date); idx += 1

                rows = await conn.fetch(f"""
                    SELECT {_RECEIPT_COLUMNS},
                           FC.title AS collection_title,
                           S.student_no,
                           -- 📋 ใบแจ้งหนี้รวมยอดมี `collection_id = NULL` ⇒ `FC.title` เป็น NULL
                           --    ⇒ ใช้ **จำนวนบรรทัดใน snapshot** มาประกอบชื่อแทน (นับใน SQL
                           --    ไม่ต้องขน `line_items` ทั้งก้อนออกมาแค่เพื่อ `.length`)
                           -- ⚠️ `jsonb_array_length` **error** ถ้าค่าไม่ใช่ array (ไม่ใช่คืน NULL)
                           --    ⇒ ต้องมี `jsonb_typeof` กันไว้ ไม่งั้นข้อมูลผิดรูปแถวเดียว
                           --    ทำให้ **ทั้งหน้าทะเบียนพัง** ไม่ใช่แค่แถวนั้น
                           CASE WHEN jsonb_typeof(R.line_items) = 'array'
                                THEN jsonb_array_length(R.line_items) END AS line_item_count
                    FROM finance_receipts R
                    LEFT JOIN fee_collections FC ON R.collection_id = FC.id
                    LEFT JOIN students S ON R.student_id = S.id
                    {where}
                    ORDER BY {_DOC_DATE} DESC, R.id DESC
                    LIMIT 500
                """, *params)

                result = []
                for r in rows:
                    d = cls._shape_receipt(r)
                    # 📋 เอกสารที่ไม่มีแคมเปญอ้างอิง (ใบแจ้งหนี้รวมยอด) ต้องมีชื่อให้แสดง ไม่งั้น
                    #    คอลัมน์ "รายการ" ในทะเบียนว่างเป็น "-" ทั้งที่ใบนั้นแจกแจง 3 โครงการ
                    #    ⇒ ประกอบชื่อจาก snapshot ที่เดียวกับที่กระดาษใช้ (`_AGGREGATE_TITLE_TEMPLATE`)
                    # ⚠️ `d["line_items"]` เป็น None ที่นี่โดยเจตนา — `_RECEIPT_COLUMNS` ไม่มีคอลัมน์นั้น
                    #    (ทะเบียนโหลดได้ถึง 500 แถว ไม่ควรขน jsonb ก้อนโตมาด้วย) ⇒ อย่าตกใจว่า None
                    d["collection_title"] = (
                        _AGGREGATE_TITLE_TEMPLATE.format(count=r["line_item_count"])
                        if r["collection_title"] is None and r["line_item_count"]
                        else r["collection_title"]
                    )
                    d["student_no"] = r["student_no"]
                    result.append(d)

                # 📚 [F5] เติมข้อมูลชุด (ให้ทะเบียนยุบเป็นชุดได้) — **คำขอที่สอง** โดยเจตนา
                #    ⚠️ `_load_batch_counts` มาจาก `ReceiptBatchesMixin` (ไฟล์อื่น) ⇒ ที่นี่พึ่ง
                #       MRO ของ `FinanceService` ทำงานได้เพราะเมธอดนี้ถูกเรียกผ่าน `cls` =
                #       `FinanceService` เสมอ (เทสต์ก็ยิงผ่าน HTTP) ต่างจาก `_issue_one`
                #       ที่มีเทสต์เรียก `CollectionsMixin.batch_confirm_payments` ตรง ๆ
                #       ⇒ ที่นั่นจึงต้อง `import` ชัดเจน ส่วนที่นี่ใช้ `cls` ได้
                #    🔴 ห้ามใช้ `COUNT(*) OVER (PARTITION BY batch_id)`: window function นับ
                #       เฉพาะแถวที่รอด `WHERE` ⇒ พอผู้ใช้กรองช่วงวันที่ (หรือ `include_voided`
                #       เป็น false ซึ่งตัดใบที่ถูกยกเลิกออก) ตัวเลขจะกลายเป็น "ขนาดของส่วนที่
                #       เห็น" ไม่ใช่ "ขนาดของชุด" ⇒ ป้าย "แสดง 12 จาก 20 ใบ" กลายเป็นคำโกหก
                #       ที่ผู้ใช้ตรวจไม่ได้ (เทสต์ `..._true_batch_size_outside_filter` ปิดไว้)
                counts = await cls._load_batch_counts(
                    conn, room_id=target_room_id, batch_ids=[d.get("batch_id") for d in result]
                )
                if counts:
                    titles = await conn.fetch(
                        "SELECT id, title FROM finance_receipt_batches WHERE room_id = $1 AND id = ANY($2::int[])",
                        target_room_id, list(counts.keys()),
                    )
                    title_by_id = {t["id"]: t["title"] for t in titles}
                    for d in result:
                        info = counts.get(d.get("batch_id"))
                        if info:
                            d["batch_title"] = title_by_id.get(d["batch_id"])
                            d["batch_size"] = info["batch_size"]
                            d["batch_voided_count"] = info["batch_voided_count"]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="FINANCE_RECEIPT", status="success",
                    endpoint_or_command="FinanceService.get_receipts", execution_time_ms=exec_time,
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=None,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_receipts",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_receipt(
        cls, pool: asyncpg.Pool, receipt_no: str, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None,
        include_voided: bool = False,
    ) -> dict:
        """เอกสาร 1 ใบ (ระบุด้วยเลขที่บนเอกสาร ไม่ใช่ id)

        🚫 ค่าปริยายไม่คืนใบที่ถูก void — แต่ `render_receipt_pdf` เรียกผ่านที่นี่
           ⇒ ต้องส่ง `include_voided=True` ตอนพิมพ์ **ใบที่ถูกยกเลิก** เพื่อให้ตรวจสอบย้อนหลังได้
           (เทมเพลตจะประทับ "ยกเลิก" ให้เอง — ดู receipt.html)
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                active_filter = ("" if include_voided
                                 else f" AND R.deleted_at IS NULL AND R.status = '{DOC_STATUS_ACTIVE}'")
                # ⚠️ `R.line_items`/`R.voucher_snapshot` ถูกเติมเข้ามา **ที่นี่ที่เดียว**
                #    (ไม่อยู่ใน `_RECEIPT_COLUMNS` เพราะตัวนั้นถูกใช้โดยทะเบียน 500 แถว)
                #    ⇒ ถ้าย้ายไปใส่ `_RECEIPT_COLUMNS` เมื่อไร ทะเบียนจะขน jsonb ทุกแถว
                #      โดยไม่มีใครได้ใช้ (ทั้งคู่เป็นคอลัมน์ที่หนักและมีไว้เพื่อหน้ารายละเอียด)
                row = await conn.fetchrow(f"""
                    SELECT {_RECEIPT_COLUMNS}, R.line_items, R.voucher_snapshot,
                           FC.title AS collection_title, FC.amount AS collection_amount,
                           FC.due_date AS collection_due_date,
                           S.student_no, R2.room_name, R2.room_code
                    FROM finance_receipts R
                    LEFT JOIN fee_collections FC ON R.collection_id = FC.id
                    LEFT JOIN students S ON R.student_id = S.id
                    JOIN rooms R2 ON R.room_id = R2.id
                    WHERE R.room_id = $1 AND R.receipt_no = $2{active_filter}
                """, target_room_id, receipt_no)
                if not row:
                    raise RoomNotFoundError("ไม่พบเอกสารเลขที่นี้")

                # 🔴 ใช้ตัวจัดรูปเดียวกันกับที่พิมพ์กระดาษ (`_shape_receipt_detail`) —
                #    ถ้าที่นี่ประกอบ dict เอง จอจะค่อย ๆ หลุดจากกระดาษโดยไม่มีใครรู้
                #    (รายละเอียดอยู่ใน docstring ของ `_shape_receipt_detail`)
                d = cls._shape_receipt_detail(row)

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=None,
                    entity_type="FINANCE_RECEIPT", entity_id=str(receipt_no), status="success",
                    endpoint_or_command="FinanceService.get_receipt", execution_time_ms=exec_time,
                )
                return d
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=None,
                        entity_type="FINANCE_RECEIPT", entity_id=str(receipt_no), status="failed",
                        error_detail=str(e), endpoint_or_command="FinanceService.get_receipt",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ==================================================================== PDF
    @classmethod
    def _line_items_for_print(cls, items: Optional[list]) -> tuple:
        """snapshot `line_items` → (บรรทัดที่จะพิมพ์, จำนวนบรรทัดที่ถูกตัดออก)

        🗓️ `due_date` ใน snapshot ผ่าน jsonb มาแล้ว ⇒ เป็น **สตริง ISO** ไม่ใช่ `date`
           ⇒ ต้องแปลงเป็นข้อความไทยที่นี่ ที่เดียว (เทมเพลตไม่รู้จัก `THAI_MONTHS_SHORT`
           และไม่ควรรู้ — วันที่บนกระดาษต้องมาจากแหล่งเดียวกับวันที่บนจอ)

        ✂️ ตัดที่ `_MAX_PRINTED_LINE_ITEMS` เพื่อรักษาสัญญา "หน้าละคน" ของไฟล์รวม
           ⚠️ ยอดรวมยัง **ครบถ้วนเสมอ** เพราะแถว "รวมทั้งสิ้น" พิมพ์ `amount` ที่พาดหัว
              (ค่าที่เก็บไว้ตอนออกเอกสาร) ไม่ใช่ผลบวกของบรรทัดที่พิมพ์ ⇒ การตัดบรรทัด
              ไม่ทำให้ยอดบนใบผิด — และมีเทสต์บังคับ `sum(line_items) == amount` ไว้แล้ว
        """
        printed, hidden = [], 0
        for i, it in enumerate(items or []):
            if i >= _MAX_PRINTED_LINE_ITEMS:
                hidden += 1
                continue
            due = it.get("due_date")
            if isinstance(due, str) and due:
                try:
                    due = date.fromisoformat(due)
                except ValueError:
                    # 📅 วันที่เพี้ยนไม่ควรทำให้ **ทั้งใบพิมพ์ไม่ได้** — บรรทัดนี้ยังมียอด
                    #    ที่ถูกต้อง ซ่อนแค่วันที่ (ผลรวมของบรรทัดจึงยังเท่ายอดพาดหัว)
                    due = None
            printed.append({
                "title": it.get("title") or "-",
                "amount": float(it.get("amount") or 0),
                "due_date_text": cls._thai_date_text(due) if isinstance(due, date) else None,
            })
        return printed, hidden

    @staticmethod
    def _voucher_channel_text(d: dict) -> Optional[str]:
        """ช่องทางจ่ายเงินของใบสำคัญจ่าย → ข้อความไทยหนึ่งบรรทัด (หรือ None ถ้าไม่มีข้อมูล)

        ⚠️ `@staticmethod` **ไม่ใช่ `@classmethod`** โดยเจตนา: ฟังก์ชันนี้ไม่ใช้ `cls` เลย
           ⇒ ถ้าติด `@classmethod` โดยที่พารามิเตอร์แรกยังชื่อ `d` จะได้
           `TypeError: takes 1 positional argument but 2 were given` **ทุกครั้งที่เรนเดอร์
           ใบสำคัญ** (ไม่ใช่ตอน import) — พลาดมาแล้วครั้งหนึ่งใน PR นี้

        🏦 ข้อมูลมาจาก `voucher_snapshot` (ไม่ได้ JOIN สด) ⇒ ใบที่พิมพ์ไปแล้วยังบอก
           ช่องทางเดิมแม้ครูจะไปแก้กระเป๋าเงินทีหลัง — ตรงกับสัญญาของเอกสารการเงิน

        ⚠️ `None` = "ไม่รู้" ไม่ใช่ "เงินสด": ใบสำคัญที่ออกก่อนฟีเจอร์นี้ (หรือกระเป๋าที่
           ถูกลบไปแล้ว) ต้องอ่านว่าไม่มีข้อมูล ไม่ใช่ถูกกล่าวหาว่าจ่ายเป็นเงินสด
           ⇒ เทมเพลตพิมพ์ "-" ให้กรณีนี้ (ห้ามเดา)
        """
        kind = d.get("account_kind")
        if not kind:
            return None
        if kind == "cash":
            return "เงินสด"
        parts = [
            p for p in (d.get("bank_name"), d.get("bank_account_no"), d.get("bank_account_name"))
            if p
        ]
        # ธนาคารที่ยังไม่ได้กรอกรายละเอียด = "โอนเข้าบัญชี" เฉย ๆ — ไม่ใช่ช่องว่าง
        return "โอนเข้าบัญชี — " + " · ".join(parts) if parts else "โอนเข้าบัญชี"

    @classmethod
    def _voucher_budget_rows(cls, d: dict) -> list:
        """งบที่ครอบรายการ (จาก snapshot) → แถวสำหรับพิมพ์

        🔴 อ่านจาก `budgets` ของ snapshot **เท่านั้น ห้าม query ใหม่** — งบที่ถูกแก้หรือลบ
           หลังออกเอกสารต้องไม่ย้อนไปเปลี่ยนกระดาษที่แจกไปแล้ว (`docs/skills.md`)

        ⚠️ จัดรูปวันที่ + cast `float` ที่นี่ ไม่ใช่ในเทมเพลต: snapshot เก็บ ISO string
           (`"2026-09-01"`) แต่กระดาษต้องได้ "1 ก.ย. 2569" แบบเดียวกับวันที่อื่นทั้งใบ
           และ `Decimal` ที่หลุดมาถึง `"{:,.2f}".format()` จะพังตอนเรนเดอร์

        🛡️ ค่าที่ผิดรูปถูก **ข้าม** ไม่ใช่ทำให้ล้มทั้งใบ: snapshot เก่าที่เขียนด้วยโค้ดคนละรุ่น
           ต้องพิมพ์ใบที่เหลือได้ ดีกว่าดาวน์โหลดไม่ได้ทั้งใบ
        """
        rows = []
        for b in d.get("budgets") or []:
            if not isinstance(b, dict):
                continue
            try:
                start = date.fromisoformat(str(b.get("start_date"))[:10])
                end = date.fromisoformat(str(b.get("end_date"))[:10])
            except (ValueError, TypeError):
                continue
            rows.append({
                "period_text": "{} – {}".format(
                    cls._thai_date_text(start), cls._thai_date_text(end)
                ),
                "amount": float(b.get("amount") or 0),
                "period_type": b.get("period_type"),
            })
        return rows

    @classmethod
    def _document_context(cls, d: dict) -> dict:
        """เอกสาร 1 ใบ (`_shape_receipt_detail`) → context ของเทมเพลต Jinja2

        🔴 แยกออกมาเป็นฟังก์ชันเดียวเพราะ **ใบเดียวกับใบในไฟล์รวมต้องได้ HTML เหมือนกันเป๊ะ**:
           ถ้าเส้นทาง PDF ใบเดียวประกอบ context เอง "พิมพ์ใบเดี่ยว" กับ "พิมพ์รวมแล้วตัดหน้า"
           จะได้กระดาษคนละแบบโดยไม่มีใครรู้จนกว่าจะมีคนเอามาวางเทียบกัน
        """
        amount = float(d["amount"])
        paid_total = float(d["paid_total_after"])
        line_items, line_items_hidden = cls._line_items_for_print(d.get("line_items"))

        context = {
            "doc_title": d["doc_type_label"],
            "doc_type": d["doc_type"],
            # 🔴 เทมเพลต branch ด้วย **ค่านี้** ไม่ใช่ `doc_type` (receipt.html หลายสิบจุด)
            #    ⇒ ชนิดเอกสารใหม่ที่ลืมใส่ที่นี่จะถูกพิมพ์ด้วยถ้อยคำของ **ใบแจ้งหนี้**
            #      ("เรียกเก็บจาก" / "ยอดค้างชำระ" / "ผู้รับแจ้ง") ผิดทั้งใบโดยไม่มีอะไรฟ้อง
            #    ⇒ ใบรับเงินล่วงหน้าเป็น "หลักฐานว่ารับเงินมาแล้ว" เหมือนใบเสร็จ ⇒ True
            #    🆕 [F6] ใบรับเงิน (`income`) ก็เป็นหลักฐานว่ารับเงินมาแล้วเหมือนกัน —
            #       ต่างกันแค่ "เงินเขาเพราะบิล" กับ "เงินเขาที่บันทึกเอง"
            #    🔴 `payment_voucher` **ไม่อยู่ในลิสต์นี้โดยเจตนา** — ใบสำคัญจ่ายเป็น
            #       เอกสารสั่งจ่าย ไม่ใช่หลักฐานว่ารับเงิน ⇒ ต้องเป็น False
            # 🔑 อ่านจาก tuple กลางตัวเดียวกับที่ `_shape_receipt` ใช้ส่งให้หน้าจอ
            #    (ดู `RECEIPT_LIKE_DOC_TYPES`) — จอกับกระดาษตอบคำถามนี้ไม่ตรงกันไม่ได้
            "is_receipt": d["doc_type"] in RECEIPT_LIKE_DOC_TYPES,
            "receipt_no": d["receipt_no"],
            # 🗓️ "วันที่" บนกระดาษ = วันของ **เหตุการณ์** ไม่ใช่วันที่กดพิมพ์
            #    ⇒ พิมพ์ซ้ำอีกกี่ครั้งก็ได้วันที่เดิม ตรงกับปี พ.ศ. บนเลขเอกสารเสมอ
            #    (`event_at` ของข้อมูลเก่าที่ไม่มีค่า → ถอยไปใช้ `issued_at` ตาม `_DOC_DATE`)
            "document_date_text": cls._thai_datetime_text(d.get("event_at") or d.get("issued_at")),
            # 🚫 ประทับสถานะบนกระดาษ — ใบที่ยกเลิกแล้วต้องไม่มีทางถูกอ่านเป็นใบที่ยังใช้ได้
            "is_voided": d.get("status") == DOC_STATUS_VOIDED,
            "void_reason": d.get("void_reason"),
            "room_name": d.get("room_name"),
            "room_code": d.get("room_code"),
            "student_no": d.get("student_no"),
            "payer_name": d.get("issued_to_name"),
            "collection_title": d.get("collection_title"),
            # ⚠️ ที่นี่ส่ง "สตริงไทยที่จัดรูปแล้ว" เข้าเทมเพลต ไม่ใช่ `date` ดิบ
            #    (ต่างจาก response ของ API ที่ยังคืน ISO `YYYY-MM-DD` ให้ frontend ไปจัดรูปเอง
            #     ⇒ ห้ามเอา `_thai_date_text` ไปใส่ใน `get_receipt` เพราะจะทำให้
            #     `ReceiptDetail.collection_due_date` ผิดสัญญาและ `formatThaiDate` พัง)
            "collection_due_date": cls._thai_date_text(d.get("collection_due_date")),
            "note": d.get("note"),
            "issuer_name": d.get("issued_by_name"),
            # 💰 ตัวเลข + คำอ่าน ต้องมาจากค่าเดียวกันเสมอ (แปลงครั้งเดียวที่นี่)
            "amount": amount,
            "amount_text": baht_text(amount),
            "paid_total_after": paid_total,
            "paid_total_after_text": baht_text(paid_total),
            # 📋 ใบแจ้งหนี้รวมยอด — ตารางแจกแจงโครงการ (ใบเสร็จ/ใบแจ้งหนี้แบบเก่า = ลิสต์ว่าง
            #    ⇒ เทมเพลตถอยไปใช้แถวเดียวตามเดิม ⇒ คำบนใบเสร็จไม่เปลี่ยน)
            "line_items": line_items,
            "line_items_hidden": line_items_hidden,
            # 🔴 สองคีย์นี้ **ต้องถูกตั้งเสมอ** แม้เอกสารชนิดนั้นไม่มีความหมายนี้
            #    เทมเพลตกันด้วย `{% if d.remaining is not none %}` (receipt.html:253)
            #    ซึ่งบรรทัดบนนั้นเขียนสัญญาไว้เองว่า *"บิลเดอร์ตั้งคีย์นี้เป็น None เสมอ
            #    เมื่อไม่มีแนวคิดนี้ และ `is defined` บนคีย์ที่เป็น None จะเป็น True"*
            #    ⚠️ แต่โค้ดเดิม **ไม่ตั้งคีย์เลย** เมื่อไม่มี `collection_amount`
            #       ⇒ Jinja ได้ `Undefined` ซึ่ง `is not none` ตอบ **True**
            #       ⇒ เข้าสาขาแล้วระเบิดที่ `"{:,.2f}".format(Undefined)`
            #       ⇒ **TypeError ทั้งการเรนเดอร์** (ดาวน์โหลด PDF ได้ 500)
            #    🕳️ กับดักนี้ซ่อนอยู่ได้นานเพราะใบเสร็จ/ใบแจ้งหนี้ทุกใบผูกกับบิล ⇒
            #       มี `collection_amount` เสมอ · **ใบรับเงินล่วงหน้า (deposit) เป็น
            #       เอกสารชนิดแรกที่ไม่มีบิล** จึงเป็นใบแรกที่ตกหลุมนี้
            #    ⇒ ตั้งเป็น None ที่นี่เพื่อให้ตรงกับสัญญาที่เทมเพลตเขียนไว้
            "collection_amount": None,
            "remaining": None,
            "remaining_text": None,
            # 🗂️ คีย์ของการยุบ (F6/PR-4) — **ต้องถูกตั้งเสมอ** ด้วยเหตุผลเดียวกับสองตัวบน:
            #    เทมเพลตกันด้วย `{% if d.is_merged %}` ซึ่ง `Undefined` ตอบ False ให้ฟรี
            #    แต่ `{{ d.doc_no_text or d.receipt_no }}` บนคีย์ที่หายไปจะเงียบ ๆ ตกไป
            #    ใช้ `receipt_no` — ซึ่ง **เป็น None** สำหรับใบที่ถูกยุบ ⇒ หัวใบว่างเปล่า
            #    ⇒ ตั้งที่นี่ที่เดียว แล้ว `_merged_context` ค่อย override ทับ
            "is_merged": False,
            "doc_no_text": None,
            "doc_date_text": None,
            "merged_count": 0,
            "members": [],
            # ══ 💸 [F6] คีย์ของ **ใบสำคัญจ่าย** ══════════════════════════════════════
            # 🔴 ตั้ง **เสมอ ทุกใบ** (เป็น `None`/`[]` สำหรับชนิดอื่น) ตามสัญญาเดียวกับ
            #    `collection_amount`/`remaining` ข้างบน — partial อ้างคีย์เหล่านี้แบบไม่มี
            #    เงื่อนไข และ `"{:,.2f}".format(Undefined)` **ระเบิดเป็น TypeError = 500**
            #    (คีย์ที่หายไปเฉย ๆ เรนเดอร์ว่าง — พังเฉพาะเมื่อมี `format()` คร่อม)
            #
            # 🗂️ `body_template` = ทางแยกของเทมเพลต **ไม่ใช่ `is_receipt`**
            #    🔴 ทำไมไม่เพิ่มสาขาที่สามใน `_receipt_body.html`: ไฟล์นั้น branch ด้วย
            #       `is_receipt` ราว 8 จุด ทุกจุดเป็น "ใบเสร็จ หรือ ใบแจ้งหนี้" ⇒ เพิ่มชนิด
            #       ที่สาม = ทุกจุดกลายเป็นสามทาง และ **ลืมจุดเดียว = พิมพ์ "เรียกเก็บจาก" /
            #       "ยอดค้างชำระ" บนใบสำคัญจ่ายโดยไม่มี error ฟ้อง** (กับดักที่บันทึกไว้ใน
            #       `docs/skills.md`) ⇒ แยกไฟล์แล้ว **ไม่มี `is_receipt` อยู่ในเส้นทางของ
            #       ใบสำคัญเลย** จึงไม่มีอะไรให้ลืม
            #    ⚠️ เป็น `{% include %}` ไม่ใช่ shell ที่สอง: ผู้ใช้ติ๊กใบเสร็จปนกับใบสำคัญ
            #       ในคำขอเดียวได้ และทั้งไฟล์ถูกเรนเดอร์ครั้งเดียวผ่าน Gotenberg ⇒ `<style>`
            #       (ฟอนต์ base64 ~61,000 ตัวอักษร) ต้องอยู่นอกลูปเสมอ
            "body_template": (
                _VOUCHER_BODY_TEMPLATE
                if d["doc_type"] == DOC_TYPE_PAYMENT_VOUCHER
                else _RECEIPT_BODY_TEMPLATE
            ),
            # 🧑💼 ผู้เบิก/ผู้รับเงิน — ใช้ `issued_to_name` ตรง ๆ **ไม่เก็บซ้ำใน snapshot**
            #    เพราะ `finance_receipts.issued_to_name` *คือ* "คนที่เอกสารออกให้" อยู่แล้ว
            "voucher_payee_name": d.get("issued_to_name"),
            "voucher_approver_name": d.get("approver_name"),
            "voucher_attachment_count": int(d.get("attachment_count") or 0),
            "voucher_account_name": d.get("account_name"),
            # 🏦 ข้อความช่องทางจ่ายถูกประกอบที่นี่ (ไม่ใช่ในเทมเพลต) — ตรรกะ "มีธนาคาร
            #    หรือไม่มี" ต้องตอบเหมือนกันทุกที่ และเทมเพลตไม่ควรมี `if` ซ้อนสามชั้น
            "voucher_channel_text": cls._voucher_channel_text(d),
            "voucher_category_name": d.get("category_name"),
            "voucher_budgets": cls._voucher_budget_rows(d),
        }
        collection_amount = d.get("collection_amount")
        if collection_amount:
            remaining = float(collection_amount) - paid_total
            context["collection_amount"] = float(collection_amount)
            context["remaining"] = remaining
            context["remaining_text"] = baht_text(remaining)
        return context

    # ============================================================ ยุบเป็นหน้าเดียว
    @staticmethod
    def _merged_item_title(d: dict) -> str:
        """ชื่อ "รายการ" ของบรรทัดหนึ่งในใบที่ถูกยุบ — คู่กับสาขา `{% else %}` ของ receipt.html

        ⚠️ ถ้อยคำต้องตรงกับที่เทมเพลตพิมพ์ให้ **ใบเดี่ยว** เป๊ะ ไม่งั้นใบเสร็จใบเดียวกัน
           จะบอก "รายการ" ไม่เหมือนกันแล้วแต่ดาวน์โหลดมาทีละใบหรือรวมทีละสาม
           (แก้ที่เทมเพลตเมื่อไร ต้องแก้ที่นี่ด้วย — ทั้งคู่มีคอมเมนต์ชี้หากัน)
        """
        if d.get("collection_title"):
            return d["collection_title"]
        if d.get("doc_type") == DOC_TYPE_DEPOSIT:
            return "รับเงินล่วงหน้า (ยังไม่หักปิดบิลใด)"
        return "รายการชำระเงิน"

    @classmethod
    def _merge_key(cls, d: dict):
        """คีย์การยุบของเอกสารหนึ่งใบ — `None` = **ห้ามยุบ** (ได้หน้าของตัวเองเสมอ)

        🔴 `student_id` คือ "คนเดียวกัน" — **ห้ามใช้ `issued_to_name` เด็ดขาด**: มันเป็น
           สตริง snapshot จาก `_display_name` (ชื่อเล่นเปลี่ยนได้) และนักเรียนสองคนในห้อง
           เดียวกันชื่อซ้ำกันได้จริง ("ไอซ์") ⇒ ใบเสร็จของเด็กสองคนจะถูกยุบรวมเป็นกระดาษ
           ใบเดียวที่ผู้ปกครองคนหนึ่งถือเลขใบเสร็จของอีกบ้านปนอยู่ด้วย

        🔴 `student_id IS NULL` → ห้ามยุบ: คอลัมน์เป็น `ON DELETE SET NULL` ⇒ ใบของ
           นักเรียนที่ถูกลบทุกใบ (ของทุกคน) กลายเป็น NULL พร้อมกัน แล้วจะยุบรวมกันหมด
           เป็นหน้าเดียวที่ไม่มีใครเป็นเจ้าของ

        🚫 `event_at` **ไม่อยู่ในคีย์** โดยเจตนา: ผู้ใช้เลือกรูปแบบ "รวม N ฉบับ + ช่วงวันที่"
           ⇒ ยุบข้ามวันได้ และหัวใบพิมพ์ **ช่วง** วันที่ ไม่ใช่โกหกว่าทุกใบอยู่วันเดียวกัน
           (แต่ละบรรทัดมีวันที่ของตัวเองอยู่แล้ว)

        ⚠️ `status` **อยู่**ในคีย์: ใบที่ถูกยกเลิกมีแบนเนอร์ของตัวเองซึ่งวางไว้บนสุดของ
           **หน้า** ไม่ใช่บนสุดของ **บรรทัด** ⇒ ถ้ายุบปนกับใบที่ยังใช้ได้ ใบที่ยกเลิก
           จะอ่านเหมือนใบปกติทั้งที่เงินส่วนนั้นถูกคืนไปแล้ว
        """
        if d.get("doc_type") not in _MERGEABLE_DOC_TYPES:
            return None
        if d.get("student_id") is None:
            return None
        return (d["student_id"], d["doc_type"], d.get("status"))

    @classmethod
    def _merged_context(cls, group: list) -> dict:
        """กลุ่มเอกสาร (≥2 ใบ คีย์เดียวกัน) → context ของ **หน้าเดียวที่มีหลายบรรทัด**

        🔴 ใช้ context ของสมาชิกตัวแรกเป็น **ฐาน** ไม่ประกอบ dict ใหม่เอง — ได้คีย์ครบ
           ทุกตัวตามสัญญาที่ `_document_context` เขียนไว้โดยอัตโนมัติ และคีย์ที่เพิ่มใน
           อนาคตก็ไหลมาที่นี่ฟรี ⇒ ไม่มีทางที่ partial จะได้ `Undefined` ไปเรียก
           `"{:,.2f}".format()` แล้วระเบิดเป็น 500
        """
        ctx = cls._document_context(group[0])

        members = []
        for d in group:
            members.append({
                "receipt_no": d["receipt_no"],
                "title": cls._merged_item_title(d),
                "amount": float(d["amount"]),
                # 🗓️ วันที่ **ของบรรทัดนั้น** — มาจาก `event_at` เหมือนหัวใบของใบเดี่ยว
                "date_text": cls._thai_day_text(d.get("event_at") or d.get("issued_at")),
            })

        # 💰 ผลบวกของ **ค่าที่เก็บไว้ตอนออกเอกสาร** — ไม่ recompute จากบิล/แคมเปญ
        #    (ใบที่ถูกยกเลิกกลางทางยังมียอดเดิมบนกระดาษ ⇒ ผลรวมต้องตรงกับที่ตาเห็น)
        total = round(sum(m["amount"] for m in members), 2)

        # 🗓️ ช่วงวันที่บนหัวใบ — เทียบสตริงได้เพราะรูปแบบเดียวกันทั้งหมด ("15 ต.ค. 2569")
        #    ⚠️ วันเดียวทั้งกลุ่ม → พิมพ์วันเดียว ไม่พิมพ์ "X – X" ที่อ่านเหมือนข้อมูลหาย
        days = [m["date_text"] for m in members if m["date_text"]]
        if not days:
            span = None
        elif len(set(days)) == 1:
            span = days[0]
        else:
            span = f"{days[0]} – {days[-1]}"

        ctx.update({
            "is_merged": True,
            "merged_count": len(members),
            "members": members,
            # 🏷️ หัวใบ: "รวม N ฉบับ" แทนเลขที่ — ใบที่ยุบ **ไม่มี** เลขที่เดียว
            #    (ทุกเลขอยู่ครบในคอลัมน์ "เลขที่" ของตารางด้านล่าง)
            "doc_no_text": f"รวม {len(members)} ฉบับ",
            "doc_date_text": span,
            "receipt_no": None,
            "amount": total,
            "amount_text": baht_text(total),
            # 🔴 ปิดทุกอย่างที่เป็นแนวคิด **ต่อบิล** — ใบที่ยุบไม่มีสิ่งนี้
            #    เหตุผลเชิงความหมาย: ใบเสร็จ 3 ใบของนักเรียนคนหนึ่งอาจมาจาก 3 แคมเปญ
            #    ⇒ ไม่มี "ยอดเต็มของรายการ" เดียว และไม่มี "ยอดสะสมที่ชำระแล้ว" ที่มี
            #      ความหมาย ⇒ หน้าที่ยุบพิมพ์เฉพาะตารางสมาชิก + ยอดรวม
            #    ⚠️ `paid_total_after = None` **บังคับ ไม่ใช่ความสวย**: receipt.html
            #       พิมพ์ `"{:,.2f}".format(d.paid_total_after)` ⇒ ถ้าไม่ปิด และเทมเพลต
            #       ไม่กันด้วย `{% if not d.is_merged %}` จะได้ TypeError = 500 ทุกครั้ง
            "paid_total_after": None,
            "paid_total_after_text": None,
            "collection_amount": None,
            "collection_title": None,
            "collection_due_date": None,
            "remaining": None,
            "remaining_text": None,
            # 🚫 `line_items` ไม่ถูกยุบ — คอลัมน์นั้นถูกเขียนโดย `_issue_invoice_aggregate`
            #    เท่านั้น (doc_type='invoice') ซึ่งไม่อยู่ใน `_MERGEABLE_DOC_TYPES`
            #    ⇒ ไม่มีข้อมูลจริงถูกทิ้งที่นี่
            "line_items": None,
            "line_items_hidden": 0,
        })
        return ctx

    @classmethod
    def _document_contexts(cls, docs: list) -> list:
        """ลิสต์เอกสารที่ shape แล้ว → ลิสต์ context **สำหรับการเรนเดอร์ไฟล์รวม**

        🎯 ผู้ใช้เลือก 3 ใบของผู้ปกครองคนเดียวกัน → ได้กระดาษ **1 หน้า 3 บรรทัด**
           แต่ละบรรทัดมีเลขที่ของตัวเอง + ยอดรวมเดียวเป็นตัวอักษร

        🔴 เรียกจาก `_render_documents_pdf` **ที่เดียว** · `render_receipt_pdf` (ใบเดียว)
           เรียก `_document_context` ตรง ๆ — **ห้ามเปลี่ยนมาเรียกตัวนี้**: URL ของใบเดียว
           ระบุเอกสารหนึ่งใบ ถ้ามันไปตามหา "พี่น้อง" มาพิมพ์รวม กระดาษที่ได้จะมีเลขของ
           เอกสารที่ URL ไม่ได้ขอ ⇒ เลขใน URL ไม่ใช่เลขบนหัวกระดาษ

        ⚠️ การยุบ **เรียงลำดับใหม่** เมื่อผู้ใช้เลือกสลับคน (A1, B1, A2 → A1, A2, B1)
           เป็นธรรมชาติของการจัดกลุ่ม และไม่ทำให้ยอด/เลขใดหายไป
        """
        # bucket ถูกสร้างตอนเจอสมาชิกตัวแรก ⇒ ลำดับหน้า = ลำดับที่ผู้ใช้เห็นบนจอ
        order, buckets = [], {}
        for d in docs:
            key = cls._merge_key(d)
            if key is None:
                order.append(("doc", d))
                continue
            if key not in buckets:
                buckets[key] = []
                order.append(("group", buckets[key]))
            buckets[key].append(d)

        contexts = []
        for kind, payload in order:
            if kind == "doc":
                contexts.append(cls._document_context(payload))
            elif len(payload) == 1:
                # 🔑 กลุ่มขนาด 1 = เอกสารเดี่ยว ⇒ **ต้องได้ context เหมือนเดิมทุกไบต์**
                #    ไม่งั้น "โหลดทีละใบ" กับ "โหลดรวม" จะได้กระดาษคนละแบบโดยไม่มีใครรู้
                contexts.append(cls._document_context(payload[0]))
            elif len(payload) > _MAX_MERGED_MEMBERS:
                # ✂️ เกินเพดาน ⇒ แยกเป็น N หน้า **ไม่ตัดบรรทัดทิ้ง** (เหตุผลอยู่ที่ค่าคงที่)
                contexts.extend(cls._document_context(m) for m in payload)
            else:
                contexts.append(cls._merged_context(payload))
        return contexts

    @classmethod
    async def render_receipt_pdf(
        cls, pool: asyncpg.Pool, receipt_no: str, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> tuple:
        """เรนเดอร์เอกสาร **1 ใบ** เป็น PDF → คืน (bytes, filename)

        อ่านผ่าน `get_receipt` (ได้ require_member + audit มาแล้ว) แล้วประกอบ context
        ส่งให้ Gotenberg — ตัวเรียกใช้ httpx อยู่ใน `pdf.py`

        ♻️ ส่ง `include_voided=True`: ใบที่ถูกยกเลิกต้อง **พิมพ์ได้** เพื่อเป็นหลักฐานว่า
           "ใบนี้ถูกยกเลิกแล้ว" — ถ้าพิมพ์ไม่ได้ ต้นฉบับที่ลูกค้าถืออยู่จะกลายเป็นเอกสาร
           ที่ระบบปฏิเสธว่าตัวเองไม่เคยออก ซึ่งตรวจสอบย้อนหลังไม่ได้เลย
           ⇒ ปลอดภัยเพราะเทมเพลตประทับสถานะ "ยกเลิก" ลงบนกระดาษให้เอง
        """
        from .pdf import html_to_pdf, pdf_filename, render_receipt_html

        d = await cls.get_receipt(
            pool=pool, receipt_no=receipt_no, client_source=client_source,
            actor_identifier=actor_identifier, server_id=server_id, room_id=room_id, user_id=user_id,
            include_voided=True,
        )

        # ⏱️ ใบเดียวไม่ส่ง `timeout` — ใช้ค่า default 30.0
        #    ⚠️ ค่านี้ **สั้นกว่า** `--api-timeout` ของ Gotenberg (120s) โดยเจตนา: ใบเดียว
        #       เรนเดอร์เสร็จในไม่กี่วินาทีเสมอ ⇒ ถ้ารอถึง 30 วิแล้วยังไม่ได้ แปลว่ามีอะไรผิด
        #       ควรบอกผู้ใช้ก่อน ดีกว่ารอต่อ 2 นาที (ต่างจากไฟล์รวมที่ใช้ `PDF_BATCH_TIMEOUT`
        #       ซึ่ง **ต้องเท่า** กับ `--api-timeout` — ดูเหตุผลใน constants.py)
        html = render_receipt_html(cls._document_context(d))
        pdf_bytes = await html_to_pdf(html)
        return pdf_bytes, pdf_filename(d["receipt_no"], d["doc_type"])

    @classmethod
    async def render_documents_pdf(
        cls, pool: asyncpg.Pool, receipt_nos: List[str], client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_id: Optional[int] = None,
    ) -> tuple:
        """เรนเดอร์ **N ใบ** เป็น PDF ไฟล์เดียว (หน้าละใบ) → คืน (bytes, filename)

        🎯 ใช้ทั้ง "ดาวน์โหลดใบเสร็จที่เลือกจากทะเบียน" และ "ใบแจ้งหนี้ทั้งห้อง"
           ⇒ ครูได้ไฟล์เดียวที่พิมพ์แจกได้เลย ไม่ต้องกดโหลด 40 ครั้ง

        ⚠️ ต่างจาก `render_receipt_pdf` ตรง **ไม่เรียก `get_receipt` ต่อใบ**: N ใบ = N รอบ
           ของ (acquire + resolve_room_id + require_member + audit) ⇒ โหลด 100 ใบ
           จะเขียน audit 100 แถวและตรวจสิทธิ์ 100 ครั้งสำหรับการกระทำเดียว
           ที่นี่จึงโหลดด้วยคำสั่งเดียว และเขียน audit **แถวเดียวที่บอกทั้งชุด**

        🔒 เส้นทางนี้ **บังคับ `require_member` เสมอ** (ผู้ใช้เว็บ/บอทที่เป็นสมาชิกจริง)
        """
        return await cls._render_documents_pdf(
            pool, receipt_nos, client_source, actor_identifier,
            server_id=server_id, room_id=room_id, user_id=user_id,
            enforce_membership=True,
        )

    @classmethod
    async def render_documents_pdf_for_system(
        cls, pool: asyncpg.Pool, receipt_nos: List[str], client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> tuple:
        """🔓 เหมือน `render_documents_pdf` แต่ **ข้าม `require_member`** — สำหรับบอทระบบ

        🎯 **จุดเดียวในระบบที่ข้ามการตรวจสมาชิกของเส้นทาง PDF** (F5/PR-3) ⇒ มีเมธอดชื่อ
           เฉพาะเพื่อให้ **grep เจอ** และให้เทสต์ชี้เป้าได้ ดีกว่าซ่อนเป็นธง boolean ที่
           ผู้เรียกทั่วไปมองไม่เห็น (`enforce_membership=False` อยู่ลึกใน `_render_documents_pdf`)

        ⚠️ **ไม่ได้ลดความปลอดภัยลงเหลือศูนย์** — สิ่งที่ยังบังคับครบ:
           (1) ต้องมี `X-API-Key` ที่ถูกต้อง (ด่านที่ router) · (2) `resolve_room_id` ยัง
           แปลง server → room และ (3) **ด่านที่สำคัญที่สุดยังอยู่**: `WHERE R.room_id = $1
           AND R.receipt_no = ANY($2)` + `missing` ⇒ เลขของห้องอื่นได้ 404 ไม่ใช่ไฟล์
           ⇒ บอทอ่านได้เฉพาะเอกสารของห้องที่มันรู้จัก server_id อยู่แล้ว
           (บอทเรียก `/{target_id}` อยู่แล้วและได้ `announcement_channel_id` ของทุกห้อง)

        ⚠️ `user_id=None` ⇒ audit log ของการพิมพ์ชุดนี้จะบันทึก `user_id` เป็น NULL
           (เหมือน system RPC อื่นของบอท) — ตัวตนผู้ทำยังติดที่ `actor_identifier`
        """
        return await cls._render_documents_pdf(
            pool, receipt_nos, client_source, actor_identifier,
            server_id=server_id, room_id=room_id, user_id=None,
            enforce_membership=False,
        )

    @classmethod
    async def _render_documents_pdf(
        cls, pool: asyncpg.Pool, receipt_nos: List[str], client_source: str,
        actor_identifier: str, server_id: Optional[int] = None,
        room_id: Optional[int] = None, user_id: Optional[int] = None,
        enforce_membership: bool = True,
    ) -> tuple:
        """ตัวจริงที่ใช้ร่วมกันของสองเมธอดข้างบน — **ห้ามเรียกตรงจาก router**
        (ผู้เรียกต้องเลือกเองว่าจะตรวจสมาชิกหรือไม่ และการเลือกนั้นต้องอ่านออกจากชื่อเมธอด)
        """
        from .pdf import html_to_pdf, pdf_filename_batch, render_receipts_html

        start_time = time.time()
        target_room_id = room_id
        # dedupe **รักษาลำดับ** — เลขซ้ำ = หน้าซ้ำในไฟล์เดียว ⇒ คนนับหน้าแล้วได้ไม่ตรง
        # กับจำนวนคน ("หน้าละคน" กลายเป็นเท็จ) กันที่นี่ไม่ต้องพึ่ง frontend
        wanted = list(dict.fromkeys(receipt_nos or []))
        if not wanted:
            raise ValueError("ต้องเลือกเอกสารอย่างน้อย 1 ฉบับ")
        if len(wanted) > RECEIPTS_PER_PDF_MAX:
            # 🚧 เพดานนี้ผูกกับ **เวลาจัดหน้าของ Chromium** ไม่ใช่ขนาดไฟล์ — เกินแล้วคำขอ
            #    จะไปชน `PDF_BATCH_TIMEOUT` ⇒ ได้ 502 ที่ผู้ใช้อ่านไม่ออกว่าทำไม
            #    ⇒ ปฏิเสธตั้งแต่ต้นพร้อมบอกว่าให้ทำอย่างไรต่อ (500 ใบในทะเบียน = 5 รอบ)
            raise ValueError(
                f"รวมไฟล์ได้ครั้งละไม่เกิน {RECEIPTS_PER_PDF_MAX} ฉบับ "
                f"(เลือกมา {len(wanted)} ฉบับ) — กรุณาแบ่งดาวน์โหลดเป็นรอบละไม่เกิน "
                f"{RECEIPTS_PER_PDF_MAX} ฉบับ"
            )
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🔒 ด่านสมาชิก — `render_documents_pdf_for_system` เป็นผู้เรียกเดียวที่ปิดด่านนี้
                #    ⚠️ ห้ามเปลี่ยนเป็น `if user_id is not None` เด็ดขาด: `user_id=None` ต้อง
                #       **ไม่** หมายถึง "ข้าม" โดยปริยาย ไม่งั้น router ที่ลืมส่ง user_id
                #       จะกลายเป็นช่องอ่านข้ามห้องแบบเงียบ ๆ (เจตนาต้องอ่านออกจากชื่อเมธอด)
                if enforce_membership:
                    await require_member(conn, target_room_id, user_id)

                # 🚫 ไม่กรอง `deleted_at`/`status` เลย (เทียบเท่า `include_voided=True` ของ
                #    `render_receipt_pdf`) — ใบที่ถูกยกเลิกต้องพิมพ์ได้ และเทมเพลตประทับ
                #    "ยกเลิก" ให้เอง ไม่ใช่หายไปจากไฟล์รวมแบบเงียบ ๆ
                rows = await conn.fetch(f"""
                    SELECT {_RECEIPT_COLUMNS}, R.line_items, R.voucher_snapshot,
                           FC.title AS collection_title, FC.amount AS collection_amount,
                           FC.due_date AS collection_due_date,
                           S.student_no, R2.room_name, R2.room_code
                    FROM finance_receipts R
                    LEFT JOIN fee_collections FC ON R.collection_id = FC.id
                    LEFT JOIN students S ON R.student_id = S.id
                    JOIN rooms R2 ON R.room_id = R2.id
                    WHERE R.room_id = $1 AND R.receipt_no = ANY($2::text[])
                """, target_room_id, wanted)
                by_no = {r["receipt_no"]: r for r in rows}

                # 🔴 เลขที่ไม่พบ = 404 ทั้งคำขอ **ห้ามข้ามเงียบ ๆ**: ไฟล์ที่ขาดไปหนึ่งหน้า
                #    หน้าตาเหมือนไฟล์ที่พิมพ์ครบ ⇒ ครูแจกจ่ายไปแล้วและไม่มีทางรู้ว่าใครไม่ได้ใบ
                #    (บอกเลขที่ไม่พบได้ — เลขนั้นผู้ใช้ส่งมาเอง และคำตอบไม่ได้ยืนยันว่า
                #     เลขนั้นมีอยู่จริงที่ห้องอื่นหรือไม่)
                missing = [n for n in wanted if n not in by_no]
                if missing:
                    raise RoomNotFoundError(
                        "ไม่พบเอกสารเลขที่ " + ", ".join(missing) + " ในห้องนี้"
                    )

                # 🔁 เรียงตามลำดับที่ผู้ใช้เห็นบนจอ ไม่ใช่ตามที่ DB คืน (ชื่อไฟล์ก็ใช้ first/last
                #    ของลิสต์นี้ ⇒ ถ้าไม่เรียง ไฟล์จะชื่อ "ตัวแรก-ตัวสุดท้าย" ที่ไม่ตรงกับข้างใน)
                docs = [cls._shape_receipt_detail(by_no[n]) for n in wanted]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="PRINT_BATCH", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_RECEIPT", status="success",
                    new_values={"receipt_nos": wanted, "count": len(wanted)},
                    endpoint_or_command="FinanceService.render_documents_pdf",
                    execution_time_ms=exec_time,
                )
            # ⬅️ connection คืนเข้า pool **ก่อน** เรียก Chromium โดยเจตนา
            #    การเรนเดอร์กินเวลาเป็นวินาที และ pool มี 10 connection ต่อ replica
            #    ⇒ ถ้ายึดไว้ระหว่างเรนเดอร์ ไฟล์ 100 หน้าจะทำให้ **ทุก endpoint การเงิน
            #      ทั้งระบบ** (ของ replica นั้น) หยุดรอ ไม่ใช่แค่คำขอที่กำลังพิมพ์อยู่

            # 🗂️ `_document_contexts` จัดกลุ่มใบของ "คนเดียวกัน ชนิดเดียวกัน สถานะเดียวกัน"
            #    ให้อยู่หน้าเดียว — ใบเดี่ยวและกลุ่มขนาด 1 ได้ context เดิมทุกไบต์
            html = render_receipts_html(cls._document_contexts(docs))
            pdf_bytes = await html_to_pdf(html, timeout=PDF_BATCH_TIMEOUT)
            # 🏷️ ถ้าชุดนี้ปนสองชนิดเอกสาร ชื่อไฟล์ต้องไม่แอบอ้างว่าเป็นชนิดใดชนิดหนึ่ง
            #    (`pdf_filename_batch` แปลงชนิดที่ไม่รู้จักเป็น "documents" ให้เอง)
            doc_types = {d["doc_type"] for d in docs}
            return pdf_bytes, pdf_filename_batch(
                wanted, docs[0]["doc_type"] if len(doc_types) == 1 else "documents"
            )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="PRINT_BATCH", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_RECEIPT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.render_documents_pdf",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e
