"""HTTP layer ของหน้าหลัก — `GET /{target_id}/home/summary` (P3)

🔒 สมาชิกที่ใช้งานอยู่ในห้องเท่านั้น (`require_member` อยู่ใน service เรียบร้อย)
🎯 ตอบคำขอเดียว — ฝั่งหน้าไม่ต้องยิง tasks/activities/finance/announcements แยกกัน
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import ForbiddenError
from models.home_schemas import HomeSummaryResponse
from services import home_summary_service

router = APIRouter()


@router.get(
    "/{target_id}/home/summary",
    response_model=HomeSummaryResponse,
    summary="สรุปหน้าหลักในคำขอเดียว (งาน · โน้ต · กิจกรรม · ยอดค้าง · ประกาศ · ตาราง)",
)
async def get_home_summary(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        data = await home_summary_service.build_home_summary(
            pool, room_id=room_id, user_id=int(user_ctx["user_id"])
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return HomeSummaryResponse(**data)
