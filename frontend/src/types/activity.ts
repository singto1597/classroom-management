/**
 * ระบบบันทึกกิจกรรมและผู้เข้าร่วม (Activity & Role Management)
 * ประเภทข้อมูลกลาง — ใช้ร่วมกับ services/activity.ts และ views/activities/*
 */

export type ActivityStatus = 'upcoming' | 'ongoing' | 'completed' | 'cancelled'
export type RoleType = 'participant' | 'staff' | 'leader'
// 🪑 P4.1 — `waitlisted` = คิวสำรอง (เกินความจุ) · เลื่อนขึ้นอัตโนมัติเมื่อมีคนยกเลิก
export type ParticipantStatus = 'confirmed' | 'cancelled' | 'attended' | 'waitlisted'

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
  /** 🪑 P4.1 — 1,2,3... = ลำดับในคิวสำรอง · null = ไม่ได้อยู่ในคิว */
  queue_position?: number | null
  metadata: Metadata
  recorded_by: string | null
  /** 🎟️ P4.2 — เวลาที่ "มาแล้ว" ถูกบันทึก (ISO) · null = ไม่เคยเช็คอินผ่านทางที่บันทึกเวลาได้ */
  checked_in_at?: string | null
  /** 🎟️ P4.2 — ชื่อทีมงานที่กดเช็คอิน/สแกนบัตร */
  checked_in_by?: string | null
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
  /** 🪑 P4.1 — ความจุ (null = ไม่จำกัด) */
  capacity?: number | null
  /** 🏷️ P4.3 — หมวดกิจกรรม (slug) + ป้ายไทยที่ backend แปลให้แล้ว · null = ยังไม่จัดหมวด */
  category?: string | null
  category_label?: string | null
  /** 📅 P4.3 — วันปิดรับลงทะเบียน (YYYY-MM-DD) · null = ไม่มีกำหนด */
  registration_deadline?: string | null
  /** 🔗 P4.3 — มีลิงก์แชร์ที่ยังไม่ถูกเพิกถอนอยู่หรือไม่ (โทเคนจริงออกให้เฉพาะตอนกดแชร์) */
  has_share_link?: boolean
  metadata: Metadata
  created_by: string | null
  created_at: string
  updated_at: string
  /** ยอดรวมทุกแถว (คงความหมายเดิม) — ที่นั่งจริงดู `confirmed_count` */
  participant_count: number
  /** 🪑 P4.1 — นั่งแล้ว (confirmed + attended) · ในคิว */
  confirmed_count?: number
  waitlisted_count?: number
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
  /** 🪑 P4.1 — ไม่ส่ง = ไม่จำกัดความจุ */
  capacity?: number | null
  /** 🏷️ P4.3 — slug จาก `ACTIVITY_CATEGORIES` · ไม่ส่ง/`''` = ไม่ระบุหมวด */
  category?: string | null
  /** 📅 P4.3 — วันปิดรับลงทะเบียน (ต้องไม่หลัง activity_date) */
  registration_deadline?: string | null
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
  /** 🪑 P4.1 — 0 = ยกเลิกเพดาน (null ที่ส่งมาตรง ๆ ถูกมองว่า "ไม่ส่ง") */
  capacity?: number
  /** 🏷️ P4.3 — ไม่ส่ง = ไม่แตะ · `null` หรือ `''` = ล้างหมวด (ต่างจาก capacity ที่ใช้ 0) */
  category?: string | null
  /** 📅 P4.3 — ไม่ส่ง = ไม่แตะ · `null` = ล้างวันปิดรับ */
  registration_deadline?: string | null
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
  upcoming: 'bg-info-50 text-info-600 border-info-200',
  ongoing: 'bg-warn-50 text-warn-600 border-warn-200',
  completed: 'bg-ok-50 text-ok-600 border-ok-200',
  cancelled: 'bg-danger-50 text-danger-600 border-danger-200',
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
  // 🪑 P4.1 — ต้องตรงกับ backend/services/activity/constants.py + docs/glossary.md
  waitlisted: 'คิวสำรอง',
}

// ================================================================
// 🌟 เปรียบเทียบกิจกรรม (Intersection / Union / ลบ) + แผนภาพเวน
// ================================================================

/**
 * สมาชิก 1 คนในภูมิภาค — **เฉพาะชื่อ** เพราะ endpoint เปรียบเทียบเปิดให้สมาชิกห้องทุกคนอ่าน
 * (ไม่มี Type A profile fields หลุดออกมาจาก backend โดยเจตนา)
 */
export interface CompareMember {
  student_id: number
  student_no: number
  first_name: string | null
  last_name: string | null
  nickname: string | null
  first_name_en: string | null
  last_name_en: string | null
  nickname_en: string | null
}

/**
 * ภูมิภาค = กลุ่มคนที่อยู่กิจกรรมชุดเดียวกันเป๊ะ
 * `key` = activity id เรียงจากน้อยไปมากต่อด้วย '-' (เช่น `"3-7"`) — **คำนวณที่ backend**
 * ฝั่งหน้าจอห้ามประกอบคีย์เอง ให้ส่ง `key` ที่ได้จาก response กลับไปเท่านั้น
 */
export interface CompareRegion {
  key: string
  activity_ids: number[]
  members: CompareMember[]
}

export interface CompareActivityInfo {
  id: number
  title: string
  activity_date: string
  participant_count: number
}

export interface ActivityCompare {
  activities: CompareActivityInfo[]
  regions: CompareRegion[]
}

// ================================================================
// 🔗 P4.3 — ลิงก์แชร์กิจกรรม (หน้าอ่านอย่างเดียว ไม่ต้องล็อกอิน)
// ================================================================

/** ผลจาก POST …/activities/{id}/share — `rotated=true` = ลิงก์เดิมถูกทำให้ตายแล้ว */
export interface ShareLink {
  activity_id: number
  share_token: string
  /** path ฝั่งเว็บ (เช่น `/share/activity/<token>`) — ประกอบ origin เองตอนคัดลอก */
  path: string
  rotated: boolean
}

export interface ShareRevokeResult {
  activity_id: number
  revoked: boolean
}

/**
 * ข้อมูลที่หน้าสาธารณะเห็น — **backend ไม่ส่ง PII เลย** (ไม่มีรายชื่อผู้เข้าร่วม)
 * ถ้าเพิ่มฟิลด์ที่นี่ต้องคิดก่อนว่า "คนนอกห้องควรเห็นไหม"
 */
export interface SharedActivity {
  activity_id: number
  title: string
  description: string | null
  activity_date: string
  base_hours: number
  status: ActivityStatus | string
  status_label: string
  category: string | null
  category_label: string | null
  registration_deadline: string | null
  is_registration_open: boolean
  capacity: number | null
  confirmed_count: number
  waitlisted_count: number
  /** null = ไม่จำกัดความจุ */
  seats_left: number | null
  room_name: string | null
}
