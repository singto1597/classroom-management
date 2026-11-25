<script setup lang="ts">
/**
 * ⚖️ ค่าปรับ — รายการ · รออนุมัติ · ประเภทความผิด (Phase 5)
 *
 * ════════════════════════════════════════════════════════════════════════════
 * 🔒 สิทธิ์ — บทเรียนเดียวกับ `CreditList.vue`/`DebtorList.vue`
 * ════════════════════════════════════════════════════════════════════════════
 * ฝั่ง backend: **อ่าน** = สมาชิกห้อง (นักเรียนเห็นเฉพาะของตัวเอง — กรองให้แล้ว)
 *              **เขียน** = `MANAGE_FINANCE`
 * ⇒ ปุ่มเขียนทุกปุ่ม gate ด้วย `canManageFinance` **ไม่ใช่ `isAdmin`**
 *
 * ════════════════════════════════════════════════════════════════════════════
 * ⚙️ กติกาหลัก
 * ════════════════════════════════════════════════════════════════════════════
 * - ออกค่าปรับหลายคนในการกดครั้งเดียว → 1 คน = 1 บิล = 1 ใบ INV-
 *   🔑 `idempotency_key` สร้างตอนเปิดแผ่นและคงเดิมตลอดรอบ (กดซ้ำไม่เกิดค่าปรับซ้ำ)
 * - ห้ามอนุมัติคำขอของตัวเอง — backend ตอบ 403 ⇒ หน้าจอซ่อนปุ่มเมื่อรู้ล่วงหน้า
 *   (รู้ได้เฉพาะ "ผู้ขอ" จาก `requested_by`; กรณี "ผู้ออกค่าปรับ" ให้ backend เป็นคนกัน)
 * - ยอดใน KPI มาจาก `getFineSummary` ทั้งหมด — ไม่รวมเองฝั่งจอ
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  BasicStudent,
  Fine,
  FineSummary,
  FineType,
  FineWaiver,
  FineRefund,
  FineListQuery,
} from '@/types/finance'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import AppTabs from '@/components/ui/AppTabs.vue'
import AppButton from '@/components/ui/AppButton.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'
import AppChip from '@/components/ui/AppChip.vue'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import { formatThaiDate, todayIso } from '@/utils/datetime'
import { useDialog } from '@/composables/useDialog'
import {
  FINE_STATUS_LABELS,
  WAIVER_CATEGORY_LABELS,
  fineStatusLabel,
  fineStatusTone,
} from '@/constants/financeFines'

const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const currentUserId = Number(authStore.userId)
/** 🔒 ปุ่ม **เขียน** ใช้ตัวนี้ — ไม่ใช่ `isAdmin` (ดูหัวไฟล์) */
const canManageFinance = computed(() => authStore.canManageFinance)

// ─────────────────────────────────────────────────────── สถานะหลักของหน้า
// ⚠️ เก็บเป็น `string` ไม่ใช่ union: `AppTabs` emit ค่าเป็น string ธรรมดา
const activeTab = ref('fines')

const fines = ref<Fine[]>([])
const fineTotal = ref(0)
const summary = ref<FineSummary | null>(null)
const types = ref<FineType[]>([])
const waivers = ref<FineWaiver[]>([])
const refunds = ref<FineRefund[]>([])
const students = ref<BasicStudent[]>([])
const accounts = ref<Account[]>([])

const isLoading = ref(true)
const hasError = ref(false)

// ตัวกรองรายการ
const statusFilter = ref('')
const typeFilter = ref('')
const searchInput = ref('')

const listGuard = createLatestGuard()

const activeTypes = computed(() => types.value.filter((t) => t.is_active))

const pendingApprovalsCount = computed(() => waivers.value.length + refunds.value.length)

const tabs = computed(() => [
  { value: 'fines', label: 'รายการค่าปรับ', count: fineTotal.value },
  { value: 'approvals', label: 'รออนุมัติ', count: pendingApprovalsCount.value },
  { value: 'types', label: 'ประเภทความผิด', count: types.value.length },
])

const buildQuery = (): FineListQuery => {
  const q: FineListQuery = { limit: 500 }
  if (statusFilter.value) q.status = statusFilter.value
  if (typeFilter.value) q.fine_type_id = Number(typeFilter.value)
  const search = searchInput.value.trim()
  if (search) q.search = search
  return q
}

const loadFines = async () => {
  const token = listGuard.begin()
  isLoading.value = true
  hasError.value = false
  try {
    const [list, sum] = await Promise.all([
      FinanceService.listFines(currentRoomId, buildQuery()),
      FinanceService.getFineSummary(currentRoomId),
    ])
    if (!listGuard.isCurrent(token)) return
    fines.value = list.fines
    fineTotal.value = list.total
    summary.value = sum
  } catch {
    if (!listGuard.isCurrent(token)) return
    hasError.value = true
  } finally {
    if (listGuard.isCurrent(token)) isLoading.value = false
  }
}

const loadApprovals = async () => {
  try {
    const [w, r] = await Promise.all([
      FinanceService.listWaivers(currentRoomId, { status: 'pending' }),
      FinanceService.listRefunds(currentRoomId, { status: 'pending' }),
    ])
    waivers.value = w.waivers
    refunds.value = r.refunds
  } catch {
    // แท็บนี้เป็นของแถม — ไม่ทำให้ทั้งหน้าล้ม (รายการหลักยังใช้ได้)
    waivers.value = []
    refunds.value = []
  }
}

const loadTypes = async () => {
  try {
    types.value = await FinanceService.getFineTypes(currentRoomId, false)
  } catch {
    types.value = []
  }
}

const loadLookups = async () => {
  try {
    const [s, a] = await Promise.all([
      FinanceService.getActiveStudents(currentRoomId),
      FinanceService.getAccounts(currentRoomId),
    ])
    students.value = s
    accounts.value = a
  } catch {
    students.value = []
    accounts.value = []
  }
}

const reloadAll = async () => {
  await Promise.all([loadFines(), loadApprovals(), loadTypes()])
}

onMounted(async () => {
  await Promise.all([loadFines(), loadApprovals(), loadTypes(), loadLookups()])
})

watch([statusFilter, typeFilter], () => void loadFines())

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchInput, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void loadFines(), 300)
})

// ════════════════════════════════════════════════════════════════════════════
// ⚖️ ออกค่าปรับ (หลายคน)
// ════════════════════════════════════════════════════════════════════════════
const isIssueOpen = ref(false)
const isIssuing = ref(false)
const issueTypeId = ref('')
const issueIncident = ref('')
const issueDue = ref('')
const issueReason = ref('')
const issueNote = ref('')
const issueEvidence = ref('')
const issueAmountOverride = ref('')
const issueSelectedIds = ref<number[]>([])
const issueKey = ref('')

const issueType = computed(() => activeTypes.value.find((t) => t.id === Number(issueTypeId.value)) ?? null)

const addDaysIso = (iso: string, days: number): string => {
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  const next = new Date(Date.UTC(y, m - 1, d + days))
  return next.toISOString().slice(0, 10)
}

const syncDueFromType = () => {
  const type = issueType.value
  if (!type) return
  issueDue.value = addDaysIso(issueIncident.value || todayIso(), type.default_due_days)
}

const openIssue = () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกค่าปรับได้', 'error')
    return
  }
  issueSelectedIds.value = []
  issueReason.value = ''
  issueNote.value = ''
  issueEvidence.value = ''
  issueAmountOverride.value = ''
  issueIncident.value = todayIso()
  issueTypeId.value = activeTypes.value[0]?.id.toString() ?? ''
  syncDueFromType()
  try {
    issueKey.value = newIdempotencyKey()
  } catch (error: unknown) {
    void dialog.alert(
      'ทำรายการไม่ได้',
      error instanceof Error ? error.message : 'สร้างรหัสกันบันทึกซ้ำไม่สำเร็จ',
      'error',
    )
    return
  }
  isIssueOpen.value = true
}

const toggleIssueStudent = (studentId: number) => {
  const i = issueSelectedIds.value.indexOf(studentId)
  if (i === -1) issueSelectedIds.value.push(studentId)
  else issueSelectedIds.value.splice(i, 1)
}

const issueOverrideNumber = computed(() => {
  const n = Number(issueAmountOverride.value)
  return Number.isFinite(n) && n > 0 ? roundMoney(n) : 0
})

const issuePerStudent = computed(
  () => issueOverrideNumber.value || (issueType.value?.default_amount ?? 0),
)

const issueTotalPreview = computed(() =>
  roundMoney(issuePerStudent.value * issueSelectedIds.value.length),
)

const issueAllSelected = computed(
  () =>
    students.value.length > 0 && issueSelectedIds.value.length === students.value.length,
)

const toggleIssueAll = () => {
  issueSelectedIds.value = issueAllSelected.value ? [] : students.value.map((s) => s.id)
}

const handleIssue = async () => {
  if (!canManageFinance.value) return
  if (!issueTypeId.value) {
    void dialog.alert('อ๊ะ!', 'กรุณาเลือกประเภทความผิด', 'warning')
    return
  }
  if (issueSelectedIds.value.length === 0) {
    void dialog.alert('อ๊ะ!', 'กรุณาติ๊กเลือกนักเรียนอย่างน้อย 1 คน', 'warning')
    return
  }
  if (!issueReason.value.trim()) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกเหตุผล (ต้องมีเพื่อเป็นหลักฐาน)', 'warning')
    return
  }
  const override = issueAmountOverride.value ? issueOverrideNumber.value : 0
  if (issueAmountOverride.value && override <= 0) {
    void dialog.alert('อ๊ะ!', 'ยอดเงินที่กรอกต้องมากกว่า 0', 'warning')
    return
  }

  isIssuing.value = true
  try {
    const res = await FinanceService.issueFines(currentRoomId, {
      fine_type_id: Number(issueTypeId.value),
      students: issueSelectedIds.value.map((studentId) => ({
        student_id: studentId,
        ...(override > 0 ? { amount: override } : {}),
      })),
      incident_date: issueIncident.value,
      due_date: issueDue.value || null,
      reason: issueReason.value.trim(),
      evidence_url: issueEvidence.value.trim() || null,
      note: issueNote.value.trim() || null,
      idempotency_key: issueKey.value,
      user_name: currentUserName,
    })

    const nos = res.invoice_nos.length > 0 ? ` · ใบแจ้งหนี้ ${res.invoice_nos.join(', ')}` : ''
    await dialog.fire({
      icon: 'success',
      title: res.reused ? 'รายการนี้ถูกบันทึกไว้แล้ว' : 'ออกค่าปรับเรียบร้อย',
      text: res.reused
        ? `ระบบตรวจพบว่าเป็นการกดซ้ำจากรายการเดิม จึงไม่ออกซ้ำ · รวม ${formatMoney(res.batch.total_amount)}`
        : `ออกค่าปรับ ${res.batch.student_count} คน · รวม ${formatMoney(res.batch.total_amount)}${nos}`,
    })

    isIssueOpen.value = false
    issueKey.value = ''
    await reloadAll()
  } catch (error: unknown) {
    void dialog.alert(
      'ออกค่าปรับไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีรายการใดถูกบันทึก',
      'error',
    )
  } finally {
    isIssuing.value = false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 🗂️ ประเภทความผิด (create/update)
// ════════════════════════════════════════════════════════════════════════════
const isTypeOpen = ref(false)
const isSavingType = ref(false)
const editingType = ref<FineType | null>(null)
const typeName = ref('')
const typeAmount = ref('')
const typeDays = ref('7')
const typeDescription = ref('')
const typeSort = ref('0')
const typeActive = ref(true)

const openTypeCreate = () => {
  if (!canManageFinance.value) return
  editingType.value = null
  typeName.value = ''
  typeAmount.value = ''
  typeDays.value = '7'
  typeDescription.value = ''
  typeSort.value = '0'
  typeActive.value = true
  isTypeOpen.value = true
}

const openTypeEdit = (type: FineType) => {
  if (!canManageFinance.value) return
  editingType.value = type
  typeName.value = type.name
  typeAmount.value = type.default_amount.toString()
  typeDays.value = type.default_due_days.toString()
  typeDescription.value = type.description ?? ''
  typeSort.value = type.sort_order.toString()
  typeActive.value = type.is_active
  isTypeOpen.value = true
}

const handleSaveType = async () => {
  if (!canManageFinance.value) return
  if (!typeName.value.trim()) {
    void dialog.alert('อ๊ะ!', 'กรุณากรอกชื่อประเภทความผิด', 'warning')
    return
  }
  const amount = Number(typeAmount.value)
  const days = Number(typeDays.value)
  if (!Number.isFinite(amount) || amount < 0) {
    void dialog.alert('อ๊ะ!', 'อัตราค่าปรับต้องเป็นตัวเลข ≥ 0', 'warning')
    return
  }
  if (!Number.isInteger(days) || days < 0 || days > 365) {
    void dialog.alert('อ๊ะ!', 'จำนวนวันกำหนดชำระต้องเป็นจำนวนเต็ม 0–365', 'warning')
    return
  }

  isSavingType.value = true
  try {
    if (editingType.value) {
      await FinanceService.updateFineType(currentRoomId, editingType.value.id, {
        name: typeName.value.trim(),
        default_amount: roundMoney(amount),
        default_due_days: days,
        description: typeDescription.value.trim() || null,
        sort_order: Number(typeSort.value) || 0,
        is_active: typeActive.value,
      })
    } else {
      await FinanceService.createFineType(currentRoomId, {
        name: typeName.value.trim(),
        default_amount: roundMoney(amount),
        default_due_days: days,
        description: typeDescription.value.trim() || null,
        sort_order: Number(typeSort.value) || 0,
      })
    }
    await dialog.alert('บันทึกแล้ว', 'ประเภทความผิดถูกบันทึกเรียบร้อย', 'success')
    isTypeOpen.value = false
    await loadTypes()
  } catch (error: unknown) {
    void dialog.alert(
      'บันทึกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  } finally {
    isSavingType.value = false
  }
}

const handleDeleteType = async (type: FineType) => {
  if (!canManageFinance.value) return
  const ok = await dialog.confirm(
    'ลบประเภทความผิดนี้?',
    `"${type.name}" จะหายจากรายการเลือก — ค่าปรับที่ออกไปแล้วยังแสดงชื่อเดิมได้`,
    { danger: true, confirmButtonText: 'ลบ' },
  )
  if (!ok.isConfirmed) return
  try {
    await FinanceService.deleteFineType(currentRoomId, type.id)
    await loadTypes()
    dialog.notify('ลบประเภทความผิดแล้ว')
  } catch (error: unknown) {
    void dialog.alert(
      'ลบไม่สำเร็จ',
      error instanceof Error ? error.message : 'ประเภทนี้อาจถูกใช้งานอยู่',
      'error',
    )
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ✅ อนุมัติ / ปฏิเสธ คำขอยกเว้น และคำขอคืนเงิน
// ════════════════════════════════════════════════════════════════════════════
const isSelfRequested = (requestedBy: number | null) =>
  requestedBy !== null && currentUserId > 0 && requestedBy === currentUserId

const accountName = (accountId: number) =>
  accounts.value.find((a) => a.id === accountId)?.account_name ?? `กระเป๋า #${accountId}`

const handleWaiverDecision = async (waiver: FineWaiver, action: 'approve' | 'reject') => {
  if (!canManageFinance.value) return
  const verb = action === 'approve' ? 'อนุมัติ' : 'ปฏิเสธ'
  const ok = await dialog.confirm(
    `${verb}คำขอยกเว้น ${formatMoney(waiver.amount)}?`,
    action === 'approve'
      ? 'การอนุมัติจะลดยอดที่ต้องเก็บของบิลนี้ และลงบัญชีส่วนลด/หนี้สูญให้ทันที'
      : 'คำขอจะถูกปิดโดยไม่กระทบยอดค่าปรับ',
    { danger: action === 'reject', confirmButtonText: verb },
  )
  if (!ok.isConfirmed) return
  try {
    if (action === 'approve') {
      await FinanceService.approveWaiver(currentRoomId, waiver.id, { user_name: currentUserName })
    } else {
      await FinanceService.rejectWaiver(currentRoomId, waiver.id, { user_name: currentUserName })
    }
    dialog.notify(`${verb}คำขอยกเว้นแล้ว`)
    await Promise.all([loadApprovals(), loadFines()])
  } catch (error: unknown) {
    void dialog.alert(
      `${verb}ไม่สำเร็จ`,
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  }
}

const handleRefundDecision = async (refund: FineRefund, action: 'approve' | 'reject') => {
  if (!canManageFinance.value) return
  const verb = action === 'approve' ? 'อนุมัติ' : 'ปฏิเสธ'
  const ok = await dialog.confirm(
    `${verb}คำขอคืนเงิน ${formatMoney(refund.amount)}?`,
    action === 'approve'
      ? `เงินจะถูกจ่ายออกจาก ${accountName(refund.account_id)} และออกใบสำคัญจ่าย (PV-) ให้ทันที`
      : 'คำขอจะถูกปิดโดยไม่จ่ายเงิน',
    { danger: action === 'reject', confirmButtonText: verb },
  )
  if (!ok.isConfirmed) return
  try {
    if (action === 'approve') {
      const res = await FinanceService.approveRefund(currentRoomId, refund.id, {
        user_name: currentUserName,
      })
      dialog.notify(res.receipt_no ? `คืนเงินแล้ว · PV ${res.receipt_no}` : 'คืนเงินแล้ว')
    } else {
      await FinanceService.rejectRefund(currentRoomId, refund.id, { user_name: currentUserName })
      dialog.notify('ปฏิเสธคำขอคืนเงินแล้ว')
    }
    await Promise.all([loadApprovals(), loadFines()])
  } catch (error: unknown) {
    void dialog.alert(
      `${verb}ไม่สำเร็จ`,
      error instanceof Error ? error.message : 'ไม่มีการเปลี่ยนแปลงใดถูกบันทึก',
      'error',
    )
  }
}
</script>

<template>
  <div class="space-y-4">
    <PageIntro
      description="ค่าปรับรายครั้ง — ออกหลายคนพร้อมกันได้ · ทุกใบรวมในยอดค้างชำระและรายงานอายุหนี้"
    >
      <template #actions>
        <AppButton v-if="canManageFinance" variant="primary" @click="openIssue">
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          ออกค่าปรับ
        </AppButton>
        <AppButton variant="secondary" to="/finance/aging">
          <i class="bi bi-graph-up" aria-hidden="true"></i>
          รายงานอายุหนี้
        </AppButton>
      </template>
    </PageIntro>

    <!-- ══════════════════════ KPI ══════════════════════ -->
    <div v-if="summary" class="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
      <div class="page-card p-3.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-cash-stack text-brand-700" aria-hidden="true"></i>
          ค้างชำระรวม
        </p>
        <p class="num mt-1.5 text-lg font-bold text-ink sm:text-2xl">
          {{ formatMoney(summary.totals.outstanding_total) }}
        </p>
        <p class="mt-0.5 text-caption text-ink-3">{{ summary.totals.count }} รายการ</p>
      </div>

      <div class="page-card p-3.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-exclamation-triangle text-danger-600" aria-hidden="true"></i>
          เลยกำหนด
        </p>
        <p class="num mt-1.5 text-lg font-bold text-danger-600 sm:text-2xl">
          {{ formatMoney(summary.totals.overdue_amount) }}
        </p>
        <p class="mt-0.5 text-caption text-ink-3">{{ summary.totals.overdue_count }} รายการ</p>
      </div>

      <div class="page-card p-3.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-check2-circle text-ok-700" aria-hidden="true"></i>
          ชำระแล้ว
        </p>
        <p class="num mt-1.5 text-lg font-bold text-ok-700 sm:text-2xl">
          {{ formatMoney(summary.totals.paid_total) }}
        </p>
        <p class="mt-0.5 text-caption text-ink-3">
          ยกเว้น {{ formatMoney(summary.totals.waived_total) }}
        </p>
      </div>

      <div class="page-card p-3.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-hourglass-split text-warn-700" aria-hidden="true"></i>
          รออนุมัติ
        </p>
        <p class="num mt-1.5 text-lg font-bold text-ink sm:text-2xl">
          {{ pendingApprovalsCount }}
        </p>
        <p class="mt-0.5 text-caption text-ink-3">คำขอยกเว้น/คืนเงิน</p>
      </div>
    </div>

    <AppTabs v-model="activeTab" :tabs="tabs" group-label="มุมมองค่าปรับ" />

    <!-- ══════════════════════ แท็บ: รายการค่าปรับ ══════════════════════ -->
    <template v-if="activeTab === 'fines'">
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="statusFilter" class="field w-auto min-w-36 text-sm" aria-label="กรองสถานะ">
          <option value="">ทุกสถานะ</option>
          <option v-for="(label, key) in FINE_STATUS_LABELS" :key="key" :value="key">
            {{ label }}
          </option>
        </select>
        <select v-model="typeFilter" class="field w-auto min-w-36 text-sm" aria-label="กรองประเภท">
          <option value="">ทุกประเภท</option>
          <option v-for="t in types" :key="t.id" :value="t.id.toString()">{{ t.name }}</option>
        </select>
        <input
          v-model="searchInput"
          type="search"
          class="field w-full text-sm sm:w-56"
          placeholder="ค้นหาชื่อนักเรียน / เหตุผล"
          aria-label="ค้นหาค่าปรับ"
        />
      </div>

      <SkeletonRows v-if="isLoading" :rows="5" height="h-20" />

      <StateBlock
        v-else-if="hasError"
        variant="error"
        title="โหลดค่าปรับไม่สำเร็จ"
        @retry="loadFines"
      />

      <StateBlock
        v-else-if="!fines.length"
        variant="empty"
        icon="bi-shield-check"
        title="ยังไม่มีค่าปรับ"
        :hint="
          statusFilter || typeFilter || searchInput
            ? 'ไม่พบรายการที่ตรงกับตัวกรอง — ลองปรับตัวกรอง'
            : 'เมื่อมีการออกค่าปรับ รายการจะปรากฏที่นี่'
        "
      />

      <ul v-else class="space-y-2">
        <li v-for="f in fines" :key="f.id">
          <RouterLink
            :to="`/finance/fines/${f.id}`"
            class="block rounded-card border border-line bg-surface p-4 transition-colors hover:bg-canvas"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-ink">
                  {{ f.student_name ?? 'ไม่ทราบชื่อ' }}
                  <span v-if="f.student_no" class="text-ink-3">· เลขที่ {{ f.student_no }}</span>
                </p>
                <p class="mt-0.5 truncate text-xs text-ink-2">
                  {{ f.fine_type_name }} · {{ formatThaiDate(f.incident_date) }}
                </p>
              </div>
              <p class="font-display num shrink-0 text-sm font-bold text-ink">
                {{ formatMoney(f.outstanding) }}
              </p>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <StatusBadge :tone="fineStatusTone(f.status)" :label="fineStatusLabel(f.status)" />
              <AppChip tone="neutral" icon="bi-calendar-event">
                ครบกำหนด {{ formatThaiDate(f.due_date) }}
              </AppChip>
              <AppChip v-if="f.invoice_no" tone="info" icon="bi-file-earmark-text">
                {{ f.invoice_no }}
              </AppChip>
            </div>
          </RouterLink>
        </li>
      </ul>
    </template>

    <!-- ══════════════════════ แท็บ: รออนุมัติ ══════════════════════ -->
    <template v-else-if="activeTab === 'approvals'">
      <section class="space-y-2">
        <h2 class="section-title flex items-center gap-2">
          <i class="bi bi-shield-minus text-brand-700" aria-hidden="true"></i>
          คำขอยกเว้น/ลด ที่รออนุมัติ
        </h2>

        <StateBlock
          v-if="!waivers.length"
          variant="empty"
          icon="bi-shield-check"
          title="ไม่มีคำขอยกเว้นที่รออนุมัติ"
        />

        <ul v-else class="space-y-2">
          <li
            v-for="w in waivers"
            :key="`w-${w.id}`"
            class="rounded-card border border-line bg-surface p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <p class="text-sm font-bold text-ink">
                  {{ WAIVER_CATEGORY_LABELS[w.reason_category] ?? w.reason_category }}
                </p>
                <p class="mt-0.5 break-words text-xs text-ink-2">{{ w.reason }}</p>
                <RouterLink
                  :to="`/finance/fines/${w.fine_id}`"
                  class="mt-1 inline-block text-xs font-bold text-brand hover:underline"
                >
                  ดูค่าปรับ #{{ w.fine_id }}
                </RouterLink>
              </div>
              <p class="num shrink-0 text-sm font-bold text-ink">{{ formatMoney(w.amount) }}</p>
            </div>
            <div v-if="canManageFinance" class="mt-3 flex flex-wrap gap-2">
              <AppButton
                variant="primary"
                :disabled="isSelfRequested(w.requested_by)"
                @click="handleWaiverDecision(w, 'approve')"
              >
                อนุมัติ
              </AppButton>
              <AppButton variant="secondary" @click="handleWaiverDecision(w, 'reject')">
                ปฏิเสธ
              </AppButton>
              <span v-if="isSelfRequested(w.requested_by)" class="self-center text-xs text-ink-3">
                ห้ามอนุมัติคำขอของตัวเอง
              </span>
            </div>
          </li>
        </ul>
      </section>

      <section class="space-y-2">
        <h2 class="section-title flex items-center gap-2">
          <i class="bi bi-cash-coin text-brand-700" aria-hidden="true"></i>
          คำขอคืนเงิน ที่รออนุมัติ
        </h2>

        <StateBlock
          v-if="!refunds.length"
          variant="empty"
          icon="bi-shield-check"
          title="ไม่มีคำขอคืนเงินที่รออนุมัติ"
        />

        <ul v-else class="space-y-2">
          <li
            v-for="r in refunds"
            :key="`r-${r.id}`"
            class="rounded-card border border-line bg-surface p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0 flex-1">
                <p class="text-sm font-bold text-ink">{{ accountName(r.account_id) }}</p>
                <p class="mt-0.5 break-words text-xs text-ink-2">{{ r.reason }}</p>
                <RouterLink
                  :to="`/finance/fines/${r.fine_id}`"
                  class="mt-1 inline-block text-xs font-bold text-brand hover:underline"
                >
                  ดูค่าปรับ #{{ r.fine_id }}
                </RouterLink>
              </div>
              <p class="num shrink-0 text-sm font-bold text-ink">{{ formatMoney(r.amount) }}</p>
            </div>
            <div v-if="canManageFinance" class="mt-3 flex flex-wrap gap-2">
              <AppButton
                variant="primary"
                :disabled="isSelfRequested(r.requested_by)"
                @click="handleRefundDecision(r, 'approve')"
              >
                อนุมัติ
              </AppButton>
              <AppButton variant="secondary" @click="handleRefundDecision(r, 'reject')">
                ปฏิเสธ
              </AppButton>
              <span v-if="isSelfRequested(r.requested_by)" class="self-center text-xs text-ink-3">
                ห้ามอนุมัติคำขอของตัวเอง
              </span>
            </div>
          </li>
        </ul>
      </section>
    </template>

    <!-- ══════════════════════ แท็บ: ประเภทความผิด ══════════════════════ -->
    <template v-else>
      <div class="flex justify-end">
        <AppButton v-if="canManageFinance" variant="secondary" @click="openTypeCreate">
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          เพิ่มประเภท
        </AppButton>
      </div>

      <StateBlock
        v-if="!types.length"
        variant="empty"
        icon="bi-tags"
        title="ยังไม่มีประเภทความผิด"
        hint="เพิ่มประเภทความผิดและอัตราเริ่มต้นเพื่อให้ออกค่าปรับได้เร็วขึ้น"
      />

      <ul v-else class="space-y-2">
        <li
          v-for="t in types"
          :key="t.id"
          class="rounded-card border border-line bg-surface p-4"
        >
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0 flex-1">
              <p class="text-sm font-bold text-ink">{{ t.name }}</p>
              <p v-if="t.description" class="mt-0.5 break-words text-xs text-ink-2">
                {{ t.description }}
              </p>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <AppChip tone="brand">{{ formatMoney(t.default_amount) }}</AppChip>
                <AppChip tone="neutral" icon="bi-calendar-event">
                  ให้ชำระใน {{ t.default_due_days }} วัน
                </AppChip>
                <AppChip v-if="!t.is_active" tone="neutral" icon="bi-pause-circle">
                  ปิดใช้งาน
                </AppChip>
              </div>
            </div>
            <div v-if="canManageFinance" class="flex shrink-0 gap-1.5">
              <AppButton variant="quiet" @click="openTypeEdit(t)">แก้ไข</AppButton>
              <AppButton variant="quiet" @click="handleDeleteType(t)">ลบ</AppButton>
            </div>
          </div>
        </li>
      </ul>
    </template>

    <!-- ══════════════════════ แผ่น: ออกค่าปรับ ══════════════════════ -->
    <AppSheet
      :open="isIssueOpen"
      label="ออกค่าปรับ"
      title="ออกค่าปรับ"
      description="1 คน = 1 บิล = 1 ใบแจ้งหนี้ · รวมในยอดค้างชำระทันที"
      size="form"
      :dismissible="!isIssuing"
      @close="isIssueOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="fine-type">ประเภทความผิด</label>
          <select
            id="fine-type"
            v-model="issueTypeId"
            class="field"
            @change="syncDueFromType"
          >
            <option value="">— เลือกประเภท —</option>
            <option v-for="t in activeTypes" :key="t.id" :value="t.id.toString()">
              {{ t.name }} · {{ formatMoney(t.default_amount) }}
            </option>
          </select>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="field-label" for="fine-incident">วันที่เกิดเหตุ</label>
            <input
              id="fine-incident"
              v-model="issueIncident"
              type="date"
              class="field"
              @change="syncDueFromType"
            />
          </div>
          <div>
            <label class="field-label" for="fine-due">กำหนดชำระ</label>
            <input id="fine-due" v-model="issueDue" type="date" class="field" />
          </div>
        </div>

        <div>
          <label class="field-label" for="fine-amount-override">
            ยอดต่อคน (ไม่บังคับ — เว้นว่าง = ใช้อัตราของประเภท)
          </label>
          <input
            id="fine-amount-override"
            v-model="issueAmountOverride"
            type="number"
            min="0.01"
            step="0.01"
            inputmode="decimal"
            class="field num"
            :placeholder="issueType ? issueType.default_amount.toString() : '0.00'"
          />
        </div>

        <div>
          <label class="field-label" for="fine-reason">เหตุผล (บังคับ)</label>
          <textarea
            id="fine-reason"
            v-model="issueReason"
            rows="2"
            maxlength="1000"
            class="field"
            placeholder="เช่น มาสายเกิน 15 นาที เมื่อคาบที่ 1"
          ></textarea>
        </div>

        <div>
          <label class="field-label" for="fine-evidence">ลิงก์หลักฐาน (ไม่บังคับ)</label>
          <input
            id="fine-evidence"
            v-model="issueEvidence"
            type="url"
            maxlength="1000"
            class="field"
            placeholder="https://…"
          />
        </div>

        <div>
          <div class="mb-1.5 flex items-center justify-between gap-2">
            <p class="field-label mb-0">นักเรียนที่ถูกปรับ ({{ issueSelectedIds.length }} คน)</p>
            <button type="button" class="text-xs font-bold text-brand" @click="toggleIssueAll">
              {{ issueAllSelected ? 'ยกเลิกทั้งหมด' : 'เลือกทั้งหมด' }}
            </button>
          </div>
          <div class="max-h-56 overflow-y-auto rounded-control border border-line">
            <label
              v-for="s in students"
              :key="s.id"
              class="flex cursor-pointer items-center gap-2 border-b border-line px-3 py-2 text-sm last:border-b-0 hover:bg-canvas"
            >
              <input
                type="checkbox"
                class="h-4 w-4 accent-brand"
                :checked="issueSelectedIds.includes(s.id)"
                @change="toggleIssueStudent(s.id)"
              />
              <span class="min-w-0 flex-1 truncate">
                {{ s.prefix }} {{ s.first_name }} {{ s.last_name }}
                <span class="text-ink-3">· เลขที่ {{ s.student_no }}</span>
              </span>
            </label>
            <p v-if="!students.length" class="px-3 py-4 text-center text-xs text-ink-3">
              ยังไม่มีรายชื่อนักเรียนในห้อง
            </p>
          </div>
        </div>

        <p v-if="issueSelectedIds.length" class="rounded-control bg-canvas p-3 text-caption text-ink-2">
          รวม <b>{{ formatMoney(issueTotalPreview) }}</b>
          ({{ formatMoney(issuePerStudent) }} × {{ issueSelectedIds.length }} คน)
        </p>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isIssueOpen = false">ยกเลิก</button>
          <button
            type="button"
            class="btn-primary"
            :disabled="isIssuing || issueSelectedIds.length === 0 || !issueTypeId"
            @click="handleIssue"
          >
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            ออกค่าปรับ {{ issueSelectedIds.length }} คน
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ══════════════════════ แผ่น: ประเภทความผิด ══════════════════════ -->
    <AppSheet
      :open="isTypeOpen"
      label="ประเภทความผิด"
      :title="editingType ? 'แก้ไขประเภทความผิด' : 'เพิ่มประเภทความผิด'"
      size="form"
      :dismissible="!isSavingType"
      @close="isTypeOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="type-name">ชื่อประเภท</label>
          <input
            id="type-name"
            v-model="typeName"
            type="text"
            maxlength="150"
            class="field"
            placeholder="เช่น มาสาย"
          />
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="field-label" for="type-amount">อัตราเริ่มต้น (บาท)</label>
            <input
              id="type-amount"
              v-model="typeAmount"
              type="number"
              min="0"
              step="0.01"
              inputmode="decimal"
              class="field num"
              placeholder="20.00"
            />
          </div>
          <div>
            <label class="field-label" for="type-days">ให้ชำระภายใน (วัน)</label>
            <input
              id="type-days"
              v-model="typeDays"
              type="number"
              min="0"
              max="365"
              step="1"
              class="field num"
            />
          </div>
        </div>
        <div>
          <label class="field-label" for="type-description">คำอธิบาย (ไม่บังคับ)</label>
          <input
            id="type-description"
            v-model="typeDescription"
            type="text"
            maxlength="500"
            class="field"
          />
        </div>
        <div>
          <label class="field-label" for="type-sort">ลำดับการแสดง</label>
          <input id="type-sort" v-model="typeSort" type="number" step="1" class="field num" />
        </div>
        <label v-if="editingType" class="flex cursor-pointer items-center gap-2 text-sm">
          <input v-model="typeActive" type="checkbox" class="h-4 w-4 accent-brand" />
          เปิดใช้งาน (ปิด = ไม่แสดงในตัวเลือกตอนออกค่าปรับ)
        </label>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isTypeOpen = false">ยกเลิก</button>
          <button type="button" class="btn-primary" :disabled="isSavingType" @click="handleSaveType">
            <i class="bi bi-check-lg" aria-hidden="true"></i>
            บันทึก
          </button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
