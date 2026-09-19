"""
เปรียบเทียบกิจกรรม (Intersection / Union / ลบ) + แผนภาพเวน + Excel export รวม — integration tests.

ครอบคลุมตาม docs/rules/testing.md:
  - Real Postgres + clean_database fixture (state isolation)
  - Randomized IDs — ห้าม hardcode (ทุก helper `RETURNING id`)
  - Deep DB verification: หลัง assert → query `activity_participants` พิสูจน์ว่าใครอยู่กิจกรรมไหน
  - Mock ActionService.notify_new_activity (กันแตะ Redis จริง)
  - เทสต์ที่แตะ Excel: หาแถว/คอลัมน์ด้วย **ป้ายหัวตาราง + เลขที่นักเรียน** ไม่ผูกกับ index
"""
import io
import json
import random
import string
import uuid
from datetime import date

import openpyxl
import pytest
from unittest.mock import AsyncMock, patch

from core.config import settings
from core.exceptions import ValidationError
from services.action_service import ActionService
from services.activity_service import ActivityService
from services.activity.sets import build_regions, region_key

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


# === Fixtures & Setup (copy pattern จาก test_activity.py) ===


async def _insert_user(pool, *, first_name="Test", last_name="User", nickname=None, email=None, discord_id=None) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, nickname, username, discord_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            email, first_name, last_name, nickname, f"user_{uuid.uuid4().hex[:8]}", discord_id,
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
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_student(pool, room_id: int, user_id: int, student_no: int, *, status="active", permissions="[]") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, $3, 'student', $4, FALSE, $5::jsonb)
            RETURNING id
            """,
            room_id, user_id, student_no, status, permissions,
        )


def _parse_metadata(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _make_web_headers(user_id: int) -> dict:
    from jose import jwt
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _activity_api(room_id: int, path: str = "", target_type: str = "room") -> str:
    return f"{API_PREFIX}/{room_id}/activities{path}?target_type={target_type}"


async def _seed_room(db_pool, *, count=5):
    """ห้อง + เจ้าของ (admin) + นักเรียน count คน พร้อมชื่อเล่น 'เล่น<N>' → (room_id, owner_id, {no: user_id})"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner)
    users = {}
    for no in range(1, count + 1):
        user_id = await _insert_user(
            db_pool, first_name=f"ชื่อ{no}", last_name=f"นามสกุล{no}", nickname=f"เล่น{no}"
        )
        await _insert_student(db_pool, room_id, user_id, no)
        users[no] = user_id
    return room_id, owner, users


async def _make_activity(db_pool, room_id, owner, *, title, student_nos=(), dynamic_fields=None,
                         required_fields=None, participant_metadata=None, activity_date=date(2026, 10, 1)):
    """สร้างกิจกรรมผ่าน service — `student_nos` คือเลขที่ที่จะเข้าร่วม"""
    metadata = {}
    if dynamic_fields:
        # copy ต่อรายการ — DATETIME_FIELD ฯลฯ เป็นค่าคงที่ระดับโมดูล ห้ามให้ service แก้ทับ
        metadata["dynamic_fields"] = [dict(d) for d in dynamic_fields]
    if required_fields:
        metadata["required_fields"] = required_fields
    per_person = participant_metadata or {}
    participants = [
        {"student_no": no, "role_type": "participant", "metadata": per_person.get(no, {})}
        for no in student_nos
    ]
    with patch.object(ActionService, "notify_new_activity", new_callable=AsyncMock):
        result = await ActivityService.create_activity(
            pool=db_pool, title=title, activity_date=activity_date, base_hours=8.0,
            status="upcoming", metadata=metadata, participants=participants,
            user_name="ผู้ดูแล", client_source="WEB_APP", actor_identifier="user_id:1",
            room_id=room_id, actor_user_id=owner,
        )
    return result["activity_id"]


async def _participant_student_nos(db_pool, activity_id: int) -> set:
    """🔎 Deep DB verification — อ่านจาก activity_participants ตรง ๆ ว่าใครอยู่กิจกรรมนี้"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.student_no
            FROM activity_participants ap
            JOIN students s ON ap.student_id = s.id
            WHERE ap.activity_id = $1 AND ap.deleted_at IS NULL
            """,
            activity_id,
        )
    return {r["student_no"] for r in rows}


async def _compare(db_pool, owner, room_id, activity_ids):
    return await ActivityService.compare_activities(
        pool=db_pool, activity_ids=list(activity_ids), user_id=owner,
        client_source="WEB_APP", actor_identifier="user_id:1", room_id=room_id,
    )


async def _export_combined(db_pool, owner, room_id, *, activity_ids, region_keys,
                           include_activity_fields=False, metadata_keys=None, user_name="ผู้ดูแล"):
    excel = await ActivityService.export_activities_combined_excel(
        pool=db_pool, activity_ids=list(activity_ids), region_keys=list(region_keys),
        metadata_keys=metadata_keys or [], include_activity_fields=include_activity_fields,
        user_name=user_name, user_id=owner, client_source="WEB_APP",
        actor_identifier="user_id:1", room_id=room_id,
    )
    return excel, openpyxl.load_workbook(io.BytesIO(excel.getvalue()))


# --- helpers อ่าน Excel ด้วย "ป้าย" ไม่ใช่ index ---


def _header(ws) -> list:
    return list(list(ws.values)[0])


def _col(ws, label: str) -> int:
    """index ของคอลัมน์จากหัวตาราง — raise ถ้าไม่มี (message บอกหัวที่มีจริง)"""
    header = _header(ws)
    assert label in header, f"ไม่พบคอลัมน์ '{label}' — หัวตารางที่มี: {header}"
    return header.index(label)


def _row_of(ws, student_no: int) -> tuple:
    """แถวของนักเรียนเลขที่ student_no (คอลัมน์แรกเป็น int)"""
    for row in list(ws.values)[1:]:
        if row[0] == student_no:
            return row
    raise AssertionError(f"ไม่พบแถวของเลขที่ {student_no}")


def _student_nos_in_sheet(ws) -> set:
    """เลขที่ทุกแถวข้อมูล — แถวรวมท้ายตารางมีค่าเป็นสตริงจึงถูกตัดออกเอง"""
    return {row[0] for row in list(ws.values)[1:] if isinstance(row[0], int)}


def _preset_keys(regions, activity_ids) -> list:
    """คีย์ภูมิภาคที่มี `activity_ids` ตรงกับชุดที่ให้ (จำลองปุ่มสำเร็จรูปฝั่งหน้า)"""
    wanted = sorted(activity_ids)
    return [r["key"] for r in regions if sorted(r["activity_ids"]) == wanted]


# ================================================================
# 1) ตรรกะภูมิภาค (service-level + deep DB verification)
# ================================================================


async def test_compare_two_activities_returns_three_regions(db_pool):
    """2 กิจกรรม → 3 ภูมิภาค และสมาชิกแต่ละภูมิภาคตรงกับ DB จริง"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="ไปทัศนศึกษา", student_nos=(1, 2, 3))
    b = await _make_activity(db_pool, room_id, owner, title="กีฬาสี", student_nos=(2, 3, 4))

    # 🔎 พิสูจน์ก่อนว่าข้อมูลตั้งต้นใน DB เป็นอย่างที่คิด
    assert await _participant_student_nos(db_pool, a) == {1, 2, 3}
    assert await _participant_student_nos(db_pool, b) == {2, 3, 4}

    data = await _compare(db_pool, owner, room_id, [a, b])

    regions = {r["key"]: r for r in data["regions"]}
    assert set(regions) == {region_key([a]), region_key([b]), region_key([a, b])}
    assert {m["student_no"] for m in regions[region_key([a])]["members"]} == {1}
    assert {m["student_no"] for m in regions[region_key([b])]["members"]} == {4}
    assert {m["student_no"] for m in regions[region_key([a, b])]["members"]} == {2, 3}

    # กิจกรรมที่เลือกถูกส่งกลับตามลำดับที่ขอ + จำนวนผู้เข้าร่วมตรงกับ DB
    assert [x["id"] for x in data["activities"]] == [a, b]
    assert [x["participant_count"] for x in data["activities"]] == [3, 3]
    assert data["activities"][0]["title"] == "ไปทัศนศึกษา"


async def test_compare_three_activities_partitions_all_members(db_pool):
    """3 กิจกรรม → ทุกคนถูกจัดเข้ากุมิภาคเดียว และจำนวนรวมเท่ากับคนที่ไม่ซ้ำ"""
    room_id, owner, _ = await _seed_room(db_pool, count=7)
    a = await _make_activity(db_pool, room_id, owner, title="กิจกรรม A", student_nos=(1, 2, 3, 4))
    b = await _make_activity(db_pool, room_id, owner, title="กิจกรรม B", student_nos=(2, 3, 5))
    c = await _make_activity(db_pool, room_id, owner, title="กิจกรรม C", student_nos=(3, 4, 6, 7))

    data = await _compare(db_pool, owner, room_id, [a, b, c])
    regions = {r["key"]: r for r in data["regions"]}

    # ภูมิภาคที่ควรมีคน (คำนวณจาก DB — คนที่อยู่ชุดกิจกรรมเดียวกันเป๊ะ)
    expected = build_regions(
        [a, b, c],
        {
            a: [{"student_id": no, "student_no": no} for no in (1, 2, 3, 4)],
            b: [{"student_id": no, "student_no": no} for no in (2, 3, 5)],
            c: [{"student_id": no, "student_no": no} for no in (3, 4, 6, 7)],
        },
    )
    assert set(regions) == {r["key"] for r in expected}
    for region in expected:
        got = {m["student_no"] for m in regions[region["key"]]["members"]}
        assert got == {m["student_no"] for m in region["members"]}, region["key"]

    # 🌟 ภูมิภาคเป็น partition — ห้ามมีใครโผล่ 2 ภูมิภาค (นับรวมแล้วต้องเท่าจำนวนคนที่ไม่ซ้ำ)
    all_nos = [m["student_no"] for r in data["regions"] for m in r["members"]]
    assert len(all_nos) == len(set(all_nos)) == 7
    # เลขที่ 3 อยู่ครบทั้งสามกิจกรรม → ต้องเป็นสมาชิกคนเดียวของภูมิภาคกลาง
    assert {m["student_no"] for m in regions[region_key([a, b, c])]["members"]} == {3}


async def test_compare_regions_are_slim_no_pii(db_pool):
    """🔒 endpoint นี้เปิดด้วย require_member → ต้องคืนเฉพาะฟิลด์ชื่อ ไม่มี metadata/PII"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1, 2))
    b = await _make_activity(db_pool, room_id, owner, title="B", student_nos=(1,))

    data = await _compare(db_pool, owner, room_id, [a, b])
    member = data["regions"][0]["members"][0]
    assert set(member) == {
        "student_id", "student_no", "first_name", "last_name", "nickname",
        "first_name_en", "last_name_en", "nickname_en",
    }
    # ชื่อเล่นติดมา (ใช้แสดงบนแผนภาพ) แต่ไม่มี metadata/PII หลุด
    assert member["nickname"] == f"เล่น{member['student_no']}"


# ================================================================
# 2) HTTP layer — serialization, validation, RBAC
# ================================================================


async def test_http_compare_returns_body_through_response_model(client, db_pool):
    """ผ่านชั้น serialization จริง — response_model ต้องไม่ตัด regions/activities ทิ้ง"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="งาน A", student_nos=(1, 2))
    b = await _make_activity(db_pool, room_id, owner, title="งาน B", student_nos=(2, 3))

    resp = client.post(
        _activity_api(room_id, "/compare"),
        json={"activity_ids": [a, b]},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert [x["title"] for x in body["activities"]] == ["งาน A", "งาน B"]
    assert body["activities"][0]["activity_date"] == "2026-10-01"
    assert body["activities"][0]["participant_count"] == 2

    assert len(body["regions"]) == 3
    keys = {r["key"] for r in body["regions"]}
    assert keys == {region_key([a]), region_key([b]), region_key([a, b])}
    # สมาชิกถูก serialize ครบทุกคีย์ (คีย์ที่ service ตั้งต้องอยู่ในโมเดล)
    for region in body["regions"]:
        assert set(region) == {"key", "activity_ids", "members"}
        for member in region["members"]:
            assert "student_no" in member and "nickname" in member


@pytest.mark.parametrize("activity_ids", [[], [7], [7, 8, 9, 10]])
async def test_http_compare_rejects_wrong_activity_count(client, db_pool, activity_ids):
    """จำนวนกิจกรรมต้องเป็น 2–3 — 1 หรือ 4 ต้องถูกปฏิเสธที่ชั้น validation"""
    room_id, owner, _ = await _seed_room(db_pool)
    resp = client.post(
        _activity_api(room_id, "/compare"),
        json={"activity_ids": activity_ids},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 422, resp.text
    assert "activity_ids" in resp.text


async def test_compare_service_rejects_duplicate_ids(db_pool):
    """ส่ง id เดียวกันซ้ำ 2 ครั้ง → ValidationError (ไม่ใช่ 3 ภูมิภาคมั่ว ๆ)"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))

    with pytest.raises(ValidationError) as exc:
        await _compare(db_pool, owner, room_id, [a, a])
    assert "ซ้ำ" in str(exc.value)


async def test_http_compare_duplicate_ids_400(client, db_pool):
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))
    resp = client.post(
        _activity_api(room_id, "/compare"),
        json={"activity_ids": [a, a]},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400, resp.text
    assert "ซ้ำ" in resp.json()["detail"]


async def test_http_compare_activity_from_other_room_404(client, db_pool):
    """IDOR — กิจกรรมของห้องอื่นต้องไม่ถูกอ่านได้ แม้จะรู้ id"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))

    other_room_id, other_owner, _ = await _seed_room(db_pool)
    foreign = await _make_activity(db_pool, other_room_id, other_owner, title="ลับ", student_nos=(1,))

    resp = client.post(
        _activity_api(room_id, "/compare"),
        json={"activity_ids": [a, foreign]},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 404, resp.text
    assert str(foreign) in resp.json()["detail"]


async def test_http_compare_member_can_read_outsider_forbidden(client, db_pool):
    """require_member: สมาชิกห้องอ่านได้ / คนนอกห้อง 403"""
    room_id, owner, users = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))
    b = await _make_activity(db_pool, room_id, owner, title="B", student_nos=(2,))
    payload = {"activity_ids": [a, b]}

    # สมาชิกธรรมดา (ไม่ใช่ admin ไม่มีสิทธิ์) → อ่านได้
    member = users[3]
    resp = client.post(_activity_api(room_id, "/compare"), json=payload, headers=_make_web_headers(member))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["regions"]) == 2

    # คนที่ไม่ใช่สมาชิกห้องนี้เลย → 403
    outsider = await _insert_user(db_pool, first_name="นอก", last_name="ห้อง")
    resp = client.post(_activity_api(room_id, "/compare"), json=payload, headers=_make_web_headers(outsider))
    assert resp.status_code == 403, resp.text
    # 🔴 ข้อความ error ต้องไม่พา URL/hostname ภายในออกไป
    assert "http" not in resp.json()["detail"]


# ================================================================
# 3) Export รวม — Intersection / Union / ลบ
# ================================================================


async def test_export_combined_intersection_only_common_members(db_pool):
    """pุ่ม 'ซ้ำทุกกิจกรรม' → ชีตรายชื่อรวมมีเฉพาะคนที่อยู่ครบทุกกิจกรรม"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="งาน A", student_nos=(1, 2, 3))
    b = await _make_activity(db_pool, room_id, owner, title="งาน B", student_nos=(2, 3, 4))

    data = await _compare(db_pool, owner, room_id, [a, b])
    keys = _preset_keys(data["regions"], [a, b])
    assert len(keys) == 1

    _, wb = await _export_combined(db_pool, owner, room_id, activity_ids=[a, b], region_keys=keys)
    ws = wb["รายชื่อรวม"]
    assert _student_nos_in_sheet(ws) == {2, 3}

    # 🌟 ติ๊กถูกครบทั้งสองคอลัมน์กิจกรรมสำหรับคนที่อยู่ทั้งคู่
    assert _row_of(ws, 2)[_col(ws, "งาน A")] == "✓"
    assert _row_of(ws, 2)[_col(ws, "งาน B")] == "✓"
    # ลำดับคอลัมน์: 4 คอลัมน์พื้นฐาน แล้วต่อด้วย 1 คอลัมน์ต่อ 1 กิจกรรม (ตามลำดับที่เลือก)
    assert _header(ws) == ["เลขที่", "ชื่อจริง", "นามสกุล", "ชื่อเล่น", "งาน A", "งาน B"]


async def test_export_combined_union_and_difference(db_pool):
    """Union = ทุกคน / ลบ (เฉพาะ A) = คนที่อยู่ A เดี่ยว — จากชุดภูมิภาคเดียวกัน"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="งาน A", student_nos=(1, 2, 3))
    b = await _make_activity(db_pool, room_id, owner, title="งาน B", student_nos=(2, 3, 4))

    data = await _compare(db_pool, owner, room_id, [a, b])
    all_keys = [r["key"] for r in data["regions"]]

    # Union — ทุกภูมิภาค
    _, wb_union = await _export_combined(db_pool, owner, room_id, activity_ids=[a, b], region_keys=all_keys)
    ws_union = wb_union["รายชื่อรวม"]
    assert _student_nos_in_sheet(ws_union) == {1, 2, 3, 4}

    # ลบ — เฉพาะภูมิภาคที่อยู่ A เดี่ยว ๆ
    diff_keys = _preset_keys(data["regions"], [a])
    _, wb_diff = await _export_combined(db_pool, owner, room_id, activity_ids=[a, b], region_keys=diff_keys)
    ws_diff = wb_diff["รายชื่อรวม"]
    assert _student_nos_in_sheet(ws_diff) == {1}
    assert _row_of(ws_diff, 1)[_col(ws_diff, "งาน A")] == "✓"
    assert _row_of(ws_diff, 1)[_col(ws_diff, "งาน B")] == "–"


async def test_export_combined_unknown_or_blank_region_key_rejected(db_pool):
    """คีย์ภูมิภาคที่ไม่ได้มาจาก compare (หรือว่าง) → ปฏิเสธ ไม่ใช่ export เงียบ ๆ"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))
    b = await _make_activity(db_pool, room_id, owner, title="B", student_nos=(2,))

    with pytest.raises(ValidationError) as exc:
        await _export_combined(db_pool, owner, room_id, activity_ids=[a, b], region_keys=["999-1000"])
    assert "ไม่รู้จัก" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        await _export_combined(db_pool, owner, room_id, activity_ids=[a, b], region_keys=["   "])
    assert "อย่างน้อย 1 ภูมิภาค" in str(exc.value)


async def test_http_export_combined_unknown_region_key_400(client, db_pool):
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))
    b = await _make_activity(db_pool, room_id, owner, title="B", student_nos=(2,))

    resp = client.post(
        _activity_api(room_id, "/export/combined"),
        json={"activity_ids": [a, b], "region_keys": ["1-2-3"], "user_name": "ผู้ดูแล"},
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 400, resp.text
    assert "ไม่รู้จัก" in resp.json()["detail"]


async def test_export_combined_requires_manage_permission(client, db_pool):
    """export ต้องใช้ MANAGE_ACTIVITIES — สมาชิกธรรมดาได้ 403"""
    room_id, owner, users = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="A", student_nos=(1,))
    b = await _make_activity(db_pool, room_id, owner, title="B", student_nos=(2,))

    resp = client.post(
        _activity_api(room_id, "/export/combined"),
        json={"activity_ids": [a, b], "region_keys": [region_key([a])], "user_name": "สมาชิก"},
        headers=_make_web_headers(users[3]),
    )
    assert resp.status_code == 403, resp.text


async def test_http_export_combined_returns_xlsx_with_thai_filename(client, db_pool):
    """HTTP layer คืนไฟล์จริง + ชื่อไฟล์ไทยแบบ RFC 5987 + ชีตชื่อไม่เกิน 31 ตัวอักษร"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="ไปทัศนศึกษา", student_nos=(1, 2))
    b = await _make_activity(db_pool, room_id, owner, title="กีฬาสี", student_nos=(2,))

    resp = client.post(
        _activity_api(room_id, "/export/combined"),
        json={
            "activity_ids": [a, b],
            "region_keys": [region_key([a, b])],
            "include_activity_fields": False,
            "user_name": "ผู้ดูแล",
        },
        headers=_make_web_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    cd = resp.headers.get("content-disposition", "")
    assert "filename*=UTF-8''" in cd
    assert "combined_activities.xlsx" in cd  # ASCII fallback

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["สรุป", "รายชื่อรวม"]
    for name in wb.sheetnames:
        assert len(name) <= 31

    ws = wb["รายชื่อรวม"]
    assert _student_nos_in_sheet(ws) == {2}
    assert _row_of(ws, 2)[_col(ws, "ไปทัศนศึกษา")] == "✓"


async def test_export_combined_summary_lists_regions_with_nicknames(db_pool):
    """ชีตสรุป — แสดงชื่อเล่นของแต่ละภูมิภาคครบ (ไม่ตัดทิ้ง) และยอดรวมไม่ซ้ำ"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(db_pool, room_id, owner, title="งาน A", student_nos=(1, 2, 3))
    b = await _make_activity(db_pool, room_id, owner, title="งาน B", student_nos=(2, 3, 4))

    data = await _compare(db_pool, owner, room_id, [a, b])
    _, wb = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=[r["key"] for r in data["regions"]]
    )
    ws = wb["สรุป"]
    # แถวภูมิภาคคือแถวที่คอลัมน์ B เป็นตัวเลข (แถวกิจกรรมมีคอลัมน์ B เป็นวันที่เป็นสตริง)
    region_rows = {row[0]: (row[1], row[2]) for row in ws.values if isinstance(row[1], int)}

    assert region_rows["งาน A + งาน B"] == (2, "เล่น2, เล่น3")
    assert region_rows["งาน A"] == (1, "เล่น1")
    assert region_rows["งาน B"] == (1, "เล่น4")

    text = "\n".join(str(c) for row in ws.values for c in row if c is not None)
    assert "รวมทั้งหมด (ไม่ซ้ำ): 4 คน" in text
    assert "1 ตุลาคม 2569" in text  # วันที่กิจกรรมเป็น พ.ศ.


# ================================================================
# 4) วันที่รายคน (โจทย์ข้อ 3) — ทั้ง export รวมและ export เดี่ยว
# ================================================================

DATETIME_FIELD = {"key": "df_1", "label": "เวลาเข้าพัก", "type": "datetime"}
INPUT_FIELD = {"key": "df_2", "label": "หมายเหตุรถ", "type": "input"}


async def test_export_combined_datetime_field_renders_thai_format(db_pool):
    """ฟิลด์ที่ประกาศ type=datetime → '1 ตุลาคม 2569 13:00 น.' (ค่าดิบจาก datetime-local)"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(
        db_pool, room_id, owner, title="ค่าย", student_nos=(1,),
        dynamic_fields=[DATETIME_FIELD], participant_metadata={1: {"df_1": "2026-10-01T13:00"}},
    )
    b = await _make_activity(db_pool, room_id, owner, title="อีกงาน", student_nos=(1,))

    _, wb = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=[region_key([a, b])],
        include_activity_fields=True,
    )
    ws = wb["รายชื่อรวม"]
    assert _row_of(ws, 1)[_col(ws, "เวลาเข้าพัก")] == "1 ตุลาคม 2569 13:00 น."


async def test_export_combined_input_field_keeps_raw_value(db_pool):
    """คู่ตรงข้าม: ค่า ISO เดียวกันแต่ฟิลด์ประกาศ type=input → ต้องไม่ถูกจัดรูปแบบ"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(
        db_pool, room_id, owner, title="ค่าย", student_nos=(1,),
        dynamic_fields=[INPUT_FIELD], participant_metadata={1: {"df_2": "2026-10-01T13:00"}},
    )
    b = await _make_activity(db_pool, room_id, owner, title="อีกงาน", student_nos=(1,))

    _, wb = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=[region_key([a, b])],
        include_activity_fields=True,
    )
    ws = wb["รายชื่อรวม"]
    # พิสูจน์ว่ากรองด้วย **declared type** จริง ไม่ได้เดาจากรูปร่างค่า
    assert _row_of(ws, 1)[_col(ws, "หมายเหตุรถ")] == "2026-10-01T13:00"


async def test_export_combined_datetime_timezone_and_free_text(db_pool):
    """ค่า UTC ถูกเลื่อนเป็นเวลาไทย (+7) แต่ free text ที่ parse ไม่ได้ต้องคืนเดิม"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(
        db_pool, room_id, owner, title="ค่าย", student_nos=(1,),
        dynamic_fields=[
            DATETIME_FIELD,
            {"key": "df_3", "label": "เวลาเดินทาง", "type": "datetime"},
        ],
        participant_metadata={1: {"df_1": "2026-10-01T06:00:00Z", "df_3": "หลังเลิกเรียน"}},
    )
    b = await _make_activity(db_pool, room_id, owner, title="อีกงาน", student_nos=(1,))

    _, wb = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=[region_key([a, b])],
        include_activity_fields=True,
    )
    row = _row_of(wb["รายชื่อรวม"], 1)
    assert row[_col(wb["รายชื่อรวม"], "เวลาเข้าพัก")] == "1 ตุลาคม 2569 13:00 น."
    assert row[_col(wb["รายชื่อรวม"], "เวลาเดินทาง")] == "หลังเลิกเรียน"


async def test_export_single_activity_datetime_field_renders_thai_format(db_pool):
    """export เดี่ยวก็ต้องได้รูปแบบเดียวกัน (โจทย์ข้อ 3 ไม่ได้จำกัดแค่ export รวม)"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(
        db_pool, room_id, owner, title="ค่าย", student_nos=(1,),
        dynamic_fields=[DATETIME_FIELD, INPUT_FIELD],
        participant_metadata={1: {"df_1": "2026-10-01T13:00", "df_2": "2026-10-01T13:00"}},
    )

    excel = await ActivityService.export_activity_excel(
        pool=db_pool, activity_id=a, metadata_keys=[], user_name="ผู้ดูแล", user_id=owner,
        client_source="WEB_APP", actor_identifier="user_id:1", room_id=room_id,
    )
    ws = openpyxl.load_workbook(io.BytesIO(excel.getvalue()))["รายชื่อผู้เข้าร่วม"]
    row = _row_of(ws, 1)
    assert row[_col(ws, "เวลาเข้าพัก")] == "1 ตุลาคม 2569 13:00 น."
    assert row[_col(ws, "หมายเหตุรถ")] == "2026-10-01T13:00"


# ================================================================
# 5) คอลัมน์ฟิลด์เฉพาะกิจกรรม (ติ๊กถูกตอน export)
# ================================================================


async def test_export_combined_activity_fields_toggle_and_prefix(db_pool):
    """ติ๊ก 'รวมข้อมูลที่เก็บรายคน' → คอลัมน์โผล่ (คีย์ซ้ำข้ามกิจกรรมต้องมีชื่อกิจกรรมนำหน้า)"""
    room_id, owner, _ = await _seed_room(db_pool)
    # ทั้งสองกิจกรรมมี df_1 คนละความหมาย → หัวตารางต้องไม่ซ้ำกัน
    a = await _make_activity(
        db_pool, room_id, owner, title="ค่าย", student_nos=(1,),
        dynamic_fields=[{"key": "df_1", "label": "เวลาเข้าพัก", "type": "input"}],
        participant_metadata={1: {"df_1": "20:00"}},
    )
    b = await _make_activity(
        db_pool, room_id, owner, title="กีฬาสี", student_nos=(1,),
        dynamic_fields=[{"key": "df_1", "label": "เวลาลงแข่ง", "type": "input"}],
        participant_metadata={1: {"df_1": "08:30"}},
    )
    keys = [region_key([a, b])]

    # --- ติ๊กถูก: คอลัมน์โผล่ ---
    _, wb_on = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=keys, include_activity_fields=True
    )
    ws_on = wb_on["รายชื่อรวม"]
    header_on = _header(ws_on)
    assert "ค่าย · เวลาเข้าพัก" in header_on
    assert "กีฬาสี · เวลาลงแข่ง" in header_on
    row = _row_of(ws_on, 1)
    assert row[_col(ws_on, "ค่าย · เวลาเข้าพัก")] == "20:00"
    assert row[_col(ws_on, "กีฬาสี · เวลาลงแข่ง")] == "08:30"

    # --- ไม่ติ๊ก: คอลัมน์ต้องหายไป (assertion เชิงลบต้องมีคู่บวก) ---
    _, wb_off = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=keys, include_activity_fields=False
    )
    header_off = _header(wb_off["รายชื่อรวม"])
    assert "ค่าย · เวลาเข้าพัก" not in header_off
    assert "กีฬาสี · เวลาลงแข่ง" not in header_off
    assert header_off[:4] == ["เลขที่", "ชื่อจริง", "นามสกุล", "ชื่อเล่น"]


async def test_export_combined_activity_field_blank_for_non_member(db_pool):
    """คนที่อยู่กิจกรรมเดียว — คอลัมน์ของอีกกิจกรรมต้องว่าง ไม่ใช่ดึง metadata ข้ามกิจกรรม"""
    room_id, owner, _ = await _seed_room(db_pool)
    a = await _make_activity(
        db_pool, room_id, owner, title="ค่าย", student_nos=(1,),
        dynamic_fields=[{"key": "df_1", "label": "เวลาเข้าพัก", "type": "input"}],
        participant_metadata={1: {"df_1": "20:00"}},
    )
    b = await _make_activity(
        db_pool, room_id, owner, title="กีฬาสี", student_nos=(2,),
        dynamic_fields=[{"key": "df_1", "label": "เวลาลงแข่ง", "type": "input"}],
        participant_metadata={2: {"df_1": "08:30"}},
    )

    _, wb = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=[region_key([a]), region_key([b])],
        include_activity_fields=True,
    )
    ws = wb["รายชื่อรวม"]
    # ⚠️ openpyxl อ่านเซลล์ที่เขียนค่า "" กลับมาเป็น None ⇒ เช็ค "ว่าง" ด้วย `in (None, "")`
    # คนที่ 1 อยู่ค่าย → ช่องของกีฬาสีต้องว่าง (ไม่ใช่ค่า 08:30 ของคนอื่น/กิจกรรมอื่น)
    assert _row_of(ws, 1)[_col(ws, "กีฬาสี · เวลาลงแข่ง")] in (None, "")
    assert _row_of(ws, 1)[_col(ws, "ค่าย · เวลาเข้าพัก")] == "20:00"
    # คนที่ 2 อยู่กีฬาสี → กลับกัน
    assert _row_of(ws, 2)[_col(ws, "ค่าย · เวลาเข้าพัก")] in (None, "")
    assert _row_of(ws, 2)[_col(ws, "กีฬาสี · เวลาลงแข่ง")] == "08:30"


async def test_export_combined_filename_truncated_and_audit_logged(db_pool):
    """ชื่อไฟล์ยาว ๆ ถูกตัดที่ 60 ตัว + audit log บันทึก EXPORT สำเร็จ"""
    room_id, owner, _ = await _seed_room(db_pool)
    long_title = "กิจกรรมทดสอบชื่อยาวมาก" * 8  # 88 ตัว → sanitize เหลือ 80 → join แล้วเกิน 60
    a = await _make_activity(db_pool, room_id, owner, title=long_title, student_nos=(1,))
    b = await _make_activity(db_pool, room_id, owner, title="อีกงาน", student_nos=(1,))

    excel, _ = await _export_combined(
        db_pool, owner, room_id, activity_ids=[a, b], region_keys=[region_key([a, b])]
    )
    suffix = "_รายชื่อผู้เข้าร่วม.xlsx"
    assert excel.filename.endswith(suffix)
    # ตัดที่ 60 ตัวอักษรจริง — ไม่ปล่อยให้ HTTP ตัด suffix ทิ้งเอง
    assert len(excel.filename) - len(suffix) == 60

    async with db_pool.acquire() as conn:
        log = await conn.fetchrow(
            "SELECT action, entity_type, entity_id, status, new_values FROM audit_logs "
            "WHERE endpoint_or_command = 'export_activities_combined_excel' ORDER BY id DESC LIMIT 1"
        )
    assert log["action"] == "EXPORT"
    assert log["entity_type"] == "ACTIVITY"
    assert log["status"] == "success"
    assert log["entity_id"] == f"{a},{b}"
    assert _parse_metadata(log["new_values"])["total_people"] == 1
