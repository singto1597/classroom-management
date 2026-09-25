"""สัญญาระดับ HTTP ของ `/api/auth/*` — ผลตรวจระบบ 2026-09-23 (M4 / M6 / M7)

ทำไมต้องมีไฟล์นี้แยกจาก `test_auth.py`:
`test_auth.py` ทดสอบ **ชั้น service** (เรียกฟังก์ชันตรง ๆ) ซึ่งเป็นชั้นที่บั๊กนี้
*ไม่ได้อยู่* ปัญหาอยู่ที่ `routers/auth_router.py` ซึ่งเป็นชั้นที่ไฟล์นั้นไม่เคยแตะเลย

🔎 บั๊กชนิดนี้รอดสายตามาได้เพราะ **โค้ดอ่านแล้วสมเหตุสมผลทุกบรรทัด**

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

ไม่มีอะไรให้สะดุด: มันดักทุกอย่าง ตั้งรหัส 500 ใส่ข้อความลงไป ดูเหมือน defensive
programming ที่ดีด้วยซ้ำ ⇒ การอ่านโค้ดไม่มีทางจับได้ ต้อง "ยิง HTTP จริงแล้วดูคำตอบ"
เทสต์ชุดนี้จึงยืนยัน **สิ่งที่ผู้เรียกเห็น** (รหัสสถานะ + ข้อความ) ไม่ใช่ตัวโค้ด

สามสิ่งที่ถูกตรึงไว้ที่นี่:
  1. **M6 — 4xx ที่ตั้งใจตอบ ต้องไม่กลายเป็น 500** (`HTTPException` ⊂ `Exception`
     ⇒ ลำดับ `except` ต้องแคบ→กว้าง)
  2. **M7 — ข้อความภายในต้องไม่รั่วออกไป** (ชื่อโฮสต์/ผู้ใช้/รายละเอียดไดรเวอร์)
     แต่ **ข้อความที่ตั้งใจให้ผู้ใช้เห็นต้องไม่ถูกกลืน** (`ForbiddenError`)
  3. **M4 — รายการฟิลด์ที่ออก API ต้องเป็นสัญญาที่ประกาศไว้** ไม่ใช่ผลข้างเคียงของ SQL

⚠️ ไฟล์นี้ตั้ง `pytestmark` ระดับโมดูล ⇒ **ทุกเทสต์ต้องเป็น `async def`** แม้ตัวที่
   ไม่ `await` อะไรเลย (เทสต์ sync ในไฟล์ที่มี mark จะได้ `PytestWarning` ซึ่งกลายเป็น
   เสียงรบกวนที่ทำให้ warning ของจริงถูกมองข้าม — ดู docs/skills.md)
"""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
# M6 — `HTTPException` ที่ raise เองต้องรอดออกไปทั้งรหัสและข้อความ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/auth/discord/login", "/api/auth/google/login"])
async def test_login_missing_code_returns_400_not_500(client, path):
    """`{}` เป็น body ที่ผ่าน Pydantic (ทั้ง `code` และ `access_token` เป็น Optional)

    ⇒ ด่าน `if not payload.code` ต้องตอบ **400** พร้อมข้อความที่บอกสาเหตุ
    ⚠️ ก่อนแก้ ได้ 500 + `"code is required"` ⇒ ผู้ใช้เห็น "เซิร์ฟเวอร์พัง"
       ทั้งที่ความจริงคือ request ของตัวเองผิด และฝั่ง client ก็ไม่รู้จะแก้อะไร
    """
    res = client.post(path, json={})

    assert res.status_code == 400, f"{path} ต้องตอบ 400 ไม่ใช่ {res.status_code}"
    assert res.json()["detail"] == "code is required"


@pytest.mark.parametrize("path", ["/api/auth/discord/login", "/api/auth/google/login"])
async def test_login_propagates_deliberate_http_exception(client, monkeypatch, path):
    """`HTTPException` ที่ **service ตั้งใจ raise** ต้องออกไปทั้งรหัสและข้อความ

    ตัวจริงที่ทำแบบนี้คือ `exchange_code_for_token` ซึ่ง raise 400
    "Discord token exchange failed" เมื่อผู้ให้บริการ OAuth ปฏิเสธ code
    ถ้าตัวดักกว้างกลืนมัน รหัสจะเพี้ยนเป็น 500 และข้อความจะถูก stringify ทับ

    ⚠️ ใช้รหัส 418 โดยเจตนา — ถ้าเทสต์ใช้ 400 (รหัสเดียวกับตัวดักกว้าง)
       จะแยกไม่ออกว่าค่าที่ตั้งใจส่งต่อมาจริง หรือถูกแทนที่ด้วยค่าของตัวดักกว้าง
    """
    from fastapi import HTTPException
    from services import auth_service

    async def _boom(code):
        raise HTTPException(status_code=418, detail="ผู้ให้บริการ OAuth ปฏิเสธคำขอนี้")

    monkeypatch.setattr(auth_service, "exchange_code_for_token", _boom)
    monkeypatch.setattr(auth_service, "exchange_google_code_for_token", _boom)

    res = client.post(path, json={"code": "fake-code"})

    assert res.status_code == 418, f"{path} กลืน HTTPException ที่ตั้งใจ raise (ได้ {res.status_code})"
    assert res.json()["detail"] == "ผู้ให้บริการ OAuth ปฏิเสธคำขอนี้"


# ─────────────────────────────────────────────────────────────────────────────
# M7 — ข้อความภายในต้องไม่รั่ว
# ─────────────────────────────────────────────────────────────────────────────

# ค่าที่จำลองว่า "ข้อความ exception ของ asyncpg/httpx มีอะไรบ้าง"
# ⚠️ เลือกค่าที่ไม่ซ้ำกับข้อความทั่วไป เพื่อให้ assert ตรวจการรั่วได้จริง
_INTERNAL_MARKERS = [
    "10.11.12.13",                     # ที่อยู่ภายใน
    "password authentication failed",  # รายละเอียดไดรเวอร์
    'relation "users"',                # ชื่อตาราง
]


@pytest.mark.parametrize("path", ["/api/auth/discord/login", "/api/auth/google/login"])
async def test_login_internal_error_does_not_leak_exception_text(client, monkeypatch, path):
    """ข้อผิดพลาดที่ไม่คาดคิด → 500 + ข้อความไทยกลาง ๆ **และไม่มีร่องรอยภายในเลย**

    ⚠️ รายละเอียดจริงยังต้องหาได้ — แต่หาได้จาก **log ไม่ใช่จาก HTTP response**
       (ตัวโค้ดใช้ `logger.exception` ซึ่งผูก traceback ไว้ครบ)
    """
    from services import auth_service

    async def _boom(code):
        raise RuntimeError(
            'connection to server at "10.11.12.13", port 5432 failed: '
            'password authentication failed for user "classroom"\n'
            'relation "users" does not exist'
        )

    monkeypatch.setattr(auth_service, "exchange_code_for_token", _boom)
    monkeypatch.setattr(auth_service, "exchange_google_code_for_token", _boom)

    res = client.post(path, json={"code": "fake-code"})

    assert res.status_code == 500
    detail = res.json()["detail"]
    for marker in _INTERNAL_MARKERS:
        assert marker not in detail, f"ข้อความภายในรั่วออก API: {marker!r}"
    # และต้องมีข้อความที่ผู้ใช้เข้าใจได้แทน (ไม่ใช่สตริงว่างหรือคำอังกฤษลอย ๆ)
    assert "ไม่สำเร็จ" in detail


async def test_link_discord_keeps_the_deliberate_forbidden_message(client, admin_headers, monkeypatch):
    """`ForbiddenError` **ไม่ใช่** ข้อความภายใน — ห้ามกลืน

    ตัวจริง: `link_oauth_account` โยน
    `ForbiddenError("บัญชีนี้ผูกกับ discord ID ... อยู่แล้ว กรุณาใช้ ID เดิม")`
    ซึ่งเป็นประโยคที่บอกผู้ใช้ว่าต้องทำอะไรต่อ ⇒ ถ้ากลืนเป็นข้อความกลาง
    ผู้ใช้จะเจอ "ผูกบัญชีไม่สำเร็จ กรุณาลองใหม่" แล้วลองใหม่วนไปเรื่อย ๆ โดยไม่มีทางสำเร็จ

    ⚠️ รหัสคงเป็น **400** ตามเดิม (ไม่เปลี่ยนเป็น 403) — งานนี้คือ "คืนข้อความที่หายไป"
       ไม่ใช่เปลี่ยนสัญญาบนสายให้ frontend ที่ผูกอยู่พัง
    """
    from core.exceptions import ForbiddenError
    from services import auth_service

    async def _fake_token(code):
        return "fake-discord-token"

    async def _fake_profile(token):
        return {"id": 123456789012345678, "email": "someone@example.com", "username": "someone"}

    async def _boom(*args, **kwargs):
        raise ForbiddenError("บัญชีนี้ผูกกับ discord ID 111 อยู่แล้ว กรุณาใช้ ID เดิม")

    monkeypatch.setattr(auth_service, "exchange_code_for_token", _fake_token)
    monkeypatch.setattr(auth_service, "get_discord_user_profile", _fake_profile)
    monkeypatch.setattr(auth_service, "link_oauth_account", _boom)

    res = client.post(
        "/api/auth/discord/link",
        json={"code": "fake-code"},
        headers=admin_headers,
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "บัญชีนี้ผูกกับ discord ID 111 อยู่แล้ว กรุณาใช้ ID เดิม"


# ─────────────────────────────────────────────────────────────────────────────
# M4 / M5 — `GET /me`: รายการฟิลด์คือสัญญา และ SQL ไม่ได้อยู่ที่ router อีกต่อไป
# ─────────────────────────────────────────────────────────────────────────────

# รายชื่อฟิลด์ที่ **ประกาศไว้** ใน `models/auth_schemas.py::UserProfileResponse`
_ME_DECLARED_FIELDS = {
    "id", "prefix", "email", "first_name", "last_name", "first_name_en", "last_name_en",
    "username", "nickname", "nickname_en", "birthday", "phone_number", "line_id",
    "address_house_no", "address_road", "address_sub_district", "address_district",
    "address_province", "address_post_code", "discord_id", "google_id",
}


async def test_me_returns_exactly_the_declared_fields(client, admin_headers):
    """🔴 ตัวชี้ขาดของ M4 — ชุดคีย์ที่ออก API ต้อง **เท่ากับ** ที่ประกาศ ไม่มากไม่น้อย

    ก่อนแก้ `GET /me` คืน `dict(user)` ดิบ ๆ โดยไม่มี `response_model`
    ⇒ **คอลัมน์ไหนถูกเพิ่มเข้า SELECT ก็หลุดออก API ทันที** โดยไม่มีใครตั้งใจ
    (นี่คือวิธีที่ฟิลด์ภายในรั่วออกไปจริง ๆ ไม่ใช่การโจมตี แต่เป็นการเผลอ)

    ⚠️ เทสต์นี้จะ **แดงทันที** ถ้ามีคนเพิ่มคอลัมน์ใน `SELECT` ของ
       `auth_service.get_user_profile` แต่ลืมเพิ่มใน `UserProfileResponse`
       — ซึ่งเป็นพฤติกรรมที่ต้องการ: ให้ความไม่ตรงกันดังตอนเทสต์ ไม่ใช่ตอนผู้ใช้เห็น
    """
    res = client.get("/api/auth/me", headers=admin_headers)

    assert res.status_code == 200
    assert set(res.json().keys()) == _ME_DECLARED_FIELDS


async def test_me_openapi_contract_is_honest(client):
    """OpenAPI ต้องบอกความจริง — ไม่งั้น frontend ที่ generate type จะได้ `{}`

    `response_model` ไม่ได้มีผลแค่ตอน filter คำตอบ แต่เป็นการ **ประกาศสัญญา**
    ให้ `/openapi.json` ซึ่งเป็นแหล่งที่มาของชนิดฝั่ง client
    """
    schema = client.get("/openapi.json").json()
    props = schema["paths"]["/api/auth/me"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    # FastAPI อ้างอิงผ่าน $ref เมื่อเป็น model ที่ประกาศไว้
    assert "$ref" in props, f"GET /me ไม่ได้ประกาศ response_model (schema = {props})"
    ref_name = props["$ref"].rsplit("/", 1)[-1]
    assert set(schema["components"]["schemas"][ref_name]["properties"].keys()) == _ME_DECLARED_FIELDS


async def test_me_unknown_user_returns_404(client):
    """M5 — service คืน `None` แล้ว **router** เป็นคนแปลงเป็น 404

    พิสูจน์เส้นทางนี้ด้วย JWT ของ `user_id` ที่ไม่มีอยู่จริง (เส้นทาง API key
    ใช้ไม่ได้เพราะ `get_current_user` จะ 404 ตั้งแต่ยังไม่ถึง router)
    """
    from services.auth_service import create_access_token

    token = create_access_token({"user_id": "987654321"})
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 404
    assert res.json()["detail"] == "User not found in database."


async def test_get_user_profile_returns_none_instead_of_raising(db_pool):
    """⚠️ ชั้น service ต้องไม่รู้จัก HTTP — M5 ย้าย SQL มาที่นี่โดย **ไม่** เปลี่ยน
    ให้มันโยน `HTTPException` (ไม่งั้นชั้น service จะผูกกับ FastAPI และเรียกซ้ำ
    จากงานอื่นไม่ได้)
    """
    from services.auth_service import get_user_profile

    assert await get_user_profile(db_pool, 987654321) is None


# ─────────────────────────────────────────────────────────────────────────────
# M4 (ต่อ) — `room_router` อนุมัติ/ปฏิเสธคำขอ: รูปคำตอบต้องตรงกับที่ประกาศ
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def pending_student_no(db_pool, admin_headers) -> int:
    """นักเรียนสถานะ `pending` ในห้องของ admin (ยิง API ได้จริงผ่าน headers)

    `added_by` ปล่อยเป็น NULL โดยเจตนา — ถ้าไม่ NULL จะโดนด่าน Consent Model
    ("คำเชิญนี้รอการยืนยันจากนักเรียน") ซึ่งเป็นคนละเส้นทาง
    """
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, student_no, class_role, status)
            VALUES ($1, $2, 'student', 'pending')
            RETURNING student_no
            """,
            admin_headers.room_id, 42,
        )


async def test_approve_request_response_shape(client, admin_headers, pending_student_no, db_pool):
    """รูปคำตอบต้องเป็น `{status, message}` เท่านั้น **และ** ต้องเปลี่ยน DB จริง

    ⚠️ ตรวจ DB ด้วย (`docs/rules/testing.md` บังคับ) — เพราะการยืนยันแค่ HTTP 200
       พิสูจน์ได้แค่ว่า handler ตอบ ไม่ได้พิสูจน์ว่าคำสั่ง SQL มีผล
    """
    res = client.put(
        f"/api/classroom/{admin_headers.room_id}/requests/{pending_student_no}/approve",
        headers=admin_headers,
    )

    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"status", "message"}
    assert body["status"] == "success"
    assert str(pending_student_no) in body["message"]

    async with db_pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT status FROM students WHERE room_id = $1 AND student_no = $2",
            admin_headers.room_id, pending_student_no,
        )
    assert status == "active"
