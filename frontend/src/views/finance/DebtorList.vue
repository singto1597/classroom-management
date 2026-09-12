<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { Debtor, Account, StudentDebtItem } from '@/types/finance'
import Swal from 'sweetalert2'

import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

const authStore = useAuthStore()
const currentServerId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

const debtors = ref<Debtor[]>([])
const accounts = ref<Account[]>([])
const isLoading = ref(true)

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false)

// Modal/Batch Pay State
const isModalOpen = ref(false)
const selectedStudent = ref<{ id: number; name: string } | null>(null)
const studentDebts = ref<StudentDebtItem[]>([])
const isLoadingDebts = ref(false)
const selectedPaymentIds = ref<number[]>([])
const payAmounts = ref<Record<number, number>>({})
const paidToAccountId = ref<string>('')
const slipImageUrl = ref('')

// Memory logic
const lastSelectedMemory = ref<number[] | null>(null)

const fetchDebtors = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    const [debtRes, accRes] = await Promise.all([
      FinanceService.getAllDebtors(currentServerId),
      FinanceService.getAccounts(currentServerId),
    ])
    debtors.value = debtRes
    accounts.value = accRes

    // Auto-select first account
    if (accounts.value.length > 0) {
      paidToAccountId.value = accounts.value[0]?.id.toString() || ''
    }
  } catch {
    hasError.value = true
    Swal.fire('เกิดข้อผิดพลาด', 'โหลดข้อมูลลูกหนี้ไม่สำเร็จ', 'error')
  } finally {
    isLoading.value = false
  }
}

const handleClearDebt = async (debtor: Debtor) => {
  // ดักฝั่ง Script: ป้องกันคนกดเรียกฟังก์ชันข้าม UI
  if (!isAdmin.value) {
    Swal.fire('ไม่มีสิทธิ์เข้าถึง', 'เฉพาะแอดมินเท่านั้นที่สามารถเคลียร์หนี้ได้', 'error')
    return
  }

  selectedStudent.value = { id: debtor.student_id, name: debtor.student_name }
  isModalOpen.value = true
  isLoadingDebts.value = true
  selectedPaymentIds.value = []
  payAmounts.value = {}
  slipImageUrl.value = ''

  try {
    const res = await FinanceService.getStudentDebts(currentServerId, debtor.student_id)
    studentDebts.value = res.debts

    // Logic: Auto-Select ฉลาดจำค่าเดิม
    studentDebts.value.forEach((debt) => {
      let shouldCheck = false
      if (lastSelectedMemory.value === null) {
        shouldCheck = true
      } else {
        shouldCheck = lastSelectedMemory.value.includes(debt.collection_id)
      }

      if (shouldCheck) {
        selectedPaymentIds.value.push(debt.payment_id)
      }
      payAmounts.value[debt.payment_id] = debt.amount
    })
  } catch {
    Swal.fire('เกิดข้อผิดพลาด', 'ดึงรายการค้างชำระไม่สำเร็จ', 'error')
    isModalOpen.value = false
  } finally {
    isLoadingDebts.value = false
  }
}

const totalSelectedAmount = computed(() => {
  return selectedPaymentIds.value.reduce((total, id) => {
    return total + (payAmounts.value[id] || 0)
  }, 0)
})

const handleBatchPay = async () => {
  // ดักอีกชั้นตอนกดยืนยันจ่ายเงิน
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error')
  }

  if (selectedPaymentIds.value.length === 0) {
    return Swal.fire('อ๊ะ!', 'กรุณาเลือกรายการที่ต้องการชำระเงิน', 'warning')
  }

  // ✅ กันเผลอกดยืนยันตอนไม่มีกระเป๋าเงินเป้าหมาย
  if (!paidToAccountId.value) {
    return Swal.fire('ยังไม่เลือกบัญชี', 'กรุณาเลือกกระเป๋าเงินที่รับเงินก่อน', 'warning')
  }

  // จดจำการตั้งค่าก่อนกดยืนยัน
  lastSelectedMemory.value = studentDebts.value
    .filter((d) => selectedPaymentIds.value.includes(d.payment_id))
    .map((d) => d.collection_id)

  try {
    Swal.fire({
      title: 'กำลังบันทึก...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading(),
    })

    // ✨ ยิงครั้งเดียวแบบ Batch — backend ประมวลผลทั้งหมดใน transaction เดียว
    // (atomic + Discord แจ้งเตือนรอบเดียว ไม่เด้งหลาย embed เหมือนลูปยิงทีละบิล)
    await FinanceService.confirmBatchPayment(currentServerId, {
      items: selectedPaymentIds.value.map((pid) => ({
        payment_id: pid,
        paid_amount: payAmounts.value[pid] || 0,
      })),
      paid_to_account_id: Number(paidToAccountId.value),
      slip_image_url: slipImageUrl.value || undefined,
      user_name: currentUserName,
    })

    Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: 'บันทึกการรับเงินรวบยอดเรียบร้อย',
      timer: 1500,
      showConfirmButton: false,
    })
    isModalOpen.value = false
    fetchDebtors()
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'บันทึกไม่สำเร็จ', 'error')
  }
}

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num)
}

onMounted(() => {
  fetchDebtors()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Outstanding Balances"
      title="สรุปผู้ค้างชำระ"
      description="รายชื่อผู้ค้างจ่ายเงินจากทุกโปรเจกต์ (รวมโปรเจกต์ที่ปิดไปแล้ว)"
    >
      <template #actions>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
      </template>
    </PageHeader>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-24" />

    <StateBlock v-else-if="hasError" variant="error" @retry="fetchDebtors" />

    <StateBlock
      v-else-if="!debtors.length"
      variant="empty"
      icon="bi-emoji-smile"
      title="ไม่มีใครติดหนี้ห้องเลย!"
      hint="ห้องนี้รวยมาก ทุกคนจ่ายเงินครบเป๊ะ"
    />

    <template v-else>
      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="d in debtors"
          :key="d.student_id"
          class="page-card border-s-4 border-s-red-500 p-4"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <span class="chip num bg-stone-100 text-stone-500">#{{ d.student_no }}</span>
              <h2 class="font-display mt-1.5 truncate text-base font-bold text-stone-900">
                {{ d.student_name }}
              </h2>
              <span class="chip mt-2 bg-amber-50 text-amber-700">
                <i class="bi bi-receipt" aria-hidden="true"></i>
                ค้าง {{ d.overdue_count }} รายการ
              </span>
            </div>

            <div class="shrink-0 text-right">
              <p class="text-[10px] font-bold uppercase tracking-[0.16em] text-stone-400">
                ยอดค้างชำระ
              </p>
              <p class="font-display num mt-1 text-xl font-bold text-red-600">
                ฿{{ formatNumber(d.total_pending_amount) }}
              </p>
            </div>
          </div>

          <div class="mt-3 flex justify-end border-t border-stone-100 pt-3">
            <button
              v-if="isAdmin"
              type="button"
              class="btn-primary w-full sm:w-auto"
              @click="handleClearDebt(d)"
            >
              <i class="bi bi-wallet2" aria-hidden="true"></i>
              เคลียร์หนี้
            </button>
            <span v-else class="chip bg-stone-100 text-stone-500">
              <i class="bi bi-lock" aria-hidden="true"></i>
              รอแอดมินดำเนินการ
            </span>
          </div>
        </div>
      </div>

      <!-- 🖥️ เดสก์ท็อป: ตาราง -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-24">เลขที่</th>
                <th>ชื่อนักเรียน</th>
                <th class="text-center">จำนวนที่ค้าง (บิล)</th>
                <th class="text-right">ยอดค้างชำระ (฿)</th>
                <th class="text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in debtors" :key="d.student_id">
                <td class="num font-bold text-stone-400">#{{ d.student_no }}</td>
                <td class="font-bold text-stone-900">{{ d.student_name }}</td>
                <td class="text-center">
                  <span class="chip bg-amber-50 text-amber-700">
                    <i class="bi bi-receipt" aria-hidden="true"></i>
                    ค้าง {{ d.overdue_count }} รายการ
                  </span>
                </td>
                <td
                  class="font-display num whitespace-nowrap text-right text-base font-bold text-red-600"
                >
                  ฿{{ formatNumber(d.total_pending_amount) }}
                </td>
                <td>
                  <div class="flex justify-end">
                    <button
                      v-if="isAdmin"
                      type="button"
                      class="btn-primary"
                      @click="handleClearDebt(d)"
                    >
                      <i class="bi bi-wallet2" aria-hidden="true"></i>
                      เคลียร์หนี้
                    </button>
                    <span v-else class="chip bg-stone-100 text-stone-500">
                      <i class="bi bi-lock" aria-hidden="true"></i>
                      รอแอดมิน
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- รับเงินรวบยอด: bottom sheet บนมือถือ / modal กลางจอบนเดสก์ท็อป -->
    <div
      v-if="isModalOpen && isAdmin"
      class="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
    >
      <div
        class="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-t-3xl border border-stone-200 bg-white md:max-h-[85vh] md:rounded-2xl"
      >
        <div
          class="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 px-4 py-4 sm:px-6"
        >
          <div class="min-w-0">
            <h2 class="font-display truncate text-lg font-bold text-stone-900">
              บันทึกรับเงินรวบยอด
            </h2>
            <p class="mt-0.5 flex items-center gap-1 truncate text-sm font-bold text-brand-700">
              <i class="bi bi-person-fill shrink-0" aria-hidden="true"></i>
              {{ selectedStudent?.name }}
            </p>
          </div>
          <button
            type="button"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-900 active:scale-[0.97]"
            aria-label="ปิดหน้าต่าง"
            @click="isModalOpen = false"
          >
            <i class="bi bi-x-lg text-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="flex-1 overflow-y-auto overscroll-contain bg-stone-50/50 p-4 sm:p-6">
          <div v-if="isLoadingDebts" class="flex justify-center py-10">
            <div
              class="h-8 w-8 animate-spin rounded-full border-2 border-stone-200 border-b-brand-700"
              role="status"
              aria-label="กำลังโหลดรายการค้างชำระ"
            ></div>
          </div>

          <div v-else class="space-y-3">
            <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">
              เลือกรายการบิลที่ต้องการชำระ
            </p>

            <label
              v-for="debt in studentDebts"
              :key="debt.payment_id"
              class="flex cursor-pointer items-center gap-3 rounded-2xl border p-4 transition-colors md:gap-4"
              :class="
                selectedPaymentIds.includes(debt.payment_id)
                  ? 'border-brand-200 bg-brand-50'
                  : 'border-stone-200 bg-white hover:border-stone-300'
              "
            >
              <!-- ช่องทำเครื่องหมาย (ซ่อน input จริงไว้) -->
              <span
                class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors"
                :class="
                  selectedPaymentIds.includes(debt.payment_id)
                    ? 'border-brand-700 bg-brand-700'
                    : 'border-stone-300 bg-white'
                "
              >
                <i
                  v-if="selectedPaymentIds.includes(debt.payment_id)"
                  class="bi bi-check-lg text-sm font-bold text-white"
                  aria-hidden="true"
                ></i>
              </span>
              <input
                v-model="selectedPaymentIds"
                type="checkbox"
                :value="debt.payment_id"
                class="hidden"
              />

              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-stone-900">{{ debt.title }}</p>
                <p class="num mt-0.5 text-[11px] font-bold text-red-600">
                  ยอดค้าง: ฿{{ formatNumber(debt.amount) }}
                </p>
              </div>

              <div class="relative w-28 shrink-0 md:w-32">
                <span
                  class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-sm font-bold text-stone-400"
                  aria-hidden="true"
                >
                  ฿
                </span>
                <input
                  v-model="payAmounts[debt.payment_id]"
                  type="number"
                  :disabled="!selectedPaymentIds.includes(debt.payment_id)"
                  :aria-label="`ยอดรับเงิน ${debt.title}`"
                  class="field num ps-7 text-right"
                />
              </div>
            </label>
          </div>

          <div class="page-card mt-6 p-4 sm:p-5">
            <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label class="field-label" for="payAccount">รับเข้ากระเป๋า</label>
                <select id="payAccount" v-model="paidToAccountId" class="field">
                  <option v-for="acc in accounts" :key="acc.id" :value="acc.id.toString()">
                    {{ acc.account_name }}
                  </option>
                </select>
              </div>
              <div>
                <label class="field-label" for="paySlip">URL รูปสลิป (ถ้ามี)</label>
                <input
                  id="paySlip"
                  v-model="slipImageUrl"
                  type="url"
                  class="field"
                  placeholder="https://..."
                />
              </div>
            </div>
          </div>
        </div>

        <div
          class="flex shrink-0 flex-col gap-3 border-t border-stone-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between sm:p-6"
        >
          <div class="flex items-center justify-between gap-3 sm:block">
            <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">
              ยอดรวมที่เลือกชำระ
            </p>
            <p class="font-display num text-2xl font-bold text-red-600">
              ฿{{ formatNumber(totalSelectedAmount) }}
            </p>
          </div>
          <button type="button" class="btn-primary w-full sm:w-auto" @click="handleBatchPay">
            <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
            ยืนยันการรับเงิน
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ซ่อนปุ่มลูกศรในช่อง Input Number ให้ดูคลีนๆ แบบแอปธนาคาร */
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
