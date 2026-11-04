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

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PeriodPicker from '@/components/finance/PeriodPicker.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { downloadBlob, combinedPdfFilename } from '@/utils/download';
import { createLatestGuard } from '@/utils/latest';
import {
  allVisibleSelected,
  batchDisplayName,
  batchVisibilityNote,
  batchVoidedNote,
  groupReceipts,
  rowAmount,
  rowSelectionState,
  selectedAmountOf,
  toggleRowSelection,
  visibleNosOf,
  type ReceiptRow,
} from '@/utils/receiptGroups';
import { formatThaiDateTime } from '@/utils/datetime';
import {
  describePeriod,
  isRangeReversed,
  toRange,
  todayThaiYearMonth,
  type PeriodValue,
} from '@/utils/period';
import type { ReceiptDocType, ReceiptListItem } from '@/types/finance';

const authStore = useAuthStore();
const dialog = useDialog();
const currentRoomId = authStore.currentRoomId!;

// 🔒 ปุ่มจัดการ **ชุด** ต้องใช้ `canManageFinance` (ไม่ใช่ `isAdmin`) ตามกฎเดียวกับปุ่มเขียน
//    ของ F2/F3/F4 — เหรัญญิกที่ถือ MANAGE_FINANCE แต่ไม่ใช่แอดมินคือคนที่ใช้ฟีเจอร์นี้จริง
//    ⚠️ หน้านี้ยัง **ไม่มีปุ่มเขียนเอกสาร** ตามเจตนาเดิม (ดูหัวไฟล์) — "จัดเป็นชุด" เป็นการ
//       จัดกลุ่มเอกสารที่ออกไปแล้ว ไม่ใช่การออกเอกสารใหม่
const canManageFinance = computed(() => authStore.canManageFinance);

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

// 🔴 ทุกค่านี้ถูกส่งเป็น query param `doc_type` ตรง ๆ ⇒ ต้องมีอยู่ใน whitelist ของ
//    `GET /finance/receipts` (`routers/finance/receipts.py`) ด้วย ไม่งั้นผู้ใช้กด chip
//    แล้วได้ 422 ทั้งที่เอกสารถูกออกจริง · ลำดับในลิสต์นี้ = ลำดับ chip บนจอ
const DOC_TYPE_FILTERS: { value: 'all' | ReceiptDocType; label: string; icon: string }[] = [
  { value: 'all', label: 'ทั้งหมด', icon: 'bi-collection' },
  { value: 'receipt', label: 'ใบเสร็จ', icon: 'bi-receipt' },
  // 💸 [F6] ใบสำคัญจ่าย — เอกสาร **จ่ายออก** ชนิดเดียวในทะเบียนนี้
  { value: 'payment_voucher', label: 'ใบสำคัญจ่าย', icon: 'bi-cash-coin' },
  // 💰 [F4] ใบรับเงินล่วงหน้า — เอกสารคนละชนิดกับใบเสร็จโดยเจตนา (เงินยังไม่ใช่รายได้)
  { value: 'deposit', label: 'ใบรับเงินล่วงหน้า', icon: 'bi-piggy-bank' },
  // 🧾 [F6] ใบรับเงิน — เงินเข้าที่บันทึกเอง (ไม่มีบิลรองรับ)
  { value: 'income', label: 'ใบรับเงิน', icon: 'bi-cash-stack' },
  { value: 'invoice', label: 'ใบแจ้งหนี้', icon: 'bi-file-earmark-text' },
];

const rangeOf = (p: PeriodValue): { startDate: string; endDate: string } | null =>
  p.mode === 'asof' ? null : toRange(p);

/**
 * 🎨 สีของ chip ตามชนิดเอกสาร — **ต้องแยกครบทุกชนิดที่ระบบออกได้**
 *
 * ⚠️ เดิมเป็น `doc_type === 'receipt' ? เขียว : เหลือง` ⇒ ใบรับเงินล่วงหน้าได้สีเหลือง
 *    เท่ากับใบแจ้งหนี้ ⇒ ผู้ใช้แยกไม่ออกว่าอันไหนคือ "เงินเข้าแล้ว" กับ "ยังไม่ได้รับเงิน"
 *    ซึ่งเป็นความต่างที่สำคัญที่สุดของสองเอกสารนี้
 *
 * 🔑 เกณฑ์คือ **สถานะของเงิน** ไม่ใช่ชื่อชนิด:
 *    • `emerald` = เงินเข้ามือแล้ว และนับเป็นรายได้ (`receipt`, `income`)
 *      ℹ️ สองชนิดนี้ **ตั้งใจให้สีเดียวกัน** — ต่างกันที่ "ผูกบิลหรือไม่" ซึ่ง chip บอกด้วย
 *         ข้อความอยู่แล้ว · การให้คนละสีจะสื่อว่าสถานะเงินต่างกัน ซึ่งไม่จริง
 *    • `sky`     = เงินเข้ามือแล้ว แต่ **ยังไม่นับเป็นรายได้** (`deposit` — เครดิตล่วงหน้า)
 *    • `amber`   = **ยังไม่ได้รับเงิน** (`invoice`)
 *    • `stone`   = **เงินออกจากห้อง** (`payment_voucher`) — ตั้งใจให้เป็นกลาง
 *
 * 🔴 ห้ามใช้ `rose-*` กับใบสำคัญจ่าย: ในหน้านี้ `rose` สื่อ "ถูกยกเลิก" อยู่แล้ว
 *    (`batchVoidedNote`, ปุ่มยกเลิก) ⇒ ใบที่ยังใช้ได้จะอ่านเหมือนใบที่ตายแล้ว
 */
const docChipClass = (docType: string): string => {
  if (docType === 'receipt' || docType === 'income') return 'bg-ok-50 text-ok-700';
  if (docType === 'deposit') return 'bg-info-50 text-info-700';
  if (docType === 'payment_voucher') return 'bg-canvas text-ink-2';
  return 'bg-warn-50 text-warn-700';
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

/**
 * 💰 ยอดเงินในกล่องสรุป — **ต้องแยก "รับ" กับ "จ่าย" ออกจากกันเด็ดขาด**
 *
 * 🔴 ของเดิมคือ `items.reduce((sum, r) => sum + r.amount, 0)` ซึ่งแปลว่า "ยอดรวม"
 *    เฉย ๆ · ถูกต้องตราบใดที่ทะเบียนมีแต่เอกสาร **รับเงิน** (ใบเสร็จ/ใบแจ้งหนี้/เครดิต)
 *    แต่ [F6] เอา **ใบสำคัญจ่าย** (เงินออก) เข้ามาอยู่ในทะเบียนเดียวกัน ⇒ ผลบวกเดียว
 *    จะกลายเป็น "เงินเข้า ลบด้วยเงินออก" ที่ไม่มีใครขอ และตัวเลขจะดูสมเหตุสมผลเสมอ
 *    ⇒ ผู้ใช้ที่ดูยอดรวมเพื่อเทียบกับสมุดบัญชีจะเจอตัวเลขที่ไม่มีที่มา โดยไม่มี error ฟ้อง
 *
 * ⚠️ `is_receipt` (จาก backend) เป็นตัวตัดสินว่า "เงินเข้า" ไม่ใช่ `doc_type` — ดูเหตุผล
 *    ในคอมเมนต์ของ `types/finance.ts` · ยอดของใบแจ้งหนี้ **ไม่นับเป็นเงินเข้า** เช่นกัน
 *    (ยังไม่ได้รับเงิน) จึงต้องมีตัวนับของตัวเอง
 */
const receivedTotal = computed(() =>
  items.value.filter((r) => r.is_receipt).reduce((sum, r) => sum + r.amount, 0),
);
const paidTotal = computed(() =>
  items.value
    .filter((r) => r.doc_type === 'payment_voucher')
    .reduce((sum, r) => sum + r.amount, 0),
);
const receiptCount = computed(() => items.value.filter((r) => r.is_receipt).length);
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

// ==========================================
// 📚 จัดกลุ่มเป็น "ชุดเอกสาร" — ตรรกะอยู่ที่ `utils/receiptGroups.ts` (มีเทสต์คุม)
// ==========================================
//
// 🔴 **ทำไมจัดกลุ่มที่หน้าจอ ไม่ใช่ให้ backend คืนโครงสร้างซ้อนกัน:**
//    `getReceipts` มีสัญญา `LIMIT 500` + ตัวกรองวันที่ที่หน้าจอพึ่งอยู่ และชุดที่มีสมาชิก
//    บางส่วนหลุดช่วงกรองจะดูเหมือน "มีไม่ครบ" โดยไม่มีอะไรฟ้อง ⇒ ต้องได้ **แถวแบนชุด
//    เดียวกันกับที่ checkbox ใช้** แล้วจัดกลุ่มจากข้อมูลชุดนั้น ไม่มีทางไม่ตรงกัน
//
// ⚠️ `batch_size` ที่แนบมากับแถวคือขนาด **ทั้งชุด** ⇒ ป้าย "แสดง N จาก M ใบ" คือสิ่งที่
//    บอกผู้ใช้ตามจริงว่าตัวกรองตัดสมาชิกออกไป และติ๊กชุดจะเลือกเฉพาะ **ที่เห็นบนจอ**
//    (ไม่แอบเลือกใบที่ผู้ใช้มองไม่เห็นแล้วโหลดเอกสารที่ตรวจไม่ได้ลงเครื่อง)

const grouped = computed(() => groupReceipts(items.value));
const rows = computed(() => grouped.value.rows);

/** ชุดที่กางอยู่ — เก็บเป็น id เพื่อให้คงสถานะกางไว้ได้หลัง `load()` รอบใหม่ */
const expandedBatchIds = ref<number[]>([]);

const isExpanded = (batchId: number): boolean => expandedBatchIds.value.includes(batchId);

const toggleExpand = (batchId: number) => {
  expandedBatchIds.value = isExpanded(batchId)
    ? expandedBatchIds.value.filter((id) => id !== batchId)
    : [...expandedBatchIds.value, batchId];
};

const selectedAmount = computed(() => selectedAmountOf(rows.value, selectedNos.value));

const allSelected = computed(() => allVisibleSelected(rows.value, selectedNos.value));

/**
 * "เลือกทั้งหมดในหน้านี้" — รวมสมาชิกของชุดที่เห็นบนจอด้วย
 * ⚠️ นับจาก `rows` ไม่ใช่ `items` โดยตรง เพื่อให้จำนวนที่เลือกตรงกับที่ enumerate จริง
 *    (ถ้าเขียนสองสูตรแยกกัน วันหนึ่งจะมีใบที่ถูกนับแต่ไม่ถูกเลือก หรือกลับกัน)
 */
const toggleSelectAll = () => {
  selectedNos.value = allSelected.value
    ? []
    : rows.value.flatMap((row) => visibleNosOf(row));
};

/**
 * สถานะติ๊กของแถว — `'some'` ต้องแยกจาก `'none'` (ดู `rowSelectionState`)
 *
 * ⚠️ รับ `ReceiptRow<ReceiptListItem>` แล้วส่งต่อให้ฟังก์ชันที่รับ `ReceiptRow<GroupableReceipt>`
 *    ได้ตรง ๆ — `ReceiptListItem` มีฟิลด์ครบตาม `GroupableReceipt` (ตัวหลังเป็น subset
 *    ที่ประกาศ optional ไว้) ⇒ **ไม่ต้อง cast** และไม่ควร cast เพราะจะปิด TypeScript
 *    ทิ้งทันทีที่มีคนเปลี่ยนชื่อฟิลด์ใน schema
 */
const rowState = (row: ReceiptRow<ReceiptListItem>) =>
  rowSelectionState(row, selectedNos.value);

const onToggleRow = (row: ReceiptRow<ReceiptListItem>) => {
  selectedNos.value = toggleRowSelection(row, selectedNos.value);
};

// ==========================================
// ✍️ จัดกลุ่ม/แก้ชื่อ/ยุบชุด (MANAGE_FINANCE)
// ==========================================

/** จำนวนขั้นต่ำของชุด — 1 ใบไม่ต้องมีชุด (ตรงกับ `AUTO_BATCH_MIN` ฝั่ง backend) */
const BATCH_MIN = 2;

const busyBatchId = ref<number | null>(null);
const isOrganizing = ref(false);

/** เลขที่ที่ติ๊กไว้และ **ยังอยู่บนจอ** — ใช้เป็น input ของการจัดชุด */
const selectedVisibleNos = computed(() => {
  const shown = new Set(items.value.map((r) => r.receipt_no));
  return selectedNos.value.filter((no) => shown.has(no));
});

const organizeSelectedAsBatch = async () => {
  if (!canManageFinance.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'การจัดชุดเอกสารต้องมีสิทธิ์จัดการการเงิน', 'warning');
    return;
  }
  const nos = selectedVisibleNos.value;
  if (nos.length < BATCH_MIN) {
    void dialog.alert(
      'เลือกไม่พอ',
      `ต้องเลือกอย่างน้อย ${BATCH_MIN} ฉบับจึงจะจัดเป็นชุดได้ (เลือกไว้ ${nos.length} ฉบับ)`,
      'warning',
    );
    return;
  }
  isOrganizing.value = true;
  try {
    const res = await FinanceService.createReceiptBatch(currentRoomId, { receipt_nos: nos });
    // 🔁 `created: false` = มีชุดที่สมาชิกชุดเดียวกันอยู่แล้ว — ไม่ใช่ความผิดพลาด
    //    ⇒ ต้องบอกให้ตรง อย่าขึ้น "สร้างสำเร็จ" ซึ่งทำให้ผู้ใช้คิดว่ามีชุดซ้ำ
    if (res.created) {
      await dialog.fire({
        icon: 'success',
        title: 'จัดเป็นชุดแล้ว',
        text: `รวม ${nos.length} ฉบับไว้ในชุดเดียวกัน`,
      });
    } else {
      await dialog.fire({
        icon: 'info',
        title: 'มีชุดนี้อยู่แล้ว',
        text: 'เอกสารชุดนี้ถูกจัดเป็นชุดไว้ก่อนหน้านี้แล้ว',
      });
    }
    selectedNos.value = [];
    await load();
  } catch (error: unknown) {
    void dialog.alert(
      'จัดชุดไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isOrganizing.value = false;
  }
};

/** เปลี่ยนชื่อชุด — เว้นว่าง = ล้างชื่อกลับไปใช้ชื่อที่ระบบประกอบให้ */
const renameBatch = async (batchId: number, currentTitle: string | null, fallback: string) => {
  const answer = await dialog.input('ตั้งชื่อชุดเอกสาร', {
    inputValue: currentTitle ?? '',
    inputPlaceholder: fallback,
    confirmButtonText: 'บันทึก',
    // ⚠️ ส่ง `null` (ไม่ใช่ `''`) เมื่อเว้นว่าง — backend แยก "ล้างชื่อ" ออกจาก "ไม่แก้"
    //    ด้วย `exclude_unset` ⇒ สตริงว่างจะกลายเป็นชื่อว่างจริง ๆ ไม่ใช่ชื่อที่ระบบประกอบ
    preConfirm: (value: string) => value.trim(),
  });
  if (!answer.isConfirmed) return;

  const next = answer.value === '' ? null : answer.value;
  if (next === (currentTitle ?? null)) return; // ไม่มีอะไรเปลี่ยน — ไม่ต้องยิง API

  busyBatchId.value = batchId;
  try {
    await FinanceService.updateReceiptBatch(currentRoomId, batchId, { title: next });
    await load();
  } catch (error: unknown) {
    void dialog.alert(
      'แก้ชื่อไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    busyBatchId.value = null;
  }
};

/**
 * ยุบชุด — 🔴 ต้องย้ำให้ชัดว่า **เอกสารไม่ถูกลบ** เพราะคำว่า "ยุบ/ลบ" ทำให้ผู้ใช้กลัวว่า
 * ใบเสร็จที่พิมพ์แจกไปแล้วจะหายไปด้วย
 */
const dissolveBatch = async (batchId: number, name: string, memberCount: number) => {
  const confirmed = await dialog.confirm(
    'ยุบชุดเอกสาร?',
    `${name} · เอกสารทั้ง ${memberCount} ฉบับยังอยู่ครบ — แค่หลุดออกจากชุด ยังดูและพิมพ์ได้ตามปกติ`,
    { icon: 'warning', confirmButtonText: 'ยุบชุด' },
  );
  if (!confirmed.isConfirmed) return;

  busyBatchId.value = batchId;
  try {
    const res = await FinanceService.deleteReceiptBatch(currentRoomId, batchId);
    expandedBatchIds.value = expandedBatchIds.value.filter((id) => id !== batchId);
    await load();
    await dialog.fire({
      icon: 'success',
      title: 'ยุบชุดแล้ว',
      text: `ปลด ${res.detached_count} ฉบับออกจากชุด (เอกสารยังอยู่ครบ)`,
    });
  } catch (error: unknown) {
    void dialog.alert(
      'ยุบชุดไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    busyBatchId.value = null;
  }
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
    void dialog.alert(
      'รวมไฟล์ไม่ได้ในครั้งเดียว',
      `เลือกไว้ ${selectedNos.value.length} ฉบับ แต่รวมได้ครั้งละไม่เกิน ${COMBINED_PDF_MAX} ฉบับ ` +
        '— กรุณาแคบช่วงวันที่ลงหรือเลือกน้อยลง',
      'warning',
    );
    return;
  }
  isDownloadingCombined.value = true;
  void dialog.loading('กำลังสร้างไฟล์ PDF...', 'ระบบกำลังรวมเอกสารเป็นไฟล์เดียว');
  try {
    const nos = [...selectedNos.value];
    const blob = await FinanceService.downloadCombinedPdf(currentRoomId, nos);
    // 🏷️ 'documents' เพราะในทะเบียนนี้เลือกปนกันได้ทั้งใบเสร็จและใบแจ้งหนี้
    //    ⇒ ชื่อไฟล์ต้องไม่แอบอ้างว่าเป็นชนิดใดชนิดหนึ่ง
    downloadBlob(blob, combinedPdfFilename(nos, 'documents'));
    dialog.close();
  } catch (error: unknown) {
    dialog.close();
    void dialog.alert(
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
    void dialog.alert(
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
    <PageIntro
      description="ทะเบียนเอกสารที่ออกแล้วของห้อง — เลขที่เอกสารเรียงตามปี พ.ศ. ของวันรับเงิน"
    ></PageIntro>

    <PeriodPicker v-model="period" :modes="['month', 'range']" />

    <!-- กรองชนิดเอกสาร: pill switch แบบเดียวกับโหมดของ PeriodPicker -->
    <div class="page-card p-3 sm:p-4">
      <p class="field-label mb-1.5">ชนิดเอกสาร</p>
      <!-- ⚠️ [F6] 6 chip บนจอ 375px: `flex-1` แถวเดียวจะบีบแต่ละปุ่มเหลือ ~60px
           จนป้ายถูกตัด ("ใบสำคัญ…") ⇒ มือถือใช้ grid 2 คอลัมน์ (ปุ่มสูง ≥44px ตาม §8)
           แล้วค่อยกลับเป็นแถวเดียวแบบ wrap ตั้งแต่ `sm` ขึ้นไป -->
      <div
        class="grid grid-cols-2 gap-1.5 sm:flex sm:flex-wrap sm:items-center"
        role="group"
        aria-label="กรองชนิดเอกสาร"
      >
        <button
          v-for="f in DOC_TYPE_FILTERS"
          :key="f.value"
          type="button"
          :aria-pressed="docTypeFilter === f.value"
          class="flex min-h-11 items-center justify-center gap-1.5 rounded-control px-2 py-2 text-sm font-bold transition-colors active:scale-[0.97] sm:px-4"
          :class="
            docTypeFilter === f.value
              ? 'bg-brand-700 text-white'
              : 'text-ink-3 hover:bg-canvas hover:text-ink'
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
        <p class="text-caption font-bold text-ink-3">เอกสาร</p>
        <p class="num mt-1 text-xl font-bold text-ink">{{ items.length }}</p>
        <p class="mt-0.5 text-caption text-ink-3">{{ describePeriod(period) }}</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-caption font-bold text-ink-3">ยอดรับเงิน</p>
        <p class="num mt-1 text-xl font-bold text-ok-700">
          {{ formatMoney(receivedTotal) }}
        </p>
        <p class="mt-0.5 text-caption text-ink-3">เฉพาะที่แสดงอยู่ (ไม่รวมใบแจ้งหนี้)</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-caption font-bold text-ink-3">ยอดจ่ายเงิน</p>
        <p class="num mt-1 text-xl font-bold text-ink">
          {{ formatMoney(paidTotal) }}
        </p>
        <p class="mt-0.5 text-caption text-ink-3">ใบสำคัญจ่ายที่แสดงอยู่</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-caption font-bold text-ink-3">เอกสารรับเงิน</p>
        <p class="num mt-1 text-xl font-bold text-ok-700">{{ receiptCount }}</p>
        <p class="mt-0.5 text-caption text-ink-3">ใบเสร็จ · รับล่วงหน้า · ใบรับเงิน</p>
      </div>
      <div class="page-card p-3.5">
        <p class="text-caption font-bold text-ink-3">ใบแจ้งหนี้</p>
        <p class="num mt-1 text-xl font-bold text-warn-700">{{ invoiceCount }}</p>
        <p class="mt-0.5 text-caption text-ink-3">เอกสารเรียกเก็บ</p>
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
          class="chip bg-warn-50 text-warn-700"
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
            <p class="min-w-0 truncate text-xs font-bold text-ink-3">
              <template v-if="selectedNos.length">
                เลือก <span class="num text-brand-700">{{ selectedNos.length }}</span> ฉบับ —
                รวม {{ formatMoney(selectedAmount) }}
              </template>
              <template v-else>ติ๊กเลือกเอกสารเพื่อรวมเป็นไฟล์เดียว (หน้าละใบ)</template>
            </p>
          </div>
          <div v-if="selectedNos.length" class="flex shrink-0 flex-wrap items-center gap-2">
            <!-- 📚 จัดกลุ่มทีหลัง — ทางเลือกของผู้ใช้ (ระบบจัดชุดให้แล้วตอนออกเอกสาร) -->
            <!-- 🔒 gate ด้วย canManageFinance ไม่ใช่ isAdmin (ดูคอมเมนต์บนสุดของสคริปต์) -->
            <button
              v-if="canManageFinance"
              type="button"
              class="btn-ghost-ui"
              :disabled="isOrganizing || selectedVisibleNos.length < BATCH_MIN"
              :title="
                selectedVisibleNos.length < BATCH_MIN
                  ? `ต้องเลือกอย่างน้อย ${BATCH_MIN} ฉบับ`
                  : 'รวมเอกสารที่เลือกไว้เป็นชุดเดียว'
              "
              @click="organizeSelectedAsBatch"
            >
              <i
                class="bi"
                :class="isOrganizing ? 'bi-hourglass-split' : 'bi-collection'"
                aria-hidden="true"
              ></i>
              จัดเป็นชุด
            </button>
            <button
              type="button"
              class="btn-primary"
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
        </div>

        <!-- 📱 มือถือ -->
        <div class="space-y-2.5 lg:hidden">
          <template v-for="row in rows" :key="row.key">
            <!-- 📚 การ์ดชุด — ยุบไว้ก่อน กดchevron เพื่อกางดูเอกสารข้างใน -->
            <div v-if="row.kind === 'batch'" class="page-card overflow-hidden">
              <div class="p-4">
                <div class="flex items-start justify-between gap-3">
                  <div class="flex min-w-0 items-start gap-2">
                    <label class="flex cursor-pointer items-center pt-0.5">
                      <input
                        type="checkbox"
                        class="peer sr-only"
                        :checked="rowState(row) === 'all'"
                        :indeterminate.prop="rowState(row) === 'some'"
                        :aria-label="`เลือกเอกสารทั้งชุด ${batchDisplayName(row)} เพื่อรวมไฟล์`"
                        @change="onToggleRow(row)"
                      />
                      <span
                        class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                        :class="
                          rowState(row) === 'none'
                            ? 'border-line bg-surface'
                            : 'border-brand-700 bg-brand-700'
                        "
                      >
                        <i
                          v-if="rowState(row) === 'all'"
                          class="bi bi-check-lg text-xs font-bold text-white"
                          aria-hidden="true"
                        ></i>
                        <i
                          v-else-if="rowState(row) === 'some'"
                          class="bi bi-dash-lg text-xs font-bold text-white"
                          aria-hidden="true"
                        ></i>
                      </span>
                    </label>
                    <div class="min-w-0">
                      <button
                        type="button"
                        class="flex min-h-11 min-w-0 items-center gap-1.5 text-left"
                        :aria-expanded="isExpanded(row.batchId)"
                        @click="toggleExpand(row.batchId)"
                      >
                        <i
                          class="bi shrink-0 text-ink-3 transition-transform"
                          :class="isExpanded(row.batchId) ? 'bi-chevron-down' : 'bi-chevron-right'"
                          aria-hidden="true"
                        ></i>
                        <span class="truncate font-bold text-ink">
                          {{ batchDisplayName(row) }}
                        </span>
                      </button>
                      <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
                        <!-- 🔴 ขนาดชุดต้องมาจาก batch_size ของ backend เสมอ -->
                        <span
                          v-if="batchVisibilityNote(row)"
                          class="chip bg-warn-50 text-warn-700"
                        >
                          <i class="bi bi-funnel" aria-hidden="true"></i>
                          {{ batchVisibilityNote(row) }}
                        </span>
                        <span v-if="batchVoidedNote(row)" class="chip bg-danger-50 text-danger-700">
                          {{ batchVoidedNote(row) }}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div class="shrink-0 text-right">
                    <p class="num text-base font-bold text-ink">
                      {{ formatMoney(rowAmount(row)) }}
                    </p>
                    <span class="chip mt-1 bg-canvas text-ink-2">
                      {{ row.visibleCount }}/{{ row.batchSize }} ใบ
                    </span>
                  </div>
                </div>

                <!-- 🔒 ปุ่มจัดการชุด — gate ด้วย canManageFinance -->
                <div
                  v-if="canManageFinance"
                  class="mt-2.5 flex items-center justify-end gap-2 border-t border-line pt-2.5"
                >
                  <button
                    type="button"
                    class="btn-ghost-ui"
                    :disabled="busyBatchId === row.batchId"
                    @click="renameBatch(row.batchId, row.title, batchDisplayName(row))"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                    ตั้งชื่อ
                  </button>
                  <button
                    type="button"
                    class="btn-ghost-ui text-danger-600"
                    :disabled="busyBatchId === row.batchId"
                    @click="dissolveBatch(row.batchId, batchDisplayName(row), row.visibleCount)"
                  >
                    <i class="bi bi-x-square" aria-hidden="true"></i>
                    ยุบชุด
                  </button>
                </div>
              </div>

              <!-- กางออก = สมาชิกที่เห็นในตัวกรองปัจจุบัน (ป้ายด้านบนบอกถ้าไม่ครบ) -->
              <div v-if="isExpanded(row.batchId)" class="space-y-2 border-t border-line p-3">
                <div
                  v-for="m in row.items"
                  :key="m.id"
                  class="rounded-control bg-canvas p-3"
                >
                  <div class="flex items-start justify-between gap-3">
                    <label class="flex min-w-0 cursor-pointer items-center gap-2">
                      <input
                        v-model="selectedNos"
                        type="checkbox"
                        :value="m.receipt_no"
                        :aria-label="`เลือกเอกสาร ${m.receipt_no} เพื่อรวมไฟล์`"
                        class="peer sr-only"
                      />
                      <span
                        class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                        :class="
                          selectedNos.includes(m.receipt_no)
                            ? 'border-brand-700 bg-brand-700'
                            : 'border-line bg-surface'
                        "
                      >
                        <i
                          v-if="selectedNos.includes(m.receipt_no)"
                          class="bi bi-check-lg text-xs font-bold text-white"
                          aria-hidden="true"
                        ></i>
                      </span>
                      <span class="num truncate text-sm font-bold text-ink">
                        {{ m.receipt_no }}
                      </span>
                    </label>
                    <p class="num shrink-0 text-sm font-bold text-ink">
                      {{ formatMoney(m.amount) }}
                    </p>
                  </div>
                  <div class="mt-1.5 flex items-center justify-between gap-3">
                    <p class="min-w-0 truncate text-xs text-ink-3">
                      {{ m.issued_to_name || '—' }}
                      <span v-if="m.student_no" class="num">— เลขที่ {{ m.student_no }}</span>
                    </p>
                    <div class="flex shrink-0 items-center gap-2">
                      <RouterLink
                        :to="`/finance/receipts/${m.receipt_no}`"
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
                        @click="downloadPdf(m)"
                      >
                        <i
                          class="bi"
                          :class="downloadingNo === m.receipt_no ? 'bi-hourglass-split' : 'bi-printer'"
                          aria-hidden="true"
                        ></i>
                        PDF
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 🧾 เอกสารเดี่ยว (ไม่ได้อยู่ในชุด) — รูปเดิมทั้งหมด -->
            <div v-else class="page-card p-4">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <label class="flex cursor-pointer items-center gap-2">
                    <input
                      v-model="selectedNos"
                      type="checkbox"
                      :value="row.item.receipt_no"
                      :aria-label="`เลือกเอกสาร ${row.item.receipt_no} เพื่อรวมไฟล์`"
                      class="peer sr-only"
                    />
                    <span
                      class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                      :class="
                        selectedNos.includes(row.item.receipt_no)
                          ? 'border-brand-700 bg-brand-700'
                          : 'border-line bg-surface'
                      "
                    >
                      <i
                        v-if="selectedNos.includes(row.item.receipt_no)"
                        class="bi bi-check-lg text-xs font-bold text-white"
                        aria-hidden="true"
                      ></i>
                    </span>
                    <span class="num truncate text-sm font-bold text-ink">
                      {{ row.item.receipt_no }}
                    </span>
                  </label>
                  <p class="mt-0.5 truncate text-xs text-ink-3">
                    {{ row.item.issued_to_name || '—' }}
                    <span v-if="row.item.student_no" class="num">
                      — เลขที่ {{ row.item.student_no }}
                    </span>
                  </p>
                  <p v-if="row.item.collection_title" class="truncate text-xs text-ink-3">
                    {{ row.item.collection_title }}
                  </p>
                </div>
                <div class="shrink-0 text-right">
                  <p class="num text-base font-bold text-ink">
                    {{ formatMoney(row.item.amount) }}
                  </p>
                  <span class="chip mt-1" :class="docChipClass(row.item.doc_type)">
                    {{ row.item.doc_type_label || row.item.doc_type }}
                  </span>
                </div>
              </div>

              <div
                class="mt-2.5 flex items-center justify-between gap-3 border-t border-line pt-2.5"
              >
                <small class="num truncate text-caption font-bold text-ink-3">
                  <i class="bi bi-clock" aria-hidden="true"></i>
                  {{ formatThaiDateTime(row.item.issued_at) }}
                </small>
                <div class="flex shrink-0 items-center gap-2">
                  <RouterLink
                    :to="`/finance/receipts/${row.item.receipt_no}`"
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
                    @click="downloadPdf(row.item)"
                  >
                    <i
                      class="bi"
                      :class="
                        downloadingNo === row.item.receipt_no ? 'bi-hourglass-split' : 'bi-printer'
                      "
                      aria-hidden="true"
                    ></i>
                    PDF
                  </button>
                </div>
              </div>
            </div>
          </template>
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
                          allSelected ? 'border-brand-700 bg-brand-700' : 'border-line bg-surface'
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
                <template v-for="row in rows" :key="row.key">
                  <!-- 📚 แถวชุด — ยุบไว้ก่อน กดchevron เพื่อกางเอกสารข้างในออกมา -->
                  <template v-if="row.kind === 'batch'">
                    <tr class="bg-canvas">
                      <td>
                        <label class="flex cursor-pointer items-center">
                          <input
                            type="checkbox"
                            class="peer sr-only"
                            :checked="rowState(row) === 'all'"
                            :indeterminate.prop="rowState(row) === 'some'"
                            :aria-label="`เลือกเอกสารทั้งชุด ${batchDisplayName(row)} เพื่อรวมไฟล์`"
                            @change="onToggleRow(row)"
                          />
                          <span
                            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                            :class="
                              rowState(row) === 'none'
                                ? 'border-line bg-surface'
                                : 'border-brand-700 bg-brand-700'
                            "
                          >
                            <i
                              v-if="rowState(row) === 'all'"
                              class="bi bi-check-lg text-xs font-bold text-white"
                              aria-hidden="true"
                            ></i>
                            <i
                              v-else-if="rowState(row) === 'some'"
                              class="bi bi-dash-lg text-xs font-bold text-white"
                              aria-hidden="true"
                            ></i>
                          </span>
                        </label>
                      </td>
                      <td colspan="5">
                        <button
                          type="button"
                          class="flex w-full items-center gap-2 text-left"
                          :aria-expanded="isExpanded(row.batchId)"
                          @click="toggleExpand(row.batchId)"
                        >
                          <i
                            class="bi shrink-0 text-ink-3"
                            :class="isExpanded(row.batchId) ? 'bi-chevron-down' : 'bi-chevron-right'"
                            aria-hidden="true"
                          ></i>
                          <span class="chip shrink-0 bg-line text-ink-2">
                            <i class="bi bi-collection" aria-hidden="true"></i>
                            ชุด
                          </span>
                          <span class="min-w-0 truncate font-bold text-ink">
                            {{ batchDisplayName(row) }}
                          </span>
                          <!-- 🔴 บอกตามจริงเมื่อตัวกรองตัดสมาชิกออก — ห้ามเงียบ -->
                          <span
                            v-if="batchVisibilityNote(row)"
                            class="chip shrink-0 bg-warn-50 text-warn-700"
                          >
                            <i class="bi bi-funnel" aria-hidden="true"></i>
                            {{ batchVisibilityNote(row) }}
                          </span>
                          <span
                            v-if="batchVoidedNote(row)"
                            class="chip shrink-0 bg-danger-50 text-danger-700"
                          >
                            {{ batchVoidedNote(row) }}
                          </span>
                        </button>
                      </td>
                      <td
                        class="num whitespace-nowrap text-right font-bold text-ink"
                      >
                        {{ formatMoney(rowAmount(row)) }}
                      </td>
                      <td>
                        <div v-if="canManageFinance" class="flex justify-end gap-2">
                          <button
                            type="button"
                            class="btn-ghost-ui"
                            :disabled="busyBatchId === row.batchId"
                            title="ตั้งชื่อชุด"
                            @click="renameBatch(row.batchId, row.title, batchDisplayName(row))"
                          >
                            <i class="bi bi-pencil" aria-hidden="true"></i>
                            ตั้งชื่อ
                          </button>
                          <button
                            type="button"
                            class="btn-ghost-ui text-danger-600"
                            :disabled="busyBatchId === row.batchId"
                            title="ยุบชุด (เอกสารไม่ถูกลบ)"
                            @click="dissolveBatch(row.batchId, batchDisplayName(row), row.visibleCount)"
                          >
                            <i class="bi bi-x-square" aria-hidden="true"></i>
                            ยุบชุด
                          </button>
                        </div>
                      </td>
                    </tr>

                    <!-- สมาชิกของชุด — แสดงเมื่อกางออก (เฉพาะที่รอดตัวกรองปัจจุบัน) -->
                    <tr
                      v-for="m in row.items"
                      v-show="isExpanded(row.batchId)"
                      :key="`m:${m.id}`"
                      class="border-l-2 border-line"
                    >
                      <td class="pl-4">
                        <label class="flex cursor-pointer items-center">
                          <input
                            v-model="selectedNos"
                            type="checkbox"
                            :value="m.receipt_no"
                            :aria-label="`เลือกเอกสาร ${m.receipt_no} เพื่อรวมไฟล์`"
                            class="peer sr-only"
                          />
                          <span
                            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                            :class="
                              selectedNos.includes(m.receipt_no)
                                ? 'border-brand-700 bg-brand-700'
                                : 'border-line bg-surface'
                            "
                          >
                            <i
                              v-if="selectedNos.includes(m.receipt_no)"
                              class="bi bi-check-lg text-xs font-bold text-white"
                              aria-hidden="true"
                            ></i>
                          </span>
                        </label>
                      </td>
                      <td class="num pl-4 font-bold text-ink">{{ m.receipt_no }}</td>
                      <td class="num whitespace-nowrap text-ink-3">
                        {{ formatThaiDateTime(m.issued_at) }}
                      </td>
                      <td>
                        <span class="chip" :class="docChipClass(m.doc_type)">
                          {{ m.doc_type_label || m.doc_type }}
                        </span>
                      </td>
                      <td>
                        <p class="font-bold text-ink">{{ m.issued_to_name || '—' }}</p>
                        <p v-if="m.student_no" class="num text-xs text-ink-3">
                          เลขที่ {{ m.student_no }}
                        </p>
                      </td>
                      <td class="max-w-[18rem] truncate text-ink-3">
                        {{ m.collection_title || '—' }}
                      </td>
                      <td
                        class="num whitespace-nowrap text-right font-bold text-ink"
                      >
                        {{ formatMoney(m.amount) }}
                      </td>
                      <td>
                        <div class="flex justify-end gap-2">
                          <RouterLink
                            :to="`/finance/receipts/${m.receipt_no}`"
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
                            @click="downloadPdf(m)"
                          >
                            <i
                              class="bi"
                              :class="
                                downloadingNo === m.receipt_no ? 'bi-hourglass-split' : 'bi-printer'
                              "
                              aria-hidden="true"
                            ></i>
                            PDF
                          </button>
                        </div>
                      </td>
                    </tr>
                  </template>

                  <!-- 🧾 แถวเอกสารเดี่ยว — รูปเดิมทั้งหมด -->
                  <tr v-else>
                    <td>
                      <label class="flex cursor-pointer items-center">
                        <input
                          v-model="selectedNos"
                          type="checkbox"
                          :value="row.item.receipt_no"
                          :aria-label="`เลือกเอกสาร ${row.item.receipt_no} เพื่อรวมไฟล์`"
                          class="peer sr-only"
                        />
                        <span
                          class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                          :class="
                            selectedNos.includes(row.item.receipt_no)
                              ? 'border-brand-700 bg-brand-700'
                              : 'border-line bg-surface'
                          "
                        >
                          <i
                            v-if="selectedNos.includes(row.item.receipt_no)"
                            class="bi bi-check-lg text-xs font-bold text-white"
                            aria-hidden="true"
                          ></i>
                        </span>
                      </label>
                    </td>
                    <td class="num font-bold text-ink">{{ row.item.receipt_no }}</td>
                    <td class="num whitespace-nowrap text-ink-3">
                      {{ formatThaiDateTime(row.item.issued_at) }}
                    </td>
                    <td>
                      <span class="chip" :class="docChipClass(row.item.doc_type)">
                        {{ row.item.doc_type_label || row.item.doc_type }}
                      </span>
                    </td>
                    <td>
                      <p class="font-bold text-ink">{{ row.item.issued_to_name || '—' }}</p>
                      <p v-if="row.item.student_no" class="num text-xs text-ink-3">
                        เลขที่ {{ row.item.student_no }}
                      </p>
                    </td>
                    <td class="max-w-[18rem] truncate text-ink-3">
                      {{ row.item.collection_title || '—' }}
                    </td>
                    <td
                      class="num whitespace-nowrap text-right font-bold text-ink"
                    >
                      {{ formatMoney(row.item.amount) }}
                    </td>
                    <td>
                      <div class="flex justify-end gap-2">
                        <RouterLink
                          :to="`/finance/receipts/${row.item.receipt_no}`"
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
                          @click="downloadPdf(row.item)"
                        >
                          <i
                            class="bi"
                            :class="
                              downloadingNo === row.item.receipt_no
                                ? 'bi-hourglass-split'
                                : 'bi-printer'
                            "
                            aria-hidden="true"
                          ></i>
                          PDF
                        </button>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
