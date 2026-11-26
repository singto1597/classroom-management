<script setup lang="ts">
/**
 * 💸 ReceiveMoneyModal — รับเงิน 1 ครั้ง = 1 event (FIN-V2 / P2.3)
 *
 * 🎯 หนึ่งครั้งที่กดยืนยัน ⇒ 1 `payment_event` ⇒ REC 1 ใบ (หลายบรรทัด) + DEP ถ้ามีส่วนเกิน
 * 🔒 ใช้ **preview จาก engine ตัวเดียวกับ commit** (P1.5/P2.1) ให้ครูเห็นผลก่อนจ่าย
 * ⚠️ เส้นนี้ไม่เรียก `confirmPayment`/`confirmBatchPayment` (legacy ออกใบเสร็จแยกต่อบิล)
 *
 * 🔴 กฎที่ห้ามพลาด
 *  1. `idempotency_key` สร้าง **ครั้งแรกที่กด** และคงค่าเดิมตอน retry/ล้มเหลว
 *     (สร้างใหม่ = รายการใหม่ ⇒ เงินสองรอบจากเงินก้อนเดียว)
 *  2. preview เป็น snapshot ไม่ใช่สัญญา: คนอื่นปิดบิลระหว่างนี้ได้ ⇒ commit ตอบ 409
 *     ต้อง reload แล้วให้ผู้ใช้ดูใหม่ ห้าม resubmit เงียบ ๆ ด้วยยอดเก่า
 *  3. `excess_action='none'` + เงินเกิน = 400 จาก backend — อย่าเปลี่ยนเป็น `credit` เอง
 *  4. เครดิตล้วน (`receipt_no=null`) ไม่มีใบเสร็จใหม่ ⇒ ซ่อนปุ่มดาวน์โหลด REC
 *  5. เงินทุกช่องเป็น string 2 ตำแหน่ง (Decimal ฝั่ง backend)
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import type {
  Account,
  AllocationPreviewResponse,
  BillSelection,
  FinancePerson,
  FinanceSettings,
  IndividualAccountItem,
  PaymentEventCreate,
  PaymentEventResult,
} from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import { downloadBlob } from '@/utils/download'
import { useDialog } from '@/composables/useDialog'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppChip from '@/components/ui/AppChip.vue'
import FormSuccess from '@/components/ui/FormSuccess.vue'
import MoneyInput from '@/components/finance/MoneyInput.vue'
import BillAllocationTable from '@/components/finance/BillAllocationTable.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    studentId: number
    studentName: string
    /** ช่องทางชำระเงิน — P2.4/P2.5 ยังไม่ merge ⇒ ส่ง `null` ตอนนี้ */
    channelId?: number | null
  }>(),
  { channelId: null },
)

const emit = defineEmits<{
  close: []
  saved: [result: PaymentEventResult]
}>()

const authStore = useAuthStore()
const dialog = useDialog()

// ⚠️ `currentRoomId` เป็น null ได้ตอน hydrate — ปุ่มเปิด modal อยู่ใต้ layout ที่มีห้องแล้วเสมอ
const roomId = computed(() => Number(authStore.currentRoomId ?? 0))

const WARNING_TEXT: Record<string, string> = {
  EXCESS_TO_CREDIT: 'ส่วนเกินจะถูกเก็บเป็นเครดิต',
  PARTIAL_PAYMENT: 'ยังปิดบิลไม่ครบ',
  UNSELECTED_OPEN_BILLS: 'ยังมีบิลเปิดที่ไม่ได้เลือก',
  CREDIT_REMAINS: 'ยังเหลือเครดิต',
  CREDIT_UNUSED_BECAUSE_CASH_COVERED: 'เงินสดพอปิดบิลแล้ว — เครดิตยังอยู่ครบ',
}

// ───────────────────────────────────────────────────── state
const account = ref<IndividualAccountItem | null>(null)
const accounts = ref<Account[]>([])
const people = ref<FinancePerson[]>([])
const settings = ref<FinanceSettings | null>(null)

const amount = ref<number | null>(null)
const useCredit = ref(false)
const excessToCredit = ref(false)
const billSelection = ref<BillSelection>('auto')
const selectedBillIds = ref<number[]>([])
const walletAccountId = ref<number | null>(null)
const receiverPersonId = ref<number | null>(null)
const receiverName = ref('')
const payerName = ref('')
const note = ref('')

const preview = ref<AllocationPreviewResponse | null>(null)
const previewError = ref('')
const isLoadingInit = ref(false)
const isPreviewing = ref(false)
const isSubmitting = ref(false)
const submittedResult = ref<PaymentEventResult | null>(null)
const initError = ref('')

/**
 * 🔑 คีย์กันรับซ้ำ — สร้างเมื่อกดยืนยันครั้งแรกเท่านั้น (ไม่ใช่ตอนเปิดแผ่น:
 * ผู้ใช้อาจเปิดค้างแล้วเปลี่ยนยอด) และรีเซ็ตเฉพาะสำเร็จ/ปิดแผ่น
 */
const attemptKey = ref<string | null>(null)

let previewTimer: ReturnType<typeof setTimeout> | null = null
const initGuard = createLatestGuard()
const previewGuard = createLatestGuard()

// ───────────────────────────────────────────────────── computed
const receivePeople = computed(() =>
  people.value.filter((p) => p.is_active && p.roles.includes('receive')),
)

const creditBalance = computed(() => Number(account.value?.credit_balance ?? 0))
const openBills = computed(() => account.value?.open_bills ?? [])

const requireReceiver = computed(() => settings.value?.require_receiver ?? false)
const hasWallet = computed(() => walletAccountId.value !== null)

/** เงื่อนไขพอสำหรับเรียก preview — เงินสด > 0 หรือเครดิต > 0 (และ manual ต้องเลือกบิล) */
const canPreview = computed(() => {
  const cash = amount.value ?? 0
  if (!(cash > 0 || (useCredit.value && creditBalance.value > 0))) return false
  if (billSelection.value === 'manual' && selectedBillIds.value.length === 0) return false
  return true
})

const submitDisabled = computed(
  () =>
    isSubmitting.value ||
    !preview.value ||
    !!previewError.value ||
    !hasWallet.value ||
    (requireReceiver.value && receiverPersonId.value === null),
)

const warningTexts = computed(() =>
  (preview.value?.warnings ?? []).map((code) => WARNING_TEXT[code] ?? code),
)

const successHint = computed(() => {
  const result = submittedResult.value
  if (!result) return ''
  if (!result.receipt_no && Number(result.credit_used) > 0) {
    return 'ใช้เครดิตปิดบิล — ไม่มีเงินสด จึงไม่มีใบเสร็จใหม่'
  }
  const parts: string[] = []
  if (result.receipt_no) parts.push(`เลขที่ ${result.receipt_no}`)
  if (result.deposit_no) parts.push(`ใบรับเงินล่วงหน้า ${result.deposit_no}`)
  return parts.join(' · ')
})

const errorMessage = (error: unknown): string =>
  error instanceof Error && error.message ? error.message : 'เกิดข้อผิดพลาดจาก API'

/** ข้อความจาก backend code → ภาษาที่ผู้ใช้ต้องตัดสินใจได้ */
const friendlyPreviewError = (error: unknown): string => {
  const msg = errorMessage(error)
  if (msg.includes('EXCESS_NOT_ALLOWED')) {
    return 'ยอดรับเกินยอดที่ใช้ปิดบิล — เปิด "เก็บส่วนเกินเป็นเครดิต" หรือลดยอด'
  }
  if (msg.includes('INVALID_AMOUNT')) return 'ยอดเงินไม่ถูกต้อง'
  return msg
}

// ───────────────────────────────────────────────────── init
const resetForm = () => {
  amount.value = null
  useCredit.value = false
  excessToCredit.value = false
  billSelection.value = 'auto'
  selectedBillIds.value = []
  note.value = ''
  preview.value = null
  previewError.value = ''
  initError.value = ''
  submittedResult.value = null
  attemptKey.value = null
}

const initialize = async () => {
  const token = initGuard.begin()
  resetForm()
  isLoadingInit.value = true

  try {
    const [detail, accountList, personList, financeSettings] = await Promise.all([
      FinanceService.getIndividualAccount(roomId.value, props.studentId),
      FinanceService.getAccounts(roomId.value),
      FinanceService.getPeople(roomId.value, { active: true }),
      FinanceService.getFinanceSettings(roomId.value),
    ])
    if (!initGuard.isCurrent(token)) return

    account.value = detail
    accounts.value = accountList
    people.value = personList
    settings.value = financeSettings

    payerName.value = props.studentName
    walletAccountId.value =
      financeSettings.default_wallet_account_id ?? accountList[0]?.id ?? null

    const receivers = personList.filter(
      (p) => p.is_active && p.roles.includes('receive'),
    )
    const defaultReceiver =
      financeSettings.default_receiver_person_id !== null
        ? receivers.find((p) => p.person_id === financeSettings.default_receiver_person_id)
        : undefined
    const receiver = defaultReceiver ?? receivers[0]
    receiverPersonId.value = receiver?.person_id ?? null
    receiverName.value = receiver?.display_name ?? ''

    useCredit.value = Number(detail.credit_balance) > 0

    // 💰 เติมยอดตั้งต้นให้ผู้ใช้ไม่ต้องพิมพ์เอง — ยอดค้างที่ยังต้องเก็บ **เป็นเงินสด**
    //    = คงค้างทั้งสิ้น − เครดิตที่ตัดบิลนี้ได้อยู่แล้ว (`ready_to_apply` ฝั่ง backend
    //    = min(credit, outstanding)) เพราะระบบจะติ๊ก "ใช้เครดิต" ให้เองเมื่อมีเครดิต
    //    ⇒ ถ้าเติม `outstanding_total` ดิบ จะเกินบิลทันที (EXCESS_NOT_ALLOWED)
    const outstandingCash = roundMoney(
      Number(detail.outstanding_total) - Number(detail.ready_to_apply),
    )
    amount.value = outstandingCash > 0 ? outstandingCash : null
  } catch (error) {
    if (!initGuard.isCurrent(token)) return
    const status = apiStatus(error)
    if (status === 404) {
      await dialog.alert('ไม่พบนักเรียน', 'นักเรียนอาจถูกลบหรือไม่ได้อยู่ในห้องนี้', 'error')
      emit('close')
      return
    }
    initError.value =
      status === 403 ? 'ไม่มีสิทธิ์รับเงิน' : errorMessage(error)
  } finally {
    if (initGuard.isCurrent(token)) isLoadingInit.value = false
  }

  if (initGuard.isCurrent(token)) schedulePreview()
}

/** โหลดเฉพาะบิล/เครดิตใหม่หลัง 409 — ไม่รื้อค่าที่ผู้ใช้พิมพ์ */
const refreshAccount = async () => {
  try {
    account.value = await FinanceService.getIndividualAccount(roomId.value, props.studentId)
  } catch {
    // ปล่อยข้อมูลเดิมไว้ — preview รอบถัดไปจะแจ้ง error เองถ้ายังปิดบิลไม่ได้
  }
}

// ───────────────────────────────────────────────────── preview
const buildPreviewPayload = () => ({
  student_id: props.studentId,
  amount_received: roundMoney(amount.value ?? 0).toFixed(2),
  use_credit: useCredit.value,
  excess_action: excessToCredit.value ? ('credit' as const) : ('none' as const),
  bill_selection: billSelection.value,
  bill_ids: billSelection.value === 'manual' ? [...selectedBillIds.value] : [],
  channel_id: props.channelId ?? null,
})

const runPreview = async () => {
  if (isLoadingInit.value || !canPreview.value) return
  const token = previewGuard.begin()
  isPreviewing.value = true
  previewError.value = ''

  try {
    const res = await FinanceService.previewPaymentEvent(roomId.value, buildPreviewPayload())
    if (!previewGuard.isCurrent(token)) return
    preview.value = res
  } catch (error) {
    if (!previewGuard.isCurrent(token)) return
    preview.value = null
    const status = apiStatus(error)
    if (status === 409) {
      await dialog.alert(
        'ข้อมูลบิลเปลี่ยน',
        'บิลถูกปิดหรือมียอดเปลี่ยน — กำลังโหลดข้อมูลใหม่',
        'warning',
      )
      if (!previewGuard.isCurrent(token)) return
      await refreshAccount()
      if (previewGuard.isCurrent(token)) void runPreview()
      return
    }
    if (status === 404) {
      await dialog.alert('ไม่พบนักเรียน', 'นักเรียนอาจถูกลบหรือไม่ได้อยู่ในห้องนี้', 'error')
      emit('close')
      return
    }
    previewError.value = friendlyPreviewError(error)
  } finally {
    if (previewGuard.isCurrent(token)) isPreviewing.value = false
  }
}

const schedulePreview = () => {
  if (previewTimer) clearTimeout(previewTimer)
  preview.value = null
  previewError.value = ''
  if (isLoadingInit.value || !canPreview.value) return
  previewTimer = setTimeout(() => void runPreview(), 350)
}

watch(
  [amount, useCredit, excessToCredit, billSelection, selectedBillIds],
  schedulePreview,
  { deep: true },
)

// ผู้รับเงินจากรายการ person — ชื่อล็อกตาม person; เลือก "ไม่ระบุ" แล้วพิมพ์เองได้
watch(receiverPersonId, (id) => {
  if (id === null) return
  const person = receivePeople.value.find((p) => p.person_id === id)
  if (person) receiverName.value = person.display_name
})

// ───────────────────────────────────────────────────── submit
const submit = async () => {
  if (submitDisabled.value || isSubmitting.value) return
  const key = (attemptKey.value ??= newIdempotencyKey())
  isSubmitting.value = true

  try {
    const payload: PaymentEventCreate = {
      ...buildPreviewPayload(),
      idempotency_key: key,
      wallet_account_id: walletAccountId.value!,
      payer_name: payerName.value.trim() || null,
      payer_person_id: null,
      receiver_person_id: receiverPersonId.value,
      receiver_name: receiverName.value.trim() || null,
      note: note.value.trim() || null,
      event_at: null,
    }
    const result = await FinanceService.createPaymentEvent(roomId.value, payload)
    submittedResult.value = result
    attemptKey.value = null
    emit('saved', result)
  } catch (error) {
    const status = apiStatus(error)
    if (status === 409) {
      await dialog.alert(
        'ข้อมูลบิลเปลี่ยน',
        'บิลถูกปิดหรือมียอดเปลี่ยน — กำลังโหลดข้อมูลใหม่ กรุณาตรวจยอดก่อนยืนยันอีกครั้ง',
        'warning',
      )
      await refreshAccount()
      schedulePreview()
      return
    }
    if (status === 403) {
      await dialog.alert('ไม่มีสิทธิ์รับเงิน', 'บัญชีนี้ไม่มีสิทธิ์ MANAGE_FINANCE', 'error')
      return
    }
    if (status === 404) {
      await dialog.alert('ไม่พบนักเรียน', 'นักเรียนอาจถูกลบหรือไม่ได้อยู่ในห้องนี้', 'error')
      emit('close')
      return
    }
    const msg = errorMessage(error)
    await dialog.alert(
      'บันทึกไม่สำเร็จ',
      msg.includes('BILL_NOT_OPEN')
        ? 'บิลถูกปิดหรือมียอดเปลี่ยน — กำลังโหลดข้อมูลใหม่'
        : msg,
      'error',
    )
  } finally {
    isSubmitting.value = false
  }
}

// ───────────────────────────────────────────────────── close / download
const closeSheet = () => {
  // 🧹 ทิ้งความพยายามที่ยังไม่สำเร็จ: เปิดใหม่ต้องเป็น "การกดครั้งใหม่"
  attemptKey.value = null
  emit('close')
}

const downloadDoc = async (receiptNo: string) => {
  try {
    const blob = await FinanceService.downloadReceiptPdf(roomId.value, receiptNo)
    downloadBlob(blob, `${receiptNo}.pdf`)
  } catch (error) {
    await dialog.alert('ดาวน์โหลดไม่สำเร็จ', errorMessage(error), 'error')
  }
}

// ─────── เปิดแผ่น (หรือเปลี่ยนนักเรียน) ⇒ รีเซ็ตแล้วโหลดใหม่; ปิดแผ่น ⇒ ทิ้งคีย์
watch(
  () => [props.open, props.studentId] as const,
  ([open]) => {
    if (!open) {
      attemptKey.value = null
      return
    }
    void initialize()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer)
})
</script>

<template>
  <AppSheet
    :open="open"
    label="รับเงิน"
    :title="submittedResult ? 'ผลการรับเงิน' : `รับเงิน — ${studentName}`"
    :description="
      submittedResult ? undefined : 'หนึ่งครั้งที่ยืนยัน = 1 รายการรับเงิน + ใบเสร็จ 1 ใบ'
    "
    size="form"
    :dismissible="!isSubmitting"
    @close="isSubmitting ? undefined : closeSheet()"
  >
    <!-- ═══════════════════════ ผลสำเร็จ ═══════════════════════ -->
    <FormSuccess
      v-if="submittedResult"
      title="บันทึกรับเงินแล้ว"
      :hint="successHint"
    >
      <AppButton
        v-if="submittedResult.receipt_no"
        variant="primary"
        @click="downloadDoc(submittedResult.receipt_no)"
      >
        <i class="bi bi-download" aria-hidden="true"></i>
        ดาวน์โหลดใบเสร็จ
      </AppButton>
      <AppButton
        v-if="submittedResult.deposit_no"
        variant="secondary"
        @click="downloadDoc(submittedResult.deposit_no)"
      >
        <i class="bi bi-download" aria-hidden="true"></i>
        ดาวน์โหลด DEP
      </AppButton>
      <AppButton variant="secondary" @click="closeSheet">เสร็จสิ้น</AppButton>

      <dl class="mt-4 grid w-full grid-cols-1 gap-1 text-left text-sm sm:grid-cols-3">
        <div>
          <dt class="text-caption text-ink-3">ปิดบิล</dt>
          <dd class="num font-bold text-ink-1">
            {{ formatMoney(Number(submittedResult.total_applied)) }}
          </dd>
        </div>
        <div>
          <dt class="text-caption text-ink-3">ใช้เครดิต</dt>
          <dd class="num font-bold text-ink-1">
            {{ formatMoney(Number(submittedResult.credit_used)) }}
          </dd>
        </div>
        <div>
          <dt class="text-caption text-ink-3">เก็บเป็นเครดิต</dt>
          <dd class="num font-bold text-ink-1">
            {{ formatMoney(Number(submittedResult.credit_added)) }}
          </dd>
        </div>
      </dl>
    </FormSuccess>

    <!-- ═══════════════════════ ฟอร์ม ═══════════════════════ -->
    <div v-else class="space-y-4">
      <div v-if="isLoadingInit" class="space-y-2">
        <div class="h-24 animate-pulse rounded-control bg-canvas"></div>
        <div class="h-10 animate-pulse rounded-control bg-canvas"></div>
      </div>

      <p
        v-else-if="initError"
        class="rounded-control border border-danger-200 bg-danger-50 px-3 py-2 text-sm text-danger-700"
      >
        {{ initError }}
      </p>

      <template v-else>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <MoneyInput
            v-model="amount"
            label="เงินสดที่รับ"
            :hint="`เครดิตคงเหลือ ${formatMoney(creditBalance)}`"
            autofocus
          />

          <div class="space-y-2">
            <label class="field-label" for="receive-wallet">กระเป๋าที่รับเงิน</label>
            <select id="receive-wallet" v-model="walletAccountId" class="field">
              <option :value="null" disabled>— เลือกกระเป๋า —</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
                {{ acc.account_name }}
              </option>
            </select>
            <p v-if="!hasWallet" class="text-caption text-danger-700">
              ยังไม่มีกระเป๋าเงิน — สร้างกระเป๋าก่อนรับเงิน
            </p>
          </div>
        </div>

        <div class="space-y-2 rounded-control border border-line p-3">
          <label class="flex items-start gap-2 text-sm">
            <input
              v-model="useCredit"
              type="checkbox"
              class="mt-0.5 h-5 w-5 accent-brand"
              :disabled="creditBalance <= 0"
            />
            <span>
              ใช้เครดิตคงเหลือปิดบิล
              <span class="num text-ink-3">({{ formatMoney(creditBalance) }})</span>
            </span>
          </label>
          <label class="flex items-start gap-2 text-sm">
            <input v-model="excessToCredit" type="checkbox" class="mt-0.5 h-5 w-5 accent-brand" />
            <span>เงินเกิน: เก็บเป็นเครดิต (ไม่ติ๊ก = ปฏิเสธยอดเกิน)</span>
          </label>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="field-label" for="receive-bill-selection">บิลที่จะปิด</label>
            <select id="receive-bill-selection" v-model="billSelection" class="field">
              <option value="auto">ทุกบิลที่ค้าง (ตามลำดับกำหนดชำระ)</option>
              <option value="manual">เลือกบิลเอง</option>
            </select>
          </div>

          <div>
            <label class="field-label" for="receive-receiver">ผู้รับเงิน</label>
            <select
              id="receive-receiver"
              :value="receiverPersonId ?? ''"
              class="field"
              @change="
                receiverPersonId = ($event.target as HTMLSelectElement).value
                  ? Number(($event.target as HTMLSelectElement).value)
                  : null
              "
            >
              <option value="">— พิมพ์ชื่อเอง —</option>
              <option v-for="p in receivePeople" :key="p.person_id" :value="p.person_id">
                {{ p.display_name }}
              </option>
            </select>
            <input
              v-if="receiverPersonId === null"
              v-model="receiverName"
              class="field mt-2"
              placeholder="ชื่อผู้รับเงิน"
              aria-label="ชื่อผู้รับเงิน"
            />
            <p v-if="requireReceiver && receiverPersonId === null" class="mt-1 text-caption text-danger-700">
              ห้องนี้กำหนดให้ต้องเลือกผู้รับเงินจากทะเบียน
            </p>
          </div>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="field-label" for="receive-payer">ผู้ชำระเงิน</label>
            <input id="receive-payer" v-model="payerName" class="field" />
          </div>
          <div>
            <label class="field-label" for="receive-note">หมายเหตุ</label>
            <input id="receive-note" v-model="note" class="field" placeholder="ไม่บังคับ" />
          </div>
        </div>

        <!-- 📋 ผลพรีวิว -->
        <div v-if="previewError">
          <p class="rounded-control border border-danger-200 bg-danger-50 px-3 py-2 text-sm text-danger-700">
            {{ previewError }}
          </p>
        </div>

        <div v-else-if="isPreviewing && !preview" class="text-sm text-ink-3">
          <i class="bi bi-hourglass-split me-1" aria-hidden="true"></i>
          กำลังคำนวณการจัดสรร…
        </div>

        <template v-else-if="preview">
          <BillAllocationTable
            v-model="selectedBillIds"
            :bills="openBills"
            :allocations="preview.allocations"
            :selection="billSelection"
            :disabled="isSubmitting"
            :totals="preview"
          />

          <div v-if="warningTexts.length" class="flex flex-wrap gap-1.5">
            <AppChip v-for="text in warningTexts" :key="text" tone="warn" icon="bi-info-circle">
              {{ text }}
            </AppChip>
          </div>

          <p class="text-caption text-ink-3">
            ยังไม่จัดสรร
            <span class="num">{{ formatMoney(Number(preview.remaining_unapplied)) }}</span>
            · ใช้เครดิต
            <span class="num">{{ formatMoney(Number(preview.credit_used)) }}</span>
          </p>
        </template>
      </template>
    </div>

    <template v-if="!submittedResult" #footer>
      <div class="flex gap-2">
        <AppButton variant="secondary" block :disabled="isSubmitting" @click="closeSheet">
          ยกเลิก
        </AppButton>
        <AppButton
          variant="primary"
          block
          :loading="isSubmitting"
          :disabled="submitDisabled"
          @click="submit"
        >
          ยืนยันรับเงิน
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
