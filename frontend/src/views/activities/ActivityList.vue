<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import type { Activity } from '@/types/activity'
import { ACTIVITY_STATUS_LABELS } from '@/types/activity'
import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const canManageActivities = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

const activities = ref<Activity[]>([])
const isLoading = ref(true)
const hasError = ref(false)
const filter = ref<StatusFilter>('all')

/** โทนสีป้ายสถานะ (chip) — คุมโทนตาม Design Contract ไม่ใช้สีฟ้า/ชมพูแบบเดิม */
function statusChip(status: unknown): string {
  const key = typeof status === 'string' ? status : ''
  if (key === 'ongoing') return 'bg-amber-50 text-amber-700'
  if (key === 'completed') return 'bg-emerald-50 text-emerald-700'
  if (key === 'cancelled') return 'bg-red-50 text-red-700'
  return 'bg-brand-50 text-brand-700'
}

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

const fetchData = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    activities.value = await ActivityService.getActivities(currentRoomId)
  } catch (error: unknown) {
    hasError.value = true
    const msg = error instanceof Error ? error.message : 'ดึงข้อมูลกิจกรรมไม่สำเร็จ'
    Toast.fire({ icon: 'error', title: msg })
  } finally {
    isLoading.value = false
  }
}

const filteredActivities = computed(() => {
  let list = activities.value
  if (filter.value !== 'all') {
    list = list.filter((a) => a.status === filter.value)
  }
  return [...list].sort((a, b) => {
    // เรียงตามวันกิจกรรม (ใกล้ก่อน) — ถ้าใกล้แล้วสถานะ upcoming ขึ้นก่อน
    return (
      new Date(a.activity_date + 'T00:00:00').getTime() -
      new Date(b.activity_date + 'T00:00:00').getTime()
    )
  })
})

type StatusFilter = 'all' | 'upcoming' | 'ongoing' | 'completed' | 'cancelled'

const statusCount = computed(() => {
  const counts: Record<StatusFilter, number> = {
    all: activities.value.length,
    upcoming: 0,
    ongoing: 0,
    completed: 0,
    cancelled: 0,
  }
  activities.value.forEach((a) => {
    const key = typeof a.status === 'string' ? (a.status as StatusFilter) : 'upcoming'
    if (key in counts) counts[key] += 1
  })
  return counts
})

// 📍 เอา metadata.tags มาทำ Badge หมวดหมู่
const getTags = (activity: Activity): string[] => {
  const tags = activity.metadata?.tags
  if (Array.isArray(tags)) {
    return tags.map(String).slice(0, 3)
  }
  if (typeof tags === 'string' && tags) {
    return tags
      .split(',')
      .map((t) => t.trim())
      .slice(0, 3)
  }
  return []
}

// 🗓️ วันที่ YYYY-MM-DD → ไทย (15 ตุลาคม 2569) + แสดงสถานะวันนี้/พรุ่งนี้
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
  if (diff === 0) return 'วันนี้'
  if (diff === 1) return 'พรุ่งนี้'
  return date.toLocaleDateString('th-TH', { day: 'numeric', month: 'long', year: 'numeric' })
}

const openActivity = (activity: Activity) => {
  router.push(`/activities/${activity.id}`)
}

const deleteActivity = async (activity: Activity) => {
  if (!canManageActivities.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะผู้ดูแลกิจกรรมเท่านั้น',
      confirmButtonColor: '#1d4ed8',
    })
  const result = await Swal.fire({
    title: 'ลบกิจกรรมนี้ไหม?',
    text: `"${activity.title}" จะถูกลบ (soft delete) พร้อมผู้เข้าร่วมทั้งหมด`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก',
  })
  if (result.isConfirmed) {
    try {
      await ActivityService.deleteActivity(currentRoomId, activity.id, currentUserName)
      Toast.fire({ icon: 'success', title: '🗑️ ลบกิจกรรมเรียบร้อยแล้ว' })
      await fetchData()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'ไม่สามารถลบกิจกรรมได้'
      Swal.fire({
        icon: 'error',
        title: 'ข้อผิดพลาด',
        text: msg,
        confirmButtonColor: '#1d4ed8',
      })
    }
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Classroom Activities"
      title="กิจกรรม & ผู้เข้าร่วม"
      description="บันทึกกิจกรรม หน้าที่ และชั่วโมงจิตอาสาของห้อง"
    >
      <template #actions>
        <router-link v-if="canManageActivities" to="/activities/create" class="btn-primary">
          <i class="bi bi-plus-lg" aria-hidden="true"></i> สร้างกิจกรรม
        </router-link>
      </template>
    </PageHeader>

    <!-- แถบกรองแบบเส้นใต้บาง (ไม่ใช่ปุ่ม pill ทึบสี) -->
    <nav
      class="flex gap-1 overflow-x-auto border-b border-stone-200"
      aria-label="กรองตามสถานะกิจกรรม"
    >
      <button
        v-for="f in ['all', 'upcoming', 'ongoing', 'completed', 'cancelled'] as const"
        :key="f"
        type="button"
        @click="filter = f"
        class="-mb-px shrink-0 border-b-2 px-3 py-2.5 text-sm font-bold transition-colors"
        :class="
          filter === f
            ? 'border-brand-700 text-brand-700'
            : 'border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-900'
        "
      >
        {{ f === 'all' ? 'ทั้งหมด' : ACTIVITY_STATUS_LABELS[f] }}
        <span class="num ms-1 text-[11px] font-bold text-stone-400">{{ statusCount[f] }}</span>
      </button>
    </nav>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-28" />

    <StateBlock v-else-if="hasError" variant="error" @retry="fetchData" />

    <StateBlock
      v-else-if="filteredActivities.length === 0"
      variant="empty"
      icon="bi-calendar-x"
      title="ยังไม่มีกิจกรรมในหมวดนี้"
      hint="สร้างกิจกรรมแรกของห้องเพื่อเริ่มบันทึกผู้เข้าร่วมและชั่วโมงจิตอาสา"
    >
      <router-link v-if="canManageActivities" to="/activities/create" class="btn-primary mt-1.5">
        <i class="bi bi-plus-lg" aria-hidden="true"></i> สร้างกิจกรรมแรก
      </router-link>
    </StateBlock>

    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="activity in filteredActivities"
        :key="activity.id"
        @click="openActivity(activity)"
        class="page-card card-hover flex cursor-pointer flex-col p-4 sm:p-5"
        :class="{ 'opacity-70': activity.status === 'cancelled' }"
      >
        <div class="flex items-start justify-between gap-3">
          <h2 class="min-w-0 flex-1 truncate font-display text-base font-bold text-stone-900">
            {{ activity.title }}
          </h2>
          <span class="chip shrink-0" :class="statusChip(activity.status)">
            {{
              ACTIVITY_STATUS_LABELS[
                typeof activity.status === 'string' ? activity.status : 'upcoming'
              ] || activity.status
            }}
          </span>
        </div>

        <!-- 🏷️ Badge หมวดหมู่จาก metadata.tags -->
        <div v-if="getTags(activity).length" class="mt-2.5 flex flex-wrap gap-1.5">
          <span
            v-for="tag in getTags(activity)"
            :key="tag"
            class="chip bg-stone-100 text-stone-600"
          >
            #{{ tag }}
          </span>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <span class="chip bg-stone-100 text-stone-600">
            <i class="bi bi-calendar-event" aria-hidden="true"></i>
            <span class="num">{{ formatDate(activity.activity_date) }}</span>
          </span>
          <span v-if="activity.base_hours > 0" class="chip bg-emerald-50 text-emerald-700">
            <i class="bi bi-clock-history" aria-hidden="true"></i>
            <span class="num">{{ activity.base_hours }}</span> ชม.
          </span>
        </div>

        <p class="mt-3 line-clamp-3 flex-1 text-sm leading-relaxed text-stone-600">
          {{ activity.description || 'ไม่มีรายละเอียดเพิ่มเติม' }}
        </p>

        <div class="mt-3 flex items-center justify-between gap-2 border-t border-stone-100 pt-3">
          <span class="inline-flex items-center gap-1.5 text-xs font-bold text-stone-500">
            <i class="bi bi-people-fill text-brand-700" aria-hidden="true"></i>
            <span class="num">{{ activity.participant_count }}</span> คน
          </span>
          <div v-if="canManageActivities" class="flex shrink-0 items-center gap-0.5">
            <router-link
              :to="`/activities/${activity.id}/edit`"
              class="flex h-11 w-11 items-center justify-center rounded-xl text-stone-500 transition-colors hover:bg-brand-50 hover:text-brand-700 active:scale-[0.97]"
              title="แก้ไขกิจกรรม"
              aria-label="แก้ไขกิจกรรม"
            >
              <i class="bi bi-pencil-square" aria-hidden="true"></i>
            </router-link>
            <button
              type="button"
              @click.stop="deleteActivity(activity)"
              class="flex h-11 w-11 items-center justify-center rounded-xl text-stone-500 transition-colors hover:bg-red-50 hover:text-red-600 active:scale-[0.97]"
              title="ลบกิจกรรม"
              aria-label="ลบกิจกรรม"
            >
              <i class="bi bi-trash3-fill" aria-hidden="true"></i>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="flex justify-center pt-2">
      <router-link to="/dashboard" class="btn-ghost-ui">
        <i class="bi bi-house" aria-hidden="true"></i> กลับหน้าหลัก
      </router-link>
    </div>
  </div>
</template>
