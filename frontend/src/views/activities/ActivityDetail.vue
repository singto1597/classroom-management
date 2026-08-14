<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import { StudentService } from '@/services/student'
import type { Activity, ActivityParticipant } from '@/types/activity'
import type { Student as StudentType } from '@/types/student'
import {
  ACTIVITY_STATUS_LABELS,
  ACTIVITY_STATUS_BADGE,
  ROLE_TYPE_LABELS,
  PARTICIPANT_STATUS_LABELS,
} from '@/types/activity'
import {
  ALL_ACTIVITY_FIELDS,
  ACTIVITY_FIELD_MAP,
  PROFILE_FIELD_KEYS,
  EVENT_FIELD_KEYS,
  type ActivityField,
} from '@/constants/activityFields'
import ActivityFieldControl from '@/components/activities/ActivityFieldControl.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const activityId = Number(route.params.id)

const activity = ref<Activity | null>(null)
const students = ref<StudentType[]>([])
const isLoading = ref(true)
const isExporting = ref(false)

const canManage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

// 🌟 คอลัมน์ Dynamic จาก activities.metadata.required_fields (Field Selector ตอนสร้าง)
const requiredFields = computed<string[]>(() => {
  const raw = activity.value?.metadata?.required_fields
  if (Array.isArray(raw)) return raw.map(String)
  return []
})
const selectedFields = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter((f) => requiredFields.value.includes(f.key)),
)
const typeAColumns = computed<ActivityField[]>(() =>
  selectedFields.value.filter((f) => PROFILE_FIELD_KEYS.has(f.key)),
)
const typeBColumns = computed<ActivityField[]>(() =>
  selectedFields.value.filter((f) => EVENT_FIELD_KEYS.has(f.key)),
)

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr + 'T00:00:00')
  return date.toLocaleDateString('th-TH', { day: 'numeric', month: 'long', year: 'numeric' })
}

const fetchData = async () => {
  isLoading.value = true
  try {
    activity.value = await ActivityService.getActivity(currentRoomId, activityId)
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'ไม่พบกิจกรรม'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
    router.push('/activities')
  } finally {
    isLoading.value = false
  }
}

const loadStudents = async () => {
  try {
    const list = await StudentService.getStudents(currentRoomId)
    students.value = (list as StudentType[]).filter((s) => s.status === 'active')
  } catch {
    students.value = []
  }
}

onMounted(async () => {
  await Promise.all([fetchData(), loadStudents()])
})

// ================================================================
// 📊 Smart Participant Table — แก้ค่า Type B ในตารางได้เลย + Batch Apply
// ================================================================
/** metadata ของ participant (mutable local state) — เผื่อแก้ในตารางแล้ว save */
const participantMetaDrafts = ref<Record<number, Record<string, unknown>>>({})

const draftMeta = (p: ActivityParticipant): Record<string, unknown> => {
  if (!participantMetaDrafts.value[p.id]) {
    participantMetaDrafts.value[p.id] = { ...p.metadata }
  }
  return participantMetaDrafts.value[p.id] ?? {}
}

const setDraftField = (p: ActivityParticipant, field: string, value: unknown) => {
  const meta = draftMeta(p)
  if (value === '' || value === null || value === undefined) {
    delete meta[field]
  } else {
    meta[field] = value
  }
  participantMetaDrafts.value = { ...participantMetaDrafts.value }
}

// 🎯 Batch Apply — ตั้งค่า Type B ให้ทุกคนที่ถูกติ๊ก (ปรับ metadata ในความจำ แล้ว Save ทีเดียว)
const selectedParticipantIds = ref<Set<number>>(new Set())
const showBatchModal = ref(false)
const batchValues = ref<Record<string, unknown>>({})
const batchFields = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter((f) => EVENT_FIELD_KEYS.has(f.key) && requiredFields.value.includes(f.key)),
)

const selectedParticipants = computed(() => {
  const parts = activity.value?.participants ?? []
  return parts.filter((p) => selectedParticipantIds.value.has(p.id))
})

const toggleSelectParticipant = (p: ActivityParticipant) => {
  const next = new Set(selectedParticipantIds.value)
  if (next.has(p.id)) next.delete(p.id)
  else next.add(p.id)
  selectedParticipantIds.value = next
}

const toggleSelectAllParticipants = () => {
  const parts = activity.value?.participants ?? []
  if (selectedParticipantIds.value.size === parts.length) {
    selectedParticipantIds.value = new Set()
  } else {
    selectedParticipantIds.value = new Set(parts.map((p) => p.id))
  }
}

const openBatchModal = () => {
  batchValues.value = {}
  showBatchModal.value = true
}

const applyBatch = async () => {
  const targets = selectedParticipants.value
  if (targets.length === 0) {
    return Swal.fire('เลือกก่อน', 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คน', 'warning')
  }
  const filled = Object.entries(batchValues.value).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  if (filled.length === 0) {
    return Swal.fire('กรอกค่า', 'กรุณากรอกค่าที่ต้องการตั้งค่าแบบกลุ่ม', 'warning')
  }
  try {
    await ActivityService.batchUpdateParticipants(currentRoomId, activityId, {
      items: targets.map((p) => ({
        participant_id: p.id,
        metadata: Object.fromEntries(filled),
      })),
      user_name: currentUserName,
    })
    // อัปเดต local participants (merge กับของเดิม) เพื่อให้ UI สะท้อนทันที
    if (activity.value) {
      for (const p of activity.value.participants) {
        if (selectedParticipantIds.value.has(p.id)) {
          p.metadata = { ...p.metadata, ...Object.fromEntries(filled) }
        }
      }
      activity.value = { ...activity.value }
    }
    showBatchModal.value = false
    selectedParticipantIds.value = new Set()
    Toast.fire({ icon: 'success', title: `ตั้งค่าแบบกลุ่มให้ ${targets.length} คนสำเร็จ` })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'ตั้งค่าแบบกลุ่มไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

/** บันทึกค่า Type B ที่แก้ในตาราง (per-participant PATCH) */
const saveDraftField = async (p: ActivityParticipant, field: string) => {
  if (!canManage.value) return
  const meta = draftMeta(p)
  try {
    await ActivityService.updateParticipant(currentRoomId, activityId, p.id, {
      metadata: { [field]: meta[field] },
      user_name: currentUserName,
    })
    p.metadata = ({
	...p.metadata,
	[field]: meta[field]
})
    Toast.fire({ icon: 'success', title: `บันทึก ${ACTIVITY_FIELD_MAP[field]?.label || field} แล้ว` })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'บันทึกไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// อัปเดตสถานะกิจกรรม
const changeStatus = async (status: string) => {
  if (!canManage.value) return
  try {
    await ActivityService.updateActivity(currentRoomId, activityId, {
      status,
      user_name: currentUserName,
    })
    activity.value!.status = status
    Toast.fire({ icon: 'success', title: 'อัปเดตสถานะกิจกรรมแล้ว' })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'อัปเดตสถานะไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// อัปเดต metadata ของกิจกรรม (เช่น ลิ้งก์แผนที่)
const editActivityMeta = async () => {
  if (!activity.value || !canManage.value) return
  const metaEntries = Object.entries(activity.value.metadata || {})
  const keys = metaEntries.map(([k]) => k)
  const vals = metaEntries.map(([, v]) => String(v))

  const { value: formValues } = await Swal.fire({
    title: 'แก้ไขข้อมูลเพิ่มเติม',
    html: `
      <div id="meta-fields" class="text-left mt-4 space-y-3"></div>
    `,
    showCancelButton: true,
    confirmButtonText: 'บันทึก',
    cancelButtonText: 'ยกเลิก',
    didOpen: () => {
      const container = document.getElementById('meta-fields')!
      container.innerHTML = ''
      if (keys.length === 0) keys.push('', '')
      keys.forEach((key, i) => {
        container.innerHTML += `
          <div class="flex gap-2">
            <input id="meta-key-${i}" placeholder="คีย์" value="${key.replace(/"/g, '&quot;')}" class="flex-1 px-3 py-2 bg-slate-50 border rounded-xl text-xs">
            <input id="meta-val-${i}" placeholder="ค่า" value="${(vals[i] || '').replace(/"/g, '&quot;')}" class="flex-1 px-3 py-2 bg-slate-50 border rounded-xl text-xs">
          </div>
        `
      })
    },
    preConfirm: () => {
      const meta: Record<string, unknown> = {}
      keys.forEach((_, i) => {
        const key = (document.getElementById(`meta-key-${i}`) as HTMLInputElement).value.trim()
        const val = (document.getElementById(`meta-val-${i}`) as HTMLInputElement).value.trim()
        if (key) meta[key] = val
      })
      return meta
    },
  })

  if (formValues) {
    try {
      await ActivityService.updateActivity(currentRoomId, activityId, {
        metadata: formValues,
        user_name: currentUserName,
      })
      activity.value.metadata = formValues
      Toast.fire({ icon: 'success', title: 'แก้ไขข้อมูลเพิ่มเติมแล้ว' })
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'บันทึกข้อมูลเพิ่มเติมไม่สำเร็จ'
      Swal.fire('ข้อผิดพลาด', msg, 'error')
    }
  }
}

// เปลี่ยนสถานะผู้เข้าร่วม (เช็คอิน)
const toggleParticipantStatus = async (participant: ActivityParticipant) => {
  if (!canManage.value) return
  const next = participant.status === 'attended' ? 'confirmed' : 'attended'
  try {
    await ActivityService.updateParticipantStatus(
      currentRoomId, activityId, participant.id, next, currentUserName,
    )
    participant.status = next
    Toast.fire({ icon: 'success', title: next === 'attended' ? '✅ เช็คอินแล้ว' : '🔄 เปลี่ยนกลับ' })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'อัปเดตสถานะไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// ลบผู้เข้าร่วม
const removeParticipant = async (participant: ActivityParticipant) => {
  if (!canManage.value) return
  const result = await Swal.fire({
    title: 'นำออกจากกิจกรรม?',
    text: `${participant.first_name} ${participant.last_name} จะถูกนำออก`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#e11d48',
    confirmButtonText: 'นำออก',
    cancelButtonText: 'ยกเลิก',
  })
  if (result.isConfirmed) {
    try {
      await ActivityService.removeParticipant(currentRoomId, activityId, participant.id, currentUserName)
      Toast.fire({ icon: 'success', title: 'นำออกแล้ว' })
      await fetchData()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'นำออกไม่สำเร็จ'
      Swal.fire('ข้อผิดพลาด', msg, 'error')
    }
  }
}

// Export Excel (Dynamic — backend อ่าน required_fields เอง ถ้าไม่มีใช้ metadataKeys)
const exportExcel = async () => {
  if (!canManage.value || !activity.value) return
  isExporting.value = true
  try {
    const blob = await ActivityService.exportActivityExcel(
      currentRoomId, activityId, requiredFields.value, currentUserName,
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `activity_${activityId}_participants.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    Toast.fire({ icon: 'success', title: 'Export Excel เรียบร้อย 📄' })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Export ไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  } finally {
    isExporting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-7xl mx-auto">

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังโหลดกิจกรรม...</p>
      </div>

      <div v-else-if="activity" class="space-y-5">
        <!-- Header -->
        <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
          <div>
            <router-link to="/activities" class="inline-flex items-center gap-1.5 text-sm font-bold text-slate-400 hover:text-slate-700 mb-2 transition-colors">
              <i class="bi bi-arrow-left"></i> กลับรายการกิจกรรม
            </router-link>
            <h3 class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-3 flex-wrap">
              <div class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0">
                <i class="bi bi-calendar-heart-fill"></i>
              </div>
              {{ activity.title }}
              <span
                class="px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border"
                :class="ACTIVITY_STATUS_BADGE[typeof activity.status === 'string' ? activity.status : 'upcoming'] || ACTIVITY_STATUS_BADGE.upcoming"
              >
                {{ ACTIVITY_STATUS_LABELS[typeof activity.status === 'string' ? activity.status : 'upcoming'] || activity.status }}
              </span>
            </h3>
          </div>

          <div v-if="canManage" class="flex flex-wrap gap-2">
            <router-link
              :to="`/activities/${activityId}/edit`"
              class="px-4 py-2.5 text-sm font-bold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 rounded-xl transition-all inline-flex items-center gap-2"
            >
              <i class="bi bi-pencil-square"></i> แก้ไข
            </router-link>
            <button
              @click="editActivityMeta"
              class="px-4 py-2.5 text-sm font-bold text-violet-600 bg-white border border-violet-200 hover:bg-violet-50 rounded-xl transition-all inline-flex items-center gap-2"
            >
              <i class="bi bi-sliders"></i> แก้ข้อมูลเพิ่มเติม
            </button>
            <button
              @click="exportExcel"
              :disabled="isExporting"
              class="px-4 py-2.5 text-sm font-bold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 rounded-xl shadow-lg shadow-emerald-600/20 transition-all inline-flex items-center gap-2"
            >
              <i v-if="isExporting" class="bi bi-arrow-repeat animate-spin"></i>
              <i v-else class="bi bi-file-earmark-excel"></i>
              Export Excel
            </button>
          </div>
        </div>

        <!-- สถานะ badges -->
        <div v-if="canManage" class="flex flex-wrap gap-2">
          <button
            v-for="(label, key) in ACTIVITY_STATUS_LABELS"
            :key="key"
            @click="changeStatus(key)"
            class="px-3 py-1.5 rounded-lg text-xs font-bold border transition-all"
            :class="activity.status === key ? 'bg-violet-600 text-white border-violet-600 shadow-sm' : 'bg-white text-slate-500 border-slate-200 hover:border-violet-300 hover:text-violet-600'"
          >
            {{ label }}
          </button>
        </div>

        <!-- Info cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="bg-white rounded-2xl p-4 shadow-sm border border-slate-100 flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center flex-shrink-0"><i class="bi bi-calendar-event"></i></div>
            <div>
              <p class="text-[11px] font-bold text-slate-400 uppercase">วันที่</p>
              <p class="text-sm font-bold text-slate-700">{{ formatDate(activity.activity_date) }}</p>
            </div>
          </div>
          <div class="bg-white rounded-2xl p-4 shadow-sm border border-slate-100 flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center flex-shrink-0"><i class="bi bi-clock-history"></i></div>
            <div>
              <p class="text-[11px] font-bold text-slate-400 uppercase">ชั่วโมงฐาน</p>
              <p class="text-sm font-bold text-slate-700">{{ activity.base_hours }} ชม.</p>
            </div>
          </div>
          <div class="bg-white rounded-2xl p-4 shadow-sm border border-slate-100 flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center flex-shrink-0"><i class="bi bi-people-fill"></i></div>
            <div>
              <p class="text-[11px] font-bold text-slate-400 uppercase">ผู้เข้าร่วม</p>
              <p class="text-sm font-bold text-slate-700">{{ activity.participant_count }} คน</p>
            </div>
          </div>
        </div>

        <!-- Description + Metadata -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="bg-white rounded-3xl p-5 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-3 flex items-center gap-2"><i class="bi bi-card-text text-violet-500"></i> รายละเอียด</h4>
            <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">{{ activity.description || 'ไม่มีรายละเอียด' }}</p>
          </div>
          <div class="bg-white rounded-3xl p-5 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-3 flex items-center gap-2"><i class="bi bi-asterisk text-violet-500"></i> ข้อมูลเพิ่มเติม</h4>
            <div class="space-y-2">
              <div v-for="(value, key) in activity.metadata" :key="key" class="flex items-start gap-2 text-sm">
                <span class="font-bold text-violet-600 bg-violet-50 px-2 py-0.5 rounded-lg text-xs whitespace-nowrap">{{ key }}</span>
                <span class="text-slate-600 break-all">
                  <template v-if="Array.isArray(value)">{{ (value as unknown[]).join(', ') }}</template>
                  <template v-else-if="typeof value === 'string' && value.startsWith('http')">
                    <a :href="value" target="_blank" rel="noopener" class="text-blue-600 underline hover:text-blue-800 inline-flex items-center gap-1">
                      <i class="bi bi-box-arrow-up-right"></i> เปิดลิงก์
                    </a>
                  </template>
                  <template v-else>{{ value }}</template>
                </span>
              </div>
              <div v-if="Object.keys(activity.metadata || {}).length === 0" class="text-sm text-slate-400">ไม่มีข้อมูลเพิ่มเติม</div>
            </div>
          </div>
        </div>

        <!-- Participants — Smart Table -->
        <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
          <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-3">
            <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-people-fill text-violet-500"></i> ผู้เข้าร่วม ({{ activity.participants.length }})
            </h4>
            <div class="flex flex-wrap gap-2">
              <button
                v-if="canManage && selectedParticipantIds.size > 0"
                @click="openBatchModal"
                class="px-4 py-2 text-sm font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-2"
              >
                <i class="bi bi-lightning-charge-fill"></i> ตั้งค่าแบบกลุ่ม ({{ selectedParticipantIds.size }})
              </button>
              <button
                v-if="canManage && activity.participants.length > 0"
                @click="toggleSelectAllParticipants"
                class="px-4 py-2 text-sm font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 rounded-xl transition-all inline-flex items-center gap-2"
              >
                <i class="bi bi-check-all"></i> {{ selectedParticipantIds.size === activity.participants.length ? 'ยกเลิกทั้งหมด' : 'เลือกทั้งหมด' }}
              </button>
            </div>
          </div>

          <!-- รายชื่อ — Smart Table (dynamic columns ตาม required_fields) -->
          <div v-if="activity.participants.length === 0" class="text-center py-10 text-slate-400 text-sm">
            ยังไม่มีผู้เข้าร่วม
          </div>
          <div v-else class="overflow-x-auto overflow-y-hidden rounded-xl border border-slate-100">
            <table class="w-full min-w-[700px] text-left">
              <thead>
                <tr class="border-b border-slate-100 bg-slate-50/60 text-[10px] font-black text-slate-400 uppercase tracking-wider">
                  <th v-if="canManage" class="py-2.5 px-2 w-10 text-center">✓</th>
                  <th class="py-2.5 px-2">เลขที่</th>
                  <th class="py-2.5 px-2">ชื่อ</th>
                  <th class="py-2.5 px-2">หน้าที่</th>
                  <th class="py-2.5 px-2">ชั่วโมง</th>
                  <th class="py-2.5 px-2">สถานะ</th>
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
                  <th v-if="canManage" class="py-2.5 px-2 text-right">จัดการ</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="p in activity.participants"
                  :key="p.id"
                  class="border-b border-slate-50 last:border-0 hover:bg-slate-50/60 transition-colors align-middle"
                  :class="{ 'bg-violet-50/50': selectedParticipantIds.has(p.id) }"
                >
                  <td v-if="canManage" class="py-3 px-2 text-center">
                    <input
                      type="checkbox"
                      :checked="selectedParticipantIds.has(p.id)"
                      @change="toggleSelectParticipant(p)"
                      class="w-4 h-4 rounded accent-violet-600"
                    />
                  </td>
                  <td class="py-3 px-2 text-sm font-bold text-slate-500">{{ p.student_no }}</td>
                  <td class="py-3 px-2 whitespace-nowrap">
                    <p class="text-sm font-bold text-slate-700">{{ p.first_name }} {{ p.last_name }}</p>
                    <p class="text-[11px] text-slate-400">{{ ROLE_TYPE_LABELS[p.role_type] || p.role_type }}</p>
                  </td>
                  <td class="py-3 px-2 text-sm text-slate-600">{{ p.role_detail || '—' }}</td>
                  <td class="py-3 px-2 text-sm text-slate-600">{{ p.earned_hours || 0 }}</td>
                  <td class="py-3 px-2">
                    <button
                      @click="toggleParticipantStatus(p)"
                      :disabled="!canManage"
                      class="px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-all"
                      :class="p.status === 'attended' ? 'bg-emerald-50 text-emerald-600 border-emerald-200' : 'bg-amber-50 text-amber-600 border-amber-200'"
                    >
                      {{ PARTICIPANT_STATUS_LABELS[p.status] || p.status }}
                    </button>
                  </td>
                  <!-- คอลัมน์ Type B — แก้ในตารางได้เลย (บันทึกเมื่อ blur/change) -->
                  <td v-for="field in typeBColumns" :key="field.key" class="py-3 px-2">
                    <ActivityFieldControl
                      :field="field"
                      :model-value="draftMeta(p)[field.key]"
                      :disabled="!canManage"
                      @update:model-value="(v: unknown) => setDraftField(p, field.key, v)"
                      @change="saveDraftField(p, field.key)"
                    />
                  </td>
                  <!-- คอลัมน์ Type A — อ่านจากโปรไฟล์ (🔒) -->
                  <td v-for="field in typeAColumns" :key="field.key" class="py-3 px-2">
                    <span class="text-xs font-semibold text-slate-600">{{ String((p as Record<string, unknown>)[field.key] ?? '—') }}</span>
                  </td>
                  <td v-if="canManage" class="py-3 px-2 text-right">
                    <button
                      @click="removeParticipant(p)"
                      class="w-8 h-8 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors inline-flex items-center justify-center"
                      title="นำออก"
                    >
                      <i class="bi bi-trash3"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <p v-if="typeBColumns.length === 0 && activity.participants.length > 0" class="text-[11px] text-slate-400 mt-3">
            💡 กิจกรรมนี้ยังไม่มีฟิลด์ Type B ที่เลือกไว้ตอนสร้าง (Required Data) — แก้ข้อมูลเพิ่มเติมได้ผ่านปุ่ม ⚙️ ต่อคน
          </p>
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
              ตั้งค่าฟิลด์ Type B ให้ผู้เข้าร่วม <b class="text-fuchsia-600">{{ selectedParticipantIds.size }} คน</b> พร้อมกัน
            </p>

            <div v-if="batchFields.length === 0" class="text-sm text-slate-500 bg-slate-50 rounded-xl p-4 text-center">
              กิจกรรมนี้ไม่มีฟิลด์ Type B ที่เลือกไว้
            </div>

            <div v-else class="space-y-4">
              <div v-for="field in batchFields" :key="field.key">
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
                :disabled="batchFields.length === 0"
                class="px-6 py-2.5 text-sm font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 disabled:opacity-50 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-1.5"
              >
                <i class="bi bi-lightning-charge-fill"></i> ใช้ค่ากับ {{ selectedParticipantIds.size }} คน
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
