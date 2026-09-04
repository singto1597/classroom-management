"""Package routers.finance — แยก finance_router ตาม resource (accounts/categories/transactions/collections/reporting/export)."""
from fastapi import APIRouter

from .accounts import router as accounts_router
from .categories import router as categories_router
from .transactions import router as transactions_router
from .collections import router as collections_router
from .reporting import router as reporting_router
from .export import router as export_router

router = APIRouter()
router.include_router(reporting_router)
router.include_router(accounts_router)
router.include_router(transactions_router)
router.include_router(export_router)
router.include_router(collections_router)
router.include_router(categories_router)

__all__ = ["router"]
