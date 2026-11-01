"""ไทม์ไลน์และสถิติ "ของฉัน" — P3.3

═══════════════════════════════════════════════════════════════════════════════
ทำไมไม่มีงาน/โน้ตในฟีดนี้
═══════════════════════════════════════════════════════════════════════════════
`tasks` เป็นของทั้งห้อง (ไม่มีคอลัมน์ผู้ทำ/ผู้ปิดงาน) และ `daily_notes` ไม่มีผู้เขียน
⇒ "งานที่ฉันทำเสร็จ" และ "โน้ตที่ฉันเขียน" **ไม่มีข้อมูลรองรับ** ถ้าฝืนทำ จะได้ตัวเลข
ที่แต่งขึ้น ซึ่งแย่กว่าไม่มีตัวเลข
⇒ ฟีดนับเฉพาะเหตุการณ์ที่ผูกกับ `students.user_id` ได้จริง:
   • payment  — ใบเสร็จ (`finance_receipts`) ที่ออกให้ฉัน
   • activity — กิจกรรม (`activity_participants`) ที่ฉันเข้าร่วม
   (P3.4 จะเพิ่ม bookmark เข้ามาทางตารางของมันเอง)

═══════════════════════════════════════════════════════════════════════════════
การแบ่งหน้า: keyset 3 คีย์ ไม่ใช่ offset
═══════════════════════════════════════════════════════════════════════════════
แหล่งข้อมูลสองตารางมี id คนละชุด ⇒ ใช้ `(happened_at, kind, entity_id)` เป็นคีย์เรียง
`ORDER BY happened_at DESC, kind DESC, entity_id DESC` และกรองหน้าถัดไปด้วย
`(happened_at, kind, entity_id) < (cursor…)` — แถวที่ถูกเพิ่ม/ลบระหว่างอ่านหน้า
จึงไม่ทำให้รายการซ้ำหรือหายเหมือน `OFFSET`

cursor เป็น opaque base64 — ฝั่งหน้าไม่ต้องรู้โครง (แต่ decode ผิด = 400 ไม่ใช่ 500)
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Optional

import asyncpg

from core.rbac import require_member

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

# ── แหล่งเหตุการณ์: ทุก branch ต้องมีคอลัมน์ชุดเดียวกันและชนิดเดียวกันเป๊ะ ──────
#    `sort_key` ไม่ได้ส่งออก — ใช้เรียง/แบ่งหน้าภายใน (kind คือส่วนที่แยกสองแหล่ง)
_EVENTS_SQL = """
WITH events AS (
    SELECT
        'payment'::text                        AS kind,
        R.id                                   AS entity_id,
        COALESCE(FC.title, 'ชำระเงิน')          AS title,
        R.receipt_no                           AS detail,
        COALESCE(R.event_at, R.issued_at)      AS happened_at,
        R.amount::float8                       AS amount,
        R.receipt_no                           AS reference,
        R.status                               AS status,
        NULL::date                             AS activity_date,
        ('/finance/receipts/' || R.receipt_no) AS url
    FROM finance_receipts R
    JOIN students S ON S.id = R.student_id AND S.user_id = $2 AND S.room_id = $1
    LEFT JOIN student_payments SP ON SP.id = R.student_payment_id
    LEFT JOIN fee_collections FC ON FC.id = SP.collection_id
    WHERE R.room_id = $1
      AND R.deleted_at IS NULL
      AND R.doc_type = 'receipt'
      AND R.status = 'active'

    UNION ALL

    SELECT
        'activity'::text,
        A.id,
        A.title,
        A.description,
        P.created_at,
        NULL::float8,
        NULL::text,
        P.status,
        A.activity_date,
        ('/activities/' || A.id)
    FROM activity_participants P
    JOIN activities A ON A.id = P.activity_id
    JOIN students S ON S.id = P.student_id AND S.user_id = $2
    WHERE A.room_id = $1
      AND A.deleted_at IS NULL
      AND P.deleted_at IS NULL
      AND P.status <> 'cancelled'
)
SELECT kind, entity_id, title, detail, happened_at, amount, reference, status,
       activity_date, url
FROM events
WHERE (
        $3::timestamptz IS NULL
        OR (happened_at, kind, entity_id) < ($3::timestamptz, $4::text, $5::integer)
      )
ORDER BY happened_at DESC, kind DESC, entity_id DESC
LIMIT $6
"""

_STATS_SQL = """
SELECT
    (SELECT COALESCE(SUM(R.amount), 0)
       FROM finance_receipts R
      WHERE R.student_id = $1 AND R.room_id = $2
        AND R.doc_type = 'receipt' AND R.status = 'active' AND R.deleted_at IS NULL
    ) AS paid_total,
    (SELECT COALESCE(SUM(P.earned_hours), 0)
       FROM activity_participants P
       JOIN activities A ON A.id = P.activity_id
      WHERE P.student_id = $1 AND A.room_id = $2
        AND P.deleted_at IS NULL AND P.status <> 'cancelled'
        AND A.deleted_at IS NULL
    ) AS activity_hours,
    (SELECT COUNT(*)
       FROM activity_participants P
       JOIN activities A ON A.id = P.activity_id
      WHERE P.student_id = $1 AND A.room_id = $2
        AND P.deleted_at IS NULL AND P.status <> 'cancelled'
        AND A.deleted_at IS NULL
    ) AS activities_joined,
    (SELECT COALESCE(SUM(FC.amount - COALESCE(SP.paid_amount, 0)), 0)
       FROM student_payments SP
       JOIN fee_collections FC ON FC.id = SP.collection_id
      WHERE SP.student_id = $1 AND SP.status = 'pending' AND FC.room_id = $2
    ) AS outstanding,
    (SELECT COUNT(*)
       FROM student_payments SP
       JOIN fee_collections FC ON FC.id = SP.collection_id
      WHERE SP.student_id = $1 AND SP.status = 'pending' AND FC.room_id = $2
    ) AS unpaid_bills,
    (SELECT COUNT(*) FROM tasks
      WHERE room_id = $2 AND deleted_at IS NULL AND status = 'done') AS room_tasks_done,
    (SELECT COUNT(*) FROM tasks
      WHERE room_id = $2 AND deleted_at IS NULL AND status = 'pending') AS room_tasks_pending
"""


def _encode_cursor(happened_at: datetime, kind: str, entity_id: int) -> str:
    raw = f"{happened_at.isoformat()}|{kind}|{entity_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str, int]:
    """decode cursor แบบ opaque — ผิดรูป = `ValueError` (router แปลเป็น 400)

    ⚠️ ต้องบังคับ `tzinfo is not None`: `timestamptz` กับ datetime ที่ไม่มี TZ
    เทียบกันไม่ได้ที่ Postgres — ถ้าปล่อยผ่านจะได้ 500 แทนข้อความที่อ่านรู้เรื่อง
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        ts_raw, kind, entity_raw = raw.split("|")
        happened_at = datetime.fromisoformat(ts_raw)
        entity_id = int(entity_raw)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("cursor ไม่ถูกต้อง — เริ่มจากหน้าแรกใหม่") from exc
    if happened_at.tzinfo is None or kind not in ("payment", "activity") or entity_id < 1:
        raise ValueError("cursor ไม่ถูกต้อง — เริ่มจากหน้าแรกใหม่")
    return happened_at, kind, entity_id


async def list_activity(
    pool: asyncpg.Pool, *, room_id: int, user_id: int, limit: int = DEFAULT_PAGE_SIZE,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    page_size = min(max(int(limit), 1), MAX_PAGE_SIZE)
    cursor_ts: Optional[datetime] = None
    cursor_kind: Optional[str] = None
    cursor_id: Optional[int] = None
    if cursor:
        cursor_ts, cursor_kind, cursor_id = _decode_cursor(cursor)

    async with pool.acquire() as conn:
        await require_member(conn, room_id, user_id)
        rows = await conn.fetch(
            _EVENTS_SQL, room_id, int(user_id), cursor_ts, cursor_kind, cursor_id, page_size + 1
        )

    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [
        {
            "kind": row["kind"],
            "entity_id": int(row["entity_id"]),
            "title": row["title"],
            "detail": row["detail"],
            "happened_at": row["happened_at"],
            "amount": float(row["amount"]) if row["amount"] is not None else None,
            "reference": row["reference"],
            "status": row["status"],
            "activity_date": row["activity_date"],
            "url": row["url"],
        }
        for row in rows
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last["happened_at"], last["kind"], int(last["entity_id"]))
    return {"items": items, "has_more": has_more, "next_cursor": next_cursor}


async def get_me_stats(pool: asyncpg.Pool, *, room_id: int, user_id: int) -> dict[str, Any]:
    """สถิติของฉันในห้องนี้ — snapshot เดียว (`repeatable_read` + `readonly`)

    ผู้ใช้ที่ไม่มีแถว `students` (แอดมิน/ผู้ดูแล) **ไม่ใช่ error** — ได้ `has_profile: False`
    และตัวเลขส่วนตัวเป็น 0 แต่ยังเห็นตัวเลขของห้อง (งานค้าง/งานเสร็จ) ได้
    """
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await require_member(conn, room_id, user_id)
            student_id = await conn.fetchval(
                """
                SELECT id FROM students
                WHERE room_id = $1 AND user_id = $2 AND status = 'active' AND deleted_at IS NULL
                ORDER BY id
                LIMIT 1
                """,
                room_id,
                int(user_id),
            )
            if student_id is None:
                room_row = await conn.fetchrow(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM tasks
                          WHERE room_id = $1 AND deleted_at IS NULL AND status = 'done') AS room_tasks_done,
                        (SELECT COUNT(*) FROM tasks
                          WHERE room_id = $1 AND deleted_at IS NULL AND status = 'pending') AS room_tasks_pending
                    """,
                    room_id,
                )
                return {
                    "has_profile": False,
                    "term": None,
                    "activities_joined": 0,
                    "activity_hours": 0.0,
                    "paid_total": 0.0,
                    "outstanding": 0.0,
                    "unpaid_bills": 0,
                    "room_tasks_done": int(room_row["room_tasks_done"] or 0),
                    "room_tasks_pending": int(room_row["room_tasks_pending"] or 0),
                }

            row = await conn.fetchrow(_STATS_SQL, student_id, room_id)

    return {
        "has_profile": True,
        "term": None,
        "activities_joined": int(row["activities_joined"] or 0),
        # NUMERIC จาก asyncpg เป็น Decimal — cast ก่อนเข้า Pydantic
        "activity_hours": float(row["activity_hours"] or 0),
        "paid_total": float(row["paid_total"] or 0),
        "outstanding": float(row["outstanding"] or 0),
        "unpaid_bills": int(row["unpaid_bills"] or 0),
        "room_tasks_done": int(row["room_tasks_done"] or 0),
        "room_tasks_pending": int(row["room_tasks_pending"] or 0),
    }
