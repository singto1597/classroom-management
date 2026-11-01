"""
Integration tests — ปีการศึกษา/เทอม สำหรับกรองสถิติ (P5)

สิ่งที่ล็อกไว้:
  1. **ปฏิทินของห้อง** — สร้าง/แก้/ลบปีและเทอมได้เฉพาะผู้มี `MANAGE_CLASSROOM_SETTINGS`
     และสมาชิกทุกคนอ่านได้ (ตัวกรองสถิติต้องเปิดให้ทุกคนใช้)
  2. **หนึ่งปีปัจจุบันต่อห้อง** — DB บังคับด้วย partial unique index; การสลับปี
     ต้องไม่ทำให้เกิด violation (service ปลดตัวเก่าก่อนในทรานแซกชันเดียว)
  3. **เทอมต้องอยู่ในปีและไม่ทับกัน** — ทับกันทำให้ "เทอม 1 + เทอม 2" มากกว่าปี
  4. **ตัวเลขกรองถูกช่วงจริง** — จ่าย/กิจกรรมใน/นอกช่วง, และ **ขอบเขตวันสุดท้าย
     ตามเวลาไทย** (ใบเสร็จ 23:30 ของวันสุดท้ายต้องอยู่ในเทอม)
  5. **ไม่มีปีปัจจุบัน = ไม่กรอง** — `term: null` และยอดเป็นทั้งหมด (ห้ามเดาปีแรก)
  6. ปี/เทอมที่ถูกถามด้วย id ที่ไม่มีจริง = 404 ไม่ใช่ 403 หรือยอดศูนย์
  7. audit log ถูกเขียนทุกครั้งที่เขียน (ตรวจ DB จริง)

Pattern ตาม docs/rules/testing.md: สร้างข้อมูลด้วย SQL ตรง ๆ, ตรวจ DB จริง,
ไม่ hardcode id
"""
import random
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio

BANGKOK = timezone(timedelta(hours=7))


# ── Helpers ─────────────────────────────────────────────────────────────────
def _api(room_id: int, path: str, query: str = "") -> str:
    base = f"/api/classroom/{room_id}{path}?target_type=room"
    return f"{base}&{query}" if query else base


def _create_year(client, headers, **overrides) -> dict:
    payload = {
        "year_be": 2569,
        "name": "ปีการศึกษา 2569",
        "start_date": "2026-05-01",
        "end_date": "2027-03-31",
    }
    payload.update(overrides)
    response = client.post(_api(headers.room_id, "/academic/years"), json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _create_term(client, headers, year_id: int, **overrides) -> dict:
    payload = {"name": "เทอม 1", "start_date": "2026-05-01", "end_date": "2026-10-31"}
    payload.update(overrides)
    response = client.post(
        _api(headers.room_id, f"/academic/years/{year_id}/terms"), json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _stats(client, headers, query: str = "") -> dict:
    response = client.get(_api(headers.room_id, "/me/stats", query), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _same_room_member(pool, *, room_id: int) -> dict:
    """ผู้ใช้ที่สอง **ในห้องเดิม** แต่ไม่ใช่ผู้ดูแล — ใช้พิสูจน์ว่าอ่านได้/เขียนไม่ได้

    `member_headers` fixture สร้างห้องของตัวเอง ⇒ ใช้ทดสอบ "คนนอกห้อง" เท่านั้น
    """
    discord_id = random.randint(1_000_000, 9_999_999)
    while await pool.fetchval("SELECT 1 FROM users WHERE discord_id = $1", discord_id):
        discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username, discord_id)"
            " VALUES ('Same', 'Room', $1, $2) RETURNING id",
            f"u{uuid.uuid4().hex[:12]}",
            discord_id,
        )
        next_no = await conn.fetchval(
            "SELECT COALESCE(MAX(student_no), 0) + 1 FROM students WHERE room_id = $1", room_id
        )
        await conn.execute(
            "INSERT INTO students"
            " (room_id, user_id, student_no, class_role, status, is_admin, permissions)"
            " VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb)",
            room_id,
            user_id,
            next_no,
        )
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


async def _insert_receipt(
    pool, *, room_id: int, student_id: int, amount: float, event_at: datetime
) -> None:
    """ใบเสร็จหนึ่งใบที่ผูกกับนักเรียนคนนี้โดยตรง (ไม่ต้องผ่านบิล)"""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO finance_receipts
                (room_id, receipt_no, doc_type, year_be, seq, student_id, amount,
                 paid_total_after, event_at, issued_at, status, deleted_at)
            VALUES ($1, $2, 'receipt', 2569, 1, $3, $4, $4, $5, $5, 'active', NULL)
            """,
            room_id,
            f"REC-{uuid.uuid4().hex[:10]}",
            student_id,
            amount,
            event_at,
        )


async def _insert_activity(
    pool, *, room_id: int, student_id: int, activity_date: date, hours: float
) -> None:
    async with pool.acquire() as conn:
        activity_id = await conn.fetchval(
            """
            INSERT INTO activities (room_id, title, description, activity_date, created_by)
            VALUES ($1, 'กิจกรรมทดสอบ', 'รายละเอียด', $2, 'tester')
            RETURNING id
            """,
            room_id,
            activity_date,
        )
        await conn.execute(
            """
            INSERT INTO activity_participants
                (activity_id, student_id, status, earned_hours, recorded_by)
            VALUES ($1, $2, 'confirmed', $3, 'tester')
            """,
            activity_id,
            student_id,
            hours,
        )


# ── 1. ปฏิทินของห้อง — สิทธิ์ ──────────────────────────────────────────────
async def test_create_year_and_list(client, admin_headers):
    created = _create_year(client, admin_headers)
    assert created["year_be"] == 2569
    assert created["is_current"] is False

    listed = client.get(_api(admin_headers.room_id, "/academic/periods"), headers=admin_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert [y["id"] for y in body["years"]] == [created["id"]]
    assert body["years"][0]["terms"] == []
    assert body["current_year_id"] is None


async def test_same_room_member_can_read_but_not_write(client, admin_headers, db_pool):
    year = _create_year(client, admin_headers)
    member = await _same_room_member(db_pool, room_id=admin_headers.room_id)

    # อ่านได้ — ตัวกรองสถิติเปิดให้สมาชิกทุกคน
    listed = client.get(_api(admin_headers.room_id, "/academic/periods"), headers=member)
    assert listed.status_code == 200, listed.text
    assert [y["id"] for y in listed.json()["years"]] == [year["id"]]

    # เขียนไม่ได้ — ต้อง MANAGE_CLASSROOM_SETTINGS (ไม่ใช่ is_admin bypass)
    denied = client.post(
        _api(admin_headers.room_id, "/academic/years"),
        json={"year_be": 2568, "start_date": "2025-05-01", "end_date": "2026-03-31"},
        headers=member,
    )
    assert denied.status_code == 403

    denied_current = client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": year["id"]},
        headers=member,
    )
    assert denied_current.status_code == 403


async def test_outside_user_cannot_read_periods(client, admin_headers, member_headers):
    """คนนอกห้องต้องไม่ได้ลิสต์ปฏิทินของห้องอื่น (member_headers = คนละห้อง)"""
    response = client.get(
        _api(admin_headers.room_id, "/academic/periods"), headers=member_headers
    )
    assert response.status_code == 403


async def test_duplicate_year_be_rejected(client, admin_headers):
    _create_year(client, admin_headers)
    response = client.post(
        _api(admin_headers.room_id, "/academic/years"),
        json={"year_be": 2569, "start_date": "2027-05-01", "end_date": "2028-03-31"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "2569" in response.json()["detail"]


async def test_invalid_date_range_rejected(client, admin_headers):
    response = client.post(
        _api(admin_headers.room_id, "/academic/years"),
        json={"year_be": 2569, "start_date": "2027-03-31", "end_date": "2026-05-01"},
        headers=admin_headers,
    )
    assert response.status_code == 400


async def test_gregorian_year_rejected_with_hint(client, admin_headers):
    response = client.post(
        _api(admin_headers.room_id, "/academic/years"),
        json={"year_be": 2026, "start_date": "2026-05-01", "end_date": "2027-03-31"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "543" in response.json()["detail"]


# ── 2. เทอม ─────────────────────────────────────────────────────────────────
async def test_term_must_fit_inside_year(client, admin_headers):
    year = _create_year(client, admin_headers)
    response = client.post(
        _api(admin_headers.room_id, f"/academic/years/{year['id']}/terms"),
        json={"name": "เทอม 1", "start_date": "2026-04-01", "end_date": "2026-10-31"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "อยู่ในช่วงของปี" in response.json()["detail"]


async def test_overlapping_terms_rejected(client, admin_headers):
    year = _create_year(client, admin_headers)
    _create_term(client, admin_headers, year["id"])

    response = client.post(
        _api(admin_headers.room_id, f"/academic/years/{year['id']}/terms"),
        json={"name": "เทอม 2", "start_date": "2026-10-31", "end_date": "2027-03-31"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "ทับ" in response.json()["detail"]

    # เทอมที่เริ่มวันถัดไปผ่าน (วันสุดท้ายเป็นแบบ inclusive)
    ok = client.post(
        _api(admin_headers.room_id, f"/academic/years/{year['id']}/terms"),
        json={"name": "เทอม 2", "start_date": "2026-11-01", "end_date": "2027-03-31"},
        headers=admin_headers,
    )
    assert ok.status_code == 200, ok.text


async def test_duplicate_term_name_rejected(client, admin_headers):
    year = _create_year(client, admin_headers)
    _create_term(client, admin_headers, year["id"])
    response = client.post(
        _api(admin_headers.room_id, f"/academic/years/{year['id']}/terms"),
        json={"name": "เทอม 1", "start_date": "2026-11-01", "end_date": "2027-03-31"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "เทอม 1" in response.json()["detail"]


async def test_update_term_rejects_overlap_but_keeps_itself(client, admin_headers):
    year = _create_year(client, admin_headers)
    term1 = _create_term(client, admin_headers, year["id"])
    _create_term(
        client,
        admin_headers,
        year["id"],
        name="เทอม 2",
        start_date="2026-11-01",
        end_date="2027-03-31",
    )

    # เลื่อนวันจบของเทอม 1 ไปทับเทอม 2 ⇒ 400
    bad = client.patch(
        _api(admin_headers.room_id, f"/academic/terms/{term1['id']}"),
        json={"end_date": "2026-12-31"},
        headers=admin_headers,
    )
    assert bad.status_code == 400

    # แก้ช่วงของตัวเองโดยไม่ทับใคร ⇒ ผ่าน (ไม่ชนกับตัวเอง)
    ok = client.patch(
        _api(admin_headers.room_id, f"/academic/terms/{term1['id']}"),
        json={"end_date": "2026-10-15"},
        headers=admin_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["end_date"] == "2026-10-15"


async def test_update_year_rejects_range_that_orphans_term(client, admin_headers):
    year = _create_year(client, admin_headers)
    _create_term(client, admin_headers, year["id"])
    response = client.patch(
        _api(admin_headers.room_id, f"/academic/years/{year['id']}"),
        json={"end_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "เทอม" in response.json()["detail"]


# ── 3. ปีปัจจุบัน ───────────────────────────────────────────────────────────
async def test_set_current_keeps_exactly_one_per_room(client, admin_headers, db_pool):
    year_a = _create_year(
        client, admin_headers, year_be=2568, start_date="2025-05-01", end_date="2026-03-31"
    )
    year_b = _create_year(client, admin_headers)

    for target in (year_a, year_b, year_a):
        response = client.put(
            _api(admin_headers.room_id, "/academic/current"),
            json={"year_id": target["id"]},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        async with db_pool.acquire() as conn:
            current = await conn.fetch(
                "SELECT id FROM academic_years WHERE room_id = $1 AND is_current"
                " AND deleted_at IS NULL",
                admin_headers.room_id,
            )
        assert [row["id"] for row in current] == [target["id"]]


async def test_set_current_year_only_clears_that_years_term(client, admin_headers, db_pool):
    """`term_id=None` = "ทั้งปี" ⇒ ต้องปลดเทอมปัจจุบัน และคำตอบต้องตรงกับ DB

    🔴 เดิม service ทิ้งเทอมปัจจุบันของปี *เดียวกัน* ไว้ ⇒ `/periods` บอกว่ามี
    เทอมปัจจุบัน แต่คำตอบของ `set_current` บอก `current_term_id: null`
    (สองแหล่งขัดกัน แล้วสถิติยังกรองด้วยเทอมเดิมทั้งที่ผู้ใช้กด "ทั้งปี")
    """
    year = _create_year(client, admin_headers)
    term = _create_term(client, admin_headers, year["id"])

    set_term = client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": year["id"], "term_id": term["id"]},
        headers=admin_headers,
    )
    assert set_term.status_code == 200, set_term.text

    year_only = client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": year["id"]},
        headers=admin_headers,
    )
    assert year_only.status_code == 200, year_only.text
    assert year_only.json() == {"current_year_id": year["id"], "current_term_id": None}

    async with db_pool.acquire() as conn:
        still_current = await conn.fetch(
            "SELECT id FROM academic_terms WHERE academic_year_id = $1 AND is_current"
            " AND deleted_at IS NULL",
            year["id"],
        )
    assert still_current == [], "ยังมีเทอมปัจจุบันค้างอยู่หลังตั้งปีแบบทั้งปี"

    listed = client.get(_api(admin_headers.room_id, "/academic/periods"), headers=admin_headers)
    assert listed.json()["current_term_id"] is None


async def test_set_current_term_must_belong_to_year(client, admin_headers):
    year_a = _create_year(
        client, admin_headers, year_be=2568, start_date="2025-05-01", end_date="2026-03-31"
    )
    year_b = _create_year(client, admin_headers)
    term_a = _create_term(
        client,
        admin_headers,
        year_a["id"],
        start_date="2025-05-01",
        end_date="2026-03-31",
    )

    response = client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": year_b["id"], "term_id": term_a["id"]},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "ไม่ได้อยู่ในปี" in response.json()["detail"]


async def test_set_current_null_clears(client, admin_headers):
    year = _create_year(client, admin_headers)
    client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": year["id"]},
        headers=admin_headers,
    )
    cleared = client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": None},
        headers=admin_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"current_year_id": None, "current_term_id": None}

    listed = client.get(_api(admin_headers.room_id, "/academic/periods"), headers=admin_headers)
    assert listed.json()["current_year_id"] is None


async def test_unknown_period_is_404(client, admin_headers):
    response = client.put(
        _api(admin_headers.room_id, "/academic/current"),
        json={"year_id": 987654321},
        headers=admin_headers,
    )
    assert response.status_code == 404


# ── 4. ลบ (soft) ────────────────────────────────────────────────────────────
async def test_delete_year_soft_deletes_terms_and_clears_current(client, admin_headers, db_pool):
    year = _create_year(client, admin_headers, is_current=True)
    term = _create_term(client, admin_headers, year["id"], is_current=True)

    response = client.delete(
        _api(admin_headers.room_id, f"/academic/years/{year['id']}"), headers=admin_headers
    )
    assert response.status_code == 200

    async with db_pool.acquire() as conn:
        year_row = await conn.fetchrow(
            "SELECT deleted_at, is_current FROM academic_years WHERE id = $1", year["id"]
        )
        term_row = await conn.fetchrow(
            "SELECT deleted_at, is_current FROM academic_terms WHERE id = $1", term["id"]
        )
    assert year_row["deleted_at"] is not None
    assert year_row["is_current"] is False
    assert term_row["deleted_at"] is not None
    assert term_row["is_current"] is False

    listed = client.get(_api(admin_headers.room_id, "/academic/periods"), headers=admin_headers)
    assert listed.json()["years"] == []
    assert listed.json()["current_year_id"] is None


# ── 5. กรองสถิติ ────────────────────────────────────────────────────────────
async def test_stats_filter_by_year_and_term(client, admin_headers, db_pool):
    room_id = admin_headers.room_id
    student_id = admin_headers.student_id

    year = _create_year(client, admin_headers)
    term1 = _create_term(client, admin_headers, year["id"])
    term2 = _create_term(
        client,
        admin_headers,
        year["id"],
        name="เทอม 2",
        start_date="2026-11-01",
        end_date="2027-03-31",
    )

    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=student_id,
        amount=100.0,
        event_at=datetime(2026, 6, 1, 10, 0, tzinfo=BANGKOK),
    )
    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=student_id,
        amount=250.0,
        event_at=datetime(2026, 12, 1, 10, 0, tzinfo=BANGKOK),
    )
    await _insert_activity(
        db_pool, room_id=room_id, student_id=student_id, activity_date=date(2026, 7, 1), hours=3.0
    )
    await _insert_activity(
        db_pool,
        room_id=room_id,
        student_id=student_id,
        activity_date=date(2027, 1, 15),
        hours=5.0,
    )

    whole_year = _stats(client, admin_headers, f"year_id={year['id']}")
    assert whole_year["paid_total"] == 350.0
    assert whole_year["activities_joined"] == 2
    assert whole_year["activity_hours"] == 8.0
    assert whole_year["term"]["year_be"] == 2569
    assert whole_year["term"]["term_id"] is None
    assert whole_year["term"]["source"] == "explicit"

    first = _stats(client, admin_headers, f"year_id={year['id']}&term_id={term1['id']}")
    assert first["paid_total"] == 100.0
    assert first["activities_joined"] == 1
    assert first["activity_hours"] == 3.0
    assert first["term"]["term_name"] == "เทอม 1"

    second = _stats(client, admin_headers, f"year_id={year['id']}&term_id={term2['id']}")
    assert second["paid_total"] == 250.0
    assert second["activities_joined"] == 1
    assert second["activity_hours"] == 5.0


async def test_stats_boundary_uses_thai_time_inclusive_end(client, admin_headers, db_pool):
    """วันสุดท้ายของเทอมต้องรวมถึง 23:30 เวลาไทย และไม่รวม 00:30 ของวันถัดไป"""
    room_id = admin_headers.room_id
    year = _create_year(client, admin_headers, end_date="2026-10-31")
    term = _create_term(client, admin_headers, year["id"], end_date="2026-10-31")

    # 23:30 ไทยของวันสุดท้าย = 16:30 UTC ของวันเดียวกัน
    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=admin_headers.student_id,
        amount=100.0,
        event_at=datetime(2026, 10, 31, 16, 30, tzinfo=timezone.utc),
    )
    # 00:30 ไทยของวันถัดไป = 17:30 UTC ของวันสุดท้าย
    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=admin_headers.student_id,
        amount=999.0,
        event_at=datetime(2026, 10, 31, 17, 30, tzinfo=timezone.utc),
    )

    in_term = _stats(client, admin_headers, f"term_id={term['id']}")
    assert in_term["paid_total"] == 100.0


async def test_no_current_year_means_no_filter(client, admin_headers, db_pool):
    room_id = admin_headers.room_id
    # มีปี แต่ไม่ได้ตั้งเป็นปัจจุบัน ⇒ ห้ามเดาว่าเป็นปีปัจจุบัน
    _create_year(client, admin_headers)
    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=admin_headers.student_id,
        amount=42.0,
        event_at=datetime(2020, 1, 1, 10, 0, tzinfo=BANGKOK),
    )

    body = _stats(client, admin_headers)
    assert body["term"] is None
    assert body["paid_total"] == 42.0  # เหตุการณ์นอกปีที่สร้างไว้ยังถูกนับ


async def test_stats_defaults_to_current_term(client, admin_headers, db_pool):
    room_id = admin_headers.room_id
    year = _create_year(client, admin_headers)
    term1 = _create_term(client, admin_headers, year["id"])
    _create_term(
        client,
        admin_headers,
        year["id"],
        name="เทอม 2",
        start_date="2026-11-01",
        end_date="2027-03-31",
    )

    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=admin_headers.student_id,
        amount=100.0,
        event_at=datetime(2026, 6, 1, 10, 0, tzinfo=BANGKOK),
    )
    await _insert_receipt(
        db_pool,
        room_id=room_id,
        student_id=admin_headers.student_id,
        amount=250.0,
        event_at=datetime(2026, 12, 1, 10, 0, tzinfo=BANGKOK),
    )

    client.put(
        _api(room_id, "/academic/current"),
        json={"year_id": year["id"], "term_id": term1["id"]},
        headers=admin_headers,
    )

    body = _stats(client, admin_headers)
    assert body["term"]["source"] == "current"
    assert body["term"]["term_id"] == term1["id"]
    assert body["paid_total"] == 100.0


async def test_stats_unknown_term_is_404(client, admin_headers):
    response = client.get(
        _api(admin_headers.room_id, "/me/stats", "term_id=987654321"), headers=admin_headers
    )
    assert response.status_code == 404


async def test_stats_term_from_other_year_is_400(client, admin_headers):
    year_a = _create_year(
        client, admin_headers, year_be=2568, start_date="2025-05-01", end_date="2026-03-31"
    )
    year_b = _create_year(client, admin_headers)
    term_a = _create_term(
        client, admin_headers, year_a["id"], start_date="2025-05-01", end_date="2026-03-31"
    )

    response = client.get(
        _api(
            admin_headers.room_id,
            "/me/stats",
            f"year_id={year_b['id']}&term_id={term_a['id']}",
        ),
        headers=admin_headers,
    )
    assert response.status_code == 400


async def test_stats_for_other_room_is_403(client, admin_headers, member_headers):
    """คนนอกห้องขอสถิติของห้องนี้ ⇒ 403 ไม่ใช่ยอดของห้องนั้น"""
    year = _create_year(client, admin_headers)
    response = client.get(
        _api(admin_headers.room_id, "/me/stats", f"year_id={year['id']}"),
        headers=member_headers,
    )
    assert response.status_code == 403


# ── 6. audit ────────────────────────────────────────────────────────────────
async def test_every_write_is_audited(client, admin_headers, db_pool):
    room_id = admin_headers.room_id
    year = _create_year(client, admin_headers)
    term = _create_term(client, admin_headers, year["id"])
    client.put(
        _api(room_id, "/academic/current"),
        json={"year_id": year["id"], "term_id": term["id"]},
        headers=admin_headers,
    )
    client.delete(_api(room_id, f"/academic/terms/{term['id']}"), headers=admin_headers)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, entity_type FROM audit_logs"
            " WHERE room_id = $1 AND entity_type IN ('ACADEMIC_YEAR', 'ACADEMIC_TERM')"
            " ORDER BY id",
            room_id,
        )
    pairs = {(row["action"], row["entity_type"]) for row in rows}
    assert ("CREATE", "ACADEMIC_YEAR") in pairs
    assert ("CREATE", "ACADEMIC_TERM") in pairs
    assert ("UPDATE", "ACADEMIC_YEAR") in pairs  # set_current
    assert ("DELETE", "ACADEMIC_TERM") in pairs
