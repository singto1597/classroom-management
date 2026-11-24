"""⚖️ ประเภทความผิด/อัตราค่าปรับ (`fine_types`) — seed + CRUD + soft delete + RBAC

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ห้องใหม่ต้องมี 5 ประเภทเริ่มต้น** — ถ้า seed ไม่ทำงาน ผู้ใช้จะเปิดหน้าค่าปรับ
   แล้วออกค่าปรับไม่ได้เลย (ฟอร์มไม่มีตัวเลือก) และ `ensure_default_fine_types`
   ต้อง **idempotent** (เรียกซ้ำใน transaction เดียวกับ create_room ไม่เพิ่มซ้ำ)
2. **การลบคือ soft delete** — บิลเก่าที่อ้างประเภทนี้เก็บ snapshot `fine_type_name`
   ไว้แล้ว ⇒ รายงานไม่หาย แต่ GET ต้องไม่คืนแถวที่ลบแล้ว
3. **ห้าม seed กลับ** — ประเภทที่ผู้ใช้ลบไปแล้วต้องไม่โผล่มาอีกตอนเรียก ensure ซ้ำ
   (ถ้า seed แบบ "ตรวจทีละชื่อ" การลบของผู้ใช้จะไม่มีผลถาวร)
4. **แยกห้อง** — ประเภทของห้อง A ต้องไม่รั่วไปห้อง B
5. **RBAC** — สมาชิกอ่านได้ (เป็นข้อมูลอ้างอิงที่ฟอร์มต้องใช้) แต่เขียนได้เฉพาะ MANAGE_FINANCE
"""
import uuid

import pytest

from services.finance.constants import DEFAULT_FINE_TYPES
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
TYPES_PATH = API_PREFIX + "/{room}/finance/fine-types"
TYPE_PATH = API_PREFIX + "/{room}/finance/fine-types/{fine_type_id}"


def _url(template: str, room_id: int, **kwargs) -> str:
    return template.format(room=room_id, **kwargs) + "?target_type=room"


async def _ensure_types(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await FinanceService.ensure_default_fine_types(conn, room_id)


async def _add_room_for(pool, user_id: int, *, is_admin: bool = True) -> int:
    """สร้างห้องที่สองให้ user เดิม (ทดสอบการแยกห้อง)"""
    async with pool.acquire() as conn:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
            "ห้องที่สอง", f"R{uuid.uuid4().hex[:6].upper()}", user_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 0, 'president', 'active', $3, '[]'::jsonb)""",
            room_id, user_id, is_admin,
        )
    return room_id


async def test_ensure_defaults_seeds_five_and_is_idempotent(db_pool, admin_headers):
    room_id = admin_headers.room_id

    first = await _ensure_types(db_pool, room_id)
    second = await _ensure_types(db_pool, room_id)

    assert first == len(DEFAULT_FINE_TYPES) == 5
    assert second == 0, "เรียกซ้ำต้องไม่เพิ่มแถว"

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, default_amount, default_due_days FROM fine_types WHERE room_id = $1 ORDER BY sort_order, id",
            room_id,
        )
    assert [r["name"] for r in rows] == [t["name"] for t in DEFAULT_FINE_TYPES]
    assert [float(r["default_amount"]) for r in rows] == [float(t["default_amount"]) for t in DEFAULT_FINE_TYPES]


async def test_deleted_type_is_not_reseeded(client, db_pool, admin_headers):
    """ลบแล้วต้องไม่กลับมา — ไม่งั้น 'ลบ' ของผู้ใช้ไม่มีความหมาย"""
    room_id = admin_headers.room_id
    await _ensure_types(db_pool, room_id)

    listing = client.get(_url(TYPES_PATH, room_id), headers=admin_headers).json()
    target = listing[0]["id"]
    res = client.delete(_url(TYPE_PATH, room_id, fine_type_id=target), headers=admin_headers)
    assert res.status_code == 200, res.text

    # ⚠️ ยังเหลือ 4 แถวที่ active ⇒ ensure ต้องไม่ seed เพิ่มเลย (ห้องเคยมีแล้ว)
    assert await _ensure_types(db_pool, room_id) == 0

    listing_after = client.get(_url(TYPES_PATH, room_id), headers=admin_headers).json()
    assert target not in [t["id"] for t in listing_after]
    assert len(listing_after) == 4

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT deleted_at, is_active FROM fine_types WHERE id = $1", target)
    assert row["deleted_at"] is not None and row["is_active"] is False


async def test_crud_and_active_only_filter(client, db_pool, finance_manager_headers):
    room_id = finance_manager_headers.room_id

    created = client.post(
        _url(TYPES_PATH, room_id),
        json={"name": "ทิ้งขยะไม่ลงถัง", "default_amount": 15, "default_due_days": 3,
              "description": "ทดสอบ", "sort_order": 9},
        headers=finance_manager_headers,
    )
    assert created.status_code == 200, created.text
    type_id = created.json()["id"]

    patched = client.patch(
        _url(TYPE_PATH, room_id, fine_type_id=type_id),
        json={"default_amount": 25.5, "is_active": False},
        headers=finance_manager_headers,
    )
    assert patched.status_code == 200, patched.text

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM fine_types WHERE id = $1", type_id)
    assert float(row["default_amount"]) == 25.5
    assert row["is_active"] is False

    all_types = client.get(_url(TYPES_PATH, room_id), headers=finance_manager_headers).json()
    active = client.get(
        _url(TYPES_PATH, room_id) + "&active_only=true", headers=finance_manager_headers
    ).json()
    assert type_id in [t["id"] for t in all_types]
    assert type_id not in [t["id"] for t in active], "is_active=false ต้องถูกกรองออกเมื่อ active_only"


async def test_types_are_isolated_per_room(client, db_pool, admin_headers):
    room_a = admin_headers.room_id
    room_b = await _add_room_for(db_pool, admin_headers.user_id)
    await _ensure_types(db_pool, room_a)

    # ผู้ใช้คนเดียวกันเป็นสมาชิกทั้งสองห้อง ⇒ ยิง room_b ต้องเห็น 0 แถว
    listing_b = client.get(_url(TYPES_PATH, room_b), headers=admin_headers)
    assert listing_b.status_code == 200, listing_b.text
    assert listing_b.json() == []


async def _add_member_to_room(pool, room_id: int, *, permissions: str = "[]") -> dict:
    """สร้างผู้ใช้ใหม่ + students row ในห้องเดิม คืน headers ที่ยิง API ได้"""
    import random

    from core.config import settings

    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            "สมาชิก", "ทดสอบ", f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, $4::jsonb)""",
            room_id, user_id, random.randint(10_000, 19_999), permissions,
        )
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


async def test_member_reads_but_cannot_write(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _ensure_types(db_pool, room_id)
    member = await _add_member_to_room(db_pool, room_id)

    assert client.get(_url(TYPES_PATH, room_id), headers=member).status_code == 200

    res = client.post(
        _url(TYPES_PATH, room_id),
        json={"name": "ห้ามสร้าง", "default_amount": 5},
        headers=member,
    )
    assert res.status_code == 403, res.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT 1 FROM fine_types WHERE room_id = $1 AND name = 'ห้ามสร้าง'", room_id
        ) is None
