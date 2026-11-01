"""ข้อมูลโปรไฟล์เฉพาะห้อง (student_room_profiles) — override ทับค่าบัญชีกลาง

กฎ:
- ครู/ผู้จัดการแก้ข้อมูลนักเรียนในห้อง → เขียนตารางนี้ (ไม่แตะ `users`)
- นักเรียนแก้โปรไฟล์ตัวเอง → เขียน `users` และล้าง override ของฟิลด์ที่แก้ในห้องนั้น
- เจ้าตัวกดยืนยันตัวตน → merge: ฟิลด์ที่บัญชีกลางมีค่าแล้ว "บัญชีชนะ" (ล้าง override),
  ฟิลด์ที่บัญชีกลางยังว่าง → เก็บ override ที่ห้องบันทึกไว้

การอ่านทุกจุดใช้ view `v_student_profiles` (COALESCE(override, users)) — ไม่ต้องเขียนกฎซ้ำ
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

import asyncpg

# ลำดับคอลัมน์คงที่ — ใช้สร้าง SQL แบบ parameterized (ชื่อคอลัมน์มาจาก whitelist นี้เท่านั้น)
PROFILE_COLUMNS: tuple[str, ...] = (
    "prefix", "first_name", "last_name", "nickname",
    "first_name_en", "last_name_en", "nickname_en",
    "birthday", "blood_group", "shirt_size", "food_allergy", "congenital_disease",
    "phone_number", "phone_number_parent", "phone_number_parent_relation",
    "line_id", "ig_username", "email",
    "address_house_no", "address_road", "address_sub_district",
    "address_district", "address_province", "address_post_code",
)

PROFILE_COLUMN_SET = frozenset(PROFILE_COLUMNS)


def _selected_columns(fields: Iterable[str]) -> list[str]:
    """กรองเฉพาะชื่อคอลัมน์ที่รู้จัก เรียงตาม PROFILE_COLUMNS (กัน SQL injection จาก key)"""
    wanted = set(fields) & PROFILE_COLUMN_SET
    return [c for c in PROFILE_COLUMNS if c in wanted]


async def upsert_room_overrides(
    conn: asyncpg.Connection,
    student_id: int,
    updates: Mapping[str, object],
    updated_by: Optional[int],
) -> None:
    """เขียน/อัปเดต override ของแถวนักเรียนหนึ่งคน — เฉพาะคีย์ที่ส่งมาเท่านั้น"""
    cols = _selected_columns(updates.keys())
    if not cols:
        return

    placeholders = ", ".join(f"${i + 3}" for i in range(len(cols)))
    assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    values = [student_id, updated_by] + [updates[c] for c in cols]

    await conn.execute(
        f"""
        INSERT INTO student_room_profiles (student_id, updated_by, {", ".join(cols)})
        VALUES ($1, $2, {placeholders})
        ON CONFLICT (student_id) DO UPDATE SET
            {assignments},
            updated_by = EXCLUDED.updated_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        *values,
    )


async def clear_room_overrides(
    conn: asyncpg.Connection,
    student_id: int,
    fields: Iterable[str],
) -> None:
    """ล้าง override ของฟิลด์ที่ระบุ (คืนค่าให้ตกไปใช้บัญชีกลาง) แล้วลบแถวถ้าไม่เหลือค่า"""
    cols = _selected_columns(fields)
    if not cols:
        return

    await conn.execute(
        f"""
        UPDATE student_room_profiles
        SET {", ".join(f"{c} = NULL" for c in cols)}, updated_at = CURRENT_TIMESTAMP
        WHERE student_id = $1
        """,
        student_id,
    )

    empty_conditions = " AND ".join(f"{c} IS NULL" for c in PROFILE_COLUMNS)
    await conn.execute(
        f"DELETE FROM student_room_profiles WHERE student_id = $1 AND {empty_conditions}",
        student_id,
    )


async def merge_room_overrides_on_claim(
    conn: asyncpg.Connection,
    student_id: int,
    user_id: int,
) -> None:
    """เจ้าตัวยืนยันตัวตนแล้ว — ให้ค่าที่มีอยู่ในบัญชีกลางชนะ override ของห้อง

    ฟิลด์ที่ `users` มีค่า (ไม่ใช่ NULL/ค่าว่าง) → ล้าง override
    ฟิลด์ที่ `users` ยังว่าง → เก็บค่าที่ห้องกรอกไว้ (merge แบบเติมช่องว่าง)
    """
    override = await conn.fetchrow(
        "SELECT * FROM student_room_profiles WHERE student_id = $1", student_id
    )
    if not override:
        return

    account = await conn.fetchrow(
        f"SELECT {', '.join(PROFILE_COLUMNS)} FROM users WHERE id = $1", user_id
    )
    if not account:
        return

    fields_to_clear = [
        col for col in PROFILE_COLUMNS
        if override[col] is not None and account[col] not in (None, "")
    ]
    await clear_room_overrides(conn, student_id, fields_to_clear)
