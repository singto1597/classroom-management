<script setup lang="ts">
/**
 * 📜 CreditHistoryModal — ประวัติเครดิตของนักเรียน 1 คน + ↩️ ยกเลิกการหัก
 *
 * ถอดมาจาก `CreditList.vue` เดิม (FIN-V2 / P3.3) — กติกาที่ห้ามหลุด:
 *  1. แถวที่มาจากใบรับเงิน (`payment_event_id != null`) **ยกเลิกตรงไม่ได้** (backend 409)
 *     ⇒ บอกทางออกให้ไปยกเลิกที่ใบรับเงิน ไม่ใช่โชว์ปุ่มที่กดแล้วพัง
 *  2. ยกเลิกสำเร็จ → โหลดประวัติใหม่ + แจ้ง parent ให้โหลดยอดบัญชีใหม่
 *  3. `CreditPanel` ไม่เรียก API เอง — การโหลดเป็นหน้าที่ของแผ่นนี้
 */
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { StudentCreditBalance, StudentCreditEntry } from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney } from '@/utils/money'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import CreditPanel from '@/components/finance/CreditPanel.vue'
import { useDialog } from '@/composables/useDialog'

const props = defineProps<{
  open: boolean
  student: StudentCreditBalance | null
  /** 🔒 `authStore.canManageFinance` — ไม่ใช่ `isAdmin` */
  canManage: boolean
}>()

const emit = defineEmits<{
  close: []
  /** ผู้ใช้กด "เติมเงินล่วงหน้า" ในแผง — parent ปิดแผ่นนี้แล้วเปิดฟอร์มเติม */
  topup: [student: StudentCreditBalance]
  /** ผู้ใช้กด "ใช้เครดิตปิดบิล" ในแผง — parent ปิดแผ่นนี้แล้วเปิดข้อเสนอ */
  apply: [student: StudentCreditBalance]
  /** ข้อมูลเครดิตเปลี่ยน (ยกเลิกการหัก) — parent ควรโหลดยอดบัญชีใหม่ */
  changed: []
}>()

const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const entries = ref<StudentCreditEntry[]>([])
const isLoading = ref(false)
const historyGuard = createLatestGuard()

const loadHistory = async (student: StudentCreditBalance) => {
  const token = historyGuard.begin()
  isLoading.value = true
  try {
    const res = await FinanceService.getStudentCredit(currentRoomId, student.student_id)
    if (!historyGuard.isCurrent(token)) return
    entries.value = res.entries
  } catch (error: unknown) {
    if (!historyGuard.isCurrent(token)) return
    void dialog.alert(
      'โหลดประวัติไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    if (historyGuard.isCurrent(token)) isLoading.value = false
  }
}

watch(
  [() => props.open, () => props.student],
  ([open, student]) => {
    if (!open || !student) return
    entries.value = []
    void loadHistory(student)
  },
  { immediate: true },
)

/** ปุ่ม "ประวัติ" ในแผง = โหลดใหม่ (ไม่ปิดแผ่น) */
const refreshHistory = async () => {
  if (props.student) await loadHistory(props.student)
}

/** ↩️ ยกเลิก "การหัก" 1 รายการ (คืนเครดิต + เปิดบิลกลับเป็นค้าง) */
const handleUndo = async (entry: StudentCreditEntry) => {
  if (!props.canManage) {
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
    // โหลดใหม่ทั้งสองส่วน — ประวัติเปลี่ยน (แถวเดิมถูกลบ, แถว reverse ถูกเพิ่ม)
    await refreshHistory()
    emit('changed')
  } catch (error: unknown) {
    void dialog.alert(
      'ยกเลิกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีอะไรถูกเปลี่ยนแปลง',
      'error',
    )
  }
}

const onPanelTopUp = (student: StudentCreditBalance) => emit('topup', student)
const onPanelApply = (student: StudentCreditBalance) => emit('apply', student)

const closeSheet = () => emit('close')
</script>

<template>
  <AppSheet
    :open="open && !!student"
    label="ประวัติเครดิต"
    title="ประวัติเครดิต"
    :description="
      student
        ? `${student.student_name} · คงเหลือ ${formatMoney(student.credit_balance)}`
        : undefined
    "
    size="form"
    @close="closeSheet"
  >
    <CreditPanel
      v-if="student"
      :student="student"
      :entries="entries"
      :can-manage="canManage"
      :loading="isLoading"
      @topup="onPanelTopUp"
      @apply="onPanelApply"
      @history="refreshHistory"
      @undo="handleUndo"
    />

    <template #footer>
      <div class="flex justify-end">
        <AppButton variant="secondary" @click="closeSheet">ปิด</AppButton>
      </div>
    </template>
  </AppSheet>
</template>
