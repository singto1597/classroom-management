<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ScheduleService } from '@/services/schedule'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

// ถอด Mock Data ออก และดึงค่าจาก Store แทน
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

const activeTab = ref<'default' | 'override'>('default')
const isSubmitting = ref(false)

const days = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์', 'เสาร์', 'อาทิตย์']

const defaultForm = reactive({
  day_of_week: 'จันทร์',
  attire: '',
  subjects: ''
})

const overrideForm = reactive({
  target_date: new Date().toISOString().split('T')[0],
  new_attire: '',
  note: ''
})

const handleSaveDefault = async () => {
  // Guard ดักฝั่ง Script ป้องกันนักเรียนแอบยิง API
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่แก้ไขตารางได้', 'error')
  }

  if (!defaultForm.attire || !defaultForm.subjects) return
  isSubmitting.value = true
  
  try {
    await ScheduleService.saveDefault(currentRoomId, {
      ...defaultForm,
      user_name: currentUserName
    })
    Swal.fire({
      icon: 'success',
      title: `บันทึกตารางวัน${defaultForm.day_of_week} เรียบร้อยแล้ว!`,
      timer: 2000,
      showConfirmButton: false
    })
  } catch (error: any) {
    Swal.fire('Error', error.response?.data?.detail || 'Failed to save default schedule', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const handleSaveOverride = async () => {
  // Guard ดักฝั่ง Script 
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่แก้ไขตารางได้', 'error')
  }

  if (!overrideForm.new_attire || !overrideForm.note) return
  isSubmitting.value = true
  
  try {
    await ScheduleService.saveOverride(currentRoomId, {
      ...(overrideForm as any),
      user_name: currentUserName
    })
    Swal.fire({
      icon: 'success',
      title: `ตั้งข้อยกเว้นสำหรับวันที่ ${overrideForm.target_date} เรียบร้อย!`,
      timer: 2000,
      showConfirmButton: false
    })
  } catch (error: any) {
    Swal.fire('Error', error.response?.data?.detail || 'Failed to save override', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="container mx-auto p-4 max-w-2xl">
    <div class="mb-6">
      <h1 class="text-2xl md:text-3xl font-bold text-gray-800 flex items-center gap-2">
        <i class="bi bi-calendar-check text-blue-600"></i> จัดการตารางเรียน
      </h1>
      <p class="text-gray-500 mt-1">ตั้งค่าตารางเรียนยืนพื้น และข้อยกเว้นการแต่งกายรายวัน</p>
    </div>

    <div class="card bg-white shadow-sm rounded-2xl overflow-hidden border border-gray-100">
      <div class="flex border-b border-gray-100">
        <button 
          @click="activeTab = 'default'"
          class="flex-1 py-4 text-center font-bold transition-all flex items-center justify-center gap-2 outline-none"
          :class="activeTab === 'default' ? 'bg-blue-50 text-blue-600 border-b-2 border-blue-600' : 'bg-white text-gray-500 hover:bg-gray-50'"
        >
          <i class="bi bi-calendar-week"></i> ตารางปกติ
        </button>
        <button 
          @click="activeTab = 'override'"
          class="flex-1 py-4 text-center font-bold transition-all flex items-center justify-center gap-2 outline-none"
          :class="activeTab === 'override' ? 'bg-rose-50 text-rose-600 border-b-2 border-rose-600' : 'bg-white text-gray-500 hover:bg-gray-50'"
        >
          <i class="bi bi-exclamation-triangle"></i> ข้อยกเว้นพิเศษ
        </button>
      </div>

      <div class="card-body p-6 md:p-8">
        <form v-if="activeTab === 'default'" @submit.prevent="handleSaveDefault">
          <h2 class="text-lg font-bold mb-6 text-gray-800 flex items-center gap-2">
             ตั้งตารางเรียนยืนพื้น (จันทร์ - ศุกร์)
          </h2>

          <div class="form-control mb-4">
            <label class="label font-bold text-gray-600 text-sm">วันในสัปดาห์</label>
            <select v-model="defaultForm.day_of_week" class="select select-bordered w-full rounded-xl bg-gray-50 focus:bg-white focus:border-blue-500 transition-colors">
              <option v-for="day in days" :key="day" :value="day">{{ day }}</option>
            </select>
          </div>

          <div class="form-control mb-4">
            <label class="label font-bold text-gray-600 text-sm">👕 ชุดที่ต้องใส่</label>
            <input 
              v-model="defaultForm.attire" 
              type="text" 
              class="input input-bordered w-full rounded-xl bg-gray-50 focus:bg-white focus:border-blue-500 transition-colors" 
              placeholder="เช่น ชุดนักเรียน, ชุดพละ"
              required 
            />
          </div>

          <div class="form-control mb-8">
            <label class="label font-bold text-gray-600 text-sm">📚 วิชาเรียน (เรียงตามคาบ)</label>
            <textarea 
              v-model="defaultForm.subjects" 
              class="textarea textarea-bordered w-full h-32 rounded-xl bg-gray-50 focus:bg-white focus:border-blue-500 transition-colors" 
              placeholder="คณิต, ไทย, อังกฤษ, พักกลางวัน, ฟิสิกส์..."
              required
            ></textarea>
          </div>

          <div class="flex flex-col gap-3">
            <template v-if="isAdmin">
              <button 
                type="submit" 
                class="btn bg-blue-600 hover:bg-blue-700 border-none text-white w-full rounded-xl shadow-md transition-all"
                :disabled="isSubmitting"
              >
                <span v-if="isSubmitting" class="loading loading-spinner"></span>
                <i v-else class="bi bi-save me-2"></i> บันทึกตารางเรียน
              </button>
            </template>
            <div v-else class="text-center p-4 bg-gray-50 text-gray-500 rounded-xl font-bold border border-gray-200">
              <i class="bi bi-lock-fill me-1 text-rose-500"></i> เฉพาะแอดมินเท่านั้นที่แก้ไขตารางได้
            </div>
            
            <router-link to="/dashboard" class="btn btn-ghost text-gray-500 hover:bg-gray-100 w-full rounded-xl">กลับหน้าหลัก</router-link>
          </div>
        </form>

        <form v-else @submit.prevent="handleSaveOverride">
          <h2 class="text-lg font-bold mb-6 text-gray-800 flex items-center gap-2">
             ตั้งข้อยกเว้นฉุกเฉิน (เปลี่ยนชุด/กิจกรรมพิเศษ)
          </h2>

          <div class="form-control mb-4">
            <label class="label font-bold text-gray-600 text-sm">วันที่เกิดการยกเว้น</label>
            <input 
              v-model="overrideForm.target_date" 
              type="date" 
              class="input input-bordered w-full rounded-xl border-rose-200 bg-rose-50/30 focus:bg-white focus:border-rose-500 transition-colors" 
              required 
            />
          </div>

          <div class="form-control mb-4">
            <label class="label font-bold text-gray-600 text-sm">👕 ชุดใหม่ที่ต้องใส่</label>
            <input 
              v-model="overrideForm.new_attire" 
              type="text" 
              class="input input-bordered w-full rounded-xl border-rose-200 bg-rose-50/30 focus:bg-white focus:border-rose-500 transition-colors" 
              placeholder="เช่น ชุดนักเรียน, ชุดพละ"
              required 
            />
          </div>

          <div class="form-control mb-8">
            <label class="label font-bold text-gray-600 text-sm">📢 หมายเหตุ / สาเหตุที่เปลี่ยน</label>
            <textarea 
              v-model="overrideForm.note" 
              class="textarea textarea-bordered h-32 rounded-xl border-rose-200 bg-rose-50/30 focus:bg-white focus:border-rose-500 transition-colors" 
              placeholder="เช่น มีกิจกรรม...จึงต้องใส่ชุดนักเรียน"
              required
            ></textarea>
          </div>

          <div class="flex flex-col gap-3">
            <template v-if="isAdmin">
              <button 
                type="submit" 
                class="btn bg-rose-600 hover:bg-rose-700 border-none text-white w-full rounded-xl shadow-md transition-all"
                :disabled="isSubmitting"
              >
                <span v-if="isSubmitting" class="loading loading-spinner"></span>
                <i v-else class="bi bi-save me-2"></i> บันทึกข้อยกเว้น
              </button>
            </template>
            <div v-else class="text-center p-4 bg-gray-50 text-gray-500 rounded-xl font-bold border border-gray-200">
              <i class="bi bi-lock-fill me-1 text-rose-500"></i> เฉพาะแอดมินเท่านั้นที่แก้ไขตารางได้
            </div>

            <router-link to="/dashboard" class="btn btn-ghost text-gray-500 hover:bg-gray-100 w-full rounded-xl">กลับหน้าหลัก</router-link>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>