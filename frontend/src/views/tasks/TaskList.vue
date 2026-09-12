<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import type { Task, DailyNote } from '@/types/task'
import Swal from 'sweetalert2'
import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

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

const tasks = ref<Task[]>([])
const notes = ref<DailyNote[]>([])
const isLoading = ref(true)
const filter = ref<'all' | 'pending' | 'done'>('pending')

// สถานะผิดพลาด — เดิมแจ้งด้วย toast อย่างเดียว ตอนนี้ใช้โชว์ StateBlock ด้วย
const hasError = ref(false)

// ตั้งค่า Toast สำหรับ SweetAlert ให้แจ้งเตือนแบบสมูท ไม่บล็อกหน้าจอ
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
    const [tasksResult, notesResult] = await Promise.allSettled([
      TaskService.getAllTasks(currentRoomId),
      TaskService.getDailyNotes(currentRoomId)
    ])

    if (tasksResult.status === 'fulfilled') {
      tasks.value = tasksResult.value as Task[]
    } else {
      hasError.value = true
      Toast.fire({ icon: 'error', title: 'ดึงข้อมูลงานไม่สำเร็จ' })
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

// 🗓️ คำนวณจำนวนวันห่างจากวันนี้ (Local Timezone — กันบัค UTC ทำให้เพี้ยน 1 วัน)
const diffDaysFromToday = (dateStr: string): number => {
  const due = new Date(dateStr + 'T00:00:00');
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
};

// 🗓️ แปลงวันที่ YYYY-MM-DD → ไทย (เช่น 5 ส.ค. 2569) และโชว์ว่าวันนี้/พรุ่งนี้
const formatDueDate = (dateStr: string) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr + 'T00:00:00');
  const diffDays = diffDaysFromToday(dateStr);

  if (diffDays === 0) return 'วันนี้';
  if (diffDays === 1) return 'พรุ่งนี้';

  return date.toLocaleDateString('th-TH', {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  });
};

const filteredTasks = computed(() => {
  let result = tasks.value
  if (filter.value !== 'all') {
    result = tasks.value.filter(task => task.status === filter.value)
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

// โทนสีป้ายสถานะตาม Design Contract (โทนพาสเทล + ตัวอักษรเข้ม)
const getStatusBadgeClass = (task: Task) => {
  if (task.status === 'done') return 'bg-stone-100 text-stone-600'

  const diffDays = diffDaysFromToday(task.due_date)

  if (diffDays < 0) return 'bg-red-50 text-red-700'
  if (diffDays === 0 || diffDays === 1) return 'bg-amber-50 text-amber-700'
  return 'bg-emerald-50 text-emerald-700'
}

// ไอคอนในป้ายสถานะ — คู่กับเงื่อนไขเดียวกับ getStatusBadgeClass
const getStatusIcon = (task: Task) => {
  if (task.status === 'done') return 'bi-check-circle-fill'

  const diffDays = diffDaysFromToday(task.due_date)

  if (diffDays < 0) return 'bi-exclamation-circle-fill'
  if (diffDays === 0 || diffDays === 1) return 'bi-clock-fill'
  return 'bi-clock'
}

const getStatusText = (task: Task) => {
  if (task.status === 'done') return 'ส่งแล้ว'

  const diffDays = diffDaysFromToday(task.due_date)

  if (diffDays < 0) return `เลยกำหนดมา ${Math.abs(diffDays)} วัน`
  if (diffDays === 0) return 'ส่งวันนี้'
  if (diffDays === 1) return 'ส่งพรุ่งนี้'
  return `เหลืออีก ${diffDays} วัน`
}

const toggleStatus = async (task: Task) => {
  if (!canManageTasks.value) return Toast.fire({ icon: 'warning', title: 'เฉพาะผู้ดูแลเท่านั้น' })
  try {
    if (task.status === 'pending') {
      await TaskService.markDone(currentRoomId, task.id, currentUserName)
      Toast.fire({ icon: 'success', title: '🎉 ยินดีด้วย! งานเสร็จแล้ว' })
    } else {
      await TaskService.markPending(currentRoomId, task.id, currentUserName)
      Toast.fire({ icon: 'info', title: '🔄 เปลี่ยนกลับเป็นยังไม่เสร็จ' })
    }
    await fetchData()
  } catch (error: unknown) {
    Swal.fire('ข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถอัปเดตสถานะได้', 'error')
  }
}

const deleteTask = async (taskId: number) => {
  if (!canManageTasks.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลเท่านั้น', 'error')
  const result = await Swal.fire({
    title: 'ลบงานนี้ทิ้งเลยไหม?',
    text: "คุณจะไม่สามารถกู้คืนข้อมูลได้!",
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก'
  })

  if (result.isConfirmed) {
    try {
      await TaskService.deleteTask(currentRoomId, taskId, currentUserName)
      Toast.fire({ icon: 'success', title: '🗑️ ลบงานเรียบร้อยแล้ว' })
      await fetchData()
    } catch (error: unknown) {
      Swal.fire('ข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถลบงานได้', 'error')
    }
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Classroom Tasks"
      title="รายการงาน & โน้ต"
      description="จัดการการบ้านและอัปเดตประกาศรายวันของห้อง"
    >
      <template #actions>
        <RouterLink v-if="canManageTasks" to="/tasks/add" class="btn-primary">
          <i class="bi bi-plus-lg" aria-hidden="true" />
          สร้างใหม่
        </RouterLink>
      </template>
    </PageHeader>

    <!-- ตัวกรองสถานะ -->
    <div class="page-card p-1.5">
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
          :class="filter === 'pending' ? 'bg-brand-700 text-white' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'"
          @click="filter = 'pending'"
        >
          กำลังทำ
          <span
            class="num rounded-full px-1.5 py-0.5 text-[10px] font-bold"
            :class="filter === 'pending' ? 'bg-white/20 text-white' : 'bg-stone-200 text-stone-600'"
          >{{ pendingCount }}</span>
        </button>

        <button
          type="button"
          class="flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
          :class="filter === 'done' ? 'bg-brand-700 text-white' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'"
          @click="filter = 'done'"
        >
          เสร็จแล้ว
          <span
            class="num rounded-full px-1.5 py-0.5 text-[10px] font-bold"
            :class="filter === 'done' ? 'bg-white/20 text-white' : 'bg-stone-200 text-stone-600'"
          >{{ doneCount }}</span>
        </button>

        <button
          type="button"
          class="flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
          :class="filter === 'all' ? 'bg-brand-700 text-white' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'"
          @click="filter = 'all'"
        >
          ทั้งหมด
          <span
            class="num rounded-full px-1.5 py-0.5 text-[10px] font-bold"
            :class="filter === 'all' ? 'bg-white/20 text-white' : 'bg-stone-200 text-stone-600'"
          >{{ tasks.length }}</span>
        </button>
      </div>
    </div>

    <!-- โน้ตรายวันล่าสุด (แสดง 3 รายการแรก) -->
    <section v-if="notes.length > 0" class="space-y-3">
      <div class="flex items-center gap-2">
        <i class="bi bi-sticky-fill text-base text-amber-500" aria-hidden="true"></i>
        <h2 class="section-title">โน้ตรายวันล่าสุด</h2>
      </div>

      <div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <article
          v-for="note in notes.slice(0, 3)"
          :key="note.id"
          class="page-card border-s-4 border-s-amber-400 p-4 sm:p-5"
        >
          <span class="chip bg-amber-50 text-amber-700">
            <i class="bi bi-calendar3" aria-hidden="true"></i>
            {{ formatDueDate(note.target_date) }}
          </span>

          <div class="mt-3 space-y-2.5">
            <div class="flex items-start gap-2">
              <i class="bi bi-backpack-fill mt-0.5 shrink-0 text-stone-400" aria-hidden="true"></i>
              <p class="min-w-0 text-sm leading-relaxed text-stone-600">
                เตรียม: <span class="font-bold text-stone-900">{{ note.bring_items || '-' }}</span>
              </p>
            </div>
            <div class="flex items-start gap-2">
              <i class="bi bi-megaphone-fill mt-0.5 shrink-0 text-stone-400" aria-hidden="true"></i>
              <p class="min-w-0 text-sm leading-relaxed text-stone-600">
                {{ note.announcement || 'ไม่มีประกาศ' }}
              </p>
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
      title="ยังไม่มีงานในหมวดหมู่นี้เลย"
      hint="พักผ่อนให้สบาย หรือเพิ่มงานใหม่เพื่อเริ่มต้นกันเถอะ!"
    />

    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      <article
        v-for="task in filteredTasks"
        :key="task.id"
        class="page-card flex flex-col p-4 sm:p-5"
        :class="[
          task.status === 'done' ? 'opacity-70' : '',
          // งานที่เลยกำหนดแล้วและยังไม่ส่ง — เน้นด้วยแถบแดงด้านซ้าย
          task.status === 'pending' && diffDaysFromToday(task.due_date) < 0
            ? 'border-s-4 border-s-red-500'
            : '',
        ]"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <h3
              class="break-words font-display text-base font-bold leading-snug text-stone-900"
              :class="{ 'line-through text-stone-400': task.status === 'done' }"
            >
              {{ task.task_name }}
            </h3>
            <p class="mt-1.5 flex flex-wrap items-center gap-x-1.5 text-xs font-bold text-stone-500">
              <i class="bi bi-calendar-event text-stone-400" aria-hidden="true"></i>
              กำหนดส่ง
              <span class="num text-stone-700">{{ formatDueDate(task.due_date) }}</span>
            </p>
          </div>

          <span class="chip shrink-0" :class="getStatusBadgeClass(task)">
            <i class="bi" :class="getStatusIcon(task)" aria-hidden="true"></i>
            {{ getStatusText(task) }}
          </span>
        </div>

        <p
          class="mt-3 grow whitespace-pre-wrap text-sm leading-relaxed text-stone-600"
          :class="{ 'line-through text-stone-400': task.status === 'done' }"
        >
          {{ task.task_detail || 'ไม่มีรายละเอียดเพิ่มเติม' }}
        </p>

        <div
          v-if="canManageTasks"
          class="mt-4 flex items-center justify-between gap-2 border-t border-stone-100 pt-3.5"
        >
          <button type="button" class="btn-ghost-ui" @click="toggleStatus(task)">
            <i
              class="bi"
              :class="task.status === 'done' ? 'bi-arrow-counterclockwise' : 'bi-check-circle-fill'"
              aria-hidden="true"
            ></i>
            {{ task.status === 'done' ? 'ยกเลิก' : 'ติ๊กเสร็จ' }}
          </button>

          <div class="flex shrink-0 items-center gap-2">
            <RouterLink
              :to="`/tasks/${task.id}/edit`"
              class="btn-ghost-ui h-10 w-10 !p-0"
              title="แก้ไข"
              aria-label="แก้ไขงาน"
            >
              <i class="bi bi-pencil-square" aria-hidden="true"></i>
            </RouterLink>
            <button
              type="button"
              class="btn-danger h-10 w-10 !p-0"
              title="ลบ"
              aria-label="ลบงาน"
              @click="deleteTask(task.id)"
            >
              <i class="bi bi-trash3-fill" aria-hidden="true"></i>
            </button>
          </div>
        </div>
      </article>
    </div>

    <div class="flex justify-center">
      <RouterLink to="/dashboard" class="btn-ghost-ui">
        <i class="bi bi-house" aria-hidden="true"></i>
        กลับหน้าหลัก
      </RouterLink>
    </div>
  </div>
</template>
