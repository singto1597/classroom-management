import asyncpg
import io
import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import List, Optional, Dict, Any
from zoneinfo import ZoneInfo

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.logger import AuditLogger
from core.exceptions import RoomNotFoundError, PaymentNotFoundError, TransactionNotFoundError
from core.rbac import require_permission, require_member
from services.action_service import ActionService

THAI_TZ = ZoneInfo("Asia/Bangkok")

# [ROUTER] 🗓️ จุดแบ่งยุค (Cut-off) ระหว่างระบบ Single-Entry (legacy) กับ Double-Entry
# =================================================================================
# วันที่ 2026-09-01 เป็นวันที่ยอดยกมา (Opening Balance, Phase 2.5) เข้า journal_entries
# → ข้อมูลก่อนวันนี้ อ่านจากตารางเก่า (finance_transactions) เท่านั้น
# → ข้อมูลตั้งแต่วันนี้ขึ้นไป อ่านจากระบบบัญชีคู่ (journal_entries/journal_lines)
#   เพื่อไม่ให้รายการเก่า/ยอดยกมา เบิ้ลหรือตกหล่น
CUTOFF_DATE = date(2026, 9, 1)

service_logger = AuditLogger(service_name="FINANCE")

# 📚 ฉลากไทยของ reference_type สำหรับคอลัมน์ Reference ใน export สมุดรายวัน
# (reference_id ที่เก็บไว้ = id ของเอกสารต้นทาง เช่น legacy_transaction_id / transfer_group_id)
REFERENCE_TYPE_LABELS = {
    "manual_transaction": "รายการ",
    "transfer": "โอนเงิน",
    "student_payment": "ชำระเงิน",
    "opening_balance": "ยอดยกมา",
    "adjustment": "ปรับปรุงยอด",
}

# [RECONCILE] ค่าคงที่สำหรับรายการกระทบยอด (Reconciliation) ระหว่างระบบ Legacy กับบัญชีคู่
# - reference_type 'adjustment' = รายการปรับปรุงยอด (สร้างโดย script reconcile_finance เท่านั้น)
# - equity ledger '3001' = ขาสะท้อน (mirror) ของส่วนต่าง → ไม่กระทบ Net Worth (คิดเฉพาะ asset)
#   และไม่ปน income statement (ต่างจาก '3000' ทุน-ยอดยกมา ของ opening_balance)
RECONCILE_REFERENCE_TYPE = "adjustment"
RECONCILE_EQUITY_CODE = "3001"
RECONCILE_EQUITY_NAME = "ปรับปรุงยอด (Reconciliation)"

# =====================================================================
# [EXPORT-ERP] ค่าคงที่กลางสำหรับ Excel Export ระดับ Enterprise
# =====================================================================
# รูปแบบตัวเลข: เงินใช้ #,##0.00 (ตามสเปค), % ใช้ 0.00"%" (เลข 50 → แสดง "50.00%")
MONEY_NUM_FMT = "#,##0.00"
PCT_NUM_FMT = '0.00"%"'

# ฉลากไทยของ account_type สำหรับงบการเงิน (GL / Trial Balance / Balance Sheet)
ACCOUNT_TYPE_LABELS = {
    "asset": "สินทรัพย์",
    "liability": "หนี้สิน",
    "equity": "ส่วนของเจ้าของ",
    "revenue": "รายได้",
    "expense": "ค่าใช้จ่าย",
}

# ฉลากไทยของ fee_collections.status
COLLECTION_STATUS_LABELS = {
    "active": "กำลังเก็บ",
    "closed": "ปิดแล้ว",
    "draft": "ร่าง",
}

# สี Tab Sheet — แยกหมวดรายงาน: Management (โทนน้ำเงิน) vs Accounting (โทนเขียวเข้ม/ม่วง)
MANAGEMENT_TAB_COLORS = ["1D4ED8", "2563EB", "0E9F6E", "DB2777"]
ACCOUNTING_TAB_COLORS = ["0F766E", "047857", "115E59", "4C1D95", "6D28D9", "4338CA"]


# [ROUTER] view ขนาดเล็ก ใช้ส่ง month/year/start_date/end_date แบบสลับกันไปมา
# ระหว่าง router กับ _resolve_export_period (เดิมรับ req object เดียว)
def _legacy_id_from_journal(metadata: dict, journal_uuid: str) -> int:
    """[DOUBLE-ENTRY] สังเคราะห์ TransactionResponse.id จาก journal.

    ระบบเดิม (frontend + revert_transaction) อ้างอิงธุรกรรมด้วย finance_transactions.id
    ซึ่ง journal เก็บไว้ใน metadata ('legacy_transaction_id' หรือ 'transfer_group_id').
    - ถ้ามี → คืนค่า int นั้น (revert ได้จริง)
    - ถ้าไม่มี (เช่น opening_balance) → คืนค่าลบที่ derived จาก UUID (คอลัมน์ไม่ซ้ำกัน,
      แต่ไม่สามารถใช้ revert ได้ — ตรงกับธรรมชาติของยอดยกมาที่ไม่ใช่ธุรกรรมรายการ)
    """
    if not isinstance(metadata, dict):
        metadata = {}
    for key in ("legacy_transaction_id", "transfer_group_id"):
        val = metadata.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    # fallback: ใช้ hash ของ UUID มาสร้าง id ลบ (กันหน้าจอ key ซ้ำ)
    try:
        return -(abs(hash(str(journal_uuid))) % (2**31 - 1) + 1)
    except Exception:
        return -1


def _naive_thai_dt(v) -> datetime:
    """[DOUBLE-ENTRY] ปรับค่าเวลาให้เป็น datetime "naive" ในโซน Asia/Bangkok ก่อนนำไป sort/เทียบ.

    ฝั่ง legacy เก็บ created_at เป็น naive TIMESTAMP (ไม่มี tz) ขณะที่ฝั่ง journal เก็บ
    transaction_date เป็น timestamptz (aware) → merge 2 ยุคต้อง normalize ให้เป็นแบบเดียวกัน
    ไม่งั้น Python เปรียบเทียบ naive กับ aware จะ TypeError.
    """
    if v is None:
        return datetime.min
    if isinstance(v, datetime):
        return v.astimezone(THAI_TZ).replace(tzinfo=None) if v.tzinfo is not None else v
    if isinstance(v, date):
        return datetime.combine(v, dtime(0))
    return datetime.min


# [CLAMP] ข้อความหมายเหตุสำหรับฟังก์ชันงบการเงิน (journal-native) เมื่อช่วงที่ขอแตะก่อนวันที่ตัด
_CLAMP_START_NOTE = ("หมายเหตุ: ช่วงก่อนวันที่ 2026-09-01 (ก่อนขึ้นระบบบัญชีคู่) ไม่มีข้อมูลในงบชุดนี้"
                     " — แสดงผลตั้งแต่วันที่ 2026-09-01 เป็นต้นไป")
_CLAMP_EMPTY_NOTE = ("หมายเหตุ: ช่วงเวลาที่ขออยู่ก่อนวันที่ 2026-09-01 (ก่อนขึ้นระบบบัญชีคู่)"
                     " — ไม่มีรายการในระบบบัญชีคู่")


def _clamp_to_cutoff(start: Optional[date], end: Optional[date]):
    """[CLAMP] จำกัดช่วงเวลาของงบการเงิน (ที่อ่าน journal ล้วน) ให้ไม่ต่ำกว่า CUTOFF_DATE.

    คืน (start2, end2, clamped, empty)
    - clamped: start ถูกดันขึ้นเป็น CUTOFF_DATE (มีส่วนก่อนเส้นถูกตัดออก)
    - empty  : ทั้งช่วงอยู่ก่อนเส้นตัด (หรือหลัง clamp แล้วว่าง) → ควรคืนค่าว่าง + note
    """
    clamped = False
    if start is not None and start < CUTOFF_DATE:
        start = CUTOFF_DATE
        clamped = True
    if end is not None and end < CUTOFF_DATE:
        return start, end, clamped, True
    if start is not None and end is not None and start > end:
        return start, end, clamped, True
    return start, end, clamped, False


# [ROUTER] view ขนาดเล็ก ใช้ส่ง month/year/start_date/end_date แบบสลับกันไปมา
# ระหว่าง router กับ _resolve_export_period (เดิมรับ req object เดียว)
class _ExportPeriodView:
    def __init__(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        self.month = month
        self.year = year
        self.start_date = start_date
        self.end_date = end_date


def _resolve_inclusive_period(month, year, start_date, end_date) -> tuple:
    """แปลง month/year/start_date/end_date → ขอบเขตวันที่แบบ "ครอบถึง" (inclusive).

    คืน (start_dt, end_dt, period_label) โดย start_dt/end_dt อาจเป็น None (ไม่จำกัด)
    - month+year → ทั้งเดือน (ต้องให้ครบคู่) — ห้ามคู่กับ start/end_date
    - start_date+end_date → ช่วงวันที่ (ครอบทั้งวัน; กัน start > end)
    - ให้ตัวเดียว (start_date หรือ end_date) → บังคับจากจุดนั้น
    - ไม่ระบุเลย → ทั้งหมด

    ใช้กับ query ที่กรองด้วย `DATE(คอลัมน์) >= start AND <= end` (เช่น journal export).
    """
    if (month is None) != (year is None):
        raise ValueError("ต้องระบุทั้ง month และ year พร้อมกัน หรือไม่ระบุทั้งคู่")
    if month is not None and year is not None:
        if start_date is not None or end_date is not None:
            raise ValueError("ไม่สามารถใช้ทั้ง month/year และ start_date/end_date พร้อมกันได้")
        start_dt = date(year, month, 1)
        if month == 12:
            end_dt = date(year, 12, 31)
        else:
            end_dt = date(year, month + 1, 1) - timedelta(days=1)
        return start_dt, end_dt, f"{year}-{month:02d}"

    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
    if start_date is not None and end_date is not None:
        return start_date, end_date, f"{start_date.isoformat()} ถึง {end_date.isoformat()}"
    if start_date is not None:
        return start_date, None, f"ตั้งแต่วันที่ {start_date.isoformat()}"
    if end_date is not None:
        return None, end_date, f"จนถึงวันที่ {end_date.isoformat()}"
    return None, None, "ทั้งหมด"

# 🎯 หมวดหมู่รายรับ/รายจ่ายค่าเริ่มต้น — seed ให้ทุกห้องทันทีที่สร้างห้อง
# (RoomManagementService.create_room นำไป INSERT ลง finance_categories)
DEFAULT_INCOME_CATEGORIES = [
    "📥 เก็บเงินห้องปกติ",
    "💸 เงินตกหล่น/เก็บได้",
    "🎉 รายได้จากกิจกรรม",
    "⚖️ ค่าปรับ",
    "♻️ เงินทอน/เงินคืน",
    "💰 เงินสนับสนุน",
    "♻️ ขายขยะขวดพลาสติก/กระดาษ",
    "📈 ดอกเบี้ยธนาคาร",
    "💖 ผู้ใหญ่ใจดี/สปอนเซอร์",
    "🛒 กำไรจากการขายของ",
    "📈 ปรับปรุงยอด (เงินเกิน)",
]

DEFAULT_EXPENSE_CATEGORIES = [
    "✏️ เครื่องเขียน/อุปกรณ์การเรียน",
    "🧹 อุปกรณ์ทำความสะอาด",
    "📄 ชีทเรียน/ถ่ายเอกสาร",
    "🔬 อุปกรณ์ทำโครงงาน",
    "🏆 กีฬาสี",
    "🙏 วันไหว้ครู",
    "🎄 กิจกรรมอื่นๆ",
    "💊 สวัสดิการเพื่อน/พยาบาล",
    "🎂 ของขวัญ/รางวัล",
    "💸 ค่าธรรมเนียม/อื่นๆ",
    "💻 เซิร์ฟเวอร์/โดเมน/ไอที",
    "⚙️ อุปกรณ์ IoT/อิเล็กทรอนิกส์",
    "🧪 สารเคมี/อุปกรณ์ทดลอง",
    "🖨️ ค่ารูปเล่ม/พอร์ตโฟลิโอ",
    "🧻 ของใช้สิ้นเปลือง",
    "💡 ซ่อมแซม/บำรุงรักษา",
    "🪴 ตกแต่งห้องเรียน",
    "⛺ ค่ายวิชาการ/ทัศนศึกษา",
    "☕ เลี้ยงรับรอง/ซัพพอร์ตครู",
    "📸 อัดรูป/ถ่ายภาพ",
    "📉 ปรับปรุงยอด (เงินขาด)",
]

# 🎯 บัญชีเงินสดค่าเริ่มต้น — seed ให้ทุกห้องทันทีที่สร้างห้อง
# (RoomManagementService.create_room นำไป INSERT ลง finance_accounts)
DEFAULT_FINANCE_ACCOUNTS = [
    "🪙 กระเป๋าเงินสด",
    "🏦 บัญชีธนาคารห้อง",
]

class FinanceService:
    @staticmethod
    def _extract_req_data(req) -> dict:
        if isinstance(req, dict):
            return req
        # 🚀 Pydantic v2 ต้องใช้ model_dump() (dict() ถูกลบใน v3) — ตรงตามกฎ CLAUDE.md
        if hasattr(req, 'model_dump') and callable(req.model_dump):
            return req.model_dump()
        if hasattr(req, 'dict') and callable(req.dict):
            return req.dict()
        try:
            return vars(req)
        except Exception:
            return {"raw_data": str(req)}

    @staticmethod
    def _finance_actor(req) -> str:
        n = getattr(req, "user_name", None)
        if n is not None and str(n).strip():
            return str(n).strip()[:200]
        return "—"

    @staticmethod
    async def _get_room_server_id(conn: asyncpg.Connection, room_id: int) -> Optional[int]:
        """ดึง server_id ของห้อง (ใช้ publish ไป Discord) — คืน None ถ้าห้องยังไม่ผูก Discord"""
        return await conn.fetchval(
            "SELECT server_id FROM rooms WHERE id = $1 AND deleted_at IS NULL",
            room_id,
        )

    # =====================================================================
    # [ROUTER] ตัวช่วยตัดสินใจว่าจะอ่านจากระบบเก่า (legacy) หรือบัญชีคู่ (v2)
    # =====================================================================
    @staticmethod
    def _period_start(
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
    ) -> Optional[date]:
        """จุดเริ่มต้นของช่วงเวลาที่ถูกขอ → ใช้ตัดสินใจ Route ไป legacy หรือ v2.

        - month/year: วันที่ 1 ของเดือน
        - start_date: ตัวมันเอง (หรือจุดเริ่มต้นของช่วง)
        - ไม่ระบุเลย: ใช้จุดเริ่มต้นของเดือนปัจจุบัน (ทำนองเดียวกับ legacy fallback)
        คืน None ไม่มีทางเกิดขึ้นจริง (เดือนปัจจุบันมีจุดเริ่มเสมอ) แต่ใส่เผื่อ type safety.
        """
        if month is not None and year is not None:
            return date(year, month, 1)
        if start_date is not None:
            return start_date
        # ไม่มีตัวกรองช่วงเวลา → default เป็นเดือนปัจจุบัน (ตรงกับ logic เดิมของ get_summary)
        today = datetime.now(THAI_TZ).date()
        return date(today.year, today.month, 1)

    # =====================================================================
    # [DUAL-WRITE] Helpers — Double-Entry (Strangler Fig Phase 3)
    # =====================================================================
    # หลักการ: ระหว่างการเปลี่ยนผ่าน ข้อมูลเก่า (insert ตรงจาก test หรือ seed เก่า)
    # อาจยังไม่มีแถวใน accounting_ledgers ดังนั้น helper นี้จะ "provision เอง"
    # จาก legacy row (finance_accounts / finance_categories) ถ้ายังไม่มี — แบบเดียวกับ
    # Phase 2 migration script (migrate_phase2_ledgers.py) แต่เป็น per-row อัตโนมัติ
    # เพื่อให้ระบบ Double-Entry กับ Legacy sync กันเสมอ โดยไม่พังตอน migration ยังไม่รัน
    @classmethod
    async def _resolve_asset_ledger(cls, conn: asyncpg.Connection, room_id: int, legacy_account_id: int) -> int:
        """คืน ledger_id ของบัญชีสินทรัพย์ที่ map กับ finance_accounts.
        ถ้ายังไม่มีแถว → provision เอง (รหัสบัญชี '1' || LPAD(id,4,'0') เหมือน Phase 2)
        และถ้า legacy row ไม่อยู่จริง → raise ValueError (กันข้อมูลไม่ตรงกัน)."""
        ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE legacy_account_id = $1", legacy_account_id
        )
        if ledger_id:
            return ledger_id
        acc = await conn.fetchrow(
            "SELECT account_name FROM finance_accounts WHERE id = $1 AND room_id = $2",
            legacy_account_id, room_id,
        )
        if not acc:
            raise ValueError(f"[DUAL-WRITE] ไม่พบ ledger mapping สำหรับบัญชีสินทรัพย์ legacy_account_id={legacy_account_id}")
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_account_id, description)
               VALUES ($1, $2, $3, 'asset', $4, 'Auto-provisioned by dual-write')
               RETURNING id""",
            room_id, f"1{legacy_account_id:04d}", acc["account_name"], legacy_account_id,
        )

    @classmethod
    async def _resolve_category_ledger(cls, conn: asyncpg.Connection, room_id: int, legacy_category_id: int, category_type: Optional[str] = None) -> int:
        """คืน ledger_id ของหมวดหมู่ revenue/expense ที่ map กับ finance_categories.
        category_type (income/expense) ใช้ตอน provision ถ้า caller ไม่รู้ (income → 'revenue' 4xxxx, expense → 5xxxx)."""
        ledger_id = await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE legacy_category_id = $1", legacy_category_id
        )
        if ledger_id:
            return ledger_id
        cat = await conn.fetchrow(
            "SELECT category_name, category_type FROM finance_categories WHERE id = $1 AND room_id = $2",
            legacy_category_id, room_id,
        )
        if not cat:
            raise ValueError(f"[DUAL-WRITE] ไม่พบ ledger mapping สำหรับหมวดหมู่ legacy_category_id={legacy_category_id}")
        effective_type = category_type or cat["category_type"]
        if effective_type == "income":
            account_type, code = "revenue", f"4{legacy_category_id:04d}"
        else:
            account_type, code = "expense", f"5{legacy_category_id:04d}"
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_category_id, description)
               VALUES ($1, $2, $3, $4, $5, 'Auto-provisioned by dual-write')
               RETURNING id""",
            room_id, code, cat["category_name"], account_type, legacy_category_id,
        )

    @classmethod
    async def _find_revenue_ledger_by_name(cls, conn: asyncpg.Connection, room_id: int, legacy_category_id: Optional[int] = None, account_name: Optional[str] = None) -> Optional[int]:
        """ค้นหา revenue ledger สำหรับเครดิตขาของ confirm_payment.
        ลำดับการค้นหา: (1) legacy_category_id ที่ mapping ตรง ๆ, (2) ชื่อบัญชี (เช่น '📥 เก็บเงินห้องปกติ'),
        (3) revenue ตัวแรกสุดของห้อง (fallback ยืดหยุ่น). คืน None ถ้าไม่มี revenue เลย (เช่น ห้องที่ seed ยังไม่ครบ)."""
        if legacy_category_id is not None:
            ledger_id = await conn.fetchval("SELECT id FROM accounting_ledgers WHERE legacy_category_id = $1", legacy_category_id)
            if ledger_id:
                return ledger_id
        if account_name:
            ledger_id = await conn.fetchval(
                "SELECT id FROM accounting_ledgers WHERE room_id = $1 AND account_name = $2 AND account_type = 'revenue'",
                room_id, account_name,
            )
            if ledger_id:
                return ledger_id
        return await conn.fetchval(
            "SELECT id FROM accounting_ledgers WHERE room_id = $1 AND account_type = 'revenue' ORDER BY id LIMIT 1",
            room_id,
        )

    @classmethod
    async def _find_or_create_default_income_category(cls, conn: asyncpg.Connection, room_id: int) -> Optional[int]:
        """[FIX A] หา/สร้าง finance_categories รายได้ค่าเริ่มต้น '📥 เก็บเงินห้องปกติ' ให้ห้อง.

        กันกรณีห้องเก่าที่ seed หมวดหมู่ไม่ครบ: ถ้าสร้างไม่เจอตอน confirm_payment ระบบเดิมจะ
        ข้าม dual-write (pass) → เงินเข้า legacy แต่ journal ไม่มี → ยอด 2 ระบบเบี้ยว.
        สร้างหมวดนี้ + ให้ `_resolve_category_ledger` สร้าง revenue ledger ตามมา
        → ทำให้ทุก path เจอหมวด+ledger ตัวเดียวกัน (find-or-create idempotent).
        """
        cat_id = await conn.fetchval(
            """SELECT id FROM finance_categories
               WHERE room_id = $1 AND category_name = $2 AND category_type = 'income'
               ORDER BY id LIMIT 1""",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )
        if cat_id:
            return cat_id
        # 🛡️ INSERT ... WHERE NOT EXISTS กัน race (2 request พร้อมกันสร้างหมวดซ้ำ)
        cat_id = await conn.fetchval(
            """INSERT INTO finance_categories (room_id, category_name, category_type)
               SELECT $1, $2, 'income'
               WHERE NOT EXISTS (
                   SELECT 1 FROM finance_categories
                   WHERE room_id = $1 AND category_name = $2 AND category_type = 'income'
               )
               RETURNING id""",
            room_id, DEFAULT_INCOME_CATEGORIES[0],
        )
        if cat_id is None:
            # อีก request สร้างไปแล้วระหว่าง SELECT กับ INSERT → ดึงกลับมา
            return await conn.fetchval(
                """SELECT id FROM finance_categories
                   WHERE room_id = $1 AND category_name = $2 AND category_type = 'income'
                   ORDER BY id LIMIT 1""",
                room_id, DEFAULT_INCOME_CATEGORIES[0],
            )
        return cat_id

    @classmethod
    async def _insert_journal_entry(
        cls, conn: asyncpg.Connection, room_id: int,
        *,
        reference_type: str, reference_id: Optional[str] = None,
        description: str, recorded_by: Optional[str] = None, slip_image_url: Optional[str] = None,
        metadata: Optional[dict] = None,
        lines: List[dict],  # [{"ledger_id": int, "debit": float, "credit": float}, ...]
    ) -> str:
        """[DUAL-WRITE] สร้าง journal_entries (หัวบิล) + journal_lines (เดบิต/เครดิต) ใน transaction เดียวกับ legacy.
        คืน UUID ของ journal entry (สำหรับ revert ตาม reference ภายหลัง).
        💡 เงินทุกจำนวน cast float() ก่อน (กฎ CLAUDE.md: NUMERIC ต้อง cast ก่อน arithmetic)"""
        entry_id = await conn.fetchval(
            """INSERT INTO journal_entries (room_id, reference_type, reference_id, description, slip_image_url, recorded_by, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
               RETURNING id""",
            room_id, reference_type, reference_id, description, slip_image_url, recorded_by,
            json.dumps(metadata or {}, ensure_ascii=False),
        )
        for line in lines:
            debit = line.get("debit", 0) or 0
            credit = line.get("credit", 0) or 0
            await conn.execute(
                """INSERT INTO journal_lines (journal_entry_id, ledger_id, debit, credit, line_description)
                   VALUES ($1, $2, $3, $4, $5)""",
                entry_id, line["ledger_id"], float(debit), float(credit), line.get("line_description"),
            )
        return entry_id

    # =====================================================================
    # [RECONCILE] กระทบยอดระหว่างระบบ Legacy (finance_accounts.balance) กับบัญชีคู่
    # =====================================================================
    @classmethod
    async def _scan_account_diffs(
        cls, conn: asyncpg.Connection, *, room_id: int, threshold: float = 0.01
    ) -> List[dict]:
        """[RECONCILE] อ่านล้วน ๆ: เปรียบเทียบ finance_accounts.balance (ระบบเดิม)
        กับยอดสุทธิ asset-ledger ของบัญชีนั้นในบัญชีคู่ (SUM(debit−credit) เฉพาะ journal
        ที่ไม่ void / ไม่ลบ — เงื่อนไขเดียวกับ _get_summary_v2).

        คืน list: {account_id, account_name, legacy_balance, ledger_net, ledger_id,
                   diff, amount, action} โดย action ∈ 'dr_asset'|'cr_asset'|'skip'
        (ledger_id เป็น None ถ้ายังไม่มี asset ledger ของบัญชี → ถือ net = 0)"""
        rows = await conn.fetch(
            """SELECT
                    FA.id AS account_id,
                    FA.account_name AS account_name,
                    FA.balance AS legacy_balance,
                    AL.id AS ledger_id,
                    COALESCE(NET.net, 0) AS ledger_net
                FROM finance_accounts FA
                LEFT JOIN LATERAL (
                    SELECT id FROM accounting_ledgers
                    WHERE legacy_account_id = FA.id
                      AND room_id = FA.room_id
                      AND account_type = 'asset'
                    ORDER BY id
                    LIMIT 1
                ) AL ON TRUE
                LEFT JOIN LATERAL (
                    SELECT SUM(L.debit - L.credit) AS net
                    FROM journal_lines L
                    JOIN journal_entries JE ON L.journal_entry_id = JE.id
                    WHERE L.ledger_id = AL.id
                      AND JE.room_id = FA.room_id
                      AND JE.deleted_at IS NULL
                      AND JE.status <> 'voided'
                ) NET ON TRUE
                WHERE FA.room_id = $1
                  AND FA.deleted_at IS NULL
                ORDER BY FA.id""",
            room_id,
        )
        result = []
        for r in rows:
            legacy = float(r["legacy_balance"])
            net = float(r["ledger_net"])
            diff = round(legacy - net, 4)
            if abs(diff) < threshold:
                action = "skip"
                amount = 0.0
            else:
                action = "dr_asset" if diff > 0 else "cr_asset"
                amount = abs(diff)
            result.append({
                "account_id": r["account_id"],
                "account_name": r["account_name"],
                "legacy_balance": legacy,
                "ledger_net": net,
                "ledger_id": r["ledger_id"],
                "diff": diff,
                "amount": amount,
                "action": action,
            })
        return result

    @classmethod
    async def _resolve_reconcile_equity_ledger(cls, conn: asyncpg.Connection, *, room_id: int) -> int:
        """[RECONCILE] หา/สร้าง ledger equity '3001' (ปรับปรุงยอด) ให้ห้อง — ใช้เป็นขา
        สะท้อน (mirror) ของรายการปรับปรุง เพื่อให้ Dr = Cr โดยไม่แตะ Net Worth (asset-only)
        และไม่ปนรายได้/รายจ่ายของงวด"""
        ledger_id = await conn.fetchval(
            """SELECT id FROM accounting_ledgers
               WHERE room_id = $1 AND account_code = $2 AND account_type = 'equity'
               ORDER BY id LIMIT 1""",
            room_id, RECONCILE_EQUITY_CODE,
        )
        if ledger_id:
            return ledger_id
        return await conn.fetchval(
            """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, description)
               VALUES ($1, $2, $3, 'equity', $4)
               RETURNING id""",
            room_id, RECONCILE_EQUITY_CODE, RECONCILE_EQUITY_NAME,
            "บัญชีพักปรับปรุงผลต่างระหว่างยอด Legacy กับบัญชีคู่ (สร้างอัตโนมัติโดย reconcile_finance)",
        )

    @classmethod
    async def reconcile_balances(
        cls,
        pool: asyncpg.Pool,
        *,
        room_id: Optional[int] = None,
        server_id: Optional[int] = None,
        apply: bool = False,
        threshold: float = 0.01,
    ) -> dict:
        """[RECONCILE] กระทบยอดเงินของห้องเดียว: เทียบ finance_accounts.balance (ระบบเดิม
        = แหล่งความจริง) กับยอดสุทธิ asset-ledger ในบัญชีคู่ของแต่ละบัญชี.

        - dry-run (default): แค่รายงานผลต่าง ไม่เขียนอะไร
        - apply=True: ใน transaction เดียว สร้าง asset ledger ที่ขาด + equity '3001' (ถ้ายังไม่มี)
          แล้ว insert journal_entries reference_type='adjustment' 1 ใบต่อบัญชีที่ต่างกัน
          (asset Dr / equity Cr เมื่อ legacy มากกว่า, asset Cr / equity Dr เมื่อ ledger เกิน)
          ให้ยอดบัญชีคู่กลับมาเท่ากับ Legacy เป๊ะ ๆ

        ⚠️ Ops tool: ไม่ล็อกแถวระหว่าง apply → ควรวิ่งช่วงที่ไม่มีรายการสด
        คืน dict รายงาน (ตัวเลขเป็น float, journal_entry_id เป็น str)
        """
        async with pool.acquire() as conn:
            resolved_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            async with conn.transaction():
                rows = await cls._scan_account_diffs(conn, room_id=resolved_room_id, threshold=threshold)
                mismatches = [r for r in rows if r["action"] != "skip"]
                room_name = await conn.fetchval(
                    "SELECT room_name FROM rooms WHERE id = $1", resolved_room_id
                )
                report = {
                    "room_id": resolved_room_id,
                    "room_name": room_name,
                    "apply": apply,
                    "threshold": threshold,
                    "checked_accounts": len(rows),
                    "adjustments_created": 0,
                    "total_adjustment_amount": 0.0,
                    "mismatches": mismatches,
                }
                if apply and mismatches:
                    equity_ledger_id = None
                    for m in mismatches:
                        asset_ledger_id = m["ledger_id"]
                        if asset_ledger_id is None:
                            asset_ledger_id = await cls._resolve_asset_ledger(
                                conn, resolved_room_id, m["account_id"]
                            )
                        if equity_ledger_id is None:
                            equity_ledger_id = await cls._resolve_reconcile_equity_ledger(
                                conn, room_id=resolved_room_id
                            )
                        amount = float(m["amount"])
                        if m["action"] == "dr_asset":
                            lines = [
                                {"ledger_id": asset_ledger_id, "debit": amount, "credit": 0,
                                 "line_description": f"ปรับปรุงยอดบัญชีให้ตรงกับระบบเดิม (เดิมขาด {amount:.2f} บาท)"},
                                {"ledger_id": equity_ledger_id, "debit": 0, "credit": amount,
                                 "line_description": "ปรับปรุงยอด (Reconciliation) ฝั่งทุน"},
                            ]
                        else:  # cr_asset
                            lines = [
                                {"ledger_id": asset_ledger_id, "debit": 0, "credit": amount,
                                 "line_description": f"ปรับปรุงยอดบัญชีให้ตรงกับระบบเดิม (เดิมเกิน {amount:.2f} บาท)"},
                                {"ledger_id": equity_ledger_id, "debit": amount, "credit": 0,
                                 "line_description": "ปรับปรุงยอด (Reconciliation) ฝั่งทุน"},
                            ]
                        entry_id = await cls._insert_journal_entry(
                            conn, resolved_room_id,
                            reference_type=RECONCILE_REFERENCE_TYPE,
                            description=f"ปรับปรุงยอดคงเหลือให้ตรงกับระบบเดิม: {m['account_name']} (Reconciliation)",
                            recorded_by="SYSTEM",
                            metadata={
                                "adjustment_type": "reconcile",
                                "finance_account_id": m["account_id"],
                                "legacy_balance": float(m["legacy_balance"]),
                                "ledger_net_before": float(m["ledger_net"]),
                                "direction": "debit_asset" if m["action"] == "dr_asset" else "credit_asset",
                            },
                            lines=lines,
                        )
                        m["journal_entry_id"] = str(entry_id)
                        report["adjustments_created"] += 1
                        report["total_adjustment_amount"] = round(report["total_adjustment_amount"] + amount, 4)
                    if report["adjustments_created"]:
                        await service_logger.log(
                            conn=conn, action="RECONCILE", actor_identifier="SYSTEM",
                            client_source="script", room_id=resolved_room_id,
                            entity_type="FINANCE_RECONCILE", entity_id=str(resolved_room_id),
                            status="success",
                            new_values={
                                "adjustments_created": report["adjustments_created"],
                                "total_amount": report["total_adjustment_amount"],
                            },
                            endpoint_or_command="FinanceService.reconcile_balances",
                        )
            return report

    @staticmethod
    async def resolve_room_id(conn: asyncpg.Connection, server_id: Optional[int] = None, room_id: Optional[int] = None) -> int:
        if room_id:
            if not await conn.fetchval("SELECT 1 FROM rooms WHERE id = $1 AND deleted_at IS NULL", room_id):
                raise RoomNotFoundError("ไม่พบห้องเรียนนี้")
            return room_id
        if server_id:
            r_id = await conn.fetchval("SELECT id FROM rooms WHERE server_id = $1 AND deleted_at IS NULL", server_id)
            if not r_id: 
                raise RoomNotFoundError(f"ไม่พบห้องสำหรับ server {server_id}")
            return r_id
        raise ValueError("ต้องระบุ server_id หรือ room_id")

    @classmethod
    async def get_active_students(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("""
                    SELECT S.id, S.student_no, U.first_name, U.last_name, U.nickname,
                           U.first_name_en, U.last_name_en, U.nickname_en
                    FROM students S
                    LEFT JOIN users U ON S.user_id = U.id
                    WHERE S.room_id = $1 AND S.status = 'active' AND S.deleted_at IS NULL
                    ORDER BY S.student_no ASC
                """, target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="success",
                    endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_LIST", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_active_students", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def create_account(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    # [DUAL-WRITE] ดึง id ของแถว legacy เพื่อ map ลง accounting_ledgers
                    new_account_id = await conn.fetchval(
                        "INSERT INTO finance_accounts (room_id, account_name, balance) VALUES ($1, $2, $3) RETURNING id",
                        target_room_id, req.account_name, req.initial_balance
                    )

                    # [DUAL-WRITE] สร้าง ledger ฝั่ง Double-Entry (asset 1xxxx) ภายใน transaction เดียวกัน
                    # รหัสบัญชี '1' || LPAD(id, 4, '0') — ตรงกับ migrate_phase2_ledgers.py
                    await conn.execute(
                        """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_account_id, description)
                           VALUES ($1, $2, $3, 'asset', $4, 'Created via dual-write (create_account)')""",
                        target_room_id, f"1{new_account_id:04d}", req.account_name, new_account_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": f"สร้างบัญชี {req.account_name} สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_accounts(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("SELECT id, account_name, balance FROM finance_accounts WHERE room_id = $1 ORDER BY id", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_ACCOUNT", status="success",
                    endpoint_or_command="FinanceService.get_accounts", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_accounts", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def add_transaction(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    current_balance = await conn.fetchval(
                        "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        req.account_id, target_room_id
                    )
                    if current_balance is None: raise ValueError("ไม่พบบัญชีนี้ในห้องของคุณ")
                    # 💡 balance กลับมาจาก DECIMAL เป็น Decimal (มี binary noise จาก float ที่เก็บเข้า)
                    # ต้อง cast float() ทั้งสองฝั่งก่อนเปรียบเทียบ (ตาม CLAUDE.md: cast float ก่อนเสมอ)
                    if req.transaction_type == 'expense' and float(current_balance) < float(req.amount):
                        raise ValueError(f"เงินไม่พอ! ยอดคงเหลือคือ {current_balance} บาท")

                    cat = await conn.fetchrow("SELECT room_id, category_type FROM finance_categories WHERE id = $1 AND deleted_at IS NULL", req.category_id)
                    if not cat or cat['room_id'] != target_room_id: raise ValueError("หมวดหมู่นี้ไม่มีอยู่ หรือไม่ใช่ของห้องคุณ!")
                    if cat['category_type'] != req.transaction_type:
                        raise ValueError(f"ประเภทหมวดหมู่ ({cat['category_type']}) ไม่ตรงกับประเภทการบันทึก ({req.transaction_type})!")

                    # [DUAL-WRITE] ดึง id ของ legacy transaction เพื่อเก็บลง journal metadata (สำหรับ revert)
                    new_tx_id = await conn.fetchval(
                        """INSERT INTO finance_transactions
                           (room_id, account_id, category_id, amount, description, transaction_type, slip_image_url, recorded_by)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
                        target_room_id, req.account_id, req.category_id, req.amount,
                        req.description, req.transaction_type, req.slip_image_url, req.user_name
                    )

                    if req.transaction_type == 'income':
                        await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.account_id)
                    elif req.transaction_type == 'expense':
                        await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.account_id)

                    # [DUAL-WRITE] เขียนฝั่ง Double-Entry (หัวบิล + 2 บรรทัด เดบิต/เครดิต) ใน transaction เดียวกัน
                    asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, req.account_id)
                    category_ledger_id = await cls._resolve_category_ledger(conn, target_room_id, req.category_id, req.transaction_type)
                    if req.transaction_type == 'income':
                        lines = [
                            {"ledger_id": asset_ledger_id, "debit": req.amount, "credit": 0, "line_description": f"รับเงินเข้าบัญชี: {req.account_id}"},
                            {"ledger_id": category_ledger_id, "debit": 0, "credit": req.amount, "line_description": f"รายได้: {req.description}"},
                        ]
                    else:  # expense
                        lines = [
                            {"ledger_id": category_ledger_id, "debit": req.amount, "credit": 0, "line_description": f"ค่าใช้จ่าย: {req.description}"},
                            {"ledger_id": asset_ledger_id, "debit": 0, "credit": req.amount, "line_description": f"เงินออกจากบัญชี: {req.account_id}"},
                        ]
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type="manual_transaction",
                        reference_id=str(new_tx_id),
                        description=req.description,
                        slip_image_url=req.slip_image_url,
                        recorded_by=req.user_name,
                        metadata={"legacy_transaction_id": new_tx_id},
                        lines=lines,
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.add_transaction", execution_time_ms=exec_time
                    )
                    # 📢 แจ้งเตือน Discord: มีรายรับ/รายจ่ายใหม่ (ไม่ @everyone — แค่โชว์ความโปร่งใส)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id:
                await ActionService.notify_new_finance(
                    server_id=room_server_id,
                    txn_type=req.transaction_type,
                    amount=float(req.amount),
                    description=req.description,
                    user_name=req.user_name,
                )
            return {"status": "success", "message": "บันทึกรายการสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.add_transaction", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def transfer_money(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        if req.from_account_id == req.to_account_id: raise ValueError("โอนเงินเข้าบัญชีเดิมไม่ได้!")

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    current_balance = await conn.fetchval(
                        "SELECT balance FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        req.from_account_id, target_room_id
                    )
                    if current_balance is None: raise RoomNotFoundError("ไม่พบบัญชีต้นทาง")
                    # Decimal vs float — cast float() ทั้งสองฝั่ง (ลบ binary noise) ก่อนเทียบ
                    if float(current_balance) < float(req.amount): raise ValueError("ยอดเงินในบัญชีต้นทางไม่เพียงพอ!")

                    # 🛡️ กันการโอนเงินข้ามห้อง (cross-room leak): ต้องเช็คบัญชีปลายทางด้วย
                    if not await conn.fetchval(
                        "SELECT 1 FROM finance_accounts WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL",
                        req.to_account_id, target_room_id
                    ):
                        raise RoomNotFoundError("ไม่พบบัญชีปลายทาง")

                    group_id = await conn.fetchval("SELECT nextval('transfer_group_id_seq')")
                    
                    await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", req.amount, req.from_account_id)
                    # [DUAL-WRITE] ดึง id ของ legacy transaction ขาออก เพื่อเก็บใน journal metadata
                    tx_from_id = await conn.fetchval(
                        """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by)
                           VALUES ($1, $2, $3, $4, 'expense', $5, $6) RETURNING id""",
                        target_room_id, req.from_account_id, req.amount, f"โอนออก: {req.description}", group_id, req.user_name
                    )

                    await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", req.amount, req.to_account_id)
                    # [DUAL-WRITE] ดึง id ของ legacy transaction ขาเข้า เพื่อเก็บใน journal metadata
                    tx_to_id = await conn.fetchval(
                        """INSERT INTO finance_transactions (room_id, account_id, amount, description, transaction_type, transfer_group_id, recorded_by)
                           VALUES ($1, $2, $3, $4, 'income', $5, $6) RETURNING id""",
                        target_room_id, req.to_account_id, req.amount, f"รับโอน: {req.description}", group_id, req.user_name
                    )

                    # [DUAL-WRITE] เขียนฝั่ง Double-Entry: ย้ายเงินระหว่างบัญชีสินทรัพย์ (Dr ปลายทาง / Cr ต้นทาง)
                    # เก็บ transfer_group_id + legacy_transaction_id ทั้งสองข้างไว้ใน metadata → revert ยกเลิกได้ทั้งกลุ่ม
                    ledger_id_from = await cls._resolve_asset_ledger(conn, target_room_id, req.from_account_id)
                    ledger_id_to = await cls._resolve_asset_ledger(conn, target_room_id, req.to_account_id)
                    await cls._insert_journal_entry(
                        conn, target_room_id,
                        reference_type="transfer",
                        reference_id=str(group_id),
                        description=req.description or "Transfer",
                        recorded_by=req.user_name,
                        metadata={
                            "transfer_group_id": group_id,
                            "legacy_transaction_id": tx_from_id,
                            "legacy_transaction_ids": [tx_from_id, tx_to_id],
                        },
                        lines=[
                            {"ledger_id": ledger_id_to, "debit": req.amount, "credit": 0, "line_description": f"รับโอนเข้าบัญชี: {req.to_account_id}"},
                            {"ledger_id": ledger_id_from, "debit": 0, "credit": req.amount, "line_description": f"โอนออกจากบัญชี: {req.from_account_id}"},
                        ],
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSFER", entity_id=str(group_id), status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.transfer_money", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "โอนเงินสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSFER", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.transfer_money", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    # =====================================================================
    # [ROUTER] get_transactions — เลือกอ่านจาก legacy หรือ Double-Entry ตามช่วงเวลา
    # =====================================================================
    @classmethod
    async def get_transactions(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)

                # [ROUTER] แบ่งอ่านตามยุคของช่วงที่ขอ (CUTOFF_DATE = 2026-09-01):
                #   - ทั้งช่วงก่อนเส้นตัด        → legacy (finance_transactions)
                #   - เริ่มที่/หลังเส้นตัด        → บัญชีคู่ (journal) 100%
                #   - "ทั้งหมด" (ไม่กรอง) / คร่อมเส้น → MERGE: legacy < 1 ก.ย. + journal >= 1 ก.ย.
                # (เหตุผล: หลังวันที่ตัด ข้อมูลมีใน journal เป็นหลัก — อ่าน legacy เฉพาะข้อมูลเก่า)
                if start_date is None and end_date is None:
                    return await cls._get_transactions_merged(
                        conn=conn, room_id=target_room_id,
                        limit=limit, offset=offset,
                        start_date=start_date, end_date=end_date,
                        account_id=account_id, category_id=category_id,
                        transaction_type=transaction_type,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )

                period_start = start_date or date.min
                if period_start >= CUTOFF_DATE:
                    # [ROUTER] ขอข้อมูลหลังวันที่ตัด → อ่านจาก journal_entries/journal_lines
                    return await cls._get_transactions_v2(
                        conn=conn, room_id=target_room_id,
                        limit=limit, offset=offset,
                        start_date=start_date, end_date=end_date,
                        account_id=account_id, category_id=category_id,
                        transaction_type=transaction_type,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )
                if end_date is not None and end_date < CUTOFF_DATE:
                    # [ROUTER] ทั้งช่วงก่อนวันที่ตัด → อ่านจากตารางเก่า
                    return await cls._get_transactions_legacy(
                        conn=conn, room_id=target_room_id,
                        limit=limit, offset=offset,
                        start_date=start_date, end_date=end_date,
                        account_id=account_id, category_id=category_id,
                        transaction_type=transaction_type,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )
                # [ROUTER] ช่วงคร่อมเส้นตัด / ระบุแค่ start_date (ปลายเปิด) → MERGE 2 ยุค
                return await cls._get_transactions_merged(
                    conn=conn, room_id=target_room_id,
                    limit=limit, offset=offset,
                    start_date=start_date, end_date=end_date,
                    account_id=account_id, category_id=category_id,
                    transaction_type=transaction_type,
                    client_source=client_source, actor_identifier=actor_identifier,
                    start_time=start_time,
                )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _fetch_legacy_items(
        cls, conn: asyncpg.Connection, *, room_id: int,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        max_date_cap: Optional[date] = None,
    ) -> List[dict]:
        """[ROUTER-LEGACY] ดึงแถว finance_transactions ของห้องแบบไม่จำกัดหน้า (LIMIT) —
        ใช้ร่วมกันโดย legacy worker (แล้ว slice เอง) และ merge (บังคับ cap ก่อนเส้นตัด).
        max_date_cap: ถ้าตั้ง → บังคับ DATE(T.created_at) <= cap (merge ใช้ cap = วันก่อน CUTOFF_DATE)"""
        where_clause = "WHERE T.room_id = $1 AND T.deleted_at IS NULL"
        params = [room_id]
        param_idx = 2

        if start_date:
            where_clause += f" AND DATE(T.created_at) >= ${param_idx}"
            params.append(start_date); param_idx += 1
        effective_end = end_date
        if max_date_cap is not None and (effective_end is None or max_date_cap < effective_end):
            effective_end = max_date_cap
        if effective_end is not None:
            where_clause += f" AND DATE(T.created_at) <= ${param_idx}"
            params.append(effective_end); param_idx += 1
        if account_id:
            where_clause += f" AND T.account_id = ${param_idx}"
            params.append(account_id); param_idx += 1
        if category_id:
            where_clause += f" AND T.category_id = ${param_idx}"
            params.append(category_id); param_idx += 1
        if transaction_type:
            where_clause += f" AND T.transaction_type = ${param_idx}"
            params.append(transaction_type); param_idx += 1

        rows = await conn.fetch(f"""
            SELECT
                T.id, T.amount, T.description, T.transaction_type, T.created_at,
                T.slip_image_url, T.recorded_by, T.transfer_group_id,
                A.account_name, C.category_name
            FROM finance_transactions T
            LEFT JOIN finance_accounts A ON T.account_id = A.id
            LEFT JOIN finance_categories C ON T.category_id = C.id
            {where_clause}
            ORDER BY T.created_at DESC, T.id DESC
        """, *params)
        return [dict(row) for row in rows]

    @classmethod
    async def _get_transactions_legacy(
        cls, conn: asyncpg.Connection, *, room_id: int,
        limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """[ROUTER-LEGACY] ประวัติฝั่ง Single-Entry — ดึงทั้งชุดแล้ว slice ที่ฝั่ง Python
        (volume ห้องเรียนเล็ก; ทำให้ legacy/v2/merge ใช้ pagination แบบเดียวกัน)"""
        items = await cls._fetch_legacy_items(
            conn=conn, room_id=room_id,
            start_date=start_date, end_date=end_date,
            account_id=account_id, category_id=category_id,
            transaction_type=transaction_type,
        )
        result = {"total_count": len(items), "items": items[offset:offset + limit]}

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
            )
        return result

    # =====================================================================
    # [DOUBLE-ENTRY] _get_transactions_v2 — แปลง Dr/Cr จาก journal กลับเป็น
    # schema เดิมที่ frontend ใช้ (TransactionResponse) โดยไม่ให้ frontend แก้ไข
    # =====================================================================
    @classmethod
    async def _get_transactions_v2(
        cls, conn: asyncpg.Connection, *, room_id: int,
        limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """อ่านประวัติจากระบบบัญชีคู่ (journal_entries + journal_lines) แล้วจัดรูป
        ให้เหมือน legacy (TransactionResponse) เพื่อ frontend ไม่ต้องแก้เลย.

        หลักการจัดประเภท (ตามสเปค Phase 4):
        - income  : สินทรัพย์ เดบิต>0  + บัญชีรายได้ เครดิต>0  (รับเงินเข้า)
        - expense : สินทรัพย์ เครดิต>0 + บัญชีค่าใช้จ่าย เดบิต>0 (เงินออก)
        - transfer: สินทรัพย์ 2 บัญชี (ฝั่งหนึ่ง เดบิต>0 / อีกฝั่ง เครดิต>0)
        - opening_balance: แสดงเป็น income (เงินเข้า Asset) — ยอด = เดบิตฝั่ง Asset
        """
        where_cond, params = ["JE.room_id = $1 AND JE.deleted_at IS NULL"], [room_id]
        idx = 2
        if start_date:
            where_cond.append(f"DATE(JE.transaction_date) >= ${idx}"); params.append(start_date); idx += 1
        if end_date:
            where_cond.append(f"DATE(JE.transaction_date) <= ${idx}"); params.append(end_date); idx += 1
        if account_id:
            # [DOUBLE-ENTRY] กรองด้วยบัญชีสินทรัพย์: journal ใดก็ตามที่ asset ledger นี้มีบทบาท (Dr หรือ Cr)
            where_cond.append(f"""
                EXISTS (
                    SELECT 1 FROM journal_lines JLx
                    JOIN accounting_ledgers ALx ON JLx.ledger_id = ALx.id
                    WHERE JLx.journal_entry_id = JE.id AND ALx.room_id = $1
                      AND ALx.legacy_account_id = ${idx} AND (JLx.debit > 0 OR JLx.credit > 0)
                )""")
            params.append(account_id); idx += 1
        if category_id:
            # [DOUBLE-ENTRY] กรองด้วยหมวดหมู่ (revenue/expense): journal ที่ ledger นั้นมีบทบาท
            where_cond.append(f"""
                EXISTS (
                    SELECT 1 FROM journal_lines JLx2
                    JOIN accounting_ledgers ALx2 ON JLx2.ledger_id = ALx2.id
                    WHERE JLx2.journal_entry_id = JE.id AND ALx2.room_id = $1
                      AND ALx2.legacy_category_id = ${idx} AND (JLx2.debit > 0 OR JLx2.credit > 0)
                )""")
            params.append(category_id); idx += 1

        # [DOUBLE-ENTRY] ยกทุกบรรทัดของ journal ที่ผ่าน filter ขึ้นมา (หลายบรรทัดต่อ 1 บิล)
        # แล้วจัดประเภทที่ฝั่ง Python (อ่านง่ายกว่า SQL หลายชั้น)
        data_sql = f"""
            SELECT
                JE.id AS journal_entry_id,
                JE.reference_type, JE.reference_id,
                JE.description AS entry_description,
                JE.transaction_date, JE.recorded_by,
                JE.slip_image_url, JE.metadata,
                L.id AS line_id, L.debit, L.credit, L.line_description,
                AL.id AS ledger_id, AL.account_code, AL.account_name, AL.account_type,
                AL.legacy_account_id, AL.legacy_category_id
            FROM journal_entries JE
            JOIN journal_lines L ON L.journal_entry_id = JE.id
            JOIN accounting_ledgers AL ON L.ledger_id = AL.id
            WHERE {' AND '.join(where_cond)}
              AND JE.status <> 'voided'
            ORDER BY JE.transaction_date DESC, JE.id DESC
        """
        rows = await conn.fetch(data_sql, *params)

        # [DOUBLE-ENTRY] กลุ่มบรรทัดตามหัวบิล
        entries: Dict[str, dict] = {}
        for r in rows:
            entry_id = str(r["journal_entry_id"])
            if entry_id not in entries:
                entries[entry_id] = {
                    "journal_entry_id": entry_id,
                    "reference_type": r["reference_type"],
                    "reference_id": r["reference_id"],
                    "description": r["entry_description"],
                    "transaction_date": r["transaction_date"],
                    "recorded_by": r["recorded_by"],
                    "slip_image_url": r["slip_image_url"],
                    "metadata": r["metadata"] or {},
                    "lines": [],
                }
            entries[entry_id]["lines"].append(r)

        # [DOUBLE-ENTRY] แปลงแต่ละบิล → TransactionResponse
        # 📌 หมายเหตุเรื่อง id: TransactionResponse.id เป็น int และ frontend ใช้เรียก
        # revert_transaction (ซึ่งค้นจาก finance_transactions.id) → สังเคราะห์จาก legacy
        # transaction id ใน metadata; ถ้าไม่มี (เช่น opening_balance) ใช้ค่าลบจาก UUID
        # เพื่อให้คอลัมน์มีค่าไม่ซ้ำกัน (เป็น id ที่ "ไม่ใช้ได้จริง" กับ revert)
        items: List[dict] = []
        for entry in entries.values():
            txn = cls._classify_journal_entry(entry, transaction_type)
            if txn is None:
                continue  # ถูกกรองด้วย transaction_type ด้านบนแล้ว
            items.append(txn)

        # [DOUBLE-ENTRY] จำลอง pagination ฝั่ง application (ชุดข้อมูลนี้เล็ก —
        # ต่อบิลมีแค่ 2-3 บรรทัด) เพื่อคง API เดิม (limit/offset + total_count)
        total_count = len(items)
        paged = items[offset:offset + limit]

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
            )
        return {"total_count": total_count, "items": paged}

    @classmethod
    async def _get_transactions_merged(
        cls, conn: asyncpg.Connection, *, room_id: int,
        limit: int = 50, offset: int = 0,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        account_id: Optional[int] = None, category_id: Optional[int] = None, transaction_type: Optional[str] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """[ROUTER-MERGE] ประวัติที่ครอบ 2 ยุค (ขอ "ทั้งหมด" หรือช่วงคร่อมเส้นตัด):
        legacy < CUTOFF_DATE + journal >= CUTOFF_DATE นำมารวม เรียง created_at DESC.

        แบ่งที่เส้นกัน dual-write เบิ้ล: legacy ถูก cap ที่ DATE <= วันก่อน 1 ก.ย.,
        journal ถูก floor ที่ DATE >= 1 ก.ย. (dual-write ใช้ timestamp เดียวกันทั้ง 2 ตาราง
        → แต่ละรายการจะโผล่จากฝั่งเดียวเท่านั้น)
        """
        # [MERGE] ฝั่ง legacy: เฉพาะวันที่ < CUTOFF_DATE (DATE <= 2026-08-31)
        legacy_res = await cls._get_transactions_legacy(
            conn=conn, room_id=room_id,
            limit=1_000_000, offset=0,
            start_date=start_date, end_date=CUTOFF_DATE - timedelta(days=1),
            account_id=account_id, category_id=category_id,
            transaction_type=transaction_type,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None,  # ไม่ log ที่ worker (log รวมที่ merged)
        )
        # [MERGE] ฝั่ง journal: วันที่ >= CUTOFF_DATE (floor start ที่ 1 ก.ย.)
        journal_start = start_date if (start_date is not None and start_date >= CUTOFF_DATE) else CUTOFF_DATE
        v2_res = await cls._get_transactions_v2(
            conn=conn, room_id=room_id,
            limit=1_000_000, offset=0,
            start_date=journal_start, end_date=end_date,
            account_id=account_id, category_id=category_id,
            transaction_type=transaction_type,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None,
        )
        # [MERGE] รวม + เรียง DESC (Python stable → ลำดับภายในฝั่งเดียวกันคงเดิม),
        # normalize tz ก่อน sort (legacy naive ↔ journal aware)
        merged = sorted(
            legacy_res["items"] + v2_res["items"],
            key=lambda it: _naive_thai_dt(it["created_at"]),
            reverse=True,
        )
        paged = merged[offset:offset + limit]

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                endpoint_or_command="FinanceService.get_transactions", execution_time_ms=exec_time
            )
        return {"total_count": len(merged), "items": paged}

    @classmethod
    def _classify_journal_entry(cls, entry: dict, transaction_type: Optional[str] = None) -> Optional[dict]:
        """[DOUBLE-ENTRY] จัดประเภทบิลจากชุด journal_lines เป็นแถว TransactionResponse
        ที่ frontend ใช้อยู่ (amount, description, transaction_type, account_name, category_name).

        คืน None ถ้าบิลไม่ตรง transaction_type ที่กรอง (คล้าย WHERE ใน legacy).
        """
        lines = entry["lines"]
        asset_lines = [ln for ln in lines if ln["account_type"] == "asset"]
        revenue_lines = [ln for ln in lines if ln["account_type"] == "revenue"]
        expense_lines = [ln for ln in lines if ln["account_type"] == "expense"]
        # กันพวก liability/equity (เช่น ขา equity ของ opening balance) เข้ามารบกวน
        asset_dr = sum(float(ln["debit"]) for ln in asset_lines)
        asset_cr = sum(float(ln["credit"]) for ln in asset_lines)
        revenue_cr = sum(float(ln["credit"]) for ln in revenue_lines)
        expense_dr = sum(float(ln["debit"]) for ln in expense_lines)

        description = entry["description"] or ""
        recorded_by = entry["recorded_by"]
        txn_type: Optional[str] = None
        amount = 0.0
        account_name: Optional[str] = None
        category_name: Optional[str] = None
        transfer_group_id = None

        # [DOUBLE-ENTRY] 1) ยอดยกมา (Opening Balance) → เงินเข้าสินทรัพย์ = 'income'
        if entry["reference_type"] == "opening_balance":
            txn_type = "income"
            # ยอด = เดบิตฝั่ง Asset (เงินที่มีจริงในกระเป๋า) ไม่รวมขา Equity
            amount = asset_dr
            # ถ้าสินทรัพย์ติดลบ (credit asset) → ให้รวมเครดิตเข้าด้วยเพื่อไม่ให้ amount เป็น 0
            if amount == 0.0:
                amount = asset_cr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            category_name = "ยอดยกมา (เปิดระบบบัญชีคู่)"
            description = description or "ยอดยกมา"

        # [DOUBLE-ENTRY] 2) Transfer ระหว่างบัญชีสินทรัพย์ → 'expense' (ขาออก) + transfer_group_id
        elif len(asset_lines) >= 2 and asset_dr > 0 and asset_cr > 0:
            txn_type = "expense"
            amount = asset_cr
            # บัญชีที่เงินออก (credit) — เป็นบัญชีต้นทาง
            out_line = next((ln for ln in asset_lines if float(ln["credit"]) > 0), asset_lines[0])
            account_name = out_line["account_name"]
            category_name = "โอนเงิน"
            transfer_group_id = entry["reference_id"] and int(entry["reference_id"]) or None
            recorded_by = recorded_by

        # [DOUBLE-ENTRY] 3) รายได้: Asset เดบิต + Revenue เครดิต (รับเงินเข้า)
        elif asset_dr > 0 and revenue_cr > 0:
            txn_type = "income"
            amount = asset_dr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            if revenue_lines:
                category_name = revenue_lines[0]["account_name"]
            description = description or "รายได้"

        # [DOUBLE-ENTRY] 4) รายจ่าย: Expense เดบิต + Asset เครดิต (เงินออก)
        elif expense_dr > 0 and asset_cr > 0:
            txn_type = "expense"
            amount = asset_cr
            if asset_lines:
                account_name = asset_lines[0]["account_name"]
            if expense_lines:
                category_name = expense_lines[0]["account_name"]
            description = description or "รายจ่าย"

        # [DOUBLE-ENTRY] 5) กรณีโครงสร้างอื่น (ไม่มี asset) → พยายามเดาจากฝั่งที่มี
        else:
            if revenue_cr > 0:
                txn_type = "income"
                amount = revenue_cr
                if revenue_lines:
                    category_name = revenue_lines[0]["account_name"]
            elif expense_dr > 0:
                txn_type = "expense"
                amount = expense_dr
                if expense_lines:
                    category_name = expense_lines[0]["account_name"]
            else:
                return None

        # [DOUBLE-ENTRY] รองรับ filter transaction_type (income/expense) แบบเดียวกับ legacy
        if transaction_type and txn_type != transaction_type:
            return None

        # 💡 เก็บบรรทัดแรกของ asset ไว้เป็น account (หน้า frontend ใช้แสดงกระเป๋าเงิน)
        if not account_name and asset_lines:
            account_name = asset_lines[0]["account_name"]
        if not account_name:
            account_name = "—"

        return {
            "id": _legacy_id_from_journal(entry.get("metadata") or {}, entry.get("journal_entry_id")),
            "amount": float(amount),
            "description": description,
            "transaction_type": txn_type,
            "created_at": entry["transaction_date"],
            "slip_image_url": entry["slip_image_url"],
            "recorded_by": recorded_by,
            "account_name": account_name,
            "category_name": category_name,
            "transfer_group_id": transfer_group_id,
        }

    @classmethod
    async def create_fee_collection(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    collection_id = await conn.fetchval(
                        "INSERT INTO fee_collections (room_id, title, amount, due_date) VALUES ($1, $2, $3, $4) RETURNING id",
                        target_room_id, req.title, req.amount, req.due_date
                    )
                    
                    target_students = []
                    if req.student_ids is not None:
                        if len(req.student_ids) == 0:
                            raise ValueError("ไม่สามารถสร้างรายการได้ เนื่องจากไม่ได้เลือกนักเรียนเลยแม้แต่คนเดียว")

                        # 💡 กรอง id ซ้ำก่อน query + INSERT กัน UniqueViolationError (student_payments มี UNIQUE(collection_id, student_id))
                        unique_ids = list(dict.fromkeys(req.student_ids))
                        valid_students = await conn.fetch(
                            "SELECT id FROM students WHERE room_id = $1 AND id = ANY($2) AND status = 'active'",
                            target_room_id, unique_ids
                        )
                        target_students = [s['id'] for s in valid_students]
                    else:
                        all_students = await conn.fetch("SELECT id FROM students WHERE room_id = $1 AND status = 'active'", target_room_id)
                        target_students = [s['id'] for s in all_students]

                    if target_students:
                        # 🛡️ กัน id ซ้ำใน target_students (ป้องกัน UniqueViolation ถ้า query คืนค่าซ้ำ)
                        target_students = list(dict.fromkeys(target_students))
                        records = [(collection_id, sid, 'pending') for sid in target_students]
                        await conn.executemany("INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, $3)", records)
                    
                    new_values = cls._extract_req_data(req)
                    new_values["resolved_target_students"] = target_students
                    msg = f"สร้างแคมเปญสำเร็จ เรียกเก็บเพื่อน {len(target_students)} คน"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", entity_id=str(collection_id), status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_fee_collection", execution_time_ms=exec_time
                    )
                    # 📢 แจ้งเตือน Discord: สร้างแคมเปญเก็บเงินใหม่ → @everyone (ทุกคนต้องรู้)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id:
                await ActionService.notify_new_collection(
                    server_id=room_server_id,
                    title=req.title,
                    amount=float(req.amount),
                    due_date=req.due_date,
                    user_name=req.user_name,
                )
            return {"status": "success", "message": msg}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_fee_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _confirm_single_payment(
        cls, conn: asyncpg.Connection, target_room_id: int,
        payment_id: int, paid_amount: float, paid_to_account_id: int,
        slip_image_url: Optional[str], user_name: str,
    ) -> dict:
        """[SHARED] รับเงิน 1 บิล (student_payment) — ใช้ร่วมโดย confirm_payment (บิลเดียว)
        และ batch_confirm_payments (รวบยอด). ต้องถูกเรียกภายใน `async with conn.transaction():`
        ของ caller เสมอ (batch จะได้ atomic ทั้งชุด). คืนข้อมูลสำหรับ audit log + publish."""
        valid_account = await conn.fetchval("SELECT id FROM finance_accounts WHERE id = $1 AND room_id = $2", paid_to_account_id, target_room_id)
        if not valid_account: raise ValueError("กระเป๋าเงินไม่มีอยู่ หรือไม่ใช่ของห้องนี้!")

        old_sp_data = await conn.fetchrow("SELECT * FROM student_payments WHERE id = $1 FOR UPDATE", payment_id)
        old_values = dict(old_sp_data) if old_sp_data else {}

        payment_info = await conn.fetchrow(
            """SELECT FC.amount as total_amount, SP.paid_amount as current_paid, FC.title,
                      U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               JOIN students S ON SP.student_id = S.id
               LEFT JOIN users U ON S.user_id = U.id
               WHERE SP.id = $1 AND FC.room_id = $2 AND FC.status = 'active'""",
            payment_id, target_room_id
        )
        if not payment_info: raise PaymentNotFoundError("ไม่พบรายการนี้ หรือแคมเปญถูกปิดไปแล้ว")

        current_paid = float(payment_info['current_paid'])
        total_amount = float(payment_info['total_amount'])

        if current_paid >= total_amount: raise ValueError("บิลนี้จ่ายครบไปเรียบร้อยแล้วครับ!")

        # 🛡️ กัน overpay: ห้ามรับเงินเกินยอดที่เหลือค้าง (current_paid + paid_amount > total)
        if paid_amount > total_amount - current_paid:
            raise ValueError(
                f"จำนวนเงินที่รับเกินยอดที่เหลือค้าง! "
                f"เหลือค้าง {total_amount - current_paid:.2f} บาท แต่ส่งมา {paid_amount:.2f} บาท"
            )

        new_total_paid = current_paid + paid_amount
        new_status = 'paid' if new_total_paid >= total_amount else 'pending'
        status_msg = "จ่ายครบแล้ว" if new_status == 'paid' else f"ทยอยจ่าย (ขาดอีก {total_amount - new_total_paid} ฿)"

        stu_name = payment_info['first_name'] or payment_info.get('first_name_en') or "Unknown"
        if payment_info['nickname']: stu_name += f" ({payment_info['nickname']})"
        dynamic_desc = f"รับเงิน: {payment_info['title']} จาก {stu_name} [{status_msg}]"

        trans_id = await conn.fetchval(
            """INSERT INTO finance_transactions
               (room_id, account_id, amount, description, transaction_type, slip_image_url, recorded_by, student_payment_id)
               VALUES ($1, $2, $3, $4, 'income', $5, $6, $7) RETURNING id""",
            target_room_id, paid_to_account_id, paid_amount, dynamic_desc, slip_image_url, user_name, payment_id
        )

        await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", paid_amount, paid_to_account_id)
        await conn.execute(
            """UPDATE student_payments
               SET status = $1, paid_amount = $2, paid_to_account_id = $3, slip_image_url = $4, recorded_by = $5, paid_at = NOW(), transaction_id = $6
               WHERE id = $7""",
            new_status, new_total_paid, paid_to_account_id, slip_image_url, user_name, trans_id, payment_id
        )

        # [DUAL-WRITE] เขียนฝั่ง Double-Entry: รับชำระเงินจากนักเรียน (Dr สินทรัพย์ / Cr รายได้เก็บเงินห้อง)
        asset_ledger_id = await cls._resolve_asset_ledger(conn, target_room_id, paid_to_account_id)
        # Credit ขาเป็นรายได้ "เก็บเงินห้องปกติ" — ถ้าไม่มี mapping ให้หา ledger ตามชื่อ
        # (seed ค่าเริ่มต้น DEFAULT_INCOME_CATEGORIES[0] = '📥 เก็บเงินห้องปกติ')
        revenue_ledger_id = await cls._find_revenue_ledger_by_name(
            conn, target_room_id, account_name=DEFAULT_INCOME_CATEGORIES[0]
        )
        if revenue_ledger_id is None:
            # [FIX A] ปิดรอยรั่วข้าม dual-write: ห้องที่ยังไม่มี ledger รายได้/หมวดหมู่ค่าเริ่มต้น
            # → สร้างหมวด '📥 เก็บเงินห้องปกติ' (ถ้ายังไม่มี) + revenue ledger ให้อัตโนมัติ
            # เพื่อให้ journal ครบฝั่ง (กัน "legacy ได้เงิน แต่บัญชีคู่ไม่มีบิล")
            legacy_cat_id = await cls._find_or_create_default_income_category(conn, target_room_id)
            if legacy_cat_id:
                revenue_ledger_id = await cls._resolve_category_ledger(conn, target_room_id, legacy_cat_id, 'income')
        # ห้ามข้าม dual-write: ถ้าหา/สร้าง ledger รายได้ไม่ได้ → error (rollback ทั้งชุด) แทนที่จะเงียบ
        if revenue_ledger_id is None:
            raise ValueError("ไม่สามารถหา/สร้าง ledger รายได้ '📥 เก็บเงินห้องปกติ' เพื่อบันทึกบัญชีคู่ได้")
        else:
            await cls._insert_journal_entry(
                conn, target_room_id,
                reference_type="student_payment",
                reference_id=str(payment_id),
                description=dynamic_desc,
                slip_image_url=slip_image_url,
                recorded_by=user_name,
                metadata={"student_payment_id": payment_id, "legacy_transaction_id": trans_id},
                lines=[
                    {"ledger_id": asset_ledger_id, "debit": paid_amount, "credit": 0, "line_description": f"รับเงินจากนักเรียน (student_payment #{payment_id})"},
                    {"ledger_id": revenue_ledger_id, "debit": 0, "credit": paid_amount, "line_description": f"รายได้: {payment_info['title']}"},
                ],
            )

        return {
            "payment_id": payment_id,
            "student_payment_id": payment_id,
            "trans_id": trans_id,
            "payer_name": stu_name,
            "title": payment_info['title'],
            "amount": paid_amount,
            "status_msg": status_msg,
            "old_values": old_values,
            "new_values": {
                "payment_id": payment_id,
                "paid_amount": paid_amount,
                "paid_to_account_id": paid_to_account_id,
                "slip_image_url": slip_image_url,
                "user_name": user_name,
            },
        }

    @classmethod
    async def confirm_payment(cls, pool: asyncpg.Pool, payment_id: int, req, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: มีแค่ผู้ดูแลการเงิน (MANAGE_FINANCE) ถึงจะรับเงินได้
                    if user_id is not None:
                        await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    result = await cls._confirm_single_payment(
                        conn=conn, target_room_id=target_room_id,
                        payment_id=payment_id,
                        paid_amount=req.paid_amount,
                        paid_to_account_id=req.paid_to_account_id,
                        slip_image_url=req.slip_image_url,
                        user_name=req.user_name,
                    )

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(payment_id), status="success",
                        old_values=result["old_values"], new_values=result["new_values"], endpoint_or_command="FinanceService.confirm_payment", execution_time_ms=exec_time
                    )
                    # 📢 แจ้งเตือน Discord: มีคนจ่ายเงินแล้ว (ไม่ @everyone — โชว์ความโปร่งใส)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id:
                await ActionService.notify_payment_confirmed(
                    server_id=room_server_id,
                    payer_name=result["payer_name"],
                    title=result["title"],
                    amount=float(result["amount"]),
                    user_name=req.user_name,
                )
            return {"status": "success", "message": f"รับเงินสำเร็จ! สถานะ: {result['status_msg']}"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(payment_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.confirm_payment", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def batch_confirm_payments(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        """✨ รับเงินรวบยอด (Batch): ปลดหนี้หลายบิลของนักเรียนคนเดียวกันใน transaction เดียว
        → publish แจ้งเตือน Discord แค่รอบเดียว (ไม่เด้งหลาย embed เหมือนยิงทีละบิล).
        ถ้าบิลใดบิลหนึ่ง error → rollback ทั้งชุด (atomic)."""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    # 🛡️ RBAC: มีแค่ผู้ดูแลการเงิน (MANAGE_FINANCE) ถึงจะรับเงินได้
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🔒 กันรายการซ้ำใน request (จ่ายบิลเดียวกันเบิ้ล) — เอาแค่ตัวแรก
                    seen_ids, items = set(), []
                    for item in req.items:
                        if item.payment_id in seen_ids:
                            continue
                        seen_ids.add(item.payment_id)
                        items.append(item)

                    payment_ids = [item.payment_id for item in items]
                    rows = await conn.fetch(
                        """SELECT SP.id, SP.student_id
                           FROM student_payments SP
                           JOIN fee_collections FC ON SP.collection_id = FC.id
                           WHERE SP.id = ANY($1) AND FC.room_id = $2 AND FC.status = 'active'""",
                        payment_ids, target_room_id
                    )
                    found_ids = {r['id'] for r in rows}
                    for item in items:
                        if item.payment_id not in found_ids:
                            raise PaymentNotFoundError(f"ไม่พบรายการ #{item.payment_id} หรือแคมเปญถูกปิดไปแล้ว")

                    # 🛡️ Batch ต้องเป็นบิลของนักเรียนคนเดียวกัน (มิฉะนั้นแจ้งเตือนรวมจะงง + จ่ายข้ามคน)
                    student_ids = {r['student_id'] for r in rows}
                    if len(student_ids) > 1:
                        raise ValueError("รายการชำระเงินต้องเป็นของนักเรียนคนเดียวกัน!")

                    results = []
                    for item in items:
                        result = await cls._confirm_single_payment(
                            conn=conn, target_room_id=target_room_id,
                            payment_id=item.payment_id,
                            paid_amount=item.paid_amount,
                            paid_to_account_id=req.paid_to_account_id,
                            slip_image_url=req.slip_image_url,
                            user_name=req.user_name,
                        )
                        results.append(result)

                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                            room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(item.payment_id), status="success",
                            old_values=result["old_values"], new_values=result["new_values"], endpoint_or_command="FinanceService.batch_confirm_payments", execution_time_ms=exec_time
                        )

                    # audit log ระดับ batch (ยืนยันว่ารับกี่รายการ ผ่าน endpoint ไหน)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT_BATCH", status="success",
                        new_values=cls._extract_req_data(req), endpoint_or_command="FinanceService.batch_confirm_payments", execution_time_ms=exec_time
                    )

                    # 📢 publish ครั้งเดียว หลัง commit (รวบรวมบิลทั้งหมด)
                    room_server_id = await cls._get_room_server_id(conn, target_room_id)
            if room_server_id and results:
                await ActionService.notify_payments_confirmed(
                    server_id=room_server_id,
                    payer_name=results[0]["payer_name"],
                    items=[{"title": r["title"], "amount": float(r["amount"])} for r in results],
                    total_amount=float(sum(r["amount"] for r in results)),
                    user_name=req.user_name,
                )
            return {"status": "success", "message": f"รับเงินรวบยอด {len(results)} รายการสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT_BATCH", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.batch_confirm_payments", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_collection_status(cls, pool: asyncpg.Pool, collection_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                sql = """
                    SELECT 
                        SP.id as payment_id, SP.student_id, SP.status, SP.paid_amount, SP.paid_at, SP.slip_image_url,
                        S.student_no, U.first_name, U.last_name, U.nickname,
                        U.first_name_en, U.last_name_en, U.nickname_en, FC.amount as total_amount
                    FROM student_payments SP
                    JOIN students S ON SP.student_id = S.id
                    LEFT JOIN users U ON S.user_id = U.id
                    JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE SP.collection_id = $1 AND S.room_id = $2
                    ORDER BY S.student_no ASC
                """
                rows = await conn.fetch(sql, collection_id, target_room_id)
                total = len(rows)
                paid_count = sum(1 for r in rows if r['status'] == 'paid')
                result = {"collection_id": collection_id, "summary": {"total": total, "paid": paid_count, "pending": total - paid_count}, "students": [dict(r) for r in rows]}

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(collection_id), status="success",
                    endpoint_or_command="FinanceService.get_collection_status", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_PAYMENT", entity_id=str(collection_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_collection_status", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def remove_student_from_collection(cls, pool: asyncpg.Pool, collection_id: int, student_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    payment = await conn.fetchrow("""
                        SELECT SP.*, FC.title 
                        FROM student_payments SP
                        JOIN fee_collections FC ON SP.collection_id = FC.id
                        WHERE SP.collection_id = $1 AND SP.student_id = $2 AND FC.room_id = $3
                        FOR UPDATE OF SP
                    """, collection_id, student_id, target_room_id)

                    if not payment:
                        raise PaymentNotFoundError("ไม่พบข้อมูลการเรียกเก็บเงินของนักเรียนคนนี้")
                    
                    old_values = dict(payment)
                    if payment['paid_amount'] > 0:
                        raise ValueError("ไม่สามารถลบได้ เนื่องจากนักเรียนมีการจ่ายเงิน (หรือทยอยจ่าย) เข้ามาแล้ว ให้ใช้วิธียกเลิกธุรกรรมการเงินแทน")

                    await conn.execute("DELETE FROM student_payments WHERE id = $1", payment['id'])

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", entity_id=str(payment['id']), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.remove_student_from_collection", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "ลบรายชื่อนักเรียนออกจากรายการนี้สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.remove_student_from_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def create_category(cls, pool: asyncpg.Pool, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    # [DUAL-WRITE] ดึง id ของแถว legacy เพื่อ map ลง accounting_ledgers
                    new_category_id = await conn.fetchval(
                        "INSERT INTO finance_categories (room_id, category_name, category_type) VALUES ($1, $2, $3) RETURNING id",
                        target_room_id, req.category_name, req.category_type
                    )

                    # [DUAL-WRITE] สร้าง ledger ฝั่ง Double-Entry (income → 'revenue' 4xxxx, expense → 5xxxx)
                    # รหัสบัญชีตรงกับ migrate_phase2_ledgers.py
                    if req.category_type == 'income':
                        ledger_type, ledger_code = 'revenue', f"4{new_category_id:04d}"
                    else:
                        ledger_type, ledger_code = 'expense', f"5{new_category_id:04d}"
                    await conn.execute(
                        """INSERT INTO accounting_ledgers (room_id, account_code, account_name, account_type, legacy_category_id, description)
                           VALUES ($1, $2, $3, $4, $5, 'Created via dual-write (create_category)')""",
                        target_room_id, ledger_code, req.category_name, ledger_type, new_category_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="success",
                        new_values=new_values, endpoint_or_command="FinanceService.create_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": f"เพิ่มหมวดหมู่ {req.category_name} แล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.create_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_categories(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, cat_type: Optional[str] = None, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                if cat_type:
                    rows = await conn.fetch("SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 AND category_type = $2 ORDER BY id", target_room_id, cat_type)
                else:
                    rows = await conn.fetch("SELECT id, category_name, category_type FROM finance_categories WHERE room_id = $1 ORDER BY id", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FINANCE_CATEGORY", status="success",
                    endpoint_or_command="FinanceService.get_categories", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_categories", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def revert_transaction(cls, pool: asyncpg.Pool, transaction_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    t = await conn.fetchrow(
                        "SELECT * FROM finance_transactions WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE",
                        transaction_id, target_room_id
                    )
                    if not t: raise TransactionNotFoundError("ไม่พบรายการธุรกรรมนี้")

                    # [FIX B] Freeze Legacy: รายการที่สร้างก่อนวันที่ขึ้นระบบบัญชีคู่ (CUTOFF_DATE)
                    # ไม่มี journal ให้ void ได้ → ห้ามยกเลิกเด็ดขาด (ให้บันทึกรายจ่ายปรับปรุงยอดแทน)
                    # กันการ "ย้อน legacy ฝั่งเดียว" จนยอด 2 ระบบเบี้ยวซ้ำอีก (guard ก่อนแตะ balance)
                    cutoff_dt = datetime.combine(CUTOFF_DATE, dtime.min)
                    freeze_msg = ("ไม่สามารถยกเลิกรายการก่อนขึ้นระบบบัญชีคู่ได้ "
                                  "ให้ใช้วิธีบันทึกรายจ่ายปรับปรุงยอดแทน")
                    if t['transfer_group_id']:
                        earliest = await conn.fetchval(
                            """SELECT MIN(created_at) FROM finance_transactions
                               WHERE transfer_group_id = $1 AND room_id = $2 AND deleted_at IS NULL""",
                            t['transfer_group_id'], target_room_id,
                        )
                        if earliest is not None and _naive_thai_dt(earliest) < cutoff_dt:
                            raise ValueError(freeze_msg)
                    elif _naive_thai_dt(t['created_at']) < cutoff_dt:
                        raise ValueError(freeze_msg)

                    old_values = dict(t)

                    if t['transfer_group_id']:
                        group_trans = await conn.fetch("SELECT * FROM finance_transactions WHERE transfer_group_id = $1 AND room_id = $2 AND deleted_at IS NULL FOR UPDATE", t['transfer_group_id'], target_room_id)
                        for gt in group_trans:
                            if gt['transaction_type'] == 'expense': 
                                await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", gt['amount'], gt['account_id'])
                            elif gt['transaction_type'] == 'income':
                                curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", gt['account_id'])
                                if float(curr_bal) < float(gt['amount']): raise ValueError("เงินในบัญชีรับโอนไม่พอหักคืน")
                                await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", gt['amount'], gt['account_id'])
                        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE transfer_group_id = $1 AND room_id = $2", t['transfer_group_id'], target_room_id)
                        # [DUAL-WRITE] ยกเลิก journal ของรายการโอนเงิน (หาด้วย metadata.transfer_group_id)
                        # 💡 ถ้ายังไม่มี journal (ข้อมูลเก่าที่ไม่ได้ผ่าน dual-write) → no-op ไม่พัง
                        await conn.execute(
                            """UPDATE journal_entries
                               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
                               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                                 AND metadata->>'transfer_group_id' = $2""",
                            target_room_id, str(t['transfer_group_id']),
                        )
                        action_detail = "ยกเลิกรายการโอนเงิน"
                    else:
                        if t['transaction_type'] == 'income':
                            curr_bal = await conn.fetchval("SELECT balance FROM finance_accounts WHERE id = $1 FOR UPDATE", t['account_id'])
                            if float(curr_bal) < float(t['amount']): raise ValueError("เงินในบัญชีไม่พอหักคืน")
                            await conn.execute("UPDATE finance_accounts SET balance = balance - $1 WHERE id = $2", t['amount'], t['account_id'])
                            
                            if t['student_payment_id']:
                                sp_id = t['student_payment_id']
                                sp_info = await conn.fetchrow("SELECT paid_amount, FC.amount as total_amount FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id WHERE SP.id = $1 FOR UPDATE", sp_id)
                                new_paid = float(sp_info['paid_amount']) - float(t['amount'])
                                new_status = 'paid' if new_paid >= float(sp_info['total_amount']) else 'pending'
                                # 💡 ถ้ายกเลิกจน paid_amount กลับเป็น 0 ให้ล้าง field การชำระทั้งหมด
                                # (กันสถานะ "จ่ายครบ" ค้างทั้งที่ยอดโดนหักคืนแล้ว)
                                if new_paid <= 0:
                                    await conn.execute(
                                        """UPDATE student_payments
                                           SET paid_amount = 0, status = 'pending', paid_to_account_id = NULL,
                                               slip_image_url = NULL, recorded_by = NULL, paid_at = NULL, transaction_id = NULL
                                           WHERE id = $1""", sp_id
                                    )
                                else:
                                    await conn.execute("UPDATE student_payments SET paid_amount = $1, status = $2 WHERE id = $3", new_paid, new_status, sp_id)

                        elif t['transaction_type'] == 'expense': 
                            await conn.execute("UPDATE finance_accounts SET balance = balance + $1 WHERE id = $2", t['amount'], t['account_id'])
                        
                        await conn.execute("UPDATE finance_transactions SET deleted_at = NOW() WHERE id = $1", transaction_id)
                        # [DUAL-WRITE] ยกเลิก journal ของรายการปกติ (หาด้วย metadata.legacy_transaction_id)
                        # 💡 ถ้ายังไม่มี journal (ข้อมูลเก่า/จาก test ที่ insert ตรง) → no-op ไม่พัง
                        await conn.execute(
                            """UPDATE journal_entries
                               SET status = 'voided', deleted_at = NOW(), updated_at = CURRENT_TIMESTAMP
                               WHERE room_id = $1 AND status <> 'voided' AND deleted_at IS NULL
                                 AND metadata->>'legacy_transaction_id' = $2""",
                            target_room_id, str(transaction_id),
                        )
                        action_detail = f"ยกเลิกรายการ {t['transaction_type']}"

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="success",
                        old_values=old_values, new_values={"action": action_detail}, endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": action_detail}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_TRANSACTION", entity_id=str(transaction_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.revert_transaction", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
            
    @classmethod
    # =====================================================================
    # [ROUTER] get_summary — เลือกอ่านจาก legacy หรือ Double-Entry ตามช่วงเวลา
    # =====================================================================
    @classmethod
    async def get_summary(
        cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str,
        month: Optional[int] = None, year: Optional[int] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)

                # 💡 month/year ต้องระบุพร้อมกันเสมอ (ไม่งั้น params เลื่อนทำให้ SQL error)
                if (month is None) != (year is None):
                    raise ValueError("ต้องระบุทั้ง month และ year พร้อมกัน หรือไม่ระบุทั้งคู่")

                # [ROUTER] จุดแบ่งเวลา: งวดที่เริ่มหลัง CUTOFF_DATE → ระบบบัญชีคู่
                # (ไม่ระบุงวด = เดือนปัจจุบัน → ขึ้นอยู่กับ wall clock ว่าเลยวันที่ตัดหรือยัง)
                period_start = cls._period_start(month, year, None, None)
                use_v2 = period_start >= CUTOFF_DATE

                if use_v2:
                    return await cls._get_summary_v2(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                    )
                return await cls._get_summary_legacy(
                    conn=conn, room_id=target_room_id,
                    month=month, year=year,
                    client_source=client_source, actor_identifier=actor_identifier,
                    start_time=start_time,
                )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _get_summary_legacy(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """[ROUTER-LEGACY] Logic เดิมของ get_summary — อ่านจาก finance_accounts + finance_transactions."""
        net_worth = await conn.fetchval("SELECT SUM(balance) FROM finance_accounts WHERE room_id = $1", room_id) or 0.0

        params = [room_id]
        if month and year:
            date_cond = "AND EXTRACT(MONTH FROM created_at) = $2 AND EXTRACT(YEAR FROM created_at) = $3"
            date_cond_t = "AND EXTRACT(MONTH FROM T.created_at) = $2 AND EXTRACT(YEAR FROM T.created_at) = $3"
            params.extend([month, year])
            period_str = f"{year}-{month:02d}"
        else:
            date_cond = "AND date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)"
            date_cond_t = "AND date_trunc('month', T.created_at) = date_trunc('month', CURRENT_DATE)"
            period_str = "current_month"

        stats = await conn.fetchrow(f"""
            SELECT
                SUM(CASE WHEN transaction_type = 'income' AND transfer_group_id IS NULL THEN amount ELSE 0 END) as total_inc,
                SUM(CASE WHEN transaction_type = 'expense' AND transfer_group_id IS NULL THEN amount ELSE 0 END) as total_exp
            FROM finance_transactions WHERE room_id = $1 AND deleted_at IS NULL {date_cond}
        """, *params)

        breakdown = await conn.fetch(f"""
            SELECT C.category_name, SUM(T.amount) as total_amount
            FROM finance_transactions T
            JOIN finance_categories C ON T.category_id = C.id
            WHERE T.room_id = $1 AND T.transaction_type = 'expense' AND T.transfer_group_id IS NULL AND T.deleted_at IS NULL {date_cond_t}
            GROUP BY C.category_name ORDER BY total_amount DESC
        """, *params)

        pending_collection = await conn.fetchval("""
            SELECT SUM(FC.amount - SP.paid_amount) FROM student_payments SP
            JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE SP.status = 'pending' AND FC.room_id = $1 AND FC.status = 'active'
        """, room_id) or 0.0

        result = {
            "net_worth": float(net_worth), "total_income": float(stats['total_inc'] or 0),
            "total_expense": float(stats['total_exp'] or 0), "pending_collection_amount": float(pending_collection),
            "period": period_str, "expense_breakdown": [dict(b) for b in breakdown]
        }

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="success",
                endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
            )
        return result

    # =====================================================================
    # [DOUBLE-ENTRY] _get_summary_v2 — สรุปยอดจาก ledger ตามหลักบัญชีคู่
    # =====================================================================
    @classmethod
    async def _get_summary_v2(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
    ) -> dict:
        """สรุปยอดจากระบบบัญชีคู่ (journal_lines) แทนการรวมจาก finance_transactions.

        - Net Worth : SUM(Dr) − SUM(Cr) ของทุก ledger ประเภท 'asset' (ยอดสะสมทั้งหมด)
        - รายได้     : SUM(Cr) − SUM(Dr) ของ 'revenue' ในงวดที่ขอ
        - รายจ่าย   : SUM(Dr) − SUM(Cr) ของ 'expense' ในงวดที่ขอ
        - Expense Breakdown: group ตาม account_name ของ ledger ประเภท 'expense'
        - ยอดยกมา (opening_balance) ไม่ถูกนับเป็นรายได้ของงวด (มันคือทุน ไม่ใช่รายได้)
        """
        if month is not None and year is not None:
            start_dt = date(year, month, 1)
            if month == 12:
                end_dt = date(year + 1, 1, 1)
            else:
                end_dt = date(year, month + 1, 1)
            period_str = f"{year}-{month:02d}"
        else:
            today = datetime.now(THAI_TZ).date()
            start_dt = date(today.year, today.month, 1)
            if today.month == 12:
                end_dt = date(today.year + 1, 1, 1)
            else:
                end_dt = date(today.year, today.month + 1, 1)
            period_str = "current_month"

        # [DOUBLE-ENTRY] ยอดสินทรัพย์สะสมทั้งห้อง (ไม่จำกัดงวด) — เทียบเท่า SUM(balance)
        # 💡 นับเฉพาะ journal ที่ไม่ได้ void และไม่ได้ลบ (ลบ legacy ที่ delete ไป)
        net_worth = await conn.fetchval(
            """SELECT COALESCE(SUM(L.debit - L.credit), 0)
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND AL.account_type = 'asset'
                 AND JE.deleted_at IS NULL AND JE.status <> 'voided'""",
            room_id,
        ) or 0.0

        # [DOUBLE-ENTRY] ยอดรายได้/รายจ่ายภายในงวด (เฉพาะ journal ที่ไม่ใช่ opening_balance)
        period_stats = await conn.fetchrow(
            """SELECT
                 COALESCE(SUM(CASE WHEN AL.account_type = 'revenue' THEN L.credit - L.debit ELSE 0 END), 0) AS total_inc,
                 COALESCE(SUM(CASE WHEN AL.account_type = 'expense' THEN L.debit - L.credit ELSE 0 END), 0) AS total_exp
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                 AND JE.reference_type <> 'opening_balance'
                 AND JE.transaction_date >= $2 AND JE.transaction_date < $3""",
            room_id, start_dt, end_dt,
        )

        # [DOUBLE-ENTRY] รายจ่ายรายหมวด (จากชื่อ ledger ฝั่ง expense) ภายในงวด
        breakdown_rows = await conn.fetch(
            """SELECT AL.account_name AS category_name, SUM(L.debit - L.credit) AS total_amount
               FROM journal_lines L
               JOIN journal_entries JE ON L.journal_entry_id = JE.id
               JOIN accounting_ledgers AL ON L.ledger_id = AL.id
               WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                 AND JE.reference_type <> 'opening_balance'
                 AND AL.account_type = 'expense'
                 AND JE.transaction_date >= $2 AND JE.transaction_date < $3
               GROUP BY AL.account_name
               ORDER BY total_amount DESC""",
            room_id, start_dt, end_dt,
        )

        pending_collection = await conn.fetchval("""
            SELECT SUM(FC.amount - SP.paid_amount) FROM student_payments SP
            JOIN fee_collections FC ON SP.collection_id = FC.id
            WHERE SP.status = 'pending' AND FC.room_id = $1 AND FC.status = 'active'
        """, room_id) or 0.0

        result = {
            "net_worth": float(net_worth),
            "total_income": float(period_stats["total_inc"] or 0),
            "total_expense": float(period_stats["total_exp"] or 0),
            "pending_collection_amount": float(pending_collection),
            "period": period_str,
            "expense_breakdown": [
                {"category_name": b["category_name"], "total_amount": float(b["total_amount"])}
                for b in breakdown_rows
            ],
        }

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_SUMMARY", status="success",
                endpoint_or_command="FinanceService.get_summary", execution_time_ms=exec_time
            )
        return result

    # =====================================================================
    # [DOUBLE-ENTRY] งบทดลอง (Trial Balance) — จุดแข็งของระบบบัญชีคู่
    # =====================================================================
    @classmethod
    async def get_trial_balance(
        cls, pool: asyncpg.Pool, room_id: int,
        client_source: str = "", actor_identifier: str = "",
        user_id: Optional[int] = None, as_of_date: Optional[date] = None, server_id: Optional[int] = None,
    ) -> dict:
        """งบทดลอง: ยอด YTD (Year-to-Date) ของทุก ledger ที่ยัง active ในห้อง.

        กติกาการหักยอดตามประเภทบัญชี (สเปค Phase 4):
        - Assets & Expenses   : Dr − Cr
        - Liabilities, Equity, Revenue : Cr − Dr

        คืน {"ledgers": [...], "total_debit": X, "total_credit": Y, "is_balanced": bool}
        โดย total_debit/total_credit คือผลรวมของยอด Dr/Cr รวม (ไม่ใช่สุทธิ) ของทุก ledger
        → ถ้า journal ทุกรายการสมดุล (Dr = Cr เสมอ) ค่าเท่ากัน และ is_balanced = True
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ ข้อมูลการเงิน → ต้องเป็นสมาชิกห้องเท่านั้น
                await require_member(conn, target_room_id, user_id)

                # [CLAMP] งบทดลองอ่านจาก journal ล้วน (ไม่มี ledger ของยุค Single-Entry)
                # → ถ้า as_of_date อยู่ก่อนวันที่ตัด กลับค่าว่าง + note (ไม่มีข้อมูลให้สรุป)
                if as_of_date is not None and as_of_date < CUTOFF_DATE:
                    return {
                        "ledgers": [],
                        "total_debit": 0.0,
                        "total_credit": 0.0,
                        "is_balanced": True,
                        "note": _CLAMP_EMPTY_NOTE,
                    }

                # [DOUBLE-ENTRY] ขอบเขตเวลา: ถึง as_of_date (ถ้าไม่ระบุ = ทั้งหมดจนถึงตอนนี้)
                if as_of_date is not None:
                    date_filter = "AND JE.transaction_date < $2"
                    params = [target_room_id, datetime.combine(as_of_date, dtime(23, 59, 59))]
                else:
                    date_filter = ""
                    params = [target_room_id]

                # [DOUBLE-ENTRY] รวม Dr/Cr ของทุก ledger ที่ active ยังไม่ void
                rows = await conn.fetch(
                    f"""SELECT
                            AL.id AS ledger_id,
                            AL.account_code,
                            AL.account_name,
                            AL.account_type,
                            COALESCE(NET.total_debit, 0)  AS total_debit,
                            COALESCE(NET.total_credit, 0) AS total_credit
                        FROM accounting_ledgers AL
                        LEFT JOIN (
                            SELECT L.ledger_id,
                                   SUM(L.debit)  AS total_debit,
                                   SUM(L.credit) AS total_credit
                            FROM journal_lines L
                            JOIN journal_entries JE ON L.journal_entry_id = JE.id
                            WHERE JE.deleted_at IS NULL
                              AND JE.status <> 'voided'
                              {date_filter}
                            GROUP BY L.ledger_id
                        ) NET ON NET.ledger_id = AL.id
                        WHERE AL.room_id = $1 AND AL.is_active = TRUE
                        ORDER BY AL.account_code NULLS LAST, AL.id""",
                    *params,
                )

                ledgers: List[dict] = []
                grand_debit = 0.0
                grand_credit = 0.0
                for r in rows:
                    dr = float(r["total_debit"])
                    cr = float(r["total_credit"])
                    # [DOUBLE-ENTRY] ตามสมการปกติของงบทดลอง
                    if r["account_type"] in ("asset", "expense"):
                        balance = dr - cr
                    else:  # liability / equity / revenue
                        balance = cr - dr
                    grand_debit += dr
                    grand_credit += cr
                    ledgers.append({
                        "ledger_id": r["ledger_id"],
                        "account_code": r["account_code"],
                        "account_name": r["account_name"],
                        "account_type": r["account_type"],
                        "total_debit": dr,
                        "total_credit": cr,
                        "balance": balance,
                    })

                result = {
                    "ledgers": ledgers,
                    "total_debit": grand_debit,
                    "total_credit": grand_credit,
                    "is_balanced": abs(grand_debit - grand_credit) < 0.01,  # เผื่อ floating noise
                }

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="TRIAL_BALANCE", status="success",
                    endpoint_or_command="FinanceService.get_trial_balance", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="TRIAL_BALANCE", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_trial_balance", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    # =====================================================================
    # [DOUBLE-ENTRY] งบกำไรขาดทุน (Income Statement) — ตามงวดเวลา
    # =====================================================================
    @classmethod
    async def get_income_statement(
        cls, pool: asyncpg.Pool, room_id: int, start_date: date, end_date: date,
        client_source: str = "", actor_identifier: str = "",
        user_id: Optional[int] = None, server_id: Optional[int] = None,
    ) -> dict:
        """งบกำไรขาดทุน: รวมรายได้/ค่าใช้จ่ายภายในช่วงเวลาที่กำหนด.

        - revenues: group ตามชื่อ ledger ประเภท 'revenue' (SUM(credit − debit))
        - expenses: group ตามชื่อ ledger ประเภท 'expense' (SUM(debit − credit))
        - net_income = Total Revenue − Total Expense
        - ไม่นับยอดยกมา (opening_balance) เพราะมันคือทุน ไม่ใช่รายได้ของงวด
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                if start_date > end_date:
                    raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")

                # [CLAMP] งบกำไรขาดทุนอ่านจาก journal ล้วน (ข้อมูลก่อนวันที่ตัดไม่อยู่ในนี้)
                query_start, _, clamped, empty = _clamp_to_cutoff(start_date, end_date)
                if empty:
                    return {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "revenues": [],
                        "expenses": [],
                        "total_revenue": 0.0,
                        "total_expense": 0.0,
                        "net_income": 0.0,
                        "note": _CLAMP_EMPTY_NOTE,
                    }

                # [DOUBLE-ENTRY] ขอบเขตปลาย → คร่อมทั้งวันของ end_date (end ยังเป็นค่าเดิม)
                end_bound = datetime.combine(end_date, dtime(23, 59, 59))

                rev_rows = await conn.fetch(
                    """SELECT AL.account_name,
                              COALESCE(SUM(L.credit - L.debit), 0) AS total
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                       WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                         AND JE.reference_type <> 'opening_balance'
                         AND AL.account_type = 'revenue'
                         AND JE.transaction_date >= $2 AND JE.transaction_date <= $3
                       GROUP BY AL.account_name
                       ORDER BY total DESC""",
                    target_room_id, query_start, end_bound,
                )

                exp_rows = await conn.fetch(
                    """SELECT AL.account_name,
                              COALESCE(SUM(L.debit - L.credit), 0) AS total
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                       WHERE JE.room_id = $1 AND JE.deleted_at IS NULL AND JE.status <> 'voided'
                         AND JE.reference_type <> 'opening_balance'
                         AND AL.account_type = 'expense'
                         AND JE.transaction_date >= $2 AND JE.transaction_date <= $3
                       GROUP BY AL.account_name
                       ORDER BY total DESC""",
                    target_room_id, query_start, end_bound,
                )

                revenues = [
                    {"account_name": r["account_name"], "amount": float(r["total"])} for r in rev_rows
                ]
                expenses = [
                    {"account_name": r["account_name"], "amount": float(r["total"])} for r in exp_rows
                ]
                total_revenue = sum(r["amount"] for r in revenues)
                total_expense = sum(r["amount"] for r in expenses)

                result = {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "revenues": revenues,
                    "expenses": expenses,
                    "total_revenue": total_revenue,
                    "total_expense": total_expense,
                    "net_income": total_revenue - total_expense,
                }

                # [CLAMP] ถ้าช่วงที่ขอเริ่มก่อน 1 ก.ย. แล้วถูกดันมา → แจ้งในผลลัพธ์
                if clamped:
                    result["note"] = _CLAMP_START_NOTE

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="INCOME_STATEMENT", status="success",
                    endpoint_or_command="FinanceService.get_income_statement", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="INCOME_STATEMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_income_statement", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_student_debts(cls, pool: asyncpg.Pool, student_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                student = await conn.fetchrow("SELECT S.id, U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en FROM students S LEFT JOIN users U ON S.user_id = U.id WHERE S.id = $1 AND S.room_id = $2", student_id, target_room_id)
                if not student: raise RoomNotFoundError("ไม่พบข้อมูลนักเรียนคนนี้ในห้อง")

                rows = await conn.fetch("""
                    SELECT SP.id as payment_id, FC.id as collection_id, FC.title, (FC.amount - COALESCE(SP.paid_amount, 0)) AS amount, FC.due_date, FC.status AS collection_status
                    FROM student_payments SP JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE SP.student_id = $1 AND SP.status = 'pending' AND FC.room_id = $2
                    ORDER BY FC.status ASC, FC.due_date ASC
                """, student_id, target_room_id)

                formatted_debts, total_pending = [], 0.0
                for r in rows:
                    row_dict = dict(r)
                    row_dict['amount'] = float(row_dict['amount'])
                    formatted_debts.append(row_dict)
                    total_pending += row_dict['amount']

                formatted_name = student['first_name'] or student.get('first_name_en') or "Unknown"
                if student['nickname']: formatted_name += f" ({student['nickname']})"

                result = {"student_id": student_id, "student_name": formatted_name, "total_pending_amount": total_pending, "debts": formatted_debts}

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="STUDENT_DEBT", entity_id=str(student_id), status="success",
                    endpoint_or_command="FinanceService.get_student_debts", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="STUDENT_DEBT", entity_id=str(student_id), status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_student_debts", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def add_student_to_collection(cls, pool: asyncpg.Pool, collection_id: int, student_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                    # 🛡️ ต้องเป็นสมาชิก active เท่านั้น (กัน pending/left student เข้ารายการเก็บเงิน)
                    if not await conn.fetchval("SELECT id FROM students WHERE id = $1 AND room_id = $2 AND status = 'active'", student_id, target_room_id):
                        raise RoomNotFoundError("ไม่พบเด็กคนนี้ในห้อง")
                    if not await conn.fetchval("SELECT id FROM fee_collections WHERE id = $1 AND room_id = $2 AND status = 'active'", collection_id, target_room_id):
                        raise ValueError("ไม่พบรายการเรียกเก็บเงินนี้ หรือแคมเปญถูกปิดไปแล้ว!")

                    try:
                        await conn.execute("INSERT INTO student_payments (collection_id, student_id, status) VALUES ($1, $2, 'pending')", collection_id, student_id)
                    except asyncpg.exceptions.UniqueViolationError:
                        raise ValueError("เพื่อนคนนี้มีชื่อในรายการนี้อยู่แล้ว")

                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", status="success",
                        new_values={"collection_id": collection_id, "student_id": student_id}, endpoint_or_command="FinanceService.add_student_to_collection", execution_time_ms=exec_time
                    )
                    return {"status": "success", "message": "เพิ่มเพื่อนเข้าสู่การเก็บเงินแล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="STUDENT_PAYMENT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.add_student_to_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
    
    @classmethod
    async def get_all_collections(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("SELECT id, title, amount, due_date, status FROM fee_collections WHERE room_id = $1 ORDER BY id DESC", target_room_id)
                result = [dict(row) for row in rows]

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="FEE_COLLECTION", status="success",
                    endpoint_or_command="FinanceService.get_all_collections", execution_time_ms=exec_time
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FEE_COLLECTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_all_collections", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_collection(cls, pool: asyncpg.Pool, collection_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    current_data = await conn.fetchrow("SELECT * FROM fee_collections WHERE id = $1 AND room_id = $2", collection_id, target_room_id)
                    if not current_data: raise RoomNotFoundError("ไม่พบแคมเปญนี้")
                    old_values = dict(current_data)

                    updates, values, idx, changed_labels = [], [], 1, []
                    
                    if req.title is not None:
                        updates.append(f"title = ${idx}"); values.append(req.title); idx += 1; changed_labels.append("title")
                    if req.amount is not None and float(req.amount) != float(current_data['amount']):
                        if await conn.fetchval("SELECT 1 FROM student_payments WHERE collection_id = $1 AND paid_amount > 0 LIMIT 1", collection_id):
                            raise ValueError("ไม่สามารถแก้จำนวนเงินได้ เนื่องจากมีเงินโอนเข้ามาแล้ว!")
                        updates.append(f"amount = ${idx}"); values.append(req.amount); idx += 1; changed_labels.append("amount")
                    if req.due_date is not None:
                        updates.append(f"due_date = ${idx}"); values.append(req.due_date); idx += 1; changed_labels.append("due_date")
                    if req.status is not None:
                        updates.append(f"status = ${idx}"); values.append(req.status); idx += 1; changed_labels.append("status")

                    if not updates: return {"status": "success", "message": "ไม่มีข้อมูลให้เปลี่ยนแปลง"}

                    values.extend([collection_id, target_room_id])
                    res = await conn.execute(f"UPDATE fee_collections SET {', '.join(updates)} WHERE id = ${idx} AND room_id = ${idx + 1}", *values)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบแคมเปญนี้")

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", entity_id=str(collection_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_collection", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตข้อมูลสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FEE_COLLECTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_collection", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_account(cls, pool: asyncpg.Pool, account_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    old_values = dict(old_data)

                    res = await conn.execute("UPDATE finance_accounts SET account_name = $1 WHERE id = $2 AND room_id = $3", req.account_name, account_id, target_room_id)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบบัญชีนี้")

                    # [DUAL-WRITE] ซิงก์ชื่อไปยัง accounting_ledgers (ถ้ามี) — กัน ledger ค้างชื่อเก่า
                    await conn.execute(
                        "UPDATE accounting_ledgers SET account_name = $1, updated_at = CURRENT_TIMESTAMP WHERE legacy_account_id = $2 AND room_id = $3",
                        req.account_name, account_id, target_room_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", entity_id=str(account_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตชื่อบัญชีสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_account(cls, pool: asyncpg.Pool, account_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_accounts WHERE id = $1 AND room_id = $2", account_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบบัญชีนี้")
                    old_values = dict(old_data)
                    
                    bal = old_data['balance']
                    if bal > 0: raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากยังมีเงินคงเหลืออยู่!")
                    if await conn.fetchval("SELECT 1 FROM student_payments WHERE paid_to_account_id = $1 LIMIT 1", account_id):
                        raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติการรับเงินผูกกับบัญชีนี้อยู่!")
                    # 🛡️ กันประวัติธุรกรรมหาย: ถ้ามี finance_transactions อ้างถึงบัญชีนี้ ห้าม hard-delete
                    # (FK account_id ON DELETE SET NULL → ประวัติรายรับ/รายจ่ายจะกลายเป็น NULL)
                    if await conn.fetchval("SELECT 1 FROM finance_transactions WHERE account_id = $1 LIMIT 1", account_id):
                        raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติธุรกรรมผูกกับบัญชีนี้!")

                    await conn.execute("DELETE FROM finance_accounts WHERE id = $1", account_id)
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", entity_id=str(account_id), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.delete_account", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "ลบบัญชีสำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_ACCOUNT", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_account", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def get_all_debtors(cls, pool: asyncpg.Pool, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None) -> List[dict]:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)
                rows = await conn.fetch("""
                    SELECT S.id as student_id, S.student_no, U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en,
                           COUNT(SP.id) as overdue_count, SUM(FC.amount - SP.paid_amount) as total_pending_amount
                    FROM students S LEFT JOIN users U ON S.user_id = U.id
                    JOIN student_payments SP ON S.id = SP.student_id JOIN fee_collections FC ON SP.collection_id = FC.id
                    WHERE S.room_id = $1 AND SP.status = 'pending'
                    GROUP BY S.id, S.student_no, U.first_name, U.nickname, U.first_name_en, U.last_name_en, U.nickname_en ORDER BY S.student_no ASC
                """, target_room_id)
                debtors = []
                for r in rows:
                    name = r['first_name'] or r.get('first_name_en') or "Unknown"
                    if r['nickname']: name += f" ({r['nickname']})"
                    debtors.append({"student_id": r['student_id'], "student_no": r['student_no'], "student_name": name, "overdue_count": r['overdue_count'], "total_pending_amount": float(r['total_pending_amount'])})
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="DEBTOR_LIST", status="success",
                    endpoint_or_command="FinanceService.get_all_debtors", execution_time_ms=exec_time
                )
                return debtors
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="DEBTOR_LIST", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.get_all_debtors", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e
    
    @classmethod
    async def update_category(cls, pool: asyncpg.Pool, category_id: int, req, user_id: int, client_source: str, actor_identifier: str, server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    old_values = dict(old_data)

                    res = await conn.execute("UPDATE finance_categories SET category_name = $1 WHERE id = $2 AND room_id = $3", req.category_name, category_id, target_room_id)
                    if res == "UPDATE 0": raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")

                    # [DUAL-WRITE] ซิงก์ชื่อไปยัง accounting_ledgers (ถ้ามี) — กัน ledger ค้างชื่อเก่า
                    await conn.execute(
                        "UPDATE accounting_ledgers SET account_name = $1, updated_at = CURRENT_TIMESTAMP WHERE legacy_category_id = $2 AND room_id = $3",
                        req.category_name, category_id, target_room_id
                    )

                    new_values = cls._extract_req_data(req)
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", entity_id=str(category_id), status="success",
                        old_values=old_values, new_values=new_values, endpoint_or_command="FinanceService.update_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "อัปเดตชื่อหมวดหมู่สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_category(cls, pool: asyncpg.Pool, category_id: int, user_id: int, client_source: str, actor_identifier: str, user_name: str = "—", server_id: Optional[int] = None, room_id: Optional[int] = None) -> dict:
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                    await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")
                    
                    old_data = await conn.fetchrow("SELECT * FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if not old_data: raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    old_values = dict(old_data)

                    if await conn.fetchval("SELECT 1 FROM finance_transactions WHERE category_id = $1 LIMIT 1", category_id):
                        raise ValueError("ไม่สามารถลบได้ เนื่องจากมีการใช้หมวดหมู่นี้อยู่!")
                    res = await conn.execute("DELETE FROM finance_categories WHERE id = $1 AND room_id = $2", category_id, target_room_id)
                    if res == "DELETE 0": raise RoomNotFoundError("ไม่พบหมวดหมู่นี้")
                    
                    exec_time = int((time.time() - start_time) * 1000)
                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", entity_id=str(category_id), status="success",
                        old_values=old_values, endpoint_or_command="FinanceService.delete_category", execution_time_ms=exec_time
                    )
                return {"status": "success", "message": "ลบหมวดหมู่สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=user_id, entity_type="FINANCE_CATEGORY", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_category", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    # =====================================================================
    # [EXPORT-ERP] Real-time data fetchers (ใช้ร่วมทั้ง export ธรรมดา & export นักบัญชี)
    # — ข้อมูล fee_collections / student_payments / students/users เป็นข้อมูล "ปัจจุบัน"
    #   ไม่ขึ้นกับยุค CUTOFF_DATE → อ่าน "ณ วันที่ส่งออก" เสมอ (มี as_of ให้ทราบ)
    # =====================================================================
    @classmethod
    async def _fetch_collection_register(cls, conn: asyncpg.Connection, room_id: int) -> dict:
        """โปรเจคเก็บเงิน (fee_collections) แบบ Real-time + ยอดรวมอัตราการเก็บ.

        fee_collections.amount = ยอดเรียกเก็บ/คน และมี student_payments 1 แถว/นักเรียนที่ถูก
        เรียกเก็บ → expected รวม = amount × จำนวนสมาชิก, paid = Σ paid_amount,
        pending = expected − paid (ไม่ต่ำกว่า 0). completion = paid/expected.

        คืน dict: {as_of, projects:[...], total_expected, total_paid, total_pending,
                   collection_rate_pct, project_count, active_count}
        """
        as_of = datetime.now(THAI_TZ).date()
        rows = await conn.fetch(
            """SELECT FC.id, FC.title, FC.amount, FC.due_date, FC.status,
                      COUNT(SP.id)                    AS member_count,
                      COALESCE(SUM(SP.paid_amount), 0) AS paid_total
               FROM fee_collections FC
               LEFT JOIN student_payments SP
                      ON SP.collection_id = FC.id AND SP.deleted_at IS NULL
               WHERE FC.room_id = $1 AND FC.deleted_at IS NULL
               GROUP BY FC.id, FC.title, FC.amount, FC.due_date, FC.status
               ORDER BY FC.due_date NULLS LAST, FC.id ASC""",
            room_id,
        )

        projects: List[dict] = []
        total_expected = total_paid = total_pending = 0.0
        active_count = 0
        for r in rows:
            member_count = int(r["member_count"] or 0)
            fee_amount = float(r["amount"] or 0.0)
            paid = float(r["paid_total"] or 0.0)
            expected = round(fee_amount * member_count, 2)
            pending = round(max(expected - paid, 0.0), 2)
            completion_pct = round(paid / expected * 100.0, 2) if expected > 0 else 0.0
            is_active = (r["status"] or "active") == "active"
            if is_active:
                active_count += 1
            if expected > 0:
                # ยอดรวมคิดจากโปรเจคที่ "มีเป้าหมายจริง" (มีสมาชิก) เท่านั้น
                total_expected += expected
                total_paid += paid
                total_pending += pending
            projects.append({
                "id": r["id"],
                "title": r["title"],
                "status": r["status"] or "active",
                "due_date": r["due_date"],
                "fee_amount": fee_amount,
                "member_count": member_count,
                "expected": expected,
                "paid": paid,
                "pending": pending,
                "completion_pct": completion_pct,
                "is_active": is_active,
            })

        return {
            "as_of": as_of,
            "projects": projects,
            "project_count": len(projects),
            "active_count": active_count,
            "total_expected": round(total_expected, 2),
            "total_paid": round(total_paid, 2),
            "total_pending": round(total_pending, 2),
            "collection_rate_pct": round(total_paid / total_expected * 100.0, 2) if total_expected > 0 else None,
        }

    @classmethod
    async def _fetch_accounts_receivable(cls, conn: asyncpg.Connection, room_id: int) -> dict:
        """ทะเบียนลูกหนี้แบบ Real-time: student_payments.status='pending' (ยังไม่จ่ายครบ).

        Join students + users + student_payments + fee_collections — 1 แถว = หนี้ค้าง 1 รายการ
        ของนักเรียน 1 คน. คืน {as_of, rows:[...], debtor_count, total_outstanding}.
        """
        as_of = datetime.now(THAI_TZ).date()
        rows = await conn.fetch(
            """SELECT S.id                                 AS student_id,
                      S.student_no, S.student_id            AS student_id_no,
                      U.first_name, U.last_name, U.nickname,
                      U.first_name_en, U.last_name_en, U.nickname_en,
                      FC.id          AS collection_id,
                      FC.title, FC.amount, FC.due_date, FC.status,
                      SP.id AS payment_id, SP.paid_amount,
                      (FC.amount - COALESCE(SP.paid_amount, 0)) AS outstanding
               FROM student_payments SP
               JOIN fee_collections FC ON SP.collection_id = FC.id
               JOIN students S         ON SP.student_id = S.id
               LEFT JOIN users U       ON S.user_id = U.id
               WHERE SP.deleted_at IS NULL
                 AND SP.status = 'pending'
                 AND FC.deleted_at IS NULL
                 AND FC.room_id = $1
               ORDER BY S.student_no ASC, FC.due_date ASC NULLS LAST, FC.id ASC""",
            room_id,
        )

        entries: List[dict] = []
        seen_students: set = set()
        total_outstanding = 0.0
        for r in rows:
            # ชื่อเต็ม = ชื่อ (ไทย/อังกฤษ) + นามสกุล + ชื่อเล่น — เพื่อ export ที่ละเอียด
            first = (r["first_name"] or r.get("first_name_en") or "").strip()
            last = (r["last_name"] or r.get("last_name_en") or "").strip()
            name = " ".join(p for p in (first, last) if p) or "Unknown"
            nickname = r["nickname"] or r.get("nickname_en") or ""
            if nickname:
                name += f" ({nickname})"
            outstanding = round(float(r["outstanding"] or 0.0), 2)
            seen_students.add(r["student_id"])
            total_outstanding += outstanding
            entries.append({
                "student_id": r["student_id"],
                "student_no": r["student_no"],
                "student_id_no": r["student_id_no"],
                "name": name,
                "nickname": nickname,
                "collection_id": r["collection_id"],
                "title": r["title"],
                "fee_amount": round(float(r["amount"] or 0.0), 2),
                "paid_amount": round(float(r["paid_amount"] or 0.0), 2),
                "outstanding": outstanding,
                "due_date": r["due_date"],
                "collection_status": r["status"] or "active",
            })

        return {
            "as_of": as_of,
            "rows": entries,
            "debtor_count": len(seen_students),
            "total_outstanding": round(total_outstanding, 2),
        }

    # =====================================================================
    # 📤 Export ประวัติการเงินเป็นไฟล์ Excel (.xlsx)
    # =====================================================================

    # =====================================================================
    # [ROUTER] export_transactions_excel — เลือกอ่านจาก legacy หรือ Double-Entry ตามช่วงเวลา
    # =====================================================================
    @classmethod
    async def export_transactions_excel(
        cls, pool: asyncpg.Pool, req, client_source: str, actor_identifier: str,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> io.BytesIO:
        """ส่งออกประวัติการทำรายการการเงินของห้องเป็น .xlsx ที่จัดรูปแบบสวยงาม.

        ช่วงเวลาที่รองรับ (เลือกอย่างใดอย่างหนึ่ง):
        - start_date + end_date  → ช่วงวันที่ที่กำหนด
        - month + year           → ทั้งเดือน
        - ไม่ระบุเลย             → ทุกอย่าง

        คัดเฉพาะคอลัมน์ที่ "คนอ่านเอาไปใช้ต่อได้" (ไม่มี system values เช่น
        deleted_at/transfer_group_id/slip URL) และรวมขาโอนเงินเข้าด้วยกัน
        เพื่อให้ตัวเลขรายรับ/รายจ่ายสะท้อนเงินจริงที่เข้า/ออกห้อง
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)

                # [EXPORT-ERP] ข้อมูลโปรเจคเก็บเงิน/ลูกหนี้แบบ Real-time (ณ วันที่ส่งออก) — ดึงครั้งเดียว
                # แล้วส่งต่อให้ path (legacy/v2/merged) ที่ถูกเลือกใช้สร้าง Sheet 4/5 (ไม่ขึ้นกับยุค)
                collection_register = await cls._fetch_collection_register(conn, target_room_id)
                accounts_receivable = await cls._fetch_accounts_receivable(conn, target_room_id)

                # [ROUTER] แบ่งอ่านตามยุค (หลัง CUTOFF_DATE = 2026-09-01 อ่าน journal 100%):
                #   - ทั้งช่วงก่อนเส้นตัด       → legacy (finance_transactions)
                #   - เริ่มที่/หลังเส้นตัด       → บัญชีคู่ (journal)
                #   - "ทั้งหมด" (ไม่กรอง) / คร่อมเส้น → MERGE legacy + journal
                month = getattr(req, "month", None)
                year = getattr(req, "year", None)
                start_date = getattr(req, "start_date", None)
                end_date = getattr(req, "end_date", None)

                if month is not None and year is not None:
                    # เดือนเดียวคาบเส้นไม่ได้ → เดือนก่อนเส้น = legacy, เดือนที่เส้นขึ้นไป = journal
                    if date(year, month, 1) >= CUTOFF_DATE:
                        return await cls._export_transactions_excel_v2(
                            conn=conn, room_id=target_room_id,
                            month=month, year=year, start_date=start_date, end_date=end_date,
                            client_source=client_source, actor_identifier=actor_identifier,
                            start_time=start_time,
                            reg=collection_register, ar=accounts_receivable,
                        )
                    return await cls._export_transactions_excel_legacy(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year, start_date=start_date, end_date=end_date,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                        reg=collection_register, ar=accounts_receivable,
                    )

                if end_date is not None and end_date < CUTOFF_DATE:
                    # [ROUTER] ทั้งช่วงก่อนวันที่ตัด → อ่านจากตารางเก่า
                    return await cls._export_transactions_excel_legacy(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year, start_date=start_date, end_date=end_date,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                        reg=collection_register, ar=accounts_receivable,
                    )
                if start_date is not None and start_date >= CUTOFF_DATE:
                    # [ROUTER] ขอข้อมูลหลังวันที่ตัด → อ่านจาก journal_entries/journal_lines
                    return await cls._export_transactions_excel_v2(
                        conn=conn, room_id=target_room_id,
                        month=month, year=year, start_date=start_date, end_date=end_date,
                        client_source=client_source, actor_identifier=actor_identifier,
                        start_time=start_time,
                        reg=collection_register, ar=accounts_receivable,
                    )
                # [ROUTER] คร่อมเส้นตัด / เปิดปลาย / ไม่ระบุช่วง (ทั้งหมด) → MERGE 2 ยุค
                return await cls._export_transactions_excel_merged(
                    conn=conn, room_id=target_room_id,
                    month=month, year=year, start_date=start_date, end_date=end_date,
                    client_source=client_source, actor_identifier=actor_identifier,
                    start_time=start_time,
                    reg=collection_register, ar=accounts_receivable,
                )
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def _export_transactions_excel_legacy(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        """[ROUTER-LEGACY] Logic เดิมของ export — อ่านจาก finance_transactions (Single-Entry)."""
        where_clause, period_params, period_label = cls._resolve_export_period(
            _ExportPeriodView(month=month, year=year, start_date=start_date, end_date=end_date)
        )

        room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        room_name = room["room_name"] if room else f"ห้อง #{room_id}"

        rows = await conn.fetch(
            f"""
            SELECT
                T.id, T.transaction_type, T.amount, T.description, T.recorded_by,
                T.created_at, T.transfer_group_id, T.student_payment_id,
                A.account_name, C.category_name
            FROM finance_transactions T
            LEFT JOIN finance_accounts A ON T.account_id = A.id
            LEFT JOIN finance_categories C ON T.category_id = C.id
            WHERE T.room_id = $1 AND T.deleted_at IS NULL {where_clause}
            ORDER BY T.created_at ASC, T.id ASC
            """,
            room_id, *period_params,
        )

        # ยอดคงเหลือปัจจุบันของแต่ละบัญชี (ดึงจาก finance_accounts ตรง ๆ
        # เพื่อสะท้อนยอดจริงรวม seed/เปิดบัญชี — ไม่ใช่แค่เงินที่เคลื่อนในงวดนี้)
        account_balances = await conn.fetch(
            "SELECT account_name, balance FROM finance_accounts WHERE room_id = $1 AND deleted_at IS NULL ORDER BY id",
            room_id,
        )

        final_rows = cls._consolidate_transfers([dict(r) for r in rows])
        excel_file = cls._build_finance_workbook(
            room_name=room_name, period_label=period_label,
            rows=final_rows, account_balances=[(r["account_name"], r["balance"]) for r in account_balances],
            generated_at=datetime.now(THAI_TZ),
            reg=reg, ar=ar,
        )

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                new_values={"period": period_label, "rows": len(final_rows)},
                endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
            )
        return excel_file

    # =====================================================================
    # [DOUBLE-ENTRY] _export_transactions_excel_v2 — สร้าง Excel จาก journal
    # (แปล Dr/Cr → แถว TransactionResponse แล้วใช้ _build_finance_workbook
    #  เหมือนเดิม แต่ยอดคงเหลือรายบัญชีคำนวณจาก Net Balance ของ ledger)
    # =====================================================================
    @classmethod
    async def _export_transactions_excel_v2(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        # [DOUBLE-ENTRY] แปลงช่วงเวลา → ฉลากเหมือน legacy (ปี-เดือน / ช่วงวันที่ / ทั้งหมด)
        # ⚠️ end_dt ต้องเป็นแบบ "ครอบถึง" (inclusive) เพราะ _get_transactions_v2 กรองด้วย `<= $3`
        # (ต่างจาก legacy month/year ที่ใช้ `<` แบบ exclusive) — กันรายการวันที่ 1 ของเดือนถัดไปหลุดเข้า
        if month is not None and year is not None:
            period_label = f"{year}-{month:02d}"
            start_dt = date(year, month, 1)
            end_dt = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        elif start_date is not None or end_date is not None:
            if start_date and end_date and start_date > end_date:
                raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
            if start_date and end_date:
                period_label = f"{start_date.isoformat()} ถึง {end_date.isoformat()}"
            elif start_date:
                period_label = f"ตั้งแต่วันที่ {start_date.isoformat()}"
            else:
                period_label = f"จนถึงวันที่ {end_date.isoformat()}"
            # วันที่เดียว → คร่อมทั้งวัน (inclusive อยู่แล้ว)
            start_dt = start_date or date.min
            end_dt = end_date or date.max
        else:
            period_label = "ทั้งหมด"
            start_dt, end_dt = None, None

        room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        room_name = room["room_name"] if room else f"ห้อง #{room_id}"

        # [DOUBLE-ENTRY] รายการทั้งหมด (แปลจาก journal) — เรียงตามเวลาเหมือน legacy export
        txn_result = await cls._get_transactions_v2(
            conn=conn, room_id=room_id,
            limit=100000, offset=0,
            start_date=start_dt, end_date=end_dt,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None,  # ไม่ log อีกครั้ง (export จะ log เอง)
        )
        raw_items = txn_result["items"]

        # [DOUBLE-ENTRY] จัดรูปให้ _build_finance_workbook ใช้ได้ (รายรับ/รายจ่าย/หมวด/บัญชี)
        final_rows = cls._format_v2_rows(raw_items)
        final_rows.sort(key=lambda x: (x["created_at"] or datetime.min, x["id"] or ""))

        # [DOUBLE-ENTRY] ยอดคงเหลือรายบัญชีจาก Net Balance ของ ledger สินทรัพย์
        # (SUM(debit) − SUM(credit)) — สะท้อนยอดจริงจากระบบบัญชีคู่ ไม่ใช่ finance_accounts
        balances = await conn.fetch(
            """SELECT AL.account_name,
                      (SELECT COALESCE(SUM(L.debit - L.credit), 0)
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       WHERE L.ledger_id = AL.id
                         AND JE.deleted_at IS NULL
                         AND JE.status <> 'voided') AS net_balance
               FROM accounting_ledgers AL
               WHERE AL.room_id = $1 AND AL.account_type = 'asset' AND AL.is_active = TRUE
               ORDER BY AL.id""",
            room_id,
        )

        excel_file = cls._build_finance_workbook(
            room_name=room_name, period_label=period_label,
            rows=final_rows,
            account_balances=[(r["account_name"], r["net_balance"]) for r in balances],
            generated_at=datetime.now(THAI_TZ),
            reg=reg, ar=ar,
        )

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                new_values={"period": period_label, "rows": len(final_rows)},
                endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
            )
        return excel_file

    @classmethod
    async def _export_transactions_excel_merged(
        cls, conn: asyncpg.Connection, *, room_id: int,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        client_source: str = "", actor_identifier: str = "", start_time: Optional[float] = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        """[ROUTER-MERGE] Export ที่ครอบ 2 ยุค (ขอ "ทั้งหมด" หรือช่วงคร่อมเส้นตัด):
        นำแถว legacy (เฉพาะ DATE(created_at) <= วันก่อน 1 ก.ย.) มา consolidate ขาโอน
        แล้วต่อกับแถว journal (transaction_date >= 1 ก.ย.) ที่ format แล้ว
        → ใส่ _build_finance_workbook เดียวกัน โดยยอดคงเหลือรายบัญชีใช้ ledger asset-net
        (แหล่งเดียวกับฝั่ง v2) เพราะช่วงนี้แตะข้อมูลหลังเส้นตัดแล้ว"""
        # [MERGE] ฉลากช่วงเวลา (เลียนแบบ v2 export / _resolve_inclusive_period)
        _, _, period_label = _resolve_inclusive_period(month, year, start_date, end_date)

        room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", room_id)
        room_name = room["room_name"] if room else f"ห้อง #{room_id}"

        # [MERGE] 1) ฝั่ง legacy: เฉพาะวันที่ < CUTOFF_DATE (consolidate ขาโอนภายใน subset นี้)
        legacy_end = CUTOFF_DATE - timedelta(days=1)
        params: List[Any] = [room_id, legacy_end]
        start_cond = ""
        if start_date is not None and start_date < CUTOFF_DATE:
            start_cond = " AND DATE(T.created_at) >= $3"
            params.append(start_date)
        legacy_rows = await conn.fetch(
            f"""
            SELECT
                T.id, T.transaction_type, T.amount, T.description, T.recorded_by,
                T.created_at, T.transfer_group_id, T.student_payment_id,
                A.account_name, C.category_name
            FROM finance_transactions T
            LEFT JOIN finance_accounts A ON T.account_id = A.id
            LEFT JOIN finance_categories C ON T.category_id = C.id
            WHERE T.room_id = $1 AND T.deleted_at IS NULL
              AND DATE(T.created_at) <= $2 {start_cond}
            ORDER BY T.created_at ASC, T.id ASC
            """,
            *params,
        )
        final_legacy = cls._consolidate_transfers([dict(r) for r in legacy_rows])

        # [MERGE] 2) ฝั่ง journal: วันที่ >= CUTOFF_DATE (floor start ที่ 1 ก.ย.)
        journal_start = start_date if (start_date is not None and start_date >= CUTOFF_DATE) else CUTOFF_DATE
        txn_result = await cls._get_transactions_v2(
            conn=conn, room_id=room_id,
            limit=100000, offset=0,
            start_date=journal_start, end_date=end_date,
            client_source=client_source, actor_identifier=actor_identifier,
            start_time=None,  # ไม่ log อีกครั้ง (export จะ log เอง)
        )
        final_v2 = cls._format_v2_rows(txn_result["items"])

        # [MERGE] 3) รวม + เรียงตามเวลา (normalize tz ก่อน sort)
        final_rows = final_legacy + final_v2
        final_rows.sort(key=lambda x: (_naive_thai_dt(x["created_at"]), x["id"] or ""))

        # [MERGE] 4) ยอดคงเหลือรายบัญชี = ledger asset-net (เหมือนฝั่ง v2)
        balances = await conn.fetch(
            """SELECT AL.account_name,
                      (SELECT COALESCE(SUM(L.debit - L.credit), 0)
                       FROM journal_lines L
                       JOIN journal_entries JE ON L.journal_entry_id = JE.id
                       WHERE L.ledger_id = AL.id
                         AND JE.deleted_at IS NULL
                         AND JE.status <> 'voided') AS net_balance
               FROM accounting_ledgers AL
               WHERE AL.room_id = $1 AND AL.account_type = 'asset' AND AL.is_active = TRUE
               ORDER BY AL.id""",
            room_id,
        )

        excel_file = cls._build_finance_workbook(
            room_name=room_name, period_label=period_label,
            rows=final_rows,
            account_balances=[(r["account_name"], r["net_balance"]) for r in balances],
            generated_at=datetime.now(THAI_TZ),
            reg=reg, ar=ar,
        )

        if start_time is not None:
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                room_id=room_id, user_id=None, entity_type="FINANCE_TRANSACTION", status="success",
                new_values={"period": period_label, "rows": len(final_rows)},
                endpoint_or_command="FinanceService.export_transactions_excel", execution_time_ms=exec_time
            )
        return excel_file

    @classmethod
    def _format_v2_rows(cls, items: List[dict]) -> List[dict]:
        """[DOUBLE-ENTRY] แปลงแถว TransactionResponse (จาก _get_transactions_v2)
        → แถวที่ _build_finance_workbook ใช้ (income/expense/category/account/type).

        การโอนเงินระหว่างบัญชี (มี transfer_group_id) จะแท็กเป็น "โอนเงินระหว่างบัญชี"
        + is_transfer=True → ข้ามออกจากยอดรวมในสรุป (เงินแค่ย้ายในห้อง) แต่ยังแสดง
        จำนวนเงินขาออกในแถวรายละเอียด (ตรงกับรูปแบบของ export แบบ legacy)"""
        formatted: List[dict] = []
        for t in items:
            amount = float(t["amount"] or 0.0)
            # [DOUBLE-ENTRY] _classify_journal_entry ใส่ transfer_group_id ให้บิลโอนเงิน
            # ระหว่างบัญชีสินทรัพย์เท่านั้น → ใช้เป็นตัวบ่งชี้โอนได้เลย
            if t.get("transfer_group_id") is not None:
                formatted.append({
                    "id": t.get("id"),
                    "created_at": t.get("created_at"),
                    "type": "โอนเงินระหว่างบัญชี",
                    "income": 0.0,
                    "expense": amount,
                    "description": t.get("description") or "",
                    "category": "โอนเงิน",
                    "account": t.get("account_name") or "—",
                    "recorded_by": t.get("recorded_by") or "—",
                    "is_transfer": True,
                })
            elif t["transaction_type"] == "income":
                formatted.append({
                    "id": t.get("id"),
                    "created_at": t.get("created_at"),
                    "type": "รายรับ",
                    "income": amount,
                    "expense": 0.0,
                    "description": t.get("description") or "",
                    "category": t.get("category_name") or "—",
                    "account": t.get("account_name") or "—",
                    "recorded_by": t.get("recorded_by") or "—",
                    "is_transfer": False,
                })
            else:  # expense (รายจ่ายจริง เงินออกนอกห้อง)
                formatted.append({
                    "id": t.get("id"),
                    "created_at": t.get("created_at"),
                    "type": "รายจ่าย",
                    "income": 0.0,
                    "expense": amount,
                    "description": t.get("description") or "",
                    "category": t.get("category_name") or "—",
                    "account": t.get("account_name") or "—",
                    "recorded_by": t.get("recorded_by") or "—",
                    "is_transfer": False,
                })
        return formatted

    @staticmethod
    def _resolve_export_period(req) -> tuple:
        """แปล req (FinanceExportRequest) → (where_sql, params, period_label).

        ถ้าใช้ month/year → ครอบทั้งเดือน (created_at >= วันที่ 1, < วันที่ 1 เดือนถัดไป)
        ถ้าใช้ start_date/end_date → คร่อมวันที่ (ให้ตัวเดียว → ตัวเดียวถูกบังคับ)
        ไม่ระบุเลย → ครอบทุกอย่าง (คอลัมน์ created_at ทั้งหมด)

        หมายเหตุ: ตำแหน่ง placeholder เริ่มที่ $2 เสมอ (เพราะ $1 คือ room_id ใน query หลัก)
        """
        month, year = getattr(req, "month", None), getattr(req, "year", None)
        start_date = getattr(req, "start_date", None)
        end_date = getattr(req, "end_date", None)

        if month is not None and year is not None:
            start = date(year, month, 1)
            if month == 12:
                end = date(year + 1, 1, 1)
            else:
                end = date(year, month + 1, 1)
            return " AND T.created_at >= $2 AND T.created_at < $3", [start, end], f"{year}-{month:02d}"

        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด")
            return (
                " AND DATE(T.created_at) >= $2 AND DATE(T.created_at) <= $3",
                [start_date, end_date],
                f"{start_date.isoformat()} ถึง {end_date.isoformat()}",
            )
        if start_date is not None:
            return " AND DATE(T.created_at) >= $2", [start_date], f"ตั้งแต่วันที่ {start_date.isoformat()}"
        if end_date is not None:
            return " AND DATE(T.created_at) <= $2", [end_date], f"จนถึงวันที่ {end_date.isoformat()}"
        return "", [], "ทั้งหมด"

    @staticmethod
    def _clean_transfer_desc(description: Optional[str], transfer_group_id: Optional[int]) -> str:
        """คำอธิบายรายการโอนเงิน: ตัดคำว่า 'โอนออก:'/'รับโอน:' ซ้ำออก เหลือแค่เรื่องที่โอน."""
        if not description:
            return ""
        # ขาโอนทั้งสองข้างมี transfer_group_id → ใช้คำอธิบายดิบ (มี โอนออก:/รับโอน: ข้างหน้า)
        if transfer_group_id is not None:
            return re.sub(r"^(โอนออก:|รับโอน:)\s*", "", description.strip())
        return description

    @classmethod
    def _consolidate_transfers(cls, rows: List[dict]) -> List[dict]:
        """รวมขาโอนเงิน (transfer_group_id เดียวกัน) เข้าเป็นรายการเดียว.

        ปัญหาของข้อมูลดิบ: การโอนเงินระหว่างบัญชีจะสร้าง 2 รายการ
        (ขาออก 'โอนออก: ...' จากบัญชีต้นทาง + ขาเข้า 'รับโอน: ...' เข้าบัญชีปลายทาง)
        ซึ่งถ้าใส่ลงตารางตรง ๆ จะทำให้รายรับ/รายจ่าย "เกินจริง" (เงินแค่ย้ายบัญชีในห้อง ไม่ได้ออกนอกห้อง)

        → จัดการโดยจับคู่ขาที่มี transfer_group_id เดียวกันเป็น 1 แถว
          โดยแสดงเป็น รายจ่ายต้นทาง (amount ลบ) และปล่อยให้ยอดรวมรายรับ/รายจ่ายสะท้อนเงินจริง
        """
        transfer_groups: Dict[int, dict] = {}
        regular_rows: List[dict] = []

        for r in rows:
            group_id = r.get("transfer_group_id")
            if group_id is None:
                regular_rows.append(r)
                continue
            # เลือก "ขาต้นทาง" (transaction_type = expense) เป็นตัวแทนกลุ่ม
            # เพื่อให้ account_name ในแถวชี้ไปที่บัญชีที่เงินออกจริง
            if group_id not in transfer_groups or r["transaction_type"] == "expense":
                transfer_groups[group_id] = r

        final_rows = []
        for r in regular_rows:
            final_rows.append(cls._format_row(r, is_transfer=False))
        for group_id in sorted(transfer_groups.keys()):
            leg = transfer_groups[group_id]
            final_rows.append(cls._format_row(leg, is_transfer=True))
        # ยังคงเรียงตามเวลาจริง (created_at + id)
        final_rows.sort(key=lambda x: (x["created_at"], x["id"]))
        return final_rows

    @classmethod
    def _format_row(cls, r: dict, is_transfer: bool) -> dict:
        """แปลงแถว asyncpg → dict ที่พร้อมใส่ Excel (คัดเฉพาะคอลัมน์ที่คนอ่านเอาไปใช้ต่อได้)."""
        txn_type = r.get("transaction_type")
        amount = float(r.get("amount") or 0.0)
        account_name = r.get("account_name") or "—"
        category_name = r.get("category_name") or "—"

        if is_transfer:
            return {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "type": "โอนเงินระหว่างบัญชี",
                "income": 0.0,
                "expense": amount,
                "description": cls._clean_transfer_desc(r.get("description"), r.get("transfer_group_id")),
                "category": "โอนเงิน",
                "account": account_name,
                "recorded_by": r.get("recorded_by") or "—",
                # 💡 flag ไว้ให้ _build_finance_workbook ข้ามรายการโอนออกจากยอดรวม
                # (เงินแค่ย้ายบัญชีในห้อง ไม่ใช่รายรับ/รายจ่ายจริง)
                "is_transfer": True,
            }

        if txn_type == "income":
            return {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "type": "รายรับ",
                "income": amount,
                "expense": 0.0,
                "description": r.get("description") or "",
                "category": category_name,
                "account": account_name,
                "recorded_by": r.get("recorded_by") or "—",
                "is_transfer": False,
            }
        return {
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "type": "รายจ่าย",
            "income": 0.0,
            "expense": amount,
            "description": r.get("description") or "",
            "category": category_name,
            "account": account_name,
            "recorded_by": r.get("recorded_by") or "—",
            "is_transfer": False,
        }

    @classmethod
    def _build_finance_workbook(
        cls, room_name: str, period_label: str, rows: List[dict],
        account_balances: Optional[List[tuple]] = None, generated_at: datetime = None,
        reg: Optional[dict] = None, ar: Optional[dict] = None,
    ) -> io.BytesIO:
        """สร้าง Workbook 5 แผ่นระดับ "ภาพรวมการเงินทั้งห้อง" สำหรับ User ทั่วไป / ประธาน / ครู:

          1. สรุปยอด                     — รายรับ/รายจ่าย/คงเหลือ + การเก็บเงิน-ลูกหนี้ (Real-time)
                                             + ยอดคงเหลือรายบัญชี
          2. ประวัติรายการ                — ทุกรายการ (zebra + autofilter + freeze)
          3. สรุปรายหมวดหมู่              — รวมยอดรายรับ/รายจ่ายรายหมวด
          4. สรุปโปรเจคเก็บเงิน (Fee Collections)  — เป้าหมาย/เก็บได้/ค้าง/%สำเร็จ รายโปรเจค
          5. ทะเบียนลูกหนี้ (Accounts Receivable)  — หนี้ค้างรายคน (จัดกลุ่ม block ต่อนักเรียน)

        reg/ar = ผลจาก _fetch_collection_register / _fetch_accounts_receivable (ข้อมูล Real-time
        ณ วันที่ export — ไม่ผูกงวดของ transaction). ถ้าไม่ส่ง → ใช้ค่าว่าง (sheet ว่างปลอดภัย).
        """
        if generated_at is None:
            generated_at = datetime.now(THAI_TZ)

        # 🐛 FIX: ข้ามรายการ "โอนเงินระหว่างบัญชี" ออกจากการรวมรายรับ/รายจ่าย
        # (เงินแค่ย้ายบัญชีในห้อง ไม่ได้เข้าหรือออกนอกห้อง) — เหมือน export เดิม
        non_transfer_rows = [
            r for r in rows
            if not (r.get("is_transfer") or r.get("type") == "โอนเงินระหว่างบัญชี")
        ]
        income_total = round(sum(r["income"] for r in non_transfer_rows), 2)
        expense_total = round(sum(r["expense"] for r in non_transfer_rows), 2)

        reg = reg or {}
        ar = ar or {}
        fee_projects: List[dict] = reg.get("projects") or []
        ar_rows: List[dict] = ar.get("rows") or []
        # [DETAIL] ดัชนี "รายการค้างชำระรายคน" ต่อโปรเจค — ใช้ไล่รายชื่อผู้ค้างใต้แต่ละโปรเจค (Sheet 4)
        #   เหมือนกด "ดูรายละเอียด" โปรเจคในเว็บ แต่กรองเฉพาะคนที่ยังจ่ายไม่ครบ
        pending_by_collection: Dict[int, List[dict]] = {}
        for _ar in ar_rows:
            pending_by_collection.setdefault(_ar["collection_id"], []).append(_ar)
        live_as_of = reg.get("as_of") or ar.get("as_of")
        live_label = live_as_of.strftime("%d/%m/%Y") if live_as_of else "—"

        # ---- ธีมสี (โทน Management: น้ำเงิน) ----
        HEADER_FILL = PatternFill("solid", fgColor="1D4ED8")
        TOTAL_FILL = PatternFill("solid", fgColor="CBD5E1")
        SUBTOTAL_FILL = PatternFill("solid", fgColor="DBEAFE")
        INCOME_FILL = PatternFill("solid", fgColor="D1FAE5")
        EXPENSE_FILL = PatternFill("solid", fgColor="FEE2E2")
        ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
        white_bold = Font(bold=True, color="FFFFFF")
        title_font = Font(bold=True, size=16, color="0F172A")
        money = MONEY_NUM_FMT

        def money_cell(ws, row, col, val):
            cell = ws.cell(row=row, column=col)
            if val is None:
                return cell
            cell.value = float(val)
            cell.number_format = money
            return cell

        def fill_row(ws, row, cols, fill):
            for c in cols:
                ws.cell(row=row, column=c).fill = fill

        wb = Workbook()
        # =====================================================================
        # Sheet 1: สรุปยอด
        # =====================================================================
        ws_summary = wb.active
        ws_summary.title = "สรุปยอด"
        ws_summary.sheet_view.showGridLines = False
        ws_summary.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[0]
        ws_summary.column_dimensions["A"].width = 40
        ws_summary.column_dimensions["B"].width = 26

        ws_summary["A1"] = f"สรุปการเงิน — {room_name}"
        ws_summary["A1"].font = title_font
        ws_summary["A2"] = (
            f"รอบระยะเวลา: {period_label} · สร้างเมื่อ "
            f"{generated_at.strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)"
        )
        ws_summary["A2"].font = Font(color="64748B", size=10)

        # กลุ่มรายรับ/รายจ่าย (เฉพาะงวดที่ export)
        ws_summary["A4"] = "รายรับรวม"
        ws_summary["B4"] = income_total
        ws_summary["A5"] = "รายจ่ายรวม"
        ws_summary["B5"] = expense_total
        ws_summary["A6"] = "คงเหลือ (รายรับ − รายจ่าย)"
        ws_summary["B6"] = round(income_total - expense_total, 2)
        for cell in ("A4", "B4"):
            ws_summary[cell].fill = INCOME_FILL
            ws_summary[cell].font = Font(bold=True)
        for cell in ("A5", "B5"):
            ws_summary[cell].fill = EXPENSE_FILL
            ws_summary[cell].font = Font(bold=True)
        for cell in ("A6", "B6"):
            ws_summary[cell].fill = TOTAL_FILL
            ws_summary[cell].font = Font(bold=True, size=12)
        for cell in ("B4", "B5", "B6"):
            ws_summary[cell].number_format = money

        # กลุ่มการเก็บเงิน / ลูกหนี้ (Real-time — ณ วันที่ส่งออก)
        row = 8
        sec_cell = ws_summary.cell(
            row=row, column=1,
            value=f"การเก็บเงิน / ลูกหนี้ — ข้อมูล ณ วันที่ {live_label} (Real-time)",
        )
        sec_cell.font = Font(bold=True, size=12, color="1E3A8A")
        row += 1

        rate = reg.get("collection_rate_pct")

        def summary_row(label, val, fmt=None, bold=False):
            nonlocal row
            lab = ws_summary.cell(row=row, column=1, value=label)
            lab.font = Font(bold=bold)
            vcell = money_cell(ws_summary, row, 2, val)
            if fmt:
                vcell.number_format = fmt
            row += 1

        summary_row("อัตราการเก็บเงินสำเร็จ (%)", rate, PCT_NUM_FMT if rate is not None else None, bold=True)
        summary_row("ยอดเรียกเก็บรวม (บาท)", reg.get("total_expected"), money)
        summary_row("เก็บเงินได้แล้ว (บาท)", reg.get("total_paid"), money)
        summary_row("หนี้ค้างชำระรวม — AR (บาท)", reg.get("total_pending"), money)
        summary_row("จำนวนลูกหนี้ที่ยังค้าง (คน)", ar.get("debtor_count"))
        summary_row("โปรเจคที่กำลังเก็บ (รายการ)", reg.get("active_count"))
        row += 1

        # ยอดคงเหลือรายบัญชี (จากข้อมูลงวด/ยุคที่ส่งมา)
        section = ws_summary.cell(row=row, column=1, value="ยอดคงเหลือรายบัญชี")
        section.font = Font(bold=True, size=12)
        row += 1
        for col, val in ((1, "บัญชี"), (2, "ยอดคงเหลือ (บาท)")):
            cell = ws_summary.cell(row=row, column=col, value=val)
            cell.fill = HEADER_FILL
            cell.font = white_bold
        row += 1
        for account, bal in (account_balances or []):
            ws_summary.cell(row=row, column=1, value=account)
            money_cell(ws_summary, row, 2, float(bal))
            row += 1
        if not account_balances:
            ws_summary.cell(row=row, column=1, value="(ไม่มีรายการในช่วงนี้)")
            money_cell(ws_summary, row, 2, 0.0)

        # =====================================================================
        # Sheet 2: ประวัติรายการ (หัวข้อหลัก)
        # =====================================================================
        ws_data = wb.create_sheet("ประวัติรายการ")
        ws_data.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[1]
        headers = [
            ("ลำดับ", 6), ("วันที่", 14), ("เวลา", 10), ("ประเภท", 14), ("รายรับ (บาท)", 14),
            ("รายจ่าย (บาท)", 14), ("รายการ", 42), ("หมวดหมู่", 20), ("บัญชี", 18), ("ผู้บันทึก", 16),
        ]
        ws_data.append([h[0] for h in headers])
        for idx, (_, width) in enumerate(headers, start=1):
            ws_data.column_dimensions[get_column_letter(idx)].width = width
            cell = ws_data.cell(row=1, column=idx)
            cell.fill = HEADER_FILL
            cell.font = white_bold
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for i, r in enumerate(rows, start=1):
            ts = r["created_at"]
            if ts is None:
                date_str, time_str = "", ""
            else:
                if isinstance(ts, datetime):
                    dt_local = ts.astimezone(THAI_TZ)
                else:
                    dt_local = datetime.combine(ts, dtime(0))
                date_str = dt_local.strftime("%d/%m/%Y")
                time_str = dt_local.strftime("%H:%M")
            ws_data.append([
                i, date_str, time_str, r["type"], r["income"], r["expense"],
                r["description"], r["category"], r["account"], r["recorded_by"],
            ])
            ws_data.cell(row=i + 1, column=5).number_format = money
            ws_data.cell(row=i + 1, column=6).number_format = money
            if i % 2 == 0:
                for col_idx in range(1, len(headers) + 1):
                    ws_data.cell(row=i + 1, column=col_idx).fill = ZEBRA_FILL

        ws_data.freeze_panes = "A2"
        ws_data.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws_data.max_row}"

        # =====================================================================
        # Sheet 3: สรุปรายหมวดหมู่
        # =====================================================================
        ws_cat = wb.create_sheet("สรุปรายหมวดหมู่")
        ws_cat.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[0]
        cat_headers = ["หมวดหมู่", "ประเภทรายการ", "ยอดรวม (บาท)"]
        ws_cat.append(cat_headers)
        ws_cat.column_dimensions["A"].width = 32
        ws_cat.column_dimensions["B"].width = 14
        ws_cat.column_dimensions["C"].width = 18
        for idx in range(1, len(cat_headers) + 1):
            cell = ws_cat.cell(row=1, column=idx)
            cell.fill = HEADER_FILL
            cell.font = white_bold

        cat_totals: Dict[str, dict] = {}
        for r in rows:
            # โอนเงินระหว่างบัญชีไม่ใช่หมวดรายรับ/รายจ่ายจริง → ข้าม (ไม่สร้างแถว 0.00)
            if r.get("is_transfer") or r.get("type") == "โอนเงินระหว่างบัญชี":
                continue
            key = r["category"]
            entry = cat_totals.setdefault(key, {"type": r["type"], "total": 0.0})
            if r["type"] == "รายรับ":
                entry["total"] += r["income"]
            elif r["type"] == "รายจ่าย":
                entry["total"] += r["expense"]

        for idx, (name, info) in enumerate(sorted(cat_totals.items()), start=2):
            ws_cat.cell(row=idx, column=1, value=name)
            ws_cat.cell(row=idx, column=2, value=info["type"])
            cell = money_cell(ws_cat, idx, 3, round(info["total"], 2))
            cell.number_format = money
            if idx % 2 == 0:
                fill_row(ws_cat, idx, (1, 2, 3), ZEBRA_FILL)
        if not cat_totals:
            ws_cat.cell(row=2, column=1, value="(ไม่มีรายการในช่วงนี้)")

        ws_cat.freeze_panes = "A2"
        ws_cat.auto_filter.ref = f"A1:C{ws_cat.max_row}"

        # =====================================================================
        # =====================================================================
        # Sheet 4: สรุปโปรเจคเก็บเงิน (Fee Collections) — ไล่รายชื่อผู้ค้างรายคน
        # =====================================================================
        # โครงสร้าง: title/subtitle → หัวตาราง 1 แถว → block ต่อโปรเจค
        #   block = แถว banner สรุปโปรเจค (ยอดเก็บ/ค้าง/%สำเร็จ) + รายชื่อนักเรียนที่ยังจ่ายไม่ครบ
        #   (เหมือนกด "ดูรายละเอียด" โปรเจคในเว็บ แต่กรองเฉพาะคนที่ยังค้าง) + แถวรวมยอดค้างของโปรเจค
        ws_fee = wb.create_sheet("สรุปโปรเจคเก็บเงิน (Fee)")
        ws_fee.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[2]
        detail_headers = [
            ("เลขที่", 8), ("ชื่อ-นามสกุล", 32), ("สถานะการจ่าย", 14),
            ("เรียกเก็บ/คน (บาท)", 16), ("ชำระแล้ว (บาท)", 15), ("คงค้าง (บาท)", 15),
        ]
        ncols_fee = len(detail_headers)

        def _table_title(ws, title, subtitle, ncols):
            """Title (แถว 1) + subtitle (แถว 2) merge ข้ามทุกคอลัมน์ → คืนแถว header (3)."""
            ws.sheet_view.showGridLines = False
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
            ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="0F172A")
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
            ws.cell(row=2, column=1, value=subtitle).font = Font(color="64748B", size=10)
            return 3

        def _write_header(ws, header_row, col_specs):
            for idx, (label, width) in enumerate(col_specs, start=1):
                ws.column_dimensions[get_column_letter(idx)].width = width
                cell = ws.cell(row=header_row, column=idx, value=label)
                cell.fill = HEADER_FILL
                cell.font = white_bold
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            return len(col_specs)

        def _merged_row(ws, row, ncols, text, *, fill=None, font=None, align="left"):
            """Merge A..{ncols} ในแถวเดียวแล้วใส่ข้อความ (ใช้ทำแถว banner/หมายเหตุ/แถวรวม)."""
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
            cell = ws.cell(row=row, column=1, value=text)
            if font is not None:
                cell.font = font
            cell.alignment = Alignment(horizontal=align, vertical="center")
            if fill:
                for cc in range(1, ncols + 1):
                    ws.cell(row=row, column=cc).fill = fill
            return cell

        def _money_label(val) -> str:
            return f"{float(val or 0.0):,.2f}"

        hr = _table_title(
            ws_fee, f"สรุปโปรเจคเก็บเงิน (Fee Collections) — {room_name}",
            f"รายชื่อผู้ค้างชำระรายคนใต้แต่ละโปรเจค · ข้อมูล ณ วันที่ {live_label} (Real-time) · "
            f"สร้างเมื่อ {generated_at.strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)",
            ncols_fee,
        )
        _write_header(ws_fee, hr, detail_headers)

        r = hr + 1
        grand_member = grand_expected = grand_paid = grand_pending = 0.0
        for p in fee_projects:
            member_count = int(p["member_count"] or 0)
            if member_count:
                grand_member += member_count
                grand_expected += p["expected"]
                grand_paid += p["paid"]
                grand_pending += p["pending"]

            status_label = COLLECTION_STATUS_LABELS.get(p["status"], p["status"])
            due_str = cls._fmt_date(p["due_date"])
            pending_here: List[dict] = pending_by_collection.get(p["id"], [])

            # ---- แถว banner: สรุปยอดของโปรเจค (หัว block) ----
            banner_text = (
                f'โปรเจค "{p["title"]}"  ·  {status_label}  ·  กำหนดชำระ {due_str or "—"}  ·  '
                f"สมาชิก {member_count} คน  ·  เรียกเก็บ {_money_label(p['fee_amount'])} บาท/คน  ·  "
                f"เป้าหมายรวม {_money_label(p['expected'])} บาท  ·  เก็บได้แล้ว {_money_label(p['paid'])} บาท  ·  "
                f"คงค้าง {_money_label(p['pending'])} บาท  ·  สำเร็จ {p['completion_pct']:,.2f}%"
            )
            _merged_row(
                ws_fee, r, ncols_fee, banner_text,
                fill=PatternFill("solid", fgColor="E0F2FE"),
                font=Font(bold=True, color="1E3A8A", size=11),
            )
            r += 1

            if not pending_here:
                _merged_row(
                    ws_fee, r, ncols_fee, "(ทุกคนจ่ายครบแล้วในโปรเจคนี้ 🎉)",
                    font=Font(italic=True, color="64748B", size=10),
                )
                r += 1
                continue

            # ---- รายชื่อนักเรียนที่ยังค้าง (จ่ายไม่ครบ) ----
            for b in pending_here:
                pay_label = "ทยอยจ่ายแล้ว" if float(b["paid_amount"] or 0.0) > 0 else "ยังไม่จ่าย"
                ws_fee.cell(row=r, column=1, value=b["student_no"])
                ws_fee.cell(row=r, column=2, value=b["name"])
                ws_fee.cell(row=r, column=3, value=pay_label)
                money_cell(ws_fee, r, 4, b["fee_amount"])
                money_cell(ws_fee, r, 5, b["paid_amount"])
                money_cell(ws_fee, r, 6, b["outstanding"])
                if r % 2 == 0:
                    fill_row(ws_fee, r, tuple(range(1, ncols_fee + 1)), ZEBRA_FILL)
                r += 1

            # ---- แถวรวมยอดค้างของโปรเจคนี้ (เฉพาะคนที่ยังค้าง) ----
            sub_total = round(sum(float(x["outstanding"] or 0.0) for x in pending_here), 2)
            _merged_row(
                ws_fee, r, 5,
                f"รวมยอดคงค้างของคนที่ยังจ่ายไม่ครบในโปรเจคนี้ ({len(pending_here)} คน)",
                fill=SUBTOTAL_FILL, font=Font(bold=True, color="1E3A8A"),
            )
            money_cell(ws_fee, r, 6, sub_total).font = Font(bold=True, color="1E3A8A")
            r += 1

        if not fee_projects:
            _merged_row(ws_fee, r, ncols_fee, "(ยังไม่มีโปรเจคเก็บเงินในห้องนี้)",
                        font=Font(color="64748B"))
            r += 1
        else:
            # แถวรวมทั้งสิ้น (ภาพรวมทั้งห้อง)
            total_text = (
                f"รวมทั้งสิ้น {len(fee_projects)} โปรเจค  ·  สมาชิกรวม {int(grand_member)} คน  ·  "
                f"เรียกเก็บรวม {_money_label(grand_expected)} บาท  ·  เก็บได้รวม {_money_label(grand_paid)} บาท  ·  "
                f"คงค้างรวม {_money_label(grand_pending)} บาท"
            )
            _merged_row(ws_fee, r, ncols_fee, total_text,
                        fill=TOTAL_FILL, font=Font(bold=True, color="0F172A"))
            r += 1
        ws_fee.freeze_panes = f"A{hr + 1}"
        ws_fee.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_fee)}{r - 1}"

        # =====================================================================
        # Sheet 5: ทะเบียนลูกหนี้ (Accounts Receivable) — รายละเอียดหนี้ค้างรายคน
        # =====================================================================
        ws_ar = wb.create_sheet("ทะเบียนลูกหนี้ (AR)")
        ws_ar.sheet_properties.tabColor = MANAGEMENT_TAB_COLORS[3]
        ar_headers = [
            ("เลขที่", 8), ("รหัสนักเรียน", 13), ("ชื่อ-นามสกุล", 30), ("รายการที่ค้างชำระ", 30),
            ("กำหนดชำระ", 12), ("ยอดเรียกเก็บ (บาท)", 15), ("ชำระแล้ว (บาท)", 14),
            ("ยอดคงค้าง (บาท)", 15), ("สถานะโปรเจค", 12),
        ]
        ncols_ar = len(ar_headers)
        hr = _table_title(
            ws_ar, f"ทะเบียนลูกหนี้ (Accounts Receivable) — {room_name}",
            f"หนี้ค้างชำระรายคน ณ วันที่ {live_label} (Real-time) · เฉพาะรายการที่ยังจ่ายไม่ครบ "
            f"(รวมโปรเจคที่ปิดไปแล้ว) · สร้างเมื่อ {generated_at.strftime('%d/%m/%Y %H:%M')} น. (เวลาไทย)",
            ncols_ar,
        )
        _write_header(ws_ar, hr, ar_headers)

        r = hr + 1
        i = 0
        while i < len(ar_rows):
            block = []
            cur_student = ar_rows[i]["student_id"]
            while i < len(ar_rows) and ar_rows[i]["student_id"] == cur_student:
                block.append(ar_rows[i])
                i += 1
            first = True
            for b in block:
                if first:
                    ws_ar.cell(row=r, column=1, value=b["student_no"])
                    ws_ar.cell(row=r, column=2, value=b["student_id_no"] or "—")
                    ws_ar.cell(row=r, column=3, value=b["name"])
                due_str = cls._fmt_date(b["due_date"])
                ws_ar.cell(row=r, column=4, value=b["title"])
                ws_ar.cell(row=r, column=5, value=due_str)
                money_cell(ws_ar, r, 6, b["fee_amount"])
                money_cell(ws_ar, r, 7, b["paid_amount"])
                money_cell(ws_ar, r, 8, b["outstanding"])
                ws_ar.cell(row=r, column=9, value=COLLECTION_STATUS_LABELS.get(b["collection_status"], b["collection_status"]))
                if r % 2 == 0:
                    fill_row(ws_ar, r, tuple(range(1, ncols_ar + 1)), ZEBRA_FILL)
                first = False
                r += 1
            # แถวย่อย: รวมหนี้รายคน (ค้างกี่รายการ/ยอดเท่าไร)
            subtotal = round(sum(float(b["outstanding"] or 0.0) for b in block), 2)
            _merged_row(
                ws_ar, r, 7,
                f"รวมหนี้ของ {block[0]['name']} — ค้าง {len(block)} รายการ",
                fill=SUBTOTAL_FILL, font=Font(bold=True, color="1E3A8A"),
            )
            money_cell(ws_ar, r, 8, subtotal).font = Font(bold=True, color="1E3A8A")
            r += 1

        if not ar_rows:
            _merged_row(ws_ar, r, ncols_ar, "(ไม่มีลูกหนี้ค้างชำระ — เก็บเงินครบทุกคนแล้ว 🎉)",
                        font=Font(color="64748B"))
            r += 1
        else:
            grand_total = float(ar.get("total_outstanding") or 0.0)
            _merged_row(
                ws_ar, r, 7,
                f"รวมลูกหนี้ทั้งสิ้น ({ar.get('debtor_count')} คน)",
                fill=TOTAL_FILL, font=Font(bold=True, color="0F172A"),
            )
            money_cell(ws_ar, r, 8, grand_total).font = Font(bold=True, color="0F172A")
            r += 1
        ws_ar.freeze_panes = f"A{hr + 1}"
        ws_ar.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_ar)}{r - 1}"

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def _fmt_date(value) -> str:
        """วันที่ → 'dd/mm/yyyy' (เวลาไทย) หรือ '' ถ้าไม่มีค่า."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.astimezone(THAI_TZ).strftime("%d/%m/%Y")
        return value.strftime("%d/%m/%Y")

    # =====================================================================
    # [DOUBLE-ENTRY] export_journal_excel — Full Financial Audit Report (GAAP/IFRS)
    # =====================================================================
    @staticmethod
    def _journal_reference(reference_type: Optional[str], reference_id: Optional[str]) -> str:
        """สร้างข้อความ Reference จาก reference_type + reference_id (เช่น 'โอนเงิน #42')."""
        if not reference_type:
            return f"#{reference_id}" if reference_id not in (None, "") else "—"
        label = REFERENCE_TYPE_LABELS.get(reference_type, reference_type)
        if reference_id not in (None, ""):
            return f"{label} #{reference_id}"
        return label

    @classmethod
    async def _fetch_general_ledger(
        cls, conn: asyncpg.Connection, *, room_id: int,
        start_dt: Optional[datetime] = None, end_dt: Optional[datetime] = None,
    ) -> List[dict]:
        """สมุดบัญชีแยกประเภท (GL): ต่อ ledger → ยอดยกมา / เดบิต-เครดิตในงวด / ยอดยกไป.

        - opening (ก่อน start_dt) = เคลื่อนไหวสะสมก่อนงวด (ถ้าไม่ระบุ start = ว่าง)
        - period  (ใน [start_dt, end_dt]) = เคลื่อนไหวของงวด
        - closing (ยอดยกไป) = opening + period (คำนวณฝั่ง Python, ตาม normal side)
        ไม่นับ journal ที่ void / soft-delete (เงื่อนไขเดียวกับ reconcile/balance)
        """
        rows = await conn.fetch(
            """SELECT AL.id AS ledger_id, AL.account_code, AL.account_name, AL.account_type,
                      COALESCE(OP.op_dr, 0)  AS op_dr,
                      COALESCE(OP.op_cr, 0)  AS op_cr,
                      COALESCE(PER.per_dr, 0) AS per_dr,
                      COALESCE(PER.per_cr, 0) AS per_cr
               FROM accounting_ledgers AL
               LEFT JOIN (
                   SELECT L.ledger_id,
                          SUM(L.debit)  AS op_dr,
                          SUM(L.credit) AS op_cr
                   FROM journal_lines L
                   JOIN journal_entries JE ON L.journal_entry_id = JE.id
                   WHERE JE.deleted_at IS NULL AND JE.status <> 'voided'
                     AND ($2::timestamptz IS NOT NULL AND JE.transaction_date < $2)
                   GROUP BY L.ledger_id
               ) OP ON OP.ledger_id = AL.id
               LEFT JOIN (
                   SELECT L.ledger_id,
                          SUM(L.debit)  AS per_dr,
                          SUM(L.credit) AS per_cr
                   FROM journal_lines L
                   JOIN journal_entries JE ON L.journal_entry_id = JE.id
                   WHERE JE.deleted_at IS NULL AND JE.status <> 'voided'
                     AND ($2::timestamptz IS NULL OR JE.transaction_date >= $2)
                     AND ($3::timestamptz IS NULL OR JE.transaction_date <= $3)
                   GROUP BY L.ledger_id
               ) PER ON PER.ledger_id = AL.id
               WHERE AL.room_id = $1 AND AL.is_active = TRUE
               ORDER BY AL.account_code NULLS LAST, AL.id""",
            room_id, start_dt, end_dt,
        )

        result: List[dict] = []
        for r in rows:
            op_dr = float(r["op_dr"])
            op_cr = float(r["op_cr"])
            per_dr = float(r["per_dr"])
            per_cr = float(r["per_cr"])
            typ = r["account_type"]
            signed = lambda dr, cr: (dr - cr) if typ in ("asset", "expense") else (cr - dr)  # noqa: E731
            result.append({
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "account_type": typ,
                "opening_balance": round(signed(op_dr, op_cr), 2),
                "period_debit": round(per_dr, 2),
                "period_credit": round(per_cr, 2),
                "closing_balance": round(signed(op_dr + per_dr, op_cr + per_cr), 2),
            })
        return result

    @classmethod
    async def _fetch_trial_balance_ledgers(
        cls, conn: asyncpg.Connection, *, room_id: int, as_of_dt: Optional[datetime] = None,
    ) -> dict:
        """งบทดลอง: ยอด YTD (≤ as_of_dt) ของทุก ledger active. เลียนแบบ get_trial_balance.

        คืน {"ledgers": [...], "total_debit", "total_credit", "is_balanced"}
        ใช้สร้าง Sheet งบทดลอง + ต่อยอด Balance Sheet (สินทรัพย์/ทุน/กำไรสะสม)
        """
        if as_of_dt is not None:
            date_filter = "AND JE.transaction_date <= $2"
            params: List[Any] = [room_id, as_of_dt]
        else:
            date_filter = ""
            params = [room_id]

        rows = await conn.fetch(
            f"""SELECT AL.id AS ledger_id, AL.account_code, AL.account_name, AL.account_type,
                       COALESCE(NET.total_debit, 0)  AS total_debit,
                       COALESCE(NET.total_credit, 0) AS total_credit
                FROM accounting_ledgers AL
                LEFT JOIN (
                    SELECT L.ledger_id,
                           SUM(L.debit)  AS total_debit,
                           SUM(L.credit) AS total_credit
                    FROM journal_lines L
                    JOIN journal_entries JE ON L.journal_entry_id = JE.id
                    WHERE JE.deleted_at IS NULL
                      AND JE.status <> 'voided'
                      {date_filter}
                    GROUP BY L.ledger_id
                ) NET ON NET.ledger_id = AL.id
                WHERE AL.room_id = $1 AND AL.is_active = TRUE
                ORDER BY AL.account_code NULLS LAST, AL.id""",
            *params,
        )

        ledgers: List[dict] = []
        grand_debit = grand_credit = 0.0
        for r in rows:
            dr = float(r["total_debit"])
            cr = float(r["total_credit"])
            balance = (dr - cr) if r["account_type"] in ("asset", "expense") else (cr - dr)
            grand_debit += dr
            grand_credit += cr
            ledgers.append({
                "ledger_id": r["ledger_id"],
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "account_type": r["account_type"],
                "total_debit": round(dr, 2),
                "total_credit": round(cr, 2),
                "balance": round(balance, 2),
            })
        return {
            "ledgers": ledgers,
            "total_debit": round(grand_debit, 2),
            "total_credit": round(grand_credit, 2),
            "is_balanced": abs(grand_debit - grand_credit) < 0.01,
        }

    @classmethod
    async def _fetch_income_statement_rows(
        cls, conn: asyncpg.Connection, *, room_id: int,
        start_dt: Optional[datetime] = None, end_dt: Optional[datetime] = None,
    ) -> dict:
        """งบกำไรขาดทุนของงวด [start_dt, end_dt] — เลียนแบบ get_income_statement.

        ไม่นับ opening_balance (คือทุน ไม่ใช่รายได้ของงวด). คืน revenues/expenses/totals/net.
        """
        def _fetch_rows(account_type: str):
            # revenue: กำไรฝั่ง Cr−Dr / expense: ค่าใช้จ่ายฝั่ง Dr−Cr
            diff_expr = "(L.credit - L.debit)" if account_type == "revenue" else "(L.debit - L.credit)"
            return conn.fetch(
                f"""SELECT AL.account_name,
                          COALESCE(SUM({diff_expr}), 0) AS total
                   FROM journal_lines L
                   JOIN journal_entries JE ON L.journal_entry_id = JE.id
                   JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                   WHERE JE.room_id = $1 AND JE.deleted_at IS NULL
                     AND JE.status <> 'voided'
                     AND JE.reference_type <> 'opening_balance'
                     AND AL.account_type = $4
                     AND ($2::timestamptz IS NULL OR JE.transaction_date >= $2)
                     AND ($3::timestamptz IS NULL OR JE.transaction_date <= $3)
                   GROUP BY AL.account_name
                   ORDER BY total DESC""",
                room_id, start_dt, end_dt, account_type,
            )

        rev_rows = await _fetch_rows("revenue")
        exp_rows = await _fetch_rows("expense")

        revenues = [{"account_name": r["account_name"], "amount": float(r["total"])} for r in rev_rows]
        expenses = [{"account_name": r["account_name"], "amount": float(r["total"])} for r in exp_rows]
        total_revenue = sum(x["amount"] for x in revenues)
        total_expense = sum(x["amount"] for x in expenses)
        net_income = total_revenue - total_expense
        return {
            "revenues": revenues,
            "expenses": expenses,
            "total_revenue": round(total_revenue, 2),
            "total_expense": round(total_expense, 2),
            "net_income": round(net_income, 2),
            "margin_pct": round(net_income / total_revenue * 100.0, 2) if total_revenue else None,
        }

    @classmethod
    def _compose_balance_sheet(cls, tb: dict, period_net_income: float, as_of_str: str) -> dict:
        """สร้างโครงงบแสดงฐานะการเงินจากงบทดลอง (YTD ≤ as_of).

        สมการที่พิสูจน์: สินทรัพย์ = หนี้สิน(0) + ส่วนของเจ้าของ + กำไรสะสมถึงวันที่
        โดยกำไรสะสม = Σ(revenue) − Σ(expense) สะสมนับจากเริ่มบัญชีคู่ (2026-09-01).
        period_net_income = กำไร/ขาดทุนสุทธิของ *งวดที่ขอ* (จากงบกำไรขาดทุน) — เก็บไว้เป็น memo
        เพื่อให้ผู้ตรวจเทียบ งบกำไรขาดทุน ↔ งบดุล ได้ชัดเจน
        """
        assets: List[dict] = []
        equities: List[dict] = []
        retained = 0.0
        assets_total = equity_total = 0.0

        for lg in tb["ledgers"]:
            typ = lg["account_type"]
            if typ == "asset":
                assets.append(lg)
                assets_total += lg["balance"]
            elif typ == "equity":
                equities.append(lg)
                equity_total += lg["balance"]
            elif typ == "revenue":
                retained += lg["balance"]      # revenue balance = Cr−Dr (กำไร)
            elif typ == "expense":
                retained -= lg["balance"]      # expense balance = Dr−Cr → ลบออกจากกำไร

        retained = round(retained, 2)
        assets_total = round(assets_total, 2)
        equity_total = round(equity_total, 2)
        total_equity_side = round(equity_total + retained, 2)

        return {
            "as_of": as_of_str,
            "assets": assets,
            "assets_total": assets_total,
            "liability_total": 0.0,
            "equities": equities,
            "equity_total": equity_total,
            "retained_earnings": retained,
            "total_equity_side": total_equity_side,
            "is_balanced": abs(assets_total - total_equity_side) < 0.01,
            "period_net_income": round(period_net_income, 2),
        }

    @classmethod
    async def export_journal_excel(
        cls, pool: asyncpg.Pool, *, client_source: str, actor_identifier: str,
        month: Optional[int] = None, year: Optional[int] = None,
        start_date: Optional[date] = None, end_date: Optional[date] = None,
        server_id: Optional[int] = None, room_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> io.BytesIO:
        """ส่งออก "Full Financial Audit Report" (GAAP/IFRS) ของห้องเป็น .xlsx สำหรับนักบัญชี.

        Workbook 6 แผ่น:
          Financial Dashboard → สมุดรายวันทั่วไป (พร้อม Audit Trail) → สมุดบัญชีแยกประเภท (GL)
          → งบทดลอง (Trial Balance) → งบกำไรขาดทุน → งบแสดงฐานะการเงิน
        ข้อมูลระดับนี้ (GL/TB/PL) อ่านจาก journal_entries/journal_lines/accounting_ledgers
        → มีผลเฉพาะตั้งแต่ 2026-09-01 (ข้อมูลก่อนหน้าเป็นยุค Single-Entry) — ใส่ note ในไฟล์.

        ช่วงเวลาที่รองรับ (เหมือน export เดิม): month+year / start_date+end_date / ทั้งหมด.
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                # 🛡️ สมาชิกห้องดูได้ (transparency) แต่ต้องเป็นสมาชิกห้องนี้เท่านั้น (กันข้ามห้อง)
                await require_member(conn, target_room_id, user_id)

                start_dt, end_dt, period_label = _resolve_inclusive_period(
                    month, year, start_date, end_date
                )

                # [CLAMP] งบชุดนี้อ่านจาก journal ล้วน → ดัน start ขึ้นเป็น 1 ก.ย. ถ้าขอช่วงก่อนหน้า
                start_dt, end_dt, clamped, _empty = _clamp_to_cutoff(start_dt, end_dt)
                note = ""
                if clamped:
                    period_label = f"{period_label} (ข้อมูลเริ่ม 2026-09-01)"
                    note = "ช่วงก่อน 2026-09-01 ไม่มีข้อมูลในบัญชีคู่ ถูกตัดออกจากรายงานนี้"
                elif start_dt is None and end_dt is None:
                    period_label = "ทั้งหมด (ตั้งแต่ขึ้นระบบบัญชีคู่ 2026-09-01)"

                room = await conn.fetchrow("SELECT room_name FROM rooms WHERE id = $1", target_room_id)
                room_name = room["room_name"] if room else f"ห้อง #{target_room_id}"

                # ขอบเขต datetime (ครอบถึงทั้งวัน) สำหรับ query GL/TB/PL
                lower_dt = datetime.combine(start_dt, dtime.min) if start_dt else None
                upper_dt = datetime.combine(end_dt, dtime(23, 59, 59)) if end_dt else None
                # PL เปิดต้นที่เส้นตัดเสมอ (ไม่มีข้อมูลก่อนหน้า) และไม่นับ opening_balance
                pl_start = lower_dt or datetime.combine(CUTOFF_DATE, dtime.min)

                # ---------- 1) สมุดรายวันทั่วไป (พร้อม Audit Trail จาก metadata) ----------
                conditions = ["JE.room_id = $1", "JE.deleted_at IS NULL", "JE.status <> 'voided'"]
                params: List[Any] = [target_room_id]
                idx = 2
                if start_dt is not None:
                    conditions.append(f"DATE(JE.transaction_date) >= ${idx}")
                    params.append(start_dt)
                    idx += 1
                if end_dt is not None:
                    conditions.append(f"DATE(JE.transaction_date) <= ${idx}")
                    params.append(end_dt)
                    idx += 1

                lines = await conn.fetch(
                    f"""
                    SELECT JE.id AS entry_id,
                           JE.reference_type, JE.reference_id,
                           JE.description, JE.transaction_date, JE.recorded_by,
                           JE.metadata,
                           L.id AS line_id, L.debit, L.credit, L.line_description,
                           AL.account_code, AL.account_name, AL.account_type
                    FROM journal_entries JE
                    JOIN journal_lines L ON L.journal_entry_id = JE.id
                    JOIN accounting_ledgers AL ON L.ledger_id = AL.id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY JE.transaction_date ASC, JE.id ASC, L.id ASC
                    """,
                    *params,
                )

                # กลุ่มหัวบิล: วันที่/Reference/คำอธิบาย/ผู้บันทึก แสดงเฉพาะบรรทัดแรก
                journal_rows: List[dict] = []
                prev_entry_id: Optional[str] = None
                for ln in lines:
                    entry_id = str(ln["entry_id"])
                    is_first_line = entry_id != prev_entry_id
                    # asyncpg อาจคืน jsonb เป็น dict หรือ JSON string ตาม codec → normalize ให้เป็น dict
                    raw_meta = ln["metadata"]
                    if isinstance(raw_meta, str):
                        try:
                            meta = json.loads(raw_meta)
                        except (ValueError, TypeError):
                            meta = {}
                    else:
                        meta = raw_meta or {}
                    base = {
                        "account_code": ln["account_code"] or "",
                        "account_name": ln["account_name"] or "—",
                        "debit": float(ln["debit"] or 0.0),
                        "credit": float(ln["credit"] or 0.0),
                        # [AUDIT-TRAIL] ทุกบรรทัดมี trace ของหัวบิล (metadata จากโมดูลต้นทาง)
                        "module": ln["reference_type"] or "",
                        "doc_id": ln["reference_id"],
                        "legacy_tx_id": meta.get("legacy_transaction_id"),
                        "transfer_group_id": meta.get("transfer_group_id"),
                        "student_payment_id": meta.get("student_payment_id"),
                        "journal_entry_id": entry_id,
                        "journal_line_id": int(ln["line_id"]),
                    }
                    if is_first_line:
                        journal_rows.append({
                            **base,
                            "date_time": ln["transaction_date"],
                            "reference": cls._journal_reference(ln["reference_type"], ln["reference_id"]),
                            "description": ln["description"] or "",
                            "recorded_by": ln["recorded_by"] or "—",
                        })
                        prev_entry_id = entry_id
                    else:
                        journal_rows.append({
                            **base,
                            "date_time": None, "reference": None,
                            "description": None, "recorded_by": None,
                        })

                # ---------- 2) GL / TB / PL / Balance Sheet / Dashboard ----------
                gl_rows = await cls._fetch_general_ledger(
                    conn, room_id=target_room_id, start_dt=lower_dt, end_dt=upper_dt,
                )
                tb = await cls._fetch_trial_balance_ledgers(
                    conn, room_id=target_room_id, as_of_dt=upper_dt,
                )
                pl = await cls._fetch_income_statement_rows(
                    conn, room_id=target_room_id, start_dt=pl_start, end_dt=upper_dt,
                )
                # ข้อมูลลูกหนี้/โปรเจคแบบ Real-time (สำหรับ Dashboard)
                reg = await cls._fetch_collection_register(conn, target_room_id)
                ar = await cls._fetch_accounts_receivable(conn, target_room_id)

                if end_dt is not None:
                    as_of_str = cls._fmt_date(end_dt)
                else:
                    today_label = datetime.now(THAI_TZ).strftime("%d/%m/%Y")
                    as_of_str = f"ถึงข้อมูลล่าสุด ({today_label})"
                balance_sheet = cls._compose_balance_sheet(tb, pl["net_income"], as_of_str)

                assets_total = balance_sheet["assets_total"]
                dashboard = {
                    "as_of": as_of_str,
                    "net_worth": assets_total,
                    "total_revenue": pl["total_revenue"],
                    "total_expense": pl["total_expense"],
                    "net_income": pl["net_income"],
                    "margin_pct": pl["margin_pct"],
                    "ar_total": ar.get("total_outstanding"),
                    "ar_debtors": ar.get("debtor_count"),
                    "collection_rate_pct": reg.get("collection_rate_pct"),
                    "ledger_count": len(tb["ledgers"]),
                    "journal_entry_count": len(journal_rows),
                }

                excel_file = cls._build_accounting_workbook(
                    room_name=room_name, period_label=period_label,
                    generated_at=datetime.now(THAI_TZ),
                    journal_rows=journal_rows, gl_rows=gl_rows, tb=tb, pl=pl,
                    balance_sheet=balance_sheet, dashboard=dashboard, note=note,
                )

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                    room_id=target_room_id, user_id=None, entity_type="ACCOUNTING_JOURNAL", status="success",
                    new_values={"period": period_label, "journal_lines": len(journal_rows)},
                    endpoint_or_command="FinanceService.export_journal_excel", execution_time_ms=exec_time
                )
                return excel_file
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="EXPORT", actor_identifier=actor_identifier, client_source=client_source,
                        room_id=target_room_id, user_id=None, entity_type="ACCOUNTING_JOURNAL", status="failed",
                        error_detail=str(e), endpoint_or_command="FinanceService.export_journal_excel",
                        execution_time_ms=exec_time
                    )
            except Exception:
                pass
            raise e

    @classmethod
    def _build_accounting_workbook(
        cls, *, room_name: str, period_label: str, generated_at: datetime,
        journal_rows: List[dict], gl_rows: List[dict], tb: dict, pl: dict,
        balance_sheet: dict, dashboard: dict, note: str = "",
    ) -> io.BytesIO:
        """สร้าง Workbook 6 แผ่น "Full Financial Audit Report" สำหรับนักบัญชี/สรรพากร.

        สี Tab เป็นโทน Accounting (เขียวเข้ม/ม่วง) ต่างจาก Management export (น้ำเงิน)
        เพื่อให้แยกหมวดรายงานชัดเจน.
        """
        HEADER_FILL = PatternFill("solid", fgColor="047857")     # เขียวเข้ม (accounting)
        TOTAL_FILL = PatternFill("solid", fgColor="D1D5DB")
        SECTION_FILL = PatternFill("solid", fgColor="D1FAE5")
        SUBTOTAL_FILL = PatternFill("solid", fgColor="E0E7FF")
        ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
        white_bold = Font(bold=True, color="FFFFFF")
        money = MONEY_NUM_FMT

        def money_cell(ws, row, col, val, bold=False):
            cell = ws.cell(row=row, column=col)
            if val is not None:
                cell.value = float(val)
                cell.number_format = money
            if bold:
                cell.font = Font(bold=True)
            return cell

        def fill_row(ws, row, cols, fill):
            for c in cols:
                ws.cell(row=row, column=c).fill = fill

        def title_rows(ws, title, subtitle, ncols):
            ws.sheet_view.showGridLines = False
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
            ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=16, color="0F172A")
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
            ws.cell(row=2, column=1, value=subtitle).font = Font(color="64748B", size=10)
            return 3

        def write_header(ws, header_row, col_specs):
            for col_idx, (label, width) in enumerate(col_specs, start=1):
                ws.column_dimensions[get_column_letter(col_idx)].width = width
                cell = ws.cell(row=header_row, column=col_idx, value=label)
                cell.fill = HEADER_FILL
                cell.font = white_bold
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            return len(col_specs)

        subtype_label = {"asset": "สินทรัพย์", "liability": "หนี้สิน", "equity": "ทุน",
                         "revenue": "รายได้", "expense": "ค่าใช้จ่าย"}

        def fmt(val):
            if val is None:
                return "—"
            if isinstance(val, float):
                return f"{val:,.2f}"
            return val

        wb = Workbook()

        # =====================================================================
        # Sheet 1: Financial Dashboard
        # =====================================================================
        ws_dash = wb.active
        ws_dash.title = "Financial Dashboard"
        ws_dash.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[0]
        ws_dash.column_dimensions["A"].width = 42
        ws_dash.column_dimensions["B"].width = 26
        _generated = generated_at.strftime("%d/%m/%Y %H:%M")
        ws_dash["A1"] = f"Financial Dashboard — {room_name}"
        ws_dash["A1"].font = Font(bold=True, size=16, color="0F172A")
        ws_dash["A2"] = (
            f"รอบ: {period_label} · ณ {dashboard['as_of']} · "
            f"สร้างเมื่อ {_generated} น. (เวลาไทย)"
        )
        ws_dash["A2"].font = Font(color="64748B", size=10)

        ws_dash["A4"] = "ภาพรวมความมั่งคั่ง (Net Worth)"
        ws_dash["A4"].font = Font(bold=True, size=12, color="065F46")
        ws_dash["A5"] = "สินทรัพย์รวม (Total Assets)"
        money_cell(ws_dash, 5, 2, dashboard["net_worth"], bold=True)
        ws_dash["A6"] = "รายได้รวม (งวด)"
        money_cell(ws_dash, 6, 2, dashboard["total_revenue"])
        ws_dash["A7"] = "ค่าใช้จ่ายรวม (งวด)"
        money_cell(ws_dash, 7, 2, dashboard["total_expense"])
        ws_dash["A8"] = "กำไร/ขาดทุนสุทธิของงวด (Net Income)"
        money_cell(ws_dash, 8, 2, dashboard["net_income"], bold=True)
        ws_dash["A9"] = "อัตรากำไร (Net Margin)"
        if dashboard["margin_pct"] is not None:
            ws_dash["B9"] = dashboard["margin_pct"]
            ws_dash["B9"].number_format = PCT_NUM_FMT
        else:
            ws_dash["B9"] = "—"

        ws_dash["A11"] = "การเรียกเก็บเงิน / ลูกหนี้ (Real-time)"
        ws_dash["A11"].font = Font(bold=True, size=12, color="065F46")
        ws_dash["A12"] = "อัตราการเก็บเงินสำเร็จ (%)"
        if dashboard["collection_rate_pct"] is not None:
            ws_dash["B12"] = dashboard["collection_rate_pct"]
            ws_dash["B12"].number_format = PCT_NUM_FMT
        else:
            ws_dash["B12"] = "—"
        ws_dash["A13"] = "ยอดหนี้ค้างชำระรวม — AR (บาท)"
        money_cell(ws_dash, 13, 2, dashboard["ar_total"])
        ws_dash["A14"] = "จำนวนลูกหนี้ (คน)"
        ws_dash["B14"] = dashboard["ar_debtors"]

        ws_dash["A16"] = "ข้อมูลบัญชีคู่ (Double-Entry)"
        ws_dash["A16"].font = Font(bold=True, size=12, color="065F46")
        ws_dash["A17"] = "จำนวนบัญชี (Ledgers)"
        ws_dash["B17"] = dashboard["ledger_count"]
        ws_dash["A18"] = "จำนวนบรรทัดสมุดรายวัน (Journal Lines)"
        ws_dash["B18"] = dashboard["journal_entry_count"]

        note_row = 20
        if note:
            ncell = ws_dash.cell(row=note_row, column=1, value=f"หมายเหตุ: {note}")
            ncell.font = Font(color="B45309", size=10, italic=True)
            note_row += 1
        if balance_sheet["as_of"].startswith("ถึงข้อมูลล่าสุด"):
            ncell = ws_dash.cell(row=note_row, column=1, value="หมายเหตุ: งบการเงินบัญชีคู่เริ่มนับตั้งแต่ 2026-09-01")
            ncell.font = Font(color="64748B", size=10, italic=True)
        # ความสมดุล (Dr=Cr ของระบบ)
        ws_dash["B5"].fill = SECTION_FILL

        # =====================================================================
        # Sheet 2: สมุดรายวันทั่วไป (General Journal) พร้อม Audit Trail
        # =====================================================================
        ws_j = wb.create_sheet("สมุดรายวัน (General Journal)")
        ws_j.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[1]
        j_headers = [
            ("วันที่", 12), ("เวลา", 8), ("Reference", 16), ("คำอธิบาย", 38),
            ("รหัสบัญชี", 10), ("ชื่อบัญชี", 24), ("เดบิต (บาท)", 14), ("เครดิต (บาท)", 14),
            ("ผู้บันทึก", 16),
            # ---- Audit Trail (Metadata / Trace) ----
            ("โมดูล (reference_type)", 18), ("Doc ID (reference_id)", 12),
            ("Legacy TX ID", 12), ("Transfer Group", 12), ("Student Payment", 12),
            ("Journal Entry ID", 38), ("Journal Line ID", 10),
        ]
        ncols_j = len(j_headers)
        hr = title_rows(
            ws_j, f"สมุดรายวันทั่วไป (General Journal) — {room_name}",
            f"รอบ: {period_label} · สร้างเมื่อ {_generated} น. (เวลาไทย)"
            + (" · " + note if note else ""),
            ncols_j,
        )
        write_header(ws_j, hr, j_headers)

        def _fmt_j_datetime(v):
            if v is None:
                return "", ""
            dt_local = v.astimezone(THAI_TZ)
            return dt_local.strftime("%d/%m/%Y"), dt_local.strftime("%H:%M")

        r = hr + 1
        for jr in journal_rows:
            date_str, time_str = _fmt_j_datetime(jr.get("date_time"))
            ws_j.cell(row=r, column=1, value=date_str or None)
            ws_j.cell(row=r, column=2, value=time_str or None)
            ws_j.cell(row=r, column=3, value=jr.get("reference"))
            ws_j.cell(row=r, column=4, value=jr.get("description"))
            ws_j.cell(row=r, column=5, value=jr.get("account_code"))
            ws_j.cell(row=r, column=6, value=jr.get("account_name"))
            dcell = money_cell(ws_j, r, 7, jr["debit"] if jr["debit"] else None)
            ccell = money_cell(ws_j, r, 8, jr["credit"] if jr["credit"] else None)
            ws_j.cell(row=r, column=9, value=jr.get("recorded_by"))
            # Audit trail (ทุกบรรทัด)
            ws_j.cell(row=r, column=10, value=jr.get("module") or None)
            ws_j.cell(row=r, column=11, value=jr.get("doc_id") or None)
            ws_j.cell(row=r, column=12, value=jr.get("legacy_tx_id"))
            ws_j.cell(row=r, column=13, value=jr.get("transfer_group_id"))
            ws_j.cell(row=r, column=14, value=jr.get("student_payment_id"))
            ws_j.cell(row=r, column=15, value=jr.get("journal_entry_id"))
            ws_j.cell(row=r, column=16, value=jr.get("journal_line_id"))
            # บรรทัดแรกของแต่ละบิล → ตัวหนาหัวข้อ
            if jr.get("description") is not None:
                for col in (3, 4, 9):
                    ws_j.cell(row=r, column=col).font = Font(bold=True)
            if (r - hr) % 2 == 0:
                fill_row(ws_j, r, tuple(range(1, ncols_j + 1)), ZEBRA_FILL)
            r += 1

        if not journal_rows:
            ws_j.cell(row=r, column=4, value="(ไม่มีรายการในช่วงนี้)")
            r += 1

        # แถวรวม (Dr = Cr เสมอ)
        debit_total = round(sum(float(x.get("debit") or 0.0) for x in journal_rows), 2)
        credit_total = round(sum(float(x.get("credit") or 0.0) for x in journal_rows), 2)
        ws_j.cell(row=r, column=1, value="รวมทั้งสิ้น").font = Font(bold=True)
        d_t = money_cell(ws_j, r, 7, debit_total, bold=True)
        c_t = money_cell(ws_j, r, 8, credit_total, bold=True)
        fill_row(ws_j, r, tuple(range(1, ncols_j + 1)), TOTAL_FILL)
        ws_j.freeze_panes = f"A{hr + 1}"
        ws_j.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_j)}{ws_j.max_row}"

        # =====================================================================
        # Sheet 3: สมุดบัญชีแยกประเภท (General Ledger)
        # =====================================================================
        ws_gl = wb.create_sheet("สมุดบัญชีแยกประเภท (GL)")
        ws_gl.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[2]
        gl_headers = [
            ("รหัสบัญชี", 10), ("ชื่อบัญชี", 26), ("ประเภท", 13),
            ("ยอดยกมา (บาท)", 16), ("เดบิต (บาท)", 14), ("เครดิต (บาท)", 14), ("ยอดยกไป (บาท)", 16),
        ]
        ncols_gl = len(gl_headers)
        hr = title_rows(
            ws_gl, f"สมุดบัญชีแยกประเภท (General Ledger) — {room_name}",
            f"รอบ: {period_label} · ยอดยกมา = สะสมก่อนงวด, ยอดยกไป = ยอดคงเหลือบัญชี · "
            f"สร้างเมื่อ {_generated} น.",
            ncols_gl,
        )
        write_header(ws_gl, hr, gl_headers)
        r = hr + 1
        for row_no, gl in enumerate(gl_rows, start=1):
            ws_gl.cell(row=r, column=1, value=gl["account_code"])
            ws_gl.cell(row=r, column=2, value=gl["account_name"])
            ws_gl.cell(row=r, column=3, value=ACCOUNT_TYPE_LABELS.get(gl["account_type"], gl["account_type"]))
            money_cell(ws_gl, r, 4, gl["opening_balance"])
            money_cell(ws_gl, r, 5, gl["period_debit"])
            money_cell(ws_gl, r, 6, gl["period_credit"])
            money_cell(ws_gl, r, 7, gl["closing_balance"], bold=True)
            if row_no % 2 == 0:
                fill_row(ws_gl, r, tuple(range(1, ncols_gl + 1)), ZEBRA_FILL)
            r += 1
        if not gl_rows:
            ws_gl.cell(row=r, column=2, value="(ยังไม่มีบัญชี/รายการในระบบบัญชีคู่ของห้องนี้)")
            r += 1
        else:
            sum_op = round(sum(x["opening_balance"] for x in gl_rows), 2)
            sum_dr = round(sum(x["period_debit"] for x in gl_rows), 2)
            sum_cr = round(sum(x["period_credit"] for x in gl_rows), 2)
            sum_cl = round(sum(x["closing_balance"] for x in gl_rows), 2)
            ws_gl.cell(row=r, column=2, value="รวมทั้งสิ้น").font = Font(bold=True)
            money_cell(ws_gl, r, 4, sum_op, bold=True)
            money_cell(ws_gl, r, 5, sum_dr, bold=True)
            money_cell(ws_gl, r, 6, sum_cr, bold=True)
            money_cell(ws_gl, r, 7, sum_cl, bold=True)
            fill_row(ws_gl, r, tuple(range(1, ncols_gl + 1)), TOTAL_FILL)
        ws_gl.freeze_panes = f"A{hr + 1}"
        ws_gl.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_gl)}{ws_gl.max_row}"

        # =====================================================================
        # Sheet 4: งบทดลอง (Trial Balance)
        # =====================================================================
        ws_tb = wb.create_sheet("งบทดลอง (Trial Balance)")
        ws_tb.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[3]
        tb_headers = [
            ("รหัสบัญชี", 10), ("ชื่อบัญชี", 26), ("ประเภท", 13),
            ("ยอดรวมเดบิต (บาท)", 16), ("ยอดรวมเครดิต (บาท)", 16), ("คงเหลือ (บาท)", 16),
        ]
        ncols_tb = len(tb_headers)
        hr = title_rows(
            ws_tb, f"งบทดลอง (Trial Balance) — {room_name}",
            f"ณ {dashboard['as_of']} · YTD ตั้งแต่เริ่มบัญชีคู่ 2026-09-01 · สร้างเมื่อ {_generated} น.",
            ncols_tb,
        )
        write_header(ws_tb, hr, tb_headers)
        r = hr + 1
        for row_no, lg in enumerate(tb["ledgers"], start=1):
            ws_tb.cell(row=r, column=1, value=lg["account_code"])
            ws_tb.cell(row=r, column=2, value=lg["account_name"])
            ws_tb.cell(row=r, column=3, value=ACCOUNT_TYPE_LABELS.get(lg["account_type"], lg["account_type"]))
            money_cell(ws_tb, r, 4, lg["total_debit"])
            money_cell(ws_tb, r, 5, lg["total_credit"])
            money_cell(ws_tb, r, 6, lg["balance"])
            if row_no % 2 == 0:
                fill_row(ws_tb, r, tuple(range(1, ncols_tb + 1)), ZEBRA_FILL)
            r += 1
        if not tb["ledgers"]:
            ws_tb.cell(row=r, column=2, value="(ไม่มีรายการ — ข้อมูลเริ่มหลัง 2026-09-01)")
            r += 1
        # แถว "รวมทั้งสิ้น" — พิสูจน์ Dr = Cr สมดุล
        ws_tb.cell(row=r, column=1, value="รวมทั้งสิ้น").font = Font(bold=True)
        money_cell(ws_tb, r, 4, tb["total_debit"], bold=True)
        money_cell(ws_tb, r, 5, tb["total_credit"], bold=True)
        ws_tb.cell(row=r, column=6, value="✅ สมดุล (Dr = Cr)" if tb["is_balanced"] else "❌ ไม่สมดุล")
        ws_tb.cell(row=r, column=6).font = Font(bold=True, color="047857" if tb["is_balanced"] else "B91C1C")
        fill_row(ws_tb, r, tuple(range(1, ncols_tb + 1)), TOTAL_FILL)
        ws_tb.freeze_panes = f"A{hr + 1}"
        ws_tb.auto_filter.ref = f"A{hr}:{get_column_letter(ncols_tb)}{ws_tb.max_row}"

        # =====================================================================
        # Sheet 5: งบกำไรขาดทุน (Income Statement)
        # =====================================================================
        ws_pl = wb.create_sheet("งบกำไรขาดทุน (Income Statement)")
        ws_pl.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[4]
        ws_pl.column_dimensions["A"].width = 6
        ws_pl.column_dimensions["B"].width = 40
        ws_pl.column_dimensions["C"].width = 22
        ws_pl["A1"] = f"งบกำไรขาดทุน (Income Statement) — {room_name}"
        ws_pl["A1"].font = Font(bold=True, size=16, color="0F172A")
        ws_pl["A2"] = f"รอบ: {period_label} · สร้างเมื่อ {_generated} น. (เวลาไทย) · (ไม่นับยอดยกมา)"
        ws_pl["A2"].font = Font(color="64748B", size=10)

        ws_pl["A4"] = "รายได้ (Revenue)"
        ws_pl["A4"].font = Font(bold=True, size=12, color="047857")
        hr = 5
        for rev in pl["revenues"]:
            ws_pl.cell(row=hr, column=2, value=rev["account_name"])
            money_cell(ws_pl, hr, 3, rev["amount"])
            hr += 1
        ws_pl.cell(row=hr, column=2, value="รวมรายได้").font = Font(bold=True)
        money_cell(ws_pl, hr, 3, pl["total_revenue"], bold=True)
        fill_row(ws_pl, hr, (1, 2, 3), SECTION_FILL)
        hr += 2

        ws_pl.cell(row=hr, column=1, value="ค่าใช้จ่าย (Expense)")
        ws_pl.cell(row=hr, column=1).font = Font(bold=True, size=12, color="B91C1C")
        hr += 1
        for exp in pl["expenses"]:
            ws_pl.cell(row=hr, column=2, value=exp["account_name"])
            money_cell(ws_pl, hr, 3, exp["amount"])
            hr += 1
        ws_pl.cell(row=hr, column=2, value="รวมค่าใช้จ่าย").font = Font(bold=True)
        money_cell(ws_pl, hr, 3, pl["total_expense"], bold=True)
        fill_row(ws_pl, hr, (1, 2, 3), SUBTOTAL_FILL)
        hr += 2

        ws_pl.cell(row=hr, column=2, value="กำไร/ขาดทุนสุทธิ (Net Income)")
        ws_pl.cell(row=hr, column=2).font = Font(bold=True, size=12)
        money_cell(ws_pl, hr, 3, pl["net_income"], bold=True)
        fill_row(ws_pl, hr, (1, 2, 3), TOTAL_FILL)
        hr += 1
        if pl["margin_pct"] is not None:
            m = ws_pl.cell(row=hr, column=3, value=pl["margin_pct"])
            m.number_format = PCT_NUM_FMT

        # =====================================================================
        # Sheet 6: งบแสดงฐานะการเงิน (Balance Sheet)
        # =====================================================================
        ws_bs = wb.create_sheet("งบแสดงฐานะการเงิน (BS)")
        ws_bs.sheet_properties.tabColor = ACCOUNTING_TAB_COLORS[5]
        ws_bs.column_dimensions["A"].width = 6
        ws_bs.column_dimensions["B"].width = 42
        ws_bs.column_dimensions["C"].width = 22
        ws_bs["A1"] = f"งบแสดงฐานะการเงิน (Balance Sheet) — {room_name}"
        ws_bs["A1"].font = Font(bold=True, size=16, color="0F172A")
        ws_bs["A2"] = (
            f"ณ {balance_sheet['as_of']} · สมการ: สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสม · "
            f"สร้างเมื่อ {_generated} น."
        )
        ws_bs["A2"].font = Font(color="64748B", size=10)

        def _bs_section_row(ws, row, label):
            ws.cell(row=row, column=2, value=label).font = Font(bold=True, size=12, color="065F46")

        row_idx = 4
        _bs_section_row(ws_bs, row_idx, "สินทรัพย์ (Assets)")
        row_idx += 1
        for a in balance_sheet["assets"]:
            ws_bs.cell(row=row_idx, column=2, value=f"  {a['account_name']} ({a['account_code']})")
            money_cell(ws_bs, row_idx, 3, a["balance"])
            row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="รวมสินทรัพย์").font = Font(bold=True)
        money_cell(ws_bs, row_idx, 3, balance_sheet["assets_total"], bold=True)
        fill_row(ws_bs, row_idx, (1, 2, 3), SECTION_FILL)
        row_idx += 2

        _bs_section_row(ws_bs, row_idx, "หนี้สิน (Liabilities)")
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="  (ระบบยังไม่มีหนี้สิน)")
        money_cell(ws_bs, row_idx, 3, 0.0)
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="รวมหนี้สิน").font = Font(bold=True)
        money_cell(ws_bs, row_idx, 3, 0.0, bold=True)
        fill_row(ws_bs, row_idx, (1, 2, 3), SUBTOTAL_FILL)
        row_idx += 2

        _bs_section_row(ws_bs, row_idx, "ส่วนของเจ้าของ (Equity)")
        row_idx += 1
        for eq in balance_sheet["equities"]:
            ws_bs.cell(row=row_idx, column=2, value=f"  {eq['account_name']} ({eq['account_code']})")
            money_cell(ws_bs, row_idx, 3, eq["balance"])
            row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="  กำไรสะสมถึงวันที่ (Retained Earnings)")
        money_cell(ws_bs, row_idx, 3, balance_sheet["retained_earnings"])
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="รวมส่วนของเจ้าของ").font = Font(bold=True)
        money_cell(ws_bs, row_idx, 3, balance_sheet["total_equity_side"], bold=True)
        fill_row(ws_bs, row_idx, (1, 2, 3), TOTAL_FILL)
        row_idx += 2

        ws_bs.cell(row=row_idx, column=2, value="ตรวจสอบสมดุล (Assets = Liab + Equity + Retained)")
        ws_bs.cell(row=row_idx, column=2).font = Font(bold=True, color="0F172A")
        ok = balance_sheet["is_balanced"]
        ws_bs.cell(row=row_idx, column=3, value="✅ สมดุล" if ok else "❌ ไม่สมดุล")
        ws_bs.cell(row=row_idx, column=3).font = Font(bold=True, color="047857" if ok else "B91C1C")
        row_idx += 1
        ws_bs.cell(row=row_idx, column=2, value="หมายเหตุ: กำไรสุทธิของงวด (ตามงบกำไรขาดทุน)")
        ws_bs.cell(row=row_idx, column=2).font = Font(color="64748B", size=10, italic=True)
        money_cell(ws_bs, row_idx, 3, balance_sheet["period_net_income"])

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output
