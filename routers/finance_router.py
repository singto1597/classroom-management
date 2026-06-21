from fastapi import APIRouter, Body, Depends, HTTPException, Query
import asyncpg
from typing import List, Optional

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user, resolve_target_to_room_id
from core.exceptions import PaymentNotFoundError, TransactionNotFoundError, ForbiddenError
from services.finance_service import FinanceService

router = APIRouter()

@router.post("/{target_id}/finance/accounts", response_model=SuccessResponse)
async def create_account(
    req: AccountCreate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.create_account(pool, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/accounts", response_model=List[AccountResponse])
async def get_accounts(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_accounts(pool, room_id=room_id)

@router.patch("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def update_account(
    account_id: int, 
    req: AccountUpdate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.update_account(pool, account_id, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.delete("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def delete_account(
    account_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.delete_account(pool, account_id, user_ctx["user_id"], actor, room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/transactions", response_model=SuccessResponse)
async def add_transaction(
    req: TransactionCreate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.add_transaction(pool, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/transactions", response_model=TransactionListResponse)
async def get_transactions(
    filters: TransactionFilter = Depends(), 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_transactions(
        pool, limit=filters.limit, offset=filters.offset, start_date=filters.start_date, 
        end_date=filters.end_date, account_id=filters.account_id, category_id=filters.category_id, 
        transaction_type=filters.transaction_type, room_id=room_id
    )

@router.post("/{target_id}/finance/transfer", response_model=SuccessResponse)
async def transfer_money(
    req: TransferCreate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.transfer_money(pool, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e: 
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/collections", response_model=SuccessResponse)
async def create_fee_collection(
    req: FeeCollectionCreate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.create_fee_collection(pool, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{target_id}/finance/payments/{payment_id}/pay", response_model=SuccessResponse)
async def confirm_payment(
    payment_id: int, 
    req: PaymentConfirm, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.confirm_payment(pool, payment_id, req, room_id=room_id)
    except PaymentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/collections", response_model=List[FeeCollectionResponse])
async def get_all_collections(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_all_collections(pool, room_id=room_id)

@router.put("/{target_id}/finance/collections/{collection_id}", response_model=SuccessResponse)
async def update_collection(
    collection_id: int, 
    req: FeeCollectionUpdate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.update_collection(pool, collection_id, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/collections/{collection_id}", response_model=CollectionStatusResponse)
async def get_collection_status(
    collection_id: int, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_collection_status(pool, collection_id, room_id=room_id)

@router.post("/{target_id}/finance/collections/{collection_id}/students/{student_id}", response_model=SuccessResponse)
async def add_student_to_collection(
    collection_id: int,
    student_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.add_student_to_collection(
            pool, collection_id, student_id, user_ctx["user_id"], actor, room_id=room_id
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/categories", response_model=SuccessResponse)
async def create_category(
    req: CategoryCreate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.create_category(pool, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/categories", response_model=List[CategoryResponse])
async def get_categories(
    cat_type: str = Query(None), 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_categories(pool, cat_type, room_id=room_id)

@router.patch("/{target_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def update_category(
    category_id: int, 
    req: CategoryUpdate, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.update_category(pool, category_id, req, user_ctx["user_id"], room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{target_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def delete_category(
    category_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.delete_category(pool, category_id, user_ctx["user_id"], actor, room_id=room_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/finance/transactions/{transaction_id}", response_model=SuccessResponse)
async def revert_transaction(
    transaction_id: int, 
    req: ActionWithUserRequest, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.revert_transaction(
            pool, transaction_id, req.user_name, user_ctx["user_id"], room_id=room_id
        )
    except TransactionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/summary", response_model=FinanceSummaryResponse)
async def get_summary(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_summary(pool, month, year, room_id=room_id)
    
@router.get("/{target_id}/finance/students/{student_id}/debts", response_model=StudentDebtProfileResponse)
async def get_student_debts(
    student_id: int, 
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_student_debts(pool, student_id, room_id=room_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {str(e)}")

@router.get("/{target_id}/finance/debtors", response_model=List[DebtorItem])
async def get_all_debtors(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    return await FinanceService.get_all_debtors(pool, room_id=room_id)