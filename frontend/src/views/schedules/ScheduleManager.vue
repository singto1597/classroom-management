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

// สิทธิ์: เห็นด้วยกับ TaskList/AddTask — ใช้ permission MANAGE_CLASSROOM_TASKS ร่วมด้วย
const canManageSchedule = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_TASKS')
)

const activeTab = ref<'default' | 'override'>('default')
const isSubmitting = ref(false)

const days = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์', 'เสาร์', 'อาทิตย์']

// ดึงวันที่ปัจจุบันแบบ Local Timezone ป้องกัน UTC Bug (แบบเดียวกับ AddTask.vue)
const getLocalDate = () => {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().split('T')[0]
}

const defaultForm = reactive({
  day_of_week: 'จันทร์',
  attire: '',
  subjects: ''
})

const overrideForm = reactive({
  target_date: getLocalDate(),
  new_attire: '',
  note: ''
})

const handleSaveDefault = async () => {
  // Guard ดักฝั่ง Script ป้องกันนักเรียนแอบยิง API
  if (!canManageSchedule.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลเท่านั้นที่แก้ไขตารางได้', 'error')
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
    Swal.fire('เกิดข้อผิดพลาด', error.response?.data?.detail || 'ไม่สามารถบันทึกตารางได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const handleSaveOverride = async () => {
  // Guard ดักฝั่ง Script
  if (!canManageSchedule.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลเท่านั้นที่แก้ไขตารางได้', 'error')
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
    Swal.fire('เกิดข้อผิดพลาด', error.response?.data?.detail || 'ไม่สามารถบันทึกข้อยกเว้นได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-3xl mx-auto">

      <!-- Header -->
      <div class="flex items-center gap-4 mb-8">
        <button
          @click="router.push('/dashboard')"
          class="w-10 h-10 bg-white rounded-full flex items-center justify-center text-slate-500 shadow-sm border border-slate-200 hover:text-slate-800 hover:shadow transition-all"
          title="กลับหน้าหลัก"
        >
          <i class="bi bi-arrow-left text-lg"></i>
        </button>
        <div>
          <h1 class="text-2xl md:text-3xl font-extrabold text-slate-800 flex items-center gap-3">
            <span class="p-2.5 bg-blue-100 rounded-2xl text-blue-600 shadow-sm">
              <i class="bi bi-calendar-check"></i>
            </span>
            จัดการตารางเรียน
          </h1>
          <p class="text-slate-500 mt-1 text-sm md:text-base">ตั้งค่าตารางเรียนยืนพื้น และข้อยกเว้นการแต่งกายรายวัน</p>
        </div>
      </div>

      <div class="bg-white rounded-[2rem] shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-slate-100 overflow-hidden">

        <!-- Tabs -->
        <div class="flex p-2 bg-slate-50/50 border-b border-slate-100">
          <button
            @click="activeTab = 'default'"
            class="flex-1 py-3.5 text-center font-bold text-sm transition-all rounded-2xl flex items-center justify-center gap-2 outline-none"
            :class="activeTab === 'default' ? 'bg-white text-blue-600 shadow-sm border border-slate-100' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100/50'"
          >
            <i class="bi bi-calendar-week text-lg"></i> ตารางปกติ
          </button>
          <button
            @click="activeTab = 'override'"
            class="flex-1 py-3.5 text-center font-bold text-sm transition-all rounded-2xl flex items-center justify-center gap-2 outline-none"
            :class="activeTab === 'override' ? 'bg-white text-rose-600 shadow-sm border border-slate-100' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-100/50'"
          >
            <i class="bi bi-exclamation-triangle text-lg"></i> ข้อยกเว้นพิเศษ
          </button>
        </div>

        <div class="p-6 md:p-10">
          <!-- ตารางปกติ -->
          <form v-if="activeTab === 'default'" @submit.prevent="handleSaveDefault" class="space-y-6">
            <h2 class="text-lg font-black text-slate-800 flex items-center gap-2">
              📅 ตั้งตารางเรียนยืนพื้น (จันทร์ - อาทิตย์)
            </h2>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-calendar3 text-blue-500"></i> วันในสัปดาห์
              </label>
              <select
                v-model="defaultForm.day_of_week"
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none font-bold"
              >
                <option v-for="day in days" :key="day" :value="day">{{ day }}</option>
              </select>
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-tshirt text-blue-500"></i> ชุดที่ต้องใส่
              </label>
              <input
                v-model="defaultForm.attire"
                type="text"
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none"
                placeholder="เช่น ชุดนักเรียน, ชุดพละ"
                required
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-book text-blue-500"></i> วิชาเรียน (เรียงตามคาบ)
              </label>
              <textarea
                v-model="defaultForm.subjects"
                class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl h-32 focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all outline-none resize-none"
                placeholder="คณิต, ไทย, อังกฤษ, พักกลางวัน, ฟิสิกส์..."
                required
              ></textarea>
            </div>

            <div class="flex flex-col gap-3 pt-2">
              <template v-if="canManageSchedule">
                <button
                  type="submit"
                  class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-blue-600/20 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                  :disabled="isSubmitting"
                >
                  <span v-if="isSubmitting" class="inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                  <template v-else><i class="bi bi-save me-1"></i> บันทึกตารางเรียน</template>
                </button>
              </template>
              <div v-else class="w-full text-center py-3.5 bg-slate-100 text-slate-500 rounded-xl font-bold border border-slate-200 flex items-center justify-center gap-2">
                <i class="bi bi-lock-fill text-rose-500"></i> เฉพาะผู้ดูแลเท่านั้นที่แก้ไขตารางได้
              </div>

              <router-link to="/dashboard" class="w-full text-center px-4 py-3 text-slate-500 hover:text-slate-800 hover:bg-slate-100 font-bold rounded-xl transition-all">
                กลับหน้าหลัก
              </router-link>
            </div>
          </form>

          <!-- ข้อยกเว้นพิเศษ -->
          <form v-else @submit.prevent="handleSaveOverride" class="space-y-6">
            <h2 class="text-lg font-black text-slate-800 flex items-center gap-2">
              🚨 ตั้งข้อยกเว้นฉุกเฉิน (เปลี่ยนชุด/กิจกรรมพิเศษ)
            </h2>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-calendar-event text-rose-500"></i> วันที่เกิดการยกเว้น
              </label>
              <input
                v-model="overrideForm.target_date"
                type="date"
                class="w-full px-4 py-3 bg-rose-50/30 border border-rose-200/60 rounded-xl focus:bg-white focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all outline-none font-bold"
                required
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-tshirt text-rose-500"></i> ชุดใหม่ที่ต้องใส่
              </label>
              <input
                v-model="overrideForm.new_attire"
                type="text"
                class="w-full px-4 py-3 bg-rose-50/30 border border-rose-200/60 rounded-xl focus:bg-white focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all outline-none"
                placeholder="เช่น ชุดนักเรียน, ชุดพละ"
                required
              />
            </div>

            <div class="space-y-2">
              <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-megaphone text-rose-500"></i> หมายเหตุ / สาเหตุที่เปลี่ยน
              </label>
              <textarea
                v-model="overrideForm.note"
                class="w-full px-4 py-3 bg-rose-50/30 border border-rose-200/60 rounded-xl h-32 focus:bg-white focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all outline-none resize-none"
                placeholder="เช่น มีกิจกรรม...จึงต้องใส่ชุดนักเรียน"
                required
              ></textarea>
            </div>

            <div class="flex flex-col gap-3 pt-2">
              <template v-if="canManageSchedule">
                <button
                  type="submit"
                  class="w-full bg-rose-600 hover:bg-rose-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-rose-600/20 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                  :disabled="isSubmitting"
                >
                  <span v-if="isSubmitting" class="inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                  <template v-else><i class="bi bi-save me-1"></i> บันทึกข้อยกเว้น</template>
                </button>
              </template>
              <div v-else class="w-full text-center py-3.5 bg-slate-100 text-slate-500 rounded-xl font-bold border border-slate-200 flex items-center justify-center gap-2">
                <i class="bi bi-lock-fill text-rose-500"></i> เฉพาะผู้ดูแลเท่านั้นที่แก้ไขตารางได้
              </div>

              <router-link to="/dashboard" class="w-full text-center px-4 py-3 text-slate-500 hover:text-slate-800 hover:bg-slate-100 font-bold rounded-xl transition-all">
                กลับหน้าหลัก
              </router-link>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>
