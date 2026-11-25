<script setup lang="ts">
/**
 * ✂️ WriteOffModal — ตัดหนี้ / ให้ส่วนลด "บิลโครงการ" (FIN-V2 / P6.3)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ชนิดรายการ (segmented)
 * ═══════════════════════════════════════════════════════════════════════════
 *  • `write_off` = ตัดเป็นหนี้สูญ — ไม่ได้รับเงินแล้ว (Dr 59002 / Cr ลูกหนี้)
 *  • `discount`  = ให้ส่วนลด — ลดยอดที่ต้องเก็บ (Dr 49002 / Cr ลูกหนี้)
 * ทั้งสองชนิดไม่แตะ `paid_amount` และไม่แตะ `fee_collections.amount` —
 * ยอดที่ถูกตัดสะสมอยู่ที่ `student_payments.written_off_amount` (P6.2)
 * ⇒ ยอดคงเหลือของหน้าจอ = 3 พจน์ `amount - paid - written_off` (`utils/outstanding.ts`)
 *
 * 🔴 idempotency key สร้าง **ตอนเปิด modal** (watch `open` → true) ไม่ใช่ตอนกดบันทึก —
 *    เน็ตสะดุดแล้วผู้ใช้กดซ้ำต้องได้ key เดิม ไม่งั้นเกิดแถว adjustment ซ้ำ
 *    (ต่างจาก void ที่ไม่มี key เพราะเปลี่ยนสถานะซ้ำไม่ได้)
 *
 * 🧮 พรีวิว "คงเหลือหลังทำรายการ" เป็น **การแสดงเท่านั้น** — แหล่งความจริงคือ
 *    `BillAdjustmentResponse.remaining` ที่ backend ตอบมา ผู้เรียกต้อง reload หลัง saved
 *
 * ⚠️ modal นี้เรียก `FinanceService` เอง (เหมือน `HandoverModal`/`ReceiveMoneyModal`)
 *    แล้ว emit `saved(result)` / `close` — `busy`/`errorMessage` จึงเป็น state ภายใน
 *
 * @example
 * <WriteOffModal
 *   :open="writeOffOpen" :payment-id="target.payment_id"
 *   :bill-label="target.label" :outstanding="target.outstanding"
 *   @close="writeOffOpen = false" @saved="fetchDetail"
 * />
 */
import { computed, ref, watch } from 'vue'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { FinanceService } from '@/services/finance'
import { useAuthStore } from '@/stores/auth'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import type {
  BillAdjustmentRequest,
  BillAdjustmentResponse,
  BillAdjustmentType,
} from '@/types/finance'

const props = defineProps<{
  open: boolean
  paymentId: number
  /** คำอธิบายบิลให้ผู้ใช้มั่นใจว่ากำลังตัดใบไหน เช่น "ค่าโครงการ ทัศนศึกษา · นาย ก." */
  billLabel: string
  /** ยอดคงเหลือปัจจุบัน (จาก `outstandingOf` ฝั่งผู้เรียก — ห้ามคำนวณเองที่นี่) */
  outstanding: number
}>()

const emit = defineEmits<{
  close: []
  saved: [result: BillAdjustmentResponse]
}>()

const ADJUSTMENT_OPTIONS: ReadonlyArray<{
  value: BillAdjustmentType
  label: string
  hint: string
}> = [
  {
    value: 'write_off',
    label: 'ตัดเป็นหนี้สูญ',
    hint: 'ไม่ได้รับเงินแล้ว — ตัดออกจากยอดที่ต้องเก็บ',
  },
  {
    value: 'discount',
    label: 'ให้ส่วนลด',
    hint: 'ลดยอดที่ต้องเก็บ (เช่น ให้ส่วนลดตามมติห้อง)',
  },
]

const REASON_MAX = 500

const authStore = useAuthStore()
const roomId = authStore.currentRoomId!

const adjustmentType = ref<BillAdjustmentType>('write_off')
const amountInput = ref('')
const reason = ref('')
const isSaving = ref(false)
const errorMessage = ref('')
/** 🔑 คีย์ของการเปิด modal ครั้งนี้ — ห้ามสร้างใหม่ตอนกดบันทึก */
const idempotencyKey = ref('')

const resetForm = () => {
  adjustmentType.value = 'write_off'
  amountInput.value = roundMoney(props.outstanding).toFixed(2)
  reason.value = ''
  errorMessage.value = ''
  try {
    idempotencyKey.value = newIdempotencyKey()
  } catch {
    // เบราว์เซอร์เก่าที่ไม่มี crypto.randomUUID — เปิด modal ได้แต่บันทึกไม่ได้
    idempotencyKey.value = ''
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) resetForm()
  },
  { immediate: true },
)

/** รับเฉพาะตัวเลข/จุดเดียว/ลบได้ (ติดลบต้องเห็นข้อความ ไม่ใช่หายเงียบ) และ ≤2 ตำแหน่ง */
const sanitizeAmount = (raw: string): string => {
  let s = raw.replace(/[,\s]/g, '').replace(/[^\d.-]/g, '')
  const negative = s.startsWith('-')
  s = s.replace(/-/g, '')
  const firstDot = s.indexOf('.')
  if (firstDot !== -1) {
    s = s.slice(0, firstDot + 1) + s.slice(firstDot + 1).replace(/\./g, '')
    const [intPart = '', decPart = ''] = s.split('.')
    s = `${intPart}.${decPart.slice(0, 2)}`
  }
  return negative ? `-${s}` : s
}

const onAmountInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  amountInput.value = sanitizeAmount(target.value)
  // เขียนค่าที่ sanitize แล้วกลับลงช่องจริง (ผู้ใช้อาจพิมพ์ "," หรือจุดที่สอง)
  target.value = amountInput.value
}

const amountText = computed(() => amountInput.value.trim())

const amountNumber = computed(() => {
  const n = Number(amountText.value)
  return Number.isFinite(n) ? roundMoney(n) : 0
})

const amountError = computed(() => {
  if (!amountText.value) return ''
  const n = Number(amountText.value)
  if (!Number.isFinite(n)) return 'จำนวนเงินไม่ถูกต้อง'
  if (n <= 0) return 'จำนวนเงินต้องมากกว่าศูนย์'
  if (n > roundMoney(props.outstanding) + 0.005) {
    return `จำนวนเงินมากกว่ายอดคงเหลือ (${formatMoney(props.outstanding)})`
  }
  return ''
})

const canSubmit = computed(
  () =>
    !!idempotencyKey.value &&
    !isSaving.value &&
    !!amountText.value &&
    amountNumber.value > 0 &&
    !amountError.value &&
    reason.value.trim().length > 0,
)

/** พรีวิวเท่านั้น — ค่าจริงคือ `result.remaining` จาก backend */
const remainingPreview = computed(() => roundMoney(props.outstanding - amountNumber.value))

const reasonLength = computed(() => reason.value.length)

const confirmText = computed(() =>
  adjustmentType.value === 'discount' ? 'ยืนยันให้ส่วนลด' : 'ยืนยันตัดหนี้',
)

const describeError = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback

const submit = async () => {
  if (!canSubmit.value) return
  isSaving.value = true
  errorMessage.value = ''
  try {
    // ⚠️ backend ของ P6.2 รับ `amount` เป็น **number** (`BillAdjustmentRequest.amount: float`)
    //    ⇒ ส่งค่าที่ปัด 2 ตำแหน่งแล้วตรง ๆ ไม่ส่ง string (Pydantic จะ coerce ได้ แต่ type ต้องตรง)
    const payload: BillAdjustmentRequest = {
      amount: amountNumber.value,
      reason: reason.value.trim(),
      idempotency_key: idempotencyKey.value,
    }
    const result =
      adjustmentType.value === 'discount'
        ? await FinanceService.discountBill(roomId, props.paymentId, payload)
        : await FinanceService.writeOffBill(roomId, props.paymentId, payload)
    emit('saved', result)
    emit('close')
  } catch (error: unknown) {
    // 409/400 → แสดงข้อความไทยจาก interceptor; คง key เดิมไว้ให้กดซ้ำได้อย่างปลอดภัย
    errorMessage.value = describeError(error, 'บันทึกการตัดหนี้ไม่สำเร็จ')
  } finally {
    isSaving.value = false
  }
}

const close = () => {
  if (isSaving.value) return
  emit('close')
}
</script>

<template>
  <AppSheet
    :open="open"
    label="ตัดหนี้ / ให้ส่วนลด"
    title="ตัดหนี้ / ให้ส่วนลด"
    :description="billLabel"
    size="dialog"
    :dismissible="!isSaving"
    @close="close"
  >
    <form class="space-y-4" @submit.prevent="submit">
      <div>
        <span class="field-label">ชนิดรายการ</span>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <button
            v-for="opt in ADJUSTMENT_OPTIONS"
            :key="opt.value"
            type="button"
            class="rounded-xl border px-3 py-2 text-left transition-colors"
            :class="
              adjustmentType === opt.value
                ? 'border-brand-700 bg-brand-tint'
                : 'border-line bg-surface'
            "
            :aria-pressed="adjustmentType === opt.value"
            :disabled="isSaving"
            @click="adjustmentType = opt.value"
          >
            <span class="block text-sm font-bold text-ink-1">{{ opt.label }}</span>
            <span class="block text-xs text-ink-3">{{ opt.hint }}</span>
          </button>
        </div>
      </div>

      <div class="rounded-xl bg-canvas px-3 py-2 text-sm">
        <div class="flex items-center justify-between gap-3">
          <span class="text-ink-3">ยอดคงเหลือปัจจุบัน</span>
          <span class="font-bold text-ink-1 tabular-nums">{{ formatMoney(outstanding) }}</span>
        </div>
        <div v-if="!amountError && amountText" class="mt-1 flex items-center justify-between gap-3">
          <span class="text-ink-3">คงเหลือหลังทำรายการ</span>
          <span class="font-bold text-brand-700 tabular-nums">{{ formatMoney(remainingPreview) }}</span>
        </div>
      </div>

      <div>
        <label class="field-label" for="writeOffAmount">จำนวนเงิน (บาท)</label>
        <input
          id="writeOffAmount"
          :value="amountInput"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          class="field tabular-nums"
          placeholder="0.00"
          :disabled="isSaving"
          :aria-invalid="!!amountError"
          :aria-describedby="amountError ? 'writeOffAmountError' : undefined"
          @input="onAmountInput"
        />
        <p v-if="amountError" id="writeOffAmountError" class="mt-1 text-sm text-danger-700">
          {{ amountError }}
        </p>
        <p v-if="!amountError" class="mt-1 text-xs text-ink-3">
          ค่าเริ่มต้นคือยอดคงเหลือทั้งหมด — ลดจำนวนได้ถ้าตัดบางส่วน
        </p>
      </div>

      <div>
        <label class="field-label" for="writeOffReason">เหตุผล (บังคับ)</label>
        <textarea
          id="writeOffReason"
          v-model="reason"
          class="field min-h-[5rem]"
          :maxlength="REASON_MAX"
          placeholder="เช่น นักเรียนย้ายโรงเรียน / ห้องมีมติให้ส่วนลดค่าทัศนศึกษา"
          :disabled="isSaving"
          aria-describedby="writeOffReasonCounter"
        ></textarea>
        <p id="writeOffReasonCounter" class="mt-1 text-right text-xs text-ink-3 tabular-nums">
          {{ reasonLength }}/{{ REASON_MAX }}
        </p>
      </div>

      <p v-if="!idempotencyKey" class="text-sm text-danger-700">
        เบราว์เซอร์นี้สร้างรหัสกันบันทึกซ้ำไม่ได้ — กรุณาอัปเดตเบราว์เซอร์ก่อนทำรายการเงิน
      </p>

      <p
        v-if="errorMessage"
        class="rounded-xl border border-danger-700/30 bg-danger-700/5 px-3 py-2 text-sm text-danger-700"
        role="alert"
      >
        {{ errorMessage }}
      </p>
    </form>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <AppButton variant="secondary" block class="sm:w-auto" :disabled="isSaving" @click="close">
          ปิด
        </AppButton>
        <AppButton
          variant="danger"
          block
          class="sm:w-auto"
          :loading="isSaving"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ confirmText }}
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
