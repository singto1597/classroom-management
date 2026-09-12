<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import { displayName } from '@/utils/name'
import type { Activity, ActivityParticipant, RosterItem } from '@/types/activity'
import { ACTIVITY_STATUS_LABELS } from '@/types/activity'
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

/** โทนสีป้ายสถานะ (chip) — คุมโทนตาม Design Contract ไม่ใช้สีฟ้า/ชมพูแบบเดิม */
function statusChip(status: unknown): string {
  const key = typeof status === 'string' ? status : ''
  if (key === 'ongoing') return 'bg-amber-50 text-amber-700'
  if (key === 'completed') return 'bg-emerald-50 text-emerald-700'
  if (key === 'cancelled') return 'bg-red-50 text-red-700'
  return 'bg-brand-50 text-brand-700'
}

const fetchData = async () => {
  isLoading.value = true
  try {
    activity.value = await ActivityService.getActivity(currentRoomId, activityId)
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
    confirmButtonColor: '#dc2626',
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
      Swal.fire({
        icon: 'error',
        title: 'ข้อผิดพลาด',
        text: msg,
        confirmButtonColor: '#1d4ed8',
      })
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
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
  }
}

// --- Export ---
/** ชื่อไฟล์ปลอดภัย: ตัดอักขระต้องห้าม + กันยาวเกิน (ใช้ชื่อกิจกรรมตั้งชื่อไฟล์) */
function safeFileName(title: string): string {
  const cleaned = title.replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, '_').trim()
  return cleaned.slice(0, 80) || 'กิจกรรม'
}

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
    // 🌟 ชื่อไฟล์ใช้ชื่อกิจกรรม (สอดคล้องกับชื่อที่ backend สร้าง) ไม่ใช่ activity_<id>
    a.download = `${safeFileName(activity.value.title)}_รายชื่อผู้เข้าร่วม.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    Toast.fire({ icon: 'success', title: 'Export Excel เรียบร้อย 📄' })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Export ไม่สำเร็จ'
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: '#1d4ed8',
    })
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
  <div class="space-y-4 sm:space-y-5">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <template v-else-if="activity">
      <!-- Header -->
      <div>
        <router-link
          to="/activities"
          class="mb-2 inline-flex items-center gap-1.5 text-sm font-bold text-stone-400 transition-colors hover:text-brand-700"
        >
          <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับรายการกิจกรรม
        </router-link>

        <PageHeader
          eyebrow="Activity"
          :title="activity.title"
          description="รายละเอียดกิจกรรม ผู้เข้าร่วม และการเช็คอิน"
        >
          <template #actions>
            <template v-if="canManage">
              <!-- ปุ่มหลัก: จัดการผู้เข้าร่วม -->
              <router-link :to="`/activities/${activityId}/manage`" class="btn-primary">
                <i class="bi bi-sliders" aria-hidden="true"></i> จัดการผู้เข้าร่วม
              </router-link>

              <!-- เมนูจุด 3 จุด: เปลี่ยนสถานะ / แก้ไข / Export -->
              <div class="relative">
                <button
                  type="button"
                  class="flex h-11 w-11 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-500 transition-colors hover:bg-stone-50 hover:text-stone-900 active:scale-[0.97]"
                  title="การจัดการกิจกรรม"
                  aria-label="การจัดการกิจกรรม"
                  @click="toggleActionMenu"
                >
                  <i class="bi bi-three-dots-vertical text-lg" aria-hidden="true"></i>
                </button>

                <transition name="fade">
                  <div
                    v-if="actionMenuOpen"
                    class="absolute right-0 top-12 z-30 w-56 origin-top-right overflow-hidden rounded-2xl border border-stone-200 bg-white py-1 shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
                  >
                    <!-- เปลี่ยนสถานะ -->
                    <p
                      class="px-4 pb-1 pt-2.5 text-[10px] font-bold uppercase tracking-wider text-stone-400"
                    >
                      เปลี่ยนสถานะ
                    </p>
                    <button
                      v-for="(label, key) in ACTIVITY_STATUS_LABELS"
                      :key="key"
                      type="button"
                      class="flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm transition-colors"
                      :class="
                        activity.status === key
                          ? 'bg-brand-50/60 font-bold text-brand-700'
                          : 'text-stone-600 hover:bg-stone-50'
                      "
                      @click="changeStatus(key)"
                    >
                      <span class="inline-flex items-center gap-2">
                        <i
                          class="bi w-4 text-center text-xs"
                          :class="statusIcon(key)"
                          aria-hidden="true"
                        ></i>
                        {{ label }}
                      </span>
                      <i
                        v-if="activity.status === key"
                        class="bi bi-check-lg text-brand-700"
                        aria-hidden="true"
                      ></i>
                    </button>

                    <div class="my-1 border-t border-stone-100"></div>

                    <!-- แก้ไข / Export -->
                    <router-link
                      :to="`/activities/${activityId}/edit`"
                      class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-stone-600 transition-colors hover:bg-stone-50"
                    >
                      <i class="bi bi-pencil-square text-stone-400" aria-hidden="true"></i>
                      แก้ไขกิจกรรม
                    </router-link>
                    <button
                      type="button"
                      class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-stone-600 transition-colors hover:bg-stone-50 disabled:opacity-50"
                      :disabled="isExporting"
                      @click="exportExcel"
                    >
                      <i
                        v-if="isExporting"
                        class="bi bi-arrow-repeat animate-spin text-emerald-600"
                        aria-hidden="true"
                      ></i>
                      <i
                        v-else
                        class="bi bi-file-earmark-excel text-emerald-600"
                        aria-hidden="true"
                      ></i>
                      Export Excel
                    </button>
                  </div>
                </transition>
              </div>
            </template>
          </template>
        </PageHeader>
      </div>

      <!-- ข้อมูลประกอบย่อ -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="chip" :class="statusChip(activity.status)">
          {{
            ACTIVITY_STATUS_LABELS[
              typeof activity.status === 'string' ? activity.status : 'upcoming'
            ] || activity.status
          }}
        </span>
        <span class="chip bg-stone-100 text-stone-600">
          <i class="bi bi-calendar-event" aria-hidden="true"></i>
          <span class="num">{{ formatDate(activity.activity_date) }}</span>
        </span>
        <span class="chip bg-stone-100 text-stone-600">
          <i class="bi bi-clock-history" aria-hidden="true"></i>
          <span class="num">{{ activity.base_hours }}</span> ชม.
        </span>
        <span class="chip bg-stone-100 text-stone-600">
          <i class="bi bi-people-fill" aria-hidden="true"></i>
          <span class="num">{{ activity.participant_count }}</span> คน
        </span>
      </div>

      <!-- Description + ข้อมูลเพิ่มเติม (friendly) -->
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div class="page-card p-4 sm:p-5">
          <h2 class="section-title mb-3 flex items-center gap-2">
            <i class="bi bi-card-text text-brand-700" aria-hidden="true"></i> รายละเอียด
          </h2>
          <p class="whitespace-pre-wrap text-sm leading-relaxed text-stone-600">
            {{ activity.description || 'ไม่มีรายละเอียด' }}
          </p>
        </div>
        <div class="page-card p-4 sm:p-5">
          <h2 class="section-title mb-3 flex items-center gap-2">
            <i class="bi bi-asterisk text-brand-700" aria-hidden="true"></i> ข้อมูลเพิ่มเติม
          </h2>
          <div v-if="activityInfoRows.length === 0" class="text-sm text-stone-400">
            ไม่มีข้อมูลเพิ่มเติม
          </div>
          <!-- Grid แบบ Minimal: แต่ละรายการเป็นกล่องเล็ก (label ด้านบน, ค่าด้านล่าง) -->
          <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div
              v-for="(row, i) in activityInfoRows"
              :key="i"
              class="rounded-xl border border-stone-200 bg-stone-50/70 px-3.5 py-2.5"
            >
              <p class="mb-1 text-[10px] font-bold uppercase tracking-wider text-stone-400">
                {{ row.label }}
              </p>
              <div class="break-all text-sm text-stone-700">
                <!-- ลิงก์แผนที่ -->
                <a
                  v-if="row.kind === 'link'"
                  :href="row.value"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1 font-bold text-brand-700 underline hover:text-brand-800"
                >
                  <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i> เปิดลิงก์
                </a>
                <!-- กำหนดการ (หลายบรรทัด) -->
                <span
                  v-else-if="row.kind === 'lines'"
                  class="block space-y-0.5 whitespace-pre-wrap"
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
                    class="chip bg-brand-50 text-brand-700"
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
      <div class="page-card p-4 sm:p-5">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 class="section-title flex min-w-0 items-center gap-2">
            <i class="bi bi-people-fill text-brand-700" aria-hidden="true"></i>
            <span class="truncate">ผู้เข้าร่วม ({{ activity.participants.length }})</span>
          </h2>
          <div class="flex flex-wrap items-center gap-2">
            <span class="chip bg-emerald-50 text-emerald-700">
              <i class="bi bi-check2-circle" aria-hidden="true"></i>
              มาแล้ว {{ attendedCount }}/{{ activity.participants.length }}
            </span>
            <span v-if="canManage" class="chip bg-stone-100 text-stone-600">
              <i class="bi bi-info-circle" aria-hidden="true"></i>
              กด "ยังไม่มา" เพื่อเช็คอิน
            </span>
          </div>
        </div>

        <StateBlock
          v-if="activity.participants.length === 0"
          variant="empty"
          icon="bi-people"
          title="ยังไม่มีผู้เข้าร่วม"
          hint="เพิ่มผู้เข้าร่วมได้จากหน้า 'จัดการผู้เข้าร่วม'"
        />
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
    </template>

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
