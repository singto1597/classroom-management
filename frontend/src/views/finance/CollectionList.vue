<script setup lang="ts">
import { computed, reactive, ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { Collection, BasicStudent, LateFeeMode } from '@/types/finance'
import { displayName } from '@/utils/name'
import { formatThaiDate } from '@/utils/datetime'
import { newIdempotencyKey } from '@/utils/money'

import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useDialog } from '@/composables/useDialog'

const authStore = useAuthStore()
const dialog = useDialog()
const currentServerId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const collections = ref<Collection[]>([])
const isLoading = ref(true)
/** 🔒 ปุ่มเขียนของการเงินใช้สิทธิ์ `MANAGE_FINANCE` (admin ผ่านอยู่แล้ว) */
const canManageFinance = computed(() => authStore.canManageFinance)

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false)

// --- 🌟 State สำหรับการสร้างโปรเจกต์ (Modal แบบเขียนเอง) ---
const isCreateModalOpen = ref(false)
const isSubmitting = ref(false)
const formTitle = ref('')
const formAmount = ref<number | ''>('')
const formDueDate = ref('')

// โหมดเลือกว่าจะเก็บเงินใครบ้าง
const selectionMode = ref<'all' | 'custom'>('all')
const studentsList = ref<BasicStudent[]>([])
const selectedStudentIds = ref<number[]>([])

// ⏰ นโยบายค่าปรับจ่ายล่าช้า (P6.5) — 'none' = ไม่ปรับ (ค่าเริ่มต้น ไม่กระทบของเดิม)
const formLateFeeMode = ref<LateFeeMode>('none')
const formLateFeeAmount = ref<number | ''>('')
const formLateFeeGrace = ref<number | ''>(0)

const fetchCollections = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    const res = await FinanceService.getCollections(currentServerId)
    collections.value = res
  } catch {
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดโปรเจกต์เก็บเงินไม่สำเร็จ', 'error')
  } finally {
    isLoading.value = false
  }
}

// เมื่อกดปุ่ม "สร้างโปรเจกต์ใหม่"
const openCreateModal = async () => {
  // รีเซ็ตฟอร์ม
  formTitle.value = ''
  formAmount.value = ''
  formDueDate.value = ''
  selectionMode.value = 'all'
  selectedStudentIds.value = []
  formLateFeeMode.value = 'none'
  formLateFeeAmount.value = ''
  formLateFeeGrace.value = 0

  // โหลดรายชื่อนักเรียนรอไว้เลย
  try {
    studentsList.value = await FinanceService.getActiveStudents(currentServerId)
    // ค่าเริ่มต้นของ Custom mode คือให้เลือกทุกคนไว้ก่อน
    selectedStudentIds.value = studentsList.value.map((s) => s.id)
  } catch (err) {
    console.error(err)
  }

  isCreateModalOpen.value = true
}

// เมื่อเปลี่ยนโหมดเป็น Custom
const handleModeChange = (mode: 'all' | 'custom') => {
  selectionMode.value = mode
  // ถ้าเปลี่ยนกลับมา Custom ใหม่ ก็เช็คให้เลือกทุกคนเหมือนเดิม
  if (mode === 'custom' && selectedStudentIds.value.length === 0) {
    selectedStudentIds.value = studentsList.value.map((s) => s.id)
  }
}

// Submit ฟอร์มสร้าง
const submitCreateCollection = async () => {
  if (!formTitle.value || !formAmount.value || !formDueDate.value) {
    void dialog.alert(
      'ข้อมูลไม่ครบ',
      'กรุณากรอกชื่อ, ยอดเรียกเก็บ และวันครบกำหนดให้ครบถ้วน',
      'warning',
    )
    return
  }

  if (selectionMode.value === 'custom' && selectedStudentIds.value.length === 0) {
    void dialog.alert(
      'ยังไม่ได้เลือกเพื่อน',
      'กรุณาเลือกรายชื่ออย่างน้อย 1 คน หรือเปลี่ยนกลับไปใช้โหมดเก็บทุกคน',
      'warning',
    )
    return
  }

  if (formLateFeeMode.value !== 'none' && Number(formLateFeeAmount.value) <= 0) {
    void dialog.alert(
      'ข้อมูลค่าปรับไม่ครบ',
      'กรุณากรอกจำนวน/เปอร์เซ็นต์ค่าปรับล่าช้าให้มากกว่า 0 หรือเลือก «ไม่ปรับ»',
      'warning',
    )
    return
  }

  isSubmitting.value = true
  try {
    const payload = {
      title: formTitle.value,
      amount: Number(formAmount.value),
      due_date: formDueDate.value,
      user_name: currentUserName,
      // ถ้า mode custom ให้ส่ง array id ไป, ถ้า all ให้ส่ง undefined (ระบบหลักจะดึงทุกคนเอง)
      student_ids: selectionMode.value === 'custom' ? selectedStudentIds.value : undefined,
      late_fee_mode: formLateFeeMode.value,
      late_fee_amount: Number(formLateFeeAmount.value) || 0,
      late_fee_grace_days: Number(formLateFeeGrace.value) || 0,
    }

    await FinanceService.createCollection(currentServerId, payload)
    isCreateModalOpen.value = false
    await dialog.fire({
      icon: 'success',
      title: 'สร้างสำเร็จ!',
      timer: 1500,
    })
    fetchCollections()
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'สร้างโปรเจกต์ไม่สำเร็จ',
      'error',
    )
  } finally {
    isSubmitting.value = false
  }
}

// --- ✏️ ฟอร์มแก้ไขโปรเจกต์ ---
const isEditOpen = ref(false)
const isUpdating = ref(false)
const editingCollection = ref<Collection | null>(null)
const editForm = reactive({
  title: '',
  amount: '' as number | '',
  due_date: '',
  status: 'active' as Collection['status'],
  late_fee_mode: 'none' as LateFeeMode,
  late_fee_amount: '' as number | '',
  late_fee_grace_days: '' as number | '',
})

const openEditSheet = (col: Collection) => {
  editingCollection.value = col
  editForm.title = col.title
  editForm.amount = col.amount
  editForm.due_date = col.due_date ?? ''
  editForm.status = col.status
  editForm.late_fee_mode = col.late_fee_mode ?? 'none'
  editForm.late_fee_amount = col.late_fee_amount ?? ''
  editForm.late_fee_grace_days = col.late_fee_grace_days ?? ''
  isEditOpen.value = true
}

const submitEditCollection = async () => {
  const col = editingCollection.value
  if (!col) return

  if (!editForm.title.trim() || !editForm.amount || !editForm.due_date) {
    void dialog.alert(
      'ข้อมูลไม่ครบ',
      'กรุณากรอกชื่อ, ยอดเรียกเก็บ และวันครบกำหนดให้ครบถ้วน',
      'warning',
    )
    return
  }

  isUpdating.value = true
  try {
    await FinanceService.updateCollection(currentServerId, col.id, {
      title: editForm.title.trim(),
      amount: Number(editForm.amount),
      due_date: editForm.due_date,
      status: editForm.status,
      user_name: currentUserName,
      late_fee_mode: editForm.late_fee_mode,
      late_fee_amount: Number(editForm.late_fee_amount) || 0,
      late_fee_grace_days: Number(editForm.late_fee_grace_days) || 0,
    })
    isEditOpen.value = false
    await dialog.fire({ icon: 'success', title: 'อัปเดตสำเร็จ!', timer: 1500 })
    fetchCollections()
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'บันทึกการตั้งค่าไม่สำเร็จ',
      'error',
    )
  } finally {
    isUpdating.value = false
  }
}

// --- 🧾 เรียกเก็บเงินเองรายบุคคล (P6.5) — หลายคน คนละยอด ภายใต้ชื่อเดียว ---
interface CustomRow {
  student: BasicStudent
  checked: boolean
  amount: number | ''
  note: string
}

const isCustomChargeOpen = ref(false)
const isCustomSubmitting = ref(false)
const customTitle = ref('')
const customDueDate = ref('')
const customRows = ref<CustomRow[]>([])
// 🔑 คงคีย์เดิมตลอดการเปิดหนึ่งครั้ง — กดส่งซ้ำ/เน็ตกระตุกจึงไม่สร้างบิลซ้ำ
const customKey = ref(newIdempotencyKey())

const selectedCustomRows = computed(() => customRows.value.filter((r) => r.checked))
const customTotal = computed(() =>
  selectedCustomRows.value.reduce((sum, r) => sum + (Number(r.amount) || 0), 0),
)

const openCustomCharge = async () => {
  customTitle.value = ''
  customDueDate.value = ''
  customKey.value = newIdempotencyKey()
  try {
    const students = await FinanceService.getActiveStudents(currentServerId)
    customRows.value = students.map((student) => ({
      student,
      checked: false,
      amount: '',
      note: '',
    }))
  } catch (err) {
    console.error(err)
    customRows.value = []
  }
  isCustomChargeOpen.value = true
}

const toggleAllCustomRows = (checked: boolean) => {
  customRows.value.forEach((row) => (row.checked = checked))
}

const submitCustomCharges = async () => {
  if (!customTitle.value.trim() || !customDueDate.value) {
    void dialog.alert('ข้อมูลไม่ครบ', 'กรุณากรอกชื่อรายการและวันครบกำหนด', 'warning')
    return
  }
  const items = selectedCustomRows.value
    .filter((r) => r.checked)
    .map((r) => ({
      student_id: r.student.id,
      amount: Number(r.amount) || 0,
      note: r.note.trim() || undefined,
    }))
  if (items.length === 0) {
    void dialog.alert('ยังไม่ได้เลือกเพื่อน', 'กรุณาเลือกอย่างน้อย 1 คน', 'warning')
    return
  }
  if (items.some((i) => i.amount <= 0)) {
    void dialog.alert(
      'ยอดไม่ครบ',
      'นักเรียนที่เลือกทุกคนต้องมียอดเรียกเก็บมากกว่า 0 บาท',
      'warning',
    )
    return
  }

  isCustomSubmitting.value = true
  try {
    const res = await FinanceService.createCustomCharges(currentServerId, {
      title: customTitle.value.trim(),
      due_date: customDueDate.value,
      items,
      idempotency_key: customKey.value,
      user_name: currentUserName,
    })
    isCustomChargeOpen.value = false
    await dialog.fire({ icon: 'success', title: res.message ?? 'เรียกเก็บสำเร็จ!', timer: 1800 })
    fetchCollections()
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'เรียกเก็บเงินไม่สำเร็จ',
      'error',
    )
  } finally {
    isCustomSubmitting.value = false
  }
}

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num)
}

onMounted(() => {
  fetchCollections()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="จัดการแคมเปญระดมทุนและการเก็บเงินเพื่อนในห้อง"
    >
      <template #actions>
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-if="canManageFinance"
            type="button"
            class="btn-ghost-ui"
            @click="openCustomCharge"
          >
            <i class="bi bi-receipt-cutoff" aria-hidden="true"></i>
            เรียกเก็บเอง (รายคน)
          </button>
          <button
            v-if="authStore.isAdmin"
            type="button"
            class="btn-primary"
            @click="openCreateModal"
          >
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            สร้างโปรเจกต์ใหม่
          </button>
        </div>
      </template>
    </PageIntro>

    <SkeletonRows v-if="isLoading" :rows="3" height="h-44" />

    <StateBlock v-else-if="hasError" variant="error" @retry="fetchCollections" />

    <StateBlock
      v-else-if="!collections.length"
      variant="empty"
      icon="bi-folder2-open"
      title="ยังไม่มีโปรเจกต์เก็บเงินในขณะนี้"
      hint="กดปุ่ม «สร้างโปรเจกต์ใหม่» เพื่อเริ่มต้นเรียกเก็บเงินจากเพื่อน ๆ ได้เลย"
    >
      <button
        v-if="authStore.isAdmin"
        type="button"
        class="btn-primary mt-1.5"
        @click="openCreateModal"
      >
        <i class="bi bi-plus-lg" aria-hidden="true"></i>
        สร้างโปรเจกต์ใหม่
      </button>
    </StateBlock>

    <div v-else class="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="col in collections"
        :key="col.id"
        class="page-card flex flex-col justify-between gap-3 border-s-4 p-4 sm:gap-4 sm:p-5"
        :class="col.status === 'active' ? 'border-s-brand-700' : 'border-s-line'"
      >
        <div class="min-w-0">
          <div class="flex items-start justify-between gap-3">
            <span
              class="chip shrink-0"
              :class="col.status === 'active' ? 'bg-ok-50 text-ok-700' : 'bg-canvas text-ink-3'"
            >
              <i
                class="bi"
                :class="col.status === 'active' ? 'bi-broadcast' : 'bi-lock-fill'"
                aria-hidden="true"
              ></i>
              {{ col.status === 'active' ? 'เปิดรับเงิน' : 'ปิดแล้ว' }}
            </span>

            <button
              v-if="authStore.isAdmin"
              type="button"
              class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-ink active:scale-[0.97]"
              title="ตั้งค่าโปรเจกต์"
              @click="openEditSheet(col)"
            >
              <i class="bi bi-gear-fill text-lg" aria-hidden="true"></i>
            </button>
          </div>

          <h2 class="mt-3 truncate text-title-m font-bold text-ink" :title="col.title">
            {{ col.title }}
          </h2>

          <p class="chip num mt-2 bg-canvas text-ink-3">
            <i class="bi bi-calendar-event" aria-hidden="true"></i>
            ครบกำหนด {{ formatThaiDate(col.due_date) }}
          </p>

          <p
            v-if="col.late_fee_mode && col.late_fee_mode !== 'none'"
            class="chip num mt-2 bg-warn-50 text-warn-700"
          >
            <i class="bi bi-alarm" aria-hidden="true"></i>
            ปรับล่าช้า
            {{ col.late_fee_mode === 'percent' ? `${col.late_fee_amount}%` : `฿${formatNumber(col.late_fee_amount ?? 0)}` }}
            <template v-if="col.late_fee_grace_days">· ผ่อนผัน {{ col.late_fee_grace_days }} วัน</template>
          </p>

          <p class="mt-3 flex items-baseline gap-1 sm:mt-4">
            <span
              class="num text-3xl font-bold tracking-tight"
              :class="col.status === 'active' ? 'text-brand-700' : 'text-ink-3'"
            >
              ฿{{ formatNumber(col.amount) }}
            </span>
            <span class="text-xs font-bold text-ink-3">/ คน</span>
          </p>
        </div>

        <RouterLink :to="`/finance/collections/${col.id}`" class="btn-ghost-ui w-full">
          ดูรายละเอียด
          <i class="bi bi-arrow-right" aria-hidden="true"></i>
        </RouterLink>
      </div>
    </div>

    <!-- ฟอร์มสร้างโปรเจกต์: bottom sheet บนมือถือ / modal กลางจอบนเดสก์ท็อป -->
    <AppSheet
      :open="isCreateModalOpen"
      label="สร้างโปรเจกต์เก็บเงิน"
      title="สร้างโปรเจกต์เก็บเงิน"
      description="ตั้งค่าบิลเรียกเก็บเงินเข้ากองกลาง"
      size="form"
      :dismissible="!isSubmitting"
      @close="isCreateModalOpen = false"
    >
      <div class="space-y-4">
        <div>
          <label class="field-label" for="colTitle">ชื่อรายการ</label>
          <input
            id="colTitle"
            v-model="formTitle"
            class="field"
            placeholder="เช่น ค่าชีทฟิสิกส์, ค่าปรับเวร"
          />
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
          <div>
            <label class="field-label" for="colAmount">ยอดเรียกเก็บ (฿)</label>
            <div class="relative">
              <span
                class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3.5 font-bold text-ink-3"
                aria-hidden="true"
              >
                ฿
              </span>
              <input
                id="colAmount"
                v-model="formAmount"
                type="number"
                class="field num ps-8 text-right"
                placeholder="0.00"
              />
            </div>
          </div>
          <div>
            <label class="field-label" for="colDueDate">ครบกำหนด</label>
            <input id="colDueDate" v-model="formDueDate" type="date" class="field" />
          </div>
        </div>

        <div class="h-px bg-line"></div>

        <!-- ⏰ ค่าปรับจ่ายล่าช้า (P6.5) — ปิดไว้โดยค่าเริ่มต้น -->
        <div>
          <p class="field-label">ค่าปรับจ่ายล่าช้า</p>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
            <div>
              <select v-model="formLateFeeMode" class="field" aria-label="รูปแบบค่าปรับล่าช้า">
                <option value="none">ไม่ปรับ</option>
                <option value="fixed">ปรับเป็นจำนวนเงิน</option>
                <option value="percent">ปรับเป็นเปอร์เซ็นต์</option>
              </select>
            </div>
            <div v-if="formLateFeeMode !== 'none'">
              <div class="relative">
                <span
                  class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3.5 font-bold text-ink-3"
                  aria-hidden="true"
                >
                  {{ formLateFeeMode === 'percent' ? '%' : '฿' }}
                </span>
                <input
                  v-model="formLateFeeAmount"
                  type="number"
                  class="field num ps-8 text-right"
                  :placeholder="formLateFeeMode === 'percent' ? 'เช่น 5' : 'เช่น 20'"
                  aria-label="จำนวนหรือเปอร์เซ็นต์ค่าปรับ"
                />
              </div>
            </div>
            <div v-if="formLateFeeMode !== 'none'">
              <input
                v-model="formLateFeeGrace"
                type="number"
                class="field num"
                placeholder="ผ่อนผัน (วัน)"
                aria-label="จำนวนวันผ่อนผัน"
              />
            </div>
          </div>
          <p v-if="formLateFeeMode !== 'none'" class="mt-2 text-caption text-ink-3">
            ระบบจะออกค่าปรับให้บิลที่ค้างเมื่อเลยกำหนด + วันผ่อนผันแล้ว (คิดจากยอดคงเหลือ
            ณ วันนั้น) — 1 บิลออกค่าปรับได้ครั้งเดียว
          </p>
        </div>

        <div class="h-px bg-line"></div>

        <div>
          <p class="field-label">ต้องการเรียกเก็บใครบ้าง?</p>
          <div class="mb-3 grid grid-cols-2 gap-3 sm:mb-4">
            <button
              type="button"
              class="flex flex-col items-center justify-center gap-1 rounded-control border px-3 py-3 text-sm font-bold transition-colors active:scale-[0.97]"
              :class="
                selectionMode === 'all'
                  ? 'border-brand-200 bg-brand-50 text-brand-700'
                  : 'border-line bg-surface text-ink-3 hover:border-ink-3'
              "
              @click="handleModeChange('all')"
            >
              <i class="bi bi-people-fill text-lg" aria-hidden="true"></i>
              เก็บทุกคน (Active)
            </button>
            <button
              type="button"
              class="flex flex-col items-center justify-center gap-1 rounded-control border px-3 py-3 text-sm font-bold transition-colors active:scale-[0.97]"
              :class="
                selectionMode === 'custom'
                  ? 'border-brand-200 bg-brand-50 text-brand-700'
                  : 'border-line bg-surface text-ink-3 hover:border-ink-3'
              "
              @click="handleModeChange('custom')"
            >
              <i class="bi bi-person-check-fill text-lg" aria-hidden="true"></i>
              ระบุตัวบุคคล
            </button>
          </div>

          <div v-if="selectionMode === 'custom'">
            <div class="mb-2 flex items-center justify-between gap-2 px-1">
              <span class="text-caption font-bold text-ink-3">
                เลือกแล้ว {{ selectedStudentIds.length }} คน
              </span>
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  class="inline-flex min-h-11 items-center text-caption font-bold text-brand-700 hover:underline"
                  @click="selectedStudentIds = studentsList.map((s) => s.id)"
                >
                  เลือกทั้งหมด
                </button>
                <span class="text-line">|</span>
                <button
                  type="button"
                  class="inline-flex min-h-11 items-center text-caption font-bold text-ink-3 hover:underline"
                  @click="selectedStudentIds = []"
                >
                  ล้างทั้งหมด
                </button>
              </div>
            </div>

            <div
              class="max-h-48 divide-y divide-line overflow-y-auto overscroll-contain rounded-control border border-line bg-surface"
            >
              <label
                v-for="s in studentsList"
                :key="s.id"
                class="flex cursor-pointer items-center justify-between gap-3 p-3 transition-colors hover:bg-canvas"
              >
                <div class="flex min-w-0 items-center gap-3">
                  <span class="num w-6 shrink-0 text-right text-caption font-bold text-ink-3">
                    #{{ s.student_no }}
                  </span>
                  <div class="min-w-0 truncate text-sm font-bold text-ink-2">
                    {{ displayName(s) }}
                    <span v-if="s.nickname || s.nickname_en" class="font-normal text-ink-3">
                      ({{ s.nickname || s.nickname_en }})
                    </span>
                  </div>
                </div>

                <span
                  class="flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors"
                  :class="
                    selectedStudentIds.includes(s.id)
                      ? 'border-brand-700 bg-brand-700'
                      : 'border-line bg-surface'
                  "
                >
                  <i
                    v-if="selectedStudentIds.includes(s.id)"
                    class="bi bi-check-lg text-xs font-bold text-white"
                    aria-hidden="true"
                  ></i>
                </span>
                <input v-model="selectedStudentIds" type="checkbox" :value="s.id" class="hidden" />
              </label>
            </div>
          </div>

          <div
            v-if="selectionMode === 'all'"
            class="flex items-center gap-2 rounded-control border border-brand-200 bg-brand-50 p-3 text-caption font-bold text-brand-700"
          >
            <i class="bi bi-info-circle-fill shrink-0" aria-hidden="true"></i>
            <span class="min-w-0">
              ระบบจะสร้างบิลเรียกเก็บเงินไปยังนักเรียนที่มีสถานะ Active ทุกคน ({{
                studentsList.length
              }}
              คน) อัตโนมัติ
            </span>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isSubmitting"
            @click="isCreateModalOpen = false"
          >
            ยกเลิก
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isSubmitting"
            @click="submitCreateCollection"
          >
            <i v-if="isSubmitting" class="bi bi-arrow-repeat animate-spin" aria-hidden="true"></i>
            {{ isSubmitting ? 'กำลังสร้าง...' : 'สร้างแคมเปญ' }}
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ฟอร์มตั้งค่าโปรเจกต์ -->
    <AppSheet
      :open="isEditOpen"
      label="ตั้งค่าโปรเจกต์"
      title="ตั้งค่าโปรเจกต์"
      :description="editingCollection?.title ?? ''"
      size="form"
      :dismissible="!isUpdating"
      @close="isEditOpen = false"
    >
      <div class="space-y-4">
        <div>
          <label class="field-label" for="editTitle">ชื่อรายการ</label>
          <input id="editTitle" v-model="editForm.title" class="field" placeholder="ชื่อรายการ" />
        </div>
        <div>
          <label class="field-label" for="editAmount">ยอดเรียกเก็บ (฿)</label>
          <input
            id="editAmount"
            v-model="editForm.amount"
            type="number"
            inputmode="decimal"
            class="field num text-right"
            placeholder="0.00"
          />
        </div>
        <div>
          <label class="field-label" for="editDueDate">ครบกำหนดชำระ</label>
          <input id="editDueDate" v-model="editForm.due_date" type="date" class="field" />
        </div>
        <div>
          <label class="field-label" for="editStatus">สถานะแคมเปญ</label>
          <select id="editStatus" v-model="editForm.status" class="field">
            <option value="active">🟢 เปิดรับเงิน</option>
            <option value="closed">🔴 ปิดแคมเปญ</option>
          </select>
        </div>
        <div class="h-px bg-line"></div>
        <div>
          <label class="field-label" for="editLateFeeMode">ค่าปรับจ่ายล่าช้า</label>
          <select id="editLateFeeMode" v-model="editForm.late_fee_mode" class="field">
            <option value="none">ไม่ปรับ</option>
            <option value="fixed">ปรับเป็นจำนวนเงิน (฿)</option>
            <option value="percent">ปรับเป็นเปอร์เซ็นต์ (%)</option>
          </select>
        </div>
        <div v-if="editForm.late_fee_mode !== 'none'" class="grid grid-cols-2 gap-3">
          <div>
            <label class="field-label" for="editLateFeeAmount">
              {{ editForm.late_fee_mode === 'percent' ? 'เปอร์เซ็นต์' : 'จำนวนเงิน (฿)' }}
            </label>
            <input
              id="editLateFeeAmount"
              v-model="editForm.late_fee_amount"
              type="number"
              class="field num text-right"
              placeholder="0"
            />
          </div>
          <div>
            <label class="field-label" for="editLateFeeGrace">ผ่อนผัน (วัน)</label>
            <input
              id="editLateFeeGrace"
              v-model="editForm.late_fee_grace_days"
              type="number"
              class="field num text-right"
              placeholder="0"
            />
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isUpdating"
            @click="isEditOpen = false"
          >
            ยกเลิก
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isUpdating"
            @click="submitEditCollection"
          >
            <i v-if="isUpdating" class="bi bi-arrow-repeat animate-spin" aria-hidden="true"></i>
            {{ isUpdating ? 'กำลังบันทึก...' : 'บันทึกการตั้งค่า' }}
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- 🧾 เรียกเก็บเองรายบุคคล: เลือกคน + ใส่ยอดต่อคน -->
    <AppSheet
      :open="isCustomChargeOpen"
      label="เรียกเก็บเงินเองรายบุคคล"
      title="เรียกเก็บเงินเอง (รายคน)"
      description="เลือกนักเรียนและกำหนดยอดของแต่ละคน — ระบบสร้างบิลแยกให้ทันที"
      size="form"
      :dismissible="!isCustomSubmitting"
      @close="isCustomChargeOpen = false"
    >
      <div class="space-y-4">
        <div>
          <label class="field-label" for="ccTitle">ชื่อรายการ</label>
          <input
            id="ccTitle"
            v-model="customTitle"
            class="field"
            placeholder="เช่น ค่าหนังสือที่เหลือ, ยอดค้างเก่า"
          />
        </div>
        <div>
          <label class="field-label" for="ccDueDate">ครบกำหนดชำระ</label>
          <input id="ccDueDate" v-model="customDueDate" type="date" class="field" />
        </div>

        <div class="h-px bg-line"></div>

        <div class="mb-2 flex items-center justify-between gap-2 px-1">
          <span class="text-caption font-bold text-ink-3">
            เลือกแล้ว {{ selectedCustomRows.length }} คน · รวม
            <span class="num text-brand-700">฿{{ formatNumber(customTotal) }}</span>
          </span>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="inline-flex min-h-11 items-center text-caption font-bold text-brand-700 hover:underline"
              @click="toggleAllCustomRows(true)"
            >
              เลือกทั้งหมด
            </button>
            <span class="text-line">|</span>
            <button
              type="button"
              class="inline-flex min-h-11 items-center text-caption font-bold text-ink-3 hover:underline"
              @click="toggleAllCustomRows(false)"
            >
              ล้างทั้งหมด
            </button>
          </div>
        </div>

        <div class="divide-y divide-line rounded-control border border-line bg-surface">
          <div
            v-for="row in customRows"
            :key="row.student.id"
            class="flex items-center gap-3 p-3"
            :class="row.checked ? 'bg-brand-50/40' : ''"
          >
            <label class="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
              <span
                class="flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors"
                :class="
                  row.checked ? 'border-brand-700 bg-brand-700' : 'border-line bg-surface'
                "
              >
                <i
                  v-if="row.checked"
                  class="bi bi-check-lg text-xs font-bold text-white"
                  aria-hidden="true"
                ></i>
              </span>
              <input v-model="row.checked" type="checkbox" class="hidden" />
              <span class="min-w-0 truncate text-sm font-bold text-ink-2">
                <span class="num text-ink-3">#{{ row.student.student_no }}</span>
                {{ displayName(row.student) }}
              </span>
            </label>
            <input
              v-model="row.amount"
              type="number"
              inputmode="decimal"
              class="field num w-24 shrink-0 text-right"
              placeholder="฿"
              :disabled="!row.checked"
              :aria-label="`ยอดของ ${displayName(row.student)}`"
            />
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isCustomSubmitting"
            @click="isCustomChargeOpen = false"
          >
            ยกเลิก
          </button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isCustomSubmitting"
            @click="submitCustomCharges"
          >
            <i
              v-if="isCustomSubmitting"
              class="bi bi-arrow-repeat animate-spin"
              aria-hidden="true"
            ></i>
            {{ isCustomSubmitting ? 'กำลังเรียกเก็บ...' : `เรียกเก็บ ${selectedCustomRows.length} คน` }}
          </button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>

<style scoped>
/* ซ่อนปุ่มในช่อง Number */
input[type='number']::-webkit-inner-spin-button,
input[type='number']::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type='number'] {
  -moz-appearance: textfield;
}
/* (scrollbar ใช้ของกลางจาก main.css แล้ว) */
</style>
