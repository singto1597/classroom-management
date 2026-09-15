"""Facade ที่รวมทุก mixin ของโมดูลการเงินเป็น FinanceService (public API เดิม)"""
from .base import BaseMixin
from .ledger import LedgerMixin
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


class FinanceService(
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
    LedgerMixin,
    BaseMixin,
):
    """Service การเงินรวม — ประกอบจาก mixin ย่อยตามความรับผิดชอบ (ดู services/finance/*)"""
    pass
