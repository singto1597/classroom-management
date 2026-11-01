"""บริการแจ้งเตือนในแอป — สร้าง (fan-out) / อ่าน / ทำเครื่องหมายว่าอ่านแล้ว

═══════════════════════════════════════════════════════════════════════════════
🎯 กฎที่ต้องถือให้ครบ
═══════════════════════════════════════════════════════════════════════════════
1. **ผู้เรียกต้องส่ง `conn` ที่อยู่ใน transaction ของงานจริงมาให้**
   `notify_user` / `notify_room` ถูกออกแบบให้เป็น "คำสั่ง SQL อีกตัวในทรานแซกชันเดิม"
   ไม่ใช่ service ที่เปิด transaction เอง — ถ้าแจ้งเตือนถูกสร้างหลัง `commit`
   แล้วโปรเซสตายระหว่างนั้น งานจะสำเร็จแต่ไม่มีใครรู้ (และกลับกัน: แจ้งเตือน
   ที่ผูกกับงานที่ rollback ไปแล้วจะค้างเป็นข่าวผี)

2. **ห้าม publish SSE เอง** — trigger `trg_notifications_fanout` เป็นคนยิง
   `pg_notify` หลัง INSERT ⇒ ถ้าที่นี่เรียก `notification_stream.broadcast()` ด้วย
   จะได้สองครั้ง (badge กระพริบ/รายการโหลดซ้ำ) และ replica ที่ไม่ได้สร้างแถวนั้นจะไม่รู้เรื่อง

3. **การอ่านกรองด้วย preference `inapp`** — ผู้ใช้ที่ปิดกลุ่ม "การเงิน" ต้องไม่เห็น
   ทั้งในรายการและในตัวเลขกระดิ่ง ตัวเลขจึงถูกคำนวณจาก query เดียวกันกับรายการ
   (กฎ "ตัวเลขบนกระดิ่ง = จำนวนในรายการ" — ไม่งั้นกลับมาเป็นบั๊ก 34 → 5 อีก)

4. **fan-out ต่อห้องใช้ INSERT … SELECT ชุดเดียว** — ไม่วนใน Python ต่อคน
   (ห้อง 40–50 คน × หลายห้อง = คำสั่ง SQL เต็มชุดถ้าวน ⇒ ช้ากว่าและล้มกลางทางได้)
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Sequence

import asyncpg

logger = logging.getLogger("API_NOTIFICATIONS")

# กลุ่มที่ผู้ใช้เปิด/ปิดได้ (announcement ปิดไม่ได้ — ประกาศของห้องคือช่องทางราชการ)
MUTABLE_GROUP_TYPES: tuple[str, ...] = ("task", "finance", "activity", "member")
ALL_GROUP_TYPES: tuple[str, ...] = (*MUTABLE_GROUP_TYPES, "announcement")

# เพดานต่อหน้า — กัน query หนักจากการเรียกที่ใส่ limit มาเอง
MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 30


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        return DEFAULT_PAGE_SIZE
    return min(limit, MAX_PAGE_SIZE)


# ═════════════════════════════════════════════════════════════════════════════
# สร้างแจ้งเตือน — ต้องอยู่ใน transaction ของผู้เรียก
# ═════════════════════════════════════════════════════════════════════════════
async def notify_user(
    conn: asyncpg.Connection,
    *,
    room_id: int,
    user_id: int,
    group_type: str,
    type: str,
    title: str,
    body: str = "",
    entity_type: Optional[str] = None,
    entity_id: Optional[int | str] = None,
    url: Optional[str] = None,
    priority: str = "normal",
) -> int:
    """สร้างแจ้งเตือนให้ผู้ใช้หนึ่งคน คืน notification id"""
    return await conn.fetchval(
        """
        INSERT INTO notifications
            (room_id, user_id, group_type, type, priority, title, body, entity_type, entity_id, url)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        room_id,
        user_id,
        group_type,
        type,
        priority,
        title,
        body,
        entity_type,
        None if entity_id is None else str(entity_id),
        url,
    )


async def notify_room(
    conn: asyncpg.Connection,
    *,
    room_id: int,
    group_type: str,
    type: str,
    title: str,
    body: str = "",
    entity_type: Optional[str] = None,
    entity_id: Optional[int | str] = None,
    url: Optional[str] = None,
    priority: str = "normal",
    exclude_user_ids: Iterable[int] = (),
) -> int:
    """สร้างแจ้งเตือนให้สมาชิกทุกคนที่ล็อกอินจริงของห้อง คืนจำนวนแถวที่สร้าง

    "สมาชิก" = แถว students ที่ `status = 'active'`, ไม่ถูกลบ, และ **ผูกกับ user จริง**
    (นักเรียนที่ยังไม่มีบัญชีไม่มีทางอ่านในแอป ⇒ ไม่ต้องสร้างแถวให้ — และไม่มี
    push subscription ให้ trigger สร้าง outbox อยู่แล้ว)
    """
    excluded = list({int(uid) for uid in exclude_user_ids if uid is not None})
    rows = await conn.fetch(
        """
        INSERT INTO notifications
            (room_id, user_id, group_type, type, priority, title, body, entity_type, entity_id, url)
        SELECT $1, s.user_id, $2, $3, $4, $5, $6, $7, $8, $9
        FROM students s
        WHERE s.room_id = $1
          AND s.status = 'active'
          AND s.deleted_at IS NULL
          AND s.user_id IS NOT NULL
          AND s.user_id <> ALL($10::int[])
        RETURNING id
        """,
        room_id,
        group_type,
        type,
        priority,
        title,
        body,
        entity_type,
        None if entity_id is None else str(entity_id),
        url,
        excluded,
    )
    return len(rows)


# ═════════════════════════════════════════════════════════════════════════════
# อ่าน
# ═════════════════════════════════════════════════════════════════════════════
# เงื่อนไข "ไม่ถูกปิดด้วย preference" ใช้ร่วมกันทั้งรายการและตัวเลข ⇒ สองที่นี้
# ขยับพร้อมกันเสมอ (แก้ที่เดียวแล้วอีกที่ไม่แก้ = กระดิ่งโชว์ 3 แต่ลิสต์มี 1)
_INAPP_VISIBLE = """
    NOT EXISTS (
        SELECT 1 FROM notification_preferences p
        WHERE p.user_id = $1
          AND p.group_type = n.group_type
          AND p.inapp = FALSE
    )
"""


async def list_notifications(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    limit: int = DEFAULT_PAGE_SIZE,
    before_id: Optional[int] = None,
) -> tuple[list[asyncpg.Record], int, bool]:
    """คืน (แถว, จำนวนที่ยังไม่อ่านของห้องนี้, ยังมีหน้าเก่ากว่าไหม)

    `limit + 1` แถวเพื่อรู้ว่า `has_more` โดยไม่ต้อง COUNT อีกรอบ
    """
    page_size = _normalize_limit(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT n.id, n.group_type, n.type, n.priority, n.title, n.body,
                   n.entity_type, n.entity_id, n.url, n.read_at, n.created_at
            FROM notifications n
            WHERE n.user_id = $1
              AND n.room_id = $2
              AND ($3::bigint IS NULL OR n.id < $3)
              AND {_INAPP_VISIBLE}
            ORDER BY n.id DESC
            LIMIT $4
            """,
            user_id,
            room_id,
            before_id,
            page_size + 1,
        )
        unread = await unread_count(conn, room_id=room_id, user_id=user_id)

    has_more = len(rows) > page_size
    return list(rows[:page_size]), int(unread), has_more


async def unread_count(conn: asyncpg.Connection, *, room_id: int, user_id: int) -> int:
    """ตัวเลขบนกระดิ่ง — ใช้ query เดียวกับรายการ (ดู `_INAPP_VISIBLE`)"""
    value = await conn.fetchval(
        f"""
        SELECT COUNT(*)
        FROM notifications n
        WHERE n.user_id = $1
          AND n.room_id = $2
          AND n.read_at IS NULL
          AND {_INAPP_VISIBLE}
        """,
        user_id,
        room_id,
    )
    return int(value or 0)


async def mark_read(
    pool: asyncpg.Pool, *, room_id: int, user_id: int, notification_id: int
) -> bool:
    """ทำเครื่องหมายอ่านแล้ว — คืน False ถ้าแถวไม่ใช่ของผู้ขอยิง (ไม่รั่วว่ามีอยู่ไหม)

    `read_at` ไม่ถูกทับถ้าอ่านแล้ว (COALESCE) ⇒ "อ่านครั้งแรกเมื่อไร" เป็นความจริง
    """
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            """
            UPDATE notifications
            SET read_at = COALESCE(read_at, NOW())
            WHERE id = $1 AND user_id = $2 AND room_id = $3
            RETURNING id
            """,
            notification_id,
            user_id,
            room_id,
        )
    return row is not None


async def mark_all_read(pool: asyncpg.Pool, *, room_id: int, user_id: int) -> int:
    """อ่านทั้งหมดของห้องนี้ — ไม่แตะห้องอื่น (badge รวมข้ามห้องต้องแยกบริบท)

    นับเฉพาะแถวที่ "ผู้ใช้มองเห็นจริง" ตาม preference ⇒ ตัวเลขที่ตอบกลับ
    ตรงกับที่กระดิ่งลดลงจริง
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            UPDATE notifications n
            SET read_at = NOW()
            WHERE n.user_id = $1
              AND n.room_id = $2
              AND n.read_at IS NULL
              AND {_INAPP_VISIBLE}
            RETURNING n.id
            """,
            user_id,
            room_id,
        )
    return len(rows)


# ═════════════════════════════════════════════════════════════════════════════
# Preference
# ═════════════════════════════════════════════════════════════════════════════
async def get_preferences(pool: asyncpg.Pool, *, user_id: int) -> list[dict]:
    """คืนครบทุกกลุ่มที่ปรับได้ — กลุ่มที่ไม่มีแถว = เปิดทั้งคู่ (ค่าเริ่มต้น)

    ต้องคืน "ครบ" ไม่ใช่เฉพาะแถวที่มีใน DB — ไม่งั้นหน้าตั้งค่าจะโชว์แค่
    สวิตช์ที่เคยแตะ และผู้ใช้จะเข้าใจผิดว่ากลุ่มที่หายไปปิดอยู่
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT group_type, inapp, push
            FROM notification_preferences
            WHERE user_id = $1
            """,
            user_id,
        )
    stored = {row["group_type"]: row for row in rows}
    return [
        {
            "group_type": group,
            "inapp": bool(stored[group]["inapp"]) if group in stored else True,
            "push": bool(stored[group]["push"]) if group in stored else True,
        }
        for group in MUTABLE_GROUP_TYPES
    ]


async def set_preference(
    pool: asyncpg.Pool,
    *,
    user_id: int,
    group_type: str,
    inapp: bool,
    push: bool,
) -> None:
    """UPSERT สวิตช์หนึ่งกลุ่ม (ผู้เรียกต้องตรวจว่า group_type อยู่ในชุดที่ปรับได้)"""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notification_preferences (user_id, group_type, inapp, push, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id, group_type)
            DO UPDATE SET inapp = EXCLUDED.inapp, push = EXCLUDED.push, updated_at = NOW()
            """,
            user_id,
            group_type,
            inapp,
            push,
        )


# ═════════════════════════════════════════════════════════════════════════════
# ตัวช่วยสำหรับ service อื่น (เรียกคู่กับ ActionService เดิม — Discord ยังทำงาน)
# ═════════════════════════════════════════════════════════════════════════════
async def notify_safely(
    conn: asyncpg.Connection,
    *,
    room_id: int,
    user_ids: Sequence[int],
    group_type: str,
    type: str,
    title: str,
    **kwargs,
) -> None:
    """เวอร์ชันที่ "แจ้งเตือนล้มไม่ทำให้ธุรกรรมหลักล้ม"

    ⚠️ ใช้เฉพาะเส้นทางที่การแจ้งเตือนเป็นของแถม (เช่น ติ๊กงานเสร็จ)
    และ **ผู้เรียกยอมรับได้ว่าแจ้งเตือนอาจหาย** — ถ้าเป็นเหตุการณ์ที่ผู้ใช้
    ต้องรู้แน่ ๆ (ใบเสร็จ/ถูกตัดสิทธิ์) ให้ใช้ `notify_user` ตรง ๆ ในทรานแซกชัน

    หมายเหตุ: การ INSERT ที่ล้มกลาง transaction จะ abort ทั้ง transaction
    ⇒ ฟังก์ชันนี้ใช้ SAVEPOINT เพื่อกู้เฉพาะบล็อกแจ้งเตือน
    """
    if not user_ids:
        return
    try:
        async with conn.transaction():
            for user_id in user_ids:
                await notify_user(
                    conn,
                    room_id=room_id,
                    user_id=user_id,
                    group_type=group_type,
                    type=type,
                    title=title,
                    **kwargs,
                )
    except Exception:  # noqa: BLE001 — ตั้งใจกลืน: ของแถมล้มห้ามล้มงานหลัก
        logger.exception("แจ้งเตือนล้มเหลว (ไม่กระทบธุรกรรมหลัก) type=%s", type)
