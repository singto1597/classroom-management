<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { TaskService } from '@/services/task'
import Swal from 'sweetalert2'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

// --- ถอด Mock Data เปลี่ยนมาดึงจาก Store ---
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

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
  } catch (error: any) {
    Swal.fire('Error', error.response?.data?.detail || 'Failed to fetch task', 'error')
    router.push('/tasks')
  } finally {
    isLoading.value = false
  }
}

const handleUpdateTask = async () => {
  if (!isAdmin.value) {
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
      showConfirmButton: false
    })
    router.push('/tasks')
  } catch (error: any) {
    Swal.fire('Error', error.response?.data?.detail || 'Failed to update task', 'error')
  } finally {
    isSubmitting.value = false
  }
}

onMounted(fetchTask)
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
          <h1 class="text-2xl font-extrabold text-slate-800">แก้ไขข้อมูลงาน</h1>
          <p class="text-slate-500 text-sm mt-0.5">อัปเดตรายละเอียด หรือเลื่อนกำหนดส่งของการบ้าน</p>
        </div>
      </div>

      <div class="bg-white shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[2rem] overflow-hidden border border-slate-100">
        
        <div class="bg-gradient-to-r from-blue-600 to-indigo-600 p-6 text-white flex items-center gap-3">
          <div class="w-10 h-10 bg-white/20 rounded-xl flex items-center justify-center backdrop-blur-md border border-white/20">
            <i class="bi bi-pencil-square text-lg"></i>
          </div>
          <h4 class="text-xl font-bold">ฟอร์มแก้ไขงาน (ID: {{ taskId }})</h4>
        </div>

        <div class="p-8 md:p-10">
          
          <div v-if="isLoading" class="flex flex-col items-center justify-center py-10 gap-3">
            <span class="loading loading-spinner loading-lg text-blue-600"></span>
            <p class="text-slate-500 font-medium animate-pulse">กำลังโหลดข้อมูล...</p>
          </div>

          <form v-else @submit.prevent="handleUpdateTask" class="space-y-6">
            
            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-bookmark-fill text-blue-500"></i> ชื่องาน <span class="text-rose-500">*</span>
              </label>
              <input 
                :disabled="!isAdmin"
                v-model="form.task_name" 
                type="text" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none disabled:opacity-60 disabled:bg-slate-100 disabled:cursor-not-allowed" 
                required 
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-card-text text-blue-500"></i> รายละเอียด
              </label>
              <textarea 
                :disabled="!isAdmin"
                v-model="form.task_detail" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl h-32 focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none resize-none disabled:opacity-60 disabled:bg-slate-100 disabled:cursor-not-allowed" 
                placeholder="อธิบายรายละเอียดงาน, ขั้นตอนการทำ, หรือแนบลิงก์ที่เกี่ยวข้อง..."
              ></textarea>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-calendar-event text-blue-500"></i> กำหนดส่ง <span class="text-rose-500">*</span>
              </label>
              <input 
                :disabled="!isAdmin"
                v-model="form.due_date" 
                type="date" 
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none disabled:opacity-60 disabled:bg-slate-100 disabled:cursor-not-allowed" 
                required 
              />
            </div>

            <div class="pt-6 mt-6 border-t border-slate-100">
              <template v-if="isAdmin">
                <button 
                  type="submit" 
                  class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-blue-600/20 transition-all flex items-center justify-center gap-2"
                  :disabled="isSubmitting"
                >
                  <span v-if="isSubmitting" class="loading loading-spinner loading-sm"></span>
                  <i v-else class="bi bi-save-fill"></i> บันทึกการแก้ไข
                </button>
              </template>
              <div v-else class="w-full text-center py-3.5 bg-slate-100 text-slate-500 rounded-xl font-medium border border-slate-200 flex items-center justify-center gap-2">
                <i class="bi bi-lock-fill text-rose-500"></i> เฉพาะแอดมินเท่านั้นที่แก้ไขได้
              </div>
            </div>
          </form>

        </div>
      </div>
    </div>
  </div>
</template>