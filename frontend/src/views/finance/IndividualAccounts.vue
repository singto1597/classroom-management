<script setup lang="ts">
/**
 * 👤 บัญชีรายบุคคล — **หน้าเดียวของงานเงินรายคน** (FIN-V2 / P1.4 + merge)
 *
 * รวมสามหน้าที่เคยซ้ำกัน ("บัญชีรายบุคคล" · "ผู้ค้างชำระ" · "เงินรับล่วงหน้า")
 * เป็นรายชื่อเดียวที่นักเรียน 1 คนมีตัวเลขครบ: ค้างทั้งหมด · เกินกำหนด · ยังไม่ถึงกำหนด ·
 * เครดิตคงเหลือ · ใช้ได้ — แล้วกดทำงานได้จากแถวนั้นเลย
 *
 * 🔓 อ่าน = สมาชิกห้องทุกคน (backend `require_member`)
 * 🔒 ปุ่ม **เขียน** ทุกปุ่ม gate ด้วย `canManageFinance` **ไม่ใช่ `isAdmin`**
 *    (บทเรียนจาก `DebtorList.vue`: เหรัญญิกที่มี MANAGE_FINANCE ต้องใช้ได้)
 *
 * ⚠️ เงินจาก individual-accounts เป็น **string 2 ตำแหน่ง** ⇒ `formatMoney(Number(x))`
 *    ส่วนเครดิต/บัญชีรายคนใช้ `StudentCreditBalance` (number) ⇒ แปลงผ่าน `toCreditBalance`
 *
 * 🔁 `/finance/debtors` และ `/finance/credits` เป็น redirect มาที่นี่ (พร้อม `status`)
 *    ⇒ ตัวกรองต้องผูกกับ `route.query` เพื่อให้ deep link เปิดมาถูกแท็บ
 */
import { ref, computed, onMounted, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CreditApplyPlan,
  CreditRoundResponse,
  FinancePerson,
  FundType,
  IndividualAccountItem,
  IndividualAccountQuery,
  IndividualAccountStatus,
  InvoiceBatchIssueResult,
  StudentCreditBalance,
} from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatAmount, formatMoney, roundMoney } from '@/utils/money'
import { formatThaiDate } from '@/utils/datetime'
import { downloadBlob, combinedPdfFilename } from '@/utils/download'

import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppTabs from '@/components/ui/AppTabs.vue'
import type { AppTabItem } from '@/components/ui/AppTabs.vue'
import RowActionMenu from '@/components/ui/RowActionMenu.vue'
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue'
import ReceiveMoneyModal from '@/components/finance/ReceiveMoneyModal.vue'
import BulkReceiveSheet from '@/components/finance/BulkReceiveSheet.vue'
import BulkCreditSheet from '@/components/finance/BulkCreditSheet.vue'
import CreditTopUpModal from '@/components/finance/CreditTopUpModal.vue'
import CreditApplyModal from '@/components/finance/CreditApplyModal.vue'
import CreditHistoryModal from '@/components/finance/CreditHistoryModal.vue'
import { useDialog } from '@/composables/useDialog'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const dialog = useDialog()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const canManageFinance = computed(() => authStore.canManageFinance)

// ─────────────────────────────────────────────────────── ตัวกรอง ↔ route.query
const STATUS_VALUES = ['all', 'outstanding', 'credit', 'settled'] as const
const FUND_TYPE_VALUES = ['room_fund', 'pass_through'] as const

const queryString = (key: string): string => {
  const raw = route.query[key]
  return (Array.isArray(raw) ? raw[0] : raw) ?? ''
}

const initialStatus = (): IndividualAccountStatus => {
  const value = queryString('status')
  return (STATUS_VALUES as readonly string[]).includes(value)
    ? (value as IndividualAccountStatus)
    : 'all'
}

const initialFundType = (): '' | FundType => {
  const value = queryString('fund_type')
  return (FUND_TYPE_VALUES as readonly string[]).includes(value) ? (value as FundType) : ''
}

// AppTabs ส่งค่ากลับเป็น string — เก็บเป็น string แล้วตรวจค่าตอนสร้าง query
const statusFilter = ref<string>(initialStatus())
const fundTypeFilter = ref<string>(initialFundType())
const searchInput = ref<string>(queryString('q'))

const normalizedStatus = (): IndividualAccountStatus =>
  (STATUS_VALUES as readonly string[]).includes(statusFilter.value)
    ? (statusFilter.value as IndividualAccountStatus)
    : 'all'

const normalizedFundType = (): '' | FundType =>
  (FUND_TYPE_VALUES as readonly string[]).includes(fundTypeFilter.value)
    ? (fundTypeFilter.value as FundType)
    : ''

const STATUS_TABS: AppTabItem[] = [
  { value: 'all', label: 'ทั้งหมด' },
  { value: 'outstanding', label: 'ค้างชำระ' },
  { value: 'credit', label: 'มีเครดิต' },
  { value: 'settled', label: 'จ่ายครบ' },
]

const buildQuery = (): IndividualAccountQuery => {
  const query: IndividualAccountQuery = {}
  const status = normalizedStatus()
  if (status !== 'all') query.status = status
  const fundType = normalizedFundType()
  if (fundType) query.fund_type = fundType
  const search = searchInput.value.trim()
  if (search) query.q = search
  return query
}

/** เขียนตัวกรองลง URL เพื่อให้แชร์/ย้อนกลับแล้วได้ผลเดิม (replace ไม่เพิ่มประวัติ) */
const syncQuery = () => {
  const next: Record<string, string> = {}
  const status = normalizedStatus()
  if (status !== 'all') next.status = status
  const fundType = normalizedFundType()
  if (fundType) next.fund_type = fundType
  const search = searchInput.value.trim()
  if (search) next.q = search

  const same =
    queryString('status') === (next.status ?? '') &&
    queryString('fund_type') === (next.fund_type ?? '') &&
    queryString('q') === (next.q ?? '')
  if (!same) void router.replace({ query: next })
}

const hasFilters = computed(
  () => normalizedStatus() !== 'all' || !!normalizedFundType() || !!searchInput.value.trim()
)

// ─────────────────────────────────────────────────────── รายการหลัก
const items = ref<IndividualAccountItem[]>([])
const asOf = ref('')
const isLoading = ref(true)
const hasError = ref(false)

const listGuard = createLatestGuard()

const money = (value: string) => formatMoney(Number(value))
const isPositive = (value: string) => Number(value) > 0

const loadAccountsList = async () => {
  const token = listGuard.begin()
  isLoading.value = true
  hasError.value = false
  try {
    const res = await FinanceService.getIndividualAccounts(currentRoomId, buildQuery())
    if (!listGuard.isCurrent(token)) return
    items.value = res.items
    asOf.value = res.as_of
  } catch {
    if (!listGuard.isCurrent(token)) return
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดบัญชีรายบุคคลไม่สำเร็จ', 'error')
  } finally {
    if (listGuard.isCurrent(token)) isLoading.value = false
  }
}

// ⏱️ ค้นหา debounce 300ms — รูปแบบเดียวกับ FineList
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchInput, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    syncQuery()
    void loadAccountsList()
  }, 300)
})

// เปลี่ยนแท็บ/ประเภทเงิน ⇒ เขียน URL + โหลดทันที
watch([statusFilter, fundTypeFilter], () => {
  syncQuery()
  void loadAccountsList()
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

// ─────────────────────────────────────────────────────── KPI (จากรายการที่กรองอยู่)
const totals = computed(() => {
  const sum = (pick: (item: IndividualAccountItem) => string) =>
    roundMoney(items.value.reduce((acc, item) => acc + Number(pick(item)), 0))
  return {
    outstanding: sum((i) => i.outstanding_total),
    overdue: sum((i) => i.overdue_total),
    upcoming: sum((i) => i.upcoming_total),
    credit: sum((i) => i.credit_balance),
    ready: sum((i) => i.ready_to_apply),
  }
})

// ─────────────────────────────────────────────────────── เลือกหลายคน (งานรวบยอด)
const selectedIds = ref<number[]>([])

const selectedCount = computed(() => selectedIds.value.length)

const allSelected = computed(
  () => items.value.length > 0 && selectedIds.value.length === items.value.length
)

const toggleSelect = (studentId: number) => {
  selectedIds.value = selectedIds.value.includes(studentId)
    ? selectedIds.value.filter((id) => id !== studentId)
    : [...selectedIds.value, studentId]
}

const toggleSelectAll = () => {
  selectedIds.value = allSelected.value ? [] : items.value.map((item) => item.student_id)
}

// 🧹 คนที่หลุดจากรายการ (จ่ายครบ/hidden โดยตัวกรอง) ต้องหลุดจากที่ติ๊กด้วย
//    ไม่งั้นคำขอออกใบแจ้งหนี้/รับเงินจะพา id ที่ backend ไม่รู้จักไปด้วย (404 ทั้งชุด)
watch(items, () => {
  const stillListed = new Set(items.value.map((item) => item.student_id))
  selectedIds.value = selectedIds.value.filter((id) => stillListed.has(id))
})

// ─────────────────────────────────────────────────────── Drill-down
const openAccount = (studentId: number) => {
  void router.push({
    name: 'finance-individual-account-detail',
    params: { studentId },
  })
}

// ─────────────────────────────────────────────────────── ตัวแปลงแถว → โมเดลเครดิต
/** individual-accounts เงินเป็น string · เครดิต modals ต้องการ number */
const toCreditBalance = (item: IndividualAccountItem): StudentCreditBalance => ({
  student_id: item.student_id,
  student_no: item.student_no,
  student_name: item.name,
  credit_balance: Number(item.credit_balance),
  total_pending_amount: Number(item.outstanding_total),
  net_pending_amount: roundMoney(Number(item.outstanding_total) - Number(item.ready_to_apply)),
})

// ─────────────────────────────────────────────────────── กระเป๋าเงิน (โมดัลเติม/หัก)
const accounts = ref<Account[]>([])

const loadAccountOptions = async () => {
  if (!canManageFinance.value) {
    accounts.value = []
    return
  }
  try {
    accounts.value = await FinanceService.getAccounts(currentRoomId)
  } catch {
    // กระเป๋าโหลดไม่ได้ ⇒ โมดัลจะแจ้งเองตอนกดยืนยัน — ไม่ทำให้ทั้งหน้าพัง
    accounts.value = []
  }
}

// ─────────────────────────────────────────────────────── รับเงินรายคน
const receiveOpen = ref(false)
const receiveTarget = ref<IndividualAccountItem | null>(null)

const openReceive = (item: IndividualAccountItem) => {
  receiveTarget.value = item
  receiveOpen.value = true
}

const onReceiveSaved = async () => {
  await loadAccountsList()
}

// ─────────────────────────────────────────────────────── เติม/หัก/ประวัติเครดิต
const topUpOpen = ref(false)
const topUpTarget = ref<StudentCreditBalance | null>(null)

const openTopUp = (item: IndividualAccountItem) => {
  topUpTarget.value = toCreditBalance(item)
  topUpOpen.value = true
}

const applyOpen = ref(false)
const applyTarget = ref<StudentCreditBalance | null>(null)

const openApply = (item: IndividualAccountItem) => {
  applyTarget.value = toCreditBalance(item)
  applyOpen.value = true
}

const historyOpen = ref(false)
const historyTarget = ref<StudentCreditBalance | null>(null)

const openHistory = (item: IndividualAccountItem) => {
  historyTarget.value = toCreditBalance(item)
  historyOpen.value = true
}

/** ประวัติขอเปิดฟอร์มจากในแผง ⇒ ปิดประวัติแล้วเปิดฟอร์มนั้น */
const onHistoryTopUp = (student: StudentCreditBalance) => {
  historyOpen.value = false
  topUpTarget.value = student
  topUpOpen.value = true
}

const onHistoryApply = (student: StudentCreditBalance) => {
  historyOpen.value = false
  applyTarget.value = student
  applyOpen.value = true
}

/** หลังเติม/หักเครดิตสำเร็จ — ยอดค้าง/เครดิตบนรายชื่อเปลี่ยนทั้งแถว */
const onCreditChanged = async () => {
  await loadAccountsList()
}

// ─────────────────────────────────────────────────────── เมนูจุด 3 จุดต่อแถว
// ⚠️ ไม่มี "เปิดบัญชี" ในเมนู — ทั้งการ์ดและแถวตารางกดที่ไหนก็เปิดบัญชีคนนั้นอยู่แล้ว
//    (ปุ่มซ้ำไว้มีแต่ทำให้แถวแน่นและกดผิดง่าย; เมนูเหลือเฉพาะงานที่ต้องตั้งใจ)
const menuItems = (item: IndividualAccountItem): RowActionItem[] => {
  const actions: RowActionItem[] = []
  if (canManageFinance.value) {
    actions.push(
      { key: 'topup', label: 'เติมเงินล่วงหน้า', icon: 'bi-plus-circle' },
      {
        key: 'apply',
        label: 'ใช้เครดิตปิดบิล',
        icon: 'bi-scissors',
        disabled: Number(item.credit_balance) <= 0,
      }
    )
  }
  actions.push({ key: 'history', label: 'ประวัติเครดิต', icon: 'bi-clock-history' })
  return actions
}

const handleRowAction = (item: IndividualAccountItem, key: string) => {
  if (key === 'topup') openTopUp(item)
  else if (key === 'apply') openApply(item)
  else if (key === 'history') openHistory(item)
}

// ─────────────────────────────────────────────────────── รับเงินหลายคน (P2.7)
const bulkReceiveOpen = ref(false)

const openBulkReceive = () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่รับเงินได้', 'error')
    return
  }
  if (!selectedIds.value.length) {
    return void dialog.alert('ยังไม่ได้เลือกนักเรียน', 'ติ๊กนักเรียนอย่างน้อย 1 คนก่อน', 'info')
  }
  bulkReceiveOpen.value = true
}

const onBulkSaved = async () => {
  selectedIds.value = []
  await loadAccountsList()
}

// ─────────────────────────────────────────────────────── ออกใบแจ้งหนี้
const ISSUE_PER_REQUEST_MAX = 100
const COMBINED_PDF_MAX = 100

/** คำเตือนที่ต้องมีทุกครั้งก่อนออกใบแจ้งหนี้ — พฤติกรรมนี้ต่างจากใบเสร็จโดยสิ้นเชิง */
const POINT_IN_TIME_HINT =
  'ใบแจ้งหนี้เป็นเอกสาร ณ จุดเวลา — ยอดค้างเปลี่ยนเมื่อนักเรียนจ่ายเพิ่ม ' +
  'การออกซ้ำจึงได้เลขใหม่ทุกครั้ง (ต่างจากใบเสร็จที่ได้เลขเดิม)'

const isIssuingInvoices = ref(false)
const isDownloadingCombined = ref(false)

const itemsWithDebt = computed(() => items.value.filter((item) => isPositive(item.outstanding_total)))

/** ยอดที่ใบแจ้งหนี้จะเรียกเก็บ = ยอดค้างรวมของนักเรียนที่ติ๊กไว้ */
const selectedInvoiceAmount = computed(() =>
  roundMoney(
    items.value
      .filter((item) => selectedIds.value.includes(item.student_id))
      .reduce((sum, item) => sum + Number(item.outstanding_total), 0)
  )
)

/** ออกใบแจ้งหนี้ **ทั้งห้อง** ต้องไม่แอบใช้ยอดของรายการที่ถูกกรองอยู่ */
const roomOutstanding = computed(() =>
  roundMoney(itemsWithDebt.value.reduce((sum, item) => sum + Number(item.outstanding_total), 0))
)

/** 🖨️ ดาวน์โหลดหลายใบเป็น PDF ไฟล์เดียว (หน้าละใบ) */
const downloadCombined = async (kind: 'receipts' | 'invoices', nos: string[]) => {
  if (isDownloadingCombined.value || nos.length === 0) return
  if (nos.length > COMBINED_PDF_MAX) {
    return dialog.alert(
      'รวมไฟล์ไม่ได้ในครั้งเดียว',
      `เลือกไว้ ${nos.length} ฉบับ แต่รวมได้ครั้งละไม่เกิน ${COMBINED_PDF_MAX} ฉบับ ` +
        '— กรุณาแบ่งดาวน์โหลดเป็นรอบ',
      'warning',
    )
  }
  isDownloadingCombined.value = true
  void dialog.loading('กำลังสร้างไฟล์ PDF...', 'ระบบกำลังรวมเอกสารเป็นไฟล์เดียว')
  try {
    const blob = await FinanceService.downloadCombinedPdf(currentRoomId, nos)
    downloadBlob(blob, combinedPdfFilename(nos, kind))
    dialog.close()
  } catch (error: unknown) {
    dialog.close()
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    isDownloadingCombined.value = false
  }
}

/**
 * ทางเดียวที่ยิง API ออกใบแจ้งหนี้ของทั้งสองปุ่ม
 * 🔴 เป็น **การเขียนจริง**: point-in-time ⇒ ต้อง confirm เสมอ ไม่มีปุ่มไหนยิงตรง
 */
const runInvoiceIssue = async (
  action: () => Promise<InvoiceBatchIssueResult>,
  description: string,
  title: string
) => {
  const confirmed = await dialog.confirm(title, `${description} — ${POINT_IN_TIME_HINT}`, {
    icon: 'question',
    confirmButtonText: 'ออกใบแจ้งหนี้',
  })
  if (!confirmed.isConfirmed) return

  isIssuingInvoices.value = true
  void dialog.loading('กำลังออกใบแจ้งหนี้...', 'ระบบกำลังสร้างเอกสารให้ทุกคนที่เลือก')
  try {
    const res = await action()
    const nos = res.receipts.map((r) => r.receipt_no)
    const canDownload = nos.length > 0 && nos.length <= COMBINED_PDF_MAX
    // 📋 ต้องรายงาน **คนที่ถูกข้าม** ด้วย ไม่งั้นผู้ใช้ไม่รู้ว่าอีกกี่คนและเพราะอะไร
    const skippedNote = res.skipped.length
      ? ` · ข้าม ${res.skipped.length} คนที่มียอดค้างน้อยกว่า 0.01 บาท: ${res.skipped
          .map((s) => s.student_name || `#${s.student_no ?? s.student_id}`)
          .join(', ')}`
      : ''

    const summary =
      `ออกใหม่ ${res.issued_count} ฉบับ (1 คน = 1 ใบ) · เลขที่ล่าสุด ${nos[nos.length - 1] ?? '—'}` +
      skippedNote +
      (canDownload ? ` · รวมเป็นไฟล์เดียวได้ (${nos.length} หน้า — หน้าละคน) เหมาะสำหรับพิมพ์แจก` : '')

    const after = canDownload
      ? await dialog.confirm('ออกใบแจ้งหนี้เรียบร้อย', summary, {
          icon: 'success',
          confirmButtonText: 'ดาวน์โหลด PDF รวม',
          cancelButtonText: 'ปิด',
        })
      : await dialog.alert('ออกใบแจ้งหนี้เรียบร้อย', summary, 'success')
    if (canDownload && after.isConfirmed) await downloadCombined('invoices', nos)
    selectedIds.value = []
  } catch (error: unknown) {
    dialog.close()
    void dialog.alert(
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
    return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกเอกสารได้', 'error')
  }
  if (selectedIds.value.length === 0) {
    return dialog.alert('อ๊ะ!', 'กรุณาติ๊กเลือกนักเรียนที่ต้องการออกใบแจ้งหนี้', 'warning')
  }
  if (selectedIds.value.length > ISSUE_PER_REQUEST_MAX) {
    return dialog.alert(
      'เลือกไว้มากเกินไป',
      `เลือก ${selectedIds.value.length} คน แต่ระบบออกได้ครั้งละไม่เกิน ${ISSUE_PER_REQUEST_MAX} ใบ`,
      'warning',
    )
  }
  return runInvoiceIssue(
    () =>
      FinanceService.issueInvoices(currentRoomId, {
        student_ids: [...selectedIds.value],
        user_name: currentUserName,
      }),
    `จะออกใบแจ้งหนี้ ${selectedIds.value.length} ฉบับ (1 คน = 1 ใบ) · ` +
      `ยอดค้างชำระรวมที่จะเรียกเก็บ ${formatAmount(selectedInvoiceAmount.value)} บาท`,
    'ออกใบแจ้งหนี้ที่เลือก?'
  )
}

/**
 * ออกใบแจ้งหนี้ให้ **ทุกคนที่มียอดค้างในห้อง** — ระบบเป็นคนหาว่าใครค้าง
 * ⚠️ จำนวน/ยอดที่อ้างในข้อความมาจากรายการที่โหลดอยู่ ⇒ ถ้ากำลังกรองอยู่ ข้อความจะบอก
 *    "ทุกคนที่มียอดค้างชำระขณะนี้" ไม่ผูกตัวเลขที่อาจไม่ครบทั้งห้อง
 */
const handleIssueRoomInvoices = () => {
  if (!canManageFinance.value) {
    return dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกเอกสารได้', 'error')
  }
  // ปฏิเสธเฉพาะเมื่อ **ไม่ได้กรองอะไรเลย** และยอดค้างทั้งห้องเป็นศูนย์จริง
  if (!hasFilters.value && roomOutstanding.value <= 0) {
    return dialog.alert('ไม่มีใครค้างชำระ', 'ห้องนี้ไม่มีนักเรียนที่มียอดค้างชำระในขณะนี้', 'info')
  }
  const scope = hasFilters.value
    ? 'ทุกคนในห้องที่มียอดค้างชำระขณะนี้'
    : `${itemsWithDebt.value.length} คนที่มียอดค้างชำระขณะนี้`
  return runInvoiceIssue(
    () => FinanceService.issueRoomInvoices(currentRoomId, { user_name: currentUserName }),
    `จะออกใบแจ้งหนี้ให้ ${scope} (1 คน = 1 ใบ) · ` +
      `ยอดค้างชำระรวมในรายการที่แสดง ${formatAmount(roomOutstanding.value)} บาท`,
    'ออกใบแจ้งหนี้ทั้งห้อง?'
  )
}

// ─────────────────────────────────────────────────────── หักเครดิตหลายคน (P3.5)
const isRoundOpen = ref(false)
const isRoundPlanLoading = ref(false)
const roundPlan = ref<CreditApplyPlan | null>(null)
const roundPeople = ref<FinancePerson[]>([])
const roundGuard = createLatestGuard()

/** เปิดหน้าตรวจข้อเสนอของนักเรียนที่ติ๊ก — ยังไม่เขียนอะไร */
const openRoundPreview = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่หักเครดิตได้', 'error')
    return
  }
  if (!selectedIds.value.length) {
    void dialog.alert('ยังไม่ได้เลือกนักเรียน', 'ติ๊กนักเรียนอย่างน้อย 1 คนก่อน', 'info')
    return
  }

  const token = roundGuard.begin()
  isRoundPlanLoading.value = true
  try {
    const [plan, people] = await Promise.all([
      FinanceService.getCreditPlan(currentRoomId, [...selectedIds.value]),
      FinanceService.getPeople(currentRoomId, { active: true }),
    ])
    if (!roundGuard.isCurrent(token)) return
    // 🛡️ ไม่มีใครมีบิลให้หักเลย ⇒ ไม่เปิดแผ่นว่าง ๆ
    if (plan.total_applied <= 0) {
      void dialog.alert(
        'ไม่มีบิลให้หัก',
        'นักเรียนที่เลือกยังไม่มีบิลค้างชำระ — จึงไม่มีอะไรต้องทำ',
        'info',
      )
      return
    }
    roundPlan.value = plan
    roundPeople.value = people
    isRoundOpen.value = true
  } catch (error: unknown) {
    if (!roundGuard.isCurrent(token)) return
    void dialog.alert(
      'ดูข้อเสนอการหักไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    if (roundGuard.isCurrent(token)) isRoundPlanLoading.value = false
  }
}

/** แผ่นรายงานผลสำเร็จ — ปิดแผ่น ล้างที่ติ๊ก แล้วโหลดยอดใหม่ */
const onRoundApplied = (res: CreditRoundResponse) => {
  isRoundOpen.value = false
  roundPlan.value = null
  selectedIds.value = []
  const skipped = res.skipped.length
  void dialog.fire({
    icon: 'success',
    title: res.reused ? 'รอบนี้ถูกบันทึกไว้แล้ว' : 'หักเครดิตหลายคนเรียบร้อย',
    text:
      `หักเครดิต ${res.events.length} คน รวม ${formatMoney(res.total_applied)} · ` +
      `คงเหลือรวม ${formatMoney(res.total_balance_after)}` +
      (skipped ? ` · ข้าม ${skipped} คน (ไม่มีบิลค้างหรือเครดิตไม่พอ)` : ''),
  })
  roundPeople.value = []
  void loadAccountsList()
}

const closeRound = () => {
  isRoundOpen.value = false
  // คงที่ติ๊กไว้โดยเจตนา: ถ้าปิดเพราะ 409 ผู้ใช้ต้องเริ่มใหม่ แต่ถ้าเปลี่ยนใจ
  // การเลือกเดิมยังมีประโยชน์ให้ลองใหม่ ⇒ ล้างเฉพาะตอนสำเร็จ
}

onMounted(() => {
  void loadAccountOptions()
  void loadAccountsList()
})
</script>

<template>
  <div class="space-y-3">
    <PageIntro
      description="ยอดค้าง เครดิต และรายการเดินบัญชีของนักเรียนแต่ละคน — รับเงิน เติมเครดิต และออกใบแจ้งหนี้ได้จากหน้านี้"
    >
      <template #actions>
        <RouterLink to="/finance/aging" class="btn-ghost-ui">
          <i class="bi bi-graph-up" aria-hidden="true"></i>
          รายงานอายุหนี้
        </RouterLink>
      </template>
    </PageIntro>

    <!-- ══════════════════════ แท็บสถานะ (ผูกกับ route.query) ══════════════════════ -->
    <AppTabs
      v-model="statusFilter"
      :tabs="STATUS_TABS"
      group-label="กรองสถานะบัญชี"
      variant="segmented"
    />

    <!-- ══════════════════════ ตัวกรอง ══════════════════════ -->
    <div class="flex flex-wrap items-center gap-2">
      <select
        v-model="fundTypeFilter"
        class="field w-auto min-w-36 text-sm"
        aria-label="กรองประเภทเงิน"
      >
        <option value="">ทุกประเภทเงิน</option>
        <option value="room_fund">เงินห้อง</option>
        <option value="pass_through">เก็บแทน / ผ่านมือ</option>
      </select>

      <input
        v-model="searchInput"
        type="search"
        class="field w-full text-sm sm:w-56"
        placeholder="ค้นหาชื่อ / เลขที่นักเรียน"
        aria-label="ค้นหาบัญชีรายบุคคล"
      />

      <p v-if="asOf && !isLoading" class="ms-auto text-caption text-ink-3">
        <i class="bi bi-calendar-check me-1" aria-hidden="true"></i>
        ข้อมูล ณ {{ formatThaiDate(asOf) }}
      </p>
    </div>

    <!-- ══════════════════════ 📊 KPI ของรายการที่กรองอยู่ ══════════════════════ -->
    <div
      v-if="!isLoading && !hasError && items.length"
      class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5"
    >
      <div class="page-card p-3">
        <p class="text-caption font-bold text-ink-3">ยอดค้างรวม</p>
        <p class="num mt-0.5 text-lg font-bold text-danger-600">
          {{ formatMoney(totals.outstanding) }}
        </p>
      </div>
      <div class="page-card p-3">
        <p class="text-caption font-bold text-ink-3">เกินกำหนด</p>
        <p class="num mt-0.5 text-lg font-bold text-danger-700">
          {{ formatMoney(totals.overdue) }}
        </p>
      </div>
      <div class="page-card p-3">
        <p class="text-caption font-bold text-ink-3">ยังไม่ถึงกำหนด</p>
        <p class="num mt-0.5 text-lg font-bold text-ink-2">
          {{ formatMoney(totals.upcoming) }}
        </p>
      </div>
      <div class="page-card p-3">
        <p class="text-caption font-bold text-ink-3">เครดิตคงเหลือ</p>
        <p class="num mt-0.5 text-lg font-bold text-ok-700">
          {{ formatMoney(totals.credit) }}
        </p>
      </div>
      <div class="page-card p-3">
        <p class="text-caption font-bold text-ink-3">เครดิตใช้ได้</p>
        <p class="num mt-0.5 text-lg font-bold text-ink-2">
          {{ formatMoney(totals.ready) }}
        </p>
      </div>
    </div>

    <!-- ══════════════════════ 💳 งานรวบยอด (เฉพาะผู้มีสิทธิ์เขียน) ══════════════════════ -->
    <div
      v-if="canManageFinance && !isLoading && !hasError && items.length"
      class="flex flex-wrap items-center justify-between gap-2 rounded-control border border-line px-3 py-2"
    >
      <div class="flex flex-wrap items-center gap-2">
        <label class="flex items-center gap-2 text-caption text-ink-2">
          <input
            type="checkbox"
            class="h-5 w-5 accent-brand-700"
            :checked="allSelected"
            aria-label="เลือกทุกคนในรายการ"
            @change="toggleSelectAll"
          />
          เลือกทั้งหมด
        </label>
        <span v-if="selectedCount" class="text-caption font-bold text-ink">
          · เลือกแล้ว {{ selectedCount }} คน
        </span>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="btn-ghost-ui"
          :disabled="!selectedCount"
          @click="openBulkReceive"
        >
          <i class="bi bi-cash-stack" aria-hidden="true"></i>
          รับเงินที่เลือก
        </button>
        <button
          type="button"
          class="btn-ghost-ui"
          :disabled="!selectedCount || isIssuingInvoices"
          @click="handleIssueSelectedInvoices"
        >
          <i class="bi bi-file-earmark-text" aria-hidden="true"></i>
          ออกใบแจ้งหนี้ที่เลือก
        </button>
        <button
          type="button"
          class="btn-ghost-ui"
          :disabled="isIssuingInvoices"
          @click="handleIssueRoomInvoices"
        >
          <i class="bi bi-file-earmark-text" aria-hidden="true"></i>
          ออกใบแจ้งหนี้ทั้งห้อง
        </button>
        <button
          type="button"
          class="btn-primary"
          :disabled="!selectedCount || isRoundPlanLoading"
          @click="openRoundPreview"
        >
          <i class="bi bi-scissors" aria-hidden="true"></i>
          {{ isRoundPlanLoading ? 'กำลังดูข้อเสนอ…' : 'ตัดเครดิตที่เลือก' }}
        </button>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-20" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดบัญชีรายบุคคลไม่สำเร็จ"
      @retry="loadAccountsList"
    />

    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      icon="bi-emoji-smile"
      title="ไม่พบบัญชีที่ตรงกับตัวกรอง"
      :hint="hasFilters ? 'ลองปรับตัวกรองหรือคำค้น' : 'ห้องนี้ยังไม่มีนักเรียนที่มีรายการการเงิน'"
    />

    <template v-else>
      <!-- ══════════════════════ 📱 มือถือ: การ์ด ══════════════════════ -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="item in items"
          :key="item.student_id"
          class="page-card relative block p-4 transition-colors hover:bg-canvas"
          role="link"
          tabindex="0"
          :aria-label="`เปิดบัญชีของ ${item.name}`"
          @click="openAccount(item.student_id)"
          @keydown.enter="openAccount(item.student_id)"
        >
          <!-- ⋮ มุมขวาบน — `@click.stop` กันไม่ให้คลิกเมนูแล้วทะลุไปเปิดบัญชี -->
          <div class="absolute right-1 top-1" @click.stop>
            <RowActionMenu
              :label="`ตัวเลือกของ ${item.name}`"
              :items="menuItems(item)"
              @select="handleRowAction(item, $event)"
            />
          </div>

          <!-- pr-11 = เผื่อที่ให้ปุ่ม ⋮ (44px) ไม่ทับยอดค้าง -->
          <div class="flex items-start justify-between gap-3 pr-11">
            <div class="flex min-w-0 items-center gap-2">
              <input
                v-if="canManageFinance"
                type="checkbox"
                class="h-5 w-5 shrink-0 accent-brand-700"
                :checked="selectedIds.includes(item.student_id)"
                :aria-label="`เลือก ${item.name}`"
                @click.stop
                @change="toggleSelect(item.student_id)"
              />
              <span class="chip num shrink-0 bg-canvas text-ink-2">#{{ item.student_no }}</span>
              <h2 class="font-display min-w-0 truncate text-base font-bold text-ink-1">
                {{ item.name }}
              </h2>
            </div>
            <div class="shrink-0 text-right">
              <p class="text-xs font-bold text-ink-3">ค้างทั้งหมด</p>
              <p
                class="font-display num mt-0.5 whitespace-nowrap text-lg font-bold"
                :class="isPositive(item.outstanding_total) ? 'text-danger-600' : 'text-ok-600'"
              >
                {{ money(item.outstanding_total) }}
              </p>
            </div>
          </div>

          <div class="mt-2.5 grid grid-cols-3 gap-2 border-t border-line pt-2.5">
            <div>
              <p class="text-caption font-bold text-ink-3">เกินกำหนด</p>
              <p
                class="num mt-0.5 text-sm font-bold"
                :class="isPositive(item.overdue_total) ? 'text-danger-700' : 'text-ink-2'"
              >
                {{ money(item.overdue_total) }}
              </p>
            </div>
            <div>
              <p class="text-caption font-bold text-ink-3">ยังไม่ถึงกำหนด</p>
              <p class="num mt-0.5 text-sm font-bold text-ink-2">
                {{ money(item.upcoming_total) }}
              </p>
            </div>
            <div>
              <p class="text-caption font-bold text-ink-3">เครดิต</p>
              <p
                class="num mt-0.5 text-sm font-bold"
                :class="isPositive(item.credit_balance) ? 'text-ok-700' : 'text-ink-2'"
              >
                {{ money(item.credit_balance) }}
              </p>
            </div>
          </div>

          <!-- รับเงินชิดขวาสุด — ไม่มีปุ่ม "เปิดบัญชี" เพราะกดการ์ดก็เข้าไปแล้ว -->
          <div
            v-if="canManageFinance"
            class="mt-2.5 flex items-center justify-end border-t border-line pt-2.5"
          >
            <button type="button" class="btn-ghost-ui" @click.stop="openReceive(item)">
              <i class="bi bi-cash-coin" aria-hidden="true"></i>
              รับเงิน
            </button>
          </div>
        </div>
      </div>

      <!-- ══════════════════════ 🖥️ เดสก์ท็อป: ตาราง ══════════════════════ -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-10">
                  <span class="sr-only">เลือก</span>
                </th>
                <th class="w-20">เลขที่</th>
                <th>ชื่อนักเรียน</th>
                <th class="text-right">ค้างทั้งหมด</th>
                <th class="text-right">เกินกำหนด</th>
                <th class="text-right">ยังไม่ถึงกำหนด</th>
                <th class="text-right">เครดิตคงเหลือ</th>
                <th class="text-right">ใช้ได้</th>
                <th class="text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.student_id"
                class="cursor-pointer"
                @click="openAccount(item.student_id)"
              >
                <td @click.stop>
                  <input
                    v-if="canManageFinance"
                    type="checkbox"
                    class="h-5 w-5 accent-brand-700"
                    :checked="selectedIds.includes(item.student_id)"
                    :aria-label="`เลือก ${item.name}`"
                    @change="toggleSelect(item.student_id)"
                  />
                </td>
                <td class="num font-bold text-ink-3">#{{ item.student_no }}</td>
                <td class="font-bold text-ink-1">{{ item.name }}</td>
                <td class="whitespace-nowrap text-right">
                  <span
                    class="num font-bold"
                    :class="isPositive(item.outstanding_total) ? 'text-danger-600' : 'text-ok-600'"
                  >
                    {{ money(item.outstanding_total) }}
                  </span>
                </td>
                <td class="whitespace-nowrap text-right">
                  <span
                    class="num font-bold"
                    :class="isPositive(item.overdue_total) ? 'text-danger-700' : 'text-ink-2'"
                  >
                    {{ money(item.overdue_total) }}
                  </span>
                </td>
                <td class="num whitespace-nowrap text-right text-ink-2">
                  {{ money(item.upcoming_total) }}
                </td>
                <td class="num whitespace-nowrap text-right">
                  <span
                    class="font-bold"
                    :class="isPositive(item.credit_balance) ? 'text-ok-700' : 'text-ink-2'"
                  >
                    {{ money(item.credit_balance) }}
                  </span>
                </td>
                <td class="num whitespace-nowrap text-right text-ink-2">
                  {{ money(item.ready_to_apply) }}
                </td>
                <td @click.stop>
                  <div class="flex items-center justify-end gap-1">
                    <button
                      v-if="canManageFinance"
                      type="button"
                      class="btn-ghost-ui"
                      @click="openReceive(item)"
                    >
                      <i class="bi bi-cash-coin" aria-hidden="true"></i>
                      รับเงิน
                    </button>
                    <RouterLink
                      :to="{
                        name: 'finance-individual-account-detail',
                        params: { studentId: item.student_id },
                      }"
                      class="btn-ghost-ui"
                      :aria-label="`เปิดบัญชีของ ${item.name}`"
                    >
                      <i class="bi bi-chevron-right" aria-hidden="true"></i>
                    </RouterLink>
                    <RowActionMenu
                      :label="`ตัวเลือกของ ${item.name}`"
                      :items="menuItems(item)"
                      @select="handleRowAction(item, $event)"
                    />
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ══════════════════════ โมดัล/ชีต ══════════════════════ -->
    <ReceiveMoneyModal
      v-if="receiveTarget"
      :open="receiveOpen"
      :student-id="receiveTarget.student_id"
      :student-name="receiveTarget.name"
      @close="receiveOpen = false"
      @saved="onReceiveSaved"
    />

    <BulkReceiveSheet
      :open="bulkReceiveOpen"
      :student-ids="selectedIds"
      @close="bulkReceiveOpen = false"
      @saved="onBulkSaved"
    />

    <BulkCreditSheet
      :open="isRoundOpen"
      :plan="roundPlan"
      :receiver-options="roundPeople"
      @close="closeRound"
      @applied="onRoundApplied"
    />

    <CreditTopUpModal
      :open="topUpOpen"
      :student="topUpTarget"
      :accounts="accounts"
      @close="topUpOpen = false"
      @saved="onCreditChanged"
    />

    <CreditApplyModal
      :open="applyOpen"
      :student="applyTarget"
      :accounts="accounts"
      @close="applyOpen = false"
      @applied="onCreditChanged"
    />

    <CreditHistoryModal
      :open="historyOpen"
      :student="historyTarget"
      :can-manage="canManageFinance"
      @close="historyOpen = false"
      @changed="onCreditChanged"
      @topup="onHistoryTopUp"
      @apply="onHistoryApply"
    />
  </div>
</template>
