"""Module-level helper functions สำหรับ finance (cutoff / time normalize / period resolve)"""
from datetime import date, datetime, time as dtime, timedelta
from typing import Optional

from .constants import THAI_TZ, CUTOFF_DATE

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
