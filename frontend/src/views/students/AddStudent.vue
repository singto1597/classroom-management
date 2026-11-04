<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import PageIntro from '@/components/ui/PageIntro.vue'
import AppTabs from '@/components/ui/AppTabs.vue'
import FormSuccess from '@/components/ui/FormSuccess.vue'
import { useDialog } from '@/composables/useDialog'
import { confirmLeave, useFormDraft, useUnsavedGuard } from '@/composables/useFormDraft'

const authStore = useAuthStore()
const dialog = useDialog()

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
const tabs = [
  { value: 'single', label: 'เพิ่มทีละคน' },
  { value: 'bulk', label: 'เพิ่มรวดเดียว (Bulk)' },
] as const
const isSubmitting = ref(false)
const setTab = (value: string) => {
  activeTab.value = value === 'bulk' ? 'bulk' : 'single'
}

/**
 * 🪜 3 ขั้นตอน: ข้อมูลบังคับ → ข้อมูลเสริม → ตรวจสอบ
 * เดิมกรอกทั้ง 7 ช่องในหน้าเดียว ⇒ บนมือถือต้องเลื่อนผ่านช่องที่ไม่บังคับ 4 ช่อง
 * กว่าจะเจอปุ่มบันทึก และไม่รู้ว่าขาดอะไรจนกดแล้วขึ้น Swal
 */
const STEPS = ['ข้อมูลหลัก', 'รายละเอียด', 'ตรวจสอบ'] as const
const step = ref(0)
const showErrors = ref(false)
// แตะแล้วแต่ยังไม่กรอก → แสดงข้อความทันที (ปุ่มถัดไปถูก disable ตั้งแต่แรก)
const touched = reactive({ no: false, first: false, last: false })
const submitted = ref<{ title: string; hint: string } | null>(null)

// Form Single
const singleForm = reactive({
  student_no: '',
  first_name: '',
  last_name: '',
  nickname: '',
  first_name_en: '',
  last_name_en: '',
  nickname_en: '',
})

// Form Bulk
const bulkData = ref('')

const draftKey = computed(() => `cls:draft:add-student:${currentRoomId}`)
const draft = useFormDraft(
  singleForm,
  () => draftKey.value,
  () => activeTab.value === 'single' && canManageStudents.value
)

onMounted(() => {
  if (draft.restore()) {
    // ผู้ใช้ไม่ได้กดอะไร — บอกให้รู้ว่ากู้ข้อมูลเดิมมา ไม่ใช่พิมพ์ค้างไว้
    step.value = 0
  }
})

const hasAnyInput = () =>
  Object.values(singleForm).some((value) => String(value).trim() !== '')

// เตือนเฉพาะเมื่อมีอะไรค้างจริง และยังไม่บันทึกสำเร็จ
useUnsavedGuard(() => hasAnyInput() && !submitted.value)
onBeforeRouteLeave(() => confirmLeave(() => hasAnyInput() && !submitted.value))

const noError = computed(() => {
  const value = singleForm.student_no.trim()
  if (!value) return 'กรุณากรอกเลขที่'
  const number = Number(value)
  if (!Number.isInteger(number) || number <= 0) return 'เลขที่ต้องเป็นจำนวนเต็มมากกว่า 0'
  return ''
})
const firstNameError = computed(() =>
  singleForm.first_name.trim() ? '' : 'กรุณากรอกชื่อจริง'
)
const lastNameError = computed(() =>
  singleForm.last_name.trim() ? '' : 'กรุณากรอกนามสกุล'
)

const stepValid = computed(() => {
  if (step.value === 0) return !noError.value && !firstNameError.value && !lastNameError.value
  return true
})

const goNext = () => {
  if (!stepValid.value) {
    showErrors.value = true
    return
  }
  showErrors.value = false
  if (step.value < STEPS.length - 1) step.value += 1
}

const goBack = () => {
  showErrors.value = false
  if (step.value > 0) step.value -= 1
}

const resetForm = () => {
  Object.assign(singleForm, {
    student_no: '',
    first_name: '',
    last_name: '',
    nickname: '',
    first_name_en: '',
    last_name_en: '',
    nickname_en: '',
  })
  step.value = 0
  showErrors.value = false
  draft.clear()
}

// --- Methods ---
const submitSingle = async () => {
  if (!canManageStudents.value) {
    return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่เพิ่มข้อมูลนักเรียนได้', 'error')
  }

  if (!stepValid.value) {
    showErrors.value = true
    step.value = 0
    return
  }

  isSubmitting.value = true
  try {
    await StudentService.addStudent(currentRoomId, {
      student_no: parseInt(singleForm.student_no),
      first_name: singleForm.first_name.trim(),
      last_name: singleForm.last_name.trim(),
      nickname: singleForm.nickname.trim(),
      first_name_en: singleForm.first_name_en.trim(),
      last_name_en: singleForm.last_name_en.trim(),
      nickname_en: singleForm.nickname_en.trim(),
      user_name: currentUserName,
    })
    // ✅ เก็บผลลัพธ์ไว้บนจอ ไม่ใช่ Swal ที่หายเองใน 1.5 วิ — ผู้ใช้ต้องอ่านรหัส/ไปต่อได้
    submitted.value = {
      title: 'เพิ่มนักเรียนเรียบร้อยแล้ว',
      hint: `เลขที่ ${singleForm.student_no} · ${singleForm.first_name} ${singleForm.last_name} เข้าใช้งานห้องได้ทันที (บัญชีจริงจะได้รับคำเชิญให้ยืนยันตัวตน — ไม่บล็อกการใช้งาน)`,
    }
    draft.clear()
  } catch (error: unknown) {
    void dialog.alert('เกิดข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถเพิ่มข้อมูลได้', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const submitBulk = async () => {
  if (!canManageStudents.value) {
    return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่เพิ่มข้อมูลนักเรียนได้', 'error')
  }

  if (!bulkData.value.trim()) {
    void dialog.alert('กรุณาใส่ข้อมูล', undefined, 'warning')
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
            last_name: last,
          }
        }
        return null
      })
      .filter((s) => s !== null)

    if (students.length === 0) {
      throw new Error('รูปแบบข้อมูลไม่ถูกต้อง (ต้องเป็น: เลขที่,ชื่อ,นามสกุล)')
    }

    await StudentService.bulkAddStudents(currentRoomId, students, currentUserName)
    submitted.value = {
      title: `นำเข้านักเรียน ${students.length} คนเรียบร้อยแล้ว`,
      hint: 'ทุกคนเข้าใช้งานห้องได้ทันที · บัญชีจริงจะได้รับคำเชิญให้ยืนยันตัวตน (ไม่บล็อกการใช้งาน)',
    }
    bulkData.value = ''
  } catch (error: unknown) {
    const errorMessage = error instanceof Error ? error.message : undefined
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      errorMessage || apiErrorDetail(error) || 'ไม่สามารถเพิ่มข้อมูลได้',
      'error'
    )
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="เพิ่มรายชื่อเพื่อนในห้องคนเดียว หรือนำเข้าแบบรวดเดียว"
    ></PageIntro>

    <!-- ✅ หน้ายืนยันสำเร็จ — ค้างไว้ให้อ่านและไปต่อ -->
    <FormSuccess
      v-if="submitted"
      :title="submitted.title"
      :hint="submitted.hint"
    >
      <RouterLink to="/students" class="btn-primary">
        <i class="bi bi-people-fill" aria-hidden="true" /> ดูรายชื่อนักเรียน
      </RouterLink>
      <button
        v-if="activeTab === 'single'"
        type="button"
        class="btn-ghost-ui"
        @click="
          () => {
            submitted = null
            resetForm()
          }
        "
      >
        <i class="bi bi-plus-lg" aria-hidden="true" /> เพิ่มอีกคน
      </button>
      <button v-else type="button" class="btn-ghost-ui" @click="submitted = null">
        <i class="bi bi-plus-lg" aria-hidden="true" /> นำเข้าอีกครั้ง
      </button>
    </FormSuccess>

    <div v-else class="page-card overflow-hidden">
      <!-- แท็บ -->
      <div class="px-4 pt-2 sm:px-6">
        <AppTabs
          :model-value="activeTab"
          :tabs="tabs"
          group-label="วิธีเพิ่มนักเรียน"
          @update:model-value="setTab"
        />
      </div>

      <!-- ฟอร์ม: เพิ่มทีละคน (3 ขั้น) -->
      <div v-if="activeTab === 'single'" class="p-4 sm:p-6">
        <!-- ความคืบหน้า — เห็นตลอดว่าอยู่ขั้นไหน เหลืออีกกี่ขั้น -->
        <ol class="mb-5 flex items-center gap-2" aria-label="ขั้นตอนการเพิ่มนักเรียน">
          <li
            v-for="(label, index) in STEPS"
            :key="label"
            class="min-w-0 flex-1"
            :aria-current="step === index ? 'step' : undefined"
          >
            <div
              class="h-1.5 rounded-full transition-colors"
              :class="index <= step ? 'bg-brand-700' : 'bg-line'"
            ></div>
            <p
              class="mt-1.5 truncate text-xs font-bold"
              :class="index === step ? 'text-brand-700' : 'text-ink-3'"
            >
              {{ index + 1 }}. {{ label }}
            </p>
          </li>
        </ol>

        <form class="space-y-4" @submit.prevent="step === STEPS.length - 1 ? submitSingle() : goNext()">
          <!-- ขั้นที่ 1: ข้อมูลบังคับ -->
          <div v-if="step === 0" class="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
            <div>
              <label class="field-label" for="studentNo">เลขที่ <span class="text-danger-500">*</span></label>
              <input
                id="studentNo"
                v-model="singleForm.student_no"
                type="number"
                inputmode="numeric"
                class="field"
                placeholder="เช่น 1"
                :aria-invalid="(showErrors || touched.no) && !!noError"
                :aria-describedby="(showErrors || touched.no) && noError ? 'studentNoError' : undefined"
                @blur="touched.no = true"
              />
              <p v-if="(showErrors || touched.no) && noError" id="studentNoError" class="mt-1 text-xs font-bold text-danger-600">
                {{ noError }}
              </p>
            </div>

            <div>
              <label class="field-label" for="firstName">ชื่อจริง <span class="text-danger-500">*</span></label>
              <input
                id="firstName"
                v-model="singleForm.first_name"
                type="text"
                class="field"
                placeholder="สมชาย"
                :aria-invalid="(showErrors || touched.first) && !!firstNameError"
                :aria-describedby="(showErrors || touched.first) && firstNameError ? 'firstNameError' : undefined"
                @blur="touched.first = true"
              />
              <p v-if="(showErrors || touched.first) && firstNameError" id="firstNameError" class="mt-1 text-xs font-bold text-danger-600">
                {{ firstNameError }}
              </p>
            </div>

            <div>
              <label class="field-label" for="lastName">นามสกุล <span class="text-danger-500">*</span></label>
              <input
                id="lastName"
                v-model="singleForm.last_name"
                type="text"
                class="field"
                placeholder="รักเรียน"
                :aria-invalid="(showErrors || touched.last) && !!lastNameError"
                :aria-describedby="(showErrors || touched.last) && lastNameError ? 'lastNameError' : undefined"
                @blur="touched.last = true"
              />
              <p v-if="(showErrors || touched.last) && lastNameError" id="lastNameError" class="mt-1 text-xs font-bold text-danger-600">
                {{ lastNameError }}
              </p>
            </div>
          </div>

          <!-- ขั้นที่ 2: ข้อมูลเสริม -->
          <div v-else-if="step === 1" class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
            <div>
              <label class="field-label" for="nickname">
                ชื่อเล่น <span class="font-normal text-ink-3">ไม่บังคับ</span>
              </label>
              <input id="nickname" v-model="singleForm.nickname" type="text" class="field" placeholder="โอม" />
            </div>

            <div>
              <label class="field-label" for="nicknameEn">
                ชื่อเล่น (อังกฤษ) <span class="font-normal text-ink-3">ไม่บังคับ</span>
              </label>
              <input id="nicknameEn" v-model="singleForm.nickname_en" type="text" class="field" placeholder="Om" />
            </div>

            <div>
              <label class="field-label" for="firstNameEn">
                ชื่อจริง (อังกฤษ) <span class="font-normal text-ink-3">ไม่บังคับ</span>
              </label>
              <input id="firstNameEn" v-model="singleForm.first_name_en" type="text" class="field" placeholder="Somchai" />
            </div>

            <div>
              <label class="field-label" for="lastNameEn">
                นามสกุล (อังกฤษ) <span class="font-normal text-ink-3">ไม่บังคับ</span>
              </label>
              <input id="lastNameEn" v-model="singleForm.last_name_en" type="text" class="field" placeholder="Jaidee" />
            </div>

            <p class="text-xs leading-relaxed text-ink-3 sm:col-span-2">
              ชื่อภาษาอังกฤษใช้แสดงบนใบรายชื่อ/ใบเสร็จ — เว้นว่างได้ถ้าไม่จำเป็น
            </p>
          </div>

          <!-- ขั้นที่ 3: ตรวจสอบก่อนบันทึก -->
          <div v-else>
            <h2 class="section-title">ตรวจสอบข้อมูล</h2>
            <dl class="mt-3 divide-y divide-line rounded-control border border-line">
              <div class="flex items-baseline justify-between gap-3 px-3.5 py-2.5">
                <dt class="text-xs font-bold text-ink-3">เลขที่</dt>
                <dd class="num font-bold text-ink-1">{{ singleForm.student_no }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-3 px-3.5 py-2.5">
                <dt class="text-xs font-bold text-ink-3">ชื่อ-นามสกุล</dt>
                <dd class="font-bold text-ink-1">{{ singleForm.first_name }} {{ singleForm.last_name }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-3 px-3.5 py-2.5">
                <dt class="text-xs font-bold text-ink-3">ชื่อเล่น</dt>
                <dd class="text-ink-2">{{ singleForm.nickname || '—' }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-3 px-3.5 py-2.5">
                <dt class="text-xs font-bold text-ink-3">ชื่อภาษาอังกฤษ</dt>
                <dd class="text-ink-2">
                  {{ [singleForm.first_name_en, singleForm.last_name_en].filter(Boolean).join(' ') || '—' }}
                </dd>
              </div>
            </dl>
            <p class="mt-2 text-xs text-ink-3">
              กด "บันทึกข้อมูล" เพื่อเพิ่มนักเรียน · หากต้องการแก้ ให้กด "ย้อนกลับ"
            </p>
          </div>

          <div class="flex flex-col-reverse gap-2 border-t border-line pt-3 sm:flex-row sm:justify-between sm:pt-4">
            <button
              v-if="step > 0"
              type="button"
              class="btn-ghost-ui"
              @click="goBack"
            >
              <i class="bi bi-arrow-left" aria-hidden="true" /> ย้อนกลับ
            </button>
            <RouterLink v-else to="/students" class="btn-ghost-ui">ยกเลิก</RouterLink>

            <template v-if="canManageStudents">
              <button
                v-if="step < STEPS.length - 1"
                type="submit"
                class="btn-primary w-full sm:w-auto"
                :disabled="!stepValid"
              >
                ถัดไป <i class="bi bi-arrow-right" aria-hidden="true" />
              </button>
              <button v-else type="submit" class="btn-primary w-full sm:w-auto" :disabled="isSubmitting">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
                  aria-hidden="true"
                ></span>
                <i v-else class="bi bi-check-lg" aria-hidden="true"></i>
                บันทึกข้อมูล
              </button>
            </template>
            <p
              v-else
              class="flex items-center justify-center gap-2 rounded-control border border-line bg-canvas p-4 text-sm font-bold text-ink-3"
            >
              <i class="bi bi-lock-fill text-danger-500" aria-hidden="true"></i> เฉพาะแอดมินเท่านั้น
            </p>
          </div>
        </form>
      </div>

      <!-- ฟอร์ม: นำเข้ารวดเดียว -->
      <div v-else class="space-y-4 p-4 sm:p-6">
        <div class="rounded-control border border-info-200 bg-info-50 p-4">
          <p class="flex items-center gap-1.5 text-sm font-bold text-info-800">
            <i class="bi bi-info-circle-fill" aria-hidden="true"></i> คำแนะนำการใช้งาน
          </p>
          <p class="mt-1 text-xs text-info-700">
            วางข้อมูลในรูปแบบ: <code class="rounded bg-info-100 px-1 font-bold">เลขที่,ชื่อ,นามสกุล</code> (หนึ่งคนต่อหนึ่งบรรทัด)
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

        <div class="border-t border-line pt-3 sm:pt-4">
          <button
            v-if="canManageStudents"
            type="button"
            class="btn-primary w-full sm:w-auto"
            :disabled="isSubmitting || !bulkData.trim()"
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
            class="flex items-center justify-center gap-2 rounded-control border border-line bg-canvas p-4 text-sm font-bold text-ink-3"
          >
            <i class="bi bi-lock-fill text-danger-500" aria-hidden="true"></i> เฉพาะแอดมินเท่านั้น
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
