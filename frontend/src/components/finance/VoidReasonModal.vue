<script setup lang="ts">
/**
 * 🚫 VoidReasonModal — กล่องยืนยัน "ยกเลิกเอกสาร/เหตุการณ์เงิน" (FIN-V2 / P6.3)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กติกาสำคัญ
 * ═══════════════════════════════════════════════════════════════════════════
 *  • **modal ไม่เรียก API เอง** — emit `confirm(reason)` แล้วให้ผู้เรียกเรียก
 *    `FinanceService.void*` เอง ⇒ modal ใช้ซ้ำได้กับ endpoint void ทั้ง 4 ตัว
 *    (`documents`, `payment-events`, `expense-vouchers`, `income-batches`)
 *  • **ไม่มี idempotency key** (ตั้งใจ) — void เปลี่ยนสถานะเป็น `voided` ซึ่งซ้ำไม่ได้
 *    อยู่แล้ว; กดซ้ำต้องได้ 409 "ยกเลิกไปแล้ว" จาก backend ไม่ใช่สร้างรายการที่สอง
 *  • `summary` เป็น **ตารางอ่านอย่างเดียว** — ค่ามาจาก detail ที่โหลดไว้หรือจาก
 *    `VoidResponse` ห้ามคำนวณเงินใหม่ในหน้านี้
 *  • `busy` ระหว่างรอ → ปิดฉากหลัง/Esc ไม่ได้ (`dismissible=false`) เพื่อไม่ให้ผู้ใช้
 *    คิดว่าไม่มีอะไรเกิดขึ้นแล้วกดซ้ำ
 *  • `errorMessage` (409/400 จาก backend) แสดงในกล่องแดงโดย **ไม่ปิด modal** ⇒
 *    ผู้ใช้อ่านเหตุผลจริงจาก backend ได้
 *  • `reasonRequired=false` = ซ่อนช่องเหตุผลและยืนยันได้ทันที — ใช้กับ legacy
 *    revert (`revertTransaction`) ที่ endpoint **ไม่รับ** reason
 *  • เคลียร์เหตุผลทุกครั้งที่ `open` กลายเป็น true — ไม่งั้นผู้ใช้เปิดใบใหม่แล้วเห็น
 *    เหตุผลของใบก่อนหน้า (และอาจกดยืนยันด้วยเหตุผลผิด)
 *
 * @example
 * <VoidReasonModal
 *   :open="voidOpen" title="ยกเลิกใบแจ้งหนี้" :summary="summaryRows"
 *   :busy="voiding" :error-message="voidError"
 *   @close="voidOpen = false" @confirm="doVoid"
 * />
 */
import { computed, ref, watch } from 'vue'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    /** แถวข้อมูลอ่านอย่างเดียว (เช่น เลขที่เอกสาร / ยอดที่จะกลับ / กระเป๋าที่กระทบ) */
    summary?: Array<{ label: string; value: string }>
    confirmText?: string
    /** `false` = ไม่ถามเหตุผล (เช่น legacy revert ที่ endpoint ไม่รับ reason) */
    reasonRequired?: boolean
    busy?: boolean
    errorMessage?: string
  }>(),
  {
    description: '',
    summary: () => [],
    confirmText: 'ยืนยันยกเลิกเอกสาร',
    reasonRequired: true,
    busy: false,
    errorMessage: '',
  },
)

const emit = defineEmits<{
  close: []
  confirm: [reason: string]
}>()

const REASON_MAX = 500

const reason = ref('')

const reasonLength = computed(() => reason.value.length)
const canConfirm = computed(
  () => (!props.reasonRequired || reason.value.trim().length > 0) && !props.busy,
)

/** เปิดใหม่ทุกครั้ง → เริ่มจากเหตุผลว่างเสมอ */
watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) reason.value = ''
  },
)

const submit = () => {
  if (!canConfirm.value) return
  emit('confirm', reason.value.trim())
}

const close = () => {
  if (props.busy) return
  emit('close')
}
</script>

<template>
  <AppSheet
    :open="open"
    :label="title"
    :title="title"
    :description="description"
    size="dialog"
    :dismissible="!busy"
    @close="close"
  >
    <div class="space-y-4">
      <dl v-if="summary.length" class="divide-y divide-line rounded-xl border border-line">
        <div
          v-for="row in summary"
          :key="row.label"
          class="flex items-start justify-between gap-3 px-3 py-2"
        >
          <dt class="text-sm text-ink-3">{{ row.label }}</dt>
          <dd class="text-right text-sm font-bold text-ink-1">{{ row.value }}</dd>
        </div>
      </dl>

      <div v-if="reasonRequired">
        <label class="field-label" for="voidReason">เหตุผลการยกเลิก (บังคับ)</label>
        <textarea
          id="voidReason"
          v-model="reason"
          class="field min-h-[6rem]"
          :maxlength="REASON_MAX"
          placeholder="เช่น บันทึกผิดคน / จำนวนเงินผิด / ออกเอกสารซ้ำ"
          :disabled="busy"
          aria-describedby="voidReasonCounter"
        ></textarea>
        <p id="voidReasonCounter" class="mt-1 text-right text-xs text-ink-3 tabular-nums">
          {{ reasonLength }}/{{ REASON_MAX }}
        </p>
      </div>

      <p
        v-if="errorMessage"
        class="rounded-xl border border-danger-700/30 bg-danger-700/5 px-3 py-2 text-sm text-danger-700"
        role="alert"
      >
        {{ errorMessage }}
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <AppButton variant="secondary" block class="sm:w-auto" :disabled="busy" @click="close">
          ไม่ยกเลิก
        </AppButton>
        <AppButton
          variant="danger"
          block
          class="sm:w-auto"
          :loading="busy"
          :disabled="!canConfirm"
          @click="submit"
        >
          {{ confirmText }}
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
