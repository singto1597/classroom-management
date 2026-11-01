"""0001 — ข้อมูลนักเรียนเป็นของห้อง (room-owned roster) + override โปรไฟล์ต่อห้อง

บริบท:
- เดิม "ครูเพิ่มนักเรียนที่มีบัญชีจริง" → แถว students เป็น pending และรอเจ้าตัวกดรับ
  ⇒ ครูแก้ข้อมูลไม่ได้ นักเรียนที่ไม่เคยล็อกอินค้าง pending ตลอดกาล
- นโยบายใหม่: การมีชื่อในห้องไม่ต้องรอ consent — แถวเป็น active ทันที
  คำเชิญเหลือเป็น "ยืนยันตัวตน" แบบไม่บล็อก
- ครูแก้ข้อมูลในห้อง = เขียน student_room_profiles (override ของห้องนั้น) ไม่แตะ users
  การอ่านทุกจุดใช้ v_student_profiles = COALESCE(override, ค่าบัญชีกลาง)

หมายเหตุ: ไฟล์นี้ apply แล้วห้ามแก้ (checksum ตรึง) — เปลี่ยน view ในอนาคตให้เขียนไฟล์ใหม่
"""

SQL: list[str] = [
    # 1) ตาราง override 1:1 กับ students (คอลัมน์ nullable ชุดเดียวกับ users)
    """
    CREATE TABLE IF NOT EXISTS student_room_profiles (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,

        prefix TEXT,
        first_name TEXT,
        last_name TEXT,
        nickname TEXT,
        first_name_en TEXT,
        last_name_en TEXT,
        nickname_en TEXT,
        birthday DATE,

        blood_group VARCHAR(3),
        shirt_size TEXT,
        food_allergy TEXT,
        congenital_disease TEXT,

        phone_number TEXT,
        phone_number_parent TEXT,
        phone_number_parent_relation TEXT,
        line_id TEXT,
        ig_username TEXT,
        email TEXT,

        address_house_no TEXT,
        address_road TEXT,
        address_sub_district TEXT,
        address_district TEXT,
        address_province TEXT,
        address_post_code VARCHAR(10),

        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 2) view กลาง: ค่าโปรไฟล์ที่ resolve แล้ว (override ของห้องชนะค่าบัญชีกลาง)
    #    query เดิมที่ alias users เป็น u/U เปลี่ยนมา JOIN view นี้ได้โดยไม่ต้องแก้ชื่อคอลัมน์
    """
    CREATE OR REPLACE VIEW v_student_profiles AS
    SELECT
        s.id AS student_id,
        s.room_id,
        s.student_no,
        u.id AS id,
        u.discord_id,
        u.deleted_at,
        COALESCE(p.prefix, u.prefix) AS prefix,
        COALESCE(p.first_name, u.first_name) AS first_name,
        COALESCE(p.last_name, u.last_name) AS last_name,
        COALESCE(p.nickname, u.nickname) AS nickname,
        COALESCE(p.first_name_en, u.first_name_en) AS first_name_en,
        COALESCE(p.last_name_en, u.last_name_en) AS last_name_en,
        COALESCE(p.nickname_en, u.nickname_en) AS nickname_en,
        COALESCE(p.birthday, u.birthday) AS birthday,
        COALESCE(p.blood_group, u.blood_group) AS blood_group,
        COALESCE(p.shirt_size, u.shirt_size) AS shirt_size,
        COALESCE(p.food_allergy, u.food_allergy) AS food_allergy,
        COALESCE(p.congenital_disease, u.congenital_disease) AS congenital_disease,
        COALESCE(p.phone_number, u.phone_number) AS phone_number,
        COALESCE(p.phone_number_parent, u.phone_number_parent) AS phone_number_parent,
        COALESCE(p.phone_number_parent_relation, u.phone_number_parent_relation) AS phone_number_parent_relation,
        COALESCE(p.line_id, u.line_id) AS line_id,
        COALESCE(p.ig_username, u.ig_username) AS ig_username,
        COALESCE(p.email, u.email) AS email,
        COALESCE(p.address_house_no, u.address_house_no) AS address_house_no,
        COALESCE(p.address_road, u.address_road) AS address_road,
        COALESCE(p.address_sub_district, u.address_sub_district) AS address_sub_district,
        COALESCE(p.address_district, u.address_district) AS address_district,
        COALESCE(p.address_province, u.address_province) AS address_province,
        COALESCE(p.address_post_code, u.address_post_code) AS address_post_code
    FROM students s
    LEFT JOIN users u ON u.id = s.user_id
    LEFT JOIN student_room_profiles p ON p.student_id = s.id
    """,
    # 3) ปลดล็อกแถว pending ที่เกิดจาก "คำเชิญของครู" (added_by IS NOT NULL)
    #    — คำขอ self-join / ขออ้างสิทธิ์ ghost (added_by IS NULL) ยังต้องรออนุมัติ
    #    ไม่แตะ identity_claimed: เจ้าตัวยังต้องกดยืนยันตัวตนเองใน Lobby
    """
    UPDATE students
    SET status = 'active', updated_at = CURRENT_TIMESTAMP
    WHERE status = 'pending'
      AND added_by IS NOT NULL
      AND deleted_at IS NULL
    """,
]
