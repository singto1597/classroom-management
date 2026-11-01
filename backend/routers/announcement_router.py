"""HTTP layer ของประกาศ — list / create / get / patch / archive / read

🔒 อ่าน = สมาชิกห้อง (`require_member` ผ่าน service ชั้นล่างเมื่อสร้าง/แก้)
   เขียน/แก้/เก็บถาวร = `MANAGE_CLASSROOM_SETTINGS` (ตรวจใน service ในทรานแซกชัน
   เดียวกับ mutation — ไม่ใช่เช็คใน router แล้วปล่อยให้ service ไม่เช็ค)
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import AnnouncementNotFoundError, ForbiddenError, RoomNotFoundError
from core.rbac import require_member
from models.announcement_schemas import (
    AnnouncementCreate,
    AnnouncementCreateResponse,
    AnnouncementItem,
    AnnouncementListResponse,
    AnnouncementUpdate,
    MarkAnnouncementReadResponse,
)
from routers._common import get_audit_context
from services import announcement_service, notification_service

router = APIRouter()


def _to_item(row: asyncpg.Record) -> AnnouncementItem:
    return AnnouncementItem(**dict(row))


async def _require_member(pool: asyncpg.Pool, room_id: int, user_id: int) -> None:
    async with pool.acquire() as conn:
        await require_member(conn, room_id, user_id)


@router.get(
    "/{target_id}/announcements",
    response_model=AnnouncementListResponse,
    summary="ประกาศของห้อง (ปักหมุด + ใหม่สุดก่อน, แบ่งหน้าด้วย before_id)",
)
async def list_announcements(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    limit: int = Query(
        notification_service.DEFAULT_PAGE_SIZE, ge=1, le=notification_service.MAX_PAGE_SIZE
    ),
    before_id: int | None = Query(None, ge=1, description="ดึงหน้าเก่ากว่านี้"),
    include_archived: bool = Query(False, description="รวมประกาศที่เก็บถาวรแล้ว"),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    pinned, rows, has_more = await announcement_service.list_announcements(
        pool,
        room_id=room_id,
        user_id=user_id,
        limit=limit,
        before_id=before_id,
        include_archived=include_archived,
    )
    return AnnouncementListResponse(
        pinned=[_to_item(row) for row in pinned],
        items=[_to_item(row) for row in rows],
        has_more=has_more,
    )


@router.post(
    "/{target_id}/announcements",
    response_model=AnnouncementCreateResponse,
    status_code=201,
    summary="ประกาศหนึ่งครั้ง → in-app + push + Discord (urgent เท่านั้นที่ @everyone)",
)
async def create_announcement(
    payload: AnnouncementCreate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        result = await announcement_service.create_announcement(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            title=payload.title,
            body=payload.body,
            priority=payload.priority,
            pinned=payload.pinned,
            client_source=client_source,
            actor_identifier=actor,
        )
    except RoomNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return AnnouncementCreateResponse(
        item=AnnouncementItem(**result["item"]),
        delivered_count=result["delivered_count"],
    )


@router.get(
    "/{target_id}/announcements/{announcement_id}",
    response_model=AnnouncementItem,
    summary="ประกาศใบเดียว (เปิดจาก deep link)",
)
async def get_announcement(
    announcement_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    try:
        row = await announcement_service.get_announcement(
            pool, room_id=room_id, user_id=user_id, announcement_id=announcement_id
        )
    except AnnouncementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_item(row)


@router.patch(
    "/{target_id}/announcements/{announcement_id}",
    response_model=AnnouncementItem,
    summary="แก้ประกาศ / ปักหมุด (ไม่สร้างแจ้งเตือนใหม่)",
)
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementUpdate,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        row = await announcement_service.update_announcement(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            announcement_id=announcement_id,
            changes=payload.model_dump(exclude_unset=True),
            client_source=client_source,
            actor_identifier=actor,
        )
    except AnnouncementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _to_item(row)


@router.post(
    "/{target_id}/announcements/{announcement_id}/archive",
    response_model=AnnouncementItem,
    summary="เก็บเข้าคลัง / เอากลับมา (idempotent)",
)
async def archive_announcement(
    announcement_id: int,
    request: Request,
    archived: bool = Query(True, description="false = เอากลับมาเป็นประกาศปกติ"),
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor = get_audit_context(request, user_ctx)
    try:
        row = await announcement_service.set_archived(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            announcement_id=announcement_id,
            archived=archived,
            client_source=client_source,
            actor_identifier=actor,
        )
    except AnnouncementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _to_item(row)


@router.post(
    "/{target_id}/announcements/{announcement_id}/read",
    response_model=MarkAnnouncementReadResponse,
    summary="ทำเครื่องหมายว่าอ่านแล้ว (อัปเดตแถวแจ้งเตือนของผู้ใช้เอง)",
)
async def mark_announcement_read(
    announcement_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    marked = await announcement_service.mark_read(
        pool, room_id=room_id, user_id=user_id, announcement_id=announcement_id
    )
    # ไม่ 404 เมื่อไม่มีแถวให้แตะ: "อ่านประกาศที่ไม่มีแจ้งเตือน" ไม่ใช่ความผิด
    # และการตอบ 404 จะเปิดช่องให้เดาได้ว่าประกาศ id ไหนมีจริงในห้องนี้
    return MarkAnnouncementReadResponse(announcement_id=announcement_id, marked=marked)
