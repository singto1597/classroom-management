<script setup lang="ts">
/**
 * ExpenseVoucherDetail — รายละเอียดใบสำคัญจ่าย (FIN-V2 / P4.3)
 * `/finance/expense-vouchers/:id`
 *
 * 🔓 อ่านเปิดให้สมาชิก (backend `require_member`) — หน้านี้ **read-only**
 *    การยกเลิกเอกสารเป็นงานของระบบยกเลิก (P6.1) ⇒ ไม่มีปุ่ม void และห้ามเรียก route ที่ยังไม่มี
 *
 * 🖨️ PDF เรียก `GET /finance/expense-vouchers/{id}/pdf` ของ P4.6 เท่านั้น
 *    — ห้ามสร้าง print view เองในหน้านี้ (จะกลายเป็นสองแหล่งความจริงของหน้าตาเอกสาร)
 *
 * ⚠️ CERT รับรองเฉพาะ **บรรทัดที่ไม่มีใบเสร็จ** ⇒ `cert_amount` ไม่เท่ากับ
 *    `total_amount` ของใบ · แสดง `cert_line_nos` ให้ตรวจย้อนได้
 */
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

import { FinanceService } from '@/services/finance';
import { apiStatus } from '@/services/api';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { downloadBlob } from '@/utils/download';
import { formatMoney } from '@/utils/money';
import { formatThaiDate, formatThaiDateTime } from '@/utils/datetime';
import type { ExpenseVoucherDetail } from '@/types/finance';

const authStore = useAuthStore();
const route = useRoute();
const dialog = useDialog();

const currentRoomId = authStore.currentRoomId!;
const voucherId = Number(route.params.id);

const detail = ref<ExpenseVoucherDetail | null>(null);
const isLoading = ref(true);
const hasError = ref(false);
const isNotFound = ref(false);
const isDownloadingPdf = ref(false);

const STATUS_LABELS: Record<string, string> = {
  active: 'ใช้งาน',
  voided: 'ยกเลิกแล้ว',
};

const RECEIPT_STATUS_LABELS: Record<string, string> = {
  attached: 'มีใบเสร็จ',
  paper: 'ใบเสร็จกระดาษ',
  none: 'ไม่มีใบเสร็จ (ออก CERT)',
};

const FUNDING_SOURCE_LABELS: Record<string, string> = {
  room_fund: 'เงินห้อง',
  pass_through: 'เงินผ่านบัญชี',
};

const SIGNATURE_ROLE_LABELS: Record<string, string> = {
  prepared: 'ผู้จัดทำ',
  approved: 'ผู้อนุมัติ',
  receiver: 'ผู้รับเงิน',
};

/** ลำดับช่องลายเซ็นบนกระดาษ — prepared · approved · receiver */
const SIGNATURE_ROLE_ORDER = ['prepared', 'approved', 'receiver'] as const;

const signatureSlots = computed(() =>
  SIGNATURE_ROLE_ORDER.map((role) => ({
    role,
    label: SIGNATURE_ROLE_LABELS[role],
    name:
      detail.value?.signatures.find((s) => s.role === role)?.signer_name ?? '',
  })),
);

const load = async () => {
  isLoading.value = true;
  hasError.value = false;
  isNotFound.value = false;
  try {
    detail.value = await FinanceService.getExpenseVoucher(currentRoomId, voucherId);
  } catch (error: unknown) {
    if (apiStatus(error) === 404) {
      isNotFound.value = true;
    } else {
      hasError.value = true;
    }
  } finally {
    isLoading.value = false;
  }
};

const downloadPdf = async () => {
  if (!detail.value || isDownloadingPdf.value) return;
  isDownloadingPdf.value = true;
  try {
    const blob = await FinanceService.downloadExpenseVoucherPdf(currentRoomId, detail.value.id);
    const filename = detail.value.pv_receipt_no
      ? `${detail.value.pv_receipt_no}.pdf`
      : `expense-voucher-${detail.value.id}.pdf`;
    downloadBlob(blob, filename);
  } catch (error: unknown) {
    // 502 = Gotenberg ล่ม (backend แปลเป็นข้อความไทยแล้ว)
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isDownloadingPdf.value = false;
  }
};

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro description="รายละเอียดใบสำคัญจ่าย — บรรทัด กระเป๋า และเลขเอกสารที่ออกให้แล้ว">
      <template #actions>
        <RouterLink to="/finance/expense-vouchers" class="btn-ghost-ui">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับรายการ
        </RouterLink>
        <button
          v-if="detail"
          type="button"
          class="btn-primary"
          :disabled="isDownloadingPdf"
          data-test="download-pdf"
          @click="downloadPdf"
        >
          <i
            class="bi"
            :class="isDownloadingPdf ? 'bi-hourglass-split' : 'bi-printer'"
            aria-hidden="true"
          ></i>
          {{ isDownloadingPdf ? 'กำลังสร้าง…' : 'ดาวน์โหลด PDF' }}
        </button>
      </template>
    </PageIntro>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-20" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดรายละเอียดใบสำคัญจ่ายไม่สำเร็จ"
      @retry="load"
    />
    <StateBlock
      v-else-if="isNotFound || !detail"
      variant="empty"
      title="ไม่พบใบสำคัญจ่ายใบนี้"
      hint="อาจถูกลบ ออกเอกสารจากห้องอื่น หรือลิงก์ไม่ถูกต้อง"
      icon="bi-file-earmark-x"
    >
      <RouterLink to="/finance/expense-vouchers" class="btn-ghost-ui mt-2">
        กลับรายการ
      </RouterLink>
    </StateBlock>

    <template v-else>
      <!-- ① หัวใบ -->
      <div class="page-card overflow-hidden">
        <div class="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
          <div class="min-w-0">
            <p class="text-xs font-bold text-ink-3">ใบสำคัญจ่ายเลขที่</p>
            <p class="num text-xl font-bold text-ink-1">
              {{ detail.pv_receipt_no || `#${detail.id}` }}
            </p>
            <p class="mt-1 text-sm text-ink-3">
              วันที่ {{ formatThaiDate(detail.voucher_date) }}
              <span class="mx-1">·</span>
              ผู้รับเงิน <span class="font-bold text-ink-2">{{ detail.payee_name }}</span>
            </p>
          </div>
          <div class="text-right">
            <p class="text-xs font-bold text-ink-3">ยอดรวมทั้งใบ</p>
            <p class="num text-2xl font-bold text-ink-1">{{ formatMoney(detail.total_amount) }}</p>
            <span
              class="chip mt-1 inline-block"
              :class="
                detail.status === 'voided'
                  ? 'bg-danger-50 text-danger-700'
                  : 'bg-ok-50 text-ok-700'
              "
            >
              {{ STATUS_LABELS[detail.status] ?? detail.status }}
            </span>
          </div>
        </div>

        <div class="border-t border-line bg-canvas px-4 py-3 text-sm sm:px-5">
          <div class="flex flex-wrap gap-x-6 gap-y-1 text-ink-3">
            <p>
              บรรทัด
              <span class="num font-bold text-ink-2">{{ detail.lines.length }}</span>
            </p>
            <p>
              สร้างเมื่อ
              <span class="font-bold text-ink-2">{{ formatThaiDateTime(detail.created_at) }}</span>
            </p>
            <p v-if="detail.pv_receipt_no">
              <RouterLink
                :to="`/finance/documents/by-no/${encodeURIComponent(detail.pv_receipt_no)}`"
                class="font-bold text-brand-700 hover:underline"
              >
                เปิดเอกสาร PV ในทะเบียน
              </RouterLink>
            </p>
          </div>
          <p v-if="detail.note" class="mt-2 text-ink-2">หมายเหตุ: {{ detail.note }}</p>
        </div>
      </div>

      <!-- ② CERT -->
      <div class="page-card overflow-hidden">
        <div class="border-b border-line bg-canvas px-4 py-3 sm:px-5">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-patch-check text-brand-700" aria-hidden="true"></i>
            ใบรับรองแทนใบเสร็จ (CERT)
          </h2>
        </div>
        <div v-if="detail.cert_receipt_no" class="p-4 sm:p-5">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="num font-bold text-ink-1">{{ detail.cert_receipt_no }}</p>
              <p class="mt-1 text-sm text-ink-3">
                รับรองบรรทัดที่
                <span class="num font-bold text-ink-2">
                  {{ detail.cert_line_nos.length ? detail.cert_line_nos.join(', ') : '—' }}
                </span>
                <span class="mx-1">·</span>
                ยอด CERT
                <span class="num font-bold text-ink-2">{{ formatMoney(detail.cert_amount) }}</span>
              </p>
            </div>
            <RouterLink
              :to="`/finance/documents/by-no/${encodeURIComponent(detail.cert_receipt_no)}`"
              class="btn-ghost-ui"
            >
              <i class="bi bi-arrow-right-circle" aria-hidden="true"></i>
              เปิดเอกสาร CERT
            </RouterLink>
          </div>
          <p class="mt-2 text-xs text-ink-3">
            ยอด CERT คำนวณจากเฉพาะบรรทัดที่ไม่มีใบเสร็จ จึงไม่เท่ากับยอดรวมทั้งใบเสมอ
          </p>
        </div>
        <p v-else class="p-4 text-sm text-ink-3 sm:p-5">
          ไม่มีรายการที่ต้องออกใบรับรอง — ทุกบรรทัดมีหลักฐานการรับเงิน
        </p>
      </div>

      <!-- ③ บรรทัด -->
      <div class="page-card overflow-hidden">
        <div class="border-b border-line bg-canvas px-4 py-3 sm:px-5">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-list-ul text-brand-700" aria-hidden="true"></i>
            รายการเบิกจ่าย
          </h2>
        </div>
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-10">#</th>
                <th>รายละเอียด</th>
                <th>หมวด</th>
                <th>งบ</th>
                <th>กระเป๋า</th>
                <th>หลักฐาน</th>
                <th class="text-right">ใบกระดาษ</th>
                <th class="text-right">จำนวนเงิน</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in detail.lines" :key="line.line_no">
                <td class="num text-ink-3">{{ line.line_no }}</td>
                <td class="min-w-[12rem]">
                  {{ line.description }}
                  <span v-if="line.attachment_placeholder" class="block text-xs text-ink-3">
                    แนบ: {{ line.attachment_placeholder }}
                  </span>
                </td>
                <td class="text-ink-3">{{ line.category_name || '—' }}</td>
                <td class="text-ink-3">{{ line.budget_label || '—' }}</td>
                <td class="text-ink-3">{{ line.wallet_name || '—' }}</td>
                <td>
                  <span
                    class="chip"
                    :class="
                      line.receipt_status === 'none'
                        ? 'bg-warn-50 text-warn-700'
                        : 'bg-canvas text-ink-2'
                    "
                  >
                    {{ RECEIPT_STATUS_LABELS[line.receipt_status] ?? line.receipt_status }}
                  </span>
                  <span class="mt-1 block text-xs text-ink-3">
                    {{ FUNDING_SOURCE_LABELS[line.funding_source] ?? line.funding_source }}
                  </span>
                </td>
                <td class="num text-right text-ink-3">{{ line.paper_bill_count }}</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(line.amount) }}
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td colspan="7" class="text-right font-bold text-ink-2">รวมทั้งสิ้น</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink-1">
                  {{ formatMoney(detail.total_amount) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <!-- ④ ลายเซ็น -->
      <div class="page-card p-4 sm:p-5">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-pen text-brand-700" aria-hidden="true"></i>
          ลายเซ็นบนเอกสาร
        </h2>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
          <div
            v-for="slot in signatureSlots"
            :key="slot.role"
            class="rounded-control bg-canvas p-3 text-center"
          >
            <p class="min-h-[1.25rem] text-sm font-bold text-ink-1">
              {{ slot.name || '—' }}
            </p>
            <p class="mt-1 text-xs text-ink-3">{{ slot.label }}</p>
          </div>
        </div>
      </div>

      <!-- ⑤ void — ยังไม่มีในรอบนี้ -->
      <div class="page-card p-4 text-sm text-ink-3 sm:p-5">
        <p class="flex items-start gap-2">
          <i class="bi bi-lock mt-0.5 shrink-0" aria-hidden="true"></i>
          <span>การยกเลิกเอกสารเป็นงานของระบบยกเลิก (P6.1) — หน้านี้แสดงข้อมูลเท่านั้น</span>
        </p>
      </div>
    </template>
  </div>
</template>
