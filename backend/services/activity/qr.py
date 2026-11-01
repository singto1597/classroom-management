"""เช็คอินด้วย QR (P4.2)

═══════════════════════════════════════════════════════════════════════════════
🎟️ รูปแบบบัตร (token)
═══════════════════════════════════════════════════════════════════════════════
    CLS-EVT1:<activity_id>:<participant_id>:<sig>

`sig = HMAC-SHA256(key, "<activity_id>:<participant_id>")` เป็น hex เต็มความยาว
- **ผูกกับกิจกรรม**: บัตรของกิจกรรมหนึ่งใช้กับอีกกิจกรรมไม่ได้ (ตรวจทั้งค่าใน token
  และกิจกรรมที่ยิงเข้ามา — สองชั้น)
- **ตรวจด้วย `hmac.compare_digest`** ไม่ใช่ `==` (กันการไล่เทียบทีละไบต์)
- **ไม่มีวันหมดอายุ** เพราะบัตรอาจถูกพิมพ์ติดป้ายชื่อ — ถ้าหมดอายุระหว่างงานคือความล้มเหลว
  ของงานจริง ยอมแลกด้วย: ออกบัตรได้เฉพาะผู้มี `MANAGE_ACTIVITIES` และทุกครั้งที่สแกน
  จะถูกบันทึกว่า "ใครกด" (`checked_in_by`) ⇒ บัตรที่หลุดต้องถูกใช้ผ่านบัญชีของทีมงาน

═══════════════════════════════════════════════════════════════════════════════
🔑 กุญแจ
═══════════════════════════════════════════════════════════════════════════════
ไม่สร้าง env var ใหม่ (เครื่อง production ต้องแก้ `.env` + redeploy ซึ่งไม่ควรเป็นเงื่อนไข
ของการทำฟีเจอร์) — ใช้ `settings.SECRET_KEY` ผสม label แยกโดเมน แล้ว sha256 ให้เป็นคีย์:

    sha256("cls-activity-qr:v1:" + SECRET_KEY)

⇒ เปลี่ยน `SECRET_KEY` = บัตรที่พิมพ์ไว้ทั้งหมดใช้ไม่ได้ (ต้องออกใหม่) — เขียนไว้ใน docs

═══════════════════════════════════════════════════════════════════════════════
🧾 ผลลัพธ์การสแกน (4 สถานะที่หน้าจอต้องแยก)
═══════════════════════════════════════════════════════════════════════════════
1. **สำเร็จ** — เพิ่งเช็คอินครั้งแรก
2. **ซ้ำ** — `already_checked_in = True` (HTTP 200 เหมือนกัน ไม่ใช่ error — สแกนพลาดบ่อย)
3. **เต็ม** — คนในคิวสำรองมา แต่ไม่มีที่นั่ง ⇒ 400 พร้อมบอกว่าต้องทำอะไร
4. **ยกเลิก** — ผู้เข้าร่วมถูกยกเลิกไปแล้ว ⇒ 400
"""
import hashlib
import hmac
import time
from typing import Optional

import asyncpg

from core.config import settings
from core.exceptions import (
    ActivityNotFoundError,
    ParticipantNotFoundError,
    ValidationError,
)
from core.rbac import require_permission
from .base import service_logger

QR_TOKEN_PREFIX = "CLS-EVT1"


def _signing_key() -> bytes:
    """คีย์ HMAC ของบัตรกิจกรรม (แยกโดเมนจาก JWT/API key ด้วย label)"""
    material = f"cls-activity-qr:v1:{settings.SECRET_KEY}".encode("utf-8")
    return hashlib.sha256(material).digest()


def _signature(activity_id: int, participant_id: int) -> str:
    payload = f"{activity_id}:{participant_id}".encode("utf-8")
    return hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()


def build_qr_token(activity_id: int, participant_id: int) -> str:
    """สร้างบัตรของ (กิจกรรม, ผู้เข้าร่วม) — เรียกได้ทั้งตอนออกบัตรและตอนตรวจ"""
    return f"{QR_TOKEN_PREFIX}:{int(activity_id)}:{int(participant_id)}:{_signature(activity_id, participant_id)}"


def parse_qr_token(token: str, expected_activity_id: int) -> int:
    """ตรวจบัตรแล้วคืน participant_id — ผิดรูปแบบ/ลายเซ็นไม่ตรง/คนละกิจกรรม = ValidationError

    ทุกกรณีที่ล้มเหลวใช้ข้อความเดียวกัน (ไม่บอกว่าผิดที่ส่วนไหน) — กันการเดาโครงสร้างบัตร
    """
    bad = ValidationError("บัตร QR ไม่ถูกต้องหรือไม่ใช่ของกิจกรรมนี้")
    if not isinstance(token, str):
        raise bad
    parts = token.strip().split(":")
    if len(parts) != 4 or parts[0] != QR_TOKEN_PREFIX:
        raise bad
    try:
        activity_id = int(parts[1])
        participant_id = int(parts[2])
    except (TypeError, ValueError):
        raise bad
    if activity_id != int(expected_activity_id):
        raise bad
    if not hmac.compare_digest(parts[3], _signature(activity_id, participant_id)):
        raise bad
    return participant_id


class QrCheckinMixin:
    @classmethod
    async def list_checkin_qr_tokens(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """ออกบัตรของทุกคนในกิจกรรม (ผู้จัดการเท่านั้น) — ใช้ทำหน้าจอ/พิมพ์ป้ายชื่อ"""
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                if actor_user_id is not None:
                    await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                activity = await cls._fetch_activity_row(conn, target_room_id, activity_id)
                if not activity:
                    raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                rows = await conn.fetch(
                    """
                    SELECT ap.id, ap.status, ap.queue_position, ap.checked_in_at,
                           s.student_no, u.first_name, u.last_name
                    FROM activity_participants ap
                    JOIN students s ON s.id = ap.student_id
                    LEFT JOIN v_student_profiles u ON u.student_id = s.id
                    WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL AND ap.status <> 'cancelled'
                    ORDER BY s.student_no ASC
                    """,
                    activity_id,
                )

                codes = [
                    {
                        "participant_id": row["id"],
                        "student_no": row["student_no"],
                        "full_name": " ".join(filter(None, [row["first_name"], row["last_name"]])),
                        "status": row["status"],
                        "queue_position": row["queue_position"],
                        "checked_in_at": row["checked_in_at"],
                        "token": build_qr_token(activity_id, row["id"]),
                    }
                    for row in rows
                ]

                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="success",
                    new_values={"issued_codes": len(codes)},
                    endpoint_or_command="list_checkin_qr_tokens",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
                return {"activity_id": activity_id, "title": activity["title"], "codes": codes}
        except Exception as e:
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY", entity_id=str(activity_id), status="failed",
                    error_detail=str(e), endpoint_or_command="list_checkin_qr_tokens",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
            raise e

    @classmethod
    async def checkin_by_qr(
        cls,
        pool: asyncpg.Pool,
        activity_id: int,
        user_name: str,
        client_source: str,
        actor_identifier: str,
        token: Optional[str] = None,
        participant_id: Optional[int] = None,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        actor_user_id: Optional[int] = None,
    ) -> dict:
        """สแกนบัตร (หรือส่ง participant_id ตรง ๆ) แล้วทำเครื่องหมาย "มาแล้ว"

        รับได้ทั้ง token และ participant_id — หน้าจอใช้ participant_id เป็นทางถอย
        เมื่อกล้องถูกปฏิเสธ (โหมดกรอกรหัส/กดชื่อในลิสต์)
        """
        start_time = time.time()
        target_room_id = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls._resolve_room_id(conn, server_id, room_id)
                    if actor_user_id is not None:
                        await require_permission(conn, target_room_id, actor_user_id, "MANAGE_ACTIVITIES")

                    if await cls._get_activity_room(conn, activity_id) != target_room_id:
                        raise ActivityNotFoundError(f"ไม่พบกิจกรรม ID: {activity_id}")

                    # 🔐 บัตรต้องเป็นของกิจกรรมนี้ (parse ตรวจซ้ำกับ activity_id ที่ยิงเข้ามา)
                    if token:
                        participant_id = parse_qr_token(token, activity_id)
                    elif participant_id is None:
                        raise ValidationError("ต้องส่ง token หรือ participant_id อย่างใดอย่างหนึ่ง")

                    # ล็อกแถวกิจกรรม = จุดนับที่นั่ง (คนจากคิวอาจได้นั่งจากการสแกน)
                    capacity = await cls._lock_activity_capacity(conn, target_room_id, activity_id)
                    participant = await conn.fetchrow(
                        f"{cls.PARTICIPANT_SELECT} "
                        "WHERE ap.id = $1 AND ap.activity_id = $2 AND ap.deleted_at IS NULL FOR UPDATE OF ap",
                        participant_id, activity_id,
                    )
                    if not participant:
                        raise ParticipantNotFoundError(f"ไม่พบผู้เข้าร่วม ID: {participant_id}")

                    full_name = " ".join(
                        filter(None, [participant["first_name"], participant["last_name"]])
                    )
                    base = {
                        "participant_id": participant["id"],
                        "student_no": participant["student_no"],
                        "full_name": full_name,
                        "status": participant["status"],
                        "checked_in_at": participant["checked_in_at"],
                        "checked_in_by": participant["checked_in_by"],
                    }

                    # ✅ สแกนซ้ำ = สำเร็จ (HTTP 200) — ถือว่ามาถึงแล้วเหมือนกัน
                    if participant["status"] == "attended":
                        return {**base, "already_checked_in": True, "was_waitlisted": False}

                    if participant["status"] == "cancelled":
                        raise ValidationError(
                            f"เลขที่ {participant['student_no']} ถูกยกเลิกการเข้าร่วมไปแล้ว — "
                            "ถ้าจะให้เข้าจริง ให้เปลี่ยนสถานะกลับเป็นยืนยันแล้วก่อน"
                        )

                    was_waitlisted = participant["status"] == "waitlisted"
                    if was_waitlisted:
                        # คิวสำรองที่มาถึงหน้างาน: เข้าได้เฉพาะเมื่อมีที่นั่งจริง (ไม่แอบเกินเพดาน)
                        counts = await cls._capacity_counts(conn, activity_id)
                        if capacity is not None and counts["seated"] >= capacity:
                            raise ValidationError(
                                f"กิจกรรมเต็มแล้ว ({counts['seated']}/{capacity} ที่นั่ง) — "
                                f"เลขที่ {participant['student_no']} ยังอยู่ในคิวสำรอง "
                                "ให้ยกเลิกคนอื่นหรือเพิ่มความจุก่อน"
                            )

                    row = await conn.fetchrow(
                        """
                        UPDATE activity_participants
                        SET status = 'attended', queue_position = NULL,
                            checked_in_at = COALESCE(checked_in_at, CURRENT_TIMESTAMP),
                            checked_in_by = $2, updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                        RETURNING checked_in_at
                        """,
                        participant["id"], user_name,
                    )

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id,
                        entity_type="ACTIVITY_PARTICIPANT", entity_id=str(participant["id"]),
                        status="success",
                        old_values={"status": participant["status"],
                                    "queue_position": participant["queue_position"]},
                        new_values={
                            "status": "attended", "queue_position": None,
                            "checked_in_by": user_name,
                            "was_waitlisted": was_waitlisted,
                            "via": "qr" if token else "participant_id",
                        },
                        endpoint_or_command="checkin_qr",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )

                    # ⚠️ ไม่เลื่อนคิวคนอื่นจากการเช็คอิน — คนจากคิวที่มาใช้ที่นั่งของตัวเอง
                    #    ไม่ได้ทำให้ที่นั่งว่างลง จึงไม่มีอะไรให้เลื่อน (การเลื่อนเกิดตอน
                    #    ยกเลิก/นำออก/เพิ่มความจุ เท่านั้น — ดู capacity.py)

                    return {
                        **base,
                        "status": "attended",
                        "checked_in_at": row["checked_in_at"],
                        "checked_in_by": user_name,
                        "already_checked_in": False,
                        "was_waitlisted": was_waitlisted,
                    }
        except Exception as e:
            async with pool.acquire() as error_conn:
                await service_logger.log(
                    conn=error_conn, action="UPDATE", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id,
                    entity_type="ACTIVITY_PARTICIPANT", status="failed", error_detail=str(e),
                    new_values={"activity_id": activity_id, "participant_id": participant_id,
                                "has_token": bool(token)},
                    endpoint_or_command="checkin_qr",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
            raise e
