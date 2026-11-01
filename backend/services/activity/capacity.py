"""ความจุกิจกรรม + คิวสำรอง (P4.1)

ระบบนี้ **ผู้ดูแลห้องเป็นคนเพิ่มรายชื่อ** ไม่ใช่ผู้เรียนกดลงทะเบียนเอง ⇒ คิวสำรองเกิดตอน
"เพิ่มเกินความจุ" (เช่น ค่ายที่รับได้ 40 คน แต่เลือกมา 45) ไม่ใช่ตอน self-register

═══════════════════════════════════════════════════════════════════════════════
🔑 กติกาที่ล็อกไว้
═══════════════════════════════════════════════════════════════════════════════
1. **นั่งได้ = `confirmed` + `attended`** — `attended` คือข้อเท็จจริงที่เกิดแล้ว ห้ามลดลงเป็นคิวสำรอง
2. **capacity = NULL แปลว่าไม่จำกัด** — แถวเดิมทั้งหมดเป็น NULL ⇒ พฤติกรรมเดิมไม่เปลี่ยน
3. **การเพิ่มทุกทางล็อกแถวกิจกรรมด้วย `FOR UPDATE`** — กันสองคำขอพร้อมกันแย่งที่นั่งแล้วเกินเพดาน
   (นับ-แล้ว-แทรก ต้องอยู่ในวิกฤตเดียวกัน ไม่งั้นเทสต์ concurrency จะเจอ capacity+1)
4. **ลดความจุต่ำกว่าคนที่ยืนยันแล้ว = ปฏิเสธ 400** — ไม่เด้งคนออกเงียบ ๆ ให้ผู้ดูแลเลือกเองว่าใครออก
5. **เลื่อนคิว = เลื่อนจริง + แจ้งเตือนในระบบ** (กลุ่ม `activity`) ใน transaction เดียวกับการยกเลิก
   — ถ้าแจ้งเตือนล้ม การยกเลิกทั้งก้อน rollback (ไม่มีสภาพ "เลื่อนแล้วแต่ไม่รู้")

ไฟล์นี้เป็น mixin ล้วน ไม่มี SQL ของ endpoint ใด ๆ — ถูกเรียกจาก activities/participants/base
"""
from typing import List, Optional, Sequence, Tuple

import asyncpg

from core.exceptions import ActivityNotFoundError, ValidationError
from services.notification_service import notify_user
from .base import service_logger

# สถานะที่นับว่า "ได้ที่นั่งแล้ว"
SEATED_STATUSES: Tuple[str, ...] = ("confirmed", "attended")
WAITLISTED = "waitlisted"


def plan_seats(
    requested: Sequence[str],
    capacity: Optional[int],
    seated: int,
    next_queue: int,
) -> List[Tuple[str, Optional[int]]]:
    """จองที่นั่งแบบบริสุทธิ์ (ไม่แตะ DB) — คืน [(resolved_status, queue_position)]

    ใช้ทั้งตอนสร้างกิจกรรม (seated = 0 ในหน่วยความจำ) และตอนเพิ่มทีละคน/หลายคน
    (seated อ่านจาก DB ก่อนเรียก) ⇒ กติกาเดียวกันทุกทาง ไม่มีทางที่สองที่จะเพี้ยน
    """
    out: List[Tuple[str, Optional[int]]] = []
    for status in requested:
        if status == "cancelled":
            out.append(("cancelled", None))
            continue
        if status == WAITLISTED or status not in SEATED_STATUSES:
            # ขอเข้าคิวเอง (หรือสถานะอื่นที่ไม่ใช่ที่นั่ง) — รักษาคำขอ ไม่แอบเลื่อนขึ้น
            out.append((WAITLISTED, next_queue))
            next_queue += 1
            continue
        if capacity is None or seated < capacity:
            out.append((status, None))
            seated += 1
        else:
            out.append((WAITLISTED, next_queue))
            next_queue += 1
    return out


class CapacityMixin:
    @classmethod
    async def _lock_activity_capacity(
        cls, conn: asyncpg.Connection, room_id: int, activity_id: int
    ) -> Optional[int]:
        """ล็อกแถวกิจกรรม (จนจบ transaction) แล้วคืนความจุ — None = ไม่จำกัด"""
        row = await conn.fetchrow(
            "SELECT room_id, capacity FROM activities "
            "WHERE id = $1 AND deleted_at IS NULL FOR UPDATE",
            activity_id,
        )
        if not row or row["room_id"] != room_id:
            raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")
        return row["capacity"]

    @classmethod
    async def _capacity_counts(cls, conn: asyncpg.Connection, activity_id: int) -> dict:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status IN ('confirmed', 'attended')) AS seated,
                COUNT(*) FILTER (WHERE status = 'waitlisted')               AS waitlisted,
                COALESCE(MAX(queue_position) FILTER (WHERE status = 'waitlisted'), 0) AS max_queue
            FROM activity_participants
            WHERE activity_id = $1 AND deleted_at IS NULL
            """,
            activity_id,
        )
        return {
            "seated": int(row["seated"] or 0),
            "waitlisted": int(row["waitlisted"] or 0),
            "max_queue": int(row["max_queue"] or 0),
        }

    @classmethod
    async def _resolve_seats(
        cls,
        conn: asyncpg.Connection,
        activity_id: int,
        capacity: Optional[int],
        requested: Sequence[str],
    ) -> List[Tuple[str, Optional[int]]]:
        """อ่านจำนวนที่นั่งที่ใช้อยู่จริง แล้วจองให้ตามลำดับที่ส่งมา"""
        counts = await cls._capacity_counts(conn, activity_id)
        return plan_seats(requested, capacity, counts["seated"], counts["max_queue"] + 1)

    @classmethod
    async def _renumber_waitlist(cls, conn: asyncpg.Connection, activity_id: int) -> None:
        """อัดคิวให้เป็น 1..N — เรียกหลังเลื่อนคิว/ยกเลิก เพื่อไม่ให้เลขคิวมีรู"""
        await conn.execute(
            """
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY queue_position NULLS LAST, created_at, id) AS rn
                FROM activity_participants
                WHERE activity_id = $1 AND deleted_at IS NULL AND status = 'waitlisted'
            )
            UPDATE activity_participants ap
            SET queue_position = ranked.rn
            FROM ranked
            WHERE ap.id = ranked.id AND ap.queue_position IS DISTINCT FROM ranked.rn
            """,
            activity_id,
        )

    @classmethod
    async def _promote_waitlist(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        activity_id: int,
        *,
        capacity: Optional[int] = None,
        actor_identifier: str,
        client_source: str,
        user_name: str,
        freed_slots: Optional[int] = None,
        lock: bool = True,
    ) -> List[dict]:
        """เลื่อนคนจากคิวขึ้นเป็น `confirmed` เท่าที่ที่นั่งว่างอยู่ — เรียกภายใน transaction เท่านั้น

        `lock=True` (ค่าเริ่มต้น) = ล็อกแถวกิจกรรมเองแล้วอ่าน capacity
        ผู้ที่ล็อกแถวนี้ไปแล้ว (เช่น `_enforce_capacity` / ตอนแก้ความจุ) ให้ส่ง `capacity=`
        มาพร้อม `lock=False` — จะได้ไม่ต้องยิง `FOR UPDATE` ซ้ำ (ซ้ำไม่ผิด แต่เปล่า)

        `capacity is None` = ไม่จำกัดความจุ ⇒ เลื่อนได้ทั้งคิว (ตัดด้วย `freed_slots` ถ้าส่งมา)
        `freed_slots` = จำนวนที่นั่งที่เพิ่งว่าง (ตัดยอดไม่ให้เลื่อนเกินที่ควร)
        """
        if lock:
            capacity = await cls._lock_activity_capacity(conn, room_id, activity_id)

        counts = await cls._capacity_counts(conn, activity_id)
        slots = counts["waitlisted"] if capacity is None else capacity - counts["seated"]
        if freed_slots is not None:
            slots = min(slots, freed_slots)
        if slots <= 0:
            return []

        title = await conn.fetchval("SELECT title FROM activities WHERE id = $1", activity_id) or "กิจกรรม"
        rows = await conn.fetch(
            """
            SELECT ap.id, ap.student_id, ap.queue_position, s.user_id, s.student_no
            FROM activity_participants ap
            JOIN students s ON s.id = ap.student_id
            WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL AND ap.status = 'waitlisted'
            ORDER BY ap.queue_position NULLS LAST, ap.created_at, ap.id
            LIMIT $2
            FOR UPDATE OF ap
            """,
            activity_id, slots,
        )

        promoted: List[dict] = []
        for row in rows:
            await conn.execute(
                "UPDATE activity_participants "
                "SET status = 'confirmed', queue_position = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = $1",
                row["id"],
            )
            promoted.append({
                "participant_id": row["id"],
                "student_no": row["student_no"],
                "queue_position": row["queue_position"],
            })
            # 🔔 แจ้งเตือนคนที่เพิ่งได้ที่นั่ง (ถ้าผูกบัญชีแล้ว) — ต้องอยู่ใน transaction เดียวกัน
            if row["user_id"]:
                await notify_user(
                    conn,
                    room_id=room_id,
                    user_id=row["user_id"],
                    group_type="activity",
                    type="activity_waitlist_promoted",
                    title="ถึงคิวของคุณแล้ว",
                    body=f"ที่ว่างในกิจกรรม “{title}” — คุณถูกเลื่อนขึ้นจากคิวสำรองแล้ว",
                    entity_type="activity",
                    entity_id=activity_id,
                    url=f"/activities/{activity_id}",
                )
            await service_logger.log(
                conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                client_source=client_source, room_id=room_id,
                entity_type="ACTIVITY_PARTICIPANT", entity_id=str(row["id"]), status="success",
                old_values={"status": WAITLISTED, "queue_position": row["queue_position"]},
                new_values={"status": "confirmed", "promoted_from_waitlist": True,
                            "recorded_by": user_name},
                endpoint_or_command="promote_waitlist",
            )

        if promoted:
            await cls._renumber_waitlist(conn, activity_id)
        return promoted

    @classmethod
    async def _free_seats_after_removal(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        activity_id: int,
        *,
        actor_identifier: str,
        client_source: str,
        user_name: str,
        freed_slots: int,
    ) -> List[dict]:
        """หลังนำคนออก/ยกเลิก — เลื่อนคิวขึ้นเท่ากับที่นั่งที่ว่าง"""
        return await cls._promote_waitlist(
            conn, room_id, activity_id,
            capacity=None,
            actor_identifier=actor_identifier,
            client_source=client_source,
            user_name=user_name,
            freed_slots=freed_slots,
        )

    @classmethod
    async def _enforce_capacity(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        activity_id: int,
        *,
        actor_identifier: str,
        client_source: str,
        user_name: str,
    ) -> dict:
        """กันเกินเพดานหลัง "แทนที่ผู้เข้าร่วมทั้งชุด" (PATCH กิจกรรม) — คืน {demoted, promoted}

        ไม่ลด `attended` เด็ดขาด; เลือกคนที่ `confirmed` ใหม่ที่สุดก่อนลงคิว
        """
        capacity = await cls._lock_activity_capacity(conn, room_id, activity_id)
        result = {"demoted": [], "promoted": []}
        if capacity is None:
            return result

        counts = await cls._capacity_counts(conn, activity_id)
        excess = counts["seated"] - capacity
        if excess > 0:
            rows = await conn.fetch(
                """
                SELECT id, student_no, user_id FROM (
                    SELECT ap.id, s.student_no, s.user_id
                    FROM activity_participants ap
                    JOIN students s ON s.id = ap.student_id
                    WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL AND ap.status = 'confirmed'
                    ORDER BY ap.created_at DESC, ap.id DESC
                    LIMIT $2
                ) AS newest_confirmed
                """,
                activity_id, excess,
            )
            # ให้คนที่ถูกถอดทีหลัง (เก่ากว่า) อยู่คิวก่อน — กลับลำดับเป็นเก่า→ใหม่
            next_pos = counts["max_queue"]
            for row in reversed(rows):
                next_pos += 1
                await conn.execute(
                    "UPDATE activity_participants "
                    "SET status = 'waitlisted', queue_position = $2, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = $1",
                    row["id"], next_pos,
                )
                result["demoted"].append({"participant_id": row["id"], "student_no": row["student_no"]})
                await service_logger.log(
                    conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=room_id,
                    entity_type="ACTIVITY_PARTICIPANT", entity_id=str(row["id"]), status="success",
                    old_values={"status": "confirmed"},
                    new_values={"status": WAITLISTED, "queue_position": next_pos,
                                "reason": "over_capacity", "recorded_by": user_name},
                    endpoint_or_command="enforce_capacity",
                )
            if result["demoted"]:
                await cls._renumber_waitlist(conn, activity_id)
                counts = await cls._capacity_counts(conn, activity_id)

        # เผื่อมีการนำคนออกในชุดเดียวกัน — เติมที่นั่งที่ว่างกลับให้คิว
        if counts["seated"] < capacity:
            result["promoted"] = await cls._promote_waitlist(
                conn, room_id, activity_id,
                capacity=capacity, lock=False,
                actor_identifier=actor_identifier,
                client_source=client_source,
                user_name=user_name,
            )
        return result

    @staticmethod
    def validate_capacity_change(new_capacity: Optional[int], seated: int) -> None:
        """เพดานใหม่ต้องไม่ต่ำกว่าคนที่ยืนยัน/มาแล้ว — ให้ผู้ดูแลเลือกเองว่าใครออก"""
        if new_capacity is not None and new_capacity < seated:
            raise ValidationError(
                f"ความจุใหม่ ({new_capacity}) น้อยกว่าจำนวนผู้เข้าร่วมที่ยืนยันแล้ว ({seated}) "
                "— นำผู้เข้าร่วมออกก่อน หรือตั้งความจุให้ไม่ต่ำกว่าจำนวนนั้น"
            )
