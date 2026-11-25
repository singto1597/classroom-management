"""Facade ที่รวมทุก mixin ของโมดูลการเงินเป็น FinanceService (public API เดิม)"""
from .base import BaseMixin
from .ledger import LedgerMixin
# 📒 เกณฑ์คงค้าง — วางติดกับ LedgerMixin เพราะพึ่ง `_resolve_*_ledger`/`_insert_journal_entry`
#    ของมันโดยตรง (ไม่มีชื่อฟังก์ชันชนกับ mixin อื่น)
from .accrual import AccrualMixin
from .accounts import AccountsMixin
from .categories import CategoriesMixin
from .transactions import TransactionsMixin
from .collections import CollectionsMixin
from .reporting import ReportingMixin
from .budgets import BudgetsMixin
from .receipts import ReceiptsMixin
from .receipt_batches import ReceiptBatchesMixin
from .credits import CreditsMixin
from .backfill import BackfillMixin
from .export import ExportMixin
# ⚖️ ค่าปรับ — `FineTypesMixin`/`FinesMixin` พึ่ง `_create_bills_with_accrual`,
#    `_post_bill_adjustment`, `_issue_fine_invoice`, `_void_invoice_for_payment`
#    (มาจาก Accrual/ReceiptsMixin) และวิธี MRO: mixin ที่ import ไว้บนสุดชนะ
#    ⇒ ทั้งสองวาง **ก่อน** Accrual/Receipts โดยไม่มีชื่อฟังก์ชันชนกันเลย
from .fine_types import FineTypesMixin
from .fines import FinesMixin
# 💸 คำขอยกเว้น/คืนเงิน — พึ่ง `_load_fine_for_update`/`_sync_fine_status`/
#    `_issue_fine_invoice`/`_void_invoice_for_payment` ของ Fines/Receipts
from .waivers import WaiversMixin
from .refunds import RefundsMixin
# 📊 รายงานผู้ค้างชำระ (aging) + สรุปค่าปรับ — อ่านอย่างเดียว ใช้ `_open_bill_predicate`
#    ของ AccrualMixin · วางตรงนี้ได้เพราะชื่อ (`get_receivables_aging`/`get_fine_summary`)
#    ไม่ชนกับ mixin ใด — ถ้าอนาคตมีชื่อชน ให้ย้ายมixin นี้ **ก่อน** ตัวที่ชน
from .receivables import ReceivablesMixin
# 📣 เตือนผู้ค้างชำระรายวัน (Phase 6) — ใช้ `_open_bill_predicate` (AccrualMixin) และ
#    `_get_room_server_id` (BaseMixin) ผ่าน MRO ของ FinanceService · ไม่มีชื่อฟังก์ชันชน
from .reminders import RemindersMixin
# ⏰ ค่าปรับจ่ายล่าช้าอัตโนมัติ (Phase 6.5) — ใช้ `_open_bill_predicate` (Accrual),
#    `_create_bills_with_accrual`, `_issue_fine_invoice` (Receipts), `_lock_room_money`
#    และ `notify_user` · ไม่มีชื่อชนกับ mixin ใด (`apply_late_fees` เป็นชื่อใหม่)
from .late_fees import LateFeesMixin
# 🧾 เรียกเก็บเงินเองรายบุคคล (Phase 6.5) — ใช้ `_create_bills_with_accrual` ผ่าน MRO
from .custom_charges import CustomChargesMixin
# 👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน + finance_settings — ไม่พึ่ง helper ของ
#    mixin ใด (ใช้ `resolve_room_id` จาก BaseMixin ผ่าน MRO) แต่วางก่อน Accrual/Ledger
#    ตามกติกา "mixin ใหม่วางก่อนตัวที่มันอาจพึ่ง" · P2.1+ อ่าน `default_receiver` จากที่นี่
from .people import PeopleMixin


class FinanceService(
    # ⚖️ ค่าปรับมาก่อนเสมอ — ชื่อฟังก์ชันไม่ชนกับ mixin ใด แต่การวางหน้ารับประกันว่า
    #    ถ้าวันหนึ่งมีชื่อชน (เช่น `update_fine`) ตัวค่าปรับจะชนะอย่างชัดเจน
    WaiversMixin,
    RefundsMixin,
    FinesMixin,
    FineTypesMixin,
    ReceivablesMixin,
    # 📣 วางติด ReceivablesMixin (ทั้งคู่อ่านอย่างเดียว/ไม่ชนชื่อ) — ถ้าอนาคตมีชื่อชน
    #    ให้ย้ายตัวที่ **ไม่ควรชนะ** ลงไปข้างล่าง (MRO: ตัวบนชนะ)
    RemindersMixin,
    # ⏰🧾 P6.5 — สองตัวนี้พึ่ง `_create_bills_with_accrual` (AccrualMixin) และ
    #    `_issue_fine_invoice` (ReceiptsMixin) ผ่าน MRO ⇒ วางไว้บนได้เหมือน mixin ค่าปรับ
    LateFeesMixin,
    CustomChargesMixin,
    ExportMixin,
    ReportingMixin,
    ReceiptsMixin,
    # 📚 วาง **หลัง** `ReceiptsMixin` โดยเจตนา: `ReceiptBatchesMixin` ไม่ได้ override
    #    ฟังก์ชันใดของ ReceiptsMixin (ชื่อไม่ชนกันเลย) ⇒ ลำดับไม่มีผลกับพฤติกรรม
    #    แต่การวางติดกันทำให้อ่านออกว่า "ชุดเอกสารเป็นเรื่องของทะเบียนเอกสาร"
    #    ⚠️ ห้ามย้าย `ReceiptsMixin` ไปหลัง mixin ที่พึ่ง `_shape_receipt*`/`_RECEIPT_COLUMNS`
    ReceiptBatchesMixin,
    CreditsMixin,
    BudgetsMixin,
    CollectionsMixin,
    TransactionsMixin,
    CategoriesMixin,
    AccountsMixin,
    BackfillMixin,
    # 👥 [FIN-V2 / P1.2] — อ่าน/เขียนทะเบียนผู้เกี่ยวข้อง + ตั้งค่าห้อง (ไม่มีชื่อชน)
    PeopleMixin,
    AccrualMixin,
    LedgerMixin,
    BaseMixin,
):
    """Service การเงินรวม — ประกอบจาก mixin ย่อยตามความรับผิดชอบ (ดู services/finance/*)"""
    pass
