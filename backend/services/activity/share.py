"""🔗 ลิงก์แชร์กิจกรรม (P4.3)

หน้าอ่านอย่างเดียวที่ **ไม่ต้องล็อกอิน** — สำหรับส่งให้ผู้ปกครอง/นักเรียนดูรายละเอียดงาน
(เช่น ในกลุ่ม LINE) โดยไม่ต้องมีบัญชีในระบบ

═══════════════════════════════════════════════════════════════════════════════
🔑 กติกาที่ล็อกไว้
═══════════════════════════════════════════════════════════════════════════════
1. **โทเคนเก็บใน DB ไม่ใช่เซ็นแบบ stateless** — เพราะต้อง *เพิกถอนได้ทันที* (ตั้ง NULL)
   ถ้าเซ็นด้วย SECRET_KEY อย่างเดียว การเพิกถอนต้องหมุนกุญแจทั้งระบบ ซึ่งทำให้ลิงก์อื่นตายหมด
2. **หนึ่งกิจกรรมมีลิงก์ได้หนึ่งลิงก์** — `POST` ซ้ำ = คืนลิงก์เดิม (idempotent) จนกว่าจะ
   ส่ง `rotate=true` หรือ `DELETE`; partial unique index กันโทเคนชนกันข้ามกิจกรรม
3. **ออก/เพิกถอน = `MANAGE_ACTIVITIES`** — ส่วน *อ่าน* เปิดสาธารณะด้วยโทเคนเท่านั้น
4. **ไม่มี PII ในหน้าสาธารณะ** — ไม่มีชื่อผู้เข้าร่วม เบอร์โทร หรือข้อมูลโปรไฟล์ใด ๆ
   เปิดเผยแค่ "งานคืออะไร จัดวันไหน ที่ไหน รับกี่คน และเหลือกี่ที่" (นับเฉพาะตัวเลข)
5. **โทเคนไม่เคยถูกเขียนลง audit** — audit เก็บแค่ "มีลิงก์อยู่แล้วหรือไม่" เพื่อไม่ให้
   ความลับไปอยู่ในตารางที่คนอื่นอ่านได้
"""
import secrets
import time
from datetime import datetime
from typing import Optional

import asyncpg

from core.exceptions import ActivityNotFoundError
from core.rbac import require_permission
from .base import service_logger
from .constants import ACTIVITY_CATEGORY_LABELS, ACTIVITY_STATUS_LABELS, THAI_TZ

# ยาว 32 ไบต์ ≈ 43 ตัวอักษร base64url — เดาไม่ได้จริง และยังพอดีกับ URL
SHARE_TOKEN_BYTES = 32
SHARE_TOKEN_MAX_LEN = 128
SHARE_PATH_PREFIX = "/share/activity/"


def new_share_token() -> str:
    return secrets.token_urlsafe(SHARE_TOKEN_BYTES)


class ShareMixin:
    @classmethod
    async def issue_share_link(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        rotate: bool = False,
    ) -> dict:
        """สร้าง/คืนลิงก์แชร์ของกิจกรรม — `rotate=True` = ออกโทเคนใหม่ (ลิงก์เก่าตายทันที)"""
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_ACTIVITIES")

                    row = await conn.fetchrow(
                        "SELECT id, share_token FROM activities "
                        "WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        activity_id, target_room_id,
                    )
                    if not row:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    existing = row["share_token"]
                    if existing and not rotate:
                        # 🔁 idempotent — กดซ้ำได้ลิงก์เดิม (ผู้ใช้กดแชร์หลายรอบโดยไม่ทำลิงก์เก่าตาย)
                        return {
                            "activity_id": activity_id,
                            "share_token": existing,
                            "path": SHARE_PATH_PREFIX + existing,
                            "rotated": False,
                        }

                    token = new_share_token()
                    await conn.execute(
                        "UPDATE activities SET share_token = $3, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        activity_id, target_room_id, token,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="SHARE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                        old_values={"has_share_link": existing is not None},
                        # 🔒 ไม่เขียนโทเคนลง audit — เก็บว่ามี/หมุนเท่านั้น
                        new_values={"has_share_link": True, "rotated": existing is not None},
                        endpoint_or_command="issue_share_link", execution_time_ms=exec_time,
                    )
                    return {
                        "activity_id": activity_id,
                        "share_token": token,
                        "path": SHARE_PATH_PREFIX + token,
                        "rotated": existing is not None,
                    }
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="SHARE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), endpoint_or_command="issue_share_link",
                    execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def revoke_share_link(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        user_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
    ) -> dict:
        """เพิกถอนลิงก์ — ลิงก์ที่ส่งออกไปแล้วเปิดไม่ได้อีก (เรียกซ้ำได้ ไม่ error)"""
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_ACTIVITIES")

                    row = await conn.fetchrow(
                        "SELECT id, share_token FROM activities "
                        "WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        activity_id, target_room_id,
                    )
                    if not row:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    had_link = row["share_token"] is not None
                    if had_link:
                        await conn.execute(
                            "UPDATE activities SET share_token = NULL, updated_at = CURRENT_TIMESTAMP "
                            "WHERE id = $1 AND room_id = $2",
                            activity_id, target_room_id,
                        )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="REVOKE_SHARE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                        old_values={"has_share_link": had_link},
                        new_values={"has_share_link": False},
                        endpoint_or_command="revoke_share_link", execution_time_ms=exec_time,
                    )
                    return {"activity_id": activity_id, "revoked": had_link}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="REVOKE_SHARE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), endpoint_or_command="revoke_share_link",
                    execution_time_ms=exec_time,
                )
            raise e

    @classmethod
    async def get_shared_activity(cls, pool: asyncpg.Pool, token: str) -> dict:
        """อ่านกิจกรรมจากโทเคน — **ไม่ต้อง auth** และไม่คืนข้อมูลส่วนบุคคลใด ๆ

        ⚠️ ไม่เขียน audit โดยเจตนา: route นี้เปิดสาธารณะและถูกเปิดบ่อย (ส่งในกลุ่มแชท)
        การบันทึกทุกครั้งจะกลบเหตุการณ์จริงใน `audit_logs` — และไม่มี actor ให้บันทึกอยู่แล้ว
        """
        if not token or len(token) > SHARE_TOKEN_MAX_LEN:
            raise ActivityNotFoundError("ไม่พบกิจกรรมนี้ — ลิงก์อาจถูกเพิกถอนหรือไม่ถูกต้อง")

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.id, a.title, a.description, a.activity_date, a.base_hours, a.status,
                       a.capacity, a.category, a.registration_deadline,
                       r.room_name,
                       (SELECT COUNT(*) FROM activity_participants ap
                          WHERE ap.activity_id = a.id AND ap.deleted_at IS NULL
                            AND ap.status IN ('confirmed', 'attended')) AS confirmed_count,
                       (SELECT COUNT(*) FROM activity_participants ap
                          WHERE ap.activity_id = a.id AND ap.deleted_at IS NULL
                            AND ap.status = 'waitlisted') AS waitlisted_count
                FROM activities a
                JOIN rooms r ON r.id = a.room_id
                WHERE a.share_token = $1 AND a.deleted_at IS NULL AND r.deleted_at IS NULL
                """,
                token,
            )

        if not row:
            raise ActivityNotFoundError("ไม่พบกิจกรรมนี้ — ลิงก์อาจถูกเพิกถอนหรือไม่ถูกต้อง")

        confirmed = int(row["confirmed_count"] or 0)
        capacity = row["capacity"]
        deadline = row["registration_deadline"]
        status = row["status"]
        # "ยังเปิดรับ" = สถานะยังไม่จบ และยังไม่เลยวันปิดรับ (นับตามวันที่ไทย ไม่ใช่ UTC)
        is_open = status in ("upcoming", "ongoing") and (
            deadline is None or datetime.now(THAI_TZ).date() <= deadline
        )

        return {
            "activity_id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "activity_date": row["activity_date"],
            "base_hours": float(row["base_hours"] or 0),
            "status": status,
            "status_label": ACTIVITY_STATUS_LABELS.get(status, status),
            "category": row["category"],
            "category_label": ACTIVITY_CATEGORY_LABELS.get(row["category"] or ""),
            "registration_deadline": deadline,
            "is_registration_open": bool(is_open),
            "capacity": capacity,
            "confirmed_count": confirmed,
            "waitlisted_count": int(row["waitlisted_count"] or 0),
            "seats_left": None if capacity is None else max(0, int(capacity) - confirmed),
            "room_name": row["room_name"],
        }
