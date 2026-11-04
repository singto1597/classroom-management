<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import type { Task, DailyNote } from '@/types/task'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import RowActionMenu from '@/components/ui/RowActionMenu.vue'
import AppTabs from '@/components/ui/AppTabs.vue'
import type { AppTabItem } from '@/components/ui/AppTabs.vue'
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue'
import { useDialog } from '@/composables/useDialog'
import { TASK_STATUS_LABELS } from '@/constants/statusLabels'
import { daysFromThaiToday, formatThaiDate, relativeThaiDay, todayIso } from '@/utils/datetime'

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

const tasks = ref<Task[]>([])
const notes = ref<DailyNote[]>([])
const isLoading = ref(true)

/**
 * 🎯 ตัวกรองเริ่มต้นอ่านจาก query ได้ (`/tasks?filter=all`)
 * เหตุผล: การ์ด KPI บน Dashboard กดแล้วต้องพาไปเจอ "จำนวนเดียวกัน"
 * (กฎ P1.10 — "34 กดแล้วเจอ 5" คือบั๊ก) ⇒ การ์ดงานทั้งหมด/งานค้างส่ง filter มาชัดเจน
 * ไม่พึ่งค่าเริ่มต้นของหน้านี้ ซึ่งวันหนึ่งอาจเปลี่ยนได้โดยไม่มีใครสังเกต
 * ค่าที่ไม่รู้จักถูกเมิน (fail-closed) กลับไปใช้ `pending`
 */
const FILTER_VALUES = ['all', 'pending', 'done'] as const
type TaskFilter = (typeof FILTER_VALUES)[number]

const parseFilter = (value: unknown): TaskFilter =>
  typeof value === 'string' && (FILTER_VALUES as readonly string[]).includes(value)
    ? (value as TaskFilter)
    : 'pending'

/**
 * 📅 ตัวกรอง "ตามกำหนดส่ง" — มาจากการ์ด "ครบกำหนดวันนี้"/"เลยกำหนด" บนหน้าหลัก
 *
 * 🔑 predicate ต้อง **เหมือน `home_summary_service._load_tasks` คำต่อคำ**:
 *    `status='pending' AND due_date = today` / `due_date < today` (วันที่ไทย)
 *    ⇒ ตัวเลขบนการ์ด = จำนวนแถวที่กรองได้ที่นี่เสมอ ไม่ใช่ "34 กดแล้วเจอ 5"
 */
type TaskDueFilter = 'today' | 'overdue'

const parseDueFilter = (value: unknown): TaskDueFilter | null =>
  value === 'today' || value === 'overdue' ? value : null

const route = useRoute()
const router = useRouter()
const initialDue = parseDueFilter(route.query.filter)
const dueFilter = ref<TaskDueFilter | null>(initialDue)
// ตัวกรองกำหนดส่งเป็น "มุมมองของงานค้าง" ⇒ สถานะต้องเป็น pending เสมอ
const filter = ref<TaskFilter>(initialDue ? 'pending' : parseFilter(route.query.filter))

/**
 * 🔁 เปลี่ยน query ระหว่างอยู่หน้าเดิม (เช่นกดการ์ดอีกใบจากหน้าหลักผ่าน back/forward)
 *    Vue Router ไม่ remount component ⇒ ต้องอ่าน query ใหม่เอง ไม่งั้นตัวกรองค้างของเก่า
 */
watch(
  () => route.query.filter,
  (raw) => {
    const due = parseDueFilter(raw)
    dueFilter.value = due
    filter.value = due ? 'pending' : parseFilter(raw)
  }
)

// สถานะผิดพลาด — เดิมแจ้งด้วย toast อย่างเดียว ตอนนี้ใช้โชว์ StateBlock ด้วย
const hasError = ref(false)

const fetchData = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    const [tasksResult, notesResult] = await Promise.allSettled([
      TaskService.getAllTasks(currentRoomId),
      TaskService.getDailyNotes(currentRoomId)
    ])

    if (tasksResult.status === 'fulfilled') {
      tasks.value = tasksResult.value as Task[]
    } else {
      hasError.value = true
      dialog.notify('ดึงข้อมูลงานไม่สำเร็จ', 'error')
    }

    if (notesResult.status === 'fulfilled') {
      notes.value = notesResult.value as DailyNote[]
    } else {
      notes.value = []
    }
  } finally {
    isLoading.value = false
  }
}

const pendingCount = computed(() => tasks.value.filter(task => task.status === 'pending').length)
const doneCount = computed(() => tasks.value.filter(task => task.status === 'done').length)

// แท็บกรองใช้ AppTabs กลาง — จำนวนในป้ายคือจำนวนจริงหลังกรอง ไม่ใช่ตัวเลขหลอก
const filterTabs = computed<AppTabItem[]>(() => [
  { value: 'pending', label: TASK_STATUS_LABELS.pending, count: pendingCount.value },
  { value: 'done', label: TASK_STATUS_LABELS.done, count: doneCount.value },
  { value: 'all', label: 'ทั้งหมด', count: tasks.value.length },
])

const setFilter = (value: string) => {
  if (value === 'all' || value === 'pending' || value === 'done') filter.value = value
  // เลือกสถานะเอง = ออกจากมุมมองกำหนดส่ง (สองตัวกรองซ้อนกันจะอ่านยากและตัวเลขไม่ตรง)
  dueFilter.value = null
}

/** ป้ายชื่อของตัวกรองกำหนดส่งที่กำลังใช้ (ใช้ทั้งในชิปและข้อความ empty) */
const dueFilterLabel = computed(() =>
  dueFilter.value === 'today' ? 'ครบกำหนดวันนี้' : dueFilter.value === 'overdue' ? 'เลยกำหนดแล้ว' : null
)

const clearDueFilter = () => {
  dueFilter.value = null
  filter.value = 'pending'
  // ล้างใน URL ด้วย เพื่อให้ refresh/แชร์ลิงก์แล้วเห็นเหมือนกัน
  void router.replace({ query: { ...route.query, filter: 'pending' } })
}

// 🗓️ คำนวณจำนวนวันห่างจาก "วันนี้ตามเวลาไทย" — ไม่ใช้ปฏิทินของอุปกรณ์
const diffDaysFromToday = (dateStr: string): number => daysFromThaiToday(dateStr) ?? 0;

// 🗓️ วันที่ YYYY-MM-DD → ไทย (เช่น 5 ส.ค. 2569) และโชว์ว่าวันนี้/พรุ่งนี้
const formatDueDate = (dateStr: string): string => {
  if (!dateStr) return '-';
  return relativeThaiDay(dateStr) ?? formatThaiDate(dateStr);
};

const filteredTasks = computed(() => {
  let result = tasks.value
  if (filter.value !== 'all') {
    result = result.filter(task => task.status === filter.value)
  }
  // 📅 วันที่เทียบแบบ ISO string (YYYY-MM-DD) — เรียงตรงกันตามตัวอักษรโดยไม่ต้องแปลง Date
  if (dueFilter.value) {
    const today = todayIso()
    result = result.filter(task =>
      dueFilter.value === 'today' ? task.due_date === today : task.due_date < today
    )
  }
  return [...result].sort((a, b) => {
    // แท็บ "ทั้งหมด": งานที่ยังไม่เสร็จขึ้นก่อนเสมอ (ไม่ให้จมอยู่ข้างล่าง)
    if (filter.value === 'all' && a.status !== b.status) {
      return a.status === 'pending' ? -1 : 1
    }
    // เรียงตามกำหนดส่ง (ใกล้ก่อน) ทั้งในหมวดที่ยังทำและที่เสร็จแล้ว
    return new Date(a.due_date).getTime() - new Date(b.due_date).getTime()
  })
})

// 🚪 ว่างเพราะ "ยังไม่มีงาน" กับ "กรองแล้วไม่เจอ" คนละเรื่อง
// เดิมใช้ข้อความเดียว ⇒ ห้องที่มีแต่งานเสร็จแล้วเห็น "ยังไม่มีงานในหมวดหมู่นี้เลย"
const emptyState = computed(() => {
  if (tasks.value.length === 0) {
    return {
      filteredOut: false,
      title: 'ยังไม่มีงานในห้องนี้',
      hint: 'เพิ่มงานแรกเพื่อเริ่มต้นติดตามการบ้านและการประกาศ',
    }
  }

  // มุมมองตามกำหนดส่งมีข้อความของตัวเอง — "ไม่มีงานสถานะ ..." จะชี้ผิดสาเหตุ
  if (dueFilter.value === 'today') {
    return {
      filteredOut: true,
      title: 'ไม่มีงานที่ครบกำหนดวันนี้',
      hint: 'งานที่เลยกำหนดแล้วหรือยังไม่ถึงกำหนดอยู่ในแท็บอื่น',
    }
  }
  if (dueFilter.value === 'overdue') {
    return {
      filteredOut: true,
      title: 'ไม่มีงานที่เลยกำหนด',
      hint: 'งานที่ยังไม่ถึงกำหนดจะแสดงในแท็บ "ยังไม่เสร็จ"',
    }
  }

  const label = filter.value === 'done' ? TASK_STATUS_LABELS.done : TASK_STATUS_LABELS.pending
  return {
    filteredOut: true,
    title: filter.value === 'all' ? 'ไม่พบงานที่ตรงกับตัวกรอง' : `ไม่มีงานสถานะ "${label}"`,
    hint: 'สลับไปดูงานทั้งหมดเพื่อตรวจว่างานยังอยู่ หรือสร้างงานใหม่',
  }
})

// โทนสีป้ายสถานะตาม Design Contract (โทนพาสเทล + ตัวอักษรเข้ม)
const getStatusBadgeClass = (task: Task) => {
  if (task.status === 'done') return 'bg-canvas text-ink-2'

  const diffDays = diffDaysFromToday(task.due_date)

  if (diffDays < 0) return 'bg-danger-50 text-danger-700'
  if (diffDays === 0 || diffDays === 1) return 'bg-warn-50 text-warn-700'
  return 'bg-ok-50 text-ok-700'
}

// ไอคอนในป้ายสถานะ — คู่กับเงื่อนไขเดียวกับ getStatusBadgeClass
const getStatusIcon = (task: Task) => {
  if (task.status === 'done') return 'bi-check-circle-fill'

  const diffDays = diffDaysFromToday(task.due_date)

  if (diffDays < 0) return 'bi-exclamation-circle-fill'
  if (diffDays === 0 || diffDays === 1) return 'bi-clock-fill'
  return 'bi-clock'
}

// ป้ายงานที่ปิดแล้วใช้คำจาก glossary ("เสร็จแล้ว") — ที่เหลือเป็นคำอธิบายกำหนดส่ง
const getStatusText = (task: Task) => {
  if (task.status === 'done') return TASK_STATUS_LABELS.done

  const diffDays = diffDaysFromToday(task.due_date)

  if (diffDays < 0) return `เลยกำหนดมา ${Math.abs(diffDays)} วัน`
  if (diffDays === 0) return 'ส่งวันนี้'
  if (diffDays === 1) return 'ส่งพรุ่งนี้'
  return `เหลืออีก ${diffDays} วัน`
}

const toggleStatus = async (task: Task) => {
  if (!canManageTasks.value) return dialog.notify('เฉพาะผู้ดูแลเท่านั้น', 'warning')
  try {
    if (task.status === 'pending') {
      await TaskService.markDone(currentRoomId, task.id, currentUserName)
      dialog.notify('🎉 ยินดีด้วย! งานเสร็จแล้ว')
    } else {
      await TaskService.markPending(currentRoomId, task.id, currentUserName)
      dialog.notify('🔄 เปลี่ยนกลับเป็นยังไม่เสร็จ', 'info')
    }
    await fetchData()
  } catch (error: unknown) {
    void dialog.alert('ข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถอัปเดตสถานะได้', 'error')
  }
}

const deleteTask = async (taskId: number) => {
  if (!canManageTasks.value) return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลเท่านั้น', 'error')
  const result = await dialog.confirm('ลบงานนี้ทิ้งเลยไหม?', 'คุณจะไม่สามารถกู้คืนข้อมูลได้!', {
    icon: 'warning',
    danger: true,
    confirmButtonText: 'ลบข้อมูล'
  })

  if (result.isConfirmed) {
    try {
      await TaskService.deleteTask(currentRoomId, taskId, currentUserName)
      dialog.notify('🗑️ ลบงานเรียบร้อยแล้ว')
      await fetchData()
    } catch (error: unknown) {
      void dialog.alert('ข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถลบงานได้', 'error')
    }
  }
}

// 🔒 รวมทุกการกระทำของงานไว้ในเมนูจุด 3 จุดมุมการ์ด
// เดิมเป็นปุ่มเปลือย 3 ปุ่มเรียงท้ายการ์ด โดย "ลบ" วางติดกับ "ติ๊กเสร็จ" ⇒ กดพลาดง่าย
const taskMenuItems = (task: Task): RowActionItem[] => {
  const isDone = task.status === 'done'
  return [
    {
      key: 'toggle',
      label: isDone ? 'ยกเลิก (ยังไม่เสร็จ)' : 'ติ๊กเสร็จ',
      icon: isDone ? 'bi-arrow-counterclockwise' : 'bi-check-circle-fill',
    },
    // มี `to` ⇒ RowActionMenu เรนเดอร์เป็น RouterLink เอง ไม่ต้องดักที่ @select
    { key: 'edit', label: 'แก้ไข', icon: 'bi-pencil-square', to: `/tasks/${task.id}/edit` },
    { key: 'delete', label: 'ลบงาน', icon: 'bi-trash3-fill', tone: 'danger' },
  ]
}

const handleTaskAction = async (task: Task, key: string) => {
  if (key === 'toggle') await toggleStatus(task)
  else if (key === 'delete') await deleteTask(task.id)
}

onMounted(fetchData)
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="จัดการการบ้านและอัปเดตประกาศรายวันของห้อง"
    >
      <template #actions>
        <RouterLink v-if="canManageTasks" to="/tasks/add" class="btn-primary hidden lg:inline-flex">
          <i class="bi bi-plus-lg" aria-hidden="true" />
          สร้างใหม่
        </RouterLink>
      </template>
    </PageIntro>

    <!--
      📅 ตัวกรองกำหนดส่ง — มาจากการ์ดหน้าหลัก (filter=today|overdue)
         แสดงเป็นชิปแยกจากแท็บสถานะ เพราะเป็น "คนละแกน" กับการกรอง status
    -->
    <div v-if="dueFilter && !isLoading && !hasError" class="flex flex-wrap items-center gap-2">
      <span class="chip bg-brand-50 text-brand-700">
        <i class="bi bi-funnel-fill" aria-hidden="true"></i>
        {{ dueFilterLabel }} · {{ filteredTasks.length }} รายการ
      </span>
      <button type="button" class="btn-ghost-ui" @click="clearDueFilter">
        <i class="bi bi-x-lg" aria-hidden="true"></i>
        ล้างตัวกรองวันที่
      </button>
    </div>

    <!-- ตัวกรองสถานะ — ซ่อนระหว่างโหลด/ผิดพลาด ไม่ให้เห็นตัวเลข 0 หลอกตา -->
    <AppTabs
      v-if="!isLoading && !hasError"
      :model-value="filter"
      :tabs="filterTabs"
      group-label="กรองสถานะงาน"
      @update:model-value="setFilter"
    />

    <!-- โน้ตรายวันล่าสุด (แสดง 3 รายการแรก) -->
    <section v-if="notes.length > 0" class="space-y-3">
      <div class="flex items-center gap-2">
        <i class="bi bi-sticky-fill text-base text-warn-500" aria-hidden="true"></i>
        <h2 class="section-title">โน้ตรายวันล่าสุด</h2>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2 lg:grid-cols-3">
        <article
          v-for="note in notes.slice(0, 3)"
          :key="note.id"
          class="page-card border-s-4 border-s-warn-400 p-3.5 sm:p-5"
        >
          <!-- ป้ายวันอยู่ซ้าย ข้อความอยู่ขวา — การ์ดเตี้ยลงและใช้ความกว้างคุ้มขึ้นบนมือถือ -->
          <div class="flex items-start gap-3">
            <span class="chip shrink-0 bg-warn-50 text-warn-700">
              <i class="bi bi-calendar3" aria-hidden="true"></i>
              {{ formatDueDate(note.target_date) }}
            </span>

            <div class="min-w-0 flex-1 space-y-1.5">
              <div class="flex items-start gap-2">
                <i class="bi bi-backpack-fill mt-0.5 shrink-0 text-ink-3" aria-hidden="true"></i>
                <p class="min-w-0 break-words text-sm leading-relaxed text-ink-2">
                  เตรียม: <span class="font-bold text-ink-1">{{ note.bring_items || '-' }}</span>
                </p>
              </div>
              <div class="flex items-start gap-2">
                <i class="bi bi-megaphone-fill mt-0.5 shrink-0 text-ink-3" aria-hidden="true"></i>
                <p class="min-w-0 break-words text-sm leading-relaxed text-ink-2">
                  {{ note.announcement || 'ไม่มีประกาศ' }}
                </p>
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-32" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="ตรวจสอบการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
      @retry="fetchData"
    />

    <StateBlock
      v-else-if="filteredTasks.length === 0"
      variant="empty"
      :title="emptyState.title"
      :hint="emptyState.hint"
    >
      <button
        v-if="emptyState.filteredOut"
        type="button"
        class="btn-ghost-ui mt-1"
        @click="filter = 'all'"
      >
        <i class="bi bi-list-ul" aria-hidden="true" />
        ดูงานทั้งหมด
      </button>
      <RouterLink v-else-if="canManageTasks" to="/tasks/add" class="btn-primary mt-1">
        <i class="bi bi-plus-lg" aria-hidden="true" />
        สร้างงานใหม่
      </RouterLink>
    </StateBlock>

    <div v-else class="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="task in filteredTasks"
        :key="task.id"
        class="page-card flex flex-col p-4 sm:p-5"
        :class="[
          task.status === 'done' ? 'opacity-70' : '',
          // งานที่เลยกำหนดแล้วและยังไม่ส่ง — เน้นด้วยแถบแดงด้านซ้าย
          task.status === 'pending' && diffDaysFromToday(task.due_date) < 0
            ? 'border-s-4 border-s-danger-500'
            : '',
        ]"
      >
        <div class="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
          <!-- min-width ที่ sm: ทำให้ flex-wrap ทำงานจริง ป้ายสถานะจึงตกบรรทัดแทนที่จะบีบชื่องาน -->
          <div class="min-w-0 flex-1 sm:min-w-[16rem]">
            <h3
              class="break-words font-display text-base font-bold leading-snug text-ink-1"
              :class="{ 'line-through text-ink-3': task.status === 'done' }"
            >
              {{ task.task_name }}
            </h3>
            <p class="mt-1.5 flex flex-wrap items-center gap-x-1.5 text-xs font-bold text-ink-3">
              <i class="bi bi-calendar-event text-ink-3" aria-hidden="true"></i>
              กำหนดส่ง
              <span class="num text-ink-2">{{ formatDueDate(task.due_date) }}</span>
            </p>
          </div>

          <!-- ป้ายสถานะ + เมนูจัดการ ห่อเป็นก้อนเดียวกันเพื่อให้ flex-wrap ของการ์ดพาไปด้วยกัน -->
          <div class="flex shrink-0 items-center gap-1.5">
            <span class="chip" :class="getStatusBadgeClass(task)">
              <i class="bi" :class="getStatusIcon(task)" aria-hidden="true"></i>
              {{ getStatusText(task) }}
            </span>

            <RowActionMenu
              v-if="canManageTasks"
              :label="`ตัวเลือกจัดการงาน ${task.task_name}`"
              :items="taskMenuItems(task)"
              @select="handleTaskAction(task, $event)"
            />
          </div>
        </div>

        <p
          class="mt-3 grow whitespace-pre-wrap break-words text-sm leading-relaxed text-ink-2"
          :class="{ 'line-through text-ink-3': task.status === 'done' }"
        >
          {{ task.task_detail || 'ไม่มีรายละเอียดเพิ่มเติม' }}
        </p>
      </article>
    </div>
  </div>
</template>
