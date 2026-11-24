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


class FinanceService(
    # ⚖️ ค่าปรับมาก่อนเสมอ — ชื่อฟังก์ชันไม่ชนกับ mixin ใด แต่การวางหน้ารับประกันว่า
    #    ถ้าวันหนึ่งมีชื่อชน (เช่น `update_fine`) ตัวค่าปรับจะชนะอย่างชัดเจน
    WaiversMixin,
    RefundsMixin,
    FinesMixin,
    FineTypesMixin,
    ReceivablesMixin,
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
    AccrualMixin,
    LedgerMixin,
    BaseMixin,
):
    """Service การเงินรวม — ประกอบจาก mixin ย่อยตามความรับผิดชอบ (ดู services/finance/*)"""
    pass
