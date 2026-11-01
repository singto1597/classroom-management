"""
ทะเบียนอุปกรณ์ Web Push ผ่าน HTTP (`/notifications/push/*`)

สิ่งที่ล็อกไว้:
  1. ไม่ได้ตั้งคีย์ VAPID ⇒ `config.enabled = false` และ subscribe ตอบ **503**
     (ไม่ใช่ 500 ที่ทำให้ดูเหมือนระบบพัง)
  2. **endpoint เดียว = หนึ่งเจ้าของ**: ลงทะเบียนซ้ำด้วยบัญชีอื่นต้อง *ย้ายเจ้าของ*
     ไม่ใช่สร้างแถวที่สอง — ไม่งั้นผู้ใช้คนก่อนจะได้ push ของคนใหม่บนเครื่องใช้ร่วม
  3. unsubscribe แตะเฉพาะอุปกรณ์ของตัวเอง
  4. การลงทะเบียนต้องยืนยันตัวว่าเป็นสมาชิกของห้อง (403 ถ้าไม่ใช่)
"""
import random
import string
import uuid

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


async def _insert_user(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username)
            VALUES ($1, 'Test', 'User', $2)
            RETURNING id
            """,
            f"{uuid.uuid4().hex[:12]}@example.com",
            f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int) -> int:
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


async def _join(pool, room_id: int, user_id: int, student_no: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb)
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


def _endpoint() -> str:
    return f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"


def _body(endpoint: str) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "B" * 40, "auth": "a" * 16}}


@pytest.fixture
def vapid_keys(monkeypatch):
    """เปิด push เฉพาะในเทสต์นี้ — ค่าใน `settings` เป็น global ⇒ ต้องคืนค่าหลังเทสต์"""
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "test-public-key")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "test-private-key")


async def test_config_reports_disabled_without_keys(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = client.get(
        f"/api/classroom/{room_id}/notifications/push/config?target_type=room",
        headers=_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json() == {"public_key": "", "enabled": False}


async def test_subscribe_is_503_when_push_not_configured(client, db_pool):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)

    resp = client.post(
        f"/api/classroom/{room_id}/notifications/push/subscribe?target_type=room",
        json=_body(_endpoint()),
        headers=_headers(owner),
    )
    assert resp.status_code == 503


async def test_subscribe_creates_row(client, db_pool, vapid_keys):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    endpoint = _endpoint()

    resp = client.post(
        f"/api/classroom/{room_id}/notifications/push/subscribe?target_type=room",
        json=_body(endpoint),
        headers=_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["endpoint"] == endpoint

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, p256dh, auth, deleted_at FROM push_subscriptions WHERE endpoint = $1",
            endpoint,
        )
    assert row["user_id"] == owner
    assert row["p256dh"] == "B" * 40
    assert row["deleted_at"] is None


async def test_same_endpoint_under_new_account_moves_ownership(client, db_pool, vapid_keys):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    other = await _insert_user(db_pool)
    await _join(db_pool, room_id, other, 1)
    endpoint = _endpoint()

    first = client.post(
        f"/api/classroom/{room_id}/notifications/push/subscribe?target_type=room",
        json=_body(endpoint),
        headers=_headers(owner),
    )
    second = client.post(
        f"/api/classroom/{room_id}/notifications/push/subscribe?target_type=room",
        json=_body(endpoint),
        headers=_headers(other),
    )
    assert first.status_code == second.status_code == 200

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id FROM push_subscriptions WHERE endpoint = $1", endpoint
        )
    assert len(rows) == 1, "เบราว์เซอร์เดิมต้องมีแถวเดียว ไม่ใช่สองแถว"
    assert rows[0]["user_id"] == other, "เจ้าของต้องย้ายไปบัญชีที่ลงทะเบียนล่าสุด"


async def test_unsubscribe_only_removes_own_device(client, db_pool, vapid_keys):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    other = await _insert_user(db_pool)
    await _join(db_pool, room_id, other, 1)
    endpoint = _endpoint()

    client.post(
        f"/api/classroom/{room_id}/notifications/push/subscribe?target_type=room",
        json=_body(endpoint),
        headers=_headers(owner),
    )

    # คนอื่นพยายามถอดอุปกรณ์ของเรา
    resp = client.post(
        f"/api/classroom/{room_id}/notifications/push/unsubscribe?target_type=room",
        json={"endpoint": endpoint},
        headers=_headers(other),
    )
    assert resp.status_code == 200
    assert resp.json() == {"removed": False}

    async with db_pool.acquire() as conn:
        deleted_at = await conn.fetchval(
            "SELECT deleted_at FROM push_subscriptions WHERE endpoint = $1", endpoint
        )
    assert deleted_at is None

    # เจ้าของจริงถอดได้
    resp = client.post(
        f"/api/classroom/{room_id}/notifications/push/unsubscribe?target_type=room",
        json={"endpoint": endpoint},
        headers=_headers(owner),
    )
    assert resp.json() == {"removed": True}
    async with db_pool.acquire() as conn:
        deleted_at = await conn.fetchval(
            "SELECT deleted_at FROM push_subscriptions WHERE endpoint = $1", endpoint
        )
    assert deleted_at is not None


async def test_subscribe_requires_membership(client, db_pool, vapid_keys):
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    outsider = await _insert_user(db_pool)

    resp = client.post(
        f"/api/classroom/{room_id}/notifications/push/subscribe?target_type=room",
        json=_body(_endpoint()),
        headers=_headers(outsider),
    )
    assert resp.status_code == 403
