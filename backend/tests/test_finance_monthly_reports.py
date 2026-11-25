"""📊 [FIN-V2 / P5.4] RPT — รายงานปิดงบเดือน (snapshot/version/cash count/variance)

═══════════════════════════════════════════════════════════════════════════════
🎯 เทสต์ชุดนี้ป้องกันอะไร
═══════════════════════════════════════════════════════════════════════════════
1. **ยอดมาจาก journal ที่ posted เท่านั้น** — ไม่นับ draft/voided/opening_balance
   และIncome/Expense มาจาก `account_type` ของ ledger ไม่ใช่เครื่องหมายในบิล
2. **1 งวด active ได้ใบเดียว** — draft/final ที่ยังใช้งาน = 409
3. **version/report_no** — v1 = `RPT-2569-11`, หลัง void + สร้างใหม่ = `RPT-2569-11-v2`
4. **unique (room, year, month, version)** — พิสูจน์ที่ DB ไม่ใช่แค่ service
5. **finalize ต้อง variance = 0** — ต่าง ≥ 0.005 → 400 และสถานะไม่เปลี่ยน
6. **void เฉพาะใบล่าสุด** — เก็บ report_no เดิม ไม่แตะ journal
7. **opening_cash** — ใช้ `closing_cash` ของรายงาน final เดือนก่อน
8. **PDF ผ่าน registry** — `%PDF-` magic bytes (patch Gotenberg)

⚠️ ยืนยันกับ DB จริงผ่าน `db_pool` ตาม `docs/rules/testing.md`
"""
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from services.finance.constants import THAI_TZ

pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/classroom"
RPT_PATH = API_PREFIX + "/{room}/finance/monthly-reports"

BE = 2569          # พ.ศ. ของปี ค.ศ. 2026


def _url(template: str, room_id: int, suffix: str = "") -> str:
    """`?target_type=room` ต้องอยู่ **ท้าย URL จริง** — suffix ต่อก่อน query เสมอ"""
    return template.format(room=room_id) + suffix + "?target_type=room"


def _create(client, headers, *, year_be=BE, month=11, note=None, room_id=None):
    body = {"year_be": year_be, "month": month}
    if note is not None:
        body["note"] = note
    return client.post(
        _url(RPT_PATH, room_id if room_id is not None else headers.room_id),
        json=body, headers=headers,
    )


def _finalize(client, headers, report_id: int, counted_cash: float, note=None):
    body = {"counted_cash": counted_cash}
    if note is not None:
        body["note"] = note
    return client.post(
        _url(RPT_PATH, headers.room_id, suffix=f"/{report_id}/finalize"),
        json=body, headers=headers,
    )


def _void(client, headers, report_id: int, reason: str = "จัดทำผิดงวด"):
    return client.post(
        _url(RPT_PATH, headers.room_id, suffix=f"/{report_id}/void"),
        json={"reason": reason}, headers=headers,
    )


# ═══════════════════════════════════════════════════════════════════ journal seed
async def _ledger(pool, room_id: int, code: str, name: str, account_type: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            room_id, code, name, account_type,
        )


async def _post_journal(pool, room_id: int, *, when: datetime, lines: list) -> str:
    """POSTED entry เดียว + บรรทัด (ledger_id, debit, credit) — คืน id ของ entry"""
    async with pool.acquire() as conn:
        journal_id = await conn.fetchval(
            """INSERT INTO journal_entries
                   (room_id, reference_type, reference_id, description, status, transaction_date)
               VALUES ($1, 'test_seed', NULL, 'seed', 'posted', $2)
               RETURNING id""",
            room_id, when,
        )
        for ledger_id, debit, credit in lines:
            await conn.execute(
                """INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit)
                   VALUES ($1, $2, $3, $4)""",
                journal_id, ledger_id, debit, credit,
            )
        return str(journal_id)


async def _seed_month(
    pool, room_id: int, *, year_ce: int = 2026, month: int = 11,
    income: float = 500.0, expense: float = 300.0,
) -> dict:
    """รายได้ 1 บรรทัด + รายจ่าย 1 บรรทัด กลางเดือน — คืน ledger ids"""
    asset = await _ledger(pool, room_id, "11101", "เงินสดในมือ", "asset")
    revenue = await _ledger(pool, room_id, "41001", "รายได้ค่าห้อง", "revenue")
    exp = await _ledger(pool, room_id, "51001", "ค่าใช้จ่ายทั่วไป", "expense")
    when = datetime(year_ce, month, 10, 12, 0, tzinfo=THAI_TZ)

    if income:
        await _post_journal(
            pool, room_id, when=when,
            lines=[(asset, income, 0), (revenue, 0, income)],
        )
    if expense:
        await _post_journal(
            pool, room_id, when=when,
            lines=[(exp, expense, 0), (asset, 0, expense)],
        )
    return {"asset": asset, "revenue": revenue, "expense": exp}


# ═══════════════════════════════════════════════════════════════════ DB helpers
async def _report_row(pool, report_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT id, room_id, year_be, month, version, report_no, status,
                      snapshot, total_income, total_expense, opening_cash, closing_cash,
                      counted_cash, variance, finalized_at, finalized_by,
                      voided_at, void_reason
               FROM finance_monthly_reports WHERE id = $1""",
            report_id,
        )


async def _journal_counts(pool, room_id: int) -> tuple:
    async with pool.acquire() as conn:
        je = await conn.fetchval(
            "SELECT COUNT(*) FROM journal_entries WHERE room_id = $1", room_id,
        )
        jl = await conn.fetchval(
            """SELECT COUNT(*) FROM journal_lines L
                 JOIN journal_entries JE ON L.journal_entry_id = JE.id
                WHERE JE.room_id = $1""",
            room_id,
        )
    return int(je), int(jl)


def _snapshot_of(row) -> dict:
    raw = row["snapshot"]
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


# ═══════════════════════════════════════ 1. totals จาก journal
async def test_create_draft_computes_totals_from_journal(client, db_pool, admin_headers):
    await _seed_month(db_pool, admin_headers.room_id, income=500.0, expense=300.0)

    res = _create(client, admin_headers, month=11)
    assert res.status_code == 200, res.text
    report = res.json()["report"]

    assert report["status"] == "draft"
    assert report["report_no"] == "RPT-2569-11"
    assert report["version"] == 1
    assert report["total_income"] == 500.0
    assert report["total_expense"] == 300.0
    assert report["opening_cash"] == 0.0
    assert report["closing_cash"] == 200.0
    assert report["counted_cash"] is None
    assert report["variance"] is None

    snapshot = report["snapshot"]
    assert snapshot["period"]["year_be"] == BE
    assert snapshot["period"]["month"] == 11
    assert snapshot["income_by_category"][0]["account_code"] == "41001"
    assert snapshot["income_by_category"][0]["amount"] == 500.0
    assert snapshot["expense_by_category"][0]["account_code"] == "51001"
    assert snapshot["expense_by_category"][0]["amount"] == 300.0
    assert snapshot["cash"]["closing"] == 200.0


# ═══════════════════════════════════════ 2. งวดเดียวมีใบ active ใบเดียว
async def test_create_second_active_report_conflicts(client, db_pool, admin_headers):
    first = _create(client, admin_headers)
    assert first.status_code == 200, first.text

    second = _create(client, admin_headers)
    assert second.status_code == 409, second.text

    count = await db_pool.fetchval(
        "SELECT COUNT(*) FROM finance_monthly_reports WHERE room_id = $1",
        admin_headers.room_id,
    )
    assert count == 1


# ═══════════════════════════════════════ 3. version + report_no
async def test_report_no_versioning(client, db_pool, admin_headers):
    first = _create(client, admin_headers)
    assert first.status_code == 200, first.text
    assert first.json()["report"]["report_no"] == "RPT-2569-11"

    voided = _void(client, admin_headers, first.json()["report"]["id"])
    assert voided.status_code == 200, voided.text

    second = _create(client, admin_headers)
    assert second.status_code == 200, second.text
    report = second.json()["report"]
    assert report["version"] == 2
    assert report["report_no"] == "RPT-2569-11-v2"


# ═══════════════════════════════════════ 4. unique (room, year, month, version) ที่ DB
async def test_unique_room_year_month_version(client, db_pool, admin_headers):
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text

    with pytest.raises(asyncpg.UniqueViolationError) as exc:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO finance_monthly_reports
                       (room_id, year_be, month, version, report_no, status, snapshot,
                        total_income, total_expense, opening_cash, closing_cash)
                   VALUES ($1, $2, 11, 1, 'RPT-2569-11-dup', 'draft', '{}'::jsonb,
                           0, 0, 0, 0)""",
                admin_headers.room_id, BE,
            )
    assert exc.value.constraint_name == "uq_finance_monthly_reports_version"


# ═══════════════════════════════════════ 5. finalize ต้อง variance = 0
async def test_finalize_requires_variance_zero(client, db_pool, admin_headers):
    await _seed_month(db_pool, admin_headers.room_id, income=500.0, expense=300.0)
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["id"]

    res = _finalize(client, admin_headers, report_id, counted_cash=201.0)
    assert res.status_code == 400, res.text
    assert "ต่าง" in res.json()["detail"]

    row = await _report_row(db_pool, report_id)
    assert row["status"] == "draft"
    assert row["counted_cash"] is None
    assert row["variance"] is None
    assert row["finalized_at"] is None


# ═══════════════════════════════════════ 6. finalize สำเร็จ → final + variance 0
async def test_finalize_sets_final_and_variance(client, db_pool, admin_headers):
    await _seed_month(db_pool, admin_headers.room_id, income=500.0, expense=300.0)
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["id"]

    res = _finalize(client, admin_headers, report_id, counted_cash=200.0,
                    note="นับเงินเสร็จ")
    assert res.status_code == 200, res.text
    report = res.json()["report"]
    assert report["status"] == "final"
    assert report["counted_cash"] == 200.0
    assert report["variance"] == 0.0

    row = await _report_row(db_pool, report_id)
    assert row["status"] == "final"
    assert row["finalized_at"] is not None
    assert row["finalized_by"] == admin_headers.user_id
    assert float(row["variance"]) == 0.0
    assert _snapshot_of(row).get("finalize_note") == "นับเงินเสร็จ"


# ═══════════════════════════════════════ 7. finalize ซ้ำ = 409
async def test_finalize_twice_conflicts(client, db_pool, admin_headers):
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["id"]

    first = _finalize(client, admin_headers, report_id, counted_cash=0.0)
    assert first.status_code == 200, first.text

    second = _finalize(client, admin_headers, report_id, counted_cash=0.0)
    assert second.status_code == 409, second.text


# ═══════════════════════════════════════ 8. void ได้เฉพาะฉบับล่าสุด
async def test_void_only_latest_version(client, db_pool, admin_headers):
    v1 = _create(client, admin_headers)
    assert v1.status_code == 200, v1.text
    v1_id = v1.json()["report"]["id"]
    assert _void(client, admin_headers, v1_id).status_code == 200

    v2 = _create(client, admin_headers)
    assert v2.status_code == 200, v2.text
    v2_id = v2.json()["report"]["id"]

    # v1 เป็นฉบับเก่า (และถูกยกเลิกแล้ว) — void ซ้ำต้อง 409
    old = _void(client, admin_headers, v1_id)
    assert old.status_code == 409, old.text

    # v2 คือฉบับล่าสุด — void ได้
    latest = _void(client, admin_headers, v2_id)
    assert latest.status_code == 200, latest.text
    row = await _report_row(db_pool, v2_id)
    assert row["status"] == "voided"
    assert row["voided_at"] is not None


# ═══════════════════════════════════════ 9. void เก็บเลขเดิม + ไม่แตะ journal
async def test_void_keeps_report_no_and_does_not_touch_journal(
    client, db_pool, admin_headers
):
    await _seed_month(db_pool, admin_headers.room_id)
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["id"]
    report_no = created.json()["report"]["report_no"]

    before = await _journal_counts(db_pool, admin_headers.room_id)

    res = _void(client, admin_headers, report_id, reason="ยอดยกมาผิด")
    assert res.status_code == 200, res.text

    row = await _report_row(db_pool, report_id)
    assert row["status"] == "voided"
    assert row["report_no"] == report_no, "ห้ามคืน/เปลี่ยนเลขที่ออกแล้ว"
    assert row["void_reason"] == "ยอดยกมาผิด"
    assert _snapshot_of(row)["cash"]["closing"] == 200.0

    assert await _journal_counts(db_pool, admin_headers.room_id) == before


# ═══════════════════════════════════════ 10. opening_cash ใช้รายงาน final เดือนก่อน
async def test_opening_cash_uses_previous_final_report(client, db_pool, admin_headers):
    await _seed_month(
        db_pool, admin_headers.room_id, year_ce=2026, month=10,
        income=500.0, expense=300.0,
    )
    october = _create(client, admin_headers, month=10)
    assert october.status_code == 200, october.text
    oct_report = october.json()["report"]
    assert oct_report["closing_cash"] == 200.0

    closed = _finalize(
        client, admin_headers, oct_report["id"], counted_cash=200.0,
    )
    assert closed.status_code == 200, closed.text

    november = _create(client, admin_headers, month=11)
    assert november.status_code == 200, november.text
    nov_report = november.json()["report"]
    assert nov_report["opening_cash"] == 200.0
    assert nov_report["total_income"] == 0.0
    assert nov_report["total_expense"] == 0.0
    assert nov_report["closing_cash"] == 200.0


# ═══════════════════════════════════════ 11. PDF — `%PDF-` magic bytes
async def test_rpt_pdf_returns_pdf(client, db_pool, admin_headers):
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["id"]

    with patch(
        "services.finance.pdf.html_to_pdf",
        AsyncMock(return_value=b"%PDF-1.4 fake"),
    ) as mocked:
        res = client.get(_url(RPT_PATH, admin_headers.room_id, suffix=f"/{report_id}/pdf"), headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.content.startswith(b"%PDF-")
    assert res.headers["content-type"] == "application/pdf"
    assert "monthly-report-RPT-2569-11.pdf" in res.headers["content-disposition"]
    assert mocked.await_count == 1


# ═══════════════════════════════════════ 12. detail + ลายเซ็นผู้จัดทำ
async def test_detail_includes_prepared_signature(client, db_pool, admin_headers):
    created = _create(client, admin_headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["report"]["id"]

    res = client.get(_url(RPT_PATH, admin_headers.room_id, suffix=f"/{report_id}"), headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["report"]["id"] == report_id
    assert len(body["signatures"]) == 1
    assert body["signatures"][0]["role"] == "prepared"
