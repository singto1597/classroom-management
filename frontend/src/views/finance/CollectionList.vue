<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { Collection, BasicStudent } from '@/types/finance'
import { displayName } from '@/utils/name'
import { formatThaiDate } from '@/utils/datetime'

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

  isSubmitting.value = true
  try {
    const payload = {
      title: formTitle.value,
      amount: Number(formAmount.value),
      due_date: formDueDate.value,
      user_name: currentUserName,
      // ถ้า mode custom ให้ส่ง array id ไป, ถ้า all ให้ส่ง undefined (ระบบหลักจะดึงทุกคนเอง)
      student_ids: selectionMode.value === 'custom' ? selectedStudentIds.value : undefined,
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
})

const openEditSheet = (col: Collection) => {
  editingCollection.value = col
  editForm.title = col.title
  editForm.amount = col.amount
  editForm.due_date = col.due_date ?? ''
  editForm.status = col.status
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
        <button v-if="authStore.isAdmin" type="button" class="btn-primary" @click="openCreateModal">
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          สร้างโปรเจกต์ใหม่
        </button>
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
