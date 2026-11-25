"""📜 [FIN-V2 / P3.4] ประวัติการรับเงิน — อ่านอย่างเดียว

⚠️ `{target_id}` คือ room_id (web) หรือ server_id (บอท) — แปลงด้วย
   `resolve_target_to_room_id` ก่อนเข้า service (service รับ `room_id` สุทธิ)

⚠️ สมาชิกห้องทุกคนอ่านได้ (`require_member` อยู่ใน service) — ไม่ต้อง
   `MANAGE_FINANCE` ตามหลัก transparency ของ finance GET

⚠️ error 400 = cursor/kind/limit ผิด, 403 = ไม่ใช่สมาชิก, 404 = ห้องไม่มี
"""
from datetime import date
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from core.dependencies import (
    get_current_user, get_db_pool, resolve_target_to_room_id,
)
from core.exceptions import ForbiddenError, RoomNotFoundError
from models.finance_schemas import PaymentHistoryResponse
from services.finance.payment_history import PaymentHistoryService

router = APIRouter()


def _raise_translated(e: Exception) -> None:
    """แปลง exception → HTTP status ตามกติกา routers (อ่าน: 400/403/404)"""
    if isinstance(e, RoomNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.get(
    "/{target_id}/finance/payment-history",
    response_model=PaymentHistoryResponse,
)
async def list_payment_history(
    date_from: Optional[date] = Query(None, alias="from", description="เริ่มช่วง (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, alias="to", description="สิ้นสุดช่วง (YYYY-MM-DD)"),
    kind: str = Query("all", description="all | event | handover"),
    student_id: Optional[int] = Query(None, description="กรองนักเรียน (ตัด handover)"),
    person_id: Optional[int] = Query(None, description="กรองผู้ถือเงินใน handover"),
    receiver_id: Optional[int] = Query(None, description="กรองผู้รับเงินของ event"),
    q: Optional[str] = Query(None, description="ค้นหาชื่อผู้จ่าย/ผู้รับ"),
    cursor: Optional[str] = Query(None, description="cursor ของหน้าถัดไป"),
    limit: int = Query(30, description="จำนวนต่อหน้า (1–100)"),
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    """ไทม์ไลน์เงินเข้า (event) + การส่งมอบเงินสด — เรียงใหม่→เก่า"""
    try:
        return await PaymentHistoryService.list_payment_history(
            pool=pool, room_id=room_id, user_id=user_ctx["user_id"],
            date_from=date_from, date_to=date_to, kind=kind,
            student_id=student_id, person_id=person_id, receiver_id=receiver_id,
            q=q, cursor=cursor, limit=limit,
        )
    except Exception as e:
        _raise_translated(e)
