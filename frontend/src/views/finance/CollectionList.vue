<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { Collection, BasicStudent } from '@/types/finance'
import { displayName } from '@/utils/name'
import Swal from 'sweetalert2'

import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

const authStore = useAuthStore()
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
    Swal.fire('เกิดข้อผิดพลาด', 'โหลดโปรเจกต์เก็บเงินไม่สำเร็จ', 'error')
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
    return Swal.fire(
      'ข้อมูลไม่ครบ',
      'กรุณากรอกชื่อ, ยอดเรียกเก็บ และวันครบกำหนดให้ครบถ้วน',
      'warning',
    )
  }

  if (selectionMode.value === 'custom' && selectedStudentIds.value.length === 0) {
    return Swal.fire(
      'ยังไม่ได้เลือกเพื่อน',
      'กรุณาเลือกรายชื่ออย่างน้อย 1 คน หรือเปลี่ยนกลับไปใช้โหมดเก็บทุกคน',
      'warning',
    )
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
    Swal.fire({ icon: 'success', title: 'สร้างสำเร็จ!', timer: 1500, showConfirmButton: false })
    isCreateModalOpen.value = false
    fetchCollections()
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'สร้างโปรเจกต์ไม่สำเร็จ', 'error')
  } finally {
    isSubmitting.value = false
  }
}

const handleEditCollection = async (col: Collection) => {
  const { value: formValues } = await Swal.fire({
    title: 'ตั้งค่าโปรเจกต์',
    html: `
      <div class="flex flex-col gap-3 mt-4 text-left">
        <div>
          <label class="text-xs font-bold text-stone-400 ms-2 uppercase tracking-wider">ชื่อรายการ</label>
          <input id="swal-title" class="swal2-input custom-swal-input mt-1" placeholder="ชื่อรายการ" value="${col.title}">
        </div>
        <div>
          <label class="text-xs font-bold text-stone-400 ms-2 uppercase tracking-wider">ยอดเรียกเก็บ (฿)</label>
          <input id="swal-amount" type="number" class="swal2-input custom-swal-input mt-1" placeholder="ยอดเรียกเก็บ" value="${col.amount}">
        </div>
        <div>
          <label class="text-xs font-bold text-stone-400 ms-2 uppercase tracking-wider">ครบกำหนดชำระ</label>
          <input id="swal-date" type="date" class="swal2-input custom-swal-input mt-1" value="${col.due_date}">
        </div>
        <div>
          <label class="text-xs font-bold text-stone-400 ms-2 uppercase tracking-wider">สถานะแคมเปญ</label>
          <select id="swal-status" class="swal2-select custom-swal-input mt-1">
            <option value="active" ${col.status === 'active' ? 'selected' : ''}>🟢 เปิดรับเงิน</option>
            <option value="closed" ${col.status === 'closed' ? 'selected' : ''}>🔴 ปิดแคมเปญ</option>
          </select>
        </div>
      </div>
    `,
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'บันทึกการตั้งค่า',
    cancelButtonText: 'ยกเลิก',
    customClass: {
      popup: 'rounded-2xl',
    },
    preConfirm: () => {
      const title = (document.getElementById('swal-title') as HTMLInputElement).value
      const amount = (document.getElementById('swal-amount') as HTMLInputElement).value
      const dueDate = (document.getElementById('swal-date') as HTMLInputElement).value
      const status = (document.getElementById('swal-status') as HTMLSelectElement).value
      return { title, amount: parseFloat(amount), due_date: dueDate, status }
    },
  })

  if (formValues) {
    try {
      await FinanceService.updateCollection(currentServerId, col.id, {
        ...formValues,
        user_name: currentUserName,
      })
      Swal.fire({ icon: 'success', title: 'อัปเดตสำเร็จ!', timer: 1500, showConfirmButton: false })
      fetchCollections()
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'บันทึกการตั้งค่าไม่สำเร็จ', 'error')
    }
  }
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr + 'T00:00:00')
  return date.toLocaleDateString('th-TH', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
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
    <PageHeader
      eyebrow="Fundraising"
      title="โปรเจกต์เก็บเงิน"
      description="จัดการแคมเปญระดมทุนและการเก็บเงินเพื่อนในห้อง"
    >
      <template #actions>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
        <button v-if="authStore.isAdmin" type="button" class="btn-primary" @click="openCreateModal">
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          สร้างโปรเจกต์ใหม่
        </button>
      </template>
    </PageHeader>

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
        :class="col.status === 'active' ? 'border-s-brand-700' : 'border-s-stone-300'"
      >
        <div class="min-w-0">
          <div class="flex items-start justify-between gap-3">
            <span
              class="chip shrink-0"
              :class="
                col.status === 'active'
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'bg-stone-100 text-stone-600'
              "
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
              class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-900 active:scale-[0.97]"
              title="ตั้งค่าโปรเจกต์"
              @click="handleEditCollection(col)"
            >
              <i class="bi bi-gear-fill text-lg" aria-hidden="true"></i>
            </button>
          </div>

          <h2
            class="font-display mt-3 truncate text-lg font-bold text-stone-900"
            :title="col.title"
          >
            {{ col.title }}
          </h2>

          <p class="chip num mt-2 bg-stone-50 text-stone-500">
            <i class="bi bi-calendar-event" aria-hidden="true"></i>
            ครบกำหนด {{ formatDate(col.due_date) }}
          </p>

          <p class="mt-3 flex items-baseline gap-1 sm:mt-4">
            <span
              class="font-display num text-3xl font-bold tracking-tight"
              :class="col.status === 'active' ? 'text-brand-700' : 'text-stone-400'"
            >
              ฿{{ formatNumber(col.amount) }}
            </span>
            <span class="text-xs font-bold text-stone-400">/ คน</span>
          </p>
        </div>

        <RouterLink :to="`/finance/collections/${col.id}`" class="btn-ghost-ui w-full">
          ดูรายละเอียด
          <i class="bi bi-arrow-right" aria-hidden="true"></i>
        </RouterLink>
      </div>
    </div>

    <!-- ฟอร์มสร้างโปรเจกต์: bottom sheet บนมือถือ / modal กลางจอบนเดสก์ท็อป -->
    <div
      v-if="isCreateModalOpen"
      class="fixed inset-0 z-[70] flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
    >
      <div
        class="flex max-h-[90dvh] w-full max-w-lg flex-col rounded-t-3xl border border-stone-200 bg-white md:rounded-2xl"
      >
        <div
          class="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 px-4 py-4 sm:px-6"
        >
          <div class="min-w-0">
            <h2 class="font-display truncate text-lg font-bold text-stone-900">
              สร้างโปรเจกต์เก็บเงิน
            </h2>
            <p class="mt-0.5 truncate text-xs font-bold text-stone-400">
              ตั้งค่าบิลเรียกเก็บเงินเข้ากองกลาง
            </p>
          </div>
          <button
            type="button"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-900 active:scale-[0.97]"
            aria-label="ปิดหน้าต่าง"
            @click="isCreateModalOpen = false"
          >
            <i class="bi bi-x-lg text-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto overscroll-contain bg-stone-50/50 p-4 sm:p-6">
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
                    class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3.5 font-bold text-stone-400"
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
          </div>

          <div class="h-px bg-stone-200"></div>

          <div>
            <p class="field-label">ต้องการเรียกเก็บใครบ้าง?</p>
            <div class="mb-3 grid grid-cols-2 gap-3 sm:mb-4">
              <button
                type="button"
                class="flex flex-col items-center justify-center gap-1 rounded-xl border px-3 py-3 text-sm font-bold transition-colors active:scale-[0.97]"
                :class="
                  selectionMode === 'all'
                    ? 'border-brand-200 bg-brand-50 text-brand-700'
                    : 'border-stone-200 bg-white text-stone-500 hover:border-stone-300'
                "
                @click="handleModeChange('all')"
              >
                <i class="bi bi-people-fill text-lg" aria-hidden="true"></i>
                เก็บทุกคน (Active)
              </button>
              <button
                type="button"
                class="flex flex-col items-center justify-center gap-1 rounded-xl border px-3 py-3 text-sm font-bold transition-colors active:scale-[0.97]"
                :class="
                  selectionMode === 'custom'
                    ? 'border-brand-200 bg-brand-50 text-brand-700'
                    : 'border-stone-200 bg-white text-stone-500 hover:border-stone-300'
                "
                @click="handleModeChange('custom')"
              >
                <i class="bi bi-person-check-fill text-lg" aria-hidden="true"></i>
                ระบุตัวบุคคล
              </button>
            </div>

            <div v-if="selectionMode === 'custom'">
              <div class="mb-2 flex items-center justify-between gap-2 px-1">
                <span class="text-xs font-bold text-stone-500">
                  เลือกแล้ว {{ selectedStudentIds.length }} คน
                </span>
                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    class="inline-flex min-h-11 items-center text-xs font-bold text-brand-700 hover:underline"
                    @click="selectedStudentIds = studentsList.map((s) => s.id)"
                  >
                    เลือกทั้งหมด
                  </button>
                  <span class="text-stone-300">|</span>
                  <button
                    type="button"
                    class="inline-flex min-h-11 items-center text-xs font-bold text-stone-500 hover:underline"
                    @click="selectedStudentIds = []"
                  >
                    ล้างทั้งหมด
                  </button>
                </div>
              </div>

              <div
                class="max-h-48 divide-y divide-stone-100 overflow-y-auto overscroll-contain rounded-2xl border border-stone-200 bg-white"
              >
                <label
                  v-for="s in studentsList"
                  :key="s.id"
                  class="flex cursor-pointer items-center justify-between gap-3 p-3 transition-colors hover:bg-stone-50"
                >
                  <div class="flex min-w-0 items-center gap-3">
                    <span class="num w-6 shrink-0 text-right text-xs font-bold text-stone-400">
                      #{{ s.student_no }}
                    </span>
                    <div class="min-w-0 truncate text-sm font-bold text-stone-700">
                      {{ displayName(s) }}
                      <span v-if="s.nickname || s.nickname_en" class="font-normal text-stone-400">
                        ({{ s.nickname || s.nickname_en }})
                      </span>
                    </div>
                  </div>

                  <span
                    class="flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors"
                    :class="
                      selectedStudentIds.includes(s.id)
                        ? 'border-brand-700 bg-brand-700'
                        : 'border-stone-300 bg-white'
                    "
                  >
                    <i
                      v-if="selectedStudentIds.includes(s.id)"
                      class="bi bi-check-lg text-xs font-bold text-white"
                      aria-hidden="true"
                    ></i>
                  </span>
                  <input
                    v-model="selectedStudentIds"
                    type="checkbox"
                    :value="s.id"
                    class="hidden"
                  />
                </label>
              </div>
            </div>

            <div
              v-if="selectionMode === 'all'"
              class="flex items-center gap-2 rounded-xl border border-brand-200 bg-brand-50 p-3 text-[11px] font-bold text-brand-700"
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

        <div
          class="flex shrink-0 flex-col-reverse gap-2 border-t border-stone-100 p-4 sm:flex-row sm:justify-end sm:p-6"
        >
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
      </div>
    </div>
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
