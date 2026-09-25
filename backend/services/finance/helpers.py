"""Module-level helper functions สำหรับ finance (cutoff / time normalize / period resolve)"""
import json
import zlib
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional

from .constants import THAI_TZ, CUTOFF_DATE


def _metadata_to_dict(raw: Any) -> dict:
    """[JSONB] แปลงค่า `journal_entries.metadata` ที่อ่านจาก asyncpg ให้เป็น dict เสมอ.

    ⚠️ asyncpg **ไม่ได้**ลง type codec สำหรับ jsonb ไว้ (grep `set_type_codec` ทั้ง
       backend/ ไม่พบเลย) ⇒ คอลัมน์ jsonb ถูกคืนกลับมาเป็น **str ดิบ**
       เช่น `'{"legacy_transaction_id": 502}'` — **ไม่ใช่ dict**

    ⇒ โค้ดที่เขียนว่า `if not isinstance(metadata, dict): metadata = {}` จะ **ทิ้งค่าจริง
       ทั้งก้อนอย่างเงียบ ๆ** แล้วตกไปใช้ fallback (บั๊ก 2026-09-14: ปุ่ม "ยกเลิกรายการ"
       ส่ง id ติดลบไป backend ⇒ "ไม่พบรายการธุรกรรมนี้" ทั้งที่ id จริงอยู่ใน DB)

    ท่าเดียวกับที่ repo นี้ทำถูกอยู่แล้ว 3 ที่ — `activity/base.py:_parse_metadata`,
    `finance/export.py` (`raw_meta`) และ `finance/receipts.py`
    ⚠️ ที่ต้องมีสำเนาเป็นของตัวเองเพราะยังไม่มี helper กลางใน `core/` และการ import
       ข้ามโมดูล (finance → activity) ผิดชั้นสถาปัตยกรรม
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _legacy_id_from_journal(metadata: Any, journal_uuid: str) -> int:
    """[DOUBLE-ENTRY] สังเคราะห์ TransactionResponse.id จาก journal.

    ระบบเดิม (frontend + revert_transaction) อ้างอิงธุรกรรมด้วย finance_transactions.id
    ซึ่ง journal เก็บไว้ใน metadata ('legacy_transaction_id' หรือ 'transfer_group_id').
    - ถ้ามี → คืนค่า int นั้น (revert ได้จริง)
    - ถ้าไม่มี (เช่น opening_balance) → คืนค่าลบที่ derived จาก UUID (คอลัมน์ไม่ซ้ำกัน,
      แต่ไม่สามารถใช้ revert ได้ — ตรงกับธรรมชาติของยอดยกมาที่ไม่ใช่ธุรกรรมรายการ)

    ⚠️ `metadata` รับได้ทั้ง dict และ str — **ห้ามแก้กลับไปเป็น `isinstance(..., dict)`
       แล้วทิ้งค่า** (ดูเหตุผลใน `_metadata_to_dict`)
    """
    metadata = _metadata_to_dict(metadata)
    for key in ("legacy_transaction_id", "transfer_group_id"):
        val = metadata.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    # fallback: id ลบที่ **คงที่** จาก UUID (กันหน้าจอ key ซ้ำ)
    #
    # 🔴 ห้ามใช้ `hash()` ของ Python — `hash()` ของ str ถูกใส่ salt แบบสุ่ม **ต่อโปรเซส**
    #    (PYTHONHASHSEED) ⇒ แถวเดียวกันได้ id คนละค่ากันในแต่ละ replica / หลัง restart
    #    ⇒ เลขบนหน้าจอเปลี่ยนเองโดยที่ข้อมูลไม่เปลี่ยน (วัดจริงบน staging จาก UUID เดียวกัน:
    #      1376437036645411758 · -4318364185880035763 · -3882699260063488080)
    #    `zlib.crc32` ให้ค่าเดิมเสมอไม่ว่าโปรเซสไหน และยังได้ช่วงค่าเดิม
    #    (-(2**31-1) .. -1) ⇒ ยังติดลบเสมอ ไม่มีทางชนกับ id จริงที่เป็นบวก
    #
    # 🔴 L5 (ผลตรวจระบบ 2026-09-23): เดิมปิดท้ายด้วย
    #        except Exception: return -1
    #    ⇒ **ทุกแถวที่ล้มเหลวได้ id เดียวกันคือ -1** ซึ่งคือ "key ซ้ำ" ที่ fallback นี้
    #      ถูกสร้างขึ้นมาเพื่อกันตั้งแต่แรก (ดูบรรทัดบน) ⇒ หน้าจอ React ได้ key ซ้ำ
    #      แล้วแสดงผลผิดแถว — อาการที่แย่กว่าการไม่มี fallback เสียอีก
    #
    #    ⇒ ทำให้การเข้ารหัส **ไม่มีทางล้มเหลว** แทนการมีสาขาสำรองที่ให้ค่าคงที่
    #      `errors="replace"` รับ lone surrogate ได้ (`.encode("utf-8")` ตรง ๆ โยน
    #      `UnicodeEncodeError: surrogates not allowed`) ⇒ ไม่ต้องมี `try` เลย
    #      และไม่มี dead code ซ่อนอยู่
    #    ⚠️ `str()` ปลอดภัย: `journal_uuid` ประกาศเป็น `str` และผู้เรียกส่ง UUID/None มา
    #       ซึ่ง `str()` แปลงได้เสมอ (ไม่เรียก `__str__` ที่ผู้ใช้นิยามเอง)
    digest = zlib.crc32(str(journal_uuid).encode("utf-8", errors="replace"))
    return -(digest % (2**31 - 1) + 1)


# =====================================================================================
# [TIMEZONE] คอลัมน์ TIMESTAMP (naive) ในโมดูลการเงิน — เก็บ "เวลา UTC" ไม่ใช่เวลาไทย
# =====================================================================================
# คอลัมน์กลุ่มนี้ถูกเขียนด้วย `NOW()` / `CURRENT_TIMESTAMP` ซึ่งคืน `timestamptz`
# แล้ว **ถูกแปลงเป็น TimeZone ของ session (= UTC) ก่อนเก็บลงคอลัมน์ naive**
# ⇒ ค่าที่อ่านกลับมาคือ "เวลา UTC แบบไม่มี tzinfo" ไม่ใช่เวลาไทยและไม่ใช่ aware
#
# ⚠️ ห้ามเรียก `.astimezone(THAI_TZ)` ตรง ๆ กับค่า naive
#    เพราะ Python จะตีความว่าเป็น **เวลาท้องถิ่นของเครื่องที่รันโค้ด**
#    → container ที่ TZ=UTC ให้ผล "ถูกโดยบังเอิญ" แต่เครื่อง dev ที่ TZ=Asia/Bangkok
#      จะได้ผลผิดไป 7 ชั่วโมง ⇒ บั๊กที่มองไม่เห็นบน CI และโผล่บนเครื่องนักพัฒนา
#    ✅ ต้อง `.replace(tzinfo=timezone.utc)` **ก่อน** แล้วจึง `.astimezone(THAI_TZ)`
#
# ฝั่ง SQL ก็มีกฎคู่กัน: เทียบขอบเขตเวลาไทยกับคอลัมน์ naive ให้ "unwrapp" ฝั่ง parameter
#    `T.created_at >= ($2::timestamptz AT TIME ZONE 'UTC')`
# โดยส่ง `_thai_day_start(...)` (aware) เข้าไปเป็น $2 — ได้ค่า naive UTC ที่เทียบกันได้
# วิธีนี้ (ก) ไม่พึ่ง TimeZone ของ session (ข) ยังใช้ index ได้ เพราะเป็นการเทียบช่วงตรง ๆ
# ทางเลือกที่ห้ามใช้: `DATE(T.created_at) >= $2` — `DATE()` ไม่แปลง tz จริง แต่ค่าที่เก็บ
# เป็น UTC อยู่แล้ว จึงได้ "วันที่แบบ UTC" ซึ่งเป็นคนละปฏิทินกับเวลาไทย
# =====================================================================================
def _naive_utc_to_thai(v: Optional[datetime]) -> Optional[datetime]:
    """แปลง naive datetime ที่เก็บเป็น UTC wall-clock → tz-aware เวลาไทย."""
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(THAI_TZ)


def _naive_utc_to_thai_naive(v: Optional[datetime]) -> Optional[datetime]:
    """เหมือน `_naive_utc_to_thai` แต่ถอด tzinfo ออก — สำหรับ sort/เทียบกับค่า naive อื่น."""
    r = _naive_utc_to_thai(v)
    return r.replace(tzinfo=None) if r is not None else None


def _as_utc(v: Optional[datetime]) -> Optional[datetime]:
    """ติดป้าย UTC ให้ค่า naive ที่อ่านจากคอลัมน์ TIMESTAMP (เก็บเป็น UTC wall-clock).

    ใช้กับ **ค่า datetime ที่จะส่งออก API** — Pydantic จะ serialize เป็น "+00:00"
    แล้ว client แปลงเป็นเวลาไทยได้ถูกต้อง

    ⚠️ ถ้าปล่อยค่า naive ออกไป JSON จะเป็น `"2026-09-01T03:00:00"` (ไม่มี offset)
       และ **JavaScript ตีความ ISO ที่ไม่มี offset เป็นเวลาท้องถิ่นของเบราว์เซอร์**
       (`new Date(...)`) ⇒ ผู้ใช้ในไทยเห็นเวลาคลาดเคลื่อน 7 ชั่วโมง
       ทั้งที่ frontend ระบุ `timeZone: 'Asia/Bangkok'` ไว้แล้วก็ตาม
       (นี่คือเหตุผลที่ `TransactionResponse.created_at` / `StudentPaymentDetail.paid_at`
        ต้องเป็น tz-aware เสมอ — ฝั่ง journal เป็น aware อยู่แล้ว ฝั่ง legacy ต้องเติมที่นี่)
    """
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def _naive_thai_dt(v) -> datetime:
    """[DOUBLE-ENTRY] ปรับค่าเวลาให้เป็น datetime "naive" ในโซน Asia/Bangkok ก่อนนำไป sort/เทียบ.

    ฝั่ง legacy เก็บ `created_at` เป็น TIMESTAMP (naive) ที่เป็น **เวลา UTC** (ดูคำอธิบาย
    บล็อกด้านบน) ขณะที่ฝั่ง journal เก็บ `transaction_date` เป็น timestamptz (aware)
    → merge 2 ยุคต้อง normalize ให้เป็น "เวลาไทยแบบ naive" เหมือนกัน ไม่งั้น
    (ก) เทียบ naive กับ aware จะ TypeError และ
    (ข) ถ้าไม่ติดป้าย UTC ก่อน รายการจะถูกเรียงผิดตำแหน่งไป 7 ชั่วโมง
    """
    if v is None:
        return datetime.min
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return _naive_utc_to_thai_naive(v)
        return v.astimezone(THAI_TZ).replace(tzinfo=None)
    if isinstance(v, date):
        return datetime.combine(v, dtime(0))
    return datetime.min


# [TIMEZONE] ขอบเขตวันแบบ tz-aware ในโซนไทย — ใช้ทุกครั้งที่เทียบกับคอลัมน์ timestamptz
#
# ⚠️ ห้ามสร้าง datetime แบบ naive (ไม่มี tzinfo) มาเทียบกับ `journal_entries.transaction_date`
#    เพราะ asyncpg เข้ารหัส naive datetime เป็น **เวลาท้องถิ่นของเครื่องที่รันโค้ด** (ไม่ใช่ UTC)
#    → ใน container ที่ TZ=UTC ค่า `datetime(2026,9,1,23,59,59)` กลายเป็น 2026-09-02 06:59:59
#      ตามเวลาไทย ⇒ งบของวันที่ 1 ก.ย. แอบกินข้อมูลถึงเช้าวันที่ 2 ก.ย.
#    ส่วน TZ=Asia/Bangkok กลับ "ถูกโดยบังเอิญ" → บั๊กนี้จึงไม่โผล่ตอนรันบนเครื่อง dev
#    ผลคือรายงานเดียวกันให้ตัวเลขต่างกันตาม TZ ของ container ซึ่งเป็นความผิดพลาดที่ตรวจยากที่สุด
def _thai_day_start(d: date) -> datetime:
    """ต้นวันของ d ตามเวลาไทย (00:00:00+07:00) — tz-aware.

    ใช้กับเงื่อนไข `>= $n` เพื่อให้ครอบทั้งวันของ d
    """
    return datetime.combine(d, dtime.min, tzinfo=THAI_TZ)


def _thai_day_end(d: date) -> datetime:
    """ปลายวันของ d ตามเวลาไทย (23:59:59.999999+07:00) — tz-aware.

    ใช้กับเงื่อนไข `<= $n` เพื่อให้ครอบทั้งวันของ d (ใช้ dtime.max ไม่ใช่ 23:59:59
    เพื่อไม่ให้รายการที่เกิดวินาทีสุดท้ายของวันหลุดออกจากรายงาน)
    """
    return datetime.combine(d, dtime.max, tzinfo=THAI_TZ)


def _thai_next_day_start(d: date) -> datetime:
    """ต้นวันของ d+1 ตามเวลาไทย — ขอบบนแบบ **ไม่รวม** สำหรับเงื่อนไข `< $n`."""
    return datetime.combine(d + timedelta(days=1), dtime.min, tzinfo=THAI_TZ)


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
