<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import { ActivityService } from '@/services/activity'
import { displayName } from '@/utils/name'
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
import ExtraInfoRows from '@/components/activities/ExtraInfoRows.vue'
import ParticipantRosterList from '@/components/activities/ParticipantRosterList.vue'
import ParticipantInfoModal from '@/components/activities/ParticipantInfoModal.vue'
import BatchApplyModal from '@/components/activities/BatchApplyModal.vue'
import Swal from 'sweetalert2'

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

const canManage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

// ================================================================
// 🏷️ โซน A — ข้อมูลกิจกรรม
// ================================================================
const form = ref({
  title: '',
  description: '',
  activity_date: new Date().toISOString().slice(0, 10),
  base_hours: 0,
  status: 'upcoming' as string,
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
    return Swal.fire('ซ้ำ', `ตำแหน่ง "${value}" มีอยู่แล้ว`, 'warning')
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
  const next = new Set(selectedNos.value)
  if (next.has(no)) {
    next.delete(no)
  } else {
    next.add(no)
  }
  selectedNos.value = next
}

const selectAll = () => {
  selectedNos.value = new Set(students.value.map((s) => s.student_no))
}

const clearAll = () => {
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
  Toast.fire({ icon: 'success', title: 'บันทึกข้อมูลของนักเรียนคนนี้แล้ว (ยังไม่บันทึกกิจกรรม)' })
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
  Toast.fire({
    icon: 'success',
    title: `ตั้งค่าแบบกลุ่มให้ ${targets.length} คนแล้ว (ยังไม่บันทึก)`,
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

onMounted(async () => {
  isLoading.value = true
  try {
    const list = await StudentService.getStudents(currentRoomId)
    students.value = (list as Student[]).filter((s) => s.status === 'active')
    if (props.mode === 'create') {
      positions.value = getActivityPositions(undefined)
    }
    applyInitial()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'โหลดรายชื่อนักเรียนไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  } finally {
    isLoading.value = false
  }
})

// ================================================================
// 🚀 Submit
// ================================================================
const validateForm = (): string | null => {
  if (!form.value.title.trim()) return 'กรุณากรอกชื่อกิจกรรม'
  if (!form.value.activity_date) return 'กรุณาเลือกวันที่'
  if (selectedNos.value.size === 0) return 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คน'
  return null
}

const submit = async () => {
  if (!canManage.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลกิจกรรมเท่านั้น', 'error')
  }
  const error = validateForm()
  if (error) return Swal.fire('กรอกข้อมูลไม่ครบ', error, 'warning')

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
        if (EVENT_FIELD_KEYS.has(k) || k === 'custom_fields') cleanMeta[k] = v
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
        metadata: activityMetadata,
        participants,
        user_name: currentUserName,
      })
      await Swal.fire({
        icon: 'success',
        title: 'สร้างกิจกรรมสำเร็จ! 🎪',
        text: `"${form.value.title}" พร้อมผู้เข้าร่วม ${participants.length} คน ถูกบันทึกแล้ว`,
        confirmButtonColor: '#8b5cf6',
        customClass: { popup: 'rounded-[2rem] shadow-2xl' },
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
        metadata: activityMetadata,
        participants,
        user_name: currentUserName,
      })
      await Swal.fire({
        icon: 'success',
        title: 'แก้ไขกิจกรรมสำเร็จ! ✏️',
        text: `"${form.value.title}" ถูกอัปเดตแล้ว`,
        confirmButtonColor: '#8b5cf6',
        customClass: { popup: 'rounded-[2rem] shadow-2xl' },
      })
      emit('saved', activityId)
    }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'บันทึกไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-7xl mx-auto">
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-3">
        <div>
          <h3
            class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-2.5"
          >
            <div
              class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0"
            >
              <i :class="mode === 'edit' ? 'bi bi-pencil-square' : 'bi bi-calendar-plus-fill'"></i>
            </div>
            {{ mode === 'edit' ? 'แก้ไขกิจกรรม' : 'สร้างกิจกรรมใหม่' }}
          </h3>
          <p class="text-slate-500 mt-1.5 ml-1 text-sm md:text-base">
            {{
              mode === 'edit'
                ? 'แก้ไขข้อมูลกิจกรรม ตำแหน่ง และผู้เข้าร่วมได้ทุกอย่าง'
                : 'กรอกข้อมูลหัวกิจกรรม + เลือกฟิลด์ที่ต้องจัดเก็บ + เลือกผู้เข้าร่วม'
            }}
          </p>
        </div>
        <router-link
          :to="mode === 'edit' && editActivityId ? `/activities/${editActivityId}` : '/activities'"
          class="inline-flex items-center gap-2 text-sm font-bold text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-4 py-2 rounded-xl transition-all"
        >
          <i class="bi bi-arrow-left"></i>
          {{ mode === 'edit' ? 'กลับหน้ารายละเอียด' : 'กลับรายการ' }}
        </router-link>
      </div>

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังโหลดรายชื่อนักเรียน...</p>
      </div>

      <div v-else class="grid grid-cols-1 lg:grid-cols-5 gap-5 md:gap-6">
        <!-- ========== โซน A: ตั้งค่ากิจกรรม ========== -->
        <div class="lg:col-span-2 space-y-5">
          <!-- ข้อมูลกิจกรรม -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-4 flex items-center gap-2">
              <i class="bi bi-card-heading text-violet-500"></i> ข้อมูลกิจกรรม
            </h4>
            <div class="space-y-4">
              <div>
                <label
                  class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block"
                  >ชื่อกิจกรรม *</label
                >
                <input
                  v-model="form.title"
                  type="text"
                  placeholder="เช่น ค่ายอาสา, งานกีฬาสี, ทัศนศึกษา"
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                />
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block"
                    >วันที่ *</label
                  >
                  <input
                    v-model="form.activity_date"
                    type="date"
                    class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                  />
                </div>
                <div>
                  <label
                    class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block"
                    >ชั่วโมงจิตอาสา</label
                  >
                  <input
                    v-model.number="form.base_hours"
                    type="number"
                    min="0"
                    step="0.5"
                    placeholder="0"
                    class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                  />
                </div>
              </div>
              <div>
                <label
                  class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block"
                  >สถานะ</label
                >
                <select
                  v-model="form.status"
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                >
                  <option value="upcoming">กำลังจะมา</option>
                  <option value="ongoing">กำลังดำเนินการ</option>
                  <option value="completed">เสร็จสิ้น</option>
                  <option value="cancelled">ยกเลิก</option>
                </select>
              </div>
              <div>
                <label
                  class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block"
                  >รายละเอียด</label
                >
                <textarea
                  v-model="form.description"
                  rows="3"
                  placeholder="รายละเอียดกิจกรรม กำหนดการคร่าว ๆ..."
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 resize-none"
                ></textarea>
              </div>
            </div>
          </div>

          <!-- 🎖️ หน้าที่/ตำแหน่งของกิจกรรม -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div class="flex items-center justify-between mb-1">
              <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-diagram-3 text-violet-500"></i> หน้าที่/ตำแหน่ง
              </h4>
            </div>
            <p class="text-xs text-slate-400 mb-4">
              กำหนดรายการตำแหน่งที่ใช้ในกิจกรรมนี้ — ผู้เข้าร่วมเลือกจากรายการนี้
              และตั้งค่าแบบกลุ่มได้ (เช่น หัวหน้ากลุ่ม, ทีมงาน, ฝ่ายทะเบียน)
            </p>

            <div class="flex gap-2 mb-3">
              <input
                v-model="newPosition"
                type="text"
                placeholder="เช่น ฝ่ายทะเบียน"
                @keyup.enter="addPosition"
                class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
              />
              <button
                @click="addPosition"
                class="px-3 py-2 text-xs font-bold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-sm transition-all inline-flex items-center gap-1 flex-shrink-0"
              >
                <i class="bi bi-plus-lg"></i> เพิ่ม
              </button>
            </div>

            <div
              v-if="positions.length === 0"
              class="text-center py-4 text-xs text-slate-400 bg-slate-50 rounded-xl"
            >
              ยังไม่มีตำแหน่ง — เพิ่มด้านบน หรือใช้ค่าเริ่มต้น
            </div>
            <div v-else class="flex flex-wrap gap-2">
              <div
                v-for="(pos, index) in positions"
                :key="pos"
                class="group inline-flex items-center gap-1 bg-violet-50 border border-violet-200 text-violet-700 rounded-full px-3 py-1.5 text-xs font-bold"
              >
                <span>{{ pos }}</span>
                <button
                  v-if="positions.length > 1"
                  type="button"
                  @click="movePosition(index, -1)"
                  :disabled="index === 0"
                  class="w-5 h-5 rounded-full flex items-center justify-center text-violet-400 hover:text-violet-700 hover:bg-violet-100 transition-colors disabled:opacity-30"
                  title="เลื่อนขึ้น"
                >
                  <i class="bi bi-chevron-up text-[10px]"></i>
                </button>
                <button
                  v-if="positions.length > 1"
                  type="button"
                  @click="movePosition(index, 1)"
                  :disabled="index === positions.length - 1"
                  class="w-5 h-5 rounded-full flex items-center justify-center text-violet-400 hover:text-violet-700 hover:bg-violet-100 transition-colors disabled:opacity-30"
                  title="เลื่อนลง"
                >
                  <i class="bi bi-chevron-down text-[10px]"></i>
                </button>
                <button
                  type="button"
                  @click="removePosition(index)"
                  class="w-5 h-5 rounded-full flex items-center justify-center text-violet-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                  title="ลบตำแหน่ง"
                >
                  <i class="bi bi-x-lg text-[10px]"></i>
                </button>
              </div>
            </div>
          </div>

          <!-- 📝 ข้อมูลเพิ่มเติมของกิจกรรม (หัวข้อ + ค่า) -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-1 flex items-center gap-2">
              <i class="bi bi-asterisk text-violet-500"></i> ข้อมูลเพิ่มเติมของกิจกรรม
            </h4>
            <p class="text-xs text-slate-400 mb-4">
              เพิ่มข้อมูลที่อยากให้คนเห็น เช่น สถานที่, ลิงก์แผนที่, กำหนดการ — แค่บอกหัวข้อกับค่า
            </p>
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
        </div>

        <!-- ========== โซน B: ผู้เข้าร่วม ========== -->
        <div class="lg:col-span-3 space-y-5">
          <!-- Field Selector -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div
              class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-2"
            >
              <div>
                <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                  <i class="bi bi-list-check text-violet-500"></i>
                  ข้อมูลที่ต้องการจัดเก็บของนักเรียน (Required Data)
                </h4>
                <p class="text-xs text-slate-400 mt-0.5">
                  ติ๊กเลือกฟิลด์ → ผู้เข้าร่วมต้องกรอกข้อมูลเหล่านี้ · 🔒 = ดึงจากโปรไฟล์อัตโนมัติ
                </p>
              </div>
              <span
                class="text-xs font-bold text-violet-600 bg-violet-50 px-3 py-1.5 rounded-lg whitespace-nowrap"
              >
                เลือกแล้ว {{ requiredFields.size }}/{{ ALL_ACTIVITY_FIELDS.length }} ฟิลด์
              </span>
            </div>

            <div v-for="cat in ACTIVITY_FIELD_CATEGORY_ORDER" :key="cat" class="mb-4 last:mb-0">
              <h5
                class="text-xs font-black text-slate-400 uppercase tracking-wider mb-2.5 flex items-center gap-1.5"
              >
                <i class="bi" :class="cat === 'profile' ? 'bi-lock-fill' : 'bi-chevron-right'"></i>
                {{ ACTIVITY_FIELD_CATEGORY_LABELS[cat] }}
              </h5>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <label
                  v-for="field in ALL_ACTIVITY_FIELDS.filter((f) => f.category === cat)"
                  :key="field.key"
                  class="flex items-start gap-2.5 px-3 py-2.5 rounded-xl border cursor-pointer transition-all select-none"
                  :class="
                    requiredFields.has(field.key)
                      ? 'bg-violet-50 border-violet-300 shadow-sm'
                      : 'bg-slate-50 border-slate-200 hover:border-violet-200 hover:bg-white'
                  "
                >
                  <input
                    type="checkbox"
                    :checked="requiredFields.has(field.key)"
                    @change="toggleRequiredField(field.key)"
                    class="mt-0.5 w-4 h-4 rounded accent-violet-600 flex-shrink-0"
                  />
                  <span class="min-w-0">
                    <span class="block text-xs font-bold text-slate-700">
                      {{ field.label }}
                      <span
                        v-if="cat === 'profile'"
                        class="text-[10px] text-violet-500"
                        title="ระบบจะดึงจากโปรไฟล์ให้อัตโนมัติ ไม่ต้องให้คนกรอกใหม่"
                        >🔒</span
                      >
                    </span>
                    <span class="block text-[10px] text-slate-400 mt-0.5">{{
                      field.hint || field.placeholder || ''
                    }}</span>
                  </span>
                </label>
              </div>
            </div>
          </div>

          <!-- เลือกผู้เข้าร่วม -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div
              class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-3"
            >
              <div>
                <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                  <i class="bi bi-people-fill text-violet-500"></i> เลือกผู้เข้าร่วม
                </h4>
                <p class="text-xs text-slate-400 mt-0.5">
                  ติ๊กชื่อ → ตั้งหน้าที่/ข้อมูลเพิ่มเติมของแต่ละคน หรือใช้ "ตั้งค่าแบบกลุ่ม"
                  สำหรับหลายคนพร้อมกัน
                </p>
              </div>
            </div>

            <div
              class="flex items-center gap-2 text-xs font-bold text-violet-600 bg-violet-50 border border-violet-100 rounded-xl px-3 py-2 mb-4"
            >
              <i class="bi bi-person-check-fill"></i> เลือกแล้ว {{ selectedCount }} คน
            </div>

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

            <div v-else class="text-center py-10 text-slate-400 text-sm">
              ยังไม่มีนักเรียนในห้องนี้
            </div>

            <p
              v-if="typeBColumns.length === 0 && students.length > 0"
              class="text-[11px] text-slate-400 mt-3"
            >
              💡 ยังไม่ได้เลือกฟิลด์ Type B → ติ๊กในส่วน "Required Data" ด้านบน
              แล้วผู้เข้าร่วมจะกรอกได้ในปุ่ม "ข้อมูลเพิ่มเติม"
            </p>
          </div>

          <!-- ปุ่มบันทึก -->
          <div class="mt-5 flex flex-col sm:flex-row justify-end gap-3">
            <router-link
              :to="
                mode === 'edit' && editActivityId ? `/activities/${editActivityId}` : '/activities'
              "
              class="w-full sm:w-auto px-6 py-3 text-slate-500 hover:text-slate-800 hover:bg-slate-100 font-bold rounded-xl transition-all text-center"
            >
              ยกเลิก
            </router-link>
            <button
              @click="submit"
              :disabled="isSaving"
              class="w-full sm:w-auto px-8 py-3 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white font-bold rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center justify-center gap-2"
            >
              <i v-if="isSaving" class="bi bi-arrow-repeat animate-spin"></i>
              <i v-else class="bi bi-check-lg"></i>
              {{
                isSaving ? 'กำลังบันทึก...' : mode === 'edit' ? 'บันทึกการแก้ไข' : 'บันทึกกิจกรรม'
              }}
            </button>
          </div>
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
