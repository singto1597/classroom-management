"""
Integration tests สำหรับ F1 — งบการเงิน (Financial Statements)

ครอบคลุม:
  [BS]   สมการ สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสม **เมื่อมี liability ledger จริง**
         (เทสต์ชุดนี้คือบทพิสูจน์ว่า `_compose_balance_sheet` ที่เคยฮาร์ดโค้ดหนี้สินเป็น 0.0
          ถูกแก้แล้ว — ก่อนแก้ `liability_total` จะเป็น 0.0 และ `is_balanced` เป็น False)
  [TB]   งบทดลอง: Dr = Cr, ยอดตรงกับ SUM() จาก DB ตรง ๆ, ตัด voided ออก
  [IS]   งบกำไรขาดทุน: 422 เมื่อขาดพารามิเตอร์, 400 เมื่อ start > end, clamp ที่ cutoff
  [CUTOFF] ขอบ 2026-08-31 / 09-01 / 09-02 บนทั้ง trial-balance และ balance-sheet
  [RBAC] สมาชิกธรรมดาอ่านได้ (require_member) / คนนอกห้อง 403 / **is_admin ไม่ bypass**
  [EXPORT] แผ่น BS ในไฟล์ Excel แสดงหนี้สินเป็นรายบรรทัด (ไม่ใช่ "(ระบบยังไม่มีหนี้สิน)")

หลักการ seeding ที่ห้ามลืม (จาก recon):
  - `create_room` ไม่ seed `accounting_ledgers` เลย → ห้องที่ INSERT ตรง ๆ มี ledger 0 แถว
  - ledger ถูกสร้างแบบ lazy จาก dual-write เท่านั้น → เทสต์ต้อง INSERT เอง
  - `accounting_ledgers` เป็นตารางเดียวที่ **ไม่มี `deleted_at`** มีแต่ `is_active`
    และรายงานทุกตัวกรอง `is_active = TRUE` → ตั้ง FALSE แล้วหายจากรายงานทุกใบ
  - `journal_lines` มี `chk_mutually_exclusive`: 1 บรรทัดต้องเป็น Dr ล้วน หรือ Cr ล้วน (อีกฝั่งใส่ 0)
  - `journal_entries.transaction_date` / `status` เป็น DB default ถ้าไม่ส่ง → เทสต์ต้องส่งเอง
    ทุกครั้ง (ไม่พึ่ง CURRENT_TIMESTAMP ซึ่งจะเป็น "วันนี้" และทำให้เทสต์เน่าตามเวลา)

หมายเหตุเรื่อง timezone: ค่าที่ส่งเป็นพารามิเตอร์ใน query ของ service เป็น naive datetime
(asyncpg ตีความเป็น UTC) ส่วน seed ใช้สตริง ISO ที่มี `+00` ต่อท้าย → ทั้งสองฝั่งอ้าง UTC
เหมือนกัน จึงไม่ขึ้นกับ timezone ของ container Postgres
"""
import io
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

import openpyxl
import pytest

from services.finance.constants import _CLAMP_EMPTY_NOTE, _CLAMP_START_NOTE
from services.finance.helpers import (
    _thai_day_start, _thai_day_end, _thai_next_day_start,
)
from services.finance_service import FinanceService

pytestmark = pytest.mark.asyncio


# =====================================================================
# ค่าคงที่ของชุดเทสต์
# =====================================================================

# ใช้ 12:00 UTC = 19:00 น. เวลาไทย → ห่างจากขอบวันทั้งสองฝั่งเกิน 7 ชม.
# จึงไม่มีการเลื่อนวัน ไม่ว่าจะตีความ naive datetime เป็น UTC หรือ Asia/Bangkok
#
# ⚠️ ต้องเป็น `datetime` ไม่ใช่ `str` — asyncpg เข้ารหัสพารามิเตอร์ timestamptz จาก
#    datetime object เท่านั้น (ส่งสตริงจะได้ DataError: expected a datetime instance)
#    ส่วน naive datetime asyncpg ตีความเป็น UTC ตรงกับที่ service ส่งเป็นขอบเขตเช่นกัน
SEED_TS = datetime(2026, 9, 1, 12, 0, 0)
POST_CUTOFF_DAY = date(2026, 9, 1)

TRIAL_BALANCE_PATH = "/api/classroom/{room}/finance/trial-balance"
INCOME_STATEMENT_PATH = "/api/classroom/{room}/finance/income-statement"
BALANCE_SHEET_PATH = "/api/classroom/{room}/finance/balance-sheet"


# =====================================================================
# Seeding helpers — สร้าง ledger/journal ตรง ๆ (ไม่ผ่าน service)
# =====================================================================


async def _insert_user(pool, *, first_name="Test", last_name="User") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (first_name, last_name, username)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            first_name, last_name, f"u{uuid.uuid4().hex[:12]}",
        )


async def _insert_room(pool, owner_id: int, room_name="ห้องงบการเงิน") -> int:
    """ห้องเปล่า — **ไม่มี** ledger/category/account (ของจริงเป็นแบบนี้เมื่อ INSERT ตรง)."""
    async with pool.acquire() as conn:
        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE room_code = $1", code):
                break
        room_id = await conn.fetchval(
            """
            INSERT INTO rooms (room_name, room_code, owner_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            room_name, code, owner_id,
        )
        await conn.execute(
            """
            INSERT INTO students (room_id, user_id, student_no, class_role, status, is_admin, permissions)
            VALUES ($1, $2, 0, 'president', 'active', TRUE, '[]'::jsonb)
            """,
            room_id, owner_id,
        )
        return room_id


async def _insert_ledger(
    pool, room_id: int, *, account_name: str, account_type: str,
    account_code=None, is_active: bool = True,
) -> int:
    """สร้าง accounting_ledgers ตรง ๆ.

    ⚠️ `is_active` ต้องเป็น TRUE ไม่งั้นรายงานทุกตัว (trial balance / GL / BS) จะไม่เห็น
    เพราะ WHERE ทุกตัวมี `AL.is_active = TRUE`
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, is_active)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            room_id, account_code, account_name, account_type, is_active,
        )


async def _post_entry(
    pool, room_id: int, *, description: str, lines, transaction_date: datetime = SEED_TS,
    reference_type: str = "manual_transaction", status: str = "posted",
) -> str:
    """สร้าง journal_entries 1 ใบ + journal_lines N บรรทัด (สมดุลจริง).

    lines = [(ledger_id, debit, credit), ...] — ฝั่งที่ไม่ใช้ต้องเป็น 0 ตาม chk_mutually_exclusive
    คืน journal_entry_id (UUID, str)
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            entry_id = await conn.fetchval(
                """
                INSERT INTO journal_entries
                    (room_id, reference_type, description, recorded_by, status, transaction_date)
                VALUES ($1, $2, $3, 'TEST', $4, $5::timestamptz)
                RETURNING id
                """,
                room_id, reference_type, description, status, transaction_date,
            )
            for ledger_id, debit, credit in lines:
                await conn.execute(
                    """
                    INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    entry_id, ledger_id, debit, credit, description,
                )
            return entry_id


async def _seed_full_chart(pool, room_id: int) -> dict:
    """สร้างผังบัญชีครบ 5 ประเภท + 4 ใบสมดุล ที่ทำให้สมการบัญชีเป็นจริงพอดี.

    รายการที่ลง (ทุกใบสมดุล Dr = Cr ในตัวเอง):
      1) ลงทุนตั้งต้น      Dr เงินสด 500      / Cr ทุน         500
      2) กู้ยืม            Dr เงินสด 300      / Cr เจ้าหนี้     300   ← liability ตัวเดียวในระบบเทสต์
      3) รับรายได้        Dr เงินสด 400      / Cr รายได้      400
      4) จ่ายค่าใช้จ่าย   Dr ค่าใช้จ่าย 200  / Cr เงินสด      200

    ยอดสะสม:
      เงินสด(asset)  = (500+300+400) − 200 = 1000   [Dr−Cr]
      เจ้าหนี้(liab)  = 300                          [Cr−Dr]
      ทุน(equity)    = 500                          [Cr−Dr]
      รายได้(rev)    = 400  → กำไรสะสม +400
      ค่าใช้จ่าย(exp)= 200  → กำไรสะสม −200
      กำไรสะสม       = 200
      ส่วนของเจ้าของรวม = 500 + 200 = 700
      ฝั่งขวารวม     = 300 + 700 = 1000  ==> เท่ากับสินทรัพย์ 1000
    """
    cash = await _insert_ledger(pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    debt = await _insert_ledger(pool, room_id, account_name="เจ้าหนี้การค้า", account_type="liability", account_code="2001")
    capital = await _insert_ledger(pool, room_id, account_name="ทุนห้องเรียน", account_type="equity", account_code="3001")
    revenue = await _insert_ledger(pool, room_id, account_name="รายรับเงินบริจาค", account_type="revenue", account_code="4001")
    expense = await _insert_ledger(pool, room_id, account_name="ค่าอุปกรณ์การเรียน", account_type="expense", account_code="5001")

    await _post_entry(pool, room_id, description="ลงทุนตั้งต้น",
                      lines=[(cash, 500.0, 0), (capital, 0, 500.0)])
    await _post_entry(pool, room_id, description="กู้ยืมเงินผู้ปกครอง",
                      lines=[(cash, 300.0, 0), (debt, 0, 300.0)])
    await _post_entry(pool, room_id, description="รับเงินบริจาค",
                      lines=[(cash, 400.0, 0), (revenue, 0, 400.0)])
    await _post_entry(pool, room_id, description="ซื้ออุปกรณ์",
                      lines=[(expense, 200.0, 0), (cash, 0, 200.0)])

    return {
        "cash": cash, "debt": debt, "capital": capital,
        "revenue": revenue, "expense": expense,
    }


def _by_ledger_id(rows: list, ledger_id: int) -> dict:
    for r in rows:
        if r["ledger_id"] == ledger_id:
            return r
    raise AssertionError(f"ไม่พบ ledger_id={ledger_id} ใน {rows}")


# =====================================================================
# [BS] งบแสดงฐานะการเงิน — สมการครบทั้ง 4 ขา
# =====================================================================


async def test_balance_sheet_equation_holds_with_liability_ledger(client, db_pool, admin_headers):
    """🎯 เทสต์หัวใจของ F1 — **ต้อง fail กับโค้ดก่อนแก้**

    ก่อนแก้: `_compose_balance_sheet` ฮาร์ดโค้ด `liability_total = 0.0` และคิด
    `is_balanced = abs(assets_total - total_equity_side)` → ได้ abs(1000 − 700) = 300 → False
    หลังแก้: อ่าน liability จาก tb จริง + เทียบกับ `total_liabilities_and_equity` → True
    """
    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    bs = res.json()

    # --- ฝั่งสินทรัพย์ ---
    assert bs["assets_total"] == pytest.approx(1000.0)
    assert len(bs["assets"]) == 1

    # --- หนี้สิน (สิ่งที่เพิ่งแก้) ---
    assert bs["liability_total"] == pytest.approx(300.0)
    assert len(bs["liabilities"]) == 1
    assert bs["liabilities"][0]["account_name"] == "เจ้าหนี้การค้า"
    assert bs["liabilities"][0]["account_code"] == "2001"
    assert bs["liabilities"][0]["balance"] == pytest.approx(300.0)

    # --- ส่วนของเจ้าของ ---
    assert bs["equity_total"] == pytest.approx(500.0)
    assert bs["retained_earnings"] == pytest.approx(200.0)
    assert bs["total_equity_side"] == pytest.approx(700.0)

    # --- สมการ ---
    assert bs["total_liabilities_and_equity"] == pytest.approx(1000.0)
    assert bs["assets_total"] == pytest.approx(bs["total_liabilities_and_equity"])
    assert bs["is_balanced"] is True

    # --- memo ที่ต้องมาคู่กับ period เสมอ ---
    assert bs["period_net_income"] == pytest.approx(200.0)   # 400 รายได้ − 200 ค่าใช้จ่าย
    assert bs["period_start"] == POST_CUTOFF_DAY.isoformat()
    assert bs["period_end"] == POST_CUTOFF_DAY.isoformat()
    assert bs["note"] is None


async def test_balance_sheet_totals_match_raw_journal_lines(client, db_pool, admin_headers):
    """Deep DB verification — ไม่เชื่อ HTTP อย่างเดียว: คำนวณ Dr/Cr ต่อ ledger จาก DB ตรง ๆ."""
    room_id = admin_headers.room_id
    ledgers = await _seed_full_chart(db_pool, room_id)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT AL.id AS ledger_id, AL.account_type,
                   COALESCE(SUM(L.debit), 0)  AS dr,
                   COALESCE(SUM(L.credit), 0) AS cr
            FROM accounting_ledgers AL
            LEFT JOIN journal_lines L  ON L.ledger_id = AL.id
            LEFT JOIN journal_entries JE ON L.journal_entry_id = JE.id
            WHERE AL.room_id = $1 AND AL.is_active = TRUE
              AND (JE.id IS NULL OR (JE.deleted_at IS NULL AND JE.status <> 'voided'))
            GROUP BY AL.id, AL.account_type
            """,
            room_id,
        )
    db = {r["ledger_id"]: (float(r["dr"]), float(r["cr"]), r["account_type"]) for r in rows}

    # ยืนยันยอดดิบก่อน — กันเทสต์ผ่านเพราะ seed ผิด
    assert db[ledgers["cash"]][:2] == (1200.0, 200.0)     # Dr 500+300+400 / Cr 200
    assert db[ledgers["debt"]][:2] == (0.0, 300.0)
    assert db[ledgers["capital"]][:2] == (0.0, 500.0)
    assert db[ledgers["revenue"]][:2] == (0.0, 400.0)
    assert db[ledgers["expense"]][:2] == (200.0, 0.0)

    # journal ทั้งห้องต้องสมดุล (Dr รวม == Cr รวม)
    assert sum(v[0] for v in db.values()) == pytest.approx(sum(v[1] for v in db.values()))

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    bs = res.json()

    # คำนวณคาดหวังจาก DB เอง (ไม่ใช้เลขลอก)
    expect_assets = sum(dr - cr for dr, cr, t in db.values() if t == "asset")
    expect_liab = sum(cr - dr for dr, cr, t in db.values() if t == "liability")
    expect_equity = sum(cr - dr for dr, cr, t in db.values() if t == "equity")
    expect_retained = (
        sum(cr - dr for dr, cr, t in db.values() if t == "revenue")
        - sum(dr - cr for dr, cr, t in db.values() if t == "expense")
    )

    assert bs["assets_total"] == pytest.approx(expect_assets)
    assert bs["liability_total"] == pytest.approx(expect_liab)
    assert bs["equity_total"] == pytest.approx(expect_equity)
    assert bs["retained_earnings"] == pytest.approx(expect_retained)
    assert bs["total_liabilities_and_equity"] == pytest.approx(
        expect_liab + expect_equity + expect_retained
    )


async def test_balance_sheet_liability_only_room_is_balanced(client, db_pool, admin_headers):
    """ห้องที่มีแต่หนี้สิน (ยังไม่ใช้เงินกู้เลย) — สมการต้องยังจริง ไม่ใช่ False เพราะฮาร์ดโค้ด 0.

    Dr เงินสด 250 / Cr เจ้าหนี้ 250 → assets 250, liab 250, equity 0, retained 0
    """
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    debt = await _insert_ledger(db_pool, room_id, account_name="เงินยืมครู", account_type="liability", account_code="2001")
    await _post_entry(db_pool, room_id, description="ยืมเงินครู",
                      lines=[(cash, 250.0, 0), (debt, 0, 250.0)])

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    bs = res.json()

    assert bs["assets_total"] == pytest.approx(250.0)
    assert bs["liability_total"] == pytest.approx(250.0)
    assert bs["equity_total"] == pytest.approx(0.0)
    assert bs["retained_earnings"] == pytest.approx(0.0)
    assert bs["total_liabilities_and_equity"] == pytest.approx(250.0)
    assert bs["is_balanced"] is True


async def test_balance_sheet_excludes_inactive_ledger(client, db_pool, admin_headers):
    """ledger ที่ `is_active = FALSE` ต้องหายจากรายงาน (WHERE AL.is_active = TRUE)."""
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    dead = await _insert_ledger(
        db_pool, room_id, account_name="บัญชีปิดใช้งาน", account_type="asset",
        account_code="1099", is_active=False,
    )
    await _post_entry(db_pool, room_id, description="ลงทุน",
                      lines=[(cash, 100.0, 0), (dead, 0, 100.0)])  # ทำให้ Dr=Cr สมดุล

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    bs = res.json()

    ledger_ids = [a["ledger_id"] for a in bs["assets"]]
    assert dead not in ledger_ids
    assert cash in ledger_ids
    # ยอดที่ลงในบัญชีที่ปิดไปแล้วไม่ถูกนับ → สินทรัพย์เหลือ 100 (Dr ของเงินสด)
    assert bs["assets_total"] == pytest.approx(100.0)


async def test_balance_sheet_balances_after_voiding_entry(client, db_pool, admin_headers):
    """ใบที่ void ต้องถูกตัดออกทั้งสองขา → สมการยังจริง (ไม่เหลือขาเดียวลอย)."""
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    debt = await _insert_ledger(db_pool, room_id, account_name="เจ้าหนี้", account_type="liability", account_code="2001")
    capital = await _insert_ledger(db_pool, room_id, account_name="ทุน", account_type="equity", account_code="3001")

    await _post_entry(db_pool, room_id, description="ทุนตั้งต้น",
                      lines=[(cash, 500.0, 0), (capital, 0, 500.0)])
    await _post_entry(db_pool, room_id, description="กู้แล้วยกเลิก",
                      lines=[(cash, 900.0, 0), (debt, 0, 900.0)], status="voided")

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    bs = res.json()

    assert bs["assets_total"] == pytest.approx(500.0)
    assert bs["liability_total"] == pytest.approx(0.0)
    assert bs["is_balanced"] is True

    # ⚠️ ledger ยัง **โผล่** ในรายการด้วยยอด 0 — ถูกต้องแล้ว: งบทดลอง/งบดุลเป็น
    #    LEFT JOIN จาก accounting_ledgers (ไม่ใช่ INNER) บัญชีที่ยัง active แต่ยังไม่มีความเคลื่อนไหว
    #    จึงต้องปรากฏเป็น 0 ไม่ใช่หายไป (นักบัญชีต้องเห็นว่ามีบัญชีนี้อยู่)
    #    สิ่งที่ต้องเป็น 0 คือ "ยอด" ไม่ใช่ "การมีอยู่ของแถว"
    assert len(bs["liabilities"]) == 1
    assert bs["liabilities"][0]["account_name"] == "เจ้าหนี้"
    assert bs["liabilities"][0]["balance"] == pytest.approx(0.0)


# =====================================================================
# [CUTOFF] ขอบวันที่ตัด — ต้องเหมือนกันทั้ง trial-balance และ balance-sheet
# =====================================================================


@pytest.mark.parametrize(
    "as_of,expect_clamped",
    [
        (date(2026, 8, 31), True),   # ก่อนเส้น 1 วัน → ว่าง + note
        (date(2026, 9, 1), False),   # วันเดียวกับเส้น → นับ (ขอบเขต ≤ สิ้นวัน)
        (date(2026, 9, 2), False),   # หลังเส้น → นับ
    ],
)
async def test_trial_balance_cutoff_boundary(client, db_pool, admin_headers, as_of, expect_clamped):
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    capital = await _insert_ledger(db_pool, room_id, account_name="ทุน", account_type="equity", account_code="3001")
    await _post_entry(db_pool, room_id, description="ทุนตั้งต้น", transaction_date=SEED_TS,
                      lines=[(cash, 700.0, 0), (capital, 0, 700.0)])

    res = client.get(
        TRIAL_BALANCE_PATH.format(room=room_id),
        params={"as_of_date": as_of.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    if expect_clamped:
        assert body["ledgers"] == []
        assert body["total_debit"] == 0.0
        assert body["total_credit"] == 0.0
        # ว่างเพราะถูกตัด ไม่ใช่เพราะพัง → ต้องสมดุลและมี note บอกสาเหตุ
        assert body["is_balanced"] is True
        assert body["note"] == _CLAMP_EMPTY_NOTE
    else:
        assert body["total_debit"] == pytest.approx(700.0)
        assert body["total_credit"] == pytest.approx(700.0)
        assert body["is_balanced"] is True
        assert body["note"] is None
        assert _by_ledger_id(body["ledgers"], cash)["balance"] == pytest.approx(700.0)


@pytest.mark.parametrize(
    "as_of,expect_clamped",
    [
        (date(2026, 8, 31), True),
        (date(2026, 9, 1), False),
        (date(2026, 9, 2), False),
    ],
)
async def test_balance_sheet_cutoff_boundary(client, db_pool, admin_headers, as_of, expect_clamped):
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    capital = await _insert_ledger(db_pool, room_id, account_name="ทุน", account_type="equity", account_code="3001")
    await _post_entry(db_pool, room_id, description="ทุนตั้งต้น", transaction_date=SEED_TS,
                      lines=[(cash, 700.0, 0), (capital, 0, 700.0)])

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": as_of.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    if expect_clamped:
        assert body["assets"] == []
        assert body["liabilities"] == []
        assert body["equities"] == []
        assert body["assets_total"] == 0.0
        assert body["liability_total"] == 0.0
        assert body["total_liabilities_and_equity"] == 0.0
        assert body["is_balanced"] is True
        assert body["note"] == _CLAMP_EMPTY_NOTE
    else:
        assert body["assets_total"] == pytest.approx(700.0)
        assert body["equity_total"] == pytest.approx(700.0)
        assert body["total_liabilities_and_equity"] == pytest.approx(700.0)
        assert body["is_balanced"] is True
        assert body["note"] is None


async def test_balance_sheet_cutoff_reports_period_even_when_empty(client, db_pool, admin_headers):
    """เส้นทางที่ถูก clamp ต้องยังคืน period_start/period_end (ไม่งั้น period_net_income ลอย).

    ⚠️ ในเส้นทางนี้ "ไม่มีงวด" จริง ๆ จึงคืน `period_start == period_end == as_of`
    (ไม่ใช่ `max(CUTOFF_DATE, 1 ม.ค. ของปี as_of)` = 2026-09-01 ซึ่งจะ **มากกว่า**
    `period_end` = 2026-08-31 แล้วกลายเป็น payload ที่ UI แสดงเป็นช่วงวันที่ย้อนกลับ)
    ความจริงว่า "ทำไมว่าง" สื่อผ่าน `note` ไม่ใช่ผ่านคู่ period ที่ขัดแย้งกันเอง
    """
    room_id = admin_headers.room_id
    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": "2026-08-31"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["period_start"] == "2026-08-31"
    assert body["period_end"] == "2026-08-31"
    # ห้ามมี payload ที่ start > end เด็ดขาด — UI จะ render เป็นช่วงวันที่ย้อนกลับ
    assert body["period_start"] <= body["period_end"]
    assert body["period_net_income"] == 0.0


async def test_balance_sheet_period_start_never_before_cutoff(client, db_pool, admin_headers):
    """กำไรสะสมนับจาก max(CUTOFF_DATE, 1 ม.ค. ของปี as_of) → ปี 2026 ต้องเริ่ม 2026-09-01."""
    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)
    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": "2026-12-31"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["period_start"] == "2026-09-01"

    # ข้ามไปปีถัดไป → เริ่ม 1 ม.ค. ของปีนั้น (หลังเส้นตัดแล้ว)
    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": "2027-03-31"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["period_start"] == "2027-01-01"


# =====================================================================
# [TB] งบทดลอง
# =====================================================================


async def test_trial_balance_matches_raw_db_and_is_balanced(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    ledgers = await _seed_full_chart(db_pool, room_id)

    async with db_pool.acquire() as conn:
        raw = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(L.debit), 0) AS dr, COALESCE(SUM(L.credit), 0) AS cr
            FROM journal_lines L
            JOIN journal_entries JE ON L.journal_entry_id = JE.id
            WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
            """,
            room_id,
        )
    assert float(raw["dr"]) == pytest.approx(1400.0)   # 500 + 300 + 400 + 200
    assert float(raw["cr"]) == pytest.approx(1400.0)

    res = client.get(
        TRIAL_BALANCE_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    tb = res.json()

    assert tb["total_debit"] == pytest.approx(float(raw["dr"]))
    assert tb["total_credit"] == pytest.approx(float(raw["cr"]))
    assert tb["total_debit"] == tb["total_credit"]
    assert tb["is_balanced"] is True
    assert tb["note"] is None

    # ยอดต่อ ledger ก็ต้องตรง (เทียบกับที่ seed ไว้) — ใช้ id ที่ seed คืนมา ไม่ hardcode เลข
    cash = _by_ledger_id(tb["ledgers"], ledgers["cash"])
    assert cash["account_name"] == "เงินสด"
    assert cash["total_debit"] == pytest.approx(1200.0)
    assert cash["total_credit"] == pytest.approx(200.0)
    assert cash["balance"] == pytest.approx(1000.0)

    debt = _by_ledger_id(tb["ledgers"], ledgers["debt"])
    # liability ใช้ Cr − Dr → ยอดเป็นบวก (ห้ามกลับเครื่องหมาย)
    assert debt["total_credit"] == pytest.approx(300.0)
    assert debt["balance"] == pytest.approx(300.0)

    # ledger ที่มียอด 0 ก็ต้องยังโผล่ในงบทดลอง (LEFT JOIN ไม่ใช่ INNER)
    assert _by_ledger_id(tb["ledgers"], ledgers["expense"])["total_debit"] == pytest.approx(200.0)


async def test_trial_balance_excludes_voided_and_soft_deleted(client, db_pool, admin_headers):
    """ใบ voided และใบที่ soft-delete ต้องไม่ถูกนับ (ทั้งคู่มีเงื่อนไขใน WHERE ของ aggregate)."""
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    capital = await _insert_ledger(db_pool, room_id, account_name="ทุน", account_type="equity", account_code="3001")

    await _post_entry(db_pool, room_id, description="นับจริง", lines=[(cash, 300.0, 0), (capital, 0, 300.0)])
    await _post_entry(db_pool, room_id, description="voided", lines=[(cash, 500.0, 0), (capital, 0, 500.0)],
                      status="voided")
    deleted_id = await _post_entry(db_pool, room_id, description="soft-deleted",
                                   lines=[(cash, 700.0, 0), (capital, 0, 700.0)])
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE journal_entries SET deleted_at = NOW() WHERE id = $1", deleted_id
        )

    res = client.get(
        TRIAL_BALANCE_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    tb = res.json()

    assert tb["total_debit"] == pytest.approx(300.0)
    assert tb["total_credit"] == pytest.approx(300.0)
    assert _by_ledger_id(tb["ledgers"], cash)["balance"] == pytest.approx(300.0)


async def test_trial_balance_multi_ledger_scope_is_per_room(client, db_pool, admin_headers):
    """ledger ของห้องอื่นต้องไม่รั่วเข้ามาในงบของห้องนี้."""
    other_owner = await _insert_user(db_pool, first_name="Other", last_name="Owner")
    other_room = await _insert_room(db_pool, other_owner, room_name="ห้องอื่น")
    other_cash = await _insert_ledger(db_pool, other_room, account_name="เงินสดห้องอื่น",
                                      account_type="asset", account_code="1001")
    other_cap = await _insert_ledger(db_pool, other_room, account_name="ทุนห้องอื่น",
                                     account_type="equity", account_code="3001")
    await _post_entry(db_pool, other_room, description="ห้องอื่น",
                      lines=[(other_cash, 999.0, 0), (other_cap, 0, 999.0)])

    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)

    res = client.get(
        TRIAL_BALANCE_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    tb = res.json()
    assert tb["total_debit"] == pytest.approx(1400.0)
    assert all("ห้องอื่น" not in r["account_name"] for r in tb["ledgers"])


async def test_trial_balance_empty_room_returns_balanced_empty(client, db_pool, admin_headers):
    """ห้องที่ยังไม่มี ledger เลย → 200 + ว่าง + สมดุล (ไม่ใช่ 500 หรือ 404)."""
    room_id = admin_headers.room_id
    res = client.get(
        TRIAL_BALANCE_PATH.format(room=room_id),
        params={"as_of_date": POST_CUTOFF_DAY.isoformat()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ledgers"] == []
    assert body["is_balanced"] is True
    assert body["note"] is None


# =====================================================================
# [IS] งบกำไรขาดทุน
# =====================================================================


async def test_income_statement_requires_both_dates(client, db_pool, admin_headers):
    """ส่งแค่ start_date → 422 (end_date เป็น Query(...) บังคับ) — ไม่ใช่ 500."""
    room_id = admin_headers.room_id
    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"start_date": "2026-09-01"},
        headers=admin_headers,
    )
    assert res.status_code == 422

    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"end_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert res.status_code == 422


async def test_income_statement_start_after_end_returns_400(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"start_date": "2026-10-31", "end_date": "2026-10-01"},
        headers=admin_headers,
    )
    assert res.status_code == 400
    assert "วันที่เริ่มต้น" in res.json()["detail"]


async def test_income_statement_totals_hand_computed(client, db_pool, admin_headers):
    """ยอดต้องเท่าที่คำนวณมือ ไม่ใช่แค่ 'มีค่า'."""
    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)

    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    pl = res.json()

    assert pl["total_revenue"] == pytest.approx(400.0)
    assert pl["total_expense"] == pytest.approx(200.0)
    assert pl["net_income"] == pytest.approx(200.0)
    assert pl["revenues"] == [{"account_name": "รายรับเงินบริจาค", "amount": 400.0}]
    assert pl["expenses"] == [{"account_name": "ค่าอุปกรณ์การเรียน", "amount": 200.0}]
    # echo ค่าที่ผู้ใช้ส่ง ไม่ใช่ค่าที่ clamp
    assert pl["start_date"] == "2026-09-01"
    assert pl["end_date"] == "2026-09-30"
    assert pl["note"] is None


async def test_income_statement_crossing_cutoff_clamps_and_notes(client, db_pool, admin_headers):
    """ช่วงที่เริ่มก่อน 1 ก.ย. → ถูก clamp + `note` = _CLAMP_START_NOTE และยอดเท่ากับช่วงที่ clamp แล้ว."""
    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)

    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"start_date": "2026-01-01", "end_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    pl = res.json()

    assert pl["note"] == _CLAMP_START_NOTE
    # ⚠️ echo ค่าที่ผู้ใช้ส่ง (2026-01-01) แต่ตัวเลขครอบแค่ตั้งแต่ 09-01 — นี่คือกับดักที่ note มีไว้บอก
    assert pl["start_date"] == "2026-01-01"
    assert pl["total_revenue"] == pytest.approx(400.0)
    assert pl["total_expense"] == pytest.approx(200.0)
    assert pl["net_income"] == pytest.approx(200.0)


async def test_income_statement_fully_before_cutoff_is_empty_with_note(client, db_pool, admin_headers):
    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)

    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"start_date": "2026-01-01", "end_date": "2026-08-31"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    pl = res.json()
    assert pl["revenues"] == []
    assert pl["expenses"] == []
    assert pl["net_income"] == 0.0
    assert pl["note"] == _CLAMP_EMPTY_NOTE


async def test_income_statement_is_period_scoped(client, db_pool, admin_headers):
    """รายการนอกช่วงที่ขอต้องไม่ถูกนับ (ขอบ inclusive ทั้งสองด้าน)."""
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    revenue = await _insert_ledger(db_pool, room_id, account_name="รายรับ", account_type="revenue", account_code="4001")

    await _post_entry(db_pool, room_id, description="ก่อนช่วง",
                      transaction_date=datetime(2026, 8, 15, 12, 0, 0),
                      lines=[(cash, 111.0, 0), (revenue, 0, 111.0)])
    await _post_entry(db_pool, room_id, description="วันแรกของช่วง",
                      transaction_date=datetime(2026, 9, 10, 12, 0, 0),
                      lines=[(cash, 222.0, 0), (revenue, 0, 222.0)])
    await _post_entry(db_pool, room_id, description="วันสุดท้ายของช่วง",
                      transaction_date=datetime(2026, 9, 20, 12, 0, 0),
                      lines=[(cash, 333.0, 0), (revenue, 0, 333.0)])
    await _post_entry(db_pool, room_id, description="หลังช่วง",
                      transaction_date=datetime(2026, 10, 5, 12, 0, 0),
                      lines=[(cash, 444.0, 0), (revenue, 0, 444.0)])

    res = client.get(
        INCOME_STATEMENT_PATH.format(room=room_id),
        params={"start_date": "2026-09-10", "end_date": "2026-09-20"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    pl = res.json()
    assert pl["total_revenue"] == pytest.approx(555.0)   # 222 + 333 เท่านั้น
    assert pl["note"] is None


# =====================================================================
# [RBAC] สิทธิ์การอ่าน
# =====================================================================


@pytest.mark.parametrize(
    "path,extra",
    [
        (TRIAL_BALANCE_PATH, {"as_of_date": "2026-09-01"}),
        (INCOME_STATEMENT_PATH, {"start_date": "2026-09-01", "end_date": "2026-09-30"}),
        (BALANCE_SHEET_PATH, {"as_of_date": "2026-09-01"}),
    ],
)
async def test_statements_allow_plain_member(client, db_pool, member_headers, path, extra):
    """สมาชิกธรรมดา (ไม่ใช่ admin, ไม่มี MANAGE_FINANCE) อ่านได้ → พิสูจน์ว่าใช้ `require_member`.

    ถ้ามีใครเปลี่ยนไปใช้ `require_permission(..., "MANAGE_FINANCE")` เทสต์นี้จะได้ 403 ทันที
    (นักเรียนต้องดูงบของห้องตัวเองได้ — transparency)
    """
    room_id = member_headers.room_id
    res = client.get(path.format(room=room_id), params=extra, headers=member_headers)
    assert res.status_code == 200, res.text


@pytest.mark.parametrize(
    "path,extra",
    [
        (TRIAL_BALANCE_PATH, {"as_of_date": "2026-09-01"}),
        (INCOME_STATEMENT_PATH, {"start_date": "2026-09-01", "end_date": "2026-09-30"}),
        (BALANCE_SHEET_PATH, {"as_of_date": "2026-09-01"}),
    ],
)
async def test_statements_forbid_non_member(client, db_pool, member_headers, path, extra):
    """ยิงข้ามห้องที่ตัวเองไม่ได้เป็นสมาชิก → 403 ทั้งสามงบ."""
    stranger = await _insert_user(db_pool, first_name="Stranger", last_name="User")
    foreign_room = await _insert_room(db_pool, stranger, room_name="ห้องของคนอื่น")

    res = client.get(path.format(room=foreign_room), params=extra, headers=member_headers)
    assert res.status_code == 403, res.text


@pytest.mark.parametrize(
    "path,extra",
    [
        (TRIAL_BALANCE_PATH, {"as_of_date": "2026-09-01"}),
        (INCOME_STATEMENT_PATH, {"start_date": "2026-09-01", "end_date": "2026-09-30"}),
        (BALANCE_SHEET_PATH, {"as_of_date": "2026-09-01"}),
    ],
)
async def test_statements_is_admin_does_not_bypass_require_member(client, db_pool, admin_headers, path, extra):
    """🎯 ความไม่สมมาตรที่จดไว้ใน core/rbac.py: `require_member` **ไม่** bypass ด้วย `is_admin`
    (ต่างจาก `require_permission`) — admin ของห้อง A ต้องอ่านงบห้อง B ไม่ได้.
    """
    stranger = await _insert_user(db_pool, first_name="Other", last_name="Admin")
    foreign_room = await _insert_room(db_pool, stranger, room_name="ห้องที่ admin ไม่ได้เป็นสมาชิก")

    res = client.get(path.format(room=foreign_room), params=extra, headers=admin_headers)
    assert res.status_code == 403, res.text


async def test_statements_unknown_room_returns_404(client, db_pool, admin_headers):
    res = client.get(
        BALANCE_SHEET_PATH.format(room=987654321),
        params={"as_of_date": "2026-09-01"},
        headers=admin_headers,
    )
    assert res.status_code == 404


# =====================================================================
# [EXPORT] แผ่นงบดุลในไฟล์ Excel
# =====================================================================


def _values(wb, sheet: str) -> list:
    return list(wb[sheet].values)


def _find_row(rows: list, col: int, needle) -> tuple:
    """หาแถวแรกที่ rows[row][col] == needle (เทียบแบบเป๊ะ) — ค้นด้วย **ป้ายชื่อ** ไม่ใช่ index.

    จงใจไม่ผูกกับลำดับแถว เพราะลำดับในแผ่น BS เคยขยับมาแล้วครั้งหนึ่ง (commit 44b5499)
    """
    for r in rows:
        if r and r[col] == needle:
            return r
    raise AssertionError(f"ไม่พบแถวที่ col {col} == {needle!r} ใน {rows}")


def _find_row_containing(rows: list, col: int, fragment: str) -> tuple:
    """หาแถวแรกที่ช่อง `col` **มี** `fragment` อยู่ข้างใน — ทนต่อการเติมต่อท้ายป้าย.

    ใช้กับป้ายที่เคยถูกเติม suffix มาแล้ว เช่น "รวมทั้งสิ้น" → "รวมทั้งสิ้น (Grand Total)"
    (การเติม suffix แบบนี้คือสาเหตุที่เทสต์เดิมของ export พัง — ดู docs/skills.md)
    """
    for r in rows:
        if r and isinstance(r[col], str) and fragment in r[col]:
            return r
    raise AssertionError(f"ไม่พบแถวที่ col {col} มี {fragment!r} ใน {rows}")


async def test_export_balance_sheet_sheet_lists_liabilities(db_pool):
    """ก่อนแก้ แผ่น BS พิมพ์ "  (ระบบยังไม่มีหนี้สิน)" และ "รวมหนี้สิน" = 0.0 เสมอ.

    เทสต์นี้หาด้วย **ป้ายชื่อ** ไม่ใช่ index เพื่อไม่ให้พังตามการสลับแผ่น/สลับแถว
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องงบดุล Export")
    await _seed_full_chart(db_pool, room_id)

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=9, year=2026,
    )
    assert isinstance(excel_file, io.BytesIO)
    wb = openpyxl.load_workbook(excel_file)

    bs_rows = _values(wb, "งบแสดงฐานะการเงิน (BS)")[3:]

    # บรรทัดหนี้สินรายตัว ต้องมีชื่อบัญชี + รหัส อยู่จริง
    liab_line = _find_row(bs_rows, 1, "  เจ้าหนี้การค้า (2001)")
    assert liab_line[2] == pytest.approx(300.0)

    # ยอดรวมหนี้สินเคยเป็น 0.0 ฮาร์ดโค้ด — ตอนนี้ต้องเป็น 300
    liab_total = _find_row(bs_rows, 1, "รวมหนี้สิน")
    assert liab_total[2] == pytest.approx(300.0)

    # ฝั่งขวาของสมการต้องเท่ากับสินทรัพย์ และมีบรรทัดรวมของตัวเอง
    assets = _find_row(bs_rows, 1, "รวมสินทรัพย์")
    combined = _find_row(bs_rows, 1, "รวมหนี้สินและส่วนของเจ้าของ")
    assert assets[2] == pytest.approx(1000.0)
    assert combined[2] == pytest.approx(1000.0)

    balanced = _find_row(bs_rows, 1, "ตรวจสอบสมดุล (Assets = Liab + Equity + Retained)")
    assert "สมดุล" in str(balanced[2])
    assert "ไม่สมดุล" not in str(balanced[2])


async def test_export_balance_sheet_flags_unbalanced_when_equation_really_breaks(db_pool):
    """ธง "สมดุล" ต้องไม่ได้เขียวตลอด — พอสมการพังจริงต้องขึ้น "ไม่สมดุล".

    สร้างสภาพที่สมการพังจริงด้วย **บรรทัดเดี่ยวที่ไม่มีคู่** (CHK ของ journal_lines
    บังคับแค่ "ต่อบรรทัด" ว่า Dr ล้วนหรือ Cr ล้วน — ไม่ได้บังคับว่าทั้ง entry ต้องสมดุล)
    → สินทรัพย์ 580 แต่ฝั่งขวา 500 จึงต้องรายงานว่าไม่สมดุล

    ถ้าไม่มีเทสต์นี้ การที่เทสต์ก่อนหน้าผ่านอาจเป็นเพราะ `is_balanced` ค้างเป็น True
    ไม่ใช่เพราะสมการจริง
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องสมการพัง")
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    capital = await _insert_ledger(db_pool, room_id, account_name="ทุน", account_type="equity", account_code="3001")

    await _post_entry(db_pool, room_id, description="ทุนตั้งต้น",
                      lines=[(cash, 500.0, 0), (capital, 0, 500.0)])

    # ขาเดียวลอย ๆ — Dr เงินสด 80 โดยไม่มี Cr คู่
    stray = await _post_entry(db_pool, room_id, description="ขาลอย", lines=[(cash, 80.0, 0)])

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT AL.account_name, COALESCE(SUM(L.debit), 0) AS dr, COALESCE(SUM(L.credit), 0) AS cr
            FROM journal_lines L
            JOIN journal_entries JE ON L.journal_entry_id = JE.id
            JOIN accounting_ledgers AL ON L.ledger_id = AL.id
            WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
            GROUP BY AL.account_name
            """,
            room_id,
        )
    by_name = {r["account_name"]: (float(r["dr"]), float(r["cr"])) for r in rows}
    assert by_name["เงินสด"] == (580.0, 0.0)
    assert by_name["ทุน"] == (0.0, 500.0)
    assert stray is not None

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=9, year=2026,
    )
    wb = openpyxl.load_workbook(excel_file)
    bs_rows = _values(wb, "งบแสดงฐานะการเงิน (BS)")[3:]

    assets = _find_row(bs_rows, 1, "รวมสินทรัพย์")
    combined = _find_row(bs_rows, 1, "รวมหนี้สินและส่วนของเจ้าของ")
    assert assets[2] == pytest.approx(580.0)
    assert combined[2] == pytest.approx(500.0)

    balanced = _find_row(bs_rows, 1, "ตรวจสอบสมดุล (Assets = Liab + Equity + Retained)")
    assert "ไม่สมดุล" in str(balanced[2])

    # และงบทดลองก็ต้องบอกว่าไม่สมดุลด้วย (Dr 580 ≠ Cr 500)
    # ⚠️ แถวรวมของงบทดลอง: ป้ายอยู่ **คอลัมน์ B (index 1)** ไม่ใช่ A และมี suffix "(Grand Total)"
    #    → เทสต์เดิมของ export เรียก `_find_row(tb_rows, 0, "รวมทั้งสิ้น")` ซึ่งผิด **สองชั้น**
    #      (คอลัมน์ผิด — ช่อง A ของแถวนั้นเป็น None — และป้ายขาด suffix) จึงพังมาตั้งแต่ commit 44b5499
    tb_rows = _values(wb, "งบทดลอง (Trial Balance)")[3:]
    tb_total = _find_row_containing(tb_rows, 1, "รวมทั้งสิ้น")
    assert tb_total[3] == pytest.approx(580.0)
    assert tb_total[4] == pytest.approx(500.0)
    assert tb_total[5] is not None and "ไม่สมดุล" in str(tb_total[5])


# =====================================================================
# [SCHEMA] response_model ต้องไม่ 500 กับเส้นทางปกติ
# =====================================================================


@pytest.mark.parametrize(
    "path,extra",
    [
        (TRIAL_BALANCE_PATH, {}),
        (BALANCE_SHEET_PATH, {}),
    ],
)
async def test_statements_without_explicit_date_return_200(client, db_pool, admin_headers, path, extra):
    """ไม่ส่งพารามิเตอร์วันที่เลย (เส้นทางที่ frontend ใช้จริง) — ต้อง 200.

    ครอบกับดัก `note: Optional[str]` ของ Pydantic: ถ้าใครลบ `= None` ออก
    `response_model` จะพังเป็น ResponseValidationError (500) ที่เส้นทางนี้ทันที
    """
    room_id = admin_headers.room_id
    res = client.get(path.format(room=room_id), params=extra, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert "note" in res.json()


async def test_balance_sheet_response_has_every_documented_key(client, db_pool, admin_headers):
    """ยืนยันสัญญาของ response — ฟิลด์ที่ frontend พึ่งต้องมีครบ (ไม่ตกหล่นเงียบ ๆ)."""
    room_id = admin_headers.room_id
    await _seed_full_chart(db_pool, room_id)

    res = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        params={"as_of_date": "2026-09-30"},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert set(body.keys()) == {
        "as_of", "assets", "assets_total", "liabilities", "liability_total",
        "equities", "equity_total", "retained_earnings", "total_equity_side",
        "total_liabilities_and_equity", "is_balanced", "period_net_income",
        "period_start", "period_end", "note",
    }
    row_keys = {"ledger_id", "account_code", "account_name", "account_type",
                "total_debit", "total_credit", "balance"}
    assert set(body["assets"][0].keys()) == row_keys
    assert set(body["liabilities"][0].keys()) == row_keys


# =====================================================================
# [SERVICE] เรียก service ตรง — กันกับดัก sync/async ของ `_compose_balance_sheet`
# =====================================================================


async def test_compose_balance_sheet_is_sync_and_awaiting_it_would_break(db_pool):
    """`_compose_balance_sheet` เป็น sync @classmethod — ยืนยันว่าไม่ใช่ coroutine.

    ถ้ามีคนเติม `async` ให้มันในอนาคต `await cls._compose_balance_sheet(...)` ใน
    `get_balance_sheet` จะได้ TypeError: object dict can't be used in 'await' expression
    """
    import inspect

    assert not inspect.iscoroutinefunction(FinanceService._compose_balance_sheet)

    result = FinanceService._compose_balance_sheet(
        tb={"ledgers": [
            {"ledger_id": 1, "account_code": "1001", "account_name": "เงินสด",
             "account_type": "asset", "total_debit": 100.0, "total_credit": 0.0, "balance": 100.0},
            {"ledger_id": 2, "account_code": "2001", "account_name": "เจ้าหนี้",
             "account_type": "liability", "total_debit": 0.0, "total_credit": 40.0, "balance": 40.0},
            {"ledger_id": 3, "account_code": "3001", "account_name": "ทุน",
             "account_type": "equity", "total_debit": 0.0, "total_credit": 60.0, "balance": 60.0},
        ]},
        period_net_income=0.0,
        as_of_str="30/09/2026",
    )
    assert result["liability_total"] == pytest.approx(40.0)
    assert result["assets_total"] == pytest.approx(100.0)
    assert result["total_liabilities_and_equity"] == pytest.approx(100.0)
    assert result["is_balanced"] is True


async def test_get_balance_sheet_service_is_period_scoped_for_retained(db_pool):
    """กำไรสะสมของงบดุลนับจากปีของ as_of เท่านั้น — ยืนยันผ่าน service ตรง."""
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องกำไรสะสม")
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    revenue = await _insert_ledger(db_pool, room_id, account_name="รายรับ", account_type="revenue", account_code="4001")

    await _post_entry(db_pool, room_id, description="รายรับปี 2026",
                      transaction_date=datetime(2026, 9, 15, 12, 0, 0),
                      lines=[(cash, 100.0, 0), (revenue, 0, 100.0)])
    await _post_entry(db_pool, room_id, description="รายรับปี 2027",
                      transaction_date=datetime(2027, 2, 15, 12, 0, 0),
                      lines=[(cash, 250.0, 0), (revenue, 0, 250.0)])

    bs_2026 = await FinanceService.get_balance_sheet(
        pool=db_pool, room_id=room_id, user_id=owner, as_of_date=date(2026, 12, 31),
    )
    assert bs_2026["period_start"] == "2026-09-01"
    assert bs_2026["period_end"] == "2026-12-31"
    assert bs_2026["retained_earnings"] == pytest.approx(100.0)
    assert bs_2026["assets_total"] == pytest.approx(100.0)

    bs_2027 = await FinanceService.get_balance_sheet(
        pool=db_pool, room_id=room_id, user_id=owner, as_of_date=date(2027, 12, 31),
    )
    assert bs_2027["period_start"] == "2027-01-01"
    # ⚠️ retained ของงบดุลเป็น "YTD ของงบทดลอง" (350) ไม่ใช่ "ของงวด" (250)
    #    ส่วน period_net_income เป็นของงวด — ทั้งคู่ต้องมาคู่กับ period_start/end เพื่อให้ผู้ตรวจเทียบได้
    assert bs_2027["retained_earnings"] == pytest.approx(350.0)
    assert bs_2027["period_net_income"] == pytest.approx(250.0)
    assert bs_2027["assets_total"] == pytest.approx(350.0)
    assert bs_2027["is_balanced"] is True


# =====================================================================
# [TIMEZONE] ขอบเขตวันต้องคิดตามเวลาไทย ไม่ใช่ TZ ของ container ที่รัน
# =====================================================================
#
# บั๊กที่เทสต์ชุดนี้ล็อกไว้: โค้ดเดิมสร้างขอบเขตเวลาด้วย `datetime.combine(d, dtime(23,59,59))`
# แบบ **naive** แล้ว asyncpg เข้ารหัส naive datetime เป็น "เวลาท้องถิ่นของเครื่องที่รัน"
# (ไม่ใช่ UTC) → ใน container ที่ TZ=UTC (ซึ่งคือภาพ production) ค่า 23:59:59 กลายเป็น
# 06:59:59 ของวันถัดไปตามเวลาไทย ⇒ งบของวันที่ d แอบกินข้อมูลถึงเช้าวันที่ d+1
# ขณะที่เครื่อง dev ที่ TZ=Asia/Bangkok กลับถูกโดยบังเอิญ → รายงานเดียวกันให้ตัวเลขคนละชุด
#
# ทุกเทสต์ในส่วนนี้ใช้เวลาที่ **UTC ยังเป็นวันก่อนหน้า** (ตี 1:30 ไทย = 18:30 UTC ของเมื่อวาน)
# จึงแยกแยะได้จริงระหว่าง "คิดตามเวลาไทย" กับ "คิดตาม TZ ของ container"

# เวลาไทย = UTC+7 คงที่ (ไม่มี DST) — เขียน offset ตรง ๆ **ไม่ดึง THAI_TZ จาก production**
# เพื่อให้เทสต์ยังจับได้ถ้ามีคนแก้ค่าคงที่นั้นเป็นค่าอื่น
THAI_OFFSET = timezone(timedelta(hours=7))


def _bkk(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> datetime:
    """สร้างเวลาที่ *เจตนา* ว่า "hh:mm:ss ตามเวลาไทยของวันนั้น" — tz-aware."""
    return datetime(y, m, d, hh, mm, ss, tzinfo=THAI_OFFSET)


async def _seed_cash_and_capital(pool, room_id: int) -> tuple:
    """ผังบัญชี 2 ตัว (เงินสด = asset, ทุน = equity) + entry ที่สมดุลเองทุกใบ.

    ใช้คู่เงินสด/ทุนเพราะทุก entry ที่ลงจะขยับ **ทั้งสองข้างเท่ากัน** → งบดุลต้อง
    `is_balanced` เสมอไม่ว่าจะตัดข้อมูลที่วันไหน การที่ยอดฝั่งสินทรัพย์เปลี่ยนตาม
    as_of_date จึงวัด "หน้าต่างเวลาที่ถูกตัด" ได้ตรง ๆ โดยไม่มีสัญญาณรบกวนจากสมการ
    """
    cash = await _insert_ledger(pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    capital = await _insert_ledger(pool, room_id, account_name="ทุนห้องเรียน", account_type="equity", account_code="3001")
    return cash, capital


@pytest.mark.parametrize(
    "as_of,expected_cash",
    [
        (date(2026, 9, 1), 0.0),      # ยังไม่ถึงวันของ A (A เกิดตี 1:30 วันที่ 2 ไทย)
        (date(2026, 9, 2), 111.0),    # ถึง A แต่ยังไม่ถึง B
        (date(2026, 9, 3), 333.0),    # ถึงทั้งคู่
    ],
)
async def test_as_of_window_is_bangkok_scoped(client, db_pool, admin_headers, as_of, expected_cash):
    """`as_of_date=d` ต้องหมายถึง "สิ้นวัน d ตามเวลาไทย" ไม่ใช่ตาม TZ ของ container.

    จุดที่พังก่อนแก้: entry A อยู่ที่ UTC 2026-09-01 18:30 (= ไทย 2 ก.ย. 01:30).
    โค้ดเดิมใช้ขอบบน naive 23:59:59 → container TZ=UTC แปลได้เป็น 2026-09-01 23:59:59Z
    ซึ่ง **มากกว่า** 18:30Z → A ถูกนับเข้าใน as_of = 1 ก.ย. ทั้งที่เป็นของวันที่ 2
    """
    room_id = admin_headers.room_id
    cash, capital = await _seed_cash_and_capital(db_pool, room_id)

    # A: ไทย 2 ก.ย. 01:30 (UTC 1 ก.ย. 18:30) / B: ไทย 3 ก.ย. 01:30 (UTC 2 ก.ย. 18:30)
    await _post_entry(db_pool, room_id, description="A ตีหนึ่งครึ่งของวันที่ 2",
                      transaction_date=_bkk(2026, 9, 2, 1, 30),
                      lines=[(cash, 111.0, 0), (capital, 0, 111.0)])
    await _post_entry(db_pool, room_id, description="B ตีหนึ่งครึ่งของวันที่ 3",
                      transaction_date=_bkk(2026, 9, 3, 1, 30),
                      lines=[(cash, 222.0, 0), (capital, 0, 222.0)])

    tb = client.get(
        TRIAL_BALANCE_PATH.format(room=room_id),
        headers=admin_headers, params={"as_of_date": as_of.isoformat()},
    )
    assert tb.status_code == 200, tb.text
    cash_row = _by_ledger_id(tb.json()["ledgers"], cash)
    assert cash_row["balance"] == pytest.approx(expected_cash), (
        f"as_of={as_of} ควรเห็นเงินสด {expected_cash} แต่ได้ {cash_row['balance']} "
        "→ ขอบเขตวันไม่ได้คิดตามเวลาไทย"
    )

    bs = client.get(
        BALANCE_SHEET_PATH.format(room=room_id),
        headers=admin_headers, params={"as_of_date": as_of.isoformat()},
    )
    assert bs.status_code == 200, bs.text
    body = bs.json()
    # งบดุลต้องเห็นยอดเดียวกับงบทดลองเป๊ะ (ทั้งคู่ใช้ _fetch_trial_balance_ledgers)
    assert body["assets_total"] == pytest.approx(expected_cash)
    assert body["equity_total"] == pytest.approx(expected_cash)
    assert body["is_balanced"] is True


async def test_day_boundary_is_exact_at_bangkok_midnight(client, db_pool, admin_headers):
    """ขอบวันต้องเป๊ะที่เที่ยงคืนไทย — 23:59:59 ของวันนั้นนับ, 00:00:00 ของวันถัดไปไม่นับ.

    เทสต์นี้ล็อกทั้งบั๊ก timezone และช่องโหว่ "วินาทีสุดท้ายหลุด" ของเงื่อนไข `< $2`
    ใน get_trial_balance (เดิม `< 23:59:59` ตัดรายการที่เกิด 23:59:59 พอดีออก)
    """
    room_id = admin_headers.room_id
    cash, capital = await _seed_cash_and_capital(db_pool, room_id)

    await _post_entry(db_pool, room_id, description="วินาทีสุดท้ายของวันที่ 2",
                      transaction_date=_bkk(2026, 9, 2, 23, 59, 59),
                      lines=[(cash, 55.0, 0), (capital, 0, 55.0)])
    await _post_entry(db_pool, room_id, description="เที่ยงคืนของวันที่ 3 พอดี",
                      transaction_date=_bkk(2026, 9, 3, 0, 0, 0),
                      lines=[(cash, 77.0, 0), (capital, 0, 77.0)])

    tb2 = client.get(TRIAL_BALANCE_PATH.format(room=room_id), headers=admin_headers,
                     params={"as_of_date": "2026-09-02"})
    assert tb2.status_code == 200, tb2.text
    assert _by_ledger_id(tb2.json()["ledgers"], cash)["balance"] == pytest.approx(55.0), (
        "as_of 2 ก.ย. ต้องได้ 55 (ไม่ใช่ 132) → ขอบบนต้องเป็นเที่ยงคืนไทยของวันที่ 3"
    )

    tb3 = client.get(TRIAL_BALANCE_PATH.format(room=room_id), headers=admin_headers,
                     params={"as_of_date": "2026-09-03"})
    assert _by_ledger_id(tb3.json()["ledgers"], cash)["balance"] == pytest.approx(132.0)


async def test_income_statement_end_date_is_bangkok_scoped(client, db_pool, admin_headers):
    """`end_date` ของงบกำไรขาดทุนต้องครอบถึงสิ้นวันนั้น *ตามเวลาไทย*."""
    room_id = admin_headers.room_id
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    revenue = await _insert_ledger(db_pool, room_id, account_name="รายรับบริจาค", account_type="revenue", account_code="4001")

    # ไทย 3 ก.ย. 01:30 = UTC 2 ก.ย. 18:30 → ต้องเป็นของงวดที่สิ้นสุด 3 ก.ย. ไม่ใช่ 2 ก.ย.
    await _post_entry(db_pool, room_id, description="รายรับตีหนึ่งครึ่ง",
                      transaction_date=_bkk(2026, 9, 3, 1, 30),
                      lines=[(cash, 999.0, 0), (revenue, 0, 999.0)])

    sep2 = client.get(INCOME_STATEMENT_PATH.format(room=room_id), headers=admin_headers,
                      params={"start_date": "2026-09-01", "end_date": "2026-09-02"})
    assert sep2.status_code == 200, sep2.text
    assert sep2.json()["total_revenue"] == pytest.approx(0.0), (
        "งวดสิ้นสุด 2 ก.ย. ต้องไม่เห็นรายการของตี 1:30 วันที่ 3 ก.ย. (เวลาไทย)"
    )
    assert sep2.json()["net_income"] == pytest.approx(0.0)

    sep3 = client.get(INCOME_STATEMENT_PATH.format(room=room_id), headers=admin_headers,
                      params={"start_date": "2026-09-01", "end_date": "2026-09-03"})
    assert sep3.status_code == 200, sep3.text
    assert sep3.json()["total_revenue"] == pytest.approx(999.0)


async def test_income_statement_window_matches_balance_sheet_period_memo(db_pool):
    """`period_net_income` ของงบดุล ต้องเท่ากับ `net_income` ของงบกำไรขาดทุนในงวดเดียวกัน.

    สองตัวนี้คำนวณจากคนละพาธ (BS: `_fetch_income_statement_rows` ผ่าน period_start/period_end
    ที่ derived; IS: `get_income_statement` ตรง ๆ) — ถ้าขอบเขตเวลาไม่ตรงกัน ค่าจะเพี้ยนจากกัน
    ซึ่งเป็นอาการที่ผู้ใช้เห็นได้ทันที ("ทำไมงบดุลกับงบกำไรขาดทุนไม่ตรงกัน")
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้องเทียบสองงบ")
    cash = await _insert_ledger(db_pool, room_id, account_name="เงินสด", account_type="asset", account_code="1001")
    revenue = await _insert_ledger(db_pool, room_id, account_name="รายรับ", account_type="revenue", account_code="4001")
    expense = await _insert_ledger(db_pool, room_id, account_name="ค่าใช้จ่าย", account_type="expense", account_code="5001")

    # ลงรายการที่ "เวลาไทยเป็นวันที่ 2" แต่ UTC ยังเป็นวันที่ 1 → ตกตรงขอบพอดี
    await _post_entry(db_pool, room_id, description="รายรับตี 1:30 วันที่ 2",
                      transaction_date=_bkk(2026, 9, 2, 1, 30),
                      lines=[(cash, 400.0, 0), (revenue, 0, 400.0)])
    await _post_entry(db_pool, room_id, description="รายจ่ายตี 2:00 วันที่ 2",
                      transaction_date=_bkk(2026, 9, 2, 2, 0),
                      lines=[(expense, 150.0, 0), (cash, 0, 150.0)])

    as_of = date(2026, 9, 2)
    bs = await FinanceService.get_balance_sheet(
        pool=db_pool, room_id=room_id, user_id=owner, as_of_date=as_of,
    )
    is_stmt = await FinanceService.get_income_statement(
        pool=db_pool, room_id=room_id, user_id=owner,
        start_date=date(2026, 9, 1), end_date=as_of,
    )

    assert bs["period_start"] == "2026-09-01"
    assert bs["period_end"] == "2026-09-02"
    assert is_stmt["net_income"] == pytest.approx(250.0)
    assert bs["period_net_income"] == pytest.approx(is_stmt["net_income"]), (
        "period_net_income ของงบดุลต้องตรงกับ net_income ของงบกำไรขาดทุนในงวดเดียวกัน"
    )
    # และฝั่งที่ตัดด้วย as_of ต้องเห็นทั้งสองรายการ (ไม่ใช่เห็นแต่รายการที่ UTC ยังเป็นวันที่ 1)
    assert bs["assets_total"] == pytest.approx(250.0)
    assert bs["is_balanced"] is True


async def test_export_balance_sheet_period_is_bangkok_scoped(db_pool):
    """แผ่น BS ในไฟล์ Excel ต้องใช้ขอบเขตเวลาไทยเหมือนกัน (export.py ไม่ใช่ทางผ่านคนละโลก).

    เทสต์นี้มีเพราะ `export.py` สร้างขอบเขตของตัวเอง (`lower_dt`/`upper_dt`/`pl_start`)
    แล้วป้อนเข้า `_fetch_*` ตัวเดียวกับที่หน้าเว็บใช้ — ถ้าแก้แต่ reporting.py
    ตัวเลขบนจอกับในไฟล์จะไม่ตรงกัน ซึ่งขัดกับข้อกำหนดตรวจรับของ F1
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้อง export timezone")
    cash, capital = await _seed_cash_and_capital(db_pool, room_id)

    await _post_entry(db_pool, room_id, description="ทุนในเดือน ก.ย.",
                      transaction_date=_bkk(2026, 9, 1, 12, 0),
                      lines=[(cash, 500.0, 0), (capital, 0, 500.0)])
    # ตี 1:30 ของวันที่ 1 ต.ค. ไทย = 18:30 UTC ของ 30 ก.ย. → ต้องไม่ถูกนับในรายงานเดือน ก.ย.
    await _post_entry(db_pool, room_id, description="ทุนตีหนึ่งครึ่งเดือน ต.ค.",
                      transaction_date=_bkk(2026, 10, 1, 1, 30),
                      lines=[(cash, 300.0, 0), (capital, 0, 300.0)])

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=9, year=2026,
    )
    wb = openpyxl.load_workbook(excel_file)
    bs_rows = _values(wb, "งบแสดงฐานะการเงิน (BS)")[3:]

    assets = _find_row(bs_rows, 1, "รวมสินทรัพย์")
    assert assets[2] == pytest.approx(500.0), (
        "รายงานเดือน ก.ย. ต้องไม่นับรายการของตี 1:30 วันที่ 1 ต.ค. (เวลาไทย)"
    )


async def test_export_journal_sheet_matches_other_sheets_bangkok_bounds(db_pool):
    """ชีต 'สมุดรายวันทั่วไป (GJ)' ต้องใช้ขอบเขตเวลาไทย **ชุดเดียวกับ** ชีตอื่นในไฟล์เดียวกัน.

    เดิมชีตนี้กรองด้วย `DATE(JE.transaction_date) >= $n` ซึ่ง `DATE()` บนคอลัมน์ timestamptz
    จะตัดตาม TimeZone ของ session (DB ตั้ง UTC) ขณะที่ชีต GL/TB/IS/BS ใช้ `lower_dt`/`upper_dt`
    แบบ tz-aware เวลาไทย → รายการที่บันทึก 00:00–07:00 น. เวลาไทยของวันหัว/ท้ายช่วง
    หลุดออกจากชีต GJ แต่ยังถูกนับในชีตงบ → **ไฟล์ Excel เดียวขัดแย้งกันเอง**

    เทสต์นี้จึงยืนยันสองชั้น: (1) รายการที่ตกตรงขอบต้องอยู่/ไม่อยู่ให้ถูก และ
    (2) ยอดรวมของชีต GJ ต้องเท่ากับยอดรวมของชีตงบทดลอง
    """
    owner = await _insert_user(db_pool, first_name="Admin", last_name="Owner")
    room_id = await _insert_room(db_pool, owner, room_name="ห้อง GJ timezone")
    cash, capital = await _seed_cash_and_capital(db_pool, room_id)

    # 03:00 น. วันที่ 1 ก.ย. ไทย = 20:00 UTC ของ 31 ส.ค. → DATE() ตาม session UTC เห็นเป็น 31 ส.ค.
    await _post_entry(db_pool, room_id, description="ทุนตีสามวันที่ 1 ก.ย.",
                      transaction_date=_bkk(2026, 9, 1, 3, 0),
                      lines=[(cash, 500.0, 0), (capital, 0, 500.0)])
    # 03:00 น. วันที่ 1 ต.ค. ไทย = 20:00 UTC ของ 30 ก.ย. → DATE() ตาม session UTC เห็นเป็น 30 ก.ย.
    await _post_entry(db_pool, room_id, description="ทุนตีสามวันที่ 1 ต.ค.",
                      transaction_date=_bkk(2026, 10, 1, 3, 0),
                      lines=[(cash, 300.0, 0), (capital, 0, 300.0)])

    excel_file = await FinanceService.export_journal_excel(
        pool=db_pool, client_source="test", actor_identifier="test",
        room_id=room_id, user_id=owner, month=9, year=2026,
    )
    wb = openpyxl.load_workbook(excel_file)
    gj_rows = _values(wb, "สมุดรายวันทั่วไป (GJ)")[3:]

    descriptions = [r[3] for r in gj_rows]
    assert "ทุนตีสามวันที่ 1 ก.ย." in descriptions, (
        "รายการ 03:00 น. เวลาไทยของวันแรกของช่วง ต้องอยู่ในชีตสมุดรายวัน "
        "(เดิมหลุดเพราะ DATE() ตัดตาม session TZ = UTC)"
    )
    assert "ทุนตีสามวันที่ 1 ต.ค." not in descriptions, (
        "รายการ 03:00 น. เวลาไทยของวันที่ 1 ต.ค. ต้องไม่หลุดเข้ามาในรายงานเดือน ก.ย."
    )

    gj_total = _find_row_containing(gj_rows, 3, "รวมทั้งสิ้น")
    assert gj_total[6] == pytest.approx(500.0), (
        "ยอดเดบิตรวมของชีตสมุดรายวันต้องเท่ากับรายการของเดือน ก.ย. ตามเวลาไทย"
    )

    # ชั้นที่สอง: ไฟล์เดียวกันต้องไม่ขัดแย้งกันเอง — ยอดรวม GJ ต้องเท่างบทดลอง
    tb_rows = _values(wb, "งบทดลอง (Trial Balance)")[3:]
    tb_total = _find_row_containing(tb_rows, 1, "รวมทั้งสิ้น")
    assert gj_total[6] == pytest.approx(tb_total[3]), (
        "ยอดเดบิตรวมในชีตสมุดรายวันต้องเท่ากับชีตงบทดลองในไฟล์เดียวกัน "
        f"(GJ={gj_total[6]}, TB={tb_total[3]})"
    )


async def test_thai_day_bound_helpers_are_tz_aware_and_pin_correct_instants():
    """ทดสอบ helper ตรง ๆ — ล็อกค่าที่ถูกต้องไว้ ไม่ต้องพึ่ง DB.

    helper เหล่านี้เป็นจุดเดียวที่กันบั๊ก timezone ไว้ทั้งระบบ ถ้ามีคนเผลอถอด tzinfo
    ออก เทสต์นี้จะพังทันทีโดยไม่ต้องรอให้ตัวเลขงบเพี้ยน
    """
    start = _thai_day_start(date(2026, 9, 1))
    end = _thai_day_end(date(2026, 9, 1))
    nxt = _thai_next_day_start(date(2026, 9, 1))

    # ต้องมี tzinfo เสมอ — naive คือรากของบั๊กทั้งชุด
    for name, dt in (("_thai_day_start", start), ("_thai_day_end", end), ("_thai_next_day_start", nxt)):
        assert dt.tzinfo is not None, f"{name} ต้องคืน datetime ที่มี tzinfo (ห้าม naive)"

    utc = timezone.utc
    # ต้นวันไทย 1 ก.ย. = 31 ส.ค. 17:00 UTC (ไม่ใช่ 1 ก.ย. 00:00 UTC)
    assert start.astimezone(utc) == datetime(2026, 8, 31, 17, 0, tzinfo=utc)
    # ปลายวันไทย 1 ก.ย. ต้องอยู่ในวันที่ 1 ก.ย. ตามเวลาไทย และก่อนเที่ยงคืนถัดไปเสมอ
    assert end.astimezone(THAI_OFFSET).date() == date(2026, 9, 1)
    assert end < nxt
    # ขอบบนแบบไม่รวม = เที่ยงคืนไทยของวันถัดไปพอดี
    assert nxt.astimezone(THAI_OFFSET) == datetime(2026, 9, 2, 0, 0, tzinfo=THAI_OFFSET)
    assert nxt.astimezone(utc) == datetime(2026, 9, 1, 17, 0, tzinfo=utc)
    # ปลายวันต้องไม่ตกไปแตะวันถัดไปแม้แต่ไมโครวินาทีเดียว
    assert _thai_day_end(date(2026, 9, 1)) < _thai_next_day_start(date(2026, 9, 1))
