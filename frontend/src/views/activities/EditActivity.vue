<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import type { Activity } from '@/types/activity'
import ActivityForm from '@/components/activities/ActivityForm.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const activityId = Number(route.params.id)

const isLoading = ref(true)
const activity = ref<Activity | null>(null)

const load = async () => {
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

onMounted(load)
</script>

<template>
  <!-- Wrapper เท่านั้น — หัวหน้า/ฟอร์มอยู่ใน ActivityForm -->
  <div class="space-y-4 sm:space-y-5">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />
    <ActivityForm
      v-else-if="activity"
      mode="edit"
      :initial-activity="activity"
      @saved="(id: number) => router.push(`/activities/${id || activityId}`)"
    />
    <StateBlock
      v-else
      variant="error"
      title="โหลดข้อมูลกิจกรรมไม่สำเร็จ"
      hint="ตรวจการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
      @retry="load"
    />
  </div>
</template>
