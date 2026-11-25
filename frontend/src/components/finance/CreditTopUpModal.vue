<script setup lang="ts">
/**
 * 💵 CreditTopUpModal — เติมเงินล่วงหน้า (top-up) ของนักเรียน 1 คน
 *
 * ถอดมาจาก `CreditList.vue` เดิม **ทั้งก้อน** (FIN-V2 / P3.3) — สัญญาที่ห้ามหลุด:
 *  1. เดินผ่าน **payment event** ด้วย `bill_selection:'manual'` + `bill_ids:[]`
 *     ⇒ เงินทั้งก้อนเป็น `credit_added` ไม่ถูกเอาไปปิดบิลที่ครูไม่ได้เลือก
 *  2. `excess_action:'credit'` + `use_credit:false` — เงินส่วนเกิน/ทั้งหมดเป็นเครดิต
 *  3. 🔑 `idempotency_key` สร้าง **ครั้งเดียวตอนเปิดแผ่น** แล้วใช้ค่าเดิมตลอดจนสำเร็จ/ปิด
 *     ถ้าสร้างใหม่ตอน retry เงินก้อนเดียวจะถูกบันทึกเป็นเครดิตสองรอบโดยไม่มีอะไรฟ้อง
 *  4. `reused=true` ไม่ใช่ความผิดพลาด — ต้องบอกให้ตรงความจริงว่าไม่บันทึกซ้ำ
 *  5. เติมเครดิตล้วน **ไม่ควร** ออกใบเสร็จ — ถ้าเจอ ให้เตือนให้แจ้งผู้ดูแล
 *
 * 🔒 ฝ่ายเขียนเช็ค `canManageFinance` ซ้ำอีกชั้น (backend บังคับอยู่แล้ว)
 * ⚠️ เงินทุกช่องเป็นสตริง 2 ตำแหน่ง (Decimal ฝั่ง backend)
 */
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { Account, PaymentEventResult, StudentCreditBalance } from '@/types/finance'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useDialog } from '@/composables/useDialog'

const props = defineProps<{
  open: boolean
  student: StudentCreditBalance | null
  /** กระเป๋าที่เงินเข้าจริง — ต้องมีอย่างน้อย 1 ใบก่อนเติมได้ */
  accounts: Account[]
}>()

const emit = defineEmits<{
  close: []
  saved: [result: PaymentEventResult]
}>()

const authStore = useAuthStore()
const dialog = useDialog()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const canManageFinance = computed(() => authStore.canManageFinance)

const topUpAmount = ref('')
const topUpAccountId = ref('')
const topUpNote = ref('')
const isToppingUp = ref(false)

/** 🔑 คีย์ของการกดครั้งนี้ — สร้างครั้งเดียวตอนเปิดแผ่น (ดูหัวไฟล์ข้อ 3) */
const topUpKey = ref('')

/** ยอดที่กรอกเป็นตัวเลขจริงหรือยัง (> 0) — ใช้ทั้งโชว์ตัวอย่างและกันการยิง API */
const topUpAmountNumber = computed(() => {
  const n = Number(topUpAmount.value)
  return Number.isFinite(n) && n > 0 ? roundMoney(n) : 0
})

const initForm = () => {
  topUpAmount.value = ''
  topUpNote.value = ''
  topUpAccountId.value = props.accounts[0]?.id.toString() ?? ''
  try {
    topUpKey.value = newIdempotencyKey()
  } catch (error: unknown) {
    // เบราว์เซอร์ที่สร้างคีย์ปลอดภัยไม่ได้ ⇒ **ไม่ทำรายการต่อ**
    void dialog.alert(
      'ทำรายการไม่ได้',
      error instanceof Error ? error.message : 'สร้างรหัสกันบันทึกซ้ำไม่สำเร็จ',
      'error',
    )
    emit('close')
  }
}

watch(
  [() => props.open, () => props.student],
  ([open, student]) => {
    if (open && student) initForm()
    else topUpKey.value = ''
  },
  { immediate: true },
)

const handleTopUp = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่เติมเงินล่วงหน้าได้', 'error')
    return
  }
  const student = props.student
  if (!student) return
  // ⚠️ เช็คซ้ำที่นี่ (ไม่พึ่ง `disabled` ของปุ่ม) — backend ยังบังคับอีกชั้นและตอบ 400
  if (topUpAmountNumber.value <= 0) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกจำนวนเงินมากกว่า 0 บาท', 'warning')
    return
  }
  if (!topUpAccountId.value) {
    void dialog.alert('ยังไม่เลือกกระเป๋า', 'กรุณาเลือกกระเป๋าเงินที่รับเงินจริงก่อน', 'warning')
    return
  }

  isToppingUp.value = true
  try {
    // 🧾 เติมเครดิตเดินผ่าน payment event (แหล่งจริงเดียว)
    const res = await FinanceService.createPaymentEvent(currentRoomId, {
      idempotency_key: topUpKey.value,
      student_id: student.student_id,
      payer_name: student.student_name,
      payer_person_id: null,
      receiver_person_id: null,
      receiver_name: currentUserName,
      wallet_account_id: Number(topUpAccountId.value),
      amount_received: topUpAmountNumber.value.toFixed(2),
      use_credit: false,
      excess_action: 'credit',
      bill_selection: 'manual',
      bill_ids: [],
      channel_id: null,
      note: topUpNote.value || null,
      event_at: null,
    })

    // 💡 `reused` = กดซ้ำด้วยคีย์เดิม ⇒ ไม่ใช่ความผิดพลาด แต่ต้องบอกให้ตรงความจริง
    const depNo = res.deposit_no ?? '—'
    if (res.receipt_no) {
      // 🚨 เติมเครดิตล้วน **ไม่ควร** ออกใบเสร็จ — ถ้าเห็นใบเสร็จ ให้แจ้งผู้ดูแลทันที
      await dialog.fire({
        icon: 'warning',
        title: 'เติมเครดิตสำเร็จ · แต่ระบบออกใบเสร็จด้วย',
        text:
          `ออกใบรับเงินล่วงหน้า ${depNo} แล้ว · พบใบเสร็จ ${res.receipt_no} ` +
          `ซึ่งไม่ควรเกิดกับการเติมเครดิตล้วน — กรุณาแจ้งผู้ดูแลระบบ`,
      })
    } else {
      await dialog.fire({
        icon: 'success',
        title: res.reused ? 'รายการนี้ถูกบันทึกไว้แล้ว' : 'เติมเงินล่วงหน้าเรียบร้อย',
        text: res.reused
          ? `ระบบตรวจพบว่าเป็นการกดซ้ำจากรายการเดิม จึงไม่บันทึกซ้ำ · เครดิตที่เพิ่ม ${formatMoney(Number(res.credit_added))}`
          : `รับเงิน ${formatMoney(Number(res.amount_received))} จาก ${student.student_name} · เพิ่มเครดิต ${formatMoney(Number(res.credit_added))} · ออกใบรับเงินล่วงหน้าเลขที่ ${depNo} แล้ว — เงินก้อนนี้จะยังไม่นับเป็นรายได้ จนกว่าจะถูกหักปิดบิล`,
      })
    }

    // ⚠️ ล้างคีย์หลังสำเร็จ ⇒ การเปิดแผ่นครั้งถัดไปคือ "รายการใหม่" จริง ๆ
    topUpKey.value = ''
    emit('saved', res)
    emit('close')
  } catch (error: unknown) {
    void dialog.alert(
      'เติมเงินล่วงหน้าไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีรายการใดถูกบันทึก',
      'error',
    )
  } finally {
    isToppingUp.value = false
  }
}

const closeSheet = () => {
  if (isToppingUp.value) return
  emit('close')
}
</script>

<template>
  <AppSheet
    :open="open && !!student"
    label="เติมเงินล่วงหน้า"
    title="เติมเงินล่วงหน้า"
    :description="
      student
        ? `${student.student_name} · เครดิตปัจจุบัน ${formatMoney(student.credit_balance)}`
        : undefined
    "
    size="form"
    :dismissible="!isToppingUp"
    @close="closeSheet"
  >
    <div class="space-y-3">
      <div>
        <label class="field-label" for="topup-amount">จำนวนเงินที่รับมา (บาท)</label>
        <input
          id="topup-amount"
          v-model="topUpAmount"
          type="number"
          min="0.01"
          step="0.01"
          inputmode="decimal"
          class="field num"
          placeholder="0.00"
        />
      </div>

      <div>
        <label class="field-label" for="topup-account">กระเป๋าที่เงินเข้าจริง</label>
        <select id="topup-account" v-model="topUpAccountId" class="field">
          <option v-for="a in accounts" :key="a.id" :value="a.id.toString()">
            {{ a.account_name }}
          </option>
        </select>
      </div>

      <div>
        <label class="field-label" for="topup-note">หมายเหตุ (ไม่บังคับ)</label>
        <input
          id="topup-note"
          v-model="topUpNote"
          type="text"
          maxlength="255"
          class="field"
          placeholder="เช่น โอนพร้อมเพย์เมื่อ 10 ก.ย."
        />
      </div>

      <!-- 💡 เตือนความหมายให้ถูกตั้งแต่ก่อนกด — กันเข้าใจว่า "รายได้เข้าแล้ว" -->
      <p class="rounded-control bg-canvas p-3 text-caption text-ink-2">
        เงินก้อนนี้จะถูกเก็บเป็น <b>เครดิตคงเหลือ</b> ของนักเรียน และยัง
        <b>ไม่นับเป็นรายได้</b> ของห้อง — ระบบจะออก
        <b>ใบรับเงินล่วงหน้า (DEP)</b> ให้เป็นหลักฐานทันที
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <AppButton variant="secondary" :disabled="isToppingUp" @click="closeSheet">ยกเลิก</AppButton>
        <AppButton
          variant="primary"
          :loading="isToppingUp"
          :disabled="isToppingUp || topUpAmountNumber <= 0"
          @click="handleTopUp"
        >
          <i class="bi bi-check-lg" aria-hidden="true"></i>
          ยืนยันเติม {{ topUpAmountNumber > 0 ? formatMoney(topUpAmountNumber) : '' }}
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
