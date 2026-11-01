"""Pydantic schemas ของปีการศึกษา + เทอม (P5)

⚠️ `start_date`/`end_date` เป็น `date` ไม่ใช่ `str` — กติกาเดียวกับทั้งระบบ
(ส่ง `str` เข้า service แล้วไปเรียก `.toordinal()`/เปรียบเทียบกับ DATE จะได้ 500
แทน 400 ที่อ่านรู้เรื่อง)

ช่วงที่รับได้ของ `year_be` ตรวจซ้ำที่ service (`MIN_YEAR_BE`..`MAX_YEAR_BE`) —
Pydantic ตรวจแค่ชนิด เพื่อให้ข้อความบอก "น่าจะพิมพ์ ค.ศ. มา" มาจากที่เดียว
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class AcademicTermOut(BaseModel):
    id: int
    name: str
    start_date: date
    end_date: date
    is_current: bool = False


class AcademicYearOut(BaseModel):
    id: int
    year_be: int
    name: Optional[str] = None
    start_date: date
    end_date: date
    is_current: bool = False
    terms: list[AcademicTermOut] = Field(default_factory=list)


class AcademicPeriodsResponse(BaseModel):
    years: list[AcademicYearOut] = Field(default_factory=list)
    current_year_id: Optional[int] = Field(None, description="ไม่มีปีปัจจุบัน = null (สถิติไม่กรอง)")
    current_term_id: Optional[int] = None


class AcademicYearCreate(BaseModel):
    year_be: int = Field(description="ปี พ.ศ. เช่น 2569")
    name: Optional[str] = Field(None, description="ชื่อที่แสดง เช่น 'ปีการศึกษา 2569'")
    start_date: date
    end_date: date
    is_current: bool = Field(False, description="ตั้งเป็นปีปัจจุบันทันที (ปลดปีเดิมให้อัตโนมัติ)")


class AcademicYearUpdate(BaseModel):
    """ทุกฟิลด์เป็น optional และ **ไม่ส่งมา = ไม่แตะ**

    `name=null` ที่ส่งมาตรง ๆ = ล้างชื่อ (ต่างจาก "ไม่ส่ง name มาเลย")
    """

    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class AcademicTermCreate(BaseModel):
    name: str = Field(description="เช่น 'เทอม 1' / 'ภาคเรียนที่ ๑'")
    start_date: date
    end_date: date
    is_current: bool = False


class AcademicTermUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class SetCurrentPeriodRequest(BaseModel):
    year_id: Optional[int] = Field(
        None, description="null = ปลดปีปัจจุบัน (สถิติกลับไปนับทั้งหมด)"
    )
    term_id: Optional[int] = Field(None, description="ต้องอยู่ในปีที่เลือก — null = ใช้ทั้งปี")


class CurrentPeriodResponse(BaseModel):
    current_year_id: Optional[int] = None
    current_term_id: Optional[int] = None


class DeletePeriodResponse(BaseModel):
    deleted: bool = True
    year_id: Optional[int] = None
    term_id: Optional[int] = None
