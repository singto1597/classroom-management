"""แคมเปญเก็บเงิน (fee_collections) + การชำระเงิน"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Header, Path, Request
from fastapi.responses import StreamingResponse
import asyncpg
from typing import List, Optional, Literal

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError, ForbiddenError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()

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
