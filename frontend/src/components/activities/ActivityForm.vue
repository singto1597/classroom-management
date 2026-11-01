<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import { ActivityService } from '@/services/activity'
import { displayName } from '@/utils/name'
import { todayIso } from '@/utils/datetime'
import type { Activity, ActivityParticipantInput, RosterItem } from '@/types/activity'
import type { Student } from '@/types/student'
import {
  ALL_ACTIVITY_FIELDS,
  PROFILE_FIELD_KEYS,
  EVENT_FIELD_KEYS,
  ACTIVITY_FIELD_CATEGORY_LABELS,
  ACTIVITY_FIELD_CATEGORY_ORDER,
  ACTIVITY_META_QUICK_ADD,
  getActivityPositions,
  customFieldsFromMeta,
  buildActivityMeta,
  splitDutyRole,
  joinDutyRole,
  type ActivityField,
  type CustomFieldEntry,
} from '@/constants/activityFields'
import { ACTIVITY_CATEGORIES } from '@/constants/activityCategories'
import ExtraInfoRows from '@/components/activities/ExtraInfoRows.vue'
import ParticipantRosterList from '@/components/activities/ParticipantRosterList.vue'
import ParticipantInfoModal from '@/components/activities/ParticipantInfoModal.vue'
import BatchApplyModal from '@/components/activities/BatchApplyModal.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import Swal from 'sweetalert2'
import { UI_COLOR } from '@/constants/theme'
import { confirmLeave, useFormDraft, useUnsavedGuard } from '@/composables/useFormDraft'

const props = defineProps<{
  mode: 'create' | 'edit'
  initialActivity?: Activity | null
}>()

const emit = defineEmits<{ (e: 'saved', activityId: number): void }>()

const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const editActivityId = computed(() =>
  props.mode === 'edit' && props.initialActivity ? props.initialActivity.id : null,
)

const isLoading = ref(true)
const isSaving = ref(false)
const hasError = ref(false)
// สถานะแสดงข้อความ validation แบบ inline (แทน Swal ที่เด้งทีละข้อ)
const showErrors = ref(false)
const touchedTitle = ref(false)
const touchedDate = ref(false)
const touchedParticipants = ref(false)

const canManage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

// ================================================================
// 🏷️ โซน A — ข้อมูลกิจกรรม
// ================================================================
const form = ref({
  title: '',
  description: '',
  activity_date: todayIso(),
  base_hours: 0,
  status: 'upcoming' as string,
  // 🏷️ P4.3 — slug จาก `ACTIVITY_CATEGORIES` ('' = ยังไม่จัดหมวด)
  category: '' as string,
  // 📅 P4.3 — วันปิดรับลงทะเบียน ('' = ไม่มีกำหนด · ต้องไม่หลังวันจัดกิจกรรม)
  registration_deadline: '' as string,
  // 🪑 P4.1 — ความจุ ('' = ไม่จำกัด) · เกินแล้วคนใหม่ไปคิวสำรอง ไม่ใช่ error
  capacity: '' as string,
})

// --- ข้อมูลเพิ่มเติมของกิจกรรม (หัวข้อ + ค่า แบบ user-friendly) ---
const activityMetaRows = ref<CustomFieldEntry[]>([])

// --- 🎖️ หน้าที่/ตำแหน่งของกิจกรรม (กำหนดเองได้ต่อกิจกรรม) ---
const positions = ref<string[]>([])
const newPosition = ref('')

const addPosition = () => {
  const value = newPosition.value.trim()
  if (!value) return
  if (positions.value.some((p) => p === value)) {
    return Swal.fire({ icon: 'warning', title: 'ซ้ำ', text: `ตำแหน่ง "${value}" มีอยู่แล้ว` })
  }
  positions.value.push(value)
  newPosition.value = ''
}

const removePosition = (index: number) => {
  positions.value.splice(index, 1)
}

const movePosition = (index: number, dir: -1 | 1) => {
  const target = index + dir
  if (target < 0 || target >= positions.value.length) return
  const arr = [...positions.value]
  const current = arr[index]
  const other = arr[target]
  if (current === undefined || other === undefined) return
  arr[index] = other
  arr[target] = current
  positions.value = arr
}

// ================================================================
// 🔘 โซน B — ข้อมูลที่เก็บของนักเรียน (Field Selector) + ผู้เข้าร่วม
// ================================================================
const requiredFields = ref<Set<string>>(new Set())

const typeAColumns = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter(
    (f) => PROFILE_FIELD_KEYS.has(f.key) && requiredFields.value.has(f.key),
  ),
)
const typeBColumns = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter((f) => EVENT_FIELD_KEYS.has(f.key) && requiredFields.value.has(f.key)),
)

const toggleRequiredField = (key: string) => {
  const next = new Set(requiredFields.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  requiredFields.value = next
}

// --- ผู้เข้าร่วม (local draft state — map ตาม student_no) ---
const students = ref<Student[]>([])
const selectedNos = ref<Set<number>>(new Set())
const dutyPosition = ref<Record<number, string>>({})
const dutyNote = ref<Record<number, string>>({})
const participantMeta = ref<Record<number, Record<string, unknown>>>({})
const participantHours = ref<Record<number, number>>({})
const participantRoleType = ref<Record<number, string>>({})
const participantStatus = ref<Record<number, string>>({})

// 📝 ร่างฟอร์ม (โหมดสร้างเท่านั้น) — เก็บฟิลด์หลัก + รายชื่อที่ติ๊กไว้
// เหตุผลที่ใช้ "กระจก" (draftState) แทนการผูก state ตรง ๆ: ฟอร์มนี้มีทั้ง Set/Record
// และ state ที่ผูกกับ students ที่โหลดทีหลัง — sessionStorage เก็บได้เฉพาะ JSON
// หมายเหตุ: ตำแหน่ง/โน้ต "รายคน" (dutyPosition/dutyNote) ยังไม่ถูกร่างไว้
const draftState = reactive({
  title: '',
  description: '',
  activity_date: todayIso(),
  base_hours: 0,
  status: 'upcoming' as string,
  category: '',
  registration_deadline: '',
  capacity: '',
  metaRows: [] as CustomFieldEntry[],
  positions: [] as string[],
  requiredFields: [] as string[],
  selectedNos: [] as number[],
})

const draft = useFormDraft(
  draftState,
  () => `cls:draft:activity:${currentRoomId}`,
  () => props.mode === 'create' && canManage.value,
)

watch(
  [form, activityMetaRows, positions, requiredFields, selectedNos],
  () => {
    draftState.title = form.value.title
    draftState.description = form.value.description
    draftState.activity_date = form.value.activity_date
    draftState.base_hours = Number(form.value.base_hours) || 0
    draftState.status = form.value.status
    draftState.category = form.value.category
    draftState.registration_deadline = form.value.registration_deadline
    draftState.capacity = form.value.capacity
    draftState.metaRows = activityMetaRows.value
    draftState.positions = positions.value
    draftState.requiredFields = Array.from(requiredFields.value)
    draftState.selectedNos = Array.from(selectedNos.value)
  },
  { deep: true },
)

/** คืนค่าร่างลง state จริง — เรียกหลังโหลดรายชื่อนักเรียนเสร็จ (ต้องรู้ว่ามีใครอยู่จริง) */
const applyDraft = () => {
  form.value.title = typeof draftState.title === 'string' ? draftState.title : ''
  form.value.description = typeof draftState.description === 'string' ? draftState.description : ''
  form.value.activity_date = draftState.activity_date || todayIso()
  form.value.base_hours = Number(draftState.base_hours) || 0
  form.value.status = draftState.status || 'upcoming'
  form.value.category = typeof draftState.category === 'string' ? draftState.category : ''
  form.value.registration_deadline =
    typeof draftState.registration_deadline === 'string' ? draftState.registration_deadline : ''
  form.value.capacity = draftState.capacity === undefined ? '' : String(draftState.capacity)
  activityMetaRows.value = Array.isArray(draftState.metaRows) ? draftState.metaRows : []
  positions.value = Array.isArray(draftState.positions)
    ? draftState.positions.map(String)
    : getActivityPositions(undefined)
  requiredFields.value = new Set(
    Array.isArray(draftState.requiredFields) ? draftState.requiredFields.map(String) : [],
  )
  // ตัดนักเรียนที่ถูกลบ/ย้ายห้องออกจากร่าง กันบันทึกไปหาคนที่ไม่มีแล้ว (backend จะ error)
  const known = new Set(students.value.map((s) => s.student_no))
  selectedNos.value = new Set(
    (Array.isArray(draftState.selectedNos) ? draftState.selectedNos : [])
      .map(Number)
      .filter((no) => known.has(no)),
  )
}


/** รายการที่ normalize สำหรับ ParticipantRosterList — โชว์นักเรียน active ทั้งหมด
 * (checkbox บอกว่าเลือกหรือยัง — ตามแบบ StudentList) */
const rosterItems = computed<RosterItem[]>(() => {
  return students.value.map((s) => ({
    key: s.student_no,
    student_no: s.student_no,
    first_name: s.first_name,
    last_name: s.last_name,
    nickname: s.nickname,
    first_name_en: s.first_name_en,
    last_name_en: s.last_name_en,
    nickname_en: s.nickname_en,
    prefix: s.prefix,
    role_type: participantRoleType.value[s.student_no] || 'participant',
    role_detail:
      joinDutyRole(dutyPosition.value[s.student_no] ?? '', dutyNote.value[s.student_no] ?? '') ||
      null,
    status: participantStatus.value[s.student_no] || 'confirmed',
    earned_hours: participantHours.value[s.student_no] ?? 0,
    metadata: participantMeta.value[s.student_no] || {},
    profile: s as unknown as Record<string, unknown>,
  }))
})

// --- Modal state ---
const infoModalOpen = ref(false)
const infoModalKey = ref<number | null>(null)
const batchModalOpen = ref(false)

const infoItem = computed<RosterItem | null>(() => {
  if (infoModalKey.value === null) return null
  return rosterItems.value.find((r) => r.key === infoModalKey.value) ?? null
})

/** เปิด modal ข้อมูลเพิ่มเติมของนักเรียนคนนี้ */
const openInfoModal = (key: string | number) => {
  infoModalKey.value = Number(key)
  infoModalOpen.value = true
}

/** ปิด modal ข้อมูลเพิ่มเติม */
const closeInfoModal = () => {
  infoModalOpen.value = false
  infoModalKey.value = null
}

const selectedCount = computed(() => selectedNos.value.size)

const toggleSelect = (no: number) => {
  touchedParticipants.value = true
  const next = new Set(selectedNos.value)
  if (next.has(no)) {
    next.delete(no)
  } else {
    next.add(no)
  }
  selectedNos.value = next
}

const selectAll = () => {
  touchedParticipants.value = true
  selectedNos.value = new Set(students.value.map((s) => s.student_no))
}

const clearAll = () => {
  touchedParticipants.value = true
  selectedNos.value = new Set()
  dutyPosition.value = {}
  dutyNote.value = {}
  participantMeta.value = {}
  participantHours.value = {}
  participantRoleType.value = {}
  participantStatus.value = {}
}

const changeDuty = (no: number, position: string, note: string) => {
  dutyPosition.value[no] = position
  dutyNote.value[no] = note
  // trigger reactivity
  dutyPosition.value = { ...dutyPosition.value }
  dutyNote.value = { ...dutyNote.value }
}

// ================================================================
// 📋 Modal: ข้อมูลเพิ่มเติมของนักเรียน (ต่อคน)
// ================================================================
const saveInfoModal = (payload: {
  role_detail: string | null
  metadata: Record<string, unknown>
  customFields: CustomFieldEntry[]
}) => {
  const no = infoModalKey.value
  if (no === null) return
  const { position, note } = splitDutyRole(payload.role_detail)
  dutyPosition.value = { ...dutyPosition.value, [no]: position }
  dutyNote.value = { ...dutyNote.value, [no]: note }
  participantMeta.value = { ...participantMeta.value, [no]: payload.metadata }
  infoModalOpen.value = false
  infoModalKey.value = null
  Swal.fire({
    icon: 'success',
    title: 'บันทึกข้อมูลของนักเรียนคนนี้แล้ว',
    text: 'ยังไม่บันทึกกิจกรรม',
    confirmButtonColor: UI_COLOR.brand,
  })
}

// ================================================================
// 🎯 Modal: ตั้งค่าแบบกลุ่ม (Batch Apply) — หน้าที่ + Type B
// ================================================================
const openBatchModal = () => {
  if (!canManage.value) return
  batchModalOpen.value = true
}

const applyBatch = (payload: { dutyPosition: string; typeB: Record<string, unknown> }) => {
  const targets = Array.from(selectedNos.value)
  if (targets.length === 0) {
    Swal.fire('เลือกก่อน', 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คนก่อนตั้งค่าแบบกลุ่ม', 'warning')
    return
  }
  for (const no of targets) {
    // หน้าที่/ตำแหน่ง — ตั้งชุดให้ทุกคน (แทนที่ของเดิม + เคลียร์หมายเหตุเดิม ตามคำเตือนใน modal)
    if (payload.dutyPosition) {
      dutyPosition.value[no] = payload.dutyPosition
      dutyNote.value[no] = ''
    }
    // Type B — merge กับของเดิม (ตาม batch semantic)
    const meta = { ...participantMeta.value[no] }
    for (const [k, v] of Object.entries(payload.typeB)) {
      if (v === '' || v === null || v === undefined) {
        delete meta[k]
      } else {
        meta[k] = v
      }
    }
    participantMeta.value[no] = meta
  }
  // trigger reactivity
  dutyPosition.value = { ...dutyPosition.value }
  dutyNote.value = { ...dutyNote.value }
  participantMeta.value = { ...participantMeta.value }
  batchModalOpen.value = false
  Swal.fire({
    icon: 'success',
    title: `ตั้งค่าแบบกลุ่มให้ ${targets.length} คนแล้ว`,
    text: 'ยังไม่บันทึกกิจกรรม',
    confirmButtonColor: UI_COLOR.brand,
  })
}

// ================================================================
// 📥 Edit prefill
// ================================================================
const applyInitial = () => {
  const act = props.initialActivity
  if (props.mode !== 'edit' || !act) return

  form.value = {
    title: act.title,
    description: act.description ?? '',
    activity_date: act.activity_date,
    base_hours: Number(act.base_hours) || 0,
    status: typeof act.status === 'string' ? act.status : 'upcoming',
    // ค่าที่ไม่รู้จัก (backend เพิ่มก่อน deploy หน้าเว็บ) ต้องไม่ทำให้ดรอปดาวน์เพี้ยน
    category:
      typeof act.category === 'string' &&
      ACTIVITY_CATEGORIES.some((c) => c.value === act.category)
        ? act.category
        : '',
    registration_deadline: act.registration_deadline ?? '',
    capacity: act.capacity === null || act.capacity === undefined ? '' : String(act.capacity),
  }

  const meta = act.metadata || {}
  activityMetaRows.value = customFieldsFromMeta(meta)
  positions.value = getActivityPositions(meta)

  const reqFields = meta.required_fields
  requiredFields.value = new Set(Array.isArray(reqFields) ? reqFields.map(String) : [])

  // ผู้เข้าร่วมเดิม → เลือกไว้ + เติมค่า
  const parts = act.participants || []
  const nos = new Set<number>()
  const pos: Record<number, string> = {}
  const note: Record<number, string> = {}
  const metaByNo: Record<number, Record<string, unknown>> = {}
  const hours: Record<number, number> = {}
  const roleTypes: Record<number, string> = {}
  const statuses: Record<number, string> = {}
  for (const p of parts) {
    const no = p.student_no
    nos.add(no)
    const { position, note: n } = splitDutyRole(p.role_detail)
    pos[no] = position
    note[no] = n
    metaByNo[no] = { ...p.metadata }
    hours[no] = Number(p.earned_hours) || 0
    roleTypes[no] = typeof p.role_type === 'string' ? p.role_type : 'participant'
    statuses[no] = typeof p.status === 'string' ? p.status : 'confirmed'
  }
  selectedNos.value = nos
  dutyPosition.value = pos
  dutyNote.value = note
  participantMeta.value = metaByNo
  participantHours.value = hours
  participantRoleType.value = roleTypes
  participantStatus.value = statuses
}

const load = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    const list = await StudentService.getStudents(currentRoomId)
    students.value = (list as Student[]).filter((s) => s.status === 'active')
    if (props.mode === 'create') {
      positions.value = getActivityPositions(undefined)
    }
    applyInitial()
  } catch (error: unknown) {
    hasError.value = true
    const msg = error instanceof Error ? error.message : 'โหลดรายชื่อนักเรียนไม่สำเร็จ'
    Swal.fire({ icon: 'error', title: 'ข้อผิดพลาด', text: msg })
  } finally {
    isLoading.value = false
  }
}

onMounted(async () => {
  await load()
  // กู้ร่างหลังโหลดรายชื่อเสร็จ — ต้องกรอง selectedNos ด้วยรายชื่อจริง
  if (props.mode === 'create' && draft.restore()) applyDraft()
})

// ================================================================
// ✍️ Validation แบบ inline (ใต้ช่อง) + ปุ่มบันทึก disabled
// ================================================================
const titleError = computed(() => (form.value.title.trim() ? '' : 'กรุณากรอกชื่อกิจกรรม'))
const dateError = computed(() => (form.value.activity_date ? '' : 'กรุณาเลือกวันที่'))
const participantsError = computed(() =>
  selectedNos.value.size > 0 ? '' : 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คน',
)
/**
 * 📅 วันปิดรับต้องไม่หลังวันจัดกิจกรรม — ตรวจที่นี่ด้วย ถ้าปล่อยไป backend
 * จะได้ 400 หลังกดบันทึก ซึ่งผู้ใช้เสียข้อมูลที่กรอกไปแล้วทั้งฟอร์ม
 * (เทียบเป็น string ได้เพราะทั้งคู่เป็น `YYYY-MM-DD`)
 */
const deadlineError = computed(() => {
  const deadline = form.value.registration_deadline
  const activityDate = form.value.activity_date
  if (!deadline || !activityDate) return ''
  return deadline > activityDate ? 'วันปิดรับลงทะเบียนต้องไม่หลังวันจัดกิจกรรม' : ''
})
/** 🪑 ความจุ: เว้นว่าง = ไม่จำกัด · กรอกแล้วต้อง ≥ 1 (0 ใช้เฉพาะตอนแก้ไขเพื่อยกเลิกเพดาน) */
const capacityError = computed(() => {
  if (form.value.capacity === '') return ''
  const value = Number(form.value.capacity)
  if (!Number.isFinite(value) || !Number.isInteger(value) || value < 1) {
    return 'ความจุต้องเป็นจำนวนเต็มตั้งแต่ 1 ขึ้นไป (เว้นว่าง = ไม่จำกัด)'
  }
  return ''
})
const formValid = computed(
  () =>
    !titleError.value &&
    !dateError.value &&
    !participantsError.value &&
    !deadlineError.value &&
    !capacityError.value,
)

/** ฟอร์มถูกแก้หรือยัง — ใช้ทั้งก่อนออกจากหน้า และตัดสินว่าเขียนร่างไหม */
const isDirty = () =>
  props.mode === 'create' &&
  canManage.value &&
  (form.value.title.trim() !== '' ||
    form.value.description.trim() !== '' ||
    form.value.activity_date !== todayIso() ||
    Number(form.value.base_hours) > 0 ||
    form.value.category !== '' ||
    form.value.registration_deadline !== '' ||
    form.value.capacity !== '' ||
    selectedNos.value.size > 0 ||
    activityMetaRows.value.length > 0 ||
    requiredFields.value.size > 0)

useUnsavedGuard(isDirty)
onBeforeRouteLeave(() => confirmLeave(isDirty))

// ================================================================
// 🚀 Submit
// ================================================================
const submit = async () => {
  if (!canManage.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลกิจกรรมเท่านั้น', 'error')
  }
  // ปุ่มถูก disable ไว้แล้ว แต่ยังกันซ้ำ (เช่นกด Enter ในช่องข้อความ)
  if (!formValid.value) {
    showErrors.value = true
    return
  }

  // ⚠️ เตือนถ้าผู้เข้าร่วมที่เลือกมีตำแหน่งไม่อยู่ในรายการแล้ว
  const orphaned = Array.from(selectedNos.value).filter((no) => {
    const pos = dutyPosition.value[no]
    if (!pos) return false
    return !positions.value.includes(pos)
  })
  if (orphaned.length > 0) {
    const names = orphaned
      .map((no) => students.value.find((s) => s.student_no === no))
      .filter(Boolean)
      .map((s) => displayName(s!))
    const result = await Swal.fire({
      icon: 'warning',
      title: 'ตำแหน่งที่เลือกไม่อยู่ในรายการ',
      text: `${names.join(', ')} ยังมีตำแหน่งเก่าที่ถูกลบจากรายการแล้ว — บันทึกต่อไหม?`,
      showCancelButton: true,
      confirmButtonText: 'บันทึกต่อ',
      cancelButtonText: 'กลับไปแก้',
      confirmButtonColor: UI_COLOR.brand,
      cancelButtonColor: UI_COLOR.neutral,
    })
    if (!result.isConfirmed) return
  }

  // 🌟 สร้าง metadata กิจกรรม: custom_fields + dual-write คีย์เก่า + positions + required_fields
  const activityMetadata = buildActivityMeta(
    activityMetaRows.value,
    positions.value,
    Array.from(requiredFields.value),
    props.mode === 'edit' ? (props.initialActivity?.metadata ?? null) : null,
  )

  const participants: ActivityParticipantInput[] = []
  for (const no of selectedNos.value) {
    const student = students.value.find((s) => s.student_no === no)
    if (!student) continue
    // 🚨 Type A (โปรไฟล์) ห้ามส่งลง metadata — backend JOIN มาจาก users ให้เอง
    // custom_fields ต้องพกไปด้วย (ไม่งั้นข้อมูลเพิ่มเติมต่อคนหายตอนสร้าง — lesson R1)
    const meta = participantMeta.value[no] || {}
    const cleanMeta: Record<string, unknown> = {}
    if (props.mode === 'edit') {
      // แก้ไข → ส่ง metadata เต็มที่แก้ใน modal (round-trip) กันข้อมูลหาย
      Object.assign(cleanMeta, meta)
    } else {
      for (const [k, v] of Object.entries(meta)) {
        // 🧩 อนุญาต dynamic field (df_<n>) ด้วย — กันค่าหายตอนสร้าง/edit
        if (EVENT_FIELD_KEYS.has(k) || k === 'custom_fields' || k.startsWith('df_')) cleanMeta[k] = v
      }
    }
    participants.push({
      student_no: no,
      role_type:
        props.mode === 'edit' ? participantRoleType.value[no] || 'participant' : 'participant',
      role_detail: joinDutyRole(dutyPosition.value[no] ?? '', dutyNote.value[no] ?? '') || null,
      earned_hours:
        props.mode === 'edit'
          ? (participantHours.value[no] ?? 0)
          : form.value.base_hours > 0
            ? form.value.base_hours
            : 0,
      status: props.mode === 'edit' ? participantStatus.value[no] || 'confirmed' : 'confirmed',
      metadata: cleanMeta,
    })
  }

  isSaving.value = true
  try {
    if (props.mode === 'create') {
      await ActivityService.createActivity(currentRoomId, {
        title: form.value.title.trim(),
        description: form.value.description.trim() || null,
        activity_date: form.value.activity_date,
        base_hours: Number(form.value.base_hours) || 0,
        status: form.value.status,
        // `null` = ไม่ระบุหมวด / ไม่มีกำหนดปิดรับ / ไม่จำกัดความจุ (ตรงกับ backend)
        category: form.value.category || null,
        registration_deadline: form.value.registration_deadline || null,
        capacity: form.value.capacity === '' ? null : Number(form.value.capacity),
        metadata: activityMetadata,
        participants,
        user_name: currentUserName,
      })
      // ✅ บันทึกสำเร็จ = ล้างร่าง ไม่งั้นเปิดฟอร์มครั้งหน้าจะเจอข้อมูลเก่า
      draft.clear()
      await Swal.fire({
        icon: 'success',
        title: 'สร้างกิจกรรมสำเร็จ! 🎪',
        text: `"${form.value.title}" พร้อมผู้เข้าร่วม ${participants.length} คน ถูกบันทึกแล้ว`,
        confirmButtonColor: UI_COLOR.brand,
      })
      emit('saved', 0)
    } else {
      const activityId = editActivityId.value
      if (!activityId) throw new Error('ไม่พบ ID กิจกรรม')
      await ActivityService.updateActivity(currentRoomId, activityId, {
        title: form.value.title.trim(),
        description: form.value.description.trim() || null,
        activity_date: form.value.activity_date,
        base_hours: Number(form.value.base_hours) || 0,
        status: form.value.status,
        // 🏷️ ส่ง `null` = ล้างค่าจริง (ต่างจาก capacity ที่ PATCH ใช้ 0 เป็นสัญญาณ
        //    เพราะ `null` ใน PATCH ถูก backend มองว่า "ไม่ส่งมา" แล้วตัดทิ้ง)
        category: form.value.category || null,
        registration_deadline: form.value.registration_deadline || null,
        capacity: form.value.capacity === '' ? 0 : Number(form.value.capacity),
        metadata: activityMetadata,
        participants,
        user_name: currentUserName,
      })
      await Swal.fire({
        icon: 'success',
        title: 'แก้ไขกิจกรรมสำเร็จ! ✏️',
        text: `"${form.value.title}" ถูกอัปเดตแล้ว`,
        confirmButtonColor: UI_COLOR.brand,
      })
      emit('saved', activityId)
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'บันทึกไม่สำเร็จ'
    Swal.fire({ icon: 'error', title: 'ข้อผิดพลาด', text: msg })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Activity Setup"
      :title="mode === 'edit' ? 'แก้ไขกิจกรรม' : 'สร้างกิจกรรมใหม่'"
      :description="
        mode === 'edit' ? 'แก้ไขข้อมูลและผู้เข้าร่วม' : 'ตั้งค่ากิจกรรมและเลือกผู้เข้าร่วม'
      "
    >
      <template #actions>
        <router-link
          :to="mode === 'edit' && editActivityId ? `/activities/${editActivityId}` : '/activities'"
          class="btn-ghost-ui"
        >
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          {{ mode === 'edit' ? 'กลับหน้ารายละเอียด' : 'กลับรายการ' }}
        </router-link>
      </template>
    </PageHeader>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <div v-else class="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-5">
      <!-- ========== โซน A: ตั้งค่ากิจกรรม ========== -->
      <div class="min-w-0 space-y-4 sm:space-y-5 lg:col-span-2">
        <!-- ข้อมูลกิจกรรม -->
        <section class="page-card p-4 sm:p-6">
          <h2 class="section-title mb-3 flex items-center gap-2 sm:mb-4">
            <i class="bi bi-card-heading text-brand-700" aria-hidden="true"></i> ข้อมูลกิจกรรม
          </h2>
          <div class="space-y-4">
            <div>
              <label class="field-label" for="activityTitle">ชื่อกิจกรรม *</label>
              <input
                id="activityTitle"
                v-model="form.title"
                type="text"
                placeholder="เช่น ค่ายอาสา, งานกีฬาสี, ทัศนศึกษา"
                class="field"
                :aria-invalid="(showErrors || touchedTitle) && !!titleError"
                :aria-describedby="
                  (showErrors || touchedTitle) && titleError ? 'activityTitleError' : undefined
                "
                @blur="touchedTitle = true"
              />
              <p
                v-if="(showErrors || touchedTitle) && titleError"
                id="activityTitleError"
                class="mt-1 text-xs font-bold text-danger-600"
              >
                {{ titleError }}
              </p>
            </div>
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
              <div>
                <label class="field-label" for="activityDate">วันที่ *</label>
                <input
                  id="activityDate"
                  v-model="form.activity_date"
                  type="date"
                  class="field"
                  :aria-invalid="(showErrors || touchedDate) && !!dateError"
                  :aria-describedby="
                    (showErrors || touchedDate) && dateError ? 'activityDateError' : undefined
                  "
                  @blur="touchedDate = true"
                />
                <p
                  v-if="(showErrors || touchedDate) && dateError"
                  id="activityDateError"
                  class="mt-1 text-xs font-bold text-danger-600"
                >
                  {{ dateError }}
                </p>
              </div>
              <div>
                <label class="field-label" for="activityHours">ชั่วโมงจิตอาสา</label>
                <input
                  id="activityHours"
                  v-model.number="form.base_hours"
                  type="number"
                  min="0"
                  step="0.5"
                  placeholder="0"
                  class="field num"
                />
              </div>
            </div>
            <div>
              <label class="field-label" for="activityStatus">สถานะ</label>
              <select id="activityStatus" v-model="form.status" class="field">
                <option value="upcoming">กำลังจะมา</option>
                <option value="ongoing">กำลังดำเนินการ</option>
                <option value="completed">เสร็จสิ้น</option>
                <option value="cancelled">ยกเลิก</option>
              </select>
            </div>
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
              <div>
                <label class="field-label" for="activityCategory">หมวดกิจกรรม</label>
                <select id="activityCategory" v-model="form.category" class="field">
                  <option value="">ไม่ระบุหมวด</option>
                  <option v-for="c in ACTIVITY_CATEGORIES" :key="c.value" :value="c.value">
                    {{ c.label }}
                  </option>
                </select>
              </div>
              <div>
                <label class="field-label" for="activityCapacity">ความจุ</label>
                <input
                  id="activityCapacity"
                  v-model="form.capacity"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="ไม่จำกัด"
                  class="field num"
                  :aria-invalid="!!capacityError"
                  :aria-describedby="capacityError ? 'activityCapacityError' : undefined"
                />
                <p
                  v-if="capacityError"
                  id="activityCapacityError"
                  class="mt-1 text-xs font-bold text-danger-600"
                >
                  {{ capacityError }}
                </p>
                <p v-else class="mt-1 text-xs leading-relaxed text-stone-500">
                  เว้นว่าง = รับได้ไม่จำกัด · เกินแล้วคนใหม่ไปอยู่คิวสำรอง
                </p>
              </div>
            </div>
            <div>
              <label class="field-label" for="activityDeadline">วันปิดรับลงทะเบียน</label>
              <input
                id="activityDeadline"
                v-model="form.registration_deadline"
                type="date"
                class="field"
                :max="form.activity_date || undefined"
                :aria-invalid="!!deadlineError"
                :aria-describedby="deadlineError ? 'activityDeadlineError' : undefined"
              />
              <p
                v-if="deadlineError"
                id="activityDeadlineError"
                class="mt-1 text-xs font-bold text-danger-600"
              >
                {{ deadlineError }}
              </p>
              <p v-else class="mt-1 text-xs leading-relaxed text-stone-500">
                วันสุดท้ายที่ยังรับผู้เข้าร่วม — ต้องไม่หลังวันจัดกิจกรรม (เว้นว่าง = ไม่มีกำหนด)
              </p>
            </div>
            <div>
              <label class="field-label" for="activityDescription">รายละเอียด</label>
              <textarea
                id="activityDescription"
                v-model="form.description"
                rows="3"
                placeholder="รายละเอียดกิจกรรม กำหนดการคร่าว ๆ..."
                class="field resize-none"
              ></textarea>
            </div>
          </div>
        </section>

        <!-- 🎖️ หน้าที่/ตำแหน่งของกิจกรรม -->
        <section class="page-card p-4 sm:p-6">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-diagram-3 text-brand-700" aria-hidden="true"></i> หน้าที่/ตำแหน่ง
          </h2>
          <p class="mt-1.5 text-xs leading-relaxed text-stone-500">
            กำหนดรายการตำแหน่งที่ใช้ในกิจกรรมนี้ — ผู้เข้าร่วมเลือกจากรายการนี้
            และตั้งค่าแบบกลุ่มได้ (เช่น หัวหน้ากลุ่ม, ทีมงาน, ฝ่ายทะเบียน)
          </p>

          <div class="mt-3 flex gap-2 sm:mt-4">
            <input
              v-model="newPosition"
              type="text"
              placeholder="เช่น ฝ่ายทะเบียน"
              aria-label="ชื่อตำแหน่งใหม่"
              class="field min-w-0 flex-1"
              @keyup.enter="addPosition"
            />
            <button type="button" class="btn-primary shrink-0" @click="addPosition">
              <i class="bi bi-plus-lg" aria-hidden="true"></i> เพิ่ม
            </button>
          </div>

          <p
            v-if="positions.length === 0"
            class="mt-3 rounded-xl border border-stone-200 bg-stone-50/60 px-4 py-3.5 text-center text-xs text-stone-500 sm:mt-4"
          >
            ยังไม่มีตำแหน่ง — เพิ่มด้านบน หรือใช้ค่าเริ่มต้น
          </p>
          <div v-else class="mt-3 flex flex-wrap gap-2 sm:mt-4">
            <div
              v-for="(pos, index) in positions"
              :key="pos"
              class="inline-flex items-center gap-0.5 rounded-xl border border-brand-200 bg-brand-50 py-0.5 pe-0.5 ps-3 text-xs font-bold text-brand-700"
            >
              <span class="max-w-[6.5rem] truncate sm:max-w-[10rem]">{{ pos }}</span>
              <button
                v-if="positions.length > 1"
                type="button"
                :disabled="index === 0"
                class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-brand-700/60 transition-colors hover:bg-brand-100 hover:text-brand-700 disabled:opacity-30"
                title="เลื่อนขึ้น"
                aria-label="เลื่อนตำแหน่งขึ้น"
                @click="movePosition(index, -1)"
              >
                <i class="bi bi-chevron-up text-xs" aria-hidden="true"></i>
              </button>
              <button
                v-if="positions.length > 1"
                type="button"
                :disabled="index === positions.length - 1"
                class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-brand-700/60 transition-colors hover:bg-brand-100 hover:text-brand-700 disabled:opacity-30"
                title="เลื่อนลง"
                aria-label="เลื่อนตำแหน่งลง"
                @click="movePosition(index, 1)"
              >
                <i class="bi bi-chevron-down text-xs" aria-hidden="true"></i>
              </button>
              <button
                type="button"
                class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-stone-500 transition-colors hover:bg-danger-50 hover:text-danger-600"
                title="ลบตำแหน่ง"
                aria-label="ลบตำแหน่ง"
                @click="removePosition(index)"
              >
                <i class="bi bi-x-lg text-xs" aria-hidden="true"></i>
              </button>
            </div>
          </div>
        </section>

        <!-- 📝 ข้อมูลเพิ่มเติมของกิจกรรม (หัวข้อ + ค่า) -->
        <section class="page-card p-4 sm:p-6">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-asterisk text-brand-700" aria-hidden="true"></i> ข้อมูลเพิ่มเติมของกิจกรรม
          </h2>
          <p class="mt-1.5 text-xs leading-relaxed text-stone-500">
            เพิ่มข้อมูลที่อยากให้คนเห็น เช่น สถานที่, ลิงก์แผนที่, กำหนดการ — แค่บอกหัวข้อกับค่า
          </p>
          <div class="mt-3 sm:mt-4">
            <ExtraInfoRows
              :rows="activityMetaRows"
              :quick-add="ACTIVITY_META_QUICK_ADD"
              placeholder="ค่า (เช่น สนามกีฬาโรงเรียน)"
              @update:rows="
                (rows: CustomFieldEntry[]) => {
                  activityMetaRows = rows
                }
              "
            />
          </div>
        </section>
      </div>

      <!-- ========== โซน B: ผู้เข้าร่วม ========== -->
      <div class="min-w-0 space-y-4 sm:space-y-5 lg:col-span-3">
        <!-- Field Selector -->
        <section class="page-card p-4 sm:p-6">
          <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0">
              <h2 class="section-title flex items-center gap-2">
                <i class="bi bi-list-check text-brand-700" aria-hidden="true"></i>
                ข้อมูลที่จัดเก็บของนักเรียน
              </h2>
              <p class="mt-1 text-xs leading-relaxed text-stone-500">
                ติ๊กเลือกฟิลด์ → ผู้เข้าร่วมต้องกรอกข้อมูลเหล่านี้ ·
                <i class="bi bi-lock-fill" aria-hidden="true"></i> = ดึงจากโปรไฟล์อัตโนมัติ
              </p>
            </div>
            <span class="chip shrink-0 self-start bg-brand-50 text-brand-700">
              เลือกแล้ว {{ requiredFields.size }}/{{ ALL_ACTIVITY_FIELDS.length }} ฟิลด์
            </span>
          </div>

          <div v-for="cat in ACTIVITY_FIELD_CATEGORY_ORDER" :key="cat" class="mt-3 sm:mt-4">
            <h3
              class="mb-2.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-500"
            >
              <i
                class="bi"
                :class="cat === 'profile' ? 'bi-lock-fill' : 'bi-chevron-right'"
                aria-hidden="true"
              ></i>
              {{ ACTIVITY_FIELD_CATEGORY_LABELS[cat] }}
            </h3>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label
                v-for="field in ALL_ACTIVITY_FIELDS.filter((f) => f.category === cat)"
                :key="field.key"
                class="flex cursor-pointer select-none items-start gap-2.5 rounded-xl border px-3 py-2 transition-colors sm:py-2.5"
                :class="
                  requiredFields.has(field.key)
                    ? 'border-brand-200 bg-brand-50'
                    : 'border-stone-200 bg-white hover:bg-stone-50'
                "
              >
                <input
                  type="checkbox"
                  :checked="requiredFields.has(field.key)"
                  class="mt-0.5 h-4 w-4 shrink-0 rounded accent-brand-700"
                  @change="toggleRequiredField(field.key)"
                />
                <span class="min-w-0">
                  <span class="block text-xs font-bold text-stone-700">
                    {{ field.label }}
                    <i
                      v-if="cat === 'profile'"
                      class="bi bi-lock-fill text-[10px] text-brand-700"
                      title="ระบบจะดึงจากโปรไฟล์ให้อัตโนมัติ ไม่ต้องให้คนกรอกใหม่"
                      aria-hidden="true"
                    ></i>
                  </span>
                  <span class="mt-0.5 hidden truncate text-[10px] text-stone-500 sm:block">{{
                    field.hint || field.placeholder || ''
                  }}</span>
                </span>
              </label>
            </div>
          </div>
        </section>

        <!-- เลือกผู้เข้าร่วม -->
        <section class="page-card p-4 sm:p-6">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-people-fill text-brand-700" aria-hidden="true"></i> เลือกผู้เข้าร่วม
          </h2>
          <p class="mt-1.5 text-xs leading-relaxed text-stone-500">
            ติ๊กชื่อ → ตั้งหน้าที่/ข้อมูลเพิ่มเติมของแต่ละคน หรือใช้ "ตั้งค่าแบบกลุ่ม"
            สำหรับหลายคนพร้อมกัน
          </p>

          <div
            class="mt-3 flex items-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 text-xs font-bold text-brand-700 sm:mt-4"
          >
            <i class="bi bi-person-check-fill" aria-hidden="true"></i> เลือกแล้ว
            <span class="num">{{ selectedCount }}</span> คน
          </div>

          <p
            v-if="(showErrors || touchedParticipants) && participantsError"
            id="activityParticipantsError"
            class="mt-2 text-xs font-bold text-danger-600"
            role="alert"
          >
            {{ participantsError }}
          </p>

          <div class="mt-3 sm:mt-4">
            <ParticipantRosterList
              v-if="students.length > 0"
              :items="rosterItems"
              :positions="positions"
              :selected-keys="selectedNos"
              selectable
              :can-manage="canManage"
              :empty-text="'ยังไม่มีนักเรียนในห้องนี้'"
              @toggle-select="(key) => toggleSelect(Number(key))"
              @select-all="selectAll"
              @clear-all="clearAll"
              @change-duty="(key, position, note) => changeDuty(Number(key), position, note)"
              @open-info="openInfoModal"
              @batch="openBatchModal"
            />

            <StateBlock
              v-else-if="hasError"
              variant="error"
              title="โหลดรายชื่อนักเรียนไม่สำเร็จ"
              hint="ตรวจการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
              @retry="load"
            />

            <StateBlock
              v-else
              variant="empty"
              title="ยังไม่มีนักเรียนในห้องนี้"
              hint="เพิ่มนักเรียนเข้าห้องเรียนก่อน แล้วจึงสร้างกิจกรรม"
            />
          </div>

          <p
            v-if="typeBColumns.length === 0 && students.length > 0"
            class="mt-3 text-[11px] text-stone-500"
          >
            ยังไม่ได้เลือกฟิลด์ Type B → ติ๊กในส่วน "ข้อมูลที่จัดเก็บของนักเรียน" ด้านบน
            แล้วผู้เข้าร่วมจะกรอกได้ในปุ่ม "ข้อมูลเพิ่มเติม"
          </p>
        </section>

        <!-- ปุ่มบันทึก -->
        <div class="page-card flex flex-col-reverse gap-2 p-4 sm:flex-row sm:justify-end sm:p-5">
          <router-link
            :to="mode === 'edit' && editActivityId ? `/activities/${editActivityId}` : '/activities'"
            class="btn-ghost-ui"
          >
            ยกเลิก
          </router-link>
          <button
            type="button"
            class="btn-primary"
            :disabled="isSaving || !formValid"
            @click="submit"
          >
            <i v-if="isSaving" class="bi bi-arrow-repeat animate-spin" aria-hidden="true"></i>
            <i v-else class="bi bi-check-lg" aria-hidden="true"></i>
            {{ isSaving ? 'กำลังบันทึก...' : mode === 'edit' ? 'บันทึกการแก้ไข' : 'บันทึกกิจกรรม' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 📋 Modal: ข้อมูลเพิ่มเติมของนักเรียน (ต่อคน) -->
    <ParticipantInfoModal
      :open="infoModalOpen && !!infoItem"
      :item="infoItem"
      :type-a-fields="typeAColumns"
      :type-b-fields="typeBColumns"
      :positions="positions"
      :can-manage="canManage"
      @close="closeInfoModal"
      @save="saveInfoModal"
    />

    <!-- 🎯 Modal: ตั้งค่าแบบกลุ่ม -->
    <BatchApplyModal
      :open="batchModalOpen"
      :positions="positions"
      :type-b-fields="typeBColumns"
      :count="selectedCount"
      @close="batchModalOpen = false"
      @apply="applyBatch"
    />
  </div>
</template>
