<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import Swal from 'sweetalert2'
import PageHeader from '@/components/ui/PageHeader.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// ดึงข้อความ error จาก backend แบบปลอดภัย (catch ได้ unknown) — คงรูปแบบเดิมของโปรเจค
// ที่อ่าน detail จาก response ของ axios ไว้
const apiErrorDetail = (error: unknown): string | undefined => {
  if (!isAxiosError<{ detail?: unknown }>(error)) return undefined
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : undefined
}

// --- ถอด Mock Data เปลี่ยนมาดึงจาก Store ---
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

// สิทธิ์: แอดมิน หรือผู้ที่มี permission จัดการงาน/ตาราง
const canManageTasks = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_TASKS')
)

const taskId = Number(route.params.id)

const isLoading = ref(true)
const isSubmitting = ref(false)

const form = reactive({
  task_name: '',
  task_detail: '',
  due_date: ''
})

const fetchTask = async () => {
  try {
    const task = await TaskService.getTaskById(currentRoomId, taskId)
    form.task_name = task.task_name
    form.task_detail = task.task_detail || ''
    form.due_date = task.due_date
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถโหลดข้อมูลงานได้', 'error')
    router.push('/tasks')
  } finally {
    isLoading.value = false
  }
}

const handleUpdateTask = async () => {
  if (!canManageTasks.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถแก้ไขงานได้', 'error')
  }

  if (!form.task_name) return
  isSubmitting.value = true

  try {
    await TaskService.updateTask(currentRoomId, taskId, {
      ...form,
      user_name: currentUserName
    })
    await Swal.fire({
      icon: 'success',
      title: 'แก้ไขงานเรียบร้อย!',
      timer: 1500,
      showConfirmButton: false,
      confirmButtonColor: '#1d4ed8'
    })
    router.push('/tasks')
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถอัปเดตงานได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}

onMounted(fetchTask)
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Edit Entry"
      title="แก้ไขข้อมูลงาน"
      description="อัปเดตรายละเอียด หรือเลื่อนกำหนดส่งของการบ้าน"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" @click="router.push('/tasks')">
          <i class="bi bi-arrow-left" aria-hidden="true" />
          ย้อนกลับ
        </button>
      </template>
    </PageHeader>

    <div class="page-card overflow-hidden">
      <!-- หัวการ์ด: ระบุรหัสงานที่กำลังแก้ -->
      <div class="flex items-center gap-3 border-b border-stone-100 px-5 py-4">
        <div
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
        >
          <i class="bi bi-pencil-square" aria-hidden="true"></i>
        </div>
        <div class="min-w-0">
          <p class="truncate font-display text-base font-bold text-stone-900">ฟอร์มแก้ไขงาน</p>
          <p class="text-xs text-stone-500">รหัสงาน <span class="num">#{{ taskId }}</span></p>
        </div>
      </div>

      <div class="p-5 sm:p-6">
        <SkeletonRows v-if="isLoading" :rows="3" height="h-14" />

        <form v-else class="space-y-4" @submit.prevent="handleUpdateTask">
          <div>
            <label class="field-label" for="taskName">
              ชื่องาน <span class="text-red-600">*</span>
            </label>
            <input
              id="taskName"
              :disabled="!canManageTasks"
              v-model="form.task_name"
              type="text"
              class="field disabled:cursor-not-allowed"
              required
            />
          </div>

          <div>
            <label class="field-label" for="taskDetail">รายละเอียด</label>
            <textarea
              id="taskDetail"
              :disabled="!canManageTasks"
              v-model="form.task_detail"
              class="field h-32 resize-none disabled:cursor-not-allowed"
              placeholder="อธิบายรายละเอียดงาน, ขั้นตอนการทำ, หรือแนบลิงก์ที่เกี่ยวข้อง..."
            ></textarea>
          </div>

          <div>
            <label class="field-label" for="taskDueDate">
              กำหนดส่ง <span class="text-red-600">*</span>
            </label>
            <input
              id="taskDueDate"
              :disabled="!canManageTasks"
              v-model="form.due_date"
              type="date"
              class="field disabled:cursor-not-allowed"
              required
            />
          </div>

          <div class="flex border-t border-stone-100 pt-4 sm:justify-end">
            <template v-if="canManageTasks">
              <button type="submit" class="btn-primary w-full sm:w-auto" :disabled="isSubmitting">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                <template v-else><i class="bi bi-save-fill" aria-hidden="true" /> บันทึกการแก้ไข</template>
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 py-3 text-sm font-bold text-stone-500"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะผู้ดูแลเท่านั้นที่แก้ไขได้
            </div>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
