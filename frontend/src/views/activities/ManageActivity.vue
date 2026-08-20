<script setup lang="ts">
/**
 * 🛠️ ManageActivity — "หน้า Checkbox ของกลุ่ม" (จัดการผู้เข้าร่วม)
 * - ☑️ Roster แบบเลือกได้ (ตั้งค่าแบบกลุ่มเฉพาะคนที่ติ๊ก)
 * - 📋 เช็คชื่อแยกแผ่นตามเหตุการณ์ (เพิ่มการเช็คชื่อ / เช็คคน / เช็คทั้งหมด)
 * - ➕ เพิ่มนักเรียน (ลิสต์คนที่ยังไม่ได้เข้าร่วม)
 * - 🧩 Dynamic Fields (สร้างฟิลด์ใหม่ที่ปรากฏกับทุกคน)
 * หน้าใหม่ /activities/:id/manage — ActivityDetail คงเป็นหน้าดูเฉยๆ
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import type {
  Activity,
  RosterItem,
  CheckinSheet,
  CheckinSheetDetail,
  AvailableStudent,
  BatchParticipantItem,
  DynamicFieldDef,
} from '@/types/activity'
import {
  ALL_ACTIVITY_FIELDS,
  PROFILE_FIELD_KEYS,
  EVENT_FIELD_KEYS,
  getDynamicFields,
  dynamicDefsToFields,
  type ActivityField,
  type CustomFieldEntry,
} from '@/constants/activityFields'
import ParticipantRosterList from '@/components/activities/ParticipantRosterList.vue'
import ParticipantInfoModal from '@/components/activities/ParticipantInfoModal.vue'
import BatchApplyModal from '@/components/activities/BatchApplyModal.vue'
import AddStudentsModal from '@/components/activities/AddStudentsModal.vue'
import CheckinSheetSection from '@/components/activities/CheckinSheetSection.vue'
import DynamicFieldManager from '@/components/activities/DynamicFieldManager.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const activityId = Number(route.params.id)

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
// 📦 ข้อมูลกิจกรรม
// ================================================================
const activity = ref<Activity | null>(null)
const isLoading = ref(true)

const requiredFields = computed<string[]>(() => {
  const raw = activity.value?.metadata?.required_fields
  if (Array.isArray(raw)) return raw.map(String)
  return []
})
const typeAColumns = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter((f) => PROFILE_FIELD_KEYS.has(f.key) && requiredFields.value.includes(f.key)),
)
const typeBColumns = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter((f) => EVENT_FIELD_KEYS.has(f.key) && requiredFields.value.includes(f.key)),
)
const positions = computed<string[]>(() => {
  const raw = activity.value?.metadata?.positions
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean)
  return []
})
/** 🧩 Dynamic Fields defs → ActivityField[] สำหรับ batch/modal */
const dynamicFields = computed<ActivityField[]>(() =>
  dynamicDefsToFields(getDynamicFields(activity.value?.metadata)),
)
const dynamicFieldDefs = computed<DynamicFieldDef[]>(() =>
  getDynamicFields(activity.value?.metadata),
)

const fetchData = async () => {
  isLoading.value = true
  try {
    activity.value = await ActivityService.getActivity(currentRoomId, activityId)
    await loadSheets()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'ไม่พบกิจกรรม'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
    router.push('/activities')
  } finally {
    isLoading.value = false
  }
}

// ================================================================
// ☑️ Roster + selection
// ================================================================
const selectedKeys = ref<Set<number>>(new Set())

const rosterItems = computed<RosterItem[]>(() =>
  (activity.value?.participants ?? []).map((p) => ({
    key: p.id,
    student_no: p.student_no,
    first_name: p.first_name,
    last_name: p.last_name,
    nickname: p.nickname,
    first_name_en: p.first_name_en,
    last_name_en: p.last_name_en,
    nickname_en: p.nickname_en,
    role_type: typeof p.role_type === 'string' ? p.role_type : 'participant',
    role_detail: p.role_detail,
    status: typeof p.status === 'string' ? p.status : 'confirmed',
    earned_hours: Number(p.earned_hours) || 0,
    metadata: { ...p.metadata },
    profile: {
      blood_group: p.blood_group,
      shirt_size: p.shirt_size,
      food_allergy: p.food_allergy,
      congenital_disease: p.congenital_disease,
      phone_number: p.phone_number,
      phone_number_parent: p.phone_number_parent,
    },
  })),
)

const selectedCount = computed(() => selectedKeys.value.size)

function toggleSelect(key: string | number) {
  const no = Number(key)
  const next = new Set(selectedKeys.value)
  if (next.has(no)) next.delete(no)
  else next.add(no)
  selectedKeys.value = next
}

function selectAll() {
  selectedKeys.value = new Set((activity.value?.participants ?? []).map((p) => p.id))
}

function clearAll() {
  selectedKeys.value = new Set()
}

// ================================================================
// 📋 Modal ข้อมูลเพิ่มเติม (ต่อคน) — บันทึกจริงผ่าน API
// ================================================================
const infoModalOpen = ref(false)
const infoModalKey = ref<number | null>(null)

const infoItem = computed<RosterItem | null>(() => {
  if (infoModalKey.value === null) return null
  return rosterItems.value.find((r) => r.key === infoModalKey.value) ?? null
})

function openInfoModal(key: string | number) {
  infoModalKey.value = Number(key)
  infoModalOpen.value = true
}

function closeInfoModal() {
  infoModalOpen.value = false
  infoModalKey.value = null
}

async function saveInfoModal(payload: {
  role_detail: string | null
  metadata: Record<string, unknown>
  customFields: CustomFieldEntry[]
}) {
  const key = infoModalKey.value
  if (key === null) return
  try {
    await ActivityService.updateParticipant(currentRoomId, activityId, key, {
      role_detail: payload.role_detail,
      metadata: payload.metadata,
      user_name: currentUserName,
    })
    closeInfoModal()
    Toast.fire({ icon: 'success', title: 'บันทึกข้อมูลนักเรียนแล้ว' })
    await fetchData()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'บันทึกไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// ================================================================
// ⚡ ตั้งค่าแบบกลุ่ม (เฉพาะคนที่ติ๊ก) — เรียก API จริง
// ================================================================
const batchModalOpen = ref(false)

function openBatch() {
  if (selectedCount.value === 0) {
    Swal.fire('เลือกก่อน', 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คนก่อนตั้งค่าแบบกลุ่ม', 'warning')
    return
  }
  batchModalOpen.value = true
}

async function applyBatch(payload: {
  dutyPosition: string
  typeB: Record<string, unknown>
  roleType: string
  status: string
  earnedHours: string
}) {
  const items: BatchParticipantItem[] = Array.from(selectedKeys.value).map((key) => {
    const item: BatchParticipantItem = {
      participant_id: Number(key),
      metadata: payload.typeB,
    }
    if (payload.dutyPosition) item.role_detail = payload.dutyPosition
    if (payload.roleType) item.role_type = payload.roleType
    if (payload.status) item.status = payload.status
    if (payload.earnedHours !== '' && payload.earnedHours !== null) {
      item.earned_hours = Number(payload.earnedHours)
    }
    return item
  })
  try {
    await ActivityService.batchUpdateParticipants(currentRoomId, activityId, {
      items,
      user_name: currentUserName,
    })
    batchModalOpen.value = false
    Toast.fire({
      icon: 'success',
      title: `ตั้งค่าแบบกลุ่มให้ ${items.length} คนแล้ว (คนที่ไม่ได้ติ๊กไม่ถูกแตะ)`,
    })
    await fetchData()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'ตั้งค่าแบบกลุ่มไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// ================================================================
// ➕ เพิ่มนักเรียน (คนที่ยังไม่ได้เข้าร่วม)
// ================================================================
const addStudentsOpen = ref(false)
const availableStudents = ref<AvailableStudent[]>([])
const availableLoading = ref(false)

async function openAddStudents() {
  addStudentsOpen.value = true
  availableLoading.value = true
  try {
    availableStudents.value = await ActivityService.getAvailableStudents(currentRoomId, activityId)
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'โหลดรายชื่อนักเรียนไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  } finally {
    availableLoading.value = false
  }
}

async function handleAddStudents(studentNos: number[]) {
  try {
    await ActivityService.batchAddParticipants(
      currentRoomId,
      activityId,
      studentNos.map((no) => ({ student_no: no })),
      currentUserName,
    )
    addStudentsOpen.value = false
    Toast.fire({ icon: 'success', title: `เพิ่มผู้เข้าร่วม ${studentNos.length} คนแล้ว` })
    await fetchData() // reload activity + sheets (ผู้เข้าร่วมใหม่ปรากฏในแผ่นเช็คชื่อด้วย)
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'เพิ่มนักเรียนไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// ================================================================
// ✅ เช็คชื่อแยกแผ่น (Multiple Attendance Sheets)
// ================================================================
const sheets = ref<CheckinSheet[]>([])
const showAddSheet = ref(false)
const newSheetTitle = ref('')
const newSheetDate = ref('')

const expandedSheetId = ref<number | null>(null)
const sheetDetails = ref<Record<number, CheckinSheetDetail>>({})
const sheetLoadingId = ref<number | null>(null)

async function loadSheets() {
  sheets.value = await ActivityService.getCheckinSheets(currentRoomId, activityId)
}

async function addSheet() {
  const title = newSheetTitle.value.trim()
  if (!title) {
    Swal.fire('กรอกชื่อก่อน', 'ต้องระบุชื่อแผ่นเช็คชื่อ เช่น "เช็คขึ้นรถ"', 'warning')
    return
  }
  try {
    await ActivityService.createCheckinSheet(currentRoomId, activityId, {
      title,
      event_date: newSheetDate.value || null,
      user_name: currentUserName,
    })
    showAddSheet.value = false
    newSheetTitle.value = ''
    newSheetDate.value = ''
    Toast.fire({ icon: 'success', title: `สร้างแผ่น "${title}" แล้ว` })
    await loadSheets()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'สร้างแผ่นเช็คชื่อไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

async function deleteSheet(sheet: CheckinSheet) {
  const result = await Swal.fire({
    title: 'ลบแผ่นเช็คชื่อนี้ไหม?',
    text: `"${sheet.title}" และประวัติการเช็คทั้งหมดจะถูกลบ`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#e11d48',
    confirmButtonText: 'ลบแผ่น',
    cancelButtonText: 'ยกเลิก',
  })
  if (!result.isConfirmed) return
  try {
    await ActivityService.deleteCheckinSheet(currentRoomId, activityId, sheet.id, currentUserName)
    if (expandedSheetId.value === sheet.id) {
      expandedSheetId.value = null
      delete sheetDetails.value[sheet.id]
    }
    Toast.fire({ icon: 'success', title: 'ลบแผ่นเช็คชื่อแล้ว' })
    await loadSheets()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'ลบแผ่นเช็คชื่อไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

async function toggleExpandSheet(sheetId: number) {
  if (expandedSheetId.value === sheetId) {
    expandedSheetId.value = null
    return
  }
  expandedSheetId.value = sheetId
  if (sheetDetails.value[sheetId]) return
  sheetLoadingId.value = sheetId
  try {
    sheetDetails.value[sheetId] = await ActivityService.getCheckinSheet(currentRoomId, activityId, sheetId)
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'โหลดแผ่นเช็คชื่อไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  } finally {
    sheetLoadingId.value = null
  }
}

async function togglePresent(sheetId: number, participantId: number, next: boolean) {
  try {
    await ActivityService.upsertCheckinRecord(
      currentRoomId, activityId, sheetId, participantId, next, currentUserName,
    )
    const detail = sheetDetails.value[sheetId]
    if (detail) {
      const p = detail.participants.find((x) => x.id === participantId)
      if (p) {
        p.is_present = next
        p.checked_at = next ? new Date().toISOString() : p.checked_at
      }
    }
    await loadSheets()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'เช็คชื่อไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

async function markAllPresent(sheetId: number) {
  const detail = sheetDetails.value[sheetId]
  if (!detail) return
  const targets = detail.participants
    .filter((p) => !p.is_present)
    .map((p) => ({ participant_id: p.id, is_present: true }))
  if (targets.length === 0) return
  try {
    await ActivityService.batchUpdateCheckinRecords(
      currentRoomId, activityId, sheetId, targets, currentUserName,
    )
    Toast.fire({ icon: 'success', title: `เช็คทั้งหมดแล้ว ${targets.length} คน` })
    for (const p of detail.participants) {
      if (!p.is_present) {
        p.is_present = true
        p.checked_at = new Date().toISOString()
      }
    }
    await loadSheets()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'เช็คทั้งหมดไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// ================================================================
// 🧩 Dynamic Fields — สร้าง/ลบฟิลด์เพิ่มเติม (ปรากฏกับทุกคน)
// ================================================================
async function updateDynamicFields(defs: DynamicFieldDef[]) {
  try {
    await ActivityService.updateActivity(currentRoomId, activityId, {
      metadata: { dynamic_fields: defs },
      user_name: currentUserName,
    })
    Toast.fire({ icon: 'success', title: 'อัปเดตฟิลด์เพิ่มเติมแล้ว' })
    await fetchData()
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'อัปเดตฟิลด์ไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

onMounted(() => {
  if (!canManage.value) {
    router.replace(`/activities/${activityId}`)
    return
  }
  fetchData()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-7xl mx-auto">
      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังโหลดข้อมูลกิจกรรม...</p>
      </div>

      <div v-else-if="activity" class="space-y-5">
        <!-- Header -->
        <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
          <div>
            <router-link
              :to="`/activities/${activityId}`"
              class="inline-flex items-center gap-1.5 text-sm font-bold text-slate-400 hover:text-slate-700 mb-2 transition-colors"
            >
              <i class="bi bi-arrow-left"></i> กลับหน้ารายละเอียด
            </router-link>
            <h3
              class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-3 flex-wrap"
            >
              <div
                class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0"
              >
                <i class="bi bi-sliders"></i>
              </div>
              จัดการผู้เข้าร่วม — {{ activity.title }}
            </h3>
            <p class="text-slate-500 mt-1.5 ml-1 text-sm md:text-base">
              ติ๊กชื่อเพื่อตั้งค่าแบบกลุ่ม · เพิ่มนักเรียน · เช็คชื่อตามเหตุการณ์ · สร้างฟิลด์เพิ่มเติม
            </p>
          </div>
          <div class="flex gap-2">
            <router-link
              :to="`/activities/${activityId}`"
              class="px-4 py-2.5 text-sm font-bold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 rounded-xl transition-all inline-flex items-center justify-center gap-2"
            >
              <i class="bi bi-eye"></i> ดูรายละเอียด
            </router-link>
            <router-link
              :to="`/activities/${activityId}/edit`"
              class="px-4 py-2.5 text-sm font-bold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center justify-center gap-2"
            >
              <i class="bi bi-pencil-square"></i> แก้ไขกิจกรรม
            </router-link>
          </div>
        </div>

        <!-- ========== ☑️ ผู้เข้าร่วม (เลือกเพื่อตั้งค่าแบบกลุ่ม) ========== -->
        <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
          <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
            <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-people-fill text-violet-500"></i> ผู้เข้าร่วม ({{
                activity.participants.length
              }})
            </h4>
            <div class="flex flex-wrap items-center gap-2">
              <button
                @click="openAddStudents"
                class="px-3.5 py-2 text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 border border-violet-200 rounded-xl transition-all inline-flex items-center gap-1.5"
              >
                <i class="bi bi-person-plus-fill"></i> เพิ่มนักเรียน
              </button>
              <button
                v-if="selectedCount > 0"
                @click="openBatch"
                class="px-3.5 py-2 text-xs font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-1.5"
              >
                <i class="bi bi-lightning-charge-fill"></i> ตั้งค่าแบบกลุ่ม ({{
                  selectedCount
                }})
              </button>
            </div>
          </div>

          <div
            v-if="selectedCount > 0"
            class="flex items-center gap-2 text-xs font-bold text-fuchsia-700 bg-fuchsia-50 border border-fuchsia-100 rounded-xl px-3 py-2 mb-3"
          >
            <i class="bi bi-check2-square"></i>
            เลือกแล้ว {{ selectedCount }} คน — ตั้งค่าแบบกลุ่มจะแก้เฉพาะคนที่ติ๊กเท่านั้น
          </div>

          <div
            v-if="activity.participants.length === 0"
            class="text-center py-10 text-slate-400 text-sm"
          >
            ยังไม่มีผู้เข้าร่วม — กด "เพิ่มนักเรียน" เพื่อเพิ่มคนแรก
          </div>
          <ParticipantRosterList
            v-else
            :items="rosterItems"
            :positions="positions"
            :selected-keys="selectedKeys"
            selectable
            hide-duty-editor
            :can-manage="canManage"
            :empty-text="'ไม่มีรายชื่อในรายการนี้'"
            @toggle-select="toggleSelect"
            @select-all="selectAll"
            @clear-all="clearAll"
            @open-info="openInfoModal"
            @batch="openBatch"
          />
        </div>

        <!-- ========== ✅ เช็คชื่อแยกแผ่น ========== -->
        <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
          <div class="flex flex-wrap items-center justify-between gap-2 mb-1">
            <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-clipboard2-check text-emerald-500"></i> เช็คชื่อตามเหตุการณ์
            </h4>
            <button
              v-if="!showAddSheet"
              @click="showAddSheet = true"
              class="px-3.5 py-2 text-xs font-bold text-emerald-600 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-xl transition-all inline-flex items-center gap-1.5"
            >
              <i class="bi bi-plus-lg"></i> เพิ่มการเช็คชื่อ
            </button>
          </div>
          <p class="text-xs text-slate-400 mb-4">
            สร้างแผ่นเช็คชื่อแยกตามเหตุการณ์ เช่น เช็คขึ้นรถ, เช็คเข้าฐาน — กดแผ่นเพื่อเช็คชื่อคน
          </p>

          <!-- inline form สร้างแผ่น -->
          <div
            v-if="showAddSheet"
            class="bg-emerald-50/50 border border-emerald-100 rounded-2xl p-4 mb-4 space-y-3"
          >
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label
                  class="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1 block"
                  >ชื่อแผ่นเช็คชื่อ *</label
                >
                <input
                  v-model="newSheetTitle"
                  type="text"
                  placeholder="เช่น เช็คขึ้นรถ, เช็คเข้าฐาน"
                  @keyup.enter="addSheet"
                  class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-400"
                />
              </div>
              <div>
                <label
                  class="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1 block"
                  >วันที่ (ไม่บังคับ)</label
                >
                <input
                  v-model="newSheetDate"
                  type="date"
                  class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-400"
                />
              </div>
            </div>
            <div class="flex justify-end gap-2">
              <button
                @click="showAddSheet = false"
                class="px-3 py-2 text-xs font-bold text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
              >
                ยกเลิก
              </button>
              <button
                @click="addSheet"
                class="px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-sm transition-all inline-flex items-center gap-1"
              >
                <i class="bi bi-check-lg"></i> สร้างแผ่นเช็คชื่อ
              </button>
            </div>
          </div>

          <!-- รายการแผ่น -->
          <div v-if="sheets.length === 0" class="text-center py-6 text-sm text-slate-400 bg-slate-50 rounded-2xl border border-dashed border-slate-200">
            ยังไม่มีแผ่นเช็คชื่อ — กด "เพิ่มการเช็คชื่อ" เพื่อสร้าง (เช่น เช็คขึ้นรถ)
          </div>
          <div v-else class="space-y-2.5">
            <CheckinSheetSection
              v-for="sheet in sheets"
              :key="sheet.id"
              :sheet="sheet"
              :participants="sheetDetails[sheet.id]?.participants ?? null"
              :loading="sheetLoadingId === sheet.id"
              :expanded="expandedSheetId === sheet.id"
              :can-manage="canManage"
              @toggle-expand="toggleExpandSheet(sheet.id)"
              @toggle-present="(pid, next) => togglePresent(sheet.id, pid, next)"
              @delete-sheet="deleteSheet(sheet)"
              @mark-all-present="markAllPresent(sheet.id)"
            />
          </div>
        </div>

        <!-- ========== 🧩 ฟิลด์เพิ่มเติม (Dynamic Fields) ========== -->
        <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
          <h4 class="text-base font-bold text-slate-700 mb-1 flex items-center gap-2">
            <i class="bi bi-puzzle text-violet-500"></i> ฟิลด์เพิ่มเติม
          </h4>
          <p class="text-xs text-slate-400 mb-4">
            สร้างฟิลด์ข้อมูลที่ต้องการเก็บเพิ่มเติม (เช่น หมายเลขกลุ่ม, รถคันที่ลง) — ฟิลด์ใหม่จะ
            ปรากฏกับผู้เข้าร่วมทุกคน และตั้งค่าแบบกลุ่มได้
          </p>
          <DynamicFieldManager
            :defs="dynamicFieldDefs"
            @update="updateDynamicFields"
          />
        </div>
      </div>
    </div>

    <!-- 📋 Modal: ข้อมูลเพิ่มเติมของนักเรียน (ต่อคน) -->
    <ParticipantInfoModal
      :open="infoModalOpen && !!infoItem"
      :item="infoItem"
      :type-a-fields="typeAColumns"
      :type-b-fields="typeBColumns"
      :dynamic-fields="dynamicFields"
      :positions="positions"
      :can-manage="canManage"
      @close="closeInfoModal"
      @save="saveInfoModal"
    />

    <!-- ⚡ Modal: ตั้งค่าแบบกลุ่ม -->
    <BatchApplyModal
      :open="batchModalOpen"
      :positions="positions"
      :type-b-fields="typeBColumns"
      :dynamic-fields="dynamicFields"
      show-role-type
      show-status
      show-earned-hours
      :count="selectedCount"
      @close="batchModalOpen = false"
      @apply="applyBatch"
    />

    <!-- ➕ Modal: เพิ่มนักเรียน -->
    <AddStudentsModal
      :open="addStudentsOpen"
      :students="availableStudents"
      :loading="availableLoading"
      @close="addStudentsOpen = false"
      @add="handleAddStudents"
    />
  </div>
</template>
