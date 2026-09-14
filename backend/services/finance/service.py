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
from .backfill import BackfillMixin
from .export import ExportMixin


class FinanceService(
    ExportMixin,
    ReportingMixin,
    ReceiptsMixin,
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
