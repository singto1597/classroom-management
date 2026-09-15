<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { Debtor, Account, StudentDebtItem, InvoiceBatchIssueResult } from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { downloadBlob, combinedPdfFilename } from '@/utils/download'
import Swal from 'sweetalert2'

import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

const router = useRouter()
const authStore = useAuthStore()
const currentServerId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

const debtors = ref<Debtor[]>([])
const accounts = ref<Account[]>([])
const isLoading = ref(true)

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false)

// Modal/Batch Pay State
const isModalOpen = ref(false)
const selectedStudent = ref<{ id: number; name: string } | null>(null)
const studentDebts = ref<StudentDebtItem[]>([])
const isLoadingDebts = ref(false)
const selectedPaymentIds = ref<number[]>([])
const payAmounts = ref<Record<number, number>>({})
const paidToAccountId = ref<string>('')
const slipImageUrl = ref('')

/**
 * 🧾 [F5] ออกใบเสร็จให้ทุกรายการที่เคลียร์ในรอบนี้ — **default ติ๊ก** ตามคำขอผู้ใช้
 *
 * 🔄 รีเซ็ตกลับเป็น "ติ๊ก" ทุกครั้งที่เปิดโมดัล (ใน `handleClearDebt`) โดยเจตนา:
 *    การค้างเป็น "ไม่ติ๊ก" ข้ามคนจะทำให้ใบเสร็จหายเงียบ ๆ ซึ่งเป็นความผิดพลาดที่
 *    ผู้ปกครองรู้ตัวช้ากว่าทุกฝ่าย (มาเอาทีหลังแล้วครูต้องออกย้อนหลังทีละใบ)
 *    ⇒ ค่าเริ่มต้นต้องเป็น "ออก" เสมอ และคนที่ไม่ต้องการต้องปิดเองทุกครั้ง
 */
const issueReceipts = ref(true)

// Memory logic
const lastSelectedMemory = ref<number[] | null>(null)

// 🔢 ตัวโหลดอิสระ 2 ตัว ⇒ ต้องมี guard คนละตัว (ใช้ร่วมกันแล้ว begin() ของตัวหนึ่ง
//    จะฆ่า token ของอีกตัว → isLoading ค้าง) — ดู utils/latest.ts
const listGuard = createLatestGuard()
const debtGuard = createLatestGuard()

const fetchDebtors = async () => {
  const token = listGuard.begin()

  isLoading.value = true
  hasError.value = false
  try {
    const [debtRes, accRes] = await Promise.all([
      FinanceService.getAllDebtors(currentServerId),
      FinanceService.getAccounts(currentServerId),
    ])
    if (!listGuard.isCurrent(token)) return
    debtors.value = debtRes
    accounts.value = accRes

    // 🧹 ตัดคนที่หลุดจากรายการทิ้งจากที่ติ๊กไว้ — เกิดได้จริง: ระหว่างที่ติ๊กอยู่ นักเรียน
    //    คนหนึ่งจ่ายครบ (จากเครื่องอื่น) แล้วหายจาก `getAllDebtors` ⇒ ถ้าไม่กรอง รายชื่อ
    //    ที่ส่งไปออกใบแจ้งหนี้จะมี id ที่ backend ไม่รู้จัก ⇒ 404 ทั้งชุด (all-or-nothing)
    //    ทั้งที่ผู้ใช้แค่กด "ออกใบแจ้งหนี้ที่เลือก" ตามปกติ
    const stillListed = new Set(debtors.value.map((d) => d.student_id))
    selectedStudentIds.value = selectedStudentIds.value.filter((id) => stillListed.has(id))

    // Auto-select first account
    if (accounts.value.length > 0) {
      paidToAccountId.value = accounts.value[0]?.id.toString() || ''
    }
  } catch {
    // คำขอเก่าที่ล้มไม่ควรขึ้นจอ ถ้าคำขอใหม่กว่าไปถึงแล้ว
    if (!listGuard.isCurrent(token)) return
    hasError.value = true
    Swal.fire('เกิดข้อผิดพลาด', 'โหลดข้อมูลลูกหนี้ไม่สำเร็จ', 'error')
  } finally {
    if (listGuard.isCurrent(token)) isLoading.value = false
  }
}

const handleClearDebt = async (debtor: Debtor) => {
  // ดักฝั่ง Script: ป้องกันคนกดเรียกฟังก์ชันข้าม UI
  if (!isAdmin.value) {
    Swal.fire('ไม่มีสิทธิ์เข้าถึง', 'เฉพาะแอดมินเท่านั้นที่สามารถเคลียร์หนี้ได้', 'error')
    return
  }

  selectedStudent.value = { id: debtor.student_id, name: debtor.student_name }
  isModalOpen.value = true
  isLoadingDebts.value = true
  selectedPaymentIds.value = []
  payAmounts.value = {}
  slipImageUrl.value = ''
  issueReceipts.value = true

  // 🔢 คำขอ "หนี้ของนักเรียนคนนี้" ต้องมี guard เพราะผลลัพธ์มันไป **เขียนทับทั้งชุด**
  //    ทั้ง studentDebts และ selectedPaymentIds — ถ้าคำตอบของนักเรียนคนก่อนมาถึงทีหลัง
  //    หัวโมดัลจะบอกชื่อนักเรียน B แต่รายการที่ติ๊กไว้เป็นบิลของนักเรียน A
  //    🔴 อันตรายกว่าเคสอื่นตรงที่ handleBatchPay ส่งแค่ payment_ids (ไม่มี student_id)
  //       ⇒ backend ตรวจไม่ได้เลยว่าปนคน และเงินจะถูกบันทึกเข้าผิดคน
  const token = debtGuard.begin()

  try {
    const res = await FinanceService.getStudentDebts(currentServerId, debtor.student_id)
    if (!debtGuard.isCurrent(token)) return
    studentDebts.value = res.debts

    // Logic: Auto-Select ฉลาดจำค่าเดิม
    studentDebts.value.forEach((debt) => {
      let shouldCheck = false
      if (lastSelectedMemory.value === null) {
        shouldCheck = true
      } else {
        shouldCheck = lastSelectedMemory.value.includes(debt.collection_id)
      }

      if (shouldCheck) {
        selectedPaymentIds.value.push(debt.payment_id)
      }
      payAmounts.value[debt.payment_id] = debt.amount
    })
  } catch {
    // ⚠️ ห้ามปิดโมดัลทิ้งถ้าเป็นคำขอเก่า — ผู้ใช้อาจเปิดโมดัลของคนใหม่ไปแล้ว
    if (!debtGuard.isCurrent(token)) return
    Swal.fire('เกิดข้อผิดพลาด', 'ดึงรายการค้างชำระไม่สำเร็จ', 'error')
    isModalOpen.value = false
  } finally {
    if (debtGuard.isCurrent(token)) isLoadingDebts.value = false
  }
}

const totalSelectedAmount = computed(() => {
  return selectedPaymentIds.value.reduce((total, id) => {
    return total + (payAmounts.value[id] || 0)
  }, 0)
})

// ==========================================
// 🧾 ออกใบแจ้งหนี้ (F3)
// ==========================================
//
// 🔄 เปลี่ยนแกน (ก.ย. 2026): **ติ๊ก "คน" ไม่ใช่ "บิล"**
//    ยอดบนใบแจ้งหนี้คือ "ยอดค้างรวมทุกบิลที่ยัง pending ของคนนั้น" ⇒ การให้ผู้ใช้เลือกบิล
//    เป็นการถามคำถามที่ระบบไม่สนใจคำตอบ (ติ๊ก 2 จาก 3 บิล ก็ยังได้ยอดรวมเท่าเดิม)
//    ⇒ ช่องติ๊กย้ายออกจากโมดัลรับเงิน (ที่นั่นคือ "บิลที่จะรับเงิน") มาอยู่ที่แถวรายชื่อ
//
// 🔒 ใช้ `canManageFinance` (ไม่ใช่ `isAdmin`) ตามกฎเดียวกับปุ่มเขียนของ F2/F3
//    ⇒ ตรงกับ `require_permission(..., "MANAGE_FINANCE")` ฝั่ง backend
//    ✅ นี่คือเหตุผลที่ปุ่ม **ต้อง** ย้ายออกจากโมดัล: โมดัลถูก gate ด้วย `isAdmin` มาแต่เดิม
//       (ของเก่า ไม่ได้แตะในรอบนี้) ⇒ ถ้าปุ่มยังอยู่ในนั้น เหรัญญิกที่ได้สิทธิ์
//       จะออกใบแจ้งหนี้ไม่ได้เลยทั้งที่มี MANAGE_FINANCE
//
// ⚠️ ยอดที่โชว์ใน confirm ต้องมาจาก `total_pending_amount` ของนักเรียนที่เลือก
//    (ค่าที่หน้าจอโชว์อยู่) ห้ามใช้ `totalSelectedAmount` ซึ่งคือ "ยอดที่จะรับเงิน"
//    จากช่องกรอกในโมดัล — คนละความหมายกันโดยสิ้นเชิง
//
// 📌 เอกสารที่ได้เป็น **1 ใบต่อ 1 คน** โดยมีตารางแจกแจงรายโครงการอยู่ข้างใน
//    ⇒ "นักเรียนคนนี้ค้างเท่าไร" ตอบได้ด้วยกระดาษแผ่นเดียว

const canManageFinance = computed(() => authStore.canManageFinance)

/** 🧾 นักเรียนที่ติ๊กไว้ที่แถวรายชื่อ — คนละชุดกับ `selectedPaymentIds` ของโมดัลรับเงิน */
const selectedStudentIds = ref<number[]>([])

/** ยอดที่ใบแจ้งหนี้จะเรียกเก็บ = ยอดค้างรวมของนักเรียนที่เลือก (ตรงกับที่หน้าจอโชว์) */
const selectedInvoiceAmount = computed(() =>
  debtors.value
    .filter((d) => selectedStudentIds.value.includes(d.student_id))
    .reduce((sum, d) => sum + d.total_pending_amount, 0),
)

/** ยอดค้างรวมทั้งห้อง — ใช้ยืนยันก่อนออกใบแจ้งหนี้ทั้งห้อง */
const totalOutstanding = computed(() =>
  debtors.value.reduce((sum, d) => sum + d.total_pending_amount, 0),
)

const allSelected = computed(
  () => debtors.value.length > 0 && selectedStudentIds.value.length === debtors.value.length,
)

const toggleSelectAll = () => {
  selectedStudentIds.value = allSelected.value ? [] : debtors.value.map((d) => d.student_id)
}

/**
 * 🚧 เพดานเดียวกับ backend (`ReceiptInvoiceIssueRequest.student_ids` และ batch ของใบเสร็จ)
 *    ⇒ เช็คที่นี่เพื่อไม่ให้ผู้ใช้เสียรอบเปล่า แต่ backend ยังบังคับซ้ำ (ไม่พึ่ง UI)
 */
const ISSUE_PER_REQUEST_MAX = 100

/**
 * 🚧 เพดานของ **PDF รวม** (`RECEIPTS_PER_PDF_MAX` ฝั่ง backend) — คนละตัวกับข้างบน
 *    backend ตอบ 400 พร้อมข้อความไทยที่บอกให้แบ่งรอบ ⇒ เช็คก่อนยิงเพื่อไม่ให้เสียเวลา
 */
const COMBINED_PDF_MAX = 100

/** คำเตือนที่ต้องมีทุกครั้งก่อนออกใบแจ้งหนี้ — พฤติกรรมนี้ต่างจากใบเสร็จโดยสิ้นเชิง */
const POINT_IN_TIME_HINT =
  '<span style="font-size:0.85em;color:#78716c">' +
  'ใบแจ้งหนี้เป็นเอกสาร <b>ณ จุดเวลา</b> — ยอดค้างเปลี่ยนเมื่อนักเรียนจ่ายเพิ่ม ' +
  'การออกซ้ำจึงได้ <b>เลขใหม่ทุกครั้ง</b> (ต่างจากใบเสร็จที่ได้เลขเดิม)' +
  '</span>'

const isIssuingInvoices = ref(false)
const isDownloadingCombined = ref(false)

/** 🖨️ ดาวน์โหลดหลายใบเป็น PDF ไฟล์เดียว (หน้าละใบ) — ทางเดียวที่เรียก `downloadBlob` ที่นี่ */
const downloadCombined = async (kind: 'receipts' | 'invoices', nos: string[]) => {
  if (isDownloadingCombined.value || nos.length === 0) return
  if (nos.length > COMBINED_PDF_MAX) {
    return Swal.fire(
      'รวมไฟล์ไม่ได้ในครั้งเดียว',
      `เลือกไว้ ${nos.length} ฉบับ แต่รวมได้ครั้งละไม่เกิน ${COMBINED_PDF_MAX} ฉบับ ` +
        '— กรุณาแบ่งดาวน์โหลดเป็นรอบ',
      'warning',
    )
  }
  isDownloadingCombined.value = true
  Swal.fire({ title: 'กำลังสร้างไฟล์ PDF...', allowOutsideClick: false, didOpen: () => Swal.showLoading() })
  try {
    const blob = await FinanceService.downloadCombinedPdf(currentServerId, nos)
    downloadBlob(blob, combinedPdfFilename(nos, kind))
    Swal.close()
  } catch (error: unknown) {
    // 502 = Gotenberg ต่อไม่ได้/เรนเดอร์ไม่ผ่าน — service แปลงเป็นข้อความไทยให้แล้ว
    Swal.fire(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    isDownloadingCombined.value = false
  }
}

/**
 * ทางเดียวที่ยิง API ออกใบแจ้งหนี้ของทั้งสองปุ่ม — สิ่งที่ต่างกันมีแค่ "จะออกให้ใคร"
 *
 * 🔴 ทั้งสองเส้นทางเป็น **การเขียนจริง**: ใบแจ้งหนี้เป็น point-in-time ⇒ กดซ้ำได้เลขใหม่
 *    ทุกครั้ง (กินเลข INV จริง) ⇒ ต้องมี confirm เสมอ ไม่มีปุ่มไหนยิงตรง
 */
const runInvoiceIssue = async (
  action: () => Promise<InvoiceBatchIssueResult>,
  description: string,
  title: string,
) => {
  const confirmed = await Swal.fire({
    title,
    html: `${description}<br><br>${POINT_IN_TIME_HINT}`,
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ออกใบแจ้งหนี้',
    cancelButtonText: 'ยกเลิก',
  })
  if (!confirmed.isConfirmed) return

  isIssuingInvoices.value = true
  Swal.fire({
    title: 'กำลังออกใบแจ้งหนี้...',
    allowOutsideClick: false,
    didOpen: () => Swal.showLoading(),
  })
  try {
    const res = await action()
    const nos = res.receipts.map((r) => r.receipt_no)
    const canDownload = nos.length > 0 && nos.length <= COMBINED_PDF_MAX
    // 📋 ข้อความต้องรายงาน **คนที่ถูกข้าม** ด้วย ไม่งั้นผู้ใช้ที่เห็น "ออก 38 ฉบับ"
    //    ทั้งที่มี 40 คน จะไม่รู้เลยว่าอีก 2 คนเป็นใครและเพราะอะไร (backend ส่ง `skipped` มาให้)
    const skippedNote = res.skipped.length
      ? `<br><span style="font-size:0.85em;color:#a16207">ข้าม ${res.skipped.length} คน ` +
        `ที่มียอดค้างน้อยกว่า 0.01 บาท: ${res.skipped
          .map((s) => s.student_name || `#${s.student_no ?? s.student_id}`)
          .join(', ')}</span>`
      : ''

    const after = await Swal.fire({
      icon: 'success',
      title: 'ออกใบแจ้งหนี้เรียบร้อย',
      html:
        `ออกใหม่ <b>${res.issued_count}</b> ฉบับ (1 คน = 1 ใบ)<br>` +
        `เลขที่ล่าสุด <b class="num">${nos[nos.length - 1] ?? '—'}</b>` +
        skippedNote +
        (canDownload
          ? `<br><br><span style="font-size:0.85em;color:#78716c">รวมเป็นไฟล์เดียวได้ ` +
            `(${nos.length} หน้า — หน้าละคน) เหมาะสำหรับพิมพ์แจก</span>`
          : ''),
      showCancelButton: canDownload,
      confirmButtonText: 'ดาวน์โหลด PDF รวม',
      cancelButtonText: 'ปิด',
      confirmButtonColor: '#1d4ed8',
      cancelButtonColor: '#78716c',
    })
    if (canDownload && after.isConfirmed) await downloadCombined('invoices', nos)
    selectedStudentIds.value = []
  } catch (error: unknown) {
    Swal.fire(
      'ออกใบแจ้งหนี้ไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีเอกสารใดถูกออก (ยกเลิกทั้งชุด)',
      'error',
    )
  } finally {
    isIssuingInvoices.value = false
  }
}

/** ออกใบแจ้งหนี้ให้ **นักเรียนที่ติ๊กไว้** (1 คน = 1 ใบ — ยอดค้างรวมของคนนั้น) */
const handleIssueSelectedInvoices = () => {
  if (!canManageFinance.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกเอกสารได้', 'error')
  }
  if (selectedStudentIds.value.length === 0) {
    return Swal.fire('อ๊ะ!', 'กรุณาติ๊กเลือกนักเรียนที่ต้องการออกใบแจ้งหนี้', 'warning')
  }
  if (selectedStudentIds.value.length > ISSUE_PER_REQUEST_MAX) {
    return Swal.fire(
      'เลือกไว้มากเกินไป',
      `เลือก ${selectedStudentIds.value.length} คน แต่ระบบออกได้ครั้งละไม่เกิน ` +
        `${ISSUE_PER_REQUEST_MAX} ใบ`,
      'warning',
    )
  }
  return runInvoiceIssue(
    () =>
      FinanceService.issueInvoices(currentServerId, {
        student_ids: [...selectedStudentIds.value],
        user_name: currentUserName,
      }),
    `จะออกใบแจ้งหนี้ <b>${selectedStudentIds.value.length}</b> ฉบับ (1 คน = 1 ใบ)<br>` +
      `ยอดค้างชำระรวมที่จะเรียกเก็บ <b>${formatNumber(selectedInvoiceAmount.value)}</b> บาท`,
    'ออกใบแจ้งหนี้ที่เลือก?',
  )
}

/**
 * ออกใบแจ้งหนี้ให้ **ทุกคนที่มียอดค้างในห้อง** — ระบบเป็นคนหาว่าใครค้าง
 *
 * ⚠️ จำนวนคนในข้อความมาจากรายการที่โหลดไว้ **ไม่ใช่ยอดสด** — ระหว่างที่เปิดหน้าอยู่
 *    อาจมีคนจ่ายครบไปแล้ว ⇒ backend จะ "ข้าม" คนนั้นและรายงานกลับมาใน `skipped`
 *    (ข้อความใน confirm จึงต้องเขียนว่า "ขณะนี้" ไม่ใช่รับประกันตัวเลข)
 */
const handleIssueRoomInvoices = () => {
  if (!canManageFinance.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกเอกสารได้', 'error')
  }
  if (!debtors.value.length) {
    return Swal.fire('ไม่มีใครค้างชำระ', 'ห้องนี้ไม่มีนักเรียนที่มียอดค้างชำระในขณะนี้', 'info')
  }
  return runInvoiceIssue(
    () => FinanceService.issueRoomInvoices(currentServerId, { user_name: currentUserName }),
    `จะออกใบแจ้งหนี้ให้ <b>${debtors.value.length}</b> คนที่มียอดค้างชำระ <b>ขณะนี้</b> ` +
      `(1 คน = 1 ใบ)<br>ยอดค้างชำระรวมทั้งห้อง ` +
      `<b>${formatNumber(totalOutstanding.value)}</b> บาท`,
    'ออกใบแจ้งหนี้ทั้งห้อง?',
  )
}

const handleBatchPay = async () => {
  // ดักอีกชั้นตอนกดยืนยันจ่ายเงิน
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error')
  }

  if (selectedPaymentIds.value.length === 0) {
    return Swal.fire('อ๊ะ!', 'กรุณาเลือกรายการที่ต้องการชำระเงิน', 'warning')
  }

  // ✅ กันเผลอกดยืนยันตอนไม่มีกระเป๋าเงินเป้าหมาย
  if (!paidToAccountId.value) {
    return Swal.fire('ยังไม่เลือกบัญชี', 'กรุณาเลือกกระเป๋าเงินที่รับเงินก่อน', 'warning')
  }

  // จดจำการตั้งค่าก่อนกดยืนยัน
  lastSelectedMemory.value = studentDebts.value
    .filter((d) => selectedPaymentIds.value.includes(d.payment_id))
    .map((d) => d.collection_id)

  try {
    Swal.fire({
      title: 'กำลังบันทึก...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading(),
    })

    // ✨ ยิงครั้งเดียวแบบ Batch — backend ประมวลผลทั้งหมดใน transaction เดียว
    // (atomic + Discord แจ้งเตือนรอบเดียว ไม่เด้งหลาย embed เหมือนลูปยิงทีละบิล)
    // 🧾 [F5] และออกใบเสร็จให้ทุกรายการ **ในธุรกรรมเดียวกัน** — ถ้าเลขเอกสารไม่พอ
    //     จะไม่มีการรับเงินเกิดขึ้นเลย (ไม่ใช่รับเงินแล้วไม่มีใบเสร็จ)
    const res = await FinanceService.confirmBatchPayment(currentServerId, {
      items: selectedPaymentIds.value.map((pid) => ({
        payment_id: pid,
        paid_amount: payAmounts.value[pid] || 0,
      })),
      paid_to_account_id: Number(paidToAccountId.value),
      slip_image_url: slipImageUrl.value || undefined,
      user_name: currentUserName,
      issue_receipts: issueReceipts.value,
    })

    isModalOpen.value = false
    fetchDebtors()

    // 🧾 มีใบเสร็จออกให้ในรอบนี้ → เสนอรวมเป็น PDF ทันที
    //    🔑 ใช้เลขที่จาก **คำตอบของคำขอนี้** ไม่ใช่จากทะเบียน ⇒ ไม่มีทางดาวน์โหลดใบของ
    //       คนอื่นปนเข้ามา และไม่ต้องเดาว่าจะกรองช่วงเวลายังไงให้ได้ "เฉพาะที่เพิ่งออก"
    //    ♻️ ใช้ `downloadCombined` ตัวเดิม — ไม่มีเส้นทางดาวน์โหลดใหม่ให้ต้องดูแล
    const nos = res.receipts.map((r) => r.receipt_no)
    if (nos.length > 0) {
      const canDownload = nos.length <= COMBINED_PDF_MAX
      const after = await Swal.fire({
        icon: 'success',
        title: 'รับเงินและออกใบเสร็จแล้ว',
        html:
          `บันทึกการรับเงินรวบยอดเรียบร้อย<br>` +
          `ออกใบเสร็จ <b>${res.issued_count}</b> ใบ` +
          (res.batch_id ? ' — รวมเป็นชุดเดียว' : '') +
          `<br>เลขที่ล่าสุด <b class="num">${nos[nos.length - 1] ?? '—'}</b>` +
          (canDownload
            ? `<br><br><span style="font-size:0.85em;color:#78716c">รวมเป็นไฟล์เดียวได้ ` +
              `(${nos.length} หน้า) เหมาะสำหรับพิมพ์แจก</span>`
            : `<br><br><span style="font-size:0.85em;color:#a16207">มี ${nos.length} ใบ ` +
              `เกินกว่าจะรวมเป็นไฟล์เดียว (สูงสุด ${COMBINED_PDF_MAX}) — ` +
              `ดาวน์โหลดเป็นชุด ๆ ได้ที่หน้าทะเบียนเอกสาร</span>`),
        showCancelButton: canDownload,
        confirmButtonText: 'ดาวน์โหลด PDF รวม',
        cancelButtonText: 'ปิด',
        confirmButtonColor: '#1d4ed8',
        cancelButtonColor: '#78716c',
      })
      if (canDownload && after.isConfirmed) await downloadCombined('receipts', nos)
      return
    }

    Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: 'บันทึกการรับเงินรวบยอดเรียบร้อย',
      timer: 1500,
      showConfirmButton: false,
    })
  } catch (error: unknown) {
    Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'บันทึกไม่สำเร็จ', 'error')
  }
}

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num)
}

onMounted(() => {
  fetchDebtors()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Outstanding Balances"
      title="สรุปผู้ค้างชำระ"
      description="รายชื่อผู้ค้างจ่ายเงินจากทุกโปรเจกต์ (รวมโปรเจกต์ที่ปิดไปแล้ว)"
    >
      <template #actions>
        <!--
          🧾 ปุ่มใบแจ้งหนี้อยู่ **ที่นี่** ไม่ใช่ในโมดัลรับเงิน (โมดัลถูก gate ด้วย `isAdmin`
          มาแต่เดิม ⇒ ปุ่มที่ซ่อนอยู่ในนั้นจะใช้ได้แค่แอดมิน) — และการเลือก "คน" ก็ไม่เกี่ยวกับ
          การเลือกบิลที่จะรับเงิน ⇒ คนละงานกัน จึงอยู่คนละที่
          ⚠️ ห้าม `:disabled` ตอนยังไม่เลือกอะไร: ปุ่มตายไม่บอกอะไรเลยว่าต้องทำอย่างไร
             ⇒ ปล่อยให้กดได้แล้ว handler ตอบเป็นข้อความไทย ("กรุณาติ๊กเลือกนักเรียน...")
        -->
        <button
          v-if="canManageFinance"
          type="button"
          class="btn-ghost-ui"
          :disabled="isIssuingInvoices"
          @click="handleIssueSelectedInvoices"
        >
          <i class="bi bi-file-earmark-text" aria-hidden="true"></i>
          ออกใบแจ้งหนี้ที่เลือก<span v-if="selectedStudentIds.length"
            >({{ selectedStudentIds.length }})</span
          >
        </button>
        <button
          v-if="canManageFinance"
          type="button"
          class="btn-ghost-ui"
          :disabled="isIssuingInvoices"
          @click="handleIssueRoomInvoices"
        >
          <i class="bi bi-collection" aria-hidden="true"></i>
          ออกใบแจ้งหนี้ทั้งห้อง
        </button>
        <!--
          💰 [F4] ทางเข้าหน้า "เงินรับล่วงหน้า" — **ห้าม gate ด้วย `isAdmin`**
          🔴 เพราะการ์ดทางเข้าอีกทางอยู่ที่ `FinanceDashboard.vue` ซึ่ง gate ด้วย `isAdmin`
             ⇒ ถ้ามีแต่ที่นั่น เหรัญญิกที่มี `MANAGE_FINANCE` แต่ไม่ใช่แอดมินจะเข้าหน้า
             เงินรับล่วงหน้าไม่ได้เลย (กับดักเดียวกับที่คอมเมนต์หัวไฟล์นี้อธิบายไว้)
          ✅ หน้านี้เปิดให้สมาชิกอ่านอยู่แล้ว ⇒ ลิงก์นี้จึงไม่ต้อง gate อะไรทั้งสิ้น
             (ปุ่มเขียนในหน้านั้น gate ด้วย `canManageFinance` เองอีกชั้น)
        -->
        <RouterLink to="/finance/credits" class="btn-ghost-ui" title="เงินรับล่วงหน้า / เครดิตคงเหลือ">
          <i class="bi bi-piggy-bank" aria-hidden="true"></i>
          เงินรับล่วงหน้า
        </RouterLink>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
      </template>
    </PageHeader>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-24" />

    <StateBlock v-else-if="hasError" variant="error" @retry="fetchDebtors" />

    <StateBlock
      v-else-if="!debtors.length"
      variant="empty"
      icon="bi-emoji-smile"
      title="ไม่มีใครติดหนี้ห้องเลย!"
      hint="ห้องนี้รวยมาก ทุกคนจ่ายเงินครบเป๊ะ"
    />

    <template v-else>
      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="d in debtors"
          :key="d.student_id"
          class="page-card border-s-4 border-s-red-500 p-4"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-2">
              <!-- 🧾 ติ๊ก "คน" เพื่อออกใบแจ้งหนี้ (คนละช่องกับ "บิลที่จะรับเงิน" ในโมดัล) -->
              <label v-if="canManageFinance" class="flex shrink-0 cursor-pointer items-center">
                <input
                  v-model="selectedStudentIds"
                  type="checkbox"
                  :value="d.student_id"
                  :aria-label="`เลือก ${d.student_name} เพื่อออกใบแจ้งหนี้`"
                  class="peer sr-only"
                />
                <span
                  class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                  :class="
                    selectedStudentIds.includes(d.student_id)
                      ? 'border-brand-700 bg-brand-700'
                      : 'border-stone-300 bg-white'
                  "
                >
                  <i
                    v-if="selectedStudentIds.includes(d.student_id)"
                    class="bi bi-check-lg text-sm font-bold text-white"
                    aria-hidden="true"
                  ></i>
                </span>
              </label>
              <span class="chip num shrink-0 bg-stone-100 text-stone-500">#{{ d.student_no }}</span>
              <h2 class="font-display min-w-0 truncate text-base font-bold text-stone-900">
                {{ d.student_name }}
              </h2>
            </div>

            <div class="shrink-0 text-right">
              <p class="text-[11px] font-bold text-stone-500">ต้องเก็บจริง</p>
              <!--
                💰 [F4] ตัวเลขหลัก = `net_pending_amount` (หักเครดิตแล้ว) — เป็นยอดที่ครู
                ต้องไปเก็บจริง ⇒ ไม่ต้องให้ครูคิดเลขเองบนจอ
                ⚠️ `total_pending_amount` ยังโชว์คู่กัน (ขีดฆ่า) เมื่อมีเครดิต เพื่อให้เห็นที่มา
                🔴 ห้ามลบเครดิตเองที่หน้าจอ (`total - credit`) — backend ส่งค่าที่หักแล้วมาให้
                   และเป็นตัวเดียวกับที่ระบบจะหักจริง ถ้าคำนวณซ้ำที่จอมีโอกาสไม่ตรงกัน
              -->
              <p
                class="font-display num mt-0.5 whitespace-nowrap text-lg font-bold"
                :class="d.net_pending_amount > 0 ? 'text-red-600' : 'text-emerald-600'"
              >
                ฿{{ formatNumber(d.net_pending_amount) }}
              </p>
              <p
                v-if="d.credit_balance > 0"
                class="num mt-0.5 whitespace-nowrap text-[11px] text-stone-400 line-through"
              >
                ฿{{ formatNumber(d.total_pending_amount) }}
              </p>
            </div>
          </div>

          <div
            class="mt-2.5 flex items-center justify-between gap-3 border-t border-stone-100 pt-2.5"
          >
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="chip shrink-0 bg-amber-50 text-amber-700">
                <i class="bi bi-receipt" aria-hidden="true"></i>
                ค้าง {{ d.overdue_count }} รายการ
              </span>
              <!-- 💰 chip เครดิต — ทำให้ "ยอดที่ลดลง" อธิบายตัวเองได้ ไม่ต้องเดา -->
              <RouterLink
                v-if="d.credit_balance > 0"
                to="/finance/credits"
                class="chip shrink-0 bg-emerald-50 text-emerald-700"
                :title="`ดูเงินรับล่วงหน้าของ ${d.student_name}`"
              >
                <i class="bi bi-piggy-bank" aria-hidden="true"></i>
                มีเครดิต ฿{{ formatNumber(d.credit_balance) }}
              </RouterLink>
            </div>
            <button
              v-if="isAdmin"
              type="button"
              class="btn-primary shrink-0"
              @click="handleClearDebt(d)"
            >
              <i class="bi bi-wallet2" aria-hidden="true"></i>
              เคลียร์หนี้
            </button>
            <span v-else class="chip shrink-0 bg-stone-100 text-stone-500">
              <i class="bi bi-lock" aria-hidden="true"></i>
              รอแอดมินดำเนินการ
            </span>
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
                  <label class="flex cursor-pointer items-center" title="เลือกทั้งหมดในหน้านี้">
                    <input
                      type="checkbox"
                      class="peer sr-only"
                      :checked="allSelected"
                      aria-label="เลือกนักเรียนทั้งหมดเพื่อออกใบแจ้งหนี้"
                      @change="toggleSelectAll"
                    />
                    <span
                      class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                      :class="allSelected ? 'border-brand-700 bg-brand-700' : 'border-stone-300 bg-white'"
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
                <th class="text-center">จำนวนที่ค้าง (บิล)</th>
                <th class="text-right">ต้องเก็บจริง (฿)</th>
                <th class="text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in debtors" :key="d.student_id">
                <td v-if="canManageFinance">
                  <label class="flex cursor-pointer items-center">
                    <input
                      v-model="selectedStudentIds"
                      type="checkbox"
                      :value="d.student_id"
                      :aria-label="`เลือก ${d.student_name} เพื่อออกใบแจ้งหนี้`"
                      class="peer sr-only"
                    />
                    <span
                      class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                      :class="
                        selectedStudentIds.includes(d.student_id)
                          ? 'border-brand-700 bg-brand-700'
                          : 'border-stone-300 bg-white'
                      "
                    >
                      <i
                        v-if="selectedStudentIds.includes(d.student_id)"
                        class="bi bi-check-lg text-xs font-bold text-white"
                        aria-hidden="true"
                      ></i>
                    </span>
                  </label>
                </td>
                <td class="num font-bold text-stone-400">#{{ d.student_no }}</td>
                <td class="font-bold text-stone-900">{{ d.student_name }}</td>
                <td class="text-center">
                  <div class="flex flex-wrap items-center justify-center gap-1.5">
                    <span class="chip bg-amber-50 text-amber-700">
                      <i class="bi bi-receipt" aria-hidden="true"></i>
                      ค้าง {{ d.overdue_count }} รายการ
                    </span>
                    <!-- 💰 chip เครดิต — อธิบายว่าทำไม "ต้องเก็บจริง" ต่ำกว่า "ยอดค้างดิบ" -->
                    <RouterLink
                      v-if="d.credit_balance > 0"
                      to="/finance/credits"
                      class="chip bg-emerald-50 text-emerald-700"
                      :title="`ดูเงินรับล่วงหน้าของ ${d.student_name}`"
                    >
                      <i class="bi bi-piggy-bank" aria-hidden="true"></i>
                      มีเครดิต ฿{{ formatNumber(d.credit_balance) }}
                    </RouterLink>
                  </div>
                </td>
                <td class="whitespace-nowrap text-right">
                  <!-- 💰 ตัวเลขหลัก = ยอดที่ต้องเก็บจริงหลังหักเครดิต (ดูเหตุผลที่การ์ดมือถือ) -->
                  <span
                    class="font-display num text-base font-bold"
                    :class="d.net_pending_amount > 0 ? 'text-red-600' : 'text-emerald-600'"
                  >
                    ฿{{ formatNumber(d.net_pending_amount) }}
                  </span>
                  <span
                    v-if="d.credit_balance > 0"
                    class="num mt-0.5 block text-[11px] font-normal text-stone-400 line-through"
                  >
                    ฿{{ formatNumber(d.total_pending_amount) }}
                  </span>
                </td>
                <td>
                  <div class="flex justify-end">
                    <button
                      v-if="isAdmin"
                      type="button"
                      class="btn-primary"
                      @click="handleClearDebt(d)"
                    >
                      <i class="bi bi-wallet2" aria-hidden="true"></i>
                      เคลียร์หนี้
                    </button>
                    <span v-else class="chip bg-stone-100 text-stone-500">
                      <i class="bi bi-lock" aria-hidden="true"></i>
                      รอแอดมิน
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- รับเงินรวบยอด: bottom sheet บนมือถือ / modal กลางจอบนเดสก์ท็อป -->
    <div
      v-if="isModalOpen && isAdmin"
      class="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
    >
      <div
        class="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-t-3xl border border-stone-200 bg-white md:max-h-[85vh] md:rounded-2xl"
      >
        <div
          class="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 px-4 py-4 sm:px-6"
        >
          <div class="min-w-0">
            <h2 class="font-display truncate text-lg font-bold text-stone-900">
              บันทึกรับเงินรวบยอด
            </h2>
            <p class="mt-0.5 flex items-center gap-1 truncate text-sm font-bold text-brand-700">
              <i class="bi bi-person-fill shrink-0" aria-hidden="true"></i>
              {{ selectedStudent?.name }}
            </p>
          </div>
          <button
            type="button"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-900 active:scale-[0.97]"
            aria-label="ปิดหน้าต่าง"
            @click="isModalOpen = false"
          >
            <i class="bi bi-x-lg text-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="flex-1 overflow-y-auto overscroll-contain bg-stone-50/50 p-4 sm:p-6">
          <div v-if="isLoadingDebts" class="flex justify-center py-10">
            <div
              class="h-8 w-8 animate-spin rounded-full border-2 border-stone-200 border-b-brand-700"
              role="status"
              aria-label="กำลังโหลดรายการค้างชำระ"
            ></div>
          </div>

          <div v-else class="space-y-3">
            <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">
              เลือกรายการบิลที่ต้องการชำระ
            </p>

            <label
              v-for="debt in studentDebts"
              :key="debt.payment_id"
              class="relative flex cursor-pointer items-center gap-3 rounded-2xl border p-4 transition-colors md:gap-4"
              :class="
                selectedPaymentIds.includes(debt.payment_id)
                  ? 'border-brand-200 bg-brand-50'
                  : 'border-stone-200 bg-white hover:border-stone-300'
              "
            >
              <!-- ช่องทำเครื่องหมาย: input จริงซ่อนแบบ sr-only เพื่อให้ยังโฟกัสด้วยคีย์บอร์ดได้ -->
              <input
                v-model="selectedPaymentIds"
                type="checkbox"
                :value="debt.payment_id"
                class="peer sr-only"
              />
              <span
                class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                :class="
                  selectedPaymentIds.includes(debt.payment_id)
                    ? 'border-brand-700 bg-brand-700'
                    : 'border-stone-300 bg-white'
                "
              >
                <i
                  v-if="selectedPaymentIds.includes(debt.payment_id)"
                  class="bi bi-check-lg text-sm font-bold text-white"
                  aria-hidden="true"
                ></i>
              </span>

              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-stone-900">{{ debt.title }}</p>
                <p class="num mt-0.5 text-[11px] font-bold text-red-600">
                  ยอดค้าง: ฿{{ formatNumber(debt.amount) }}
                </p>
              </div>

              <div class="relative w-32 shrink-0 sm:w-36">
                <span
                  class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-2.5 text-sm font-bold text-stone-400"
                  aria-hidden="true"
                >
                  ฿
                </span>
                <input
                  v-model="payAmounts[debt.payment_id]"
                  type="number"
                  :disabled="!selectedPaymentIds.includes(debt.payment_id)"
                  :aria-label="`ยอดรับเงิน ${debt.title}`"
                  class="field num ps-6 pe-1.5 text-right"
                />
              </div>
            </label>
          </div>

          <div class="page-card mt-6 p-4 sm:p-5">
            <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label class="field-label" for="payAccount">รับเข้ากระเป๋า</label>
                <select id="payAccount" v-model="paidToAccountId" class="field">
                  <option v-for="acc in accounts" :key="acc.id" :value="acc.id.toString()">
                    {{ acc.account_name }}
                  </option>
                </select>
              </div>
              <div>
                <label class="field-label" for="paySlip">URL รูปสลิป (ถ้ามี)</label>
                <input
                  id="paySlip"
                  v-model="slipImageUrl"
                  type="url"
                  class="field"
                  placeholder="https://..."
                />
              </div>
            </div>

            <!--
              🧾 [F5] ออกใบเสร็จอัตโนมัติ — ติ๊กไว้เป็นค่าเริ่มต้นตามคำขอผู้ใช้
              ("กดเคลียร์หนี้แล้วอยากให้มันออกใบเสร็จมาพร้อมกันหมดเลย")
              ⚠️ ข้อความต้องบอกผลของการปิดติ๊กให้ครบทั้งสองด้าน: ไม่มีใบเสร็จ **และ**
                 ไม่มีอะไรถูกบันทึกเลยถ้าเลขเอกสารไม่พอ — ครูที่ถือเงินสดอยู่ต้องรู้ก่อนกด
            -->
            <label
              class="mt-4 flex min-h-11 cursor-pointer items-start gap-3 rounded-2xl border border-stone-200 bg-white p-3 transition-colors hover:border-stone-300"
            >
              <input v-model="issueReceipts" type="checkbox" class="peer sr-only" />
              <span
                class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                :class="
                  issueReceipts ? 'border-brand-700 bg-brand-700' : 'border-stone-300 bg-white'
                "
              >
                <i
                  v-if="issueReceipts"
                  class="bi bi-check-lg text-sm font-bold text-white"
                  aria-hidden="true"
                ></i>
              </span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm font-bold text-stone-900">
                  ออกใบเสร็จให้ทุกรายการที่เคลียร์
                </span>
                <span class="mt-0.5 block text-[11px] font-bold text-stone-500">
                  ออกพร้อมกับการบันทึกรับเงินในครั้งเดียว — ถ้าเลขเอกสารไม่พอ
                  ระบบจะไม่บันทึกการรับเงินเลย
                </span>
              </span>
            </label>
          </div>
        </div>

        <div
          class="flex shrink-0 flex-col gap-3 border-t border-stone-200 bg-white p-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:pt-4 sm:pb-[calc(env(safe-area-inset-bottom)+1.5rem)]"
        >
          <div class="flex items-center justify-between gap-3 sm:block">
            <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">
              ยอดรวมที่เลือกชำระ
            </p>
            <p class="font-display num text-2xl font-bold text-red-600">
              ฿{{ formatNumber(totalSelectedAmount) }}
            </p>
          </div>
          <div class="flex flex-col gap-2 sm:flex-row">
            <!--
              🚫 ปุ่ม "ออกใบแจ้งหนี้" ถูก **ย้ายออกจากที่นี่** ไปอยู่ที่หัวหน้า (PageHeader #actions)
              เหตุผล: (ก) ยอดบนใบคือยอดค้างรวมทุกบิลของคนนั้น ⇒ การติ๊กบิลในโมดัลนี้ไม่ได้
              มีผลกับยอดบนใบเลย (ข) โมดัลนี้ gate ด้วย `isAdmin` ⇒ เหรัญญิกที่มี
              MANAGE_FINANCE จะกดไม่ได้
              ⇒ ในโมดัลนี้เหลือเฉพาะ "บันทึกรับเงิน" ซึ่งเป็นหน้าที่เดียวของมัน
            -->
            <button type="button" class="btn-primary w-full sm:w-auto" @click="handleBatchPay">
              <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
              ยืนยันการรับเงิน
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ซ่อนปุ่มลูกศรในช่อง Input Number ให้ดูคลีนๆ แบบแอปธนาคาร */
input[type='number']::-webkit-inner-spin-button,
input[type='number']::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type='number'] {
  -moz-appearance: textfield;
}
/* (scrollbar ใช้ของกลางจาก main.css แล้ว) */
</style>
