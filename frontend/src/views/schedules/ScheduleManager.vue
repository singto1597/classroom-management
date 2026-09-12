<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { ScheduleService } from '@/services/schedule'
import Swal from 'sweetalert2'
import PageHeader from '@/components/ui/PageHeader.vue'

const authStore = useAuthStore()

// ดึงข้อความ error จาก backend แบบปลอดภัย (catch ได้ unknown) — คงรูปแบบเดิมของโปรเจค
// ที่อ่าน detail จาก response ของ axios ไว้
const apiErrorDetail = (error: unknown): string | undefined => {
  if (!isAxiosError<{ detail?: unknown }>(error)) return undefined
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : undefined
}

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
const getLocalDate = (): string => {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  const [datePart] = date.toISOString().split('T')
  return datePart ?? ''
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
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถบันทึกตารางได้', 'error')
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
      ...overrideForm,
      user_name: currentUserName
    })
    Swal.fire({
      icon: 'success',
      title: `ตั้งข้อยกเว้นสำหรับวันที่ ${overrideForm.target_date} เรียบร้อย!`,
      timer: 2000,
      showConfirmButton: false
    })
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถบันทึกข้อยกเว้นได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <!-- ไม่มีปุ่มใน #actions: ปุ่ม "กลับหน้าหลัก" ที่ท้ายฟอร์มเป็นทางออกเดียวของหน้านี้ -->
    <PageHeader
      eyebrow="Class Schedule"
      title="จัดการตารางเรียน"
      description="ตั้งค่าตารางเรียนยืนพื้น และข้อยกเว้นการแต่งกายรายวัน"
    />

    <div class="page-card overflow-hidden">
      <!-- สลับโหมด: ตารางปกติ / ข้อยกเว้น -->
      <div class="border-b border-stone-100 p-3 sm:p-4">
        <div class="flex items-center gap-1 rounded-xl bg-stone-100 p-1">
          <button
            type="button"
            class="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="activeTab === 'default' ? 'bg-brand-50 text-brand-700' : 'text-stone-500 hover:bg-stone-200/60 hover:text-stone-900'"
            @click="activeTab = 'default'"
          >
            <i class="bi bi-calendar-week text-base" aria-hidden="true"></i>
            ตารางปกติ
          </button>
          <button
            type="button"
            class="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="activeTab === 'override' ? 'bg-brand-50 text-brand-700' : 'text-stone-500 hover:bg-stone-200/60 hover:text-stone-900'"
            @click="activeTab = 'override'"
          >
            <i class="bi bi-exclamation-triangle text-base" aria-hidden="true"></i>
            ข้อยกเว้นพิเศษ
          </button>
        </div>
      </div>

      <div class="p-4 sm:p-6">
        <!-- ตารางเรียนยืนพื้น -->
        <form v-if="activeTab === 'default'" class="space-y-4" @submit.prevent="handleSaveDefault">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-calendar-week text-brand-700" aria-hidden="true"></i>
            ตั้งตารางเรียนยืนพื้น (จันทร์ - อาทิตย์)
          </h2>

          <div class="space-y-3.5 border-t border-stone-100 pt-3 sm:pt-4">
            <div>
              <label class="field-label" for="dayOfWeek">วันในสัปดาห์</label>
              <select id="dayOfWeek" v-model="defaultForm.day_of_week" class="field font-bold">
                <option v-for="day in days" :key="day" :value="day">{{ day }}</option>
              </select>
            </div>

            <div>
              <label class="field-label" for="attire">ชุดที่ต้องใส่</label>
              <input
                id="attire"
                v-model="defaultForm.attire"
                type="text"
                class="field"
                placeholder="เช่น ชุดนักเรียน, ชุดพละ"
                required
              />
            </div>

            <div>
              <label class="field-label" for="subjects">วิชาเรียน (เรียงตามคาบ)</label>
              <textarea
                id="subjects"
                v-model="defaultForm.subjects"
                class="field h-32 resize-none"
                placeholder="คณิต, ไทย, อังกฤษ, พักกลางวัน, ฟิสิกส์..."
                required
              ></textarea>
            </div>
          </div>

          <div class="flex flex-col-reverse gap-2 border-t border-stone-100 pt-3 sm:flex-row sm:items-center sm:justify-end sm:pt-4">
            <RouterLink to="/dashboard" class="btn-ghost-ui w-full sm:w-auto">
              กลับหน้าหลัก
            </RouterLink>
            <template v-if="canManageSchedule">
              <button
                type="submit"
                class="btn-primary w-full sm:w-auto sm:min-w-[11rem]"
                :disabled="isSubmitting"
              >
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                <i v-else class="bi bi-save" aria-hidden="true" />
                {{ isSubmitting ? 'กำลังบันทึก...' : 'บันทึกตารางเรียน' }}
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 py-3 text-sm font-bold text-stone-500 sm:w-auto"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะผู้ดูแลเท่านั้นที่แก้ไขตารางได้
            </div>
          </div>
        </form>

        <!-- ข้อยกเว้นพิเศษรายวัน -->
        <form v-else class="space-y-4" @submit.prevent="handleSaveOverride">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="section-title flex items-center gap-2">
              <i class="bi bi-exclamation-triangle text-amber-600" aria-hidden="true"></i>
              ตั้งข้อยกเว้นฉุกเฉิน (เปลี่ยนชุด/กิจกรรมพิเศษ)
            </h2>
          </div>

          <div class="space-y-3.5 border-t border-stone-100 pt-3 sm:pt-4">
            <div>
              <label class="field-label" for="overrideDate">วันที่เกิดการยกเว้น</label>
              <input
                id="overrideDate"
                v-model="overrideForm.target_date"
                type="date"
                class="field font-bold"
                required
              />
            </div>

            <div>
              <label class="field-label" for="newAttire">ชุดใหม่ที่ต้องใส่</label>
              <input
                id="newAttire"
                v-model="overrideForm.new_attire"
                type="text"
                class="field"
                placeholder="เช่น ชุดนักเรียน, ชุดพละ"
                required
              />
            </div>

            <div>
              <label class="field-label" for="overrideNote">หมายเหตุ / สาเหตุที่เปลี่ยน</label>
              <textarea
                id="overrideNote"
                v-model="overrideForm.note"
                class="field h-32 resize-none"
                placeholder="เช่น มีกิจกรรม...จึงต้องใส่ชุดนักเรียน"
                required
              ></textarea>
            </div>
          </div>

          <div class="flex flex-col-reverse gap-2 border-t border-stone-100 pt-3 sm:flex-row sm:items-center sm:justify-end sm:pt-4">
            <RouterLink to="/dashboard" class="btn-ghost-ui w-full sm:w-auto">
              กลับหน้าหลัก
            </RouterLink>
            <template v-if="canManageSchedule">
              <button
                type="submit"
                class="btn-primary w-full sm:w-auto sm:min-w-[11rem]"
                :disabled="isSubmitting"
              >
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                <i v-else class="bi bi-save" aria-hidden="true" />
                {{ isSubmitting ? 'กำลังบันทึก...' : 'บันทึกข้อยกเว้น' }}
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 py-3 text-sm font-bold text-stone-500 sm:w-auto"
            >
              <i class="bi bi-lock-fill" aria-hidden="true" /> เฉพาะผู้ดูแลเท่านั้นที่แก้ไขตารางได้
            </div>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
