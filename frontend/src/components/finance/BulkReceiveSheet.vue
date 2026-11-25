<script setup lang="ts">
/**
 * 📥 BulkReceiveSheet — รับเงินหลายคนในรอบเดียว (FIN-V2 / P2.7)
 *
 * 🎯 1 ครั้งที่กดยืนยัน = 1 คำขอ = 1 transaction = **all-or-nothing**
 *    ⇒ 1 นักเรียน = 1 event + REC/DEP ของตัวเอง · แจ้ง Discord ครั้งเดียว
 * 🔒 ใช้ **preview จาก engine ตัวเดียวกับ commit** (P1.5/P2.1) ตรวจยอดรวมก่อนยืนยัน
 * ⚠️ ไม่เรียกเส้น legacy "รับหลายบิลของคนเดียว" (`confirmBatch*` ใน `DebtorList.vue`) —
 *    ชีตนี้คือเส้นใหม่ v2 และของเดิมยังต้องใช้งานได้จนถึง P6.5 ⇒ ห้ามลบ/แก้ของเดิม
 *
 * 🔴 กฎที่ห้ามพลาด
 *  1. `idempotency_key` ของทั้งรอบสร้าง **ครั้งแรกที่กดยืนยัน** และคงเดิมตอน retry
 *     (redeploy key ใหม่ = รอบใหม่ ⇒ เงินซ้ำจากเงินชุดเดียว)
 *  2. `reference_no` คงที่ตลอดรอบ — backend ใช้ตรวจ replay คู่กับคีย์
 *  3. preview เป็น snapshot ไม่ใช่สัญญา: มีคนปิดบิลระหว่างนี้ได้ ⇒ commit 409
 *     และ **ไม่มีใครถูกบันทึก** ⇒ reload รายชื่อ/ล้าง preview แต่คงยอดที่พิมพ์ไว้
 *  4. คนที่เครดิตครอบเต็มได้ `amount=0` + `use_credit=true` ⇒ มี event แต่ไม่มี REC
 *  5. เงินทุกช่องส่ง backend เป็น string 2 ตำแหน่ง (`roundMoney(...).toFixed(2)`)
 *  6. รอบนี้ **ไม่เลือกช่องทางชำระ** (P2.7 ไม่มี P2.4 dependency) ⇒ `channel_id: null`
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import type {
  Account,
  AllocationPreviewResponse,
  BulkPaymentErrorDetail,
  BulkPaymentEventResult,
  Debtor,
  FinancePerson,
  FinanceSettings,
} from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import { downloadBlob, combinedPdfFilename } from '@/utils/download'
import { useDialog } from '@/composables/useDialog'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import FormSuccess from '@/components/ui/FormSuccess.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    /** นักเรียนที่ติ๊กไว้ที่หน้า list — ว่าง = ทุกคนที่มียอดค้าง */
    studentIds?: number[]
  }>(),
  { studentIds: () => [] },
)

const emit = defineEmits<{
  close: []
  saved: [result: BulkPaymentEventResult]
}>()

const authStore = useAuthStore()
const dialog = useDialog()

const roomId = computed(() => Number(authStore.currentRoomId ?? 0))
const canWrite = computed(() => authStore.canManageFinance)

/** 🚧 เพดานเดียวกับ backend (`BulkPaymentEventCreate.items` และ PDF รวม) */
const MAX_ITEMS = 100

// ───────────────────────────────────────────────────── state
const debtors = ref<Debtor[]>([])
const accounts = ref<Account[]>([])
const people = ref<FinancePerson[]>([])
const settings = ref<FinanceSettings | null>(null)

const selectedIds = ref<number[]>([])
const amounts = ref<Record<number, number | null>>({})
const useCredit = ref(false)
const excessToCredit = ref(false)

const previews = ref<Record<number, AllocationPreviewResponse>>({})
const previewErrors = ref<Record<number, string>>({})

const referenceNo = ref('')
const walletAccountId = ref<number | null>(null)
const receiverPersonId = ref<number | null>(null)
const receiverName = ref('')
const note = ref('')

const isLoading = ref(false)
const isPreviewing = ref(false)
const isSubmitting = ref(false)
const initError = ref('')
const failedStudentId = ref<number | null>(null)
const submittedResult = ref<BulkPaymentEventResult | null>(null)

/** 🔑 คีย์ของทั้งรอบ — สร้างเมื่อกดยืนยันครั้งแรกเท่านั้น (retry ต้องใช้ตัวเดิม) */
const attemptKey = ref<string | null>(null)

const initGuard = createLatestGuard()
const previewGuard = createLatestGuard()

// ───────────────────────────────────────────────────── computed
const receivePeople = computed(() =>
  people.value.filter((p) => p.is_active && p.roles.includes('receive')),
)

const requireReceiver = computed(() => settings.value?.require_receiver ?? false)

const selectedDebtors = computed(() =>
  debtors.value.filter((d) => selectedIds.value.includes(d.student_id)),
)

const rowAmount = (d: Debtor): number => amounts.value[d.student_id] ?? 0

/** แถวที่จะส่งจริง — เงินสด > 0 หรือ (ใช้เครดิต และมีเครดิตเหลือ) */
const payloadRows = computed(() =>
  selectedDebtors.value.filter(
    (d) => rowAmount(d) > 0 || (useCredit.value && Number(d.credit_balance) > 0),
  ),
)

const totalCash = computed(() =>
  payloadRows.value.reduce((sum, d) => sum + roundMoney(rowAmount(d)), 0),
)

const hasPreviewErrors = computed(() => Object.keys(previewErrors.value).length > 0)

const allPreviewed = computed(
  () =>
    payloadRows.value.length > 0 &&
    payloadRows.value.every((d) => !!previews.value[d.student_id]),
)

const previewTotals = computed(() => {
  let applied = 0
  let credit = 0
  let added = 0
  for (const d of payloadRows.value) {
    const p = previews.value[d.student_id]
    if (!p) continue
    applied += Number(p.total_applied)
    credit += Number(p.credit_used)
    added += Number(p.credit_added)
  }
  return { applied, credit, added }
})

const submitDisabled = computed(
  () =>
    !canWrite.value ||
    isSubmitting.value ||
    !allPreviewed.value ||
    hasPreviewErrors.value ||
    payloadRows.value.length === 0 ||
    walletAccountId.value === null ||
    (requireReceiver.value && receiverPersonId.value === null),
)

const receiptNos = computed(
  () =>
    (submittedResult.value?.events ?? [])
      .map((e) => e.event.receipt_no)
      .filter((no): no is string => !!no),
)

const successHint = computed(() => {
  const result = submittedResult.value
  if (!result) return ''
  if (result.reused) return 'รายการนี้เคยบันทึกแล้ว (กดซ้ำ) — ไม่มีเอกสารใหม่'
  return `ยอดเงินสดรวม ${formatMoney(Number(result.total_amount_received))} บาท`
})

// ───────────────────────────────────────────────────── helpers
const errorMessage = (error: unknown): string =>
  error instanceof Error && error.message ? error.message : 'เกิดข้อผิดพลาดจาก API'

/** detail ที่ backend ส่งเป็น object (`BulkPaymentFailure` มี student_id) */
const failureDetail = (error: unknown): BulkPaymentErrorDetail | null => {
  const raw = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return raw as BulkPaymentErrorDetail
  }
  return null
}

const friendlyPreviewError = (error: unknown): string => {
  const msg = errorMessage(error)
  if (msg.includes('EXCESS_NOT_ALLOWED')) {
    return 'ยอดเกินยอดที่ใช้ปิดบิล — ลดยอดหรือเปิด "เก็บส่วนเกินเป็นเครดิต"'
  }
  if (msg.includes('INVALID_AMOUNT')) return 'ยอดเงินไม่ถูกต้อง'
  return msg
}

const makeReferenceNo = (): string => {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `BULK-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  )
}

const jaiFullValue = (d: Debtor): number =>
  useCredit.value
    ? Math.max(Number(d.net_pending_amount), 0)
    : Number(d.total_pending_amount)

const applyJaiFull = (d: Debtor) => {
  amounts.value = { ...amounts.value, [d.student_id]: jaiFullValue(d) }
}

const onAmountInput = (d: Debtor, event: Event) => {
  const raw = (event.target as HTMLInputElement).value.replace(/[,\s]/g, '')
  const num = raw === '' ? null : Number(raw)
  amounts.value = {
    ...amounts.value,
    [d.student_id]: num !== null && Number.isFinite(num) ? num : null,
  }
}

const amountText = (d: Debtor): string => {
  const value = amounts.value[d.student_id]
  return value === null || value === undefined ? '' : String(value)
}

const rowStatus = (d: Debtor): 'ok' | 'error' | 'pending' | 'skipped' => {
  if (previewErrors.value[d.student_id]) return 'error'
  if (previews.value[d.student_id]) return 'ok'
  return payloadRows.value.some((r) => r.student_id === d.student_id)
    ? 'pending'
    : 'skipped'
}

// ───────────────────────────────────────────────────── reset / init
const resetState = () => {
  debtors.value = []
  accounts.value = []
  people.value = []
  settings.value = null
  selectedIds.value = []
  amounts.value = {}
  useCredit.value = false
  excessToCredit.value = false
  previews.value = {}
  previewErrors.value = {}
  referenceNo.value = ''
  walletAccountId.value = null
  receiverPersonId.value = null
  receiverName.value = ''
  note.value = ''
  initError.value = ''
  failedStudentId.value = null
  submittedResult.value = null
  attemptKey.value = null
}

const initialize = async () => {
  const token = initGuard.begin()
  resetState()
  isLoading.value = true

  try {
    const [list, accountList, personList, financeSettings] = await Promise.all([
      FinanceService.getAllDebtors(roomId.value),
      FinanceService.getAccounts(roomId.value),
      FinanceService.getPeople(roomId.value, { active: true }),
      FinanceService.getFinanceSettings(roomId.value),
    ])
    if (!initGuard.isCurrent(token)) return

    debtors.value = list
    accounts.value = accountList
    people.value = personList
    settings.value = financeSettings

    walletAccountId.value =
      financeSettings.default_wallet_account_id ?? accountList[0]?.id ?? null

    const receivers = personList.filter(
      (p) => p.is_active && p.roles.includes('receive'),
    )
    const defaultReceiver =
      financeSettings.default_receiver_person_id !== null
        ? receivers.find(
            (p) => p.person_id === financeSettings.default_receiver_person_id,
          )
        : undefined
    const receiver = defaultReceiver ?? receivers[0]
    receiverPersonId.value = receiver?.person_id ?? null
    receiverName.value = receiver?.display_name ?? ''

    // 🎯 ติ๊กเฉพาะคนที่มียอดค้าง — ถ้าหน้ารายชื่อส่งชุดมา ให้ใช้ชุดนั้นตัดกัน
    const eligible = list.filter((d) => Number(d.total_pending_amount) > 0)
    const wanted =
      props.studentIds.length > 0 ? new Set(props.studentIds) : null
    selectedIds.value = eligible
      .filter((d) => !wanted || wanted.has(d.student_id))
      .map((d) => d.student_id)

    const nextAmounts: Record<number, number | null> = {}
    for (const d of eligible) nextAmounts[d.student_id] = jaiFullValue(d)
    amounts.value = nextAmounts

    referenceNo.value = makeReferenceNo()
    attemptKey.value = null
  } catch (error) {
    if (!initGuard.isCurrent(token)) return
    initError.value =
      apiStatus(error) === 403 ? 'ไม่มีสิทธิ์รับเงิน' : errorMessage(error)
  } finally {
    if (initGuard.isCurrent(token)) isLoading.value = false
  }
}

/** โหลดยอดค้างใหม่หลัง 409 — คงยอดที่ผู้ใช้พิมพ์ไว้ (ไม่รีเซ็ต amounts) */
const reloadDebtors = async () => {
  try {
    const list = await FinanceService.getAllDebtors(roomId.value)
    debtors.value = list
    const alive = new Set(list.map((d) => d.student_id))
    selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
  } catch {
    // เก็บรายการเดิมไว้ — preview รอบถัดไปจะบอกเองถ้ายังปิดบิลไม่ได้
  }
}

// ───────────────────────────────────────────────────── preview
const invalidatePreviews = () => {
  previews.value = {}
  previewErrors.value = {}
}

const buildPreviewPayload = (d: Debtor) => ({
  student_id: d.student_id,
  amount_received: roundMoney(rowAmount(d)).toFixed(2),
  use_credit: useCredit.value,
  excess_action: excessToCredit.value ? ('credit' as const) : ('none' as const),
  bill_selection: 'auto' as const,
  bill_ids: [] as number[],
  channel_id: null,
})

const runPreview = async () => {
  const rows = payloadRows.value
  if (!rows.length || isPreviewing.value) return
  const token = previewGuard.begin()
  isPreviewing.value = true
  previewErrors.value = {}

  const settled = await Promise.allSettled(
    rows.map((d) =>
      FinanceService.previewPaymentEvent(roomId.value, buildPreviewPayload(d)),
    ),
  )
  if (!previewGuard.isCurrent(token)) return

  const nextPreviews: Record<number, AllocationPreviewResponse> = {}
  const nextErrors: Record<number, string> = {}
  settled.forEach((outcome, index) => {
    const row = rows[index]
    if (!row) return
    if (outcome.status === 'fulfilled') {
      nextPreviews[row.student_id] = outcome.value
    } else {
      nextErrors[row.student_id] = friendlyPreviewError(outcome.reason)
    }
  })

  previews.value = nextPreviews
  previewErrors.value = nextErrors
  isPreviewing.value = false
}

// การแก้ยอด/ติ๊ก/ตัวเลือก ทำให้ preview เดิมหมดสิทธิ์ (ต้องตรวจใหม่ก่อนยืนยัน)
watch([amounts, selectedIds, useCredit, excessToCredit], invalidatePreviews, {
  deep: true,
})

watch(receiverPersonId, (id) => {
  if (id === null) return
  const person = receivePeople.value.find((p) => p.person_id === id)
  if (person) receiverName.value = person.display_name
})

// ───────────────────────────────────────────────────── submit
const submit = async () => {
  if (submitDisabled.value || isSubmitting.value) return

  const rows = payloadRows.value
  const confirmed = await dialog.confirm(
    'ยืนยันรับเงิน',
    `รับเงิน ${rows.length} คน รวม ${formatMoney(totalCash.value)} บาท — ` +
      'ทั้งรอบจะสำเร็จหรือล้มทั้งหมด (ถ้ามีคนใดผิด ไม่มีใครถูกบันทึก)',
  )
  if (!confirmed.isConfirmed) return

  const key = (attemptKey.value ??= newIdempotencyKey())
  isSubmitting.value = true
  failedStudentId.value = null

  try {
    const result = await FinanceService.createBulkPaymentEvent(roomId.value, {
      idempotency_key: key,
      reference_no: referenceNo.value.trim(),
      channel_id: null,
      wallet_account_id: walletAccountId.value!,
      receiver_person_id: receiverPersonId.value,
      receiver_name: receiverName.value.trim(),
      note: note.value.trim() || null,
      event_at: null,
      items: rows.map((d) => ({
        student_id: d.student_id,
        amount_received: roundMoney(rowAmount(d)).toFixed(2),
        use_credit: useCredit.value,
        excess_action: excessToCredit.value ? ('credit' as const) : ('none' as const),
        note: null,
      })),
    })
    submittedResult.value = result
    attemptKey.value = null
    emit('saved', result)
  } catch (error) {
    // 🔴 error ระดับ item (มี student_id) — ไฮไลต์แถวนั้นและบอกว่าไม่มีใครถูกบันทึก
    const detail = failureDetail(error)
    if (detail && detail.message) {
      failedStudentId.value = detail.student_id ?? null
      const name =
        debtors.value.find((d) => d.student_id === detail.student_id)?.student_name ??
        `นักเรียน #${detail.student_id}`
      await dialog.alert(
        'บันทึกไม่สำเร็จ',
        `${name}: ${detail.message} — ทั้งรอบไม่ถูกบันทึก (${detail.item_code})`,
        'error',
      )
      await reloadDebtors()
      invalidatePreviews()
      return
    }

    // ⚠️ คง amounts + attemptKey ไว้ ⇒ กดซ้ำได้อย่างปลอดภัยด้วยคีย์เดิม
    const status = apiStatus(error)
    const msg = errorMessage(error)
    await dialog.alert(
      'บันทึกไม่สำเร็จ',
      msg.includes('BILL_NOT_OPEN')
        ? 'บิลถูกปิดหรือมียอดเปลี่ยน — กำลังโหลดข้อมูลใหม่ กรุณาตรวจยอดอีกครั้ง'
        : msg,
      'error',
    )
    if (status === 400 || status === 409) {
      await reloadDebtors()
      invalidatePreviews()
    }
  } finally {
    isSubmitting.value = false
  }
}

// ───────────────────────────────────────────────────── close / download
const closeSheet = () => {
  attemptKey.value = null
  emit('close')
}

const downloadReceipt = async (receiptNo: string) => {
  try {
    const blob = await FinanceService.downloadReceiptPdf(roomId.value, receiptNo)
    downloadBlob(blob, `${receiptNo}.pdf`)
  } catch (error) {
    await dialog.alert('ดาวน์โหลดไม่สำเร็จ', errorMessage(error), 'error')
  }
}

const downloadCombined = async () => {
  const nos = receiptNos.value
  if (!nos.length) return
  if (nos.length > MAX_ITEMS) {
    await dialog.alert(
      'ใบเสร็จมากเกินไป',
      `ดาวน์โหลดรวมได้ครั้งละไม่เกิน ${MAX_ITEMS} ใบ — ใช้หน้าทะเบียนเอกสารแบ่งรอบ`,
      'info',
    )
    return
  }
  try {
    const blob = await FinanceService.downloadCombinedPdf(roomId.value, nos)
    downloadBlob(blob, combinedPdfFilename(nos))
  } catch (error) {
    await dialog.alert('ดาวน์โหลดไม่สำเร็จ', errorMessage(error), 'error')
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      void initialize()
    } else {
      attemptKey.value = null
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  initGuard.begin()
  previewGuard.begin()
})
</script>

<template>
  <AppSheet
    :open="open"
    label="รับเงินหลายคน"
    :title="submittedResult ? 'ผลการรับเงิน' : 'รับเงินหลายคน'"
    :description="
      submittedResult
        ? undefined
        : '1 รอบ = ทั้งหมดหรือไม่บันทึกเลย · 1 นักเรียน = 1 รายการรับเงิน + ใบเสร็จ'
    "
    size="full"
    :dismissible="!isSubmitting"
    @close="isSubmitting ? undefined : closeSheet()"
  >
    <!-- ═══════════════════════ ผลสำเร็จ ═══════════════════════ -->
    <FormSuccess
      v-if="submittedResult"
      :title="`บันทึกรับเงิน ${submittedResult.events.length} คนแล้ว`"
      :hint="successHint"
    >
      <AppButton
        v-if="receiptNos.length > 0"
        variant="primary"
        @click="downloadCombined"
      >
        <i class="bi bi-download" aria-hidden="true"></i>
        ดาวน์โหลด REC ทั้งหมด
      </AppButton>
      <AppButton variant="secondary" @click="closeSheet">เสร็จสิ้น</AppButton>

      <div class="mt-4 w-full space-y-2 text-left">
        <div
          v-for="row in submittedResult.events"
          :key="row.student_id"
          class="flex items-center justify-between gap-3 rounded-control border border-line px-3 py-2 text-sm"
        >
          <div class="min-w-0">
            <div class="truncate font-medium text-ink-1">{{ row.student_name }}</div>
            <div class="text-caption text-ink-3">
              <span v-if="row.event.receipt_no">REC {{ row.event.receipt_no }}</span>
              <span v-else>ใช้เครดิตปิดบิล — ไม่มีใบเสร็จใหม่</span>
              <span v-if="row.event.deposit_no"> · DEP {{ row.event.deposit_no }}</span>
            </div>
          </div>
          <AppButton
            v-if="row.event.receipt_no"
            variant="secondary"
            @click="downloadReceipt(row.event.receipt_no)"
          >
            ดูใบเสร็จ
          </AppButton>
        </div>
      </div>
    </FormSuccess>

    <!-- ═══════════════════════ ฟอร์ม ═══════════════════════ -->
    <div v-else class="space-y-4">
      <div v-if="isLoading" class="space-y-2">
        <div class="h-10 animate-pulse rounded-control bg-canvas"></div>
        <div class="h-40 animate-pulse rounded-control bg-canvas"></div>
      </div>

      <p
        v-else-if="initError"
        class="rounded-control border border-danger-200 bg-danger-50 px-3 py-2 text-sm text-danger-700"
      >
        {{ initError }}
      </p>

      <p
        v-else-if="!canWrite"
        class="rounded-control border border-line px-3 py-2 text-sm text-ink-3"
      >
        บัญชีนี้ไม่มีสิทธิ์รับเงิน (ต้องมีสิทธิ์ MANAGE_FINANCE)
      </p>

      <template v-else>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <label class="field-label" for="bulk-reference">เลขที่รับเงิน</label>
            <input
              id="bulk-reference"
              v-model="referenceNo"
              class="field"
              maxlength="64"
              :disabled="isSubmitting || attemptKey !== null"
            />
            <!-- 🔒 หลังกดยืนยันครั้งแรกแล้ว ห้ามแก้เลขนี้จนจบรอบ:
                 all-or-nothing ผูกกับ (คีย์ของรอบ + เลขนี้) ⇒ แก้แล้วกดซ้ำ
                 backend จะตอบ 409 REFERENCE_NO_CONFLICT แทนที่จะคืนผลเดิม -->
            <p v-if="attemptKey !== null" class="mt-1 text-caption text-ink-3">
              ล็อกเลขนี้แล้วเพื่อกันบันทึกซ้ำ — กดยืนยันซ้ำได้อย่างปลอดภัย
            </p>
          </div>

          <div>
            <label class="field-label" for="bulk-wallet">กระเป๋าที่รับเงิน</label>
            <select
              id="bulk-wallet"
              v-model="walletAccountId"
              class="field"
              :disabled="isSubmitting"
            >
              <option :value="null" disabled>— เลือกกระเป๋า —</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
                {{ acc.account_name }}
              </option>
            </select>
            <p v-if="walletAccountId === null" class="text-caption text-danger-700">
              ยังไม่มีกระเป๋าเงิน — สร้างกระเป๋าก่อนรับเงิน
            </p>
          </div>

          <div>
            <label class="field-label" for="bulk-receiver">ผู้รับเงิน</label>
            <select
              id="bulk-receiver"
              :value="receiverPersonId ?? ''"
              class="field"
              :disabled="isSubmitting"
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
              :disabled="isSubmitting"
            />
            <p
              v-if="requireReceiver && receiverPersonId === null"
              class="mt-1 text-caption text-danger-700"
            >
              ห้องนี้กำหนดให้ต้องเลือกผู้รับเงินจากทะเบียน
            </p>
          </div>
        </div>

        <div class="grid grid-cols-1 gap-3 rounded-control border border-line p-3 sm:grid-cols-2">
          <label class="flex items-start gap-2 text-sm">
            <input
              v-model="useCredit"
              type="checkbox"
              class="mt-0.5 h-5 w-5 accent-brand-700"
              aria-label="ใช้เครดิตคงเหลือปิดบิล"
              :disabled="isSubmitting"
            />
            <span>ใช้เครดิตคงเหลือปิดบิล (หักเครดิตก่อนเก็บเงินสด)</span>
          </label>
          <label class="flex items-start gap-2 text-sm">
            <input
              v-model="excessToCredit"
              type="checkbox"
              class="mt-0.5 h-5 w-5 accent-brand-700"
              aria-label="เงินเกินเก็บเป็นเครดิต"
              :disabled="isSubmitting"
            />
            <span>เงินเกิน: เก็บเป็นเครดิต (ไม่ติ๊ก = ปฏิเสธยอดเกิน)</span>
          </label>
          <div class="sm:col-span-2">
            <label class="field-label" for="bulk-note">หมายเหตุ</label>
            <input
              id="bulk-note"
              v-model="note"
              class="field"
              placeholder="ไม่บังคับ"
              :disabled="isSubmitting"
            />
          </div>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-caption text-ink-3">
            เลือก <span class="num">{{ payloadRows.length }}</span> คน · เงินสดรวม
            <span class="num">{{ formatMoney(totalCash) }}</span>
            <template v-if="allPreviewed">
              · ปิดบิล <span class="num">{{ formatMoney(previewTotals.applied) }}</span>
              · ใช้เครดิต <span class="num">{{ formatMoney(previewTotals.credit) }}</span>
              <template v-if="previewTotals.added > 0">
                · เก็บเป็นเครดิต
                <span class="num">{{ formatMoney(previewTotals.added) }}</span>
              </template>
            </template>
          </p>
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isPreviewing || payloadRows.length === 0"
            @click="runPreview"
          >
            <i class="bi bi-calculator" aria-hidden="true"></i>
            {{ isPreviewing ? 'กำลังตรวจสอบ…' : 'ตรวจสอบยอดทั้งหมด' }}
          </button>
        </div>

        <p
          v-if="hasPreviewErrors"
          class="rounded-control border border-danger-200 bg-danger-50 px-3 py-2 text-sm text-danger-700"
        >
          มีรายการที่ตรวจสอบไม่ผ่าน — แก้ยอดหรือปิดบิลค้างให้เรียบร้อยก่อนยืนยัน
        </p>

        <div class="overflow-x-auto rounded-control border border-line">
          <table class="w-full min-w-[720px] text-sm">
            <thead class="bg-canvas text-left text-caption text-ink-3">
              <tr>
                <th class="w-10 px-3 py-2"></th>
                <th class="px-3 py-2">นักเรียน</th>
                <th class="px-3 py-2 text-right">ยอดค้าง</th>
                <th class="px-3 py-2 text-right">เครดิต</th>
                <th class="px-3 py-2">ยอดที่ต้องเก็บ</th>
                <th class="px-3 py-2">ตรวจสอบ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="d in debtors"
                :key="d.student_id"
                class="border-t border-line"
                :class="failedStudentId === d.student_id ? 'bg-danger-50' : ''"
              >
                <td class="px-3 py-2">
                  <input
                    v-model="selectedIds"
                    type="checkbox"
                    class="h-5 w-5 accent-brand-700"
                    :value="d.student_id"
                    :aria-label="`เลือก ${d.student_name}`"
                    :disabled="isSubmitting"
                  />
                </td>
                <td class="px-3 py-2">
                  <div class="font-medium text-ink-1">{{ d.student_name }}</div>
                  <div class="text-caption text-ink-3">เลขที่ {{ d.student_no }}</div>
                </td>
                <td class="num px-3 py-2 text-right">
                  {{ formatMoney(Number(d.total_pending_amount)) }}
                </td>
                <td class="num px-3 py-2 text-right">
                  {{ formatMoney(Number(d.credit_balance)) }}
                </td>
                <td class="px-3 py-2">
                  <div class="flex items-center gap-2">
                    <input
                      class="field w-32 text-right"
                      type="text"
                      inputmode="decimal"
                      :value="amountText(d)"
                      :aria-label="`ยอดที่ต้องเก็บของ ${d.student_name}`"
                      :disabled="isSubmitting || !selectedIds.includes(d.student_id)"
                      @input="onAmountInput(d, $event)"
                    />
                    <button
                      type="button"
                      class="text-caption text-brand underline-offset-2 hover:underline"
                      :disabled="isSubmitting || !selectedIds.includes(d.student_id)"
                      @click="applyJaiFull(d)"
                    >
                      จ่ายครบ
                    </button>
                  </div>
                </td>
                <td class="px-3 py-2">
                  <span
                    v-if="rowStatus(d) === 'ok'"
                    class="text-ok-600"
                    title="ตรวจสอบผ่าน"
                  >
                    <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
                  </span>
                  <span
                    v-else-if="rowStatus(d) === 'error'"
                    class="text-caption text-danger-700"
                  >
                    {{ previewErrors[d.student_id] }}
                  </span>
                  <span v-else-if="rowStatus(d) === 'pending'" class="text-caption text-ink-3">
                    ยังไม่ตรวจ
                  </span>
                  <span v-else class="text-caption text-ink-3">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="debtors.length === 0" class="text-sm text-ink-3">
          ไม่มีนักเรียนที่ค้างชำระในห้องนี้
        </p>
      </template>
    </div>

    <template v-if="!submittedResult" #footer>
      <div class="flex gap-2">
        <AppButton variant="secondary" block :disabled="isSubmitting" @click="closeSheet">
          ยกเลิก
        </AppButton>
        <!-- 🔒 ไม่มี MANAGE_FINANCE ⇒ ไม่เรนเดอร์ปุ่มเขียนเลย (ไม่ใช่แค่ disable) -->
        <AppButton
          v-if="canWrite"
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
