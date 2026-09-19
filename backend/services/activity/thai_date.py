"""จัดรูปแบบวันเวลาแบบไทย (พ.ศ.) สำหรับ Excel export ของกิจกรรม

แยกเป็นโมดูลกลางเพราะ **ทั้ง export เดี่ยวและ export รวมต้องใช้** — ถ้าไว้เป็น
staticmethod บน mixin ตัวใดตัวหนึ่ง อีกตัวจะต้องพึ่ง MRO ซึ่งเปราะ
"""
from datetime import date, datetime
from typing import Any, Optional

from .constants import THAI_MONTH_NAMES, THAI_TZ

BUDDHIST_ERA_OFFSET = 543


def format_buddhist_date(value: Any) -> str:
    """date/datetime → '1 ตุลาคม 2569' (พ.ศ. = ค.ศ. + 543)

    ค่าที่ไม่ใช่ date/datetime คืน `str(value)` ตรง ๆ (พฤติกรรมเดิมของ
    `ExportMixin._format_buddhist_date` — ห้ามเปลี่ยน ไม่งั้นเทสเดิมพัง)
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return str(value)
    return f"{value.day} {THAI_MONTH_NAMES[value.month - 1]} {value.year + BUDDHIST_ERA_OFFSET}"


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    """สตริง ISO-8601 → datetime; คืน None ถ้าไม่ใช่ ISO (ไม่เดาจากรูปร่าง)

    ใช้ `datetime.fromisoformat` ของ py3.12 ซึ่งรับทั้ง `2026-10-01T13:00`,
    `2026-10-01 13:00:00`, `...+07:00` และ `...Z`
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _is_date_only(text: str) -> bool:
    """'2026-10-01' → True ; '2026-10-01T13:00' / '2026-10-01 13:00' → False

    จำเป็นเพราะ `datetime.fromisoformat('2026-10-01')` สำเร็จ (ได้เที่ยงคืน)
    ⇒ ถ้าไม่แยกก่อน จะเติม '00:00 น.' ให้ค่าที่ผู้ใช้กรอกแค่วันที่
    """
    return "T" not in text and " " not in text and len(text) == 10


def _render(dt: datetime) -> str:
    """'1 ตุลาคม 2569 13:00 น.' — วันไม่เติมศูนย์หน้า, ชั่วโมง/นาทีเติมสองหลัก"""
    # 🔴 naive = เวลานาฬิกาไทยอยู่แล้ว (ค่ามาจาก <input type="datetime-local"> ของผู้ใช้ไทย)
    #    ⇒ ห้าม .astimezone() บนค่า naive ตรง ๆ เด็ดขาด (บทเรียน timezone ใน docs/skills.md)
    #    ค่าที่มี tzinfo มาแล้วเท่านั้นจึงจะถูกเลื่อนเข้าเวลาไทย
    if dt.tzinfo is not None:
        dt = dt.astimezone(THAI_TZ)
    return (
        f"{dt.day} {THAI_MONTH_NAMES[dt.month - 1]} {dt.year + BUDDHIST_ERA_OFFSET} "
        f"{dt.hour:02d}:{dt.minute:02d} น."
    )


def format_thai_datetime(value: Any) -> str:
    """แปลงค่า 'วันที่/เวลา' ที่เก็บรายคน → ข้อความไทยที่อ่านออก

    | อินพุต                                   | ผล                                    |
    |------------------------------------------|---------------------------------------|
    | `datetime` มี tzinfo                     | เลื่อนเป็นเวลาไทยแล้วจัดรูปแบบ         |
    | `datetime` naive                         | ถือเป็นเวลานาฬิกาไทย **ไม่เลื่อน**      |
    | `date` (ไม่ใช่ datetime)                 | `format_buddhist_date`                 |
    | สตริง ISO ที่มีเวลา                       | `1 ตุลาคม 2569 13:00 น.`               |
    | สตริง ISO ที่เป็นวันที่ล้วน               | `1 ตุลาคม 2569`                        |
    | สตริงที่ parse ไม่ได้ / None / ชนิดอื่น   | **คืนค่าเดิมไม่แตะ**                    |

    ข้อสุดท้ายสำคัญ: ฟิลด์เหล่านี้เป็น free text ได้ (เช่น `check_in_time` ที่เก็บ
    "13:00" หรือ "หลังเลิกเรียน") ⇒ ห้ามทำค่าที่อ่านไม่ออกให้พังหรือหายไป
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _render(value)
    if isinstance(value, date):
        return format_buddhist_date(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        parsed = parse_iso_datetime(text)
        if parsed is None:
            return value  # free text — คืนเดิม
        if _is_date_only(text):
            return format_buddhist_date(parsed)
        return _render(parsed)
    return str(value)
