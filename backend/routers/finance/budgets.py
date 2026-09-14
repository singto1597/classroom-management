"""งบประมาณรายหมวด/รายงวด (finance_budgets) — F2

⚠️ ลำดับการประกาศ route สำคัญ: `/finance/budgets/overview` **ต้องมาก่อน** route ที่มี
   path param ในตำแหน่งเดียวกัน ถ้าวันหนึ่งมีคนเพิ่ม `GET /finance/budgets/{budget_id}`
   แล้ววางไว้ข้างบน FastAPI จะ match "overview" เข้ากับ `{budget_id}` แล้วได้ 422
   (ปัจจุบันยังไม่มี route นั้น — กันไว้ก่อนเพราะเป็นกับดักที่แก้ยากตอนเจอ)

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — ดู `routers/_common.py`
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
import asyncpg
from typing import List, Optional

from models.finance_schemas import *
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import RoomNotFoundError, ForbiddenError
from services.finance_service import FinanceService

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


@router.post("/{target_id}/finance/budgets", response_model=SuccessResponse)
async def create_budget(
    req: BudgetCreate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.create_budget(
            pool=pool, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/budgets/overview", response_model=BudgetOverviewResponse)
async def get_budget_overview(
    request: Request,
    start_date: date = Query(..., description="วันเริ่มช่วงที่ดู (ค.ศ.)"),
    end_date: date = Query(..., description="วันสิ้นสุดช่วงที่ดู (ค.ศ.)"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_budget_overview(
            pool=pool, client_source=client_source, actor_identifier=actor,
            start_date=start_date, end_date=end_date,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{target_id}/finance/budgets", response_model=List[BudgetResponse])
async def get_budgets(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    category_type: Optional[str] = Query(None, pattern="^(income|expense)$"),
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.get_budgets(
            pool=pool, client_source=client_source, actor_identifier=actor,
            start_date=start_date, end_date=end_date, category_type=category_type,
            server_id=target.server_id, room_id=target.room_id,
            user_id=user_ctx["user_id"],
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{target_id}/finance/budgets/{budget_id}", response_model=SuccessResponse)
async def update_budget(
    budget_id: int,
    req: BudgetUpdate,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await FinanceService.update_budget(
            pool=pool, budget_id=budget_id, req=req, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{target_id}/finance/budgets/{budget_id}", response_model=SuccessResponse)
async def delete_budget(
    budget_id: int,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    req: Optional[ActionWithUserRequest] = Body(None),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        actor_name = req.user_name if req else "—"
        return await FinanceService.delete_budget(
            pool=pool, budget_id=budget_id, user_id=user_ctx["user_id"],
            client_source=client_source, actor_identifier=actor, user_name=actor_name,
            server_id=target.server_id, room_id=target.room_id,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
