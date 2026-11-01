"""ประกาศของห้อง — ทางเดียวที่ "ประกาศหนึ่งครั้ง" ไปถึงครบทุกช่องทาง

═══════════════════════════════════════════════════════════════════════════════
📣 เดิม vs ใหม่
═══════════════════════════════════════════════════════════════════════════════
เดิม: หน้าเว็บ ➜ `ActionService.notify_custom_message` ➜ Redis ➜ Discord เท่านั้น
      ⇒ คนที่ไม่ได้อยู่หน้า Discord ไม่เคยเห็นประกาศ และไม่มีที่ให้ย้อนอ่าน

ใหม่: `create_announcement()` เขียนแถว `announcements` + แจ้งเตือนทั้งห้อง
      **ในทรานแซกชันเดียวกัน** ⇒ ประกาศมีที่เก็บถาวร มีอ่านแล้ว มีปักหมุด
      และ trigger `trg_notifications_fanout` พาไปถึง SSE + push ให้เอง
      จากนั้น (หลัง commit เท่านั้น) ค่อย publish เข้า Discord ทางเดิม

═══════════════════════════════════════════════════════════════════════════════
🚦 ลำดับที่ห้ามสลับ
═══════════════════════════════════════════════════════════════════════════════
1. Insert ประกาศ + fan-out การแจ้งเตือน + audit อยู่ใน transaction เดียว
2. **หลัง commit** จึง publish เข้า Discord
   - ถ้าสลับกัน: publish ก่อนแล้ว transaction rollback ⇒ Discord มีประกาศที่ระบบ
     ไม่มี ซึ่งลบไม่ได้ด้วยเครื่องมือของระบบ
   - `ActionService._publish` กลืน exception อยู่แล้ว ⇒ Redis ล่มไม่ทำให้ประกาศหาย
     (แค่ Discord ไม่ได้รับ) ซึ่งเป็นทางที่ยอมรับได้

═══════════════════════════════════════════════════════════════════════════════
🌙 quiet hours กับประกาศ
═══════════════════════════════════════════════════════════════════════════════
`priority` ของประกาศถูกส่งต่อไปเป็น `priority` ของแถวแจ้งเตือนตรง ๆ
⇒ worker จัดการเอง: `urgent` ทะลุ quiet hours, ระดับอื่นเลื่อนส่งถึงเช้า
ไม่ต้องมีธง `bypass_quiet_hours` แยก (สองที่ตัดสินเรื่องเดียวกันได้ไม่ช้าก็เร็วจะขัดกัน)

ประกาศ `urgent` เท่านั้นที่ @everyone ใน Discord ส่วนประกาศปกติลงเป็น embed เฉย ๆ
(ลด ping ที่ไม่จำเป็น — ตรงกับกติกาในแผน)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import asyncpg

from core.exceptions import AnnouncementNotFoundError, RoomNotFoundError
from core.logger import AuditLogger
from core.rbac import require_permission
from services import notification_service
from services.action_service import ActionService

logger = logging.getLogger("API_ANNOUNCEMENT")

announcement_logger = AuditLogger(service_name="ANNOUNCEMENT")

# ต้องตรงกับ CHECK ใน migration 0002 (announcements_priority_check)
PRIORITIES: tuple[str, ...] = ("normal", "high", "urgent")

# เพดานจำนวนประกาศปักหมุดที่ส่งกลับในหน้าแรก — กันห้องที่ปักไว้ทุกใบจนหน้าแรกจม
MAX_PINNED = 20

# ฟิลด์ที่แก้ได้ผ่าน PATCH — whitelist เท่านั้น (กันการเขียนคอลัมน์ที่ไม่ตั้งใจ)
_UPDATABLE_FIELDS = ("title", "body", "priority", "pinned")


def _display_name(row: Optional[asyncpg.Record]) -> str:
    """ชื่อที่ใช้ใน footer ของ embed — ไม่รับชื่อจาก client (กันการแอบอ้าง)"""
    if row is None:
        return "ระบบ"
    parts = [row["first_name"], row["last_name"]]
    name = " ".join(part for part in parts if part).strip()
    return name or row["username"] or "ระบบ"


async def create_announcement(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    title: str,
    body: str = "",
    priority: str = "normal",
    pinned: bool = False,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    """สร้างประกาศ + แจ้งเตือนทั้งห้อง แล้วค่อยส่งเข้า Discord

    คืน `{"item": {...}, "delivered_count": n}` — `delivered_count` คือจำนวน
    **สมาชิกที่ล็อกอินจริง** ที่ได้รับแจ้งเตือน (ไม่รวมผู้เขียนเอง)
    """
    if priority not in PRIORITIES:
        raise ValueError(f"priority ต้องเป็นหนึ่งใน {PRIORITIES}")

    start = time.time()

    async with pool.acquire() as conn:
        async with conn.transaction():
            room = await conn.fetchrow(
                "SELECT id, server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL",
                room_id,
            )
            if not room:
                raise RoomNotFoundError(f"ไม่พบห้องเรียน ID: {room_id}")

            # ประกาศ = ช่องทางราชการของห้อง ⇒ สิทธิ์เดียวกับที่ตั้งค่าห้อง
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")

            author = await conn.fetchrow(
                "SELECT first_name, last_name, username FROM users WHERE id = $1", user_id
            )

            row = await conn.fetchrow(
                """
                INSERT INTO announcements (room_id, title, body, priority, pinned, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, created_at
                """,
                room_id,
                title,
                body,
                priority,
                pinned,
                user_id,
            )
            announcement_id = int(row["id"])

            # fan-out ชุดเดียวต่อห้อง — ไม่วนใน Python ต่อคน (ดู notification_service)
            # ผู้เขียนไม่ต้องรับแจ้งเตือนประกาศของตัวเอง (แต่ยังเห็นในหน้าเว็บ)
            delivered = await notification_service.notify_room(
                conn,
                room_id=room_id,
                group_type="announcement",
                type="announcement_published",
                title=title,
                body=body,
                entity_type="announcement",
                entity_id=announcement_id,
                url=f"/announcements/{announcement_id}",
                priority=priority,
                exclude_user_ids=[user_id],
            )

            exec_time = int((time.time() - start) * 1000)
            await announcement_logger.log(
                conn=conn,
                action="CREATE",
                actor_identifier=actor_identifier,
                client_source=client_source,
                room_id=room_id,
                user_id=user_id,
                entity_type="ANNOUNCEMENT",
                entity_id=str(announcement_id),
                new_values={
                    "title": title,
                    "body": body,
                    "priority": priority,
                    "pinned": pinned,
                    "delivered_count": delivered,
                },
                endpoint_or_command="create_announcement",
                execution_time_ms=exec_time,
            )

    # ── หลัง commit เท่านั้น (ดูเหตุผลใน docstring) ───────────────────────────
    server_id = room["server_id"]
    if server_id:
        await ActionService.notify_custom_message(
            server_id=int(server_id),
            title=title,
            message=body or title,
            user_name=_display_name(author),
            mention=(priority == "urgent"),
        )

    return {
        "item": {
            "id": announcement_id,
            "title": title,
            "body": body,
            "priority": priority,
            "pinned": pinned,
            "archived_at": None,
            "created_by": user_id,
            "created_at": row["created_at"],
            "updated_at": row["created_at"],
            "is_unread": False,
        },
        "delivered_count": delivered,
    }


# ═════════════════════════════════════════════════════════════════════════════
# อ่าน
# ═════════════════════════════════════════════════════════════════════════════
# สถานะ "ยังไม่อ่าน" ของประกาศ = อ่านจาก **แถวแจ้งเตือนของผู้ใช้เอง**
# ไม่สร้างตาราง read-tracking ที่สอง ⇒ กระดิ่งกับหน้าประกาศใช้แหล่งเดียวกันเสมอ
# (คนที่เข้าห้องมาหลังประกาศออก ไม่มีแถวแจ้งเตือน ⇒ ถือว่าอ่านแล้ว ไม่ใช่ค้างไม่อ่านตลอดกาล)
_UNREAD_PREDICATE = """
    EXISTS (
        SELECT 1 FROM notifications n
        WHERE n.room_id = a.room_id
          AND n.user_id = $2
          AND n.entity_type = 'announcement'
          AND n.entity_id = a.id::text
          AND n.read_at IS NULL
    )
"""

_IS_UNREAD = f"{_UNREAD_PREDICATE} AS is_unread"

_ITEM_COLUMNS = f"""
    a.id, a.title, a.body, a.priority, a.pinned, a.archived_at,
    a.created_by, a.created_at, a.updated_at,
    {_IS_UNREAD}
"""


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        return notification_service.DEFAULT_PAGE_SIZE
    return min(limit, notification_service.MAX_PAGE_SIZE)


async def list_announcements(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    limit: int = notification_service.DEFAULT_PAGE_SIZE,
    before_id: Optional[int] = None,
    include_archived: bool = False,
    unread_only: bool = False,
) -> tuple[list[asyncpg.Record], list[asyncpg.Record], bool]:
    """คืน (ปักหมุด, รายการ, ยังมีหน้าเก่าไหม)

    - **ปักหมุด** ส่งกลับเฉพาะหน้าแรก (`before_id` ว่าง) เพราะถ้าปนกับการแบ่งหน้า
      ด้วย id จะมีใบที่ id ต่ำกว่าตัวชี้ค้างไม่เคยถูกส่งมา
    - รายการปกติเรียงใหม่สุดก่อน + cursor `before_id`
    - `unread_only=True` = ปลายทางของการ์ด "ประกาศยังไม่อ่าน" บนหน้าหลัก
      (ใช้ predicate ตัวเดียวกับ `_IS_UNREAD` ⇒ นับกับแสดงตรงกันเสมอ)
    """
    page_size = _normalize_limit(limit)

    async with pool.acquire() as conn:
        pinned: list[asyncpg.Record] = []
        if before_id is None:
            pinned = list(
                await conn.fetch(
                    f"""
                    SELECT {_ITEM_COLUMNS}
                    FROM announcements a
                    WHERE a.room_id = $1
                      AND a.pinned
                      AND ($3 OR a.archived_at IS NULL)
                      AND (NOT $5::boolean OR {_UNREAD_PREDICATE})
                    ORDER BY a.id DESC
                    LIMIT $4
                    """,
                    room_id,
                    user_id,
                    include_archived,
                    MAX_PINNED,
                    unread_only,
                )
            )

        rows = await conn.fetch(
            f"""
            SELECT {_ITEM_COLUMNS}
            FROM announcements a
            WHERE a.room_id = $1
              AND NOT a.pinned
              AND ($3::bigint IS NULL OR a.id < $3)
              AND ($5 OR a.archived_at IS NULL)
              AND (NOT $6::boolean OR {_UNREAD_PREDICATE})
            ORDER BY a.id DESC
            LIMIT $4
            """,
            room_id,
            user_id,
            before_id,
            page_size + 1,
            include_archived,
            unread_only,
        )

    has_more = len(rows) > page_size
    return pinned, list(rows[:page_size]), has_more


async def get_announcement(
    pool: asyncpg.Pool, *, room_id: int, user_id: int, announcement_id: int
) -> asyncpg.Record:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT {_ITEM_COLUMNS}
            FROM announcements a
            WHERE a.room_id = $1 AND a.id = $3
            """,
            room_id,
            user_id,
            announcement_id,
        )
    if row is None:
        raise AnnouncementNotFoundError(f"ไม่พบประกาศ ID: {announcement_id}")
    return row


# ═════════════════════════════════════════════════════════════════════════════
# แก้ไข / ปักหมุด / เก็บถาวร
# ═════════════════════════════════════════════════════════════════════════════
async def update_announcement(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    announcement_id: int,
    changes: dict[str, Any],
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> asyncpg.Record:
    """แก้เฉพาะฟิลด์ใน whitelist — ไม่สร้างแจ้งเตือนใหม่ (กันสแปมจากการแก้คำผิด)"""
    fields = {k: v for k, v in changes.items() if k in _UPDATABLE_FIELDS and v is not None}
    if not fields:
        return await get_announcement(
            pool, room_id=room_id, user_id=user_id, announcement_id=announcement_id
        )

    start = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")

            old = await conn.fetchrow(
                """
                SELECT id, title, body, priority, pinned
                FROM announcements
                WHERE id = $1 AND room_id = $2
                FOR UPDATE
                """,
                announcement_id,
                room_id,
            )
            if old is None:
                raise AnnouncementNotFoundError(f"ไม่พบประกาศ ID: {announcement_id}")

            sets: list[str] = []
            params: list[Any] = []
            for column in _UPDATABLE_FIELDS:
                if column in fields:
                    params.append(fields[column])
                    sets.append(f"{column} = ${len(params)}")
            params.append(announcement_id)
            params.append(room_id)
            await conn.execute(
                f"""
                UPDATE announcements
                SET {', '.join(sets)}, updated_at = NOW()
                WHERE id = ${len(params) - 1} AND room_id = ${len(params)}
                """,
                *params,
            )

            exec_time = int((time.time() - start) * 1000)
            await announcement_logger.log(
                conn=conn,
                action="UPDATE",
                actor_identifier=actor_identifier,
                client_source=client_source,
                room_id=room_id,
                user_id=user_id,
                entity_type="ANNOUNCEMENT",
                entity_id=str(announcement_id),
                old_values={k: old[k] for k in _UPDATABLE_FIELDS},
                new_values=fields,
                endpoint_or_command="update_announcement",
                execution_time_ms=exec_time,
            )

    return await get_announcement(
        pool, room_id=room_id, user_id=user_id, announcement_id=announcement_id
    )


async def set_archived(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    announcement_id: int,
    archived: bool,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> asyncpg.Record:
    """เก็บเข้าคลัง / เอากลับมาปักเป็นประกาศปกติ (idempotent ทั้งคู่)"""
    start = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")

            row = await conn.fetchrow(
                """
                UPDATE announcements
                SET archived_at = CASE WHEN $3 THEN NOW() ELSE NULL END,
                    updated_at = NOW()
                WHERE id = $1 AND room_id = $2
                RETURNING id
                """,
                announcement_id,
                room_id,
                archived,
            )
            if row is None:
                raise AnnouncementNotFoundError(f"ไม่พบประกาศ ID: {announcement_id}")

            exec_time = int((time.time() - start) * 1000)
            await announcement_logger.log(
                conn=conn,
                action="UPDATE",
                actor_identifier=actor_identifier,
                client_source=client_source,
                room_id=room_id,
                user_id=user_id,
                entity_type="ANNOUNCEMENT",
                entity_id=str(announcement_id),
                new_values={"archived": archived},
                endpoint_or_command="archive_announcement",
                execution_time_ms=exec_time,
            )

    return await get_announcement(
        pool, room_id=room_id, user_id=user_id, announcement_id=announcement_id
    )


# ═════════════════════════════════════════════════════════════════════════════
# อ่านแล้ว
# ═════════════════════════════════════════════════════════════════════════════
async def mark_read(
    pool: asyncpg.Pool, *, room_id: int, user_id: int, announcement_id: int
) -> bool:
    """ทำเครื่องหมายอ่านแล้ว = อัปเดตแถวแจ้งเตือนของผู้ใช้เอง (COALESCE = ไม่ทับเวลาอ่านครั้งแรก)

    คืน False ถ้าไม่มีแถวให้แตะ (เช่น เข้าห้องมาหลังประกาศออก) — ไม่ใช่ error
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE notifications
            SET read_at = COALESCE(read_at, NOW())
            WHERE room_id = $1
              AND user_id = $2
              AND entity_type = 'announcement'
              AND entity_id = $3
            RETURNING id
            """,
            room_id,
            user_id,
            str(announcement_id),
        )
    return len(rows) > 0
