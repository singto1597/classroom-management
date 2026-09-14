"""Package routers.finance — แยก finance_router ตาม resource (accounts/categories/transactions/collections/reporting/export)."""
from fastapi import APIRouter

from .accounts import router as accounts_router
from .categories import router as categories_router
from .transactions import router as transactions_router
from .collections import router as collections_router
from .reporting import router as reporting_router
from .budgets import router as budgets_router
from .receipts import router as receipts_router
from .credits import router as credits_router
from .export import router as export_router

router = APIRouter()
router.include_router(reporting_router)
router.include_router(accounts_router)
router.include_router(transactions_router)
router.include_router(export_router)
router.include_router(collections_router)
router.include_router(categories_router)
router.include_router(budgets_router)
router.include_router(receipts_router)
# [F4] เงินรับล่วงหน้า — ประกาศ **หลัง** receipts โดยเจตนา: ทุก path ของกลุ่มนี้
# ขึ้นต้นด้วย `/finance/credits` ซึ่งไม่ซ้ำกับใคร ⇒ ลำดับไม่มีผล แต่การวางไว้ท้าย
# ทำให้ diff ของงานนี้ต่อเติมท้ายไฟล์ และไม่ตัดหน้า router ที่ deploy อยู่แล้ว
router.include_router(credits_router)

__all__ = ["router"]
