"""ศูนย์กลางกฎความเป็นส่วนตัว (Privacy Gate) — ทุกจุดที่อ่าน PII ต้องใช้ฟังก์ชันจากไฟล์นี้

นโยบายล่าสุด (2026-11-01, "ข้อมูลของห้อง เอาความสะดวกก่อน"):
- รายชื่อนักเรียนเป็นข้อมูลของห้อง — ครูเพิ่ม/แก้ได้ทันที ไม่ต้องรอเจ้าตัวยืนยัน
- PII (เบอร์/ที่อยู่/วันเกิด/ข้อมูลสุขภาพ) เห็นได้เฉพาะ **ผู้จัดการห้อง**
  (MANAGE_STUDENTS / VIEW_ALL_STUDENTS / is_admin / super admin)
- เจ้าตัวเห็น PII ของตัวเองได้เสมอ
- นักเรียนทั่วไปเห็นชื่อเพื่อนได้ (transparency) แต่ PII ถูก mask

`identity_claimed` ยังใช้เป็น "สถานะยืนยันตัวตน" ใน UI และเป็นตัวกระตุ้นการ merge
ข้อมูลบัญชีกลางตอนเจ้าตัวกดยืนยัน — ไม่ใช่เงื่อนไขเปิด PII อีกต่อไป
"""

SENTINEL = "🔒 ไม่มีสิทธิ์เข้าถึง"

PRIVATE_STUDENT_FIELDS = frozenset([
    "phone_number", "phone_number_parent", "phone_number_parent_relation",
    "email", "line_id", "ig_username", "birthday",
    "address_house_no", "address_road", "address_sub_district",
    "address_district", "address_province", "address_post_code",
    "blood_group", "shirt_size", "food_allergy", "congenital_disease",
])

# ข้อมูลส่วนตัว (Type A) ที่อ่านจาก view v_student_profiles — ใช้ในระบบกิจกรรม
PROFILE_TYPE_A_FIELDS = frozenset([
    "blood_group", "shirt_size", "food_allergy", "congenital_disease",
    "phone_number", "phone_number_parent",
])


def is_real_claimed_account(u: dict) -> bool:
    """True ถ้า users row เป็นบัญชีจริงที่เจ้าตัวยืนยันแล้ว (ไม่ใช่ ghost ที่มีแค่ชื่อ)."""
    return bool(u.get("google_id") or u.get("discord_id") or u.get("email") or u.get("phone_number"))


def can_view_pii(*, requester_user_id, target_user_id, is_super_admin,
                 viewer_is_manager) -> bool:
    """กฎกลางสำหรับ profile/search/export: super admin / ดูตัวเอง / ผู้จัดการห้อง."""
    if is_super_admin:
        return True
    if requester_user_id is not None and target_user_id is not None and int(requester_user_id) == int(target_user_id):
        return True
    return bool(viewer_is_manager)


def can_view_activity_pii(*, requester_user_id, target_user_id, is_super_admin,
                          viewer_is_manager) -> bool:
    """กฎ Type A fields ในกิจกรรม — ผู้จัดการห้อง / ตัวเอง / super admin เท่านั้น."""
    if is_super_admin:
        return True
    if requester_user_id is not None and target_user_id is not None and int(requester_user_id) == int(target_user_id):
        return True
    return bool(viewer_is_manager)


def mask_private_fields(data: dict, can_view: bool, fields=PRIVATE_STUDENT_FIELDS) -> dict:
    """ถ้าไม่มีสิทธิ์ เปลี่ยนค่า PII เป็น SENTINEL (แก้ dict ตรง ๆ แล้วคืนเดิม)."""
    if not can_view:
        for f in fields:
            if f in data:
                data[f] = SENTINEL
    return data
