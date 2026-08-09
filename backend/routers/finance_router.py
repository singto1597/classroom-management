from fastapi import APIRouter, Body, Depends, HTTPException, Query, Header, Path, Request
from fastapi.responses import StreamingResponse
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
    target_type: Literal["server", "room"] = Query("room", description="ระบุประเภทไอดีว่าเป็น server หรือ room (default=room สำหรับ web)")
) -> TargetResolution:
    return TargetResolution(
        server_id=target_id if target_type == "server" else None,
        room_id=target_id if target_type == "room" else None
    )

def get_audit_context(request: Request, user_ctx: dict = None) -> tuple[str, str]:
    client_source = request.headers.get("x-client-source", "WEB_APP")
    ip = request.client.host if request.client else "unknown"
    if user_ctx and "user_id" in user_ctx:
        actor_identifier = f"user_id:{user_ctx['user_id']}"
    else:
        actor_identifier = request.headers.get("x-actor-id", f"ip:{ip}")
    return client_source, actor_identifier


# --- SUMMARY ENDPOINT (แก้ไข response_model และการส่ง Parameter แล้ว) ---
@router.get("/{target_id}/finance/summary", response_model=FinanceSummaryResponse)
async def get_summary(
    request: Request,
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_summary(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            month=month,
            year=year,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- DOUBLE-ENTRY REPORTING (Phase 4) ---
@router.get("/{target_id}/finance/trial-balance")
async def get_trial_balance(
    request: Request,
    as_of_date: Optional[date] = Query(None, description="งบ ณ วันที่ (ไม่ระบุ = ทั้งหมดจนถึงตอนนี้)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_trial_balance(
            pool=pool,
            room_id=target.room_id,
            server_id=target.server_id,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx["user_id"],
            as_of_date=as_of_date
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{target_id}/finance/income-statement")
async def get_income_statement(
    request: Request,
    start_date: date = Query(..., description="วันที่เริ่มต้น"),
    end_date: date = Query(..., description="วันที่สิ้นสุด"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_income_statement(
            pool=pool,
            room_id=target.room_id,
            server_id=target.server_id,
            start_date=start_date,
            end_date=end_date,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/students", response_model=List[StudentBasicInfo])
async def get_active_students(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_active_students(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/finance/accounts", response_model=SuccessResponse)
async def create_account(
    req: AccountCreate, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_account(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/accounts", response_model=List[AccountResponse])
async def get_accounts(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_accounts(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.patch("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def update_account(
    account_id: int,
    req: AccountUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_account(
            pool=pool,
            account_id=account_id,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
@router.delete("/{target_id}/finance/accounts/{account_id}", response_model=SuccessResponse)
async def delete_account(
    account_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.delete_account(
            pool=pool,
            account_id=account_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
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
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.add_transaction(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/transactions", response_model=TransactionListResponse)
async def get_transactions(
    request: Request,
    filters: TransactionFilter = Depends(), 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_transactions(
            pool=pool,
            limit=filters.limit,
            offset=filters.offset,
            start_date=filters.start_date,
            end_date=filters.end_date,
            account_id=filters.account_id,
            category_id=filters.category_id,
            transaction_type=filters.transaction_type,
            server_id=target.server_id,
            room_id=target.room_id,
            client_source=client_source,
            actor_identifier=actor,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/finance/export")
async def export_transactions(
    req: FinanceExportRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        excel_file = await FinanceService.export_transactions_excel(
            pool=pool,
            req=req,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
        ref_id = target.server_id or target.room_id
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=finance_export_{ref_id}.xlsx"}
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
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.revert_transaction(
            pool=pool,
            transaction_id=transaction_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except (RoomNotFoundError, TransactionNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{target_id}/finance/transfer", response_model=SuccessResponse)
async def transfer_money(
    req: TransferCreate, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.transfer_money(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
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
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_fee_collection(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
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
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.confirm_payment(
            pool=pool,
            payment_id=payment_id,
            req=req,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except (RoomNotFoundError, PaymentNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ✨ รับเงินรวบยอด (Batch) — ปลดหนี้หลายรายการของนักเรียนคนเดียวกันในครั้งเดียว
# (yield notification เดียว ไม่เด้งหลาย embed) — เส้นทาง 4 segment ไม่ชน /payments/{id}/pay
@router.put("/{target_id}/finance/payments/batch", response_model=SuccessResponse)
async def batch_confirm_payments(
    req: BatchPaymentConfirm,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.batch_confirm_payments(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except (RoomNotFoundError, PaymentNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/collections", response_model=List[FeeCollectionResponse])
async def get_all_collections(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_all_collections(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{target_id}/finance/collections/{collection_id}", response_model=SuccessResponse)
async def update_collection(
    collection_id: int, 
    req: FeeCollectionUpdate, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_collection(
            pool=pool,
            collection_id=collection_id,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/collections/{collection_id}", response_model=CollectionStatusResponse)
async def get_collection_status(
    collection_id: int, 
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_collection_status(
            pool=pool,
            collection_id=collection_id,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/{target_id}/finance/collections/{collection_id}/students/{student_id}", response_model=SuccessResponse)
async def add_student_to_collection(
    collection_id: int,
    student_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.add_student_to_collection(
            pool=pool,
            collection_id=collection_id,
            student_id=student_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{target_id}/finance/collections/{collection_id}/students/{student_id}", response_model=SuccessResponse)
async def remove_student_from_collection(
    collection_id: int,
    student_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.remove_student_from_collection(
            pool=pool,
            collection_id=collection_id,
            student_id=student_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
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
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_category(
            pool=pool,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/categories", response_model=List[CategoryResponse])
async def get_categories(
    request: Request,
    cat_type: Optional[str] = Query(None, description="income หรือ expense"), 
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_categories(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            cat_type=cat_type,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.patch("/{target_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def update_category(
    category_id: int,
    req: CategoryUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_category(
            pool=pool,
            category_id=category_id,
            req=req,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{target_id}/finance/categories/{category_id}", response_model=SuccessResponse)
async def delete_category(
    category_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.delete_category(
            pool=pool,
            category_id=category_id,
            user_id=user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor,
            user_name=actor_name,
            server_id=target.server_id,
            room_id=target.room_id
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{target_id}/finance/debtors", response_model=List[DebtorItem])
async def get_all_debtors(
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_all_debtors(
            pool=pool,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{target_id}/finance/students/{student_id}/debts", response_model=StudentDebtProfileResponse)
async def get_student_debts(
    student_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_student_debts(
            pool=pool,
            student_id=student_id,
            client_source=client_source,
            actor_identifier=actor,
            server_id=target.server_id,
            room_id=target.room_id,
            user_id=user_ctx["user_id"]
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))