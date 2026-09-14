<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { CollectionStatus, Account, StudentPaymentDetail } from '@/types/finance'
import { displayName } from '@/utils/name'
import Swal from 'sweetalert2'

import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

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
    Swal.fire('เกิดข้อผิดพลาด', 'ไม่สามารถโหลดรายละเอียดแคมเปญได้', 'error')
  } finally {
    isLoading.value = false
  }
}

const progress = computed(() => {
  if (!data.value) return 0
  const { total, paid } = data.value.summary
  return total > 0 ? Math.round((paid / total) * 100) : 0
})

const handlePay = async (student: StudentPaymentDetail) => {
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถรับเงินได้', 'error')
  }

  const remaining = student.total_amount - student.paid_amount

  const { value: formValues } = await Swal.fire({
    title: `รับเงิน: ${displayName(student)}`,
    html:
      '<div class="mb-3 text-left">' +
      '<label class="block text-xs font-bold text-stone-400 mb-1 uppercase">รับเงินเข้าบัญชีห้อง</label>' +
      `<select id="swal-acc" class="swal2-input w-full">
        ${accounts.value.map((acc) => `<option value="${acc.id}">${acc.account_name}</option>`).join('')}
      </select>` +
      '</div>' +
      '<div class="mb-3 text-left">' +
      '<label class="block text-xs font-bold text-stone-400 mb-1 uppercase">จำนวนเงินที่จ่าย (฿)</label>' +
      `<input id="swal-amt" type="number" class="swal2-input w-full" value="${remaining}" step="0.01">` +
      '</div>' +
      '<div class="text-left">' +
      '<label class="block text-xs font-bold text-stone-400 mb-1 uppercase">URL รูปสลิป (ถ้ามี)</label>' +
      '<input id="swal-slip" type="url" class="swal2-input w-full" placeholder="https://...">' +
      '</div>',
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonText: '✅ ยืนยันการรับเงิน',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    preConfirm: () => {
      const accId = (document.getElementById('swal-acc') as HTMLSelectElement).value
      const amount = (document.getElementById('swal-amt') as HTMLInputElement).value
      const slip = (document.getElementById('swal-slip') as HTMLInputElement).value
      if (!accId || !amount) {
        Swal.showValidationMessage('กรุณากรอกข้อมูลให้ครบถ้วน')
        return false
      }
      return {
        paid_to_account_id: Number(accId),
        paid_amount: parseFloat(amount),
        slip_image_url: slip,
      }
    },
  })

  if (formValues) {
    try {
      await FinanceService.confirmPayment(currentServerId, student.payment_id, {
        ...formValues,
        user_name: currentUserName,
      })
      Swal.fire({ icon: 'success', title: 'รับเงินสำเร็จ!', timer: 1500, showConfirmButton: false })
      fetchDetail()
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'รับเงินไม่สำเร็จ', 'error')
    }
  }
}

// ✨ ฟังก์ชันใหม่: ลบรายชื่อคนออกจากแคมเปญ
const handleRemoveStudent = async (student: StudentPaymentDetail) => {
  if (student.paid_amount > 0) {
    return Swal.fire(
      'ลบไม่ได้',
      'มีการชำระเงินเข้ามาแล้ว ถ้ายกเลิกต้องไป Revert รายการแทน',
      'warning',
    )
  }

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    html: `คุณต้องการลบรายชื่อ <b>${displayName(student)}</b> ออกจากการเก็บเงินนี้ใช่หรือไม่?`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบรายชื่อออก',
    cancelButtonText: 'ยกเลิก',
  })

  if (result.isConfirmed) {
    try {
      await FinanceService.removeStudentFromCollection(
        currentServerId,
        collectionId,
        student.student_id,
        currentUserName,
      )
      Swal.fire({ icon: 'success', title: 'ลบเรียบร้อย', timer: 1500, showConfirmButton: false })
      fetchDetail()
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'ลบรายชื่อไม่สำเร็จ', 'error')
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

/** จำนวนบิลที่มีเงินเข้าแล้ว (= บิลที่ออกใบเสร็จได้) — ใช้โชว์บนปุ่มรวบยอด */
const issuableCount = computed(
  () => data.value?.students.filter((s) => s.paid_amount > 0).length ?? 0,
)

const handleIssueReceipt = async (student: StudentPaymentDetail) => {
  if (!canManageFinance.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกใบเสร็จได้', 'error')
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
    Swal.fire(
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
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้มีสิทธิ์จัดการการเงินเท่านั้นที่ออกใบเสร็จได้', 'error')
  }
  const paymentIds = (data.value?.students ?? [])
    .filter((s) => s.paid_amount > 0)
    .map((s) => s.payment_id)
  if (!paymentIds.length) return

  // เพดานของ backend คือ 100 ใบ/ครั้ง — เกินกว่านั้นต้องบอกให้แคบลง ไม่ใช่ยิงแล้วเงียบ
  if (paymentIds.length > 100) {
    return Swal.fire(
      'ออกทีละมากเกินไป',
      `เลือกไว้ ${paymentIds.length} บิล แต่ระบบออกได้ครั้งละไม่เกิน 100 ใบ กรุณาแยกโปรเจกต์หรือออกทีละส่วน`,
      'warning',
    )
  }

  const result = await Swal.fire({
    title: 'ออกใบเสร็จทั้งหมด?',
    html: `จะออกใบเสร็จให้ <b>${paymentIds.length}</b> รายการที่มีเงินเข้าแล้ว<br>
           ใบที่เคยออกไปแล้วจะได้ <b>เลขเดิม</b> (ไม่กินเลขใหม่)`,
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ออกใบเสร็จ',
    cancelButtonText: 'ยกเลิก',
  })
  if (!result.isConfirmed) return

  isIssuingBatch.value = true
  Swal.fire({ title: 'กำลังออกใบเสร็จ...', allowOutsideClick: false, didOpen: () => Swal.showLoading() })
  try {
    const res = await FinanceService.issueReceiptsBatch(currentServerId, {
      payment_ids: paymentIds,
      doc_type: 'receipt',
      user_name: currentUserName,
    })
    Swal.fire({
      icon: 'success',
      title: 'ออกใบเสร็จเรียบร้อย',
      text: `ออกใหม่ ${res.issued_count} ใบ · ใช้เลขเดิม ${res.reused_count} ใบ`,
      timer: 2000,
      showConfirmButton: false,
    })
  } catch (error: unknown) {
    Swal.fire(
      'ออกใบเสร็จไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีใบใดถูกออก (ยกเลิกทั้งชุด)',
      'error',
    )
  } finally {
    isIssuingBatch.value = false
  }
}

/** แจ้งผล + ทางไปดูเอกสาร — ใบที่เคยออกแล้วใช้ถ้อยคำต่างจากใบใหม่ (ไม่ใช่ error) */
const showIssued = (receiptNo: string, reused: boolean, allowOpen: boolean) => {
  void Swal.fire({
    icon: reused ? 'info' : 'success',
    title: reused ? 'ใบเสร็จนี้เคยออกแล้ว' : 'ออกใบเสร็จเรียบร้อย',
    html: `เลขที่เอกสาร <b class="num">${receiptNo}</b>${
      reused ? '<br>ระบบคืนใบเดิมให้ — เลขที่เอกสารไม่เปลี่ยน' : ''
    }`,
    showCancelButton: allowOpen,
    confirmButtonText: allowOpen ? 'ดูเอกสาร' : 'ตกลง',
    cancelButtonText: 'ปิด',
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
  }).then((r) => {
    if (allowOpen && r.isConfirmed) {
      router.push(`/finance/receipts/${receiptNo}`)
    }
  })
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return (
    date.toLocaleString('th-TH', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Bangkok',
    }) + ' น.'
  )
}

onMounted(() => {
  fetchDetail()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Collection Detail"
      :title="data ? `รายละเอียดโปรเจกต์ #${data.collection_id}` : 'รายละเอียดโปรเจกต์'"
      description="ติดตามความคืบหน้าการเก็บเงินและบันทึกการรับชำระของนักเรียนแต่ละคน"
    >
      <template #actions>
        <RouterLink to="/finance/collections" class="btn-ghost-ui" title="กลับหน้าโครงการ">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าโครงการ
        </RouterLink>
        <button
          v-if="isAdmin"
          type="button"
          :class="
            isEditMode
              ? 'inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-bold text-amber-700 transition-colors active:scale-[0.97]'
              : 'btn-ghost-ui'
          "
          @click="isEditMode = !isEditMode"
        >
          <i class="bi bi-pencil-square" aria-hidden="true"></i>
          {{ isEditMode ? 'ปิดโหมดแก้ไข' : 'โหมดจัดการรายชื่อ' }}
        </button>
      </template>
    </PageHeader>

    <!-- ความคืบหน้าของแคมเปญ (การ์ดสรุปตัวเลข → padding มือถือหนึ่งขั้นที่แน่นกว่า) -->
    <div v-if="data" class="page-card p-3.5 sm:p-5">
      <div class="flex items-center justify-between gap-3">
        <p class="min-w-0 truncate text-sm font-bold text-stone-500">
          ความคืบหน้า (จ่ายแล้ว
          <span class="num">{{ data.summary.paid }}</span>
          จาก
          <span class="num">{{ data.summary.total }}</span>
          คน)
        </p>
        <p class="num font-display shrink-0 text-lg font-bold text-emerald-600">{{ progress }}%</p>
      </div>
      <div class="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-stone-100">
        <div
          class="h-full bg-emerald-500 transition-all duration-1000"
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
        <p class="text-sm text-stone-500">
          มี
          <span class="num font-bold text-stone-700">{{ issuableCount }}</span>
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
          :class="isEditMode ? 'border-s-4 border-s-amber-400' : ''"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-3">
              <div
                class="num flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-stone-200 bg-stone-50 text-xs font-bold text-stone-500"
              >
                #{{ s.student_no }}
              </div>
              <div class="min-w-0">
                <p class="truncate text-sm font-bold text-stone-900">{{ displayName(s) }}</p>
                <p
                  v-if="s.nickname || s.nickname_en"
                  class="truncate text-xs italic text-stone-400"
                >
                  ({{ s.nickname || s.nickname_en }})
                </p>
              </div>
            </div>

            <!-- สถานะ -->
            <div v-if="s.status === 'paid'" class="flex shrink-0 flex-col items-end gap-1">
              <span class="chip bg-emerald-50 text-emerald-700">
                <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
                จ่ายครบแล้ว
              </span>
              <small v-if="s.paid_at" class="num text-[10px] font-bold text-stone-400">
                <i class="bi bi-clock" aria-hidden="true"></i> {{ formatDate(s.paid_at) }}
              </small>
            </div>
            <div v-else-if="s.paid_amount > 0" class="flex shrink-0 flex-col items-end gap-1">
              <span class="chip bg-amber-50 text-amber-700">
                <i class="bi bi-hourglass-split" aria-hidden="true"></i>
                ฿{{ formatNumber(s.paid_amount) }}
              </span>
              <small class="num text-[10px] font-bold text-red-600">
                ค้างอีก ฿{{ formatNumber(s.total_amount - s.paid_amount) }}
              </small>
            </div>
            <span v-else class="chip shrink-0 bg-red-50 text-red-700">
              <i class="bi bi-clock-fill" aria-hidden="true"></i>
              ค้าง ฿{{ formatNumber(s.total_amount) }}
            </span>
          </div>

          <!-- ปุ่มจัดการ -->
          <div class="mt-3 flex justify-end gap-2 border-t border-stone-100 pt-3">
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
                class="chip bg-stone-100 text-stone-500"
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
                class="chip bg-stone-100 text-stone-400"
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
        <div v-if="isEditMode" class="h-1 w-full bg-amber-400" aria-hidden="true"></div>
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
                <td class="num font-bold text-stone-400">#{{ s.student_no }}</td>
                <td>
                  <p class="font-bold text-stone-900">{{ displayName(s) }}</p>
                  <p v-if="s.nickname || s.nickname_en" class="text-xs italic text-stone-400">
                    ({{ s.nickname || s.nickname_en }})
                  </p>
                </td>
                <td>
                  <div v-if="s.status === 'paid'" class="flex flex-col items-start gap-1">
                    <span class="chip bg-emerald-50 text-emerald-700">
                      <i class="bi bi-check-circle-fill" aria-hidden="true"></i>
                      จ่ายครบแล้ว
                    </span>
                    <small v-if="s.paid_at" class="num text-[10px] font-bold text-stone-400">
                      <i class="bi bi-clock" aria-hidden="true"></i> {{ formatDate(s.paid_at) }}
                    </small>
                  </div>
                  <div v-else-if="s.paid_amount > 0" class="flex flex-col items-start gap-1">
                    <span class="chip bg-amber-50 text-amber-700">
                      <i class="bi bi-hourglass-split" aria-hidden="true"></i>
                      ทยอยจ่ายแล้ว ฿{{ formatNumber(s.paid_amount) }}
                    </span>
                    <small class="num text-[10px] font-bold text-red-600">
                      (ค้างอีก ฿{{ formatNumber(s.total_amount - s.paid_amount) }})
                    </small>
                  </div>
                  <span v-else class="chip bg-red-50 text-red-700">
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
                        class="chip bg-stone-100 text-stone-500"
                      >
                        รอแอดมินรับยอด
                      </span>
                    </template>
                    <template v-else>
                      <button
                        v-if="s.paid_amount === 0"
                        type="button"
                        class="flex h-11 w-11 items-center justify-center rounded-xl border border-red-200 bg-white text-red-600 transition-colors hover:bg-red-50 active:scale-[0.97]"
                        title="ลบออกจากแคมเปญ"
                        @click="handleRemoveStudent(s)"
                      >
                        <i class="bi bi-trash3-fill" aria-hidden="true"></i>
                      </button>
                      <span
                        v-else
                        class="chip bg-stone-100 text-stone-400"
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
  </div>
</template>

<style scoped>
/* Swal popup ถูก render นอก scope ของ Vue — เก็บไว้เฉพาะฟอนต์ไทยของ input */
.swal2-input {
  border-radius: 1rem !important;
  font-family: 'Noto Sans Thai', sans-serif !important;
}
</style>
