"""📣 เตือนผู้ค้างชำระรายวัน (Phase 6)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **เลือกบิลถูกชุด** — เลยกำหนด + ครบกำหนดใน 3 วัน เท่านั้น; บิลที่จ่ายครบ/
   ถูกลบ/โปรเจกต์ถูกลบ/ไม่มีกำหนดชำระ/ไกลเกิน 3 วัน ต้องหลุดออก
   (ใช้ predicate "บิลเปิด" มาตรฐานเดียวกับทั้งระบบ)
2. **ไม่ส่งซ้ำวันเดียว** — in-app ต่อคน (`inapp:{user_id}:{date}`) และ Discord
   ชุดเดียวต่อห้อง (`discord:digest:{date}`) ผ่าน `reminder_dispatch_log`
   ⇒ เรียก dispatch ซ้ำกี่ครั้งก็ได้ข้อความชุดเดิมครั้งเดียว
3. **ในแอปเป็นของส่วนตัว** — นักเรียนเห็นเฉพาะบิลของตัวเอง ชี้ไป `/finance/my-debts`
   และนักเรียนที่ยังไม่ผูกบัญชี (`user_id IS NULL`) ต้องไม่ทำให้เกิดแจ้งเตือนลอย
4. **Discord แบ่งข้อความเมื่อคนเยอะ** — `part`/`total_parts` ครบ และยอดรวมของทั้งห้อง
   ซ้ำทุกส่วน เพื่อให้อ่านบางส่วนแล้วยังรู้ยอดจริง
5. **worker** — ยังไม่ถึงเวลา = ไม่แตะ DB · ถึงเวลา = ส่งหนึ่งครั้ง ·
   สคีมียังไม่มา (`42P01`) = `schema_pending` ไม่ใช่ crash
"""
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from services.action_service import ActionService
from services.finance_service import FinanceService
from workers.finance_reminder_worker import _is_missing_schema_error, is_due, run_once

pytestmark = pytest.mark.asyncio

AS_OF = date(2026, 11, 24)


# ---------------------------------------------------------------- seeding

async def _insert_user(pool, first_name: str = "Kid") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "Test", f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_student(pool, room_id: int, *, student_no: int, user_id=None) -> int:
    if user_id is None:
        user_id = await _insert_user(pool)
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _insert_bill(pool, room_id: int, student_id: int, *, due: date | None,
                       amount: float = 100.0, paid: float = 0.0,
                       status: str = "pending", deleted: bool = False,
                       coll_deleted: bool = False) -> int:
    """สร้างโปรเจกต์เก็บเงิน + บิล 1 ใบ — คืน payment_id"""
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status, deleted_at)
               VALUES ($1, $2, $3, $4, 'active', CASE WHEN $5 THEN NOW() ELSE NULL END)
               RETURNING id""",
            room_id, f"ค่าห้อง {uuid.uuid4().hex[:4]}", amount, due, coll_deleted,
        )
        return await conn.fetchval(
            """INSERT INTO student_payments
                   (collection_id, student_id, status, paid_amount, deleted_at)
               VALUES ($1, $2, $3, $4, CASE WHEN $5 THEN NOW() ELSE NULL END) RETURNING id""",
            collection_id, student_id, status, paid, deleted,
        )


async def _set_server_id(pool, room_id: int, server_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE rooms SET server_id = $1 WHERE id = $2", server_id, room_id)


async def _notifications(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT type, title, body, url, user_id FROM notifications
               WHERE room_id = $1 ORDER BY id""",
            room_id,
        )


# ---------------------------------------------------------------- collection

async def test_collects_only_overdue_and_due_soon_open_bills(db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _insert_student(db_pool, room_id, student_no=2)

    overdue_id = await _insert_bill(db_pool, room_id, student_id, due=AS_OF - timedelta(days=2))
    today_id = await _insert_bill(db_pool, room_id, student_id, due=AS_OF)
    soon_id = await _insert_bill(db_pool, room_id, student_id, due=AS_OF + timedelta(days=3))
    # ↓ ต้องหลุดทุกใบ
    await _insert_bill(db_pool, room_id, student_id, due=AS_OF + timedelta(days=4))  # ไกลเกิน
    await _insert_bill(db_pool, room_id, student_id, due=AS_OF - timedelta(days=2),
                       amount=100.0, paid=100.0)                                   # จ่ายครบ
    await _insert_bill(db_pool, room_id, student_id, due=AS_OF - timedelta(days=2),
                       deleted=True)                                               # บิลถูกลบ
    await _insert_bill(db_pool, room_id, student_id, due=AS_OF - timedelta(days=2),
                       coll_deleted=True)                                          # โปรเจกต์ถูกลบ
    await _insert_bill(db_pool, room_id, student_id, due=None)                      # ไม่ระบุกำหนด

    async with db_pool.acquire() as conn:
        rows = await FinanceService._collect_reminder_bills(conn, as_of=AS_OF, room_id=room_id)

    assert sorted(r["payment_id"] for r in rows) == sorted([overdue_id, today_id, soon_id])


async def test_in_app_once_per_student_per_day(db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = admin_headers.student_id  # ผูกบัญชีแล้ว (user_id = admin_headers.user_id)
    await _insert_bill(db_pool, room_id, student_id, due=AS_OF - timedelta(days=1), amount=50.0)
    await _insert_bill(db_pool, room_id, student_id, due=AS_OF + timedelta(days=1), amount=25.0)

    first = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)
    second = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)

    assert first["in_app_sent"] == 1
    assert first["students"] == 1
    assert first["total_amount"] == 75.0
    assert second["in_app_sent"] == 0
    assert second["in_app_duplicate"] == 1

    rows = await _notifications(db_pool, room_id)
    reminders = [r for r in rows if r["type"] == "debt_reminder"]
    assert len(reminders) == 1
    assert reminders[0]["user_id"] == admin_headers.user_id
    assert reminders[0]["url"] == "/finance/my-debts"
    assert "75.00" in reminders[0]["title"]
    assert "เลยกำหนด 1 วัน" in reminders[0]["body"]


async def test_student_without_account_still_listed_on_discord_only(db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _set_server_id(db_pool, room_id, 123456789)
    # ชื่อในรายการแบบ "ghost" (user_id IS NULL) — ยังไม่มีบัญชีให้แจ้งเตือนส่วนตัว
    async with db_pool.acquire() as conn:
        no_account = await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role,
                                     status, is_admin, permissions)
               VALUES ($1, NULL, $2, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, 9,
        )
    await _insert_bill(db_pool, room_id, no_account, due=AS_OF - timedelta(days=5), amount=30.0)

    with patch.object(ActionService, "notify_debt_reminder", new_callable=AsyncMock) as mock_pub:
        stats = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)

    # ไม่มีบัญชี ⇒ ไม่มีแจ้งเตือนในแอป แต่ยังอยู่ในประกาศ Discord ของห้อง
    assert stats["in_app_sent"] == 0
    assert stats["discord_sent"] == 1
    mock_pub.assert_awaited_once()
    kwargs = mock_pub.await_args.kwargs
    assert kwargs["server_id"] == 123456789
    assert kwargs["total_students"] == 1
    assert kwargs["total_amount"] == 30.0
    assert kwargs["students"][0]["student_no"] == 9
    assert kwargs["students"][0]["overdue_count"] == 1
    assert (kwargs["part"], kwargs["total_parts"]) == (1, 1)


async def test_discord_digest_once_per_day(db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _set_server_id(db_pool, room_id, 987654321)
    await _insert_bill(db_pool, room_id, admin_headers.student_id, due=AS_OF, amount=40.0)

    with patch.object(ActionService, "notify_debt_reminder", new_callable=AsyncMock) as mock_pub:
        first = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)
        second = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)

    assert first["discord_sent"] == 1
    assert second["discord_sent"] == 0
    assert second["discord_duplicate"] == 1
    mock_pub.assert_awaited_once()


async def test_discord_split_into_parts_when_many_students(db_pool, admin_headers):
    from services.finance.reminders import REMINDER_DISCORD_CHUNK_SIZE

    room_id = admin_headers.room_id
    await _set_server_id(db_pool, room_id, 111222333)
    total = REMINDER_DISCORD_CHUNK_SIZE + 5
    for i in range(total):
        sid = await _insert_student(db_pool, room_id, student_no=100 + i)
        await _insert_bill(db_pool, room_id, sid, due=AS_OF - timedelta(days=1), amount=10.0)

    with patch.object(ActionService, "notify_debt_reminder", new_callable=AsyncMock) as mock_pub:
        stats = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)

    assert stats["discord_sent"] == 1
    assert mock_pub.await_count == 2
    parts = [c.kwargs["part"] for c in mock_pub.await_args_list]
    totals = [c.kwargs["total_parts"] for c in mock_pub.await_args_list]
    counts = [len(c.kwargs["students"]) for c in mock_pub.await_args_list]
    assert parts == [1, 2]
    assert totals == [2, 2]
    assert counts == [REMINDER_DISCORD_CHUNK_SIZE, 5]
    # ยอดรวมของทั้งห้องต้องซ้ำทุกส่วน
    assert all(c.kwargs["total_students"] == total for c in mock_pub.await_args_list)
    assert all(c.kwargs["total_amount"] == float(total * 10) for c in mock_pub.await_args_list)


async def test_no_bills_sends_nothing(db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _set_server_id(db_pool, room_id, 555555555)

    with patch.object(ActionService, "notify_debt_reminder", new_callable=AsyncMock) as mock_pub:
        stats = await FinanceService.dispatch_daily_reminders(db_pool, as_of=AS_OF)

    assert stats["rooms_with_debt"] == 0
    assert stats["in_app_sent"] == 0
    assert stats["discord_sent"] == 0
    mock_pub.assert_not_awaited()
    assert await _notifications(db_pool, room_id) == []


# ---------------------------------------------------------------- worker

class _MissingTableError(Exception):
    """เลียนแบบ asyncpg.UndefinedTableError — `_is_missing_schema_error` อ่าน `.sqlstate`"""
    sqlstate = "42P01"


async def test_is_due_uses_hour_minute_not_exact_minute():
    assert is_due(datetime(2026, 11, 24, 8, 59), 9, 0) is False
    assert is_due(datetime(2026, 11, 24, 9, 0), 9, 0) is True
    assert is_due(datetime(2026, 11, 24, 14, 3), 9, 0) is True


async def test_is_missing_schema_error_detects_42p01():
    assert _is_missing_schema_error(_MissingTableError()) is True
    assert _is_missing_schema_error(ValueError("boom")) is False


async def test_run_once_waits_before_scheduled_time(db_pool):
    with patch.object(FinanceService, "dispatch_daily_reminders", new_callable=AsyncMock) as mock_dispatch:
        result = await run_once(db_pool, now=datetime(2026, 11, 24, 6, 30))

    assert result["status"] == "waiting"
    mock_dispatch.assert_not_awaited()


async def test_run_once_dispatches_after_scheduled_time(db_pool):
    expected = {"rooms_with_debt": 1, "in_app_sent": 1}
    with patch.object(FinanceService, "dispatch_daily_reminders",
                      new_callable=AsyncMock, return_value=expected) as mock_dispatch:
        result = await run_once(db_pool, now=datetime(2026, 11, 24, 9, 5))

    assert result["status"] == "sent"
    assert result["in_app_sent"] == 1
    mock_dispatch.assert_awaited_once()
    assert mock_dispatch.await_args.kwargs["as_of"] == AS_OF


async def test_run_once_waits_for_missing_schema(db_pool):
    with patch.object(FinanceService, "dispatch_daily_reminders",
                      new_callable=AsyncMock, side_effect=_MissingTableError()):
        result = await run_once(db_pool, now=datetime(2026, 11, 24, 9, 5))

    assert result["status"] == "schema_pending"
