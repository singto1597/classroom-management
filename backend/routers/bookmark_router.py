"""HTTP layer ของบุ๊กมาร์ก "บันทึกไว้" — P3.4

🔒 ทุก endpoint ผ่าน `require_member` ใน service (คนนอกห้องได้ 403)
🎯 `POST` ซ้ำ = 200 + `created: false` (ไม่ใช่ 201 ซ้ำ ๆ หรือ unique violation)
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import (
    ActivityNotFoundError,
    AnnouncementNotFoundError,
    BookmarkNotFoundError,
    ForbiddenError,
)
from models.bookmark_schemas import (
    BookmarkCreateRequest,
    BookmarkCreateResponse,
    BookmarkListResponse,
    BookmarkStateResponse,
)
from routers._common import get_audit_context
from services import bookmarks_service

router = APIRouter()


@router.get(
    "/{target_id}/bookmarks",
    response_model=BookmarkListResponse,
    summary="รายการที่ฉันบันทึกไว้ (ใหม่สุดก่อน, แบ่งหน้าด้วย cursor)",
)
async def list_my_bookmarks(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    entity_type: str | None = Query(None, description="กรองเฉพาะ announcement หรือ activity"),
    limit: int = Query(
        bookmarks_service.DEFAULT_PAGE_SIZE,
        ge=1,
        le=bookmarks_service.MAX_PAGE_SIZE,
        description="จำนวนรายการต่อหน้า",
    ),
    cursor: str | None = Query(None, description="cursor จาก next_cursor ของหน้าก่อน"),
):
    try:
        data = await bookmarks_service.list_bookmarks(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            entity_type=entity_type,
            limit=limit,
            cursor=cursor,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BookmarkListResponse(**data)


@router.post(
    "/{target_id}/bookmarks",
    response_model=BookmarkCreateResponse,
    status_code=201,
    summary="บันทึกไว้ (กดซ้ำได้ — 200 + created=false เมื่อมีอยู่แล้ว)",
)
async def create_bookmark(
    payload: BookmarkCreateRequest,
    request: Request,
    response: Response,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor_identifier = get_audit_context(request, user_ctx)
    try:
        data = await bookmarks_service.add_bookmark(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            actor_identifier=actor_identifier,
            client_source=client_source,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (AnnouncementNotFoundError, ActivityNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not data["created"]:
        # ไม่ได้สร้างใหม่ ⇒ 201 จะโกหก (และ client ที่ใช้ 201 ตัดสินว่าจะ "เด้งกลับ" จะเด้งผิด)
        response.status_code = 200
    return BookmarkCreateResponse(**data)


@router.delete(
    "/{target_id}/bookmarks/{bookmark_id}",
    status_code=204,
    summary="ยกเลิกการบันทึก (soft delete — กดบันทึกซ้ำได้)",
)
async def delete_bookmark(
    bookmark_id: int,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    client_source, actor_identifier = get_audit_context(request, user_ctx)
    try:
        await bookmarks_service.remove_bookmark(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            bookmark_id=bookmark_id,
            actor_identifier=actor_identifier,
            client_source=client_source,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except BookmarkNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/{target_id}/bookmarks/state",
    response_model=BookmarkStateResponse,
    summary="สถานะบุ๊กมาร์กของรายการหนึ่ง (สำหรับวาดไอคอนในหน้ารายละเอียด)",
)
async def get_bookmark_state(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    entity_type: str = Query(..., description="announcement หรือ activity"),
    entity_id: int = Query(..., ge=1),
):
    try:
        data = await bookmarks_service.get_bookmark_state(
            pool,
            room_id=room_id,
            user_id=int(user_ctx["user_id"]),
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return BookmarkStateResponse(**data)
