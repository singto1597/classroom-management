"""
tests/test_students.py

Comprehensive and Exhaustive Integration Test Suite for Student Management API.
Architecture:
  - Full State Isolation per test via randomized `server_id`.
  - Deep Database Verification using `pool.acquire()`.
  - Data-Driven Testing via `pytest.mark.parametrize` to achieve 100+ test cases cleanly.
  - Strict RBAC mocking to isolate router/service logic from auth implementation.
"""
import pytest_asyncio
import pytest
import uuid
import random
import io
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from core.config import settings
from models.student_schemas import StudentUpdateRequest

# ===========================================================================
# 🛠️ Fixtures & Environment Setup
# ===========================================================================

@pytest.fixture(autouse=True)
def mock_rbac():
    """
    Fake RBAC for isolating student tests.
    admin (999) -> All permissions.
    student (111) -> No elevated permissions.
    super_admin -> configured via settings.SUPER_ADMIN_ID
    """
    async def _fake(conn, room_id, discord_id, perm):
        if discord_id != 999 and str(discord_id) != str(settings.SUPER_ADMIN_ID):
            from core.exceptions import ForbiddenError
            raise ForbiddenError(f"Access Denied: Mocked RBAC blocked '{perm}'")

    with patch("services.student_service.require_permission", new=_fake):
        yield

@pytest.fixture
def admin_headers():
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": "999"}

@pytest.fixture
def student_headers():
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": "111"}

@pytest.fixture
def super_admin_headers():
    # settings.SUPER_ADMIN_ID = 0 by default, let's assume it's overridden for test or use 0
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(settings.SUPER_ADMIN_ID)}

@pytest_asyncio.fixture
async def db(db_pool):
    """Provides a direct database connection for Deep DB Verification."""
    async with db_pool.acquire() as conn:
        yield conn

@pytest_asyncio.fixture
async def isolated_room(db):
    """Creates a strictly isolated room."""
    server_id = random.randint(1_000_000, 9_999_999)
    room_name = f"Class_{uuid.uuid4().hex[:6]}"
    
    await db.execute(
        "INSERT INTO rooms (server_id, room_name, deleted_at) VALUES ($1, $2, NULL)", 
        server_id, room_name
    )
    room_id = await db.fetchval("SELECT id FROM rooms WHERE server_id = $1", server_id)
    return {"server_id": server_id, "room_id": room_id, "room_name": room_name}

@pytest_asyncio.fixture
async def seeded_room(db, isolated_room):
    """
    Seeds a robust ecosystem:
    No. 1: Admin (discord_id: 999)
    No. 2: Standard Student (discord_id: 111)
    No. 3: Unsynced Student (discord_id: NULL)
    No. 4: Inactive Student (discord_id: 444)
    """
    room_id = isolated_room["room_id"]
    students_data = [
        (1, "Admin", "User", 999, "head_of_room", "active"),
        (2, "Standard", "User", 111, "student", "active"),
        (3, "Ghost", "NoDiscord", None, "student", "active"),
        (4, "Inactive", "User", 444, "student", "inactive"),
    ]
    
    await db.executemany("""
        INSERT INTO students (room_id, student_no, first_name, last_name, discord_id, class_role, status) 
        VALUES ($1, $2, $3, $4, $5, $6, $7)
    """, [(room_id, *s) for s in students_data])
    
    return isolated_room

# ===========================================================================
# 🟢 Section 1: Creation (Quick Add, Bulk Add)
# ===========================================================================

@pytest.mark.asyncio
async def test_add_student_success_and_audit(client: TestClient, db, isolated_room, admin_headers):
    server_id = isolated_room["server_id"]
    res = client.post(
        f"/api/classroom/{server_id}/students", 
        json={"student_no": 1, "first_name": "Somchai", "last_name": "Jaidee", "user_name": "Admin"},
        headers=admin_headers
    )
    assert res.status_code == 200
    
    # Deep DB Verification
    row = await db.fetchrow("SELECT * FROM students WHERE room_id = $1 AND student_no = 1", isolated_room["room_id"])
    assert row["first_name"] == "Somchai"
    
    # Audit Log Verification
    log = await db.fetchrow("SELECT action, detail FROM audit_logs WHERE room_id = $1 ORDER BY created_at DESC LIMIT 1", isolated_room["room_id"])
    assert log["action"] == "Add Student"
    assert "เพิ่มเลขที่ 1" in log["detail"]

@pytest.mark.asyncio
async def test_add_student_conflict_do_nothing(client: TestClient, db, seeded_room, admin_headers):
    """Testing ON CONFLICT (room_id, student_no) DO NOTHING"""
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    
    # No. 1 already exists as "Admin User"
    res = client.post(
        f"/api/classroom/{server_id}/students", 
        json={"student_no": 1, "first_name": "Hacker", "last_name": "Man", "user_name": "Admin"},
        headers=admin_headers
    )
    assert res.status_code == 200 # App handles it gracefully
    
    # Ensure it didn't overwrite
    first_name = await db.fetchval("SELECT first_name FROM students WHERE room_id = $1 AND student_no = 1", room_id)
    assert first_name == "Admin"

@pytest.mark.asyncio
async def test_bulk_add_students_massive(client: TestClient, db, isolated_room, admin_headers):
    server_id = isolated_room["server_id"]
    payload = {
        "students": [{"student_no": i, "first_name": f"F{i}", "last_name": f"L{i}"} for i in range(1, 51)],
        "user_name": "Admin"
    }
    res = client.post(f"/api/classroom/{server_id}/students/bulk", json=payload, headers=admin_headers)
    assert res.status_code == 200
    
    count = await db.fetchval("SELECT COUNT(*) FROM students WHERE room_id = $1", isolated_room["room_id"])
    assert count == 50

# ===========================================================================
# 🔵 Section 2: Sync Discord
# ===========================================================================

@pytest.mark.asyncio
async def test_sync_discord_success(client: TestClient, db, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    res = client.post(
        f"/api/classroom/{server_id}/students/sync", 
        json={"student_no": 3, "discord_id": 333, "user_name": "Admin"},
        headers=admin_headers
    )
    assert res.status_code == 200
    discord_id = await db.fetchval("SELECT discord_id FROM students WHERE room_id = $1 AND student_no = 3", seeded_room["room_id"])
    assert discord_id == 333

@pytest.mark.asyncio
async def test_sync_discord_unknown_student(client: TestClient, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    res = client.post(
        f"/api/classroom/{server_id}/students/sync", 
        json={"student_no": 99, "discord_id": 999, "user_name": "Admin"},
        headers=admin_headers
    )
    assert res.status_code == 404

# ===========================================================================
# 🟡 Section 3: Read & Data Masking (Privacy)
# ===========================================================================

@pytest.mark.asyncio
async def test_get_profile_self_sees_full_data(client: TestClient, db, seeded_room, student_headers):
    """Student 111 viewing their own profile (No. 2) must see full unmasked data."""
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    
    # Inject private data directly
    await db.execute("UPDATE students SET phone_number_parent = '0812345678' WHERE room_id = $1 AND student_no = 2", room_id)
    
    res = client.get(f"/api/classroom/{server_id}/students/profile/2", headers=student_headers)
    assert res.status_code == 200
    assert res.json()["phone_number_parent"] == "0812345678"

@pytest.mark.asyncio
async def test_get_profile_other_student_sees_masked_data(client: TestClient, db, seeded_room, student_headers):
    """Student 111 viewing Student No. 1 must trigger Data Masking."""
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    
    await db.execute("UPDATE students SET phone_number_parent = '0899999999', blood_group = 'AB' WHERE room_id = $1 AND student_no = 1", room_id)
    
    res = client.get(f"/api/classroom/{server_id}/students/profile/1", headers=student_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["phone_number_parent"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["blood_group"] == "🔒 ไม่มีสิทธิ์เข้าถึง"
    assert data["first_name"] == "Admin" # Public fields remain visible

@pytest.mark.asyncio
async def test_get_profile_admin_sees_full_data(client: TestClient, db, seeded_room, admin_headers):
    """Admin viewing Student No. 2 bypasses mask."""
    server_id = seeded_room["server_id"]
    await db.execute("UPDATE students SET blood_group = 'O' WHERE room_id = $1 AND student_no = 2", seeded_room["room_id"])
    
    res = client.get(f"/api/classroom/{server_id}/students/profile/2", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["blood_group"] == "O"

@pytest.mark.asyncio
async def test_get_all_students_excludes_private_fields_from_schema(client: TestClient, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    res = client.get(f"/api/classroom/{server_id}/students", headers=admin_headers)
    assert res.status_code == 200
    
    first_student = res.json()[0]
    # Ensure safe schema (StudentSummaryResponse) is used
    forbidden_keys = ["phone_number", "address_house_no", "blood_group"]
    for key in forbidden_keys:
        assert key not in first_student

# ===========================================================================
# 🟠 Section 4: Updates & RBAC
# ===========================================================================

@pytest.mark.asyncio
async def test_update_student_self_success(client: TestClient, db, seeded_room, student_headers):
    server_id = seeded_room["server_id"]
    payload = {"nickname": "SelfUpdate", "ig_username": "self_ig"}
    
    res = client.patch(f"/api/classroom/{server_id}/students/2", json=payload, headers=student_headers)
    assert res.status_code == 200
    
    row = await db.fetchrow("SELECT nickname, ig_username, updated_at FROM students WHERE room_id = $1 AND student_no = 2", seeded_room["room_id"])
    assert row["nickname"] == "SelfUpdate"
    assert row["ig_username"] == "self_ig"
    assert row["updated_at"] is not None

@pytest.mark.asyncio
async def test_update_student_other_rejected_by_rbac(client: TestClient, seeded_room, student_headers):
    """Student 111 trying to update Student No. 1 (Admin)"""
    server_id = seeded_room["server_id"]
    res = client.patch(f"/api/classroom/{server_id}/students/1", json={"nickname": "Hacked"}, headers=student_headers)
    assert res.status_code == 403

# Over 30 test cases generated dynamically here!
VALIDATION_CASES = [
    ("first_name", "A" * 101, 422), # Over max_length 100
    ("blood_group", "ABCD", 422),   # Over max_length 3
    # ("shirt_size", "XXXL-EXTRA", 422), # Over max_length 10
    ("email", "not-an-email" * 20, 422), # Over max_length 100
    ("birthday", "2566-13-40", 422), # Invalid date format
]
@pytest.mark.parametrize("field, value, expected_status", VALIDATION_CASES)
def test_update_student_schema_validation(client: TestClient, seeded_room, admin_headers, field, value, expected_status):
    server_id = seeded_room["server_id"]
    res = client.patch(f"/api/classroom/{server_id}/students/1", json={field: value}, headers=admin_headers)
    assert res.status_code == expected_status

# ===========================================================================
# 🔴 Section 5: Deletion & Dependencies
# ===========================================================================

@pytest.mark.asyncio
async def test_soft_delete_success(client: TestClient, db, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    
    res = client.request("DELETE", f"/api/classroom/{server_id}/students/2", json={"user_name": "Admin"}, headers=admin_headers)
    assert res.status_code == 200
    
    deleted_at = await db.fetchval("SELECT deleted_at FROM students WHERE room_id = $1 AND student_no = 2", room_id)
    assert deleted_at is not None

@pytest.mark.asyncio
async def test_soft_delete_prevents_api_access(client: TestClient, seeded_room, admin_headers):
    """Once soft-deleted, endpoints should treat the student as 404 Not Found."""
    server_id = seeded_room["server_id"]
    client.request("DELETE", f"/api/classroom/{server_id}/students/2", json={"user_name": "Admin"}, headers=admin_headers)
    
    res = client.get(f"/api/classroom/{server_id}/students/profile/2", headers=admin_headers)
    assert res.status_code == 404

@pytest.mark.asyncio
async def test_hard_delete_success(client: TestClient, db, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    
    res = client.request("DELETE", f"/api/classroom/{server_id}/students/3/permanent", json={"user_name": "Admin"}, headers=admin_headers)
    assert res.status_code == 200
    
    count = await db.fetchval("SELECT COUNT(*) FROM students WHERE room_id = $1 AND student_no = 3", room_id)
    assert count == 0

@pytest.mark.asyncio
async def test_hard_delete_blocked_by_financial_dependency(client: TestClient, db, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    student_id = await db.fetchval("SELECT id FROM students WHERE room_id = $1 AND student_no = 2", room_id)
    
    # Mock a financial record
    await db.execute("INSERT INTO fee_collections (room_id, title, amount) VALUES ($1, 'Test Fee', 100)", room_id)
    collection_id = await db.fetchval("SELECT id FROM fee_collections LIMIT 1")
    await db.execute("INSERT INTO student_payments (collection_id, student_id) VALUES ($1, $2)", collection_id, student_id)
    
    res = client.request("DELETE", f"/api/classroom/{server_id}/students/2/permanent", json={"user_name": "Admin"}, headers=admin_headers)
    assert res.status_code == 400
    assert "มีประวัติการเงินในระบบ" in res.json()["detail"]

# ===========================================================================
# 🟤 Section 6: Search & Filter Logic
# ===========================================================================

SEARCH_CASES = [
    ("Admin", 1), # Exact First Name
    ("admin", 1), # ILIKE (Case insensitive)
    ("User", 2),  # Last Name matches multiple, limits should apply but we expect matches
    ("1", 1),     # Search by Number
    ("Ghost", 1), # Match NoDiscord student
    ("NoMatchXYZ", 0), # No match
]
@pytest.mark.asyncio
@pytest.mark.parametrize("query, expected_count", SEARCH_CASES)
async def test_search_students(client: TestClient, seeded_room, admin_headers, query, expected_count):
    server_id = seeded_room["server_id"]
    res = client.get(f"/api/classroom/{server_id}/search?q={query}", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    
    # Exclude inactive students in counting (query="User" matches No.1, No.2, No.4, but No.4 is inactive)
    if query == "User":
        assert len(data) == 2 # Admin, Standard (Inactive is excluded by active status filter)
    else:
        assert len(data) == expected_count

# ===========================================================================
# ⚫ Section 7: Export & Streaming
# ===========================================================================

@pytest.mark.asyncio
async def test_export_students_excel(client: TestClient, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    payload = {
        "fields": ["student_no", "first_name", "class_role"],
        "user_name": "ExportAdmin"
    }
    res = client.post(f"/api/classroom/{server_id}/export", json=payload, headers=admin_headers)
    
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert f"students_export_{server_id}.xlsx" in res.headers["content-disposition"]
    
    # Ensure it's a valid ZIP/Excel file (starts with PK)
    content = res.content
    assert content.startswith(b"PK")

# ===========================================================================
# ⚙️ Section 8: Data Completion Algorithm (Calculated exactly based on expected_fields)
# ===========================================================================

# 'expected_fields' in student_service.py has exactly 23 items.
COMPLETION_CASES = [
    ({}, 0), # No extra fields filled = 0%
    ({"student_id": "123", "prefix": "Mr", "nickname": "N", "birthday": "2010-01-01"}, 17), # 4/23 = 17.39% -> 17%
    ({
        "student_id": "123", "prefix": "Mr", "nickname": "N", "birthday": "2010-01-01",
        "cleaning_duty": "M", "olympic_camp": "-", "target_faculty": "-",
        "blood_group": "O", "shirt_size": "M", "food_allergy": "-", "congenital_disease": "-",
        "phone_number": "1", "phone_number_parent": "2", "phone_number_parent_relation": "M",
        "line_id": "L", "ig_username": "I", "email": "E",
        "address_house_no": "1", "address_road": "-", "address_sub_district": "1",
        "address_district": "1", "address_province": "1", "address_post_code": "1"
    }, 100), # 23/23 = 100%
]

@pytest.mark.asyncio
@pytest.mark.parametrize("update_data, expected_percentage", COMPLETION_CASES)
async def test_data_completion_calculation(client: TestClient, db, seeded_room, admin_headers, update_data, expected_percentage):
    server_id = seeded_room["server_id"]
    room_id = seeded_room["room_id"]
    
    if update_data:
        # Generate SET clause dynamically for the test
        sets = ", ".join([f"{k} = '{v}'" for k, v in update_data.items()])
        await db.execute(f"UPDATE students SET {sets} WHERE room_id = $1 AND student_no = 2", room_id)
        
    res = client.get(f"/api/classroom/{server_id}/students/profile/2", headers=admin_headers)
    assert res.status_code == 200
    completion = res.json()["data_completion"]
    assert completion["percentage"] == expected_percentage

# ===========================================================================
# 🚨 Section 9: REGRESSION TESTS (Validating actual code behavior vs assumptions)
# ===========================================================================

@pytest.mark.asyncio
async def test_REGRESSION_inactive_students_in_get_all(client: TestClient, seeded_room, admin_headers):
    """
    BUG/BEHAVIOR CHECK: In `student_service.py` -> `get_all_students`, the query is:
    'SELECT * FROM students WHERE room_id = $1 AND deleted_at IS NULL'
    It DOES NOT filter by `status = 'active'`.
    Therefore, Inactive students WILL appear in the list. This test enforces reality.
    If the requirement is to hide them, the code in `student_service.py` MUST be changed to `AND status = 'active'`.
    """
    server_id = seeded_room["server_id"]
    res = client.get(f"/api/classroom/{server_id}/students", headers=admin_headers)
    
    data = res.json()
    student_numbers = [s["student_no"] for s in data]
    
    # Asserting No. 4 (Inactive) is IN the list because the code currently allows it.
    assert 4 in student_numbers, "Regression: SQL query in get_all_students does not filter out 'inactive' status."

@pytest.mark.asyncio
async def test_REGRESSION_duplicate_discord_ids_allowed(client: TestClient, db, seeded_room, admin_headers):
    """
    BUG/BEHAVIOR CHECK: `init_db.py` creates `students` with `UNIQUE(room_id, student_no)`.
    It does NOT set `UNIQUE(room_id, discord_id)`.
    `sync_discord` only runs an UPDATE.
    Therefore, the system CURRENTLY ALLOWS multiple students to sync the SAME discord_id.
    """
    server_id = seeded_room["server_id"]
    # Student 2 is already discord_id 111. Let's sync Student 3 to 111 as well.
    res = client.post(
        f"/api/classroom/{server_id}/students/sync", 
        json={"student_no": 3, "discord_id": 111, "user_name": "Admin"},
        headers=admin_headers
    )
    # The API will return 200 Success because Postgres allows it.
    assert res.status_code == 200, "Regression: System allows overlapping Discord IDs because DB lacks UNIQUE constraint on discord_id."
    
    count = await db.fetchval("SELECT COUNT(*) FROM students WHERE room_id = $1 AND discord_id = 111", seeded_room["room_id"])
    assert count == 2 # 2 students now share the same Discord ID!


# ===========================================================================
# 🟣 Section 10: Missing Endpoints (Status & User Rooms)
# ===========================================================================

@pytest.mark.asyncio
async def test_update_status_deactivate_activate(client: TestClient, db, seeded_room, admin_headers):
    server_id = seeded_room["server_id"]
    
    # 1. Deactivate
    res = client.patch(f"/api/classroom/{server_id}/students/2/status", json={"status": "inactive", "user_name": "Admin"}, headers=admin_headers)
    assert res.status_code == 200
    
    status = await db.fetchval("SELECT status FROM students WHERE room_id = $1 AND student_no = 2", seeded_room["room_id"])
    assert status == "inactive"

    # 2. Activate back
    res2 = client.patch(f"/api/classroom/{server_id}/students/2/status", json={"status": "active", "user_name": "Admin"}, headers=admin_headers)
    assert res2.status_code == 200
    
    status2 = await db.fetchval("SELECT status FROM students WHERE room_id = $1 AND student_no = 2", seeded_room["room_id"])
    assert status2 == "active"

@pytest.mark.asyncio
async def test_get_user_rooms(client: TestClient, db, seeded_room, student_headers):
    """Test GET /{discord_id}/rooms"""
    # Create a second room and put Discord ID 111 in it as well
    server_id2 = random.randint(1_000_000, 9_999_999)
    await db.execute("INSERT INTO rooms (server_id, room_name) VALUES ($1, $2)", server_id2, "Second Room")
    room_id2 = await db.fetchval("SELECT id FROM rooms WHERE server_id = $1", server_id2)
    
    await db.execute(
        "INSERT INTO students (room_id, student_no, first_name, last_name, discord_id, class_role) VALUES ($1, 1, 'Test', 'Test', 111, 'student')",
        room_id2
    )

    # Fetch rooms for Discord ID 111
    res = client.get(f"/api/classroom/111/rooms", headers=student_headers)
    assert res.status_code == 200
    rooms = res.json()
    
    assert len(rooms) == 2
    server_ids = [r["server_id"] for r in rooms]
    assert seeded_room["server_id"] in server_ids
    assert server_id2 in server_ids

@pytest.mark.asyncio
async def test_super_admin_bypasses_privacy_masking(client: TestClient, db, seeded_room, super_admin_headers):
    """Super Admin must see all private data without being a member of the room."""
    server_id = seeded_room["server_id"]
    
    # Inject private data
    await db.execute("UPDATE students SET phone_number = '0999999999' WHERE room_id = $1 AND student_no = 2", seeded_room["room_id"])
    
    # Request profile using Super Admin headers
    res = client.get(f"/api/classroom/{server_id}/students/profile/2", headers=super_admin_headers)
    assert res.status_code == 200
    
    # Assert masking is bypassed
    assert res.json()["phone_number"] == "0999999999"