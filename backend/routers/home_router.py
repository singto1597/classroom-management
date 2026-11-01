"""HTTP layer ของหน้าหลัก + "ของฉัน" — P3

- `GET /{target_id}/home/summary` — สรุปหน้าหลักในคำขอเดียว (P3.1)
- `GET /{target_id}/me/activity` — ไทม์ไลน์ของฉัน (P3.3)
- `GET /{target_id}/me/stats` — สถิติของฉัน + ตัวเลขงานของห้อง (P3.3)

🔒 สมาชิกที่ใช้งานอยู่ในห้องเท่านั้น (`require_member` อยู่ใน service เรียบร้อย)
🎯 ตอบคำขอเดียว — ฝั่งหน้าไม่ต้องยิง tasks/activities/finance/announcements แยกกัน
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import (
    AcademicPeriodNotFoundError,
    ForbiddenError,
    ValidationError,
)
from models.home_schemas import HomeSummaryResponse
from models.me_schemas import MeActivityResponse, MeStatsResponse
from services import home_summary_service, me_activity_service

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


@router.get(
    "/{target_id}/me/activity",
    response_model=MeActivityResponse,
    summary="ไทม์ไลน์ของฉัน (จ่ายเงิน · เข้าร่วมกิจกรรม) — แบ่งหน้าด้วย cursor",
)
async def get_my_activity(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    limit: int = Query(
        me_activity_service.DEFAULT_PAGE_SIZE,
        ge=1,
        le=me_activity_service.MAX_PAGE_SIZE,
        description="จำนวนรายการต่อหน้า",
    ),
    cursor: str | None = Query(None, description="cursor จาก next_cursor ของหน้าก่อน"),
):
    try:
        data = await me_activity_service.list_activity(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            limit=limit,
            cursor=cursor,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        # cursor ผิดรูป = คำขอของผู้ใช้ ไม่ใช่บั๊กของเซิร์ฟเวอร์
        raise HTTPException(status_code=400, detail=str(exc))
    return MeActivityResponse(**data)


@router.get(
    "/{target_id}/me/stats",
    response_model=MeStatsResponse,
    summary="สถิติของฉัน (กิจกรรม · ชั่วโมง · จ่าย/ค้าง) + ตัวเลขงานของห้องเพื่อบริบท",
)
async def get_my_stats(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    year_id: int | None = Query(
        None, ge=1, description="กรองตามปีการศึกษา — ไม่ระบุ = ปีปัจจุบันของห้อง (ถ้ามี)"
    ),
    term_id: int | None = Query(None, ge=1, description="กรองตามเทอม — ต้องอยู่ในปีที่เลือก"),
):
    try:
        data = await me_activity_service.get_me_stats(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            year_id=year_id,
            term_id=term_id,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except AcademicPeriodNotFoundError as exc:
        # 🗓️ ปี/เทอมที่ขอถูกลบไปแล้วหรือไม่ใช่ของห้องนี้ ⇒ 404
        #    (หน้าจอจะได้บอก "ช่วงเวลานี้ไม่มีแล้ว" แทนการโชว์ตัวเลขทั้งหมดเงียบ ๆ)
        raise HTTPException(status_code=404, detail=str(exc))
    except ValidationError as exc:
        # เช่น เทอมที่เลือกไม่ได้อยู่ในปีที่เลือก ⇒ 400
        raise HTTPException(status_code=400, detail=str(exc))
    return MeStatsResponse(**data)
