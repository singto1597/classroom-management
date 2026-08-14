<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import type { Activity } from '@/types/activity'
import { ACTIVITY_STATUS_LABELS, ACTIVITY_STATUS_BADGE } from '@/types/activity'
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
const filter = ref<StatusFilter>('all')

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

const fetchData = async () => {
  isLoading.value = true
  try {
    activities.value = await ActivityService.getActivities(currentRoomId)
  } catch (error: any) {
    Toast.fire({ icon: 'error', title: error?.message || 'ดึงข้อมูลกิจกรรมไม่สำเร็จ' })
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
    return new Date(a.activity_date + 'T00:00:00').getTime() - new Date(b.activity_date + 'T00:00:00').getTime()
  })
})

type StatusFilter = 'all' | 'upcoming' | 'ongoing' | 'completed' | 'cancelled'

const statusCount = computed(() => {
  const counts: Record<StatusFilter, number> = { all: activities.value.length, upcoming: 0, ongoing: 0, completed: 0, cancelled: 0 }
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
    return tags.split(',').map((t) => t.trim()).slice(0, 3)
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
  if (!canManageActivities.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลกิจกรรมเท่านั้น', 'error')
  const result = await Swal.fire({
    title: 'ลบกิจกรรมนี้ไหม?',
    text: `"${activity.title}" จะถูกลบ (soft delete) พร้อมผู้เข้าร่วมทั้งหมด`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#e11d48',
    cancelButtonColor: '#94a3b8',
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก',
  })
  if (result.isConfirmed) {
    try {
      await ActivityService.deleteActivity(currentRoomId, activity.id, currentUserName)
      Toast.fire({ icon: 'success', title: '🗑️ ลบกิจกรรมเรียบร้อยแล้ว' })
      await fetchData()
    } catch (error: any) {
      Swal.fire('ข้อผิดพลาด', error?.message || 'ไม่สามารถลบกิจกรรมได้', 'error')
    }
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-6xl mx-auto">
      <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center mb-5 md:mb-8 gap-4">
        <div class="w-full lg:w-auto">
          <h3 class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-2.5">
            <div class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0">
              <i class="bi bi-calendar-heart-fill"></i>
            </div>
            กิจกรรม & ผู้เข้าร่วม
          </h3>
          <p class="text-slate-500 mt-1.5 ml-1 text-sm md:text-base">บันทึกกิจกรรม หน้าที่ และชั่วโมงจิตอาสาของห้อง</p>
        </div>

        <div class="flex flex-col sm:flex-row items-center gap-3 w-full lg:w-auto">
          <div class="bg-slate-200/60 p-1.5 rounded-2xl flex flex-nowrap items-center gap-1 shadow-inner backdrop-blur-sm w-full sm:w-auto overflow-x-auto">
            <button
              v-for="f in (['all', 'upcoming', 'ongoing', 'completed', 'cancelled'] as const)"
              :key="f"
              @click="filter = f"
              :class="filter === f ? 'bg-white text-violet-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'"
              class="flex-1 sm:flex-none px-3.5 sm:px-4 py-2 rounded-xl text-sm font-bold transition-all duration-300 whitespace-nowrap text-center inline-flex items-center justify-center gap-1.5"
            >
              {{ f === 'all' ? 'ทั้งหมด' : ACTIVITY_STATUS_LABELS[f] }}
              <span class="px-1.5 py-0.5 rounded-full text-[10px] font-black" :class="filter === f ? 'bg-violet-100 text-violet-600' : 'bg-slate-300/50 text-slate-600'">{{ statusCount[f] }}</span>
            </button>
          </div>

          <router-link
            v-if="canManageActivities"
            to="/activities/create"
            class="w-full sm:w-auto px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white font-bold rounded-xl shadow-lg shadow-violet-600/20 transition-all flex items-center justify-center gap-2 whitespace-nowrap"
          >
            <i class="bi bi-plus-lg"></i> สร้างกิจกรรม
          </router-link>
        </div>
      </div>

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังดึงข้อมูลกิจกรรม...</p>
      </div>

      <div v-else-if="filteredActivities.length === 0" class="flex flex-col items-center justify-center py-20 md:py-24 bg-white rounded-[2rem] shadow-sm border border-slate-100 px-4 text-center">
        <div class="w-20 h-20 md:w-24 md:h-24 bg-slate-50 rounded-full flex items-center justify-center mb-6">
          <i class="bi bi-calendar-x text-3xl md:text-4xl text-slate-300"></i>
        </div>
        <h4 class="text-lg md:text-xl font-bold text-slate-700 mb-2">ยังไม่มีกิจกรรมในหมวดนี้</h4>
        <p class="text-sm md:text-base text-slate-400">สร้างกิจกรรมแรกของห้องเลย! 🎪</p>
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 md:gap-6">
        <div
          v-for="activity in filteredActivities"
          :key="activity.id"
          @click="openActivity(activity)"
          class="group cursor-pointer bg-white rounded-3xl p-4 md:p-5 shadow-[0_4px_20px_rgb(0,0,0,0.03)] border border-slate-100 hover:shadow-lg hover:-translate-y-1 transition-all duration-300 flex flex-col"
          :class="{ 'opacity-70 grayscale-[0.2]': activity.status === 'cancelled' }"
        >
          <div class="flex flex-col sm:flex-row sm:justify-between sm:items-start mb-3 gap-2 sm:gap-4">
            <h5 class="text-lg font-bold text-slate-800 leading-tight flex-grow">{{ activity.title }}</h5>
            <span
              class="px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider whitespace-nowrap inline-block border"
              :class="ACTIVITY_STATUS_BADGE[typeof activity.status === 'string' ? activity.status : 'upcoming'] || ACTIVITY_STATUS_BADGE.upcoming"
            >
              {{ ACTIVITY_STATUS_LABELS[typeof activity.status === 'string' ? activity.status : 'upcoming'] || activity.status }}
            </span>
          </div>

          <!-- 🏷️ Badge หมวดหมู่จาก metadata.tags -->
          <div v-if="getTags(activity).length" class="flex flex-wrap gap-1.5 mb-3">
            <span
              v-for="tag in getTags(activity)"
              :key="tag"
              class="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-violet-50 text-violet-600 border border-violet-100"
            >
              #{{ tag }}
            </span>
          </div>

          <div class="flex flex-wrap items-center gap-2 text-slate-500 text-xs font-semibold mb-3">
            <span class="bg-slate-50 w-fit px-3 py-1.5 rounded-lg border border-slate-100 inline-flex items-center gap-1.5">
              <i class="bi bi-calendar-event text-violet-500"></i> {{ formatDate(activity.activity_date) }}
            </span>
            <span v-if="activity.base_hours > 0" class="bg-emerald-50 w-fit px-3 py-1.5 rounded-lg border border-emerald-100 inline-flex items-center gap-1.5 text-emerald-600">
              <i class="bi bi-clock-history"></i> {{ activity.base_hours }} ชม.
            </span>
          </div>

          <p class="text-slate-600 text-sm mb-4 whitespace-pre-wrap leading-relaxed flex-grow">
            {{ activity.description || 'ไม่มีรายละเอียดเพิ่มเติม' }}
          </p>

          <div class="flex justify-between items-center mt-auto pt-3 border-t border-slate-100">
            <span class="inline-flex items-center gap-1.5 text-xs font-bold text-slate-500">
              <i class="bi bi-people-fill text-violet-500"></i> {{ activity.participant_count }} คน
            </span>
            <div v-if="canManageActivities" class="flex gap-2">
              <router-link
                :to="`/activities/${activity.id}/edit`"
                class="w-10 h-10 sm:w-9 sm:h-9 rounded-full flex items-center justify-center text-slate-400 bg-slate-50 hover:bg-violet-50 hover:text-violet-600 transition-colors"
                title="แก้ไขกิจกรรม"
              >
                <i class="bi bi-pencil-square"></i>
              </router-link>
              <button
                @click.stop="deleteActivity(activity)"
                class="w-10 h-10 sm:w-9 sm:h-9 rounded-full flex items-center justify-center text-slate-400 bg-slate-50 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                title="ลบกิจกรรม"
              >
                <i class="bi bi-trash3-fill"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="mt-10 md:mt-12 flex flex-col sm:flex-row justify-center items-center gap-4">
        <router-link to="/dashboard" class="w-full sm:w-auto px-8 py-3 md:py-3.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 font-bold rounded-2xl transition-all flex items-center justify-center gap-2">
          <i class="bi bi-house"></i> กลับหน้าหลัก
        </router-link>
      </div>
    </div>
  </div>
</template>
