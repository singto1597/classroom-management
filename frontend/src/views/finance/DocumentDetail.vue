<script setup lang="ts">
/**
 * 📄 [FIN-V2 / P5.2] รายละเอียดเอกสาร 1 ใบ — รับ `:docType` + `:docId` จาก route
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมรับ id ไม่ใช่เลขเอกสาร
 * ═══════════════════════════════════════════════════════════════════════════
 * เลขเอกสาร (`REC-2569-0042`) อยู่คนละ namespace ต่อชนิด และ RPT ท้ายเดือน
 * ยังไม่มีเลขก่อน finalized ⇒ route ใช้ **คู่ (`doc_type`, `doc_id`)** ที่ backend
 * รับประกันว่ามีจริงเสมอ (`GET /finance/documents/{doc_type}/{doc_id}`)
 *
 * 🚫 [P6.3] ปุ่ม "ยกเลิกเอกสาร" mount ที่นี่ — **เฉพาะ `invoice`** ที่ยัง active:
 *    - REC/DEP → ต้องยกเลิกผ่านเหตุการณ์รับเงิน (`/payment-events/{id}/void`)
 *    - CERT    → ต้องยกเลิกพร้อม PV (backend ตอบ 409 ชี้ทาง)
 *    - ACK/RPT → มีปุ่มของตัวเองในหน้า P5.5
 *    ⇒ หน้าจอแสดง "ข้อความชี้ทาง" แทนปุ่มสำหรับชนิดเหล่านั้น ไม่เดา endpoint เอง
 *
 * 🧩 `line_items` / `document_meta` **โครงต่างกันตามชนิด** ⇒ ทุกคีย์เป็น optional
 *    และแสดงเฉพาะคีย์ที่มีค่า (ห้าม hardcode ว่ามีทุกคีย์ — Jinja/BE อาจเพิ่ม/ลดได้)
 *
 * 🔗 แผง "เอกสารที่เกี่ยวข้อง" มาจาก `links` — เดินต่อได้ในหน้าเดิม (route param เปลี่ยน
 *    ⇒ watcher โหลดใหม่ ไม่ต้อง remount หน้า)
 */
import { computed, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import DocumentTypeBadge from '@/components/finance/DocumentTypeBadge.vue';
import VoidReasonModal from '@/components/finance/VoidReasonModal.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { createLatestGuard } from '@/utils/latest';
import { downloadBlob } from '@/utils/download';
import { formatMoney } from '@/utils/money';
import {
  THAI_MONTHS,
  formatThaiDate,
  formatThaiDateTime,
} from '@/utils/datetime';
import { isDocumentType, typeLabel } from '@/utils/documentFilters';
import type {
  DocumentDetail,
  DocumentLineItem,
  DocumentLink,
  DocumentSignatureItem,
  DocumentType,
} from '@/types/finance';

const route = useRoute();
const authStore = useAuthStore();
const dialog = useDialog();
const currentRoomId = authStore.currentRoomId!;

/** ชนิดเอกสารจาก route — ตรวจกับรายการที่รู้จักก่อนยิง API (กัน URL มือพิมพ์) */
const docType = computed<DocumentType | null>(() => {
  const raw = route.params.docType;
  const value = Array.isArray(raw) ? raw[0] : raw;
  return isDocumentType(value) ? value : null;
});

const docId = computed<number | null>(() => {
  const raw = route.params.docId;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
});

const isValidTarget = computed(() => docType.value !== null && docId.value !== null);

const doc = ref<DocumentDetail | null>(null);
const isLoading = ref(true);
const errorMessage = ref<string | null>(null);
const guard = createLatestGuard();

const load = async () => {
  const type = docType.value;
  const id = docId.value;
  if (!type || id === null) {
    doc.value = null;
    isLoading.value = false;
    errorMessage.value = null;
    return;
  }
  const token = guard.begin();
  isLoading.value = true;
  errorMessage.value = null;
  try {
    const res = await FinanceService.getDocumentDetail(currentRoomId, type, id);
    if (!guard.isCurrent(token)) return;
    doc.value = res;
  } catch (error: unknown) {
    if (!guard.isCurrent(token)) return;
    doc.value = null;
    errorMessage.value =
      error instanceof Error ? error.message : 'โหลดรายละเอียดเอกสารไม่สำเร็จ';
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

/** เปิดเอกสารลิงก์ในหน้าเดิม — route param เปลี่ยนแล้ว watcher โหลดใหม่เอง */
watch([docType, docId], () => void load(), { immediate: true });

// ── การแสดงผล ────────────────────────────────────────────────────────────

/** `doc_at` เป็น timestamp ปกติ แต่ RPT/สรุปอาจเป็น date-only — แยกก่อนจัดรูป */
const formatDocAt = (value: string | null): string => {
  if (!value) return '—';
  return value.length === 10 ? formatThaiDate(value) : formatThaiDateTime(value);
};

const amountText = (value: string | null): string =>
  value === null ? '—' : formatMoney(Number(value));

const isVoided = computed(() => doc.value?.status === 'voided');

const STATUS_LABELS: Record<string, string> = {
  active: 'ใช้งาน',
  voided: 'ยกเลิก',
  draft: 'ร่าง',
  final: 'ปิดแล้ว',
  finalized: 'ปิดแล้ว',
};

const statusLabel = (status: string): string => STATUS_LABELS[status] ?? status;

// ── line items (generic — ต่างกันทุกชนิด) ─────────────────────────────────
const lineItems = computed<DocumentLineItem[]>(() => doc.value?.line_items ?? []);

/** ยอดบรรทัด — REC v2 ใช้ `amount_applied`, INV/INC ใช้ `amount`, PV/INV ใช้ `bill_amount` */
const lineAmount = (line: DocumentLineItem): number | null => {
  const value = line.amount_applied ?? line.amount ?? line.bill_amount ?? null;
  return value === null ? null : Number(value);
};

const lineTitle = (line: DocumentLineItem): string =>
  line.title ?? line.description ?? line.category_name ?? '—';

const RECEIPT_STATUS_LABELS: Record<string, string> = {
  attached: 'แนบใบเสร็จแล้ว',
  paper: 'บิลกระดาษ',
  none: 'ไม่มีบิล',
};

const receiptStatusLabel = (value: string | null | undefined): string =>
  value ? (RECEIPT_STATUS_LABELS[value] ?? value) : '';

const hasLineExtras = computed(() =>
  lineItems.value.some(
    (line) =>
      Boolean(line.due_date) ||
      Boolean(line.category_name) ||
      Boolean(line.wallet_name) ||
      Boolean(line.receipt_status),
  ),
);

// ── RPT ──────────────────────────────────────────────────────────────────
const isReport = computed(() => doc.value?.doc_type === 'monthly_report');

const reportPeriod = computed(() => {
  const current = doc.value;
  if (!current || current.year_be === null || current.month === null) return '—';
  return `${THAI_MONTHS[current.month - 1] ?? current.month} ${current.year_be}`;
});

/** 🔴 ส่วนต่างต้องเป็น 0 ก่อนปิดงบ — แสดงแดงเมื่อไม่ใช่ศูนย์เพื่อดึงความสนใจ */
const varianceValue = computed(() => doc.value?.variance ?? null);

const varianceTone = computed(() => {
  if (varianceValue.value === null) return 'text-ink-2';
  return Math.abs(varianceValue.value) < 0.005 ? 'text-ok-700' : 'text-danger-700';
});

// ── document_meta — แสดงเฉพาะคีย์ที่รู้จัก (คีย์อื่นเป็นข้อมูลเครื่อง ไม่ใช่ของผู้ใช้) ──
const META_LABELS: Record<string, string> = {
  channel_label: 'ช่องทางรับเงิน',
  channel_name: 'ช่องทางรับเงิน',
  note: 'หมายเหตุ',
  title: 'หัวเรื่อง',
  payer_name: 'ผู้จ่าย',
  receiver_name: 'ผู้รับเงิน',
  reference_no: 'เลขอ้างอิง',
  period_label: 'ช่วงเวลา',
  fund_type: 'แหล่งเงิน',
};

const metaEntries = computed<Array<{ label: string; value: string }>>(() => {
  const meta = doc.value?.document_meta;
  if (!meta) return [];
  const entries: Array<{ label: string; value: string }> = [];
  for (const [key, raw] of Object.entries(meta)) {
    const label = META_LABELS[key];
    if (!label) continue;
    if (raw === null || raw === undefined) continue;
    if (typeof raw !== 'string' && typeof raw !== 'number' && typeof raw !== 'boolean') continue;
    const value = typeof raw === 'boolean' ? (raw ? 'ใช่' : 'ไม่ใช่') : String(raw).trim();
    if (value) entries.push({ label, value });
  }
  return entries;
});

// ── ลายเซ็น ──────────────────────────────────────────────────────────────
const SIGNATURE_ROLE_LABELS: Record<string, string> = {
  issuer: 'ผู้ออกเอกสาร',
  prepared_by: 'ผู้จัดทำ',
  approved_by: 'ผู้อนุมัติ',
  received_by: 'ผู้รับเงิน',
  receiver: 'ผู้รับเงิน',
  payer: 'ผู้จ่าย',
  custodian: 'ผู้ถือเงิน',
  witness: 'พยาน',
};

const signatureRoleLabel = (role: string): string =>
  SIGNATURE_ROLE_LABELS[role] ?? role;

const signatures = computed<DocumentSignatureItem[]>(() => doc.value?.signatures ?? []);

// ── ลิงก์เอกสาร ──────────────────────────────────────────────────────────
const LINK_TYPE_LABELS: Record<string, string> = {
  document: 'เอกสารอ้างอิง',
  related: 'เอกสารที่เกี่ยวข้อง',
  certificate: 'ใบรับรองแทนใบเสร็จ',
  payment_event: 'เหตุการณ์รับเงิน',
  void: 'เอกสารที่ถูกยกเลิก',
  report: 'รายงานปิดงบ',
};

const linkTypeLabel = (linkType: string): string =>
  LINK_TYPE_LABELS[linkType] ?? linkType;

const links = computed<DocumentLink[]>(() => doc.value?.links ?? []);

// ── ดาวน์โหลด PDF ────────────────────────────────────────────────────────
const isDownloading = ref(false);

const pdfFilename = (): string => {
  const current = doc.value;
  const base = current?.doc_no ?? `${docType.value ?? 'document'}-${docId.value ?? 0}`;
  // `\` และ `/` ใช้ในชื่อไฟล์ไม่ได้ (Windows/บางเบราว์เซอร์ตัดชื่อทิ้ง)
  return `${base.replace(/[\\/]/g, '-')}.pdf`;
};

const downloadPdf = async () => {
  const type = docType.value;
  const id = docId.value;
  if (!type || id === null || isDownloading.value) return;
  isDownloading.value = true;
  void dialog.loading('กำลังสร้างไฟล์ PDF...', 'รอสักครู่');
  try {
    const blob = await FinanceService.downloadDocumentPdf(currentRoomId, type, id);
    downloadBlob(blob, pdfFilename());
    dialog.close();
  } catch (error: unknown) {
    dialog.close();
    // backend 404 = ชนิดนี้ยังไม่รองรับ PDF (เช่น RPT ก่อน P5.4) — แสดงข้อความจาก BE ตรง ๆ
    void dialog.alert(
      'ดาวน์โหลด PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isDownloading.value = false;
  }
};

// ── 🚫 ยกเลิกเอกสาร (P6.3) ─────────────────────────────────────────────────
//
// 🔴 `void_document` รับเฉพาะ `invoice` — REC/DEP/CERT/ACK/RPT ต้องผ่านเส้นทางของมันเอง
//    (backend ตอบ 409 พร้อมชี้ endpoint) ⇒ หน้าจอไม่เดา endpoint จาก doc_type
// 🔴 ไม่มี idempotency key (ตั้งใจ) — กดซ้ำต้องได้ 409 "ยกเลิกแล้ว" จาก backend

const canManageFinance = computed(() => authStore.canManageFinance);

const isVoidOpen = ref(false);
const isVoiding = ref(false);
const voidError = ref('');

const canVoidInvoice = computed(
  () =>
    canManageFinance.value &&
    doc.value?.doc_type === 'invoice' &&
    doc.value?.status === 'active',
);

/** ข้อความชี้ทางสำหรับชนิดที่ยกเลิกเดี่ยวไม่ได้ — ไม่แสดงปุ่มที่กดแล้วได้ 400/409 */
const voidHelpText = computed(() => {
  const current = doc.value;
  if (!canManageFinance.value || !current || current.status !== 'active') return '';
  switch (current.doc_type) {
    case 'receipt':
    case 'deposit':
      return 'เอกสารนี้เกิดจากรายการรับเงิน — ยกเลิกที่ประวัติการรับเงิน (เหตุการณ์รับเงิน)';
    case 'payment_voucher':
      return 'ใบสำคัญจ่ายยกเลิกได้ที่หน้าใบสำคัญจ่าย (ทะเบียนเอกสาร)';
    case 'certificate':
      return 'ใบรับรองแทนใบเสร็จยกเลิกเดี่ยวไม่ได้ — ต้องยกเลิกพร้อมใบสำคัญจ่ายที่ออกคู่กัน';
    default:
      // ACK/RPT มีปุ่มของตัวเองในหน้า P5.5 — ไม่แสดงข้อความซ้ำ
      return '';
  }
});

/** สรุปสิ่งที่กำลังจะถูกกลับ — ค่าจากเอกสารที่โหลดไว้ (ห้ามคำนวณใหม่) */
const voidSummary = computed<Array<{ label: string; value: string }>>(() => {
  const current = doc.value;
  if (!current) return [];
  return [
    { label: 'เลขที่เอกสาร', value: current.doc_no ?? `#${current.doc_id}` },
    { label: 'ประเภท', value: typeLabel(current.doc_type) },
    { label: 'ยอดรวม', value: amountText(current.amount) },
  ];
});

const openVoid = () => {
  voidError.value = '';
  isVoidOpen.value = true;
};

const confirmVoid = async (reason: string) => {
  const current = doc.value;
  if (!current || isVoiding.value) return;
  isVoiding.value = true;
  voidError.value = '';
  try {
    await FinanceService.voidDocument(currentRoomId, current.doc_type, current.doc_id, {
      reason,
    });
    isVoidOpen.value = false;
    await dialog.alert(
      'ยกเลิกแล้ว',
      'เอกสารถูกยกเลิก — ยังพิมพ์ดูได้และจะแสดงป้าย "ยกเลิก" ในทะเบียน',
      'success',
    );
    // 🔄 reload เพื่อเห็นสถานะ voided + ป้าย และปุ่มหาย (ไม่พาออกจากหน้า)
    await load();
  } catch (error: unknown) {
    // 409/400 → แสดงข้อความไทยจาก backend ในกล่องแดงของ modal (ไม่ปิดเอง)
    voidError.value = error instanceof Error ? error.message : 'ยกเลิกเอกสารไม่สำเร็จ';
  } finally {
    isVoiding.value = false;
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <RouterLink to="/finance/documents" class="btn-ghost-ui">
        <i class="bi bi-chevron-left" aria-hidden="true"></i>
        กลับทะเบียนเอกสาร
      </RouterLink>
      <div class="flex flex-wrap items-center gap-2">
        <!-- 🚫 ยกเลิกเอกสาร — เฉพาะใบแจ้งหนี้ที่ยัง active (ชนิดอื่นมีข้อความชี้ทางด้านล่าง) -->
        <button
          v-if="canVoidInvoice"
          type="button"
          class="btn-danger"
          :disabled="isVoiding"
          @click="openVoid"
        >
          <i class="bi bi-x-octagon" aria-hidden="true"></i>
          ยกเลิกเอกสาร
        </button>
        <button
          v-if="doc"
          type="button"
          class="btn-primary"
          :disabled="isDownloading"
          @click="downloadPdf"
        >
          <i
            class="bi"
            :class="isDownloading ? 'bi-hourglass-split' : 'bi-file-earmark-pdf'"
            aria-hidden="true"
          ></i>
          ดาวน์โหลด PDF
        </button>
      </div>
    </div>

    <p
      v-if="voidHelpText"
      class="rounded-xl border border-line bg-canvas px-3 py-2 text-sm text-ink-3"
    >
      <i class="bi bi-info-circle" aria-hidden="true"></i>
      {{ voidHelpText }}
    </p>

    <!-- URL ผิดรูป (ชนิดไม่รู้จัก / id ไม่ใช่จำนวนเต็ม) — ไม่ต้องยิง API -->
    <StateBlock
      v-if="!isValidTarget"
      variant="empty"
      icon="bi-question-circle"
      title="ไม่พบเอกสารนี้"
      hint="ลิงก์อาจผิดรูปหรือเอกสารถูกลบ — กลับไปเลือกจากทะเบียนเอกสาร"
    />

    <SkeletonRows v-else-if="isLoading" :rows="4" height="h-24" />

    <StateBlock
      v-else-if="errorMessage"
      variant="error"
      title="โหลดรายละเอียดเอกสารไม่สำเร็จ"
      :hint="errorMessage"
      @retry="load"
    />

    <template v-else-if="doc">
      <!-- 🚩 ป้ายยกเลิก — ต้องเห็นก่อนรายละเอียดอื่น -->
      <div
        v-if="isVoided"
        class="page-card border-danger-200 bg-danger-50 p-4"
        role="alert"
      >
        <p class="flex items-center gap-2 font-bold text-danger-700">
          <i class="bi bi-x-octagon-fill" aria-hidden="true"></i>
          เอกสารนี้ถูกยกเลิก
        </p>
        <p v-if="doc.void_reason" class="mt-1 text-sm text-danger-700">
          เหตุผล: {{ doc.void_reason }}
        </p>
        <p v-if="doc.voided_at" class="num mt-1 text-xs text-danger-700">
          เมื่อ {{ formatDocAt(doc.voided_at) }}
        </p>
      </div>

      <!-- หัวเอกสาร -->
      <div class="page-card p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <DocumentTypeBadge :doc-type="doc.doc_type" />
              <span
                class="chip"
                :class="
                  isVoided ? 'bg-danger-50 text-danger-700' : 'bg-canvas text-ink-2'
                "
              >
                {{ statusLabel(doc.status) }}
              </span>
            </div>
            <p class="num mt-2 font-display text-title-l font-bold text-ink">
              {{ doc.doc_no ?? `#${doc.doc_id}` }}
            </p>
            <p class="text-sm text-ink-3">
              {{ typeLabel(doc.doc_type) }} · {{ formatDocAt(doc.doc_at) }}
            </p>
          </div>
          <div class="text-right">
            <p class="text-caption font-bold text-ink-3">ยอดรวม</p>
            <p class="num font-display text-title-l font-bold text-ink">
              {{ amountText(doc.amount) }}
            </p>
            <p v-if="doc.amounts_in_words" class="text-caption text-ink-3">
              {{ doc.amounts_in_words }}
            </p>
          </div>
        </div>

        <dl class="mt-4 grid gap-x-6 gap-y-2 border-t border-line pt-4 sm:grid-cols-2">
          <div v-if="doc.student_name" class="flex justify-between gap-3 sm:block">
            <dt class="field-label">นักเรียน</dt>
            <dd class="text-sm font-bold text-ink">
              {{ doc.student_name }}
              <span v-if="doc.student_no !== null" class="num text-ink-3">
                · เลขที่ {{ doc.student_no }}
              </span>
            </dd>
          </div>
          <div v-if="doc.receiver_name" class="flex justify-between gap-3 sm:block">
            <dt class="field-label">ผู้รับเงิน</dt>
            <dd class="text-sm font-bold text-ink">{{ doc.receiver_name }}</dd>
          </div>
          <div v-if="doc.issued_to_name" class="flex justify-between gap-3 sm:block">
            <dt class="field-label">ออกให้</dt>
            <dd class="text-sm font-bold text-ink">{{ doc.issued_to_name }}</dd>
          </div>
          <div v-if="doc.issued_by_name" class="flex justify-between gap-3 sm:block">
            <dt class="field-label">ออกโดย</dt>
            <dd class="text-sm font-bold text-ink">{{ doc.issued_by_name }}</dd>
          </div>
          <div v-if="doc.issued_at" class="flex justify-between gap-3 sm:block">
            <dt class="field-label">เวลาออกเอกสาร</dt>
            <dd class="num text-sm font-bold text-ink">{{ formatDocAt(doc.issued_at) }}</dd>
          </div>
          <div
            v-for="entry in metaEntries"
            :key="entry.label"
            class="flex justify-between gap-3 sm:block"
          >
            <dt class="field-label">{{ entry.label }}</dt>
            <dd class="text-sm font-bold text-ink">{{ entry.value }}</dd>
          </div>
          <div v-if="doc.note" class="flex justify-between gap-3 sm:col-span-2 sm:block">
            <dt class="field-label">หมายเหตุ</dt>
            <dd class="whitespace-pre-line text-sm text-ink">{{ doc.note }}</dd>
          </div>
        </dl>
      </div>

      <!-- 🧾 รายงานปิดงบ (RPT) — บล็อกตัวเลขเฉพาะชนิดนี้ -->
      <div v-if="isReport" class="page-card p-4 sm:p-5">
        <h2 class="font-display text-title-m font-bold text-ink">
          สรุปการปิดงบ
          <span class="text-ink-3">· {{ reportPeriod }}</span>
          <span v-if="doc.version !== null" class="num text-ink-3">· ฉบับที่ {{ doc.version }}</span>
        </h2>
        <dl class="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-sm text-ink-3">รายรับรวม</dt>
            <dd class="num text-sm font-bold text-ok-700">
              {{ doc.total_income === null ? '—' : formatMoney(doc.total_income) }}
            </dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-sm text-ink-3">รายจ่ายรวม</dt>
            <dd class="num text-sm font-bold text-danger-700">
              {{ doc.total_expense === null ? '—' : formatMoney(doc.total_expense) }}
            </dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-sm text-ink-3">เงินสดยกมา</dt>
            <dd class="num text-sm font-bold text-ink">
              {{ doc.opening_cash === null ? '—' : formatMoney(doc.opening_cash) }}
            </dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-sm text-ink-3">เงินสดคงเหลือ (ระบบ)</dt>
            <dd class="num text-sm font-bold text-ink">
              {{ doc.closing_cash === null ? '—' : formatMoney(doc.closing_cash) }}
            </dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-sm text-ink-3">เงินสดนับจริง</dt>
            <dd class="num text-sm font-bold text-ink">
              {{ doc.counted_cash === null ? '—' : formatMoney(doc.counted_cash) }}
            </dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-sm text-ink-3">ส่วนต่าง</dt>
            <dd class="num text-sm font-bold" :class="varianceTone">
              {{ varianceValue === null ? '—' : formatMoney(varianceValue) }}
            </dd>
          </div>
        </dl>
        <p v-if="doc.finalized_at" class="mt-3 text-caption font-bold text-ink-3">
          ปิดงบเมื่อ {{ formatDocAt(doc.finalized_at) }}
        </p>
      </div>

      <!-- 🧮 รายการบรรทัด (ถ้ามี) -->
      <div v-if="lineItems.length" class="page-card overflow-hidden">
        <h2 class="border-b border-line px-4 py-3 font-display text-title-m font-bold text-ink">
          รายการในเอกสาร
          <span class="num text-ink-3">· {{ lineItems.length }} รายการ</span>
        </h2>
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-12 text-right">#</th>
                <th>รายการ</th>
                <th v-if="hasLineExtras">รายละเอียด</th>
                <th class="text-right">จำนวนเงิน</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, index) in lineItems" :key="index">
                <td class="num text-right text-ink-3">{{ line.line_no ?? index + 1 }}</td>
                <td class="font-bold text-ink">{{ lineTitle(line) }}</td>
                <td v-if="hasLineExtras" class="text-ink-2">
                  <span class="flex flex-wrap items-center gap-1.5">
                    <span v-if="line.category_name" class="chip bg-canvas text-ink-2">
                      {{ line.category_name }}
                    </span>
                    <span v-if="line.wallet_name" class="chip bg-canvas text-ink-2">
                      <i class="bi bi-wallet2" aria-hidden="true"></i>
                      {{ line.wallet_name }}
                    </span>
                    <span v-if="line.receipt_status" class="chip bg-canvas text-ink-2">
                      {{ receiptStatusLabel(line.receipt_status) }}
                      <template v-if="line.paper_bill_count">
                        · {{ line.paper_bill_count }} ใบ
                      </template>
                    </span>
                    <span v-if="line.due_date" class="num text-caption text-ink-3">
                      ครบกำหนด {{ formatThaiDate(line.due_date) }}
                    </span>
                  </span>
                </td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ lineAmount(line) === null ? '—' : formatMoney(lineAmount(line)) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 🔗 เอกสารที่เกี่ยวข้อง -->
      <div v-if="links.length" class="page-card p-4 sm:p-5">
        <h2 class="font-display text-title-m font-bold text-ink">เอกสารที่เกี่ยวข้อง</h2>
        <ul class="mt-2 divide-y divide-line">
          <li
            v-for="link in links"
            :key="`${link.doc_type}:${link.doc_id}`"
            class="flex flex-wrap items-center justify-between gap-2 py-2"
          >
            <span class="flex min-w-0 flex-wrap items-center gap-1.5">
              <span class="chip bg-canvas text-ink-2">
                <i
                  class="bi"
                  :class="link.direction === 'out' ? 'bi-arrow-right' : 'bi-arrow-left'"
                  aria-hidden="true"
                ></i>
                {{ linkTypeLabel(link.link_type) }}
              </span>
              <DocumentTypeBadge :doc-type="link.doc_type" />
            </span>
            <RouterLink
              :to="{
                name: 'finance-document-detail',
                params: { docType: link.doc_type, docId: link.doc_id },
              }"
              class="num min-h-11 text-sm font-bold text-brand hover:underline"
            >
              {{ link.doc_no ?? `#${link.doc_id}` }}
            </RouterLink>
          </li>
        </ul>
      </div>

      <!-- ✍️ ลายเซ็นที่บันทึกไว้ -->
      <div v-if="signatures.length" class="page-card p-4 sm:p-5">
        <h2 class="font-display text-title-m font-bold text-ink">ผู้ลงนาม</h2>
        <dl class="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <div
            v-for="signature in signatures"
            :key="`${signature.role}:${signature.person_id ?? signature.signer_name}`"
            class="flex justify-between gap-3"
          >
            <dt class="text-sm text-ink-3">{{ signatureRoleLabel(signature.role) }}</dt>
            <dd class="text-right text-sm font-bold text-ink">
              {{ signature.signer_name }}
              <span v-if="signature.signed_at" class="num block text-caption font-normal text-ink-3">
                {{ formatDocAt(signature.signed_at) }}
              </span>
            </dd>
          </div>
        </dl>
      </div>
    </template>

    <!-- ═══════════════════ แผ่น: ยกเลิกเอกสาร (P6.3) ═══════════════════ -->
    <VoidReasonModal
      :open="isVoidOpen"
      title="ยกเลิกเอกสาร"
      description="ยกเลิกแล้วย้อนกลับไม่ได้ — เอกสารยังอยู่ในทะเบียนพร้อมป้ายยกเลิก"
      :summary="voidSummary"
      :busy="isVoiding"
      :error-message="voidError"
      @close="isVoidOpen = false"
      @confirm="confirmVoid"
    />
  </div>
</template>
