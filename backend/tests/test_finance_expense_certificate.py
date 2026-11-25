"""🧾 [FIN-V2 / P4.2] ใบรับรองแทนใบเสร็จ (CERT) — พ่วงใบสำคัญจ่าย

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **CERT ออกเฉพาะเมื่อมีบรรทัด `receipt_status='none'`** — ไม่มี none = ไม่มี CERT
   (ไม่ใช่ error, ไม่ใช่ใบเปล่า)
2. **ยอด CERT = ผลรวมเฉพาะบรรทัด none** — 250 attached + 100 none ⇒ 100.00
3. **CERT เป็นเอกสาร ไม่ใช่เงิน** — ไม่มี journal/txn/balance ใหม่เลย
4. **ลิงก์ครบ** — `voucher.cert_receipt_id`, `related_receipt_id`, และ
   `finance_document_links` ทิศ certificate → payment_voucher (`cert_for_voucher`)
5. **1 voucher = 1 CERT** — retry คีย์เดิมได้ใบเดิม (`cert:{voucher_id}`)
6. **atomic ทั้งใบ** — CERT ล้ม ⇒ voucher/PV/txn ไม่เหลือ
7. **ขอบเขตห้อง** — ห้องอื่นสร้างไม่ได้ ⇒ ไม่มี CERT หลุดข้ามห้อง

⚠️ ยืนยันกับ Postgres จริงทุกข้อผ่าน `db_pool` (กฎ docs/rules/testing.md)
"""
import importlib.util
import pathlib
import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
_CERT_DOC_TYPE = "certificate"


# ═══════════════════════════════════════════════════════════════════ helpers
# 🔁 ใช้ helper ของ P4.1 ตรง ๆ (tests/ ไม่ใช่ package ⇒ โหลดเป็นโมดูล)
_P41 = None


def _p41():
    global _P41
    if _P41 is None:
        path = pathlib.Path(__file__).with_name("test_finance_expense_voucher.py")
        spec = importlib.util.spec_from_file_location("_p41_helpers_for_p42", path)
        _P41 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_P41)
    return _P41


def _vouchers_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/expense-vouchers?target_type=room"


def _voucher_url(room_id: int, voucher_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/expense-vouchers/{voucher_id}?target_type=room"


async def _cert_rows(pool, voucher_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT * FROM finance_receipts
               WHERE doc_type = $1 AND idempotency_key = $2
               ORDER BY id""",
            _CERT_DOC_TYPE, f"cert:{voucher_id}",
        )


async def _cert_single(pool, voucher_id: int):
    rows = await _cert_rows(pool, voucher_id)
    assert len(rows) == 1, f"ต้องมี CERT 1 ใบ แต่พบ {len(rows)}"
    return rows[0]


async def _seed(pool, room: int):
    """หมวด 1 ใบ + กระเป๋า 1 ใบ (500)"""
    h = _p41()
    cat = await h._insert_category(pool, room, "วัสดุสำนักงาน")
    wallet = await h._insert_account(pool, room, "เงินสดห้อง", 500.0)
    return cat, wallet


async def _create(client, headers, room: int, payload: dict):
    return client.post(_vouchers_url(room), json=payload, headers=headers)


# ═══════════════ 1. มีบรรทัด none ⇒ ออก CERT 1 ใบ
async def test_cert_issued_when_any_line_has_no_receipt(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[
            h._line(250.0, category_id=cat, wallet_account_id=wallet,
                    description="มีใบเสร็จ", receipt_status="attached"),
            h._line(100.0, category_id=cat, wallet_account_id=wallet,
                    description="ไม่มีใบเสร็จ", receipt_status="none"),
        ],
    )
    res = await _create(client, admin_headers, room, payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cert_receipt_id"] is not None
    assert body["cert_receipt_no"].startswith("CERT-")
    assert body["cert_line_nos"] == [2]

    cert = await _cert_single(db_pool, body["id"])
    assert cert["room_id"] == room
    assert cert["doc_type"] == _CERT_DOC_TYPE


# ═══════════════ 2. ยอด CERT = ผลรวมเฉพาะบรรทัด none (ไม่ใช่ 350)
async def test_cert_amount_equals_sum_of_none_lines_only(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[
            h._line(250.0, category_id=cat, wallet_account_id=wallet,
                    description="มีใบเสร็จ", receipt_status="attached"),
            h._line(100.0, category_id=cat, wallet_account_id=wallet,
                    description="ไม่มีใบเสร็จ", receipt_status="none"),
        ],
    )
    res = await _create(client, admin_headers, room, payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert h._money(body["cert_amount"]) == "100.00"
    assert h._money(body["total_amount"]) == "350.00"

    cert = await _cert_single(db_pool, body["id"])
    assert h._money(cert["amount"]) == "100.00"
    assert h._money(cert["paid_total_after"]) == "0.00"


# ═══════════════ 3. ทุกบรรทัดมีหลักฐาน ⇒ ไม่มี CERT เลย
async def test_cert_not_issued_when_all_lines_have_receipts(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[
            h._line(150.0, category_id=cat, wallet_account_id=wallet,
                    receipt_status="attached"),
            h._line(50.0, category_id=cat, wallet_account_id=wallet,
                    receipt_status="paper", paper_bill_count=2),
        ],
    )
    res = await _create(client, admin_headers, room, payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cert_receipt_id"] is None
    assert body["cert_receipt_no"] is None
    assert body["cert_amount"] is None
    assert body["cert_line_nos"] == []

    assert await h._count(db_pool, "finance_receipts", room) == 1  # มีแต่ PV
    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = $2",
            room, _CERT_DOC_TYPE,
        ) == 0


# ═══════════════ 4. ลิงก์ voucher ↔ CERT ↔ PV ครบ
async def test_cert_links_to_pv_and_voucher(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                       receipt_status="none")],
    )
    res = await _create(client, admin_headers, room, payload)
    assert res.status_code == 200, res.text
    body = res.json()

    cert = await _cert_single(db_pool, body["id"])
    assert cert["related_receipt_id"] == body["pv_receipt_id"]

    async with db_pool.acquire() as conn:
        voucher = await conn.fetchrow(
            "SELECT cert_receipt_id, pv_receipt_id FROM finance_expense_vouchers WHERE id = $1",
            body["id"],
        )
        assert voucher["cert_receipt_id"] == cert["id"]
        assert voucher["pv_receipt_id"] == body["pv_receipt_id"]

        links = await conn.fetch(
            """SELECT from_doc_type, from_doc_id, to_doc_type, to_doc_id, link_type
               FROM finance_document_links WHERE room_id = $1""",
            room,
        )
        assert len(links) == 1
        link = links[0]
        assert link["from_doc_type"] == _CERT_DOC_TYPE
        assert link["from_doc_id"] == cert["id"]
        assert link["to_doc_type"] == "payment_voucher"
        assert link["to_doc_id"] == body["pv_receipt_id"]
        assert link["link_type"] == "cert_for_voucher"


# ═══════════════ 5. เลข CERT ไม่ซ้ำ + ปี พ.ศ. จาก event + seq จาก counter เดียวกัน
async def test_cert_has_unique_number_and_cert_prefix(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    body1 = (
        await _create(client, admin_headers, room, h._payload(
            default_wallet_account_id=wallet,
            lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                           receipt_status="none")],
        ))
    ).json()
    body2 = (
        await _create(client, admin_headers, room, h._payload(
            default_wallet_account_id=wallet,
            lines=[h._line(80.0, category_id=cat, wallet_account_id=wallet,
                           receipt_status="none")],
        ))
    ).json()

    cert1 = await _cert_single(db_pool, body1["id"])
    cert2 = await _cert_single(db_pool, body2["id"])

    assert cert1["receipt_no"].startswith("CERT-")
    assert cert2["receipt_no"].startswith("CERT-")
    assert cert1["receipt_no"] != cert2["receipt_no"]
    assert cert2["seq"] == cert1["seq"] + 1

    # ปี พ.ศ. ต้องมาจาก event_at ไม่ใช่เวลาที่กด
    expected_year_be = cert1["event_at"].astimezone(
        h.THAI_TZ
    ).year + 543
    assert cert1["year_be"] == expected_year_be

    async with db_pool.acquire() as conn:
        counter = await conn.fetchrow(
            """SELECT last_seq FROM receipt_sequences
               WHERE room_id = $1 AND year_be = $2 AND doc_type = $3""",
            room, expected_year_be, _CERT_DOC_TYPE,
        )
        assert counter["last_seq"] == cert2["seq"]


# ═══════════════ 6. CERT ไม่สร้าง journal / transaction ใหม่ (ไม่ใช่เงิน)
async def test_cert_writes_no_journal_or_transaction(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    async with db_pool.acquire() as conn:
        txn_before = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room,
        )
        journal_before = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room,
        )

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[
            h._line(250.0, category_id=cat, wallet_account_id=wallet,
                    receipt_status="attached"),
            h._line(100.0, category_id=cat, wallet_account_id=wallet,
                    receipt_status="none"),
        ],
    )
    res = await _create(client, admin_headers, room, payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cert_receipt_id"] is not None

    async with db_pool.acquire() as conn:
        txn_after = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_transactions WHERE room_id = $1", room,
        )
        journal_after = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room,
        )
        cert_refs = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_entries
               WHERE room_id = $1 AND (
                     reference_type ILIKE '%cert%' OR description ILIKE '%CERT%'
               )""",
            room,
        )

    # 2 บรรทัด ⇒ 2 txn + 2 journal จาก P4.1 เท่านั้น
    assert txn_after - txn_before == 2
    assert journal_after - journal_before == 2
    assert cert_refs == 0
    # ยอดกระเป๋าลดตาม 2 บรรทัด (350) — CERT ไม่แตะ
    assert h._money(await h._balance(db_pool, wallet)) == "150.00"


# ═══════════════ 7. CERT มี 2 ลายเซ็น (ไม่มี receiver)
async def test_cert_has_two_signature_rows(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)
    person = await h._insert_person(db_pool, room, "ครูอนุมัติ")

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                       receipt_status="none")],
        approved_by_person_id=person,
    )
    res = await _create(client, admin_headers, room, payload)
    assert res.status_code == 200, res.text
    cert = await _cert_single(db_pool, res.json()["id"])

    async with db_pool.acquire() as conn:
        sigs = await conn.fetch(
            """SELECT role, person_id, signer_name, signed_at, sort_order
               FROM finance_document_signatures
               WHERE doc_type = $1 AND doc_id = $2 ORDER BY sort_order""",
            _CERT_DOC_TYPE, cert["id"],
        )
    assert [s["role"] for s in sigs] == ["prepared", "approved"]
    assert [s["sort_order"] for s in sigs] == [0, 1]
    assert all(s["signed_at"] is None for s in sigs)
    assert sigs[1]["person_id"] == person
    assert all(s["role"] != "receiver" for s in sigs)


# ═══════════════ 8. retry คีย์เดิม ⇒ ได้ CERT ใบเดิม ไม่สร้างเพิ่ม
async def test_cert_replay_returns_same_certificate(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    payload = h._payload(
        key="certidem-" + uuid.uuid4().hex,
        default_wallet_account_id=wallet,
        lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                       receipt_status="none")],
    )
    first = await _create(client, admin_headers, room, payload)
    assert first.status_code == 200, first.text
    second = await _create(client, admin_headers, room, payload)
    assert second.status_code == 200, second.text

    a, b = first.json(), second.json()
    assert b["reused"] is True
    assert b["cert_receipt_id"] == a["cert_receipt_id"]
    assert b["cert_receipt_no"] == a["cert_receipt_no"]
    assert b["cert_amount"] == a["cert_amount"]
    assert len(await _cert_rows(db_pool, a["id"])) == 1


# ═══════════════ 9. idempotency_key = `cert:{voucher_id}`
async def test_cert_idempotency_key_is_cert_voucher_id(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    res = await _create(client, admin_headers, room, h._payload(
        default_wallet_account_id=wallet,
        lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                       receipt_status="none")],
    ))
    assert res.status_code == 200, res.text
    body = res.json()

    cert = await _cert_single(db_pool, body["id"])
    assert cert["idempotency_key"] == f"cert:{body['id']}"
    assert cert["layout_version"] == 2


# ═══════════════ 10. CERT ล้ม ⇒ ทั้งใบ rollback (ไม่มี voucher/PV/txn เหลือ)
async def test_cert_transaction_atomic_with_voucher(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    async def _boom(*args, **kwargs):
        raise ValueError("CERT ล้มกลางทาง (ทดสอบ)")

    payload = h._payload(
        default_wallet_account_id=wallet,
        lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                       receipt_status="none")],
    )
    with patch("services.finance.expense_vouchers.issue_certificate_locked", new=_boom):
        res = await _create(client, admin_headers, room, payload)

    assert res.status_code == 400, res.text
    assert await h._count(db_pool, "finance_expense_vouchers", room) == 0
    assert await h._count(db_pool, "finance_transactions", room) == 0
    assert await h._count(db_pool, "journal_entries", room) == 0
    assert await h._count(db_pool, "finance_receipts", room) == 0
    assert h._money(await h._balance(db_pool, wallet)) == "500.00"


# ═══════════════ 11. ขอบเขตห้อง — สร้างข้ามห้องไม่ได้ ⇒ ไม่มี CERT หลุด
async def test_cert_is_room_scoped(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    res = await _create(client, admin_headers, room, h._payload(
        default_wallet_account_id=wallet,
        lines=[h._line(100.0, category_id=cat, wallet_account_id=wallet,
                       receipt_status="none")],
    ))
    assert res.status_code == 200, res.text
    body = res.json()
    cert = await _cert_single(db_pool, body["id"])
    assert cert["room_id"] == room

    # ห้องอื่น — admin คนนี้ไม่ใช่สมาชิก ⇒ 403 และไม่มีร่องรอย
    other_room = await h._insert_room(db_pool, admin_headers.user_id)
    other_cat = await h._insert_category(db_pool, other_room, "วัสดุสำนักงาน")
    other_wallet = await h._insert_account(db_pool, other_room, "เงินสดห้อง", 500.0)
    cross = await _create(client, admin_headers, other_room, h._payload(
        default_wallet_account_id=other_wallet,
        lines=[h._line(100.0, category_id=other_cat, wallet_account_id=other_wallet,
                       receipt_status="none")],
    ))
    assert cross.status_code == 403, cross.text

    async with db_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1 AND doc_type = $2",
            other_room, _CERT_DOC_TYPE,
        ) == 0
        # CERT ของห้องเรายังผูกกับ PV ของห้องเราเท่านั้น
        pv = await conn.fetchrow(
            "SELECT room_id FROM finance_receipts WHERE id = $1", body["pv_receipt_id"],
        )
        assert pv["room_id"] == room


# ═══════════════ 12. ยอด CERT ปัด 2 ตำแหน่ง (0.1 + 0.2 = 0.30)
async def test_cert_cert_amount_rounds_to_two_decimals(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    res = await _create(client, admin_headers, room, h._payload(
        default_wallet_account_id=wallet,
        lines=[
            h._line(0.1, category_id=cat, wallet_account_id=wallet,
                    description="เศษหนึ่ง", receipt_status="none"),
            h._line(0.2, category_id=cat, wallet_account_id=wallet,
                    description="เศษสอง", receipt_status="none"),
        ],
    ))
    assert res.status_code == 200, res.text
    body = res.json()
    assert h._money(body["cert_amount"]) == "0.30"

    cert = await _cert_single(db_pool, body["id"])
    assert h._money(cert["amount"]) == "0.30"


# ═══════════════ 13. GET detail คืนฟิลด์ CERT ครบ
async def test_cert_detail_includes_cert_fields(
    client, db_pool, admin_headers,
):
    h = _p41()
    room = admin_headers.room_id
    cat, wallet = await _seed(db_pool, room)

    res = await _create(client, admin_headers, room, h._payload(
        default_wallet_account_id=wallet,
        lines=[
            h._line(250.0, category_id=cat, wallet_account_id=wallet,
                    receipt_status="attached"),
            h._line(100.0, category_id=cat, wallet_account_id=wallet,
                    receipt_status="none"),
        ],
    ))
    assert res.status_code == 200, res.text
    body = res.json()

    detail = client.get(_voucher_url(room, body["id"]), headers=admin_headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["cert_receipt_id"] == body["cert_receipt_id"]
    assert data["cert_receipt_no"] == body["cert_receipt_no"]
    assert h._money(data["cert_amount"]) == "100.00"
    assert data["cert_line_nos"] == [2]
