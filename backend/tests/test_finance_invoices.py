"""[F3 รอบสอง] ใบแจ้งหนี้ **ยอดค้างรวมต่อคน** + PDF รวมหลายใบในไฟล์เดียว

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร (เรียงตามความสำคัญ)
═══════════════════════════════════════════════════════════════════════════════
1. **ยอดบนใบ = ยอดที่หน้าลูกหนี้โชว์** — predicate ของ `_load_student_outstanding`
   ต้องเหมือน `get_all_debtors` เป๊ะ ถ้าหลุดจากกันเมื่อไร ครูเถียงกับผู้ปกครองไม่ได้
   ⇒ เทสต์เทียบสองตัวเลขนี้ตรง ๆ ไม่ใช่เทียบกับค่าที่ hardcode ไว้

2. **ตารางโครงการเป็น snapshot** — พิมพ์ซ้ำหลังนักเรียนจ่ายบางส่วน ต้องได้บรรทัดชุดเดิม
   ไม่ใช่คำนวณใหม่จากยอดปัจจุบัน (ไม่งั้นผลรวมบรรทัดจะไม่เท่ายอดพาดหัว = เอกสาร
   ขัดแย้งตัวเอง ซึ่งเป็นความผิดพลาดที่ผู้ตรวจสอบภายนอกจับได้ทันที)

3. **1 คน = 1 ใบ** — `student_payment_id`/`collection_id` ต้องเป็น NULL
   ถ้ามีค่าแปลว่ายังใช้เส้นทาง "ใบละบิล" ที่ถูกแทนที่ไปแล้ว

4. **ทั้งห้อง = ออกจริงทุกคน** — กินเลข INV จริงและเขียนแถวจริง (ไม่ใช่ PDF ลอย ๆ)
   และคนที่ยอดปัดเป็นสตางค์แล้วเหลือ 0 ต้องถูก **ข้ามแล้วรายงาน** ไม่ใช่ทำให้ทั้งห้องล้ม

5. **PDF รวม = ไฟล์เดียว หน้าละใบ** — เรนเดอร์ครั้งเดียว, ฟอนต์ฝังครั้งเดียว (ไม่บวมตาม N)

⚠️ ทุกเทสต์ยืนยันกับ DB จริงผ่าน `db_pool` ไม่เชื่อแค่ HTTP status (กฎ docs/rules/testing.md)
"""
import random
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from services.finance.constants import (
    BUDDHIST_ERA_OFFSET, RECEIPTS_PER_PDF_MAX, THAI_TZ,
)

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices"
ROOM_INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices/room"
COMBINED_PDF_PATH = API_PREFIX + "/{room}/finance/receipts/pdf"
RECEIPT_PATH = API_PREFIX + "/{room}/finance/receipts/{receipt_no}"
RECEIPTS_PATH = API_PREFIX + "/{room}/finance/receipts"
DEBTORS_PATH = API_PREFIX + "/{room}/finance/debtors"


def _url(template: str, room_id: int, **kwargs) -> str:
    """สร้าง URL ของ finance API — web ต้องส่ง `target_type=room` เสมอ (default คือ server)"""
    return template.format(room=room_id, **kwargs) + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _make_debtor(pool, room_id: int, *, student_no: int = 90,
                       first_name: str = "เด็กชายทดสอบ") -> int:
    """สร้าง user + students row สำหรับเป็น "ผู้ชำระเงิน" (คนละคนกับผู้ออกเอกสาร)"""
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


async def _make_bill(pool, room_id: int, student_id: int, *,
                     title: str = "ค่าเทอม", amount: float = 1000.0,
                     due_date: date = date(2026, 12, 31)) -> int:
    """สร้าง fee_collections + student_payments (บิลตั้งต้นที่ยัง `pending`) → collection_id

    ⚠️ ตั้ง `status='pending'` และ `paid_amount=0` **เสมอ** — ถ้าต้องการ "จ่ายบางส่วน"
       ต้องผ่าน `_pay` (เส้นทางจริง) เพราะการยัด `paid_amount` ตรง ๆ โดยไม่แก้ status
       จะสร้างสภาพที่ใบแจ้งหนี้มองไม่เห็นบิลนั้น (predicate คือ `SP.status='pending'`)
    """
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, title, amount, due_date,
        )
        await conn.execute(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0)""",
            collection_id, student_id,
        )
    return collection_id


async def _insert_account(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, "กระเป๋ากลาง",
        )


# ═══════════════════════════════════════════════════════════════════ HTTP helpers
def _pay(client, headers, payment_id: int, account_id: int, amount: float):
    """จ่ายผ่านเส้นทางเงินจริง — ทำให้ได้สถานะ "ทยอยจ่าย" (`status` ยังเป็น pending)"""
    return client.put(
        _url(API_PREFIX + "/{room}/finance/payments/{payment_id}/pay", headers.room_id,
             payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )


# ⚠️ สี่ตัวล่างนี้รับ `room_id` แยกจาก `headers` ได้ เพราะบางเทสต์ใช้ headers ที่ **ไม่ใช่**
#    `admin_headers` (เช่น `_member_headers_in` ที่คืน `dict` เปล่า ไม่มี `.room_id`)
#    ⇒ ถ้าบังคับอ่าน `headers.room_id` เทสต์พวกนั้นจะพังด้วย `AttributeError` ไม่ใช่ผลของ API
def _issue_invoices(client, headers, student_ids, room_id=None):
    return client.post(
        _url(INVOICES_PATH, room_id if room_id is not None else headers.room_id),
        json={"student_ids": student_ids}, headers=headers,
    )


def _issue_room_invoices(client, headers, room_id=None):
    return client.post(
        _url(ROOM_INVOICES_PATH, room_id if room_id is not None else headers.room_id),
        json={}, headers=headers,
    )


def _combined_pdf(client, headers, receipt_nos, room_id=None):
    return client.post(
        _url(COMBINED_PDF_PATH, room_id if room_id is not None else headers.room_id),
        json={"receipt_nos": receipt_nos}, headers=headers,
    )


async def _make_other_room(pool, user_id: int) -> int:
    """ห้องที่สองที่ user คนเดิมเป็นแอดมิน — ให้ผ่าน RBAC แล้วไปตกที่ด่านของ service"""
    async with pool.acquire() as conn:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
            "ห้องที่สอง", f"R{uuid.uuid4().hex[:6].upper()}", user_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 0, 'president', 'active', TRUE, '[]'::jsonb)""",
            room_id, user_id,
        )
    return room_id


async def _member_headers_in(pool, room_id: int) -> dict:
    """สร้างสมาชิกธรรมดา **ในห้องที่ระบุ** แล้วคืน headers ที่ยิง API ได้

    🎯 ต้องสร้างเองในห้องนี้ (ใช้ `member_headers` fixture ไม่ได้ — ห้องนั้นเป็นห้องอื่น)
       เพราะเทสต์ "สมาชิกอ่าน PDF รวมได้" ต้องมีเอกสารจริงอยู่ในห้องเดียวกับสมาชิกคนนั้น
    """
    from core.config import settings

    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ('สมาชิก', 'อ่านได้', $1, $2) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 50, 'student', 'active', FALSE, '[]'::jsonb)""",
            room_id, user_id,
        )
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


async def _payment_id_of(pool, collection_id: int, student_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM student_payments WHERE collection_id = $1 AND student_id = $2",
            collection_id, student_id,
        )


async def _db_rows(pool, room_id: int, *, doc_type: str = "invoice") -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, receipt_no, doc_type, year_be, seq, student_payment_id,
                      legacy_transaction_id, student_id, collection_id, amount,
                      paid_total_after, line_items, event_at, issued_at, deleted_at
               FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2 ORDER BY id""",
            room_id, doc_type,
        )
        return [dict(r) for r in rows]


async def _db_count(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room_id,
        )


async def _db_seq(pool, room_id: int, doc_type: str = "invoice"):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT last_seq FROM receipt_sequences WHERE room_id = $1 AND doc_type = $2",
            room_id, doc_type,
        )


# ═════════════════════════ 1. 🎯 ความเท่ากันของยอด (สำคัญที่สุดในไฟล์นี้)
async def test_invoice_amount_equals_the_debtor_page_amount(client, db_pool, admin_headers):
    """ยอดบนใบแจ้งหนี้ต้อง **เท่ากับ** `total_pending_amount` ที่หน้าลูกหนี้โชว์เป๊ะ

    🎯 นี่คือเทสต์ที่กัน "predicate drift" — วันที่ `_load_student_outstanding` กับ
       `get_all_debtors` กรองต่างกัน (เช่นมีคนเติม `FC.status='active'` หรือ
       `SP.deleted_at IS NULL` เข้าข้างเดียว) ตัวเลขสองที่จะเงียบ ๆ ต่างกัน
       แล้วครูจะยืนยันยอดกับผู้ปกครองไม่ได้

    ⚠️ เทสต์นี้ **ไม่** hardcode ยอดที่คาดไว้โดยเจตนา — เปรียบเทียบสองแหล่งของจริง
       ⇒ ถ้าวันหนึ่ง business rule เปลี่ยน ยอดจะเปลี่ยนทั้งคู่พร้อมกันและเทสต์ยังมีความหมาย
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)

    # 3 บิลค้าง + จ่ายบางส่วนไป 1 บิล ⇒ ยอดค้างไม่เท่าผลรวมยอดบิลดิบ
    c1 = await _make_bill(db_pool, room_id, student_id, title="ค่าเทอม", amount=1200.0)
    await _make_bill(db_pool, room_id, student_id, title="ค่าอาหารกลางวัน", amount=850.5)
    await _make_bill(db_pool, room_id, student_id, title="ค่าทัศนศึกษา", amount=430.25)
    assert _pay(client, admin_headers, await _payment_id_of(db_pool, c1, student_id),
                account_id, 200.0).status_code == 200

    debtors = client.get(_url(DEBTORS_PATH, room_id), headers=admin_headers)
    assert debtors.status_code == 200, debtors.text
    row = next(d for d in debtors.json() if d["student_id"] == student_id)
    assert row["overdue_count"] == 3

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    doc = res.json()["receipts"][0]

    assert doc["amount"] == pytest.approx(row["total_pending_amount"], abs=0.005), (
        f"ยอดบนใบ ({doc['amount']}) ไม่เท่ากับที่หน้าลูกหนี้โชว์ "
        f"({row['total_pending_amount']}) — predicate สองที่หลุดจากกันแล้ว"
    )
    # 2280.75 = 1200 + 850.5 + 430.25 - 200 ⇒ ยืนยันว่าเทสต์ไม่ได้เทียบ 0 กับ 0
    assert doc["amount"] == pytest.approx(2280.75, abs=0.005)


# ═════════════════════════════════════════════ 2. 📋 snapshot ของตารางโครงการ
async def test_line_items_are_a_snapshot_not_recomputed_at_print_time(
    client, db_pool, admin_headers
):
    """จ่ายเพิ่มหลังออกใบ ⇒ ใบเดิมต้องยังแสดงรายการชุดเดิมและผลรวมเท่าเดิม

    🎯 เอกสารที่ออกให้ผู้ปกครองไปแล้วเป็น **หลักฐาน ณ จุดเวลา** — ถ้าตอนพิมพ์กลับไป
       คำนวณใหม่ ใบที่พิมพ์ซ้ำจะมียอดบรรทัดรวมไม่เท่ายอดพาดหัวที่เก็บไว้
       = เอกสารขัดแย้งตัวเอง ซึ่งเป็นสิ่งที่ตรวจสอบย้อนหลังไม่ได้
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    # ⚠️ ต้องมี `due_date` ต่างกัน — `_load_student_outstanding` เรียงด้วย
    #    `FC.status ASC, FC.due_date ASC` ⇒ วันเดียวกันจะเสมอกันและลำดับไม่ถูกรับประกัน
    #    (เทสต์ที่ assert ลำดับจะกลายเป็นเทสต์ที่ผ่านบ้างไม่ผ่านบ้าง)
    c1 = await _make_bill(db_pool, room_id, student_id, title="ค่าเทอม", amount=1000.0,
                          due_date=date(2026, 1, 31))
    await _make_bill(db_pool, room_id, student_id, title="ค่าอาหาร", amount=500.0,
                     due_date=date(2026, 2, 28))

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    issued = res.json()["receipts"][0]
    receipt_no = issued["receipt_no"]
    assert issued["amount"] == pytest.approx(1500.0)

    # จ่ายเพิ่ม 600 หลังจากใบออกไปแล้ว
    assert _pay(client, admin_headers, await _payment_id_of(db_pool, c1, student_id),
                account_id, 600.0).status_code == 200

    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                        headers=admin_headers)
    assert detail.status_code == 200, detail.text
    d = detail.json()

    titles = [it["title"] for it in d["line_items"]]
    assert titles == ["ค่าเทอม", "ค่าอาหาร"], "ลำดับต้องคงที่ตาม snapshot"
    assert sum(it["amount"] for it in d["line_items"]) == pytest.approx(d["amount"]), (
        "ผลรวมของบรรทัดต้องเท่ากับยอดพาดหัวเสมอ — ทั้งคู่มาจาก snapshot ก้อนเดียวกัน"
    )
    assert d["amount"] == pytest.approx(1500.0), "ยอดพาดหัวต้องไม่ขยับตามการจ่ายทีหลัง"
    assert [it["amount"] for it in d["line_items"]] == [1000.0, 500.0]


async def test_line_items_survive_the_jsonb_round_trip(client, db_pool, admin_headers):
    """`line_items` ต้องกลับมาเป็น **list ของ dict** ไม่ใช่ `str` หรือ dict ก้อนเดียว

    🔴 asyncpg ไม่มี JSONB codec ที่ไหนในโปรเจกต์ ⇒ ค่าดิบคือ `str` ที่ต้อง `json.loads`
       ถ้าลืม: หน้า detail จะได้ ValidationError ของ Pydantic = **500** และหน้า PDF
       จะเรียก `.get()` บนสตริงไม่ได้ = **500** เช่นกัน (คนละที่ คนละสาเหตุ)
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, title="ค่าเทอม", amount=100.0,
                     due_date=date(2026, 12, 31))
    await _make_bill(db_pool, room_id, student_id, title="ค่าประกัน", amount=250.0,
                     due_date=date(2026, 6, 30))

    assert _issue_invoices(client, admin_headers, [student_id]).status_code == 200

    # 1) ชั้น DB: ของจริงเก็บเป็น jsonb (ไม่ใช่ text) และเป็น array
    async with db_pool.acquire() as conn:
        kind = await conn.fetchval(
            "SELECT jsonb_typeof(line_items) FROM finance_receipts WHERE room_id = $1",
            room_id,
        )
    assert kind == "array"

    # 2) ชั้น API: ต้องถูก parse เป็นลิสต์ของ dict แล้ว
    rows = client.get(_url(RECEIPTS_PATH, room_id),
                      params={"doc_type": "invoice"}, headers=admin_headers).json()
    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=rows[0]["receipt_no"]),
                        headers=admin_headers)
    assert detail.status_code == 200, detail.text
    items = detail.json()["line_items"]
    assert isinstance(items, list), f"ได้ {type(items).__name__} แทน list"
    assert all(isinstance(it, dict) for it in items), items
    assert set(items[0]) == {"title", "amount", "due_date"}
    # ISO ของ DATE ต้อง round-trip ตรง (ไม่กลายเป็น timestamp มีเวลา 00:00:00)
    # และเรียงตามกำหนดชำระจากน้อยไปมาก (`FC.status ASC, FC.due_date ASC`)
    assert [it["due_date"] for it in items] == ["2026-06-30", "2026-12-31"]


# ═══════════════════════════════════════════════════ 3. ✍️ 1 คน = 1 ใบ
async def test_three_bills_become_one_invoice_with_no_bill_reference(
    client, db_pool, admin_headers
):
    """นักเรียน 3 บิลค้าง → ออกครั้งเดียวได้ **1 ใบ** และไม่ผูกกับบิล/แคมเปญใดเลย"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, title="บิล 1", amount=100.0)
    await _make_bill(db_pool, room_id, student_id, title="บิล 2", amount=200.0)
    await _make_bill(db_pool, room_id, student_id, title="บิล 3", amount=300.0)

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    assert res.json()["issued_count"] == 1
    assert res.json()["skipped"] == []

    rows = await _db_rows(db_pool, room_id)
    assert len(rows) == 1, "1 คนต้องได้ 1 ใบ ไม่ใช่ใบละบิล"
    row = rows[0]
    assert row["student_id"] == student_id
    # 🔴 NULL ทั้งสามตัวคือ **สัญญา** ของใบรวมยอด
    assert row["student_payment_id"] is None, "ใบรวมไม่ผูกกับบิลเดียว"
    assert row["collection_id"] is None, "ใบรวมไม่ผูกกับแคมเปญเดียว"
    assert row["legacy_transaction_id"] is None
    assert float(row["amount"]) == pytest.approx(600.0)
    assert row["seq"] == 1
    assert await _db_seq(db_pool, room_id) == 1


async def test_duplicate_student_ids_produce_one_invoice(client, db_pool, admin_headers):
    """ส่ง `student_id` ซ้ำมา (checkbox เพี้ยน) ต้องได้ใบเดียว ไม่ใช่สองใบคนละเลข"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=400.0)

    res = _issue_invoices(client, admin_headers, [student_id, student_id, student_id])
    assert res.status_code == 200, res.text
    assert res.json()["issued_count"] == 1
    assert len(await _db_rows(db_pool, room_id)) == 1
    assert await _db_seq(db_pool, room_id) == 1, "ต้องไม่กินเลขเกินหนึ่ง"


async def test_invoices_do_not_touch_the_receipt_counter(client, db_pool, admin_headers):
    """ตัวนับ `receipt` ต้องไม่ถูกแตะเลยโดยการออกใบแจ้งหนี้ (คนละชุดเลขกัน)"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=500.0)

    assert _issue_invoices(client, admin_headers, [student_id]).status_code == 200
    assert await _db_seq(db_pool, room_id, "invoice") == 1
    assert await _db_seq(db_pool, room_id, "receipt") is None


# ══════════════════════════════════════ 4. 🏫 ออกทั้งห้อง (room-wide)
async def test_room_wide_issues_for_every_debtor(client, db_pool, admin_headers):
    """ทั้งห้อง: 3 คนค้าง + 1 คนไม่เคยมีบิล → 3 ใบ และคนไม่มีบิลไม่ถูกพูดถึงเลย"""
    room_id = admin_headers.room_id
    debtors = [
        await _make_debtor(db_pool, room_id, student_no=90 + i, first_name=f"ลูกหนี้{i}")
        for i in range(3)
    ]
    for i, sid in enumerate(debtors):
        await _make_bill(db_pool, room_id, sid, title=f"บิลของคนที่ {i}", amount=100.0 * (i + 1))

    # คนที่ไม่เคยมีบิลเลย — ต้องไม่ปรากฏใน `skipped` ด้วย (ไม่ใช่ "ถูกข้าม" แต่ "ไม่มีอะไรค้าง")
    await _make_debtor(db_pool, room_id, student_no=99, first_name="ไม่มีบิล")

    res = _issue_room_invoices(client, admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["issued_count"] == 3
    assert body["skipped"] == []
    assert {r["student_id"] for r in body["receipts"]} == set(debtors)
    assert [r["amount"] for r in body["receipts"]] == [100.0, 200.0, 300.0]

    # 🧾 เป็นการเขียนจริง ไม่ใช่ PDF ลอย ๆ — มีทั้งแถวและเลขที่ถูกกิน
    assert len(await _db_rows(db_pool, room_id)) == 3
    assert await _db_seq(db_pool, room_id) == 3
    assert all(r["student_payment_id"] is None for r in await _db_rows(db_pool, room_id))


async def test_room_wide_skips_a_zero_outstanding_bill_and_reports_it(
    client, db_pool, admin_headers
):
    """บิลที่ `status='pending'` แต่จ่ายครบแล้ว → **ข้ามแล้วรายงาน** ไม่ใช่ทำให้ทั้งห้องล้ม

    🎯 สภาพนี้เกิดได้จริง (แก้ `paid_amount` ด้วยมือ / ข้อมูลนำเข้า) และมันเป็นเหตุผลที่
       เส้นทางทั้งห้องใช้ "ข้าม" แทน "raise": ผู้ใช้ไม่ได้เลือกคนนี้ และไม่มีอะไรให้เขาแก้
       ⇒ ถ้า raise ทั้งห้องจะล้มเพราะคนที่ผู้ใช้ไม่รู้จัก

    🔴 และต้อง **รายงาน** ให้เห็น — ถ้า `skipped` ถูกตัดทิ้งจาก response_model
       ผู้ใช้จะเห็น "ออก 2 ฉบับ" โดยไม่รู้ว่าทำไมไม่ครบทุกคน
    """
    room_id = admin_headers.room_id
    ok_a = await _make_debtor(db_pool, room_id, student_no=90, first_name="ค้างจริง A")
    ok_b = await _make_debtor(db_pool, room_id, student_no=91, first_name="ค้างจริง B")
    zero = await _make_debtor(db_pool, room_id, student_no=92, first_name="จ่ายครบแต่ยัง pending")
    await _make_bill(db_pool, room_id, ok_a, amount=100.0)
    await _make_bill(db_pool, room_id, ok_b, amount=200.0)

    # บิลที่ "จ่ายครบ" แต่ยัง pending — ยัดตรง ๆ เพราะเส้นทางรับเงินจะตั้ง status='paid'
    c_zero = await _make_bill(db_pool, room_id, zero, amount=300.0)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET paid_amount = 300.0 WHERE collection_id = $1",
            c_zero,
        )

    res = _issue_room_invoices(client, admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["issued_count"] == 2, "คนที่ยอดเหลือ 0 ต้องไม่ได้รับใบ"
    assert [s["student_id"] for s in body["skipped"]] == [zero]
    assert body["skipped"][0]["student_name"] == "จ่ายครบแต่ยัง pending"
    assert "0.01" in body["skipped"][0]["reason"] or "สตางค์" in body["skipped"][0]["reason"]

    assert await _db_seq(db_pool, room_id) == 2, "ต้องไม่กินเลขให้คนที่ถูกข้าม"
    assert {r["student_id"] for r in await _db_rows(db_pool, room_id)} == {ok_a, ok_b}


async def test_room_wide_with_no_debtors_writes_nothing(client, db_pool, admin_headers):
    """ห้องที่ไม่มีใครค้าง → 200 พร้อมข้อความที่อ่านรู้เรื่อง และ **ไม่กินเลข**"""
    res = _issue_room_invoices(client, admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["issued_count"] == 0
    assert "ไม่มีนักเรียนที่มียอดค้างชำระ" in res.json()["message"]
    assert await _db_count(db_pool, admin_headers.room_id) == 0
    assert await _db_seq(db_pool, admin_headers.room_id) is None


# ═══════════════════════════════════════════ 5. 🧱 all-or-nothing + ด่านยอด
async def test_one_bad_student_aborts_the_whole_batch_and_writes_nothing(
    client, db_pool, admin_headers
):
    """มีคนเดียวที่ออกไม่ได้ → **ไม่มีใครได้ใบเลย** และเลขต้องไม่ถูกกินแม้แต่เลขเดียว

    🎯 ใบแจ้งหนี้เป็น point-in-time ⇒ "กดซ้ำ" ไม่ปลอดภัย ถ้าสำเร็จไป 3 จาก 5 คน
       ผู้ใช้ไม่มีทางกู้นอกจากกดใหม่ แล้วจะได้ใบชุดใหม่ของ 3 คนแรกทับกับชุดเดิม
       = ทะเบียนมีเอกสารซ้ำยอดเดียวกันคนละเลข
    """
    room_id = admin_headers.room_id
    good = await _make_debtor(db_pool, room_id, student_no=90, first_name="ออกได้")
    await _make_bill(db_pool, room_id, good, amount=100.0)
    # คนที่สอง: ไม่มีบิลค้างเลย ⇒ `_issue_invoice_aggregate` โยน ValueError
    empty = await _make_debtor(db_pool, room_id, student_no=91, first_name="ไม่มีอะไรค้าง")

    res = _issue_invoices(client, admin_headers, [good, empty])
    assert res.status_code == 400, res.text
    assert await _db_count(db_pool, room_id) == 0, "ต้องไม่เหลือแถวของคนแรกที่ออกสำเร็จ"
    assert await _db_seq(db_pool, room_id) is None, "transaction ต้อง rollback เลขด้วย"


async def test_unknown_or_foreign_student_id_is_404_and_writes_nothing(
    client, db_pool, admin_headers
):
    """คนที่ไม่มีในห้องนี้ → **404** (ไม่ใช่ 400 และไม่ใช่ 403) และไม่ทิ้งร่องรอยใด ๆ

    🎯 404 โดยเจตนา: 403 จะแปลว่า "มีคนนี้อยู่จริงแต่เธอไม่มีสิทธิ์" ซึ่งยืนยันการมีอยู่
       ของ `student_id` ให้คนที่เดาเลขได้ — หลักเดียวกับ `_load_payment` ของใบเสร็จ
    ⚠️ ทั้ง "ไม่มี id นี้ในระบบเลย" และ "มีแต่เป็นของห้องอื่น" ตกที่สาขาเดียวกัน
       ⇒ ทดสอบทั้งคู่เพื่อยืนยันว่ามันแยกไม่ออกจากกันจริง
    """
    room_id = admin_headers.room_id
    other_room = await _make_other_room(db_pool, admin_headers.user_id)
    other_student = await _make_debtor(db_pool, other_room)
    await _make_bill(db_pool, other_room, other_student, amount=100.0)

    for bogus in (123456789, other_student):
        res = _issue_invoices(client, admin_headers, [bogus])
        assert res.status_code == 404, f"{bogus}: {res.text}"
        assert await _db_count(db_pool, room_id) == 0
        assert await _db_count(db_pool, other_room) == 0, "ห้ามออกเอกสารให้ห้องอื่น"
        assert await _db_seq(db_pool, room_id) is None
        assert await _db_seq(db_pool, other_room) is None


@pytest.mark.parametrize(
    "bill_amount, expected_status",
    [
        # 0.004 → ปัดเป็นสตางค์แล้วเหลือ 0.00 ⇒ ต้อง 400 และ **ไม่กินเลข**
        (0.004, 400),
        # 0.005 → ปัดขึ้นเป็น 0.01 ⇒ ออกได้จริง (ขอบบนของด่าน — บันทึกไว้ให้เห็นว่าด่านอยู่ตรงไหน)
        (0.005, 200),
    ],
)
async def test_sub_satang_boundary_is_decided_after_rounding(
    client, db_pool, admin_headers, bill_amount, expected_status,
):
    """ด่านยอดต้องตัดสินที่ **ค่าหลังปัดเป็นสตางค์** ไม่ใช่ค่าดิบ

    🎯 `chk_receipt_amount_positive (amount > 0)` เป็น CHECK ของ DB ⇒ ถ้าปล่อยผ่านไป
       asyncpg โยน `CheckViolationError` ซึ่งไม่มีชั้นไหนแปลงเป็น HTTP = **500**
       ผู้ใช้เห็น "ระบบพัง" ทั้งที่ปัญหาคือยอด
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=bill_amount)

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == expected_status, res.text

    if expected_status == 400:
        detail = str(res.json())
        assert "0.01" in detail or "สตางค์" in detail
        assert await _db_count(db_pool, room_id) == 0
        assert await _db_seq(db_pool, room_id) is None, "ต้องไม่จองเลขก่อนตรวจยอด"
    else:
        assert res.json()["receipts"][0]["amount"] == pytest.approx(0.01)


# ══════════════════════════════════════════════════ 6. 🛡️ RBAC
async def test_member_cannot_issue_invoices_and_writes_nothing(
    client, db_pool, member_headers
):
    """สมาชิกธรรมดา → 403 ทั้งสองเส้นทาง และ DB ต้องไม่มีร่องรอยใด ๆ"""
    room_id = member_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=1000.0)

    assert _issue_invoices(client, member_headers, [student_id]).status_code == 403
    assert _issue_room_invoices(client, member_headers).status_code == 403

    assert await _db_count(db_pool, room_id) == 0, "403 ต้องไม่ทิ้งแถวไว้"
    assert await _db_seq(db_pool, room_id) is None, "403 ต้องไม่กินเลข"


async def test_finance_manager_can_issue_without_being_admin(
    client, db_pool, finance_manager_headers
):
    """เหรัญญิก (`MANAGE_FINANCE`, `is_admin=FALSE`) ต้องออกได้จริง — ไม่ได้ผ่านเพราะ bypass"""
    room_id = finance_manager_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=750.0)

    res = _issue_invoices(client, finance_manager_headers, [student_id])
    assert res.status_code == 200, res.text
    assert res.json()["receipts"][0]["amount"] == pytest.approx(750.0)
    assert len(await _db_rows(db_pool, room_id)) == 1


async def test_member_can_read_the_combined_pdf(client, db_pool, admin_headers):
    """PDF รวมเปิดให้สมาชิกทุกคนอ่าน (ตรงกับ `require_member`) แต่ต้องมีใบจริงก่อน"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100.0)
    receipt_no = _issue_invoices(
        client, admin_headers, [student_id]
    ).json()["receipts"][0]["receipt_no"]

    member = await _member_headers_in(db_pool, room_id)
    # 🔓 พิมพ์เอกสารที่มีอยู่แล้ว = การอ่าน (เหมือน PDF ใบเดียว) — สมาชิกอ่านได้
    assert client.get(_url(RECEIPTS_PATH, room_id), headers=member).status_code == 200

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n% fake\n%%EOF\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = _combined_pdf(client, member, [receipt_no], room_id)
    assert res.status_code == 200, res.text
    assert mock_render.await_count == 1

    # ⚠️ แต่การ **เขียน** ยังต้องมี MANAGE_FINANCE — สิทธิ์อ่านไม่ลามไปถึงการออกเอกสาร
    assert _issue_invoices(client, member, [student_id], room_id).status_code == 403
    assert _issue_room_invoices(client, member, room_id).status_code == 403


# ══════════════════════════════════════════ 7. 🖨️ PDF รวมหลายใบในไฟล์เดียว
async def test_combined_pdf_renders_once_with_one_page_per_document(
    client, db_pool, admin_headers
):
    """3 ใบ → เรนเดอร์ **ครั้งเดียว**, มี 3 `.doc` และ 2 ตัวแบ่งหน้า, ฟอนต์ฝัง **2** (ไม่ใช่ 6)

    🎯 `await_count == 1` คือหัวใจ: ถ้าเรนเดอร์ทีละใบแล้วค่อยรวมไฟล์ จะได้ PDF 3 ไฟล์
       ที่ไม่ใช่ "ไฟล์เดียว หน้าละใบ" และกินเวลา Chromium เป็น 3 เท่า
    🎯 จำนวนฟอนต์ต้องคงที่ตาม **น้ำหนัก** ไม่ใช่ตามจำนวนใบ — `<style>` อยู่นอกลูป
       ถ้าเผลอย้ายเข้าไป ไฟล์จะบวมเป็น N เท่า (ฟอนต์ละ ~61,000 ตัวอักษร)
    """
    room_id = admin_headers.room_id
    nos = []
    for i in range(3):
        sid = await _make_debtor(db_pool, room_id, student_no=90 + i, first_name=f"คนที่ {i}")
        await _make_bill(db_pool, room_id, sid, amount=100.0 * (i + 1))
        nos.append(_issue_invoices(
            client, admin_headers, [sid]
        ).json()["receipts"][0]["receipt_no"])

    fake_pdf = b"%PDF-1.4\n% fake\n%%EOF\n"
    mock_render = AsyncMock(return_value=fake_pdf)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = _combined_pdf(client, admin_headers, nos)

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == fake_pdf
    assert res.headers["content-length"] == str(len(fake_pdf))
    # 🏷️ ชื่อไฟล์บอก "ช่วงเลขที่" ไม่ใช่วันที่ — ให้ตรงกับเลขบนเอกสารข้างใน
    assert f"invoices-{nos[0]}-to-{nos[-1]}.pdf" in res.headers["content-disposition"]

    assert mock_render.await_count == 1, "ต้องเรนเดอร์ครั้งเดียวสำหรับทั้งไฟล์"
    html = mock_render.await_args.args[0]
    assert html.count('class="doc"') + html.count('class="doc doc-break"') == 3
    assert html.count('class="doc doc-break"') == 2, "ตัวแบ่งหน้าต้องอยู่ระหว่างใบ ไม่ใช่หลังใบสุดท้าย"
    assert html.count("data:font/ttf;base64,") == 2, "ฟอนต์ฝังครั้งเดียว ไม่บวมตามจำนวนใบ"
    # ลำดับในไฟล์ต้องตามลำดับที่ขอ — ไม่งั้นใบของคนหนึ่งไปโผล่ผิดที่
    assert html.index(nos[0]) < html.index(nos[1]) < html.index(nos[2])
    assert "{{" not in html and "{%" not in html


async def test_combined_pdf_keeps_the_requested_order_not_the_db_order(
    client, db_pool, admin_headers
):
    """ส่งเลขที่กลับลำดับ → ไฟล์ต้องเรียงตามที่ขอ (ผู้ใช้เลือกเองว่าใครก่อนใคร)"""
    room_id = admin_headers.room_id
    nos = []
    for i in range(2):
        sid = await _make_debtor(db_pool, room_id, student_no=90 + i)
        await _make_bill(db_pool, room_id, sid, amount=100.0)
        nos.append(_issue_invoices(
            client, admin_headers, [sid]
        ).json()["receipts"][0]["receipt_no"])

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = _combined_pdf(client, admin_headers, list(reversed(nos)))
    assert res.status_code == 200, res.text

    html = mock_render.await_args.args[0]
    assert html.index(nos[1]) < html.index(nos[0])
    assert f"invoices-{nos[1]}-to-{nos[0]}.pdf" in res.headers["content-disposition"]


async def test_combined_pdf_mixes_receipts_and_invoices_under_a_neutral_name(
    client, db_pool, admin_headers
):
    """ชุดที่มีทั้งใบเสร็จและใบแจ้งหนี้ → ชื่อไฟล์ต้องไม่แอบอ้างว่าเป็นชนิดใดชนิดหนึ่ง"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    sid_a = await _make_debtor(db_pool, room_id, student_no=90)
    sid_b = await _make_debtor(db_pool, room_id, student_no=91)
    c_a = await _make_bill(db_pool, room_id, sid_a, amount=300.0)
    await _make_bill(db_pool, room_id, sid_b, amount=400.0)
    assert _pay(client, admin_headers, await _payment_id_of(db_pool, c_a, sid_a),
                account_id, 300.0).status_code == 200

    rec = client.post(_url(RECEIPTS_PATH, room_id),
                      json={"payment_id": await _payment_id_of(db_pool, c_a, sid_a)},
                      headers=admin_headers).json()["receipt"]["receipt_no"]
    inv = _issue_invoices(
        client, admin_headers, [sid_b]
    ).json()["receipts"][0]["receipt_no"]

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = _combined_pdf(client, admin_headers, [rec, inv])
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "documents-" in disposition, disposition
    assert "receipts-" not in disposition and "invoices-" not in disposition


async def test_combined_pdf_unknown_number_is_404_not_a_missing_page(
    client, db_pool, admin_headers
):
    """มีเลขที่ขอมาแต่ไม่มีในห้อง → 404 ทั้งชุด **ไม่ใช่** ข้ามเงียบ ๆ

    🎯 ไฟล์ที่ขาดหน้าโดยไม่มีสัญญาณจะดูเหมือน "พิมพ์ครบ" — ครูแจกเอกสารไม่ครบโดยไม่รู้
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100.0)
    real = _issue_invoices(
        client, admin_headers, [student_id]
    ).json()["receipts"][0]["receipt_no"]

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = _combined_pdf(client, admin_headers, [real, "INV-2569-0099"])
    assert res.status_code == 404, res.text
    assert mock_render.await_count == 0, "ต้องไม่เรนเดอร์ไฟล์ที่ขาดหน้า"


async def test_combined_pdf_over_the_cap_is_400_with_a_thai_explanation(
    client, db_pool, admin_headers
):
    """เกินเพดาน → 400 พร้อมข้อความไทยที่บอกทางออก (ไม่ใช่ 422 ดิบของ Pydantic)

    ⚠️ `ReceiptCombinedPdfRequest` **ไม่มี** `max_length` โดยเจตนา: 422 ของ Pydantic
       ถูก reformat เป็นข้อความ generic ที่ไม่ได้บอกว่าต้องทำอะไรต่อ
    """
    room_id = admin_headers.room_id
    too_many = [f"INV-2569-{i:04d}" for i in range(1, RECEIPTS_PER_PDF_MAX + 2)]

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = _combined_pdf(client, admin_headers, too_many)
    assert res.status_code == 400, res.text
    assert str(RECEIPTS_PER_PDF_MAX) in res.json()["detail"]
    assert mock_render.await_count == 0

    # ส่วนเส้นทางออกใบแจ้งหนี้ **มี** เพดานที่ schema (100 คน/คำขอ) → 422
    overflow = client.post(
        _url(INVOICES_PATH, room_id),
        json={"student_ids": list(range(1, RECEIPTS_PER_PDF_MAX + 2))},
        headers=admin_headers,
    )
    assert overflow.status_code == 422, overflow.text


async def test_combined_pdf_with_no_documents_is_422(client, db_pool, admin_headers):
    """ไม่ส่งเลขมาเลย → 422 จาก schema (ไม่ใช่ 400 ของ service — ไม่มีอะไรให้ตีความ)"""
    res = _combined_pdf(client, admin_headers, [])
    assert res.status_code == 422, res.text


async def test_invoice_number_is_stable_when_reopened(client, db_pool, admin_headers):
    """เปิดใบเดิมซ้ำ → เลขเดิม เส้นทางอ่านไม่มีผลข้างเคียง (ไม่กินเลข ไม่เขียนแถว)"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100.0)
    receipt_no = _issue_invoices(
        client, admin_headers, [student_id]
    ).json()["receipts"][0]["receipt_no"]

    for _ in range(3):
        res = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                         headers=admin_headers)
        assert res.status_code == 200, res.text
        assert res.json()["receipt_no"] == receipt_no

    assert await _db_seq(db_pool, room_id) == 1
    assert await _db_count(db_pool, room_id) == 1


async def test_invoice_uses_the_thai_calendar_day_for_the_document_date(
    client, db_pool, admin_headers
):
    """วันบนเอกสาร (`event_at`) ต้องเป็นวันไทยของ **ตอนออก** — และ `event_at == issued_at` เป๊ะ"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=100.0)

    doc = _issue_invoices(client, admin_headers, [student_id]).json()["receipts"][0]
    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    assert doc["year_be"] == year_be
    assert doc["receipt_no"] == f"INV-{year_be}-0001"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT event_at, issued_at FROM finance_receipts WHERE receipt_no = $1",
            doc["receipt_no"],
        )
    assert row["event_at"] == row["issued_at"], (
        "ทั้งคู่ต้องอ่านจาก CURRENT_TIMESTAMP ครั้งเดียวของ transaction เดียวกัน"
    )
