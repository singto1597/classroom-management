"""👥 [FIN-V2 / P1.2] ทะเบียนผู้เกี่ยวข้องทางการเงิน + ตั้งค่าการเงินของห้อง

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **กฎรูปทรง person** — student ต้องมี student_id, ครู/บุคคลภายนอกห้ามมี
   (ตรงกับ CHECK `chk_finance_people_student_link`) ⇒ ผู้ใช้ได้ 400 ภาษาไทย
   ไม่ใช่ 500 จาก DB
2. **กันนักเรียนซ้ำ** — partial unique (room_id, student_id) ทำงานจริง
3. **soft delete ต้องไม่ลบแถว** — เอกสารเก่ายังชี้ person เดิม และปิดใช้งานแล้ว
   รายชื่อต้องหายจาก GET
4. **ซิงก์นักเรียน idempotent** และ **ไม่ทับชื่อที่ครูแก้** (กฎที่สำคัญที่สุดของ
   ปุ่ม "ซิงก์รายชื่อ")
5. **settings ไม่มีแถวก็ GET ได้** (คืน default) และ PATCH upsert แถวเดียว
6. **RBAC** — สมาชิกธรรมดาอ่านได้แต่เขียนไม่ได้

⚠️ ทุกอย่างยืนยันกับ Postgres จริงผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import pytest

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


def _people_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/people"


def _settings_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/settings"


async def _insert_student(pool, room_id: int, student_no: int, *, status: str = "active") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 'student', $3, FALSE, '[]'::jsonb) RETURNING id""",
            room_id, student_no, status,
        )


async def _count_people(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM finance_people WHERE room_id = $1 AND deleted_at IS NULL",
            room_id,
        )


# ═══════════════════════════════════════════════════════════════════ 1. สร้าง/อ่าน
async def test_create_student_person_and_read_back(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    res = client.post(
        _people_url(room_id),
        json={
            "person_type": "student",
            "student_id": admin_headers.student_id,
            "display_name": "เด็กชายทดสอบ",
            "roles": ["receive"],
        },
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["person_type"] == "student"
    assert body["roles"] == ["receive"]
    assert body["is_active"] is True

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT person_type, student_id, roles, is_active, deleted_at "
            "FROM finance_people WHERE id = $1",
            body["person_id"],
        )
    assert row["person_type"] == "student"
    assert row["student_id"] == admin_headers.student_id
    assert row["roles"] == ["receive"]
    assert row["is_active"] is True
    assert row["deleted_at"] is None

    # GET ต้องเห็นคนนี้ + ฟิลด์ที่ response_model ประกาศครบ
    listed = client.get(_people_url(room_id), headers=admin_headers)
    assert listed.status_code == 200
    ids = [p["person_id"] for p in listed.json()["people"]]
    assert body["person_id"] in ids


async def test_student_person_requires_student_id(client, admin_headers):
    res = client.post(
        _people_url(admin_headers.room_id),
        json={"person_type": "student", "display_name": "ไม่มีรหัส"},
        headers=admin_headers,
    )
    assert res.status_code == 400
    assert "นักเรียน" in res.json()["detail"]


async def test_teacher_person_must_not_have_student_id(client, admin_headers):
    res = client.post(
        _people_url(admin_headers.room_id),
        json={
            "person_type": "teacher",
            "student_id": admin_headers.student_id,
            "display_name": "ครูทดสอบ",
        },
        headers=admin_headers,
    )
    assert res.status_code == 400


async def test_student_from_another_room_rejected(client, db_pool, admin_headers):
    """ห้ามผูก person กับนักเรียนของห้องอื่นผ่าน API (กัน data leak ข้ามห้อง)"""
    async with db_pool.acquire() as conn:
        other_room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ('ห้องอื่น', 'OTHER1', NULL) RETURNING id"
        )
    other_student_id = await _insert_student(db_pool, other_room_id, 1)

    res = client.post(
        _people_url(admin_headers.room_id),
        json={"person_type": "student", "student_id": other_student_id, "display_name": "ข้ามห้อง"},
        headers=admin_headers,
    )
    assert res.status_code == 400


async def test_duplicate_student_person_rejected(client, db_pool, admin_headers):
    payload = {
        "person_type": "student",
        "student_id": admin_headers.student_id,
        "display_name": "คนเดิม",
    }
    first = client.post(_people_url(admin_headers.room_id), json=payload, headers=admin_headers)
    assert first.status_code == 200

    second = client.post(_people_url(admin_headers.room_id), json=payload, headers=admin_headers)
    assert second.status_code in (400, 409)

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_people WHERE room_id = $1 AND student_id = $2",
            admin_headers.room_id, admin_headers.student_id,
        )
    assert count == 1


async def test_invalid_role_rejected(client, admin_headers):
    res = client.post(
        _people_url(admin_headers.room_id),
        json={"person_type": "external", "display_name": "คนนอก", "roles": ["admin"]},
        headers=admin_headers,
    )
    assert res.status_code == 422


# ═══════════════════════════════════════════════════════════════════ 2. แก้/ลบ
async def test_soft_delete_hides_person_but_keeps_row(client, db_pool, admin_headers):
    created = client.post(
        _people_url(admin_headers.room_id),
        json={"person_type": "external", "display_name": "ผู้ชำระเงิน"},
        headers=admin_headers,
    ).json()
    person_id = created["person_id"]

    res = client.delete(
        f"{_people_url(admin_headers.room_id)}/{person_id}", headers=admin_headers,
    )
    assert res.status_code == 200

    listed = client.get(_people_url(admin_headers.room_id), headers=admin_headers)
    assert person_id not in [p["person_id"] for p in listed.json()["people"]]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT deleted_at, is_active FROM finance_people WHERE id = $1", person_id,
        )
    assert row is not None, "soft delete ต้องไม่ลบแถว"
    assert row["deleted_at"] is not None
    assert row["is_active"] is False


async def test_update_person_roles(client, db_pool, admin_headers):
    created = client.post(
        _people_url(admin_headers.room_id),
        json={"person_type": "teacher", "display_name": "ครูการเงิน"},
        headers=admin_headers,
    ).json()

    res = client.patch(
        f"{_people_url(admin_headers.room_id)}/{created['person_id']}",
        json={"roles": ["receive", "pay"]},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["roles"] == ["receive", "pay"]

    async with db_pool.acquire() as conn:
        roles = await conn.fetchval(
            "SELECT roles FROM finance_people WHERE id = $1", created["person_id"],
        )
    assert roles == ["receive", "pay"]


# ═══════════════════════════════════════════════════════════════════ 3. ซิงก์นักเรียน
async def test_sync_students_is_idempotent(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    for no in (2, 3, 4):
        await _insert_student(db_pool, room_id, no)

    async with db_pool.acquire() as conn:
        active_count = await conn.fetchval(
            """SELECT COUNT(*) FROM students
               WHERE room_id = $1 AND status = 'active' AND deleted_at IS NULL""",
            room_id,
        )

    first = client.post(f"{_people_url(room_id)}/sync-students", headers=admin_headers)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == active_count
    assert first.json()["updated"] == 0

    second = client.post(f"{_people_url(room_id)}/sync-students", headers=admin_headers)
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["updated"] == active_count
    assert await _count_people(db_pool, room_id) == active_count

    # 🔴 ครูแก้ชื่อด้วยมือ → ซิงก์ซ้ำต้องไม่ทับ
    async with db_pool.acquire() as conn:
        person_id = await conn.fetchval(
            "SELECT id FROM finance_people WHERE room_id = $1 AND student_id = $2",
            room_id, admin_headers.student_id,
        )
        await conn.execute(
            "UPDATE finance_people SET display_name = 'ชื่อที่ครูตั้งเอง' WHERE id = $1",
            person_id,
        )

    third = client.post(f"{_people_url(room_id)}/sync-students", headers=admin_headers)
    assert third.status_code == 200

    async with db_pool.acquire() as conn:
        name = await conn.fetchval(
            "SELECT display_name FROM finance_people WHERE id = $1", person_id,
        )
    assert name == "ชื่อที่ครูตั้งเอง", "ซิงก์ต้องไม่ทับชื่อที่ครูแก้"


async def test_sync_only_active_students(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    left_student = await _insert_student(db_pool, room_id, 9, status="left")

    res = client.post(f"{_people_url(room_id)}/sync-students", headers=admin_headers)
    assert res.status_code == 200

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_people WHERE student_id = $1", left_student,
        )
    assert count == 0


# ═══════════════════════════════════════════════════════════════════ 4. settings
async def test_settings_defaults_without_row(client, db_pool, admin_headers):
    res = client.get(_settings_url(admin_headers.room_id), headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "default_receiver_person_id": None,
        "default_wallet_account_id": None,
        "require_receiver": True,
        "receipt_note": None,
    }
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_settings WHERE room_id = $1", admin_headers.room_id,
        )
    assert count == 0, "GET ต้องไม่มี side effect (ไม่สร้างแถว)"


async def test_settings_upsert_and_read(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    person = client.post(
        _people_url(room_id),
        json={"person_type": "teacher", "display_name": "ครูผู้รับเงิน"},
        headers=admin_headers,
    ).json()
    async with db_pool.acquire() as conn:
        account_id = await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, 'เงินสด', 0) RETURNING id",
            room_id,
        )

    patched = client.patch(
        _settings_url(room_id),
        json={
            "default_receiver_person_id": person["person_id"],
            "default_wallet_account_id": account_id,
            "require_receiver": False,
            "receipt_note": "ขอบคุณที่ชำระเงิน",
        },
        headers=admin_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["default_receiver_person_id"] == person["person_id"]

    got = client.get(_settings_url(room_id), headers=admin_headers)
    assert got.status_code == 200
    body = got.json()
    assert body["default_wallet_account_id"] == account_id
    assert body["require_receiver"] is False
    assert body["receipt_note"] == "ขอบคุณที่ชำระเงิน"

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_settings WHERE room_id = $1", room_id,
        )
    assert count == 1, "upsert ต้องมีแถวเดียวต่อห้อง"

    # PATCH ซ้ำต้องไม่งอกแถวใหม่
    client.patch(_settings_url(room_id), json={"require_receiver": True}, headers=admin_headers)
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_settings WHERE room_id = $1", room_id,
        )
    assert count == 1


async def test_settings_rejects_unknown_receiver(client, admin_headers):
    res = client.patch(
        _settings_url(admin_headers.room_id),
        json={"default_receiver_person_id": 999_999},
        headers=admin_headers,
    )
    assert res.status_code == 400


# ═══════════════════════════════════════════════════════════════════ 5. RBAC
async def test_member_cannot_write_people(client, db_pool, member_headers):
    res = client.post(
        _people_url(member_headers.room_id),
        json={"person_type": "external", "display_name": "คนนอก"},
        headers=member_headers,
    )
    assert res.status_code == 403
    assert await _count_people(db_pool, member_headers.room_id) == 0

    # อ่านได้ (transparency) — แต่ต้องเป็นสมาชิกของห้องนั้น
    read = client.get(_people_url(member_headers.room_id), headers=member_headers)
    assert read.status_code == 200


async def test_finance_manager_can_write_people(client, finance_manager_headers):
    res = client.post(
        _people_url(finance_manager_headers.room_id),
        json={"person_type": "external", "display_name": "ผู้ชำระเงิน"},
        headers=finance_manager_headers,
    )
    assert res.status_code == 200, res.text
