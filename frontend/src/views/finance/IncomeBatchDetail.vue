<script setup lang="ts">
/**
 * IncomeBatchDetail — รายละเอียดใบรับเงิน (FIN-V2 / P4.5)
 * `/finance/income-batches/:id`
 *
 * 🔓 อ่านเปิดให้สมาชิก (backend `require_member`) — หน้านี้ **read-only**
 *    การยกเลิกเอกสารเป็นงานของระบบยกเลิก (P6.1) ⇒ ไม่มีปุ่ม void
 *
 * 🖨️ PDF เรียก `GET /finance/income-batches/{id}/pdf` ของ P4.6 เท่านั้น
 *    — ห้ามสร้าง print view เอง (สองแหล่งความจริงของหน้าตาเอกสาร)
 *
 * ⚠️ `channel` เป็น **snapshot ณ วันบันทึก** (มีแค่ค่า mask) ไม่ใช่ค่าปัจจุบัน
 * ⚠️ backend ไม่คืน `wallet_name` ⇒ ต้อง JOIN เองฝั่งจอด้วย `getAccounts`
 *    (endpoint นี้อ่านได้โดยสมาชิก — `require_member`)
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
import type { Account, IncomeBatchDetail } from '@/types/finance';

const authStore = useAuthStore();
const route = useRoute();
const dialog = useDialog();

const currentRoomId = authStore.currentRoomId!;
const batchId = Number(route.params.id);

const detail = ref<IncomeBatchDetail | null>(null);
const accounts = ref<Account[]>([]);
const isLoading = ref(true);
const hasError = ref(false);
const isNotFound = ref(false);
const isDownloadingPdf = ref(false);

const STATUS_LABELS: Record<string, string> = {
  active: 'ใช้งาน',
  voided: 'ยกเลิกแล้ว',
};

const SIGNATURE_ROLE_LABELS: Record<string, string> = {
  prepared: 'ผู้ออก',
  receiver: 'ผู้รับเงิน',
};

/** ลำดับช่องลายเซ็นบนกระดาษ — prepared · receiver (INC ไม่มีผู้อนุมัติ) */
const SIGNATURE_ROLE_ORDER = ['prepared', 'receiver'] as const;

const signatureSlots = computed(() =>
  SIGNATURE_ROLE_ORDER.map((role) => ({
    role,
    label: SIGNATURE_ROLE_LABELS[role],
    name: detail.value?.signatures.find((s) => s.role === role)?.signer_name ?? '',
  })),
);

const walletName = computed(() => {
  if (!detail.value) return '';
  return (
    accounts.value.find((a) => a.id === detail.value?.wallet_account_id)?.account_name ??
    `#${detail.value.wallet_account_id}`
  );
});

const channelText = computed(() => {
  const channel = detail.value?.channel;
  if (!channel || !channel.channel_type) return '';
  const parts = [channel.label, channel.bank_name, channel.account_number_masked];
  return parts.filter(Boolean).join(' · ');
});

const load = async () => {
  isLoading.value = true;
  hasError.value = false;
  isNotFound.value = false;
  try {
    const [batch, accRes] = await Promise.all([
      FinanceService.getIncomeBatch(currentRoomId, batchId),
      // ชื่อกระเป๋าใช้แค่แสดงผล — ถ้าโหลดไม่ได้ก็ยังเห็นเลขกระเป๋า
      FinanceService.getAccounts(currentRoomId).catch(() => [] as Account[]),
    ]);
    detail.value = batch;
    accounts.value = accRes;
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
    const blob = await FinanceService.downloadIncomeBatchPdf(currentRoomId, detail.value.id);
    const filename = detail.value.inc_receipt_no
      ? `${detail.value.inc_receipt_no}.pdf`
      : `income-batch-${detail.value.id}.pdf`;
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
    <PageIntro description="รายละเอียดใบรับเงิน — บรรทัด กระเป๋า และเลขเอกสารที่ออกให้แล้ว">
      <template #actions>
        <RouterLink to="/finance/income-batches" class="btn-ghost-ui">
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
      hint="โหลดรายละเอียดใบรับเงินไม่สำเร็จ"
      @retry="load"
    />
    <StateBlock
      v-else-if="isNotFound || !detail"
      variant="empty"
      title="ไม่พบใบรับเงินใบนี้"
      hint="อาจถูกลบ ออกเอกสารจากห้องอื่น หรือลิงก์ไม่ถูกต้อง"
      icon="bi-file-earmark-x"
    >
      <RouterLink to="/finance/income-batches" class="btn-ghost-ui mt-2">
        กลับรายการ
      </RouterLink>
    </StateBlock>

    <template v-else>
      <!-- ① หัวใบ -->
      <div class="page-card overflow-hidden">
        <div class="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
          <div class="min-w-0">
            <p class="text-xs font-bold text-ink-3">ใบรับเงินเลขที่</p>
            <p class="num text-xl font-bold text-ink-1">
              {{ detail.inc_receipt_no || `#${detail.id}` }}
            </p>
            <p class="mt-1 text-sm text-ink-3">
              วันที่ {{ formatThaiDate(detail.income_date) }}
              <span class="mx-1">·</span>
              ผู้จ่าย <span class="font-bold text-ink-2">{{ detail.payer_name }}</span>
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
              ผู้รับเงิน
              <span class="font-bold text-ink-2">{{ detail.receiver_name }}</span>
            </p>
            <p>
              กระเป๋า
              <span class="font-bold text-ink-2">{{ walletName }}</span>
            </p>
            <p v-if="channelText">
              ช่องทาง
              <span class="font-bold text-ink-2">{{ channelText }}</span>
            </p>
            <p>
              บรรทัด
              <span class="num font-bold text-ink-2">{{ detail.lines.length }}</span>
            </p>
            <p>
              สร้างเมื่อ
              <span class="font-bold text-ink-2">{{ formatThaiDateTime(detail.created_at) }}</span>
            </p>
            <p v-if="detail.inc_receipt_no">
              <RouterLink
                :to="`/finance/documents/by-no/${encodeURIComponent(detail.inc_receipt_no)}`"
                class="font-bold text-brand-700 hover:underline"
              >
                เปิดเอกสาร INC ในทะเบียน
              </RouterLink>
            </p>
          </div>
          <p v-if="detail.note" class="mt-2 text-ink-2">หมายเหตุ: {{ detail.note }}</p>
        </div>
      </div>

      <!-- ② บรรทัด -->
      <div class="page-card overflow-hidden">
        <div class="border-b border-line bg-canvas px-4 py-3 sm:px-5">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-list-ul text-brand-700" aria-hidden="true"></i>
            รายการรับเงิน
          </h2>
        </div>
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-10">#</th>
                <th>รายละเอียด</th>
                <th>หมวดรายรับ</th>
                <th class="text-right">จำนวนเงิน</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in detail.lines" :key="line.line_no">
                <td class="num text-ink-3">{{ line.line_no }}</td>
                <td class="min-w-[12rem]">{{ line.description }}</td>
                <td class="text-ink-3">{{ line.category_name || '—' }}</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(line.amount) }}
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr>
                <td colspan="3" class="text-right font-bold text-ink-2">รวมทั้งสิ้น</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink-1">
                  {{ formatMoney(detail.total_amount) }}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <!-- ③ ลายเซ็น -->
      <div class="page-card p-4 sm:p-5">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-pen text-brand-700" aria-hidden="true"></i>
          ลายเซ็นบนเอกสาร
        </h2>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
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

      <!-- ④ void — ยังไม่มีในรอบนี้ -->
      <div class="page-card p-4 text-sm text-ink-3 sm:p-5">
        <p class="flex items-start gap-2">
          <i class="bi bi-lock mt-0.5 shrink-0" aria-hidden="true"></i>
          <span>การยกเลิกเอกสารเป็นงานของระบบยกเลิก (P6.1) — หน้านี้แสดงข้อมูลเท่านั้น</span>
        </p>
      </div>
    </template>
  </div>
</template>
