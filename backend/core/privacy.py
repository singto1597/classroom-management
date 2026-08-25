"""ศูนย์กลางกฎความเป็นส่วนตัว (Privacy Gate) — ทุกจุดที่อ่าน PII ต้องใช้ฟังก์ชันจากไฟล์นี้

ช่องโหว่เดิม: แอดมินแอดชื่อนักเรียนที่ตรงกับบัญชีจริง → ระบบ link บัญชีจริงให้อัตโนมัติ
โดยไม่ยินยอม → เห็น PII เต็ม (profile/search/export/activities)

กฎ (Consent Model): PII ของสมาชิกจะเปิดให้ห้องเห็นได้ ต่อเมื่อสมาชิก "อ้างสิทธิ์/ยืนยันตัวตน"
การเป็นสมาชิกเอง (students.identity_claimed = TRUE) หรือผู้ขอดูเป็นตัวเจ้าตัวเอง / SUPER_ADMIN เท่านั้น
"""

SENTINEL = "🔒 ไม่มีสิทธิ์เข้าถึง"

PRIVATE_STUDENT_FIELDS = frozenset([
    "phone_number", "phone_number_parent", "phone_number_parent_relation",
    "email", "line_id", "ig_username", "birthday",
    "address_house_no", "address_road", "address_sub_district",
    "address_district", "address_province", "address_post_code",
    "blood_group", "shirt_size", "food_allergy", "congenital_disease",
])

# ข้อมูลส่วนตัว (Type A) ที่อ่านจากตาราง users ผ่าน JOIN — ใช้ในระบบกิจกรรม
PROFILE_TYPE_A_FIELDS = frozenset([
    "blood_group", "shirt_size", "food_allergy", "congenital_disease",
    "phone_number", "phone_number_parent",
])


def is_real_claimed_account(u: dict) -> bool:
    """True ถ้า users row เป็นบัญชีจริงที่เจ้าตัวยืนยันแล้ว (ไม่ใช่ ghost ที่มีแค่ชื่อ)."""
    return bool(u.get("google_id") or u.get("discord_id") or u.get("email") or u.get("phone_number"))


def can_view_pii(*, requester_user_id, target_user_id, identity_claimed,
                 is_super_admin, viewer_has_view_all) -> bool:
    """กฎกลางสำหรับ profile/search/export: PII เห็นได้ถ้า super admin / ดูตัวเอง / (claimed + มี VIEW_ALL_STUDENTS)."""
    if is_super_admin:
        return True
    if requester_user_id is not None and target_user_id is not None and int(requester_user_id) == int(target_user_id):
        return True
    return bool(identity_claimed) and bool(viewer_has_view_all)


def can_view_activity_pii(*, requester_user_id, target_user_id, identity_claimed, is_super_admin) -> bool:
    """กฎสำหรับ Type A fields ในกิจกรรม — สมาชิกห้องเห็นได้ (ต้องเป็น member อยู่แล้วผ่าน require_member)
    แต่เฉพาะ participant ที่ claimed ถึงจะเห็น PII."""
    if is_super_admin:
        return True
    if requester_user_id is not None and target_user_id is not None and int(requester_user_id) == int(target_user_id):
        return True
    return bool(identity_claimed)


def mask_private_fields(data: dict, can_view: bool, fields=PRIVATE_STUDENT_FIELDS) -> dict:
    """ถ้าไม่มีสิทธิ์ เปลี่ยนค่า PII เป็น SENTINEL (แก้ dict ตรง ๆ แล้วคืนเดิม)."""
    if not can_view:
        for f in fields:
            if f in data:
                data[f] = SENTINEL
    return data
