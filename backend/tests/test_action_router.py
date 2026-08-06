"""
Integration tests for action_router.py — Web → Discord ประกาศ (CUSTOM_MESSAGE event)

ครอบคลุมผ่าน HTTP (TestClient):
  - Auth path ทั้งสอง: Web (JWT Bearer) และ Discord bot (X-API-Key + X-Discord-Id)
  - Status mapping ของ router: 404 (ไม่มีห้อง), 403 (ไม่มีสิทธิ์), 422 (payload ผิด)
  - publish ผ่าน ActionService.notify_custom_message ถูกเรียกด้วย server_id ที่ถูกต้อง
  - Deep DB verification: audit_logs มีแถว MESSAGE / ข้อความถูกเก็บ
  - Pattern ตาม docs/rules/testing.md: mock ActionService.notify_custom_message (ไม่แตะ Redis จริง)
"""
import random
import string
import uuid
from unittest.mock import patch, AsyncMock

import pytest

from core.config import settings
from services.action_service import ActionService

pytestmark = pytest.mark.asyncio


# === Helpers (ลอก pattern จาก test_finance_http.py) ===


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", username=None, discord_id=None) -> int:
    if username is None:
        username = f"u{uuid.uuid4().hex[:12]}"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            email, first_name, last_name, username, discord_id,
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room", server_id=None) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id, server_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            room_name, code, owner_id, server_id,
        )
        # ผู้สร้างห้องเป็น admin (is_admin=TRUE) → ผ่าน require_permission เสมอ
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *, is_admin=False, permissions="[]") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', 'active', $4, $5::jsonb)
            RETURNING id
            """,
            room_id, user_id, student_no, is_admin, permissions,
        )


def _make_web_headers(user_id: int) -> dict:
    from jose import jwt
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_bot_headers(discord_id: int) -> dict:
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


def _room_api(target_id: int, path: str, target_type: str = "room") -> str:
    return f"/api/classroom/{target_id}{path}?target_type={target_type}"


# === Tests ===


async def test_web_sends_custom_message_to_discord(client, db_pool):
    """Web user (admin) ส่งข้อความ → notify_custom_message ถูกเรียก + audit log ถูกเขียน"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    with patch.object(ActionService, "notify_custom_message", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/messages"),
            json={"title": "ประกาศด่วน", "message": "พรุ่งนี้หยุดเรียน", "user_name": "ครูใหญ่"},
            headers=_make_web_headers(owner),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        mock_notify.assert_awaited_once_with(
            server_id=server_id, title="ประกาศด่วน", message="พรุ่งนี้หยุดเรียน", user_name="ครูใหญ่",
        )

    # Deep DB verification: audit_logs มีแถว MESSAGE
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT room_id, action, entity_type, new_values FROM audit_logs WHERE room_id = $1",
            room_id,
        )
        assert row is not None
        assert row["action"] == "CREATE"
        assert row["entity_type"] == "MESSAGE"
        assert row["room_id"] == room_id


async def test_web_member_with_permission_can_send_message(client, db_pool):
    """สมาชิกที่ได้รับสิทธิ์ MANAGE_CLASSROOM_SETTINGS (ไม่ใช่ admin) ก็ส่งประกาศได้"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    member = await _insert_user(db_pool, first_name="นร.", last_name="มีสิทธิ์")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    await _insert_student(
        db_pool, room_id, member, student_no=1,
        permissions='["MANAGE_CLASSROOM_SETTINGS"]',
    )

    with patch.object(ActionService, "notify_custom_message", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/messages"),
            json={"title": "แจ้งเพื่อน", "message": "การบ้านเล่ม 2", "user_name": "นร.มีสิทธิ์"},
            headers=_make_web_headers(member),
        )
        assert resp.status_code == 200
        mock_notify.assert_awaited_once_with(
            server_id=server_id, title="แจ้งเพื่อน", message="การบ้านเล่ม 2", user_name="นร.มีสิทธิ์",
        )


async def test_web_plain_member_forbidden(client, db_pool):
    """สมาชิกที่ไม่มีสิทธิ์ (permissions ว่าง) → 403 และไม่ publish"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    member = await _insert_user(db_pool, first_name="นร.", last_name="ธรรมดา")
    room_id = await _insert_room(db_pool, owner)
    await _insert_student(db_pool, room_id, member, student_no=1, permissions="[]")

    with patch.object(ActionService, "notify_custom_message", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/messages"),
            json={"title": "แจ้งเพื่อน", "message": "การบ้านเล่ม 2", "user_name": "นร.ธรรมดา"},
            headers=_make_web_headers(member),
        )
        assert resp.status_code == 403
        mock_notify.assert_not_awaited()


async def test_web_outsider_forbidden(client, db_pool):
    """คนนอกห้อง (ไม่ใช่สมาชิก) → 403 และไม่ publish"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool, first_name="คน", last_name="นอกห้อง")

    with patch.object(ActionService, "notify_custom_message", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/messages"),
            json={"title": "ห้าม", "message": "สอดแนม", "user_name": "คนนอกห้อง"},
            headers=_make_web_headers(outsider),
        )
        assert resp.status_code == 403
        mock_notify.assert_not_awaited()


async def test_web_room_not_found_404(client, db_pool):
    """ส่งไปห้องที่ไม่มีอยู่จริง → 404 และไม่ publish"""
    outsider = await _insert_user(db_pool, first_name="คน", last_name="นอกห้อง")

    with patch.object(ActionService, "notify_custom_message", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(999_999_999, "/messages"),
            json={"title": "ทดสอบ", "message": "ไม่มีห้อง", "user_name": "คนนอกห้อง"},
            headers=_make_web_headers(outsider),
        )
        assert resp.status_code == 404
        mock_notify.assert_not_awaited()


async def test_web_requires_auth(client, db_pool):
    """ไม่ส่ง token → 401 (ต้องมีห้องจริง เพราะ resolve_target_to_room_id รันก่อน auth)"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    room_id = await _insert_room(db_pool, owner)

    resp = client.post(
        _room_api(room_id, "/messages"),
        json={"title": "x", "message": "y", "user_name": "z"},
    )
    assert resp.status_code == 401


async def test_web_validation_empty_fields_422(client, db_pool):
    """title / message ว่างเปล่า → 422"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    room_id = await _insert_room(db_pool, owner)

    resp = client.post(
        _room_api(room_id, "/messages"),
        json={"title": "", "message": "", "user_name": "ครูใหญ่"},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 422


async def test_bot_sends_custom_message(client, db_pool):
    """Bot path (X-API-Key + X-Discord-Id) ส่งผ่าน target_type=server ได้เหมือนกัน"""
    discord_id = 775500
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่", discord_id=discord_id)
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    with patch.object(ActionService, "notify_custom_message", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(server_id, "/messages", target_type="server"),
            json={"title": "ประกาศ", "message": "ข้อความจากบอท", "user_name": "ครูใหญ่"},
            headers=_make_bot_headers(discord_id),
        )
        assert resp.status_code == 200
        mock_notify.assert_awaited_once_with(
            server_id=server_id, title="ประกาศ", message="ข้อความจากบอท", user_name="ครูใหญ่",
        )


async def test_bot_api_key_without_discord_id_400(client, db_pool):
    """มี API Key แต่ไม่มี X-Discord-Id → 400"""
    owner = await _insert_user(db_pool, first_name="ครู", last_name="ใหญ่")
    room_id = await _insert_room(db_pool, owner)

    resp = client.post(
        _room_api(room_id, "/messages"),
        json={"title": "x", "message": "y", "user_name": "z"},
        headers={"X-API-Key": settings.API_KEY},
    )
    assert resp.status_code == 400
