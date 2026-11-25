"""🧾 [FIN-V2 / P2.6] INV v2 (ช่องทาง + PromptPay QR) + ACK (ใบรับทราบยอดค้าง)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **INV snapshot ช่องทาง ≤3 / primary แรก / mask แล้ว** — เลขบัญชี/PromptPay เต็ม
   ห้ามหลุดออกเอกสารหรือ API (คอลัมน์ `promptpay_id_masked` เก็บ canonical เต็ม)
2. **QR ฝังยอดตาม qr_mode** — fixed มี tag 54, open ไม่มี; payload เก็บใน snapshot
3. **คำขอช่องทางที่ผิดไม่เผาเลข INV** — >3/ปิดใช้งาน/ต่างห้อง = 400 ก่อนจองเลข
4. **ACK ไม่แตะเงินเลย** — ไม่มี transaction/journal/กระเป๋า/เครดิต/paid_amount ขยับ
   และ `paid_total_after = 0` (ACK ไม่ใช่หลักฐานการชำระเงิน)
5. **ACK idempotent** — คีย์เดิม = ใบเดิม (`reused=true`) ไม่กินเลขซ้ำ
6. **include_invoice ผูก INV↔ACK ใน transaction เดียว** — ใบ INV ล้ม = ทั้งชุด rollback
7. **RBAC** — ADMIN/MANAGE_FINANCE ออกได้; สมาชิกธรรมดา 403

⚠️ ยืนยันกับ DB จริงผ่าน `db_pool` ตาม `docs/rules/testing.md`
"""
import json
import random
import re
import uuid
from datetime import date, datetime
from unittest.mock import patch

import pytest

from services.finance.constants import BUDDHIST_ERA_OFFSET, THAI_TZ
from services.finance.pdf import render_receipts_html
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices"
ROOM_INVOICES_PATH = API_PREFIX + "/{room}/finance/receipts/invoices/room"
ACKS_PATH = API_PREFIX + "/{room}/finance/acknowledgements"
CHANNELS_PATH = API_PREFIX + "/{room}/finance/payment-channels"
PAY_PATH = API_PREFIX + "/{room}/finance/payments/{payment_id}/pay"

_PAYLOAD = "0812345678"          # เบอร์ผู้ใช้จริง
_CANONICAL = "0066812345678"     # canonical ที่ DB เก็บ (ห้ามหลุดออก response/HTML)
_MASKED = "081-XXX-5678"


def _url(template: str, room_id: int, **kwargs) -> str:
    return template.format(room=room_id, **kwargs) + "?target_type=room"


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _make_debtor(pool, room_id: int, *, student_no: int = 90,
                       first_name: str = "เด็กชายทดสอบ") -> int:
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


async def _insert_account(pool, room_id: int, balance: float = 0.0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
            room_id, "กระเป๋ากลาง", balance,
        )


async def _make_other_room(pool, user_id: int) -> int:
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
    from core.config import settings

    discord_id = random.randint(1_000_000, 9_999_999)
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ('สมาชิก', 'ทดสอบ', $1, $2) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}", discord_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 51, 'student', 'active', FALSE, '[]'::jsonb)""",
            room_id, user_id,
        )
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id)}


# ═══════════════════════════════════════════════════════════════════ HTTP helpers
def _create_channel(client, headers, room_id, payload) -> dict:
    res = client.post(_url(CHANNELS_PATH, room_id), json=payload, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _cash(label: str = "เงินสด") -> dict:
    return {"channel_type": "cash", "label": label}


def _bank() -> dict:
    return {
        "channel_type": "bank_transfer", "label": "ธนาคารกรุงไทย",
        "account_name": "ครูเอ", "bank_name": "กรุงไทย",
        "account_number": "1234567890",
    }


def _promptpay(qr_mode: str = "open") -> dict:
    return {
        "channel_type": "promptpay", "label": "พร้อมเพย์ครูเอ",
        "account_name": "ครูเอ", "promptpay_id": _PAYLOAD, "qr_mode": qr_mode,
    }


def _issue_invoices(client, headers, student_ids, *, channel_ids=None, room_id=None):
    body = {"student_ids": student_ids}
    if channel_ids is not None:
        body["channel_ids"] = channel_ids
    return client.post(
        _url(INVOICES_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _issue_room_invoices(client, headers, *, channel_ids=None, room_id=None):
    body = {}
    if channel_ids is not None:
        body["channel_ids"] = channel_ids
    return client.post(
        _url(ROOM_INVOICES_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _ack_body(**over) -> dict:
    body = {
        "scope": "room",
        "include_invoice": True,
        "idempotency_key": f"ack-{uuid.uuid4().hex[:16]}",
    }
    body.update(over)
    return body


def _issue_ack(client, headers, *, room_id=None, **over):
    return client.post(
        _url(ACKS_PATH, room_id if room_id is not None else headers.room_id),
        json=_ack_body(**over), headers=headers,
    )


def _pay_full(client, headers, payment_id: int, account_id: int, amount: float):
    return client.put(
        _url(PAY_PATH, headers.room_id, payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )


# ═══════════════════════════════════════════════════════════════════ DB helpers
async def _payment_id_of(pool, collection_id: int, student_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT id FROM student_payments WHERE collection_id = $1 AND student_id = $2",
            collection_id, student_id,
        )


async def _meta_of(pool, receipt_no: str) -> dict:
    async with pool.acquire() as conn:
        raw = await conn.fetchval(
            "SELECT document_meta FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        )
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


async def _doc_row(pool, receipt_no: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, receipt_no, doc_type, year_be, seq, amount, paid_total_after,
                      layout_version, document_meta, idempotency_key, status
               FROM finance_receipts WHERE receipt_no = $1""",
            receipt_no,
        )


async def _count(pool, sql: str, *args) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def _invoices(pool, room_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, receipt_no, student_id, amount FROM finance_receipts
               WHERE room_id = $1 AND doc_type = 'invoice' ORDER BY id""",
            room_id,
        )


async def _ack_entries(pool, ack_id: int) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT student_id, invoice_receipt_id, outstanding_amount
               FROM finance_ack_entries WHERE ack_receipt_id = $1 ORDER BY id""",
            ack_id,
        )


async def _render_doc(pool, room_id: int, user_id: int, receipt_no: str) -> str:
    """ดึงเอกสารผ่าน service (shape เดียวกับหน้าจอ) แล้วเรนเดอร์ HTML รวมของ shell"""
    doc = await FinanceService.get_receipt(
        pool=pool, receipt_no=receipt_no, client_source="test",
        actor_identifier="test", room_id=room_id, user_id=user_id,
    )
    return render_receipts_html([FinanceService._document_context(doc)])


def _today_year_be() -> int:
    return datetime.now(THAI_TZ).year + BUDDHIST_ERA_OFFSET


# ═══════════════════════════════════════ 1. snapshot ช่องทาง (≤3, primary แรก)
async def test_invoice_snapshot_holds_at_most_three_channels_primary_first(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=1000.0)

    primary = _create_channel(client, admin_headers, room_id, _promptpay("open"))
    bank = _create_channel(client, admin_headers, room_id, _bank())
    cash = _create_channel(client, admin_headers, room_id, _cash())
    assert primary["is_primary"] is True

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    meta = await _meta_of(db_pool, res.json()["receipts"][0]["receipt_no"])

    assert len(meta["channels"]) == 3
    assert [c["channel_id"] for c in meta["channels"]] == [
        primary["id"], bank["id"], cash["id"],
    ]
    assert meta["channels"][0]["is_primary"] is True
    assert meta["primary_channel_id"] == primary["id"]


# ═══════════════════════════════════ 2. PromptPay/บัญชีต้องถูก mask ทุกจุด
async def test_invoice_snapshot_masks_promptpay_and_account_numbers(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=500.0)

    _create_channel(client, admin_headers, room_id, _promptpay("open"))
    _create_channel(client, admin_headers, room_id, _bank())

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipts"][0]["receipt_no"]
    meta = await _meta_of(db_pool, receipt_no)

    by_type = {c["channel_type"]: c for c in meta["channels"]}
    assert by_type["promptpay"]["promptpay_id_masked"] == _MASKED
    assert by_type["bank_transfer"]["account_number_masked"] == "******7890"

    # 🔒 เลขเต็มต้องไม่โผล่ใน response และไม่โผล่ใน snapshot ของ "ช่องทาง"
    #    ⚠️ `qr_payload` มี canonical อยู่ข้างในโดยธรรมชาติ (EMVCo tag 29) —
    #    ข้อบังคับคือ "payload ห้ามออกจาก server" ⇒ ตรวจที่ HTML (เทสต์ dispatch) แทน
    assert _PAYLOAD not in res.text
    assert "1234567890" not in res.text
    assert _CANONICAL not in json.dumps(meta["channels"], ensure_ascii=False)
    assert _CANONICAL in meta["qr_payload"], "payload ต้องสร้างจากเลขเต็มใน DB (ฝั่ง server)"


# ═══════════════════════════════════════════════ 3-4. QR ฝังยอด / ไม่ฝังยอด
async def test_fixed_qr_embeds_invoice_amount(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=1000.0)
    _create_channel(client, admin_headers, room_id, _promptpay("fixed"))

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    meta = await _meta_of(db_pool, res.json()["receipts"][0]["receipt_no"])

    payload = meta["qr_payload"]
    assert payload is not None
    assert payload.startswith("000201010212"), "QR fixed ต้องมี tag 01 = 12"
    assert "54071000.00" in payload, "ยอดในใบต้องถูกฝังเป็น tag 54"


async def test_open_qr_has_no_amount_tag(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=1000.0)
    _create_channel(client, admin_headers, room_id, _promptpay("open"))

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    meta = await _meta_of(db_pool, res.json()["receipts"][0]["receipt_no"])

    payload = meta["qr_payload"]
    assert payload.startswith("000201010211"), "QR open ต้องมี tag 01 = 11"
    # 🔴 ตรวจ tag 54 แบบเป็นขอบเขต TLV ไม่ใช่ substring "54" (มีได้ในเลขอื่น)
    assert re.search(r"54\d{2}\d{2}\.\d{2}", payload) is None


# ═════════════════════════════ 5-7. คำขอช่องทางผิด / ลำดับที่ผู้ใช้เลือก
async def test_more_than_three_channel_ids_is_400_and_burns_no_sequence(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id)

    res = _issue_invoices(client, admin_headers, [student_id],
                          channel_ids=[1, 2, 3, 4])
    assert res.status_code == 400, res.text
    assert "ไม่เกิน 3" in res.json()["detail"]
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1 AND doc_type = 'invoice'",
        room_id,
    ) == 0
    assert await _invoices(db_pool, room_id) == []


async def test_inactive_or_foreign_channel_is_400(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id)

    _create_channel(client, admin_headers, room_id, _cash())
    second = _create_channel(client, admin_headers, room_id, _bank())
    # ปิดใช้งานช่องทางที่สอง (ไม่ใช่ primary) — ต้องเลือกไม่ได้อีก
    deact = client.patch(
        _url(CHANNELS_PATH + "/{channel_id}", room_id, channel_id=second["id"]),
        json={"is_active": False}, headers=admin_headers,
    )
    assert deact.status_code == 200, deact.text

    res = _issue_invoices(client, admin_headers, [student_id], channel_ids=[second["id"]])
    assert res.status_code == 400, res.text

    # ช่องทางของห้องอื่นก็เลือกไม่ได้
    other_room = await _make_other_room(db_pool, admin_headers.user_id)
    foreign = _create_channel(client, admin_headers, other_room, _cash("ห้องอื่น"))
    res2 = _issue_invoices(client, admin_headers, [student_id], channel_ids=[foreign["id"]])
    assert res2.status_code == 400, res2.text

    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1 AND doc_type = 'invoice'",
        room_id,
    ) == 0


async def test_requested_order_is_kept_and_primary_is_prepended(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id)

    primary = _create_channel(client, admin_headers, room_id, _cash())     # primary อัตโนมัติ
    bank = _create_channel(client, admin_headers, room_id, _bank())
    pp = _create_channel(client, admin_headers, room_id, _promptpay("open"))

    # ผู้ใช้เลือก [promptpay, bank] แต่ไม่ได้เลือก primary ⇒ primary ต้องแทรกเป็นตัวแรก
    res = _issue_invoices(client, admin_headers, [student_id],
                          channel_ids=[pp["id"], bank["id"]])
    assert res.status_code == 200, res.text
    meta = await _meta_of(db_pool, res.json()["receipts"][0]["receipt_no"])

    assert [c["channel_id"] for c in meta["channels"]] == [
        primary["id"], pp["id"], bank["id"],
    ]

    # เลือก primary เอง ⇒ ลำดับของผู้ใช้คงเดิม
    res2 = _issue_invoices(client, admin_headers, [student_id],
                           channel_ids=[bank["id"], primary["id"]])
    assert res2.status_code == 200, res2.text
    meta2 = await _meta_of(db_pool, res2.json()["receipts"][0]["receipt_no"])
    assert [c["channel_id"] for c in meta2["channels"]] == [bank["id"], primary["id"]]


# ═════════════════════════════════════════ 8-9. ไม่มีช่องทาง / snapshot รายการ
async def test_no_channels_snapshot_is_empty_and_has_no_qr(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id)

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    meta = await _meta_of(db_pool, res.json()["receipts"][0]["receipt_no"])

    assert meta["channels"] == []
    assert meta["primary_channel_id"] is None
    assert meta["qr_payload"] is None


async def test_invoice_line_items_keep_legacy_contract_and_due_date_is_earliest(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, title="ค่าเทอม", amount=1000.0,
                     due_date=date(2027, 3, 1))
    await _make_bill(db_pool, room_id, student_id, title="ค่าอาหาร", amount=250.5,
                     due_date=date(2026, 12, 15))

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipts"][0]["receipt_no"]
    meta = await _meta_of(db_pool, receipt_no)

    assert meta["due_date"] == "2026-12-15"
    async with db_pool.acquire() as conn:
        items = json.loads(await conn.fetchval(
            "SELECT line_items FROM finance_receipts WHERE receipt_no = $1", receipt_no,
        ))
    assert {(it["title"], it["due_date"]) for it in items} == {
        ("ค่าเทอม", "2027-03-01"), ("ค่าอาหาร", "2026-12-15"),
    }
    assert all(set(it) == {"title", "amount", "due_date"} for it in items)


# ═══════════════════════════════ 10 / 3-cont. dispatch + HTML ของ INV v2
async def test_invoice_v2_html_has_channels_qr_and_no_receiver_signature(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=1000.0)
    _create_channel(client, admin_headers, room_id, _promptpay("fixed"))

    res = _issue_invoices(client, admin_headers, [student_id])
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipts"][0]["receipt_no"]

    doc = await FinanceService.get_receipt(
        pool=db_pool, receipt_no=receipt_no, client_source="test",
        actor_identifier="test", room_id=room_id, user_id=admin_headers.user_id,
    )
    ctx = FinanceService._document_context(doc)
    assert ctx["body_template"] == "_invoice_body_v2.html"
    assert ctx["is_receipt"] is False

    html = render_receipts_html([ctx])
    assert "ช่องทางชำระเงิน" in html
    assert "ช่องทางหลัก" in html
    assert "data:image/svg+xml;base64," in html
    assert "ผู้ออกเอกสาร" in html
    assert "ผู้รับเงิน" not in html, "INV ไม่มีช่องเซ็นผู้รับเงิน"
    assert "ไม่ใช่หลักฐานการชำระเงิน" in html
    assert _MASKED in html
    assert _PAYLOAD not in html and _CANONICAL not in html
    assert html.count("data:font/ttf;base64,") == 2, "ฟอนต์ต้องฝังครั้งเดียว (Regular+Bold)"


# ══════════════════════════════════════════ 11/21/22. ถ้อยคำ + ไม่มี QR ใน ACK
async def test_ack_html_words_and_no_qr_or_receipt_wording(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    student_id = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, student_id, amount=750.0)

    res = _issue_ack(client, admin_headers, scope="room", include_invoice=False)
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipt"]["receipt_no"]

    doc = await FinanceService.get_receipt(
        pool=db_pool, receipt_no=receipt_no, client_source="test",
        actor_identifier="test", room_id=room_id, user_id=admin_headers.user_id,
    )
    ctx = FinanceService._document_context(doc)
    assert ctx["body_template"] == "_acknowledgement_body_v2.html"

    html = render_receipts_html([ctx])
    assert "ใบรับทราบยอดค้าง" in html
    assert "ไม่ใช่หลักฐานการชำระเงิน" in html
    assert "ผู้รับทราบ" in html and "ผู้แจ้ง" in html
    assert "ผู้รับเงิน" not in html
    assert "ใบเสร็จรับเงิน" not in html
    assert "data:image/svg" not in html, "ACK ห้ามมี QR"
    assert "ช่องทางชำระเงิน" not in html, "ACK ห้ามมีช่องทางชำระเงิน"
    assert html.count("data:font/ttf;base64,") == 2


# ════════════════════════════════ 12-14. ยอด/รายชื่อ/ไม่แตะเงินของ ACK
async def test_ack_amount_is_total_outstanding_and_no_money_moves(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id, balance=4321.0)
    s1 = await _make_debtor(db_pool, room_id, student_no=91)
    s2 = await _make_debtor(db_pool, room_id, student_no=92)
    await _make_bill(db_pool, room_id, s1, amount=1000.0)
    await _make_bill(db_pool, room_id, s2, amount=250.5)

    async def snapshot():
        async with db_pool.acquire() as conn:
            return {
                "balance": float(await conn.fetchval(
                    "SELECT COALESCE(SUM(balance), 0) FROM finance_accounts WHERE room_id = $1",
                    room_id)),
                "paid": float(await conn.fetchval(
                    """SELECT COALESCE(SUM(SP.paid_amount), 0) FROM student_payments SP
                       JOIN fee_collections FC ON FC.id = SP.collection_id
                       WHERE FC.room_id = $1""", room_id)),
                "transactions": await conn.fetchval(
                    "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room_id),
                "journal_entries": await conn.fetchval(
                    "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id),
                "journal_lines": await conn.fetchval(
                    """SELECT COUNT(*) FROM journal_lines L
                       JOIN journal_entries E ON E.id = L.journal_entry_id
                       WHERE E.room_id = $1""", room_id),
                "credits": await conn.fetchval(
                    "SELECT COUNT(*) FROM student_credits WHERE room_id = $1", room_id),
            }

    before = await snapshot()
    res = _issue_ack(client, admin_headers, scope="selected",
                     student_ids=[s1, s2], include_invoice=True)
    assert res.status_code == 200, res.text
    body = res.json()

    ack_row = await _doc_row(db_pool, body["receipt"]["receipt_no"])
    assert float(ack_row["amount"]) == pytest.approx(1250.5, abs=0.005)
    assert float(ack_row["paid_total_after"]) == 0.0
    assert ack_row["layout_version"] == 2
    assert ack_row["doc_type"] == "acknowledgement"

    assert {e["student_id"] for e in body["entries"]} == {s1, s2}
    assert len(body["entries"]) == 2
    rows = await _ack_entries(db_pool, ack_row["id"])
    assert [r["student_id"] for r in rows] == [s1, s2], "1 แถว/นักเรียน ตามลำดับที่เลือก"

    after = await snapshot()
    assert after == before, f"ACK ต้องไม่แตะเงินเลย (ก่อน={before} หลัง={after})"
    assert account_id  # กระเป๋าถูกสร้างจริง (กัน snapshot เทียบ 0 กับ 0)


# ═══════════════════════════════ 15-16. ขอบเขตทั้งห้อง / คนที่เลือก
async def test_room_scope_skips_fully_paid_students(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    unpaid = await _make_debtor(db_pool, room_id, student_no=93)
    paid = await _make_debtor(db_pool, room_id, student_no=94)
    await _make_bill(db_pool, room_id, unpaid, amount=400.0)
    c2 = await _make_bill(db_pool, room_id, paid, amount=600.0)
    paid_payment = await _payment_id_of(db_pool, c2, paid)
    assert _pay_full(client, admin_headers, paid_payment, account_id, 600.0).status_code == 200

    res = _issue_ack(client, admin_headers, scope="room", include_invoice=False)
    assert res.status_code == 200, res.text
    entries = res.json()["entries"]
    assert [e["student_id"] for e in entries] == [unpaid]


async def test_room_scope_with_no_debtors_is_400(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    account_id = await _insert_account(db_pool, room_id)
    sid = await _make_debtor(db_pool, room_id)
    collection_id = await _make_bill(db_pool, room_id, sid, amount=300.0)
    payment_id = await _payment_id_of(db_pool, collection_id, sid)
    assert _pay_full(client, admin_headers, payment_id, account_id, 300.0).status_code == 200

    res = _issue_ack(client, admin_headers, scope="room", include_invoice=False)
    assert res.status_code == 400, res.text
    assert "ไม่มีนักเรียนที่มียอดค้าง" in res.json()["detail"]
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = 'acknowledgement'",
        room_id,
    ) == 0


async def test_selected_student_without_debt_is_400(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _make_debtor(db_pool, room_id)

    res = _issue_ack(client, admin_headers, scope="selected",
                     student_ids=[sid], include_invoice=False)
    assert res.status_code == 400, res.text
    assert "ไม่มีบิลค้างชำระ" in res.json()["detail"]


# ═══════════════════════════════════════════════════ 17. idempotency
async def test_ack_is_idempotent_with_same_key(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, sid, amount=880.0)
    key = f"ack-{uuid.uuid4().hex[:16]}"

    first = _issue_ack(client, admin_headers, scope="selected", student_ids=[sid],
                       include_invoice=True, idempotency_key=key)
    assert first.status_code == 200, first.text
    assert first.json()["reused"] is False
    inv_count_before = len(await _invoices(db_pool, room_id))

    second = _issue_ack(client, admin_headers, scope="selected", student_ids=[sid],
                        include_invoice=True, idempotency_key=key)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["reused"] is True
    assert body["receipt"]["receipt_no"] == first.json()["receipt"]["receipt_no"]
    assert body["entries"] == first.json()["entries"]

    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = 'acknowledgement'",
        room_id,
    ) == 1
    assert len(await _invoices(db_pool, room_id)) == inv_count_before, (
        "replay ต้องไม่ออก INV ชุดใหม่"
    )


# ═════════════════════════════ 18-19. include_invoice true/false + links
async def test_include_invoice_true_links_invoices_to_ack(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    s1 = await _make_debtor(db_pool, room_id, student_no=95)
    s2 = await _make_debtor(db_pool, room_id, student_no=96)
    await _make_bill(db_pool, room_id, s1, amount=100.0)
    await _make_bill(db_pool, room_id, s2, amount=200.0)

    res = _issue_ack(client, admin_headers, scope="selected", student_ids=[s1, s2],
                     include_invoice=True)
    assert res.status_code == 200, res.text
    body = res.json()
    ack_id = body["receipt"]["id"]

    # response ต้องประกาศ entries/invoice_receipt_nos ครบ (ไม่งั้น response_model ตัดทิ้ง)
    assert len(body["invoice_receipt_nos"]) == 2
    assert all(e["invoice_receipt_id"] and e["invoice_receipt_no"] for e in body["entries"])

    invoices = await _invoices(db_pool, room_id)
    assert len(invoices) == 2
    assert sorted(i["receipt_no"] for i in invoices) == sorted(body["invoice_receipt_nos"])
    assert {i["student_id"] for i in invoices} == {s1, s2}

    async with db_pool.acquire() as conn:
        links = await conn.fetch(
            """SELECT from_doc_type, from_doc_id, to_doc_type, to_doc_id, link_type
               FROM finance_document_links WHERE room_id = $1""",
            room_id,
        )
    assert len(links) == 2
    assert {l["from_doc_type"] for l in links} == {"acknowledgement"}
    assert {l["from_doc_id"] for l in links} == {ack_id}
    assert {l["to_doc_type"] for l in links} == {"invoice"}
    assert {l["link_type"] for l in links} == {"invoice_for_ack"}
    assert {l["to_doc_id"] for l in links} == {i["id"] for i in invoices}


async def test_include_invoice_false_writes_no_invoice_or_link(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, sid, amount=120.0)

    res = _issue_ack(client, admin_headers, scope="room", include_invoice=False)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["invoice_receipt_nos"] == []
    assert all(e["invoice_receipt_id"] is None for e in body["entries"])
    assert await _invoices(db_pool, room_id) == []
    assert await _count(
        db_pool, "SELECT COUNT(*) FROM finance_document_links WHERE room_id = $1", room_id,
    ) == 0


# ══════════════════════════════════════════ 20. RBAC + router pre-DB guards
async def test_member_cannot_issue_acknowledgement(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    sid = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, sid)
    member = await _member_headers_in(db_pool, room_id)

    res = _issue_ack(client, member, room_id=room_id, scope="room")
    assert res.status_code == 403, res.text
    assert await _count(
        db_pool,
        "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = 'acknowledgement'",
        room_id,
    ) == 0


async def test_ack_request_shape_is_validated_before_db(client, db_pool, admin_headers):
    room_id = admin_headers.room_id

    empty_selected = _issue_ack(client, admin_headers, scope="selected",
                                student_ids=[], include_invoice=False)
    assert empty_selected.status_code == 400, empty_selected.text

    room_with_ids = _issue_ack(client, admin_headers, scope="room",
                               student_ids=[123], include_invoice=False)
    assert room_with_ids.status_code == 400, room_with_ids.text


# ═══════════════════════════════════════════════ 23. เลข ACK (ปี พ.ศ. + seq 1)
async def test_ack_numbering_uses_buddhist_year_and_own_sequence(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    sid = await _make_debtor(db_pool, room_id)
    await _make_bill(db_pool, room_id, sid)

    res = _issue_ack(client, admin_headers, scope="room", include_invoice=False)
    assert res.status_code == 200, res.text
    receipt_no = res.json()["receipt"]["receipt_no"]

    year_be = res.json()["receipt"]["year_be"]
    assert year_be == _today_year_be()
    assert receipt_no == f"ACK-{year_be}-0001"
    row = await _doc_row(db_pool, receipt_no)
    assert row["seq"] == 1
    assert await _count(
        db_pool,
        """SELECT last_seq FROM receipt_sequences
           WHERE room_id = $1 AND doc_type = 'acknowledgement' AND year_be = $2""",
        room_id, year_be,
    ) == 1


# ═══════════════════════════════ 24. all-or-nothing (INV ล้ม = ACK ไม่เกิด)
async def test_ack_is_all_or_nothing_when_an_invoice_fails(
    client, db_pool, admin_headers
):
    room_id = admin_headers.room_id
    s1 = await _make_debtor(db_pool, room_id, student_no=97)
    s2 = await _make_debtor(db_pool, room_id, student_no=98)
    await _make_bill(db_pool, room_id, s1, amount=100.0)
    await _make_bill(db_pool, room_id, s2, amount=200.0)

    original = FinanceService._issue_invoice_aggregate
    state = {"calls": 0}

    async def flaky(cls, *args, **kwargs):
        state["calls"] += 1
        if state["calls"] >= 2:
            raise RuntimeError("forced failure on second invoice")
        return await original.__func__(cls, *args, **kwargs)

    with patch.object(FinanceService, "_issue_invoice_aggregate", classmethod(flaky)):
        with pytest.raises(RuntimeError):
            _issue_ack(client, admin_headers, scope="selected",
                       student_ids=[s1, s2], include_invoice=True)

    assert state["calls"] == 2, "ต้องพยายามออก INV ครบก่อนล้ม"
    async with db_pool.acquire() as conn:
        acks = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = 'acknowledgement'",
            room_id,
        )
        invs = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = 'invoice'",
            room_id,
        )
        seqs = await conn.fetchval(
            "SELECT COUNT(*) FROM receipt_sequences WHERE room_id = $1", room_id,
        )
        entries = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_ack_entries WHERE room_id = $1", room_id,
        )
        links = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_document_links WHERE room_id = $1", room_id,
        )
    assert (acks, invs, seqs, entries, links) == (0, 0, 0, 0, 0), (
        "transaction ต้อง rollback ทั้งชุด — INV ใบที่สำเร็จแล้วและเลขที่จองไปต้องหายด้วย"
    )
