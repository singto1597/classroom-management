<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import type { Activity } from '@/types/activity'
import ActivityForm from '@/components/activities/ActivityForm.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const activityId = Number(route.params.id)

const isLoading = ref(true)
const activity = ref<Activity | null>(null)

onMounted(async () => {
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
})
</script>

<template>
  <div>
    <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
      <p class="text-slate-400 font-medium animate-pulse">กำลังโหลดกิจกรรม...</p>
    </div>
    <ActivityForm
      v-else-if="activity"
      mode="edit"
      :initial-activity="activity"
      @saved="(id: number) => router.push(`/activities/${id || activityId}`)"
    />
  </div>
</template>
