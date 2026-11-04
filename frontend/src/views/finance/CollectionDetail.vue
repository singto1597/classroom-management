<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { CollectionStatus, Account, StudentPaymentDetail } from '@/types/finance'
import { displayName } from '@/utils/name'
import { formatThaiDateTime } from '@/utils/datetime'
import { downloadBlob, combinedPdfFilename } from '@/utils/download'

import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useDialog } from '@/composables/useDialog'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const dialog = useDialog()

const currentServerId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!
const isAdmin = computed(() => authStore.isAdmin)

const collectionId = Number(route.params.id)
const data = ref<CollectionStatus | null>(null)
const accounts = ref<Account[]>([])
const isLoading = ref(true)

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false)

// ✨ State สำหรับโหมดแก้ไข
const isEditMode = ref(false)

const fetchDetail = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    const [detailRes, accountsRes] = await Promise.all([
      FinanceService.getCollectionStatus(currentServerId, collectionId),
      FinanceService.getAccounts(currentServerId),
    ])
    data.value = detailRes
    accounts.value = accountsRes
  } catch {
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'ไม่สามารถโหลดรายละเอียดแคมเปญได้', 'error')
  } finally {
    isLoading.value = false
  }
}

const progress = computed(() => {
  if (!data.value) return 0
  const { total, paid } = data.value.summary
  return total > 0 ? Math.round((paid / total) * 100) : 0
})

const isPayOpen = ref(false)
const payTarget = ref<StudentPaymentDetail | null>(null)
const isPaying = ref(false)
const payForm = reactive({
  accountId: '',
  amount: '',
  slipUrl: '',
})

/** เปิดแผ่นรับเงิน — ยอดเริ่มต้นคือยอดคงเหลือของบิลนั้น */
const handlePay = (student: StudentPaymentDetail) => {
  if (!isAdmin.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถรับเงินได้', 'error')
    return
  }
  payTarget.value = student
  payForm.accountId = accounts.value[0]?.id.toString() ?? ''
  payForm.amount =
    student.total_amount - student.paid_amount > 0
      ? String(student.total_amount - student.paid_amount)
      : ''
  payForm.slipUrl = ''
  isPayOpen.value = true
}

const submitPayment = async () => {
  const student = payTarget.value
  if (!student) return
  const amount = Number(payForm.amount)
  if (!payForm.accountId || !Number.isFinite(amount) || amount <= 0) {
    void dialog.alert('ข้อมูลไม่ครบ', 'กรุณาเลือกบัญชีและกรอกจำนวนเงินที่มากกว่า 0 บาท', 'warning')
    return
  }

  isPaying.value = true
  try {
    await FinanceService.confirmPayment(currentServerId, student.payment_id, {
      paid_to_account_id: Number(payForm.accountId),
      paid_amount: amount,
      slip_image_url: payForm.slipUrl.trim(),
      user_name: currentUserName,
    })
    isPayOpen.value = false
    await dialog.fire({ icon: 'success', title: 'รับเงินสำเร็จ!', timer: 1500 })
    await fetchDetail()
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'รับเงินไม่สำเร็จ',
      'error',
    )
  } finally {
    isPaying.value = false
  }
}

// ✨ ฟังก์ชันใหม่: ลบรายชื่อคนออกจากแคมเปญ
const handleRemoveStudent = async (student: StudentPaymentDetail) => {
  if (student.paid_amount > 0) {
    void dialog.alert(
      'ลบไม่ได้',
      'มีการชำระเงินเข้ามาแล้ว ถ้ายกเลิกต้องไป Revert รายการแทน',
      'warning',
    )
    return
  }

  const result = await dialog.confirm(
    'ยืนยันการลบ?',
    `คุณต้องการลบรายชื่อ ${displayName(student)} ออกจากการเก็บเงินนี้ใช่หรือไม่?`,
    { icon: 'warning', danger: true, confirmButtonText: 'ลบรายชื่อออก' },
  )

  if (result.isConfirmed) {
    try {
      await FinanceService.removeStudentFromCollection(
        currentServerId,
        collectionId,
        student.student_id,
        currentUserName,
      )
      await dialog.fire({ icon: 'success', title: 'ลบเรียบร้อย', timer: 1500 })
      await fetchDetail()
    } catch (error: unknown) {
      void dialog.alert(
        'เกิดข้อผิดพลาด',
        error instanceof Error ? error.message : 'ลบรายชื่อไม่สำเร็จ',
        'error',
      )
    }
  }
}

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num)
}

// ==========================================
// 🧾 ออกใบเสร็จ (F3)
// ==========================================
//
// 🔒 gate ด้วย `canManageFinance` (ไม่ใช่ isAdmin) เพราะ backend บังคับ
//    `require_permission(..., "MANAGE_FINANCE")` — เหรัญญิกที่ได้สิทธิ์ต้องออกเอกสารได้จริง
//
// ⚠️ `issueReceipt` **idempotent** — กดซ้ำได้เลขเดิม ไม่กินเลขใหม่ ⇒ ไม่ต้อง confirm ก่อน
//    (ต่างจากใบแจ้งหนี้ใน DebtorList ที่กินเลขใหม่ทุกครั้ง)
//
// ⚠️ ไม่ส่ง `transaction_id` ⇒ backend เลือก **งวดรับเงินล่าสุด** ของบิลนั้น
//    บิลที่ผ่อนจ่าย 500+500 จะได้ใบเสร็จของงวดที่ 2 — ใบของงวดแรกออกได้เฉพาะเมื่อระบุ
//    `transaction_id` ซึ่งยังไม่มี UI ให้เลือกในรอบนี้ (ตั้งใจ — ต้องมี endpoint
//    list งวดรับเงินของบิลก่อน)

const canManageFinance = computed(() => authStore.canManageFinance)

/** `payment_id` ที่กำลังออกเอกสาร — กันกดรัวและให้ spinner หมุนเฉพาะแถวนั้น */
const issuingPaymentId = ref<number | null>(null)
const isIssuingBatch = ref(false)

/**
 * 🚧 เพดานของ **PDF รวม** — `RECEIPTS_PER_PDF_MAX` ฝั่ง backend (ไม่ใช่เพดานของ batch
 * รับเงินซึ่งเป็น 100 เท่ากันโดยบังเอิญ ไม่ใช่โดยสัญญา)
 * ⚠️ ทั้งสองค่าเป็น 100 แต่มันผูกกับคนละข้อจำกัด ⇒ ถ้าวันหนึ่งเพดานรวมขยับ (เพราะ
 *    Chromium เร็วขึ้น) ตัวเลขนี้ต้องขยับตาม ส่วนเพดาน batch ไม่เกี่ยว
 */
const COMBINED_PDF_MAX = 100

/** จำนวนบิลที่มีเงินเข้าแล้ว (= บิลที่ออกใบเสร็จได้) — ใช้โชว์บนปุ่มรวบยอด */
const issuableCount = computed(
  () => data.value?.students.filter((s) => s.paid_amount > 0).length ?? 0,
)

const handleIssueReceipt = async (student: StudentPaymentDetail) => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกใบเสร็จได้', 'error')
    return
  }
  if (issuingPaymentId.value !== null) return

  issuingPaymentId.value = student.payment_id
  try {
    const res = await FinanceService.issueReceipt(currentServerId, {
      payment_id: student.payment_id,
      doc_type: 'receipt',
      user_name: currentUserName,
    })
    showIssued(res.receipt.receipt_no, res.reused, true)
  } catch (error: unknown) {
    void dialog.alert(
      'ออกใบเสร็จไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    issuingPaymentId.value = null
  }
}

/** ออกรวบยอดให้ทุกบิลที่มีเงินเข้าแล้ว — backend ทำใน transaction เดียว (all-or-nothing) */
const handleIssueAllReceipts = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกใบเสร็จได้', 'error')
    return
  }
  const paymentIds = (data.value?.students ?? [])
    .filter((s) => s.paid_amount > 0)
    .map((s) => s.payment_id)
  if (!paymentIds.length) return

  // เพดานของ backend คือ 100 ใบ/ครั้ง — เกินกว่านั้นต้องบอกให้แคบลง ไม่ใช่ยิงแล้วเงียบ
  if (paymentIds.length > 100) {
    void dialog.alert(
      'ออกทีละมากเกินไป',
      `เลือกไว้ ${paymentIds.length} บิล แต่ระบบออกได้ครั้งละไม่เกิน 100 ใบ กรุณาแยกโปรเจกต์หรือออกทีละส่วน`,
      'warning',
    )
    return
  }

  const result = await dialog.confirm(
    'ออกใบเสร็จทั้งหมด?',
    `จะออกใบเสร็จให้ ${paymentIds.length} รายการที่มีเงินเข้าแล้ว · ใบที่เคยออกไปแล้วจะได้เลขเดิม (ไม่กินเลขใหม่)`,
    { confirmButtonText: 'ออกใบเสร็จ' },
  )
  if (!result.isConfirmed) return

  isIssuingBatch.value = true
  void dialog.loading('กำลังออกใบเสร็จ...')
  try {
    const res = await FinanceService.issueReceiptsBatch(currentServerId, {
      payment_ids: paymentIds,
      doc_type: 'receipt',
      user_name: currentUserName,
    })
    const nos = res.receipts.map((r) => r.receipt_no)
    // 🖨️ เสนอ "ดาวน์โหลดรวมเป็น PDF" แทนการปิดเองใน 2 วินาที
    //    ⚠️ ของเดิมใช้ `timer: 2000, showConfirmButton: false` ⇒ ครูที่ออกใบเสร็จ 40 ใบ
    //       ต้องไปกดโหลดทีละใบจากทะเบียน 40 ครั้ง (ซึ่งคือปัญหาที่งานนี้มาแก้)
    //    ⚠️ เพดาน 100 ฉบับบังคับที่ backend ⇒ เช็คก่อนไม่ให้เสนอปุ่มที่กดแล้วได้ 400
    const canDownload = nos.length > 0 && nos.length <= COMBINED_PDF_MAX
    const summary = `ออกใหม่ ${res.issued_count} ใบ · ใช้เลขเดิม ${res.reused_count} ใบ`
    const downloadHint = canDownload
      ? ` · รวมเป็นไฟล์เดียวได้ (${nos.length} หน้า — หน้าละบิล) เหมาะสำหรับพิมพ์แจก`
      : ''
    const after = canDownload
      ? await dialog.confirm('ออกใบเสร็จเรียบร้อย', summary + downloadHint, {
          icon: 'success',
          confirmButtonText: 'ดาวน์โหลด PDF รวม',
          cancelButtonText: 'ปิด',
        })
      : await dialog.alert('ออกใบเสร็จเรียบร้อย', summary, 'success')
    if (canDownload && after.isConfirmed) await downloadCombined(nos)
  } catch (error: unknown) {
    dialog.close()
    void dialog.alert(
      'ออกใบเสร็จไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีใบใดถูกออก (ยกเลิกทั้งชุด)',
      'error',
    )
  } finally {
    isIssuingBatch.value = false
    // 🔄 โหลดใหม่ **หลัง** ออกเอกสารเสร็จ — ของเดิมลืมบรรทัดนี้ ทำให้ `issuableCount`
    //    และสถานะ "ออกแล้ว/ยังไม่ออก" ของทุกแถวค้างค่าเก่าจนกว่าจะรีเฟรชหน้าเอง
    //    ⇒ ครูเห็นปุ่ม "ออกใบเสร็จทั้งหมด (40)" อยู่ทั้งที่ออกไปแล้ว
    //    ⚠️ อยู่ใน `finally` (ไม่ใช่หลัง `try`) เพราะต้องรีเฟรชแม้บางใบล้ม — สถานะจริง
    //       อาจเปลี่ยนไปบางส่วนแล้ว และปุ่มที่โชว์จำนวนผิดคือสิ่งที่ทำให้กดซ้ำโดยไม่รู้ตัว
    void fetchDetail()
  }
}

/**
 * 🖨️ ดาวน์โหลดใบเสร็จที่เพิ่งออกทั้งหมดเป็น PDF ไฟล์เดียว (หน้าละบิล)
 * ⚠️ ไม่ได้ออกเอกสารใหม่ — รับเฉพาะเลขที่ที่มีอยู่แล้ว (การอ่าน ไม่กินเลข)
 */
const downloadCombined = async (nos: string[]) => {
  if (nos.length > COMBINED_PDF_MAX) {
    void dialog.alert(
      'รวมไฟล์ไม่ได้ในครั้งเดียว',
      `มี ${nos.length} ใบ แต่รวมได้ครั้งละไม่เกิน ${COMBINED_PDF_MAX} ใบ ` +
        '— กรุณาดาวน์โหลดจากทะเบียนเอกสารโดยแบ่งเป็นรอบ',
      'warning',
    )
    return
  }
  void dialog.loading('กำลังสร้างไฟล์ PDF...', 'ระบบกำลังรวมเอกสารเป็นไฟล์เดียว')
  try {
    const blob = await FinanceService.downloadCombinedPdf(currentServerId, nos)
    downloadBlob(blob, combinedPdfFilename(nos, 'receipts'))
    dialog.close()
  } catch (error: unknown) {
    dialog.close()
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  }
}

/** แจ้งผล + ทางไปดูเอกสาร — ใบที่เคยออกแล้วใช้ถ้อยคำต่างจากใบใหม่ (ไม่ใช่ error) */
const showIssued = async (receiptNo: string, reused: boolean, allowOpen: boolean) => {
  const text = reused
    ? `เลขที่เอกสาร ${receiptNo} · ระบบคืนใบเดิมให้ — เลขที่เอกสารไม่เปลี่ยน`
    : `เลขที่เอกสาร ${receiptNo}`
  const result = allowOpen
    ? await dialog.confirm(reused ? 'ใบเสร็จนี้เคยออกแล้ว' : 'ออกใบเสร็จเรียบร้อย', text, {
        icon: reused ? 'info' : 'success',
        confirmButtonText: 'ดูเอกสาร',
        cancelButtonText: 'ปิด',
      })
    : await dialog.alert(reused ? 'ใบเสร็จนี้เคยออกแล้ว' : 'ออกใบเสร็จเรียบร้อย', text, reused ? 'info' : 'success')
  if (allowOpen && result.isConfirmed) {
    await router.push(`/finance/receipts/${receiptNo}`)
  }
}

onMounted(() => {
  fetchDetail()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="ติดตามความคืบหน้าการเก็บเงินและบันทึกการรับชำระของนักเรียนแต่ละคน"
    >
      <template #actions>
        <button
          v-if="isAdmin"
          type="button"
          :class="
            isEditMode
              ? 'inline-flex min-h-11 items-center justify-center gap-2 rounded-control border border-warn-300 bg-warn-50 px-4 py-2.5 text-sm font-bold text-warn-700 transition-colors active:scale-[0.97]'
              : 'btn-ghost-ui'
          "
          @click="isEditMode = !isEditMode"
        >
          <i class="bi bi-pencil-square" aria-hidden="true"></i>
          {{ isEditMode ? 'ปิดโหมดแก้ไข' : 'โหมดจัดการรายชื่อ' }}
        </button>
      </template>
    </PageIntro>

    <!-- ความคืบหน้าของแคมเปญ (การ์ดสรุปตัวเลข → padding มือถือหนึ่งขั้นที่แน่นกว่า) -->
    <div v-if="data" class="page-card p-3.5 sm:p-5">
      <div class="flex items-center justify-between gap-3">
        <p class="min-w-0 truncate text-sm font-bold text-ink-2">
          ความคืบหน้า (จ่ายแล้ว
          <span class="num">{{ data.summary.paid }}</span>
          จาก
          <span class="num">{{ data.summary.total }}</span>
          คน)
        </p>
        <p class="num shrink-0 text-lg font-bold text-ok-600">{{ progress }}%</p>
      </div>
      <div class="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-canvas">
        <div
          class="h-full bg-ok-500 transition-all duration-1000"
          :style="{ width: `${progress}%` }"
        ></div>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />

    <StateBlock v-else-if="hasError || !data" variant="error" @retry="fetchDetail" />

    <StateBlock
      v-else-if="!data.students.length"
      variant="empty"
      icon="bi-person-x"
      title="ไม่มีรายชื่อนักเรียนในแคมเปญนี้"
      hint="ลองตรวจสอบการตั้งค่าโปรเจกต์อีกครั้ง"
    />

    <template v-else>
      <!-- 🧾 ออกรวบยอด — โผล่เฉพาะเมื่อมีบิลที่เงินเข้าแล้วจริง ๆ (ไม่มี = ไม่มีอะไรให้ออก) -->
      <div
        v-if="canManageFinance && issuableCount > 0"
        class="page-card flex flex-col gap-2 p-3.5 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
      >
        <p class="text-sm text-ink-3">
          มี
          <span class="num font-bold text-ink-2">{{ issuableCount }}</span>
          รายการที่รับเงินแล้ว — ออกใบเสร็จได้
        </p>
        <button
          type="button"
          class="btn-primary w-full shrink-0 sm:w-auto"
          :disabled="isIssuingBatch"
          @click="handleIssueAllReceipts"
        >
          <i
            class="bi"
            :class="isIssuingBatch ? 'bi-hourglass-split' : 'bi-receipt-cutoff'"
            aria-hidden="true"
          ></i>
          ออกใบเสร็จทั้งหมด
        </button>
      </div>

      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="s in data.students"
          :key="s.payment_id"
          class="page-card p-4"
          :class="isEditMode ? 'border-s-4 border-s-warn-400' : ''"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-3">
              <div
                class="num flex h-9 w-9 shrink-0 items-center justify-center rounded-control border border-line bg-canvas text-xs font-bold text-ink-3"
              >
                #{{ s.student_no }}
              </div>
              <div class="min-w-0">
                <p class="truncate text-sm font-bold text-ink">{{ displayName(s) }}</p>
                <p
                  v-if="s.nickname || s.nickname_en"
                  class="truncate text-xs italic text-ink-3"
                >
                  ({{ s.nickname || s.nickname_en }})
                </p>
              </div>
            </div>

            <!-- สถานะ -->
            <div v-if="s.status === 'paid'" class="flex shrink-0 flex-col items-end gap-1">
              <span class="chip bg-ok-50 text-ok-700">
                <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
                จ่ายครบแล้ว
              </span>
              <small v-if="s.paid_at" class="num text-caption font-bold text-ink-3">
                <i class="bi bi-clock" aria-hidden="true"></i> {{ formatThaiDateTime(s.paid_at) }}
              </small>
            </div>
            <div v-else-if="s.paid_amount > 0" class="flex shrink-0 flex-col items-end gap-1">
              <span class="chip bg-warn-50 text-warn-700">
                <i class="bi bi-hourglass-split" aria-hidden="true"></i>
                ฿{{ formatNumber(s.paid_amount) }}
              </span>
              <small class="num text-caption font-bold text-danger-600">
                ค้างอีก ฿{{ formatNumber(s.total_amount - s.paid_amount) }}
              </small>
            </div>
            <span v-else class="chip shrink-0 bg-danger-50 text-danger-700">
              <i class="bi bi-clock-fill" aria-hidden="true"></i>
              ค้าง ฿{{ formatNumber(s.total_amount) }}
            </span>
          </div>

          <!-- ปุ่มจัดการ -->
          <div class="mt-3 flex justify-end gap-2 border-t border-line pt-3">
            <template v-if="!isEditMode">
              <!-- 🧾 ออกใบเสร็จได้เมื่อ "มีเงินเข้าแล้ว" — บิลที่ยังไม่จ่าย backend ตอบ 400 -->
              <button
                v-if="s.paid_amount > 0 && canManageFinance"
                type="button"
                class="btn-ghost-ui"
                :disabled="issuingPaymentId !== null"
                @click="handleIssueReceipt(s)"
              >
                <i
                  class="bi"
                  :class="issuingPaymentId === s.payment_id ? 'bi-hourglass-split' : 'bi-receipt'"
                  aria-hidden="true"
                ></i>
                ใบเสร็จ
              </button>
              <button
                v-if="s.status === 'pending' && isAdmin"
                type="button"
                class="btn-primary"
                @click="handlePay(s)"
              >
                <i class="bi bi-wallet2" aria-hidden="true"></i>
                รับเงิน
              </button>
              <span
                v-else-if="s.status === 'pending'"
                class="chip bg-canvas text-ink-2"
              >
                รอแอดมินรับยอด
              </span>
            </template>
            <template v-else>
              <button
                v-if="s.paid_amount === 0"
                type="button"
                class="btn-danger"
                title="ลบออกจากแคมเปญ"
                @click="handleRemoveStudent(s)"
              >
                <i class="bi bi-trash3-fill" aria-hidden="true"></i>
                ลบออก
              </button>
              <span
                v-else
                class="chip bg-canvas text-ink-2"
                title="ลบไม่ได้ เพราะมีการจ่ายเงินแล้ว"
              >
                <i class="bi bi-lock-fill" aria-hidden="true"></i>
                ลบไม่ได้
              </span>
            </template>
          </div>
        </div>
      </div>

      <!-- 🖥️ เดสก์ท็อป: ตาราง -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div v-if="isEditMode" class="h-1 w-full bg-warn-400" aria-hidden="true"></div>
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-24">เลขที่</th>
                <th>ชื่อ-สกุล</th>
                <th>สถานะ</th>
                <th class="text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in data.students" :key="s.payment_id">
                <td class="num font-bold text-ink-3">#{{ s.student_no }}</td>
                <td>
                  <p class="font-bold text-ink">{{ displayName(s) }}</p>
                  <p v-if="s.nickname || s.nickname_en" class="text-xs italic text-ink-3">
                    ({{ s.nickname || s.nickname_en }})
                  </p>
                </td>
                <td>
                  <div v-if="s.status === 'paid'" class="flex flex-col items-start gap-1">
                    <span class="chip bg-ok-50 text-ok-700">
                      <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
                      จ่ายครบแล้ว
                    </span>
                    <small v-if="s.paid_at" class="num text-caption font-bold text-ink-3">
                      <i class="bi bi-clock" aria-hidden="true"></i> {{ formatThaiDateTime(s.paid_at) }}
                    </small>
                  </div>
                  <div v-else-if="s.paid_amount > 0" class="flex flex-col items-start gap-1">
                    <span class="chip bg-warn-50 text-warn-700">
                      <i class="bi bi-hourglass-split" aria-hidden="true"></i>
                      ทยอยจ่ายแล้ว ฿{{ formatNumber(s.paid_amount) }}
                    </span>
                    <small class="num text-caption font-bold text-danger-600">
                      (ค้างอีก ฿{{ formatNumber(s.total_amount - s.paid_amount) }})
                    </small>
                  </div>
                  <span v-else class="chip bg-danger-50 text-danger-700">
                    <i class="bi bi-clock-fill" aria-hidden="true"></i>
                    ค้างจ่าย (฿{{ formatNumber(s.total_amount) }})
                  </span>
                </td>
                <td>
                  <div class="flex justify-end gap-2">
                    <template v-if="!isEditMode">
                      <!-- 🧾 ออกใบเสร็จได้เมื่อ "มีเงินเข้าแล้ว" — บิลที่ยังไม่จ่าย backend ตอบ 400 -->
                      <button
                        v-if="s.paid_amount > 0 && canManageFinance"
                        type="button"
                        class="btn-ghost-ui"
                        :disabled="issuingPaymentId !== null"
                        @click="handleIssueReceipt(s)"
                      >
                        <i
                          class="bi"
                          :class="
                            issuingPaymentId === s.payment_id ? 'bi-hourglass-split' : 'bi-receipt'
                          "
                          aria-hidden="true"
                        ></i>
                        ใบเสร็จ
                      </button>
                      <button
                        v-if="s.status === 'pending' && isAdmin"
                        type="button"
                        class="btn-primary"
                        @click="handlePay(s)"
                      >
                        <i class="bi bi-wallet2" aria-hidden="true"></i>
                        รับเงิน
                      </button>
                      <span
                        v-else-if="s.status === 'pending'"
                        class="chip bg-canvas text-ink-2"
                      >
                        รอแอดมินรับยอด
                      </span>
                    </template>
                    <template v-else>
                      <button
                        v-if="s.paid_amount === 0"
                        type="button"
                        class="flex h-11 w-11 items-center justify-center rounded-control border border-danger-200 bg-surface text-danger-600 transition-colors hover:bg-danger-50 active:scale-[0.97]"
                        title="ลบออกจากแคมเปญ"
                        @click="handleRemoveStudent(s)"
                      >
                        <i class="bi bi-trash3-fill" aria-hidden="true"></i>
                      </button>
                      <span
                        v-else
                        class="chip bg-canvas text-ink-2"
                        title="ลบไม่ได้ เพราะมีการจ่ายเงินแล้ว"
                      >
                        <i class="bi bi-lock-fill" aria-hidden="true"></i>
                        ลบไม่ได้
                      </span>
                    </template>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ══════════════════════ แผ่น: รับเงิน ══════════════════════ -->
    <AppSheet
      :open="isPayOpen && !!payTarget"
      label="รับเงิน"
      :title="payTarget ? `รับเงิน: ${displayName(payTarget)}` : 'รับเงิน'"
      :description="
        payTarget
          ? `ยอดคงเหลือ ฿${formatNumber(payTarget.total_amount - payTarget.paid_amount)}`
          : undefined
      "
      size="form"
      :dismissible="!isPaying"
      @close="isPayOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="field-label" for="pay-account">รับเงินเข้าบัญชีห้อง</label>
          <select id="pay-account" v-model="payForm.accountId" class="field">
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id.toString()">
              {{ acc.account_name }}
            </option>
          </select>
        </div>

        <div>
          <label class="field-label" for="pay-amount">จำนวนเงินที่จ่าย (฿)</label>
          <input
            id="pay-amount"
            v-model="payForm.amount"
            type="number"
            min="0.01"
            step="0.01"
            inputmode="decimal"
            class="field num"
            placeholder="0.00"
          />
        </div>

        <div>
          <label class="field-label" for="pay-slip">URL รูปสลิป (ถ้ามี)</label>
          <input
            id="pay-slip"
            v-model="payForm.slipUrl"
            type="url"
            class="field"
            placeholder="https://..."
          />
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="isPayOpen = false">ยกเลิก</button>
          <button type="button" class="btn-primary" :disabled="isPaying" @click="submitPayment">
            <i class="bi bi-wallet2" aria-hidden="true"></i>
            ยืนยันการรับเงิน
          </button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
