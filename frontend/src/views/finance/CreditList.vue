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
import { createLatestGuard } from '@/utils/latest'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import Swal from 'sweetalert2'

import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

const authStore = useAuthStore()
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
    Swal.fire('เกิดข้อผิดพลาด', 'โหลดข้อมูลเงินรับล่วงหน้าไม่สำเร็จ', 'error')
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
    return Swal.fire(
      'ทำรายการไม่ได้',
      error instanceof Error ? error.message : 'สร้างรหัสกันบันทึกซ้ำไม่สำเร็จ',
      'error',
    )
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
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่เติมเงินล่วงหน้าได้', 'error')
  }
  const student = topUpTarget.value
  if (!student) return
  // ⚠️ เช็คซ้ำที่นี่ (ไม่พึ่ง `disabled` ของปุ่ม) — backend ยังบังคับอีกชั้นและตอบ 400
  if (topUpAmountNumber.value <= 0) {
    return Swal.fire('อ๊ะ!', 'กรุณากรอกจำนวนเงินมากกว่า 0 บาท', 'warning')
  }
  if (!topUpAccountId.value) {
    return Swal.fire('ยังไม่เลือกกระเป๋า', 'กรุณาเลือกกระเป๋าเงินที่รับเงินจริงก่อน', 'warning')
  }

  isToppingUp.value = true
  try {
    const res = await FinanceService.topUpCredit(currentRoomId, {
      student_id: student.student_id,
      amount: topUpAmountNumber.value,
      paid_to_account_id: Number(topUpAccountId.value),
      note: topUpNote.value || null,
      user_name: currentUserName,
      idempotency_key: topUpKey.value,
    })

    // 💡 `reused` = true แปลว่ากดซ้ำด้วยคีย์เดิม ⇒ **ไม่ใช่ความผิดพลาด** แต่ต้องบอก
    //    ให้ตรงความจริง ไม่งั้นผู้ใช้จะนึกว่าเงินเข้าอีกรอบ (หรือนึกว่าไม่เข้าเลย)
    const depNo = res.receipt?.receipt_no ?? '—'
    await Swal.fire({
      icon: 'success',
      title: res.reused ? 'รายการนี้ถูกบันทึกไว้แล้ว' : 'เติมเงินล่วงหน้าเรียบร้อย',
      html: res.reused
        ? `ระบบตรวจพบว่าเป็นการกดซ้ำจากรายการเดิม จึง <b>ไม่บันทึกซ้ำ</b><br>` +
          `เครดิตคงเหลือ <b class="num">${formatMoney(res.balance_after)}</b>`
        : `รับเงิน <b class="num">${formatMoney(res.amount)}</b> จาก <b>${res.student_name}</b><br>` +
          `เครดิตคงเหลือ <b class="num">${formatMoney(res.balance_after)}</b><br>` +
          `<span style="font-size:0.85em;color:#78716c">` +
          `ออกใบรับเงินล่วงหน้าเลขที่ <b>${depNo}</b> แล้ว — ` +
          `เงินก้อนนี้จะยัง <b>ไม่นับเป็นรายได้</b> จนกว่าจะถูกหักปิดบิล</span>`,
      confirmButtonColor: '#1d4ed8',
    })

    isTopUpOpen.value = false
    await fetchCredits()
    // ⚠️ ล้างคีย์หลังสำเร็จ ⇒ การเปิดโมดัลครั้งถัดไปคือ "รายการใหม่" จริง ๆ
    topUpKey.value = ''
  } catch (error: unknown) {
    Swal.fire(
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
const selectedIds = ref<number[]>([])
const isApplyOpen = ref(false)
const isPlanLoading = ref(false)
const isApplying = ref(false)
const applyPlan = ref<CreditApplyPlan | null>(null)

/** หักได้เฉพาะคนที่มีเครดิตเหลือ — คนที่เครดิต 0 จะได้ข้อเสนอว่างเปล่า (ไม่มีอะไรให้ทำ) */
const selectableCredits = computed(() => credits.value.filter((c) => c.credit_balance > 0))

const allSelected = computed(
  () =>
    selectableCredits.value.length > 0 &&
    selectedIds.value.length === selectableCredits.value.length,
)

const toggleSelectAll = () => {
  selectedIds.value = allSelected.value ? [] : selectableCredits.value.map((c) => c.student_id)
}

const toggleOne = (studentId: number) => {
  const i = selectedIds.value.indexOf(studentId)
  if (i === -1) selectedIds.value.push(studentId)
  else selectedIds.value.splice(i, 1)
}

/** ยอดเครดิตของคนที่เลือก — ใช้ยืนยันก่อนขอข้อเสนอ */
const selectedBalance = computed(() =>
  roundMoney(
    credits.value
      .filter((c) => selectedIds.value.includes(c.student_id))
      .reduce((s, c) => s + c.credit_balance, 0),
  ),
)

const planGuard = createLatestGuard()

/**
 * ขอ **ข้อเสนอ** การหักแล้วเปิดหน้าตรวจ — ยังไม่เขียนอะไร
 * 🔴 ต้องเรียกตัวนี้เสมอ ห้ามข้ามไป `applyCredit` ตรง ๆ (กติกา "ครูยืนยัน")
 */
const openApplyPreview = async () => {
  if (!canManageFinance.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
  }
  if (selectedIds.value.length === 0) {
    return Swal.fire('อ๊ะ!', 'กรุณาติ๊กเลือกนักเรียนที่ต้องการหักเครดิต', 'warning')
  }

  const token = planGuard.begin()
  isPlanLoading.value = true
  try {
    const plan = await FinanceService.getCreditPlan(currentRoomId, [...selectedIds.value])
    if (!planGuard.isCurrent(token)) return
    // 🛡️ ไม่มีบิลให้หักเลย = ไม่มีอะไรเกิดขึ้น ⇒ บอกให้รู้แทนที่จะเปิดหน้าว่าง ๆ
    if (plan.total_applied <= 0) {
      return Swal.fire(
        'ไม่มีบิลให้หัก',
        'นักเรียนที่เลือกยังไม่มีบิลค้างชำระ (หรือไม่มีเครดิตเหลือ) — จึงไม่มีอะไรต้องทำ',
        'info',
      )
    }
    applyPlan.value = plan
    isApplyOpen.value = true
  } catch (error: unknown) {
    if (!planGuard.isCurrent(token)) return
    Swal.fire(
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
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
  }
  const plan = applyPlan.value
  if (!plan) return

  const confirmed = await Swal.fire({
    title: 'ยืนยันการหักเครดิต?',
    html:
      `จะหักเครดิตของ <b>${plan.items.length}</b> คน ไปปิดบิลรวม ` +
      `<b>${planAllocations.value.length}</b> รายการ<br>` +
      `ยอดที่หักรวม <b class="num">${formatMoney(plan.total_applied)}</b><br><br>` +
      `<span style="font-size:0.85em;color:#78716c">` +
      `การหักเครดิต <b>ไม่มีเงินเคลื่อนไหว</b> (เงินเข้ามาตั้งแต่ตอนเติม) ` +
      `และ <b>ไม่มีการออกใบเสร็จใหม่</b> — หลักฐานคือใบรับเงินล่วงหน้าที่ออกไว้แล้ว<br>` +
      `รายการนี้ยกเลิกได้ภายหลังหากหักผิด</span>`,
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ยืนยันหักเครดิต',
    cancelButtonText: 'ยกเลิก',
  })
  if (!confirmed.isConfirmed) return

  isApplying.value = true
  Swal.fire({
    title: 'กำลังหักเครดิต...',
    allowOutsideClick: false,
    didOpen: () => Swal.showLoading(),
  })
  try {
    const res = await FinanceService.applyCredit(currentRoomId, {
      student_ids: plan.items.map((i) => i.student_id),
      user_name: currentUserName,
    })

    isApplyOpen.value = false
    await Swal.fire({
      icon: 'success',
      title: 'หักเครดิตเรียบร้อย',
      html:
        `หักไป <b class="num">${formatMoney(res.total_applied)}</b> ` +
        `ปิดบิล ${res.bills_paid ?? 0} รายการ<br>` +
        `เครดิตคงเหลือรวม <b class="num">${formatMoney(res.total_balance_after)}</b>`,
      confirmButtonColor: '#1d4ed8',
    })
    selectedIds.value = []
    await fetchCredits()
  } catch (error: unknown) {
    // all-or-nothing: ล้มแล้ว **ไม่มีอะไรถูกหักเลย** — ต้องบอกให้ชัด ไม่งั้นผู้ใช้
    // จะไม่กล้ากดซ้ำเพราะนึกว่าหักไปบางส่วนแล้ว
    Swal.fire(
      'หักเครดิตไม่สำเร็จ',
      (error instanceof Error ? error.message : 'เกิดข้อผิดพลาด') +
        '<br><span style="font-size:0.85em;color:#78716c">ยังไม่มีรายการใดถูกหัก (ยกเลิกทั้งชุด)</span>',
      'error',
    )
  } finally {
    isApplying.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 📜 ประวัติเครดิต + ↩️ ยกเลิกการหัก
// ════════════════════════════════════════════════════════════════════════════
const isHistoryOpen = ref(false)
const historyTarget = ref<StudentCreditBalance | null>(null)
const historyEntries = ref<StudentCreditEntry[]>([])
const isHistoryLoading = ref(false)
const historyGuard = createLatestGuard()

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
    Swal.fire(
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
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ยกเลิกได้', 'error')
  }
  const confirmed = await Swal.fire({
    title: 'ยกเลิกการหักนี้?',
    html:
      `คืนเครดิต <b class="num">${formatMoney(entry.amount)}</b> ` +
      `เข้ากระเป๋านักเรียน และเปิดบิลกลับเป็น "ค้างชำระ"<br>` +
      `<span style="font-size:0.85em;color:#78716c">` +
      `บิล: ${entry.collection_title ?? '—'} · รายการนี้จะยังอยู่ในประวัติ (ไม่ถูกลบ)</span>`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#b91c1c',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ยืนยันยกเลิกการหัก',
    cancelButtonText: 'ไม่ใช่',
  })
  if (!confirmed.isConfirmed) return

  try {
    const res = await FinanceService.undoCreditApplication(currentRoomId, {
      credit_entry_id: entry.id,
      user_name: currentUserName,
    })
    await Swal.fire({
      icon: 'success',
      title: 'ยกเลิกการหักเรียบร้อย',
      html:
        `คืนเครดิต <b class="num">${formatMoney(res.reverted_amount)}</b><br>` +
        `เครดิตคงเหลือ <b class="num">${formatMoney(res.credit_balance_after)}</b>`,
      confirmButtonColor: '#1d4ed8',
    })
    // โหลดใหม่ทั้งสองส่วน — ประวัติเปลี่ยน (แถวเดิมถูกลบ, แถว reverse ถูกเพิ่ม)
    if (historyTarget.value) await openHistory(historyTarget.value)
    await fetchCredits()
  } catch (error: unknown) {
    Swal.fire(
      'ยกเลิกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีอะไรถูกเปลี่ยนแปลง',
      'error',
    )
  }
}

/** ฉลาก/สีของแต่ละประเภทรายการ — ไม่ให้ผู้ใช้ต้องตีความตัวอักษรอังกฤษเอง */
const entryChipClass = (type: string): string => {
  if (type === 'topup') return 'bg-emerald-50 text-emerald-700'
  if (type === 'apply') return 'bg-amber-50 text-amber-700'
  return 'bg-stone-100 text-stone-600'
}

/** 🗓️ วันเวลาไทยแบบสั้น — `created_at` มี timezone มาจาก backend ⇒ Date แปลงให้เอง */
const formatDateTime = (iso: string | null): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('th-TH', {
    timeZone: 'Asia/Bangkok',
    day: 'numeric',
    month: 'short',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  fetchCredits()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Prepaid Credits"
      title="เงินรับล่วงหน้า"
      description="เงินที่ห้องถือไว้ให้เพื่อนแต่ละคน — จะกลายเป็นรายได้ก็ต่อเมื่อถูกหักไปปิดบิล"
    >
      <template #actions>
        <!--
          🔒 ปุ่มเขียน gate ด้วย `canManageFinance` **ไม่ใช่ `isAdmin`** — บทเรียนเดียวกับ
          `DebtorList.vue`: เหรัญญิกที่มี MANAGE_FINANCE แต่ไม่ใช่แอดมินต้องใช้ได้
          ⚠️ ห้าม `:disabled` ตอนยังไม่ติ๊กใคร — ปุ่มตายไม่บอกอะไร ⇒ ปล่อยให้กดได้
             แล้ว handler ตอบเป็นข้อความไทย
        -->
        <button
          v-if="canManageFinance"
          type="button"
          class="btn-ghost-ui"
          :disabled="isPlanLoading"
          @click="openApplyPreview"
        >
          <i class="bi bi-scissors" aria-hidden="true"></i>
          หักเครดิตที่เลือก<span v-if="selectedIds.length">({{ selectedIds.length }})</span>
        </button>
        <RouterLink to="/finance/debtors" class="btn-ghost-ui" title="ดูยอดค้างชำระ">
          <i class="bi bi-people" aria-hidden="true"></i>
          ยอดค้างชำระ
        </RouterLink>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
      </template>
    </PageHeader>

    <!-- 📊 สรุปภาพรวม — ตัวเลขหลักคือ "เงินที่ถือไว้" ซึ่ง **ไม่ใช่รายได้** -->
    <div v-if="!isLoading && !hasError" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="page-card p-4">
        <p class="text-[11px] font-bold text-stone-500">เงินที่ห้องถือไว้ให้ทุกคน</p>
        <p class="font-display num mt-1 text-2xl font-bold text-stone-900">
          {{ formatMoney(totalHeld) }}
        </p>
        <p class="mt-1 text-[11px] text-stone-500">
          ยังไม่นับเป็นรายได้ — จะนับก็ต่อเมื่อหักปิดบิลแล้ว
        </p>
      </div>
      <div class="page-card p-4">
        <p class="text-[11px] font-bold text-stone-500">จำนวนคนที่มีเครดิตคงเหลือ</p>
        <p class="font-display num mt-1 text-2xl font-bold text-stone-900">
          {{ holdersCount }} <span class="text-base font-bold text-stone-400">คน</span>
        </p>
        <p class="mt-1 text-[11px] text-stone-500">จากทั้งหมด {{ credits.length }} คนในห้อง</p>
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
      <!--
        📊 แถบสรุปสิ่งที่ติ๊กไว้ — โผล่เฉพาะเมื่อมีของ
        💡 มีไว้เพราะปุ่ม "หักเครดิต" อยู่ที่หัวหน้าจอ (ไกลจากรายการ) ⇒ ถ้าไม่สรุปไว้ตรงนี้
           ผู้ใช้ที่เลื่อนลงมาติ๊กจะไม่เห็นว่าเลือกไปเท่าไรแล้ว
      -->
      <div
        v-if="canManageFinance && selectedIds.length > 0"
        class="page-card flex flex-wrap items-center justify-between gap-3 border-s-4 border-s-brand-700 p-3"
      >
        <p class="min-w-0 text-sm font-bold text-stone-700">
          เลือกไว้ <span class="num">{{ selectedIds.length }}</span> คน ·
          เครดิตที่เลือก <span class="num text-emerald-600">{{ formatMoney(selectedBalance) }}</span>
        </p>
        <div class="flex shrink-0 gap-2">
          <button type="button" class="btn-ghost-ui" @click="selectedIds = []">ล้างที่เลือก</button>
          <button type="button" class="btn-primary" @click="openApplyPreview">
            <i class="bi bi-scissors" aria-hidden="true"></i>
            ดูข้อเสนอการหัก
          </button>
        </div>
      </div>

      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="c in credits"
          :key="c.student_id"
          class="page-card p-4"
          :class="c.credit_balance > 0 ? 'border-s-4 border-s-emerald-500' : ''"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-2">
              <label
                v-if="canManageFinance && c.credit_balance > 0"
                class="flex shrink-0 cursor-pointer items-center"
              >
                <input
                  type="checkbox"
                  class="peer sr-only"
                  :checked="selectedIds.includes(c.student_id)"
                  :aria-label="`เลือก ${c.student_name} เพื่อหักเครดิต`"
                  @change="toggleOne(c.student_id)"
                />
                <span
                  class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                  :class="
                    selectedIds.includes(c.student_id)
                      ? 'border-brand-700 bg-brand-700'
                      : 'border-stone-300 bg-white'
                  "
                >
                  <i
                    v-if="selectedIds.includes(c.student_id)"
                    class="bi bi-check-lg text-sm font-bold text-white"
                    aria-hidden="true"
                  ></i>
                </span>
              </label>
              <span class="chip num shrink-0 bg-stone-100 text-stone-500">#{{ c.student_no }}</span>
              <h2 class="font-display min-w-0 truncate text-base font-bold text-stone-900">
                {{ c.student_name }}
              </h2>
            </div>

            <div class="shrink-0 text-right">
              <p class="text-[11px] font-bold text-stone-500">เครดิตคงเหลือ</p>
              <p
                class="font-display num mt-0.5 whitespace-nowrap text-lg font-bold"
                :class="c.credit_balance > 0 ? 'text-emerald-600' : 'text-stone-300'"
              >
                {{ formatMoney(c.credit_balance) }}
              </p>
            </div>
          </div>

          <div class="mt-2.5 flex flex-wrap items-center gap-2 border-t border-stone-100 pt-2.5">
            <span class="chip shrink-0 bg-stone-100 text-stone-600">
              ค้าง {{ formatMoney(c.total_pending_amount) }}
            </span>
            <span
              class="chip shrink-0"
              :class="c.net_pending_amount > 0 ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'"
            >
              ต้องเก็บจริง {{ formatMoney(c.net_pending_amount) }}
            </span>
          </div>

          <div v-if="canManageFinance" class="mt-2.5 flex flex-wrap gap-2">
            <button type="button" class="btn-ghost-ui" @click="openTopUp(c)">
              <i class="bi bi-plus-circle" aria-hidden="true"></i>
              เติมเงินล่วงหน้า
            </button>
            <button type="button" class="btn-ghost-ui" @click="openHistory(c)">
              <i class="bi bi-clock-history" aria-hidden="true"></i>
              ประวัติ
            </button>
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
                <th v-if="canManageFinance" class="w-10">
                  <label class="flex cursor-pointer items-center" title="เลือกทั้งหมดที่มีเครดิต">
                    <input
                      type="checkbox"
                      class="peer sr-only"
                      :checked="allSelected"
                      aria-label="เลือกนักเรียนทั้งหมดที่มีเครดิต"
                      @change="toggleSelectAll"
                    />
                    <span
                      class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                      :class="
                        allSelected ? 'border-brand-700 bg-brand-700' : 'border-stone-300 bg-white'
                      "
                    >
                      <i
                        v-if="allSelected"
                        class="bi bi-check-lg text-xs font-bold text-white"
                        aria-hidden="true"
                      ></i>
                    </span>
                  </label>
                </th>
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
                <td v-if="canManageFinance">
                  <label v-if="c.credit_balance > 0" class="flex cursor-pointer items-center">
                    <input
                      type="checkbox"
                      class="peer sr-only"
                      :checked="selectedIds.includes(c.student_id)"
                      :aria-label="`เลือก ${c.student_name} เพื่อหักเครดิต`"
                      @change="toggleOne(c.student_id)"
                    />
                    <span
                      class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                      :class="
                        selectedIds.includes(c.student_id)
                          ? 'border-brand-700 bg-brand-700'
                          : 'border-stone-300 bg-white'
                      "
                    >
                      <i
                        v-if="selectedIds.includes(c.student_id)"
                        class="bi bi-check-lg text-xs font-bold text-white"
                        aria-hidden="true"
                      ></i>
                    </span>
                  </label>
                </td>
                <td class="num font-bold text-stone-400">#{{ c.student_no }}</td>
                <td class="font-bold text-stone-900">{{ c.student_name }}</td>
                <td
                  class="font-display num whitespace-nowrap text-right font-bold"
                  :class="c.credit_balance > 0 ? 'text-emerald-600' : 'text-stone-300'"
                >
                  {{ formatMoney(c.credit_balance) }}
                </td>
                <td class="num whitespace-nowrap text-right text-stone-500">
                  {{ formatMoney(c.total_pending_amount) }}
                </td>
                <td
                  class="num whitespace-nowrap text-right font-bold"
                  :class="c.net_pending_amount > 0 ? 'text-red-600' : 'text-emerald-600'"
                >
                  {{ formatMoney(c.net_pending_amount) }}
                </td>
                <td>
                  <div class="flex justify-end gap-2">
                    <button
                      v-if="canManageFinance"
                      type="button"
                      class="btn-ghost-ui"
                      @click="openTopUp(c)"
                    >
                      <i class="bi bi-plus-circle" aria-hidden="true"></i>
                      เติม
                    </button>
                    <button type="button" class="btn-ghost-ui" @click="openHistory(c)">
                      <i class="bi bi-clock-history" aria-hidden="true"></i>
                      ประวัติ
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ══════════════════════ โมดัล: เติมเงินล่วงหน้า ══════════════════════ -->
    <div
      v-if="isTopUpOpen && topUpTarget"
      class="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
      @click.self="isTopUpOpen = false"
    >
      <div
        class="page-card max-h-[90vh] w-full overflow-y-auto overscroll-contain rounded-t-3xl p-4 md:max-h-[85vh] md:max-w-lg md:rounded-2xl md:p-6"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="eyebrow">Prepaid Top-up</p>
            <h2 class="page-title truncate">เติมเงินล่วงหน้า</h2>
            <!-- ⚠️ ห้ามใส่ `truncate` ที่บรรทัดนี้ — ที่ 375px มันตัด **ตัวเลขเงิน** กลางคัน
                 ("เครดิตปัจจุบัน ฿1,50…") ซึ่งอ่านผิดความหมายได้ (ดูเหมือน ฿1,50 ไม่ใช่ ฿1,500.00)
                 ⇒ ให้ตัดบรรทัดแทน · ตัว `<h2>` ข้างบนยัง `truncate` ได้เพราะเป็นข้อความคงที่ -->
            <p class="page-lede">
              {{ topUpTarget.student_name }} · เครดิตปัจจุบัน
              {{ formatMoney(topUpTarget.credit_balance) }}
            </p>
          </div>
          <button
            type="button"
            class="btn-ghost-ui shrink-0"
            aria-label="ปิด"
            @click="isTopUpOpen = false"
          >
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="mt-4 space-y-3">
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
          <p class="rounded-xl bg-stone-50 p-3 text-[11px] text-stone-600">
            เงินก้อนนี้จะถูกเก็บเป็น <b>เครดิตคงเหลือ</b> ของนักเรียน และยัง
            <b>ไม่นับเป็นรายได้</b> ของห้อง — ระบบจะออก
            <b>ใบรับเงินล่วงหน้า (DEP)</b> ให้เป็นหลักฐานทันที
          </p>
        </div>

        <div class="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
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
      </div>
    </div>

    <!-- ══════════════ โมดัล: ตรวจข้อเสนอการหัก (ระบบเสนอ → ครูยืนยัน) ══════════════ -->
    <div
      v-if="isApplyOpen && applyPlan"
      class="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
      @click.self="isApplyOpen = false"
    >
      <div
        class="page-card max-h-[90vh] w-full overflow-y-auto overscroll-contain rounded-t-3xl p-4 md:max-h-[85vh] md:max-w-2xl md:rounded-2xl md:p-6"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="eyebrow">Review Before Apply</p>
            <h2 class="page-title truncate">ตรวจข้อเสนอการหักเครดิต</h2>
            <p class="page-lede">
              ระบบจะหักบิลที่ <b>ครบกำหนดก่อน</b> ก่อน — ยังไม่มีอะไรถูกบันทึกจนกว่าจะยืนยัน
            </p>
          </div>
          <button
            type="button"
            class="btn-ghost-ui shrink-0"
            aria-label="ปิด"
            @click="isApplyOpen = false"
          >
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="mt-4 space-y-3">
          <div v-for="item in applyPlan.items" :key="item.student_id" class="page-card p-3">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="font-display truncate font-bold text-stone-900">
                  {{ item.student_name ?? `#${item.student_id}` }}
                </p>
                <p class="text-[11px] text-stone-500">
                  เครดิตก่อนหัก {{ formatMoney(item.balance_before) }}
                </p>
              </div>
              <div class="shrink-0 text-right">
                <p class="num font-display font-bold text-stone-900">
                  −{{ formatMoney(item.total_applied) }}
                </p>
                <p class="text-[11px] text-stone-500">
                  เหลือ {{ formatMoney(item.balance_after) }}
                </p>
              </div>
            </div>

            <p v-if="!item.allocations.length" class="mt-2 text-[11px] text-stone-500">
              ไม่มีบิลให้หัก — เครดิตคงอยู่เต็มจำนวน
            </p>

            <ul v-else class="mt-2 space-y-1.5 border-t border-stone-100 pt-2">
              <li
                v-for="a in item.allocations"
                :key="a.payment_id"
                class="flex items-start justify-between gap-3 text-[12px]"
              >
                <span class="min-w-0 truncate text-stone-600">
                  {{ a.title ?? 'รายการชำระเงิน' }}
                  <span v-if="a.due_date" class="text-stone-400">
                    ({{ a.due_date }})
                  </span>
                </span>
                <span class="num shrink-0 text-right font-bold text-stone-800">
                  {{ formatMoney(a.apply_amount) }}
                </span>
              </li>
            </ul>
          </div>
        </div>

        <div class="mt-4 flex items-center justify-between border-t border-stone-200 pt-3">
          <span class="text-sm font-bold text-stone-600">รวมที่จะหัก</span>
          <span class="num font-display text-lg font-bold text-stone-900">
            {{ formatMoney(applyPlan.total_applied) }}
          </span>
        </div>

        <p class="mt-3 rounded-xl bg-stone-50 p-3 text-[11px] text-stone-600">
          การหักเครดิต <b>ไม่มีเงินเคลื่อนไหว</b> และ <b>ไม่ออกใบเสร็จใหม่</b> —
          รายได้ของห้องจะถูกนับ <b>ณ จังหวะนี้</b> และหลักฐานคือใบรับเงินล่วงหน้าที่ออกไว้แล้ว
        </p>

        <div class="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isApplyOpen = false">ยกเลิก</button>
          <button type="button" class="btn-primary" :disabled="isApplying" @click="handleApply">
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            ยืนยันหักเครดิต
          </button>
        </div>
      </div>
    </div>

    <!-- ══════════════════════ โมดัล: ประวัติเครดิต ══════════════════════ -->
    <div
      v-if="isHistoryOpen && historyTarget"
      class="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
      @click.self="isHistoryOpen = false"
    >
      <div
        class="page-card max-h-[90vh] w-full overflow-y-auto overscroll-contain rounded-t-3xl p-4 md:max-h-[85vh] md:max-w-2xl md:rounded-2xl md:p-6"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="eyebrow">Credit Ledger</p>
            <h2 class="page-title truncate">ประวัติเครดิต</h2>
            <p class="page-lede truncate">
              {{ historyTarget.student_name }} · คงเหลือ
              {{ formatMoney(historyTarget.credit_balance) }}
            </p>
          </div>
          <button
            type="button"
            class="btn-ghost-ui shrink-0"
            aria-label="ปิด"
            @click="isHistoryOpen = false"
          >
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>

        <SkeletonRows v-if="isHistoryLoading" :rows="3" height="h-16" />

        <StateBlock
          v-else-if="!historyEntries.length"
          variant="empty"
          icon="bi-journal"
          title="ยังไม่มีรายการเครดิต"
          hint="เมื่อมีการเติมเงินล่วงหน้าหรือหักปิดบิล รายการจะปรากฏที่นี่"
        />

        <ul v-else class="mt-4 space-y-2">
          <li v-for="e in historyEntries" :key="e.id" class="page-card p-3">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="chip shrink-0" :class="entryChipClass(e.entry_type)">
                    {{ e.entry_type_label ?? e.entry_type }}
                  </span>
                  <span class="text-[11px] text-stone-400">{{ formatDateTime(e.created_at) }}</span>
                </div>
                <p class="mt-1 min-w-0 truncate text-[12px] text-stone-600">
                  <template v-if="e.collection_title">{{ e.collection_title }}</template>
                  <template v-else-if="e.receipt_no">ใบรับเงินล่วงหน้า {{ e.receipt_no }}</template>
                  <template v-else>{{ e.note ?? '—' }}</template>
                </p>
                <p v-if="e.recorded_by" class="mt-0.5 text-[11px] text-stone-400">
                  โดย {{ e.recorded_by }}
                </p>
              </div>
              <div class="shrink-0 text-right">
                <p class="num font-display font-bold text-stone-900">
                  {{ formatMoney(e.amount) }}
                </p>
                <p class="text-[11px] text-stone-500">
                  คงเหลือ {{ formatMoney(e.balance_after) }}
                </p>
                <button
                  v-if="canManageFinance && e.entry_type === 'apply'"
                  type="button"
                  class="btn-ghost-ui mt-1.5"
                  @click="handleUndo(e)"
                >
                  <i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
                  ยกเลิกการหักนี้
                </button>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>
