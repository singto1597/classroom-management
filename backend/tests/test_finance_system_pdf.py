"""[F5/PR-3] System PDF route ของบอท — `POST /{target_id}/finance/system/receipts/pdf`

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร (เรียงตามความสำคัญ)
═══════════════════════════════════════════════════════════════════════════════
1. **"คู่แฝดต้องไม่ยืดหยุ่นตามกัน"** — route เดิม (`/finance/receipts/pdf`) ต้องยัง
   **ปฏิเสธ** principal แบบบอทระบบ ⇒ พิสูจน์ว่าการเพิ่ม route ใหม่ไม่ได้เปิดประตูหลัง
   ให้หน้าจอเดิม (ข้อนี้มีค่าที่สุดของไฟล์: การเผลอเปลี่ยน `get_current_user` เป็น
   `get_current_user_or_bot` ที่ route เดิม จะไม่ทำให้เทสต์อื่นล้มแม้แต่ตัวเดียว)

2. **ด่านสมาชิกถูกปิดให้ "บอทระบบ" เท่านั้น** — บอทที่ไม่มี `users` row ต้องได้ 200
   แต่ JWT ของคนนอกห้องต้องยังได้ 403 (มิฉะนั้นคือช่องอ่านเอกสารข้ามห้อง)

3. **ด่านที่สำคัญที่สุดยังอยู่** — เลขของห้องอื่นยัง 404 เพราะด่านนั้นอยู่ใน SQL ของ
   service ไม่ใช่ในตัว router (งานนี้ **ไม่แตะ** SQL นั้น — เทสต์นี้กันไม่ให้มีคนไปแตะ)

4. **อ่านเท่านั้น 100%** — หลังเรียกสำเร็จทั้ง `finance_receipts` และ `receipt_sequences`
   ต้องไม่ขยับ **และซอร์สของ router ต้องไม่มี SQL/การเรียก DB เลย** (ด่านที่สองเพราะ
   ด่านแรกพิสูจน์ได้แค่เส้นทางที่เทสต์วิ่งไปถึง — ไม่ใช่เส้นทางที่ยังไม่มีใครเขียน)

5. **audit log ต้องบอกตัวตนได้** — บอทระบบไม่มี `user_id` ⇒ ต้องตกไปใช้ `X-Actor-Id`
   ไม่ใช่บันทึกสตริง `"user_id:None"` ที่อ่านเหมือน "ผู้ใช้ที่ id เป็น None"

⚠️ ทุกเทสต์ยืนยันกับ DB จริงผ่าน `db_pool` ไม่เชื่อแค่ HTTP status (docs/rules/testing.md)
⚠️ ไฟล์นี้เป็น **เอกเทศ** เหมือนเทสต์ไฟล์อื่นใน repo (`tests/` ไม่มี `__init__.py` และ
   ไม่มีการ import ข้ามไฟล์เทสต์) ⇒ helper ถูกคัดลอกรูปมาจาก `test_finance_receipts.py`
"""
import ast
import json
import random
import string
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from core.config import settings
from services.finance.constants import RECEIPTS_PER_PDF_MAX

pytestmark = pytest.mark.asyncio

# ⚠️ finance router mount ด้วย prefix `/api/classroom` (backend/main.py)
API_PREFIX = "/api/classroom"
SYSTEM_PDF_PATH = API_PREFIX + "/{target}/finance/system/receipts/pdf"
WEB_PDF_PATH = API_PREFIX + "/{target}/finance/receipts/pdf"
PAY_PATH = API_PREFIX + "/{target}/finance/payments/{payment_id}/pay"
RECEIPTS_PATH = API_PREFIX + "/{target}/finance/receipts"

FAKE_PDF = b"%PDF-1.4\n% fake\n%%EOF\n"

# 🪪 ค่าที่บอทส่งมาจริง (`bot_discord/services/finance_api.py: AUTO_ATTACH_ACTOR`)
BOT_ACTOR = "discord-bot:auto-attach"

# 🖨️ ตัวคั่นหน้าในไฟล์รวม — เทมเพลตใส่คลาสนี้ให้ **ทุกใบยกเว้นใบสุดท้าย**
#    (`backend/templates/finance/receipt.html`: `class="doc{% if not loop.last %} doc-break"`)
DOC_BREAK = '<div class="doc doc-break">'


def _page_count(html: str) -> int:
    """นับ "หน้า" ในไฟล์รวม = ตัวคั่นหน้า + 1

    ⚠️ **ห้ามนับ `'<div class="doc'`**: `<div class="doc-title">` ก็ขึ้นต้นด้วยสตริงนั้น
       ⇒ ใบเดียวจะนับได้ 2 ซึ่งอ่านแล้วเหมือน "มี 2 หน้า" (พลาดมาแล้วรอบหนึ่ง)
    """
    return html.count(DOC_BREAK) + 1


def _bot_user_id() -> int:
    """id ของ bot application — ช่วงเดียวกับ `test_get_room_data_auth_chain.py`"""
    return random.randint(10_000_000_000, 99_999_999_999)


def _seven_digit_id() -> int:
    """ช่วง 7 หลัก — ใช้ทั้งเป็น server_id และ discord_id ของ user ที่มีอยู่จริง"""
    return random.randint(1_000_000, 9_999_999)


# ═══════════════════════════════════════════════════════════════════ seed helpers
async def _insert_user(pool, *, discord_id=None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username, discord_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            "ทดสอบ", "ระบบ", f"u{uuid.uuid4().hex[:12]}", discord_id,
        )


async def _insert_room(pool, owner_id: int, *, server_id=None) -> int:
    """ห้องที่ owner เป็นสมาชิก (president + is_admin) — ยิง API ด้วย JWT ของ owner ได้"""
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """INSERT INTO rooms (room_name, room_code, owner_id, server_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            "ห้องทดสอบ", code, owner_id, server_id,
        )
        await conn.execute(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, 0, 'president', 'active', TRUE, '["all"]'::jsonb)""",
            room_id, owner_id,
        )
    return room_id


async def _insert_account(pool, room_id: int) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, 0) RETURNING id",
            room_id, "กระเป๋ากลาง",
        )


async def _make_debtor(pool, room_id: int, *, student_no: int = 90) -> int:
    async with pool.acquire() as conn:
        user_id = await conn.fetchval(
            """INSERT INTO users (first_name, last_name, username)
               VALUES ('เด็กชายทดสอบ', 'ทดลอง', $1) RETURNING id""",
            f"u{uuid.uuid4().hex[:12]}",
        )
        return await conn.fetchval(
            """INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
               VALUES ($1, $2, $3, 'student', 'active', FALSE, '[]'::jsonb) RETURNING id""",
            room_id, user_id, student_no,
        )


async def _make_bill(pool, room_id: int, student_id: int, *, amount: float = 1000.0) -> int:
    async with pool.acquire() as conn:
        collection_id = await conn.fetchval(
            """INSERT INTO fee_collections (room_id, title, amount, due_date, status)
               VALUES ($1, 'ค่าเทอม', $2, $3, 'active') RETURNING id""",
            room_id, amount, date(2026, 12, 31),
        )
        return await conn.fetchval(
            """INSERT INTO student_payments (collection_id, student_id, status, paid_amount)
               VALUES ($1, $2, 'pending', 0) RETURNING id""",
            collection_id, student_id,
        )


# ═══════════════════════════════════════════════════════════════════ HTTP helpers
def _api(target_id: int, path: str, target_type: str, **kwargs) -> str:
    """สร้าง URL — web ต้องส่ง `target_type=room` เสมอ (default ของ API คือ server)"""
    return path.format(target=target_id, **kwargs) + f"?target_type={target_type}"


def _bot_headers(discord_id: int, **extra) -> dict:
    return {"X-API-Key": settings.API_KEY, "X-Discord-Id": str(discord_id), **extra}


def _web_headers(user_id: int) -> dict:
    token = jwt.encode(
        {"user_id": user_id, "exp": 9999999999},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def _issue_one_receipt(client, headers, pool, room_id: int, *, amount: float = 1200.0) -> str:
    """รับเงิน 1 บิลแล้วออกใบเสร็จผ่าน **เส้นทางจริง** → คืนเลขที่ใบเสร็จ

    ⚠️ ห้าม INSERT แถวใบเสร็จตรง ๆ: เทสต์นี้ต้องพิสูจน์ว่าไฟล์ที่บอทได้มาจากเอกสาร
       ที่ระบบออกเองจริง (มี `line_items`, `event_at`, `issued_to_name` ครบ) ไม่ใช่แถว
       ที่เราประกอบขึ้นเพื่อให้เทสต์ผ่าน
    """
    account_id = await _insert_account(pool, room_id)
    student_id = await _make_debtor(pool, room_id)
    payment_id = await _make_bill(pool, room_id, student_id, amount=amount)

    paid = client.put(
        _api(room_id, PAY_PATH, "room", payment_id=payment_id),
        json={"paid_to_account_id": account_id, "paid_amount": amount, "user_name": "Tester"},
        headers=headers,
    )
    assert paid.status_code == 200, paid.text

    issued = client.post(
        _api(room_id, RECEIPTS_PATH, "room"),
        json={"payment_id": payment_id, "doc_type": "receipt"},
        headers=headers,
    )
    assert issued.status_code == 200, issued.text
    return issued.json()["receipt"]["receipt_no"]


async def _snapshot(pool, room_id: int) -> tuple:
    """(จำนวนใบเสร็จในห้อง, เลขล่าสุดที่จองไปแล้วของทุก doc_type)"""
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM finance_receipts WHERE room_id = $1", room_id
        )
        seqs = await conn.fetch(
            """SELECT doc_type, year_be, last_seq FROM receipt_sequences
               WHERE room_id = $1 ORDER BY doc_type, year_be""",
            room_id,
        )
    return count, [(r["doc_type"], r["year_be"], r["last_seq"]) for r in seqs]


async def _last_audit(pool, room_id: int, *, status: str = "success"):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT user_id, actor_identifier, client_source, action, entity_type,
                      status, error_detail, new_values
               FROM audit_logs
               WHERE room_id = $1 AND action = 'PRINT_BATCH' AND status = $2
               ORDER BY id DESC LIMIT 1""",
            room_id, status,
        )


def _audit_json(raw):
    """`new_values`/`old_values` ถูกอ่านกลับเป็นสตริงได้ (asyncpg ไม่ถอด jsonb ให้เอง)"""
    if raw is None or isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


# ═════════════════════════════════════════════════ 1. ประตูของบอทระบบ
async def test_system_pdf_serves_pdf_to_unregistered_bot_principal(client, db_pool):
    """🔑 บอทระบบ (API key ถูกต้อง แต่ discord_id ไม่มีใน `users`) → 200 + ไฟล์ PDF

    ใช้ `target_type=server` เหมือนที่บอทเรียกจริง: บอทรู้จัก server_id (Discord guild)
    ไม่ใช่ room_id ภายใน — พิสูจน์ว่าได้ไฟล์จริงโดยไม่ต้องรู้ id ภายในของระบบ
    """
    owner = await _insert_user(db_pool)
    server_id = _seven_digit_id()
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    mock_render = AsyncMock(return_value=FAKE_PDF)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.post(
            _api(server_id, SYSTEM_PDF_PATH, "server"),
            json={"receipt_nos": [receipt_no]},
            headers=_bot_headers(_bot_user_id(), **{"X-Actor-Id": BOT_ACTOR}),
        )

    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content == FAKE_PDF
    assert f"receipts-{receipt_no}.pdf" in res.headers["content-disposition"]

    # เอกสารของ **คนนั้น** ต้องอยู่ในไฟล์จริง — ไม่ใช่ไฟล์ที่ผ่านด่านได้เพราะว่างเปล่า
    assert mock_render.await_count == 1
    html = mock_render.await_args.args[0]
    assert receipt_no in html          # เลขที่ที่ขอมา
    assert "เด็กชายทดสอบ" in html      # ชื่อผู้ชำระ (จาก `issued_to_name` ของใบจริง)


async def test_system_pdf_rejects_web_jwt_of_non_member(client, db_pool):
    """🔑 JWT จริงของคนที่ **ไม่ได้เป็นสมาชิกห้องนี้** → 403

    ถ้าเทสต์นี้ล้ม (ได้ไฟล์) = เราเปิดช่องอ่านเอกสารข้ามห้องให้ทั้งเว็บ
    ตัว ternary `is_bot_system` คือสิ่งเดียวที่กันเรื่องนี้ไว้
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    outsider = await _insert_user(db_pool)  # บัญชีจริง แต่ไม่ใช่สมาชิกห้องนี้
    res = client.post(
        _api(room_id, SYSTEM_PDF_PATH, "room"),
        json={"receipt_nos": [receipt_no]},
        headers=_web_headers(outsider),
    )
    assert res.status_code == 403, res.text


async def test_member_with_api_key_identity_is_still_membership_checked(client, db_pool):
    """บอทที่ `discord_id` **ผูกเป็น user จริง** แต่ไม่ใช่สมาชิกห้อง → 403 (ไม่ใช่ 200)

    🔑 พิสูจน์ว่า `is_bot_system` ขึ้นกับ "มีแถวใน `users` ไหม" ไม่ใช่ "ส่ง API key มาไหม"
       ⇒ การมี API key ไม่ได้ให้สิทธิ์อ่านทุกห้องโดยตัวมันเอง
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    registered = _seven_digit_id()
    await _insert_user(db_pool, discord_id=registered)
    res = client.post(
        _api(room_id, SYSTEM_PDF_PATH, "room"),
        json={"receipt_nos": [receipt_no]},
        headers=_bot_headers(registered),
    )
    assert res.status_code == 403, res.text


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"X-Discord-Id": "123"}, id="ไม่มี API key"),
        pytest.param({"X-API-Key": "not-the-key", "X-Discord-Id": "123"}, id="API key ผิด"),
    ],
)
async def test_system_pdf_requires_a_valid_api_key(client, db_pool, headers):
    """ไม่มีคีย์/คีย์ผิด → 401 ที่ด่าน dependency (ไม่ใช่ 400/403 จาก service)"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    res = client.post(
        _api(room_id, SYSTEM_PDF_PATH, "room"),
        json={"receipt_nos": ["REC-2569-0001"]},
        headers=headers,
    )
    assert res.status_code == 401, res.text


# ═══════════════════════════════════ 2. คู่แฝดต้องไม่ยืดหยุ่นตามกัน
async def test_old_web_pdf_route_still_refuses_bot_system_principal(client, db_pool):
    """🔑 route เดิมต้องยัง **ปฏิเสธ** บอทระบบ — พิสูจน์ว่าด่านเดิมยังอยู่ครบ

    ⚠️ คำตอบคือ **404** ไม่ใช่ 401/403: `get_current_user` (คนละตัวกับ
       `get_current_user_or_bot`) ไม่มีแนวคิด "บอทระบบ" เลย ⇒ บอทที่ไม่มี `users` row
       ตกที่ `raise HTTPException(404, "ไม่พบบัญชีผู้ใช้ที่ผูกกับ Discord ID นี้")`
       ซึ่งเป็น **พฤติกรรมที่ต้องการ**: หน้าจอเดิมไม่รู้จักและไม่ยอมรับ principal ชนิดนี้

    ถ้าเทสต์นี้ได้ 200 ⇒ มีคนเปลี่ยน dependency ของ route เดิมเป็น `get_current_user_or_bot`
    ⇒ ด่านสมาชิกของหน้าจอเดิมถูกเปิดด้วย API key ของบอท = RBAC พังทั้งหน้า
    """
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    res = client.post(
        _api(room_id, WEB_PDF_PATH, "room"),
        json={"receipt_nos": [receipt_no]},
        headers=_bot_headers(_bot_user_id()),
    )
    assert res.status_code == 404, res.text


async def test_old_web_pdf_route_still_forbids_non_member_discord_user(client, db_pool):
    """คู่แฝดอีกครึ่ง: บอทที่เป็น user จริงแต่ไม่ใช่สมาชิก → route เดิมให้ **403** ไม่ใช่ 200"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    registered = _seven_digit_id()
    await _insert_user(db_pool, discord_id=registered)
    res = client.post(
        _api(room_id, WEB_PDF_PATH, "room"),
        json={"receipt_nos": [receipt_no]},
        headers=_bot_headers(registered),
    )
    assert res.status_code == 403, res.text


# ═════════════════════════════════════════════════════════════════ 3. อ่านเท่านั้น
async def test_system_pdf_is_read_only(client, db_pool):
    """🔑 หลังเรียกสำเร็จ เอกสารและตัวนับเลขต้องไม่ขยับแม้แต่แถวเดียว

    ⚠️ `receipt_sequences.last_seq` คือตัวที่อันตรายที่สุด: ถ้าเส้นทางนี้เผลอ "ออกเอกสาร"
       ขึ้นมา เลขที่ออกไปแล้วจะถูกกิน ⇒ เลขบนใบเสร็จของครูไม่ต่อเนื่องโดยไม่มีใครรู้สาเหตุ
    """
    owner = await _insert_user(db_pool)
    server_id = _seven_digit_id()
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    before = await _snapshot(db_pool, room_id)
    assert before[0] == 1 and before[1], "sanity: ต้องมีใบเสร็จ 1 ใบและมีแถว sequence"

    with patch("services.finance.pdf.html_to_pdf", new=AsyncMock(return_value=FAKE_PDF)):
        res = client.post(
            _api(server_id, SYSTEM_PDF_PATH, "server"),
            json={"receipt_nos": [receipt_no]},
            headers=_bot_headers(_bot_user_id()),
        )
    assert res.status_code == 200, res.text
    assert await _snapshot(db_pool, room_id) == before


async def test_system_pdf_router_contains_no_database_access():
    """🔒 ซอร์สของ router ต้องไม่มี SQL และไม่แตะ DB เลย — ไม่ใช่แค่ "เส้นทางที่เทสต์วิ่ง"

    ⚠️ ใช้ `ast` ไม่ใช่ grep: docstring ของไฟล์นั้น **พูดถึง** `INSERT`/`UPDATE` เพื่อ
       อธิบายว่าห้ามมี ⇒ grep ดิบจะฟ้องโค้ดที่ถูกต้อง และถ้าเราไปกรองบรรทัดคอมเมนต์ทิ้ง
       ก็ยังเหลือ docstring ที่หลุดมาได้ ⇒ ต้องดู "สตริงที่รันจริง" อย่างเดียว

    ⚠️ เป็น `async def` โดยไม่มี `await` โดยเจตนา: ทั้งไฟล์ถูก mark ด้วย
       `pytestmark = pytest.mark.asyncio` (แบบเดียวกับเทสต์ไฟล์อื่นทุกไฟล์ใน repo)
       และ pytest-asyncio จะเตือนถ้าเทสต์ที่ถูก mark ไม่ใช่ coroutine
    """
    tree = ast.parse(
        (Path(__file__).resolve().parent.parent / "routers" / "finance" / "system.py")
        .read_text(encoding="utf-8")
    )
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_docstring(node, clean=False)
            if text:
                docstrings.add(text)

    literals = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docstrings
    ]
    for blob in literals:
        upper = blob.upper()
        for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "SELECT "):
            assert forbidden not in upper, f"router ของบอทต้องอ่านเท่านั้น — เจอ {forbidden!r}"

    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    db_calls = {"execute", "executemany", "fetch", "fetchrow", "fetchval", "copy_records_to_table"}
    assert not (called & db_calls), f"router ต้องไม่แตะ DB เอง — เจอ {called & db_calls}"


async def test_system_pdf_audit_records_the_bot_actor(client, db_pool):
    """audit log ต้องบันทึก `user_id = NULL` (บอทระบบไม่มี) แต่ `actor_identifier` ต้องบอกตัวตนได้"""
    owner = await _insert_user(db_pool)
    server_id = _seven_digit_id()
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    with patch("services.finance.pdf.html_to_pdf", new=AsyncMock(return_value=FAKE_PDF)):
        res = client.post(
            _api(server_id, SYSTEM_PDF_PATH, "server"),
            json={"receipt_nos": [receipt_no]},
            headers=_bot_headers(_bot_user_id(), **{"X-Actor-Id": BOT_ACTOR}),
        )
    assert res.status_code == 200, res.text

    row = await _last_audit(db_pool, room_id)
    assert row is not None, "ต้องมีแถว PRINT_BATCH ที่สำเร็จ"
    assert row["user_id"] is None, "บอทระบบไม่มี user_id ⇒ ต้องเป็น NULL ไม่ใช่ 0"
    assert row["actor_identifier"] == BOT_ACTOR
    # 🚫 กับดักเดิม: ส่ง `user_ctx` ที่มีคีย์ `user_id` (ค่า None) เข้า `get_audit_context`
    #    จะได้สตริง "user_id:None" ซึ่งอ่านเหมือน "ผู้ใช้ที่ id เป็น None"
    assert "None" not in (row["actor_identifier"] or "")
    assert row["entity_type"] == "FINANCE_RECEIPT"
    assert _audit_json(row["new_values"])["receipt_nos"] == [receipt_no]


# ══════════════════════════════════════════════════════ 4. ขอบเขตของเอกสาร
async def test_system_pdf_404_when_receipt_belongs_to_another_room(client, db_pool):
    """เลขของห้องอื่น → 404 — การข้ามด่านสมาชิก **ไม่ได้** ข้ามด่าน "เอกสารต้องอยู่ในห้องนี้"

    🔑 นี่คือด่านที่สำคัญที่สุดของทั้งฟีเจอร์: บอทถือ API key เดียวที่ใช้ได้กับทุก server
       ⇒ ถ้าด่านนี้หาย บอทตัวเดียวที่ถูกยึดจะอ่านใบเสร็จของทุกห้องในระบบ
    """
    owner = await _insert_user(db_pool)
    server_a, server_b = _seven_digit_id(), _seven_digit_id()
    while server_b == server_a:
        server_b = _seven_digit_id()
    await _insert_room(db_pool, owner, server_id=server_a)
    room_b = await _insert_room(db_pool, owner, server_id=server_b)
    receipt_of_b = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_b)

    mock_render = AsyncMock(return_value=FAKE_PDF)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.post(
            _api(server_a, SYSTEM_PDF_PATH, "server"),
            json={"receipt_nos": [receipt_of_b]},
            headers=_bot_headers(_bot_user_id()),
        )
    assert res.status_code == 404, res.text
    assert receipt_of_b in res.json()["detail"]
    mock_render.assert_not_awaited()  # ห้ามเสียแรงเรนเดอร์ก่อนตรวจว่ามีเอกสารจริง


async def test_system_pdf_404_for_unknown_receipt_number(client, db_pool):
    owner = await _insert_user(db_pool)
    server_id = _seven_digit_id()
    await _insert_room(db_pool, owner, server_id=server_id)
    res = client.post(
        _api(server_id, SYSTEM_PDF_PATH, "server"),
        json={"receipt_nos": ["REC-2569-9999"]},
        headers=_bot_headers(_bot_user_id()),
    )
    assert res.status_code == 404, res.text


@pytest.mark.parametrize("payload", [{}, {"receipt_nos": []}])
async def test_system_pdf_rejects_empty_selection(client, db_pool, payload):
    """ไม่ได้ส่งเลขมาเลย → 422 จาก Pydantic (`min_length=1`) ไม่ใช่ 500"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    res = client.post(
        _api(room_id, SYSTEM_PDF_PATH, "room"),
        json=payload,
        headers=_bot_headers(_bot_user_id()),
    )
    assert res.status_code == 422, res.text


async def test_system_pdf_rejects_more_than_the_batch_ceiling(client, db_pool):
    """เกินเพดาน 100 ฉบับ → 400 พร้อมข้อความที่บอกทางออก (ไม่ใช่ 502 จาก timeout ของ Chromium)"""
    owner = await _insert_user(db_pool)
    room_id = await _insert_room(db_pool, owner)
    too_many = [f"REC-2569-{i:04d}" for i in range(RECEIPTS_PER_PDF_MAX + 1)]
    res = client.post(
        _api(room_id, SYSTEM_PDF_PATH, "room"),
        json={"receipt_nos": too_many},
        headers=_bot_headers(_bot_user_id()),
    )
    assert res.status_code == 400, res.text
    assert str(RECEIPTS_PER_PDF_MAX) in res.json()["detail"]


async def test_system_pdf_dedupes_repeated_receipt_numbers(client, db_pool):
    """เลขซ้ำต้องกลายเป็น **หนึ่งหน้า** — ไม่งั้นคนนับหน้ากับจำนวนคนไม่ตรงกัน

    ⚠️ นับ "หน้า" จากตัวคั่นหน้า ไม่ใช่นับเลขที่เอกสาร: เลขที่ปรากฏได้มากกว่าหนึ่งครั้ง
       ต่อหน้าอย่างถูกต้อง (หัวกระดาษ + ท้ายกระดาษ) ⇒ การนับสตริงจะตีความไม่ได้
    """
    owner = await _insert_user(db_pool)
    server_id = _seven_digit_id()
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    mock_render = AsyncMock(return_value=FAKE_PDF)
    with patch("services.finance.pdf.html_to_pdf", new=mock_render):
        res = client.post(
            _api(server_id, SYSTEM_PDF_PATH, "server"),
            json={"receipt_nos": [receipt_no, receipt_no, receipt_no]},
            headers=_bot_headers(_bot_user_id()),
        )
    assert res.status_code == 200, res.text
    assert _page_count(mock_render.await_args.args[0]) == 1
    # และ audit ต้องบันทึกชุดที่ dedupe แล้ว (ไม่ใช่ 3 ใบ)
    row = await _last_audit(db_pool, room_id)
    assert _audit_json(row["new_values"]) == {"receipt_nos": [receipt_no], "count": 1}


async def test_system_pdf_maps_gotenberg_failure_to_502(client, db_pool):
    """Gotenberg ล่ม → 502 (ไม่ใช่ 500) ⇒ บอทแยกออกได้ว่า "แนบไม่ได้ชั่วคราว" แล้วส่งข้อความต่อ"""
    owner = await _insert_user(db_pool)
    server_id = _seven_digit_id()
    room_id = await _insert_room(db_pool, owner, server_id=server_id)
    receipt_no = await _issue_one_receipt(client, _web_headers(owner), db_pool, room_id)

    from services.finance.pdf import PdfRenderError

    async def boom(*_args, **_kwargs):
        raise PdfRenderError("Gotenberg ไม่ตอบ")

    with patch("services.finance.pdf.html_to_pdf", new=boom):
        res = client.post(
            _api(server_id, SYSTEM_PDF_PATH, "server"),
            json={"receipt_nos": [receipt_no]},
            headers=_bot_headers(_bot_user_id()),
        )
    assert res.status_code == 502, res.text
    assert "Gotenberg" in res.json()["detail"]

    # ล้มเหลวก็ยังต้องมีร่องรอย (status='failed') — ไม่ใช่หายเงียบ
    failed = await _last_audit(db_pool, room_id, status="failed")
    assert failed is not None and failed["error_detail"]


# ═══════════════════════════ 5. บอทต้องมีทางเดียวที่ข้ามด่านสมาชิก (เชิงโครงสร้าง)
async def test_the_membership_bypass_lives_in_exactly_one_place():
    """🔒 ทั้งโปรเจกต์ต้องมี **ที่เดียว** ที่ปิดด่านสมาชิกของเส้นทาง PDF

    ⚠️ กันการ copy เมธอดนี้ไปใช้กับ route อื่น (เช่น route ที่เขียน) โดยไม่ต้องรอให้มี
       ใครเขียนเทสต์พฤติกรรมของ route นั้น — ซึ่งเป็นวิธีที่ช่องโหว่เกิดขึ้นจริง
    ⚠️ `async def` เปล่า ๆ ด้วยเหตุผลเดียวกับเทสต์เชิงโครงสร้างข้างบน
    """
    backend = Path(__file__).resolve().parent.parent
    flag_files, caller_files = set(), set()
    for path in backend.rglob("*.py"):
        if "tests" in path.parts:
            continue
        rel = path.relative_to(backend).as_posix()
        # ตัดบรรทัดคอมเมนต์ทิ้ง: คอมเมนต์ที่ "พูดถึง" ธงนี้ไม่ใช่การใช้ธงนี้
        code = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("#")
        )
        if "enforce_membership=False" in code:
            flag_files.add(rel)
        if "render_documents_pdf_for_system" in code:
            caller_files.add(rel)

    assert flag_files == {"services/finance/receipts.py"}, (
        f"ธงปิดด่านสมาชิกต้องมีที่เดียว — เจอ {sorted(flag_files)}"
    )
    assert caller_files == {"services/finance/receipts.py", "routers/finance/system.py"}, (
        f"ผู้เรียกที่ข้ามด่านต้องมีแค่ router ของระบบ — เจอ {sorted(caller_files)}"
    )
