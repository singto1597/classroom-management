"""สรุปหน้าหลัก — **คำขอเดียว** ต่อการเปิดแอป (P3)

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมี endpoint นี้
═══════════════════════════════════════════════════════════════════════════════
เดิม `Dashboard.vue` ยิง `TaskService.getAllTasks()` แล้วนับฝั่งหน้า ⇒ (ก) ข้อมูล
ทั้งห้องถูกดึงมาเพื่อใช้แค่ 2 ตัวเลข (ข) ตัวเลขกับลิสต์ปลายทางนับด้วยคนละโค้ด
⇒ วันหนึ่งจะไม่ตรงกันโดยไม่มีใครรู้

ที่นี่ทุกตัวเลขถูกนับด้วย **predicate เดียวกับ endpoint รายการที่การ์ดนั้นพาไป**
⇒ "34 กดแล้วเจอ 5" เกิดขึ้นไม่ได้ตามโครงสร้าง

═══════════════════════════════════════════════════════════════════════════════
snapshot เดียว
═══════════════════════════════════════════════════════════════════════════════
ทุก query รันใน transaction เดียวแบบ `REPEATABLE READ` + `READ ONLY`
⇒ ทั้งก้อนเห็นฐานข้อมูล ณ จุดเวลาเดียวกัน (ครึ่งทางที่มีคนเพิ่มงาน ตัวเลขจะไม่กลายเป็น
"งานวันนี้ 3 แต่รายการมี 4") · read-only ทำให้ไม่มีทางเผลอเขียนใน path อ่าน

⚠️ "วันนี้" คือ **วันที่ไทย** ตาม `Asia/Bangkok` — คำนวณใน SQL (`NOW() AT TIME ZONE`)
ไม่ใช่นาฬิกาของ Python/เซิร์ฟเวอร์ ซึ่งอาจตั้ง TZ คนละแบบ
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import asyncpg

from core.rbac import require_member

logger = logging.getLogger("API_HOME_SUMMARY")

# เพดานตัวอย่างในหน้าแรก — ตัวเลขบนการ์ดคือของจริง ไม่ใช่ความยาวลิสต์นี้
TASK_PREVIEW_LIMIT = 3
ACTIVITY_LIMIT = 3

# ลำดับวันแบบเดียวกับ `ClassroomService._get_thai_day` (วันที่ 0 = จันทร์)
THAI_DAYS: tuple[str, ...] = (
    "จันทร์",
    "อังคาร",
    "พุธ",
    "พฤหัสบดี",
    "ศุกร์",
    "เสาร์",
    "อาทิตย์",
)

_THAI_TODAY_SQL = "SELECT (NOW() AT TIME ZONE 'Asia/Bangkok')::date"


async def build_home_summary(
    pool: asyncpg.Pool, *, room_id: int, user_id: int
) -> dict[str, Any]:
    """ประกอบสรุปหน้าหลักของผู้ใช้คนหนึ่งในห้องหนึ่ง

    ┗ เรียก `require_member` ก่อน ⇒ คนนอกห้องได้ 403 แม้จะถือ JWT ที่ยังไม่หมดอายุ
    """
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await require_member(conn, room_id, user_id)
            today: date = await conn.fetchval(_THAI_TODAY_SQL)

            tasks = await _load_tasks(conn, room_id=room_id, today=today)
            note = await _load_note(conn, room_id=room_id, today=today)
            activities = await _load_activities(conn, room_id=room_id, today=today)
            finance = await _load_finance(conn, room_id=room_id, user_id=user_id)
            announcements = await _load_announcements(conn, room_id=room_id, user_id=user_id)
            schedule = await _load_schedule(conn, room_id=room_id, today=today)

    return {
        "today": today,
        "tasks": tasks,
        "note": note,
        "activities": activities,
        "finance": finance,
        "announcements": announcements,
        "schedule": schedule,
    }


async def _load_tasks(
    conn: asyncpg.Connection, *, room_id: int, today: date
) -> dict[str, Any]:
    """นับงานที่ยังไม่เสร็จ 3 ก้อน + ตัวอย่างไม่เกิน `TASK_PREVIEW_LIMIT` รายการ

    `done` ไม่ถูกนับในก้อนไหนเลย — การ์ดทุกใบพาไปที่ `/tasks?filter=...` ซึ่ง
    หน้างานกรองด้วย `status` เดียวกัน
    """
    counts = await conn.fetchrow(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_total,
            COUNT(*) FILTER (WHERE status = 'pending' AND due_date = $2) AS due_today,
            COUNT(*) FILTER (WHERE status = 'pending' AND due_date < $2) AS overdue
        FROM tasks
        WHERE room_id = $1 AND deleted_at IS NULL
        """,
        room_id,
        today,
    )
    items = await conn.fetch(
        """
        SELECT id, task_name, due_date, status
        FROM tasks
        WHERE room_id = $1 AND deleted_at IS NULL AND status = 'pending'
        ORDER BY due_date ASC, id ASC
        LIMIT $2
        """,
        room_id,
        TASK_PREVIEW_LIMIT,
    )
    return {
        "total": int(counts["total"] or 0),
        "pending_total": int(counts["pending_total"] or 0),
        "due_today": int(counts["due_today"] or 0),
        "overdue": int(counts["overdue"] or 0),
        "items": [dict(row) for row in items],
    }


async def _load_note(
    conn: asyncpg.Connection, *, room_id: int, today: date
) -> dict[str, Any] | None:
    """โน้ตของวันนี้ — ไม่มีแถว = `None` (ไม่ใช่ `{}`) เพื่อให้ฝั่งหน้าแยก "ว่าง" ออกได้ชัด"""
    row = await conn.fetchrow(
        """
        SELECT bring_items, announcement
        FROM daily_notes
        WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        room_id,
        today,
    )
    if row is None:
        return None
    return {"bring_items": row["bring_items"], "announcement": row["announcement"]}


async def _load_activities(
    conn: asyncpg.Connection, *, room_id: int, today: date
) -> list[dict[str, Any]]:
    """กิจกรรมที่ยังเปิดรับ — `upcoming` และยังไม่ผ่านวันไปแล้ว"""
    rows = await conn.fetch(
        """
        SELECT id, title, activity_date, status, base_hours
        FROM activities
        WHERE room_id = $1
          AND deleted_at IS NULL
          AND status = 'upcoming'
          AND activity_date >= $2
        ORDER BY activity_date ASC, id ASC
        LIMIT $3
        """,
        room_id,
        today,
        ACTIVITY_LIMIT,
    )
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "activity_date": row["activity_date"],
            "status": row["status"],
            # NUMERIC มาจาก asyncpg เป็น Decimal — ต้อง cast ก่อนส่งเข้า Pydantic
            "base_hours": float(row["base_hours"] or 0),
        }
        for row in rows
    ]


async def _load_finance(
    conn: asyncpg.Connection, *, room_id: int, user_id: int
) -> dict[str, Any]:
    """ยอดค้างชำระ **ของตัวเอง** — predicate เดียวกับ `get_my_debts`/`GET /finance/me/debts`

    ⚠️ ห้ามกรองด้วย `room_id` ของ `fee_collections` อย่างเดียวแล้วลืม `SP.status='pending'`
    — บิลที่จ่ายครบแล้วจะถูกนับค้างอีกครั้ง
    """
    student_id = await conn.fetchval(
        """
        SELECT id FROM students
        WHERE room_id = $1 AND user_id = $2 AND status = 'active' AND deleted_at IS NULL
        ORDER BY id
        LIMIT 1
        """,
        room_id,
        user_id,
    )
    if student_id is None:
        # แอดมิน/ผู้ดูแลที่ไม่มีแถวนักเรียน — ยังเปิดหน้าหลักได้ แต่ไม่มี "ของฉัน" ให้สรุป
        return {"has_profile": False, "outstanding": 0.0, "unpaid_bills": 0}

    row = await conn.fetchrow(
        """
        SELECT
            COALESCE(SUM(FC.amount - COALESCE(SP.paid_amount, 0)), 0) AS outstanding,
            COUNT(*) AS unpaid_bills
        FROM student_payments SP
        JOIN fee_collections FC ON FC.id = SP.collection_id
        WHERE SP.student_id = $1
          AND SP.status = 'pending'
          AND FC.room_id = $2
        """,
        student_id,
        room_id,
    )
    return {
        "has_profile": True,
        "outstanding": float(row["outstanding"] or 0),
        "unpaid_bills": int(row["unpaid_bills"] or 0),
    }


async def _load_announcements(
    conn: asyncpg.Connection, *, room_id: int, user_id: int
) -> dict[str, Any]:
    """ประกาศที่ยังไม่อ่าน — ใช้ `_IS_UNREAD` ชุดเดียวกับ `announcement_service`

    ประกาศที่ถูกเก็บถาวรแล้วไม่ถูกนับ (หน้า `/announcements` ซ่อนมันโดยค่าเริ่มต้น)
    """
    count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM announcements a
        WHERE a.room_id = $1
          AND a.archived_at IS NULL
          AND EXISTS (
              SELECT 1 FROM notifications n
              WHERE n.room_id = a.room_id
                AND n.user_id = $2
                AND n.entity_type = 'announcement'
                AND n.entity_id = a.id::text
                AND n.read_at IS NULL
          )
        """,
        room_id,
        user_id,
    )
    return {"unread_count": int(count or 0)}


async def _load_schedule(
    conn: asyncpg.Connection, *, room_id: int, today: date
) -> dict[str, Any]:
    """ตารางเรียนของวันนี้ — ค่าเริ่มต้นรายสัปดาห์ + การแก้เฉพาะวัน (ถ้ามี)"""
    day_name = THAI_DAYS[today.weekday()]
    default = await conn.fetchrow(
        """
        SELECT attire, subjects
        FROM default_schedules
        WHERE room_id = $1 AND day_of_week = $2 AND deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        room_id,
        day_name,
    )
    override = await conn.fetchrow(
        """
        SELECT new_attire, note
        FROM schedule_overrides
        WHERE room_id = $1 AND target_date = $2 AND deleted_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        room_id,
        today,
    )

    attire = default["attire"] if default else None
    if override and override["new_attire"]:
        # ล็อกคำเดียวกับ `ClassroomService.get_daily_summary` — สองที่ต้องอ่านเหมือนกัน
        attire = f"🚨 {override['new_attire']} (กรณีพิเศษ)"

    return {
        "day_of_week": day_name,
        "attire": attire,
        "subjects": default["subjects"] if default else None,
        "override_note": override["note"] if override else None,
    }
