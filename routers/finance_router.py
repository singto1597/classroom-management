from fastapi import APIRouter, Body, Depends, HTTPException, Query, Header, Path
import asyncpg
from typing import List, Optional, Literal
from pydantic import BaseModel

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError, ForbiddenError
from services.finance_service import FinanceService

router = APIRouter()

class TargetResolution(BaseModel):
    server_id: Optional[int] = None
    room_id: Optional[int] = None

def get_target(
    target_id: int = Path(...),
    target_type: Literal["server", "room"] = Query("server", description="ระบุประเภทไอดีว่าเป็น server หรือ room")
) -> TargetResolution:
    return TargetResolution(
        server_id=target_id if target_type == "server" else None,
        room_id=target_id if target_type == "room" else None
    )

# ✨ API ใหม่: ดึงรายชื่อนักเรียนสำหรับสร้างแคมเปญ
@router.get("/{target_id}/finance/students", response_model=List[StudentBasicInfo])
async def get_active_students(
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_active_students(
            pool, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{target_id}/finance/accounts", response_model=SuccessResponse)
async def create_account(
    req: AccountCreate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.create_account(
            pool, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/accounts", response_model=List[AccountResponse])
async def get_accounts(
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_accounts(
            pool, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def update_account(
    account_id: int, 
    req: AccountUpdate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.update_account(
            pool, account_id, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.delete("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def delete_account(
    account_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.delete_account(
            pool, account_id, user_ctx["user_id"], actor, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/transactions", response_model=SuccessResponse)
async def add_transaction(
    req: TransactionCreate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.add_transaction(
            pool, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/transactions", response_model=TransactionListResponse)
async def get_transactions(
    filters: TransactionFilter = Depends(), 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_transactions(
            pool, 
            limit=filters.limit, 
            offset=filters.offset, 
            start_date=filters.start_date, 
            end_date=filters.end_date, 
            account_id=filters.account_id, 
            category_id=filters.category_id, 
            transaction_type=filters.transaction_type,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{target_id}/finance/transfer", response_model=SuccessResponse)
async def transfer_money(
    req: TransferCreate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.transfer_money(
            pool, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e: 
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/collections", response_model=SuccessResponse)
async def create_fee_collection(
    req: FeeCollectionCreate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.create_fee_collection(
            pool, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{target_id}/finance/payments/{payment_id}/pay", response_model=SuccessResponse)
async def confirm_payment(
    payment_id: int, 
    req: PaymentConfirm, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.confirm_payment(
            pool, payment_id, req, server_id=target.server_id, room_id=target.room_id
        )
    except (RoomNotFoundError, PaymentNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/collections", response_model=List[FeeCollectionResponse])
async def get_all_collections(
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_all_collections(
            pool, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{target_id}/finance/collections/{collection_id}", response_model=SuccessResponse)
async def update_collection(
    collection_id: int, 
    req: FeeCollectionUpdate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.update_collection(
            pool, collection_id, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/collections/{collection_id}", response_model=CollectionStatusResponse)
async def get_collection_status(
    collection_id: int, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_collection_status(
            pool, collection_id, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{target_id}/finance/collections/{collection_id}/students/{student_id}", response_model=SuccessResponse)
async def add_student_to_collection(
    collection_id: int,
    student_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.add_student_to_collection(
            pool, collection_id, student_id, user_ctx["user_id"], actor, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ✨ API ใหม่: ลบรายชื่อคนออกจากแคมเปญ
@router.delete("/{target_id}/finance/collections/{collection_id}/students/{student_id}", response_model=SuccessResponse)
async def remove_student_from_collection(
    collection_id: int,
    student_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.remove_student_from_collection(
            pool, collection_id, student_id, user_ctx["user_id"], actor, server_id=target.server_id, room_id=target.room_id
        )
    except (RoomNotFoundError, PaymentNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/categories", response_model=SuccessResponse)
async def create_category(
    req: CategoryCreate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.create_category(
            pool, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/categories", response_model=List[CategoryResponse])
async def get_categories(
    cat_type: str = Query(None, description="income หรือ expense"), 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_categories(
            pool, cat_type, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{target_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def update_category(
    category_id: int, 
    req: CategoryUpdate, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.update_category(
            pool, category_id, req, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{target_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def delete_category(
    category_id: int,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        actor = req.user_name if req else "—"
        return await FinanceService.delete_category(
            pool, category_id, user_ctx["user_id"], actor, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/finance/transactions/{transaction_id}", response_model=SuccessResponse)
async def revert_transaction(
    transaction_id: int, 
    req: ActionWithUserRequest, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.revert_transaction(
            pool, transaction_id, req.user_name, user_ctx["user_id"], server_id=target.server_id, room_id=target.room_id
        )
    except (RoomNotFoundError, TransactionNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/summary", response_model=FinanceSummaryResponse)
async def get_summary(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_summary(
            pool, month, year, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
@router.get("/{target_id}/finance/students/{student_id}/debts", response_model=StudentDebtProfileResponse)
async def get_student_debts(
    student_id: int, 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_student_debts(
            pool, student_id, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {str(e)}")

@router.get("/{target_id}/finance/debtors", response_model=List[DebtorItem])
async def get_all_debtors(
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await FinanceService.get_all_debtors(
            pool, server_id=target.server_id, room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))