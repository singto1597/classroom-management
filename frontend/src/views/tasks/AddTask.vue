<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

// --- ถอด Mock Data เปลี่ยนมาดึงจาก Store ---
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

const activeTab = ref<'task' | 'note'>('task')
const isSubmitting = ref(false)

// 🛠️ Fix Bug: ฟังก์ชันดึงวันที่ปัจจุบัน (Local Timezone) เพื่อป้องกันวันที่เพี้ยนเป็นเมื่อวานตอนเช้าตรู่ (UTC Bug)
const getLocalDate = () => {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().split('T')[0]
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
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถเพิ่มงานได้', 'error')
  }
  
  if (!taskForm.task_name) return
  isSubmitting.value = true
  
  try {
    await TaskService.createTask(currentRoomId, {
      ...(taskForm as any),
      user_name: currentUserName
    })
    await Swal.fire({
      icon: 'success',
      title: 'เพิ่มงานเรียบร้อยแล้ว!',
      timer: 1500,
      showConfirmButton: false
    })
    router.push('/tasks')
  } catch (error: any) {
    Swal.fire('Error', error.response?.data?.detail || 'Failed to add task', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const handleAddNote = async () => {
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถเพิ่มประกาศได้', 'error')
  }

  if (!noteForm.target_date) return
  isSubmitting.value = true
  
  try {
    await TaskService.createDailyNote(currentRoomId, {
      ...(noteForm as any),
      user_name: currentUserName
    })
    await Swal.fire({
      icon: 'success',
      title: `บันทึกโน้ตสำหรับวันที่ ${noteForm.target_date} เรียบร้อย!`,
      timer: 1500,
      showConfirmButton: false
    })
    router.push('/tasks')
  } catch (error: any) {
    Swal.fire('Error', error.response?.data?.detail || 'Failed to add note', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 py-10 px-4 sm:px-6">
    <div class="max-w-2xl mx-auto">
      
      <div class="flex items-center gap-4 mb-8">
        <button 
          @click="router.push('/tasks')" 
          class="w-10 h-10 bg-white rounded-full flex items-center justify-center text-slate-500 shadow-sm border border-slate-200 hover:text-slate-800 hover:shadow transition-all"
        >
          <i class="bi bi-arrow-left text-lg"></i>
        </button>
        <div>
          <h1 class="text-2xl font-extrabold text-slate-800">สร้างรายการใหม่</h1>
          <p class="text-slate-500 text-sm mt-0.5">เพิ่มการบ้าน, ชิ้นงาน หรือโน้ตประกาศรายวัน</p>
        </div>
      </div>

      <div class="bg-white shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[2rem] overflow-hidden border border-slate-100">
        
        <div class="flex p-2 bg-slate-50/50 border-b border-slate-100">
          <button 
            @click="activeTab = 'task'"
            class="flex-1 py-3.5 text-center font-bold text-sm transition-all rounded-2xl flex items-center justify-center gap-2 outline-none"
            :class="activeTab === 'task' ? 'bg-white text-blue-600 shadow-sm border border-slate-100' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100/50'"
          >
            <i class="bi bi-journal-plus text-lg"></i> งาน / การบ้าน
          </button>
          <button 
            @click="activeTab = 'note'"
            class="flex-1 py-3.5 text-center font-bold text-sm transition-all rounded-2xl flex items-center justify-center gap-2 outline-none"
            :class="activeTab === 'note' ? 'bg-white text-amber-600 shadow-sm border border-slate-100' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100/50'"
          >
            <i class="bi bi-sticky text-lg"></i> โน้ต / ประกาศ
          </button>
        </div>

        <div class="p-8 md:p-10">
          <form v-if="activeTab === 'task'" @submit.prevent="handleAddTask" class="space-y-6">
            
            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-bookmark-fill text-blue-500"></i> ชื่องาน <span class="text-rose-500">*</span>
              </label>
              <input 
                :disabled="!isAdmin"
                v-model="taskForm.task_name" 
                type="text" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none disabled:opacity-60" 
                placeholder="เช่น การบ้านคณิตศาสตร์ หน้า 45"
                required 
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-card-text text-blue-500"></i> รายละเอียด
              </label>
              <textarea 
                :disabled="!isAdmin"
                v-model="taskForm.task_detail" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl h-32 focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none resize-none disabled:opacity-60" 
                placeholder="อธิบายรายละเอียดงาน, ขั้นตอนการทำ, หรือแนบลิงก์ที่เกี่ยวข้อง..."
              ></textarea>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-calendar-event text-blue-500"></i> กำหนดส่ง <span class="text-rose-500">*</span>
              </label>
              <input 
                :disabled="!isAdmin"
                v-model="taskForm.due_date" 
                type="date" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none disabled:opacity-60" 
                required 
              />
            </div>

            <div class="pt-4">
              <template v-if="isAdmin">
                <button 
                  type="submit" 
                  class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-blue-600/20 transition-all flex items-center justify-center gap-2"
                  :disabled="isSubmitting"
                >
                  <span v-if="isSubmitting" class="loading loading-spinner loading-sm"></span>
                  <i v-else class="bi bi-plus-lg"></i> บันทึกงานใหม่
                </button>
              </template>
              <div v-else class="w-full text-center py-3.5 bg-slate-100 text-slate-500 rounded-xl font-medium border border-slate-200 flex items-center justify-center gap-2">
                <i class="bi bi-lock-fill"></i> เฉพาะแอดมิน
              </div>
            </div>
          </form>

          <form v-else @submit.prevent="handleAddNote" class="space-y-6">
            
            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-calendar-check-fill text-amber-500"></i> วันที่เป้าหมาย <span class="text-rose-500">*</span>
              </label>
              <input 
                :disabled="!isAdmin"
                v-model="noteForm.target_date" 
                type="date" 
                class="w-full px-4 py-3 bg-amber-50/30 border border-amber-200/50 rounded-xl focus:bg-white focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500 transition-all outline-none disabled:opacity-60" 
                required 
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-backpack-fill text-amber-500"></i> สิ่งที่ต้องเตรียม
              </label>
              <input 
                :disabled="!isAdmin"
                v-model="noteForm.bring_items" 
                type="text" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500 transition-all outline-none disabled:opacity-60" 
                placeholder="เช่น สีไม้, อุปกรณ์พละ (ถ้าไม่มีให้เว้นว่างไว้)"
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-megaphone-fill text-amber-500"></i> ประกาศ / หมายเหตุ
              </label>
              <textarea 
                :disabled="!isAdmin"
                v-model="noteForm.announcement" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl h-32 focus:bg-white focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500 transition-all outline-none resize-none disabled:opacity-60" 
                placeholder="ประกาศแจ้งเตือนเพื่อนๆ ในห้อง... (ถ้าไม่มีให้เว้นว่างไว้)"
              ></textarea>
            </div>

            <div class="pt-4">
              <template v-if="isAdmin">
                <button 
                  type="submit" 
                  class="w-full bg-amber-500 hover:bg-amber-600 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-amber-500/20 transition-all flex items-center justify-center gap-2"
                  :disabled="isSubmitting"
                >
                  <span v-if="isSubmitting" class="loading loading-spinner loading-sm"></span>
                  <i v-else class="bi bi-plus-lg"></i> บันทึกโน้ต/ประกาศ
                </button>
              </template>
              <div v-else class="w-full text-center py-3.5 bg-slate-100 text-slate-500 rounded-xl font-medium border border-slate-200 flex items-center justify-center gap-2">
                <i class="bi bi-lock-fill"></i> เฉพาะแอดมิน
              </div>
            </div>
          </form>

        </div>
      </div>
    </div>
  </div>
</template>