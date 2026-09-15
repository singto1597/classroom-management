"""[F3] เทสต์ใบเสร็จ / ใบแจ้งหนี้ — finance_receipts + receipt_sequences + PDF

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร (เรียงตามความสำคัญ)
═══════════════════════════════════════════════════════════════════════════════
1. **Idempotency ของใบเสร็จ** — ออกซ้ำต้องได้เลขเดิม ไม่กินเลขใหม่ และต้องไม่ error
   (การพิมพ์ซ้ำเป็นเรื่องปกติของงานเอกสาร ไม่ใช่การเก็บเงินซ้ำ)

2. **ปี พ.ศ. ต้องมาจาก "เหตุการณ์รับเงิน" ไม่ใช่ `student_payments.paid_at`**
   `_confirm_single_payment` ทับ `paid_at` ทุกงวด ⇒ ถ้าอ่าน `paid_at` ใบเสร็จย้อนหลัง
   จะได้เลขปีของ "งวดล่าสุด" ซึ่งผิด และเป็นบั๊กที่เงียบที่สุดในโมดูลนี้
   ⇒ มีเทสต์ขอบ UTC↔ไทย ที่ 16:59 / 17:00 UTC ของวันที่ 31 ธ.ค. (ข้ามปีจริง)

3. **ความไม่สมมาตร receipt vs invoice** — ใบแจ้งหนี้ต้องกินเลขใหม่ทุกครั้ง (point-in-time)
   เทสต์นี้ยืนยัน "เจตนา" ไม่ใช่บั๊ก ถ้ามีใครเผลอเอา invoice เข้า unique index จะ fail

4. **เลขเอกสารต้องเสถียร** — revert แล้วจ่ายใหม่ ต้องได้เลขใหม่ และแถวเดิมต้องไม่ถูกแตะ
   (เหตุผลที่ต้องมีตาราง receipt_sequences แทนการคำนวณ ROW_NUMBER() ตอนอ่าน)

5. **ด่าน RBAC เขียนจริง** — `finance_manager_headers` (ไม่ใช่ admin) ต้องออกได้
   และ `member_headers` ต้อง 403 **โดยไม่มีแถวถูกเขียน** (ไม่ใช่แค่ได้ status)

⚠️ ทุกเทสต์ยืนยันกับ DB จริงผ่าน `db_pool` ไม่เชื่อแค่ HTTP status (กฎ docs/rules/testing.md)
"""
import asyncio
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import asyncpg
import httpx
import pytest

from services.finance.constants import (
    BUDDHIST_ERA_OFFSET, RECEIPT_FONT_FILES, RECEIPT_NO_PATTERN,
    RECEIPT_SEQ_MAX, RECEIPT_SEQ_OVERFLOW_MSG, THAI_MONTHS_SHORT, THAI_TZ,
)
from services.finance.pdf import PdfRenderError, gotenberg_configured
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

# ⚠️ finance router mount ด้วย prefix `/api/classroom` (backend/main.py:79)
API_PREFIX = "/api/classroom"
RECEIPTS_PATH = API_PREFIX + "/{room}/finance/receipts"
BATCH_PATH = API_PREFIX + "/{room}/finance/receipts/batch"
# 🧾 ใบแจ้งหนี้ "ยอดค้างรวมต่อคน" — คนละเส้นทางกับใบเสร็จ (F3 รอบสอง)
INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices"
ROOM_INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices/room"
COMBINED_PDF_PATH = API_PREFIX + "/{room}/finance/receipts/pdf"
RECEIPT_PATH = API_PREFIX + "/{room}/finance/receipts/{receipt_no}"
PDF_PATH = API_PREFIX + "/{room}/finance/receipts/{receipt_no}/pdf"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"
TRANSACTION_PATH = API_PREFIX + "/{room}/finance/transactions/{tx_id}"
ACCOUNTS_PATH = API_PREFIX + "/{room}/finance/accounts"


def _url(template: str, room_id: int, **kwargs) -> str:
    """สร้าง URL ของ finance API — web ต้องส่ง `target_type=room` เสมอ (default คือ server)"""
    return template.format(room=room_id, **kwargs) + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _insert_room_for(pool, user_id: int, *, is_admin: bool = True) -> int:
    """สร้างห้องเพิ่มให้ user ที่มีอยู่แล้ว (ใช้ทดสอบกรณี "เป็นสมาชิกสองห้อง")

    ⚠️ `student_no=0` ไม่ชนกับใครเพราะเป็นห้องใหม่ (partial unique index ผูกกับ room_id)
    """
    async with pool.acquire() as conn:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, $3) RETURNING id",
            "ห้องที่สอง", f"R{uuid.uuid4().hex[:6].upper()}", user_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 0, 'president', 'active', $3, '[]'::jsonb)""",
            room_id, user_id, is_admin,
        )
    return room_id


async def _insert_account(pool, room_id: int, name: str = "กระเป๋ากลาง", balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, name, balance,
        )


async def _make_debtor(pool, room_id: int, *, student_no: int = 90,
                       first_name: str = "เด็กชายทดสอบ") -> int:
    """สร้าง user + students row สำหรับเป็น "ผู้ชำระเงิน" (คนละคนกับผู้ออกใบเสร็จ)

    ⚠️ `student_no` ต้องไม่ชนกับคนอื่นในห้อง — conftest จองเลข 1 ไว้แล้ว
    """
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ($1, $2, $3) RETURNING id",
            first_name, "ทดลอง", f"u{uuid.uuid4().hex[:12]}",
        )
        student_id = await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )
    return student_id


async def _make_bill(pool, room_id: int, student_id: int, *,
                     amount: float = 1000.0, paid_amount: float = 0.0) -> tuple:
    """สร้าง fee_collections + student_payments (บิลตั้งต้น) → (collection_id, payment_id)"""
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, $2, $3, $4, 'active') RETURNING id""",
            room_id, "ค่าเทอม", amount, date(2026, 12, 31),
        )
        payment_id = await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            collection_id, student_id, "paid" if paid_amount > 0 else "pending", paid_amount,
        )
    return collection_id, payment_id


async def _seed_payment_event(pool, room_id: int, payment_id: int, account_id: int,
                              *, amount: float, created_at: datetime) -> int:
    """INSERT แถว finance_transactions แทน "เหตุการณ์รับเงิน" 1 งวด พร้อมคุมเวลาที่เกิด

    ⚠️ **ไม่** เขียน journal คู่ให้ — เจตนา: ใช้ทดสอบเส้นทางอ่านของใบเสร็จ
    (`_resolve_event` อ่านตารางนี้ตารางเดียว) ไม่ได้ทดสอบ dual-write

    ⚠️ `created_at` เป็น TIMESTAMP **naive ที่เก็บ UTC** → ส่ง naive เข้าไปตรง ๆ
       (เหมือนที่ DB เก็บจริง) ห้ามส่ง aware
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO finance_transactions
                   (room_id, account_id, amount, description, transaction_type,
                    recorded_by, student_payment_id, created_at)
               VALUES ($1, $2, $3, 'seed งวดรับเงิน', 'income', 'Tester', $4, $5)
               RETURNING id""",
            room_id, account_id, amount, payment_id, created_at,
        )


# ═══════════════════════════════════════════════════════════════════ HTTP helpers
def _pay(client, headers, payment_id: int, account_id: int, amount: float):
    """ยิงเส้นทางเงินจริง (PUT .../pay) — เพื่อให้ได้เหตุการณ์รับเงินที่มี dual-write ครบ"""
    return client.put(
        _url(PAY_PATH, headers.room_id, payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )


def _issue(client, headers, payment_id: int, *, doc_type: str = "receipt",
           transaction_id=None, note=None, room_id=None):
    body = {"payment_id": payment_id, "doc_type": doc_type}
    if transaction_id is not None:
        body["transaction_id"] = transaction_id
    if note is not None:
        body["note"] = note
    return client.post(
        _url(RECEIPTS_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _issue_invoices(client, headers, student_ids, *, note=None, room_id=None):
    """ออกใบแจ้งหนี้ "ยอดค้างรวมต่อคน" — ส่ง **student_id** ไม่ใช่ payment_id

    ⚠️ อย่าสับสนกับ `_issue`: ตัวนั้นคือเส้นทางใบเสร็จที่รับ `payment_id`
       (และใบแจ้งหนี้ถูกย้ายออกจากที่นั่นแล้ว — ส่ง `doc_type='invoice'` ไปจะได้ 400)
    """
    body = {"student_ids": student_ids}
    if note is not None:
        body["note"] = note
    return client.post(
        _url(INVOICES_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _issue_room_invoices(client, headers, *, note=None, room_id=None):
    """ออกใบแจ้งหนี้ทั้งห้อง — ไม่ส่งรายชื่อไป ระบบหาเจ้าหนี้เอง"""
    body = {}
    if note is not None:
        body["note"] = note
    return client.post(
        _url(ROOM_INVOICES_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


async def _db_receipts(pool, room_id: int, *, doc_type: str = "receipt") -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, receipt_no, doc_type, year_be, seq, student_payment_id,
                      legacy_transaction_id, student_id, collection_id, amount,
                      paid_total_after, issued_to_name, issued_by, issued_by_name,
                      note, event_at, status, voided_at, voided_by, void_reason,
                      issued_at, deleted_at
               FROM finance_receipts
               WHERE room_id = $1 AND doc_type = $2
               ORDER BY id""",
            room_id, doc_type,
        )
        return [dict(r) for r in rows]


def _pdf_has_embedded_truetype(pdf: bytes) -> bool:
    """มี `/FontFile2` (ฟอนต์ TrueType ฝังในไฟล์) อยู่จริงหรือไม่

    ⚠️ ห้าม grep ไบต์ดิบ ๆ ของ PDF — PDF 1.5+ เก็บ dictionary ไว้ใน **object stream**
       ที่บีบอัดด้วย FlateDecode ⇒ ต้องคลาย zlib ของทุก stream ก่อนแล้วค่อยค้น
       (grep ดิบจะได้ false negative แล้วเข้าใจผิดว่าฟอนต์ไม่ได้ฝัง)

    ใช้เป็นด่านกันการถอยกลับไปเป็น **Type 3** ซึ่งเกิดเมื่อใช้ variable font กับ
    Chromium/Skia — เอกสารยังดูปกติแต่ไฟล์ใหญ่ขึ้น 5.5 เท่าและร้านพิมพ์ไม่ยอมรับ
    """
    import re
    import zlib

    hay = pdf
    for m in re.finditer(rb"stream\r?\n", pdf):
        start = m.end()
        end = pdf.find(b"endstream", start)
        if end == -1:
            continue
        try:
            hay += b"\n" + zlib.decompress(pdf[start:end])
        except zlib.error:
            continue   # stream ที่ไม่ใช่ FlateDecode (เช่นรูปภาพ) — ข้าม
    return b"/FontFile2" in hay


def _assert_tz_aware_iso(value: str) -> None:
    """`timestamptz` ต้อง serialize พร้อม offset เสมอ

    ⚠️ Pydantic v2 เขียน UTC เป็น `Z` ไม่ใช่ `+00:00` (ทั้งคู่ถูกต้อง) — ที่ต้องกันคือ
    กรณีหลุดเป็น naive (`2026-09-13T12:41:46`) ซึ่ง JavaScript จะตีเป็นเวลา **ของเบราว์เซอร์**
    แล้วผู้ใช้ในไทยเห็นเวลาคลาดเคลื่อน 7 ชั่วโมง
    """
    assert value.endswith("Z") or "+" in value[10:], f"ไม่ใช่ tz-aware ISO: {value}"


async def _db_last_seq(pool, room_id: int, year_be: int, doc_type: str = "receipt"):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """SELECT last_seq FROM receipt_sequences
               WHERE room_id = $1 AND year_be = $2 AND doc_type = $3""",
            room_id, year_be, doc_type,
        )


async def _db_receipt_count(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room_id,
        )


# ═══════════════════════════════════════════════════════════ 1. happy path + DB
async def test_issue_receipt_happy_path_and_deep_db(client, db_pool, admin_headers):
    """เส้นทางปกติ: จ่ายครบ → ออกใบเสร็จ → ตรวจแถวใน DB และตัวนับเลขทุกคอลัมน์"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)

    assert _pay(client, admin_headers, payment_id, account_id, 1000.0).status_code == 200

    res = _issue(client, admin_headers, payment_id, note="ออกให้ผู้ปกครอง")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["reused"] is False

    receipt = body["receipt"]
    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    assert receipt["receipt_no"] == f"REC-{year_be}-0001"
    assert receipt["doc_type"] == "receipt"
    assert receipt["doc_type_label"] == "ใบเสร็จรับเงิน"
    assert receipt["amount"] == 1000.0
    assert receipt["amount_text"] == "หนึ่งพันบาทถ้วน"
    assert receipt["paid_total_after"] == 1000.0
    assert receipt["issued_to_name"] == "เด็กชายทดสอบ"
    assert receipt["note"] == "ออกให้ผู้ปกครอง"
    # issued_at ต้องเป็น tz-aware เสมอ (ไม่งั้น JS ตีเป็นเวลาเบราว์เซอร์ → คลาด 7 ชม.)
    _assert_tz_aware_iso(receipt["issued_at"])

    # ── deep DB: แถวจริงในฐานข้อมูล ──
    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 1
    row = rows[0]
    assert float(row["amount"]) == 1000.0
    assert float(row["paid_total_after"]) == 1000.0
    assert row["student_payment_id"] == payment_id
    assert row["student_id"] == student_id
    assert row["year_be"] == year_be
    assert row["seq"] == 1
    assert row["deleted_at"] is None
    assert row["issued_by"] == admin_headers.user_id
    assert row["issued_by_name"] == "—"
    # legacy_transaction_id ต้องชี้ "งวดรับเงิน" จริง ไม่ใช่ NULL
    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval(
            "SELECT transaction_id FROM student_payments WHERE id = $1", payment_id,
        )
    assert row["legacy_transaction_id"] == tx_id

    # ── deep DB: ตัวนับเลข ──
    assert await _db_last_seq(db_pool, room_id, year_be) == 1

    # ── audit log ถูกเขียนใน transaction เดียวกัน ──
    async with db_pool.acquire() as conn:
        log = await conn.fetchrow(
            """SELECT action, entity_type, entity_id, status, new_values
               FROM audit_logs
               WHERE entity_type = 'FINANCE_RECEIPT' AND entity_id = $1 AND action = 'CREATE'""",
            str(receipt["id"]),
        )
    assert log is not None
    assert log["status"] == "success"
    new_values = json.loads(log["new_values"])
    assert new_values["receipt_no"] == receipt["receipt_no"]
    assert new_values["reused"] is False


# ═══════════════════════════════════════════════════════ 2. idempotency (แกน)
async def test_reissue_returns_same_receipt_without_burning_a_number(client, db_pool, admin_headers):
    """🔁 ออกซ้ำ → 200 ทั้งสองครั้ง, เลขเดิม, แถวเดียว, last_seq ไม่ขยับ, reused=True

    นี่คือข้อกำหนดแกนของ F3 — "พิมพ์ซ้ำ" ต้องถูกและปลอดภัย ไม่ใช่ error และไม่กินเลขใหม่
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id)
    assert _pay(client, admin_headers, payment_id, account_id, 1000.0).status_code == 200

    first = _issue(client, admin_headers, payment_id)
    assert first.status_code == 200, first.text
    assert first.json()["reused"] is False

    second = _issue(client, admin_headers, payment_id)
    assert second.status_code == 200, second.text          # ⚠️ ต้องไม่ raise
    assert second.json()["reused"] is True
    assert second.json()["receipt"]["receipt_no"] == first.json()["receipt"]["receipt_no"]
    assert second.json()["receipt"]["id"] == first.json()["receipt"]["id"]
    # issued_at ของใบเดิมต้องไม่ถูกเขียนทับ
    assert second.json()["receipt"]["issued_at"] == first.json()["receipt"]["issued_at"]

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 1, "ออกซ้ำต้องไม่สร้างแถวที่สอง"
    year_be = rows[0]["year_be"]
    assert await _db_last_seq(db_pool, room_id, year_be) == 1, "ออกซ้ำต้องไม่กินเลข"


async def test_pre_dualwrite_bill_receipt_is_also_idempotent(client, db_pool, admin_headers):
    """🔁 บิลที่ไม่มีแถว finance_transactions (ก่อนยุค dual-write) ก็ต้อง idempotent

    เคสนี้ `legacy_transaction_id` เป็น NULL → ต้องถูกครอบด้วย `COALESCE(..., 0)`
    ใน partial unique index `idx_finance_receipts_tx_active`
    (ถ้าใช้ `IS NOT NULL` ใน predicate ใบเสร็จกลุ่มนี้จะหลุดออกจาก index ทั้งที่ผูกบิลอยู่)
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    # paid_amount > 0 แต่ **ไม่มี** แถว finance_transactions → เข้าเส้นทาง fallback
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=800.0, paid_amount=800.0)

    first = _issue(client, admin_headers, payment_id)
    assert first.status_code == 200, first.text
    assert first.json()["receipt"]["legacy_transaction_id"] is None
    assert first.json()["receipt"]["amount"] == 800.0
    assert first.json()["receipt"]["paid_total_after"] == 800.0

    second = _issue(client, admin_headers, payment_id)
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert second.json()["receipt"]["receipt_no"] == first.json()["receipt"]["receipt_no"]

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 1
    assert await _db_last_seq(db_pool, room_id, rows[0]["year_be"]) == 1


# ═══════════════════════════════════════════════════ 3. ความเป็นเอกลักษณ์ของเลข
async def test_five_receipts_get_five_distinct_sequential_numbers(client, db_pool, admin_headers):
    """5 ใบ → 5 เลขต่างกัน เรียง 0001..0005 และ last_seq == 5"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    payment_ids = []
    for i in range(5):
        student_id = await _make_debtor(db_pool, room_id, student_no=90 + i, first_name=f"เด็ก{i}")
        _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=100.0 * (i + 1))
        assert _pay(client, admin_headers, payment_id, account_id, 100.0 * (i + 1)).status_code == 200
        payment_ids.append(payment_id)

    numbers = []
    for pid in payment_ids:
        res = _issue(client, admin_headers, pid)
        assert res.status_code == 200, res.text
        numbers.append(res.json()["receipt"]["receipt_no"])

    assert len(set(numbers)) == 5, f"เลขต้องไม่ซ้ำกัน: {numbers}"
    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    assert numbers == [f"REC-{year_be}-{i:04d}" for i in range(1, 6)]
    assert await _db_last_seq(db_pool, room_id, year_be) == 5
    assert await _db_receipt_count(db_pool, room_id) == 5


# ═══════════════════════════════════════ 4. ความเสถียรของเลขข้าม revert → จ่ายใหม่
async def test_receipt_number_is_stable_across_revert_and_repay(client, db_pool, admin_headers):
    """ออก → revert → จ่ายใหม่ → ออกใหม่ ต้องได้ **เลขใหม่** และเลข/ยอดของแถวเดิมต้องไม่ถูกแตะ

    นี่คือเหตุผลที่ต้องมีตาราง `receipt_sequences` แทนการคำนวณ ROW_NUMBER() ตอนอ่าน:
    เลขที่ derive จะเปลี่ยนย้อนหลังทันทีที่ revert ทำให้ใบเสร็จที่พิมพ์ไปแล้วเปลี่ยนเลข
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id)
    assert _pay(client, admin_headers, payment_id, account_id, 1000.0).status_code == 200

    first = _issue(client, admin_headers, payment_id)
    assert first.status_code == 200, first.text
    first_no = first.json()["receipt"]["receipt_no"]
    first_id = first.json()["receipt"]["id"]

    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval(
            "SELECT transaction_id FROM student_payments WHERE id = $1", payment_id,
        )
    res = client.request(
        "DELETE", _url(TRANSACTION_PATH, room_id, tx_id=tx_id),
        json={"user_name": "Tester"}, headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    # revert ล้าง paid_at/transaction_id ของบิล (นี่คือเหตุผลที่ paid_at ใช้ไม่ได้)
    async with db_pool.acquire() as conn:
        sp = await conn.fetchrow(
            "SELECT paid_amount, paid_at, transaction_id, status FROM student_payments WHERE id = $1",
            payment_id,
        )
    assert float(sp["paid_amount"]) == 0.0
    assert sp["paid_at"] is None and sp["transaction_id"] is None and sp["status"] == "pending"

    # จ่ายใหม่ → เหตุการณ์ใหม่ → ใบเสร็จใหม่ เลขใหม่
    assert _pay(client, admin_headers, payment_id, account_id, 1000.0).status_code == 200
    second = _issue(client, admin_headers, payment_id)
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is False
    second_no = second.json()["receipt"]["receipt_no"]
    assert second_no != first_no

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 2
    old = next(r for r in rows if r["id"] == first_id)
    assert old["receipt_no"] == first_no, "ใบที่ออกไปแล้วต้องไม่ถูกแก้เลขย้อนหลัง"
    assert float(old["amount"]) == 1000.0
    # 🧾 **ไม่ใช่ `deleted_at IS NULL` อีกต่อไป** — ตั้งแต่ #60 การยกเลิกรายการต้อง void
    #    ใบเสร็จที่ผูกอยู่ด้วย (ดู `test_revert_voids_the_receipt_instead_of_leaving_it_active`)
    #    สิ่งที่เทสต์นี้ป้องกันคือ "เลขกับยอดของใบเดิมต้องไม่ถูกเขียนทับ" ซึ่งยังจริงอยู่
    #    ส่วนการหายไปจากรายการคือ **เจตนา** ไม่ใช่การถูกลบ
    assert old["status"] == "voided"
    assert old["deleted_at"] is not None
    assert await _db_last_seq(db_pool, room_id, rows[0]["year_be"]) == 2


# ═══════════════════════════════ 5. ปี พ.ศ. จาก "เหตุการณ์รับเงิน" (ไม่ใช่ paid_at)
@pytest.mark.parametrize(
    "event_utc, expected_year_be, why",
    [
        (datetime(2026, 10, 1, 3, 0), 2026 + BUDDHIST_ERA_OFFSET, "กลางปี ปกติ"),
        (datetime(2027, 1, 5, 3, 0), 2027 + BUDDHIST_ERA_OFFSET, "ต้นปีถัดไป"),
        # 🔴 ขอบ UTC↔ไทยที่ข้ามปี: 16:59 UTC = 23:59 ไทย (ยังเป็น 31 ธ.ค.)
        (datetime(2026, 12, 31, 16, 59), 2026 + BUDDHIST_ERA_OFFSET, "นาทีสุดท้ายของปีไทย"),
        # 🔴 17:00 UTC = 00:00 ของ 1 ม.ค. ไทย → ต้องเป็นปีถัดไป
        #    ถ้าโค้ดเผลอใช้ปี UTC ตรง ๆ เทสต์นี้จะได้ 2569 (fail)
        (datetime(2026, 12, 31, 17, 0), 2027 + BUDDHIST_ERA_OFFSET, "ข้ามปีเพราะ UTC+7"),
    ],
)
async def test_year_be_comes_from_payment_event_in_thai_time(
    client, db_pool, admin_headers, event_utc, expected_year_be, why
):
    """ปี พ.ศ. ของเลขเอกสาร = ปีของ "เหตุการณ์รับเงิน" ในเวลาไทย

    ⚠️ เคส 17:00 UTC ของ 31 ธ.ค. คือหัวใจ: ตรงกับ 00:00 ของ 1 ม.ค. ไทย
    โค้ดที่อ่านปีจาก `created_at` แบบ UTC ตรง ๆ จะได้ปีผิด (เอกสารออกปีภาษีผิด)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=500.0, paid_amount=500.0)
    await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                              amount=500.0, created_at=event_utc)

    res = _issue(client, admin_headers, payment_id)
    assert res.status_code == 200, res.text
    receipt = res.json()["receipt"]
    assert receipt["year_be"] == expected_year_be, why
    assert receipt["receipt_no"] == f"REC-{expected_year_be}-0001"
    assert receipt["seq"] == 1

    rows = await _db_receipts(db_pool, room_id)
    assert rows[0]["year_be"] == expected_year_be
    assert await _db_last_seq(db_pool, room_id, expected_year_be) == 1


async def test_year_sequences_are_independent_per_buddhist_year(client, db_pool, admin_headers):
    """คนละปี พ.ศ. → คนละตัวนับ เลขเริ่ม 0001 ใหม่ทั้งคู่"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=600.0, paid_amount=600.0)

    tx_2569 = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                        amount=200.0, created_at=datetime(2026, 6, 1, 3, 0))
    tx_2570 = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                        amount=200.0, created_at=datetime(2027, 6, 1, 3, 0))

    # ระบุ transaction_id ชัดเจนเพื่อออกใบเสร็จของแต่ละงวด (งวดหลัง = ค่าเริ่มต้น)
    res_a = _issue(client, admin_headers, payment_id, transaction_id=tx_2570)
    assert res_a.status_code == 200, res_a.text
    assert res_a.json()["receipt"]["receipt_no"] == "REC-2570-0001"

    res_b = _issue(client, admin_headers, payment_id, transaction_id=tx_2569)
    assert res_b.status_code == 200, res_b.text
    assert res_b.json()["receipt"]["receipt_no"] == "REC-2569-0001"

    assert await _db_last_seq(db_pool, room_id, 2569) == 1
    assert await _db_last_seq(db_pool, room_id, 2570) == 1


# ═══════════════════════════════════════════════════════════════ 6. ผ่อนชำระ
async def test_instalment_payments_produce_one_receipt_per_event(client, db_pool, admin_headers):
    """จ่าย 500/1000 → ใบที่ 1 (amount=500, paid_total_after=500); จ่ายที่เหลือ → ใบที่ 2

    แล้วออกใบที่ 1 ซ้ำ (ระบุ transaction_id ของงวดแรก) ต้องได้ **ใบเดิม**
    ⇒ พิสูจน์ว่า `legacy_transaction_id` อยู่ใน unique key จริง ไม่ได้กันแค่ระดับบิล
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)

    assert _pay(client, admin_headers, payment_id, account_id, 500.0).status_code == 200
    async with db_pool.acquire() as conn:
        tx_1 = await conn.fetchval(
            "SELECT transaction_id FROM student_payments WHERE id = $1", payment_id,
        )
    r1 = _issue(client, admin_headers, payment_id)
    assert r1.status_code == 200, r1.text
    assert r1.json()["receipt"]["amount"] == 500.0
    assert r1.json()["receipt"]["paid_total_after"] == 500.0
    assert r1.json()["receipt"]["amount_text"] == "ห้าร้อยบาทถ้วน"

    # งวดที่เหลือ
    assert _pay(client, admin_headers, payment_id, account_id, 500.0).status_code == 200
    async with db_pool.acquire() as conn:
        tx_2 = await conn.fetchval(
            "SELECT transaction_id FROM student_payments WHERE id = $1", payment_id,
        )
    assert tx_2 != tx_1
    r2 = _issue(client, admin_headers, payment_id)
    assert r2.status_code == 200, r2.text
    assert r2.json()["receipt"]["amount"] == 500.0
    assert r2.json()["receipt"]["paid_total_after"] == 1000.0
    assert r2.json()["receipt"]["receipt_no"] != r1.json()["receipt"]["receipt_no"]

    # ออกใบของงวดแรกซ้ำ → ต้องได้ใบเดิม (ไม่ใช่ใบของงวดล่าสุด)
    again = _issue(client, admin_headers, payment_id, transaction_id=tx_1)
    assert again.status_code == 200, again.text
    assert again.json()["reused"] is True
    assert again.json()["receipt"]["receipt_no"] == r1.json()["receipt"]["receipt_no"]
    assert again.json()["receipt"]["paid_total_after"] == 500.0

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 2
    assert [float(r["paid_total_after"]) for r in rows] == [500.0, 1000.0]
    assert await _db_last_seq(db_pool, room_id, rows[0]["year_be"]) == 2


async def test_unknown_transaction_id_is_rejected_not_silently_substituted(
    client, db_pool, admin_headers
):
    """ส่ง transaction_id ที่ไม่ใช่ของบิลนี้ → 400 (ห้ามเงียบ ๆ ออกใบของงวดอื่นให้)"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    other_student = await _make_debtor(db_pool, room_id, student_no=91)
    _, other_payment = await _make_bill(db_pool, room_id, other_student, amount=300.0)
    foreign_tx = await _seed_payment_event(db_pool, room_id, other_payment, account_id,
                                           amount=300.0, created_at=datetime(2026, 9, 5, 3, 0))

    student_id = await _make_debtor(db_pool, room_id, student_no=92)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)
    assert _pay(client, admin_headers, payment_id, account_id, 1000.0).status_code == 200

    res = _issue(client, admin_headers, payment_id, transaction_id=foreign_tx)
    assert res.status_code == 400, res.text
    assert await _db_receipt_count(db_pool, room_id) == 0


# ══════════════════════════════ 7. ความไม่สมมาตร: ใบแจ้งหนี้ point-in-time
async def test_invoice_is_point_in_time_and_gets_a_new_number_every_time(
    client, db_pool, admin_headers
):
    """ใบแจ้งหนี้ **ตั้งใจ** ให้ออกซ้ำได้และกินเลขใหม่ทุกครั้ง (ยอดค้างเปลี่ยนเมื่อจ่ายเพิ่ม)

    เทสต์นี้ยืนยัน "เจตนา" ของความไม่สมมาตรกับใบเสร็จ — ถ้ามีใครเผลอเอา
    doc_type='invoice' เข้าไปใน unique index `idx_finance_receipts_tx_active` เทสต์นี้จะ fail
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1200.0)

    first = _issue_invoices(client, admin_headers, [student_id])
    assert first.status_code == 200, first.text
    assert first.json()["issued_count"] == 1
    doc = first.json()["receipts"][0]
    # ℹ️ ไม่มีฟิลด์ `reused` ในเส้นทางนี้ (ต่างจาก `_issue`) — "ไม่อยู่ใน idempotency index"
    #    พิสูจน์ด้วยเลขที่ต่างกันข้างล่างแทน ซึ่งเป็นสิ่งที่ผู้ใช้เห็นจริง
    assert doc["amount"] == 1200.0, "ใบแจ้งหนี้ = ยอดค้างทั้งก้อน"
    assert doc["paid_total_after"] == 0.0
    assert doc["legacy_transaction_id"] is None
    assert doc["receipt_no"].startswith("INV-")
    assert doc["doc_type_label"] == "ใบแจ้งหนี้"
    # 🔴 ใบนี้ไม่ผูกกับ "บิลเดียว" — ถ้ามีค่าติดมาแปลว่ายังใช้เส้นทางใบละบิลอยู่
    assert doc["student_payment_id"] is None
    assert doc["collection_id"] is None
    assert doc["student_id"] == student_id

    second = _issue_invoices(client, admin_headers, [student_id])
    assert second.status_code == 200, second.text
    again = second.json()["receipts"][0]
    assert again["receipt_no"] != doc["receipt_no"], (
        "ใบแจ้งหนี้ต้องได้เลขใหม่ทุกครั้ง (point-in-time) — เลขเดิมแปลว่าไปเข้า "
        "idempotency index ของใบเสร็จเข้าแล้ว"
    )
    assert again["amount"] == 1200.0

    rows = await _db_receipts(db_pool, room_id, doc_type="invoice")
    assert len(rows) == 2
    assert {r["seq"] for r in rows} == {1, 2}
    assert await _db_last_seq(db_pool, room_id, rows[0]["year_be"], "invoice") == 2
    # ⚠️ ตัวนับของ receipt ต้องไม่ถูกแตะเลยโดยการออก invoice
    assert await _db_last_seq(db_pool, room_id, rows[0]["year_be"], "receipt") is None


async def test_invoice_for_fully_paid_bill_is_rejected(client, db_pool, admin_headers):
    """บิลที่ชำระครบแล้ว → ไม่มีอะไรให้แจ้งหนี้ → 400"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=400.0)
    assert _pay(client, admin_headers, payment_id, account_id, 400.0).status_code == 200

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 400, res.text
    assert "ไม่มีบิลค้างชำระ" in res.json()["detail"], (
        "ต้องเป็น 400 ของ 'ไม่มีอะไรให้แจ้งหนี้' ไม่ใช่ 400 ของเส้นทางที่ถูกย้ายไปแล้ว"
    )
    assert await _db_receipt_count(db_pool, room_id) == 0


async def test_stale_invoice_path_returns_400_pointing_at_the_new_endpoint(
    client, db_pool, admin_headers
):
    """หน้าจอที่ค้างเปิดอยู่ (deploy ใหม่ทับ) ยังยิง `doc_type='invoice'` มาที่เดิมได้

    ⇒ ต้องได้ **400 พร้อมข้อความไทยที่บอกว่าปุ่มย้ายไปไหน** ไม่ใช่ 422 ดิบของ Pydantic
      และไม่ใช่ 200 ที่ออกเอกสารผิดรูปแบบให้
    ⚠️ ยังไม่ปิดที่ pattern ของ Pydantic โดยเจตนา — ดูเหตุผลใน `issue_receipt`
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=500.0)

    res = _issue(client, admin_headers, payment_id, doc_type="invoice")
    assert res.status_code == 400, res.text
    assert "receipts/invoices" in res.json()["detail"], (
        "ข้อความต้องชี้ไปที่เส้นทางใหม่ ไม่งั้นครูจะไม่รู้ว่าต้องกดตรงไหน"
    )
    # และต้องไม่ยิงเอกสารออกมาให้
    assert await _db_receipt_count(db_pool, room_id) == 0


# ════════════════════════════════════════════════════════════════════ 8. guards
async def test_receipt_for_unpaid_bill_is_rejected(client, db_pool, admin_headers):
    """บิลที่ยังไม่ได้รับเงิน → 400 และต้องไม่มีแถว/เลขถูกเขียน"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id)

    res = _issue(client, admin_headers, payment_id)
    assert res.status_code == 400, res.text
    assert await _db_receipt_count(db_pool, room_id) == 0
    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    assert await _db_last_seq(db_pool, room_id, year_be) is None


@pytest.mark.parametrize(
    "collection_amount, paid_amount, doc_type",
    [
        # ใบเสร็จ: บิลที่ถูกทำเป็น "จ่ายแล้ว" แต่ยอดเก็บได้จริง 4 สตางค์ครึ่งสตางค์
        # ⚠️ `student_payments.paid_amount` เป็น `DECIMAL` **ไม่จำกัดสเกล** (init_db.py:283)
        #    ⇒ 0.004 เก็บได้จริง และไม่มีแถว finance_transactions ⇒ ไปตกที่ fallback
        #    ใน `_resolve_event` ที่คืน `float(paid_amount)` ตรง ๆ
        (1000.0, 0.004, "receipt"),
        # ใบแจ้งหนี้: ยอดค้าง 0.001 → ผ่านด่าน `outstanding <= 0` มาได้ แต่ปัดแล้วเหลือ 0.00
        (1000.0, 999.999, "invoice"),
    ],
)
async def test_sub_satang_amount_is_400_not_500(
    client, db_pool, admin_headers, collection_amount, paid_amount, doc_type,
):
    """ยอดที่ปัดเป็นสตางค์แล้วเหลือ 0.00 → **400 พร้อมข้อความไทย** ไม่ใช่ 500 ดิบ

    🎯 บั๊กที่เทสต์นี้กัน: `chk_receipt_amount_positive (amount > 0)` เป็น CHECK ของ DB
       ⇒ asyncpg โยน `CheckViolationError` ซึ่ง **ไม่มีชั้นไหนแปลงเป็น HTTP** ⇒ 500
       ผู้ใช้เห็น "ระบบพัง" ทั้งที่ปัญหาคือยอดที่กรอก และไม่รู้เลยว่าต้องแก้ตรงไหน

    ⚠️ สังเกตว่าด่านเดิม `paid_amount <= 0` (receipts.py:281) **ไม่พอ** เพราะมันเช็คค่าดิบ
       ⇒ ต้องเช็ค "ค่าที่ CHECK จะเห็น" (คือค่าหลัง `round(..., 2)`) — เทสต์นี้จึงยิง 400
       ไม่ใช่ 200 ที่ INSERT ไม่ผ่านแล้วกลายเป็น 500
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(
        db_pool, room_id, student_id, amount=collection_amount,
        # ⚠️ ใบแจ้งหนี้ต้องสร้างบิลแบบ **ยัง pending** ก่อน (ดูเหตุผลข้างล่าง) แล้วค่อย
        #    ยัด `paid_amount` เข้าไปตรง ๆ — ส่วนใบเสร็จใช้ค่าที่ `_make_bill` ตั้งให้เลย
        paid_amount=0.0 if doc_type == "invoice" else paid_amount,
    )

    if doc_type == "invoice":
        # 🔴 ต้องเซ็ตผ่าน SQL ตรง ๆ ไม่ผ่าน `_pay`: เส้นทางรับเงินจะตั้ง `status='paid'`
        #    ทันทีที่จ่ายครบ ⇒ บิลนั้นจะ **หลุดออกจาก predicate `SP.status='pending'`**
        #    ของ `_load_student_outstanding` แล้วเราไม่ได้ทดสอบด่าน `round()` เลย
        #    (ได้ 400 คนละเหตุผล = เทสต์ผ่านโดยไม่ได้กันอะไร)
        #    สภาพที่ต้องการคือ "ยัง pending แต่จ่ายมาแล้ว 999.999 จาก 1000" ซึ่งเกิดได้จริง
        #    เมื่อมีคนแก้ `paid_amount` ด้วยมือ/ข้อมูลนำเข้า — เป็นสภาพที่ด่านนี้มีไว้กัน
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE student_payments SET paid_amount = $2 WHERE id = $1",
                payment_id, paid_amount,
            )
        res = _issue_invoices(client, admin_headers, [student_id])
    else:
        # ⚠️ สองเส้นทางรับ "ตัวชี้เป้า" คนละแบบ: ใบเสร็จชี้ที่ **บิล** (`payment_id`)
        #    ส่วนใบแจ้งหนี้ชี้ที่ **คน** (`student_id`)
        res = _issue(client, admin_headers, payment_id, doc_type=doc_type)
    assert res.status_code == 400, res.text

    # ข้อความต้องบอกผู้ใช้ว่าปัญหาคือ "ยอด" ไม่ใช่ปล่อยให้เดา
    detail = json.dumps(res.json(), ensure_ascii=False)
    assert "0.01" in detail or "สตางค์" in detail, detail

    # 🔍 ต้องไม่เหลือร่องรอย: ไม่มีแถวเอกสาร และไม่มีการจองเลข (ไม่มีเลขถูกเผา)
    assert await _db_receipt_count(db_pool, room_id) == 0
    async with db_pool.acquire() as conn:
        burned = await conn.fetchval(
            "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1", room_id,
        )
    assert burned == 0, "ต้องไม่จองเลขก่อนตรวจยอด — ไม่งั้นเลขจะขาดโดยไม่มีเอกสาร"


async def test_cross_room_payment_returns_404_not_403(client, db_pool, admin_headers):
    """บิลของห้องอื่น → 404 (ไม่ใช่ 403) เพื่อไม่ยืนยันว่ามี id นั้นอยู่จริง

    สร้างห้องที่สองให้ user คนเดียวกันเป็นแอดมิน เพื่อให้ผ่าน `require_permission`
    แล้วไปตกที่ `_load_payment` (ถ้า 403 แปลว่าตกที่ RBAC แทน = เทสต์ไม่ได้ทดสอบ guard นี้)
    """
    other_room = await _insert_room_for(db_pool, admin_headers.user_id)
    other_student = await _make_debtor(db_pool, other_room)
    _, other_payment = await _make_bill(db_pool, other_room, other_student)

    # ยิงโดย URL ชี้ห้องที่สอง แต่ payment_id เป็นของห้องแรก
    room_a = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_a, student_no=93)
    _, payment_a = await _make_bill(db_pool, room_a, student_id)

    res = _issue(client, admin_headers, payment_a, room_id=other_room)
    assert res.status_code == 404, res.text
    assert await _db_receipt_count(db_pool, other_room) == 0
    # และกลับกัน: บิลของห้องสอง ยิงเข้า URL ของห้องแรก
    res2 = _issue(client, admin_headers, other_payment, room_id=room_a)
    assert res2.status_code == 404, res2.text
    assert await _db_receipt_count(db_pool, room_a) == 0


async def test_member_without_manage_finance_gets_403_and_writes_nothing(
    client, db_pool, member_headers
):
    """สมาชิกธรรมดา (ไม่มี MANAGE_FINANCE) → 403 และ DB ต้องไม่มีร่องรอยใด ๆ"""
    room_id = member_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id)

    # จ่ายเงินสำเร็จ (ต้องมี MANAGE_FINANCE จึงจ่ายได้ → 403 ก่อน)
    assert _pay(client, member_headers, payment_id, account_id, 1000.0).status_code == 403
    # ยืนยันด้วย admin ของห้องนั้นว่าจ่ายได้จริง (เทสต์นี้จะไม่ผ่านเพราะ "จ่ายไม่ได้" เฉย ๆ)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET status='paid', paid_amount=1000.0, paid_at=NOW() WHERE id=$1",
            payment_id,
        )

    res = _issue(client, member_headers, payment_id)
    assert res.status_code == 403, res.text
    assert await _db_receipt_count(db_pool, room_id) == 0, "403 ต้องไม่ทิ้งแถวไว้"
    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    assert await _db_last_seq(db_pool, room_id, year_be) is None, "403 ต้องไม่กินเลข"

    # อ่านได้ (require_member) — สิทธิ์อ่านเปิดกว้างกว่าสิทธิ์เขียน
    assert client.get(_url(RECEIPTS_PATH, room_id), headers=member_headers).status_code == 200


async def test_finance_manager_can_issue_without_being_admin(client, db_pool, finance_manager_headers):
    """เหรัญญิก (permissions=['MANAGE_FINANCE'], is_admin=FALSE) ต้องออกใบเสร็จได้จริง

    เป็นด่านควบคุมบวกของ RBAC — พิสูจน์ว่าไม่ได้ผ่านเพราะ is_admin bypass
    """
    room_id = finance_manager_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id)

    assert _pay(client, finance_manager_headers, payment_id, account_id, 1000.0).status_code == 200
    res = _issue(client, finance_manager_headers, payment_id)
    assert res.status_code == 200, res.text
    # ⚠️ `issued_by` ถูกกรองออกจาก response โดย `response_model` (ReceiptResponse ไม่มีฟิลด์นี้)
    #    → ตรวจที่ DB เท่านั้น (การเพิ่มฟิลด์นี้เข้า response คือการเปิดเผย user_id โดยไม่จำเป็น)
    assert "issued_by" not in res.json()["receipt"]
    rows = await _db_receipts(db_pool, room_id)
    assert rows[0]["issued_by"] == finance_manager_headers.user_id


# ═══════════════════════════════════════════════════════════ 9. batch (all-or-nothing)
async def test_batch_issue_dedupes_ids_and_is_all_or_nothing(client, db_pool, admin_headers):
    """batch: dedupe payment_id ซ้ำ, ออกครบทุกใบใน transaction เดียว และล้มทั้งชุดถ้ามีใบเสีย"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    payment_ids = []
    for i in range(3):
        student_id = await _make_debtor(db_pool, room_id, student_no=94 + i, first_name=f"Batch{i}")
        _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=250.0)
        assert _pay(client, admin_headers, payment_id, account_id, 250.0).status_code == 200
        payment_ids.append(payment_id)

    # ส่ง id ซ้ำ (จำลอง checkbox ซ้ำ) → ต้องได้ 3 ใบ ไม่ใช่ 4
    res = client.post(
        _url(BATCH_PATH, room_id),
        json={"payment_ids": [payment_ids[0], payment_ids[1], payment_ids[1], payment_ids[2]]},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["issued_count"] == 3
    assert body["reused_count"] == 0
    assert len({r["receipt_no"] for r in body["receipts"]}) == 3
    assert await _db_receipt_count(db_pool, room_id) == 3

    # ── all-or-nothing: ใบที่ 4 เป็นบิลที่ยังไม่จ่าย → ต้องไม่เหลือแถวใหม่เลย ──
    student_id = await _make_debtor(db_pool, room_id, student_no=97)
    _, unpaid = await _make_bill(db_pool, room_id, student_id, amount=500.0)
    res2 = client.post(
        _url(BATCH_PATH, room_id),
        json={"payment_ids": [unpaid]},   # บิลที่ 1-3 ออกไปแล้ว (จะ reused) + บิลที่ยังไม่จ่าย
        headers=admin_headers,
    )
    assert res2.status_code == 400, res2.text
    res3 = client.post(
        _url(BATCH_PATH, room_id),
        json={"payment_ids": [payment_ids[0], unpaid]},
        headers=admin_headers,
    )
    assert res3.status_code == 400, res3.text
    assert await _db_receipt_count(db_pool, room_id) == 3, "ล้มทั้งชุดต้องไม่เหลือแถวค้าง"


async def test_batch_is_idempotent_on_second_call(client, db_pool, admin_headers):
    """เรียก batch ซ้ำชุดเดิม → reused_count เท่ากับจำนวนบิล และเลขไม่ขยับ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    payment_ids = []
    for i in range(2):
        student_id = await _make_debtor(db_pool, room_id, student_no=98 + i, first_name=f"Idem{i}")
        _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=150.0)
        assert _pay(client, admin_headers, payment_id, account_id, 150.0).status_code == 200
        payment_ids.append(payment_id)

    first = client.post(_url(BATCH_PATH, room_id), json={"payment_ids": payment_ids},
                        headers=admin_headers)
    assert first.status_code == 200, first.text
    second = client.post(_url(BATCH_PATH, room_id), json={"payment_ids": payment_ids},
                         headers=admin_headers)
    assert second.status_code == 200, second.text
    assert second.json()["issued_count"] == 0
    assert second.json()["reused_count"] == 2
    assert ([r["receipt_no"] for r in second.json()["receipts"]]
            == [r["receipt_no"] for r in first.json()["receipts"]])
    assert await _db_receipt_count(db_pool, room_id) == 2
    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    assert await _db_last_seq(db_pool, room_id, year_be) == 2


# ══════════════════════════════════════════════════════ 10. ลำดับการล็อก (deadlock)
class _RecordingConn:
    """connection ปลอมที่บันทึกว่า "ถูกล็อก id อะไร ตามลำดับไหน"

    🎯 ใช้พิสูจน์ **ลำดับ** แบบ deterministic — ไม่ต้องพึ่งการแข่งกันของสอง connection
       ซึ่งพิสูจน์อะไรไม่ได้จริง (ดูคอมเมนต์ในเทสต์ว่าทำไมวิธีเดิมถึงหลอกตัวเอง)
    """

    def __init__(self):
        self.locked_ids = []

    async def fetchval(self, query, *args):
        self.locked_ids.append(args[0])
        return args[0]


async def test_lock_helper_locks_in_id_order_regardless_of_caller_order():
    """`_lock_payments_in_order` ต้องล็อกตาม id **เสมอ** ไม่ใช่ตามลำดับที่ผู้ใช้ส่งมา

    🎯 บั๊กที่เทสต์นี้กัน (DeadlockDetectedError 40P01 → router ไม่แปลง → 500 + rollback ทั้งชุด):
       ถ้าล็อกตามลำดับที่ส่งมา สองคำขอของห้องเดียวกันที่ส่งบิลชุดเดียวกัน **สลับลำดับกัน**
       (A: P2→P1, B: P1→P2) จะวนรอกันทันที: A ยึด P2 รอ P1 ขณะที่ B ยึด P1 รอ P2

    🧪 ทำไมพิสูจน์ "ลำดับ" แทนที่จะยิงสอง connection ให้ตายกันจริง:
       วิธีนั้น **หลอกตัวเองได้ง่ายมาก** — ถ้าฝั่งแรกยึดล็อกครบทั้งสองใบ *ก่อน* ฝั่งที่สองเริ่ม
       ฝั่งที่สองจะแค่ "รอ" แล้วไปต่อ ⇒ ไม่เกิด deadlock ไม่ว่าจะเรียงหรือไม่เรียง
       (ซึ่งคือสิ่งที่เกิดขึ้นจริงกับเวอร์ชันแรกของเทสต์นี้ — mutation ไม่จับ)
       การบันทึก "ลำดับ id ที่ถูกล็อก" ตรง ๆ จึงเป็นหลักฐานที่ทั้ง deterministic และมีฟันจริง:
       ถ้าถอด `sorted()` ออก ลำดับที่ได้จะกลายเป็นลำดับของผู้เรียก → เทสต์ล้มทันที
    """
    from services.finance.base import _lock_payments_in_order

    # ผู้ใช้ส่งสลับลำดับ + ซ้ำ + มี None ปน (checkbox ฝั่ง UI ส่งซ้ำได้)
    conn_a = _RecordingConn()
    await _lock_payments_in_order(conn_a, [7, 3, 9, 3, None])
    assert conn_a.locked_ids == [3, 7, 9], f"ไม่ได้เรียงตาม id: {conn_a.locked_ids}"

    # อีกคำขอส่ง **ลำดับตรงข้าม** → ต้องได้ผลลัพธ์เดียวกันเป๊ะ นี่คือหัวใจของการกัน deadlock
    conn_b = _RecordingConn()
    await _lock_payments_in_order(conn_b, [9, 7, 3])
    assert conn_b.locked_ids == [3, 7, 9], f"ไม่ได้เรียงตาม id: {conn_b.locked_ids}"
    assert conn_a.locked_ids == conn_b.locked_ids

    # ลิสต์ว่าง / มีแต่ None → ต้องไม่ล็อกอะไรเลยและไม่ระเบิด
    conn_c = _RecordingConn()
    await _lock_payments_in_order(conn_c, [])
    await _lock_payments_in_order(conn_c, [None, None])
    assert conn_c.locked_ids == []


async def test_lock_helper_actually_takes_row_locks(db_pool):
    """helper ต้อง **ล็อกจริง** ไม่ใช่แค่ `SELECT` ธรรมดา (กันการถอยกลับเป็น no-op)

    🧪 พิสูจน์ด้วย `FOR UPDATE NOWAIT` จากอีก connection: ถ้าแถวถูกล็อกจริง
       Postgres จะโยน `LockNotAvailableError` ทันทีแทนที่จะรอ
    """
    import asyncpg

    from services.finance.base import _lock_payments_in_order

    async with db_pool.acquire() as setup:
        room_id = await setup.fetchval(
            "INSERT INTO rooms (room_name, room_code, owner_id) VALUES ($1, $2, NULL) RETURNING id",
            "ห้องทดสอบล็อก", f"LOCK{uuid.uuid4().hex[:6].upper()}",
        )
        user_id = await setup.fetchval(
            "INSERT INTO users (first_name, last_name, username) VALUES ('ล็อก', 'ทดสอบ', $1) RETURNING id",
            f"lk{uuid.uuid4().hex[:12]}",
        )
        student_id = await setup.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 1, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id,
        )
        collection_id = await setup.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, 'งบทดสอบล็อก', 100.0, $2, 'active') RETURNING id""",
            room_id, date(2026, 12, 31),
        )
        payment_id = await setup.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0) RETURNING id""",
            collection_id, student_id,
        )

    async with db_pool.acquire() as holder:
        async with holder.transaction():
            await _lock_payments_in_order(holder, [payment_id])

            async with db_pool.acquire() as other:
                with pytest.raises(asyncpg.exceptions.LockNotAvailableError):
                    await other.fetchval(
                        "SELECT id FROM student_payments WHERE id = $1 FOR UPDATE NOWAIT",
                        payment_id,
                    )


async def test_batch_confirm_payments_uses_the_same_canonical_lock_order():
    """เส้นทางรับเงินรวบยอดต้องล็อกบิลทั้งชุด **ก่อน** เข้าลูป (ไม่ใช่ล็อกทีละใบกลางลูป)

    🎯 เหตุผล: `_confirm_single_payment` ต่อใบจะไปแตะ `finance_accounts` (บวกยอดเข้าบัญชี)
       ⇒ ถ้าล็อก SP ทีละใบกลางลูป ลำดับการล็อกจะกลายเป็น SP1→ACC→SP2→ACC ซึ่ง **สลับกันได้**
       กับอีกคำขอหนึ่ง ⇒ ต้องยึด SP ให้ครบก่อน แล้วค่อยแตะ ACC

    ⚠️ เทสต์นี้เป็น **ด่านเชิงโครงสร้าง** (อ่านซอร์ส) ไม่ใช่เชิงพฤติกรรม — จงใจเป็นแบบนั้น
       เพราะ "ล็อกก่อนอ่าน" สังเกตจาก HTTP ไม่ได้: `TestClient` เป็น sync ยิงพร้อมกันจริงไม่ได้
       และเราแทรก `lock_timeout` เข้า connection ของแอปไม่ได้
       ⇒ พฤติกรรมของตัวช่วยถูกพิสูจน์แล้วในสองเทสต์ข้างบน ตัวนี้ทำหน้าที่จับ
         "มีคนย้ายหรือลบคำสั่งล็อกออกจากตำแหน่งนี้" ซึ่งเทสต์เหล่านั้นจับไม่ได้
    """
    import inspect
    import re

    from services.finance import collections as collections_module

    src = inspect.getsource(collections_module.CollectionsMixin.batch_confirm_payments)
    # หา "บรรทัดที่เรียกจริง" ไม่ใช่การเอ่ยถึงในคอมเมนต์/docstring
    lock_at = re.search(r"^\s*await _lock_payments_in_order\(", src, re.M)
    assert lock_at, "batch_confirm_payments ไม่ได้ล็อกบิลทั้งชุดตามลำดับ"

    read_at = re.search(r"^\s*rows = await conn\.fetch\(", src, re.M)
    confirm_at = re.search(r"_confirm_single_payment\(", src)
    assert read_at is None or lock_at.start() < read_at.start(), \
        "ล็อกช้ากว่าการอ่าน — ลำดับยังแข่งกันได้"
    assert confirm_at is None or lock_at.start() < confirm_at.start(), \
        "ล็อกช้ากว่าการเขียน — ลำดับยังแข่งกันได้"

# ══════════════════════════════════════════════════════════════ 11. อ่าน / path param
async def test_receipt_number_path_param_is_validated(client, db_pool, admin_headers):
    """`receipt_no` ต้องเป็น str + pattern REC-2569-0042 — รูปแบบผิด 422, ไม่มีจริง 404"""
    room_id = admin_headers.room_id
    # รูปแบบผิด → 422 (ไม่ใช่ 500 และไม่ใช่ 404)
    assert client.get(_url(RECEIPT_PATH, room_id, receipt_no="1234"),
                      headers=admin_headers).status_code == 422
    assert client.get(_url(RECEIPT_PATH, room_id, receipt_no="rec-2569-0001"),
                      headers=admin_headers).status_code == 422
    # รูปแบบถูกแต่ไม่มีในระบบ → 404
    assert client.get(_url(RECEIPT_PATH, room_id, receipt_no="REC-2569-0099"),
                      headers=admin_headers).status_code == 404


async def test_get_receipt_detail_and_list_filters(client, db_pool, admin_headers):
    """รายละเอียด 1 ใบ + ตัวกรอง doc_type / student_id ของหน้ารายการ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_a = await _make_debtor(db_pool, room_id, student_no=99, first_name="สมชาย")
    student_b = await _make_debtor(db_pool, room_id, student_no=100, first_name="สมหญิง")
    _, pay_a = await _make_bill(db_pool, room_id, student_a, amount=700.0)
    _, pay_b = await _make_bill(db_pool, room_id, student_b, amount=900.0)
    assert _pay(client, admin_headers, pay_a, account_id, 700.0).status_code == 200
    # pay_b ยังไม่จ่าย → ใช้ออกใบแจ้งหนี้ได้อย่างเดียว (เส้นทางรับ `student_id`)
    rec_a = _issue(client, admin_headers, pay_a).json()["receipt"]
    inv_b = _issue_invoices(client, admin_headers, [student_b]).json()["receipts"][0]

    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=rec_a["receipt_no"]),
                        headers=admin_headers)
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["receipt_no"] == rec_a["receipt_no"]
    assert d["collection_title"] == "ค่าเทอม"
    assert d["collection_amount"] == 700.0
    assert d["student_no"] == 99
    assert d["room_name"] == "Test Room"
    assert d["amount_text"] == "เจ็ดร้อยบาทถ้วน"

    everything = client.get(_url(RECEIPTS_PATH, room_id), headers=admin_headers)
    assert everything.status_code == 200
    assert len(everything.json()) == 2

    only_receipts = client.get(_url(RECEIPTS_PATH, room_id),
                               params={"doc_type": "receipt"}, headers=admin_headers)
    assert [r["receipt_no"] for r in only_receipts.json()] == [rec_a["receipt_no"]]

    only_invoices = client.get(_url(RECEIPTS_PATH, room_id),
                               params={"doc_type": "invoice"}, headers=admin_headers)
    assert [r["receipt_no"] for r in only_invoices.json()] == [inv_b["receipt_no"]]

    by_student = client.get(_url(RECEIPTS_PATH, room_id),
                            params={"student_id": student_a}, headers=admin_headers)
    assert [r["receipt_no"] for r in by_student.json()] == [rec_a["receipt_no"]]

    # 🧾 ใบแจ้งหนี้รวมยอดไม่มีแคมเปญให้ JOIN ⇒ ชื่อรายการต้องถูก **derive จาก snapshot**
    #    ไม่ใช่ '-' และไม่ใช่ NULL — ครูต้องอ่านทะเบียนแล้วรู้ว่าใบนี้อ้างถึงอะไร
    invoice_row = only_invoices.json()[0]
    assert invoice_row["collection_title"] == "ยอดค้างชำระรวม 1 โครงการ"
    assert invoice_row["collection_id"] is None, "ใบรวมไม่ผูกกับแคมเปญเดียว"

    inv_detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=inv_b["receipt_no"]),
                            headers=admin_headers)
    assert inv_detail.status_code == 200, inv_detail.text
    di = inv_detail.json()
    # ยอดเต็ม = ยอดค้าง + ที่จ่ายแล้ว ⇒ `collection_amount - paid_total_after` = `amount`
    # ตรงกับ "รวมทั้งสิ้น" บนกระดาษ และกับ `remaining` ที่ frontend คำนวณเอง
    assert di["collection_amount"] == 900.0, "ยอดเต็ม = ยอดค้าง + ที่จ่ายแล้ว"
    assert di["collection_amount"] - di["paid_total_after"] == di["amount"]
    assert [it["title"] for it in di["line_items"]] == ["ค่าเทอม"]

    # doc_type นอกเหนือจาก receipt|invoice → 422
    assert client.get(_url(RECEIPTS_PATH, room_id),
                      params={"doc_type": "quote"}, headers=admin_headers).status_code == 422


async def test_get_receipts_filters_by_thai_calendar_day(client, db_pool, admin_headers):
    """ตัวกรองช่วงวันใช้เวลาไทยบน "วันที่ของเอกสาร" (`_DOC_DATE`) — ขอบบนเป็น half-open (+1 วัน)

    ⚠️ เทสต์นี้ยิงด้วยข้อมูลที่ `event_at` ≈ `issued_at` (รับเงินแล้วออกใบเสร็จทันที)
       จึงผ่านได้แม้โค้ดกลับไปกรองด้วย `issued_at` — ตัวที่มีฟันจริงคือ
       `test_date_filter_follows_event_at_not_issued_at` ที่บังคับให้สองค่าห่างกัน 3 เดือน
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=100.0)
    assert _pay(client, admin_headers, payment_id, account_id, 100.0).status_code == 200
    receipt = _issue(client, admin_headers, payment_id).json()["receipt"]

    today_thai = datetime.now(THAI_TZ).date()
    hit = client.get(_url(RECEIPTS_PATH, room_id),
                     params={"start_date": today_thai.isoformat(),
                             "end_date": today_thai.isoformat()},
                     headers=admin_headers)
    assert [r["receipt_no"] for r in hit.json()] == [receipt["receipt_no"]]

    # วันถัดไป → ต้องไม่พบ (พิสูจน์ว่าขอบไม่กว้างเกิน)
    tomorrow = (today_thai + timedelta(days=1)).isoformat()
    miss = client.get(_url(RECEIPTS_PATH, room_id),
                      params={"start_date": tomorrow, "end_date": tomorrow},
                      headers=admin_headers)
    assert miss.json() == []


# ══════════════════════════════════════════════════════════════════════ 11. PDF
async def test_receipt_pdf_streams_with_mocked_gotenberg(client, db_pool, admin_headers):
    """mock การเรียก Gotenberg — suite ต้องไม่ต้องมี Chromium

    ตรวจ HTML ที่ส่งเข้า Gotenberg ด้วย: ต้องมีฟอนต์ฝังเป็น data URI และคำอ่านจำนวนเงิน
    (ถ้าลืม inject `font_faces` เอกสารจะออกมาเป็นกล่องสี่เหลี่ยมโดยที่เทสต์อื่นไม่จับได้)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1500.5)
    assert _pay(client, admin_headers, payment_id, account_id, 1500.5).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    fake_pdf = b"%PDF-1.4\n% fake\n%%EOF\n"
    mock_render = AsyncMock(return_value=fake_pdf)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == fake_pdf
    assert f"receipt-{receipt_no}.pdf" in res.headers["content-disposition"]
    assert res.headers["content-length"] == str(len(fake_pdf))

    assert mock_render.await_count == 1
    html = mock_render.await_args.args[0]
    assert "data:font/ttf;base64," in html, "ฟอนต์ไทยต้องถูกฝังเป็น data URI"
    assert html.count("data:font/ttf;base64,") == 2, "ต้องมีทั้ง Regular และ Bold"
    assert "font-weight: 400" in html and "font-weight: 700" in html
    assert "หนึ่งพันห้าร้อยบาทห้าสิบสตางค์" in html
    # เทมเพลตต้องไม่เหลือ placeholder ที่ render ไม่ได้
    assert "{{" not in html and "{%" not in html
    # ชื่อ/เลขเอกสารของใบนั้นต้องอยู่ในเอกสาร
    assert receipt_no in html
    assert "เด็กชายทดสอบ" in html


async def test_invoice_pdf_uses_billing_wording_not_receipt_wording(client, db_pool, admin_headers):
    """ใบแจ้งหนี้ต้องไม่พูดว่า "ได้รับเงินจาก" (ยังไม่ได้รับ) และไม่เหลือ "None" บนเอกสาร"""
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    # สองบิลที่ยังไม่จ่าย ⇒ ใบเดียวต้องแจกแจง **สองบรรทัด** และยอดพาดหัว = 700 + 500
    await _make_bill(db_pool, room_id, student_id, amount=1200.0)
    await _make_bill(db_pool, room_id, student_id, amount=500.0)
    receipt_no = _issue_invoices(
        client, admin_headers, [student_id]
    ).json()["receipts"][0]["receipt_no"]

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    assert "invoice-" + receipt_no + ".pdf" in res.headers["content-disposition"]

    html = mock_render.await_args.args[0]
    assert "เรียกเก็บจาก" in html
    assert "ได้รับเงินจาก" not in html
    assert "ผู้รับแจ้ง" in html
    assert ">None<" not in html and " None " not in html

    # 📋 ตารางแจกแจงต้องโผล่ พร้อมบรรทัด "รวมทั้งสิ้น" ที่เท่ากับยอดพาดหัว
    assert "ยอดค้างชำระรวม 2 โครงการ" in html
    assert html.count("ค่าเทอม") == 2, "ต้องมีสองบรรทัด (บิลละบรรทัด) จาก snapshot"
    assert "รวมทั้งสิ้น" in html
    assert "1,700.00" in html, "ยอดพาดหัวต้องเป็นผลรวมของทุกบิลที่ค้าง"
    # 🔴 snapshot ต้องเป็นสำเนา ไม่ใช่การอ้างถึงบิล — พิมพ์ซ้ำหลังจ่ายบางส่วนต้องได้เลขเดิม
    assert "1,200.00" in html and "500.00" in html


async def test_pdf_render_failure_maps_to_502(client, db_pool, admin_headers):
    """Gotenberg ใช้งานไม่ได้ → 502 (ไม่ใช่ 500 ที่แปลว่าโค้ดเราพัง)

    และข้อความที่ส่งถึงผู้ใช้ต้องเป็นข้อความ **กลาง ๆ ที่ไม่มีชื่อ upstream**
    (ก่อนหน้านี้เทสต์นี้ assert ว่า detail ต้องมีคำว่า "Gotenberg" ซึ่งล็อกนโยบายเก่า
    ที่บอกชื่อระบบภายในให้สมาชิกทุกคนของห้องอ่าน — ดูข้อ 12.5 ที่ทดสอบต้นทาง)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=200.0)
    assert _pay(client, admin_headers, payment_id, account_id, 200.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    # จำลอง service ที่ "ทำถูกแล้ว" คือโยนข้อความกลาง ๆ ออกมา (ไม่ใช่ URL)
    from services.finance.constants import PDF_RENDER_UNAVAILABLE_MSG

    boom = AsyncMock(side_effect=PdfRenderError(PDF_RENDER_UNAVAILABLE_MSG))
    with patch("services.finance.pdf.html_to_pdf", new=boom):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 502, res.text

    detail = res.json()["detail"]
    assert PDF_RENDER_UNAVAILABLE_MSG in detail
    # 502 ยังต้องบอกผู้ใช้ว่าลองใหม่ได้ — ไม่ใช่ปล่อยเป็นความผิดพลาดที่ดูถาวร
    assert "ลองใหม่" in detail
    # 🔒 ห้ามมีชื่อระบบภายใน ไม่ว่าจะเขียนแบบไหน
    for leaked in ("Gotenberg", "gotenberg", "http", "localhost", "3000"):
        assert leaked not in detail, f"502 detail หลุดคำว่า {leaked!r}: {detail}"


async def test_pdf_of_unknown_receipt_is_404(client, db_pool, admin_headers):
    """เลขที่ไม่มีจริง → 404 ก่อนถึงขั้นตอนเรนเดอร์ (ไม่เสียเวลาเรียก Gotenberg)"""
    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, admin_headers.room_id, receipt_no="REC-2569-0099"),
                         headers=admin_headers)
    assert res.status_code == 404, res.text
    assert mock_render.await_count == 0


@pytest.mark.skipif(
    gotenberg_configured() is None,
    reason="ไม่มี Gotenberg จริงในสภาพแวดล้อมนี้ (GOTENBERG_URL เป็นค่า default/localhost)",
)
async def test_receipt_pdf_against_real_gotenberg(client, db_pool, admin_headers):
    """เทสต์จริง 1 ตัว — ข้ามอัตโนมัติเมื่อไม่มี service (ค่า default คือ localhost)

    ตรวจว่าได้ PDF จริง (magic bytes) และมีฟอนต์ TrueType ฝังอยู่ ไม่ใช่ Type 3
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1500.0)
    assert _pay(client, admin_headers, payment_id, account_id, 1500.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.content.startswith(b"%PDF-")
    assert len(res.content) > 10_000
    # 🔴 ฟอนต์ไทยต้องถูก "ฝังจริง" เป็น TrueType — ไม่ใช่ Type 3 ที่ Chromium ถอยไปใช้
    #    เมื่อเจอ variable font (ดู constants.RECEIPT_FONT_FILES) ⇒ ถ้าเทสต์นี้ fail
    #    แปลว่าเทมเพลตกลับไปใช้ `font-weight: <ช่วง>` หรือเปลี่ยนไปใช้ฟอนต์ตัวแปรอีก
    assert _pdf_has_embedded_truetype(res.content), (
        "PDF ไม่มี /FontFile2 — ฟอนต์ไม่ได้ถูกฝังเป็น TrueType (อาจถอยไปเป็น Type 3)"
    )


# ═══════════════════════════════════════════════════════ 12. regression จากรอบรีวิว
#
# ทุกเทสต์ในหัวข้อนี้ "ต้อง fail กับโค้ดก่อนหน้า" — ถ้าเขียนแล้วผ่านทันทีแปลว่าไม่ได้กันอะไร
# (ยกเว้นข้อ 12.6 ที่ปิดช่อง coverage ที่เดิม skip ตลอด)
#
# ที่มา: การรีวิวแบบ adversarial 7 มิติบน changeset ของ F3 พบ 12 ประเด็นที่รอดการหักล้าง
# และ 4 ในนั้นเป็นบั๊กจริงที่ต้องแก้ ⇒ เทสต์ชุดนี้คือหลักฐานว่ามันถูกแก้จริงและจะไม่กลับมา


async def test_invoice_year_be_follows_the_issue_date_not_the_last_instalment(
    client, db_pool, admin_headers
):
    """ใบแจ้งหนี้ต้องใช้ปี พ.ศ. ของ **วันออกเอกสาร** ไม่ใช่ปีของงวดที่จ่ายล่าสุด

    บั๊กเดิม: ใบแจ้งหนี้ส่ง `event_at = pay["paid_at"]` เข้าไปคำนวณปี
    `paid_at` ถูก `_confirm_single_payment` **ทับด้วย NOW() ทุกงวด** ⇒ มันคือเวลาของ
    "งวดล่าสุด" ไม่ใช่เวลาของเหตุการณ์ตั้งต้น ⇒ บิลที่ผ่อนจ่ายไว้เมื่อปลายปีก่อน
    จะได้เลข INV ของ **ปีที่แล้ว** ทั้งที่เอกสารลงวันที่ปีนี้

    💥 ที่สำคัญคือความไม่สม่ำเสมอในวันเดียวกัน: บิลที่ยังไม่จ่ายเลย (`paid_at IS NULL`)
    ได้เลขของวันนี้ ส่วนบิลที่ผ่อนแล้วได้เลขของปีที่แล้ว ⇒ สองใบที่ออกห่างกันไม่กี่นาที
    อยู่คนละชุดเลข ซึ่งอธิบายให้ผู้ตรวจสอบไม่ได้ (เทสต์คู่อยู่ในข้อถัดไป)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)
    # 🔴 ผ่อนผ่าน **เส้นทางรับเงินจริง** ไม่ใช่ `_make_bill(paid_amount=...)`:
    #    ตัวนั้นตั้ง `status='paid'` ทันทีที่มียอดจ่าย ⇒ บิลจะหลุด predicate `SP.status='pending'`
    #    ของใบแจ้งหนี้ แล้วเทสต์จะได้ 400 แทนที่จะได้ใบ (ผ่านโดยไม่ได้ทดสอบปี พ.ศ. เลย)
    #    การจ่ายบางส่วนผ่าน `_confirm_single_payment` เท่านั้นที่คง `status='pending'` ไว้
    assert _pay(client, admin_headers, payment_id, account_id, 300.0).status_code == 200

    # จำลองสภาพจริงหลัง "ผ่อนงวดแรกเมื่อปลายปีที่แล้ว"
    # `paid_at` เป็น TIMESTAMP naive ที่เก็บ UTC (core/init_db.py) → ส่ง naive เข้าไปตรง ๆ
    previous_year_be = 2025 + BUDDHIST_ERA_OFFSET
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET paid_at = $2 WHERE id = $1",
            payment_id, datetime(2025, 11, 15, 4, 0),
        )

    today_be = datetime.now(timezone.utc).astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    # การ์ดกันเทสต์กลายเป็นโมฆะ: ถ้ารันในปี 2568 ทั้งสองฝั่งจะเท่ากันแล้วจับบั๊กไม่ได้
    assert today_be != previous_year_be, (
        f"เทสต์นี้ต้องรันในปี พ.ศ. ที่ไม่ใช่ {previous_year_be} (ปีนี้คือ {today_be})"
    )

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    doc = res.json()["receipts"][0]

    assert doc["year_be"] == today_be, (
        f"ใบแจ้งหนี้ได้ปี {doc['year_be']} แต่ปีของวันออกเอกสารคือ {today_be} "
        f"— แปลว่าปีหลุดมาจาก paid_at ของงวดล่าสุดอีกแล้ว"
    )
    assert doc["receipt_no"] == f"INV-{today_be}-0001"

    # ตัวนับถูกสร้าง/กินที่ปีของวันนี้เท่านั้น — ต้องไม่มีแถวของปีเก่าผุดขึ้นมา
    assert await _db_last_seq(db_pool, room_id, today_be, "invoice") == 1
    assert await _db_last_seq(db_pool, room_id, previous_year_be, "invoice") is None


async def test_invoice_year_is_the_same_for_a_paid_and_an_unpaid_bill(
    client, db_pool, admin_headers
):
    """บิลที่ยังไม่จ่ายเลย กับบิลที่ผ่อนไปแล้ว ต้องออกใบแจ้งหนี้ชุดเลขเดียวกันในวันเดียว

    นี่คือหน้าตาของบั๊กที่ผู้ใช้สังเกตได้จริง และเป็นเหตุผลที่ข้อ 12.1 ต้องมีคู่:
    ถ้าปีมาจาก `paid_at` สองใบนี้จะอยู่คนละชุดเลขทั้งที่ออกวันเดียวกัน
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    today_be = datetime.now(timezone.utc).astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET

    # (ก) บิลที่ยังไม่เคยจ่ายเลย → paid_at IS NULL
    unpaid_student = await _make_debtor(db_pool, room_id, student_no=94)
    _, unpaid_payment = await _make_bill(db_pool, room_id, unpaid_student, amount=500.0)

    # (ข) บิลที่ผ่อนไว้เมื่อปีที่แล้ว → paid_at เป็นของปีก่อน
    #    ⚠️ ผ่อนผ่านเส้นทางรับเงินจริงเท่านั้น — `_make_bill(paid_amount=...)` ตั้ง
    #       `status='paid'` ซึ่งทำให้บิลหายไปจาก predicate ของใบแจ้งหนี้ (เหตุผลเดียวกับข้อ 12.1)
    paid_student = await _make_debtor(db_pool, room_id, student_no=95)
    _, paid_payment = await _make_bill(db_pool, room_id, paid_student, amount=1000.0)
    assert _pay(client, admin_headers, paid_payment, account_id, 400.0).status_code == 200
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE student_payments SET paid_at = $2 WHERE id = $1",
            paid_payment, datetime(2025, 3, 2, 4, 0),
        )

    first = _issue_invoices(client, admin_headers, [unpaid_student])
    second = _issue_invoices(client, admin_headers, [paid_student])
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    years = {first.json()["receipts"][0]["year_be"], second.json()["receipts"][0]["year_be"]}
    assert years == {today_be}, (
        f"ใบแจ้งหนี้สองใบที่ออกวันเดียวกันได้ปี {years} — ต้องเป็นชุดเลข {today_be} ทั้งคู่"
    )
    # ต่อเนื่องกันจริง: 0001 แล้ว 0002 ในชุดเดียว (ไม่ใช่คนละชุดแล้วซ้ำเลขกัน)
    assert first.json()["receipts"][0]["receipt_no"] == f"INV-{today_be}-0001"
    assert second.json()["receipts"][0]["receipt_no"] == f"INV-{today_be}-0002"
    assert await _db_last_seq(db_pool, room_id, today_be, "invoice") == 2


async def test_doc_number_overflow_is_rejected_and_does_not_burn_the_number(
    client, db_pool, admin_headers
):
    """seq ครบ 9999 แล้วต้อง **ปฏิเสธพร้อมข้อความที่อ่านรู้เรื่อง** ไม่ใช่เก็บเลขที่เปิดไม่ได้

    ทำไมต้องมีเพดาน: `RECEIPT_NO_TEMPLATE` ใช้ `{seq:04d}` ซึ่ง **กว้างขึ้นเอง** เป็น 5 หลัก
    เมื่อเกิน 9999 (ไม่ error) แต่ `RECEIPT_NO_PATTERN` — ซึ่งเป็น path param ของ
    GET detail/PDF — บังคับ 4 หลัก ⇒ ใบที่ 10000 จะ INSERT สำเร็จและโผล่ในทะเบียน
    แต่ **เปิดดู/พิมพ์ซ้ำไม่ได้ตลอดกาล (422)** ซึ่งเป็นเอกสารที่ออกให้ผู้ปกครองไปแล้ว

    ⚠️ และต้อง **ไม่เผาเลข**: `raise` อยู่ใน `conn.transaction()` เดียวกับการจองเลข
       ⇒ last_seq ต้อง rollback กลับเป็น 9999 ไม่ใช่ค้างที่ 10000
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=250.0)
    assert _pay(client, admin_headers, payment_id, account_id, 250.0).status_code == 200

    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, 'receipt', $3)""",
            room_id, year_be, RECEIPT_SEQ_MAX,          # 9999 → ใบถัดไปคือ 10000
        )

    res = _issue(client, admin_headers, payment_id)
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == RECEIPT_SEQ_OVERFLOW_MSG

    # ไม่มีแถวถูกเขียน และเลขไม่ถูกเผา
    assert await _db_receipt_count(db_pool, room_id) == 0
    assert await _db_last_seq(db_pool, room_id, year_be, "receipt") == RECEIPT_SEQ_MAX, (
        "เลขถูกเผา — last_seq ต้อง rollback กลับมาเท่าเดิม"
    )


async def test_the_last_available_seq_is_still_openable_by_its_doc_number(
    client, db_pool, admin_headers
):
    """seq 9999 (เลขสุดท้ายที่ยัง 4 หลัก) ต้อง **เปิดดูได้จริง** ด้วยเลขนั้น

    เทสต์นี้ผูก `RECEIPT_SEQ_MAX` เข้ากับ `RECEIPT_NO_PATTERN` ของ route จริง
    ⇒ ถ้ามีใครขยับเพดานขึ้นเป็น 99999 โดยไม่แก้ pattern เทสต์นี้จะ fail ทันที
    (ต่างจากเทสต์ 12.3 ที่พิสูจน์ "ปฏิเสธเมื่อเกิน" — อันนี้พิสูจน์ "ขอบบนยังใช้ได้")
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=250.0)
    assert _pay(client, admin_headers, payment_id, account_id, 250.0).status_code == 200

    year_be = datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
               VALUES ($1, $2, 'receipt', $3)""",
            room_id, year_be, RECEIPT_SEQ_MAX - 1,      # → ใบนี้ได้ 9999
        )

    res = _issue(client, admin_headers, payment_id)
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipt"]["receipt_no"]
    assert receipt_no == f"REC-{year_be}-{RECEIPT_SEQ_MAX:04d}"
    assert re.fullmatch(RECEIPT_NO_PATTERN, receipt_no), (
        f"เลขเอกสาร {receipt_no} ไม่ตรงกับ pattern ของ path param — จะเปิดกลับไม่ได้"
    )

    # พิสูจน์กับ route จริง ไม่ใช่แค่ regex
    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["receipt_no"] == receipt_no


async def test_pdf_failure_message_carries_no_internal_url():
    """ข้อความ 502 ที่ผู้ใช้เห็นต้อง **ไม่มี URL/hostname ภายใน**

    เส้นทาง PDF เปิดแค่ `require_member` ⇒ สมาชิกทุกคนของห้อง (รวมนักเรียน) อ่านได้
    ⇒ ชื่อ container/hostname ภายในเป็นข้อมูลที่ไม่ควรหลุดออกไป และไม่ช่วยให้ใครแก้ปัญหาได้
    รายละเอียดจริงถูก log ไว้ฝั่ง server แทน (ดู services/finance/pdf.py)

    ⚠️ เทสต์นี้ทดสอบ `html_to_pdf` ตรง ๆ (ไม่ผ่าน HTTP) เพื่อจับ **ข้อความต้นทาง**
       ไม่ใช่ข้อความที่ router ต่อเติม — ถ้าต้นทางมี URL ต่อให้ router ตัดทิ้งก็ไม่หาย

    🔴 ประวัติ: รอบแรกแก้ไปแค่ 2 สาขาของ `html_to_pdf` แล้ว **เหลืออีก 3 จุดที่ raise**
       (`_font_data_uri` ใส่ path เต็ม, `_get_template` ใส่ path เต็ม, สาขา 200-แต่เนื้อหาว่าง
       เอ่ยชื่อ "Gotenberg") — เทสต์เดิมผ่านทั้งที่ยังหลุด เพราะมันแตะไม่ถึงสามจุดนั้น
       ⇒ เทสต์นี้จึงต้องครอบ **ทุกจุดที่ raise PdfRenderError** ไม่ใช่แค่จุดที่ถูกชี้ในรายงาน
          (และ router ก็ต่อ `str(e)` ตรง ๆ ⇒ ตรวจที่ router ไม่มีทางจับได้เลย)
    """
    from pathlib import Path

    from services.finance import pdf as pdf_module
    from services.finance.constants import (
        PDF_ASSET_MISSING_MSG, PDF_RENDER_FAILED_MSG, PDF_RENDER_UNAVAILABLE_MSG,
    )

    internal_host = "classroom-management_pdf_gotenberg"

    # (ก) ต่อไม่ติด — ข้อความของ httpx มี URL ติดมาด้วย ต้องไม่รอดออกไป
    async def _refuse(*_args, **_kwargs):
        raise httpx.ConnectError(f"All connection attempts failed: http://{internal_host}:3000")

    with patch.object(pdf_module.httpx.AsyncClient, "post", new=_refuse):
        with pytest.raises(PdfRenderError) as excinfo:
            await pdf_module.html_to_pdf("<html></html>")

    unavailable = str(excinfo.value)
    assert unavailable == PDF_RENDER_UNAVAILABLE_MSG
    assert internal_host not in unavailable
    assert "http" not in unavailable.lower()
    assert "connect" not in unavailable.lower()

    # (ข) Gotenberg ตอบไม่ใช่ 200 — เนื้อหาดิบจาก upstream ก็ต้องไม่รอดออกไป
    upstream_body = b"<html>Chromium exited with code 1 at /tmp/chromium-xyz</html>"
    with patch.object(
        pdf_module.httpx.AsyncClient, "post",
        new=AsyncMock(return_value=httpx.Response(500, content=upstream_body)),
    ):
        with pytest.raises(PdfRenderError) as excinfo:
            await pdf_module.html_to_pdf("<html></html>")

    failed = str(excinfo.value)
    assert failed == PDF_RENDER_FAILED_MSG
    assert "/tmp/chromium-xyz" not in failed
    assert internal_host not in failed
    assert "http" not in failed.lower()

    # (ค) Gotenberg ตอบ 200 แต่เนื้อหาว่าง — ไม่มี URL แต่มี **ชื่อ service ภายใน**
    #     ซึ่งเข้าข่ายเดียวกัน (และขัดกับเทสต์ที่ห้ามคำนี้ในสองสาขาข้างบน)
    with patch.object(
        pdf_module.httpx.AsyncClient, "post",
        new=AsyncMock(return_value=httpx.Response(200, content=b"")),
    ):
        with pytest.raises(PdfRenderError) as excinfo:
            await pdf_module.html_to_pdf("<html></html>")

    empty = str(excinfo.value)
    assert empty == PDF_RENDER_FAILED_MSG
    assert "gotenberg" not in empty.lower()

    # (ง) ไฟล์ประกอบของฝั่งเราหาย (ฟอนต์ / เทมเพลต) — เดิมสาขาพวกนี้ใส่ **path เต็มบนเซิร์ฟเวอร์**
    #     เช่น `/app/assets/fonts/NotoSansThai-Regular.ttf` ลงในข้อความที่ผู้ใช้อ่าน
    try:
        with patch.object(pdf_module, "FONT_DIR", Path("/nowhere/assets/fonts")):
            pdf_module._font_data_uri.cache_clear()
            with pytest.raises(PdfRenderError) as excinfo:
                pdf_module._font_data_uri("regular")
        font_msg = str(excinfo.value)
        assert font_msg == PDF_ASSET_MISSING_MSG
        assert "/nowhere" not in font_msg
        assert "assets" not in font_msg
        assert ".ttf" not in font_msg

        with patch.object(
            pdf_module, "TEMPLATE_PATH", Path("/nowhere/templates/receipt.html")
        ):
            pdf_module._get_template.cache_clear()
            with pytest.raises(PdfRenderError) as excinfo:
                pdf_module._get_template()
        tpl_msg = str(excinfo.value)
        # ไม่ว่า jinja2 จะถูกติดตั้งหรือไม่ ทั้งสองเส้นทางต้องให้ข้อความกลางตัวเดียวกัน
        assert tpl_msg == PDF_ASSET_MISSING_MSG
        assert "/nowhere" not in tpl_msg
        assert ".html" not in tpl_msg
    finally:
        # 🧹 คืน cache ให้ว่าง — เทสต์ถัดไปต้องอ่านไฟล์จริงต่อ ไม่ใช่ค่าที่ patch ไว้
        pdf_module._font_data_uri.cache_clear()
        pdf_module._get_template.cache_clear()

    # ทุกข้อความยังบอกผู้ใช้ว่าต้องทำอะไรต่อ — ไม่ใช่แค่ "error" เปล่า ๆ
    assert "ลองใหม่" in unavailable and "ลองใหม่" in failed and "ลองใหม่" in empty
    assert "ผู้ดูแลระบบ" in font_msg and "ผู้ดูแลระบบ" in tpl_msg


def _ttf_table_tags(path) -> set:
    """อ่านสารบัญตาราง (table directory) ของไฟล์ TTF/OTF → เซ็ตของ tag

    โครงสร้าง: sfntVersion(4) + numTables(2) + searchRange/entrySelector/rangeShift(6)
    แล้วตามด้วย table record ขนาด 16 ไบต์ต่อตาราง: tag(4) + checkSum(4) + offset(4) + length(4)
    ⇒ tag ของตารางที่ i เริ่มที่ไบต์ 12 + i*16
    """
    import struct
    from pathlib import Path

    from services.finance.constants import RECEIPT_FONT_DIR

    backend_root = Path(__file__).resolve().parents[1]
    data = (backend_root / RECEIPT_FONT_DIR / path).read_bytes()

    sfnt_version = data[:4]
    assert sfnt_version in (b"\x00\x01\x00\x00", b"true", b"OTTO"), (
        f"{path} ไม่ใช่ไฟล์ sfnt ที่อ่านได้ (sfntVersion={sfnt_version!r})"
    )
    (num_tables,) = struct.unpack(">H", data[4:6])
    assert 0 < num_tables < 200, f"{path}: จำนวนตารางผิดปกติ ({num_tables})"

    return {data[12 + i * 16: 16 + i * 16].decode("latin-1") for i in range(num_tables)}


@pytest.mark.parametrize("font_key", sorted(RECEIPT_FONT_FILES))
async def test_receipt_fonts_are_static_so_chromium_embeds_them_as_truetype(font_key):
    """ฟอนต์ที่ commit ไว้ต้องเป็น **static TrueType** ไม่ใช่ variable font

    🕳️ ปิดช่องที่เดิมมีแต่เทสต์ที่ skip ตลอด: `test_receipt_pdf_against_real_gotenberg`
    เป็นเทสต์เดียวที่จับ "Chromium ถอยไปเป็น Type 3" ได้ และมัน skip ทุกครั้งที่ไม่มี
    Gotenberg จริง (รวมทั้งใน CI) ⇒ การสลับฟอนต์กลับไปเป็นตัวแปรจะผ่านทุกเทสต์
    เงียบ ๆ แล้วเพิ่งไปพังตอน deploy จริง

    ตรวจที่ **สาเหตุ** ไม่ใช่ที่อาการ: Skia embed ฟอนต์ตัวแปรลง PDF ไม่ได้ จึงวาด glyph
    เป็น Type 3 (ไฟล์ใหญ่ 5.5 เท่า + ร้านพิมพ์ไม่รับ) ⇒ ฟอนต์ที่มีตาราง `fvar`
    (นิยามแกนของ variable font) คือตัวที่ทำให้เกิดปัญหานั้น ตรวจได้โดยไม่ต้องมี Chrome
    """
    filename = RECEIPT_FONT_FILES[font_key][0]
    tags = _ttf_table_tags(filename)

    assert "fvar" not in tags, (
        f"{filename} เป็น **variable font** (มีตาราง fvar) — Chromium/Skia จะ embed "
        f"ลง PDF ไม่ได้และถอยไปวาดเป็น Type 3 ⇒ ต้องใช้ไฟล์ static แยกตามน้ำหนัก"
    )
    assert "glyf" in tags, (
        f"{filename} ไม่มีตาราง glyf ⇒ ไม่ใช่ TrueType แบบ outline "
        f"(ถ้าเป็น CFF/OpenType Chromium จะแปลงเป็น Type 1C ไม่ใช่ CID TrueType)"
    )
    assert "CFF " not in tags, (
        f"{filename} เป็น OpenType/CFF (ตาราง CFF) — ต้องเป็น TrueType ที่มี glyf"
    )
    # 🧪 sanity: ตารางพื้นฐานที่ฟอนต์ที่ใช้งานได้ต้องมี (กันการ parse ผิดไฟล์)
    assert {"head", "hhea", "hmtx", "cmap", "name", "post", "maxp"} <= tags, (
        f"{filename}: สารบัญตารางไม่ครบ ไม่เหมือนไฟล์ฟอนต์ที่ใช้งานได้ (ได้ {sorted(tags)})"
    )


async def test_receipt_template_declares_one_font_face_per_weight():
    """เทมเพลตต้องมี @font-face **หนึ่งอันต่อหนึ่งน้ำหนัก** และไม่มี `font-weight: <ช่วง>`

    `font-weight: 100 900` คือรูปแบบที่ใช้กับ variable font — ถ้ามันกลับมา
    ต่อให้ไฟล์ฟอนต์ยังเป็น static เบราว์เซอร์ก็จะ match ผิด/สังเคราะห์ตัวหนาเอง
    ⇒ ต้องเป็นเลขเดี่ยว (`{{ f.weight }}` ซึ่งมาจาก RECEIPT_FONT_FILES)

    ⚠️ เทสต์นี้ไม่ต้องมี DB เลย — `render_receipt_html` ฉีด `font_faces` ให้เอง
       ที่เหลือของเทมเพลตเป็น `{{ x or '-' }}` / `{% if x %}` ทั้งหมด **ยกเว้นสองกรณี**:
         • ตัวเลขที่จัดรูปด้วย `"{:,.2f}".format(...)` ⇒ ต้องส่งมาให้ครบทั้ง 4 ตัว
           (Jinja2 เรียก `__format__` บน `Undefined` ไม่ได้ → TypeError ไม่ใช่ช่องว่าง)
         • 🔴 `body_template` — ตั้งแต่แยกเทมเพลตเป็น partial (shell + `{% include %}`)
           คีย์นี้ **ขาดไม่ได้** เพราะ `{% include Undefined %}` โยน `UndefinedError`
           (ต่างจาก `{{ Undefined }}` ที่เรนเดอร์เป็นช่องว่าง) ⇒ ต้องเป็นชื่อไฟล์ partial จริง
       ถ้าเพิ่มฟิลด์ใหม่ในเทมเพลตแล้วเทสต์นี้พัง ให้เติมคีย์ที่นี่ **ไม่ใช่**
       ไปทำให้เทมเพลตกลืน Undefined — การพังคือสัญญาณว่ามีฟิลด์ใหม่ที่ยังไม่มีใครครอบ
       🔴 และ **ห้ามใส่ default ให้ `{% include d.body_template or … %}`** เด็ดขาด:
       ใบสำคัญจ่ายที่ `_document_context` ลืมตั้งคีย์นี้จะ **พิมพ์ถ้อยคำใบเสร็จทั้งใบ
       โดยไม่มี error** ซึ่งคือกับดักที่การแยก body template มีไว้ป้องกันตั้งแต่แรก
    """
    from services.finance.pdf import render_receipt_html

    html = render_receipt_html({
        # 4 ฟิลด์ตัวเลขในเทมเพลต (receipt.html บรรทัด 136, 140, 147, 154, 159, 164)
        "amount": 1234.5,
        "collection_amount": 2000.0,
        "paid_total_after": 1234.5,
        "remaining": 765.5,
        "amount_text": "หนึ่งพันสองร้อยสามสิบสี่บาทห้าสิบสตางค์",
        "is_receipt": True,
        # 🔴 partial ที่ shell จะ `{% include %}` — คีย์บังคับ ไม่มี default โดยเจตนา
        "body_template": "_receipt_body.html",
    })

    # ⚠️ ต้องตัด CSS comment ออกก่อนตรวจ — เทมเพลตมีคอมเมนต์ เตือนเรื่อง
    #    "@font-face ต่อหนึ่งไฟล์" และยกตัวอย่าง "font-weight: 100 900" ว่าเป็นสิ่งต้องห้าม
    #    ⇒ ถ้าไม่ตัดออก จะนับคำเตือนเป็นโค้ดจริงแล้วเทสต์ fail ทั้งที่เทมเพลตถูก
    #    (คอมเมนต์ ของ Jinja2 `{# #}` ถูกตัดทิ้งตอน render อยู่แล้ว จึงเหลือแต่ CSS)
    css = re.sub(r"/\*.*?\*/", "", html, flags=re.S)

    assert css.count("@font-face {") == len(RECEIPT_FONT_FILES) == 2, (
        f"ต้องมี @font-face หนึ่งอันต่อหนึ่งน้ำหนัก (พบ {css.count('@font-face {')} อัน "
        f"จากฟอนต์ {len(RECEIPT_FONT_FILES)} ไฟล์)"
    )
    for _, weight in RECEIPT_FONT_FILES.values():
        assert f"font-weight: {weight};" in css
    # ไม่มีช่วงน้ำหนักเหลืออยู่ (รูปแบบของ variable font)
    assert not re.search(r"font-weight:\s*\d+\s+\d+", css), (
        "พบ `font-weight: <ช่วง>` — นั่นคือรูปแบบของ variable font ซึ่งทำให้ Skia ถอยไป Type 3"
    )


async def test_pdf_prints_thai_buddhist_dates_that_agree_with_its_own_doc_number(
    client, db_pool, admin_headers
):
    """บรรทัดวันที่บนเอกสารต้องเป็น **พ.ศ. + ชื่อเดือนไทย** ไม่ใช่ ISO/ค.ศ.

    เอกสารใบเดียวกันมีเลขที่เป็น พ.ศ. อยู่แล้ว (`REC-2569-0042`) ⇒ ถ้าบรรทัดวันที่เป็น
    ค.ศ. (`2026-09-13`) เอกสารจะ **ขัดแย้งกับตัวเอง** ซึ่งเป็นสิ่งที่ผู้ตรวจสอบ/bัญชี
    จับได้ทันทีและเสียความน่าเชื่อถือทั้งใบ · เป็นบั๊กที่เทสต์อื่นจับไม่ได้เลยเพราะ
    `receipt_no` ยังถูกต้องทุกตัวอักษร

    ⚠️ เทสต์นี้ **คำนวณค่าที่คาดหวังเอง** (zoneinfo + ชื่อเดือนไทยเขียนตรง ๆ) ไม่เรียก
       `_thai_datetime_text` ของ service — ถ้าเรียก ก็เท่ากับเอาฟังก์ชันที่ถูกทดสอบ
       มาตั้งโจทย์ให้ตัวเอง แล้วเทสต์จะผ่านตลอดแม้ชื่อเดือนไทยจะสะกดผิด
    """
    from zoneinfo import ZoneInfo

    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1500.0)
    assert _pay(client, admin_headers, payment_id, account_id, 1500.0).status_code == 200
    issued = _issue(client, admin_headers, payment_id)
    assert issued.status_code == 200, issued.text
    receipt_no = issued.json()["receipt"]["receipt_no"]

    async with db_pool.acquire() as conn:
        # 🗓️ อ่าน `event_at` **ไม่ใช่ `issued_at`** — บรรทัดวันที่บนกระดาษต้องเป็น
        #    "เวลาของเหตุการณ์รับเงิน" ไม่ใช่เวลาที่กดพิมพ์/กดออกเอกสาร
        #    (เทสต์ `test_printed_date_follows_the_payment_event_not_the_print_time`
        #     แยกไว้อีกตัวเพื่อพิสูจน์ส่วนนี้ให้ชัดด้วยการบังคับให้สองค่าต่างกันจริง)
        issued_at = await conn.fetchval(
            "SELECT event_at FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )
    assert issued_at is not None, "ใบเสร็จที่ผูกกับเหตุการณ์รับเงินต้องมี event_at เสมอ"

    # ── คำนวณค่าที่ควรพิมพ์เอง (อิสระจากโค้ดที่ถูกทดสอบ) ──
    thai = issued_at.astimezone(ZoneInfo("Asia/Bangkok"))
    months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
              "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    year_be = thai.year + 543
    year_ce = thai.year
    expected_date = f"{thai.day} {months[thai.month - 1]} {year_be} {thai.strftime('%H:%M')} น."

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    html = mock_render.await_args.args[0]

    # (ก) วันที่ที่พิมพ์ต้องตรงกับ พ.ศ./ชื่อเดือนไทย/เวลาของใบนั้น
    assert expected_date in html, (
        f"ไม่พบวันที่ไทย {expected_date!r} บนเอกสาร — บรรทัดวันที่อาจกลับไปเป็น ISO/ค.ศ."
    )
    # เลขเอกสารกับวันที่ต้องเป็นปี พ.ศ. เดียวกัน (เอกสารไม่ขัดแย้งกับตัวเอง)
    assert str(year_be) in receipt_no
    # (ข) ห้ามมี ค.ศ. โผล่ที่ไหนเลย — มันจะขัดกับเลขเอกสารที่เป็น พ.ศ.
    assert str(year_ce) not in html, (
        f"พบปี ค.ศ. {year_ce} บนเอกสารที่มีเลขเป็น พ.ศ. ({receipt_no}) — เอกสารขัดแย้งกับตัวเอง"
    )
    assert re.search(rf"\b{year_ce}-\d{{2}}-\d{{2}}\b", html) is None, "พบวันที่แบบ ISO"

    # (ค) กำหนดชำระ (DATE ล้วน) ก็ต้องเป็น พ.ศ. + ชื่อเดือนไทย ไม่มีเวลาติดมา
    #     bill ตั้ง due_date = 2026-12-31 → "31 ธ.ค. 2569"
    assert "31 ธ.ค. 2569" in html, (
        "กำหนดชำระต้องเป็น พ.ศ. แบบไม่มีเวลาติด — ถ้ามี 07:00 โผล่มาแปลว่าใช้ตัวจัดรูปเวลากับฟิลด์ DATE"
    )
    assert "07:00" not in html


# ══════════════════════════════ 13. 🗓️ "วันที่ของเอกสาร" = เวลาของเหตุการณ์ (#62)
# 🎯 กฎที่เทสต์ชุดนี้ล็อกไว้: **ทั้งปี พ.ศ. บนเลขเอกสาร และวันที่ที่พิมพ์บนกระดาษ
#    ต้องมาจาก "เวลาไทย ณ วินาทีที่บันทึกการจ่ายเงิน" ค่าเดียวกันเสมอ**
#    ⇒ เปิดดู/พิมพ์ซ้ำเมื่อไรก็ได้วันเดิม ไม่ขึ้นกับว่ากดตอนไหน
#
# ⚠️ ทำไมต้องมีเทสต์ที่ "บังคับให้สองค่าต่างกันจริง": เทสต์ที่รับเงินแล้วออกใบเสร็จทันที
#    จะมี `event_at` ≈ `issued_at` (ห่างกันไม่กี่มิลลิวินาที) ⇒ โค้ดที่เผลอกลับไปใช้
#    `issued_at` จะ **ผ่านทุกเทสต์** แล้วเพิ่งไปพังกับใบเสร็จที่ออกย้อนหลังข้ามวัน/ข้ามปี
async def test_event_at_is_the_payment_moment_that_the_doc_number_was_built_from(
    client, db_pool, admin_headers
):
    """`event_at` ต้องเป็นเวลาของ **แถวเหตุการณ์รับเงิน** ไม่ใช่เวลาที่ออกเอกสาร"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)
    assert _pay(client, admin_headers, payment_id, account_id, 1000.0).status_code == 200

    issued = _issue(client, admin_headers, payment_id)
    assert issued.status_code == 200, issued.text
    body = issued.json()["receipt"]

    async with db_pool.acquire() as conn:
        ft = await conn.fetchrow(
            """SELECT id, created_at FROM finance_transactions
               WHERE student_payment_id = $1 AND deleted_at IS NULL ORDER BY id DESC LIMIT 1""",
            payment_id,
        )

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "active", "ใบที่เพิ่งออกต้องเป็น active"
    assert row["voided_at"] is None and row["deleted_at"] is None
    # 🔑 คอลัมน์กับที่มาของเลขปีต้องเป็น "วินาทีเดียวกัน"
    assert row["event_at"] == ft["created_at"].replace(tzinfo=timezone.utc), (
        f"event_at ({row['event_at']}) ต้องเท่ากับเวลาของเหตุการณ์รับเงิน "
        f"({ft['created_at']} naive UTC) ไม่ใช่เวลาที่ออกเอกสาร ({row['issued_at']})"
    )
    assert row["year_be"] == (ft["created_at"].replace(tzinfo=timezone.utc)
                              .astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET)

    # ส่งออก API ต้องเป็น tz-aware เสมอ (ไม่ใช่ naive) ไม่งั้นเบราว์เซอร์ตีเป็นเวลาเครื่องตัวเอง
    _assert_tz_aware_iso(body["event_at"])
    _assert_tz_aware_iso(body["issued_at"])


async def test_printed_date_follows_the_payment_event_not_the_print_time(
    client, db_pool, admin_headers
):
    """วันที่บนกระดาษต้องเป็นวันของ "เหตุการณ์" แม้จะออก/พิมพ์คนละวันกันคนละเดือน

    ข้อมูลชุดนี้จำลองเคสจริง: รับเงินเมื่อ 20 พ.ค. 2569 แต่เพิ่งมาออกใบเสร็จวันนี้ (ก.ย.)
    ⇒ กระดาษต้องลง "20 พ.ค. 2569" ไม่ใช่เดือน ก.ย. ที่กดพิมพ์
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    # บิลถูกทำเป็นจ่ายแล้วโดยไม่มีแถว FT — แล้วเรา seed เหตุการณ์เองด้วยเวลาที่ควบคุมได้
    _, payment_id = await _make_bill(db_pool, room_id, student_id,
                                     amount=1000.0, paid_amount=1000.0)
    event_utc = datetime(2026, 5, 20, 3, 0)          # naive UTC → ไทย 10:00 น.
    ft_id = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                      amount=1000.0, created_at=event_utc)

    issued = _issue(client, admin_headers, payment_id, transaction_id=ft_id)
    assert issued.status_code == 200, issued.text
    receipt_no = issued.json()["receipt"]["receipt_no"]
    assert receipt_no.startswith("REC-2569-"), receipt_no

    async with db_pool.acquire() as conn:
        issued_at = await conn.fetchval(
            "SELECT issued_at FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )
    assert issued_at.astimezone(THAI_TZ).date() != date(2026, 5, 20), (
        "เทสต์นี้จะไม่มีความหมายถ้าออกใบเสร็จวันเดียวกับเหตุการณ์ — "
        "ต้องเป็นคนละวันเพื่อให้แยกได้ว่าวันที่บนกระดาษมาจากค่าไหน"
    )

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    html = mock_render.await_args.args[0]

    assert "20 พ.ค. 2569 10:00 น." in html, (
        "วันที่บนกระดาษต้องเป็นวันของเหตุการณ์รับเงิน (20 พ.ค. 2569) — "
        "ถ้าไม่พบ แปลว่าโค้ดกลับไปใช้ issued_at"
    )
    # และต้อง **ไม่มี** วันที่ของ issued_at หลงเหลืออยู่ที่ไหนบนเอกสาร
    issued_thai = issued_at.astimezone(THAI_TZ)
    issued_text = (f"{issued_thai.day} {THAI_MONTHS_SHORT[issued_thai.month - 1]} "
                   f"{issued_thai.year + BUDDHIST_ERA_OFFSET}")
    assert issued_text not in html, (
        f"พบวันที่ของ issued_at ({issued_text}) บนเอกสาร — จอกับกระดาษจะลงคนละวัน"
    )


async def test_doc_year_and_printed_date_cross_the_buddhist_year_together(
    client, db_pool, admin_headers
):
    """เหตุการณ์ 31 ธ.ค. 2568 23:59 ไทย (16:59 UTC) ที่ออกใบเสร็จในปีถัดไป

    🔴 เคสที่บั๊กเดิมแสดงออก: เลขใช้ปีของเหตุการณ์ (2568) แต่วันที่พิมพ์ใช้ปีที่ออก (2569)
    ⇒ เอกสารขัดแย้งกับตัวเอง · เทสต์นี้บังคับทั้งสองค่าที่ขอบเขตข้ามปีพร้อมกัน
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id,
                                     amount=500.0, paid_amount=500.0)
    # 16:59 UTC = 23:59 ไทย ของวันที่ 31 ธ.ค. 2568 — นาทีสุดท้ายของปีไทย
    ft_id = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                      amount=500.0,
                                      created_at=datetime(2025, 12, 31, 16, 59))

    issued = _issue(client, admin_headers, payment_id, transaction_id=ft_id)
    assert issued.status_code == 200, issued.text
    receipt_no = issued.json()["receipt"]["receipt_no"]
    assert receipt_no == "REC-2568-0001", (
        f"ได้ {receipt_no} — ปี พ.ศ. ต้องเป็นของ **เหตุการณ์** (2568) "
        f"ไม่ใช่ปีที่ออกเอกสาร (2569)"
    )

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    html = mock_render.await_args.args[0]
    assert "31 ธ.ค. 2568 23:59 น." in html, (
        "วันที่บนกระดาษต้องเป็นปีเดียวกับเลขเอกสาร (2568) ไม่ใช่ปีที่กดพิมพ์"
    )


async def test_date_filter_follows_event_at_not_issued_at(client, db_pool, admin_headers):
    """ตัวกรองช่วงวันของรายการต้องกรองด้วย "วันที่ของเอกสาร" ตัวเดียวกับที่พิมพ์

    ⚠️ ถ้ากรองด้วย `issued_at` แต่กระดาษลง `event_at` ผู้ใช้จะ **ค้นใบเสร็จไม่เจอ**
       ทั้งที่ถือกระดาษที่ลงวันนั้นอยู่ในมือ — ซึ่งเป็นอาการที่ลูกค้าจับได้ทันที
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id,
                                     amount=200.0, paid_amount=200.0)
    ft_id = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                      amount=200.0, created_at=datetime(2026, 5, 20, 3, 0))
    receipt_no = _issue(client, admin_headers, payment_id,
                        transaction_id=ft_id).json()["receipt"]["receipt_no"]

    # วันของเหตุการณ์ → ต้องเจอ
    hit = client.get(_url(RECEIPTS_PATH, room_id),
                     params={"start_date": "2026-05-20", "end_date": "2026-05-20"},
                     headers=admin_headers)
    assert [r["receipt_no"] for r in hit.json()] == [receipt_no]

    # วันนี้ (วันที่ออกเอกสารจริง) → ต้อง **ไม่** เจอ
    today_thai = datetime.now(THAI_TZ).date().isoformat()
    miss = client.get(_url(RECEIPTS_PATH, room_id),
                      params={"start_date": today_thai, "end_date": today_thai},
                      headers=admin_headers)
    assert miss.json() == [], (
        f"เจอใบเสร็จเมื่อกรองด้วย issued_at ({today_thai}) — "
        f"แปลว่าตัวกรองยังใช้ issued_at ไม่ใช่ event_at"
    )


async def test_invoice_event_at_is_exactly_its_own_issued_at(client, db_pool, admin_headers):
    """ใบแจ้งหนี้ไม่ผูกกับเหตุการณ์รับเงิน ⇒ `event_at` ต้อง **เท่ากับ** `issued_at` เป๊ะ

    ไม่ใช่ค่าที่ต่างกันไม่กี่มิลลิวินาที — ทั้งคู่ต้องอ่านจาก `CURRENT_TIMESTAMP` ครั้งเดียว
    ของ transaction เดียวกัน (ถ้าอ่านสองครั้งหรือใช้ `datetime.now()` ของแอป 3 replica
    จะได้นาฬิกาคนละเรือนแล้วค่าไม่ตรงกัน)
    """
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)

    issued = _issue_invoices(client, admin_headers, [student_id])
    assert issued.status_code == 200, issued.text
    receipt_no = issued.json()["receipts"][0]["receipt_no"]

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT event_at, issued_at FROM finance_receipts WHERE receipt_no = $1",
            receipt_no,
        )
    assert row["event_at"] == row["issued_at"], (
        f"ใบแจ้งหนี้ต้องมี event_at == issued_at เป๊ะ "
        f"(ได้ {row['event_at']} กับ {row['issued_at']})"
    )


async def test_legacy_receipt_without_event_at_falls_back_to_issued_at(
    client, db_pool, admin_headers
):
    """ข้อมูลเก่าที่ `event_at IS NULL` ต้องยังพิมพ์ได้ — ถอยไปใช้ `issued_at`

    ใบเสร็จที่ออกไปก่อนมีคอลัมน์นี้ต้องไม่กลายเป็นเอกสารที่พิมพ์ไม่ได้
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=100.0)
    assert _pay(client, admin_headers, payment_id, account_id, 100.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    # จำลองข้อมูลยุคก่อนมีคอลัมน์
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE finance_receipts SET event_at = NULL WHERE receipt_no = $1", receipt_no,
        )
        issued_at = await conn.fetchval(
            "SELECT issued_at FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )

    thai = issued_at.astimezone(THAI_TZ)
    expected = (f"{thai.day} {THAI_MONTHS_SHORT[thai.month - 1]} "
                f"{thai.year + BUDDHIST_ERA_OFFSET} {thai.strftime('%H:%M')} น.")

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    assert expected in mock_render.await_args.args[0], (
        "ใบที่ event_at IS NULL ต้องถอยไปใช้ issued_at ไม่ใช่พิมพ์ '-' หรือพัง"
    )

    # และตัวกรองช่วงวันก็ต้องถอยตาม (`_DOC_DATE = COALESCE(event_at, issued_at)`)
    hit = client.get(_url(RECEIPTS_PATH, room_id),
                     params={"start_date": thai.date().isoformat(),
                             "end_date": thai.date().isoformat()},
                     headers=admin_headers)
    assert [r["receipt_no"] for r in hit.json()] == [receipt_no]


# ═══════════════════════ 14. 🧾 revert ต้อง void ใบเสร็จ ไม่ทิ้งให้ค้าง active (#60)
# 🎯 กฎที่ล็อกไว้: **ห้ามมีใบเสร็จที่ยัง active อยู่ทั้งที่รายการรับเงินถูกยกเลิกไปแล้ว**
#    ถ้าปล่อยไว้ ฐานข้อมูลบอก "บิลนี้ยังไม่ถูกจ่าย" แต่กระดาษที่ผู้ปกครองถืออยู่อ้างว่ารับเงินแล้ว
#    ⇒ สองหลักฐานขัดกันเองและตรวจสอบย้อนหลังไม่ได้
async def _revert(client, db_pool, headers, payment_id: int):
    """ยิง `DELETE .../finance/transactions/{tx_id}` ของ **งวดล่าสุด** ของบิลใบนี้"""
    async with db_pool.acquire() as conn:
        tx_id = await conn.fetchval(
            "SELECT transaction_id FROM student_payments WHERE id = $1", payment_id,
        )
    assert tx_id is not None, "บิลนี้ยังไม่ถูกจ่าย จึงไม่มีรายการให้ยกเลิก"
    return client.request(
        "DELETE", _url(TRANSACTION_PATH, headers.room_id, tx_id=tx_id),
        json={"user_name": "Tester"}, headers=headers,
    )


async def test_revert_voids_the_receipt_instead_of_leaving_it_active(
    client, db_pool, admin_headers
):
    """จ่าย → ออกใบเสร็จ → ยกเลิกรายการ ⇒ ใบเสร็จต้องเป็น voided ครบทุกช่อง"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=500.0)
    assert _pay(client, admin_headers, payment_id, account_id, 500.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    res = await _revert(client, db_pool, admin_headers, payment_id)
    assert res.status_code == 200, res.text

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 1, "ต้องไม่ลบแถวทิ้ง — เก็บไว้เป็นหลักฐานการตรวจสอบ"
    row = rows[0]
    assert row["status"] == "voided", (
        f"ใบเสร็จค้างสถานะ {row['status']!r} ทั้งที่รายการถูกรับคืน — "
        f"ฐานข้อมูลกับกระดาษที่ผู้ปกครองถือจะขัดกันเอง"
    )
    assert row["voided_at"] is not None, "ต้องประทับเวลาที่ยกเลิก"
    assert row["voided_by"] == admin_headers.user_id, "ต้องรู้ว่าใครเป็นคนยกเลิก"
    assert row["void_reason"], "ต้องมีเหตุผลให้ตรวจสอบย้อนหลัง"
    assert row["deleted_at"] is not None, (
        "ต้องตั้ง deleted_at คู่กับ status ด้วย — ทุกจุดอ่านเดิมและ partial unique index "
        "กรอง `deleted_at IS NULL` ⇒ ถ้าไม่ตั้ง ใบที่ void แล้วจะยังโผล่ในเส้นทางอ่านเดิม"
    )
    # เลขที่เอกสารต้องไม่ถูกแตะ — เอกสารที่พิมพ์แจกไปแล้วต้องเปิดกลับมาเจอได้เสมอ
    assert row["receipt_no"] == receipt_no

    # เส้นทางอ่านปกติต้องไม่คืนใบที่ถูกยกเลิก
    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                        headers=admin_headers)
    assert detail.status_code == 404, (
        "ใบที่ถูกยกเลิกต้องไม่ถูกคืนจากเส้นทางอ่านปกติ (ผู้ใช้ไม่ควรเจอเอกสารที่โมฆะแล้ว)"
    )
    listing = client.get(_url(RECEIPTS_PATH, room_id), headers=admin_headers)
    assert listing.json() == []


async def test_voided_receipt_can_never_stay_un_soft_deleted(
    client, db_pool, admin_headers
):
    """DB ต้อง **ห้าม** `status='voided'` + `deleted_at IS NULL` — เสาหลักที่ทำให้ด่านซ้ำซ้อนปลอดภัย

    🧬 ที่มา: mutation M6 — ถอด `AND R.status = 'active'` ออกจาก `get_receipts`
       (`receipts.py:610`) แล้ว **เทสต์ทั้งไฟล์ยังเขียว** ซึ่งอ่านเผิน ๆ เหมือน
       "เทสต์พิสูจน์ไม่ได้" แต่ของจริงคือ **equivalent mutant** และนี่คือหลักฐาน:

       `chk_receipt_voided_is_deleted` (`init_db.py:459`) บังคับ
       `status = 'active' OR deleted_at IS NOT NULL`
       ⇒ แถวใดที่มี `deleted_at IS NULL` **จำเป็นต้อง** มี `status = 'active'`
       ⇒ `AND R.status = 'active'` ถูกลอจิกกลืนด้วย `AND R.deleted_at IS NULL` ไปแล้ว
       ⇒ **ไม่มี**ทรงข้อมูลใดที่ทำให้ clause เดียวนั้นเปลี่ยนคำตอบได้ (จึงไม่ใช่ช่องโหว่ของเทสต์)

    🎯 เทสต์นี้จึง pin **เหตุผลที่ทำให้สอง clause กลืนกันได้** ไม่ได้ pin ตัว clause
       ถ้าวันหนึ่งมีคนถอดหรือผ่อน CHECK นี้ ไฟล์นี้จะล้มตรงนี้ทันที —
       ซึ่งเป็นสัญญาณที่ถูกต้องว่า "ด่าน `status` กลายเป็นตัวจริงแล้ว ห้ามถอดออก"
       (ทางกลับกัน: การไปเขียนเทสต์ที่ seed สถานะนี้ลงตารางตรง ๆ ทำไม่ได้ —
        DB จะปฏิเสธ ซึ่งก็คือสิ่งที่เทสต์นี้พิสูจน์)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=250.0)
    assert _pay(client, admin_headers, payment_id, account_id, 250.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    async with db_pool.acquire() as conn:
        # 🚫 ทิศที่ต้องเกิดไม่ได้: ยกเลิกแล้วแต่ยังไม่ soft delete
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                """UPDATE finance_receipts SET status = 'voided', deleted_at = NULL
                   WHERE room_id = $1 AND receipt_no = $2""",
                room_id, receipt_no,
            )

        # ✅ ทิศที่ต้องผ่าน: soft delete โดยไม่แตะ status
        #    ⇒ พิสูจน์ว่า constraint จำกัดทิศเดียวจริง ไม่ได้เป็น `CHECK (false)` ที่ห้ามหมด
        await conn.execute(
            """UPDATE finance_receipts SET status = 'active', deleted_at = NOW()
               WHERE room_id = $1 AND receipt_no = $2""",
            room_id, receipt_no,
        )
        assert await conn.fetchval(
            "SELECT deleted_at FROM finance_receipts WHERE room_id = $1 AND receipt_no = $2",
            room_id, receipt_no,
        ) is not None, "ทิศนี้ต้องเขียนผ่าน — ไม่งั้น constraint กันกว้างเกินจนผิด"


async def test_revert_report_includes_the_voided_receipt_numbers(
    client, db_pool, admin_headers
):
    """คำตอบของ revert ต้องบอกเลขใบเสร็จที่ถูกยกเลิก — ผู้ใช้ต้องรู้ว่ากระดาษใบไหนโมฆะ"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=300.0)
    assert _pay(client, admin_headers, payment_id, account_id, 300.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    body = (await _revert(client, db_pool, admin_headers, payment_id)).json()
    assert body["voided_receipts"] == [receipt_no]
    assert receipt_no in body["message"]

    # และต้องลง audit log ให้ตรวจย้อนหลังได้ว่าใบไหนถูกยกเลิกพร้อมรายการนี้
    async with db_pool.acquire() as conn:
        new_values = await conn.fetchval(
            """SELECT new_values FROM audit_logs
               WHERE room_id = $1 AND entity_type = 'FINANCE_TRANSACTION'
               ORDER BY id DESC LIMIT 1""",
            room_id,
        )
    assert receipt_no in json.dumps(new_values, default=str), (
        "audit log ของการยกเลิกรายการต้องบันทึกเลขใบเสร็จที่ถูกยกเลิกไว้ด้วย"
    )


async def test_voided_receipt_stays_readable_for_audit(client, db_pool, admin_headers):
    """ใบที่ยกเลิกแล้วต้อง **เปิดดูได้** ด้วย `include_voided=true` เพื่อตรวจสอบย้อนหลัง"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=700.0)
    assert _pay(client, admin_headers, payment_id, account_id, 700.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    assert (await _revert(client, db_pool, admin_headers, payment_id)).status_code == 200

    detail = client.get(_url(RECEIPT_PATH, room_id, receipt_no=receipt_no),
                        params={"include_voided": "true"}, headers=admin_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "voided"
    assert body["voided_at"] is not None
    assert body["void_reason"]
    assert float(body["amount"]) == 700.0, "ยอดเดิมต้องไม่ถูกแก้"

    listing = client.get(_url(RECEIPTS_PATH, room_id),
                         params={"include_voided": "true"}, headers=admin_headers)
    assert [r["receipt_no"] for r in listing.json()] == [receipt_no]


async def test_repay_after_revert_issues_a_new_active_receipt(
    client, db_pool, admin_headers
):
    """ยกเลิก → จ่ายใหม่ ⇒ ต้องได้ใบใหม่ที่ active และใบเก่าต้องยังเป็น voided

    ⚠️ จุดที่พังได้ง่าย: `_find_existing` (ด่าน idempotency) ต้องไม่คืนใบที่ถูกยกเลิก
       ไปแล้ว ไม่งั้นผู้ใช้จะได้ "ใบเสร็จที่โมฆะ" กลับมาแทนใบใหม่
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=400.0)
    assert _pay(client, admin_headers, payment_id, account_id, 400.0).status_code == 200
    first_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    assert (await _revert(client, db_pool, admin_headers, payment_id)).status_code == 200
    assert _pay(client, admin_headers, payment_id, account_id, 400.0).status_code == 200

    second = _issue(client, admin_headers, payment_id)
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is False
    second_no = second.json()["receipt"]["receipt_no"]
    assert second_no != first_no

    rows = await _db_receipts(db_pool, room_id)
    assert len(rows) == 2
    by_no = {r["receipt_no"]: r for r in rows}
    assert by_no[first_no]["status"] == "voided"
    assert by_no[second_no]["status"] == "active"
    assert by_no[second_no]["deleted_at"] is None
    # ใบที่ active ต้องเปิดได้ตามปกติ
    assert client.get(_url(RECEIPT_PATH, room_id, receipt_no=second_no),
                      headers=admin_headers).status_code == 200


async def test_partial_revert_voids_only_the_reverted_instalments_receipt(
    client, db_pool, admin_headers
):
    """ผ่อน 2 งวด → ยกเลิกงวดที่ 2 ⇒ ใบของงวดที่ 2 เป็น voided แต่ใบของงวดที่ 1 ยัง active

    เงินงวดที่ 1 ยังรับจริงอยู่ การยกเลิกใบนั้นด้วยจะทำให้หลักฐานการรับเงินหายไป
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=1000.0)

    assert _pay(client, admin_headers, payment_id, account_id, 500.0).status_code == 200
    first_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]
    assert _pay(client, admin_headers, payment_id, account_id, 500.0).status_code == 200
    second_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]
    assert first_no != second_no

    assert (await _revert(client, db_pool, admin_headers, payment_id)).status_code == 200

    rows = {r["receipt_no"]: r for r in await _db_receipts(db_pool, room_id)}
    assert rows[second_no]["status"] == "voided"
    assert rows[first_no]["status"] == "active", (
        "ใบของงวดที่ 1 ต้องไม่ถูกยกเลิกตาม — เงินงวดนั้นยังรับอยู่จริง"
    )
    assert rows[first_no]["deleted_at"] is None
    assert client.get(_url(RECEIPT_PATH, room_id, receipt_no=first_no),
                      headers=admin_headers).status_code == 200


async def test_voided_receipt_pdf_is_stamped_void_with_its_reason(
    client, db_pool, admin_headers
):
    """พิมพ์ใบที่ถูกยกเลิกได้ **แต่ต้องประทับ "ยกเลิก" ชัดเจน** พร้อมเหตุผล

    ทางเลือกคือปฏิเสธการพิมพ์ ซึ่งจะทำให้ต้นฉบับที่ผู้ปกครองถืออยู่กลายเป็นเอกสาร
    ที่ระบบปฏิเสธว่าตัวเองไม่เคยออก — แย่กว่า ⇒ พิมพ์ได้แต่ต้องบอกสถานะ
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=250.0)
    assert _pay(client, admin_headers, payment_id, account_id, 250.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    assert (await _revert(client, db_pool, admin_headers, payment_id)).status_code == 200

    async with db_pool.acquire() as conn:
        reason = await conn.fetchval(
            "SELECT void_reason FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )

    mock_render = AsyncMock(return_value=b"%PDF-1.4\n")
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.get(_url(PDF_PATH, room_id, receipt_no=receipt_no), headers=admin_headers)
    assert res.status_code == 200, res.text
    html = mock_render.await_args.args[0]

    assert "เอกสารนี้ถูกยกเลิกแล้ว" in html, "ใบที่โมฆะต้องมีแบนเนอร์ประทับบนกระดาษ"
    assert reason in html, "ต้องพิมพ์เหตุผลของการยกเลิกให้ผู้ตรวจสอบเห็น"
    # แบนเนอร์ต้องมาก่อนหัวเอกสาร (คนอ่านต้องรู้ก่อนอ่านตัวเลข)
    assert html.index("เอกสารนี้ถูกยกเลิกแล้ว") < html.index('class="head"')


async def test_voided_receipt_does_not_count_as_already_issued(
    client, db_pool, admin_headers
):
    """ด่าน idempotency ต้องไม่คืนใบที่ถูก void แล้ว — ต้องออกใบใหม่ให้

    Void ด้วยสถานะ **จริง** ที่ระบบใช้ (status + voided_at + deleted_at) แล้วออกซ้ำ
    ⇒ ต้องได้ใบใหม่ ไม่ใช่ `reused: True` พร้อมเลขของใบที่โมฆะไปแล้ว
    (ถ้า `_find_existing` หลุดกรองใบที่ void ผู้ใช้จะถือ "ใบเสร็จที่ยกเลิกแล้ว"
     กลับบ้านโดยคิดว่าเป็นหลักฐานการจ่ายเงิน)
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=600.0)
    assert _pay(client, admin_headers, payment_id, account_id, 600.0).status_code == 200
    first_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE finance_receipts
               SET status = 'voided', voided_at = CURRENT_TIMESTAMP,
                   void_reason = 'จำลอง', deleted_at = NOW()
               WHERE receipt_no = $1""",
            first_no,
        )

    again = _issue(client, admin_headers, payment_id)
    assert again.status_code == 200, again.text
    assert again.json()["reused"] is False, (
        "ได้ใบที่ถูกยกเลิกไปแล้วกลับมา — `_find_existing` ต้องไม่มองว่าใบที่ void แล้ว "
        "คือ 'ออกไปแล้ว'"
    )
    assert again.json()["receipt"]["receipt_no"] != first_no

    rows = {r["receipt_no"]: r for r in await _db_receipts(db_pool, room_id)}
    assert rows[first_no]["status"] == "voided"
    assert rows[again.json()["receipt"]["receipt_no"]]["status"] == "active"


async def test_voided_status_without_soft_delete_is_rejected_by_the_db(
    client, db_pool, admin_headers
):
    """`chk_receipt_voided_is_deleted` — "voided ⇒ ต้องมี deleted_at" บังคับที่ DB

    🔒 สถานะ `status='voided'` + `deleted_at IS NULL` เป็นกับดักที่ **ตันทั้งสองทาง**:
    - partial unique index ยังนับว่ามีใบอยู่ ⇒ ออกใบใหม่ของงวดเดิมไม่ได้ (400)
    - `_find_existing` ปฏิเสธเพราะกรอง `status='active'` ⇒ ใบเดิมก็ไม่ถูกคืน
    ⇒ ผู้ใช้ได้ 400 "เลขเอกสารซ้ำ" ทั้งที่ไม่มีเลขซ้ำ — ข้อความโกหกและแก้ไม่ได้
    ⇒ ทางออกคือทำให้สถานะนั้น **เกิดขึ้นไม่ได้เลย** ไม่ใช่พึ่งวินัยของคนเขียนโค้ด
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=600.0)
    assert _pay(client, admin_headers, payment_id, account_id, 600.0).status_code == 200
    receipt_no = _issue(client, admin_headers, payment_id).json()["receipt"]["receipt_no"]

    async with db_pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE finance_receipts SET status = 'voided' WHERE receipt_no = $1",
                receipt_no,
            )
        # คู่ (status, deleted_at) ที่ถูกต้องต้องผ่าน
        await conn.execute(
            """UPDATE finance_receipts SET status = 'voided', deleted_at = NOW()
               WHERE receipt_no = $1""",
            receipt_no,
        )


async def test_receipt_status_check_constraint_rejects_unknown_values(
    db_pool, admin_headers
):
    """`chk_receipt_status` ต้องกันค่าที่ไม่รู้จัก — สถานะเป็นสัญญาระหว่าง DB กับโค้ด"""
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id, amount=100.0)
    reservation = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                            amount=100.0,
                                            created_at=datetime(2026, 6, 1, 3, 0))
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO finance_receipts
                   (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                    legacy_transaction_id, student_id, amount, paid_total_after, event_at)
               VALUES ($1, 'REC-2569-9001', 'receipt', 2569, 9001, $2, $3, $4, 100.0, 100.0,
                       CURRENT_TIMESTAMP)""",
            room_id, payment_id, reservation, student_id,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE finance_receipts SET status = 'cancelled' WHERE receipt_no = $1",
                "REC-2569-9001",
            )


# ═════ 15. 🔁 "แพ้การแข่งขัน" (UniqueViolation) + SAVEPOINT — พิสูจน์ด้วยสอง connection
async def _wait_until_blocked(pool, pattern: str, *, timeout: float = 20.0) -> dict:
    """รอจนมี session ที่ **ติดล็อกอยู่ที่คำสั่ง `pattern`** แล้วคืนแถวของ session นั้น

    🎯 ทำไมต้องมีตัวรอแบบนี้อะไรที่อิงสถานะจริง — การทดสอบการแข่งกันมีจุดตายคือ "จังหวะ":
    ต้องรู้แน่ว่าอีกฝั่งไปถึงไหนแล้วก่อนจะเดินต่อ ถ้าใช้ `asyncio.sleep(...)` แทน
    เทสต์จะเปราะแบบเงียบ ๆ (เครื่องเร็ว = ยังไม่ถึงจุดที่ต้องทดสอบ แต่เทสต์ก็ผ่าน
    / เครื่องช้า = รอไม่พอ แล้วล้มด้วย `TimeoutError` ที่อ่านไม่ออกว่าเกิดอะไรขึ้น)

    ⚠️ ต้องรอที่ **`wait_event_type = 'Lock'`** ไม่ใช่แค่มีคำสั่งนั้นใน `pg_stat_activity`
       เพราะระหว่างที่ยังไม่ติดล็อก คำสั่งเดียวกันก็ปรากฏอยู่แล้ว (`state='active'`)
       ⇒ รอแบบกว้างจะผ่านทันทีตั้งแต่ยังไม่มีการแข่งเกิดขึ้น แล้วเทสต์จะพิสูจน์อะไรไม่ได้เลย
    """
    deadline = time.monotonic() + timeout
    async with pool.acquire() as watcher:
        while True:
            row = await watcher.fetchrow(
                """SELECT pid, wait_event_type, wait_event
                   FROM pg_stat_activity
                   WHERE datname = current_database()
                     AND state = 'active'
                     AND wait_event_type = 'Lock'
                     AND query LIKE $1""",
                pattern,
            )
            if row:
                return dict(row)
            if time.monotonic() >= deadline:
                # 🚨 ล้มแบบบอกของจริง: ถ้าไม่เจอ ให้เห็นว่า session อื่นกำลังทำอะไรอยู่
                #    ไม่งั้นจะเสียเวลางงว่า "block ไม่เกิด" หรือ "block เกิดที่อื่น"
                seen = await watcher.fetch(
                    """SELECT pid, state, wait_event_type, wait_event, LEFT(query, 80) AS q
                       FROM pg_stat_activity
                       WHERE datname = current_database() AND pid <> pg_backend_pid()"""
                )
                raise AssertionError(
                    f"ไม่พบ session ที่ติดล็อกอยู่ที่ {pattern!r} ภายใน {timeout:.0f}s — "
                    f"สถานะจริงใน DB: {[dict(r) for r in seen]}"
                )
            await asyncio.sleep(0.05)


async def test_the_loser_of_the_race_gets_the_winning_receipt_not_a_500(
    db_pool, admin_headers
):
    """คำขอที่ **แพ้การแข่งขัน** ต้องได้ใบของ "ผู้ชนะ" คืน ไม่ใช่ 500

    🎯 ตัวจัดการ `except asyncpg.UniqueViolationError` ใน `_issue_one` คือ "idempotency
    ชั้นที่ 2" (ชั้นที่ 1 คือ `_find_existing` ก่อน INSERT) — และมัน **อ่าน `conn` ต่อ**
    ⇒ ถ้าไม่มี savepoint ครอบ INSERT ไว้ Postgres จะทำเครื่องหมาย transaction ว่า aborted
    ทันทีที่ INSERT ล้ม ⇒ คำสั่งถัดไปได้ `25P02 InFailedSQLTransactionError`
    ซึ่งไม่มีชั้นไหนแปลงเป็น HTTP ⇒ **ผู้ใช้เห็น 500 แทนที่จะเห็นใบเสร็จ**
    ⇒ ตัวจัดการการแข่งจะกลายเป็นโค้ดที่ทำให้ *แย่ลง* กว่าไม่มีมัน
    (นี่คือ mutation ที่เทสต์นี้จับ: ถอด `async with conn.transaction():` ออก → ล้มด้วย 25P02)

    🧪 ทำไมเทสต์นี้ต้องจงใจ "แฮ็ก" ฉาก:
      ภายใต้ lock protocol ปัจจุบัน (advisory lock ต่อห้อง + `FOR UPDATE OF SP` ใน `_load_payment`)
      ชั้น idempotency ที่ 1 จะ **มองเห็นแถวของคู่แข่งเสมอ** ⇒ ชั้นที่ 2 ไม่มีทางถูกเรียกเลย
      เพราะการ INSERT แถวลูกของ `finance_receipts` จะถือ `FOR KEY SHARE` บนแถว
      `student_payments` ซึ่ง **ชนกับ `FOR UPDATE`** ที่ผู้ขอออกเอกสารถืออยู่
      ⇒ คู่แข่งที่ยิงพร้อมกันจะไปติดที่ `_load_payment` ก่อน (ไม่ใช่ที่ unique index)
        แล้วพอคู่แข่ง commit ชั้นที่ 1 ก็อ่านเจอ = ทางที่ถูกต้องอยู่แล้ว
      ⇒ เทสต์นี้จึงจำลอง **"ผู้เขียนที่ข้าม lock protocol"** (ตรงกับสถานการณ์ที่ตัวจัดการนี้มีไว้กัน)
        ด้วย `session_replication_role = replica` บนอีก connection ซึ่งปิด trigger ของ FK
        ⇒ แถวคู่แข่งเข้า unique index ได้โดยไม่ต้องยึดล็อกบน `student_payments`
        ⇒ ทำให้คำขอจริงไปติดที่ unique index **แบบ deterministic** (ไม่ใช่แข่งจริงซึ่งพิสูจน์ไม่ได้)

    ⚠️ และเพราะ "ปิด FK trigger" ไม่ได้แปลว่า "ปิด CHECK" — แถวคู่แข่งที่ใส่เข้ามายังต้อง
       ผ่าน `chk_receipt_status` / `chk_receipt_voided_is_deleted` ตามปกติ
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id,
                                     amount=500.0, paid_amount=500.0)
    # งวดรับเงิน: 1 มิ.ย. 2026 03:00 UTC = 10:00 ไทย → ปี พ.ศ. 2569
    ft_id = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                      amount=500.0, created_at=datetime(2026, 6, 1, 3, 0))

    winner_no = "REC-2569-7777"
    task = None
    conn1 = await db_pool.acquire()
    try:
        async with conn1.transaction():
            # 🔓 ปิด FK trigger เฉพาะ connection นี้ (ต้องเป็น superuser — test_admin เป็น)
            #    ⇒ แถวนี้ไม่ยึด KEY SHARE บน student_payments ⇒ คำขอจริงไม่ไปติดที่ _load_payment
            await conn1.execute("SET LOCAL session_replication_role = replica")
            await conn1.execute(
                """INSERT INTO finance_receipts
                       (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                        legacy_transaction_id, amount, paid_total_after,
                        issued_to_name, issued_by_name, event_at, issued_at)
                   VALUES ($1, $2, 'receipt', 2569, 7777, $3, $4, 500.0, 500.0,
                           'ผู้ชนะการแข่ง', 'Tester', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                room_id, winner_no, payment_id, ft_id,
            )

            # 🏁 ยิงคำขอจริง (ผ่าน service ตรง ๆ — router ไม่ใช่สิ่งที่เทสต์นี้พิสูจน์)
            #    `FinanceService.issue_receipt` เป็นคนเปิด transaction ของตัวเอง
            task = asyncio.create_task(
                FinanceService.issue_receipt(
                    db_pool, payment_id, admin_headers.user_id,
                    "test", "tester", doc_type="receipt", room_id=room_id,
                )
            )

            # ⏳ รอจนกว่าคำขอจะไปติดที่ unique index ของคู่แข่ง (ไม่ใช่ sleep เดา)
            await _wait_until_blocked(db_pool, "%INSERT INTO finance_receipts%")

        # ← ออกจาก `async with` = COMMIT ของคู่แข่ง ⇒ ปลดล็อกให้คำขอ แล้วมันได้ UniqueViolation
        result = await asyncio.wait_for(task, timeout=20)
        task = None
    finally:
        if task is not None:  # เทสต์ล้มกลางทาง — อย่าทิ้ง task ที่ค้าง blocked ไว้
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # เก็บกวาดเท่านั้น — ไม่สนใจ error
                pass
        await db_pool.release(conn1)

    # ── คำขอที่แพ้ต้องได้ใบของผู้ชนะ ไม่ใช่ error ────────────────────────────
    assert result["reused"] is True, (
        "คำขอที่แพ้การแข่งขันต้องได้ใบเดิมคืน (reused=True) — "
        f"ได้ reused={result['reused']} เลข {result['receipt']['receipt_no']}"
    )
    assert result["receipt"]["receipt_no"] == winner_no
    assert "ถูกออกไปแล้ว" in result["message"]

    # ── และต้องไม่มีใบที่สองเกิดขึ้นจริง ────────────────────────────────────
    receipts = await _db_receipts(db_pool, room_id)
    assert len(receipts) == 1, f"ต้องเหลือใบเดียว ได้ {[r['receipt_no'] for r in receipts]}"
    assert receipts[0]["receipt_no"] == winner_no
    assert receipts[0]["status"] == "active" and receipts[0]["deleted_at"] is None, \
        "แถวของผู้ชนะต้องไม่ถูกแตะเลย"

    # 📌 เลขที่คำขอที่แพ้จองไปแล้วถูก "ใช้ฟรี" 1 หมายเลข (ยอมรับได้ — ดูคอมเมนต์ใน `_issue_one`)
    #    ยืนยันไว้ตรงนี้เพื่อให้พฤติกรรมนี้ **ถูกบันทึก** ไม่ใช่ถูกค้นพบทีหลังแล้วเข้าใจผิดว่าเป็นบั๊ก
    assert await _db_last_seq(db_pool, room_id, 2569) == 1


async def test_the_room_lock_funnels_the_same_race_into_layer_one(db_pool, admin_headers):
    """คู่แข่งที่ **ทำตาม lock protocol** ต้องไม่พาไปถึงชั้นที่ 2 — ชั้นที่ 1 จับได้เอง

    🎯 นี่คือหลักฐานเชิงพฤติกรรมว่า "ทำไมชั้นที่ 2 ถึงไม่มีทางถูกเรียกในเส้นทางปกติ":
      คู่แข่งที่ยึด advisory lock ของห้องก่อน (แบบที่ `_issue_one` ทุกตัวทำ) จะทำให้คำขอ
      ไป **ติดที่ advisory lock** ไม่ใช่ที่ unique index ⇒ พอคู่แข่ง commit แล้วคำขอได้ล็อกต่อ
      ชั้น idempotency ที่ 1 (`_find_existing`) จะอ่านเจอแถวนั้นทันทีและคืนใบเดิม
      ⇒ ไม่มีการจองเลขฟุ่มเฟือย ไม่มี UniqueViolation ⇒ **ผลลัพธ์ที่ผู้ใช้เห็นเหมือนกัน**
        แต่ทางที่ไปถึงมันสะอาดกว่า

    🧪 สัญญาณรอ: `pg_advisory_xact_lock` ใน `pg_stat_activity` — เป็นคำสั่งที่ต่างจาก
       `INSERT INTO finance_receipts` ของเทสต์ข้างบนชัดเจน ⇒ แยกสองเส้นทางออกจากกันได้จริง
    """
    from services.finance.base import _MONEY_LOCK_NAMESPACE

    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id,
                                     amount=500.0, paid_amount=500.0)
    ft_id = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                      amount=500.0, created_at=datetime(2026, 6, 1, 3, 0))

    winner_no = "REC-2569-8888"
    task = None
    conn1 = await db_pool.acquire()
    try:
        async with conn1.transaction():
            # คู่แข่งทำตาม protocol เป๊ะ: ยึด advisory lock ของห้องก่อนแตะอะไรทั้งสิ้น
            await conn1.execute(
                "SELECT pg_advisory_xact_lock($1, $2)", _MONEY_LOCK_NAMESPACE, room_id,
            )
            await conn1.execute(
                """INSERT INTO finance_receipts
                       (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                        legacy_transaction_id, amount, paid_total_after,
                        issued_to_name, issued_by_name, event_at, issued_at)
                   VALUES ($1, $2, 'receipt', 2569, 8888, $3, $4, 500.0, 500.0,
                           'ผู้ชนะการแข่ง', 'Tester', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                room_id, winner_no, payment_id, ft_id,
            )
            await conn1.execute(
                """INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
                   VALUES ($1, 2569, 'receipt', 8888)
                   ON CONFLICT (room_id, year_be, doc_type)
                   DO UPDATE SET last_seq = GREATEST(receipt_sequences.last_seq, 8888)""",
                room_id,
            )

            task = asyncio.create_task(
                FinanceService.issue_receipt(
                    db_pool, payment_id, admin_headers.user_id,
                    "test", "tester", doc_type="receipt", room_id=room_id,
                )
            )
            # รอที่ advisory lock — คนละสัญญาณกับเทสต์ข้างบน ⇒ เส้นทางต่างกันจริง
            await _wait_until_blocked(db_pool, "%pg_advisory_xact_lock%")

        result = await asyncio.wait_for(task, timeout=20)
        task = None
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # เก็บกวาดเท่านั้น — ไม่สนใจ error
                pass
        await db_pool.release(conn1)

    assert result["reused"] is True
    assert result["receipt"]["receipt_no"] == winner_no

    receipts = await _db_receipts(db_pool, room_id)
    assert len(receipts) == 1
    # ✅ ต่างจากเทสต์ข้างบน: ไม่มีเลขถูกเผา เพราะไม่มีการจองเลขเกิดขึ้นเลย
    assert await _db_last_seq(db_pool, room_id, 2569) == 8888


async def test_a_child_row_lock_stops_the_other_issuer_before_the_index(db_pool, admin_headers):
    """**กลไก** ที่ทำให้ชั้นที่ 2 ไม่ถูกเรียก: FK lock บน `student_payments` มาก่อน unique index

    🎯 นี่คือหลักฐานเชิงประจักษ์ของข้อสรุปใน `docs/skills.md` ว่า "ภายใต้ lock protocol นี้
      ชั้น idempotency ที่ 2 ไม่มีทางถูกเรียก" — ไม่ใช่การให้เหตุผลลอย ๆ:
      แถวลูกของ `finance_receipts` ทุกแถวถือ **`FOR KEY SHARE`** บนแถว `student_payments`
      ของตัวเอง (FK trigger ทำเอง) และ Key Share **ชนกับ `FOR UPDATE`** ที่ `_load_payment` ยึด
      ⇒ คู่แข่งที่ "ข้าม advisory lock" (ซึ่งเป็นตัวที่เทสต์ข้างบนจำลอง) ก็ยังไปติดที่
      `_load_payment` **ก่อน** จะถึง unique index — แล้วพอคู่แข่ง commit ชั้นที่ 1 ก็อ่านเจอ
      ⇒ ได้ `reused: True` พร้อม **เลขไม่ถูกจองเลย** (ต่างจากเทสต์ข้างบนที่มีเลขถูกเผา 1 หมายเลข)

    📌 เทสต์นี้จึงเป็นตัวชี้วัดว่า "ทางเข้าชั้นที่ 2 ต้องปิด FK trigger เท่านั้น" — ถ้าวันหนึ่ง
      มีคนเปลี่ยน `_load_payment` จาก `FOR UPDATE OF SP` เป็นอย่างอื่น (เช่น `FOR NO KEY UPDATE`
      ซึ่ง **ไม่ชน** กับ Key Share) เทสต์นี้จะล้มทันที = สัญญาณว่าชั้นที่ 2 กลับมา reachable
    """
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    student_id = await _make_debtor(db_pool, room_id)
    _, payment_id = await _make_bill(db_pool, room_id, student_id,
                                     amount=500.0, paid_amount=500.0)
    ft_id = await _seed_payment_event(db_pool, room_id, payment_id, account_id,
                                      amount=500.0, created_at=datetime(2026, 6, 1, 3, 0))

    winner_no = "REC-2569-6666"
    task = None
    conn1 = await db_pool.acquire()
    try:
        async with conn1.transaction():
            # ⚠️ **ไม่** ปิด FK trigger ที่นี่ — ต้องการให้แถวนี้ยึด KEY SHARE บนบิลตามปกติ
            await conn1.execute(
                """INSERT INTO finance_receipts
                       (room_id, receipt_no, doc_type, year_be, seq, student_payment_id,
                        legacy_transaction_id, amount, paid_total_after,
                        issued_to_name, issued_by_name, event_at, issued_at)
                   VALUES ($1, $2, 'receipt', 2569, 6666, $3, $4, 500.0, 500.0,
                           'ผู้ชนะการแข่ง', 'Tester', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                room_id, winner_no, payment_id, ft_id,
            )

            task = asyncio.create_task(
                FinanceService.issue_receipt(
                    db_pool, payment_id, admin_headers.user_id,
                    "test", "tester", doc_type="receipt", room_id=room_id,
                )
            )
            # 🎯 ต้องติดที่ **การล็อกบิล** ไม่ใช่ที่ตัว INSERT ของใบเสร็จ
            await _wait_until_blocked(db_pool, "%FOR UPDATE OF SP%")

        result = await asyncio.wait_for(task, timeout=20)
        task = None
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # เก็บกวาดเท่านั้น — ไม่สนใจ error
                pass
        await db_pool.release(conn1)

    assert result["reused"] is True
    assert result["receipt"]["receipt_no"] == winner_no

    # ✅ ไม่มีแถวใน receipt_sequences เลย = ไม่มีการจองเลขเกิดขึ้น ⇒ ชั้นที่ 1 เป็นคนจับ
    assert await _db_last_seq(db_pool, room_id, 2569) is None
    receipts = await _db_receipts(db_pool, room_id)
    assert len(receipts) == 1 and receipts[0]["receipt_no"] == winner_no
