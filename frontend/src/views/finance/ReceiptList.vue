<script setup lang="ts">
/**
 * ReceiptList — ทะเบียนเอกสารการเงิน (ใบเสร็จ + ใบแจ้งหนี้) — F3
 *
 * 🔓 อ่านเปิดให้สมาชิกทุกคน (ตรงกับ `require_member` ฝั่ง backend)
 *    หน้านี้ **ไม่มีปุ่มเขียนเลย** — การออกเอกสารเกิดที่บริบทของมัน คือ
 *    หน้ารายละเอียดโปรเจกต์ (CollectionDetail) และหน้าลูกหนี้ (DebtorList)
 *    ที่นั่นรู้ว่า "บิลไหน" ⇒ ไม่ต้องมาเลือกบิลซ้ำที่นี่
 *
 * ⚠️ ช่วงวันที่กรองตาม **วันตามปฏิทินไทย** ไม่ใช่ UTC (backend ใช้ `AT TIME ZONE 'Asia/Bangkok'`
 *    บน `issued_at`) ⇒ เวลาที่แสดงผลต้องจัดรูปในโซนไทยด้วย ไม่งั้นเอกสารที่ออก 18:30 UTC
 *    จะโผล่ในวันที่ 14 (ตามตัวกรอง) แต่จอเขียนว่า 13 — ดู `formatThaiDateTime`
 *
 * ⚠️ backend จำกัด `LIMIT 500` เรียงใหม่→เก่า ⇒ ถ้าได้ครบ 500 แถวต้อง **บอกผู้ใช้**
 *    ว่าเห็นไม่หมด (ไม่ใช่ปล่อยเงียบ ๆ แล้วให้อ่านเป็น "มีเท่านี้") — ดู `hitsLimit`
 */
import { computed, onMounted, ref, watch } from 'vue';
import Swal from 'sweetalert2';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PeriodPicker from '@/components/finance/PeriodPicker.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { downloadBlob, combinedPdfFilename } from '@/utils/download';
import { createLatestGuard } from '@/utils/latest';
import {
  describePeriod,
  formatThaiDateTime,
  isRangeReversed,
  toRange,
  todayThaiYearMonth,
  type PeriodValue,
} from '@/utils/period';
import type { ReceiptDocType, ReceiptListItem } from '@/types/finance';

const authStore = useAuthStore();
const currentRoomId = authStore.currentRoomId!;

// 🌏 ค่าเริ่มต้น = เดือนนี้ตามเวลาไทย (ดู utils/period.todayThaiYearMonth)
const initial = todayThaiYearMonth();
const period = ref<PeriodValue>({ mode: 'month', month: initial.month, year: initial.year });

/** 'all' = ทั้งสองชนิด (เป็นค่าเริ่มต้น เพราะครูมักดูรวมก่อนแยก) */
const docTypeFilter = ref<'all' | ReceiptDocType>('all');

const items = ref<ReceiptListItem[]>([]);
const isLoading = ref(true);
const hasError = ref(false);
// 🏁 กันคำตอบของคำขอเก่ามาทับคำตอบของคำขอใหม่ (ดู utils/latest.ts)
const guard = createLatestGuard();

/** 🔒 เพดานเดียวกับ `LIMIT 500` ใน `ReceiptsMixin.get_receipts` — แก้ที่นั่นต้องแก้ที่นี่ */
const LIST_LIMIT = 500;
const hitsLimit = computed(() => items.value.length >= LIST_LIMIT);

const DOC_TYPE_FILTERS: { value: 'all' | ReceiptDocType; label: string; icon: string }[] = [
  { value: 'all', label: 'ทั้งหมด', icon: 'bi-collection' },
  { value: 'receipt', label: 'ใบเสร็จ', icon: 'bi-receipt' },
  { value: 'invoice', label: 'ใบแจ้งหนี้', icon: 'bi-file-earmark-text' },
  // 💰 [F4] ใบรับเงินล่วงหน้า — เอกสารคนละชนิดกับใบเสร็จโดยเจตนา (เงินยังไม่ใช่รายได้)
  //    ⚠️ service ส่งค่านี้เป็น query param ⇒ backend ต้องรับ 'deposit' ด้วย ไม่งั้น 422
  { value: 'deposit', label: 'ใบรับเงินล่วงหน้า', icon: 'bi-piggy-bank' },
];

const rangeOf = (p: PeriodValue): { startDate: string; endDate: string } | null =>
  p.mode === 'asof' ? null : toRange(p);

/**
 * 🎨 สีของ chip ตามชนิดเอกสาร — **ต้องแยก 3 ทาง ไม่ใช่ 2**
 * ⚠️ เดิมเป็น `doc_type === 'receipt' ? เขียว : เหลือง` ⇒ ใบรับเงินล่วงหน้าจะได้สีเหลือง
 *    เท่ากับใบแจ้งหนี้ ⇒ ผู้ใช้แยกไม่ออกว่าอันไหนคือ "เงินเข้าแล้ว" กับ "ยังไม่ได้รับเงิน"
 *    ซึ่งเป็นความต่างที่สำคัญที่สุดของสองเอกสารนี้
 *    🔴 ห้ามยุบกลับเป็น 2 ทาง — "ใบเสร็จ" (เงินเข้า+เป็นรายได้) กับ "ใบรับเงินล่วงหน้า"
 *       (เงินเข้าแต่ **ยังไม่ใช่รายได้**) ต้องดูต่างกันด้วยตาเปล่า
 */
const docChipClass = (docType: string): string => {
  if (docType === 'receipt') return 'bg-emerald-50 text-emerald-700';
  if (docType === 'deposit') return 'bg-sky-50 text-sky-700';
  return 'bg-amber-50 text-amber-700';
};

/** เงินทุกตัวในหน้านี้ผ่านฟังก์ชันเดียว — เติม `฿` เสมอ (แบบเดียวกับ BudgetList/FinancialStatements) */
const formatMoney = (value: number): string =>
  `${value < 0 ? '−' : ''}฿${Math.abs(value).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const load = async () => {
  // ช่วงวันที่กลับด้าน — PeriodPicker แสดง error inline อยู่แล้ว ไม่ต้องยิง API (backend จะ 400)
  if (isRangeReversed(period.value)) return;

  const range = rangeOf(period.value);
  if (!range) return;

  // 🏁 ผู้ใช้สลับเดือน/ช่วง หรือสลับ pill ใบเสร็จ↔ใบแจ้งหนี้ เร็ว ๆ ได้ ⇒ มีคำขอซ้อนกัน
  //    และคำตอบไม่ได้กลับมาตามลำดับที่ส่ง ⇒ ต้องทิ้งคำตอบของคำขอที่ถูกแทนที่แล้ว
  //    ไม่งั้นทะเบียนกับ KPI ทั้ง 4 ใบจะโชว์เอกสารของตัวกรองเก่าใต้ป้ายตัวกรองใหม่
  const token = guard.begin();

  isLoading.value = true;
  hasError.value = false;
  try {
    const rows = await FinanceService.getReceipts(currentRoomId, {
      startDate: range.startDate,
      endDate: range.endDate,
      // 'all' = ไม่ส่ง doc_type เลย (ส่ง undefined แล้ว service จะไม่ใส่ query param ให้)
      docType: docTypeFilter.value === 'all' ? undefined : docTypeFilter.value,
    });
    if (!guard.isCurrent(token)) return;
    items.value = rows;

    // 🧹 ตัดเลขที่หลุดจากมุมมองปัจจุบันทิ้งจากที่ติ๊กไว้ — เกิดได้จริงเมื่อผู้ใช้สลับเดือน
    //    หรือสลับ pill ใบเสร็จ↔ใบแจ้งหนี้ หลังจากติ๊กไว้แล้ว ⇒ ถ้าไม่กรอง ปุ่มจะบอก
    //    "เลือก 12 ใบ" ทั้งที่บนจอเหลือ 3 ใบ และไฟล์ที่ได้จะมีเอกสารของตัวกรองเก่าปนมา
    //    ซึ่งผู้ใช้ตรวจไม่ได้เลยเพราะมันไม่อยู่บนจอแล้ว
    const shown = new Set(items.value.map((r) => r.receipt_no));
    selectedNos.value = selectedNos.value.filter((no) => shown.has(no));
  } catch (error) {
    // error ของคำขอเก่าไม่ควรขึ้นจอ ถ้าคำขอใหม่กว่าไปถึงแล้ว
    if (!guard.isCurrent(token)) return;
    console.error('Failed to load receipts:', error);
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

watch([period, docTypeFilter], () => {
  void load();
});

onMounted(() => {
  void load();
});

// ==========================================
// 📊 สรุปหัวหน้า
// ==========================================

const totalAmount = computed(() => items.value.reduce((sum, r) => sum + r.amount, 0));
const receiptCount = computed(() => items.value.filter((r) => r.doc_type === 'receipt').length);
const invoiceCount = computed(() => items.value.filter((r) => r.doc_type === 'invoice').length);

// ==========================================
// ☑️ เลือกหลายใบ → รวมเป็น PDF ไฟล์เดียว (หน้าละใบ)
// ==========================================
//
// 🔓 หน้านี้ยัง **ไม่มีปุ่มเขียน** — การติ๊กเลือกเป็นการอ่านล้วน (ไม่กินเลข ไม่เขียนแถว)
//    ตรงกับ `require_member` ที่ครอบ `POST /finance/receipts/pdf` ฝั่ง backend
//
// 🔴 เก็บ **เลขที่เอกสาร** ไม่ใช่ `id` — endpoint รวมรับ `receipt_no` เพราะเลขที่คือ
//    สิ่งเดียวที่ผู้ใช้เห็นบนกระดาษและอ้างถึงได้ (id เป็นรายละเอียดภายใน)
//
// 🚫 ไม่มี "เลือกทั้งหมดทุกช่วงวันที่" โดยเจตนา — `items` ถูกจำกัดที่ 500 แถวและถูกกรอง
//    ด้วยช่วงวันที่อยู่ ⇒ "ทั้งหมด" ที่สื่อความหมายได้มีแค่ "ทั้งหมดที่เห็นบนจอ" เท่านั้น

const selectedNos = ref<string[]>([]);

/** 🔒 เพดานเดียวกับ `RECEIPTS_PER_PDF_MAX` ฝั่ง backend — เกินแล้วได้ 400 (พร้อมข้อความไทย) */
const COMBINED_PDF_MAX = 100;

const isDownloadingCombined = ref(false);

const selectedAmount = computed(() =>
  items.value.filter((r) => selectedNos.value.includes(r.receipt_no)).reduce((s, r) => s + r.amount, 0),
);

const allSelected = computed(
  () => items.value.length > 0 && selectedNos.value.length === items.value.length,
);

const toggleSelectAll = () => {
  selectedNos.value = allSelected.value ? [] : items.value.map((r) => r.receipt_no);
};

/**
 * 🖨️ รวมเอกสารที่เลือกเป็น PDF ไฟล์เดียว — **หน้าละใบ** ตามลำดับที่เลือก
 *
 * ⚠️ backend ตอบ 404 ทั้งคำขอถ้ามีเลขใดไม่พบ (ไม่ข้ามเงียบ ๆ) ⇒ เลขที่ค้างอยู่ใน
 *    `selectedNos` หลังตัวกรองเปลี่ยนจะถูกตัดออกตั้งแต่ใน `load()` แล้ว
 */
const downloadCombined = async () => {
  if (isDownloadingCombined.value || selectedNos.value.length === 0) return;
  if (selectedNos.value.length > COMBINED_PDF_MAX) {
    return Swal.fire(
      'รวมไฟล์ไม่ได้ในครั้งเดียว',
      `เลือกไว้ ${selectedNos.value.length} ฉบับ แต่รวมได้ครั้งละไม่เกิน ${COMBINED_PDF_MAX} ฉบับ ` +
        '— กรุณาแคบช่วงวันที่ลงหรือเลือกน้อยลง',
      'warning',
    );
  }
  isDownloadingCombined.value = true;
  Swal.fire({
    title: 'กำลังสร้างไฟล์ PDF...',
    allowOutsideClick: false,
    didOpen: () => Swal.showLoading(),
  });
  try {
    const nos = [...selectedNos.value];
    const blob = await FinanceService.downloadCombinedPdf(currentRoomId, nos);
    // 🏷️ 'documents' เพราะในทะเบียนนี้เลือกปนกันได้ทั้งใบเสร็จและใบแจ้งหนี้
    //    ⇒ ชื่อไฟล์ต้องไม่แอบอ้างว่าเป็นชนิดใดชนิดหนึ่ง
    downloadBlob(blob, combinedPdfFilename(nos, 'documents'));
    Swal.close();
  } catch (error: unknown) {
    Swal.fire(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isDownloadingCombined.value = false;
  }
};

// ==========================================
// 🖨️ ดาวน์โหลด PDF (backend เรนเดอร์ผ่าน Gotenberg)
// ==========================================

/** เก็บ `receipt_no` ที่กำลังโหลดอยู่ — กันกดรัวและให้ spinner หมุนเฉพาะแถวนั้น */
const downloadingNo = ref<string | null>(null);

const downloadPdf = async (receipt: ReceiptListItem) => {
  if (downloadingNo.value) return;
  downloadingNo.value = receipt.receipt_no;
  try {
    const blob = await FinanceService.downloadReceiptPdf(currentRoomId, receipt.receipt_no);
    downloadBlob(blob, `${receipt.doc_type}-${receipt.receipt_no}.pdf`);
  } catch (error: unknown) {
    // 502 = Gotenberg ต่อไม่ได้/เรนเดอร์ไม่ผ่าน — ข้อความไทยมาจาก service แล้ว
    Swal.fire(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    downloadingNo.value = null;
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Finance Documents"
      title="ใบเสร็จ / ใบแจ้งหนี้"
      description="ทะเบียนเอกสารที่ออกแล้วของห้อง — เลขที่เอกสารเรียงตามปี พ.ศ. ของวันรับเงิน"
    >
      <template #actions>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
      </template>
    </PageHeader>

    <PeriodPicker v-model="period" :modes="['month', 'range']" />

    <!-- กรองชนิดเอกสาร: pill switch แบบเดียวกับโหมดของ PeriodPicker -->
    <div class="page-card p-3 sm:p-4">
      <p class="field-label mb-1.5">ชนิดเอกสาร</p>
      <div class="flex items-center gap-1" role="group" aria-label="กรองชนิดเอกสาร">
        <button
          v-for="f in DOC_TYPE_FILTERS"
          :key="f.value"
          type="button"
          :aria-pressed="docTypeFilter === f.value"
          class="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl px-2 py-2 text-sm font-bold transition-colors active:scale-[0.97] sm:flex-none sm:px-4"
          :class="
            docTypeFilter === f.value
              ? 'bg-brand-700 text-white'
              : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'
          "
          @click="docTypeFilter = f.value"
        >
          <i class="bi text-base" :class="f.icon" aria-hidden="true"></i>
          <span class="truncate">{{ f.label }}</span>
        </button>
      </div>
    </div>

    <!-- สรุปช่วงที่กำลังดู — ตัวเลขมาจากชุดที่กรองแล้วตรง ๆ ไม่ใช่ยอดสะสมของห้อง -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div class="page-card p-3.5">
        <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">เอกสาร</p>
        <p class="font-display num mt-1 text-xl font-bold text-stone-900">{{ items.length }}</p>
        <p class="mt-0.5 text-[11px] text-stone-500">{{ describePeriod(period) }}</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">ยอดรวม</p>
        <p class="font-display num mt-1 text-xl font-bold text-brand-700">
          {{ formatMoney(totalAmount) }}
        </p>
        <p class="mt-0.5 text-[11px] text-stone-500">เฉพาะที่แสดงอยู่</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">ใบเสร็จ</p>
        <p class="font-display num mt-1 text-xl font-bold text-emerald-700">{{ receiptCount }}</p>
        <p class="mt-0.5 text-[11px] text-stone-500">เอกสารรับเงิน</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">ใบแจ้งหนี้</p>
        <p class="font-display num mt-1 text-xl font-bold text-amber-700">{{ invoiceCount }}</p>
        <p class="mt-0.5 text-[11px] text-stone-500">เอกสารเรียกเก็บ</p>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />

    <template v-else>
      <StateBlock v-if="hasError" variant="error" @retry="load" />

      <StateBlock
        v-else-if="!items.length"
        variant="empty"
        icon="bi-file-earmark-x"
        title="ยังไม่มีเอกสารในช่วงนี้"
        hint="ออกใบเสร็จได้จากหน้าโครงการเก็บเงิน (รายชื่อที่จ่ายแล้ว) และออกใบแจ้งหนี้ได้จากหน้าสรุปผู้ค้างชำระ"
      />

      <template v-else>
        <p
          v-if="hitsLimit"
          class="chip bg-amber-50 text-amber-700"
          role="status"
        >
          <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
          แสดง {{ LIST_LIMIT }} รายการล่าสุด — มีเอกสารมากกว่านี้ในช่วงที่เลือก กรุณาแคบช่วงวันที่ลง
        </p>

        <!-- ☑️ แถบรวมเอกสาร: ทำงานกับ "ที่เห็นบนจอ" เท่านั้น (ดูเหตุผลในสคริปต์) -->
        <div class="page-card flex flex-wrap items-center justify-between gap-3 p-3 sm:p-4">
          <div class="flex min-w-0 items-center gap-2">
            <button type="button" class="btn-ghost-ui" @click="toggleSelectAll">
              <i class="bi" :class="allSelected ? 'bi-x-square' : 'bi-check2-square'" aria-hidden="true"></i>
              {{ allSelected ? 'ล้างที่เลือก' : 'เลือกทั้งหมดในหน้านี้' }}
            </button>
            <p class="min-w-0 truncate text-xs font-bold text-stone-500">
              <template v-if="selectedNos.length">
                เลือก <span class="num text-brand-700">{{ selectedNos.length }}</span> ฉบับ —
                รวม {{ formatMoney(selectedAmount) }}
              </template>
              <template v-else>ติ๊กเลือกเอกสารเพื่อรวมเป็นไฟล์เดียว (หน้าละใบ)</template>
            </p>
          </div>
          <button
            v-if="selectedNos.length"
            type="button"
            class="btn-primary shrink-0"
            :disabled="isDownloadingCombined"
            @click="downloadCombined"
          >
            <i
              class="bi"
              :class="isDownloadingCombined ? 'bi-hourglass-split' : 'bi-file-earmark-zip'"
              aria-hidden="true"
            ></i>
            ดาวน์โหลดรวมเป็นไฟล์เดียว
          </button>
        </div>

        <!-- 📱 มือถือ -->
        <div class="space-y-2.5 lg:hidden">
          <div v-for="r in items" :key="r.id" class="page-card p-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <label class="flex cursor-pointer items-center gap-2">
                  <input
                    v-model="selectedNos"
                    type="checkbox"
                    :value="r.receipt_no"
                    :aria-label="`เลือกเอกสาร ${r.receipt_no} เพื่อรวมไฟล์`"
                    class="peer sr-only"
                  />
                  <span
                    class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                    :class="
                      selectedNos.includes(r.receipt_no)
                        ? 'border-brand-700 bg-brand-700'
                        : 'border-stone-300 bg-white'
                    "
                  >
                    <i
                      v-if="selectedNos.includes(r.receipt_no)"
                      class="bi bi-check-lg text-xs font-bold text-white"
                      aria-hidden="true"
                    ></i>
                  </span>
                  <span class="num truncate text-sm font-bold text-stone-900">{{ r.receipt_no }}</span>
                </label>
                <p class="mt-0.5 truncate text-xs text-stone-500">
                  {{ r.issued_to_name || '—' }}
                  <span v-if="r.student_no" class="num">— เลขที่ {{ r.student_no }}</span>
                </p>
                <p v-if="r.collection_title" class="truncate text-xs text-stone-400">
                  {{ r.collection_title }}
                </p>
              </div>
              <div class="shrink-0 text-right">
                <p class="font-display num text-base font-bold text-stone-900">
                  {{ formatMoney(r.amount) }}
                </p>
                <span class="chip mt-1" :class="docChipClass(r.doc_type)">
                  {{ r.doc_type_label || r.doc_type }}
                </span>
              </div>
            </div>

            <div
              class="mt-2.5 flex items-center justify-between gap-3 border-t border-stone-100 pt-2.5"
            >
              <small class="num truncate text-[11px] font-bold text-stone-400">
                <i class="bi bi-clock" aria-hidden="true"></i> {{ formatThaiDateTime(r.issued_at) }}
              </small>
              <div class="flex shrink-0 items-center gap-2">
                <RouterLink
                  :to="`/finance/receipts/${r.receipt_no}`"
                  class="btn-ghost-ui"
                  title="ดูรายละเอียดเอกสาร"
                >
                  <i class="bi bi-eye" aria-hidden="true"></i>
                  ดู
                </RouterLink>
                <button
                  type="button"
                  class="btn-primary"
                  :disabled="downloadingNo !== null"
                  @click="downloadPdf(r)"
                >
                  <i
                    class="bi"
                    :class="downloadingNo === r.receipt_no ? 'bi-hourglass-split' : 'bi-printer'"
                    aria-hidden="true"
                  ></i>
                  PDF
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 🖥️ เดสก์ท็อป -->
        <div class="page-card hidden overflow-hidden lg:block">
          <div class="overflow-x-auto">
            <table class="data-table">
              <thead>
                <tr>
                  <th class="w-10">
                    <label class="flex cursor-pointer items-center" title="เลือกทั้งหมดในหน้านี้">
                      <input
                        type="checkbox"
                        class="peer sr-only"
                        :checked="allSelected"
                        aria-label="เลือกเอกสารทั้งหมดในหน้านี้"
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
                  <th>เลขที่เอกสาร</th>
                  <th>วันที่ออก</th>
                  <th>ชนิด</th>
                  <th>ผู้รับเอกสาร</th>
                  <th>รายการ</th>
                  <th class="text-right">จำนวนเงิน</th>
                  <th class="text-right">จัดการ</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in items" :key="r.id">
                  <td>
                    <label class="flex cursor-pointer items-center">
                      <input
                        v-model="selectedNos"
                        type="checkbox"
                        :value="r.receipt_no"
                        :aria-label="`เลือกเอกสาร ${r.receipt_no} เพื่อรวมไฟล์`"
                        class="peer sr-only"
                      />
                      <span
                        class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                        :class="
                          selectedNos.includes(r.receipt_no)
                            ? 'border-brand-700 bg-brand-700'
                            : 'border-stone-300 bg-white'
                        "
                      >
                        <i
                          v-if="selectedNos.includes(r.receipt_no)"
                          class="bi bi-check-lg text-xs font-bold text-white"
                          aria-hidden="true"
                        ></i>
                      </span>
                    </label>
                  </td>
                  <td class="num font-bold text-stone-900">{{ r.receipt_no }}</td>
                  <td class="num whitespace-nowrap text-stone-500">
                    {{ formatThaiDateTime(r.issued_at) }}
                  </td>
                  <td>
                    <span class="chip" :class="docChipClass(r.doc_type)">
                      {{ r.doc_type_label || r.doc_type }}
                    </span>
                  </td>
                  <td>
                    <p class="font-bold text-stone-900">{{ r.issued_to_name || '—' }}</p>
                    <p v-if="r.student_no" class="num text-xs text-stone-400">
                      เลขที่ {{ r.student_no }}
                    </p>
                  </td>
                  <td class="max-w-[18rem] truncate text-stone-500">
                    {{ r.collection_title || '—' }}
                  </td>
                  <td class="font-display num whitespace-nowrap text-right font-bold text-stone-900">
                    {{ formatMoney(r.amount) }}
                  </td>
                  <td>
                    <div class="flex justify-end gap-2">
                      <RouterLink
                        :to="`/finance/receipts/${r.receipt_no}`"
                        class="btn-ghost-ui"
                        title="ดูรายละเอียดเอกสาร"
                      >
                        <i class="bi bi-eye" aria-hidden="true"></i>
                        ดู
                      </RouterLink>
                      <button
                        type="button"
                        class="btn-primary"
                        :disabled="downloadingNo !== null"
                        @click="downloadPdf(r)"
                      >
                        <i
                          class="bi"
                          :class="downloadingNo === r.receipt_no ? 'bi-hourglass-split' : 'bi-printer'"
                          aria-hidden="true"
                        ></i>
                        PDF
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
