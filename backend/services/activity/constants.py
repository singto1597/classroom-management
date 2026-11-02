"""ค่าคงที่ + ป้าย label ของ activity service (เวลาไทย, ชื่อเดือน, ป้าย Excel export)."""
from typing import Dict, FrozenSet, List, Optional
from zoneinfo import ZoneInfo

from core.exceptions import ValidationError

THAI_TZ = ZoneInfo("Asia/Bangkok")

THAI_MONTH_NAMES: List[str] = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

# 🌟 คอลัมน์มาตรฐานใน Excel export — แผนที่ชื่อคอลัมน์ → ภาษาไทย
# ครอบคลุมทั้ง base fields, Type A (profile), และ Type B (metadata เฉพาะกิจกรรม)
EXPORT_HEADER_LABELS: Dict[str, str] = {
    "student_no": "เลขที่",
    "first_name": "ชื่อจริง",
    "last_name": "นามสกุล",
    "nickname": "ชื่อเล่น",
    "first_name_en": "ชื่อจริง (EN)",
    "last_name_en": "นามสกุล (EN)",
    "nickname_en": "ชื่อเล่น (EN)",
    "role_type": "หน้าที่ (ประเภท)",
    "role_detail": "รายละเอียดหน้าที่",
    "earned_hours": "ชั่วโมงจิตอาสา",
    "status": "สถานะเข้าร่วม",
    # Type A — จากโปรไฟล์ users
    "blood_group": "กรุ๊ปเลือด",
    "shirt_size": "ไซส์เสื้อ",
    "food_allergy": "อาหารที่แพ้",
    "congenital_disease": "โรคประจำตัว",
    "phone_number": "เบอร์โทรศัพท์นักเรียน",
    "phone_number_parent": "เบอร์โทรศัพท์ผู้ปกครอง",
    # Type B — metadata เฉพาะกิจกรรม (หมวดการเดินทาง)
    "bus_number": "หมายเลขรถบัส",
    "van_number": "หมายเลขรถตู้",
    "seat_number": "เลขที่นั่ง",
    "travel_method": "วิธีการเดินทาง",
    # Type B — ที่พักและการจัดกลุ่ม
    "room_number": "หมายเลขห้องพัก",
    "building_name": "ชื่ออาคาร/ตึกพัก",
    "group_name": "ชื่อกลุ่ม/สี/ค่าย/บ้าน",
    "team_role": "บทบาทในทีม",
    # Type B — การจัดการหน้างาน
    "consent_status": "ใบขออนุญาตผู้ปกครอง",
    "is_paid": "สถานะจ่ายเงินค่าค่าย",
    "check_in_time": "เวลาเช็คอิน",
    # 🌟 ข้อมูลเพิ่มเติมต่อคน (custom_fields) — คอลัมน์ที่ได้จาก participant.metadata.custom_fields
    "custom_fields": "ข้อมูลเพิ่มเติม",
}

# 🌟 ป้ายภาษาไทยสำหรับคีย์ metadata ของกิจกรรม (ใช้ตอน export สรุป) — กันแสดงคีย์ดิบ
# ครอบคลุมคีย์เก่า (dual-write) + คีย์ภายใน (positions/required_fields)
ACTIVITY_META_LABELS: Dict[str, str] = {
    "location_name": "สถานที่",
    "location_url": "ลิงก์แผนที่",
    "agenda": "กำหนดการ",
    "tags": "หมวดหมู่",
    "positions": "หน้าที่/ตำแหน่ง",
    "required_fields": "ข้อมูลที่เก็บต่อคน",
    "dynamic_fields": "ฟิลด์เพิ่มเติมต่อคน",
}

# 🌟 Type A — Profile Fields: ดึงจากตาราง users (READ ONLY ในบริบทกิจกรรม) — ห้ามเก็บซ้ำลง JSONB
# ตอน GET participants จะ JOIN กลับมาพร้อมเสมอ และตอน Export จะอ่านจาก record ตรง ๆ
PROFILE_FIELDS: FrozenSet[str] = frozenset({
    "blood_group", "shirt_size", "food_allergy", "congenital_disease",
    "phone_number", "phone_number_parent",
})
PROFILE_FIELD_LABELS: Dict[str, str] = {
    "blood_group": "กรุ๊ปเลือด",
    "shirt_size": "ไซส์เสื้อ",
    "food_allergy": "อาหารที่แพ้",
    "congenital_disease": "โรคประจำตัว",
    "phone_number": "เบอร์โทรศัพท์นักเรียน",
    "phone_number_parent": "เบอร์โทรศัพท์ผู้ปกครอง",
}

ROLE_TYPE_LABELS: Dict[str, str] = {
    "participant": "ผู้เข้าร่วม",
    "staff": "ทีมงาน",
    "leader": "หัวหน้ากลุ่ม",
}

PARTICIPANT_STATUS_LABELS: Dict[str, str] = {
    "confirmed": "ยืนยันแล้ว",
    "cancelled": "ยกเลิก",
    "attended": "มาแล้ว",
}

# 🌟 ป้ายภาษาไทยของสถานะกิจกรรม (ค่าใน activities.status) — ใช้ในหน้า Summary ของ Excel
# (เลียนแบบ ACTIVITY_STATUS_LABELS ฝั่ง Vue — ก่อนหน้าเอา PARTICIPANT_STATUS_LABELS มาใช้ผิดที่
#  เลยได้ "ongoing" ติดมาเป็นอังกฤษ; ตรงนี้เป็นคนละชุดกับสถานะเข้าร่วมของ participant)
ACTIVITY_STATUS_LABELS: Dict[str, str] = {
    "upcoming": "กำลังจะมา",
    "ongoing": "กำลังดำเนินการ",
    "completed": "เสร็จสิ้น",
    "cancelled": "ยกเลิก",
}

# สีธีม (hex) ของแต่ละสถานะ — ใช้แต้มสีข้อความใน Excel ให้ตรงกับ badge ฝั่ง Vue
ACTIVITY_STATUS_COLORS: Dict[str, str] = {
    "upcoming": "2563EB",   # น้ำเงิน
    "ongoing": "D97706",    # ส้ม-เหลือง
    "completed": "059669",  # เขียว
    "cancelled": "E11D48",  # แดง
}
PARTICIPANT_STATUS_COLORS: Dict[str, str] = {
    "confirmed": "059669",  # เขียว
    "attended": "2563EB",   # น้ำเงิน
    "cancelled": "E11D48",  # แดง
}

# 🌟 ความกว้างคอลัมน์ (จุด) ของ Sheet รายชื่อ — เลขที่แคบ ฟิลด์ยาว ๆ กว้าง
EXPORT_FIELD_WIDTHS: Dict[str, int] = {
    "student_no": 7,
    "first_name": 18,
    "last_name": 18,
    "nickname": 13,
    "first_name_en": 16,
    "last_name_en": 16,
    "nickname_en": 13,
    "role_type": 15,
    "role_detail": 28,
    "earned_hours": 12,
    "status": 15,
    "custom_fields": 45,
}
DEFAULT_EXPORT_COL_WIDTH = 22

# ═══════════════════════════════════════════════════════════════════════════
# 🏷️ P4.3 — หมวดกิจกรรม (category)
# ═══════════════════════════════════════════════════════════════════════════
# รายการ **ปิด** (fixed set) — ฝั่ง Vue มีสำเนาที่ `constants/activityCategories.ts`
# ซึ่งล็อกด้วยเทสต์ ⇒ เพิ่มหมวดใหม่ต้องแก้สองที่ + migration ไม่ต้องทำ (คอลัมน์เป็น TEXT)
# เรียงตามลำดับที่อยากให้โผล่ในดรอปดาวน์ (ทั่วไปก่อน → อื่น ๆ ท้ายสุด)
ACTIVITY_CATEGORIES: List[Dict[str, str]] = [
    {"value": "camp", "label": "ค่าย"},
    {"value": "competition", "label": "การแข่งขัน"},
    {"value": "volunteer", "label": "จิตอาสา"},
    {"value": "training", "label": "อบรม/สัมมนา"},
    {"value": "ceremony", "label": "พิธีการ"},
    {"value": "other", "label": "อื่น ๆ"},
]
ACTIVITY_CATEGORY_VALUES: FrozenSet[str] = frozenset(c["value"] for c in ACTIVITY_CATEGORIES)
ACTIVITY_CATEGORY_LABELS: Dict[str, str] = {c["value"]: c["label"] for c in ACTIVITY_CATEGORIES}


def normalize_category(value: Optional[str]) -> Optional[str]:
    """ทำความสะอาดค่าหมวด → slug ที่รู้จัก หรือ None (ไม่ระบุ)

    - `None` / `""` / ช่องว่างล้วน = **ล้างหมวด** (ตั้ง NULL) — ใช้เป็นทาง "ยกเลิกหมวด"
      ใน PATCH ได้ เพราะผู้เรียกแปลง `""` เป็น `None` ก่อนถึงจุดนี้
    - ค่าที่ไม่รู้จัก = 400 พร้อมรายการที่รับได้ (ไม่เดาใกล้เคียงให้ — กันพิมพ์ผิดแล้วเงียบ)
    """
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if cleaned not in ACTIVITY_CATEGORY_VALUES:
        allowed = " · ".join(f"{c['value']} ({c['label']})" for c in ACTIVITY_CATEGORIES)
        raise ValidationError(f"ไม่รู้จักหมวดกิจกรรม '{value}' — รับได้เฉพาะ: {allowed}")
    return cleaned
