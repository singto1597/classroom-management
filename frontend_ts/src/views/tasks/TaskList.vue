<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import type { Task, DailyNote } from '@/types/task'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

// --- ถอด Mock Data เปลี่ยนมาดึงจาก Store ---
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

const tasks = ref<Task[]>([])
const notes = ref<DailyNote[]>([])
const isLoading = ref(true)
const filter = ref<'all' | 'pending' | 'done'>('pending')

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
  try {
    const [tasksResult, notesResult] = await Promise.allSettled([
      TaskService.getAllTasks(currentRoomId),
      TaskService.getDailyNotes(currentRoomId)
    ])

    if (tasksResult.status === 'fulfilled') {
      tasks.value = tasksResult.value as Task[]
    } else {
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

const filteredTasks = computed(() => {
  if (filter.value === 'all') return tasks.value
  return tasks.value.filter(task => task.status === filter.value)
})

// ปรับสี Badge ให้ดูพรีเมียมขึ้น (Pastel & Border)
const getStatusBadgeClass = (task: Task) => {
  if (task.status === 'done') return 'bg-slate-100 text-slate-500 border border-slate-200'
  
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const dueDate = new Date(task.due_date)
  dueDate.setHours(0, 0, 0, 0)
  
  const diffTime = dueDate.getTime() - today.getTime()
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

  if (diffDays < 0) return 'bg-rose-50 text-rose-600 border border-rose-200'
  if (diffDays === 0 || diffDays === 1) return 'bg-amber-50 text-amber-600 border border-amber-200'
  return 'bg-emerald-50 text-emerald-600 border border-emerald-200'
}

const getStatusText = (task: Task) => {
  if (task.status === 'done') return 'ส่งแล้ว 🎉'
  
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const dueDate = new Date(task.due_date)
  dueDate.setHours(0, 0, 0, 0)
  
  const diffTime = dueDate.getTime() - today.getTime()
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))

  if (diffDays < 0) return `เลยกำหนดมา ${Math.abs(diffDays)} วัน!`
  if (diffDays === 0) return 'ส่งวันนี้!'
  if (diffDays === 1) return 'ส่งพรุ่งนี้!'
  return `เหลืออีก ${diffDays} วัน`
}

const toggleStatus = async (task: Task) => {
  if (!isAdmin.value) return Toast.fire({ icon: 'warning', title: 'เฉพาะแอดมินเท่านั้น' })
  try {
    if (task.status === 'pending') {
      await TaskService.markDone(currentRoomId, task.id, currentUserName)
      Toast.fire({ icon: 'success', title: '🎉 ยินดีด้วย! งานเสร็จแล้ว' })
    } else {
      await TaskService.markPending(currentRoomId, task.id, currentUserName)
      Toast.fire({ icon: 'info', title: '🔄 เปลี่ยนกลับเป็นยังไม่เสร็จ' })
    }
    await fetchData()
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error.response?.data?.detail || 'ไม่สามารถอัปเดตสถานะได้', 'error')
  }
}

const deleteTask = async (taskId: number) => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error')
  const result = await Swal.fire({
    title: 'ลบงานนี้ทิ้งเลยไหม?',
    text: "คุณจะไม่สามารถกู้คืนข้อมูลได้!",
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#e11d48',
    cancelButtonColor: '#94a3b8',
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก'
  })

  if (result.isConfirmed) {
    try {
      await TaskService.deleteTask(currentRoomId, taskId, currentUserName)
      Toast.fire({ icon: 'success', title: '🗑️ ลบงานเรียบร้อยแล้ว' })
      await fetchData()
    } catch (error: any) {
      Swal.fire('ข้อผิดพลาด', error.response?.data?.detail || 'ไม่สามารถลบงานได้', 'error')
    }
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-6xl mx-auto">
      
      <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center mb-6 md:mb-10 gap-6">
        <div class="w-full lg:w-auto">
          <h3 class="text-xl sm:text-2xl md:text-3xl font-extrabold text-slate-800 flex items-center gap-3">
            <div class="p-2.5 sm:p-3 bg-blue-100 rounded-2xl text-blue-600 shadow-sm flex-shrink-0">
              <i class="bi bi-clipboard-check"></i>
            </div>
            รายการงาน & โน้ต
          </h3>
          <p class="text-slate-500 mt-2 ml-1 text-sm md:text-base">จัดการการบ้านและอัปเดตประกาศรายวันของห้อง</p>
        </div>
        
        <div class="flex flex-col sm:flex-row items-center gap-3 w-full lg:w-auto">
          <div class="bg-slate-200/60 p-1.5 rounded-2xl flex flex-wrap sm:flex-nowrap items-center gap-1 shadow-inner backdrop-blur-sm w-full sm:w-auto justify-center sm:justify-start">
            <button @click="filter = 'pending'" :class="filter === 'pending' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'" class="flex-1 sm:flex-none px-4 sm:px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-300 whitespace-nowrap text-center">กำลังทำ</button>
            <button @click="filter = 'done'" :class="filter === 'done' ? 'bg-white text-emerald-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'" class="flex-1 sm:flex-none px-4 sm:px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-300 whitespace-nowrap text-center">เสร็จแล้ว</button>
            <button @click="filter = 'all'" :class="filter === 'all' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'" class="flex-1 sm:flex-none px-4 sm:px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-300 whitespace-nowrap text-center">ทั้งหมด</button>
          </div>

          <router-link v-if="isAdmin" to="/tasks/add" class="w-full sm:w-auto px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-600/20 transition-all flex items-center justify-center gap-2 whitespace-nowrap">
            <i class="bi bi-plus-lg"></i> สร้างใหม่
          </router-link>
        </div>
      </div>

      <div v-if="notes.length > 0" class="mb-10 md:mb-12">
        <div class="flex items-center gap-2 mb-4 ml-1">
          <i class="bi bi-sticky-fill text-amber-500 text-lg"></i>
          <h4 class="text-base md:text-lg font-bold text-slate-700">โน้ตรายวันล่าสุด</h4>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-5">
          <div v-for="note in notes.slice(0, 3)" :key="note.id" 
               class="relative bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/60 rounded-3xl p-5 md:p-6 shadow-sm hover:shadow-md transition-shadow">
            <div class="absolute -top-3 -right-3 w-8 h-8 bg-white rounded-full flex items-center justify-center shadow-sm border border-slate-100 text-amber-400">
              <i class="bi bi-pin-angle-fill"></i>
            </div>
            <div class="mb-4">
              <span class="text-xs font-bold text-amber-700 bg-amber-200/50 px-3 py-1.5 rounded-full backdrop-blur-sm">
                📅 {{ note.target_date }}
              </span>
            </div>
            <div class="space-y-3">
              <div class="flex items-start gap-2 text-slate-700">
                <span class="mt-0.5">🎒</span>
                <p class="text-sm font-semibold leading-relaxed">เตรียม: <span class="font-bold text-amber-900">{{ note.bring_items || '-' }}</span></p>
              </div>
              <div class="flex items-start gap-2 text-slate-700">
                <span class="mt-0.5 text-rose-500"><i class="bi bi-megaphone-fill"></i></span>
                <p class="text-sm font-medium leading-relaxed">{{ note.announcement || 'ไม่มีประกาศ' }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังดึงข้อมูลงาน...</p>
      </div>

      <div v-else-if="filteredTasks.length === 0" class="flex flex-col items-center justify-center py-20 md:py-24 bg-white rounded-[2rem] shadow-sm border border-slate-100 px-4 text-center">
        <div class="w-20 h-20 md:w-24 md:h-24 bg-slate-50 rounded-full flex items-center justify-center mb-6">
          <i class="bi bi-inbox text-3xl md:text-4xl text-slate-300"></i>
        </div>
        <h4 class="text-lg md:text-xl font-bold text-slate-700 mb-2">ยังไม่มีงานในหมวดหมู่นี้เลย</h4>
        <p class="text-sm md:text-base text-slate-400">พักผ่อนให้สบาย หรือเพิ่มงานใหม่เพื่อเริ่มต้นกันเถอะ!</p>
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 md:gap-6">
        <div 
          v-for="task in filteredTasks" 
          :key="task.id"
          class="group bg-white rounded-3xl p-5 md:p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-slate-100 hover:shadow-lg hover:-translate-y-1 transition-all duration-300 flex flex-col"
          :class="{ 'opacity-60 bg-slate-50 grayscale-[0.2]': task.status === 'done' }"
        >
          <div class="flex flex-col sm:flex-row sm:justify-between sm:items-start mb-4 gap-2 sm:gap-4">
            <h5 class="text-lg font-bold text-slate-800 leading-tight" :class="{ 'line-through text-slate-400': task.status === 'done' }">
              {{ task.task_name }}
            </h5>
            <div class="flex-shrink-0">
              <span :class="['px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider whitespace-nowrap inline-block', getStatusBadgeClass(task)]">
                {{ getStatusText(task) }}
              </span>
            </div>
          </div>
          
          <div class="flex items-center gap-2 text-slate-500 text-xs font-semibold mb-4 bg-slate-50 w-fit px-3 py-1.5 rounded-lg border border-slate-100">
            <i class="bi bi-calendar-event text-blue-500"></i> 
            กำหนดส่ง: <span class="text-slate-700">{{ task.due_date }}</span>
          </div>
          
          <p class="text-slate-600 text-sm mb-6 whitespace-pre-wrap leading-relaxed flex-grow" :class="{ 'line-through text-slate-400': task.status === 'done' }">
            {{ task.task_detail || 'ไม่มีรายละเอียดเพิ่มเติม' }}
          </p>

          <div v-if="isAdmin" class="flex justify-between items-center mt-auto pt-4 border-t border-slate-100">
            <button 
              @click="toggleStatus(task)"
              class="flex items-center gap-1.5 px-3 py-2 sm:py-1.5 rounded-lg text-sm font-bold transition-colors"
              :class="task.status === 'done' ? 'text-amber-600 bg-amber-50 hover:bg-amber-100' : 'text-emerald-600 bg-emerald-50 hover:bg-emerald-100'"
            >
              <i :class="task.status === 'done' ? 'bi bi-arrow-counterclockwise' : 'bi bi-check-circle-fill'"></i>
              {{ task.status === 'done' ? 'ยกเลิก' : 'ติ๊กเสร็จ' }}
            </button>

            <div class="flex gap-2">
              <router-link 
                :to="`/tasks/${task.id}/edit`" 
                class="w-10 h-10 sm:w-9 sm:h-9 rounded-full flex items-center justify-center text-slate-400 bg-slate-50 hover:bg-blue-50 hover:text-blue-600 transition-colors"
                title="แก้ไข"
              >
                <i class="bi bi-pencil-square"></i>
              </router-link>
              <button 
                @click="deleteTask(task.id)"
                class="w-10 h-10 sm:w-9 sm:h-9 rounded-full flex items-center justify-center text-slate-400 bg-slate-50 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                title="ลบ"
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

<style scoped>
</style>