"""[F5] ชุดเอกสาร (Document Batch) — finance_receipt_batches + `finance_receipts.batch_id`

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร (เรียงตามความสำคัญ)
═══════════════════════════════════════════════════════════════════════════════
1. **`batch_size` ต้องนับ "ทั้งชุด" ไม่ใช่ "แถวที่รอดตัวกรอง"** ← ตัวที่มีค่าที่สุด
   ถ้าใครเปลี่ยนไปใช้ `COUNT(*) OVER (PARTITION BY batch_id)` ตัวเลขจะดูถูกทุกครั้งที่
   ไม่ได้กรองอะไร แล้ว **โกหกทันทีที่ผู้ใช้กรองช่วงวันที่** ⇒ เทสต์นี้กรองให้เห็นชัด ๆ

2. **ยุบชุดต้องไม่แตะเอกสาร** — ใบเสร็จยัง `status='active'`, ยอดเดิม, เลขที่เดิม
   (ผู้ใช้กำลังแจกเอกสารที่พิมพ์ไปแล้ว ⇒ "ยุบชุด" ห้ามมีความหมายอื่นนอกจาก "เลิกจัดกลุ่ม")

3. **ชุดต้องไม่ข้ามห้อง** — ทั้งการอ่าน/แก้ด้วยการเดา `batch_id` และการอ้างเลขที่เอกสาร
   ของห้องอื่น (ตรวจกับ DB ว่า **ไม่มีแถวถูกสร้าง/ถูกแก้** ไม่ใช่ดูแค่ status code)

4. **กดซ้ำต้องไม่สร้างชุดซ้ำ** — เซตสมาชิกเดิม ⇒ คืนชุดเดิม `created=false`
   และตารางต้องมีแถวเดียว (idempotency ที่ผูกกับ "ผลลัพธ์" ไม่ใช่ "เหตุการณ์")

5. **ชุดอัตโนมัติต้องนับเฉพาะใบที่ออกใหม่จริง** — ใบที่ `reused` ไม่ถูกย้ายเข้าชุดใหม่
   และออกใบเดียวต้อง **ไม่** สร้างชุด (ไม่มีอะไรให้ยุบ)

⚠️ ทุกเทสต์ยืนยันกับ DB จริงผ่าน `db_pool` ไม่เชื่อแค่ HTTP status (กฎ docs/rules/testing.md)
"""
import uuid
from datetime import date, datetime, timezone

import pytest

from services.finance.constants import AUTO_BATCH_MIN, BATCH_RECEIPTS_MAX

pytestmark = pytest.mark.asyncio

# ⚠️ finance router mount ด้วย prefix `/api/classroom` (backend/main.py:79)
API_PREFIX = "/api/classroom"
BATCHES_PATH = API_PREFIX + "/{room}/finance/receipt-batches"
BATCH_PATH = API_PREFIX + "/{room}/finance/receipt-batches/{batch_id}"
BATCH_RECEIPTS_PATH = API_PREFIX + "/{room}/finance/receipt-batches/{batch_id}/receipts"
RECEIPTS_PATH = API_PREFIX + "/{room}/finance/receipts"
ISSUE_BATCH_PATH = API_PREFIX + "/{room}/finance/receipts/batch"
INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices"
ROOM_INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices/room"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"


def _url(template: str, room_id: int, **kwargs) -> str:
    """URL ของ finance API — web ต้องส่ง `target_type=room` เสมอ (default คือ server)"""
    return template.format(room=room_id, **kwargs) + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, name,
        )


async def _make_debtor(pool, room_id: int, *, student_no: int = 90,
                       first_name: str = "เด็กชายทดสอบ") -> int:
    """สร้าง user + students row สำหรับเป็นผู้ชำระ (คนละคนกับผู้ออกเอกสาร)"""
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "ทดลอง", f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _join_room(pool, room_id: int, user_id: int, *, student_no: int = 99,
                     is_admin: bool = False, permissions: str = "[]") -> int:
    """เพิ่ม **ผู้ใช้ที่มีอยู่แล้ว** (จาก fixture) เข้าเป็นสมาชิกของห้องที่ระบุ

    🎯 จำเป็นเพราะ fixture `member_headers`/`finance_manager_headers` สร้างห้องของตัวเอง
       ⇒ การทดสอบ "สมาชิกห้องเดียวกันอ่านได้/เขียนไม่ได้" ต้องย้ายเขามาก่อน
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', $4, $5::jsonb) RETURNING id""",
            room_id, user_id, student_no, is_admin, permissions,
        )


async def _make_bill(pool, room_id: int, student_id: int, *, amount: float = 1000.0,
                     title: str = "ค่าเทอม") -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, title, amount, date(2026, 12, 31),
        )
        return await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0) RETURNING id""",
            collection_id, student_id,
        )


# ═══════════════════════════════════════════════════════════════════ HTTP helpers
def _issue_one(client, headers, payment_id: int, *, room_id=None):
    return client.post(
        _url(RECEIPTS_PATH, room_id if room_id is not None else headers.room_id),
        json={"payment_id": payment_id, "doc_type": "receipt"}, headers=headers,
    )


def _issue_many(client, headers, payment_ids, *, room_id=None):
    return client.post(
        _url(ISSUE_BATCH_PATH, room_id if room_id is not None else headers.room_id),
        json={"payment_ids": payment_ids}, headers=headers,
    )


def _create_batch(client, headers, receipt_nos, *, title=None, room_id=None):
    body = {"receipt_nos": receipt_nos}
    if title is not None:
        body["title"] = title
    return client.post(
        _url(BATCHES_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _set_members(client, headers, batch_id, receipt_nos, *, room_id=None):
    return client.put(
        _url(BATCH_RECEIPTS_PATH, room_id if room_id is not None else headers.room_id,
             batch_id=batch_id),
        json={"receipt_nos": receipt_nos}, headers=headers,
    )


def _rename(client, headers, batch_id, *, room_id=None, **fields):
    return client.patch(
        _url(BATCH_PATH, room_id if room_id is not None else headers.room_id, batch_id=batch_id),
        json=fields, headers=headers,
    )


def _dissolve(client, headers, batch_id, *, room_id=None):
    return client.delete(
        _url(BATCH_PATH, room_id if room_id is not None else headers.room_id, batch_id=batch_id),
        headers=headers,
    )


def _list_batches(client, headers, *, room_id=None):
    return client.get(
        _url(BATCHES_PATH, room_id if room_id is not None else headers.room_id), headers=headers,
    )


def _batch_detail(client, headers, batch_id, *, room_id=None):
    return client.get(
        _url(BATCH_PATH, room_id if room_id is not None else headers.room_id, batch_id=batch_id),
        headers=headers,
    )


def _list_receipts(client, headers, *, room_id=None, extra: str = ""):
    return client.get(
        _url(RECEIPTS_PATH, room_id if room_id is not None else headers.room_id) + extra,
        headers=headers,
    )


async def _pay(client, headers, payment_id: int, account_id: int, amount: float):
    return client.put(
        _url(PAY_PATH, headers.room_id, payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )


# ═══════════════════════════════════════════════════════════════════ DB helpers
async def _db_batches(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, room_id, title, source, note, created_by, created_by_name,
                      created_at, updated_at, deleted_at
               FROM finance_receipt_batches WHERE room_id = $1 ORDER BY id""",
            room_id,
        )
        return [dict(r) for r in rows]


async def _db_batch_id_of(pool, receipt_no: str):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT batch_id FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )


async def _db_receipt(pool, receipt_no: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, receipt_no, status, amount, deleted_at, batch_id
               FROM finance_receipts WHERE receipt_no = $1""",
            receipt_no,
        )
        return dict(row) if row else None


async def _db_tx_of(pool, receipt_no: str):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT legacy_transaction_id FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )


async def _seed_receipts(client, db_pool, headers, *, count: int = 3,
                         months_apart: bool = False):
    """จ่ายจริงทีละบิล → ออกใบเสร็จ **ทีละใบ** (ไม่ผ่านเส้นทาง batch ⇒ ไม่มีชุดอัตโนมัติ)

    คืน `(account_id, [receipt_no, ...])` เรียงตามลำดับการออก
    """
    room_id = headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    nos = []
    for i in range(count):
        student_id = await _make_debtor(db_pool, room_id, student_no=90 + i,
                                        first_name=f"เด็ก{i}")
        amount = 100.0 * (i + 1)
        payment_id = await _make_bill(db_pool, room_id, student_id, amount=amount)
        paid = await _pay(client, headers, payment_id, account_id, amount)
        assert paid.status_code == 200, paid.text
        res = _issue_one(client, headers, payment_id)
        assert res.status_code == 200, res.text
        no = res.json()["receipt"]["receipt_no"]
        nos.append(no)
        if months_apart:
            # 🗓️ ถอย "วันที่ของเอกสาร" ของใบนี้ไปคนละเดือน — เพื่อทดสอบตัวกรองช่วงวันที่
            #    (`_DOC_DATE = COALESCE(event_at, issued_at)`)
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE finance_receipts SET event_at = $2 WHERE receipt_no = $1",
                    no, datetime(2026, 1 + i, 15, 12, 0, tzinfo=timezone.utc),
                )
    return account_id, nos


# ═══════════════════════════ 1. create: ย้ายใบจริง + idempotent
async def test_create_batch_moves_receipts_and_is_idempotent(client, db_pool, admin_headers):
    """สร้างชุด → ใบถูกผูกจริง · **กดซ้ำ** → คืนชุดเดิม ไม่สร้างแถวที่สอง"""
    room_id = admin_headers.room_id
    _, nos = await _seed_receipts(client, db_pool, admin_headers)

    res = _create_batch(client, admin_headers, nos[:2], title="ชุดผู้ปกครอง")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] is True
    batch_id = body["batch"]["id"]
    assert body["batch"]["source"] == "manual"
    assert body["batch"]["title"] == "ชุดผู้ปกครอง"
    assert body["batch"]["batch_size"] == 2
    assert body["batch"]["active_count"] == 2
    assert body["batch"]["voided_count"] == 0
    assert body["batch"]["total_amount"] == 300.0     # 100 + 200
    assert body["batch"]["created_by"] == admin_headers.user_id
    assert body["batch"]["created_by_name"] == "—"    # ไม่ได้ส่ง user_name มา

    # ── deep DB: ใบ 2 ใบแรกถูกผูก ใบที่สามไม่ถูกแตะ ──
    assert await _db_batch_id_of(db_pool, nos[0]) == batch_id
    assert await _db_batch_id_of(db_pool, nos[1]) == batch_id
    assert await _db_batch_id_of(db_pool, nos[2]) is None, (
        "ใบที่ไม่ได้ถูกเลือกต้องไม่ถูกดึงเข้าชุด"
    )

    # 🔁 กดซ้ำด้วยเซตเดิม → ต้องไม่สร้างชุดใหม่ (และไม่ error)
    again = _create_batch(client, admin_headers, nos[:2], title="ชื่ออื่นก็ไม่สร้างใหม่")
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["batch"]["id"] == batch_id, "กดซ้ำต้องได้ชุดเดิม ไม่ใช่ชุดที่สอง"

    rows = await _db_batches(db_pool, room_id)
    assert len(rows) == 1, f"กดซ้ำแล้วมีชุด {len(rows)} ชุด — idempotency ไม่ทำงาน"

    # 🔀 ลำดับที่ส่งสลับกันก็ยังต้องถือว่า "เซตเดียวกัน" (เทียบด้วย array_agg ORDER BY id)
    shuffled = _create_batch(client, admin_headers, [nos[1], nos[0]])
    assert shuffled.status_code == 200, shuffled.text
    assert shuffled.json()["created"] is False
    assert len(await _db_batches(db_pool, room_id)) == 1


async def test_create_batch_rejects_receipt_of_another_room(client, db_pool, admin_headers,
                                                           finance_manager_headers):
    """เลขที่เอกสารของห้องอื่น → 404 และ **ไม่มีแถวชุดถูกสร้าง** (ตรวจกับ DB)"""
    _, nos = await _seed_receipts(client, db_pool, admin_headers)

    # เหรัญญิกของ **อีกห้องหนึ่ง** (มี MANAGE_FINANCE จริง ⇒ ผ่านด่านสิทธิ์ แต่ต้องไม่ผ่านด่านห้อง)
    res = _create_batch(client, finance_manager_headers, nos[:2])
    assert res.status_code == 404, res.text
    assert "ไม่พบเอกสารเลขที่" in res.json()["detail"]
    assert await _db_batches(db_pool, finance_manager_headers.room_id) == [], (
        "คำขอที่ล้มต้องไม่ทิ้งแถวชุดค้างไว้"
    )
    # ⚠️ ต้องเป็น list comprehension ไม่ใช่ generator — `await` ใน genexp สร้าง
    #    async generator ที่ `all()` ใช้ไม่ได้ (ได้ TypeError ไม่ใช่ AssertionError)
    attached = [await _db_batch_id_of(db_pool, n) for n in nos[:2]]
    assert attached == [None, None], "ใบของห้องอื่นต้องไม่ถูกดึงเข้าชุดของเรา"


async def test_member_reads_but_cannot_write(client, db_pool, admin_headers,
                                             member_headers, finance_manager_headers):
    """สมาชิก **ห้องเดียวกัน** อ่านชุดได้ (200) แต่เขียนไม่ได้ (403) และไม่มีอะไรถูกเขียน

    ⚠️🔴 กับดักของเทสต์นี้: fixture สร้างห้องใหม่ให้ทุกตัว ⇒ ต้อง **ย้าย** ผู้ใช้เข้ามาใน
       ห้องของ admin ก่อน (`_join_room`) **และส่ง `room_id=` ให้ครบทุกครั้ง** เพราะ
       helper ทุกตัวปริยายเป็น `headers.room_id` ซึ่งของสมาชิกที่ถูกย้ายคือ **ห้องเดิม
       ของเขา** ไม่ใช่ห้องที่เรากำลังทดสอบ ⇒ ถ้าลืมส่ง จะกลายเป็นเทสต์คนละเรื่อง
       (403 เพราะไม่มีสิทธิ์ในห้องตัวเอง / 404 เพราะไม่มีชุดในห้องตัวเอง)
       โดยไม่มีการเตือนใด ๆ
    """
    room_id = admin_headers.room_id
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos[:2]).json()["batch"]["id"]
    await _join_room(db_pool, room_id, member_headers.user_id, student_no=97)
    await _join_room(db_pool, room_id, finance_manager_headers.user_id, student_no=98,
                     permissions='["MANAGE_FINANCE"]')

    # อ่าน: สมาชิกธรรมดาของห้องนี้ผ่าน (200) — `require_member` ไม่ต้องมีสิทธิ์ใด ๆ
    listed = _list_batches(client, member_headers, room_id=room_id)
    assert listed.status_code == 200, listed.text
    assert [b["id"] for b in listed.json()] == [batch_id], "สมาชิกต้องเห็นชุดของห้องตัวเอง"
    assert _batch_detail(client, member_headers, batch_id, room_id=room_id).status_code == 200

    # เขียน: สมาชิกธรรมดา 403 ทุกเส้นทาง
    assert _create_batch(client, member_headers, nos, room_id=room_id).status_code == 403
    assert _set_members(client, member_headers, batch_id, nos, room_id=room_id).status_code == 403
    assert _rename(client, member_headers, batch_id, room_id=room_id, title="x").status_code == 403
    assert _dissolve(client, member_headers, batch_id, room_id=room_id).status_code == 403

    # ── deep DB: ไม่มีอะไรถูกเขียนเลย ──
    row = (await _db_batches(db_pool, room_id))[0]
    assert row["deleted_at"] is None, "403 ต้องไม่ยุบชุด"
    assert row["title"] is None, "403 ต้องไม่แก้ชื่อ"
    assert await _db_batch_id_of(db_pool, nos[2]) is None, "403 ต้องไม่ย้ายใบเข้าชุด"

    # เหรัญญิก (ไม่ใช่ admin) ของ **ห้องเดียวกัน** แก้ได้ → พิสูจน์ว่า require_permission
    # ตัดสินจาก `permissions` จริง ไม่ได้ผ่านเพราะ `is_admin` bypass
    ok = _rename(client, finance_manager_headers, batch_id, room_id=room_id,
                 title="เหรัญญิกตั้งชื่อ")
    assert ok.status_code == 200, ok.text
    assert (await _db_batches(db_pool, room_id))[0]["title"] == "เหรัญญิกตั้งชื่อ"


# ═══════════════════════════ 2. set members: เพิ่ม + ถอดในคำขอเดียว
async def test_set_members_adds_and_detaches(client, db_pool, admin_headers):
    """`PUT .../receipts` = **ตั้งสมาชิกทั้งชุด** — ใบที่หายจากลิสต์ต้อง `batch_id = NULL`"""
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos).json()["batch"]["id"]

    res = _set_members(client, admin_headers, batch_id, [nos[0], nos[2]])
    assert res.status_code == 200, res.text
    assert res.json()["batch"]["batch_size"] == 2

    assert await _db_batch_id_of(db_pool, nos[0]) == batch_id
    assert await _db_batch_id_of(db_pool, nos[1]) is None, (
        "ใบที่หายจากลิสต์ต้องถูก **ถอดออก** — ไม่ใช่ค้างอยู่ในชุด"
    )
    assert await _db_batch_id_of(db_pool, nos[2]) == batch_id

    # 🔀 ใบถูกย้ายเข้าชุดใหม่ได้ — และต้องหลุดจากชุดเดิม (1 ใบอยู่ได้ชุดเดียว)
    other = _create_batch(client, admin_headers, [nos[2]]).json()["batch"]["id"]
    assert await _db_batch_id_of(db_pool, nos[2]) == other
    assert _batch_detail(client, admin_headers, batch_id).json()["batch"]["batch_size"] == 1


async def test_set_members_rejects_empty_list(client, db_pool, admin_headers):
    """ลิสต์ว่าง → 422 จาก Pydantic (`min_length=1`) — ชุดที่ไม่มีสมาชิกไม่ใช่สถานะที่มีประโยชน์"""
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos[:2]).json()["batch"]["id"]
    assert _set_members(client, admin_headers, batch_id, []).status_code == 422
    assert _batch_detail(client, admin_headers, batch_id).json()["batch"]["batch_size"] == 2


async def test_create_batch_rejects_more_than_the_pdf_ceiling(client, db_pool, admin_headers):
    """เกินเพดานต่อชุด → 400 พร้อมบอกทางออก (และไม่สร้างชุด)"""
    fake = [f"REC-2569-{i:04d}" for i in range(1, BATCH_RECEIPTS_MAX + 2)]
    res = _create_batch(client, admin_headers, fake)
    assert res.status_code == 400, res.text
    assert str(BATCH_RECEIPTS_MAX) in res.json()["detail"]
    assert await _db_batches(db_pool, admin_headers.room_id) == []


# ═══════════════════════════ 3. ยุบชุด: เอกสารต้องไม่ถูกแตะเลย
async def test_dissolve_detaches_but_never_touches_documents(client, db_pool, admin_headers):
    """ยุบชุด → ชุด soft-deleted + ใบทุกใบ `batch_id IS NULL` **แต่เอกสารยัง active ครบ**"""
    room_id = admin_headers.room_id
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos[:2]).json()["batch"]["id"]
    before = [await _db_receipt(db_pool, n) for n in nos]

    res = _dissolve(client, admin_headers, batch_id)
    assert res.status_code == 200, res.text
    assert res.json() == {"batch_id": batch_id, "detached_count": 2}

    # ── deep DB: ชุดถูกลบแบบ soft ──
    rows = await _db_batches(db_pool, room_id)
    assert len(rows) == 1 and rows[0]["deleted_at"] is not None, "ต้องเป็น soft delete"

    # ── deep DB: เอกสารไม่ถูกแตะเลย ──
    for n, old in zip(nos, before):
        now = await _db_receipt(db_pool, n)
        assert now["batch_id"] is None, f"ใบ {n} ยังค้างอยู่ในชุดที่ยุบแล้ว"
        assert now["status"] == "active", f"ยุบชุดต้องไม่ยกเลิกเอกสาร (ใบ {n})"
        assert float(now["amount"]) == float(old["amount"]), "ยอดเงินต้องไม่ถูกแตะ"
        assert now["receipt_no"] == old["receipt_no"] and now["deleted_at"] is None

    # ทะเบียนยังเห็นใบครบ 3 ใบ (2 ใบที่เคยอยู่ในชุด + 1 ใบที่ไม่เคยอยู่)
    listing = _list_receipts(client, admin_headers).json()
    assert len(listing) == 3
    assert all(r["batch_id"] is None for r in listing)

    # ชุดที่ยุบแล้วหายจากรายการ และกดซ้ำได้ 404 (ไม่ใช่ 200 เงียบ ๆ)
    assert _list_batches(client, admin_headers).json() == []
    assert _dissolve(client, admin_headers, batch_id).status_code == 404


async def test_rename_batch_and_patch_semantics(client, db_pool, admin_headers):
    """PATCH เปลี่ยนชื่อ/โน้ต — `title=null` = ล้างชื่อ · ฟิลด์ที่ไม่ส่งมาไม่ถูกแตะ"""
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos[:2]).json()["batch"]["id"]

    res = _rename(client, admin_headers, batch_id, title="ชุดใหม่", note="โน้ต")
    assert res.status_code == 200, res.text
    assert res.json()["batch"]["title"] == "ชุดใหม่"
    assert res.json()["batch"]["note"] == "โน้ต"

    # ส่งแค่ title → note ต้องคงเดิม (exclude_unset)
    res = _rename(client, admin_headers, batch_id, title=None)
    assert res.status_code == 200, res.text
    assert res.json()["batch"]["title"] is None, "`null` ที่ส่งมาชัด ๆ = ล้างชื่อ"
    assert res.json()["batch"]["note"] == "โน้ต", "ฟิลด์ที่ไม่ส่งมาต้องไม่ถูกแตะ"

    # ไม่ส่งอะไรเลย → 400 (ไม่ใช่ 200 เงียบ ๆ ที่ไม่มีอะไรเกิดขึ้น)
    assert _rename(client, admin_headers, batch_id).status_code == 400

    # 🛡️ ฟิลด์ที่ไม่อยู่ใน allowlist ต้องถูก **มองข้าม** ไม่ใช่ต่อเข้า SQL
    assert _rename(client, admin_headers, batch_id, source="auto").status_code == 400
    row = (await _db_batches(db_pool, admin_headers.room_id))[0]
    assert row["source"] == "manual", "`source` เป็นของระบบ ผู้ใช้แก้ไม่ได้"


# ═══════════════════════════ 4. 🔑 batch_size นับจากทั้งชุด ไม่ใช่จากผลกรอง
async def test_true_batch_size_survives_the_date_filter(client, db_pool, admin_headers):
    """🔑 สร้างชุด 3 ใบคนละเดือน → กรองเดือนเดียว → ได้ 1 แถว แต่ `batch_size` ต้องเป็น 3

    🧪 นี่คือเทสต์ที่จับ `COUNT(*) OVER (PARTITION BY batch_id)` ได้: window function
       นับเฉพาะแถวที่รอด `WHERE` ⇒ จะคืน 1 แทน 3 แล้วหน้าจอจะขึ้น "แสดง 1 จาก 1 ใบ"
       ทั้งที่ในชุดมี 3 ใบ — ผู้ใช้ไม่มีทางรู้ว่าขาด
    """
    _, nos = await _seed_receipts(client, db_pool, admin_headers, months_apart=True)
    batch_id = _create_batch(client, admin_headers, nos).json()["batch"]["id"]

    listing = _list_receipts(client, admin_headers,
                             extra="&start_date=2026-02-01&end_date=2026-02-28").json()
    assert len(listing) == 1, f"ตัวกรองต้องเหลือใบเดียว (ได้ {len(listing)})"
    row = listing[0]
    assert row["batch_id"] == batch_id
    assert row["batch_size"] == 3, (
        f"`batch_size` ต้องเป็นขนาดของ **ทั้งชุด** (3) ไม่ใช่จำนวนแถวที่รอดตัวกรอง "
        f"(ได้ {row['batch_size']}) — ไม่งั้นป้าย 'แสดง N จาก M ใบ' จะโกหก"
    )
    assert row["batch_voided_count"] == 0

    # ไม่กรอง → เห็นครบ 3 ใบ โดย `batch_size` เท่าเดิม
    full = _list_receipts(client, admin_headers).json()
    assert len(full) == 3
    assert {r["batch_size"] for r in full} == {3}
    assert {r["batch_id"] for r in full} == {batch_id}

    # `GET .../receipt-batches` ก็ต้องบอกขนาดจริงเท่ากัน
    batches = _list_batches(client, admin_headers).json()
    assert len(batches) == 1 and batches[0]["batch_size"] == 3
    assert batches[0]["active_count"] == 3
    assert batches[0]["first_doc_at"] is not None and batches[0]["last_doc_at"] is not None


async def test_voided_member_stays_in_the_batch_and_is_counted(client, db_pool, admin_headers):
    """ใบที่ถูกยกเลิก **ยังเป็นสมาชิกของชุด** และถูกนับใน `batch_voided_count`

    🔴 เจตนา: ชุดคือบันทึกประวัติว่า "ออกพร้อมกัน" การถอดสมาชิกออก = เขียนประวัติใหม่
       และชื่อชุด "3 ใบ" จะกลายเป็นคำโกหก ⇒ หน้าจอต้องบอกความจริงด้วยตัวนับแทน
       (`transactions.revert_transaction` จึง **ไม่ต้องแก้เลย**)
    """
    room_id = admin_headers.room_id
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos).json()["batch"]["id"]

    async def _revert(no):
        tx_id = await _db_tx_of(db_pool, no)
        assert tx_id is not None
        return client.request("DELETE", _url(TRANSACTION_PATH, room_id, tx_id=tx_id),
                              json={"user_name": "Tester"}, headers=admin_headers)

    assert (await _revert(nos[0])).status_code == 200

    voided = await _db_receipt(db_pool, nos[0])
    assert voided["status"] == "voided" and voided["deleted_at"] is not None
    assert voided["batch_id"] == batch_id, (
        "การยกเลิกรายการต้อง **ไม่** ถอดใบออกจากชุด — ถ้าถอด ชุดจะเหลือ 2 ใบ "
        "ทั้งที่ผู้ใช้เห็นชื่อ 'ชุด 3 ใบ'"
    )

    listing = _list_receipts(client, admin_headers).json()
    assert len(listing) == 2, "ทะเบียนปกติต้องไม่คืนใบที่ถูกยกเลิก"
    for r in listing:
        assert r["batch_size"] == 3, "ขนาดชุดต้องนับใบที่ถูกยกเลิกด้วย"
        assert r["batch_voided_count"] == 1

    # หน้ารายละเอียดชุดต้องเห็น **ทั้ง 3 ใบ** (รวมใบที่ถูกยกเลิก) ⇒ ตัวเลขตรงกับ voided_count
    detail = _batch_detail(client, admin_headers, batch_id).json()
    assert len(detail["receipts"]) == 3
    assert detail["batch"]["voided_count"] == 1
    assert detail["batch"]["active_count"] == 2
    # ยอดของชุดนี้ = 100 + 200 + 300 = 600 · ใบแรก (100) ถูกยกเลิก ⇒ เหลือ 500
    assert detail["batch"]["total_amount"] == 500.0, "ยอดรวมนับเฉพาะใบที่ยัง active"
    statuses = {r["receipt_no"]: r["status"] for r in detail["receipts"]}
    assert statuses[nos[0]] == "voided"
    # ใบในชุดต้องมาพร้อมข้อมูลระดับหน้ารายละเอียด (ไม่ใช่แค่ list item)
    assert "collection_title" in detail["receipts"][0]
    assert "room_name" in detail["receipts"][0]

    # ชุดที่สมาชิก active = 0 ต้องหายจากรายการชุด (กดเข้าไปแล้วว่าง = อ่านไม่ออกว่าเกิดอะไร)
    for n in nos[1:]:
        assert (await _revert(n)).status_code == 200
    assert _list_batches(client, admin_headers).json() == [], (
        "ชุดที่ไม่มีสมาชิก active เหลืออยู่ต้องไม่ถูกคืน"
    )
    # แต่ยังเปิดดูได้ตรง ๆ ด้วย id (หน้าจอที่ค้างเปิดอยู่ต้องไม่พัง)
    assert _batch_detail(client, admin_headers, batch_id).status_code == 200


# ═══════════════════════════ 5. ชุดอัตโนมัติตอนออกเอกสาร
async def test_batch_issue_creates_a_batch_automatically(client, db_pool, admin_headers):
    """ออกใบเสร็จ 2 ใบในคำสั่งเดียว → ได้ชุด `source='auto'` และใบถูกผูกครบ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    payment_ids = []
    for i in range(2):
        sid = await _make_debtor(db_pool, room_id, student_no=90 + i)
        amount = 100.0 * (i + 1)
        pid = await _make_bill(db_pool, room_id, sid, amount=amount)
        assert (await _pay(client, admin_headers, pid, account_id, amount)).status_code == 200
        payment_ids.append(pid)

    res = _issue_many(client, admin_headers, payment_ids)
    assert res.status_code == 200, res.text
    body = res.json()
    batch_id = body["batch_id"]
    assert batch_id is not None, "ออก 2 ใบในรอบเดียวต้องได้ชุดอัตโนมัติ"
    assert body["issued_count"] == 2

    rows = await _db_batches(db_pool, room_id)
    assert len(rows) == 1
    assert rows[0]["id"] == batch_id and rows[0]["source"] == "auto"
    assert rows[0]["title"] is None, (
        "ห้ามเก็บชื่อที่ประกอบแล้วลง DB — มันจะกลายเป็น snapshot ที่โกหกเมื่อมีใบถูกยกเลิก"
    )
    for r in body["receipts"]:
        assert r["batch_id"] == batch_id, "คำตอบต้องบอกชุดให้ผู้ใช้โหลดต่อได้ทันที"
        assert await _db_batch_id_of(db_pool, r["receipt_no"]) == batch_id


async def test_single_issue_creates_no_batch(client, db_pool, admin_headers):
    """ออกใบเดียว → **ไม่** สร้างชุด (ไม่มีอะไรให้ยุบ)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    sid = await _make_debtor(db_pool, room_id, student_no=90)
    pid = await _make_bill(db_pool, room_id, sid, amount=100.0)
    assert (await _pay(client, admin_headers, pid, account_id, 100.0)).status_code == 200

    body = _issue_many(client, admin_headers, [pid]).json()
    assert body["batch_id"] is None
    assert await _db_batches(db_pool, room_id) == []
    assert AUTO_BATCH_MIN == 2, "เกณฑ์ขั้นต่ำของชุดอัตโนมัติเปลี่ยนไป — เทสต์นี้ต้องถูกทบทวน"


async def test_reused_receipts_are_not_moved_into_a_new_batch(client, db_pool, admin_headers):
    """🔑 ใบที่ `reused=True` (ออกไปแล้วก่อนหน้านี้) **ไม่ถูกย้ายเข้าชุดใหม่**

    🧪 รอบที่ส่ง [ใบเก่า, ใบใหม่] มี "ใบใหม่จริง" ใบเดียว ⇒ ไม่ถึงเกณฑ์ ⇒ ไม่สร้างชุด
       และใบเก่าต้องไม่ถูกดึงเข้าชุดใด ๆ (ถ้าใครเผลอนับใบ reused เป็นสมาชิก
       ใบเก่าจะถูกย้ายเข้าชุดใหม่เงียบ ๆ และกดออกซ้ำหลายรอบจะได้ชุดใหญ่ขึ้นเรื่อย ๆ)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    old_sid = await _make_debtor(db_pool, room_id, student_no=90)
    old_pid = await _make_bill(db_pool, room_id, old_sid, amount=100.0)
    new_sid = await _make_debtor(db_pool, room_id, student_no=91)
    new_pid = await _make_bill(db_pool, room_id, new_sid, amount=200.0)
    for pid, amt in ((old_pid, 100.0), (new_pid, 200.0)):
        assert (await _pay(client, admin_headers, pid, account_id, amt)).status_code == 200

    old_no = _issue_one(client, admin_headers, old_pid).json()["receipt"]["receipt_no"]

    body = _issue_many(client, admin_headers, [old_pid, new_pid]).json()
    assert body["reused_count"] == 1 and body["issued_count"] == 1, body
    assert body["batch_id"] is None, (
        "รอบนี้มีใบใหม่จริงใบเดียว ⇒ ไม่ถึงเกณฑ์ ⇒ ต้องไม่สร้างชุด"
    )
    assert await _db_batch_id_of(db_pool, old_no) is None, (
        "ใบที่ถูก reuse ต้องไม่ถูกดึงเข้าชุดใหม่"
    )
    assert await _db_batches(db_pool, room_id) == []


async def test_room_invoice_issue_creates_a_room_batch(client, db_pool, admin_headers):
    """ออกใบแจ้งหนี้ทั้งห้อง → ชุด `source='room'` · ติ๊กเลือกรายคน → `source='auto'`"""
    room_id = admin_headers.room_id
    sids = []
    for i in range(2):
        sid = await _make_debtor(db_pool, room_id, student_no=90 + i)
        await _make_bill(db_pool, room_id, sid, amount=100.0 * (i + 1))
        sids.append(sid)

    res = client.post(_url(ROOM_INVOICES_PATH, room_id), json={}, headers=admin_headers)
    assert res.status_code == 200, res.text
    room_batch = res.json()["batch_id"]
    assert room_batch is not None, "ออกให้ทั้งห้อง 2 คนต้องได้ชุด"
    assert (await _db_batches(db_pool, room_id))[0]["source"] == "room"

    res = client.post(_url(INVOICES_PATH, room_id), json={"student_ids": sids},
                      headers=admin_headers)
    assert res.status_code == 200, res.text
    picked_batch = res.json()["batch_id"]
    assert picked_batch is not None and picked_batch != room_batch
    sources = {r["id"]: r["source"] for r in await _db_batches(db_pool, room_id)}
    assert sources == {room_batch: "room", picked_batch: "auto"}

    # ทะเบียนต้องรายงานขนาดจริงของแต่ละชุด (คนละชุด คนละใบ)
    batches = {b["id"]: b for b in _list_batches(client, admin_headers).json()}
    assert batches[room_batch]["batch_size"] == 2
    assert batches[picked_batch]["batch_size"] == 2
    doc_types = {r["doc_type"] for r in _list_receipts(client, admin_headers).json()}
    assert doc_types == {"invoice"}, "ใบแจ้งหนี้ต้องอยู่ในทะเบียนเดียวกัน (ชุดปนชนิดได้)"


# ═══════════════════════════ 6. ขอบเขตห้อง + ใบที่ไม่มีชุด
async def test_batch_is_scoped_to_the_room(client, db_pool, admin_headers,
                                           finance_manager_headers):
    """เดา `batch_id` ของห้องอื่น → 404 (ตรวจกับ DB ว่าแถวไม่ถูกแตะ)"""
    room_id = admin_headers.room_id
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    batch_id = _create_batch(client, admin_headers, nos[:2]).json()["batch"]["id"]

    assert _batch_detail(client, finance_manager_headers, batch_id).status_code == 404
    assert _set_members(client, finance_manager_headers, batch_id, nos[:2]).status_code == 404
    assert _rename(client, finance_manager_headers, batch_id, title="x").status_code == 404
    assert _dissolve(client, finance_manager_headers, batch_id).status_code == 404
    assert _list_batches(client, finance_manager_headers).json() == []

    row = (await _db_batches(db_pool, room_id))[0]
    assert row["deleted_at"] is None and row["room_id"] == room_id
    assert row["title"] is None and await _db_batch_id_of(db_pool, nos[0]) == batch_id


async def test_receipts_without_any_batch_report_null_batch_fields(client, db_pool, admin_headers):
    """ใบที่ไม่ได้อยู่ในชุด → ฟิลด์ชุดเป็น null ทั้งหมด (ไม่ใช่ 0 ที่อ่านผิดความหมาย)"""
    _, nos = await _seed_receipts(client, db_pool, admin_headers)
    listing = _list_receipts(client, admin_headers).json()
    assert len(listing) == 3
    for r in listing:
        assert r["batch_id"] is None
        assert r["batch_size"] is None
        assert r["batch_voided_count"] is None
        assert r["batch_title"] is None
