/**
 * ระบบบันทึกกิจกรรมและผู้เข้าร่วม (Activity & Role Management)
 * ประเภทข้อมูลกลาง — ใช้ร่วมกับ services/activity.ts และ views/activities/*
 */

export type ActivityStatus = 'upcoming' | 'ongoing' | 'completed' | 'cancelled'
export type RoleType = 'participant' | 'staff' | 'leader'
export type ParticipantStatus = 'confirmed' | 'cancelled' | 'attended'

/** ข้อมูล metadata เป็น key-value อิสระ (JSONB ฝั่ง backend) — ต่อยอด Dynamic ได้ */
export type Metadata = Record<string, unknown>

export interface ActivityParticipant {
  id: number
  activity_id: number
  student_id: number
  student_no: number
  first_name: string
  last_name: string
  nickname: string | null
  first_name_en: string | null
  last_name_en: string | null
  nickname_en: string | null
  role_type: RoleType | string
  role_detail: string | null
  earned_hours: number
  status: ParticipantStatus | string
  metadata: Metadata
  recorded_by: string | null
  /** 🌟 Type A Profile Fields — JOIN มาจากตาราง users (READ ONLY ในบริบทกิจกรรม) */
  blood_group?: string | null
  shirt_size?: string | null
  food_allergy?: string | null
  congenital_disease?: string | null
  phone_number?: string | null
  phone_number_parent?: string | null
}

/** รายการ Batch Apply — อัปเดต metadata ของ participant ที่ถูกติ๊ก (merge กับของเดิม) + ตั้งหน้าที่ได้
 * ทุกฟิลด์นอกจาก participant_id เป็น optional — ไม่ส่ง = ไม่แตะของเดิม */
export interface BatchParticipantItem {
  participant_id: number
  /** 🎖️ หน้าที่/ตำแหน่ง (role_detail) — batch ตั้งหน้าที่ให้ทุกคนที่ติ๊กพร้อมกัน ไม่ส่ง = ไม่แตะ */
  role_detail?: string | null
  /** 🌟 role_type (participant/staff/leader) — batch ตั้งแบบกลุ่มได้ */
  role_type?: string | null
  /** 🌟 status (confirmed/cancelled/attended) — batch ตั้งแบบกลุ่มได้ */
  status?: string | null
  /** 🌟 ชั่วโมงจิตอาสา — batch ตั้งแบบกลุ่มได้ */
  earned_hours?: number | null
  metadata: Metadata
}

/** ================================================================
 *  🌟 Dynamic Fields — ฟิลด์ที่ผู้จัดการกิจกรรมสร้างเอง (activities.metadata.dynamic_fields)
 *  def อยู่ระดับกิจกรรม; ค่าแต่ละคนเก็บที่ activity_participants.metadata['df_<n>']
 *  ================================================================ */
export type DynamicFieldType = 'input' | 'dropdown' | 'boolean' | 'datetime'

export interface DynamicFieldOption {
  value: string
  label: string
}

export interface DynamicFieldDef {
  key: string
  label: string
  type: DynamicFieldType
  options?: DynamicFieldOption[]
}

/** ================================================================
 *  ✅ ระบบเช็คชื่อแยกแผ่น (Multiple Attendance Sheets)
 *  ================================================================ */
export interface CheckinSheet {
  id: number
  activity_id: number
  title: string
  event_date: string | null
  created_by: string | null
  created_at: string
  updated_at: string
  checked_count: number
  total_count: number
}

/** เครื่องหมายเช็คของ participant 1 คนในแผ่น */
export interface CheckinMark {
  is_present: boolean
  checked_at: string | null
  recorded_by: string | null
}

export interface CheckinSheetDetail {
  sheet: CheckinSheet
  participants: (ActivityParticipant & CheckinMark)[]
}

/** นักเรียนในห้องที่ยังไม่ได้เข้ากิจกรรมนี้ (สำหรับปุ่มเพิ่มนักเรียน) */
export interface AvailableStudent {
  student_id: number
  student_no: number
  first_name: string | null
  last_name: string | null
  nickname: string | null
  first_name_en: string | null
  last_name_en: string | null
  nickname_en: string | null
  blood_group?: string | null
  shirt_size?: string | null
  food_allergy?: string | null
  congenital_disease?: string | null
  phone_number?: string | null
  phone_number_parent?: string | null
}

/** 1 รายการเช็คชื่อใน batch */
export interface CheckinRecordInput {
  participant_id: number
  is_present: boolean
}

export interface BatchParticipantUpdate {
  items: BatchParticipantItem[]
  user_name: string
}

export interface Activity {
  id: number
  room_id: number
  title: string
  description: string | null
  activity_date: string // YYYY-MM-DD
  base_hours: number
  status: ActivityStatus | string
  metadata: Metadata
  created_by: string | null
  created_at: string
  updated_at: string
  participant_count: number
  participants: ActivityParticipant[]
}

/** ผู้เข้าร่วมที่ส่งตอนสร้างกิจกรรม — ระบุด้วย student_no (เลขที่) */
export interface ActivityParticipantInput {
  student_no: number
  role_type: RoleType | string
  role_detail?: string | null
  earned_hours?: number
  status?: ParticipantStatus | string
  metadata?: Metadata
}

export interface ActivityCreate {
  title: string
  description?: string | null
  activity_date: string
  base_hours?: number
  status?: ActivityStatus | string
  metadata?: Metadata
  participants?: ActivityParticipantInput[]
  user_name: string
}

export interface ActivityUpdate {
  title?: string
  description?: string | null
  activity_date?: string
  base_hours?: number
  status?: ActivityStatus | string
  metadata?: Metadata
  /** ถ้าส่งมา → แทนที่ผู้เข้าร่วมทั้งชุด (เพิ่ม/แก้/ลบ/กู้คืน) เหมือนตอนสร้าง */
  participants?: ActivityParticipantInput[]
  user_name: string
}

export interface ParticipantAdd {
  student_no: number
  role_type?: RoleType | string
  role_detail?: string | null
  earned_hours?: number
  status?: ParticipantStatus | string
  metadata?: Metadata
  user_name: string
}

export interface ParticipantUpdate {
  role_type?: RoleType | string
  role_detail?: string | null
  earned_hours?: number
  status?: ParticipantStatus | string
  metadata?: Metadata
  user_name: string
}

/** แถวที่ normalize แล้วของ ParticipantRosterList — parent map จาก ActivityParticipant | Student มาเป็นตัวนี้ */
export interface RosterItem {
  key: string | number
  student_no: number
  first_name: string
  last_name: string
  nickname: string | null
  first_name_en: string | null
  last_name_en: string | null
  nickname_en: string | null
  prefix?: string | null
  role_type: string
  role_detail: string | null
  status: string
  earned_hours: number
  metadata: Record<string, unknown>
  /** Type A profile values (JOIN users) — ใช้แสดงใน modal ข้อมูลเพิ่มเติม */
  profile: Record<string, unknown>
}

/** กิจกรรม + หน้าที่ของฉัน (สำหรับบอท /my_roles และหน้าโปรไฟล์) */
export interface MyActivityRole {
  activity_id: number
  title: string
  activity_date: string
  base_hours: number
  status: ActivityStatus | string
  activity_metadata: Metadata
  role_type: RoleType | string
  role_detail: string | null
  earned_hours: number
  participant_status: ParticipantStatus | string
  participant_metadata: Metadata
}

/** ป้ายสถานะกิจกรรม (สีไทย) */
export const ACTIVITY_STATUS_LABELS: Record<string, string> = {
  upcoming: 'กำลังจะมา',
  ongoing: 'กำลังดำเนินการ',
  completed: 'เสร็จสิ้น',
  cancelled: 'ยกเลิก',
}

export const ACTIVITY_STATUS_BADGE: Record<string, string> = {
  upcoming: 'bg-blue-50 text-blue-600 border-blue-200',
  ongoing: 'bg-amber-50 text-amber-600 border-amber-200',
  completed: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  cancelled: 'bg-rose-50 text-rose-600 border-rose-200',
}

export const ROLE_TYPE_LABELS: Record<string, string> = {
  participant: 'ผู้เข้าร่วม',
  staff: 'ทีมงาน',
  leader: 'หัวหน้ากลุ่ม',
}

export const PARTICIPANT_STATUS_LABELS: Record<string, string> = {
  confirmed: 'ยืนยันแล้ว',
  cancelled: 'ยกเลิก',
  attended: 'มาแล้ว',
}
