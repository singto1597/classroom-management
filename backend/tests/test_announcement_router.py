"""
Integration tests — ประกาศของห้อง (`routers/announcement_router.py`)

สิ่งที่ล็อกไว้:
  1. **ประกาศหนึ่งครั้งไปถึงทุกช่องทางในธุรกรรมเดียว**: แถว `announcements` +
     แจ้งเตือนของสมาชิกที่ล็อกอินจริง (ไม่รวมผู้เขียน) + audit — ถ้าไม่มีแถวแจ้งเตือน
     ประกาศจะไม่ขึ้นบนกระดิ่งและไม่ถูกส่งต่อ (SSE/push ขับด้วย trigger ของ notifications)
  2. **Discord อยู่หลัง commit** และ `mention` ผูกกับ priority: urgent เท่านั้นที่ @everyone
  3. **สิทธิ์**: ผู้ที่ไม่มี `MANAGE_CLASSROOM_SETTINGS` สร้าง/แก้/เก็บถาวรไม่ได้ (403)
     แต่สมาชิกทั่วไปอ่านได้
  4. **อ่านแล้ว = แถวแจ้งเตือนของผู้ใช้เอง** — mark read แล้ว `is_unread` ต้องเปลี่ยน
     และไม่แตะของคนอื่น
  5. **ปักหมุด/เก็บถาวร**: ปักหมุดแยกออกมาอยู่บนสุด, เก็บถาวรซ่อนจากรายการแต่ยังดึงได้
  6. **quiet hours**: ค่าเริ่มต้น = ปิด, PUT ต้องมีสิทธิ์, audit ถูกเขียน, รูปแบบเวลาผิด = 422

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
และ **mock `ActionService.notify_custom_message`** (ห้ามยิง Redis จริง)
"""
import json
import random
import string
import uuid

import pytest

from core.config import settings
from services.action_service import ActionService

pytestmark = pytest.mark.asyncio


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _insert_user(pool, first_name: str = "Test", last_name: str = "User") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            f"{uuid.uuid4().hex[:12]}@example.com",
            first_name,
            last_name,
            f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int) -> int:
    """เจ้าของห้อง = student แถวแรกที่ is_admin (ผ่าน require_permission ทุกสิทธิ์)"""
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('Test Room', $1, $2) RETURNING id",
            code,
            owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '[]'::jsonb)
            """,
            room_id,
            owner_id,
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb)
            RETURNING id
            """,
            room_id,
            user_id,
            student_no,
        )


def _headers(user_id: int) -> dict:
    from jose import jwt

    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _api(room_id: int, path: str) -> str:
    return f"/api/classroom/{room_id}{path}?target_type=room"


@pytest.fixture
def discord_calls(monkeypatch):
    """แทน Discord ด้วยลิสต์ — เก็บ args ทุกครั้งที่มีคนพยายาม publish"""
    calls: list[dict] = []

    async def _fake(cls, server_id, title, message, user_name, mention=True):
        calls.append(
            {
                "server_id": server_id,
                "title": title,
                "message": message,
                "user_name": user_name,
                "mention": mention,
            }
        )

    monkeypatch.setattr(ActionService, "notify_custom_message", classmethod(_fake))
    return calls


async def _set_room_server_id(pool, room_id: int, server_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET server_id = $2 WHERE id = $1", room_id, server_id)


async def _notifications_of(pool, room_id: int, user_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM notifications WHERE room_id = $1 AND user_id = $2 ORDER BY id",
            room_id,
            user_id,
        )


# ── 1–2. สร้าง + fan-out + Discord ──────────────────────────────────────────
async def test_create_fans_out_to_members_with_accounts(client, db_pool, discord_calls):
    owner = await _insert_user(db_pool, "สมชาย", "ใจดี")
    room_id = await _insert_room(db_pool, owner)
    alice = await _insert_user(db_pool)
    bob = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, alice, 1)
    await _insert_student(db_pool, room_id, bob, 2)
    # สมาชิกที่ยังไม่มีบัญชี (user_id NULL) ต้องไม่ถูกสร้างแจ้งเตือนให้
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, NULL, 3, 'student', 'active', FALSE, '[]'::jsonb)
            """,
            room_id,
        )
    await _set_room_server_id(db_pool, room_id, 123456789)

    resp = client.post(
        _api(room_id, "/announcements"),
        json={"title": "พรุ่งนี้เรียนออนไลน์", "body": "เข้า Zoom 8:00", "priority": "normal"},
        headers=_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["delivered_count"] == 2
    announcement_id = body["item"]["id"]

    # แถวประกาศมีจริงและผูกกับผู้เขียน (ไม่ใช่ชื่อที่ client ส่งมา)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM announcements WHERE id = $1", announcement_id)
    assert row["title"] == "พรุ่งนี้เรียนออนไลน์"
    assert row["created_by"] == owner

    for member in (alice, bob):
        notes = await _notifications_of(db_pool, room_id, member)
        assert len(notes) == 1
        assert notes[0]["group_type"] == "announcement"
        assert notes[0]["entity_type"] == "announcement"
        assert notes[0]["entity_id"] == str(announcement_id)
        assert notes[0]["url"] == f"/announcements/{announcement_id}"

    # ผู้เขียนไม่ต้องได้แจ้งเตือนประกาศของตัวเอง
    assert await _notifications_of(db_pool, room_id, owner) == []

    # Discord: หลัง commit, ประกาศปกติไม่ @everyone, ชื่อผู้ประกาศมาจาก DB
    assert len(discord_calls) == 1
    assert discord_calls[0]["mention"] is False
    assert discord_calls[0]["user_name"] == "สมชาย ใจดี"

    # audit ถูกเขียนในทรานแซกชันเดียวกับประกาศ
    async with db_pool.acquire() as conn:
        audit = await conn.fetchrow(
            """
            SELECT * FROM audit_logs
            WHERE entity_type = 'ANNOUNCEMENT' AND entity_id = $1 AND action = 'CREATE'
            """,
            str(announcement_id),
        )
    assert audit is not None
    assert audit["room_id"] == room_id


async def test_urgent_announcement_mentions_everyone_and_marks_notification_urgent(
    client, db_pool, discord_calls
):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, member, 1)
    await _set_room_server_id(db_pool, room_id, 42)

    resp = client.post(
        _api(room_id, "/announcements"),
        json={"title": "ด่วน", "body": "ปิดเรียนวันนี้", "priority": "urgent"},
        headers=_headers(owner),
    )
    assert resp.status_code == 201, resp.text

    # priority ของแจ้งเตือนถูกส่งผ่านตรง ๆ ⇒ worker เห็น urgent แล้วทะลุ quiet hours เอง
    notes = await _notifications_of(db_pool, room_id, member)
    assert notes[0]["priority"] == "urgent"
    assert discord_calls[0]["mention"] is True


async def test_create_requires_manage_permission(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    plain_member = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, plain_member, 1)

    resp = client.post(
        _api(room_id, "/announcements"),
        json={"title": "ขอประกาศหน่อย", "body": ""},
        headers=_headers(plain_member),
    )
    assert resp.status_code == 403

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM announcements WHERE room_id = $1", room_id)
    assert count == 0


# ── 3–5. อ่าน / อ่านแล้ว / ปักหมุด / เก็บถาวร ───────────────────────────────
async def _create(client, room_id: int, owner_id: int, **payload) -> dict:
    body = {"title": "ประกาศ", "body": "เนื้อหา"}
    body.update(payload)
    resp = client.post(_api(room_id, "/announcements"), json=body, headers=_headers(owner_id))
    assert resp.status_code == 201, resp.text
    return resp.json()["item"]


async def test_list_marks_unread_then_read(client, db_pool, discord_calls):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool)
    other = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, member, 1)
    await _insert_student(db_pool, room_id, other, 2)

    item = await _create(client, room_id, owner, title="ประกาศที่ 1")

    listed = client.get(_api(room_id, "/announcements"), headers=_headers(member)).json()
    assert listed["items"][0]["is_unread"] is True

    read = client.post(
        _api(room_id, f"/announcements/{item['id']}/read"), headers=_headers(member)
    )
    assert read.status_code == 200
    assert read.json()["marked"] is True

    listed = client.get(_api(room_id, "/announcements"), headers=_headers(member)).json()
    assert listed["items"][0]["is_unread"] is False

    # การอ่านของคนหนึ่งไม่กระทบอีกคน
    other_list = client.get(_api(room_id, "/announcements"), headers=_headers(other)).json()
    assert other_list["items"][0]["is_unread"] is True


async def test_mark_read_is_idempotent(client, db_pool, discord_calls):
    """กด "อ่านแล้ว" ซ้ำต้องไม่เปลี่ยนเวลาเดิม และไม่ error"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, member, 1)
    item = await _create(client, room_id, owner)

    first = client.post(_api(room_id, f"/announcements/{item['id']}/read"), headers=_headers(member))
    assert first.status_code == 200
    assert first.json()["marked"] is True

    first_read_at = await db_pool.fetchval(
        "SELECT read_at FROM notifications WHERE user_id = $1 AND entity_type = 'announcement' "
        "AND entity_id = $2",
        member,
        str(item["id"]),
    )
    assert first_read_at is not None

    second = client.post(_api(room_id, f"/announcements/{item['id']}/read"), headers=_headers(member))
    assert second.status_code == 200
    # UPDATE โดนแถวเดิม (WHERE ไม่ได้กรอง read_at) แต่ COALESCE ทำให้เวลาเดิมไม่ถูกทับ
    assert second.json()["marked"] is True

    second_read_at = await db_pool.fetchval(
        "SELECT read_at FROM notifications WHERE user_id = $1 AND entity_type = 'announcement' "
        "AND entity_id = $2",
        member,
        str(item["id"]),
    )
    assert second_read_at == first_read_at, "COALESCE(read_at, NOW()) ต้องไม่ทับเวลาเดิม"


async def test_non_member_cannot_list_announcements(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    await _create(client, room_id, owner)

    outsider = await _insert_user(db_pool)
    resp = client.get(_api(room_id, "/announcements"), headers=_headers(outsider))
    assert resp.status_code == 403


async def test_pinned_are_separate_and_archived_hidden(client, db_pool, discord_calls):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    pinned = await _create(client, room_id, owner, title="ปักหมุด", pinned=True)
    normal = await _create(client, room_id, owner, title="ปกติ")
    archived = await _create(client, room_id, owner, title="เก็บแล้ว")

    archived_resp = client.post(
        _api(room_id, f"/announcements/{archived['id']}/archive"), headers=_headers(owner)
    )
    assert archived_resp.status_code == 200
    assert archived_resp.json()["archived_at"] is not None

    listed = client.get(_api(room_id, "/announcements"), headers=_headers(owner)).json()
    assert [item["id"] for item in listed["pinned"]] == [pinned["id"]]
    assert [item["id"] for item in listed["items"]] == [normal["id"]]

    with_archived = client.get(
        f"/api/classroom/{room_id}/announcements?target_type=room&include_archived=true",
        headers=_headers(owner),
    ).json()
    assert {item["id"] for item in with_archived["items"]} == {normal["id"], archived["id"]}

    # หน้าถัดไปไม่ส่ง pinned ซ้ำ (กันปักหมุดค้างข้ามหน้า)
    second_page = client.get(
        f"/api/classroom/{room_id}/announcements?target_type=room&limit=1&before_id={normal['id']}",
        headers=_headers(owner),
    ).json()
    assert second_page["pinned"] == []


async def test_patch_updates_fields_and_audits(client, db_pool, discord_calls):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    item = await _create(client, room_id, owner)

    resp = client.patch(
        _api(room_id, f"/announcements/{item['id']}"),
        json={"title": "แก้หัวข้อ", "priority": "high"},
        headers=_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["title"] == "แก้หัวข้อ"
    assert updated["priority"] == "high"
    assert updated["body"] == "เนื้อหา"  # ฟิลด์ที่ไม่ส่งต้องไม่ถูกแตะ

    async with db_pool.acquire() as conn:
        audit = await conn.fetchrow(
            """
            SELECT * FROM audit_logs
            WHERE entity_type = 'ANNOUNCEMENT' AND entity_id = $1 AND action = 'UPDATE'
            """,
            str(item["id"]),
        )
    assert audit is not None
    # ⚠️ JSONB ออกมาเป็น `str` (asyncpg ไม่ถอดให้ถ้าไม่ได้ลง codec) — ต้องถอดเอง
    assert json.loads(audit["new_values"])["title"] == "แก้หัวข้อ"

    # การแก้ไม่สร้างแจ้งเตือนใหม่
    async with db_pool.acquire() as conn:
        notes = await conn.fetchval(
            "SELECT COUNT(*) FROM notifications WHERE entity_id = $1", str(item["id"])
        )
    assert notes == 0  # เจ้าของไม่มีแถวแจ้งเตือนของประกาศตัวเอง และไม่มีการ fan-out รอบใหม่


async def test_get_single_is_room_scoped(client, db_pool, discord_calls):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    other_room = await _insert_room(db_pool, owner)
    item = await _create(client, room_id, owner)

    # เจ้าของเป็นสมาชิกทั้งสองห้อง แต่ประกาศของห้องหนึ่งต้องไม่รั่วไปอีกห้อง
    resp = client.get(
        _api(other_room, f"/announcements/{item['id']}"), headers=_headers(owner)
    )
    assert resp.status_code == 404


# ── 6. quiet hours ──────────────────────────────────────────────────────────
async def test_quiet_hours_defaults_to_disabled(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, member, 1)

    resp = client.get(_api(room_id, "/notifications/quiet-hours"), headers=_headers(member))
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "start": "22:00", "end": "07:00"}


async def test_quiet_hours_put_requires_permission_and_audits(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    member = await _insert_user(db_pool)
    await _insert_student(db_pool, room_id, member, 1)

    forbidden = client.put(
        _api(room_id, "/notifications/quiet-hours"),
        json={"enabled": True, "start": "22:00", "end": "07:00"},
        headers=_headers(member),
    )
    assert forbidden.status_code == 403

    saved = client.put(
        _api(room_id, "/notifications/quiet-hours"),
        json={"enabled": True, "start": "22:00", "end": "07:00"},
        headers=_headers(owner),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"enabled": True, "start": "22:00", "end": "07:00"}

    # สมาชิกอ่านได้เพื่ออธิบายว่าทำไม push เงียบ
    read = client.get(_api(room_id, "/notifications/quiet-hours"), headers=_headers(member))
    assert read.json()["enabled"] is True

    async with db_pool.acquire() as conn:
        audit = await conn.fetchrow(
            """
            SELECT * FROM audit_logs
            WHERE entity_type = 'APP_SETTING' AND entity_id = 'quiet_hours' AND action = 'UPDATE'
            """
        )
    assert audit is not None
    assert json.loads(audit["new_values"])["enabled"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": True, "start": "25:00", "end": "07:00"},
        {"enabled": True, "start": "22:60", "end": "07:00"},
        {"enabled": True, "start": "10pm", "end": "07:00"},
    ],
)
async def test_quiet_hours_rejects_bad_format(client, db_pool, payload):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = client.put(
        _api(room_id, "/notifications/quiet-hours"), json=payload, headers=_headers(owner)
    )
    assert resp.status_code == 422
