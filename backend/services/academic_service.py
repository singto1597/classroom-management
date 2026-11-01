"""ปีการศึกษา + เทอม — **ตัวกรองเวลา** ของสถิติ ไม่ใช่ระบบเลื่อนชั้น (P5)

═══════════════════════════════════════════════════════════════════════════════
🎯 สิ่งที่โมดูลนี้ "ทำ" และ "ไม่ทำ"
═══════════════════════════════════════════════════════════════════════════════
ทำ:
  · เก็บปฏิทินของห้อง (ปี พ.ศ. + เทอม) พร้อมธง "ปัจจุบัน"
  · แปลง (year_id, term_id) เป็น **ช่วงวันที่** ให้ query สถิติใช้
  · ยืนยันว่าช่วงที่ผู้ใช้เลือกมีอยู่จริงและเป็นของห้องนี้ (404 ไม่ใช่คืนศูนย์)

ไม่ทำ:
  · ไม่ย้ายนักเรียนไปปีใหม่ (ไม่มี `students.academic_year_id` ในระบบนี้)
  · ไม่ตัดสินว่า "ใครอยู่ปีไหน" — สถิติของปี/เทอมนับจาก *วันที่ของเหตุการณ์*
    (ใบเสร็จ / วันที่จัดกิจกรรม) ซึ่งเป็นข้อมูลที่ตรวจย้อนได้อยู่แล้ว

═══════════════════════════════════════════════════════════════════════════════
🕳️ "ไม่มีปีปัจจุบัน" = ไม่กรอง (และต้องบอกผู้ใช้ ไม่ใช่เดา)
═══════════════════════════════════════════════════════════════════════════════
ห้องที่ยังไม่เคยตั้งปีการศึกษา ⇒ `resolve_window` คืน `None` ⇒ สถิติทั้งก้อน
เหมือนก่อน P5 และ response มี `term: null`
**ห้ามเดา**ว่า "ปีแรกที่สร้าง" คือปีปัจจุบัน หรือ "ปีที่ครอบวันนี้" คือปัจจุบัน —
สองอย่างนั้นผิดทั้งคู่เมื่ออาจารย์สร้างปีถัดไปล่วงหน้าไว้ก่อน

═══════════════════════════════════════════════════════════════════════════════
📅 วันที่ vs เวลา
═══════════════════════════════════════════════════════════════════════════════
`start_date`/`end_date` เป็น DATE ⇒ ปลายช่วง **รวมวันสุดท้าย** เสมอกติกาเดียวกับ
`registration_deadline`: ใช้ `BETWEEN` กับคอลัมน์ DATE และ
`>= start AND < end + 1 วัน` กับคอลัมน์ timestamptz (แปลงขอบเขตเป็นเวลาไทยก่อน)
ถ้าใช้ `< end_date` ตรง ๆ เทอมจะหายไปหนึ่งวัน — เทสต์มีเคสวันสุดท้ายอยู่

═══════════════════════════════════════════════════════════════════════════════
🔒 สิทธิ์
═══════════════════════════════════════════════════════════════════════════════
อ่าน = สมาชิกห้อง (`require_member`) — ตัวกรองของสถิติต้องเปิดให้ทุกคนใช้
เขียน = `MANAGE_CLASSROOM_SETTINGS` (ผู้ดูแลห้อง) — ตรวจจริงใน service ที่ชั้นนี้
เฉพาะ เพื่อให้ทุก endpoint ที่เรียกใช้ผ่านกติกาเดียวกันโดยไม่มีทางลัด
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Optional

import asyncpg

from core.exceptions import AcademicPeriodNotFoundError, ValidationError
from core.logger import AuditLogger
from core.rbac import require_member, require_permission

logger = logging.getLogger("API_ACADEMIC")

academic_logger = AuditLogger(service_name="ACADEMIC")

# ช่วงปี พ.ศ. ที่รับได้ — กว้างพอสำหรับโรงเรียนที่ใช้ระบบนี้ แต่กันการพิมพ์ผิด
# (เช่นใส่ ค.ศ. 2026 มาเป็น พ.ศ. ⇒ 2026 อยู่นอกช่วง ⇒ 400 พร้อมบอกช่วงที่รับ)
MIN_YEAR_BE = 2500
MAX_YEAR_BE = 2699

TERM_MAX_LENGTH = 60
YEAR_NAME_MAX_LENGTH = 60


# ═════════════════════════════════════════════════════════════════════════════
# ตัวช่วยตรวจค่า
# ═════════════════════════════════════════════════════════════════════════════
def _validate_range(start: date, end: date, label: str) -> None:
    if end < start:
        raise ValidationError(f"วันสิ้นสุดของ{label}ต้องไม่ก่อนวันเริ่มต้น")


def _validate_year_be(year_be: int) -> None:
    if not (MIN_YEAR_BE <= int(year_be) <= MAX_YEAR_BE):
        raise ValidationError(
            f"ปี พ.ศ. ต้องอยู่ระหว่าง {MIN_YEAR_BE}–{MAX_YEAR_BE} "
            "(ถ้าพิมพ์เป็น ค.ศ. เช่น 2026 ให้บวก 543)"
        )


def _clean_text(value: Optional[str], *, label: str, max_length: int) -> Optional[str]:
    """ตัดช่องว่างหัวท้าย · สตริงว่าง = `None` (ไม่ใช่ค่าว่างที่ทำให้ CHECK/unique เพี้ยน)"""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValidationError(f"{label}ยาวเกิน {max_length} ตัวอักษร")
    return text


# ═════════════════════════════════════════════════════════════════════════════
# อ่าน
# ═════════════════════════════════════════════════════════════════════════════
_YEARS_SQL = """
SELECT id, room_id, year_be, name, start_date, end_date, is_current
FROM academic_years
WHERE room_id = $1 AND deleted_at IS NULL
ORDER BY year_be DESC
"""

_TERMS_SQL = """
SELECT id, academic_year_id, name, start_date, end_date, is_current
FROM academic_terms
WHERE academic_year_id = ANY($1::int[]) AND deleted_at IS NULL
ORDER BY start_date, id
"""


def _row_to_year(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "year_be": int(row["year_be"]),
        "name": row["name"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "is_current": bool(row["is_current"]),
        "terms": [],
    }


async def list_periods(
    pool: asyncpg.Pool, *, room_id: int, user_id: int
) -> dict[str, Any]:
    """ปีทั้งหมดของห้องพร้อมเทอมในแต่ละปี + ธงปัจจุบัน

    เรียงปีใหม่ → เก่า และเทอมตามวันเริ่ม — หน้าจอไม่ต้องเรียงเอง
    """
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await require_member(conn, room_id, user_id)
            year_rows = await conn.fetch(_YEARS_SQL, room_id)
            years = [_row_to_year(row) for row in year_rows]
            if years:
                term_rows = await conn.fetch(_TERMS_SQL, [y["id"] for y in years])
                by_year = {y["id"]: y for y in years}
                for row in term_rows:
                    target = by_year.get(int(row["academic_year_id"]))
                    if target is None:  # pragma: no cover — ANY() ครอบอยู่แล้ว
                        continue
                    target["terms"].append(
                        {
                            "id": int(row["id"]),
                            "name": row["name"],
                            "start_date": row["start_date"],
                            "end_date": row["end_date"],
                            "is_current": bool(row["is_current"]),
                        }
                    )

    current_year = next((y for y in years if y["is_current"]), None)
    current_term = None
    if current_year is not None:
        current_term = next((t for t in current_year["terms"] if t["is_current"]), None)

    return {
        "years": years,
        "current_year_id": current_year["id"] if current_year else None,
        "current_term_id": current_term["id"] if current_term else None,
    }


async def _fetch_year(
    conn: asyncpg.Connection, *, room_id: int, year_id: int, for_update: bool = False
) -> asyncpg.Record:
    """แถวปีของห้องนี้ — ไม่มี/ถูกลบ/ของห้องอื่น = `AcademicPeriodNotFoundError`

    ทั้งสามกรณีตอบข้อความเดียวกันโดยเจตนา: การแยกว่า "ปีนี้ไม่มี" กับ
    "ปีนี้ของห้องอื่น" จะกลายเป็นช่องให้เดา id ของห้องอื่น
    """
    suffix = " FOR UPDATE" if for_update else ""
    row = await conn.fetchrow(
        "SELECT id, room_id, year_be, name, start_date, end_date, is_current"
        " FROM academic_years"
        " WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL" + suffix,
        year_id,
        room_id,
    )
    if row is None:
        raise AcademicPeriodNotFoundError("ไม่พบปีการศึกษานี้ในห้อง")
    return row


async def _fetch_term(
    conn: asyncpg.Connection, *, room_id: int, term_id: int, for_update: bool = False
) -> asyncpg.Record:
    suffix = " FOR UPDATE" if for_update else ""
    row = await conn.fetchrow(
        "SELECT T.id, T.academic_year_id, T.name, T.start_date, T.end_date, T.is_current,"
        "       Y.year_be, Y.name AS year_name, Y.start_date AS year_start, Y.end_date AS year_end"
        " FROM academic_terms T"
        " JOIN academic_years Y ON Y.id = T.academic_year_id"
        " WHERE T.id = $1 AND Y.room_id = $2"
        "   AND T.deleted_at IS NULL AND Y.deleted_at IS NULL" + suffix,
        term_id,
        room_id,
    )
    if row is None:
        raise AcademicPeriodNotFoundError("ไม่พบเทอมนี้ในห้อง")
    return row


# ═════════════════════════════════════════════════════════════════════════════
# เขียน — ปีการศึกษา
# ═════════════════════════════════════════════════════════════════════════════
async def _clear_current_year(conn: asyncpg.Connection, room_id: int, keep_id: int) -> None:
    """ปลดธงปัจจุบันของปีอื่นก่อน — partial unique index อนุญาตปีปัจจุบันแค่หนึ่งปี"""
    await conn.execute(
        "UPDATE academic_years SET is_current = FALSE, updated_at = NOW()"
        " WHERE room_id = $1 AND is_current AND deleted_at IS NULL AND id <> $2",
        room_id,
        keep_id,
    )


async def _clear_current_term(
    conn: asyncpg.Connection, academic_year_id: int, keep_id: int
) -> None:
    await conn.execute(
        "UPDATE academic_terms SET is_current = FALSE, updated_at = NOW()"
        " WHERE academic_year_id = $1 AND is_current AND deleted_at IS NULL AND id <> $2",
        academic_year_id,
        keep_id,
    )


async def _audit(
    conn: asyncpg.Connection,
    *,
    action: str,
    room_id: int,
    user_id: int,
    entity_type: str,
    entity_id: int,
    old_values: Optional[dict[str, Any]],
    new_values: Optional[dict[str, Any]],
    endpoint: str,
    client_source: str,
    actor_identifier: str,
    started_at: float,
) -> None:
    await academic_logger.log(
        conn=conn,
        action=action,
        actor_identifier=actor_identifier,
        client_source=client_source,
        room_id=room_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=str(entity_id),
        old_values=old_values,
        new_values=new_values,
        endpoint_or_command=endpoint,
        execution_time_ms=int((time.time() - started_at) * 1000),
    )


async def create_year(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    year_be: int,
    name: Optional[str],
    start_date: date,
    end_date: date,
    is_current: bool = False,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    started = time.time()
    _validate_year_be(year_be)
    _validate_range(start_date, end_date, "ปีการศึกษา")
    clean_name = _clean_text(name, label="ชื่อปีการศึกษา", max_length=YEAR_NAME_MAX_LENGTH)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
            existing = await conn.fetchval(
                "SELECT id FROM academic_years"
                " WHERE room_id = $1 AND year_be = $2 AND deleted_at IS NULL",
                room_id,
                int(year_be),
            )
            if existing is not None:
                raise ValidationError(f"มีปี พ.ศ. {int(year_be)} ในห้องนี้แล้ว")

            row = await conn.fetchrow(
                "INSERT INTO academic_years"
                " (room_id, year_be, name, start_date, end_date, is_current)"
                " VALUES ($1, $2, $3, $4, $5, FALSE)"
                " RETURNING id, room_id, year_be, name, start_date, end_date, is_current",
                room_id,
                int(year_be),
                clean_name,
                start_date,
                end_date,
            )
            created = _row_to_year(row)
            if is_current:
                await _clear_current_year(conn, room_id, created["id"])
                await conn.execute(
                    "UPDATE academic_years SET is_current = TRUE, updated_at = NOW() WHERE id = $1",
                    created["id"],
                )
                created["is_current"] = True
                # ปีใหม่เป็นปัจจุบัน ⇒ เทอมปัจจุบันของปีอื่นไม่ใช่ "ปัจจุบัน" อีกแล้ว
                await conn.execute(
                    "UPDATE academic_terms SET is_current = FALSE, updated_at = NOW()"
                    " WHERE is_current AND deleted_at IS NULL"
                    "   AND academic_year_id IN ("
                    "       SELECT id FROM academic_years WHERE room_id = $1 AND id <> $2)",
                    room_id,
                    created["id"],
                )

            await _audit(
                conn,
                action="CREATE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_YEAR",
                entity_id=created["id"],
                old_values=None,
                new_values={k: v for k, v in created.items() if k != "terms"},
                endpoint="create_academic_year",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return created


async def update_year(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    year_id: int,
    name: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    """แก้ชื่อ/ช่วงวันของปี — **ไม่** แตะธงปัจจุบัน (ใช้ `set_current` เท่านั้น)

    ⚠️ `exclude_unset` ของ Pydantic ทำให้แยก "ไม่ส่งมา" (ไม่แตะ) กับ "ส่ง null" (ล้างชื่อ)
    ได้ ⇒ `name=None` ที่ส่งมาตรง ๆ = ล้างชื่อ (ตั้งใจ) ไม่ใช่ "ไม่เปลี่ยน"
    """
    started = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
            row = await _fetch_year(conn, room_id=room_id, year_id=year_id, for_update=True)

            new_start = start_date if start_date is not None else row["start_date"]
            new_end = end_date if end_date is not None else row["end_date"]
            _validate_range(new_start, new_end, "ปีการศึกษา")
            clean_name = (
                _clean_text(name, label="ชื่อปีการศึกษา", max_length=YEAR_NAME_MAX_LENGTH)
                if name is not None
                else row["name"]
            )

            # เทอมที่อยู่ในปีนี้ต้องยังอยู่ในช่วงใหม่ ไม่งั้นจะเหลือเทอมลอยนอกปี
            outside = await conn.fetchval(
                "SELECT COUNT(*) FROM academic_terms"
                " WHERE academic_year_id = $1 AND deleted_at IS NULL"
                "   AND (start_date < $2 OR end_date > $3)",
                year_id,
                new_start,
                new_end,
            )
            if outside:
                raise ValidationError(
                    "มีเทอมที่อยู่นอกช่วงวันใหม่ — แก้หรือลบเทอมนั้นก่อนเปลี่ยนช่วงของปี"
                )

            updated_row = await conn.fetchrow(
                "UPDATE academic_years"
                " SET name = $2, start_date = $3, end_date = $4, updated_at = NOW()"
                " WHERE id = $1"
                " RETURNING id, room_id, year_be, name, start_date, end_date, is_current",
                year_id,
                clean_name,
                new_start,
                new_end,
            )
            updated = _row_to_year(updated_row)

            await _audit(
                conn,
                action="UPDATE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_YEAR",
                entity_id=year_id,
                old_values=_row_to_year(row),
                new_values=updated,
                endpoint="update_academic_year",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return updated


async def delete_year(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    year_id: int,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    """ลบปี (soft) — ลบเทอมในปีนั้นตามไปด้วย และปลดธงปัจจุบันของทั้งคู่"""
    started = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
            row = await _fetch_year(conn, room_id=room_id, year_id=year_id, for_update=True)

            await conn.execute(
                "UPDATE academic_terms"
                " SET deleted_at = NOW(), is_current = FALSE, updated_at = NOW()"
                " WHERE academic_year_id = $1 AND deleted_at IS NULL",
                year_id,
            )
            await conn.execute(
                "UPDATE academic_years"
                " SET deleted_at = NOW(), is_current = FALSE, updated_at = NOW()"
                " WHERE id = $1",
                year_id,
            )

            await _audit(
                conn,
                action="DELETE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_YEAR",
                entity_id=year_id,
                old_values=_row_to_year(row),
                new_values=None,
                endpoint="delete_academic_year",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return {"deleted": True, "year_id": year_id}


# ═════════════════════════════════════════════════════════════════════════════
# เขียน — เทอม
# ═════════════════════════════════════════════════════════════════════════════
async def _assert_term_fits(
    conn: asyncpg.Connection,
    *,
    year_id: int,
    start_date: date,
    end_date: date,
    ignore_term_id: Optional[int] = None,
) -> None:
    """เทอมต้องอยู่ในปี และต้องไม่ทับกับเทอมอื่นของปีเดียวกัน

    การทับกันทำให้ "ยอดของเทอม 1 + เทอม 2" มากกว่ายอดของปี — ตัวเลขที่ดูปกติ
    แต่เพิ่มกันแล้วไม่ลงตัว คือความผิดพลาดที่ผู้ใช้จับได้ช้าที่สุด
    """
    year = await conn.fetchrow(
        "SELECT start_date, end_date FROM academic_years"
        " WHERE id = $1 AND deleted_at IS NULL",
        year_id,
    )
    if year is None:  # pragma: no cover — ผู้เรียกถือ row มาแล้ว
        raise AcademicPeriodNotFoundError("ไม่พบปีการศึกษานี้ในห้อง")
    if start_date < year["start_date"] or end_date > year["end_date"]:
        raise ValidationError(
            "ช่วงของเทอมต้องอยู่ในช่วงของปีการศึกษา"
            f" ({year['start_date']} ถึง {year['end_date']})"
        )

    overlap = await conn.fetchval(
        "SELECT 1 FROM academic_terms"
        " WHERE academic_year_id = $1 AND deleted_at IS NULL"
        "   AND id <> COALESCE($2, -1)"
        "   AND start_date <= $4 AND end_date >= $3"
        " LIMIT 1",
        year_id,
        ignore_term_id,
        start_date,
        end_date,
    )
    if overlap:
        raise ValidationError("ช่วงของเทอมทับกับเทอมอื่นในปีเดียวกัน")


async def create_term(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    year_id: int,
    name: str,
    start_date: date,
    end_date: date,
    is_current: bool = False,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    started = time.time()
    clean_name = _clean_text(name, label="ชื่อเทอม", max_length=TERM_MAX_LENGTH)
    if clean_name is None:
        raise ValidationError("ต้องระบุชื่อเทอม")
    _validate_range(start_date, end_date, "เทอม")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
            await _fetch_year(conn, room_id=room_id, year_id=year_id, for_update=True)
            await _assert_term_fits(
                conn, year_id=year_id, start_date=start_date, end_date=end_date
            )

            duplicate = await conn.fetchval(
                "SELECT id FROM academic_terms"
                " WHERE academic_year_id = $1 AND name = $2 AND deleted_at IS NULL",
                year_id,
                clean_name,
            )
            if duplicate is not None:
                raise ValidationError(f"มีเทอมชื่อ “{clean_name}” ในปีนี้แล้ว")

            row = await conn.fetchrow(
                "INSERT INTO academic_terms"
                " (academic_year_id, name, start_date, end_date, is_current)"
                " VALUES ($1, $2, $3, $4, FALSE)"
                " RETURNING id, name, start_date, end_date, is_current",
                year_id,
                clean_name,
                start_date,
                end_date,
            )
            created = {
                "id": int(row["id"]),
                "academic_year_id": year_id,
                "name": row["name"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "is_current": False,
            }
            if is_current:
                await _clear_current_term(conn, year_id, created["id"])
                await conn.execute(
                    "UPDATE academic_terms SET is_current = TRUE, updated_at = NOW() WHERE id = $1",
                    created["id"],
                )
                created["is_current"] = True

            await _audit(
                conn,
                action="CREATE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_TERM",
                entity_id=created["id"],
                old_values=None,
                new_values=created,
                endpoint="create_academic_term",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return created


async def update_term(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    term_id: int,
    name: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    started = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
            row = await _fetch_term(conn, room_id=room_id, term_id=term_id, for_update=True)
            year_id = int(row["academic_year_id"])

            new_start = start_date if start_date is not None else row["start_date"]
            new_end = end_date if end_date is not None else row["end_date"]
            _validate_range(new_start, new_end, "เทอม")
            await _assert_term_fits(
                conn,
                year_id=year_id,
                start_date=new_start,
                end_date=new_end,
                ignore_term_id=term_id,
            )

            clean_name = row["name"]
            if name is not None:
                clean_name = _clean_text(name, label="ชื่อเทอม", max_length=TERM_MAX_LENGTH)
                if clean_name is None:
                    raise ValidationError("ต้องระบุชื่อเทอม")
                duplicate = await conn.fetchval(
                    "SELECT id FROM academic_terms"
                    " WHERE academic_year_id = $1 AND name = $2"
                    "   AND deleted_at IS NULL AND id <> $3",
                    year_id,
                    clean_name,
                    term_id,
                )
                if duplicate is not None:
                    raise ValidationError(f"มีเทอมชื่อ “{clean_name}” ในปีนี้แล้ว")

            updated_row = await conn.fetchrow(
                "UPDATE academic_terms"
                " SET name = $2, start_date = $3, end_date = $4, updated_at = NOW()"
                " WHERE id = $1"
                " RETURNING id, academic_year_id, name, start_date, end_date, is_current",
                term_id,
                clean_name,
                new_start,
                new_end,
            )
            updated = {
                "id": int(updated_row["id"]),
                "academic_year_id": int(updated_row["academic_year_id"]),
                "name": updated_row["name"],
                "start_date": updated_row["start_date"],
                "end_date": updated_row["end_date"],
                "is_current": bool(updated_row["is_current"]),
            }

            await _audit(
                conn,
                action="UPDATE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_TERM",
                entity_id=term_id,
                old_values={
                    "name": row["name"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "is_current": bool(row["is_current"]),
                },
                new_values=updated,
                endpoint="update_academic_term",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return updated


async def delete_term(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    term_id: int,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    started = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")
            row = await _fetch_term(conn, room_id=room_id, term_id=term_id, for_update=True)
            await conn.execute(
                "UPDATE academic_terms"
                " SET deleted_at = NOW(), is_current = FALSE, updated_at = NOW()"
                " WHERE id = $1",
                term_id,
            )
            await _audit(
                conn,
                action="DELETE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_TERM",
                entity_id=term_id,
                old_values={
                    "name": row["name"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "is_current": bool(row["is_current"]),
                },
                new_values=None,
                endpoint="delete_academic_term",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return {"deleted": True, "term_id": term_id}


# ═════════════════════════════════════════════════════════════════════════════
# ตั้ง "ปัจจุบัน"
# ═════════════════════════════════════════════════════════════════════════════
async def set_current(
    pool: asyncpg.Pool,
    *,
    room_id: int,
    user_id: int,
    year_id: Optional[int],
    term_id: Optional[int] = None,
    client_source: str = "WEB_APP",
    actor_identifier: str = "",
) -> dict[str, Any]:
    """ตั้งปีปัจจุบัน (และเทอมปัจจุบันถ้าระบุ) — `year_id=None` = ปลดทั้งหมด

    ปลดแล้วสถิติกลับไปเป็น "ทั้งก้อน" พร้อม `term: null` — ไม่ใช่ error

    🔑 `term_id=None` แปลว่า **"ทั้งปี"** ไม่ใช่ "ไม่แตะเทอมเดิม" ⇒ ปลดเทอมปัจจุบัน
       ของ *ทุกปีในห้องนี้* (รวมปีที่เพิ่งตั้ง) ให้ตรงกับค่าที่ฟังก์ชันคืนกลับมา
       ถ้าไม่ปลด เทอมปัจจุบันของปีเดิมจะค้างอยู่ ⇒ `/periods` บอกว่ามีเทอมปัจจุบัน
       แต่คำตอบของ `set_current` บอก `current_term_id: None` = สองแหล่งขัดกัน
    """
    started = time.time()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await require_permission(conn, room_id, user_id, "MANAGE_CLASSROOM_SETTINGS")

            if year_id is None:
                await conn.execute(
                    "UPDATE academic_years SET is_current = FALSE, updated_at = NOW()"
                    " WHERE room_id = $1 AND is_current AND deleted_at IS NULL",
                    room_id,
                )
                await conn.execute(
                    "UPDATE academic_terms SET is_current = FALSE, updated_at = NOW()"
                    " WHERE is_current AND deleted_at IS NULL"
                    "   AND academic_year_id IN ("
                    "       SELECT id FROM academic_years WHERE room_id = $1)",
                    room_id,
                )
                await _audit(
                    conn,
                    action="UPDATE",
                    room_id=room_id,
                    user_id=user_id,
                    entity_type="ACADEMIC_YEAR",
                    entity_id=0,
                    old_values=None,
                    new_values={"current": None},
                    endpoint="set_current_period",
                    client_source=client_source,
                    actor_identifier=actor_identifier,
                    started_at=started,
                )
                return {"current_year_id": None, "current_term_id": None}

            year = await _fetch_year(conn, room_id=room_id, year_id=year_id, for_update=True)
            term_row = None
            if term_id is not None:
                term_row = await _fetch_term(
                    conn, room_id=room_id, term_id=term_id, for_update=True
                )
                if int(term_row["academic_year_id"]) != int(year_id):
                    raise ValidationError("เทอมที่เลือกไม่ได้อยู่ในปีที่เลือก")

            await _clear_current_year(conn, room_id, int(year_id))
            await conn.execute(
                "UPDATE academic_years SET is_current = TRUE, updated_at = NOW() WHERE id = $1",
                year_id,
            )
            # เทอมปัจจุบันของปีอื่นไม่มีความหมายเมื่อปีเปลี่ยน และ `term_id=None`
            # หมายถึง "ทั้งปี" ⇒ ปลดเทอมปัจจุบันของทุกปีในห้องนี้ (ดู docstring)
            await conn.execute(
                "UPDATE academic_terms SET is_current = FALSE, updated_at = NOW()"
                " WHERE is_current AND deleted_at IS NULL"
                "   AND academic_year_id IN ("
                "       SELECT id FROM academic_years WHERE room_id = $1)",
                room_id,
            )
            if term_row is not None:
                await _clear_current_term(conn, int(year_id), int(term_id))
                await conn.execute(
                    "UPDATE academic_terms SET is_current = TRUE, updated_at = NOW()"
                    " WHERE id = $1",
                    term_id,
                )

            await _audit(
                conn,
                action="UPDATE",
                room_id=room_id,
                user_id=user_id,
                entity_type="ACADEMIC_YEAR",
                entity_id=int(year_id),
                old_values={"was_current": bool(year["is_current"])},
                new_values={
                    "current_year_id": int(year_id),
                    "current_term_id": int(term_id) if term_id is not None else None,
                },
                endpoint="set_current_period",
                client_source=client_source,
                actor_identifier=actor_identifier,
                started_at=started,
            )

    return {
        "current_year_id": int(year_id),
        "current_term_id": int(term_id) if term_id is not None else None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# แปลง (year_id, term_id) → ช่วงวันที่
# ═════════════════════════════════════════════════════════════════════════════
async def resolve_window(
    conn: asyncpg.Connection,
    *,
    room_id: int,
    year_id: Optional[int] = None,
    term_id: Optional[int] = None,
) -> tuple[Optional[dict[str, Any]], Optional[date], Optional[date]]:
    """คืน `(term_info, date_from, date_to)`

    · เลือกเทอม → ช่วงของเทอม · เลือกปีอย่างเดียว → ช่วงของปี
    · ไม่เลือกอะไรเลย → ปีปัจจุบัน (+ เทอมปัจจุบันถ้ามี) ⇒ ไม่มีปีปัจจุบัน = `(None, None, None)`
    · id ที่ไม่มีจริง/ของห้องอื่น = `AcademicPeriodNotFoundError` (route แปลเป็น 404)

    🔑 ฟังก์ชันนี้รับ `conn` เดิมของผู้เรียก **โดยเจตนา** — ต้องอยู่ใน snapshot
    เดียวกับการนับสถิติ ไม่งั้นปฏิทินเปลี่ยนกลางคำขอแล้วตัวเลขจะมาจากคนละช่วง
    """
    if term_id is not None:
        term = await _fetch_term(conn, room_id=room_id, term_id=term_id)
        if year_id is not None and int(term["academic_year_id"]) != int(year_id):
            raise ValidationError("เทอมที่เลือกไม่ได้อยู่ในปีที่เลือก")
        return (
            {
                "year_id": int(term["academic_year_id"]),
                "year_be": int(term["year_be"]),
                "year_name": term["year_name"],
                "term_id": int(term["id"]),
                "term_name": term["name"],
                "source": "explicit",
            },
            term["start_date"],
            term["end_date"],
        )

    if year_id is not None:
        year = await _fetch_year(conn, room_id=room_id, year_id=year_id)
        return (
            {
                "year_id": int(year["id"]),
                "year_be": int(year["year_be"]),
                "year_name": year["name"],
                "term_id": None,
                "term_name": None,
                "source": "explicit",
            },
            year["start_date"],
            year["end_date"],
        )

    # ไม่ระบุอะไร = ใช้ปีปัจจุบันของห้อง (ถ้ามี)
    current_year = await conn.fetchrow(
        "SELECT id, year_be, name, start_date, end_date FROM academic_years"
        " WHERE room_id = $1 AND is_current AND deleted_at IS NULL",
        room_id,
    )
    if current_year is None:
        return (None, None, None)

    current_term = await conn.fetchrow(
        "SELECT id, name, start_date, end_date FROM academic_terms"
        " WHERE academic_year_id = $1 AND is_current AND deleted_at IS NULL",
        current_year["id"],
    )
    if current_term is not None:
        return (
            {
                "year_id": int(current_year["id"]),
                "year_be": int(current_year["year_be"]),
                "year_name": current_year["name"],
                "term_id": int(current_term["id"]),
                "term_name": current_term["name"],
                "source": "current",
            },
            current_term["start_date"],
            current_term["end_date"],
        )

    return (
        {
            "year_id": int(current_year["id"]),
            "year_be": int(current_year["year_be"]),
            "year_name": current_year["name"],
            "term_id": None,
            "term_name": None,
            "source": "current",
        },
        current_year["start_date"],
        current_year["end_date"],
    )
