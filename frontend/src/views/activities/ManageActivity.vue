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
import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
  }
}

// ================================================================
// ⚡ ตั้งค่าแบบกลุ่ม (เฉพาะคนที่ติ๊ก) — เรียก API จริง
// ================================================================
const batchModalOpen = ref(false)

function openBatch() {
  if (selectedCount.value === 0) {
    Swal.fire({
      icon: 'warning',
      title: 'เลือกก่อน',
      text: 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คนก่อนตั้งค่าแบบกลุ่ม',
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'warning',
      title: 'กรอกชื่อก่อน',
      text: 'ต้องระบุชื่อแผ่นเช็คชื่อ เช่น "เช็คขึ้นรถ"',
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
  }
}

async function deleteSheet(sheet: CheckinSheet) {
  const result = await Swal.fire({
    title: 'ลบแผ่นเช็คชื่อนี้ไหม?',
    text: `"${sheet.title}" และประวัติการเช็คทั้งหมดจะถูกลบ`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
  <div class="space-y-4 sm:space-y-5">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <template v-else-if="activity">
      <!-- Header -->
      <div>
        <PageHeader
          eyebrow="Activity Management"
          title="จัดการผู้เข้าร่วม"
          :description="activity.title"
        >
          <template #actions>
            <router-link :to="`/activities/${activityId}`" class="btn-ghost-ui w-full sm:w-auto">
              <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับหน้ารายละเอียด
            </router-link>
            <router-link
              :to="`/activities/${activityId}/edit`"
              class="btn-primary w-full sm:w-auto"
            >
              <i class="bi bi-pencil-square" aria-hidden="true"></i> แก้ไขกิจกรรม
            </router-link>
          </template>
        </PageHeader>
      </div>

      <!-- ========== ☑️ ผู้เข้าร่วม (เลือกเพื่อตั้งค่าแบบกลุ่ม) ========== -->
      <div class="page-card p-4 sm:p-5">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="section-title flex min-w-0 items-center gap-2">
            <i class="bi bi-people-fill text-brand-700" aria-hidden="true"></i>
            <span class="truncate">ผู้เข้าร่วม ({{ activity.participants.length }})</span>
          </h2>
          <button
            v-if="activity.participants.length > 0"
            type="button"
            class="btn-ghost-ui"
            @click="openAddStudents"
          >
            <i class="bi bi-person-plus-fill" aria-hidden="true"></i> เพิ่มนักเรียน
          </button>
        </div>

        <div
          v-if="selectedCount > 0"
          class="mb-3 flex items-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 text-xs font-bold text-brand-700"
        >
          <i class="bi bi-check2-square" aria-hidden="true"></i>
          เลือกแล้ว {{ selectedCount }} คน
        </div>

        <StateBlock
          v-if="activity.participants.length === 0"
          variant="empty"
          icon="bi-people"
          title="ยังไม่มีผู้เข้าร่วม"
          hint="กดปุ่มด้านล่างเพื่อเพิ่มนักเรียนคนแรกเข้ากิจกรรมนี้"
        >
          <button type="button" class="btn-primary mt-1.5" @click="openAddStudents">
            <i class="bi bi-person-plus-fill" aria-hidden="true"></i> เพิ่มนักเรียน
          </button>
        </StateBlock>
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
      <div class="page-card p-4 sm:p-5">
        <div class="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h2 class="section-title flex min-w-0 items-center gap-2">
            <i class="bi bi-clipboard2-check text-emerald-600" aria-hidden="true"></i>
            <span class="truncate">เช็คชื่อตามเหตุการณ์</span>
          </h2>
          <button
            v-if="!showAddSheet"
            type="button"
            class="btn-ghost-ui"
            @click="showAddSheet = true"
          >
            <i class="bi bi-plus-lg" aria-hidden="true"></i> เพิ่มการเช็คชื่อ
          </button>
        </div>
        <p class="mb-3 text-xs text-stone-400 sm:mb-4">
          สร้างแผ่นเช็คชื่อแยกตามเหตุการณ์ เช่น เช็คขึ้นรถ, เช็คเข้าฐาน — กดแผ่นเพื่อเช็คชื่อคน
        </p>

        <!-- inline form สร้างแผ่น -->
        <div
          v-if="showAddSheet"
          class="mb-3 space-y-3 rounded-2xl border border-stone-200 bg-stone-50/60 p-3.5 sm:mb-4 sm:p-4"
        >
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="field-label" for="newSheetTitle">ชื่อแผ่นเช็คชื่อ *</label>
              <input
                id="newSheetTitle"
                v-model="newSheetTitle"
                type="text"
                placeholder="เช่น เช็คขึ้นรถ, เช็คเข้าฐาน"
                @keyup.enter="addSheet"
                class="field"
              />
            </div>
            <div>
              <label class="field-label" for="newSheetDate">วันที่ (ไม่บังคับ)</label>
              <input id="newSheetDate" v-model="newSheetDate" type="date" class="field" />
            </div>
          </div>
          <div class="flex flex-col-reverse gap-2 border-t border-stone-100 pt-3 sm:flex-row sm:justify-end">
            <button type="button" class="btn-ghost-ui" @click="showAddSheet = false">ยกเลิก</button>
            <button type="button" class="btn-primary" @click="addSheet">
              <i class="bi bi-check-lg" aria-hidden="true"></i> สร้างแผ่นเช็คชื่อ
            </button>
          </div>
        </div>

        <!-- รายการแผ่น -->
        <StateBlock
          v-if="sheets.length === 0"
          variant="empty"
          icon="bi-clipboard2"
          title="ยังไม่มีแผ่นเช็คชื่อ"
          hint='กด "เพิ่มการเช็คชื่อ" เพื่อสร้างแผ่นแรก เช่น เช็คขึ้นรถ'
        />
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
      <div class="page-card p-4 sm:p-5">
        <h2 class="section-title mb-1 flex min-w-0 items-center gap-2">
          <i class="bi bi-puzzle text-brand-700" aria-hidden="true"></i>
          <span class="truncate">ฟิลด์เพิ่มเติม</span>
        </h2>
        <p class="mb-3 text-xs text-stone-400 sm:mb-4">
          สร้างฟิลด์ข้อมูลที่ต้องการเก็บเพิ่มเติม (เช่น หมายเลขกลุ่ม, รถคันที่ลง) — ฟิลด์ใหม่จะ
          ปรากฏกับผู้เข้าร่วมทุกคน และตั้งค่าแบบกลุ่มได้
        </p>
        <DynamicFieldManager :defs="dynamicFieldDefs" @update="updateDynamicFields" />
      </div>
    </template>

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
