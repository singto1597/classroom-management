"""📣 เตือนผู้ค้างชำระรายวัน — in-app ต่อคน + Discord สรุปต่อห้อง (Phase 6)

═══════════════════════════════════════════════════════════════════════════════
🔁 หลักการ
═══════════════════════════════════════════════════════════════════════════════
1. **ใช้ predicate "บิลเปิด" มาตรฐานเดียวทั้งระบบ** (`_open_bill_predicate`)
   ⇒ เตือนเฉพาะหนี้ที่ยังมีจริง: บิลที่จ่ายครบ/ถูกลบ/โปรเจกต์ถูกลบ หลุดออกเอง
2. **นับเฉพาะบิลที่ `due_date <= วันนี้ + 3`** — "เลยกำหนด" + "ครบกำหนดใน 3 วัน"
   ตามข้อตกลง #25
3. **กันซ้ำที่ DB ไม่ใช่ที่ memory** — `reminder_dispatch_log` มี unique
   `(room_id, dispatch_key, channel)` ⇒ INSERT ... ON CONFLICT DO NOTHING RETURNING id
   เป็นการ "จองสิทธิ์ส่ง" ที่ atomic: worker ตาย/รีสตาร์ท/รันซ้ำวันเดียวไม่มีทางส่งซ้ำ
4. **in-app แยกต่อนักเรียน** (คีย์ `inapp:{user_id}:{date}`) · **Discord วันละชุดต่อห้อง**
   (คีย์ `discord:digest:{date}`) — อย่างหลังยอมรับว่ารายชื่อ+ยอดเป็นข้อมูลสาธารณะในห้อง
   ตามข้อตกลง #21
5. **ไม่มีรายการ = ไม่ส่งอะไรเลย** — ไม่มีข้อความ "วันนี้ไม่มีใครค้าง" (spam)

⚠️ `reminder_dispatch_log` ถูกสร้างใน migration 0010 — worker ที่บูตก่อน migration
   ต้องรอ (ดู `_is_missing_schema_error` ใน workers/finance_reminder_worker.py)
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

import asyncpg

from services.action_service import ActionService
from services.notification_service import notify_user

from .constants import COLLECTION_KIND_PROJECT

# จำนวนวันล่วงหน้าที่ถือว่า "ใกล้ครบกำหนด"
REMINDER_LOOKAHEAD_DAYS = 3

# จำนวนนักเรียนสูงสุดต่อข้อความ Discord หนึ่งชุด — embed มีเพดานความยาว ~4,096 ตัวอักษร
# ⇒ 20 คนโดยมีชื่อ+ยอดต่อบรรทัดยังเหลือที่ว่างมาก และอ่านง่ายบนมือถือ
REMINDER_DISCORD_CHUNK_SIZE = 20

# จำนวนรายการสูงสุดที่แสดงใน body ของแจ้งเตือนในแอป (ที่เหลือสรุปเป็น "และอีก N")
INAPP_MAX_LINES = 5

CHANNEL_INAPP = "inapp"
CHANNEL_DISCORD = "discord"

_EPS = 0.005


def _student_name(row) -> str:
    """ไทย → อังกฤษ → "นักเรียน" แล้วต่อชื่อเล่นในวงเล็บ (รูปแบบเดียวกับทั้งโมดูลการเงิน)"""
    name = row["first_name"] or row["first_name_en"] or "นักเรียน"
    if row["nickname"]:
        name += f" ({row['nickname']})"
    return name


class RemindersMixin:
    # ─────────────────────────────────────────────────────────────────────────
    # อ่านข้อมูล (ไม่มี side effect — เทสต์เรียกตรงได้)
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    async def _collect_reminder_bills(
        cls,
        conn: asyncpg.Connection,
        *,
        as_of: date,
        room_id: Optional[int] = None,
    ) -> list:
        """บิลเปิดที่ถึง/ใกล้ถึงกำหนด ณ `as_of` — เรียงตามห้อง/เลขที่/กำหนดชำระ"""
        params: list = [as_of + timedelta(days=REMINDER_LOOKAHEAD_DAYS), _EPS]
        room_clause = ""
        if room_id is not None:
            params.append(room_id)
            room_clause = f"AND FC.room_id = ${len(params)}"

        return await conn.fetch(
            f"""
            SELECT FC.room_id,
                   SP.id AS payment_id,
                   SP.student_id,
                   S.user_id,
                   S.student_no,
                   U.first_name,
                   U.nickname,
                   U.first_name_en,
                   FC.title,
                   FC.due_date,
                   (FC.amount - COALESCE(SP.paid_amount, 0) - COALESCE(SP.written_off_amount, 0)) AS outstanding,
                   FC.collection_kind,
                   F.id AS fine_id
            FROM student_payments SP
            JOIN fee_collections FC ON FC.id = SP.collection_id
            JOIN students S ON S.id = SP.student_id AND S.deleted_at IS NULL
            LEFT JOIN v_student_profiles U ON U.student_id = S.id
            LEFT JOIN fines F
                   ON F.student_payment_id = SP.id AND F.deleted_at IS NULL
            WHERE {cls._open_bill_predicate()}
              AND FC.due_date IS NOT NULL
              AND FC.due_date <= $1
              AND (FC.amount - COALESCE(SP.paid_amount, 0) - COALESCE(SP.written_off_amount, 0)) > $2
              {room_clause}
            ORDER BY FC.room_id, S.student_no, FC.due_date, FC.id
            """,
            *params,
        )

    @staticmethod
    def _group_reminder_bills(bills, as_of: date) -> list[dict]:
        """จัดกลุ่มบิลเป็น "ต่อนักเรียน" — ยอดรวม/จำนวนเลยกำหนด/จำนวนใกล้ครบ + รายการย่อย"""
        students: dict[int, dict] = {}
        for row in bills:
            sid = int(row["student_id"])
            entry = students.get(sid)
            if entry is None:
                entry = {
                    "student_id": sid,
                    "user_id": int(row["user_id"]) if row["user_id"] else None,
                    "student_no": row["student_no"],
                    "name": _student_name(row),
                    "total": 0.0,
                    "overdue_count": 0,
                    "due_soon_count": 0,
                    "items": [],
                }
                students[sid] = entry

            # ⚠️ Decimal → float ก่อนบวกเสมอ (กฎทั้งโมดูลการเงิน)
            amount = round(float(row["outstanding"]), 2)
            due: date = row["due_date"]
            overdue_days = max((as_of - due).days, 0)
            entry["total"] = round(entry["total"] + amount, 2)
            if due < as_of:
                entry["overdue_count"] += 1
            else:
                entry["due_soon_count"] += 1
            entry["items"].append(
                {
                    "payment_id": row["payment_id"],
                    "title": row["title"],
                    "amount": amount,
                    "due_date": due.isoformat(),
                    "overdue_days": overdue_days,
                    "collection_kind": row["collection_kind"] or COLLECTION_KIND_PROJECT,
                    "fine_id": row["fine_id"],
                }
            )

        return sorted(students.values(), key=lambda s: (s["student_no"] or 0, s["student_id"]))

    @staticmethod
    def _reminder_body(student: dict) -> str:
        """ข้อความในแอป: รายการแรก ๆ + สรุปที่เหลือ (body ที่ยาวเกินถูกตัดใน UI อยู่แล้ว)"""
        lines: list[str] = []
        for item in student["items"][:INAPP_MAX_LINES]:
            text = f"• {item['title']} — {item['amount']:,.2f} บาท"
            if item["overdue_days"] > 0:
                text += f" (เลยกำหนด {item['overdue_days']} วัน)"
            else:
                text += f" (ครบกำหนด {item['due_date']})"
            lines.append(text)
        remaining = len(student["items"]) - INAPP_MAX_LINES
        if remaining > 0:
            lines.append(f"…และอีก {remaining} รายการ")
        return "\n".join(lines)

    @staticmethod
    def _build_reminder_digest(students: list[dict], as_of: date) -> list[dict]:
        """ชุด payload Discord — แบ่งเป็นหลายส่วนถ้ารายชื่อเยอะ (ผู้เรียก publish ทีละส่วน)

        `total_students`/`total_amount` เป็นยอดของ **ทั้งห้อง** ซ้ำทุกส่วน
        ⇒ แม้ส่วนหลังหลุด บอทยังรายงานยอดรวมถูก
        """
        entries = [
            {
                "student_no": s["student_no"],
                "name": s["name"],
                "total": s["total"],
                "overdue_count": s["overdue_count"],
                "due_soon_count": s["due_soon_count"],
            }
            for s in students
        ]
        total_amount = round(sum(s["total"] for s in students), 2)

        chunks = [
            entries[i : i + REMINDER_DISCORD_CHUNK_SIZE]
            for i in range(0, len(entries), REMINDER_DISCORD_CHUNK_SIZE)
        ] or [[]]

        return [
            {
                "as_of": as_of.isoformat(),
                "total_students": len(entries),
                "total_amount": total_amount,
                "students": chunk,
                "part": index + 1,
                "total_parts": len(chunks),
            }
            for index, chunk in enumerate(chunks)
        ]

    @staticmethod
    async def _claim_dispatch(
        conn: asyncpg.Connection,
        *,
        room_id: int,
        dispatch_key: str,
        channel: str,
        payload: dict,
    ) -> Optional[int]:
        """จองสิทธิ์ส่งของวันนี้ — คืน id ถ้าได้สิทธิ์, `None` ถ้าส่งไปแล้ว

        🔑 INSERT ... ON CONFLICT DO NOTHING RETURNING คือด่านกันซ้ำที่ atomic
        (สอง worker/สองรอบรันพร้อมกัน — มีตัวเดียวที่ได้แถวกลับมา)
        """
        return await conn.fetchval(
            """
            INSERT INTO reminder_dispatch_log (room_id, dispatch_key, channel, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (room_id, dispatch_key, channel) DO NOTHING
            RETURNING id
            """,
            room_id,
            dispatch_key,
            channel,
            json.dumps(payload, ensure_ascii=False, default=str),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ส่งจริง — เรียกจาก worker วันละครั้ง
    # ─────────────────────────────────────────────────────────────────────────
    @classmethod
    async def dispatch_daily_reminders(
        cls,
        pool: asyncpg.Pool,
        *,
        as_of: date,
        room_id: Optional[int] = None,
    ) -> dict:
        """ส่งเตือนของวัน `as_of` (Asia/Bangkok) — ปลอดภัยต่อการเรียกซ้ำหลายรอบ

        คืนสถิติที่ assert ได้: `in_app_sent` / `in_app_duplicate` /
        `discord_sent` / `discord_duplicate` / `students` / `total_amount`
        """
        stats = {
            "as_of": as_of.isoformat(),
            "rooms_with_debt": 0,
            "students": 0,
            "total_amount": 0.0,
            "in_app_sent": 0,
            "in_app_duplicate": 0,
            "discord_sent": 0,
            "discord_duplicate": 0,
        }
        # ⚠️ publish Discord **หลัง commit** — เก็บไว้ก่อนแล้วยิงทีหลัง
        pending_publishes: list[tuple[int, dict]] = []

        async with pool.acquire() as conn:
            async with conn.transaction():
                bills = await cls._collect_reminder_bills(
                    conn, as_of=as_of, room_id=room_id
                )
                if not bills:
                    return stats

                bills_by_room: dict[int, list] = {}
                for row in bills:
                    bills_by_room.setdefault(int(row["room_id"]), []).append(row)
                stats["rooms_with_debt"] = len(bills_by_room)

                for rid, room_bills in bills_by_room.items():
                    students = cls._group_reminder_bills(room_bills, as_of)
                    stats["students"] += len(students)
                    stats["total_amount"] = round(
                        stats["total_amount"] + sum(s["total"] for s in students), 2
                    )

                    # ── in-app: คนละแจ้งเตือน นักเรียนเห็นเฉพาะบิลของตัวเอง
                    for student in students:
                        if not student["user_id"]:
                            continue
                        key = f"inapp:{student['user_id']}:{as_of.isoformat()}"
                        claimed = await cls._claim_dispatch(
                            conn,
                            room_id=rid,
                            dispatch_key=key,
                            channel=CHANNEL_INAPP,
                            payload={
                                "student_id": student["student_id"],
                                "count": len(student["items"]),
                                "total": student["total"],
                            },
                        )
                        if claimed is None:
                            stats["in_app_duplicate"] += 1
                            continue

                        await notify_user(
                            conn,
                            room_id=rid,
                            user_id=student["user_id"],
                            group_type="finance",
                            type="debt_reminder",
                            title=(
                                f"มีบิลค้างชำระ {len(student['items'])} รายการ "
                                f"รวม {student['total']:,.2f} บาท"
                            ),
                            body=cls._reminder_body(student),
                            entity_type="student",
                            entity_id=student["student_id"],
                            url="/finance/my-debts",
                        )
                        stats["in_app_sent"] += 1

                    # ── Discord: วันละชุดต่อห้อง (ไม่ @everyone)
                    server_id = await cls._get_room_server_id(conn, rid)
                    if not server_id:
                        continue
                    key = f"discord:digest:{as_of.isoformat()}"
                    claimed = await cls._claim_dispatch(
                        conn,
                        room_id=rid,
                        dispatch_key=key,
                        channel=CHANNEL_DISCORD,
                        payload={
                            "total_students": len(students),
                            "total_amount": round(
                                sum(s["total"] for s in students), 2
                            ),
                        },
                    )
                    if claimed is None:
                        stats["discord_duplicate"] += 1
                        continue
                    stats["discord_sent"] += 1
                    for chunk in cls._build_reminder_digest(students, as_of):
                        pending_publishes.append((int(server_id), chunk))

        for server_id, chunk in pending_publishes:
            await ActionService.notify_debt_reminder(server_id=server_id, **chunk)

        return stats
