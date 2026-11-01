"""Pydantic schemas ของตั้งค่าห้อง (`app_settings`) — เริ่มที่ quiet hours"""

from pydantic import BaseModel, Field

# รูปแบบเดียวกับ `_HHMM_RE` ใน services/app_settings_service.py
_HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
_HHMM_DESCRIPTION = "รูปแบบ HH:MM (00:00–23:59) เวลาไทย"


class QuietHoursResponse(BaseModel):
    enabled: bool
    start: str
    end: str


class QuietHoursUpdate(BaseModel):
    """ทั้งสามฟิลด์ส่งมาทุกครั้ง (ไม่ใช่ PATCH) — UI มีสวิตช์ + สองช่องเวลาอยู่ด้วยกัน"""

    enabled: bool = True
    start: str = Field(..., pattern=_HHMM_PATTERN, description=_HHMM_DESCRIPTION)
    end: str = Field(..., pattern=_HHMM_PATTERN, description=_HHMM_DESCRIPTION)
