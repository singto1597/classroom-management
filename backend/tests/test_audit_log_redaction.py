"""
เทสต์ — ข้อมูลส่วนบุคคลต้องไม่รั่วลง audit_logs

**ที่มา:** การตรวจระบบเมื่อ 2026-09-23 พบว่า `auth_service.process_user_login`
ใช้ `SELECT *` แล้วส่งทั้งแถว `users` เข้า `old_values` ⇒ ข้อมูลสุขภาพ
(`congenital_disease`) เบอร์โทร (`phone_number_parent`) วันเกิด และที่อยู่
ถูกคัดลอกลง `audit_logs` ไปแล้วหลายร้อยแถว ทั้งที่ตารางนั้นมีคนอ่านได้กว้างกว่า

**แก้สองชั้น:**
1. ต้นทาง — เลิกใช้ `SELECT *` ใน `auth_service` (เลือกเฉพาะคีย์ระบุตัวตน)
2. ปลายทาง — `core/logger.py::redact_sensitive()` ปกปิดก่อนเขียนทุกครั้ง

ชั้นที่ 2 คือชั้นที่เทสต์ชุดนี้ล็อกไว้ เพราะผู้เรียก `service_logger.log()` มี 31 จุด
และจะเพิ่มอีก — เทสต์ที่ผูกกับผู้เรียกทีละคนจะไม่กันอะไรเลยในอนาคต
"""
import json
import random
import string
import uuid
from datetime import date

import pytest

from core.logger import REDACTED, redact_sensitive
from models.auth_schemas import OAuthProfilePayload, UserProfileUpdate
from services.auth_service import process_user_login, update_user_profile

# หมายเหตุ: ไฟล์นี้มีทั้งเทสต์ sync (ฟังก์ชันบริสุทธิ์ของ redact_sensitive) และ async
# จึงไม่ใส่ `pytestmark` ระดับโมดูล แต่ติด @pytest.mark.asyncio เฉพาะตัวที่เป็น async
# ⚠️ ห้ามใช้อีเมลโดเมน `.local` ใน payload — EmailStr ของ pydantic ปฏิเสธ TLD สงวน


# === Helpers ===


def _payload(email: str, **over) -> dict:
    data = {"email": email, "first_name": "ทดสอบ", "last_name": "ระบบ"}
    data.update(over)
    return data


async def _insert_full_user(pool, **over) -> int:
    """ผู้ใช้ที่มีข้อมูลส่วนบุคคลครบทุกช่องที่ถือว่าอ่อนไหว"""
    values = {
        "email": f"u{uuid.uuid4().hex[:12]}@example.com",
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "first_name": "สมชาย",
        "last_name": "ใจดี",
        "birthday": date(2008, 5, 14),
        "phone_number": "0812345678",
        "phone_number_parent": "0898765432",
        "phone_number_parent_relation": "มารดา",
        "line_id": "somchai.line",
        "ig_username": "somchai.ig",
        "congenital_disease": "หอบหืด",
        "food_allergy": "ถั่วลิสง",
        "blood_group": "B",
        "shirt_size": "M",
        "address_house_no": "99/1",
        "address_road": "สุขุมวิท",
        "address_sub_district": "คลองเตย",
        "address_district": "คลองเตย",
        "address_province": "กรุงเทพมหานคร",
        "address_post_code": "10110",
    }
    values.update(over)
    cols = ", ".join(values)
    ph = ", ".join(f"${i + 1}" for i in range(len(values)))
    async with pool.acquire() as conn:
        return await conn.fetchval(
            f"INSERT INTO users ({cols}) VALUES ({ph}) RETURNING id",
            *values.values(),
        )


async def _fetch_log(pool, action: str) -> dict:
    """คืน audit row ล่าสุดของ action นั้น — แกะ jsonb เป็น dict ให้แล้ว"""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT old_values, new_values, status FROM audit_logs "
            "WHERE action = $1 ORDER BY created_at DESC LIMIT 1",
            action,
        )
    assert row is not None, f"ไม่พบ audit log ของ action={action}"

    def _load(v):
        return json.loads(v) if isinstance(v, str) else (v or {})

    return {"old": _load(row["old_values"]), "new": _load(row["new_values"]),
            "status": row["status"]}


def _flatten(obj):
    """ดึงค่าทุกค่าที่ซ้อนอยู่ข้างในออกมาเป็น list ของ string — ใช้กวาดหาค่าลับ"""
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flatten(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_flatten(v))
    elif obj is not None:
        out.append(str(obj))
    return out


# === Section 1: ตัว函 redact_sensitive เอง ===


def test_redact_replaces_sensitive_keys():
    """คีย์ที่รู้จักถูกแทนด้วย [REDACTED] ส่วนคีย์อื่นไม่แตะ"""
    src = {"id": 7, "first_name": "สมชาย", "phone_number": "0812345678",
           "congenital_disease": "หอบหืด"}
    out = redact_sensitive(src)

    assert out["phone_number"] == REDACTED
    assert out["congenital_disease"] == REDACTED
    assert out["id"] == 7
    assert out["first_name"] == "สมชาย"  # ชื่อไม่ใช่ความลับ — audit ต้องรู้ว่าใคร


@pytest.mark.parametrize("key", [
    "password_hash", "refresh_token", "client_secret", "API_KEY", "apiKey",
    "session_token", "student_password",
])
def test_redact_catches_future_key_patterns(key):
    """คีย์ความลับที่ยังไม่เกิดวันนี้ ก็ต้องถูกปกปิดโดยไม่ต้องมีใครมาเพิ่มชื่อ"""
    assert redact_sensitive({key: "ค่าลับ"})[key] == REDACTED


def test_redact_walks_nested_structures():
    """payload ของ audit ซ้อนได้ทั้ง dict ใน dict และ list ของ dict"""
    src = {
        "current_user": {"id": 1, "phone_number": "0812345678"},
        "merged_user": {"birthday": "2008-05-14", "email": "a@b.c"},
        "items": [{"line_id": "x"}, {"id": 2}],
    }
    out = redact_sensitive(src)

    assert out["current_user"]["phone_number"] == REDACTED
    assert out["current_user"]["id"] == 1
    assert out["merged_user"]["birthday"] == REDACTED
    assert out["merged_user"]["email"] == "a@b.c"  # ต้องเหลือไว้ audit การรวมบัญชี
    assert out["items"][0]["line_id"] == REDACTED
    assert out["items"][1]["id"] == 2


def test_redact_does_not_mutate_input():
    """ต้องไม่แก้ dict ต้นฉบับ — ผู้เรียกบางเจ้ายังใช้ค่าจริงต่อหลัง log"""
    src = {"phone_number": "0812345678"}
    redact_sensitive(src)
    assert src["phone_number"] == "0812345678"


def test_redact_passes_none_and_scalars():
    assert redact_sensitive(None) is None
    assert redact_sensitive("plain") == "plain"
    assert redact_sensitive(5) == 5


# === Section 2: ด่านที่ logger — หัวใจของการกันซ้ำ ===


@pytest.mark.asyncio
async def test_logger_redacts_a_whole_users_row(db_pool):
    """จำลองอนาคตที่มีคนเผลอเอา SELECT * กลับมา — logger ต้องกันไว้ให้ได้

    เทสต์นี้ตั้งใจ *ไม่* ผ่าน auth_service เลย เพราะสิ่งที่ต้องพิสูจน์คือ
    "ต่อให้ผู้เรียกส่งแถว users เต็ม ๆ มา มันก็ไม่ลงตาราง" — ถ้าด่านอยู่ที่ผู้เรียกเท่านั้น
    เทสต์นี้จะ fail ทันทีที่ผู้เรียกคนใหม่ทำพลาด ซึ่งคือสิ่งที่เราต้องการกัน
    """
    from core.logger import AuditLogger

    user_id = await _insert_full_user(db_pool)
    async with db_pool.acquire() as conn:
        full_row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        leaked_row = dict(full_row)  # ← สิ่งที่ SELECT * เคยส่งเข้า audit

        await AuditLogger(service_name="TEST").log(
            conn=conn,
            action="SIMULATED_SELECT_STAR",
            actor_identifier="tester",
            client_source="test",
            user_id=user_id,
            entity_type="USER",
            entity_id=str(user_id),
            old_values={"existing_by_provider": leaked_row},
            new_values=leaked_row,
        )

    logged = await _fetch_log(db_pool, "SIMULATED_SELECT_STAR")
    flat = _flatten(logged)

    # ค่าจริงต้องไม่โผล่ที่ไหนเลย
    for secret in ("0812345678", "0898765432", "หอบหืด", "ถั่วลิสง",
                   "somchai.line", "99/1", "2008-05-14", "10110"):
        assert secret not in flat, f"ค่า {secret!r} รั่วลง audit_logs"

    # แต่ต้องยังรู้ว่า "ฟิลด์นี้มีอยู่" เพื่อให้ audit ยังตอบคำถามเดิมได้
    assert logged["old"]["existing_by_provider"]["phone_number"] == REDACTED
    assert logged["new"]["congenital_disease"] == REDACTED


@pytest.mark.asyncio
async def test_logger_keeps_non_sensitive_fields_intact(db_pool):
    """ปกปิดต้องไม่กว้างเกิน — ไม่งั้น audit ไร้ค่า"""
    from core.logger import AuditLogger

    async with db_pool.acquire() as conn:
        await AuditLogger(service_name="TEST").log(
            conn=conn,
            action="NON_SENSITIVE_CHECK",
            actor_identifier="tester",
            client_source="test",
            old_values={"room_name": "ม.6/1", "is_admin": True, "student_no": 12},
        )

    logged = await _fetch_log(db_pool, "NON_SENSITIVE_CHECK")
    assert logged["old"] == {"room_name": "ม.6/1", "is_admin": True, "student_no": 12}


# === Section 3: เส้นทางจริงใน auth_service — ต้องไม่หลุดทั้งสองทาง ===


@pytest.mark.asyncio
async def test_login_audit_has_no_personal_data(db_pool):
    """process_user_login ของผู้ใช้เดิม — audit ต้องไม่พกข้อมูลสุขภาพ/ติดต่อเลย"""
    discord_id = random.randint(10_000_000, 99_999_999)
    email = f"u{uuid.uuid4().hex[:12]}@example.com"
    await _insert_full_user(db_pool, discord_id=discord_id, email=email)

    await process_user_login(
        db_pool,
        OAuthProfilePayload(**_payload(email, discord_id=discord_id, username="somchai")),
        client_source="test",
        actor_identifier="tester",
    )

    logged = await _fetch_log(db_pool, "PROCESS_USER_LOGIN")
    flat = _flatten(logged)

    for secret in ("0812345678", "0898765432", "หอบหืด", "somchai.line", "99/1"):
        assert secret not in flat, f"process_user_login รั่วค่า {secret!r}"

    # แถวเดิมถูกดึงมาแบบระบุคอลัมน์ ⇒ ไม่มีแม้แต่คีย์อ่อนไหวให้เห็น
    existing = logged["old"].get("existing_by_provider", {})
    assert "phone_number" not in existing
    assert "congenital_disease" not in existing
    # แต่คีย์ระบุตัวตนยังอยู่ เพราะ audit การรวมบัญชีต้องใช้
    assert existing.get("email") == email


@pytest.mark.asyncio
async def test_profile_update_audit_redacted_but_write_still_real(db_pool):
    """หัวใจ: ปกปิดที่ log แต่ข้อมูลจริงต้องลงฐานข้อมูลครบ

    ถ้าเผลอไปปกปิดที่ชั้น service แทนที่จะเป็นชั้น logger เบอร์โทรจริงในตาราง users
    จะกลายเป็น [REDACTED] — เทสต์นี้จับเคสนั้น
    """
    user_id = await _insert_full_user(db_pool)
    new_phone = "0800000001"
    new_house = "123/45"

    await update_user_profile(
        db_pool, user_id,
        UserProfileUpdate(
            prefix="นาย", first_name="สมชาย", last_name="ใจดี", nickname="ชาย",
            birthday=date(2008, 5, 14), phone_number=new_phone,
            line_id="new.line", address_house_no=new_house, address_road="พหลโยธิน",
            address_sub_district="จตุจักร", address_district="จตุจักร",
            address_province="กรุงเทพมหานคร", address_post_code="10900",
        ),
        client_source="test",
        actor_identifier="tester",
    )

    # 1) ฐานข้อมูลจริงได้ค่าจริง
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT phone_number, address_house_no, line_id FROM users WHERE id = $1",
            user_id,
        )
    assert row["phone_number"] == new_phone, "การปกปิด log ไปโดนข้อมูลจริงเข้า!"
    assert row["address_house_no"] == new_house
    assert row["line_id"] == "new.line"

    # 2) audit ได้ [REDACTED]
    logged = await _fetch_log(db_pool, "UPDATE_USER_PROFILE")
    assert logged["new"]["phone_number"] == REDACTED
    assert logged["new"]["address_house_no"] == REDACTED
    assert logged["new"]["birthday"] == REDACTED
    assert new_phone not in _flatten(logged)
    assert new_house not in _flatten(logged)
    # ชื่อยังต้องเห็น — เป็นสาระของ audit
    assert logged["new"]["first_name"] == "สมชาย"
