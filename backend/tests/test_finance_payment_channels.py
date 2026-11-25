"""💳 [FIN-V2 / P2.4] ช่องทางชำระเงิน + PromptPay QR (integration, Postgres จริง)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **เลข PromptPay เต็มหลุดออก API** — เก็บ canonical ใน DB (ข้อจำกัด schema 0012)
   แต่ทุก response ต้อง mask ⇒ ตรวจทั้ง response text และ audit_logs
2. **เลขบัญชีเต็มไม่ถูกเก็บ** — `account_number_masked` ต้องเป็น mask เท่านั้น
3. **active ≤ 3 + primary 1 ตัว** — invariant ข้ามแถวที่ต้องนับใต้ `_lock_room_money`
   (มีเทสต์ยิงพร้อมกันจริงสองคำขอ)
4. **primary ไม่หายไป** — ลบ/ปิดตัวหลักต้อง promote ตัวถัดไปอัตโนมัติ
5. **QR ไม่เขียน DB** และตอบ `no-store` (ยอด fixed เปลี่ยนได้)
6. RBAC: อ่านได้ทุกสมาชิก เขียนได้เฉพาะ `MANAGE_FINANCE`
7. soft delete เท่านั้น (เอกสารเก่าอ้างช่องทางเดิมได้)

⚠️ ยืนยันกับ DB จริงผ่าน `db_pool` ตาม `docs/rules/testing.md`
"""
import asyncio
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"


def _channels_url(room_id: int) -> str:
    return f"{API_PREFIX}/{room_id}/finance/payment-channels"


def _channel_url(room_id: int, channel_id: int) -> str:
    return f"{_channels_url(room_id)}/{channel_id}"


def _promptpay(**over) -> dict:
    payload = {
        "channel_type": "promptpay",
        "label": "พร้อมเพย์ครูเอ",
        "account_name": "ครูเอ",
        "promptpay_id": "0812345678",
        "qr_mode": "open",
    }
    payload.update(over)
    return payload


def _cash(**over) -> dict:
    payload = {"channel_type": "cash", "label": "เงินสด"}
    payload.update(over)
    return payload


def _bank(**over) -> dict:
    payload = {
        "channel_type": "bank_transfer",
        "label": "ธนาคารกรุงไทย",
        "account_name": "ครูเอ",
        "bank_name": "กรุงไทย",
        "account_number": "1234567890",
    }
    payload.update(over)
    return payload


async def _channel_row(pool, channel_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, room_id, channel_type, label, promptpay_id_masked,
                      account_number_masked, qr_mode, is_primary, is_active,
                      deleted_at, updated_at
               FROM finance_payment_channels WHERE id = $1""",
            channel_id,
        )


# ═════════════════════════════════════════════════════ 14. mask PromptPay
async def test_create_promptpay_channel_masks_id(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    res = client.post(
        _channels_url(room_id), json=_promptpay(), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["promptpay_id_masked"] == "081-XXX-5678"
    assert body["has_qr"] is True
    assert body["is_primary"] is True  # active ตัวแรกเป็น primary อัตโนมัติ
    assert "0066812345678" not in res.text
    assert "0812345678" not in res.text

    row = await _channel_row(db_pool, body["id"])
    assert row["promptpay_id_masked"] == "0066812345678"
    assert row["qr_mode"] == "open"


# ═════════════════════════════════════════════════════ 15. mask เลขบัญชี
async def test_create_bank_channel_stores_only_mask(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    res = client.post(
        _channels_url(room_id), json=_bank(), headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["account_number_masked"] == "******7890"
    assert "1234567890" not in res.text

    row = await _channel_row(db_pool, body["id"])
    assert row["account_number_masked"] == "******7890"
    assert row["account_number_masked"] != "1234567890"


# ═════════════════════════════════════════════════════ 16. custom_qr ถูกปฏิเสธ
async def test_custom_qr_rejected(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    res = client.post(
        _channels_url(room_id),
        json={"channel_type": "custom_qr", "label": "QR ร้านค้า", "qr_mode": "open"},
        headers=admin_headers,
    )
    assert res.status_code == 400
    assert "ยังไม่รองรับ" in res.json()["detail"]

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_payment_channels WHERE room_id = $1", room_id,
        )
    assert count == 0


# ═════════════════════════════════════════════════════ 17. active ≤ 3
async def test_max_three_active_channels(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    created = [
        client.post(_channels_url(room_id), json=_cash(label=f"เงินสด {i}"), headers=admin_headers)
        for i in range(3)
    ]
    assert [r.status_code for r in created] == [200, 200, 200], [r.text for r in created]

    fourth = client.post(
        _channels_url(room_id), json=_cash(label="เงินสด 4"), headers=admin_headers,
    )
    assert fourth.status_code == 400
    assert "ครบ 3" in fourth.json()["detail"]

    # ปิด 1 ตัว → สร้างใหม่ได้
    off = client.patch(
        _channel_url(room_id, created[0].json()["id"]),
        json={"is_active": False}, headers=admin_headers,
    )
    assert off.status_code == 200, off.text

    again = client.post(
        _channels_url(room_id), json=_cash(label="เงินสด 4"), headers=admin_headers,
    )
    assert again.status_code == 200, again.text

    async with db_pool.acquire() as conn:
        active = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_payment_channels
               WHERE room_id = $1 AND is_active AND deleted_at IS NULL""",
            room_id,
        )
    assert active == 3


# ═════════════════════════════════════════════════════ 18. primary 1 ตัว
async def test_only_one_primary(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    a = client.post(_channels_url(room_id), json=_promptpay(), headers=admin_headers)
    assert a.status_code == 200 and a.json()["is_primary"] is True

    b = client.post(
        _channels_url(room_id), json=_cash(label="เงินสด", is_primary=True),
        headers=admin_headers,
    )
    assert b.status_code == 200, b.text
    assert b.json()["is_primary"] is True

    row_a = await _channel_row(db_pool, a.json()["id"])
    assert row_a["is_primary"] is False

    async with db_pool.acquire() as conn:
        primaries = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_payment_channels
               WHERE room_id = $1 AND is_primary AND deleted_at IS NULL""",
            room_id,
        )
    assert primaries == 1


# ═════════════════════════════════════════════════════ 19. ลบ primary → promote
async def test_delete_primary_promotes_next(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    a = client.post(_channels_url(room_id), json=_promptpay(), headers=admin_headers)
    b = client.post(_channels_url(room_id), json=_cash(), headers=admin_headers)
    assert a.json()["is_primary"] is True
    assert b.json()["is_primary"] is False

    deleted = client.delete(_channel_url(room_id, a.json()["id"]), headers=admin_headers)
    assert deleted.status_code == 200, deleted.text

    row_b = await _channel_row(db_pool, b.json()["id"])
    assert row_b["is_primary"] is True
    assert row_b["is_active"] is True


# ═════════════════════════════════════════════════════ 20. ปิดใช้งาน → QR 400
async def test_inactive_channel_qr_400(client, admin_headers):
    room_id = admin_headers.room_id
    created = client.post(
        _channels_url(room_id), json=_promptpay(), headers=admin_headers,
    ).json()

    off = client.patch(
        _channel_url(room_id, created["id"]),
        json={"is_active": False}, headers=admin_headers,
    )
    assert off.status_code == 200

    res = client.get(
        f"{_channel_url(room_id, created['id'])}/qr.svg", headers=admin_headers,
    )
    assert res.status_code == 400
    assert "ปิดใช้งาน" in res.json()["detail"]


# ═════════════════════════════════════════════════════ 21. QR headers/body
async def test_qr_svg_content_type_and_no_store(client, admin_headers):
    room_id = admin_headers.room_id
    created = client.post(
        _channels_url(room_id), json=_promptpay(), headers=admin_headers,
    ).json()

    res = client.get(
        f"{_channel_url(room_id, created['id'])}/qr.svg", headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert res.headers["cache-control"] == "no-store"
    assert res.text.lstrip().startswith("<svg")


# ═════════════════════════════════════════════════════ 22. open/fixed guards
async def test_qr_open_rejects_amount_and_fixed_requires_amount(client, admin_headers):
    room_id = admin_headers.room_id
    opened = client.post(
        _channels_url(room_id), json=_promptpay(), headers=admin_headers,
    ).json()
    bad_open = client.get(
        f"{_channel_url(room_id, opened['id'])}/qr.svg?amount=100",
        headers=admin_headers,
    )
    assert bad_open.status_code == 400
    assert "ไม่ระบุยอด" in bad_open.json()["detail"] or "open" in bad_open.json()["detail"]

    fixed = client.post(
        _channels_url(room_id),
        json=_promptpay(label="พร้อมเพย์ fixed", qr_mode="fixed"),
        headers=admin_headers,
    )
    assert fixed.status_code == 200, fixed.text
    bad_fixed = client.get(
        f"{_channel_url(room_id, fixed.json()['id'])}/qr.svg", headers=admin_headers,
    )
    assert bad_fixed.status_code == 400
    assert "ต้องระบุยอด" in bad_fixed.json()["detail"]

    ok_fixed = client.get(
        f"{_channel_url(room_id, fixed.json()['id'])}/qr.svg?amount=1250.50",
        headers=admin_headers,
    )
    assert ok_fixed.status_code == 200, ok_fixed.text


# ═════════════════════════════════════════════════════ 23. ยอด 2 ตำแหน่ง
async def test_qr_amount_is_formatted_two_decimals():
    from services.finance.qr import build_promptpay_payload

    payload = build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="fixed", amount=Decimal("1250.5"),
    )
    assert "54071250.50" in payload
    assert "," not in payload


# ═════════════════════════════════════════════════════ 24. ช่องทางไม่ใช่พร้อมเพย์
async def test_qr_non_promptpay_400(client, admin_headers):
    room_id = admin_headers.room_id
    cash = client.post(
        _channels_url(room_id), json=_cash(), headers=admin_headers,
    ).json()

    res = client.get(
        f"{_channel_url(room_id, cash['id'])}/qr.svg", headers=admin_headers,
    )
    assert res.status_code == 400
    assert "ไม่รองรับ" in res.json()["detail"]


# ═════════════════════════════════════════════════════ 25. list: sort + mask
async def test_channel_list_masks_and_sorts(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    p = client.post(_channels_url(room_id), json=_promptpay(), headers=admin_headers).json()
    c = client.post(_channels_url(room_id), json=_cash(), headers=admin_headers).json()
    b = client.post(_channels_url(room_id), json=_bank(), headers=admin_headers).json()
    assert p["is_primary"] is True

    res = client.get(_channels_url(room_id), headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()["channels"]
    assert [ch["id"] for ch in body] == [p["id"], c["id"], b["id"]]
    assert body[0]["is_primary"] is True
    assert "0066812345678" not in res.text
    assert "1234567890" not in res.text

    # ปิดใช้งาน 1 ตัว → list ปกติไม่เห็น, include_inactive เห็นครบ
    client.patch(
        _channel_url(room_id, c["id"]), json={"is_active": False}, headers=admin_headers,
    )
    visible = client.get(_channels_url(room_id), headers=admin_headers).json()["channels"]
    assert c["id"] not in [ch["id"] for ch in visible]

    all_res = client.get(
        _channels_url(room_id) + "?include_inactive=true", headers=admin_headers,
    ).json()["channels"]
    assert c["id"] in [ch["id"] for ch in all_res]


# ═════════════════════════════════════════════════════ 26. RBAC
async def test_channel_write_requires_manage_finance(client, member_headers):
    room_id = member_headers.room_id
    denied = client.post(
        _channels_url(room_id), json=_cash(), headers=member_headers,
    )
    assert denied.status_code == 403

    allowed = client.get(_channels_url(room_id), headers=member_headers)
    assert allowed.status_code == 200
    assert allowed.json()["channels"] == []


# ═════════════════════════════════════════════════════ 27. audit
async def test_channel_crud_writes_audit(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    created = client.post(
        _channels_url(room_id), json=_promptpay(), headers=admin_headers,
    ).json()
    client.patch(
        _channel_url(room_id, created["id"]), json={"label": "พร้อมเพย์ใหม่"},
        headers=admin_headers,
    )
    client.delete(_channel_url(room_id, created["id"]), headers=admin_headers)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT action, new_values::text AS new_values, old_values::text AS old_values
               FROM audit_logs
               WHERE entity_type = 'FINANCE_PAYMENT_CHANNEL' AND status = 'success'""",
        )
    actions = {r["action"] for r in rows}
    assert {"CREATE", "UPDATE", "DELETE"} <= actions
    for row in rows:
        assert "0066812345678" not in (row["new_values"] or "")
        assert "0066812345678" not in (row["old_values"] or "")


# ═════════════════════════════════════════════════════ 28. concurrency ≤3
async def test_channel_limit_enforced_under_concurrency(client, db_pool, admin_headers):
    """สองคำขอสร้างพร้อมกันต้องไม่ทะลุ 3 — พิสูจน์ว่า invariant อยู่ใต้ล็อกห้องจริง"""
    from models.finance_schemas import PaymentChannelCreate
    from services.finance_service import FinanceService

    room_id = admin_headers.room_id
    for i in range(2):
        res = client.post(
            _channels_url(room_id), json=_cash(label=f"เงินสด {i}"), headers=admin_headers,
        )
        assert res.status_code == 200, res.text

    results = await asyncio.gather(
        FinanceService.create_payment_channel(
            pool=db_pool, req=PaymentChannelCreate(channel_type="cash", label="A"),
            client_source="test", actor_identifier="test",
            room_id=room_id, user_id=admin_headers.user_id,
        ),
        FinanceService.create_payment_channel(
            pool=db_pool, req=PaymentChannelCreate(channel_type="cash", label="B"),
            client_source="test", actor_identifier="test",
            room_id=room_id, user_id=admin_headers.user_id,
        ),
        return_exceptions=True,
    )

    ok = [r for r in results if isinstance(r, dict)]
    failed = [r for r in results if isinstance(r, ValueError)]
    assert len(ok) == 1, results
    assert len(failed) == 1, results
    assert "ครบ 3" in str(failed[0])

    async with db_pool.acquire() as conn:
        active = await conn.fetchval(
            """SELECT COUNT(*) FROM finance_payment_channels
               WHERE room_id = $1 AND is_active AND deleted_at IS NULL""",
            room_id,
        )
    assert active == 3


# ═════════════════════════════════════════════════════ 29. soft delete
async def test_delete_is_soft(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    created = client.post(
        _channels_url(room_id), json=_cash(), headers=admin_headers,
    ).json()

    res = client.delete(_channel_url(room_id, created["id"]), headers=admin_headers)
    assert res.status_code == 200

    row = await _channel_row(db_pool, created["id"])
    assert row is not None
    assert row["deleted_at"] is not None
    assert row["is_active"] is False

    listed = client.get(_channels_url(room_id), headers=admin_headers).json()["channels"]
    assert created["id"] not in [c["id"] for c in listed]


# ═════════════════════════════════════════════════════ 30. QR ไม่เขียน DB
async def test_qr_does_not_write(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    created = client.post(
        _channels_url(room_id), json=_promptpay(), headers=admin_headers,
    ).json()

    async def snapshot():
        async with db_pool.acquire() as conn:
            return await conn.fetch(
                """SELECT id, label, is_primary, is_active, updated_at, deleted_at
                   FROM finance_payment_channels WHERE room_id = $1 ORDER BY id""",
                room_id,
            )

    before = await snapshot()
    res = client.get(
        f"{_channel_url(room_id, created['id'])}/qr.svg", headers=admin_headers,
    )
    assert res.status_code == 200
    after = await snapshot()

    assert [dict(r) for r in before] == [dict(r) for r in after]
