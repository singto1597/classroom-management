export interface Student {
  id: number
  user_id: number | null
  room_id: number | string
  discord_id: number | null
  discord_id_str: string | null
  student_no: number
  student_id: number | null
  prefix: string | null
  first_name: string
  last_name: string
  nickname: string | null
  first_name_en: string | null
  last_name_en: string | null
  nickname_en: string | null
  birthday: string | null // ISO Date string (YYYY-MM-DD)
  class_role: string
  cleaning_duty: string | null
  olympic_camp: string | null
  portfolio: string | null
  target_faculty: string | null
  blood_group: string | null
  shirt_size: string | null
  food_allergy: string | null
  congenital_disease: string | null
  phone_number: string | null
  phone_number_parent: string | null
  phone_number_parent_relation: string | null
  line_id: string | null
  ig_username: string | null
  email: string | null
  address_house_no: string | null
  address_road: string | null
  address_sub_district: string | null
  address_district: string | null
  address_province: string | null
  address_post_code: string | null
  status: 'active' | 'inactive' | 'pending'
  created_at: string
  updated_at: string
  deleted_at: string | null

  is_admin?: boolean;
  permissions?: string[];
  // 🛡️ Consent Model: identity_claimed = เจ้าตัวยืนยันตัวตนการเป็นสมาชิกแล้ว (PII ถึงจะเปิดให้ห้องดู)
  identity_claimed?: boolean;
  added_by?: number | null;
}

/** รายการคำขอที่รอจัดการ (Consent Model) — ตรงกับ PendingRequestResponse ใน backend/models/room_schemas.py
 *  หมายเหตุ: ฟิลด์ Optional ของ Pydantic มาทาง JSON ได้ทั้งแบบ null และแบบไม่ส่งมา จึงประกาศเป็น optional + nullable */
export interface PendingStudentRequest {
  id: number
  student_no: number
  first_name?: string | null
  last_name?: string | null
  first_name_en?: string | null
  last_name_en?: string | null
  created_at: string
  identity_claimed: boolean
  added_by?: number | null
  request_type: 'join_request' | 'claim_request' | 'invite_pending'
  ghost_first_name?: string | null
  ghost_last_name?: string | null
  ghost_first_name_en?: string | null
  ghost_last_name_en?: string | null
  name_match?: boolean | null
}

/** ฟอร์มแก้ไขข้อมูลนักเรียน — Partial<Student> + ฟิลด์ควบคุมพิเศษ (ย้ายเลขที่ / สิทธิ์ผู้ดูแล) */
export type StudentForm = Partial<Student> & {
  new_student_no?: number | null
  is_admin?: boolean
  permissions?: string[]
}

/** Body ที่ส่งขึ้น PATCH /classroom/{roomId}/students/{studentNo} — ต้องมี user_name สำหรับ audit log */
export type StudentUpdatePayload = StudentForm & {
  user_name?: string
}

/**
 * ข้อมูลนักเรียนแบบย่อ — ใช้ตอน "เพิ่มนักเรียน"/"เพิ่มแบบ Bulk"
 * ตรงกับ backend/models/student_schemas.py → StudentQuickAdd
 */
export interface StudentQuickAdd {
  student_no: number;
  first_name: string;
  last_name: string;
  nickname?: string | null;
  first_name_en?: string | null;
  last_name_en?: string | null;
  nickname_en?: string | null;
}

/** POST /api/classroom/{room_id}/students (StudentAddRequest = StudentQuickAdd + user_name) */
export interface StudentAddPayload extends StudentQuickAdd {
  user_name: string;
}

/** คำเชิญเข้าร่วมห้อง (Consent Model) — แอดมินแอดชื่อเราให้ ต้องกดรับเองก่อนถึงเป็นสมาชิก */
export interface Invite {
  invite_id: number
  student_no: number
  room_id: number
  room_name: string
  room_code: string | null
  server_id: number | null
  added_by_first: string | null
  added_by_last: string | null
  created_at: string | null
}
