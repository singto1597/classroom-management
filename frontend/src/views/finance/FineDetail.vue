<script setup lang="ts">
/**
 * ⚖️ รายละเอียดค่าปรับ — 1 ใบ + ประวัติคำขอยกเว้น/คืนเงิน (Phase 5)
 *
 * ════════════════════════════════════════════════════════════════════════════
 * 🔒 สิทธิ์
 * ════════════════════════════════════════════════════════════════════════════
 * - อ่าน: สมาชิกห้อง (นักเรียนเห็นเฉพาะใบของตัวเอง — backend กรองให้)
 * - เขียน/อนุมัติ: `MANAGE_FINANCE` ⇒ gate ด้วย `canManageFinance` ไม่ใช่ `isAdmin`
 * - **ห้ามอนุมัติคำขอของตัวเอง** — backend ตอบ 403; หน้าจอซ่อนปุ่มเมื่อรู้ล่วงหน้า
 *   (รู้ได้เฉพาะ `requested_by`; กรณี "ผู้ออกค่าปรับ" ให้ backend เป็นคนกันอีกชั้น)
 *
 * ════════════════════════════════════════════════════════════════════════════
 * ⚙️ กติกาวงจรชีวิต
 * ════════════════════════════════════════════════════════════════════════════
 * - แก้ไข/ยกเลิกได้ **ก่อนจ่าย** (paid_amount = 0)
 * - จ่ายแล้ว → ใช้ยกเว้น/ลด หรือคืนเงินเท่านั้น (ไม่ใช่ยกเลิก)
 * - ชำระเงินใช้ flow เดิม `confirmBatchPayment` (1 รายการ) → ออก REC- ให้ในธุรกรรมเดียว
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  FineDetail as FineDetailData,
  FineWaiver,
  FineRefund,
} from '@/types/finance'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import AppChip from '@/components/ui/AppChip.vue'
import { formatMoney, roundMoney } from '@/utils/money'
import { formatThaiDate, formatThaiDateTime } from '@/utils/datetime'
import { useDialog } from '@/composables/useDialog'
import {
  WAIVER_CATEGORY_LABELS,
  WAIVER_STATUS_LABELS,
  REFUND_STATUS_LABELS,
  fineStatusLabel,
  fineStatusTone,
} from '@/constants/financeFines'

const route = useRoute()
const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const currentUserId = Number(authStore.userId)
const canManageFinance = computed(() => authStore.canManageFinance)

const fineId = computed(() => Number(route.params.id))

const fine = ref<FineDetailData | null>(null)
const accounts = ref<Account[]>([])
const isLoading = ref(true)
const hasError = ref(false)

const walletName = (accountId: number) =>
  accounts.value.find((a) => a.id === accountId)?.account_name ?? `กระเป๋า #${accountId}`

const waistTone = (status: string): 'neutral' | 'ok' | 'warn' | 'danger' =>
  status === 'approved' ? 'ok' : status === 'rejected' ? 'danger' : status === 'pending' ? 'warn' : 'neutral'

const isSelfRequested = (requestedBy: number | null) =>
  requestedBy !== null && currentUserId > 0 && requestedBy === currentUserId

const load = async () => {
  if (!Number.isFinite(fineId.value) || fineId.value <= 0) {
    hasError.value = true
    isLoading.value = false
    return
  }
  isLoading.value = true
  hasError.value = false
  try {
    const [detail, acc] = await Promise.all([
      FinanceService.getFine(currentRoomId, fineId.value),
      FinanceService.getAccounts(currentRoomId),
    ])
    fine.value = detail
    accounts.value = acc
  } catch {
    hasError.value = true
  } finally {
    isLoading.value = false
  }
}

onMounted(load)
watch(fineId, load)

// ─────────────────────────────────────────────────────── สถานะที่ใช้ตัดสินปุ่ม
const pendingWaiver = computed(
  () => fine.value?.waivers.find((w) => w.status === 'pending') ?? null,
)
const pendingRefund = computed(
  () => fine.value?.refunds.find((r) => r.status === 'pending') ?? null,
)

const refundable = computed(() =>
  fine.value ? roundMoney(fine.value.paid_amount - fine.value.refunded_amount) : 0,
)

const canPay = computed(
  () =>
    canManageFinance.value &&
    !!fine.value &&
    fine.value.outstanding > 0.005 &&
    !['cancelled', 'paid', 'waived', 'refunded'].includes(fine.value.status),
)

const canEdit = computed(
  () => canManageFinance.value && fine.value?.status === 'issued' && fine.value.paid_amount <= 0.005,
)

const canCancel = computed(
  () =>
    canManageFinance.value &&
    !!fine.value &&
    fine.value.paid_amount <= 0.005 &&
    fine.value.refunded_amount <= 0.005 &&
    !['cancelled', 'waived', 'refunded'].includes(fine.value.status),
)

const canRequestWaiver = computed(
  () => canManageFinance.value && !!fine.value && fine.value.outstanding > 0.005 && !pendingWaiver.value,
)

const canRequestRefund = computed(
  () => canManageFinance.value && refundable.value > 0.005 && !pendingRefund.value,
)

// ════════════════════════════════════════════════════════════════════════════
// 💵 ชำระเงิน (1 บิลผ่าน batch flow เดิม → ออกใบเสร็จในธุรกรรมเดียว)
// ════════════════════════════════════════════════════════════════════════════
const isPayOpen = ref(false)
const isPaying = ref(false)
const payAmount = ref('')
const payAccountId = ref('')
const paySlipUrl = ref('')
const payIssueReceipt = ref(true)

const payAmountNumber = computed(() => {
  const n = Number(payAmount.value)
  return Number.isFinite(n) && n > 0 ? roundMoney(n) : 0
})

const openPay = () => {
  if (!fine.value) return
  payAmount.value = fine.value.outstanding.toString()
  payAccountId.value = accounts.value[0]?.id.toString() ?? ''
  paySlipUrl.value = ''
  payIssueReceipt.value = true
  isPayOpen.value = true
}

const handlePay = async () => {
  if (!canManageFinance.value || !fine.value) return
  if (payAmountNumber.value <= 0) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกจำนวนเงินมากกว่า 0 บาท', 'warning')
    return
  }
  if (payAmountNumber.value > fine.value.outstanding + 0.005) {
    void dialog.alert('อ๊ะ!', 'ยอดชำระต้องไม่เกินยอดคงเหลือ', 'warning')
    return
  }
  if (!payAccountId.value) {
    void dialog.alert('ยังไม่เลือกกระเป๋า', 'กรุณาเลือกกระเป๋าเงินที่รับเงินจริง', 'warning')
    return
  }

  isPaying.value = true
  try {
    const res = await FinanceService.confirmBatchPayment(currentRoomId, {
      items: [{ payment_id: fine.value.student_payment_id, paid_amount: payAmountNumber.value }],
      paid_to_account_id: Number(payAccountId.value),
      slip_image_url: paySlipUrl.value.trim() || null,
      user_name: currentUserName,
      issue_receipts: payIssueReceipt.value,
    })
    const nos = res.receipts.map((r) => r.receipt_no)
    await dialog.alert(
      'บันทึกการรับเงินเรียบร้อย',
      nos.length > 0
        ? `รับเงิน ${formatMoney(payAmountNumber.value)} · ออกใบเสร็จ ${nos.join(', ')}`
        : `รับเงิน ${formatMoney(payAmountNumber.value)}`,
      'success',
    )
    isPayOpen.value = false
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'บันทึกการรับเงินไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีรายการใดถูกบันทึก',
      'error',
    )
  } finally {
    isPaying.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ✏️ แก้ไข (ก่อนจ่ายเท่านั้น) — backend void/ออก INV ใหม่ให้เอง
// ════════════════════════════════════════════════════════════════════════════
const isEditOpen = ref(false)
const isSavingEdit = ref(false)
const editAmount = ref('')
const editIncident = ref('')
const editDue = ref('')
const editReason = ref('')
const editEvidence = ref('')
const editNote = ref('')

const openEdit = () => {
  if (!fine.value) return
  editAmount.value = fine.value.amount.toString()
  editIncident.value = fine.value.incident_date
  editDue.value = fine.value.due_date
  editReason.value = fine.value.reason
  editEvidence.value = fine.value.evidence_url ?? ''
  editNote.value = fine.value.note ?? ''
  isEditOpen.value = true
}

const handleSaveEdit = async () => {
  if (!canManageFinance.value || !fine.value) return
  const amount = Number(editAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) {
    void dialog.alert('อ๊ะ!', 'ยอดค่าปรับต้องมากกว่า 0', 'warning')
    return
  }
  if (!editReason.value.trim()) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกเหตุผล', 'warning')
    return
  }
  isSavingEdit.value = true
  try {
    await FinanceService.updateFine(currentRoomId, fine.value.id, {
      amount: roundMoney(amount),
      incident_date: editIncident.value,
      due_date: editDue.value,
      reason: editReason.value.trim(),
      evidence_url: editEvidence.value.trim() || null,
      note: editNote.value.trim() || null,
      user_name: currentUserName,
    })
    await dialog.alert('บันทึกแล้ว', 'ค่าปรับถูกแก้ไขและออกใบแจ้งหนี้ใหม่ให้แล้ว', 'success')
    isEditOpen.value = false
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'แก้ไขไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  } finally {
    isSavingEdit.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ❌ ยกเลิก (ก่อนจ่ายเท่านั้น) — กลับ journal + soft delete บิล
// ════════════════════════════════════════════════════════════════════════════
const isCancelling = ref(false)

const handleCancel = async () => {
  if (!canManageFinance.value || !fine.value) return
  const note = await dialog.input('ยกเลิกค่าปรับนี้?', {
    text: 'เหตุผล (ไม่บังคับ) — ใช้เป็นบันทึกในประวัติ',
    input: 'textarea',
    danger: true,
    confirmButtonText: 'ยกเลิกค่าปรับ',
  })
  if (!note.isConfirmed) return

  isCancelling.value = true
  try {
    await FinanceService.cancelFine(currentRoomId, fine.value.id, {
      reason: note.value.trim() || null,
      user_name: currentUserName,
    })
    await dialog.alert('ยกเลิกแล้ว', 'ค่าปรับถูกยกเลิกและกลับรายการบัญชีให้แล้ว', 'success')
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'ยกเลิกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  } finally {
    isCancelling.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 🛡️ คำขอยกเว้น/ลด
// ════════════════════════════════════════════════════════════════════════════
const isWaiverOpen = ref(false)
const isSavingWaiver = ref(false)
const waiverAmount = ref('')
const waiverCategory = ref<'discount' | 'uncollectible'>('discount')
const waiverReason = ref('')

const openWaiver = () => {
  if (!fine.value) return
  waiverAmount.value = fine.value.outstanding.toString()
  waiverCategory.value = 'discount'
  waiverReason.value = ''
  isWaiverOpen.value = true
}

const handleRequestWaiver = async () => {
  if (!canManageFinance.value || !fine.value) return
  const amount = Number(waiverAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) {
    void dialog.alert('อ๊ะ!', 'ยอดยกเว้นต้องมากกว่า 0', 'warning')
    return
  }
  if (amount > fine.value.outstanding + 0.005) {
    void dialog.alert('อ๊ะ!', 'ยอดยกเว้นต้องไม่เกินยอดคงเหลือ', 'warning')
    return
  }
  if (!waiverReason.value.trim()) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกเหตุผลการยกเว้น', 'warning')
    return
  }
  isSavingWaiver.value = true
  try {
    await FinanceService.requestWaiver(currentRoomId, fine.value.id, {
      amount: roundMoney(amount),
      reason_category: waiverCategory.value,
      reason: waiverReason.value.trim(),
      user_name: currentUserName,
    })
    await dialog.alert(
      'ส่งคำขอแล้ว',
      'รอให้ผู้มีสิทธิ์จัดการการเงินคนอื่นอนุมัติ (ห้ามอนุมัติคำขอของตัวเอง)',
      'success',
    )
    isWaiverOpen.value = false
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'ส่งคำขอไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  } finally {
    isSavingWaiver.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 💸 คำขอคืนเงิน
// ════════════════════════════════════════════════════════════════════════════
const isRefundOpen = ref(false)
const isSavingRefund = ref(false)
const refundAmount = ref('')
const refundAccountId = ref('')
const refundReason = ref('')

const openRefund = () => {
  refundAmount.value = refundable.value.toString()
  refundAccountId.value = accounts.value[0]?.id.toString() ?? ''
  refundReason.value = ''
  isRefundOpen.value = true
}

const handleRequestRefund = async () => {
  if (!canManageFinance.value || !fine.value) return
  const amount = Number(refundAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) {
    void dialog.alert('อ๊ะ!', 'ยอดคืนเงินต้องมากกว่า 0', 'warning')
    return
  }
  if (amount > refundable.value + 0.005) {
    void dialog.alert('อ๊ะ!', 'ยอดคืนเงินต้องไม่เกินยอดที่ชำระมาและยังไม่ถูกคืน', 'warning')
    return
  }
  if (!refundAccountId.value) {
    void dialog.alert('ยังไม่เลือกกระเป๋า', 'กรุณาเลือกกระเป๋าที่จะจ่ายเงินคืน', 'warning')
    return
  }
  if (!refundReason.value.trim()) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกเหตุผลการคืนเงิน', 'warning')
    return
  }
  isSavingRefund.value = true
  try {
    await FinanceService.requestRefund(currentRoomId, fine.value.id, {
      account_id: Number(refundAccountId.value),
      amount: roundMoney(amount),
      reason: refundReason.value.trim(),
      user_name: currentUserName,
    })
    await dialog.alert(
      'ส่งคำขอแล้ว',
      'รอให้ผู้มีสิทธิ์จัดการการเงินคนอื่นอนุมัติก่อน เงินจะยังไม่ออกจากกระเป๋า',
      'success',
    )
    isRefundOpen.value = false
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'ส่งคำขอไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  } finally {
    isSavingRefund.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ✅ อนุมัติ / ปฏิเสธ (ในนามของอีกคน)
// ════════════════════════════════════════════════════════════════════════════
const handleWaiverDecision = async (waiver: FineWaiver, action: 'approve' | 'reject') => {
  if (!canManageFinance.value) return
  const verb = action === 'approve' ? 'อนุมัติ' : 'ปฏิเสธ'
  const ok = await dialog.confirm(
    `${verb}คำขอยกเว้น ${formatMoney(waiver.amount)}?`,
    action === 'approve'
      ? 'การอนุมัติจะลดยอดบิลและลงบัญชีส่วนลด/หนี้สูญให้ทันที'
      : 'คำขอจะถูกปิดโดยไม่กระทบยอดค่าปรับ',
    { danger: action === 'reject', confirmButtonText: verb },
  )
  if (!ok.isConfirmed) return
  try {
    if (action === 'approve') {
      await FinanceService.approveWaiver(currentRoomId, waiver.id, { user_name: currentUserName })
    } else {
      await FinanceService.rejectWaiver(currentRoomId, waiver.id, { user_name: currentUserName })
    }
    dialog.notify(`${verb}คำขอยกเว้นแล้ว`)
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      `${verb}ไม่สำเร็จ`,
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  }
}

const handleRefundDecision = async (refund: FineRefund, action: 'approve' | 'reject') => {
  if (!canManageFinance.value) return
  const verb = action === 'approve' ? 'อนุมัติ' : 'ปฏิเสธ'
  const ok = await dialog.confirm(
    `${verb}คำขอคืนเงิน ${formatMoney(refund.amount)}?`,
    action === 'approve'
      ? `เงินจะถูกจ่ายออกจาก ${walletName(refund.account_id)} และออกใบสำคัญจ่าย (PV-) ให้ทันที`
      : 'คำขอจะถูกปิดโดยไม่จ่ายเงิน',
    { danger: action === 'reject', confirmButtonText: verb },
  )
  if (!ok.isConfirmed) return
  try {
    if (action === 'approve') {
      const res = await FinanceService.approveRefund(currentRoomId, refund.id, {
        user_name: currentUserName,
      })
      dialog.notify(res.receipt_no ? `คืนเงินแล้ว · PV ${res.receipt_no}` : 'คืนเงินแล้ว')
    } else {
      await FinanceService.rejectRefund(currentRoomId, refund.id, { user_name: currentUserName })
      dialog.notify('ปฏิเสธคำขอคืนเงินแล้ว')
    }
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      `${verb}ไม่สำเร็จ`,
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  }
}
</script>

<template>
  <div class="space-y-4">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <StateBlock
      v-else-if="hasError || !fine"
      variant="error"
      title="โหลดรายละเอียดค่าปรับไม่สำเร็จ"
      @retry="load"
    />

    <template v-else>
      <PageIntro :description="`${fine.fine_type_name} · เกิดเหตุ ${formatThaiDate(fine.incident_date)}`">
        <template #actions>
          <AppButton variant="secondary" to="/finance/fines">
            <i class="bi bi-arrow-left" aria-hidden="true"></i>
            กลับรายการ
          </AppButton>
          <AppButton v-if="canPay" variant="primary" @click="openPay">
            <i class="bi bi-cash-coin" aria-hidden="true"></i>
            บันทึกชำระเงิน
          </AppButton>
        </template>
      </PageIntro>

      <!-- ══════════════════════ ข้อมูลหลัก ══════════════════════ -->
      <div class="page-card p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <StatusBadge :tone="fineStatusTone(fine.status)" :label="fineStatusLabel(fine.status)" />
              <AppChip tone="neutral" icon="bi-person-badge">
                {{ fine.student_name ?? 'ไม่ทราบชื่อ' }}
                <template v-if="fine.student_no"> · เลขที่ {{ fine.student_no }}</template>
              </AppChip>
            </div>
            <p class="mt-2 break-words text-sm text-ink">{{ fine.reason }}</p>
            <p v-if="fine.note" class="mt-1 break-words text-xs text-ink-2">หมายเหตุ: {{ fine.note }}</p>
            <a
              v-if="fine.evidence_url"
              :href="fine.evidence_url"
              target="_blank"
              rel="noopener noreferrer"
              class="mt-1 inline-block text-xs font-bold text-brand hover:underline"
            >
              เปิดหลักฐาน
            </a>
          </div>
          <div class="text-right">
            <p class="text-caption font-bold text-ink-3">ยอดคงเหลือ</p>
            <p class="font-display num text-2xl font-bold text-danger-600">
              {{ formatMoney(fine.outstanding) }}
            </p>
          </div>
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
          <div>
            <dt class="text-caption text-ink-3">ยอดเดิม</dt>
            <dd class="num font-bold text-ink">{{ formatMoney(fine.original_amount) }}</dd>
          </div>
          <div>
            <dt class="text-caption text-ink-3">ยอดปัจจุบัน</dt>
            <dd class="num font-bold text-ink">{{ formatMoney(fine.amount) }}</dd>
          </div>
          <div>
            <dt class="text-caption text-ink-3">ชำระแล้ว</dt>
            <dd class="num font-bold text-ok-700">{{ formatMoney(fine.paid_amount) }}</dd>
          </div>
          <div>
            <dt class="text-caption text-ink-3">ยกเว้นแล้ว</dt>
            <dd class="num font-bold text-ink">{{ formatMoney(fine.waived_amount) }}</dd>
          </div>
          <div>
            <dt class="text-caption text-ink-3">คืนเงินแล้ว</dt>
            <dd class="num font-bold text-ink">{{ formatMoney(fine.refunded_amount) }}</dd>
          </div>
          <div>
            <dt class="text-caption text-ink-3">กำหนดชำระ</dt>
            <dd class="font-bold text-ink">{{ formatThaiDate(fine.due_date) }}</dd>
          </div>
        </dl>

        <div class="mt-4 flex flex-wrap items-center gap-1.5">
          <AppChip tone="neutral" icon="bi-calendar-check">
            เกิดเหตุ {{ formatThaiDate(fine.incident_date) }}
          </AppChip>
          <AppChip v-if="fine.incident_date === fine.due_date" tone="warn" icon="bi-clock">
            ครบกำหนดวันเดียวกับเกิดเหตุ
          </AppChip>
          <RouterLink
            v-if="fine.invoice_no"
            :to="`/finance/receipts/${fine.invoice_no}`"
            class="chip bg-info-50 text-info-700 transition-colors hover:bg-info-100"
          >
            <i class="bi bi-file-earmark-text" aria-hidden="true"></i>
            {{ fine.invoice_no }}
          </RouterLink>
        </div>

        <!-- ทางเลือกตามสถานะ -->
        <div
          v-if="canManageFinance"
          class="mt-4 flex flex-wrap gap-2 border-t border-line pt-4"
        >
          <AppButton v-if="canEdit" variant="secondary" @click="openEdit">แก้ไข</AppButton>
          <AppButton v-if="canRequestWaiver" variant="secondary" @click="openWaiver">
            ขอยกเว้น/ลด
          </AppButton>
          <AppButton v-if="canRequestRefund" variant="secondary" @click="openRefund">
            ขอคืนเงิน
          </AppButton>
          <AppButton v-if="canCancel" variant="danger" :loading="isCancelling" @click="handleCancel">
            ยกเลิกค่าปรับ
          </AppButton>
          <p v-if="!canEdit && !canCancel && fine.status !== 'cancelled'" class="text-xs text-ink-3">
            ชำระเงินแล้ว — แก้ยอด/ยกเลิกไม่ได้ ใช้ยกเว้นหรือคืนเงินแทน
          </p>
        </div>
      </div>

      <!-- ══════════════════════ คำขอยกเว้น ══════════════════════ -->
      <section class="space-y-2">
        <h2 class="section-title flex items-center gap-2">
          <i class="bi bi-shield-minus text-brand-700" aria-hidden="true"></i>
          คำขอยกเว้น/ลด ({{ fine.waivers.length }})
        </h2>

        <p v-if="!fine.waivers.length" class="px-1 text-xs text-ink-3">ยังไม่มีคำขอยกเว้น</p>

        <ul v-else class="space-y-2">
          <li
            v-for="w in fine.waivers"
            :key="`w-${w.id}`"
            class="rounded-card border border-line bg-surface p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <p class="text-sm font-bold text-ink">
                  {{ WAIVER_CATEGORY_LABELS[w.reason_category] ?? w.reason_category }}
                </p>
                <p class="mt-0.5 break-words text-xs text-ink-2">{{ w.reason }}</p>
                <p class="mt-1 text-caption text-ink-3">
                  ขอเมื่อ {{ formatThaiDateTime(w.requested_at) }}
                  <template v-if="w.decided_at"> · ตัดสิน {{ formatThaiDateTime(w.decided_at) }}</template>
                </p>
                <p v-if="w.decision_note" class="mt-0.5 text-xs text-ink-2">
                  หมายเหตุ: {{ w.decision_note }}
                </p>
              </div>
              <div class="shrink-0 text-right">
                <p class="num text-sm font-bold text-ink">{{ formatMoney(w.amount) }}</p>
                <StatusBadge
                  :tone="waistTone(w.status)"
                  :label="WAIVER_STATUS_LABELS[w.status] ?? w.status"
                />
              </div>
            </div>
            <div v-if="canManageFinance && w.status === 'pending'" class="mt-3 flex flex-wrap gap-2">
              <AppButton
                variant="primary"
                :disabled="isSelfRequested(w.requested_by)"
                @click="handleWaiverDecision(w, 'approve')"
              >
                อนุมัติ
              </AppButton>
              <AppButton variant="secondary" @click="handleWaiverDecision(w, 'reject')">
                ปฏิเสธ
              </AppButton>
              <span v-if="isSelfRequested(w.requested_by)" class="self-center text-xs text-ink-3">
                ห้ามอนุมัติคำขอของตัวเอง
              </span>
            </div>
          </li>
        </ul>
      </section>

      <!-- ══════════════════════ คำขอคืนเงิน ══════════════════════ -->
      <section class="space-y-2">
        <h2 class="section-title flex items-center gap-2">
          <i class="bi bi-cash-coin text-brand-700" aria-hidden="true"></i>
          คำขอคืนเงิน ({{ fine.refunds.length }})
        </h2>

        <p v-if="!fine.refunds.length" class="px-1 text-xs text-ink-3">ยังไม่มีคำขอคืนเงิน</p>

        <ul v-else class="space-y-2">
          <li
            v-for="r in fine.refunds"
            :key="`r-${r.id}`"
            class="rounded-card border border-line bg-surface p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <p class="text-sm font-bold text-ink">{{ walletName(r.account_id) }}</p>
                <p class="mt-0.5 break-words text-xs text-ink-2">{{ r.reason }}</p>
                <p class="mt-1 text-caption text-ink-3">
                  ขอเมื่อ {{ formatThaiDateTime(r.requested_at) }}
                  <template v-if="r.decided_at"> · ตัดสิน {{ formatThaiDateTime(r.decided_at) }}</template>
                </p>
                <p v-if="r.decision_note" class="mt-0.5 text-xs text-ink-2">
                  หมายเหตุ: {{ r.decision_note }}
                </p>
              </div>
              <div class="shrink-0 text-right">
                <p class="num text-sm font-bold text-ink">{{ formatMoney(r.amount) }}</p>
                <StatusBadge
                  :tone="waistTone(r.status)"
                  :label="REFUND_STATUS_LABELS[r.status] ?? r.status"
                />
              </div>
            </div>
            <div v-if="canManageFinance && r.status === 'pending'" class="mt-3 flex flex-wrap gap-2">
              <AppButton
                variant="primary"
                :disabled="isSelfRequested(r.requested_by)"
                @click="handleRefundDecision(r, 'approve')"
              >
                อนุมัติ
              </AppButton>
              <AppButton variant="secondary" @click="handleRefundDecision(r, 'reject')">
                ปฏิเสธ
              </AppButton>
              <span v-if="isSelfRequested(r.requested_by)" class="self-center text-xs text-ink-3">
                ห้ามอนุมัติคำขอของตัวเอง
              </span>
            </div>
          </li>
        </ul>
      </section>
    </template>

    <!-- ══════════════════════ แผ่น: ชำระเงิน ══════════════════════ -->
    <AppSheet
      :open="isPayOpen"
      label="บันทึกชำระเงิน"
      title="บันทึกชำระเงิน"
      :description="fine ? `ยอดคงเหลือ ${formatMoney(fine.outstanding)}` : undefined"
      size="form"
      :dismissible="!isPaying"
      @close="isPayOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="pay-amount">จำนวนเงินที่รับ (บาท)</label>
          <input
            id="pay-amount"
            v-model="payAmount"
            type="number"
            min="0.01"
            step="0.01"
            inputmode="decimal"
            class="field num"
          />
        </div>
        <div>
          <label class="field-label" for="pay-account">กระเป๋าที่เงินเข้าจริง</label>
          <select id="pay-account" v-model="payAccountId" class="field">
            <option v-for="a in accounts" :key="a.id" :value="a.id.toString()">
              {{ a.account_name }}
            </option>
          </select>
        </div>
        <div>
          <label class="field-label" for="pay-slip">ลิงก์สลิป (ไม่บังคับ)</label>
          <input
            id="pay-slip"
            v-model="paySlipUrl"
            type="url"
            maxlength="1000"
            class="field"
            placeholder="https://…"
          />
        </div>
        <label class="flex cursor-pointer items-center gap-2 text-sm">
          <input v-model="payIssueReceipt" type="checkbox" class="h-4 w-4 accent-brand" />
          ออกใบเสร็จรับเงิน (REC-) ให้ในรอบนี้
        </label>
      </div>
      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isPayOpen = false">ยกเลิก</button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isPaying || payAmountNumber <= 0"
            @click="handlePay"
          >
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            ยืนยันรับ {{ formatMoney(payAmountNumber) }}
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ══════════════════════ แผ่น: แก้ไข ══════════════════════ -->
    <AppSheet
      :open="isEditOpen"
      label="แก้ไขค่าปรับ"
      title="แก้ไขค่าปรับ"
      description="ทำได้ก่อนชำระเงินเท่านั้น · ระบบจะออกใบแจ้งหนี้ใหม่ให้"
      size="form"
      :dismissible="!isSavingEdit"
      @close="isEditOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="edit-amount">ยอดค่าปรับ (บาท)</label>
          <input
            id="edit-amount"
            v-model="editAmount"
            type="number"
            min="0.01"
            step="0.01"
            inputmode="decimal"
            class="field num"
          />
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="field-label" for="edit-incident">วันที่เกิดเหตุ</label>
            <input id="edit-incident" v-model="editIncident" type="date" class="field" />
          </div>
          <div>
            <label class="field-label" for="edit-due">กำหนดชำระ</label>
            <input id="edit-due" v-model="editDue" type="date" class="field" />
          </div>
        </div>
        <div>
          <label class="field-label" for="edit-reason">เหตุผล</label>
          <textarea id="edit-reason" v-model="editReason" rows="2" maxlength="1000" class="field"></textarea>
        </div>
        <div>
          <label class="field-label" for="edit-evidence">ลิงก์หลักฐาน (ไม่บังคับ)</label>
          <input id="edit-evidence" v-model="editEvidence" type="url" maxlength="1000" class="field" />
        </div>
        <div>
          <label class="field-label" for="edit-note">หมายเหตุ (ไม่บังคับ)</label>
          <input id="edit-note" v-model="editNote" type="text" maxlength="1000" class="field" />
        </div>
      </div>
      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isEditOpen = false">ยกเลิก</button>
          <button type="button" class="btn-primary" :disabled="isSavingEdit" @click="handleSaveEdit">
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            บันทึก
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ══════════════════════ แผ่น: ขอยกเว้น ══════════════════════ -->
    <AppSheet
      :open="isWaiverOpen"
      label="ขอยกเว้นค่าปรับ"
      title="ขอยกเว้น/ลดค่าปรับ"
      description="ต้องให้ผู้มีสิทธิ์คนอื่นอนุมัติ · ห้ามอนุมัติคำขอของตัวเอง"
      size="form"
      :dismissible="!isSavingWaiver"
      @close="isWaiverOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="waiver-amount">ยอดที่ขอยกเว้น (บาท)</label>
          <input
            id="waiver-amount"
            v-model="waiverAmount"
            type="number"
            min="0.01"
            step="0.01"
            inputmode="decimal"
            class="field num"
          />
        </div>
        <div>
          <label class="field-label" for="waiver-category">เหตุผลทางบัญชี</label>
          <select id="waiver-category" v-model="waiverCategory" class="field">
            <option value="discount">ส่วนลดค่าปรับ (contra-revenue 49002)</option>
            <option value="uncollectible">หนี้สูญ — ตามไม่ได้ (ค่าใช้จ่าย 59001)</option>
          </select>
        </div>
        <div>
          <label class="field-label" for="waiver-reason">เหตุผล</label>
          <textarea id="waiver-reason" v-model="waiverReason" rows="2" maxlength="1000" class="field"></textarea>
        </div>
      </div>
      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isWaiverOpen = false">ยกเลิก</button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isSavingWaiver"
            @click="handleRequestWaiver"
          >
            <i class="bi bi-send" aria-hidden="true"></i>
            ส่งคำขอ
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ══════════════════════ แผ่น: ขอคืนเงิน ══════════════════════ -->
    <AppSheet
      :open="isRefundOpen"
      label="ขอคืนเงินค่าปรับ"
      title="ขอคืนเงินค่าปรับ"
      :description="`คืนได้ไม่เกิน ${formatMoney(refundable)}`"
      size="form"
      :dismissible="!isSavingRefund"
      @close="isRefundOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="refund-amount">ยอดคืนเงิน (บาท)</label>
          <input
            id="refund-amount"
            v-model="refundAmount"
            type="number"
            min="0.01"
            step="0.01"
            inputmode="decimal"
            class="field num"
          />
        </div>
        <div>
          <label class="field-label" for="refund-account">กระเป๋าที่จ่ายเงินคืน</label>
          <select id="refund-account" v-model="refundAccountId" class="field">
            <option v-for="a in accounts" :key="a.id" :value="a.id.toString()">
              {{ a.account_name }} · {{ formatMoney(a.balance) }}
            </option>
          </select>
        </div>
        <div>
          <label class="field-label" for="refund-reason">เหตุผล</label>
          <textarea id="refund-reason" v-model="refundReason" rows="2" maxlength="1000" class="field"></textarea>
        </div>
      </div>
      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isRefundOpen = false">ยกเลิก</button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isSavingRefund"
            @click="handleRequestRefund"
          >
            <i class="bi bi-send" aria-hidden="true"></i>
            ส่งคำขอ
          </button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
