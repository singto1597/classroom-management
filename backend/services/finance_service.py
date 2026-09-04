"""Re-export shim — โค้ดจริงถูกแยกไปที่ services/finance/ ตามความรับผิดชอบ

เก็บไฟล์นี้ไว้เพื่อให้ import path เดิม (``from services.finance_service import FinanceService``)
ของ routers / tests / scripts ยังทำงานได้โดยไม่ต้องแก้ไข.
"""
from services.finance import (
    FinanceService,
    CUTOFF_DATE,
    DEFAULT_INCOME_CATEGORIES,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_FINANCE_ACCOUNTS,
)

__all__ = [
    "FinanceService",
    "CUTOFF_DATE",
    "DEFAULT_INCOME_CATEGORIES",
    "DEFAULT_EXPENSE_CATEGORIES",
    "DEFAULT_FINANCE_ACCOUNTS",
]
