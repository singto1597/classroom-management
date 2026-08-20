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
import type { DynamicFieldDef } from '@/types/activity'

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
 *  แต่ละกิจกรรมกำหนดเองได้ (ค่าเริ่มต้นเป็นกลาง — ใช้กับกิจกรรมไหนก็ได้
 *  ไม่ผูกกับกีฬาสี เช่น หัวหน้ากลุ่ม/ทีมงาน/ฝ่ายต่าง ๆ)
 *  ================================================================ */
/** ค่าเริ่มต้นสำหรับกิจกรรมที่ยังไม่ได้ตั้งตำแหน่ง (backward compat) */
export const DEFAULT_ACTIVITY_POSITIONS: string[] = [
  'หัวหน้ากลุ่ม',
  'ทีมงาน',
  'ผู้ประสานงาน',
  'ฝ่ายทะเบียน',
  'ฝ่ายสถานที่',
  'ฝ่ายประชาสัมพันธ์',
]

/** อ่านรายการตำแหน่งจาก metadata (fallback ค่าเริ่มต้นถ้าไม่มี / ว่างเปล่า) */
export function getActivityPositions(metadata?: Record<string, unknown> | null): string[] {
  const raw = metadata?.positions
  if (Array.isArray(raw)) {
    const list = raw
      .map(String)
      .map((s) => s.trim())
      .filter(Boolean)
    if (list.length > 0) return list
  }
  return [...DEFAULT_ACTIVITY_POSITIONS]
}

/** "นักกีฬา: วิ่ง 100 เมตร" → { position: 'นักกีฬา', note: 'วิ่ง 100 เมตร' } */
export function splitDutyRole(roleDetail: string | null | undefined): {
  position: string
  note: string
} {
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

/** ================================================================
 *  📝 ข้อมูลเพิ่มเติมแบบ User-Friendly (หัวข้อ + ค่า)
 *  - ข้อมูลเพิ่มเติมของกิจกรรม → activities.metadata.custom_fields
 *  - ข้อมูลเพิ่มเติมของนักเรียน → activity_participants.metadata.custom_fields
 *  ไม่ต้องให้ผู้ใช้พิมพ์ "ชื่อตัวแปร" อีกต่อไป — แค่ใส่หัวข้อกับค่าที่ต้องการเก็บ
 *  ================================================================ */
/** 1 รายการของข้อมูลเพิ่มเติม (หัวข้อ + ค่า) */
export interface CustomFieldEntry {
  label: string
  value: string
}

/** แถวข้อมูลที่พร้อมแสดงผล (แปล label แล้ว) สำหรับหน้า detail */
export interface ActivityInfoRow {
  label: string
  value: string
  /** วิธีแสดงผล (ลิงก์/หลายบรรทัด) — ใช้จัดสไตล์ให้สวยขึ้น */
  kind?: 'text' | 'link' | 'lines' | 'chips'
}

/** คีย์ metadata กิจกรรมที่รู้จัก → label ไทย (ใช้ตอนแสดงผล detail + export-friendly) */
export const ACTIVITY_META_KEY_LABELS: Record<string, string> = {
  location_name: 'สถานที่',
  location_url: 'ลิงก์แผนที่',
  agenda: 'กำหนดการ',
  tags: 'หมวดหมู่',
}

/** ปุ่มเพิ่มข้อมูลลัด (quick-add) — กดแล้วเพิ่มแถว "หัวข้อ+ค่า" ที่พร้อมกรอก */
export const ACTIVITY_META_QUICK_ADD: Array<{ label: string; key: string; placeholder: string }> = [
  { label: 'สถานที่', key: 'location_name', placeholder: 'เช่น สนามกีฬาโรงเรียน' },
  { label: 'ลิงก์แผนที่', key: 'location_url', placeholder: 'https://maps.google.com/...' },
  { label: 'กำหนดการ', key: 'agenda', placeholder: '08:00 เปิดงาน | 10:00 แข่ง' },
  { label: 'หมวดหมู่', key: 'tags', placeholder: 'เช่น กีฬา, ค่าย, ทัศนศึกษา (คั่นด้วย ,)' },
]

/** คีย์เก่าที่ dual-write (เขียนคู่กับ custom_fields) — ใช้ตอน buildActivityMeta/serialize */
const LEGACY_META_KEYS = new Set(['location_name', 'location_url', 'agenda', 'tags'])

/** value ที่เก็บในคีย์เก่า (array ต่อเป็นข้อความ) — ใช้ตอน edit-prefill แปลงกลับเป็นแถว */
function legacyValueToString(key: string, value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(String).join(', ')
  return String(value)
}

/**
 * ข้อมูลเพิ่มเติมของกิจกรรม → แถว friendly (สำหรับหน้า detail + list)
 * - custom_fields → แถวตามที่เก็บ
 * - คีย์เก่าที่รู้จัก (location_name/url, agenda, tags) → label ไทย
 * - positions / required_fields → แสดงเป็น "หน้าที่/ตำแหน่ง" / "ข้อมูลที่เก็บต่อคน"
 */
export function renderActivityInfo(metadata?: Record<string, unknown> | null): ActivityInfoRow[] {
  if (!metadata) return []
  const rows: ActivityInfoRow[] = []

  // 1) custom_fields (ข้อมูลเพิ่มเติมแบบ friendly) — มาก่อนเสมอ
  const custom = metadata.custom_fields
  if (Array.isArray(custom)) {
    for (const entry of custom) {
      if (!entry || typeof entry !== 'object') continue
      const label = String((entry as Record<string, unknown>).label ?? '').trim()
      const value = String((entry as Record<string, unknown>).value ?? '').trim()
      if (label && value) rows.push({ label, value })
    }
  }

  // 2) คีย์เก่าที่รู้จัก (กันซ้ำกับ custom_fields ที่ map แล้ว)
  const seen = new Set(rows.map((r) => r.label))
  for (const key of ['location_name', 'location_url', 'agenda', 'tags'] as const) {
    const raw = metadata[key]
    if (raw === null || raw === undefined) continue
    const label = ACTIVITY_META_KEY_LABELS[key] ?? key
    if (seen.has(label)) continue // custom_fields มีหัวข้อนี้แล้ว → ข้าม (กันซ้ำ)
    const value = legacyValueToString(key, raw).trim()
    if (!value) continue
    seen.add(label)
    if (key === 'location_url' && /^https?:\/\//i.test(value)) {
      rows.push({ label, value, kind: 'link' })
    } else if (key === 'agenda') {
      rows.push({ label, value, kind: 'lines' })
    } else if (key === 'tags') {
      rows.push({ label, value, kind: 'chips' })
    } else {
      rows.push({ label, value })
    }
  }

  // 3) positions / required_fields — แปลงเป็น label ไทย (ไม่แสดงคีย์ดิบ)
  const positions = metadata.positions
  if (Array.isArray(positions) && positions.length > 0) {
    rows.push({ label: 'หน้าที่/ตำแหน่ง', value: positions.map(String).join(' · ') })
  }
  const required = metadata.required_fields
  if (Array.isArray(required) && required.length > 0) {
    const labels = required
      .map((k) => String(k).trim())
      .filter(Boolean)
      .map((k) => ACTIVITY_FIELD_MAP[k]?.label ?? k)
    if (labels.length > 0) rows.push({ label: 'ข้อมูลที่เก็บต่อคน', value: labels.join(' · ') })
  }

  return rows
}

/**
 * metadata → แถวข้อมูลเพิ่มเติมสำหรับแก้ไข (edit-prefill)
 * - มี custom_fields (กิจกรรมใหม่) → ใช้โดยตรง
 * - ไม่มี (กิจกรรมเก่า) → reconstruct จากคีย์เก่าที่รู้จัก (กันข้อมูลเก่าหาย)
 */
export function customFieldsFromMeta(
  metadata?: Record<string, unknown> | null,
): CustomFieldEntry[] {
  if (!metadata) return []
  const custom = metadata.custom_fields
  if (Array.isArray(custom)) {
    const rows = custom
      .filter((e): e is CustomFieldEntry => !!e && typeof e === 'object')
      .map((e) => {
        const entry = e as unknown as Record<string, unknown>
        return {
          label: String(entry.label ?? '').trim(),
          value: String(entry.value ?? '').trim(),
        }
      })
    if (rows.length > 0) return rows
  }
  // fallback: คีย์เก่า
  const rows: CustomFieldEntry[] = []
  for (const key of ['location_name', 'location_url', 'agenda', 'tags'] as const) {
    const raw = metadata[key]
    if (raw === null || raw === undefined) continue
    const value = legacyValueToString(key, raw).trim()
    if (!value) continue
    rows.push({ label: ACTIVITY_META_KEY_LABELS[key] ?? key, value })
  }
  return rows
}

/**
 * แปลงแถว "หัวข้อ+ค่า" → metadata dict (ใช้ตอน submit)
 * - ตั้ง custom_fields = [{label, value}]
 * - dual-write คีย์เก่า (location_name/url, agenda, tags) เพื่อให้บอท/List ยังอ่านได้
 * - ถ้ามี priorMeta และคีย์เก่าตัวไหนไม่มีแถวแล้ว → ส่ง `key: null` (backend delete-on-null กัน ghost)
 * - tags คั่น , → array, agenda คั่น | → array
 */
export function buildActivityMeta(
  rows: CustomFieldEntry[],
  positions: string[],
  requiredFields: string[],
  priorMeta?: Record<string, unknown> | null,
): Record<string, unknown> {
  const meta: Record<string, unknown> = {}

  // 1) custom_fields — เฉพาะแถวที่กรอกครบ
  const custom = rows
    .map((r) => ({ label: r.label.trim(), value: r.value.trim() }))
    .filter((r) => r.label && r.value)
  if (custom.length > 0) meta.custom_fields = custom

  // 2) dual-write คีย์เก่า จากแถวที่ label ตรงกับ quick-add
  for (const quick of ACTIVITY_META_QUICK_ADD) {
    const match = custom.find((r) => r.label === quick.label)
    if (!match) continue
    if (quick.key === 'tags') {
      meta.tags = match.value
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
    } else if (quick.key === 'agenda') {
      meta.agenda = match.value
        .split('|')
        .map((t) => t.trim())
        .filter(Boolean)
    } else {
      meta[quick.key] = match.value
    }
  }

  // 3) คีย์เก่าที่เคยมีแต่ไม่มีแถวแล้ว → ส่ง null (ให้ backend ลบออก) — กันข้อมูลเก่าค้าง
  if (priorMeta) {
    for (const key of LEGACY_META_KEYS) {
      if (priorMeta[key] !== undefined && priorMeta[key] !== null && !(key in meta)) {
        meta[key] = null
      }
    }
  }

  // 4) positions + required_fields (เก็บแยกเป็นคีย์เฉพาะ — source of truth)
  meta.positions = [...positions]
  meta.required_fields = [...requiredFields]

  return meta
}

/** ================================================================
 *  🧩 Dynamic Fields — ฟิลด์ที่ผู้จัดการกิจกรรมสร้างเอง
 *  def อยู่ที่ activities.metadata.dynamic_fields = [{key, label, type, options?}]
 *  ค่าแต่ละคนเก็บที่ activity_participants.metadata['df_<n>']
 *  ================================================================ */

/** อ่านรายการ dynamic field defs จาก activity metadata (fallback []) */
export function getDynamicFields(metadata?: Record<string, unknown> | null): DynamicFieldDef[] {
  const raw = metadata?.dynamic_fields
  if (!Array.isArray(raw)) return []
  const defs: DynamicFieldDef[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const d = item as Record<string, unknown>
    const key = String(d.key ?? '').trim()
    const label = String(d.label ?? '').trim()
    const type = String(d.type ?? 'input') as DynamicFieldDef['type']
    if (!key || !label) continue
    defs.push({
      key,
      label,
      type: ['input', 'dropdown', 'boolean', 'datetime'].includes(type) ? type : 'input',
      options: Array.isArray(d.options)
        ? (d.options as { value?: unknown; label?: unknown }[])
            .map((o) => ({
              value: String(o?.value ?? ''),
              label: String(o?.label ?? ''),
            }))
            .filter((o) => o.value && o.label)
        : undefined,
    })
  }
  return defs
}

/** dynamic field defs → ActivityField[] (สำหรับ reuse ActivityFieldControl / Batch / modal) */
export function dynamicDefsToFields(defs: DynamicFieldDef[]): ActivityField[] {
  return defs.map((d) => ({
    key: d.key,
    label: d.label,
    type: d.type,
    category: 'operation' as const,
    options: d.options,
  }))
}

/** อ่านค่าของ participant สำหรับ dynamic field key (จาก metadata['df_<n>']) */
export function readDynamicValue(
  metadata: Record<string, unknown> | undefined | null,
  key: string,
): unknown {
  if (!metadata) return undefined
  return metadata[key]
}
