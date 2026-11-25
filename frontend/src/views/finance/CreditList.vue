<script setup lang="ts">
/**
 * 💰 เงินรับล่วงหน้า — เครดิตคงเหลือรายนักเรียน (F4)
 *
 * ════════════════════════════════════════════════════════════════════════════
 * 🔑 สิ่งที่หน้านี้ต้องสื่อให้ถูก (ถ้าสื่อผิด ผู้ใช้จะเข้าใจการเงินของห้องผิดทั้งห้อง)
 * ════════════════════════════════════════════════════════════════════════════
 *    เติมเครดิต = รับเงินจริงเข้ากระเป๋า แต่ **ยังไม่ใช่รายได้ของห้อง** — เป็น
 *                 "เงินที่เราถือไว้ให้เขา" (หนี้สิน) จนกว่าจะถูกใช้ปิดบิล
 *    หักเครดิต  = เอาเงินที่ถือไว้ไปปิดบิล ⇒ **ไม่มีเงินเคลื่อนไหวในจังหวะนี้**
 *                 และ **ไม่มีใบเสร็จใหม่** (หลักฐานคือใบ DEP ตอนเติม)
 *
 * ⇒ ถ้อยคำบนจอจึงห้ามใช้ "รายได้" กับการเติมเงิน และห้ามใช้ "รับเงิน" กับการหักเครดิต
 *
 * ════════════════════════════════════════════════════════════════════════════
 * 🔒 สิทธิ์ (บทเรียนจาก `DebtorList.vue` — ห้ามพลาดซ้ำ)
 * ════════════════════════════════════════════════════════════════════════════
 * ฝั่ง backend แยกชัด: **อ่าน** = สมาชิกห้องทุกคน · **เขียน** = `MANAGE_FINANCE`
 * ⇒ ปุ่มเขียนทุกปุ่มที่นี่ gate ด้วย `canManageFinance` **ไม่ใช่ `isAdmin`**
 *    ถ้าใช้ `isAdmin` เหรัญญิกที่มีสิทธิ์จริงจะใช้ฟีเจอร์นี้ไม่ได้เลย
 *
 * ════════════════════════════════════════════════════════════════════════════
 * ⚙️ กติกาที่ผู้ใช้เลือกไว้: **ระบบเสนอ → ครูยืนยัน** (ไม่หักเองเงียบ ๆ)
 * ════════════════════════════════════════════════════════════════════════════
 * ⇒ ปุ่ม "หักเครดิต" **ไม่ยิง API ทันที** แต่เปิดหน้าตรวจข้อเสนอ (`getCreditPlan`)
 *    ให้เห็นก่อนว่าจะหักบิลไหน เท่าไร เหลือเท่าไร แล้วจึงกดยืนยัน
 *    ตัวเลขที่โชว์ตอนตรวจกับที่ระบบทำจริงมาจากฟังก์ชันเดียวกันฝั่ง backend
 */
import { ref, onMounted, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  StudentCreditBalance,
  CreditApplyPlan,
  StudentCreditEntry,
  CreditAllocationItem,
} from '@/types/finance'
import RowActionMenu from '@/components/ui/RowActionMenu.vue';
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue';
import { createLatestGuard } from '@/utils/latest'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'

import CreditPanel from '@/components/finance/CreditPanel.vue'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useDialog } from '@/composables/useDialog'

const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

/** 🔒 ปุ่ม **เขียน** ใช้ตัวนี้ — ไม่ใช่ `isAdmin` (ดูเหตุผลในหัวไฟล์) */
const canManageFinance = computed(() => authStore.canManageFinance)

// ─────────────────────────────────────────────────────── สถานะของรายการหลัก
const credits = ref<StudentCreditBalance[]>([])
const accounts = ref<Account[]>([])
const isLoading = ref(true)
const hasError = ref(false)

const listGuard = createLatestGuard()

// ─────────────────────────────────────────────────────── สรุปภาพรวม
/** เงินที่ห้อง **ถือไว้** ให้ทุกคนรวมกัน — ไม่ใช่รายได้ (ยังไม่ถูกใช้ปิดบิล) */
const totalHeld = computed(() => roundMoney(credits.value.reduce((s, c) => s + c.credit_balance, 0)))

/** จำนวนคนที่มีเครดิตคงเหลือ (> 0) */
const holdersCount = computed(() => credits.value.filter((c) => c.credit_balance > 0).length)

const fetchCredits = async () => {
  const token = listGuard.begin()
  isLoading.value = true
  hasError.value = false
  try {
    const [creditRes, accRes] = await Promise.all([
      FinanceService.getCredits(currentRoomId),
      // ต้องมีกระเป๋าให้เลือกตอนเติมเงิน (ขา Dr ของ journal) — คนละรายการกับเครดิต
      FinanceService.getAccounts(currentRoomId),
    ])
    if (!listGuard.isCurrent(token)) return
    credits.value = creditRes
    accounts.value = accRes
  } catch {
    if (!listGuard.isCurrent(token)) return
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดข้อมูลเงินรับล่วงหน้าไม่สำเร็จ', 'error')
  } finally {
    if (listGuard.isCurrent(token)) isLoading.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 💵 เติมเงินล่วงหน้า (top-up)
// ════════════════════════════════════════════════════════════════════════════
const isTopUpOpen = ref(false)
const topUpTarget = ref<StudentCreditBalance | null>(null)
const topUpAmount = ref<string>('')
const topUpAccountId = ref<string>('')
const topUpNote = ref<string>('')
const isToppingUp = ref(false)

/**
 * 🔑 รหัสกันบันทึกซ้ำของ **การกดครั้งนี้**
 *
 * 🔴 ต้องสร้าง **ครั้งเดียวตอนเปิดโมดัล** แล้วใช้ค่าเดิมตลอดจนสำเร็จ/ปิด
 *    ถ้าสร้างใหม่ตอน retry (เช่น ยิงซ้ำหลังเน็ตสะดุด) backend จะมองเป็น "รายการใหม่"
 *    ⇒ เงินก้อนเดียวถูกบันทึกเป็นเครดิต **สองรอบ** โดยไม่มีอะไรฟ้อง
 *    ⇒ จึงเก็บไว้ที่ตัวแปรนี้ ไม่ใช่เรียกในฟังก์ชันยิง API
 */
const topUpKey = ref<string>('')

const openTopUp = (student: StudentCreditBalance) => {
  topUpTarget.value = student
  topUpAmount.value = ''
  topUpNote.value = ''
  topUpAccountId.value = accounts.value[0]?.id.toString() ?? ''
  try {
    topUpKey.value = newIdempotencyKey()
  } catch (error: unknown) {
    // เบราว์เซอร์ที่สร้างคีย์ปลอดภัยไม่ได้ ⇒ **ไม่ทำรายการต่อ** (ดูเหตุผลใน utils/money.ts)
    void dialog.alert(
      'ทำรายการไม่ได้',
      error instanceof Error ? error.message : 'สร้างรหัสกันบันทึกซ้ำไม่สำเร็จ',
      'error',
    )
    return
  }
  isTopUpOpen.value = true
}

/** ยอดที่กรอกเป็นตัวเลขจริงหรือยัง (> 0) — ใช้ทั้งโชว์ตัวอย่างและกันการยิง API */
const topUpAmountNumber = computed(() => {
  const n = Number(topUpAmount.value)
  return Number.isFinite(n) && n > 0 ? roundMoney(n) : 0
})

const handleTopUp = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่เติมเงินล่วงหน้าได้', 'error')
    return
  }
  const student = topUpTarget.value
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
    // 🧾 [FIN-V2 / P3.3] เติมเครดิตเดินผ่าน **payment event** แล้ว (แหล่งจริงเดียว)
    //    `manual` + `bill_ids: []` = **ไม่ปิดบิลสักใบ** ⇒ เงินทั้งก้อนกลายเป็น `credit_added`
    //    `excess_action: 'credit'` = ส่วนเกิน/ทั้งหมดเป็นเครดิต (ได้รับอนุญาตตามกติกา event)
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

    // 💡 `reused` = true แปลว่ากดซ้ำด้วยคีย์เดิม ⇒ **ไม่ใช่ความผิดพลาด** แต่ต้องบอก
    //    ให้ตรงความจริง ไม่งั้นผู้ใช้จะนึกว่าเงินเข้าอีกรอบ (หรือนึกว่าไม่เข้าเลย)
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

    isTopUpOpen.value = false
    await fetchCredits()
    // ⚠️ ล้างคีย์หลังสำเร็จ ⇒ การเปิดโมดัลครั้งถัดไปคือ "รายการใหม่" จริง ๆ
    topUpKey.value = ''
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

// ════════════════════════════════════════════════════════════════════════════
// ✂️ หักเครดิตปิดบิล — "ระบบเสนอ → ครูยืนยัน"
// ════════════════════════════════════════════════════════════════════════════
const isApplyOpen = ref(false)
const isPlanLoading = ref(false)
const isApplying = ref(false)
const applyPlan = ref<CreditApplyPlan | null>(null)
const applyTarget = ref<StudentCreditBalance | null>(null)

/**
 * 🔑 รหัสกันบันทึกซ้ำของ **การหักครั้งนี้**
 * 🔴 สร้างครั้งเดียวตอนเปิดแผ่น (หลังพรีวิวสำเร็จ) แล้วใช้ค่าเดิมตลอดจนสำเร็จ/ปิด
 */
const applyKey = ref<string>('')

const planGuard = createLatestGuard()

/**
 * ขอ **ข้อเสนอ** การหักของนักเรียน 1 คนแล้วเปิดหน้าตรวจ — ยังไม่เขียนอะไร
 * 🔴 ต้องเรียกตัวนี้เสมอ ห้ามข้ามไป commit ตรง ๆ (กติกา "ครูยืนยัน")
 * ℹ️ หลายคนพร้อมกันอยู่ใน P3.5 (`BulkCreditSheet`) — หน้านี้ทีละคน
 */
const openApplyPreview = async (student: StudentCreditBalance) => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
    return
  }
  if (student.credit_balance <= 0) {
    void dialog.alert('ไม่มีเครดิตให้ใช้', `${student.student_name} ไม่มีเครดิตคงเหลือ`, 'info')
    return
  }

  const token = planGuard.begin()
  isPlanLoading.value = true
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
      return
    }
    applyPlan.value = plan
    applyTarget.value = student
    applyKey.value = newIdempotencyKey()
    isApplyOpen.value = true
  } catch (error: unknown) {
    if (!planGuard.isCurrent(token)) return
    void dialog.alert(
      'ดูข้อเสนอการหักไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    if (planGuard.isCurrent(token)) isPlanLoading.value = false
  }
}

/** แถวบิลทั้งหมดในข้อเสนอ — ใช้ทั้งแสดงผลและนับจำนวน */
const planAllocations = computed<CreditAllocationItem[]>(
  () => applyPlan.value?.items.flatMap((i) => i.allocations) ?? [],
)

const handleApply = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
    return
  }
  const plan = applyPlan.value
  const student = applyTarget.value
  if (!plan || !student) return
  // 🧾 การหักเครดิตไม่แตะกระเป๋าเงิน — แต่ backend ยังต้องมี `wallet_account_id`
  //    (ไม่มีผลกับยอด) ⇒ ใช้กระเป๋าแรกของห้อง
  const walletAccountId = accounts.value[0]?.id
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
    // 🧾 [FIN-V2 / P3.3] หักเครดิตเดินผ่าน payment event (`use_credit` + ไม่มีเงินสด)
    //    ⇒ ได้แถว `student_credits` ที่มี `payment_event_id` + ไม่มี REC / transaction
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

    isApplyOpen.value = false
    await dialog.fire({
      icon: 'success',
      title: 'หักเครดิตเรียบร้อย',
      text:
        `ใช้เครดิต ${formatMoney(Number(res.credit_used))} ปิดบิล ${res.allocations.length} รายการ · ` +
        `ยอดที่ปิดรวม ${formatMoney(Number(res.total_applied))}`,
    })
    applyKey.value = ''
    await fetchCredits()
  } catch (error: unknown) {
    // all-or-nothing: ล้มแล้ว **ไม่มีอะไรถูกหักเลย** — ต้องบอกให้ชัด ไม่งั้นผู้ใช้
    // จะไม่กล้ากดซ้ำเพราะนึกว่าหักไปบางส่วนแล้ว
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

/** ปิดแผ่นหักเครดิต — ล้างคีย์เพื่อไม่ให้คีย์เดิมค้างไปรายการถัดไป */
const closeApply = () => {
  isApplyOpen.value = false
  applyKey.value = ''
}

// ════════════════════════════════════════════════════════════════════════════
// 📜 ประวัติเครดิต + ↩️ ยกเลิกการหัก
// ════════════════════════════════════════════════════════════════════════════
const isHistoryOpen = ref(false)
const historyTarget = ref<StudentCreditBalance | null>(null)
const historyEntries = ref<StudentCreditEntry[]>([])
const isHistoryLoading = ref(false)
const historyGuard = createLatestGuard()

// 🔒 การ์ด/แถวละ "ปุ่มเดียว": เติมเงิน (งานหลักของหน้านี้)
//    ประวัติเป็นงานอ่านที่เกิดบ่อยกว่าแต่ไม่ใช่การกระทำหลัก ⇒ อยู่ในเมนูจุด 3 จุด
//    ผู้ใช้ที่ไม่มีสิทธิ์เขียนไม่เห็น "เติม" ⇒ ประวัติยังเป็นการ์ดปุ่มเดียวอยู่แล้ว
const creditMenuItems: RowActionItem[] = [
  { key: 'history', label: 'ประวัติเครดิต', icon: 'bi-clock-history' },
];

const handleCreditAction = (student: StudentCreditBalance, key: string) => {
  if (key === 'history') void openHistory(student);
};

const openHistory = async (student: StudentCreditBalance) => {
  historyTarget.value = student
  historyEntries.value = []
  isHistoryOpen.value = true

  const token = historyGuard.begin()
  isHistoryLoading.value = true
  try {
    const res = await FinanceService.getStudentCredit(currentRoomId, student.student_id)
    if (!historyGuard.isCurrent(token)) return
    historyEntries.value = res.entries
  } catch (error: unknown) {
    if (!historyGuard.isCurrent(token)) return
    void dialog.alert(
      'โหลดประวัติไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
    isHistoryOpen.value = false
  } finally {
    if (historyGuard.isCurrent(token)) isHistoryLoading.value = false
  }
}

/** ↩️ ยกเลิก "การหัก" 1 รายการ (คืนเครดิต + เปิดบิลกลับเป็นค้าง) */
const handleUndo = async (entry: StudentCreditEntry) => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ยกเลิกได้', 'error')
    return
  }
  // 🧾 [FIN-V2 / P3.3] แถวที่เกิดจากใบรับเงิน **ห้ามยกเลิกตรง** (backend ตอบ 409)
  //    ต้องไปยกเลิกที่ใบรับเงิน (void engine, P6.1) ⇒ บอกทางออกแทนการยิง API
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
    if (historyTarget.value) await openHistory(historyTarget.value)
    await fetchCredits()
  } catch (error: unknown) {
    void dialog.alert(
      'ยกเลิกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีอะไรถูกเปลี่ยนแปลง',
      'error',
    )
  }
}

/** 📜 แผงเครดิต (CreditPanel) ขอเปิดฟอร์มจากในประวัติ ⇒ ปิดแผ่นแล้วเปิดฟอร์มนั้น */
const onPanelTopUp = (student: StudentCreditBalance) => {
  isHistoryOpen.value = false
  openTopUp(student)
}

const onPanelApply = (student: StudentCreditBalance) => {
  isHistoryOpen.value = false
  void openApplyPreview(student)
}

/** ปุ่ม "ประวัติ" ในแผง = โหลดใหม่ (ไม่ปิดแผ่น) */
const refreshHistory = async () => {
  if (historyTarget.value) await openHistory(historyTarget.value)
}

onMounted(() => {
  fetchCredits()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="เงินที่ห้องถือไว้ให้เพื่อนแต่ละคน — จะกลายเป็นรายได้ก็ต่อเมื่อถูกหักไปปิดบิล"
    >
      <template #actions>
        <!--
          🔒 ปุ่มเขียน gate ด้วย `canManageFinance` **ไม่ใช่ `isAdmin`** — บทเรียนเดียวกับ
          `DebtorList.vue`: เหรัญญิกที่มี MANAGE_FINANCE แต่ไม่ใช่แอดมินต้องใช้ได้
          ℹ️ P3.3: หักเครดิตทำ **ทีละคน** จากปุ่มในแถว — หลายคนพร้อมกันอยู่ใน P3.5
        -->
        <RouterLink to="/finance/debtors" class="btn-ghost-ui" title="ดูยอดค้างชำระ">
          <i class="bi bi-people" aria-hidden="true"></i>
          ยอดค้างชำระ
        </RouterLink>
      </template>
    </PageIntro>

    <!-- 📊 สรุปภาพรวม — ตัวเลขหลักคือ "เงินที่ถือไว้" ซึ่ง **ไม่ใช่รายได้** -->
    <div v-if="!isLoading && !hasError" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="page-card p-4">
        <p class="text-caption font-bold text-ink-3">เงินที่ห้องถือไว้ให้ทุกคน</p>
        <p class="num mt-1 text-2xl font-bold text-ink">
          {{ formatMoney(totalHeld) }}
        </p>
        <p class="mt-1 text-caption text-ink-3">
          ยังไม่นับเป็นรายได้ — จะนับก็ต่อเมื่อหักปิดบิลแล้ว
        </p>
      </div>
      <div class="page-card p-4">
        <p class="text-caption font-bold text-ink-3">จำนวนคนที่มีเครดิตคงเหลือ</p>
        <p class="num mt-1 text-2xl font-bold text-ink">
          {{ holdersCount }} <span class="text-base font-bold text-ink-3">คน</span>
        </p>
        <p class="mt-1 text-caption text-ink-3">จากทั้งหมด {{ credits.length }} คนในห้อง</p>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-24" />

    <StateBlock v-else-if="hasError" variant="error" @retry="fetchCredits" />

    <StateBlock
      v-else-if="!credits.length"
      variant="empty"
      icon="bi-person-x"
      title="ยังไม่มีนักเรียนในห้องนี้"
      hint="เพิ่มนักเรียนเข้าห้องก่อน แล้วจึงเติมเงินล่วงหน้าได้"
    />

    <template v-else>
      <!-- ℹ️ P3.3: ตัด multi-select ออก — หักเครดิตทีละคน (หลายคนพร้อมกัน = P3.5) -->
      <p class="text-caption text-ink-3">
        ใช้เครดิตได้ทีละคนจากปุ่มในแต่ละแถว · ใช้เครดิตหลายคนพร้อมกันจะมาใน P3.5
      </p>

      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="c in credits"
          :key="c.student_id"
          class="page-card p-4"
          :class="c.credit_balance > 0 ? 'border-s-4 border-s-ok-500' : ''"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-2">
              <span class="chip num shrink-0 bg-canvas text-ink-2">#{{ c.student_no }}</span>
              <h2 class="min-w-0 truncate text-base font-bold text-ink">
                {{ c.student_name }}
              </h2>
            </div>

            <div class="shrink-0 text-right">
              <p class="text-caption font-bold text-ink-3">เครดิตคงเหลือ</p>
              <p
                class="num mt-0.5 whitespace-nowrap text-lg font-bold"
                :class="c.credit_balance > 0 ? 'text-ok-600' : 'text-ink-3'"
              >
                {{ formatMoney(c.credit_balance) }}
              </p>
            </div>
          </div>

          <div class="mt-2.5 flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
            <span class="chip shrink-0 bg-canvas text-ink-2">
              ค้าง {{ formatMoney(c.total_pending_amount) }}
            </span>
            <span
              class="chip shrink-0"
              :class="c.net_pending_amount > 0 ? 'bg-danger-50 text-danger-700' : 'bg-ok-50 text-ok-700'"
            >
              ต้องเก็บจริง {{ formatMoney(c.net_pending_amount) }}
            </span>
          </div>

          <div v-if="canManageFinance" class="mt-2.5 flex flex-wrap items-center gap-2">
            <button type="button" class="btn-ghost-ui" @click="openTopUp(c)">
              <i class="bi bi-plus-circle" aria-hidden="true"></i>
              เติมเงินล่วงหน้า
            </button>
            <button
              type="button"
              class="btn-ghost-ui"
              :disabled="c.credit_balance <= 0 || isPlanLoading"
              @click="openApplyPreview(c)"
            >
              <i class="bi bi-scissors" aria-hidden="true"></i>
              ใช้เครดิตปิดบิล
            </button>
            <RowActionMenu
              :label="`ตัวเลือกของ ${c.student_name}`"
              :items="creditMenuItems"
              @select="handleCreditAction(c, $event)"
            />
          </div>
          <div v-else class="mt-2.5">
            <button type="button" class="btn-ghost-ui" @click="openHistory(c)">
              <i class="bi bi-clock-history" aria-hidden="true"></i>
              ดูประวัติเครดิต
            </button>
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
                <th class="text-right">เครดิตคงเหลือ (฿)</th>
                <th class="text-right">ยอดค้างดิบ (฿)</th>
                <th class="text-right">ต้องเก็บจริง (฿)</th>
                <th class="text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in credits" :key="c.student_id">
                <td class="num font-bold text-ink-3">#{{ c.student_no }}</td>
                <td class="font-bold text-ink">{{ c.student_name }}</td>
                <td
                  class="num whitespace-nowrap text-right font-bold"
                  :class="c.credit_balance > 0 ? 'text-ok-600' : 'text-ink-3'"
                >
                  {{ formatMoney(c.credit_balance) }}
                </td>
                <td class="num whitespace-nowrap text-right text-ink-3">
                  {{ formatMoney(c.total_pending_amount) }}
                </td>
                <td
                  class="num whitespace-nowrap text-right font-bold"
                  :class="c.net_pending_amount > 0 ? 'text-danger-600' : 'text-ok-600'"
                >
                  {{ formatMoney(c.net_pending_amount) }}
                </td>
                <td>
                  <div class="flex items-center justify-end gap-2">
                    <button
                      v-if="canManageFinance"
                      type="button"
                      class="btn-ghost-ui"
                      @click="openTopUp(c)"
                    >
                      <i class="bi bi-plus-circle" aria-hidden="true"></i>
                      เติม
                    </button>
                    <button
                      v-if="canManageFinance"
                      type="button"
                      class="btn-ghost-ui"
                      :disabled="c.credit_balance <= 0 || isPlanLoading"
                      @click="openApplyPreview(c)"
                    >
                      <i class="bi bi-scissors" aria-hidden="true"></i>
                      ใช้เครดิต
                    </button>
                    <button
                      v-else
                      type="button"
                      class="btn-ghost-ui"
                      @click="openHistory(c)"
                    >
                      <i class="bi bi-clock-history" aria-hidden="true"></i>
                      ประวัติ
                    </button>
                    <RowActionMenu
                      v-if="canManageFinance"
                      :label="`ตัวเลือกของ ${c.student_name}`"
                      :items="creditMenuItems"
                      @select="handleCreditAction(c, $event)"
                    />
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ══════════════════════ แผ่น: เติมเงินล่วงหน้า ══════════════════════ -->
    <AppSheet
      :open="isTopUpOpen && !!topUpTarget"
      label="เติมเงินล่วงหน้า"
      title="เติมเงินล่วงหน้า"
      :description="
        topUpTarget
          ? `${topUpTarget.student_name} · เครดิตปัจจุบัน ${formatMoney(topUpTarget.credit_balance)}`
          : undefined
      "
      size="form"
      :dismissible="!isToppingUp"
      @close="isTopUpOpen = false"
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
          <button type="button" class="btn-ghost-ui" @click="isTopUpOpen = false">ยกเลิก</button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isToppingUp || topUpAmountNumber <= 0"
            @click="handleTopUp"
          >
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            ยืนยันเติม {{ topUpAmountNumber > 0 ? formatMoney(topUpAmountNumber) : '' }}
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ══════════════ แผ่น: ตรวจข้อเสนอการหัก (ระบบเสนอ → ครูยืนยัน) ══════════════ -->
    <AppSheet
      :open="isApplyOpen && !!applyPlan"
      label="ตรวจข้อเสนอการหักเครดิต"
      title="ตรวจข้อเสนอการหักเครดิต"
      description="ระบบจะหักบิลที่ครบกำหนดก่อน — ยังไม่มีอะไรถูกบันทึกจนกว่าจะยืนยัน"
      size="form"
      :dismissible="!isApplying"
      @close="closeApply"
    >
      <div v-if="applyPlan" class="space-y-3">
        <div v-for="item in applyPlan.items" :key="item.student_id" class="rounded-control border border-line p-3">
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
              <p class="num font-bold text-ink">
                −{{ formatMoney(item.total_applied) }}
              </p>
              <p class="text-caption text-ink-3">
                เหลือ {{ formatMoney(item.balance_after) }}
              </p>
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
                <span v-if="a.due_date" class="text-ink-3">
                  ({{ a.due_date }})
                </span>
              </span>
              <span class="num shrink-0 text-right font-bold text-ink">
                {{ formatMoney(a.apply_amount) }}
              </span>
            </li>
          </ul>
        </div>

        <div class="flex items-center justify-between border-t border-line pt-3">
          <span class="text-sm font-bold text-ink-2">รวมที่จะหัก</span>
          <span class="num text-lg font-bold text-ink">
            {{ formatMoney(applyPlan.total_applied) }}
          </span>
        </div>

        <p class="rounded-control bg-canvas p-3 text-caption text-ink-2">
          การหักเครดิต <b>ไม่มีเงินเคลื่อนไหว</b> และ <b>ไม่ออกใบเสร็จใหม่</b> —
          รายได้ของห้องจะถูกนับ <b>ณ จังหวะนี้</b> และหลักฐานคือใบรับเงินล่วงหน้าที่ออกไว้แล้ว
        </p>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="closeApply">ยกเลิก</button>
          <button type="button" class="btn-primary" :disabled="isApplying" @click="handleApply">
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            ยืนยันหักเครดิต
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ══════════════════════ แผ่น: ประวัติเครดิต ══════════════════════ -->
    <AppSheet
      :open="isHistoryOpen && !!historyTarget"
      label="ประวัติเครดิต"
      title="ประวัติเครดิต"
      :description="
        historyTarget
          ? `${historyTarget.student_name} · คงเหลือ ${formatMoney(historyTarget.credit_balance)}`
          : undefined
      "
      size="form"
      @close="isHistoryOpen = false"
    >
      <CreditPanel
        v-if="historyTarget"
        :student="historyTarget"
        :entries="historyEntries"
        :can-manage="canManageFinance"
        :loading="isHistoryLoading"
        @topup="onPanelTopUp"
        @apply="onPanelApply"
        @history="refreshHistory"
        @undo="handleUndo"
      />

      <template #footer>
        <div class="flex justify-end">
          <button type="button" class="btn-ghost-ui" @click="isHistoryOpen = false">ปิด</button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
