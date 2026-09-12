<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import Swal from 'sweetalert2'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()
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

const activeTab = ref<'task' | 'note'>('task')
const isSubmitting = ref(false)

// 🛠️ Fix Bug: ฟังก์ชันดึงวันที่ปัจจุบัน (Local Timezone) เพื่อป้องกันวันที่เพี้ยนเป็นเมื่อวานตอนเช้าตรู่ (UTC Bug)
const getLocalDate = (): string => {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  const [datePart] = date.toISOString().split('T')
  return datePart ?? ''
}

const taskForm = reactive({
  task_name: '',
  task_detail: '',
  due_date: getLocalDate()
})

const noteForm = reactive({
  target_date: getLocalDate(),
  bring_items: '',
  announcement: ''
})

const handleAddTask = async () => {
  if (!canManageTasks.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถเพิ่มงานได้', 'error')
  }

  if (!taskForm.task_name) return
  isSubmitting.value = true

  try {
    await TaskService.createTask(currentRoomId, {
      ...taskForm,
      user_name: currentUserName
    })
    await Swal.fire({
      icon: 'success',
      title: 'เพิ่มงานเรียบร้อยแล้ว!',
      timer: 1500,
      showConfirmButton: false,
      confirmButtonColor: '#1d4ed8'
    })
    router.push('/tasks')
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถเพิ่มงานได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const handleAddNote = async () => {
  if (!canManageTasks.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถเพิ่มประกาศได้', 'error')
  }

  if (!noteForm.target_date) return
  isSubmitting.value = true

  try {
    await TaskService.createDailyNote(currentRoomId, {
      ...noteForm,
      user_name: currentUserName
    })
    await Swal.fire({
      icon: 'success',
      title: `บันทึกโน้ตสำหรับวันที่ ${noteForm.target_date} เรียบร้อย!`,
      timer: 1500,
      showConfirmButton: false,
      confirmButtonColor: '#1d4ed8'
    })
    router.push('/tasks')
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถเพิ่มโน้ตได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="New Entry"
      title="สร้างรายการใหม่"
      description="เพิ่มการบ้าน ชิ้นงาน หรือโน้ตประกาศรายวัน"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" @click="router.push('/tasks')">
          <i class="bi bi-arrow-left" aria-hidden="true" />
          ย้อนกลับ
        </button>
      </template>
    </PageHeader>

    <div class="page-card overflow-hidden">
      <!-- สลับฟอร์ม: งาน / โน้ต -->
      <div class="border-b border-stone-100 p-1.5">
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="activeTab === 'task' ? 'bg-brand-700 text-white' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'"
            @click="activeTab = 'task'"
          >
            <i class="bi bi-journal-plus text-base" aria-hidden="true"></i>
            งาน / การบ้าน
          </button>
          <button
            type="button"
            class="flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="activeTab === 'note' ? 'bg-brand-700 text-white' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'"
            @click="activeTab = 'note'"
          >
            <i class="bi bi-sticky text-base" aria-hidden="true"></i>
            โน้ต / ประกาศ
          </button>
        </div>
      </div>

      <div class="p-5 sm:p-6">
        <form v-if="activeTab === 'task'" class="space-y-4" @submit.prevent="handleAddTask">
          <div>
            <label class="field-label" for="taskName">
              ชื่องาน <span class="text-red-600">*</span>
            </label>
            <input
              id="taskName"
              :disabled="!canManageTasks"
              v-model="taskForm.task_name"
              type="text"
              class="field"
              placeholder="เช่น การบ้านคณิตศาสตร์ หน้า 45"
              required
            />
          </div>

          <div>
            <label class="field-label" for="taskDetail">รายละเอียด</label>
            <textarea
              id="taskDetail"
              :disabled="!canManageTasks"
              v-model="taskForm.task_detail"
              class="field h-32 resize-none"
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
              v-model="taskForm.due_date"
              type="date"
              class="field"
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
                <template v-else><i class="bi bi-plus-lg" aria-hidden="true" /> บันทึกงานใหม่</template>
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 py-3 text-sm font-bold text-stone-500"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะแอดมิน
            </div>
          </div>
        </form>

        <form v-else class="space-y-4" @submit.prevent="handleAddNote">
          <div>
            <label class="field-label" for="noteDate">
              วันที่เป้าหมาย <span class="text-red-600">*</span>
            </label>
            <input
              id="noteDate"
              :disabled="!canManageTasks"
              v-model="noteForm.target_date"
              type="date"
              class="field"
              required
            />
          </div>

          <div>
            <label class="field-label" for="noteBringItems">สิ่งที่ต้องเตรียม</label>
            <input
              id="noteBringItems"
              :disabled="!canManageTasks"
              v-model="noteForm.bring_items"
              type="text"
              class="field"
              placeholder="เช่น สีไม้, อุปกรณ์พละ (ถ้าไม่มีให้เว้นว่างไว้)"
            />
          </div>

          <div>
            <label class="field-label" for="noteAnnouncement">ประกาศ / หมายเหตุ</label>
            <textarea
              id="noteAnnouncement"
              :disabled="!canManageTasks"
              v-model="noteForm.announcement"
              class="field h-32 resize-none"
              placeholder="ประกาศแจ้งเตือนเพื่อนๆ ในห้อง... (ถ้าไม่มีให้เว้นว่างไว้)"
            ></textarea>
          </div>

          <div class="flex border-t border-stone-100 pt-4 sm:justify-end">
            <template v-if="canManageTasks">
              <button type="submit" class="btn-primary w-full sm:w-auto" :disabled="isSubmitting">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                <template v-else><i class="bi bi-plus-lg" aria-hidden="true" /> บันทึกโน้ต/ประกาศ</template>
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 py-3 text-sm font-bold text-stone-500"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะแอดมิน
            </div>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
