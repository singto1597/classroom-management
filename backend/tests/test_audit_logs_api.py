"""Integration tests — หน้าดูบันทึกกิจกรรม `GET /api/classroom/{id}/audit-logs` (P6.2)

สิ่งที่ล็อกไว้:
  1. **สิทธิ์** — ต้องมี `VIEW_AUDIT_LOGS`; สมาชิกธรรมดาได้ 403 (บันทึกมี IP/UA)
  2. **ไม่รั่วข้ามห้อง** — บันทึกของห้องอื่นต้องไม่โผล่ แม้ผู้ใช้จะเป็นประธานห้องนั้น
  3. **keyset pagination** — เดินครบทุกหน้าโดยไม่มีแถวซ้ำ/หาย แม้มีแถวใหม่แทรกหัวตาราง
  4. **ตัวกรอง** — service/action/คำค้น ทำงานจริง
  5. **ขอบเขตวันตามเวลาไทย** — แถว 00:30 น. ไทย (17:30 UTC วันก่อน) ต้องถูกนับเป็นวันไทย
  6. **cursor เสีย = 400** ไม่ใช่ 500
  7. **audit ของการดู เขียนหน้าแรกครั้งเดียว** — เลื่อนหน้าไม่เขียนเพิ่ม
  8. **migration 0009** เติม `VIEW_AUDIT_LOGS` ให้บทบาทเดิมแบบ idempotent

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
ไม่ hardcode id
"""
import json
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio

BANGKOK = timezone(timedelta(hours=7))


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _make_member(pool, *, permissions: str = "[]", is_admin: bool = False, class_role: str = "student"):
    """สร้าง user + room + students row แล้วคืน headers ที่ยิง API ได้"""
    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username, discord_id) "
            "VALUES ('Test', 'User', $1, $2) RETURNING id",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('Test Room', $1, $2) RETURNING id",
            code, user_id,
        )
        student_id = await conn.fetchval(
            "INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions) "
            "VALUES ($1, $2, 1, $3, 'active', $4, $5::jsonb) RETURNING id",
            room_id, user_id, class_role, is_admin, permissions,
        )
    return {
        "room_id": room_id,
        "user_id": user_id,
        "student_id": student_id,
        "headers": {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)},
    }


async def _insert_log(
    pool,
    room_id: int,
    *,
    service_name: str = "ACADEMIC",
    action: str = "CREATE",
    actor_identifier: str = "user_id:1",
    status: str = "success",
    entity_id: str = "1",
    endpoint: str = "create_academic_year",
    created_at: datetime | None = None,
    user_id: int | None = None,
) -> uuid.UUID:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO audit_logs (
                room_id, user_id, actor_identifier, client_source, service_name,
                action, entity_type, entity_id, status, endpoint_or_command, created_at
            ) VALUES ($1, $2, $3, 'WEB_APP', $4, $5, 'ACADEMIC_YEAR', $6, $7, $8, COALESCE($9, NOW()))
            RETURNING id
            """,
            room_id, user_id, actor_identifier, service_name, action, entity_id, status, endpoint, created_at,
        )


def _url(room_id: int, **params) -> str:
    from urllib.parse import urlencode

    query = {"target_type": "room", **params}
    return f"/api/classroom/{room_id}/audit-logs?{urlencode(query)}"


PRESIDENT = '["VIEW_AUDIT_LOGS"]'


# ── 1–2. สิทธิ์ + การแยกห้อง ────────────────────────────────────────────────
async def test_president_sees_only_own_room_logs(client, db_pool):
    me = await _make_member(db_pool, permissions=PRESIDENT)
    other = await _make_member(db_pool, permissions=PRESIDENT)

    mine_id = await _insert_log(db_pool, me["room_id"], entity_id="10")
    await _insert_log(db_pool, other["room_id"], entity_id="20")

    response = client.get(_url(me["room_id"]), headers=me["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {item["id"] for item in body["items"]}

    assert str(mine_id) in ids
    # 🚨 ถ้าขาด WHERE room_id = $1 ข้อนี้จะจับได้ทันที
    assert all(item["entity_id"] == "10" for item in body["items"]), body["items"]


async def test_member_without_permission_is_forbidden(client, db_pool):
    member = await _make_member(db_pool)  # permissions = []
    await _insert_log(db_pool, member["room_id"])

    response = client.get(_url(member["room_id"]), headers=member["headers"])
    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"] or "Access" in response.json()["detail"]


async def test_admin_bypasses_permission(client, db_pool):
    """is_admin ผ่านทุกด่านตาม require_permission — ไม่ต้องมี VIEW_AUDIT_LOGS"""
    admin = await _make_member(db_pool, is_admin=True)
    await _insert_log(db_pool, admin["room_id"])

    response = client.get(_url(admin["room_id"]), headers=admin["headers"])
    assert response.status_code == 200


# ── 3. การเลื่อนหน้า ────────────────────────────────────────────────────────
async def test_keyset_pagination_walks_all_rows_without_duplicates(client, db_pool):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    room_id = president["room_id"]
    for i in range(5):
        await _insert_log(db_pool, room_id, entity_id=str(i))

    seen: list[str] = []
    cursor = None
    for _ in range(10):  # กัน infinite loop ถ้าตรรกะพัง
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = client.get(_url(room_id, **params), headers=president["headers"])
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not body["has_more"]:
            break

    assert len(seen) == 5, seen
    assert len(set(seen)) == 5, "มีแถวซ้ำระหว่างหน้า — keyset เพี้ยน"


async def test_new_rows_at_top_do_not_shift_next_page(client, db_pool):
    """แถวใหม่ที่แทรกหัวตารางต้องไม่ทำให้หน้าถัดไปซ้ำ/ข้าม (เหตุผลที่ใช้ keyset)"""
    president = await _make_member(db_pool, permissions=PRESIDENT)
    room_id = president["room_id"]
    old_ids = [str(await _insert_log(db_pool, room_id, entity_id=str(i))) for i in range(4)]

    first = client.get(_url(room_id, limit=2), headers=president["headers"]).json()
    # ระหว่างที่ผู้ใช้กำลังอ่าน มีคนทำรายการใหม่ 2 ครั้ง
    await _insert_log(db_pool, room_id, entity_id="new-1")
    await _insert_log(db_pool, room_id, entity_id="new-2")

    second = client.get(
        _url(room_id, limit=2, cursor=first["next_cursor"]), headers=president["headers"]
    ).json()

    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids), "หน้าถัดไปทับหน้าแรก"
    assert second_ids.issubset(set(old_ids)), (second_ids, old_ids)


async def test_limit_is_clamped_to_range(client, db_pool):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    await _insert_log(db_pool, president["room_id"])

    assert client.get(_url(president["room_id"], limit=0), headers=president["headers"]).status_code == 422
    assert client.get(_url(president["room_id"], limit=999), headers=president["headers"]).status_code == 422


# ── 4. ตัวกรอง ──────────────────────────────────────────────────────────────
async def test_filters_by_service_action_and_search(client, db_pool):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    room_id = president["room_id"]
    await _insert_log(db_pool, room_id, service_name="FINANCE", action="CREATE", endpoint="create_receipt", entity_id="1")
    await _insert_log(db_pool, room_id, service_name="ACADEMIC", action="UPDATE", endpoint="update_year", entity_id="2")
    await _insert_log(db_pool, room_id, service_name="ACADEMIC", action="CREATE", actor_identifier="user_id:777", entity_id="3")

    def _entity_ids(**params) -> set[str]:
        response = client.get(_url(room_id, **params), headers=president["headers"])
        assert response.status_code == 200, response.text
        return {item["entity_id"] for item in response.json()["items"]}

    assert _entity_ids(service_name="FINANCE") == {"1"}
    assert _entity_ids(action="UPDATE") == {"2"}
    assert _entity_ids(service_name="ACADEMIC", action="CREATE") == {"3"}
    assert _entity_ids(q="777") == {"3"}
    assert _entity_ids(q="create_receipt") == {"1"}
    # `%` ต้องถูกมองเป็นตัวอักษร ไม่ใช่ไวลด์การ์ดของ ILIKE
    assert _entity_ids(q="%") == set()


# ── 5. ขอบเขตวันตามเวลาไทย ──────────────────────────────────────────────────
async def test_date_filter_uses_bangkok_boundary(client, db_pool):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    room_id = president["room_id"]
    # 00:30 น. ของวันที่ 1 มี.ค. ไทย = 17:30 UTC ของ 28 ก.พ.
    await _insert_log(
        db_pool, room_id, entity_id="bangkok-midnight",
        created_at=datetime(2026, 3, 1, 0, 30, tzinfo=BANGKOK),
    )
    await _insert_log(
        db_pool, room_id, entity_id="previous-day",
        created_at=datetime(2026, 2, 28, 23, 30, tzinfo=BANGKOK),
    )

    def _entity_ids(**params) -> set[str]:
        response = client.get(_url(room_id, **params), headers=president["headers"])
        assert response.status_code == 200, response.text
        return {item["entity_id"] for item in response.json()["items"]}

    assert _entity_ids(date_from="2026-03-01") == {"bangkok-midnight"}
    assert _entity_ids(date_to="2026-02-28") == {"previous-day"}
    # วันสุดท้ายต้อง "รวมทั้งวัน" ไม่ใช่ตัดที่ 00:00
    assert _entity_ids(date_from="2026-02-28", date_to="2026-02-28") == {"previous-day"}


# ── 6. cursor เสีย ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad_cursor", ["not-base64!!", "bm90LWEtY3Vyc29y", "!!!"])
async def test_invalid_cursor_returns_400(client, db_pool, bad_cursor):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    response = client.get(
        _url(president["room_id"], cursor=bad_cursor), headers=president["headers"]
    )
    assert response.status_code == 400, response.text


# ── 7. audit ของการดู ───────────────────────────────────────────────────────
async def test_view_is_logged_once_per_first_page(client, db_pool):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    room_id = president["room_id"]
    for i in range(3):
        await _insert_log(db_pool, room_id, entity_id=str(i))

    first = client.get(_url(room_id, limit=2), headers=president["headers"]).json()

    async def _count_view_rows() -> int:
        async with db_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM audit_logs WHERE room_id = $1 AND endpoint_or_command = 'list_audit_logs'",
                room_id,
            )

    assert await _count_view_rows() == 1

    # เลื่อนหน้า — ต้องไม่เขียนแถว VIEW เพิ่ม (ไม่งั้นตารางที่กำลังอ่านจะพองด้วยแถวของตัวเอง)
    assert first["next_cursor"]
    client.get(_url(room_id, limit=2, cursor=first["next_cursor"]), headers=president["headers"])
    assert await _count_view_rows() == 1


# ── 8. options ──────────────────────────────────────────────────────────────
async def test_options_returns_values_present_in_room(client, db_pool):
    president = await _make_member(db_pool, permissions=PRESIDENT)
    room_id = president["room_id"]
    await _insert_log(db_pool, room_id, service_name="FINANCE", action="CREATE")
    await _insert_log(db_pool, room_id, service_name="ACADEMIC", action="UPDATE", status="failed")

    response = client.get(
        f"/api/classroom/{room_id}/audit-logs/options?target_type=room",
        headers=president["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["service_names"] == ["ACADEMIC", "FINANCE"]
    assert body["actions"] == ["CREATE", "UPDATE"]
    assert body["statuses"] == ["failed", "success"]


async def test_options_requires_permission(client, db_pool):
    member = await _make_member(db_pool)
    response = client.get(
        f"/api/classroom/{member['room_id']}/audit-logs/options?target_type=room",
        headers=member["headers"],
    )
    assert response.status_code == 403


# ── 9. migration 0009 ───────────────────────────────────────────────────────
async def test_migration_0009_backfills_leadership_only_and_is_idempotent(db_pool):
    role_sql = import_module("core.migrations.0009_audit_logs_viewer").SQL[0]

    president = await _make_member(db_pool, class_role="president")
    staff = await _make_member(db_pool, class_role="staff_academic")

    async def _permissions(student_row_id: int) -> list[str]:
        # ⚠️ asyncpg คืน jsonb เป็นสตริง (ไม่มี codec ติดตั้ง) ⇒ ต้อง json.loads เอง
        async with db_pool.acquire() as conn:
            raw = await conn.fetchval("SELECT permissions FROM students WHERE id = $1", student_row_id)
        return json.loads(raw)

    # รัน 2 รอบ — ต้องได้ผลเท่ากัน (NOT ... ? กันค่าซ้ำ)
    async with db_pool.acquire() as conn:
        await conn.execute(role_sql)
        await conn.execute(role_sql)

    assert await _permissions(president["student_id"]) == ["VIEW_AUDIT_LOGS"]
    assert await _permissions(staff["student_id"]) == [], "staff ไม่ควรได้สิทธิ์จาก backfill นี้"
