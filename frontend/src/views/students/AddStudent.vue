<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

// --- นำ Mock Data ออก แล้วดึงจาก Store ---
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

// --- State ---
const activeTab = ref<'single' | 'bulk'>('single')
const isSubmitting = ref(false)

// Form Single
const singleForm = ref({
  student_no: '',
  first_name: '',
  last_name: ''
})

// Form Bulk
const bulkData = ref('')

// --- Methods ---
const submitSingle = async () => {
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่เพิ่มข้อมูลนักเรียนได้', 'error')
  }

  if (!singleForm.value.student_no || !singleForm.value.first_name || !singleForm.value.last_name) {
    Swal.fire('กรุณากรอกข้อมูลให้ครบ', '', 'warning')
    return
  }

  isSubmitting.value = true
  try {
    await StudentService.addStudent(currentRoomId, {
      student_no: parseInt(singleForm.value.student_no),
      first_name: singleForm.value.first_name,
      last_name: singleForm.value.last_name,
      user_name: currentUserName
    })
    await Swal.fire('สำเร็จ!', 'เพิ่มนักเรียนเรียบร้อยแล้ว', 'success')
    router.push('/students')
  } catch (error: any) {
    Swal.fire('เกิดข้อผิดพลาด', error.response?.data?.detail || 'ไม่สามารถเพิ่มข้อมูลได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const submitBulk = async () => {
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่เพิ่มข้อมูลนักเรียนได้', 'error')
  }

  if (!bulkData.value.trim()) {
    Swal.fire('กรุณาใส่ข้อมูล', '', 'warning')
    return
  }

  isSubmitting.value = true
  try {
    const lines = bulkData.value.trim().split('\n')
    const students = lines
      .map((line) => {
        const [no, first, last] = line.split(',').map((s) => s.trim())
        if (no && first && last) {
          return {
            student_no: parseInt(no),
            first_name: first,
            last_name: last
          }
        }
        return null
      })
      .filter((s) => s !== null)

    if (students.length === 0) {
      throw new Error('รูปแบบข้อมูลไม่ถูกต้อง (ต้องเป็น: เลขที่,ชื่อ,นามสกุล)')
    }

    await StudentService.bulkAddStudents(currentRoomId, students, currentUserName)
    await Swal.fire('สำเร็จ!', `เพิ่มนักเรียนรวดเดียว ${students.length} คน เรียบร้อยแล้ว`, 'success')
    router.push('/students')
  } catch (error: any) {
    Swal.fire('เกิดข้อผิดพลาด', error.message || error.response?.data?.detail || 'ไม่สามารถเพิ่มข้อมูลได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="p-6 max-w-4xl mx-auto">
    <div class="flex items-center gap-4 mb-8">
      <button 
        @click="router.back()" 
        class="p-2 hover:bg-gray-100 rounded-full transition-colors text-gray-600"
      >
        <i class="bi bi-arrow-left text-xl"></i>
      </button>
      <h1 class="text-2xl font-bold text-gray-800">เพิ่มนักเรียนใหม่</h1>
    </div>

    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      <div class="flex border-b border-gray-100">
        <button
          @click="activeTab = 'single'"
          class="flex-1 py-4 text-sm font-bold transition-all border-b-2"
          :class="activeTab === 'single' ? 'border-blue-600 text-blue-600 bg-blue-50/30' : 'border-transparent text-gray-400 hover:text-gray-600'"
        >
          <i class="bi bi-person-fill me-2"></i>เพิ่มทีละคน
        </button>
        <button
          @click="activeTab = 'bulk'"
          class="flex-1 py-4 text-sm font-bold transition-all border-b-2"
          :class="activeTab === 'bulk' ? 'border-blue-600 text-blue-600 bg-blue-50/30' : 'border-transparent text-gray-400 hover:text-gray-600'"
        >
          <i class="bi bi-people-fill me-2"></i>เพิ่มรวดเดียว (Bulk)
        </button>
      </div>

      <div class="p-8">
        <div v-if="activeTab === 'single'" class="space-y-6">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="space-y-2">
              <label class="text-sm font-bold text-gray-700">เลขที่</label>
              <input
                v-model="singleForm.student_no"
                type="number"
                placeholder="เช่น 1"
                class="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
              />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-bold text-gray-700">ชื่อจริง</label>
              <input
                v-model="singleForm.first_name"
                type="text"
                placeholder="สมชาย"
                class="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
              />
            </div>
            <div class="space-y-2">
              <label class="text-sm font-bold text-gray-700">นามสกุล</label>
              <input
                v-model="singleForm.last_name"
                type="text"
                placeholder="รักเรียน"
                class="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
              />
            </div>
          </div>
          <div class="pt-4">
            <template v-if="isAdmin">
              <button
                @click="submitSingle"
                :disabled="isSubmitting"
                class="w-full md:w-auto px-8 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-bold rounded-xl shadow-lg shadow-blue-200 transition-all flex items-center justify-center"
              >
                <span v-if="isSubmitting" class="animate-spin me-2"><i class="bi bi-arrow-repeat"></i></span>
                <i v-else class="bi bi-check-lg me-2"></i> บันทึกข้อมูล
              </button>
            </template>
            <div v-else class="text-center p-4 bg-gray-50 text-gray-500 rounded-xl font-bold border border-gray-200 inline-block w-full md:w-auto">
              <i class="bi bi-lock-fill me-1 text-rose-500"></i> เฉพาะแอดมินเท่านั้น
            </div>
          </div>
        </div>

        <div v-if="activeTab === 'bulk'" class="space-y-6">
          <div class="bg-amber-50 border border-amber-200 p-4 rounded-xl mb-4">
            <h4 class="text-amber-800 font-bold text-sm mb-1"><i class="bi bi-info-circle-fill me-1"></i> คำแนะนำการใช้งาน:</h4>
            <p class="text-amber-700 text-xs">วางข้อมูลในรูปแบบ: <code class="bg-amber-100 px-1 rounded font-bold">เลขที่,ชื่อ,นามสกุล</code> (หนึ่งคนต่อหนึ่งบรรทัด)</p>
          </div>
          <div class="space-y-2">
            <label class="text-sm font-bold text-gray-700">ข้อมูลนักเรียน (CSV Format)</label>
            <textarea
              v-model="bulkData"
              rows="10"
              placeholder="1,สมชาย,รักเรียน&#10;2,สมหญิง,ขยันดี"
              class="w-full px-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all font-mono text-sm"
            ></textarea>
          </div>
          <div class="pt-4">
            <template v-if="isAdmin">
              <button
                @click="submitBulk"
                :disabled="isSubmitting"
                class="w-full md:w-auto px-8 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-bold rounded-xl shadow-lg shadow-blue-200 transition-all flex items-center justify-center"
              >
                <span v-if="isSubmitting" class="animate-spin me-2"><i class="bi bi-arrow-repeat"></i></span>
                <i v-else class="bi bi-rocket-takeoff-fill me-2"></i> นำเข้าข้อมูลทั้งหมด
              </button>
            </template>
            <div v-else class="text-center p-4 bg-gray-50 text-gray-500 rounded-xl font-bold border border-gray-200 inline-block w-full md:w-auto">
              <i class="bi bi-lock-fill me-1 text-rose-500"></i> เฉพาะแอดมินเท่านั้น
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>