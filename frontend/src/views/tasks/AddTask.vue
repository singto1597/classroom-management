<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import { todayIso } from '@/utils/datetime'
import AppTabs from '@/components/ui/AppTabs.vue'
import PageIntro from '@/components/ui/PageIntro.vue'
import FormSuccess from '@/components/ui/FormSuccess.vue'
import { useDialog } from '@/composables/useDialog'
import { confirmLeave, useFormDraft, useUnsavedGuard } from '@/composables/useFormDraft'

const authStore = useAuthStore()
const dialog = useDialog()

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
const tabs = [
  { value: 'task', label: 'งาน / การบ้าน' },
  { value: 'note', label: 'โน้ต / ประกาศ' },
] as const
const setTab = (value: string) => {
  activeTab.value = value === 'note' ? 'note' : 'task'
}
const isSubmitting = ref(false)
const showErrors = ref(false)
// แตะแล้วแต่ยังไม่กรอก → แสดงข้อความทันที (ปุ่มบันทึกถูก disable ตั้งแต่แรก)
const touchedName = ref(false)
const touchedDue = ref(false)
const touchedNoteDate = ref(false)
const submitted = ref<{ title: string; hint: string } | null>(null)

const taskForm = reactive({
  task_name: '',
  task_detail: '',
  // 🗓️ ค่าเริ่มต้น = "วันนี้" ตามเวลาไทย ไม่ใช่ปฏิทินของอุปกรณ์ผู้ใช้
  //    เดิมใช้ getLocalDate() ที่คิดจาก timezone ของเครื่อง (แก้ UTC Bug ได้เฉพาะเครื่อง
  //    ที่ตั้ง TZ เป็นไทย) ⇒ เครื่องที่ตั้ง TZ ตามหลังไทย เช่น UTC-5 เปิดตอนเช้าตามเวลาไทย
  //    จะได้ "เมื่อวาน" ⇒ งานกลายเป็นเลยกำหนดทันทีที่สร้าง
  //    ใช้ todayIso() จาก utils/datetime เพื่อให้มีแหล่งความจริงเดียวเรื่องโซนเวลา
  due_date: todayIso(),
})

const noteForm = reactive({
  target_date: todayIso(),
  bring_items: '',
  announcement: '',
})

// 📝 ร่างแยกตามแท็บ — สลับแท็บแล้วงานที่พิมพ์ค้างไม่หาย และไม่ปนกัน
const taskDraft = useFormDraft(
  taskForm,
  () => `cls:draft:add-task:${currentRoomId}:task`,
  () => activeTab.value === 'task' && canManageTasks.value
)
const noteDraft = useFormDraft(
  noteForm,
  () => `cls:draft:add-task:${currentRoomId}:note`,
  () => activeTab.value === 'note' && canManageTasks.value
)

onMounted(() => {
  taskDraft.restore()
  noteDraft.restore()
})

const taskNameError = computed(() => (taskForm.task_name.trim() ? '' : 'กรุณากรอกชื่องาน'))
const dueDateError = computed(() => (taskForm.due_date ? '' : 'กรุณาเลือกกำหนดส่ง'))
const noteDateError = computed(() => (noteForm.target_date ? '' : 'กรุณาเลือกวันที่'))

const taskValid = computed(() => !taskNameError.value && !dueDateError.value)
const noteValid = computed(() => !noteDateError.value)

const isDirty = () => {
  if (submitted.value) return false
  if (activeTab.value === 'task') {
    return (
      taskForm.task_name.trim() !== '' ||
      taskForm.task_detail.trim() !== '' ||
      taskForm.due_date !== todayIso()
    )
  }
  return (
    noteForm.bring_items.trim() !== '' ||
    noteForm.announcement.trim() !== '' ||
    noteForm.target_date !== todayIso()
  )
}

useUnsavedGuard(isDirty)
onBeforeRouteLeave(() => confirmLeave(isDirty))

const resetTask = () => {
  taskForm.task_name = ''
  taskForm.task_detail = ''
  taskForm.due_date = todayIso()
  showErrors.value = false
  taskDraft.clear()
}

const resetNote = () => {
  noteForm.target_date = todayIso()
  noteForm.bring_items = ''
  noteForm.announcement = ''
  showErrors.value = false
  noteDraft.clear()
}

const handleAddTask = async () => {
  if (!canManageTasks.value) {
    return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถเพิ่มงานได้', 'error')
  }

  if (!taskValid.value) {
    showErrors.value = true
    return
  }

  isSubmitting.value = true
  try {
    await TaskService.createTask(currentRoomId, {
      ...taskForm,
      task_name: taskForm.task_name.trim(),
      task_detail: taskForm.task_detail.trim(),
      user_name: currentUserName,
    })
    // ✅ แสดงผลค้างบนจอ แทน Swal ที่ปิดเองใน 1.5 วิ — ผู้ใช้เลือกได้ว่าจะไปต่อหรือสร้างอีก
    submitted.value = {
      title: 'เพิ่มงานเรียบร้อยแล้ว',
      hint: `"${taskForm.task_name.trim()}" กำหนดส่ง ${taskForm.due_date} — ปรากฏในรายการงานของห้องแล้ว`,
    }
    taskDraft.clear()
  } catch (error: unknown) {
    void dialog.alert('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถเพิ่มงานได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const handleAddNote = async () => {
  if (!canManageTasks.value) {
    return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถเพิ่มประกาศได้', 'error')
  }

  if (!noteValid.value) {
    showErrors.value = true
    return
  }

  isSubmitting.value = true
  try {
    await TaskService.createDailyNote(currentRoomId, {
      ...noteForm,
      bring_items: noteForm.bring_items.trim(),
      announcement: noteForm.announcement.trim(),
      user_name: currentUserName,
    })
    submitted.value = {
      title: 'บันทึกโน้ตเรียบร้อยแล้ว',
      hint: `โน้ตสำหรับวันที่ ${noteForm.target_date} ถูกเพิ่มในรายการแล้ว`,
    }
    noteDraft.clear()
  } catch (error: unknown) {
    void dialog.alert('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถเพิ่มโน้ตได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      :description="
        activeTab === 'task'
          ? 'เพิ่มงานพร้อมกำหนดส่งให้สมาชิกในห้อง'
          : 'บันทึกโน้ตหรือประกาศสั้น ๆ ให้สมาชิกเห็นบนหน้าแรก'
      "
    />

    <!-- ✅ ผลลัพธ์ค้างบนจอ พร้อมทางไปต่อ -->
    <FormSuccess v-if="submitted" :title="submitted.title" :hint="submitted.hint">
      <RouterLink to="/tasks" class="btn-primary">
        <i class="bi bi-list-ul" aria-hidden="true" /> ดูรายการงาน
      </RouterLink>
      <button
        type="button"
        class="btn-ghost-ui"
        @click="
          () => {
            submitted = null
            if (activeTab === 'task') resetTask()
            else resetNote()
          }
        "
      >
        <i class="bi bi-plus-lg" aria-hidden="true" />
        {{ activeTab === 'task' ? 'สร้างงานอีก' : 'บันทึกโน้ตอีก' }}
      </button>
    </FormSuccess>

    <div v-else class="page-card overflow-hidden">
      <!-- สลับฟอร์ม: งาน / โน้ต -->
      <div class="border-b border-line p-3 sm:px-6">
        <AppTabs
          :model-value="activeTab"
          :tabs="tabs"
          group-label="ประเภทที่ต้องการเพิ่ม"
          variant="segmented"
          @update:model-value="setTab"
        />
      </div>

      <div class="p-4 sm:p-6">
        <form v-if="activeTab === 'task'" class="space-y-4" @submit.prevent="handleAddTask">
          <div>
            <label class="field-label" for="taskName">
              ชื่องาน <span class="text-danger-600">*</span>
            </label>
            <input
              id="taskName"
              :disabled="!canManageTasks"
              v-model="taskForm.task_name"
              type="text"
              class="field"
              placeholder="เช่น การบ้านคณิตศาสตร์ หน้า 45"
              :aria-invalid="(showErrors || touchedName) && !!taskNameError"
              :aria-describedby="(showErrors || touchedName) && taskNameError ? 'taskNameError' : undefined"
              @blur="touchedName = true"
            />
            <p v-if="(showErrors || touchedName) && taskNameError" id="taskNameError" class="mt-1 text-xs font-bold text-danger-600">
              {{ taskNameError }}
            </p>
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
              กำหนดส่ง <span class="text-danger-600">*</span>
            </label>
            <input
              id="taskDueDate"
              :disabled="!canManageTasks"
              v-model="taskForm.due_date"
              type="date"
              class="field"
              :aria-invalid="(showErrors || touchedDue) && !!dueDateError"
              :aria-describedby="(showErrors || touchedDue) && dueDateError ? 'taskDueDateError' : undefined"
              @blur="touchedDue = true"
            />
            <p v-if="(showErrors || touchedDue) && dueDateError" id="taskDueDateError" class="mt-1 text-xs font-bold text-danger-600">
              {{ dueDateError }}
            </p>
          </div>

          <div class="flex flex-col-reverse gap-2 border-t border-line pt-3 sm:flex-row sm:justify-end sm:pt-4">
            <template v-if="canManageTasks">
              <RouterLink to="/tasks" class="btn-ghost-ui">ยกเลิก</RouterLink>
              <button type="submit" class="btn-primary w-full sm:w-auto" :disabled="isSubmitting || !taskValid">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                <template v-else><i class="bi bi-plus-lg" aria-hidden="true" /> บันทึกงานใหม่</template>
              </button>
            </template>
            <p
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-control bg-canvas py-2.5 text-sm font-bold text-ink-3"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะแอดมิน
            </p>
          </div>
        </form>

        <form v-else class="space-y-4" @submit.prevent="handleAddNote">
          <div>
            <label class="field-label" for="noteDate">
              วันที่เป้าหมาย <span class="text-danger-600">*</span>
            </label>
            <input
              id="noteDate"
              :disabled="!canManageTasks"
              v-model="noteForm.target_date"
              type="date"
              class="field"
              :aria-invalid="(showErrors || touchedNoteDate) && !!noteDateError"
              :aria-describedby="(showErrors || touchedNoteDate) && noteDateError ? 'noteDateError' : undefined"
              @blur="touchedNoteDate = true"
            />
            <p v-if="(showErrors || touchedNoteDate) && noteDateError" id="noteDateError" class="mt-1 text-xs font-bold text-danger-600">
              {{ noteDateError }}
            </p>
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

          <div class="flex flex-col-reverse gap-2 border-t border-line pt-3 sm:flex-row sm:justify-end sm:pt-4">
            <template v-if="canManageTasks">
              <RouterLink to="/tasks" class="btn-ghost-ui">ยกเลิก</RouterLink>
              <button type="submit" class="btn-primary w-full sm:w-auto" :disabled="isSubmitting || !noteValid">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                <template v-else><i class="bi bi-plus-lg" aria-hidden="true" /> บันทึกโน้ต/ประกาศ</template>
              </button>
            </template>
            <p
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-control bg-canvas py-2.5 text-sm font-bold text-ink-3"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะแอดมิน
            </p>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
