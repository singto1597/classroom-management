<script setup lang="ts">
/**
 * 👤 บัญชีรายบุคคล — รายละเอียดนักเรียน 1 คน (FIN-V2 / P1.4)
 *
 * หน้านี้ **แยก route** โดยเจตนา (ไม่ใช่ modal) เพื่อส่งลิงก์ให้ผู้ปกครอง/นักเรียนได้
 * และเป็นที่ลงจอดของ "เปิดจากรายการเดินบัญชี" ในอนาคต
 *
 * รวมเป็น **โต๊ะทำงานของนักเรียน 1 คน**:
 *   บิลค้าง · รับเงิน · เครดิตเต็มรูปแบบ (เติม/ตัด/ประวัติ/ยกเลิกการหัก) · ประวัติรับเงินล่าสุด
 *
 * 🔓 อ่านอย่างเดียว · สมาชิกห้องอ่านได้ — ห้าม gate ด้วย `isAdmin`
 * 🔒 ปุ่มเขียน (รับเงิน/เติมเครดิต/หักเครดิต/ยกเลิก) gate ด้วย `canManageFinance`
 *
 * ⚠️ เงินเป็น string 2 ตำแหน่งจาก API ⇒ `formatMoney(Number(x))` / `formatAmount(Number(x))`
 *    ส่วน `CreditPanel`/โมดัลเครดิตใช้ `StudentCreditBalance` (number) ⇒ แปลงผ่าน `creditBalance`
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import type {
  Account,
  IndividualAccountItem,
  StudentCreditBalance,
  StudentCreditEntry,
} from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatAmount, formatMoney, roundMoney } from '@/utils/money'
import { formatThaiDate, formatThaiDateTime, todayIso } from '@/utils/datetime'

import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AccountSummaryCard from '@/components/finance/AccountSummaryCard.vue'
import ReceiveMoneyModal from '@/components/finance/ReceiveMoneyModal.vue'
import CreditPanel from '@/components/finance/CreditPanel.vue'
import CreditTopUpModal from '@/components/finance/CreditTopUpModal.vue'
import CreditApplyModal from '@/components/finance/CreditApplyModal.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useDialog } from '@/composables/useDialog'

const route = useRoute()
const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const canManageFinance = computed(() => authStore.canManageFinance)

const account = ref<IndividualAccountItem | null>(null)
const isLoading = ref(true)
const hasError = ref(false)
const notFound = ref(false)

const detailGuard = createLatestGuard()

const studentId = computed(() => Number(route.params.studentId))

const FUND_TYPE_LABELS: Record<string, string> = {
  room_fund: 'เงินห้อง',
  pass_through: 'เก็บแทน / ผ่านมือ',
}

const fundTypeLabel = (value: string | null) => (value ? FUND_TYPE_LABELS[value] ?? value : '—')

const today = todayIso()
const isOverdue = (dueDate: string | null) => !!dueDate && dueDate < today

// ─────────────────────────────────────────────────────── โหลดบัญชี
const loadAccount = async () => {
  const token = detailGuard.begin()
  isLoading.value = true
  hasError.value = false
  notFound.value = false
  try {
    const res = await FinanceService.getIndividualAccount(currentRoomId, studentId.value)
    if (!detailGuard.isCurrent(token)) return
    account.value = res
  } catch (error) {
    if (!detailGuard.isCurrent(token)) return
    // 404 = ไม่ใช่สมาชิกของห้องนี้ (หรือถูกลบ) — แสดง empty state ไม่ใช่ error กลาง
    if (apiStatus(error) === 404) {
      notFound.value = true
      account.value = null
      return
    }
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดบัญชีของนักเรียนไม่สำเร็จ', 'error')
  } finally {
    if (detailGuard.isCurrent(token)) isLoading.value = false
  }
}

// ─────────────────────────────────────────────────────── เครดิต (P3.3)
const creditEntries = ref<StudentCreditEntry[]>([])
const creditLoading = ref(false)
const creditError = ref(false)
const creditGuard = createLatestGuard()

const loadCredit = async () => {
  const token = creditGuard.begin()
  creditLoading.value = true
  creditError.value = false
  try {
    const res = await FinanceService.getStudentCredit(currentRoomId, studentId.value)
    if (!creditGuard.isCurrent(token)) return
    creditEntries.value = res.entries
  } catch {
    if (!creditGuard.isCurrent(token)) return
    // ไม่เด้ง alert ซ้ำกับ loadAccount — ส่วนเครดิตมี StateBlock ให้ลองใหม่เอง
    creditError.value = true
  } finally {
    if (creditGuard.isCurrent(token)) creditLoading.value = false
  }
}

const refreshAll = async () => {
  await Promise.all([loadAccount(), loadCredit()])
}

/** แปลง `IndividualAccountItem` (string) → `StudentCreditBalance` (number) ให้ CreditPanel/โมดัล */
const creditBalance = computed<StudentCreditBalance | null>(() => {
  const a = account.value
  if (!a) return null
  return {
    student_id: a.student_id,
    student_no: a.student_no,
    student_name: a.name,
    credit_balance: Number(a.credit_balance),
    total_pending_amount: Number(a.outstanding_total),
    net_pending_amount: roundMoney(Number(a.outstanding_total) - Number(a.ready_to_apply)),
  }
})

// ─────────────────────────────────────────────────────── กระเป๋าเงิน (โมดัลเติม/หัก)
const accounts = ref<Account[]>([])

const loadAccountOptions = async () => {
  if (!canManageFinance.value) {
    accounts.value = []
    return
  }
  try {
    accounts.value = await FinanceService.getAccounts(currentRoomId)
  } catch {
    accounts.value = []
  }
}

// ─────────────────────────────────────────────────────── รับเงิน (P2.3)
/** modal รับเงิน — เปิดได้เฉพาะผู้มีสิทธิ์ และต้องมี account โหลดแล้ว */
const receiveOpen = ref(false)

/** หลังบันทึกรับเงินสำเร็จ: การ์ดสรุป/บิล/เครดิต เปลี่ยนทั้งหมด ⇒ โหลดใหม่ทันที */
const onPaymentSaved = async () => {
  await refreshAll()
}

// ─────────────────────────────────────────────────────── เติม/หักเครดิต
const topUpOpen = ref(false)
const applyOpen = ref(false)

/** หลังเติม/หักสำเร็จ — ยอดบัญชีและประวัติเครดิตเปลี่ยนทั้งคู่ */
const onCreditChanged = async () => {
  await refreshAll()
}

/** ↩️ ยกเลิก "การหัก" 1 รายการ (คืนเครดิต + เปิดบิลกลับเป็นค้าง) */
const handleUndo = async (entry: StudentCreditEntry) => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ยกเลิกได้', 'error')
    return
  }
  // 🧾 แถวที่เกิดจากใบรับเงิน **ห้ามยกเลิกตรง** (backend ตอบ 409)
  if (entry.payment_event_id !== null && entry.payment_event_id !== undefined) {
    void dialog.alert(
      'ยกเลิกที่นี่ไม่ได้',
      `รายการนี้เกิดจากใบรับเงิน #${entry.payment_event_id} — ต้องยกเลิกที่รายการรับเงินนั้น ` +
        `(ระบบจะคืนบิล/เครดิต/บัญชีให้พร้อมกัน)`,
      'info',
    )
    return
  }
  const confirmed = await dialog.confirm(
    'ยกเลิกการหักนี้?',
    `คืนเครดิต ${formatMoney(entry.amount)} เข้ากระเป๋านักเรียน และเปิดบิลกลับเป็น "ค้างชำระ" · ` +
      `บิล: ${entry.collection_title ?? '—'} · รายการนี้จะยังอยู่ในประวัติ (ไม่ถูกลบ)`,
    {
      icon: 'warning',
      danger: true,
      confirmButtonText: 'ยืนยันยกเลิกการหัก',
      cancelButtonText: 'ไม่ใช่',
    },
  )
  if (!confirmed.isConfirmed) return

  try {
    const res = await FinanceService.undoCreditApplication(currentRoomId, {
      credit_entry_id: entry.id,
      user_name: currentUserName,
    })
    await dialog.fire({
      icon: 'success',
      title: 'ยกเลิกการหักเรียบร้อย',
      text:
        `คืนเครดิต ${formatMoney(res.reverted_amount)} · ` +
        `เครดิตคงเหลือ ${formatMoney(res.credit_balance_after)}`,
    })
    await refreshAll()
  } catch (error: unknown) {
    void dialog.alert(
      'ยกเลิกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีอะไรถูกเปลี่ยนแปลง',
      'error',
    )
  }
}

// route param เปลี่ยน (เช่นกดจากรายการเดินบัญชีของอีกคน) ⇒ โหลดใหม่ ไม่ค้างข้อมูลเก่า
// และปิดโมดัลทั้งหมดเพื่อกันบันทึกผิดคน
watch(studentId, () => {
  receiveOpen.value = false
  topUpOpen.value = false
  applyOpen.value = false
  creditEntries.value = []
  void refreshAll()
})

onMounted(() => {
  void loadAccountOptions()
  void refreshAll()
})
</script>

<template>
  <div class="space-y-3">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <StateBlock
      v-else-if="notFound"
      variant="empty"
      icon="bi-person-x"
      title="ไม่พบบัญชีของนักเรียนคนนี้"
      hint="นักเรียนอาจถูกลบหรือไม่ได้อยู่ในห้องนี้ — กลับไปที่รายการบัญชีรายบุคคล"
    >
      <RouterLink to="/finance/individual-accounts" class="btn-ghost-ui">
        <i class="bi bi-arrow-left" aria-hidden="true"></i>
        กลับไปบัญชีรายบุคคล
      </RouterLink>
    </StateBlock>

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดบัญชีของนักเรียนไม่สำเร็จ"
      @retry="refreshAll"
    />

    <template v-else-if="account">
      <div v-if="canManageFinance" class="flex justify-end">
        <AppButton variant="primary" @click="receiveOpen = true">
          <i class="bi bi-cash-coin" aria-hidden="true"></i>
          รับเงิน
        </AppButton>
      </div>

      <AccountSummaryCard :account="account" />

      <!-- ══════════════════════ บิลที่ยังเปิด ══════════════════════ -->
      <section class="page-card overflow-hidden">
        <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 class="font-display text-base font-bold text-ink-1">
            <i class="bi bi-receipt me-1.5 text-brand-700" aria-hidden="true"></i>
            บิลที่ยังค้าง
          </h2>
          <span class="chip bg-canvas text-ink-2">{{ account.open_bills.length }} รายการ</span>
        </div>

        <div
          v-if="!account.open_bills.length"
          class="px-4 py-8 text-center text-sm text-ink-3"
        >
          <i class="bi bi-check2-circle me-1 text-ok-600" aria-hidden="true"></i>
          ไม่มีบิลค้างของนักเรียนคนนี้
        </div>

        <template v-else>
          <!-- 📱 มือถือ: การ์ดต่อบิล -->
          <div class="space-y-2 p-3 lg:hidden">
            <div
              v-for="bill in account.open_bills"
              :key="bill.student_payment_id"
              class="rounded-control border p-3"
              :class="isOverdue(bill.due_date) ? 'border-danger-200 bg-danger-50' : 'border-line'"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-bold text-ink-1">{{ bill.title }}</p>
                  <p class="mt-0.5 flex flex-wrap items-center gap-1.5 text-caption text-ink-3">
                    <span>{{ fundTypeLabel(bill.fund_type) }}</span>
                    <span v-if="bill.collection_kind === 'fine'" class="chip bg-warn-50 text-warn-700">
                      ค่าปรับ
                    </span>
                  </p>
                </div>
                <p class="num shrink-0 text-right text-sm font-bold text-danger-600">
                  {{ formatMoney(Number(bill.outstanding)) }}
                </p>
              </div>

              <div class="mt-2 flex items-center justify-between gap-3 text-caption text-ink-3">
                <span
                  class="flex items-center gap-1"
                  :class="isOverdue(bill.due_date) ? 'font-bold text-danger-700' : ''"
                >
                  <i class="bi bi-calendar-event" aria-hidden="true"></i>
                  {{ bill.due_date ? formatThaiDate(bill.due_date) : 'ไม่กำหนด' }}
                </span>
                <span class="num">
                  ยอด {{ formatAmount(Number(bill.amount)) }}
                  · จ่าย {{ formatAmount(Number(bill.paid_amount)) }}
                  <template v-if="Number(bill.written_off_amount) > 0">
                    · ตัด {{ formatAmount(Number(bill.written_off_amount)) }}
                  </template>
                </span>
              </div>
            </div>
          </div>

          <!-- 🖥️ เดสก์ท็อป: ตาราง -->
          <div class="hidden overflow-x-auto lg:block">
            <table class="data-table">
              <thead>
                <tr>
                  <th>ชื่อบิล</th>
                  <th>ประเภท</th>
                  <th>กำหนด</th>
                  <th class="text-right">ยอด (฿)</th>
                  <th class="text-right">จ่ายแล้ว (฿)</th>
                  <th class="text-right">ตัดจำหน่าย (฿)</th>
                  <th class="text-right">คงเหลือ (฿)</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="bill in account.open_bills"
                  :key="bill.student_payment_id"
                  :class="isOverdue(bill.due_date) ? 'bg-danger-50' : ''"
                >
                  <td class="font-bold text-ink-1">
                    {{ bill.title }}
                    <span
                      v-if="bill.collection_kind === 'fine'"
                      class="chip ms-1 bg-warn-50 text-warn-700"
                    >
                      ค่าปรับ
                    </span>
                  </td>
                  <td class="text-ink-2">{{ fundTypeLabel(bill.fund_type) }}</td>
                  <td
                    class="whitespace-nowrap"
                    :class="isOverdue(bill.due_date) ? 'font-bold text-danger-700' : 'text-ink-2'"
                  >
                    {{ bill.due_date ? formatThaiDate(bill.due_date) : 'ไม่กำหนด' }}
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ formatAmount(Number(bill.amount)) }}
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ formatAmount(Number(bill.paid_amount)) }}
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ formatAmount(Number(bill.written_off_amount)) }}
                  </td>
                  <td class="num whitespace-nowrap text-right font-bold text-danger-600">
                    {{ formatAmount(Number(bill.outstanding)) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>

      <!-- ══════════════════════ เครดิต (เงินรับล่วงหน้า) ══════════════════════ -->
      <section class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="font-display text-base font-bold text-ink-1">
            <i class="bi bi-piggy-bank me-1.5 text-ok-700" aria-hidden="true"></i>
            เครดิต (เงินรับล่วงหน้า)
          </h2>
          <RouterLink
            :to="{ name: 'finance-student-statement', params: { studentId } }"
            class="btn-ghost-ui"
          >
            <i class="bi bi-journal-text" aria-hidden="true"></i>
            รายการเดินบัญชี
          </RouterLink>
        </div>

        <StateBlock
          v-if="creditError"
          variant="error"
          title="โหลดประวัติเครดิตไม่สำเร็จ"
          @retry="loadCredit"
        />

        <CreditPanel
          v-else-if="creditBalance"
          :student="creditBalance"
          :entries="creditEntries"
          :can-manage="canManageFinance"
          :loading="creditLoading"
          @topup="topUpOpen = true"
          @apply="applyOpen = true"
          @history="loadCredit"
          @undo="handleUndo"
        />
      </section>

      <!-- ══════════════════════ ประวัติรับเงินล่าสุด ══════════════════════ -->
      <section class="page-card overflow-hidden">
        <div class="border-b border-line px-4 py-3">
          <h2 class="font-display text-base font-bold text-ink-1">
            <i class="bi bi-clock-history me-1.5 text-brand-700" aria-hidden="true"></i>
            ประวัติรับเงินล่าสุด
          </h2>
        </div>

        <div v-if="!account.recent_events.length" class="px-4 py-8 text-center text-sm text-ink-3">
          <i class="bi bi-inbox me-1" aria-hidden="true"></i>
          ยังไม่มีประวัติรับเงิน
        </div>

        <ul v-else class="divide-y divide-line">
          <li
            v-for="event in account.recent_events"
            :key="event.event_id"
            class="flex items-center justify-between gap-3 px-4 py-3"
          >
            <div class="min-w-0">
              <p class="text-sm font-bold text-ink-1">
                {{ formatThaiDateTime(event.event_at) }}
              </p>
              <p class="mt-0.5 text-caption text-ink-3">
                ผู้รับเงิน {{ event.receiver_name || '—' }}
                <template v-if="Number(event.credit_used) > 0">
                  · ใช้เครดิต {{ formatMoney(Number(event.credit_used)) }}
                </template>
              </p>
            </div>
            <p class="num shrink-0 text-sm font-bold text-ok-700">
              {{ formatMoney(Number(event.amount_received)) }}
            </p>
          </li>
        </ul>
      </section>

      <ReceiveMoneyModal
        :open="receiveOpen"
        :student-id="account.student_id"
        :student-name="account.name"
        @close="receiveOpen = false"
        @saved="onPaymentSaved"
      />

      <CreditTopUpModal
        :open="topUpOpen"
        :student="creditBalance"
        :accounts="accounts"
        @close="topUpOpen = false"
        @saved="onCreditChanged"
      />

      <CreditApplyModal
        :open="applyOpen"
        :student="creditBalance"
        :accounts="accounts"
        @close="applyOpen = false"
        @applied="onCreditChanged"
      />
    </template>
  </div>
</template>
