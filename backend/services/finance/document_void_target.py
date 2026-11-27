"""🎯 ตัดสินว่าเอกสารในทะเบียน "ยกเลิกได้ด้วยอะไร" — บริสุทธิ์ ไม่แตะ DB

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องตัดสินฝั่ง backend
═══════════════════════════════════════════════════════════════════════════════
ทะเบียนรวมเอกสาร 8 ชนิดที่เกิดจากตารางคนละตาราง (finance_receipts / monthly_reports)
และเอกสารบางใบ "เป็นภาพสะท้อน" ของ record ต้นทางอีกที:

  REC/DEP ← payment_event หรือ legacy finance_transaction
  PV      ← expense voucher
  CERT    ← expense voucher (ยกเลิกพร้อม PV — ไม่มีทางยกเลิกเดี่ยว)
  INC     ← income batch

ถ้าให้ frontend เดาเอง มันจะเดาผิดทันทีที่ backend เพิ่มชนิด/เปลี่ยนความสัมพันธ์
⇒ ส่ง `void_target` มาพร้อมแถว แล้ว frontend แค่ dispatch ตาม `method`

🔴 กติกาที่ล็อกไว้ (มีเทสต์):
- เอกสารที่ `deleted` หรือ status ไม่ใช่ active ⇒ `None` (ยกเลิกซ้ำไม่ได้)
- REC/DEP ใช้ **payment_event ก่อน** legacy transaction — event คือเหตุการณ์จริง
- CERT **ห้าม fallback legacy** — CERT ถูกยกเลิกเฉพาะพร้อม PV
- RPT ใช้ life cycle `draft|final` (ไม่ใช่ `active`) และไม่มี `deleted_at`
"""
from typing import Any, Dict, Optional

from .constants import (
    DOC_STATUS_ACTIVE,
    DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_CERTIFICATE,
    DOC_TYPE_DEPOSIT,
    DOC_TYPE_INCOME,
    DOC_TYPE_INVOICE,
    DOC_TYPE_MONTHLY_REPORT,
    DOC_TYPE_PAYMENT_VOUCHER,
    DOC_TYPE_RECEIPT,
)

# สถานะของ RPT ที่ยังยกเลิกได้ — ต่างจากเอกสารใบอื่นที่ใช้ DOC_STATUS_ACTIVE
MONTHLY_REPORT_VOIDABLE_STATUSES = ("draft", "final")


def _target(
    method: str, entity_id: Optional[int] = None, receipt_no: Optional[str] = None
) -> Dict[str, Any]:
    return {"method": method, "id": entity_id, "receipt_no": receipt_no}


def resolve_void_target(
    *,
    doc_type: str,
    doc_id: int,
    status: str,
    doc_no: Optional[str] = None,
    deleted: bool = False,
    payment_event_id: Optional[int] = None,
    legacy_transaction_id: Optional[int] = None,
    voucher_id: Optional[int] = None,
    batch_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """คืน `{"method", "id", "receipt_no"}` หรือ `None` ถ้ายกเลิกจากทะเบียนไม่ได้

    ทุก id ที่ส่งเข้ามาเป็น `int | None` แล้ว (ผู้เรียกแปลงจาก jsonb มาก่อน)
    """
    if doc_type == DOC_TYPE_MONTHLY_REPORT:
        if status not in MONTHLY_REPORT_VOIDABLE_STATUSES:
            return None
        return _target("monthly_report", int(doc_id))

    if deleted or status != DOC_STATUS_ACTIVE:
        return None

    if doc_type == DOC_TYPE_INVOICE:
        return _target("invoice", int(doc_id))

    if doc_type in (DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT):
        # 🎯 event มาก่อน: ใบเสร็จ/ใบรับล่วงหน้าคือผลลัพธ์ของ "เหตุการณ์รับเงิน"
        if payment_event_id is not None:
            return _target("payment_event", int(payment_event_id))
        if legacy_transaction_id is not None:
            return _target("legacy_transaction", int(legacy_transaction_id))
        return None

    if doc_type == DOC_TYPE_PAYMENT_VOUCHER:
        if voucher_id is not None:
            return _target("expense_voucher", int(voucher_id))
        if legacy_transaction_id is not None:
            return _target("legacy_transaction", int(legacy_transaction_id))
        return None

    if doc_type == DOC_TYPE_CERTIFICATE:
        # 🔴 ไม่ fallback legacy โดยเจตนา — CERT ยกเลิกพร้อม PV เท่านั้น
        if voucher_id is not None:
            return _target("expense_voucher", int(voucher_id))
        return None

    if doc_type == DOC_TYPE_INCOME:
        if batch_id is not None:
            return _target("income_batch", int(batch_id))
        if legacy_transaction_id is not None:
            return _target("legacy_transaction", int(legacy_transaction_id))
        return None

    if doc_type == DOC_TYPE_ACKNOWLEDGEMENT:
        # ACK ระบุด้วยเลขเอกสาร (endpoint เดิมรับ `receipt_no`)
        if doc_no:
            return _target("acknowledgement", receipt_no=str(doc_no))
        return None

    return None
