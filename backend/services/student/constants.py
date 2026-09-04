"""ค่าคงที่ + ป้าย label ของ student service (ชุดฟิลด์ patch/global/local, ป้าย export)."""
from typing import Dict, FrozenSet, List
from zoneinfo import ZoneInfo

from models.student_schemas import StudentUpdateRequest

STUDENT_PATCHABLE_COLUMNS: FrozenSet[str] = frozenset(StudentUpdateRequest.model_fields.keys())

GLOBAL_FIELDS: FrozenSet[str] = frozenset([
    'prefix', 'first_name', 'last_name', 'nickname',
    'first_name_en', 'last_name_en', 'nickname_en', 'birthday',
    'blood_group', 'shirt_size', 'food_allergy', 'congenital_disease',
    'phone_number', 'phone_number_parent', 'phone_number_parent_relation',
    'line_id', 'ig_username', 'email',
    'address_house_no', 'address_road', 'address_sub_district',
    'address_district', 'address_province', 'address_post_code'
])

# ฟิลด์ชื่อที่ต้อง NFC-normalize ก่อนเขียนลง users (แก้ อำ/อํา ฯลฯ; normalize_nfc = NFC + strip)
NAME_NFC_FIELDS: FrozenSet[str] = frozenset(['prefix', 'first_name', 'last_name', 'nickname', 'nickname_en'])

LOCAL_FIELDS: FrozenSet[str] = frozenset([
    'student_id', 'class_role', 'cleaning_duty', 'olympic_camp',
    'portfolio', 'target_faculty', 'is_admin', 'permissions', 'status'
])

THAI_TZ = ZoneInfo("Asia/Bangkok")

THAI_MONTH_NAMES: List[str] = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

# หัวคอลัมน์ภาษาไทยสำหรับ Export (คีย์ = field ใน BASE_STUDENT_SELECT)
EXPORT_HEADER_LABELS: Dict[str, str] = {
    "student_no": "เลขที่",
    "student_id": "รหัสนักเรียน",
    "prefix": "คำนำหน้า",
    "first_name": "ชื่อจริง",
    "last_name": "นามสกุล",
    "nickname": "ชื่อเล่น",
    "first_name_en": "ชื่อจริง (EN)",
    "last_name_en": "นามสกุล (EN)",
    "nickname_en": "ชื่อเล่น (EN)",
    "birthday": "วันเกิด",
    "class_role": "บทบาทในห้อง",
    "cleaning_duty": "เวรทำความสะอาด",
    "olympic_camp": "สอวน. / ค่าย",
    "target_faculty": "คณะเป้าหมาย",
    "portfolio": "ผลงาน",
    "blood_group": "กรุ๊ปเลือด",
    "shirt_size": "ไซส์เสื้อ",
    "food_allergy": "แพ้อาหาร",
    "congenital_disease": "โรคประจำตัว",
    "phone_number": "เบอร์โทรศัพท์",
    "phone_number_parent": "เบอร์ผู้ปกครอง",
    "phone_number_parent_relation": "ความสัมพันธ์",
    "line_id": "LINE ID",
    "ig_username": "IG Username",
    "email": "อีเมล",
    "address_house_no": "บ้านเลขที่/หมู่/ซอย",
    "address_road": "ถนน",
    "address_sub_district": "ตำบล/แขวง",
    "address_district": "อำเภอ/เขต",
    "address_province": "จังหวัด",
    "address_post_code": "รหัสไปรษณีย์",
    "status": "สถานะ",  # defensive: มีใน BASE_STUDENT_SELECT แม้ frontend ไม่ให้เลือก
}

ROLE_LABELS: Dict[str, str] = {
    "student": "นักเรียน",
    "president": "หัวหน้าห้อง",
    "vice_president": "รองหัวหน้าห้อง",
    "secretary": "เลขานุการ (เรขา)",
    "vice_academic": "รองวิชาการ",
    "vice_activity": "รองกิจกรรม",
    "vice_discipline": "รองระเบียบวินัย",
    "vice_reception": "รองปฏิคม",
    "vice_pr": "รองประชาสัมพันธ์",
    "vice_sanitation": "รองสุขาภิบาล",
    "staff_academic": "กรรมการวิชาการ",
    "staff_activity": "กรรมการกิจกรรม",
    "staff_discipline": "กรรมการระเบียบวินัย",
    "staff_reception": "กรรมการปฏิคม",
    "staff_pr": "กรรมการประชาสัมพันธ์",
    "staff_sanitation": "กรรมการสุขาภิบาล",
    "treasurer": "เหรัญญิก",
    "admin": "ผู้ดูแลระบบ",
}

STATUS_LABELS: Dict[str, str] = {
    "active": "กำลังเรียน",
    "pending": "รออนุมัติ",
    "inactive": "พ้นสภาพ",
}

DEFAULT_COL_WIDTH = 18
EXPORT_COLUMN_WIDTHS: Dict[str, int] = {
    "student_no": 8, "student_id": 14, "prefix": 10,
    "first_name": 16, "last_name": 16, "nickname": 14,
    "first_name_en": 16, "last_name_en": 16, "nickname_en": 14,
    "birthday": 22,
    "class_role": 18, "cleaning_duty": 20, "olympic_camp": 24,
    "target_faculty": 18, "portfolio": 30,
    "blood_group": 10, "shirt_size": 10, "food_allergy": 20, "congenital_disease": 20,
    "phone_number": 18, "phone_number_parent": 18, "phone_number_parent_relation": 14,
    "line_id": 16, "ig_username": 16, "email": 26,
    "address_house_no": 24, "address_road": 20, "address_sub_district": 20,
    "address_district": 20, "address_province": 14, "address_post_code": 14,
}

CENTER_FIELDS: FrozenSet[str] = frozenset({"student_no", "blood_group", "shirt_size", "address_post_code"})
WRAP_TEXT_FIELDS: FrozenSet[str] = frozenset({
    "portfolio", "olympic_camp", "cleaning_duty", "food_allergy",
    "congenital_disease", "address_house_no",
})
