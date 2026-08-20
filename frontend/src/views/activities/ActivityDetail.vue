<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import { displayName } from '@/utils/name'
import type { Activity, ActivityParticipant, RosterItem } from '@/types/activity'
import { ACTIVITY_STATUS_LABELS, ACTIVITY_STATUS_BADGE } from '@/types/activity'
import {
  ALL_ACTIVITY_FIELDS,
  PROFILE_FIELD_KEYS,
  EVENT_FIELD_KEYS,
  renderActivityInfo,
  type ActivityField,
  type ActivityInfoRow,
} from '@/constants/activityFields'
import ParticipantRosterList from '@/components/activities/ParticipantRosterList.vue'
import ParticipantInfoModal from '@/components/activities/ParticipantInfoModal.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const activityId = Number(route.params.id)

const activity = ref<Activity | null>(null)
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
const typeAColumns = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter(
    (f) => PROFILE_FIELD_KEYS.has(f.key) && requiredFields.value.includes(f.key),
  ),
)
const typeBColumns = computed<ActivityField[]>(() =>
  ALL_ACTIVITY_FIELDS.filter(
    (f) => EVENT_FIELD_KEYS.has(f.key) && requiredFields.value.includes(f.key),
  ),
)

/** หน้าที่/ตำแหน่งของกิจกรรมนี้ */
const positions = computed<string[]>(() => {
  const raw = activity.value?.metadata?.positions
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean)
  return []
})

/** ข้อมูลเพิ่มเติมของกิจกรรม → แถว friendly (label ไทย ไม่มีคีย์ดิบ) */
const activityInfoRows = computed<ActivityInfoRow[]>(() =>
  renderActivityInfo(activity.value?.metadata),
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

// ================================================================
// 👥 ผู้เข้าร่วม — การ์ดรายชื่อ (ตามแบบ StudentList) — โหมดแสดงเฉย ๆ
// ================================================================
const rosterItems = computed<RosterItem[]>(() => {
  return (activity.value?.participants ?? []).map((p) => ({
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
  }))
})

/** ค้น participant จาก key (participant.id) */
function participantByKey(key: string | number): ActivityParticipant | undefined {
  return (activity.value?.participants ?? []).find((p) => p.id === Number(key))
}

/** จำนวนผู้เข้าร่วมที่เช็คอินแล้ว (มาแล้ว) — แสดง summary ที่หัวรายชื่อ */
const attendedCount = computed(
  () => (activity.value?.participants ?? []).filter((p) => p.status === 'attended').length,
)

// --- Per-student info modal (อ่านอย่างเดียว) ---
const infoModalOpen = ref(false)
const infoModalKey = ref<number | null>(null)

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

// --- Check-in / status toggle ---
const toggleParticipantStatus = async (key: string | number) => {
  const participant = participantByKey(key)
  if (!participant || !canManage.value) return
  const next = participant.status === 'attended' ? 'confirmed' : 'attended'
  try {
    await ActivityService.updateParticipantStatus(
      currentRoomId,
      activityId,
      participant.id,
      next,
      currentUserName,
    )
    participant.status = next
    activity.value = { ...activity.value! }
    Toast.fire({
      icon: 'success',
      title: next === 'attended' ? '✅ เช็คอินแล้ว' : '🔄 เปลี่ยนกลับ',
    })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'อัปเดตสถานะไม่สำเร็จ'
    Swal.fire('ข้อผิดพลาด', msg, 'error')
  }
}

// --- Remove participant (ซ่อนในเมนูจุด 3 จุด) ---
const removeParticipant = async (key: string | number) => {
  const participant = participantByKey(key)
  if (!participant || !canManage.value) return
  const result = await Swal.fire({
    title: 'นำออกจากกิจกรรม?',
    text: `${displayName(participant)} จะถูกนำออก`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#e11d48',
    confirmButtonText: 'นำออก',
    cancelButtonText: 'ยกเลิก',
  })
  if (result.isConfirmed) {
    try {
      await ActivityService.removeParticipant(
        currentRoomId,
        activityId,
        participant.id,
        currentUserName,
      )
      Toast.fire({ icon: 'success', title: 'นำออกแล้ว' })
      await fetchData()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'นำออกไม่สำเร็จ'
      Swal.fire('ข้อผิดพลาด', msg, 'error')
    }
  }
}

// --- Activity status ---
const changeStatus = async (status: string) => {
  if (!canManage.value) return
  closeActionMenu()
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

// --- Export ---
const exportExcel = async () => {
  if (!canManage.value || !activity.value) return
  closeActionMenu()
  isExporting.value = true
  try {
    const blob = await ActivityService.exportActivityExcel(
      currentRoomId,
      activityId,
      requiredFields.value,
      currentUserName,
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

/** แสดงข้อมูลเพิ่มเติมของกิจกรรมแบบ friendly (map kind → icon/format) */
function infoValueDisplay(row: ActivityInfoRow): string {
  if (row.kind === 'chips' && row.value) {
    // แสดงเป็น chips (หมวดหมู่)
    return row.value
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
      .join(' · ')
  }
  return row.value
}

// --- เมนูจุด 3 จุด (รวมแอคชั่น: เปลี่ยนสถานะ / แก้ไข / Export) ---
const actionMenuOpen = ref(false)

function toggleActionMenu(event: Event) {
  event.stopPropagation() // ป้องกันไม่ให้คลิกทะลุไปปิดเมนูทันที (document listener)
  actionMenuOpen.value = !actionMenuOpen.value
}

function closeActionMenu() {
  actionMenuOpen.value = false
}

/** ไอคอนสำหรับแต่ละสถานะกิจกรรม (ในเมนูเปลี่ยนสถานะ) */
function statusIcon(status: string): string {
  switch (status) {
    case 'upcoming':
      return 'bi-calendar-event'
    case 'ongoing':
      return 'bi-play-circle'
    case 'completed':
      return 'bi-check2-circle'
    case 'cancelled':
      return 'bi-x-circle'
    default:
      return 'bi-circle'
  }
}

onMounted(() => {
  document.addEventListener('click', closeActionMenu)
  fetchData()
})
onUnmounted(() => document.removeEventListener('click', closeActionMenu))
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
            <router-link
              to="/activities"
              class="inline-flex items-center gap-1.5 text-sm font-bold text-slate-400 hover:text-slate-700 mb-2 transition-colors"
            >
              <i class="bi bi-arrow-left"></i> กลับรายการกิจกรรม
            </router-link>
            <h3
              class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-3 flex-wrap"
            >
              <div
                class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0"
              >
                <i class="bi bi-calendar-heart-fill"></i>
              </div>
              {{ activity.title }}
              <span
                class="px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border"
                :class="
                  ACTIVITY_STATUS_BADGE[
                    typeof activity.status === 'string' ? activity.status : 'upcoming'
                  ] || ACTIVITY_STATUS_BADGE.upcoming
                "
              >
                {{
                  ACTIVITY_STATUS_LABELS[
                    typeof activity.status === 'string' ? activity.status : 'upcoming'
                  ] || activity.status
                }}
              </span>
            </h3>
          </div>

          <div v-if="canManage" class="flex items-center gap-2 w-full sm:w-auto">
            <!-- ปุ่มหลัก: จัดการผู้เข้าร่วม -->
            <router-link
              :to="`/activities/${activityId}/manage`"
              class="flex-1 sm:flex-none px-4 py-2.5 text-sm font-bold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center justify-center gap-2"
            >
              <i class="bi bi-sliders"></i> จัดการผู้เข้าร่วม
            </router-link>

            <!-- เมนูจุด 3 จุด: เปลี่ยนสถานะ / แก้ไข / Export -->
            <div class="relative">
              <button
                @click="toggleActionMenu"
                class="w-10 h-10 flex items-center justify-center rounded-xl text-slate-500 bg-white border border-slate-200 hover:bg-slate-50 hover:text-slate-700 transition-colors"
                title="การจัดการกิจกรรม"
              >
                <i class="bi bi-three-dots-vertical text-lg"></i>
              </button>

              <transition name="fade">
                <div
                  v-if="actionMenuOpen"
                  class="absolute right-0 top-12 w-56 bg-white rounded-2xl shadow-[0_4px_20px_-4px_rgba(0,0,0,0.15)] border border-slate-100 overflow-hidden z-30 py-1 origin-top-right"
                >
                  <!-- เปลี่ยนสถานะ -->
                  <p
                    class="px-4 pt-2.5 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400"
                  >
                    เปลี่ยนสถานะ
                  </p>
                  <button
                    v-for="(label, key) in ACTIVITY_STATUS_LABELS"
                    :key="key"
                    @click="changeStatus(key)"
                    class="w-full text-left px-4 py-2 text-sm flex items-center justify-between gap-2 transition-colors"
                    :class="
                      activity.status === key
                        ? 'text-violet-600 font-bold bg-violet-50/60'
                        : 'text-slate-600 hover:bg-slate-50'
                    "
                  >
                    <span class="inline-flex items-center gap-2">
                      <i class="bi text-xs w-4 text-center" :class="statusIcon(key)"></i>
                      {{ label }}
                    </span>
                    <i v-if="activity.status === key" class="bi bi-check-lg text-violet-600"></i>
                  </button>

                  <div class="my-1 border-t border-slate-100"></div>

                  <!-- แก้ไข / Export -->
                  <router-link
                    :to="`/activities/${activityId}/edit`"
                    class="w-full text-left px-4 py-2.5 text-sm text-slate-600 hover:bg-slate-50 flex items-center gap-2.5 transition-colors"
                  >
                    <i class="bi bi-pencil-square text-slate-400"></i> แก้ไขกิจกรรม
                  </router-link>
                  <button
                    @click="exportExcel"
                    :disabled="isExporting"
                    class="w-full text-left px-4 py-2.5 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50 flex items-center gap-2.5 transition-colors"
                  >
                    <i
                      v-if="isExporting"
                      class="bi bi-arrow-repeat animate-spin text-emerald-500"
                    ></i>
                    <i v-else class="bi bi-file-earmark-excel text-emerald-500"></i>
                    Export Excel
                  </button>
                </div>
              </transition>
            </div>
          </div>
        </div>

        <!-- ข้อมูลประกอบย่อ (badge เล็ก กระชับ) -->
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="inline-flex items-center gap-1.5 text-xs font-bold text-slate-600 bg-white border border-slate-100 rounded-lg px-2.5 py-1 shadow-sm"
          >
            <i class="bi bi-calendar-event text-violet-500"></i>
            {{ formatDate(activity.activity_date) }}
          </span>
          <span
            class="inline-flex items-center gap-1.5 text-xs font-bold text-slate-600 bg-white border border-slate-100 rounded-lg px-2.5 py-1 shadow-sm"
          >
            <i class="bi bi-clock-history text-emerald-500"></i>
            {{ activity.base_hours }} ชม.
          </span>
          <span
            class="inline-flex items-center gap-1.5 text-xs font-bold text-slate-600 bg-white border border-slate-100 rounded-lg px-2.5 py-1 shadow-sm"
          >
            <i class="bi bi-people-fill text-blue-500"></i>
            {{ activity.participant_count }} คน
          </span>
        </div>

        <!-- Description + ข้อมูลเพิ่มเติม (friendly) -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="bg-white rounded-3xl p-5 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-3 flex items-center gap-2">
              <i class="bi bi-card-text text-violet-500"></i> รายละเอียด
            </h4>
            <p class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">
              {{ activity.description || 'ไม่มีรายละเอียด' }}
            </p>
          </div>
          <div class="bg-white rounded-3xl p-5 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-3 flex items-center gap-2">
              <i class="bi bi-asterisk text-violet-500"></i> ข้อมูลเพิ่มเติม
            </h4>
            <div v-if="activityInfoRows.length === 0" class="text-sm text-slate-400">
              ไม่มีข้อมูลเพิ่มเติม
            </div>
            <!-- Grid แบบ Minimal: แต่ละรายการเป็นกล่องเล็ก (label ด้านบน, ค่าด้านล่าง) -->
            <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div
                v-for="(row, i) in activityInfoRows"
                :key="i"
                class="bg-slate-50/70 border border-slate-100 rounded-xl px-3.5 py-2.5"
              >
                <p class="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
                  {{ row.label }}
                </p>
                <div class="text-sm text-slate-700 break-all">
                  <!-- ลิงก์แผนที่ -->
                  <a
                    v-if="row.kind === 'link'"
                    :href="row.value"
                    target="_blank"
                    rel="noopener"
                    class="text-blue-600 underline hover:text-blue-800 inline-flex items-center gap-1"
                  >
                    <i class="bi bi-box-arrow-up-right"></i> เปิดลิงก์
                  </a>
                  <!-- กำหนดการ (หลายบรรทัด) -->
                  <span
                    v-else-if="row.kind === 'lines'"
                    class="whitespace-pre-wrap block space-y-0.5"
                  >
                    <span
                      v-for="(line, li) in row.value
                        .split(/[|\n]/)
                        .map((s) => s.trim())
                        .filter(Boolean)"
                      :key="li"
                      class="block"
                    >
                      • {{ line }}
                    </span>
                  </span>
                  <!-- หมวดหมู่ -->
                  <span v-else-if="row.kind === 'chips'" class="inline-flex flex-wrap gap-1.5">
                    <span
                      v-for="(tag, ti) in row.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean)"
                      :key="ti"
                      class="px-2.5 py-0.5 rounded-lg text-[11px] font-bold bg-violet-50 text-violet-600 border border-violet-100"
                    >
                      #{{ tag }}
                    </span>
                  </span>
                  <!-- ข้อความปกติ -->
                  <span v-else>{{ infoValueDisplay(row) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ผู้เข้าร่วม — การ์ดรายชื่อ (อ่านอย่างเดียว) -->
        <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
          <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
            <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-people-fill text-violet-500"></i> ผู้เข้าร่วม ({{
                activity.participants.length
              }})
            </h4>
            <div class="flex flex-wrap items-center gap-2">
              <span
                class="inline-flex items-center gap-1.5 text-[11px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-lg px-2.5 py-1"
              >
                <i class="bi bi-check2-circle"></i>
                มาแล้ว {{ attendedCount }}/{{ activity.participants.length }}
              </span>
              <span
                v-if="canManage"
                class="inline-flex items-center gap-1.5 text-[11px] font-bold text-slate-400 bg-slate-50 border border-slate-100 rounded-lg px-2.5 py-1"
              >
                <i class="bi bi-info-circle"></i>
                กด "ยังไม่มา" เพื่อเช็คอิน
              </span>
            </div>
          </div>

          <div
            v-if="activity.participants.length === 0"
            class="text-center py-10 text-slate-400 text-sm"
          >
            ยังไม่มีผู้เข้าร่วม
          </div>
          <ParticipantRosterList
            v-else
            :items="rosterItems"
            :positions="positions"
            read-only
            :can-manage="canManage"
            :show-status-toggle="canManage"
            :show-remove="canManage"
            :empty-text="'ไม่มีรายชื่อในรายการนี้'"
            @open-info="openInfoModal"
            @toggle-status="toggleParticipantStatus"
            @remove="removeParticipant"
          />
        </div>
      </div>
    </div>

    <!-- 📋 Modal: ข้อมูลเพิ่มเติมของนักเรียน (ต่อคน) — อ่านอย่างเดียว -->
    <ParticipantInfoModal
      :open="infoModalOpen && !!infoItem"
      :item="infoItem"
      :type-a-fields="typeAColumns"
      :type-b-fields="typeBColumns"
      :positions="positions"
      :can-manage="canManage"
      read-only
      @close="closeInfoModal"
    />
  </div>
</template>

<style scoped>
/* Animation สำหรับ Dropdown จุด 3 จุด */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: scale(0.95);
}
</style>
