from fastapi import APIRouter, Body, Depends, HTTPException, Query, Header
import asyncpg
from typing import List, Optional

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError, ForbiddenError
from services.finance_service import FinanceService

router = APIRouter()

@router.post("/{server_id}/finance/accounts", response_model=SuccessResponse)
async def create_account(
    server_id: int, 
    req: AccountCreate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.create_account(pool, server_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{server_id}/finance/accounts", response_model=List[AccountResponse])
async def get_accounts(
    server_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_accounts(pool, server_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{server_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def update_account(
    server_id: int, 
    account_id: int, 
    req: AccountUpdate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.update_account(pool, server_id, account_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.delete("/{server_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def delete_account(
    server_id: int,
    account_id: int,
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    discord_id: int = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.delete_account(pool, server_id, account_id, discord_id, actor)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{server_id}/finance/transactions", response_model=SuccessResponse)
async def add_transaction(
    server_id: int, 
    req: TransactionCreate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.add_transaction(pool, server_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{server_id}/finance/transactions", response_model=TransactionListResponse)
async def get_transactions(
    server_id: int, 
    filters: TransactionFilter = Depends(), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_transactions(
            pool, 
            server_id, 
            limit=filters.limit, 
            offset=filters.offset, 
            start_date=filters.start_date, 
            end_date=filters.end_date, 
            account_id=filters.account_id, 
            category_id=filters.category_id, 
            transaction_type=filters.transaction_type
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{server_id}/finance/transfer", response_model=SuccessResponse)
async def transfer_money(
    server_id: int, 
    req: TransferCreate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.transfer_money(pool, server_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e: 
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{server_id}/finance/collections", response_model=SuccessResponse)
async def create_fee_collection(
    server_id: int, 
    req: FeeCollectionCreate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.create_fee_collection(pool, server_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{server_id}/finance/payments/{payment_id}/pay", response_model=SuccessResponse)
async def confirm_payment(
    server_id: int, 
    payment_id: int, 
    req: PaymentConfirm, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.confirm_payment(pool, server_id, payment_id, req)
    except (RoomNotFoundError, PaymentNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{server_id}/finance/collections", response_model=List[FeeCollectionResponse])
async def get_all_collections(
    server_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_all_collections(pool, server_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{server_id}/finance/collections/{collection_id}", response_model=SuccessResponse)
async def update_collection(
    server_id: int, 
    collection_id: int, 
    req: FeeCollectionUpdate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.update_collection(pool, server_id, collection_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{server_id}/finance/collections/{collection_id}", response_model=CollectionStatusResponse)
async def get_collection_status(
    server_id: int, 
    collection_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_collection_status(pool, server_id, collection_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{server_id}/finance/collections/{collection_id}/students/{student_id}", response_model=SuccessResponse)
async def add_student_to_collection(
    server_id: int,
    collection_id: int,
    student_id: int,
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    discord_id: int = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.add_student_to_collection(
            pool, server_id, collection_id, student_id, discord_id, actor
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- หมวดหมู่ (Categories) ---
@router.post("/{server_id}/finance/categories", response_model=SuccessResponse)
async def create_category(
    server_id: int, 
    req: CategoryCreate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.create_category(pool, server_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{server_id}/finance/categories", response_model=List[CategoryResponse])
async def get_categories(
    server_id: int, 
    cat_type: str = Query(None, description="income หรือ expense"), 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_categories(pool, server_id, cat_type)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{server_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def update_category(
    server_id: int, 
    category_id: int, 
    req: CategoryUpdate, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.update_category(pool, server_id, category_id, req, discord_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{server_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def delete_category(
    server_id: int,
    category_id: int,
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    discord_id: int = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.delete_category(pool, server_id, category_id, discord_id, actor)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{server_id}/finance/transactions/{transaction_id}", response_model=SuccessResponse)
async def revert_transaction(
    server_id: int, 
    transaction_id: int, 
    req: ActionWithUserRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.revert_transaction(pool, server_id, transaction_id, req.user_name, discord_id)
    except (RoomNotFoundError, TransactionNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{server_id}/finance/summary", response_model=FinanceSummaryResponse)
async def get_summary(
    server_id: int, 
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_summary(pool, server_id, month, year)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
@router.get("/{server_id}/finance/students/{student_id}/debts", response_model=StudentDebtProfileResponse)
async def get_student_debts(
    server_id: int, 
    student_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    """
    ดึงรายการหนี้รายบุคคล สำหรับใช้ใน Modal จ่ายรวบยอด (Batch Payment)
    """
    try:
        return await FinanceService.get_student_debts(pool, server_id, student_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {str(e)}")



@router.get("/{server_id}/finance/debtors", response_model=List[DebtorItem])
async def get_all_debtors(
    server_id: int, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        return await FinanceService.get_all_debtors(pool, server_id)
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

