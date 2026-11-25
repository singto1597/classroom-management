<script setup lang="ts">
/**
 * 🧾 [FIN-V2 / P5.5] AckDetail — รายละเอียดใบรับทราบยอดค้าง — `/finance/acknowledgements/:receiptNo`
 *
 * 🔓 อ่านเปิดให้สมาชิก · ปุ่มยกเลิกเฉพาะ `canManageFinance` (backend บังคับซ้ำ)
 *
 * 🔴 รายชื่อผู้ค้างอ่านจาก `finance_ack_entries` (snapshot ณ วันออก) **ไม่ใช่บิลสด** —
 *    หน้าจอนี้แสดง "สิ่งที่ผู้ปกครองเซ็นรับทราบ" ไม่ใช่ยอดปัจจุบัน
 *    ⇒ ห้าม JOIN/recompute ยอดใน FE แม้ส่วนต่างจะดูจับต้องได้
 *
 * 🖨️ ใบที่ยกเลิกแล้วยังพิมพ์ได้ (เทมเพลตประทับ "ยกเลิก" ให้เอง) — ใช้ registry PDF
 *    ผ่าน `downloadAckPdf` (backend ไม่มี route pdf เฉพาะของ ACK)
 */
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import AppButton from '@/components/ui/AppButton.vue';

import { FinanceService } from '@/services/finance';
import { apiStatus } from '@/services/api';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { downloadBlob } from '@/utils/download';
import { formatMoney } from '@/utils/money';
import { formatThaiDateTime } from '@/utils/datetime';
import type { AckDetailResponse } from '@/types/finance';

const authStore = useAuthStore();
const route = useRoute();
const dialog = useDialog();

const currentRoomId = authStore.currentRoomId!;
const receiptNo = String(route.params.receiptNo ?? '');

const canManageFinance = computed(() => authStore.canManageFinance);

const detail = ref<AckDetailResponse | null>(null);
const isLoading = ref(true);
const hasError = ref(false);
const isNotFound = ref(false);
const isDownloadingPdf = ref(false);
const isVoiding = ref(false);

const receipt = computed(() => detail.value?.receipt ?? null);
const isVoided = computed(() => receipt.value?.status === 'voided');

const issuedAt = computed(
  () => formatThaiDateTime(receipt.value?.event_at ?? receipt.value?.issued_at ?? null),
);

const includeInvoice = computed(() => {
  const meta = receipt.value?.document_meta;
  return meta && typeof meta['include_invoice'] === 'boolean'
    ? meta['include_invoice']
    : null;
});

const load = async () => {
  isLoading.value = true;
  hasError.value = false;
  isNotFound.value = false;
  try {
    detail.value = await FinanceService.getAcknowledgement(currentRoomId, receiptNo);
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
  if (isDownloadingPdf.value || !receipt.value) return;
  isDownloadingPdf.value = true;
  try {
    const blob = await FinanceService.downloadAckPdf(currentRoomId, receipt.value.receipt_no);
    downloadBlob(blob, `${receipt.value.receipt_no}.pdf`);
  } catch (error: unknown) {
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isDownloadingPdf.value = false;
  }
};

const voidReceipt = async () => {
  if (!receipt.value || isVoiding.value) return;
  const result = await dialog.confirm(
    'ยกเลิกใบรับทราบนี้?',
    'เอกสารจะไม่มีผลอีกต่อไป — รายชื่อที่เคยแจ้งยังถูกเก็บไว้เป็นหลักฐาน และไม่กระทบยอดเงิน',
    {
      danger: true,
      confirmButtonText: 'ยกเลิกเอกสาร',
      input: 'textarea',
      inputLabel: 'เหตุผลที่ยกเลิก (บังคับ)',
      inputPlaceholder: 'เช่น แจ้งผิดชุดนักเรียน / ยอดไม่ตรง',
      preConfirm: (value: string) => {
        const trimmed = value.trim();
        if (!trimmed) throw new Error('กรุณาระบุเหตุผลที่ยกเลิกเอกสาร');
        return trimmed;
      },
    },
  );
  if (!result.isConfirmed) return;

  isVoiding.value = true;
  try {
    await FinanceService.voidAcknowledgement(currentRoomId, receipt.value.receipt_no, {
      reason: result.value.trim(),
    });
    dialog.notify('ยกเลิกใบรับทราบแล้ว');
    await load();
  } catch (error: unknown) {
    void dialog.alert(
      'ยกเลิกไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isVoiding.value = false;
  }
};

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro :description="`ใบรับทราบยอดค้าง ${receiptNo}`">
      <template #actions>
        <AppButton
          variant="secondary"
          :loading="isDownloadingPdf"
          :disabled="!receipt"
          @click="downloadPdf"
        >
          <i v-if="!isDownloadingPdf" class="bi bi-printer" aria-hidden="true"></i>
          ดาวน์โหลด PDF
        </AppButton>
        <AppButton
          v-if="canManageFinance && receipt && !isVoided"
          variant="danger"
          :loading="isVoiding"
          @click="voidReceipt"
        >
          ยกเลิกเอกสาร
        </AppButton>
      </template>
    </PageIntro>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-20" />
    <StateBlock
      v-else-if="isNotFound"
      variant="empty"
      title="ไม่พบเอกสารเลขที่นี้"
      hint="อาจถูกลบไปแล้ว หรือเลขที่เอกสารไม่ถูกต้อง"
      icon="bi-file-earmark-x"
    >
      <RouterLink to="/finance/acknowledgements" class="btn-ghost-ui mt-2">
        กลับหน้ารายการใบรับทราบ
      </RouterLink>
    </StateBlock>
    <StateBlock
      v-else-if="hasError || !detail || !receipt"
      variant="error"
      hint="โหลดรายละเอียดใบรับทราบไม่สำเร็จ"
      @retry="load"
    />

    <template v-else>
      <!-- แบนเนอร์สถานะ -->
      <div
        v-if="isVoided"
        class="flex gap-2.5 rounded-card border border-danger-200 bg-danger-50 px-3.5 py-3"
        role="status"
      >
        <i class="bi bi-slash-circle mt-0.5 text-danger-600" aria-hidden="true"></i>
        <div class="min-w-0 text-sm leading-relaxed text-danger-700">
          <p class="font-bold">เอกสารนี้ถูกยกเลิกแล้ว — ไม่มีผลต่อยอดเงิน</p>
          <p v-if="receipt.void_reason" class="mt-0.5">
            เหตุผล: {{ receipt.void_reason }}
          </p>
          <p v-if="receipt.voided_at" class="mt-0.5 text-caption">
            เมื่อ {{ formatThaiDateTime(receipt.voided_at) }}
          </p>
        </div>
      </div>

      <!-- หัวเอกสาร -->
      <div class="page-card p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="num font-display text-title-m font-bold text-ink-1">{{ receipt.receipt_no }}</p>
            <p class="mt-1 text-sm text-ink-2">{{ issuedAt }}</p>
          </div>
          <span
            class="chip"
            :class="isVoided ? 'bg-danger-50 text-danger-700' : 'bg-ok-50 text-ok-700'"
          >
            {{ isVoided ? 'ยกเลิกแล้ว' : 'ใช้งาน' }}
          </span>
        </div>

        <dl class="mt-4 grid gap-2 sm:grid-cols-3">
          <div class="rounded-control bg-canvas px-3 py-2.5">
            <dt class="text-caption text-ink-3">ยอดค้างรวม</dt>
            <dd class="num mt-0.5 text-lg font-bold text-ink-1">
              {{ formatMoney(receipt.amount) }}
            </dd>
          </div>
          <div class="rounded-control bg-canvas px-3 py-2.5">
            <dt class="text-caption text-ink-3">จำนวนนักเรียน</dt>
            <dd class="num mt-0.5 text-lg font-bold text-ink-1">
              {{ detail.entry_count }}
            </dd>
          </div>
          <div class="rounded-control bg-canvas px-3 py-2.5">
            <dt class="text-caption text-ink-3">ออกใบแจ้งหนี้ด้วย</dt>
            <dd class="mt-0.5 text-lg font-bold text-ink-1">
              {{ includeInvoice === null ? '—' : includeInvoice ? 'ใช่' : 'ไม่ใช่' }}
            </dd>
          </div>
        </dl>

        <p v-if="receipt.note" class="mt-3 text-sm leading-relaxed text-ink-2">
          หมายเหตุ: {{ receipt.note }}
        </p>
      </div>

      <!-- รายชื่อผู้ค้าง (snapshot) -->
      <div class="page-card overflow-hidden">
        <h2 class="section-title px-4 pt-4 sm:px-5">รายชื่อผู้ค้าง ณ วันออกเอกสาร</h2>
        <div class="mt-3 overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-14 text-right">ลำดับ</th>
                <th>ชื่อนักเรียน</th>
                <th>เลขที่นักเรียน</th>
                <th class="text-right">ยอดค้าง</th>
                <th>ใบแจ้งหนี้</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(entry, index) in detail.entries" :key="entry.student_id">
                <td class="num text-right text-ink-3">{{ index + 1 }}</td>
                <td class="min-w-[10rem] text-ink-1">{{ entry.student_name ?? '—' }}</td>
                <td class="num text-ink-2">{{ entry.student_no ?? '—' }}</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(entry.outstanding_amount) }}
                </td>
                <td class="whitespace-nowrap">
                  <RouterLink
                    v-if="entry.invoice_receipt_id !== null"
                    :to="{
                      name: 'finance-document-detail',
                      params: { docType: 'invoice', docId: entry.invoice_receipt_id },
                    }"
                    class="num font-bold text-brand underline-offset-2 hover:underline"
                  >
                    {{ entry.invoice_receipt_no ?? `#${entry.invoice_receipt_id}` }}
                  </RouterLink>
                  <span v-else class="text-ink-3">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
