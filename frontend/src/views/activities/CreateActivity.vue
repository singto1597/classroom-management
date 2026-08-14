<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import { ActivityService } from '@/services/activity'
import type { Student } from '@/types/student'
import type { ActivityParticipantInput } from '@/types/activity'
import {
  ALL_ACTIVITY_FIELDS,
  EVENT_FIELDS,
  PROFILE_FIELD_KEYS,
  EVENT_FIELD_KEYS,
  ACTIVITY_FIELD_CATEGORY_LABELS,
  ACTIVITY_FIELD_CATEGORY_ORDER,
  type ActivityField,
} from '@/constants/activityFields'
import ActivityFieldControl from '@/components/activities/ActivityFieldControl.vue'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const isLoading = ref(true)
const isSaving = ref(false)

// --- ฟอร์มหลัก ---
const form = ref({
  title: '',
  description: '',
  activity_date: new Date().toISOString().slice(0, 10),
  base_hours: 0,
  status: 'upcoming' as string,
})

// --- 🌟 Metadata กิจกรรม (key-value) เก็บพิกัด/ลิ้งก์/แท็ก ---
interface MetaEntry {
  key: string
  value: string
}
const activityMeta = ref<MetaEntry[]>([{ key: '', value: '' }])

// ฟิลด์ช่วย (preset) สำหรับ metadata
const metaPresets = [
  { key: 'tags', placeholder: 'เช่น กีฬา, ค่าย, ทัศนศึกษา (คั่นด้วย ,)' },
  { key: 'location_url', placeholder: 'https://maps.google.com/...' },
  { key: 'agenda', placeholder: '08:00 เปิดงาน | 10:00 แข่ง | 12:00 พัก' },
  { key: 'location_name', placeholder: 'สนามกีฬาโรงเรียน' },
]

// ================================================================
// 🌟 Field Selector (Required Data) — ข้อมูลที่ต้องการจัดเก็บสำหรับกิจกรรมนี้
// เก็บ key ที่ติ๊กลง activities.metadata.required_fields
// Type A (🔒) → ดึงจากโปรไฟล์อัตโนมัติ ไม่ให้กรอกใหม่
// Type B → เป็นคอลัมน์ที่แก้ในตาราง / Batch Apply ได้
// ================================================================
const requiredFields = ref<Set<string>>(new Set())

const selectedFields = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter((f) => requiredFields.value.has(f.key)),
)
const typeAColumns = computed<ActivityField[]>(() =>
  selectedFields.value.filter((f) => PROFILE_FIELD_KEYS.has(f.key)),
)
const typeBColumns = computed<ActivityField[]>(() =>
  selectedFields.value.filter((f) => EVENT_FIELD_KEYS.has(f.key)),
)
/** ฟิลด์ Type B ที่ถูกเลือก — ใช้ใน Batch Apply Modal */
const batchFields = computed<ActivityField[]>(() =>
  EVENT_FIELDS.filter((f) => requiredFields.value.has(f.key)),
)
/** ฟิลด์ Type B ที่ถูกเลือกและสามารถตั้งค่าแบบกลุ่มได้ (ไม่ใช่ boolean ที่ต้องการค่าเฉพาะราย) */
const batchSettableFields = computed<ActivityField[]>(() => batchFields.value)

const toggleRequiredField = (key: string) => {
  const next = new Set(requiredFields.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  requiredFields.value = next
}

// --- รายชื่อนักเรียน + การเลือก (เป็นทั้งผู้เข้าร่วมและเป้าหมาย Batch Apply) ---
const students = ref<Student[]>([])
const selectedNos = ref<Set<number>>(new Set())
const roleDetails = ref<Record<number, string>>({})
const participantMeta = ref<Record<number, Record<string, unknown>>>({})

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

onMounted(async () => {
  isLoading.value = true
  try {
    const list = await StudentService.getStudents(currentRoomId)
    students.value = (list as Student[]).filter((s) => s.status === 'active')
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'โหลดรายชื่อนักเรียนไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  } finally {
    isLoading.value = false
  }
})

const selectedCount = computed(() => selectedNos.value.size)

const toggleSelect = (student: Student) => {
  const no = student.student_no
  if (selectedNos.value.has(no)) {
    selectedNos.value.delete(no)
    delete roleDetails.value[no]
  } else {
    selectedNos.value.add(no)
  }
  // trigger reactivity
  selectedNos.value = new Set(selectedNos.value)
}

const selectAll = () => {
  students.value.forEach((s) => selectedNos.value.add(s.student_no))
  selectedNos.value = new Set(selectedNos.value)
}

const clearAll = () => {
  selectedNos.value = new Set()
  roleDetails.value = {}
  participantMeta.value = {}
}

// --- Metadata helper ---
const buildMetadata = (entries: MetaEntry[]): Record<string, unknown> => {
  const result: Record<string, unknown> = {}
  for (const e of entries) {
    const key = e.key.trim()
    const value = e.value.trim()
    if (!key) continue
    // แปลงค่าแบบง่าย: ถ้าเป็น array (คั่น ,) ให้แยกเป็น list
    if (key === 'tags' && value.includes(',')) {
      result[key] = value.split(',').map((t) => t.trim()).filter(Boolean)
    } else if (key === 'agenda' && value.includes('|')) {
      result[key] = value.split('|').map((t) => t.trim()).filter(Boolean)
    } else {
      result[key] = value
    }
  }
  return result
}

// ⚠️ ใน template refs ถูก auto-unwrap → ฟังก์ชันรับ array ตรง ๆ (ไม่ใช่ Ref)
const addMetaRow = (entries: MetaEntry[]) => {
  entries.push({ key: '', value: '' })
}
const removeMetaRow = (entries: MetaEntry[], index: number) => {
  entries.splice(index, 1)
}

// ================================================================
// 📊 Smart Participant Table — แก้ค่า Type B ในตารางได้เลย (ไม่ต้องเปิด Modal)
// ================================================================
/** อ่านค่า Type A จากโปรไฟล์นักเรียน (JOIN users ฝั่ง backend ก็ได้ค่าเดียวกัน) */
const profileValue = (student: Student, key: string): unknown => {
  return (student as unknown as Record<string, unknown>)[key]
}

/** อ่าน metadata Type B ของ participant (ลบ key ที่ไม่มีค่า) */
const getParticipantMeta = (no: number): Record<string, unknown> => {
  if (!participantMeta.value[no]) participantMeta.value[no] = {}
  return participantMeta.value[no]
}

const setParticipantField = (no: number, field: string, value: unknown) => {
  const meta = getParticipantMeta(no)
  if (value === '' || value === null || value === undefined) {
    delete meta[field]
  } else {
    meta[field] = value
  }
  // trigger reactivity (เผื่อ key ใหม่ที่ Vue ไม่ track ผ่าน proxy)
  participantMeta.value = { ...participantMeta.value }
}

const getRoleDetail = (no: number): string => roleDetails.value[no] ?? ''

// ================================================================
// 🎯 Batch Action (คลุมดำตั้งค่า) — ตั้งค่า Type B ให้ทุกคนที่ถูกติ๊กพร้อมกัน
// แก้ Local State ก่อน แล้วกด "บันทึกกิจกรรม" ค่อยยิง payload เดียว
// ================================================================
const showBatchModal = ref(false)
const batchValues = ref<Record<string, unknown>>({})

const openBatchModal = () => {
  if (!canManage.value) return
  batchValues.value = {}
  showBatchModal.value = true
}

const applyBatch = () => {
  const values = batchValues.value
  const targets = Array.from(selectedNos.value)
  if (targets.length === 0) {
    Swal.fire('เลือกก่อน', 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คนก่อนตั้งค่าแบบกลุ่ม', 'warning')
    return
  }
  const filled = Object.entries(values).filter(
    ([, v]) => v !== '' && v !== null && v !== undefined,
  )
  if (filled.length === 0) {
    Swal.fire('กรอกค่า', 'กรุณากรอกค่าที่ต้องการตั้งค่าแบบกลุ่ม', 'warning')
    return
  }
  for (const no of targets) {
    for (const [key, val] of filled) {
      setParticipantField(no, key, val)
    }
  }
  showBatchModal.value = false
  Toast.fire({
    icon: 'success',
    title: `ตั้งค่าแบบกลุ่มให้ ${targets.length} คนแล้ว (ยังไม่บันทึก)`,
  })
}

// --- Submit ---
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

  // 🌟 ใส่ required_fields ลง metadata กิจกรรม (Field Selector) — backend export ใช้ค่านี้
  const activityMetadata = buildMetadata(activityMeta.value)
  activityMetadata.required_fields = Array.from(requiredFields.value)

  const participants: ActivityParticipantInput[] = []
  for (const no of selectedNos.value) {
    const student = students.value.find((s) => s.student_no === no)
    if (!student) continue
    // 🚨 Type A (โปรไฟล์) ห้ามส่งลง metadata — backend JOIN มาจาก users ให้เอง
    const meta = getParticipantMeta(no)
    const cleanMeta: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(meta)) {
      if (EVENT_FIELD_KEYS.has(k)) cleanMeta[k] = v
    }
    participants.push({
      student_no: no,
      role_type: 'participant',
      role_detail: getRoleDetail(no).trim() || null,
      earned_hours: form.value.base_hours > 0 ? form.value.base_hours : 0,
      metadata: cleanMeta,
    })
  }

  isSaving.value = true
  try {
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
    router.push('/activities')
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'สร้างกิจกรรมไม่สำเร็จ'
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
          <h3 class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-2.5">
            <div class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0">
              <i class="bi bi-calendar-plus-fill"></i>
            </div>
            สร้างกิจกรรมใหม่
          </h3>
          <p class="text-slate-500 mt-1.5 ml-1 text-sm md:text-base">กรอกข้อมูลหัวกิจกรรม + เลือกฟิลด์ที่ต้องจัดเก็บ + เลือกผู้เข้าร่วม</p>
        </div>
        <router-link to="/activities" class="inline-flex items-center gap-2 text-sm font-bold text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-4 py-2 rounded-xl transition-all">
          <i class="bi bi-arrow-left"></i> กลับรายการ
        </router-link>
      </div>

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังโหลดรายชื่อนักเรียน...</p>
      </div>

      <div v-else class="grid grid-cols-1 lg:grid-cols-5 gap-5 md:gap-6">
        <!-- ========== ส่วนหัวกิจกรรม ========== -->
        <div class="lg:col-span-2 space-y-5">
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-4 flex items-center gap-2">
              <i class="bi bi-card-heading text-violet-500"></i> ข้อมูลกิจกรรม
            </h4>
            <div class="space-y-4">
              <div>
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">ชื่อกิจกรรม *</label>
                <input
                  v-model="form.title"
                  type="text"
                  placeholder="เช่น กีฬาสีประจำปี 2026"
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                />
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">วันที่ *</label>
                  <input
                    v-model="form.activity_date"
                    type="date"
                    class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                  />
                </div>
                <div>
                  <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">ชั่วโมงจิตอาสา</label>
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
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">สถานะ</label>
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
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">รายละเอียด</label>
                <textarea
                  v-model="form.description"
                  rows="3"
                  placeholder="รายละเอียดกิจกรรม กำหนดการคร่าว ๆ..."
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 resize-none"
                ></textarea>
              </div>
            </div>
          </div>

          <!-- 🌟 Metadata กิจกรรม -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div class="flex items-center justify-between mb-4">
              <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-asterisk text-violet-500"></i> Metadata เพิ่มเติม
              </h4>
              <button
                @click="addMetaRow(activityMeta)"
                class="text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 px-3 py-1.5 rounded-lg transition-colors inline-flex items-center gap-1"
              >
                <i class="bi bi-plus-lg"></i> Add Metadata
              </button>
            </div>
            <div class="space-y-3">
              <div
                v-for="(meta, index) in activityMeta"
                :key="index"
                class="flex gap-2 items-center"
              >
                <input
                  v-model="meta.key"
                  list="meta-preset-keys"
                  placeholder="คีย์ (เช่น location_url, tags)"
                  class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
                <datalist id="meta-preset-keys">
                  <option v-for="p in metaPresets" :key="p.key" :value="p.key">{{ p.placeholder }}</option>
                </datalist>
                <input
                  v-model="meta.value"
                  :placeholder="metaPresets.find((p) => p.key === meta.key)?.placeholder || 'ค่า'"
                  class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
                <button
                  v-if="activityMeta.length > 1"
                  @click="removeMetaRow(activityMeta, index)"
                  class="w-8 h-8 flex-shrink-0 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors flex items-center justify-center"
                  title="ลบคีย์"
                >
                  <i class="bi bi-x-lg"></i>
                </button>
              </div>
              <p class="text-[11px] text-slate-400 mt-2 leading-relaxed">
                💡 ใช้ <code class="bg-slate-100 px-1 rounded">tags</code> คั่นด้วย , เพื่อทำ Badge หมวดหมู่ · <code class="bg-slate-100 px-1 rounded">location_url</code> สำหรับลิ้งก์ Google Maps
              </p>
            </div>
          </div>
        </div>

        <!-- ========== Field Selector + Smart Participant Table ========== -->
        <div class="lg:col-span-3 space-y-5">
          <!-- 🌟 Field Selector (Required Data) -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-2">
              <div>
                <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                  <i class="bi bi-list-check text-violet-500"></i> ข้อมูลที่ต้องการจัดเก็บสำหรับกิจกรรมนี้ (Required Data)
                </h4>
                <p class="text-xs text-slate-400 mt-0.5">
                  ติ๊กเลือกฟิลด์ → ตารางผู้เข้าร่วมจะแสดงเฉพาะคอลัมน์เหล่านี้ · 🔒 = ดึงจากโปรไฟล์อัตโนมัติ
                </p>
              </div>
              <span class="text-xs font-bold text-violet-600 bg-violet-50 px-3 py-1.5 rounded-lg whitespace-nowrap">
                เลือกแล้ว {{ requiredFields.size }}/{{ ALL_ACTIVITY_FIELDS.length }} ฟิลด์
              </span>
            </div>

            <div v-for="cat in ACTIVITY_FIELD_CATEGORY_ORDER" :key="cat" class="mb-4 last:mb-0">
              <h5 class="text-xs font-black text-slate-400 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                <i class="bi" :class="cat === 'profile' ? 'bi-lock-fill' : 'bi-chevron-right'"></i>
                {{ ACTIVITY_FIELD_CATEGORY_LABELS[cat] }}
              </h5>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <label
                  v-for="field in ALL_ACTIVITY_FIELDS.filter((f) => f.category === cat)"
                  :key="field.key"
                  class="flex items-start gap-2.5 px-3 py-2.5 rounded-xl border cursor-pointer transition-all select-none"
                  :class="requiredFields.has(field.key)
                    ? 'bg-violet-50 border-violet-300 shadow-sm'
                    : 'bg-slate-50 border-slate-200 hover:border-violet-200 hover:bg-white'"
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
                      <span v-if="cat === 'profile'" class="text-[10px] text-violet-500" title="ระบบจะดึงจากโปรไฟล์ให้อัตโนมัติ ไม่ต้องให้คนกรอกใหม่">🔒</span>
                    </span>
                    <span class="block text-[10px] text-slate-400 mt-0.5">{{ field.hint || field.placeholder || '' }}</span>
                  </span>
                </label>
              </div>
            </div>
          </div>

          <!-- ========== Smart Participant Table ========== -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-3">
              <div>
                <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                  <i class="bi bi-people-fill text-violet-500"></i> เลือกผู้เข้าร่วม
                </h4>
                <p class="text-xs text-slate-400 mt-0.5">
                  ติ๊กชื่อ → แก้ค่าฟิลด์ Type B ในตารางได้เลย · คอลัมน์ Type A เป็นค่าจากโปรไฟล์ (อ่านอย่างเดียว)
                </p>
              </div>
              <div class="flex flex-wrap gap-2">
                <button
                  v-if="selectedCount > 0"
                  @click="openBatchModal"
                  class="px-4 py-2 text-xs font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-1.5"
                >
                  <i class="bi bi-lightning-charge-fill"></i> ตั้งค่าแบบกลุ่ม (Batch Apply)
                </button>
                <button @click="selectAll" class="text-xs font-bold text-slate-500 hover:text-violet-600 bg-slate-50 hover:bg-violet-50 px-3 py-2 rounded-lg transition-colors inline-flex items-center gap-1">
                  <i class="bi bi-check-all"></i> เลือกทั้งหมด
                </button>
                <button @click="clearAll" class="text-xs font-bold text-slate-500 hover:text-rose-600 bg-slate-50 hover:bg-rose-50 px-3 py-2 rounded-lg transition-colors inline-flex items-center gap-1">
                  <i class="bi bi-x-lg"></i> ล้าง
                </button>
              </div>
            </div>

            <div class="flex items-center gap-2 text-xs font-bold text-violet-600 bg-violet-50 border border-violet-100 rounded-xl px-3 py-2 mb-4">
              <i class="bi bi-person-check-fill"></i> เลือกแล้ว {{ selectedCount }} คน
            </div>

            <!-- ตาราง Smart (dynamic columns) -->
            <div v-if="students.length === 0" class="text-center py-10 text-slate-400 text-sm">
              ยังไม่มีนักเรียนในห้องนี้
            </div>
            <div v-else class="overflow-x-auto overflow-y-hidden rounded-xl border border-slate-100">
              <table class="w-full min-w-[700px] text-left">
                <thead>
                  <tr class="border-b border-slate-100 bg-slate-50/60 text-[10px] font-black text-slate-400 uppercase tracking-wider">
                    <th class="py-2.5 px-2 w-10 text-center">✓</th>
                    <th class="py-2.5 px-2">เลขที่</th>
                    <th class="py-2.5 px-2">ชื่อ</th>
                    <th class="py-2.5 px-2 min-w-[140px]">หน้าที่</th>
                    <th
                      v-for="field in typeBColumns"
                      :key="field.key"
                      class="py-2.5 px-2 min-w-[130px]"
                    >
                      {{ field.label }}
                    </th>
                    <th
                      v-for="field in typeAColumns"
                      :key="field.key"
                      class="py-2.5 px-2 min-w-[120px]"
                    >
                      {{ field.label }} <span class="text-violet-400">🔒</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="student in students"
                    :key="student.student_no"
                    class="border-b border-slate-50 last:border-0 hover:bg-slate-50/60 transition-colors align-middle"
                    :class="{ 'bg-violet-50/50': selectedNos.has(student.student_no) }"
                  >
                    <td class="py-2.5 px-2 text-center">
                      <input
                        type="checkbox"
                        :checked="selectedNos.has(student.student_no)"
                        @change="toggleSelect(student)"
                        class="w-4 h-4 rounded accent-violet-600"
                      />
                    </td>
                    <td class="py-2.5 px-2 text-sm font-bold text-slate-500 whitespace-nowrap">{{ student.student_no }}</td>
                    <td class="py-2.5 px-2 whitespace-nowrap">
                      <p class="text-sm font-bold text-slate-700">{{ student.prefix || '' }}{{ student.first_name }} {{ student.last_name }}</p>
                      <p class="text-[10px] text-slate-400">{{ student.nickname || '—' }}</p>
                    </td>
                    <td class="py-2.5 px-2">
                      <input
                        v-model="roleDetails[student.student_no]"
                        type="text"
                        placeholder="หน้าที่ เช่น ถือป้าย"
                        :disabled="!selectedNos.has(student.student_no)"
                        class="w-full px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
                      />
                    </td>
                    <!-- คอลัมน์ Type B — แก้ในตารางได้เลย -->
                    <td v-for="field in typeBColumns" :key="field.key" class="py-2.5 px-2">
                      <ActivityFieldControl
                        :field="field"
                        :model-value="getParticipantMeta(student.student_no)[field.key]"
                        :disabled="!selectedNos.has(student.student_no)"
                        @update:model-value="(v: unknown) => setParticipantField(student.student_no, field.key, v)"
                      />
                    </td>
                    <!-- คอลัมน์ Type A — อ่านจากโปรไฟล์ (🔒) -->
                    <td v-for="field in typeAColumns" :key="field.key" class="py-2.5 px-2">
                      <span class="text-xs font-semibold text-slate-600">{{ String(profileValue(student, field.key) ?? '—') }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <p v-if="typeBColumns.length === 0" class="text-[11px] text-slate-400 mt-3">
              💡 ยังไม่ได้เลือกฟิลด์ Type B → ติ๊กในส่วน "Required Data" ด้านบน แล้วจะเห็นคอลัมน์ให้กรอก (เช่น หมายเลขรถบัส, ห้องพัก)
            </p>
          </div>

          <!-- ปุ่มบันทึก -->
          <div class="mt-5 flex flex-col sm:flex-row justify-end gap-3">
            <router-link to="/activities" class="w-full sm:w-auto px-6 py-3 text-slate-500 hover:text-slate-800 hover:bg-slate-100 font-bold rounded-xl transition-all text-center">
              ยกเลิก
            </router-link>
            <button
              @click="submit"
              :disabled="isSaving"
              class="w-full sm:w-auto px-8 py-3 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white font-bold rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center justify-center gap-2"
            >
              <i v-if="isSaving" class="bi bi-arrow-repeat animate-spin"></i>
              <i v-else class="bi bi-check-lg"></i>
              {{ isSaving ? 'กำลังบันทึก...' : 'บันทึกกิจกรรม' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 🎯 Modal: Batch Apply (ตั้งค่าแบบกลุ่ม) -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showBatchModal" class="fixed inset-0 z-[70] bg-slate-900/40 backdrop-blur-sm flex items-end md:items-center justify-center p-0 md:p-4" @click.self="showBatchModal = false">
          <div class="w-full md:max-w-lg bg-white rounded-t-3xl md:rounded-3xl shadow-2xl p-5 md:p-6 max-h-[90dvh] overflow-y-auto overflow-x-hidden">
            <div class="flex items-center justify-between mb-1">
              <h4 class="text-base font-bold text-slate-800 flex items-center gap-2">
                <i class="bi bi-lightning-charge-fill text-fuchsia-500"></i>
                ตั้งค่าแบบกลุ่ม
              </h4>
              <button @click="showBatchModal = false" class="w-9 h-9 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 flex items-center justify-center">
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
            <p class="text-xs text-slate-400 mb-5">
              ตั้งค่าฟิลด์ Type B ที่เลือกไว้ใน Required Data ให้ผู้เข้าร่วม <b class="text-fuchsia-600">{{ selectedCount }} คน</b> พร้อมกัน · ยังไม่บันทึกจนกว่าจะกด "บันทึกกิจกรรม"
            </p>

            <div v-if="batchSettableFields.length === 0" class="text-sm text-slate-500 bg-slate-50 rounded-xl p-4 text-center">
              ยังไม่เลือกฟิลด์ Type B ในส่วน Required Data → ติ๊กก่อน แล้วกลับมาตั้งค่าแบบกลุ่ม
            </div>

            <div v-else class="space-y-4">
              <div v-for="field in batchSettableFields" :key="field.key">
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block flex items-center gap-1.5">
                  <i class="bi" :class="field.type === 'boolean' ? 'bi-check-circle' : 'bi-pencil'"></i>
                  {{ field.label }}
                </label>
                <ActivityFieldControl
                  :field="field"
                  :model-value="batchValues[field.key]"
                  @update:model-value="(v: unknown) => { batchValues[field.key] = v }"
                />
              </div>
            </div>

            <div class="flex justify-end gap-3 mt-6">
              <button
                @click="showBatchModal = false"
                class="px-5 py-2.5 text-sm font-bold text-slate-500 hover:bg-slate-100 rounded-xl transition-colors"
              >
                ยกเลิก
              </button>
              <button
                @click="applyBatch"
                :disabled="batchSettableFields.length === 0"
                class="px-6 py-2.5 text-sm font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 disabled:opacity-50 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-1.5"
              >
                <i class="bi bi-lightning-charge-fill"></i> ใช้ค่ากับ {{ selectedCount }} คน
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
