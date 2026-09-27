"""
Integration tests — POST /api/auth/refresh

**ที่มา:** token ของเว็บมีอายุจำกัดตาม `ACCESS_TOKEN_EXPIRE_MINUTES` และเมื่อครบกำหนด
backend ตอบ 401 → frontend ลบ session ทั้งชุดแล้วเด้งไปหน้า login ⇒ ผู้ใช้ที่เข้าใช้งาน
ทุกวันก็ยังต้องล็อกอินใหม่เมื่อครบรอบ (production ตั้งไว้ 1440 นาที = 24 ชม. พอดี)

endpoint นี้ให้ frontend ต่ออายุล่วงหน้าเป็นรอบ ๆ ระหว่างที่ยังใช้งานอยู่

**สัญญาที่ไฟล์นี้ล็อกไว้:**
1. token ที่ยังไม่หมดอายุ → ได้ token ใหม่ที่ใช้ได้จริง (ยืนยันด้วยการยิง `/me` ต่อ)
2. **`user_id` ใน token ใหม่เป็น `str`** เหมือนที่ `login` สร้าง — ไม่ใช่ `int`
   (ถ้าที่นี่ส่ง int จะได้ token ที่หน้าตาเหมือนกันแต่ชนิดต่างกัน ซึ่งหา bug ยาก)
3. ไม่มี credential → 401
4. token ปลอม/เซ็นด้วยกุญแจผิด → 401
5. บัญชีที่ถูกลบ (soft delete) → 404 ห้ามต่ออายุให้
6. **ไม่ใช่ทางลัดข้ามการล็อกอิน** — token ที่หมดอายุแล้วต้องใช้ไม่ได้ (ไม่มี grace window)
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from core.config import settings

pytestmark = pytest.mark.asyncio


# === Helpers ===


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", deleted=False) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, deleted_at)
            VALUES ($1, $2, $3, $4, CASE WHEN $5 THEN NOW() ELSE NULL END)
            RETURNING id
            """,
            email, first_name, last_name, f"user_{uuid.uuid4().hex[:8]}", deleted,
        )


def _token_for(user_id, *, expires_in_minutes: int | None = 60, secret: str | None = None) -> str:
    """สร้าง JWT แบบเดียวกับที่ `create_access_token()` ทำ (exp เป็น epoch ผ่าน jose)"""
    payload = {"user_id": str(user_id)}
    if expires_in_minutes is not None:
        payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    return jwt.encode(payload, secret or settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


# === Section 1: เส้นทางสำเร็จ ===


async def test_refresh_returns_usable_token(client, db_pool):
    """หัวใจของฟีเจอร์ — token ใหม่ต้องใช้ยิง endpoint ที่ต้อง auth ได้จริง"""
    user_id = await _insert_user(db_pool)

    resp = client.post("/api/auth/refresh", headers=_bearer(_token_for(user_id)))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == str(user_id)
    assert body["token_type"] == "bearer"

    # 🔑 ต้องยิงต่อได้จริง ไม่ใช่แค่ได้สตริงกลับมา
    me = client.get("/api/auth/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["id"] == user_id


async def test_refresh_extends_expiry(client, db_pool):
    """token ใหม่ต้องมี `exp` ไกลกว่าเดิม — ไม่ใช่คืน token เก่ามาเฉย ๆ"""
    user_id = await _insert_user(db_pool)
    old_token = _token_for(user_id, expires_in_minutes=1)
    old_exp = _decode(old_token)["exp"]

    resp = client.post("/api/auth/refresh", headers=_bearer(old_token))
    assert resp.status_code == 200, resp.text

    new_exp = _decode(resp.json()["access_token"])["exp"]
    assert new_exp > old_exp


async def test_refresh_keeps_user_id_as_string(client, db_pool):
    """
    ⚠️ สัญญาชนิดข้อมูล: `login` สร้าง `{"user_id": str(...)}` — ที่นี่ต้องเหมือนกัน

    frontend ถอดค่านี้ไปใช้ต่อ (`decodeJwtPayload` → `setUserId`) ถ้าชนิดไม่ตรงกัน
    จะได้ token ที่ "หน้าตาเหมือนกันแต่พฤติกรรมต่างกัน" ซึ่งตามหาสาเหตุยากมาก
    """
    user_id = await _insert_user(db_pool)

    resp = client.post("/api/auth/refresh", headers=_bearer(_token_for(user_id)))

    assert resp.status_code == 200, resp.text
    assert isinstance(_decode(resp.json()["access_token"])["user_id"], str)


# === Section 2: ปฏิเสธคำขอที่ไม่มีสิทธิ์ ===


async def test_refresh_without_credentials_returns_401(client, db_pool):
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401, resp.text


async def test_refresh_with_forged_token_returns_401(client, db_pool):
    """เซ็นด้วยกุญแจอื่น → 401 (ไม่ใช่ 500 และไม่ใช่ 200)"""
    user_id = await _insert_user(db_pool)
    forged = _token_for(user_id, secret="not-the-real-secret")

    resp = client.post("/api/auth/refresh", headers=_bearer(forged))
    assert resp.status_code == 401, resp.text


async def test_refresh_with_expired_token_returns_401(client, db_pool):
    """
    🔴 ห้ามมี grace window — token ที่หมดอายุแล้วต้องต่ออายุไม่ได้

    ถ้าเผลอรับ token ที่ตายแล้ว (เช่น decode ด้วย `verify_exp: False`) เท่ากับยืดอายุ
    token ที่อาจรั่วไปแล้วโดยไม่มีใครรู้ ซึ่งเป็นช่องโหว่ที่ endpoint นี้ไม่ควรสร้าง
    """
    user_id = await _insert_user(db_pool)
    expired = _token_for(user_id, expires_in_minutes=-1)

    resp = client.post("/api/auth/refresh", headers=_bearer(expired))
    assert resp.status_code == 401, resp.text


async def test_refresh_for_deleted_user_returns_404(client, db_pool):
    """
    token ยังไม่หมดอายุ แต่บัญชีถูกลบไปแล้ว → ห้ามต่ออายุ

    ⚠️ `get_current_user` (เส้นทาง JWT) ไม่ได้แตะ DB เลย มันแค่ถอด token
       ⇒ ถ้า service ไม่เช็คเอง บัญชีที่ถูกลบจะต่ออายุ token ตัวเองได้ตลอดไป
    """
    user_id = await _insert_user(db_pool, deleted=True)

    resp = client.post("/api/auth/refresh", headers=_bearer(_token_for(user_id)))
    assert resp.status_code == 404, resp.text
