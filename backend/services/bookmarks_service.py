"""บุ๊กมาร์ก "บันทึกไว้" — P3.4

═══════════════════════════════════════════════════════════════════════════════
ขอบเขต
═══════════════════════════════════════════════════════════════════════════════
เก็บเฉพาะรายการที่สมาชิกห้องทุกคนอ่านได้อยู่แล้ว (ประกาศ · กิจกรรม) — ไม่ได้เพิ่มสิทธิ์
การเข้าถึงใหม่ บุ๊กมาร์กจึงเป็น "ทางลัด" ไม่ใช่ "ประตูหลัง":
  • ตรวจ `room_id` ของเป้าหมายทุกครั้ง ⇒ ข้ามห้องบุ๊กมาร์กไม่ได้ (404 ไม่ใช่ 200)
  • ยังต้องผ่าน `require_member` เหมือน endpoint อื่นของห้อง

═══════════════════════════════════════════════════════════════════════════════
กดซ้ำ / ลบ / กดใหม่
═══════════════════════════════════════════════════════════════════════════════
unique index เป็น partial (`WHERE deleted_at IS NULL`) ⇒ แถวที่ลบแล้วไม่กิน key
`add_bookmark` จึงต้อง "คืนชีพ" แถวเดิมก่อนเสมอ ถ้า INSERT ตรง ๆ จะได้แถวขยะเพิ่มขึ้น
ทุกครั้งที่ผู้ใช้เปลี่ยนใจ (และ audit จะเล่าเรื่องผิดว่าเป็นการเพิ่มครั้งแรก)

═══════════════════════════════════════════════════════════════════════════════
การแบ่งหน้า
═══════════════════════════════════════════════════════════════════════════════
เรียงตามเวลาที่ **บันทึก** (`created_at DESC, id DESC`) ไม่ใช่เวลาของเนื้อหา — ผู้ใช้
จำได้ว่า "เพิ่งกดเมื่อกี้" ไม่ได้จำวันที่ประกาศ และคีย์ 2 ตัวก็พอเพราะทุกแถวอยู่ใน
ตารางเดียวกัน (ต่างจากฟีด /me/activity ที่ UNION สองตาราง)
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Optional

import asyncpg

from core.exceptions import (
    ActivityNotFoundError,
    AnnouncementNotFoundError,
    BookmarkNotFoundError,
)
from core.logger import AuditLogger
from core.rbac import require_member

bookmark_logger = AuditLogger(service_name="BOOKMARK")

# ต้องตรงกับ CHECK ใน migration 0004 — ถ้าเพิ่มชนิดใหม่ต้องเขียน migration ใหม่
ENTITY_TYPES: tuple[str, ...] = ("announcement", "activity")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

_LIST_SQL = """
WITH mine AS (
    SELECT b.id, b.entity_type, b.entity_id, b.created_at
      FROM bookmarks b
     WHERE b.user_id = $1
       AND b.room_id = $2
       AND b.deleted_at IS NULL
       AND ($3::text IS NULL OR b.entity_type = $3)
       AND (
            $4::timestamptz IS NULL
            OR (b.created_at, b.id) < ($4::timestamptz, $5::bigint)
           )
     ORDER BY b.created_at DESC, b.id DESC
     LIMIT $6
)
SELECT
    m.id                                   AS bookmark_id,
    m.entity_type,
    m.entity_id,
    m.created_at                           AS bookmarked_at,
    COALESCE(AN.title, AC.title)           AS title,
    LEFT(COALESCE(AN.body, AC.description, ''), 160) AS snippet,
    CASE WHEN m.entity_type = 'announcement'
         -- created_at เป็น timestamptz ⇒ ต้องแปลงเป็นวันที่แบบ Bangkok ไม่ใช่ TZ ของเซิร์ฟเวอร์
         THEN (AN.created_at AT TIME ZONE 'Asia/Bangkok')::date
         ELSE AC.activity_date
    END                                    AS occurred_on,
    CASE WHEN m.entity_type = 'announcement'
         THEN ('/announcements/' || m.entity_id)
         ELSE ('/activities/' || m.entity_id)
    END                                    AS url,
    -- เป้าหมายถูกลบถาวร/ไม่พบ = ลิงก์ตาย ⇒ หน้าแสดง "ไม่พร้อมใช้งาน" ไม่ใช่กดแล้ว 404
    CASE WHEN m.entity_type = 'announcement'
         THEN (AN.id IS NOT NULL)
         ELSE (AC.id IS NOT NULL)
    END                                    AS available
  FROM mine m
  LEFT JOIN announcements AN
         ON m.entity_type = 'announcement' AND AN.id = m.entity_id AND AN.room_id = $2
  LEFT JOIN activities AC
         ON m.entity_type = 'activity' AND AC.id = m.entity_id AND AC.room_id = $2
        AND AC.deleted_at IS NULL
 ORDER BY m.created_at DESC, m.id DESC
"""


def _encode_cursor(created_at: datetime, bookmark_id: int) -> str:
    raw = f"{created_at.isoformat()}|{bookmark_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    """ผิดรูป = `ValueError` (router แปลเป็น 400 ไม่ใช่ 500)"""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        ts_raw, id_raw = raw.split("|")
        created_at = datetime.fromisoformat(ts_raw)
        bookmark_id = int(id_raw)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("cursor ไม่ถูกต้อง — เริ่มจากหน้าแรกใหม่") from exc
    if created_at.tzinfo is None or bookmark_id < 1:
        raise ValueError("cursor ไม่ถูกต้อง — เริ่มจากหน้าแรกใหม่")
    return created_at, bookmark_id


def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type ต้องเป็นหนึ่งใน {', '.join(ENTITY_TYPES)}")


async def _ensure_target_exists(
    conn: asyncpg.Connection, room_id: int, entity_type: str, entity_id: int
) -> None:
    """ยืนยันว่าเป้าหมายอยู่ในห้องนี้จริง — ข้ามห้อง = 404 (ไม่ใช่ 200 เงียบ ๆ)"""
    if entity_type == "announcement":
        found = await conn.fetchval(
            "SELECT 1 FROM announcements WHERE id = $1 AND room_id = $2",
            entity_id,
            room_id,
        )
        if not found:
            raise AnnouncementNotFoundError(f"ไม่พบประกาศ ID: {entity_id}")
        return
    found = await conn.fetchval(
        "SELECT 1 FROM activities WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
        entity_id,
        room_id,
    )
    if not found:
        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {entity_id}")


async def list_bookmarks(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    entity_type: Optional[str] = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    if entity_type is not None:
        _validate_entity_type(entity_type)
    page_size = min(max(int(limit), 1), MAX_PAGE_SIZE)
    cursor_ts: Optional[datetime] = None
    cursor_id: Optional[int] = None
    if cursor:
        cursor_ts, cursor_id = _decode_cursor(cursor)

    async with pool.acquire() as conn:
        await require_member(conn, room_id, user_id)
        rows = await conn.fetch(
            _LIST_SQL, int(user_id), room_id, entity_type, cursor_ts, cursor_id, page_size + 1
        )

    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [
        {
            "bookmark_id": int(row["bookmark_id"]),
            "entity_type": row["entity_type"],
            "entity_id": int(row["entity_id"]),
            "title": row["title"] or "รายการนี้ถูกลบแล้ว",
            "snippet": row["snippet"] or "",
            "occurred_on": row["occurred_on"],
            "url": row["url"],
            "available": bool(row["available"]),
            "created_at": row["bookmarked_at"],
        }
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last["bookmarked_at"], int(last["bookmark_id"]))
    return {"items": items, "has_more": has_more, "next_cursor": next_cursor}


async def add_bookmark(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    entity_type: str,
    entity_id: int,
    actor_identifier: str = "system",
    client_source: str = "WEB_APP",
) -> dict[str, Any]:
    """กดบันทึก — ซ้ำไม่มีผลข้างเคียง (`created=False`)

    คืนชีพแถวที่ soft-delete ไว้ก่อน ⇒ หนึ่งคน × หนึ่งรายการ = หนึ่งแถวตลอดชีพ
    """
    _validate_entity_type(entity_type)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_member(conn, room_id, user_id)
            await _ensure_target_exists(conn, room_id, entity_type, entity_id)

            restored = await conn.fetchrow(
                """
                UPDATE bookmarks
                   SET deleted_at = NULL, created_at = NOW()
                 WHERE user_id = $1 AND room_id = $2
                   AND entity_type = $3 AND entity_id = $4
                   AND deleted_at IS NOT NULL
                RETURNING id, created_at
                """,
                int(user_id),
                room_id,
                entity_type,
                entity_id,
            )
            if restored is not None:
                row, created, restored_only = restored, True, True
            else:
                existing = await conn.fetchrow(
                    """
                    SELECT id, created_at FROM bookmarks
                     WHERE user_id = $1 AND room_id = $2
                       AND entity_type = $3 AND entity_id = $4
                       AND deleted_at IS NULL
                    """,
                    int(user_id),
                    room_id,
                    entity_type,
                    entity_id,
                )
                if existing is not None:
                    row, created, restored_only = existing, False, False
                else:  # INSERT จริง — ครั้งแรกของผู้ใช้คนนี้ในรายการนี้
                    row = await conn.fetchrow(
                        """
                        INSERT INTO bookmarks (user_id, room_id, entity_type, entity_id)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id, created_at
                        """,
                        int(user_id),
                        room_id,
                        entity_type,
                        entity_id,
                    )
                    created, restored_only = True, False

            await bookmark_logger.log(
                conn=conn,
                action="CREATE",
                actor_identifier=actor_identifier,
                client_source=client_source,
                room_id=room_id,
                user_id=int(user_id),
                entity_type="BOOKMARK",
                entity_id=str(row["id"]),
                new_values={
                    "target_type": entity_type,
                    "target_id": entity_id,
                    "restored": restored_only,
                },
                endpoint_or_command="add_bookmark",
            )

    return {
        "id": int(row["id"]),
        "entity_type": entity_type,
        "entity_id": int(entity_id),
        "created_at": row["created_at"],
        "created": created,
    }


async def remove_bookmark(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    bookmark_id: int,
    actor_identifier: str = "system",
    client_source: str = "WEB_APP",
) -> None:
    """ลบของตัวเองเท่านั้น — ของคนอื่นตอบ 404 เหมือน "ไม่มี" (ไม่บอกว่ามีอยู่)"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_member(conn, room_id, user_id)
            row = await conn.fetchrow(
                """
                UPDATE bookmarks
                   SET deleted_at = NOW()
                 WHERE id = $1 AND user_id = $2 AND room_id = $3 AND deleted_at IS NULL
                RETURNING entity_type, entity_id
                """,
                bookmark_id,
                int(user_id),
                room_id,
            )
            if row is None:
                raise BookmarkNotFoundError(f"ไม่พบบุ๊กมาร์ก ID: {bookmark_id}")

            await bookmark_logger.log(
                conn=conn,
                action="DELETE",
                actor_identifier=actor_identifier,
                client_source=client_source,
                room_id=room_id,
                user_id=int(user_id),
                entity_type="BOOKMARK",
                entity_id=str(bookmark_id),
                old_values={
                    "target_type": row["entity_type"],
                    "target_id": int(row["entity_id"]),
                },
                endpoint_or_command="remove_bookmark",
            )


async def get_bookmark_state(
    pool: asyncpg.Pool, *, room_id: int, user_id: int, entity_type: str, entity_id: int
) -> dict[str, Any]:
    """สถานะของไอคอนในหน้ารายละเอียด — ไม่ตรวจว่าเป้าหมายมีจริง (หน้านั้นแสดงอยู่แล้ว)"""
    _validate_entity_type(entity_type)
    async with pool.acquire() as conn:
        await require_member(conn, room_id, user_id)
        bookmark_id = await conn.fetchval(
            """
            SELECT id FROM bookmarks
             WHERE user_id = $1 AND room_id = $2
               AND entity_type = $3 AND entity_id = $4
               AND deleted_at IS NULL
            """,
            int(user_id),
            room_id,
            entity_type,
            entity_id,
        )
    return {
        "bookmarked": bookmark_id is not None,
        "bookmark_id": int(bookmark_id) if bookmark_id is not None else None,
    }
