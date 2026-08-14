/**
 * 🗂️ Data Dictionary & Field Configuration — ระบบ Dynamic Smart Forms สำหรับกิจกรรม
 *
 * เป็น source of truth กลางของ "ฟิลด์ที่กิจกรรมจะเก็บข้อมูลได้" ทั้งหมด (DRY Principle):
 * - Field Selector (CreateActivity.vue) ติ๊กเลือก → เก็บ key ลง activities.metadata.required_fields
 * - Smart Participant Table ใช้คอลัมน์ตามที่เลือก
 * - Batch Apply ใช้เฉพาะฟิลด์ Type B ที่ถูกเลือก
 * - Backend Export อ่าน required_fields แล้ว map ค่า Type A (จาก users) / Type B (จาก metadata)
 *
 * ⚠️ ต้องซิงก์กับ backend/services/activity_service.py:
 *   - PROFILE_FIELDS / PROFILE_FIELD_LABELS (Type A)
 *   - EXPORT_HEADER_LABELS (Thai label ตอน Export)
 */

/** ชนิดของฟิลด์ — ควบคุมว่า UI จะ render เป็นอะไร */
export type ActivityFieldType = 'input' | 'dropdown' | 'boolean' | 'datetime'

export interface ActivityFieldOption {
  value: string
  label: string
}

/** ฟิลด์หนึ่งตัวใน Field Dictionary */
export interface ActivityField {
  key: string
  label: string
  type: ActivityFieldType
  /** หมวดหมู่ที่ใช้จัดกลุ่มใน Field Selector */
  category: 'profile' | 'transport' | 'accommodation' | 'operation'
  /** placeholder ตัวอย่างตอนเป็น input */
  placeholder?: string
  /** ตัวเลือก (เฉพาะ dropdown) */
  options?: ActivityFieldOption[]
  /** คำอธิบายสั้น ๆ ใต้ชื่อฟิลด์ */
  hint?: string
}

/** ================================================================
 *  Type A — Profile Fields: ดึงจากตาราง users (READ ONLY ในบริบทกิจกรรม)
 *  🔒 ไม่เก็บลง JSONB metadata ตอน GET จะ JOIN กลับมาจาก backend ให้อัตโนมัติ
 *  ================================================================ */
export const PROFILE_FIELDS: ActivityField[] = [
  {
    key: 'blood_group',
    label: 'กรุ๊ปเลือด',
    type: 'input',
    category: 'profile',
    placeholder: 'เช่น A, B, O, AB',
    hint: 'จากโปรไฟล์ส่วนตัว 🔒',
  },
  {
    key: 'shirt_size',
    label: 'ไซส์เสื้อ',
    type: 'input',
    category: 'profile',
    placeholder: 'เช่น S, M, L, XL',
    hint: 'จากโปรไฟล์ส่วนตัว 🔒',
  },
  {
    key: 'food_allergy',
    label: 'อาหารที่แพ้',
    type: 'input',
    category: 'profile',
    placeholder: 'เช่น กุ้ง, ถั่วลิสง',
    hint: 'จากโปรไฟล์ส่วนตัว 🔒',
  },
  {
    key: 'congenital_disease',
    label: 'โรคประจำตัว',
    type: 'input',
    category: 'profile',
    placeholder: 'เช่น หอบหืด, แพ้ยา',
    hint: 'จากโปรไฟล์ส่วนตัว 🔒',
  },
  {
    key: 'phone_number',
    label: 'เบอร์โทรศัพท์นักเรียน',
    type: 'input',
    category: 'profile',
    placeholder: 'เช่น 08X-XXX-XXXX',
    hint: 'จากโปรไฟล์ส่วนตัว 🔒',
  },
  {
    key: 'phone_number_parent',
    label: 'เบอร์โทรศัพท์ผู้ปกครอง',
    type: 'input',
    category: 'profile',
    placeholder: 'เช่น 08X-XXX-XXXX',
    hint: 'จากโปรไฟล์ส่วนตัว 🔒',
  },
]

/** ================================================================
 *  Type B — Event-Specific Fields: บันทึกลง activity_participants.metadata (Editable)
 *  ================================================================ */
export const EVENT_FIELDS: ActivityField[] = [
  // --- หมวดการเดินทาง (Transport) ---
  {
    key: 'bus_number',
    label: 'หมายเลขรถบัส',
    type: 'input',
    category: 'transport',
    placeholder: 'เช่น คันที่ 1 / B2',
  },
  {
    key: 'van_number',
    label: 'หมายเลขรถตู้',
    type: 'input',
    category: 'transport',
    placeholder: 'เช่น V1',
  },
  {
    key: 'seat_number',
    label: 'เลขที่นั่ง',
    type: 'input',
    category: 'transport',
    placeholder: 'เช่น A12',
  },
  {
    key: 'travel_method',
    label: 'วิธีการเดินทาง',
    type: 'dropdown',
    category: 'transport',
    options: [
      { value: 'school', label: 'ไปกับโรงเรียน' },
      { value: 'parent', label: 'ผู้ปกครองรับส่ง' },
      { value: 'self', label: 'เดินทางเอง' },
    ],
  },
  // --- หมวดที่พักและการจัดกลุ่ม (Accommodation & Grouping) ---
  {
    key: 'room_number',
    label: 'หมายเลขห้องพัก',
    type: 'input',
    category: 'accommodation',
    placeholder: 'เช่น 501',
  },
  {
    key: 'building_name',
    label: 'ชื่ออาคาร/ตึกพัก',
    type: 'input',
    category: 'accommodation',
    placeholder: 'เช่น อาคารหอ 1',
  },
  {
    key: 'group_name',
    label: 'ชื่อกลุ่ม/สี/ค่าย/บ้าน',
    type: 'input',
    category: 'accommodation',
    placeholder: 'เช่น กลุ่มสีแดง',
  },
  {
    key: 'team_role',
    label: 'บทบาทในทีม',
    type: 'dropdown',
    category: 'accommodation',
    options: [
      { value: 'mentor', label: 'พี่เลี้ยง' },
      { value: 'staff', label: 'สตาฟฟ์' },
      { value: 'participant', label: 'ผู้เข้าร่วม' },
    ],
  },
  // --- หมวดการจัดการหน้างาน (Operation) ---
  {
    key: 'consent_status',
    label: 'ใบขออนุญาตผู้ปกครอง',
    type: 'dropdown',
    category: 'operation',
    options: [
      { value: 'pending', label: 'รอส่ง' },
      { value: 'submitted', label: 'ส่งแล้ว' },
      { value: 'not_attending', label: 'ไม่เข้าร่วม' },
    ],
  },
  {
    key: 'is_paid',
    label: 'สถานะจ่ายเงินค่าค่าย',
    type: 'boolean',
    category: 'operation',
  },
  {
    key: 'check_in_time',
    label: 'เวลาลงทะเบียน',
    type: 'datetime',
    category: 'operation',
    placeholder: 'เช่น 08:30',
  },
]

/** รวมทุกฟิลด์ (Type A + Type B) — ใช้ใน Field Selector / ตาราง / Batch */
export const ALL_ACTIVITY_FIELDS: ActivityField[] = [...PROFILE_FIELDS, ...EVENT_FIELDS]

/** Map key → ฟิลด์ (ค้นไว) */
export const ACTIVITY_FIELD_MAP: Record<string, ActivityField> = Object.fromEntries(
  ALL_ACTIVITY_FIELDS.map((f) => [f.key, f]),
)

/** กลุ่ม Type A (จากโปรไฟล์) — ค้น key ได้ไว */
export const PROFILE_FIELD_KEYS: Set<string> = new Set(PROFILE_FIELDS.map((f) => f.key))

/** กลุ่ม Type B (metadata เฉพาะกิจกรรม) — ค้น key ได้ไว */
export const EVENT_FIELD_KEYS: Set<string> = new Set(EVENT_FIELDS.map((f) => f.key))

/** ป้ายหมวดหมู่สำหรับ Field Selector (ไทย) */
export const ACTIVITY_FIELD_CATEGORY_LABELS: Record<string, string> = {
  profile: 'ข้อมูลจากโปรไฟล์ (🔒 ดึงอัตโนมัติ)',
  transport: 'หมวดการเดินทาง (Transport)',
  accommodation: 'ที่พักและการจัดกลุ่ม (Accommodation & Grouping)',
  operation: 'การจัดการหน้างาน (Operation)',
}

/** ลำดับหมวดหมู่ที่ใช้ render (profile ก่อน แล้วค่อย Type B) */
export const ACTIVITY_FIELD_CATEGORY_ORDER: ActivityField['category'][] = [
  'profile',
  'transport',
  'accommodation',
  'operation',
]

/** ฟิลด์ Type B ที่เป็น Dropdown → แสดง label ไทยแทน raw value */
export function fieldDisplayValue(field: ActivityField | undefined, raw: unknown): string {
  if (raw === null || raw === undefined) return ''
  if (field?.type === 'boolean') {
    return raw ? '✅ จ่ายแล้ว' : '⏳ ยังไม่จ่าย'
  }
  if (field?.type === 'dropdown' && field.options) {
    const opt = field.options.find((o) => o.value === String(raw))
    if (opt) return opt.label
  }
  return String(raw)
}

/** ================================================================
 *  🎖️ ตำแหน่ง/หน้าที่ของกิจกรรม (Activity Duty Positions)
 *  เก็บเป็น Array ของชื่อตำแหน่งใน activities.metadata.positions
 *  แต่ละกิจกรรมกำหนดเองได้ (เช่น กีฬาสี: นักกีฬา/แสตน/สตาฟแสตน/สตาฟนักกีฬา)
 *  ================================================================ */
/** ค่าเริ่มต้นสำหรับกิจกรรมที่ยังไม่ได้ตั้งตำแหน่ง (backward compat) */
export const DEFAULT_ACTIVITY_POSITIONS: string[] = [
  'นักกีฬา',
  'แสตน',
  'สตาฟแสตน',
  'สตาฟนักกีฬา',
]

/** อ่านรายการตำแหน่งจาก metadata (fallback ค่าเริ่มต้นถ้าไม่มี / ว่างเปล่า) */
export function getActivityPositions(metadata?: Record<string, unknown> | null): string[] {
  const raw = metadata?.positions
  if (Array.isArray(raw)) {
    const list = raw.map(String).map((s) => s.trim()).filter(Boolean)
    if (list.length > 0) return list
  }
  return [...DEFAULT_ACTIVITY_POSITIONS]
}

/** "นักกีฬา: วิ่ง 100 เมตร" → { position: 'นักกีฬา', note: 'วิ่ง 100 เมตร' } */
export function splitDutyRole(roleDetail: string | null | undefined): { position: string; note: string } {
  const raw = (roleDetail ?? '').trim()
  const idx = raw.indexOf(': ')
  if (idx === -1) return { position: raw, note: '' }
  return { position: raw.slice(0, idx).trim(), note: raw.slice(idx + 2).trim() }
}

/** { position, note } → "นักกีฬา: วิ่ง 100 เมตร" (note ว่าง → แค่ตำแหน่ง) */
export function joinDutyRole(position: string, note: string): string {
  const p = position.trim()
  const n = note.trim()
  if (!p) return n
  return n ? `${p}: ${n}` : p
}
