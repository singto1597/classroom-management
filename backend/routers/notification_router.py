"""HTTP layer ของแจ้งเตือนในแอป — list / unread-count / read / read-all / stream (SSE)

🔒 ทุก endpoint ตรวจ "เป็นสมาชิกของห้องนี้จริง" (`require_member`) ก่อนเสมอ
เพราะ `user_id` อย่างเดียวไม่พอ: คนที่ถูกลบออกจากห้องแล้วแต่ยังถือ JWT
ต้องไม่เห็นแจ้งเตือนของห้องนั้นอีก

⚠️ `GET .../stream` ใช้ `Authorization` header ปกติ (ไม่อยากรับ token ใน query
เพราะจะไปโผล่ใน access log ของ nginx/Cloudflare) ⇒ ฝั่งเบราว์เซอร์ใช้
`fetch()` อ่าน stream แทน `EventSource` (ดู `frontend/src/services/notificationStream.ts`)
"""

from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from core.config import settings
from core.dependencies import get_current_user, get_db_pool, resolve_target_to_room_id
from core.exceptions import ForbiddenError
from core.rbac import require_member
from models.notification_schemas import (
    MarkAllReadResponse,
    MarkReadResponse,
    PreferenceItem,
    PreferenceListResponse,
    PreferenceUpdate,
    NotificationItem,
    NotificationListResponse,
    PushConfigResponse,
    PushSubscribeRequest,
    PushSubscriptionResponse,
    PushUnsubscribeRequest,
    PushUnsubscribeResponse,
    UnreadCountResponse,
)
from services import notification_service, push_service
from services.notification_stream import notification_stream

logger = logging.getLogger("API_NOTIFICATION_ROUTER")

router = APIRouter()

# ❤️ short probe ของ SSE — ต้องสั้นกว่าทุก timeout ที่อยู่ระหว่างทาง แต่ยาวพอ
# ไม่ให้ผู้ให้บริการ proxy ตัดการเชื่อมต่อที่ "เงียบ" (CF/Traefik ใช้ idle 100 วิ)
HEARTBEAT_SECONDS = 25


async def _require_member(pool: asyncpg.Pool, room_id: int, user_id: int) -> None:
    async with pool.acquire() as conn:
        await require_member(conn, room_id, user_id)


def _to_item(row: asyncpg.Record) -> NotificationItem:
    return NotificationItem(**dict(row))


@router.get(
    "/{target_id}/notifications",
    response_model=NotificationListResponse,
    summary="รายการแจ้งเตือนของผู้ใช้ในห้อง (ใหม่สุดก่อน, แบ่งหน้าด้วย before_id)",
)
async def list_notifications(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
    limit: int = Query(notification_service.DEFAULT_PAGE_SIZE, ge=1, le=notification_service.MAX_PAGE_SIZE),
    before_id: int | None = Query(None, ge=1, description="ดึงหน้าเก่ากว่านี้ (id ล่าสุดของหน้าก่อน)"),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    rows, unread, has_more = await notification_service.list_notifications(
        pool, room_id=room_id, user_id=user_id, limit=limit, before_id=before_id
    )
    return NotificationListResponse(
        items=[_to_item(row) for row in rows],
        unread_count=unread,
        has_more=has_more,
    )


@router.get(
    "/{target_id}/notifications/unread-count",
    response_model=UnreadCountResponse,
    summary="จำนวนแจ้งเตือนที่ยังไม่อ่าน (ตัวเลขเดียวกับที่ใช้ในรายการ)",
)
async def get_unread_count(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    async with pool.acquire() as conn:
        count = await notification_service.unread_count(conn, room_id=room_id, user_id=user_id)
    return UnreadCountResponse(unread_count=count)


@router.post(
    "/{target_id}/notifications/read-all",
    response_model=MarkAllReadResponse,
    summary="ทำเครื่องหมายว่าอ่านแล้วทั้งหมดของห้องนี้",
)
async def mark_all_read(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    marked = await notification_service.mark_all_read(pool, room_id=room_id, user_id=user_id)
    return MarkAllReadResponse(marked_count=marked)


@router.post(
    "/{target_id}/notifications/{notification_id}/read",
    response_model=MarkReadResponse,
    summary="ทำเครื่องหมายว่าอ่านแล้ว (ไม่สนใจว่าเคยอ่านแล้วหรือยัง)",
)
async def mark_read(
    notification_id: int,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    marked = await notification_service.mark_read(
        pool, room_id=room_id, user_id=user_id, notification_id=notification_id
    )
    # ไม่ 404: แจ้งเตือนของคนอื่น "ไม่มีอยู่สำหรับคุณ" — ตอบ 200 + marked=false
    # เพื่อไม่ให้เดาได้ว่า id นั้นมีจริงหรือไม่
    return MarkReadResponse(notification_id=notification_id, marked=marked)


@router.get(
    "/{target_id}/notifications/preferences",
    response_model=PreferenceListResponse,
    summary="สวิตช์เปิด/ปิดต่อกลุ่ม (คืนครบทุกกลุ่มเสมอ)",
)
async def get_preferences(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    # preference เป็นของผู้ใช้ ไม่ผูกห้อง — แต่ยังต้องเป็นสมาชิกของห้องที่ยิงมา
    try:
        await _require_member(pool, room_id, int(user_ctx["user_id"]))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    items = await notification_service.get_preferences(pool, user_id=int(user_ctx["user_id"]))
    return PreferenceListResponse(items=[PreferenceItem(**item) for item in items])


@router.put(
    "/{target_id}/notifications/preferences",
    response_model=PreferenceItem,
    summary="ตั้งสวิตช์ของกลุ่มหนึ่ง (ไม่รับ group=announcement)",
)
async def set_preference(
    payload: PreferenceUpdate,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        await _require_member(pool, room_id, int(user_ctx["user_id"]))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await notification_service.set_preference(
        pool,
        user_id=int(user_ctx["user_id"]),
        group_type=payload.group_type,
        inapp=payload.inapp,
        push=payload.push,
    )
    return PreferenceItem(group_type=payload.group_type, inapp=payload.inapp, push=payload.push)


# ── Web Push ────────────────────────────────────────────────────────────────
@router.get(
    "/{target_id}/notifications/push/config",
    response_model=PushConfigResponse,
    summary="คีย์สาธารณะ VAPID + เปิดใช้อยู่ไหม (หน้าเว็บใช้ตัดสินใจว่าจะโชว์ปุ่มไหม)",
)
async def get_push_config(
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    try:
        await _require_member(pool, room_id, int(user_ctx["user_id"]))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    enabled = push_service.push_enabled()
    return PushConfigResponse(
        public_key=settings.VAPID_PUBLIC_KEY if enabled else "",
        enabled=enabled,
    )


@router.post(
    "/{target_id}/notifications/push/subscribe",
    response_model=PushSubscriptionResponse,
    summary="ลงทะเบียนอุปกรณ์รับ push (endpoint ซ้ำ = ย้ายเจ้าของเครื่อง ไม่สร้างแถวใหม่)",
)
async def subscribe_push(
    payload: PushSubscribeRequest,
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not push_service.push_enabled():
        # ไม่ใช่ความผิดของผู้ใช้ — บอกตรง ๆ ว่าผู้ดูแลยังไม่ได้ตั้งระบบ
        raise HTTPException(status_code=503, detail="ระบบแจ้งเตือนบนอุปกรณ์ยังไม่เปิดใช้งาน")

    subscription_id = await push_service.save_subscription(
        pool,
        user_id=user_id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_agent=request.headers.get("user-agent"),
    )
    return PushSubscriptionResponse(subscription_id=subscription_id, endpoint=payload.endpoint)


@router.post(
    "/{target_id}/notifications/push/unsubscribe",
    response_model=PushUnsubscribeResponse,
    summary="เลิกสมัครของอุปกรณ์นี้ (เฉพาะอุปกรณ์ของผู้เรียกเอง)",
)
async def unsubscribe_push(
    payload: PushUnsubscribeRequest,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    removed = await push_service.delete_subscription(
        pool, user_id=user_id, endpoint=payload.endpoint
    )
    return PushUnsubscribeResponse(removed=removed)


@router.get(
    "/{target_id}/notifications/stream",
    summary="สตรีมแจ้งเตือนสด (SSE) — ส่งเฉพาะสัญญาณว่ามีของใหม่",
    response_class=StreamingResponse,
)
async def stream_notifications(
    request: Request,
    room_id: int = Depends(resolve_target_to_room_id),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user),
):
    user_id = int(user_ctx["user_id"])
    try:
        await _require_member(pool, room_id, user_id)
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    queue = notification_stream.subscribe(user_id)

    async def event_generator():
        try:
            # ทักทันที ⇒ client รู้ว่า "ต่อติดแล้ว" ไม่ใช่ค้างเงียบจนต้องรอ 25 วิ
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # comment frame (ขึ้นต้นด้วย :) — client ไม่ต้องตีความ
                    yield ": ping\n\n"
                    continue
                yield f"event: notification\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            notification_stream.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # ห้ามแคช: ถ้า CF/nginx เก็บ response นี้ไว้ ผู้ใช้คนอื่นจะได้สตรีมของคนก่อน
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # nginx: ปิด buffering ไม่งั้น event จะค้างในบัฟเฟอร์จนครบชุด
            "X-Accel-Buffering": "no",
        },
    )
