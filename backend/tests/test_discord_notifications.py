"""
Tests for Discord notification payloads (mention + category)

ครอบคลุม:
- ActionService._publish เติม mention/category ใน payload
- notify_* ที่ mention=True (งานใหม่, โน้ตใหม่, ประกาศ, แคมเปญเก็บเงิน)
- notify_* ที่ mention=False (ส่งงาน, รายรับ/รายจ่าย, จ่ายเงิน, สมาชิกใหม่)
- FinanceService: add_transaction / confirm_payment / create_fee_collection publish
- StudentService: add_student publish
"""
import random
import string
import uuid
from unittest.mock import patch, AsyncMock

import pytest

from core.config import settings
from jose import jwt

pytestmark = pytest.mark.asyncio


async def _insert_user(pool, *, email=None, first_name="Test", last_name="User", discord_id=None) -> int:
    if email is None:
        email = f"u{uuid.uuid4().hex[:12]}@test.local"
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, first_name, last_name, username, discord_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            email, first_name, last_name, f"user_{uuid.uuid4().hex[:8]}", discord_id,
        )


async def _insert_room(pool, owner_id: int, room_name="Test Room", server_id=None, channel_id=None) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id, server_id, announcement_channel_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_name, code, owner_id, server_id, channel_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, $3::jsonb)
            """,
            room_id, owner_id, '["all"]',
        )
        return room_id


async def _insert_finance_account(pool, room_id: int, name="กองกลาง", balance=100.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, balance,
        )


async def _insert_category(pool, room_id: int, name="ค่าใช้จ่าย", cat_type="expense") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, cat_type,
        )


def _make_web_headers(user_id: int) -> dict:
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _room_api(target_id: int, path: str) -> str:
    return f"/api/classroom/{target_id}{path}?target_type=room"


# === ActionService._publish payload shape ===


async def test_publish_mentions_require_everyone(db_pool):
    """งานใหม่/โน้ตใหม่/ประกาศ/แคมเปญ → mention=True"""
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_new_task(server_id, "งาน", "ละเอียด", "2026-08-10", "ครู")
        await ActionService.notify_new_note(server_id, "2026-08-10", "หัวข้อ", "ครู")
        await ActionService.notify_custom_message(server_id, "หัว", "ข้อความ", "ครู")
        await ActionService.notify_new_collection(server_id, "ค่าเทอม", 1000.0, "2026-08-10", "เหรัญญิก")

    mention_events = [call.kwargs.get("mention") for call in mock_pub.await_args_list]
    assert all(m is True for m in mention_events)


async def test_publish_no_mention_for_silent(db_pool):
    """ส่งงาน/รายรับ-จ่าย/จ่ายเงิน/สมาชิกใหม่ → mention=False"""
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_task_done(server_id, "งาน", "นร.")
        await ActionService.notify_new_finance(server_id, "income", 500.0, "รายได้", "เหรัญญิก")
        await ActionService.notify_new_finance(server_id, "expense", 300.0, "ค่าใช้จ่าย", "เหรัญญิก")
        await ActionService.notify_payment_confirmed(server_id, "สิงโต", "ค่าเทอม", 1000.0, "เหรัญญิก")
        await ActionService.notify_new_student(server_id, 5, "สมชาย", "ใจดี", "ครู")

    mention_events = [call.kwargs.get("mention") for call in mock_pub.await_args_list]
    assert all(m is False for m in mention_events)


async def test_notify_payments_confirmed_payload(db_pool):
    """รับเงินรวบยอด (Batch) → publish ครั้งเดียว พร้อม items/รวมใน payload (channel=minor)"""
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)
    items = [
        {"title": "ค่าเทอม", "amount": 300.0},
        {"title": "ค่าเสื้อ", "amount": 200.0},
    ]

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_payments_confirmed(
            server_id=server_id,
            payer_name="สิงโต",
            items=items,
            total_amount=500.0,
            user_name="เหรัญญิก",
        )

    mock_pub.assert_awaited_once()
    kwargs = mock_pub.await_args.kwargs
    assert kwargs["mention"] is False
    assert kwargs["channel"] == "minor"
    assert kwargs["category"] == "✅ จ่ายเงินแล้ว"
    # payload_data เป็น positional arg ตัวที่ 3 ของ _publish (ไม่อยู่ใน kwargs)
    payload = mock_pub.await_args.args[2]
    assert payload["payer_name"] == "สิงโต"
    assert payload["items"] == items
    assert payload["total_amount"] == 500.0
    assert payload["count"] == 2


async def test_notify_payments_confirmed_carries_receipt_nos(db_pool):
    """[F5/PR-3] เคลียร์หนี้ที่ออกใบเสร็จอัตโนมัติ → payload ต้องพา `receipt_nos` ไปให้บอท

    🔑 นี่คือ **สัญญาระหว่างสองบริการ**: บอทขอ PDF ด้วยเลขชุดนี้แล้วแนบไปกับข้อความ
       ใบเดิม (`data.get("receipt_nos")` ใน `cogs/redis_listener.py`) ⇒ ถ้า backend
       หยุดส่งคีย์นี้ ฟีเจอร์แนบไฟล์หายทั้งฟีเจอร์โดยที่ **ไม่มีอะไร error เลย**
       (บอทตกไปใช้เส้นทาง "ไม่มีใบเสร็จ" อย่างเงียบ ๆ) — เทสต์นี้คือด่านเดียวที่จับได้
    """
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)
    receipt_nos = ["REC-2569-0001", "REC-2569-0002"]

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_payments_confirmed(
            server_id=server_id,
            payer_name="สิงโต",
            items=[{"title": "ค่าเทอม", "amount": 300.0}],
            total_amount=300.0,
            user_name="เหรัญญิก",
            receipt_nos=receipt_nos,
        )

    mock_pub.assert_awaited_once()
    payload = mock_pub.await_args.args[2]
    assert payload["receipt_nos"] == receipt_nos
    # ลำดับเลขต้องเรียงตามที่ออกจริง — บอทใช้ทั้งชุดเป็นคำขอเดียว ไม่ได้เรียงเอง
    assert payload["receipt_nos"] == sorted(payload["receipt_nos"])
    # และการเพิ่มคีย์นี้ต้องไม่เปลี่ยนอย่างอื่นของข้อความเดิม
    assert mock_pub.await_args.kwargs["mention"] is False
    assert mock_pub.await_args.kwargs["channel"] == "minor"


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="ไม่ส่งมา (บิลเดียว/ติ๊กปิด)"),
        pytest.param({"receipt_nos": None}, id="ส่งมาเป็น None"),
        pytest.param({"receipt_nos": []}, id="ส่งมาเป็นลิสต์ว่าง"),
    ],
)
async def test_notify_payments_confirmed_without_receipts_has_no_key(db_pool, kwargs):
    """[F5/PR-3] ไม่มีใบเสร็จ → **ไม่มีคีย์ `receipt_nos` เลย** (ไม่ใช่ `receipt_nos: None`)

    🔑 เส้นทางเดิม (บิลเดียวจาก `confirm_payment`, การติ๊กปิด, รายการที่ไม่มีใบเสร็จ)
       ต้องเหมือนเดิม **ทุกไบต์** รวมถึงรูปร่างของ payload ที่ Redis — บอทแยกสองทางด้วย
       `if data.get("receipt_nos"):` ⇒ ทั้ง `None` และลิสต์ว่างพาไปทางเดิมได้เหมือนกัน
       แต่การ "ไม่ใส่คีย์" คือสัญญาที่เทสต์ได้ชัดกว่าและไม่มีทางกำกวม
    """
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_payments_confirmed(
            server_id=server_id,
            payer_name="สิงโต",
            items=[{"title": "ค่าอาหาร", "amount": 50.0}],
            total_amount=50.0,
            user_name="เหรัญญิก",
            **kwargs,
        )

    mock_pub.assert_awaited_once()
    payload = mock_pub.await_args.args[2]
    assert "receipt_nos" not in payload
    assert payload["count"] == 1


async def test_notify_new_finance_carries_receipt_nos_of_its_document(db_pool):
    """[F6/PR-6] บันทึกรายจ่าย/รายรับ → payload ต้องพาเลข **เอกสารประกอบ** ไปให้บอท

    🔑 สัญญาระหว่างสองบริการเหมือนของ PR-3 เป๊ะ: บอทขอ PDF ด้วยเลขชุดนี้แล้วแนบไปกับ
       **ข้อความเดิม** (`data.get("receipt_nos")` ใน `cogs/redis_listener.py`) ⇒ ถ้า backend
       หยุดส่งคีย์นี้ ฟีเจอร์แนบใบสำคัญจ่าย/ใบรับเงินหายทั้งฟีเจอร์โดยที่ **ไม่มีอะไร error เลย**
       (บอทตกไปใช้เส้นทาง "ไม่มีเอกสาร" อย่างเงียบ ๆ) — เทสต์นี้คือด่านเดียวที่จับได้
    """
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_new_finance(
            server_id, "expense", 300.0, "ค่าซ่อมแซมห้อง", "เหรัญญิก",
            receipt_nos=["PV-2569-0001"],
        )

    mock_pub.assert_awaited_once()
    payload = mock_pub.await_args.args[2]
    assert payload["receipt_nos"] == ["PV-2569-0001"]
    assert payload["txn_type"] == "expense"
    # และการเพิ่มคีย์นี้ต้องไม่เปลี่ยนอย่างอื่นของข้อความเดิม
    assert mock_pub.await_args.kwargs["mention"] is False
    assert mock_pub.await_args.kwargs["channel"] == "minor"
    assert mock_pub.await_args.kwargs["category"] == "💸 มีรายจ่าย"


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="ไม่ส่งมา (เรียกจากที่อื่น/ไม่มีเอกสาร)"),
        pytest.param({"receipt_nos": None}, id="ส่งมาเป็น None"),
        pytest.param({"receipt_nos": []}, id="ส่งมาเป็นลิสต์ว่าง"),
    ],
)
async def test_notify_new_finance_without_document_has_no_key(db_pool, kwargs):
    """[F6/PR-6] ไม่มีเอกสาร → **ไม่มีคีย์ `receipt_nos` เลย** (ไม่ใช่ `receipt_nos: None`)

    🔑 เส้นทางเดิมต้องเหมือนเดิม **ทุกไบต์** รวมถึงรูปร่างของ payload ที่ Redis — บอทแยก
       สองทางด้วย `if data.get("receipt_nos"):` ⇒ ทั้ง `None` และลิสต์ว่างพาไปทางเดิมได้
       เหมือนกัน แต่การ "ไม่ใส่คีย์" คือสัญญาที่เทสต์ได้ชัดกว่าและไม่มีทางกำกวม
    """
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_new_finance(
            server_id, "income", 500.0, "ขายขยะ", "เหรัญญิก", **kwargs
        )

    mock_pub.assert_awaited_once()
    payload = mock_pub.await_args.args[2]
    assert "receipt_nos" not in payload
    # รูปร่างเดิม 4 คีย์ — ไม่มีอะไรมากกว่านี้
    assert set(payload) == {"txn_type", "amount", "description", "user_name"}


async def test_publish_category_present(db_pool):
    """ทุก event มี category (หัวข้อก่อน embed)"""
    from services.action_service import ActionService
    server_id = random.randint(1_000_000, 9_999_999)

    with patch.object(ActionService, "_publish", new_callable=AsyncMock) as mock_pub:
        await ActionService.notify_new_task(server_id, "งาน", "ละเอียด", "2026-08-10", "ครู")
        await ActionService.notify_new_finance(server_id, "income", 500.0, "รายได้", "เหรัญญิก")

    for call in mock_pub.await_args_list:
        assert call.kwargs.get("category"), f"missing category: {call}"


# === FinanceService publishes ===


async def test_add_income_transaction_publishes(client, db_pool):
    """บันทึกรายรับ → publish notify_new_finance (income)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    account_id = await _insert_finance_account(db_pool, room_id)
    cat_id = await _insert_category(db_pool, room_id, "รายได้", "income")

    from services.action_service import ActionService
    with patch.object(ActionService, "notify_new_finance", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/finance/transactions"),
            json={"account_id": account_id, "category_id": cat_id, "amount": 500.0,
                  "description": "ขายขยะ", "transaction_type": "income", "user_name": "เหรัญญิก",
                  "payee_name": "ผู้จ่ายเงินทดสอบ"},
            headers=_make_web_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    mock_notify.assert_awaited_once()
    kwargs = mock_notify.await_args.kwargs
    assert kwargs["server_id"] == server_id
    assert kwargs["txn_type"] == "income"
    assert kwargs["amount"] == 500.0
    # 🧾 [F6/PR-6] ต้องส่งเลขเอกสารที่เพิ่งออกไปด้วย ⇒ บอทโหลด PDF มาปิดท้าย **ข้อความนี้**
    #    🔑 เทียบกับ `resp.json()` ไม่ใช่ hardcode — พิสูจน์ว่าเลขที่ผู้ใช้เห็นบนจอ
    #       คือเลขเดียวกันกับที่ถูกส่งไปแนบไฟล์ (และพิสูจน์ว่าเอกสารถูกออกจริง)
    #    🔴 `receipt_nos` เป็น **list** เสมอเมื่อมีเอกสาร — บอทวนซ้ำได้โดยไม่ต้องแยกกรณี
    assert kwargs["receipt_nos"] == [resp.json()["receipt_no"]]


async def test_add_expense_transaction_publishes(client, db_pool):
    """บันทึกรายจ่าย → publish notify_new_finance (expense)"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    account_id = await _insert_finance_account(db_pool, room_id, balance=1000.0)
    cat_id = await _insert_category(db_pool, room_id, "ค่าใช้จ่าย", "expense")

    from services.action_service import ActionService
    with patch.object(ActionService, "notify_new_finance", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/finance/transactions"),
            json={"account_id": account_id, "category_id": cat_id, "amount": 300.0,
                  "description": "ซื้ออุปกรณ์", "transaction_type": "expense", "user_name": "เหรัญญิก",
                  "payee_name": "ร้านอุปกรณ์การเรียน"},
            headers=_make_web_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    mock_notify.assert_awaited_once()
    kwargs = mock_notify.await_args.kwargs
    assert kwargs["txn_type"] == "expense"
    # 🧾 [F6/PR-6] รายจ่าย → ใบสำคัญจ่าย (`PV-…`) ต้องถูกส่งไปแนบพร้อมข้อความนี้
    assert kwargs["receipt_nos"] == [resp.json()["receipt_no"]]


async def test_create_collection_publishes_mention(client, db_pool):
    """สร้างแคมเปญเก็บเงิน → publish notify_new_collection"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    from services.action_service import ActionService
    with patch.object(ActionService, "notify_new_collection", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/finance/collections"),
            json={"title": "ค่าเทอม", "amount": 1000.0, "due_date": "2026-08-10", "user_name": "เหรัญญิก"},
            headers=_make_web_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    mock_notify.assert_awaited_once()
    assert mock_notify.await_args.kwargs["server_id"] == server_id


# === StudentService publishes ===


async def test_add_student_publishes(client, db_pool):
    """เพิ่มนักเรียน → publish notify_new_student"""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    server_id = random.randint(1_000_000, 9_999_999)
    room_id = await _insert_room(db_pool, owner, server_id=server_id)

    from services.action_service import ActionService
    with patch.object(ActionService, "notify_new_student", new_callable=AsyncMock) as mock_notify:
        resp = client.post(
            _room_api(room_id, "/students"),
            json={"student_no": 5, "first_name": "สมชาย", "last_name": "ใจดี", "user_name": "ครู"},
            headers=_make_web_headers(owner),
        )
        assert resp.status_code == 200, resp.text

    mock_notify.assert_awaited_once()
    assert mock_notify.await_args.kwargs["server_id"] == server_id
    assert mock_notify.await_args.kwargs["student_no"] == 5
