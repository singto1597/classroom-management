<script setup lang="ts">
/**
 * ✂️ CreditApplyModal — หักเครดิตปิดบิลของนักเรียน 1 คน
 *
 * ถอดมาจาก `CreditList.vue` เดิม **ทั้งก้อน** (FIN-V2 / P3.3) — กติกา "ระบบเสนอ → ครูยืนยัน":
 *  1. เปิดแผ่น = ขอ **ข้อเสนอ** (`getCreditPlan`) ก่อนเสมอ — ยังไม่เขียนอะไร
 *  2. ไม่มีบิลให้หัก (`total_applied <= 0`) ⇒ บอกแล้วปิด ไม่เปิดหน้าว่าง ๆ
 *  3. หักจริงเดินผ่าน payment event แบบไม่มีเงินสด:
 *     `amount_received:'0.00'` + `use_credit:true` + `excess_action:'none'` + `bill_selection:'auto'`
 *     ⇒ ไม่มี REC ใหม่, ไม่แตะกระเป๋าเงิน (แต่ backend ยังต้องมี `wallet_account_id`)
 *  4. 🔑 `idempotency_key` สร้าง **หลังพรีวิวสำเร็จครั้งแรก** แล้วคงเดิมตลอดจนสำเร็จ/ปิด
 *  5. all-or-nothing: ล้มแล้วต้องบอกว่า **ยังไม่มีรายการใดถูกหัก**
 *
 * 🔒 ฝ่ายเขียนเช็ค `canManageFinance` ซ้ำอีกชั้น
 */
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CreditApplyPlan,
  CreditAllocationItem,
  PaymentEventResult,
  StudentCreditBalance,
} from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney, newIdempotencyKey } from '@/utils/money'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import { useDialog } from '@/composables/useDialog'

const props = defineProps<{
  open: boolean
  student: StudentCreditBalance | null
  /** ใช้กระเป๋าแรกของห้องเป็น `wallet_account_id` (การหักไม่แตะยอดกระเป๋า) */
  accounts: Account[]
}>()

const emit = defineEmits<{
  close: []
  applied: [result: PaymentEventResult]
}>()

const authStore = useAuthStore()
const dialog = useDialog()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const canManageFinance = computed(() => authStore.canManageFinance)

const isPlanLoading = ref(false)
const isApplying = ref(false)
const applyPlan = ref<CreditApplyPlan | null>(null)
const applyKey = ref('')

const planGuard = createLatestGuard()

/** แถวบิลทั้งหมดในข้อเสนอ — ใช้ทั้งแสดงผลและนับจำนวน */
const planAllocations = computed<CreditAllocationItem[]>(
  () => applyPlan.value?.items.flatMap((i) => i.allocations) ?? [],
)

const closeSheet = () => {
  // ห้ามปิดระหว่างยิง API — คำตอบที่มาทีหลังจะไม่มีใครรับ
  if (isApplying.value) return
  isPlanLoading.value = false
  applyPlan.value = null
  // ล้างคีย์เพื่อไม่ให้คีย์เดิมค้างไปรายการถัดไป
  applyKey.value = ''
  emit('close')
}

/**
 * ขอ **ข้อเสนอ** การหักของนักเรียน 1 คน — ยังไม่เขียนอะไร
 * 🔴 ห้ามข้ามไป commit ตรง ๆ (กติกา "ครูยืนยัน")
 */
const loadPlan = async (student: StudentCreditBalance) => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
    emit('close')
    return
  }
  if (student.credit_balance <= 0) {
    void dialog.alert('ไม่มีเครดิตให้ใช้', `${student.student_name} ไม่มีเครดิตคงเหลือ`, 'info')
    emit('close')
    return
  }

  const token = planGuard.begin()
  isPlanLoading.value = true
  applyPlan.value = null
  try {
    const plan = await FinanceService.getCreditPlan(currentRoomId, [student.student_id])
    if (!planGuard.isCurrent(token)) return
    // 🛡️ ไม่มีบิลให้หักเลย = ไม่มีอะไรเกิดขึ้น ⇒ บอกให้รู้แทนที่จะเปิดหน้าว่าง ๆ
    if (plan.total_applied <= 0) {
      void dialog.alert(
        'ไม่มีบิลให้หัก',
        `${student.student_name} ยังไม่มีบิลค้างชำระ — จึงไม่มีอะไรต้องทำ`,
        'info',
      )
      emit('close')
      return
    }
    applyPlan.value = plan
    applyKey.value = newIdempotencyKey()
  } catch (error: unknown) {
    if (!planGuard.isCurrent(token)) return
    void dialog.alert(
      'ดูข้อเสนอการหักไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
    emit('close')
  } finally {
    if (planGuard.isCurrent(token)) isPlanLoading.value = false
  }
}

watch(
  [() => props.open, () => props.student],
  ([open, student]) => {
    if (open && student) void loadPlan(student)
    else applyKey.value = ''
  },
  { immediate: true },
)

const handleApply = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
    return
  }
  const plan = applyPlan.value
  const student = props.student
  if (!plan || !student) return

  // 🧾 การหักเครดิตไม่แตะกระเป๋าเงิน — แต่ backend ยังต้องมี `wallet_account_id`
  const walletAccountId = props.accounts[0]?.id
  if (!walletAccountId) {
    void dialog.alert('ยังไม่มีกระเป๋าเงิน', 'ต้องมีกระเป๋าเงินในห้องก่อนจึงจะหักเครดิตได้', 'warning')
    return
  }

  const confirmed = await dialog.confirm(
    'ยืนยันการหักเครดิต?',
    `จะหักเครดิตของ ${student.student_name} ไปปิดบิลรวม ${planAllocations.value.length} รายการ · ` +
      `ยอดที่หักรวม ${formatMoney(plan.total_applied)} · ` +
      `การหักเครดิตไม่มีเงินเคลื่อนไหว (เงินเข้ามาตั้งแต่ตอนเติม) — ` +
      `หลักฐานคือใบรับเงินล่วงหน้าที่ออกไว้แล้ว`,
    { confirmButtonText: 'ยืนยันหักเครดิต' },
  )
  if (!confirmed.isConfirmed) return

  isApplying.value = true
  void dialog.loading('กำลังหักเครดิต...')
  try {
    const res = await FinanceService.createPaymentEvent(currentRoomId, {
      idempotency_key: applyKey.value,
      student_id: student.student_id,
      payer_name: student.student_name,
      payer_person_id: null,
      receiver_person_id: null,
      receiver_name: currentUserName,
      wallet_account_id: walletAccountId,
      amount_received: '0.00',
      use_credit: true,
      excess_action: 'none',
      bill_selection: 'auto',
      bill_ids: [],
      channel_id: null,
      note: 'ใช้เครดิตปิดบิล',
      event_at: null,
    })

    await dialog.fire({
      icon: 'success',
      title: 'หักเครดิตเรียบร้อย',
      text:
        `ใช้เครดิต ${formatMoney(Number(res.credit_used))} ปิดบิล ${res.allocations.length} รายการ · ` +
        `ยอดที่ปิดรวม ${formatMoney(Number(res.total_applied))}`,
    })
    applyKey.value = ''
    emit('applied', res)
    emit('close')
  } catch (error: unknown) {
    // all-or-nothing: ล้มแล้ว **ไม่มีอะไรถูกหักเลย** — ต้องบอกให้ชัด
    dialog.close()
    void dialog.alert(
      'หักเครดิตไม่สำเร็จ',
      (error instanceof Error ? error.message : 'เกิดข้อผิดพลาด') +
        ' — ยังไม่มีรายการใดถูกหัก (ยกเลิกทั้งชุด)',
      'error',
    )
  } finally {
    isApplying.value = false
  }
}
</script>

<template>
  <AppSheet
    :open="open && !!student"
    label="ตรวจข้อเสนอการหักเครดิต"
    title="ตรวจข้อเสนอการหักเครดิต"
    description="ระบบจะหักบิลที่ครบกำหนดก่อน — ยังไม่มีอะไรถูกบันทึกจนกว่าจะยืนยัน"
    size="form"
    :dismissible="!isApplying"
    @close="closeSheet"
  >
    <SkeletonRows v-if="isPlanLoading" :rows="3" height="h-16" />

    <div v-else-if="applyPlan" class="space-y-3">
      <div
        v-for="item in applyPlan.items"
        :key="item.student_id"
        class="rounded-control border border-line p-3"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate font-bold text-ink">
              {{ item.student_name ?? `#${item.student_id}` }}
            </p>
            <p class="text-caption text-ink-3">
              เครดิตก่อนหัก {{ formatMoney(item.balance_before) }}
            </p>
          </div>
          <div class="shrink-0 text-right">
            <p class="num font-bold text-ink">−{{ formatMoney(item.total_applied) }}</p>
            <p class="text-caption text-ink-3">เหลือ {{ formatMoney(item.balance_after) }}</p>
          </div>
        </div>

        <p v-if="!item.allocations.length" class="mt-2 text-caption text-ink-3">
          ไม่มีบิลให้หัก — เครดิตคงอยู่เต็มจำนวน
        </p>

        <ul v-else class="mt-2 space-y-1.5 border-t border-line pt-2">
          <li
            v-for="a in item.allocations"
            :key="a.payment_id"
            class="flex items-start justify-between gap-3 text-caption"
          >
            <span class="min-w-0 truncate text-ink-2">
              {{ a.title ?? 'รายการชำระเงิน' }}
              <span v-if="a.due_date" class="text-ink-3">({{ a.due_date }})</span>
            </span>
            <span class="num shrink-0 text-right font-bold text-ink">
              {{ formatMoney(a.apply_amount) }}
            </span>
          </li>
        </ul>
      </div>

      <div class="flex items-center justify-between border-t border-line pt-3">
        <span class="text-sm font-bold text-ink-2">รวมที่จะหัก</span>
        <span class="num text-lg font-bold text-ink">{{ formatMoney(applyPlan.total_applied) }}</span>
      </div>

      <p class="rounded-control bg-canvas p-3 text-caption text-ink-2">
        การหักเครดิต <b>ไม่มีเงินเคลื่อนไหว</b> และ <b>ไม่ออกใบเสร็จใหม่</b> —
        รายได้ของห้องจะถูกนับ <b>ณ จังหวะนี้</b> และหลักฐานคือใบรับเงินล่วงหน้าที่ออกไว้แล้ว
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <AppButton variant="secondary" :disabled="isApplying" @click="closeSheet">ยกเลิก</AppButton>
        <AppButton
          variant="primary"
          :loading="isApplying"
          :disabled="isApplying || !applyPlan"
          @click="handleApply"
        >
          <i class="bi bi-check-lg" aria-hidden="true"></i>
          ยืนยันหักเครดิต
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
