<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import PageHeader from '@/components/ui/PageHeader.vue'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

// ดึงข้อความ error จาก backend แบบปลอดภัย (catch ได้ unknown) — คงรูปแบบเดิมของโปรเจค
// ที่อ่าน detail จาก response ของ axios ไว้
const apiErrorDetail = (error: unknown): string | undefined => {
  if (!isAxiosError<{ detail?: unknown }>(error)) return undefined
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : undefined
}

// --- นำ Mock Data ออก แล้วดึงจาก Store ---
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

// สิทธิ์: แอดมิน หรือผู้ที่มี permission จัดการนักเรียน
const canManageStudents = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_STUDENTS')
)

// --- State ---
const activeTab = ref<'single' | 'bulk'>('single')
const isSubmitting = ref(false)

// Form Single
const singleForm = ref({
  student_no: '',
  first_name: '',
  last_name: '',
  nickname: '',
  first_name_en: '',
  last_name_en: '',
  nickname_en: ''
})

// Form Bulk
const bulkData = ref('')

// --- Methods ---
const submitSingle = async () => {
  if (!canManageStudents.value) {
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้นที่เพิ่มข้อมูลนักเรียนได้',
      confirmButtonColor: '#1d4ed8'
    })
  }

  if (!singleForm.value.student_no || !singleForm.value.first_name || !singleForm.value.last_name) {
    Swal.fire({ icon: 'warning', title: 'กรุณากรอกข้อมูลให้ครบ', confirmButtonColor: '#1d4ed8' })
    return
  }

  isSubmitting.value = true
  try {
    await StudentService.addStudent(currentRoomId, {
      student_no: parseInt(singleForm.value.student_no),
      first_name: singleForm.value.first_name,
      last_name: singleForm.value.last_name,
      nickname: singleForm.value.nickname,
      first_name_en: singleForm.value.first_name_en,
      last_name_en: singleForm.value.last_name_en,
      nickname_en: singleForm.value.nickname_en,
      user_name: currentUserName
    })
    await Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: 'เพิ่มนักเรียนเรียบร้อยแล้ว (ถ้าเป็นผู้ใช้จริง ระบบจะส่งคำเชิญให้เขายืนยันตัวตนก่อนถึงเปิดข้อมูลส่วนตัว)',
      confirmButtonColor: '#1d4ed8'
    })
    router.push('/students')
  } catch (error: unknown) {
    Swal.fire({
      icon: 'error',
      title: 'เกิดข้อผิดพลาด',
      text: apiErrorDetail(error) || 'ไม่สามารถเพิ่มข้อมูลได้',
      confirmButtonColor: '#1d4ed8'
    })
  } finally {
    isSubmitting.value = false
  }
}

const submitBulk = async () => {
  if (!canManageStudents.value) {
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้นที่เพิ่มข้อมูลนักเรียนได้',
      confirmButtonColor: '#1d4ed8'
    })
  }

  if (!bulkData.value.trim()) {
    Swal.fire({ icon: 'warning', title: 'กรุณาใส่ข้อมูล', confirmButtonColor: '#1d4ed8' })
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
    await Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: `เพิ่มนักเรียนรวดเดียว ${students.length} คน เรียบร้อยแล้ว (ผู้ใช้จริงจะได้รับคำเชิญให้ยืนยันตัวตนก่อนเปิดข้อมูลส่วนตัว)`,
      confirmButtonColor: '#1d4ed8'
    })
    router.push('/students')
  } catch (error: unknown) {
    const errorMessage = error instanceof Error ? error.message : undefined
    Swal.fire({
      icon: 'error',
      title: 'เกิดข้อผิดพลาด',
      text: errorMessage || apiErrorDetail(error) || 'ไม่สามารถเพิ่มข้อมูลได้',
      confirmButtonColor: '#1d4ed8'
    })
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">

    <PageHeader
      eyebrow="New Student"
      title="เพิ่มนักเรียนใหม่"
      description="เพิ่มรายชื่อเพื่อนในห้องคนเดียว หรือนำเข้าแบบรวดเดียว"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" @click="router.back()">
          <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับ
        </button>
      </template>
    </PageHeader>

    <div class="page-card overflow-hidden">
      <!-- แท็บ -->
      <div role="tablist" class="flex border-b border-stone-200">
        <button
          type="button"
          role="tab"
          :aria-selected="activeTab === 'single'"
          class="flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap border-b-2 px-2 py-3 text-sm font-bold transition-colors"
          :class="activeTab === 'single'
            ? 'border-brand-700 text-brand-700'
            : 'border-transparent text-stone-400 hover:text-stone-700'"
          @click="activeTab = 'single'"
        >
          <i class="bi bi-person-fill" aria-hidden="true"></i> เพิ่มทีละคน
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="activeTab === 'bulk'"
          class="flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap border-b-2 px-2 py-3 text-sm font-bold transition-colors"
          :class="activeTab === 'bulk'
            ? 'border-brand-700 text-brand-700'
            : 'border-transparent text-stone-400 hover:text-stone-700'"
          @click="activeTab = 'bulk'"
        >
          <i class="bi bi-people-fill" aria-hidden="true"></i> เพิ่มรวดเดียว<span class="hidden sm:inline"> (Bulk)</span>
        </button>
      </div>

      <!-- ฟอร์ม: เพิ่มทีละคน -->
      <div v-if="activeTab === 'single'" class="space-y-4 p-4 sm:p-6">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3">
          <div>
            <label class="field-label" for="studentNo">เลขที่ <span class="text-red-500">*</span></label>
            <input id="studentNo" v-model="singleForm.student_no" type="number" class="field" placeholder="เช่น 1" />
          </div>

          <div>
            <label class="field-label" for="firstName">ชื่อจริง <span class="text-red-500">*</span></label>
            <input id="firstName" v-model="singleForm.first_name" type="text" class="field" placeholder="สมชาย" />
          </div>

          <div>
            <label class="field-label" for="lastName">นามสกุล <span class="text-red-500">*</span></label>
            <input id="lastName" v-model="singleForm.last_name" type="text" class="field" placeholder="รักเรียน" />
          </div>

          <div>
            <label class="field-label" for="nickname">
              ชื่อเล่น <span class="font-normal text-stone-400">ไม่บังคับ</span>
            </label>
            <input id="nickname" v-model="singleForm.nickname" type="text" class="field" placeholder="โอม" />
          </div>

          <div>
            <label class="field-label" for="firstNameEn">
              ชื่อจริง (อังกฤษ) <span class="font-normal text-stone-400">ไม่บังคับ</span>
            </label>
            <input id="firstNameEn" v-model="singleForm.first_name_en" type="text" class="field" placeholder="Somchai" />
          </div>

          <div>
            <label class="field-label" for="lastNameEn">
              นามสกุล (อังกฤษ) <span class="font-normal text-stone-400">ไม่บังคับ</span>
            </label>
            <input id="lastNameEn" v-model="singleForm.last_name_en" type="text" class="field" placeholder="Jaidee" />
          </div>

          <div>
            <label class="field-label" for="nicknameEn">
              ชื่อเล่น (อังกฤษ) <span class="font-normal text-stone-400">ไม่บังคับ</span>
            </label>
            <input id="nicknameEn" v-model="singleForm.nickname_en" type="text" class="field" placeholder="Om" />
          </div>
        </div>

        <div class="border-t border-stone-100 pt-3 sm:pt-4">
          <button
            v-if="canManageStudents"
            type="button"
            class="btn-primary w-full sm:w-auto"
            :disabled="isSubmitting"
            @click="submitSingle"
          >
            <span
              v-if="isSubmitting"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
              aria-hidden="true"
            ></span>
            <i v-else class="bi bi-check-lg" aria-hidden="true"></i>
            บันทึกข้อมูล
          </button>
          <div
            v-else
            class="flex items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 p-4 text-sm font-bold text-stone-500"
          >
            <i class="bi bi-lock-fill text-red-500" aria-hidden="true"></i> เฉพาะแอดมินเท่านั้น
          </div>
        </div>
      </div>

      <!-- ฟอร์ม: นำเข้ารวดเดียว -->
      <div v-else class="space-y-4 p-4 sm:p-6">
        <div class="rounded-xl border border-sky-200 bg-sky-50 p-4">
          <p class="flex items-center gap-1.5 text-sm font-bold text-sky-800">
            <i class="bi bi-info-circle-fill" aria-hidden="true"></i> คำแนะนำการใช้งาน
          </p>
          <p class="mt-1 text-xs text-sky-700">
            วางข้อมูลในรูปแบบ: <code class="rounded bg-sky-100 px-1 font-bold">เลขที่,ชื่อ,นามสกุล</code> (หนึ่งคนต่อหนึ่งบรรทัด)
          </p>
        </div>

        <div>
          <label class="field-label" for="bulkData">ข้อมูลนักเรียน (CSV Format)</label>
          <textarea
            id="bulkData"
            v-model="bulkData"
            rows="10"
            class="field font-mono"
            placeholder="1,สมชาย,รักเรียน&#10;2,สมหญิง,ขยันดี"
          ></textarea>
        </div>

        <div class="border-t border-stone-100 pt-3 sm:pt-4">
          <button
            v-if="canManageStudents"
            type="button"
            class="btn-primary w-full sm:w-auto"
            :disabled="isSubmitting"
            @click="submitBulk"
          >
            <span
              v-if="isSubmitting"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
              aria-hidden="true"
            ></span>
            <i v-else class="bi bi-rocket-takeoff-fill" aria-hidden="true"></i>
            นำเข้าข้อมูลทั้งหมด
          </button>
          <div
            v-else
            class="flex items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 p-4 text-sm font-bold text-stone-500"
          >
            <i class="bi bi-lock-fill text-red-500" aria-hidden="true"></i> เฉพาะแอดมินเท่านั้น
          </div>
        </div>
      </div>
    </div>

  </div>
</template>
