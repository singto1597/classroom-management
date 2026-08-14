<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import { StudentService } from '@/services/student'
import type { Activity, ActivityParticipant, ParticipantAdd } from '@/types/activity'
import type { Student as StudentType } from '@/types/student'
import {
  ACTIVITY_STATUS_LABELS,
  ACTIVITY_STATUS_BADGE,
  ROLE_TYPE_LABELS,
  PARTICIPANT_STATUS_LABELS,
} from '@/types/activity'
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

// ฟอร์มเพิ่มผู้เข้าร่วม
const addForm = ref({
  student_no: 0 as number,
  role_detail: '',
  role_type: 'participant',
  bus_number: '',
})

const showAddParticipant = ref(false)
const metadataKeys = ref<string[]>(['bus_number', 'room_number', 'shirt_size', 'phone_number'])

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

const getTags = (metadata: Record<string, unknown> | undefined): string[] => {
  const tags = metadata?.tags
  if (Array.isArray(tags)) return tags.map(String).slice(0, 3)
  if (typeof tags === 'string' && tags) return tags.split(',').map((t) => t.trim()).slice(0, 3)
  return []
}

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr + 'T00:00:00')
  return date.toLocaleDateString('th-TH', { day: 'numeric', month: 'long', year: 'numeric' })
}

const fetchData = async () => {
  isLoading.value = true
  try {
    activity.value = await ActivityService.getActivity(currentRoomId, activityId)
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'ไม่พบกิจกรรม', 'error')
    router.push('/activities')
  } finally {
    isLoading.value = false
  }
}

const loadStudents = async () => {
  try {
    const list = await StudentService.getStudents(currentRoomId)
    students.value = (list as any[]).filter((s) => s.status === 'active')
  } catch {
    students.value = []
  }
}

onMounted(async () => {
  await Promise.all([fetchData(), loadStudents()])
})

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
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'อัปเดตสถานะไม่สำเร็จ', 'error')
  }
}

// อัปเดต metadata ของกิจกรรม (เช่น ลิ้งก์แผนที่)
const editActivityMeta = async () => {
  if (!activity.value || !canManage.value) return
  const metaEntries = Object.entries(activity.value.metadata || {})
  const keys = metaEntries.map(([k]) => k)
  const vals = metaEntries.map(([, v]) => String(v))

  const { value: formValues } = await Swal.fire({
    title: 'แก้ไข Metadata กิจกรรม',
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
      Toast.fire({ icon: 'success', title: 'แก้ไข metadata แล้ว' })
    } catch (error: any) {
      Swal.fire('ข้อผิดพลาด', error?.message || 'บันทึก metadata ไม่สำเร็จ', 'error')
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
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'อัปเดตสถานะไม่สำเร็จ', 'error')
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
    } catch (error: any) {
      Swal.fire('ข้อผิดพลาด', error?.message || 'นำออกไม่สำเร็จ', 'error')
    }
  }
}

// เพิ่มผู้เข้าร่วม
const submitAddParticipant = async () => {
  if (!addForm.value.student_no) {
    return Swal.fire('กรอกไม่ครบ', 'กรุณาเลือกเลขที่นักเรียน', 'warning')
  }
  const payload: ParticipantAdd = {
    student_no: addForm.value.student_no,
    role_type: addForm.value.role_type,
    role_detail: addForm.value.role_detail.trim() || null,
    metadata: addForm.value.bus_number ? { bus_number: addForm.value.bus_number } : {},
    user_name: currentUserName,
  }
  try {
    await ActivityService.addParticipant(currentRoomId, activityId, payload)
    Toast.fire({ icon: 'success', title: 'เพิ่มผู้เข้าร่วมแล้ว' })
    showAddParticipant.value = false
    addForm.value = { student_no: 0, role_detail: '', role_type: 'participant', bus_number: '' }
    await fetchData()
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'เพิ่มผู้เข้าร่วมไม่สำเร็จ', 'error')
  }
}

// Export Excel
const exportExcel = async () => {
  if (!canManage.value || !activity.value) return
  isExporting.value = true
  try {
    const blob = await ActivityService.exportActivityExcel(
      currentRoomId, activityId, metadataKeys.value, currentUserName,
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `activity_${activityId}_participants.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    Toast.fire({ icon: 'success', title: 'Export Excel เรียบร้อย 📄' })
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'Export ไม่สำเร็จ', 'error')
  } finally {
    isExporting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-6xl mx-auto">

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
            <button
              @click="editActivityMeta"
              class="px-4 py-2.5 text-sm font-bold text-violet-600 bg-white border border-violet-200 hover:bg-violet-50 rounded-xl transition-all inline-flex items-center gap-2"
            >
              <i class="bi bi-sliders"></i> แก้ Metadata
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
            <h4 class="text-base font-bold text-slate-700 mb-3 flex items-center gap-2"><i class="bi bi-asterisk text-violet-500"></i> Metadata</h4>
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
              <div v-if="Object.keys(activity.metadata || {}).length === 0" class="text-sm text-slate-400">ไม่มี metadata</div>
            </div>
          </div>
        </div>

        <!-- Participants -->
        <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
          <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-3">
            <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-people-fill text-violet-500"></i> ผู้เข้าร่วม ({{ activity.participants.length }})
            </h4>
            <button
              v-if="canManage"
              @click="showAddParticipant = !showAddParticipant"
              class="px-4 py-2 text-sm font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 rounded-xl transition-all inline-flex items-center gap-2"
            >
              <i class="bi bi-person-plus"></i> เพิ่มผู้เข้าร่วม
            </button>
          </div>

          <!-- ฟอร์มเพิ่ม -->
          <div v-if="showAddParticipant" class="bg-slate-50 rounded-2xl p-4 mb-4 border border-slate-100 space-y-3">
            <div class="grid grid-cols-1 sm:grid-cols-4 gap-3">
              <div>
                <label class="text-[11px] font-bold text-slate-400 uppercase mb-1 block">เลขที่</label>
                <select
                  v-model.number="addForm.student_no"
                  class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                >
                  <option :value="0" disabled>เลือกเลขที่</option>
                  <option
                    v-for="s in students"
                    :key="s.student_no"
                    :value="Number(s.student_no)"
                  >
                    {{ s.student_no }} — {{ s.prefix || '' }}{{ s.first_name }} {{ s.last_name }}
                  </option>
                </select>
              </div>
              <div>
                <label class="text-[11px] font-bold text-slate-400 uppercase mb-1 block">ประเภท</label>
                <select
                  v-model="addForm.role_type"
                  class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                >
                  <option value="participant">ผู้เข้าร่วม</option>
                  <option value="staff">ทีมงาน</option>
                  <option value="leader">หัวหน้ากลุ่ม</option>
                </select>
              </div>
              <div>
                <label class="text-[11px] font-bold text-slate-400 uppercase mb-1 block">หน้าที่</label>
                <input
                  v-model="addForm.role_detail"
                  type="text"
                  placeholder="เช่น สวัสดิการ"
                  class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
              </div>
              <div>
                <label class="text-[11px] font-bold text-slate-400 uppercase mb-1 block">เบอร์รถบัส</label>
                <input
                  v-model="addForm.bus_number"
                  type="text"
                  placeholder="เช่น B2"
                  class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
              </div>
            </div>
            <div class="flex justify-end">
              <button
                @click="submitAddParticipant"
                class="px-5 py-2 text-sm font-bold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-sm transition-all"
              >
                เพิ่ม
              </button>
            </div>
          </div>

          <!-- รายชื่อ -->
          <div v-if="activity.participants.length === 0" class="text-center py-10 text-slate-400 text-sm">
            ยังไม่มีผู้เข้าร่วม
          </div>
          <div v-else class="overflow-x-auto overflow-y-hidden">
            <table class="w-full min-w-[640px] text-left">
              <thead>
                <tr class="border-b border-slate-100 text-[11px] font-black text-slate-400 uppercase tracking-wider">
                  <th class="py-2.5 px-2">เลขที่</th>
                  <th class="py-2.5 px-2">ชื่อ</th>
                  <th class="py-2.5 px-2">หน้าที่</th>
                  <th class="py-2.5 px-2">ชั่วโมง</th>
                  <th class="py-2.5 px-2">สถานะ</th>
                  <th class="py-2.5 px-2">metadata</th>
                  <th v-if="canManage" class="py-2.5 px-2 text-right">จัดการ</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="p in activity.participants"
                  :key="p.id"
                  class="border-b border-slate-50 last:border-0 hover:bg-slate-50/60 transition-colors"
                >
                  <td class="py-3 px-2 text-sm font-bold text-slate-500">{{ p.student_no }}</td>
                  <td class="py-3 px-2">
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
                  <td class="py-3 px-2">
                    <div class="flex flex-wrap gap-1">
                      <span
                        v-for="(v, k) in (p.metadata || {})"
                        :key="k"
                        class="px-1.5 py-0.5 rounded-md bg-slate-50 border border-slate-100 text-[10px] font-bold text-slate-500"
                      >
                        {{ k }}: {{ String(v) }}
                      </span>
                      <span v-if="Object.keys(p.metadata || {}).length === 0" class="text-[11px] text-slate-300">—</span>
                    </div>
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
        </div>
      </div>
    </div>
  </div>
</template>
