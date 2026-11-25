"""💰 [FIN-V2 / P4.4] ใบรับเงินหลายบรรทัด (income batch)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **1 ใบ = N transactions + N journals + 1 INC** — ไม่ใช่ journal รวมก้อนเดียว
   (รายงาน/งบอ่านยอดต่อหมวดจากรายการ ⇒ รวมแล้วยอดหมวดเพี้ยน)
2. **กระเป๋าเดียวทั้งใบ** — ยอดเข้าถูกครั้งเดียว ไม่กระจายหลายบัญชี
3. **INC 1 ใบ** — `layout_version=2`, anchor `legacy_transaction_id` = txn บรรทัดแรก,
   `idempotency_key='inc:{id}'`, 2 ลายเซ็น (`prepared`/`receiver`)
4. **ผู้จ่ายอิสระ** — ไม่ต้องมีใน students/people
5. **ผู้รับจากทะเบียน** — ส่ง person id แล้วชื่อบนเอกสารต้องมาจาก `display_name`
6. **idempotency** — คีย์เดิม + payload เดิม ⇒ ใบเดิม (`reused=true`);
   payload ต่าง ⇒ **409**
7. **ตรวจครบก่อนเขียน** — ยอดรวมไม่ตรง / หมวดรายจ่าย / ช่องทางไม่ตรงกระเป๋า ⇒ 400
8. **atomic ทั้งใบ** — ล้มกลางทาง ⇒ rollback ทั้งใบ (ยอดกระเป๋าไม่ขยับ)

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import importlib.util
import json
import pathlib
import random
import string
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from services.finance.constants import THAI_TZ
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
_INC_DOC_TYPE = "income"


# ═══════════════════════════════════════════════════════════════════ helpers
def _batches_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/income-batches?target_type=room"


def _batch_url(room_id: int, batch_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/income-batches/{batch_id}?target_type=room"


def _new_key() -> str:
    return uuid.uuid4().hex


def _money(value) -> str:
    return f"{float(value):.2f}"


async def _insert_room(pool, owner_id: int) -> int:
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        return await conn.fetchval(
            """INSERT INTO rooms (room_name, room_code, owner_id)
               VALUES ('ห้องอื่น', $1, $2) RETURNING id""",
            code, owner_id,
        )


async def _insert_category(
    pool, room_id: int, name: str, cat_type: str = "income",
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               VALUES ($1, $2, $3) RETURNING id""",
            room_id, name, cat_type,
        )


async def _insert_account(
    pool, room_id: int, name: str = "กระเป๋ากลาง", balance: float = 0.0,
    is_custody: bool = False,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_accounts (room_id, account_name, balance, is_custody)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            room_id, name, balance, is_custody,
        )


async def _insert_person(
    pool, room_id: int, name: str, roles=("receive",), is_active: bool = True,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_people
                   (room_id, person_type, display_name, roles, is_active)
               VALUES ($1, 'external', $2, $3::TEXT[], $4) RETURNING id""",
            room_id, name, list(roles), is_active,
        )


async def _insert_channel(
    pool, room_id: int, label: str = "เงินสดหน้าร้าน",
    channel_type: str = "cash", wallet_account_id=None,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_payment_channels
                   (room_id, channel_type, label, wallet_account_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            room_id, channel_type, label, wallet_account_id,
        )


async def _balance(pool, account_id: int) -> float:
    async with pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT balance FROM finance_accounts WHERE id = $1", account_id
        ))


async def _count(pool, table: str, room_id: int) -> int:
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE room_id = $1", room_id,
        ))


async def _inc_rows(pool, batch_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM finance_receipts
               WHERE doc_type = $1 AND idempotency_key = $2 ORDER BY id""",
            _INC_DOC_TYPE, f"inc:{batch_id}",
        )


def _line(amount: float, *, category_id: int, description: str = "รายการทดสอบ") -> dict:
    return {
        "description": description,
        "amount": _money(amount),
        "category_id": category_id,
    }


def _payload(
    *, key=None, wallet_account_id: int, lines: list,
    payer_name: str = "ผู้ปกครองนักเรียน ม.2",
    receiver_person_id=None, receiver_name: str | None = "ครูสมหญิง",
    channel_id=None, income_date=None, note: str = "รายรับอื่นทดสอบ",
    total_amount=None,
) -> dict:
    body = {
        "idempotency_key": key or _new_key(),
        "payer_name": payer_name,
        "wallet_account_id": wallet_account_id,
        "note": note,
        "lines": lines,
    }
    if receiver_person_id is not None:
        body["receiver_person_id"] = receiver_person_id
    if receiver_name is not None:
        body["receiver_name"] = receiver_name
    if channel_id is not None:
        body["channel_id"] = channel_id
    if income_date is not None:
        body["income_date"] = income_date
    if total_amount is not None:
        body["total_amount"] = _money(total_amount)
    return body


async def _seed(pool, room: int):
    """หมวดรายรับ 2 ใบ + กระเป๋า 1 ใบ (0 บาท) — คืน (cat_a, cat_b, wallet)"""
    cat_a = await _insert_category(pool, room, "เงินสนับสนุนกิจกรรม")
    cat_b = await _insert_category(pool, room, "ขายของที่ระลึก")
    wallet = await _insert_account(pool, room, "เงินสดหน้าร้าน", 0.0)
    return cat_a, cat_b, wallet


def _two_line_payload(cat_a, cat_b, wallet, key=None) -> dict:
    return _payload(
        key=key, wallet_account_id=wallet,
        lines=[
            _line(2000.0, category_id=cat_a, description="เงินสนับสนุนกิจกรรม"),
            _line(500.0, category_id=cat_b, description="ขายของที่ระลึก"),
        ],
    )


def _money_lock_tests():
    """โหลด `test_finance_money_lock.py` เป็นโมดูล (tests/ ไม่ใช่ package)"""
    path = pathlib.Path(__file__).with_name("test_finance_money_lock.py")
    spec = importlib.util.spec_from_file_location("_money_lock_tests_for_p44", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ═════════════ 1. 2 บรรทัด → 2 txn + 2 journal (Dr=Cr=2500)
async def test_create_batch_two_lines_creates_two_transactions_and_journals(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    res = client.post(
        _batches_url(room), json=_two_line_payload(cat_a, cat_b, wallet),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    batch_id = body["id"]
    assert _money(body["total_amount"]) == "2500.00"
    assert body["line_count"] == 2
    assert body["reused"] is False

    async with db_pool.acquire() as conn:
        txns = await conn.fetch(
            """SELECT id, amount, transaction_type, account_id, payee_name
               FROM finance_transactions
               WHERE room_id = $1 AND income_batch_id = $2 ORDER BY id""",
            room, batch_id,
        )
        assert len(txns) == 2
        assert sorted(_money(t["amount"]) for t in txns) == ["2000.00", "500.00"]
        assert all(t["transaction_type"] == "income" for t in txns)
        assert all(t["account_id"] == wallet for t in txns)
        assert all(t["payee_name"] == "ผู้ปกครองนักเรียน ม.2" for t in txns)

        lines = await conn.fetch(
            """SELECT line_no, finance_transaction_id, amount
               FROM finance_income_lines WHERE batch_id = $1 ORDER BY line_no""",
            batch_id,
        )
        assert [row["line_no"] for row in lines] == [1, 2]
        assert {row["finance_transaction_id"] for row in lines} == {t["id"] for t in txns}

        journals = await conn.fetch(
            """SELECT id FROM journal_entries
               WHERE room_id = $1 AND reference_type = 'income_batch' ORDER BY id""",
            room,
        )
        assert len(journals) == 2
        for j in journals:
            totals = await conn.fetchrow(
                """SELECT SUM(debit) AS dr, SUM(credit) AS cr, COUNT(*) AS n
                   FROM journal_lines WHERE journal_entry_id = $1""",
                j["id"],
            )
            assert int(totals["n"]) == 2
            assert _money(totals["dr"]) == _money(totals["cr"])
        # ผลรวม Dr = 2500 ทั้งใบ (ไม่ใช่ 2500 ต่อบรรทัด)
        grand = await conn.fetchrow(
            """SELECT SUM(debit) AS dr, SUM(credit) AS cr
               FROM journal_lines WHERE journal_entry_id = ANY($1::uuid[])""",
            [j["id"] for j in journals],
        )
        assert _money(grand["dr"]) == "2500.00"
        assert _money(grand["cr"]) == "2500.00"


# ═════════════ 2. กระเป๋าเดียว — ยอดเข้าครั้งเดียว (+2500)
async def test_batch_uses_single_wallet_and_credits_total_once(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    res = client.post(
        _batches_url(room), json=_two_line_payload(cat_a, cat_b, wallet),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    assert _money(await _balance(db_pool, wallet)) == "2500.00"
    # ไม่มีกระเป๋าอื่นถูกสร้าง/ถูกแตะ
    assert await _count(db_pool, "finance_accounts", room) == 1


# ═════════════ 3. INC 1 ใบ + anchor txn บรรทัดแรก
async def test_batch_issues_exactly_one_inc(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    res = client.post(
        _batches_url(room), json=_two_line_payload(cat_a, cat_b, wallet),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["inc_receipt_no"].startswith("INC-")

    incs = await _inc_rows(db_pool, body["id"])
    assert len(incs) == 1
    inc = incs[0]
    assert inc["layout_version"] == 2
    assert _money(inc["amount"]) == "2500.00"
    assert _money(inc["paid_total_after"]) == "2500.00"
    assert inc["issued_to_name"] == "ผู้ปกครองนักเรียน ม.2"
    assert inc["room_id"] == room

    async with db_pool.acquire() as conn:
        first_txn = await conn.fetchval(
            """SELECT id FROM finance_transactions
               WHERE income_batch_id = $1 ORDER BY id LIMIT 1""",
            body["id"],
        )
        batch = await conn.fetchrow(
            "SELECT inc_receipt_id FROM finance_income_batches WHERE id = $1",
            body["id"],
        )
    assert inc["legacy_transaction_id"] == first_txn
    assert batch["inc_receipt_id"] == inc["id"]
    assert body["inc_receipt_id"] == inc["id"]


# ═════════════ 4. idempotency_key = `inc:{batch_id}`
async def test_inc_idempotency_key_is_inc_batch_id(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    res = client.post(
        _batches_url(room), json=_two_line_payload(cat_a, cat_b, wallet),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    incs = await _inc_rows(db_pool, body["id"])
    assert len(incs) == 1
    assert incs[0]["idempotency_key"] == f"inc:{body['id']}"


# ═════════════ 5. 2 ลายเซ็น (prepared / receiver)
async def test_batch_writes_two_signatures(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    person = await _insert_person(db_pool, room, "ครูสมหญิง")

    res = client.post(
        _batches_url(room),
        json=_payload(
            wallet_account_id=wallet, receiver_person_id=person,
            lines=[_line(100.0, category_id=cat_a)],
        ),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    async with db_pool.acquire() as conn:
        sigs = await conn.fetch(
            """SELECT role, person_id, signer_name, signed_at, sort_order
               FROM finance_document_signatures
               WHERE doc_type = $1 AND doc_id = $2 ORDER BY sort_order""",
            _INC_DOC_TYPE, body["inc_receipt_id"],
        )
    assert [s["role"] for s in sigs] == ["prepared", "receiver"]
    assert [s["sort_order"] for s in sigs] == [0, 1]
    assert all(s["signed_at"] is None for s in sigs)
    assert sigs[1]["person_id"] == person
    assert sigs[1]["signer_name"] == "ครูสมหญิง"


# ═════════════ 6. retry คีย์เดิม payload เดิม ⇒ ใบเดิม
async def test_batch_replay_returns_same_documents(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    key = "income-idem-" + uuid.uuid4().hex

    payload = _two_line_payload(cat_a, cat_b, wallet, key=key)
    first = client.post(_batches_url(room), json=payload, headers=admin_headers)
    assert first.status_code == 200, first.text
    second = client.post(_batches_url(room), json=payload, headers=admin_headers)
    assert second.status_code == 200, second.text

    a, b = first.json(), second.json()
    assert b["reused"] is True
    assert b["id"] == a["id"]
    assert b["inc_receipt_no"] == a["inc_receipt_no"]

    assert await _count(db_pool, "finance_income_batches", room) == 1
    assert await _count(db_pool, "finance_transactions", room) == 2
    assert await _count(db_pool, "finance_receipts", room) == 1
    assert _money(await _balance(db_pool, wallet)) == "2500.00"


# ═════════════ 7. คีย์เดิม payload ต่าง ⇒ 409
async def test_batch_replay_with_different_payload_is_409(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    key = "income-idem-" + uuid.uuid4().hex

    first = client.post(
        _batches_url(room),
        json=_two_line_payload(cat_a, cat_b, wallet, key=key),
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    changed = _two_line_payload(cat_a, cat_b, wallet, key=key)
    changed["note"] = "เปลี่ยนหมายเหตุ"
    second = client.post(_batches_url(room), json=changed, headers=admin_headers)
    assert second.status_code == 409, second.text

    assert await _count(db_pool, "finance_income_batches", room) == 1


# ═════════════ 8. ยอดรวมไม่ตรง ⇒ 400 และไม่มีร่องรอย
async def test_batch_rejects_total_mismatch(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    payload = _two_line_payload(cat_a, cat_b, wallet)
    payload["total_amount"] = "9999.00"
    res = client.post(_batches_url(room), json=payload, headers=admin_headers)
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_income_batches", room) == 0
    assert await _count(db_pool, "finance_transactions", room) == 0
    assert _money(await _balance(db_pool, wallet)) == "0.00"


# ═════════════ 9. หมวดรายจ่าย ⇒ 400
async def test_batch_rejects_expense_category(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    expense_cat = await _insert_category(db_pool, room, "วัสดุสำนักงาน", "expense")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)

    res = client.post(
        _batches_url(room),
        json=_payload(
            wallet_account_id=wallet,
            lines=[_line(100.0, category_id=expense_cat)],
        ),
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_income_batches", room) == 0


# ═════════════ 10. person id ชนะชื่อที่ client ส่ง
async def test_batch_receiver_person_snapshot_overrides_client_name(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    person = await _insert_person(db_pool, room, "ครูสมหญิง")

    res = client.post(
        _batches_url(room),
        json=_payload(
            wallet_account_id=wallet, receiver_person_id=person,
            receiver_name="ชื่อปลอมจาก client",
            lines=[_line(100.0, category_id=cat_a)],
        ),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    async with db_pool.acquire() as conn:
        batch = await conn.fetchrow(
            """SELECT receiver_name, receiver_person_id
               FROM finance_income_batches WHERE id = $1""",
            body["id"],
        )
        meta = await conn.fetchval(
            """SELECT document_meta->>'receiver_name' FROM finance_receipts
               WHERE id = $1""",
            body["inc_receipt_id"],
        )
        sig = await conn.fetchval(
            """SELECT signer_name FROM finance_document_signatures
               WHERE doc_type = $1 AND doc_id = $2 AND role = 'receiver'""",
            _INC_DOC_TYPE, body["inc_receipt_id"],
        )
    assert batch["receiver_name"] == "ครูสมหญิง"
    assert batch["receiver_person_id"] == person
    assert meta == "ครูสมหญิง"
    assert sig == "ครูสมหญิง"


# ═════════════ 11. ช่องทางที่ผูกกระเป๋าอื่น ⇒ 400
async def test_batch_channel_wallet_mismatch_is_400(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    other_wallet = await _insert_account(db_pool, room, "ธนาคารห้อง", 0.0)
    channel = await _insert_channel(
        db_pool, room, label="เงินสดสาขา", channel_type="cash",
        wallet_account_id=other_wallet,
    )

    res = client.post(
        _batches_url(room),
        json=_payload(
            wallet_account_id=wallet, channel_id=channel,
            lines=[_line(100.0, category_id=cat_a)],
        ),
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_income_batches", room) == 0


# ═════════════ 12. เก็บ channel snapshot + channel_id
async def test_batch_stores_channel_snapshot(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    channel = await _insert_channel(
        db_pool, room, label="เงินสดหน้าร้าน", channel_type="cash",
        wallet_account_id=wallet,
    )

    res = client.post(
        _batches_url(room),
        json=_payload(
            wallet_account_id=wallet, channel_id=channel,
            lines=[_line(100.0, category_id=cat_a)],
        ),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    async with db_pool.acquire() as conn:
        batch = await conn.fetchrow(
            """SELECT channel_id, channel_snapshot
               FROM finance_income_batches WHERE id = $1""",
            body["id"],
        )
        inc_meta = await conn.fetchval(
            "SELECT document_meta FROM finance_receipts WHERE id = $1",
            body["inc_receipt_id"],
        )
    snap = batch["channel_snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap)
    meta = json.loads(inc_meta) if isinstance(inc_meta, str) else inc_meta
    assert batch["channel_id"] == channel
    assert snap["channel_type"] == "cash"
    assert snap["label"] == "เงินสดหน้าร้าน"
    assert meta["channel"]["channel_type"] == "cash"


# ═════════════ 13. ล้มกลางทาง ⇒ rollback ทั้งใบ
async def test_batch_rolls_back_all_lines_on_midway_failure(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    original = FinanceService._insert_journal_entry
    calls = {"n": 0}

    async def _fail_on_second(cls_, conn, room_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("ล้มกลางทาง (ทดสอบ)")
        return await original(conn, room_id, **kwargs)

    with patch.object(FinanceService, "_insert_journal_entry", new=classmethod(_fail_on_second)):
        res = client.post(
            _batches_url(room), json=_two_line_payload(cat_a, cat_b, wallet),
            headers=admin_headers,
        )

    assert res.status_code == 400, res.text
    assert calls["n"] == 2
    assert await _count(db_pool, "finance_income_batches", room) == 0
    # `finance_income_lines` ไม่มี `room_id` — นับผ่าน batch ของห้องนี้
    async with db_pool.acquire() as conn:
        line_count = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_income_lines L
               JOIN finance_income_batches B ON B.id = L.batch_id
               WHERE B.room_id = $1""",
            room,
        )
    assert int(line_count) == 0
    assert await _count(db_pool, "finance_transactions", room) == 0
    assert await _count(db_pool, "journal_entries", room) == 0
    assert await _count(db_pool, "finance_receipts", room) == 0
    assert _money(await _balance(db_pool, wallet)) == "0.00"


# ═════════════ 14. ต้องมี MANAGE_FINANCE ⇒ 403
async def test_batch_requires_manage_finance(
    client, db_pool, member_headers,
):
    room = member_headers.room_id
    cat = await _insert_category(db_pool, room, "เงินสนับสนุนกิจกรรม")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)

    res = client.post(
        _batches_url(room),
        json=_payload(wallet_account_id=wallet,
                      lines=[_line(100.0, category_id=cat)]),
        headers=member_headers,
    )
    assert res.status_code == 403, res.text
    assert await _count(db_pool, "finance_income_batches", room) == 0


# ═════════════ 15. ขอบเขตห้อง — สร้างข้ามห้องไม่ได้
async def test_batch_is_room_scoped(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)

    own = client.post(
        _batches_url(room), json=_two_line_payload(cat_a, cat_b, wallet),
        headers=admin_headers,
    )
    assert own.status_code == 200, own.text

    other_room = await _insert_room(db_pool, admin_headers.user_id)
    other_cat = await _insert_category(db_pool, other_room, "เงินสนับสนุนกิจกรรม")
    other_wallet = await _insert_account(db_pool, other_room, "เงินสดหน้าร้าน", 0.0)
    cross = client.post(
        _batches_url(other_room),
        json=_payload(wallet_account_id=other_wallet,
                      lines=[_line(100.0, category_id=other_cat)]),
        headers=admin_headers,
    )
    assert cross.status_code == 403, cross.text
    assert await _count(db_pool, "finance_income_batches", other_room) == 0
    assert await _count(db_pool, "finance_receipts", other_room) == 0


# ═════════════ 16. เพดาน 50 บรรทัด
async def test_batch_caps_lines_at_50(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "เงินสนับสนุนกิจกรรม")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)

    res = client.post(
        _batches_url(room),
        json=_payload(
            wallet_account_id=wallet,
            lines=[_line(1.0, category_id=cat) for _ in range(51)],
        ),
        headers=admin_headers,
    )
    assert res.status_code == 400, res.text
    assert await _count(db_pool, "finance_income_batches", room) == 0


# ═════════════ 17. `_MONEY_PATHS` มี income batch
async def test_money_path_list_includes_create_income_batch():
    module = _money_lock_tests()
    assert ("income_batches", "IncomeBatchesMixin", "create_income_batch") in module._MONEY_PATHS


# ═════════════ 18. list/detail shapes
async def test_income_list_and_detail_shapes(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat_a, cat_b, wallet = await _seed(db_pool, room)
    channel = await _insert_channel(
        db_pool, room, label="เงินสดหน้าร้าน", channel_type="cash",
        wallet_account_id=wallet,
    )
    created = client.post(
        _batches_url(room),
        json=_payload(wallet_account_id=wallet, channel_id=channel,
                      lines=[
                          _line(2000.0, category_id=cat_a, description="เงินสนับสนุนกิจกรรม"),
                          _line(500.0, category_id=cat_b, description="ขายของที่ระลึก"),
                      ]),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    batch_id = created.json()["id"]

    listing = client.get(_batches_url(room), headers=admin_headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert len(body["items"]) == 1
    assert _money(body["total"]) == "2500.00"
    item = body["items"][0]
    assert item["id"] == batch_id
    assert item["line_count"] == 2
    assert item["payer_name"] == "ผู้ปกครองนักเรียน ม.2"
    assert item["receiver_name"] == "ครูสมหญิง"
    assert item["inc_receipt_no"] == created.json()["inc_receipt_no"]

    detail = client.get(_batch_url(room, batch_id), headers=admin_headers)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["payer_name"] == "ผู้ปกครองนักเรียน ม.2"
    assert len(d["lines"]) == 2
    assert [row["line_no"] for row in d["lines"]] == [1, 2]
    assert d["lines"][0]["category_name"] == "เงินสนับสนุนกิจกรรม"
    assert d["channel"]["channel_type"] == "cash"
    assert d["channel"]["label"] == "เงินสดหน้าร้าน"
    assert len(d["signatures"]) == 2


# ═════════════ 19. งบรายรับนับยอดใช้ตามหมวด ไม่นับซ้ำ
async def test_budget_usage_counts_income_lines_per_category(
    client, db_pool, admin_headers,
):
    room = admin_headers.room_id
    cat = await _insert_category(db_pool, room, "เงินสนับสนุนกิจกรรม")
    cat_other = await _insert_category(db_pool, room, "ขายของที่ระลึก")
    wallet = await _insert_account(db_pool, room, "เงินสดหน้าร้าน", 0.0)

    today = datetime.now(THAI_TZ).date()
    budget = client.post(
        f"{API_PREFIX}/{room}/finance/budgets?target_type=room",
        json={
            "category_id": cat,
            "amount": 5000,
            "start_date": today.isoformat(),
            "end_date": today.isoformat(),
            "note": "งบรายรับทดสอบ P4.4",
            "user_name": "Tester",
        },
        headers=admin_headers,
    )
    assert budget.status_code == 200, budget.text
    async with db_pool.acquire() as conn:
        budget_id = await conn.fetchval(
            "SELECT id FROM finance_budgets WHERE room_id = $1 AND category_id = $2",
            room, cat,
        )

    res = client.post(
        _batches_url(room),
        json=_payload(wallet_account_id=wallet, lines=[
            _line(2000.0, category_id=cat, description="เงินสนับสนุนกิจกรรม"),
            _line(500.0, category_id=cat_other, description="ขายของที่ระลึก"),
        ]),
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text

    overview = client.get(
        f"{API_PREFIX}/{room}/finance/budgets/overview?target_type=room",
        params={"start_date": today.isoformat(), "end_date": today.isoformat()},
        headers=admin_headers,
    )
    assert overview.status_code == 200, overview.text
    item = next(i for i in overview.json()["items"] if i["budget_id"] == budget_id)
    # 2000 = เฉพาะหมวดนี้ **ครั้งเดียว** — ถ้านับ txn+journal ซ้ำจะเป็น 4000
    assert _money(item["used"]) == "2000.00"
