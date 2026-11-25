<script setup lang="ts">
/**
 * 📊 [FIN-V2 / P5.5] MonthlyReportWizard — สร้าง/ปิดงบรายเดือน (RPT)
 *
 * ใช้ component เดียวสองโหมด:
 *   - `finance-monthly-report-new` (`/finance/monthly-reports/new`) — ฟอร์มสร้างฉบับร่าง
 *   - `finance-monthly-report` (`/finance/monthly-reports/:id(\d+)`) — วิซาร์ด 3 การ์ด
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ห้ามละเมิด
 * ═══════════════════════════════════════════════════════════════════════════
 * 1. 🚫 **ห้ามคำนวณยอดรายรับ/รายจ่าย/เงินสดปิดใน FE** — อ่านจาก `snapshot` ของ backend
 *    ที่ตรึงไว้ตอนออกฉบับร่างเท่านั้น (ยอดหลังออกใบแล้วอาจต่างจากวันนี้)
 * 2. 🔢 `counted_cash` ส่งเป็น **string ทศนิยม 2 ตำแหน่ง** เท่านั้น — ห้ามส่ง number
 *    (floating point ทำให้ backend เห็นผลต่าง 1e-12 แล้วตอบ 400 ทั้งที่กรอกถูก)
 * 3. ✅ ปุ่มปิดงบเปิดเฉพาะ `canFinalize(variance)` — เกณฑ์เดียวกับ backend (|v| < 0.005)
 *    แสดงข้อความบอกเหตุผลเมื่อกดไม่ได้ อย่าปล่อยให้กดแล้วเจอ 400 เปล่า ๆ
 * 4. ↔️ สร้างเสร็จใช้ `router.replace` — กด back ต้องไม่กลับไปฟอร์มสร้างซ้ำ
 *
 * 🗓️ ปีเป็น **พ.ศ.** ตามที่ backend เก็บ (`year_be`) — ไม่แปลงเป็น ค.ศ. บนจอ
 * 📌 เดือนปริยาย = **เดือนก่อน** (ปิดงบเมื่อสิ้นเดือน) และปีถอยเมื่อเดือนก่อนคือธ.ค.
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import AppButton from '@/components/ui/AppButton.vue';
import CashCountPanel from '@/components/finance/CashCountPanel.vue';

import { FinanceService } from '@/services/finance';
import { apiStatus } from '@/services/api';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { downloadBlob } from '@/utils/download';
import { formatMoney } from '@/utils/money';
import { formatThaiDateTime, THAI_MONTHS } from '@/utils/datetime';
import { todayThaiYearMonth } from '@/utils/period';
import { canFinalize, computeVariance, normalizeCashInput, varianceMessage } from '@/utils/cashVariance';
import type { MonthlyReportDetailResponse, MonthlyReportResponse } from '@/types/finance';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const dialog = useDialog();

const currentRoomId = authStore.currentRoomId!;
const canManageFinance = computed(() => authStore.canManageFinance);

// ══════════════════════════════════════════════════════════════════════════
// โหมด: อ่าน `:id` (ตัวเลขเท่านั้น) — route ใหม่ไม่มี param นี้
// ══════════════════════════════════════════════════════════════════════════
const reportId = computed<number | null>(() => {
  const raw = route.params.id;
  if (typeof raw !== 'string' || !/^\d+$/.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
});
const isNewMode = computed(() => reportId.value === null);

// ══════════════════════════════════════════════════════════════════════════
// โหมด new — ฟอร์มสร้างฉบับร่าง
// ══════════════════════════════════════════════════════════════════════════
const nowYm = todayThaiYearMonth();
const queryYear = Number(route.query.year);
const queryMonth = Number(route.query.month);

const defaultYearBe =
  Number.isInteger(queryYear) && queryYear >= 2500 && queryYear <= 2700
    ? queryYear
    : nowYm.month === 1
      ? nowYm.year + 543 - 1
      : nowYm.year + 543;
const defaultMonth =
  Number.isInteger(queryMonth) && queryMonth >= 1 && queryMonth <= 12
    ? queryMonth
    : nowYm.month === 1
      ? 12
      : nowYm.month - 1;

const formYearBe = ref<number>(defaultYearBe);
const formMonth = ref<number>(defaultMonth);
const formNote = ref('');
const isCreating = ref(false);

const MONTH_OPTIONS = THAI_MONTHS.map((label, index) => ({ value: index + 1, label }));

// ══════════════════════════════════════════════════════════════════════════
// โหมด id — วิซาร์ด 3 การ์ด
// ══════════════════════════════════════════════════════════════════════════
const detail = ref<MonthlyReportDetailResponse | null>(null);
const isLoading = ref(false);
const hasError = ref(false);
const isNotFound = ref(false);
const isDownloadingPdf = ref(false);
const isFinalizing = ref(false);
const isVoiding = ref(false);

/** ยอดนับได้ (string ที่ normalize แล้ว) — seed จาก backend เมื่อปิดงบไปแล้ว */
const counted = ref<string>('');
const finalizeNote = ref('');

const report = computed<MonthlyReportResponse | null>(() => detail.value?.report ?? null);
const isDraft = computed(() => report.value?.status === 'draft');
const isFinal = computed(() => report.value?.status === 'final');
const isVoided = computed(() => report.value?.status === 'voided');
/** แก้ไขได้เฉพาะฉบับร่าง (หลังปิดงบ/ยกเลิก ห้ามแก้ยอด) */
const isEditable = computed(() => isDraft.value && canManageFinance.value);

const expectedCash = computed(() => report.value?.closing_cash ?? 0);
const variance = computed(() =>
  report.value === null ? null : computeVariance(counted.value, expectedCash.value),
);
const canSubmitFinalize = computed(
  () => isEditable.value && !isFinalizing.value && canFinalize(variance.value),
);

const periodLabel = computed(() =>
  report.value
    ? `${THAI_MONTHS[report.value.month - 1] ?? report.value.month} ${report.value.year_be}`
    : '',
);

const incomeLines = computed(() => report.value?.snapshot.income_by_category ?? []);
const expenseLines = computed(() => report.value?.snapshot.expense_by_category ?? []);

const seedCounted = (res: MonthlyReportDetailResponse) => {
  const raw = res.report.counted_cash;
  counted.value = raw === null ? '' : raw.toFixed(2);
  finalizeNote.value = res.report.snapshot.finalize_note ?? '';
};

const load = async () => {
  if (reportId.value === null) {
    detail.value = null;
    hasError.value = false;
    isNotFound.value = false;
    return;
  }
  isLoading.value = true;
  hasError.value = false;
  isNotFound.value = false;
  try {
    const res = await FinanceService.getMonthlyReport(currentRoomId, reportId.value);
    detail.value = res;
    seedCounted(res);
  } catch (error: unknown) {
    detail.value = null;
    if (apiStatus(error) === 404) isNotFound.value = true;
    else hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

watch(reportId, () => {
  void load();
});

onMounted(() => {
  void load();
});

const createReport = async () => {
  if (isCreating.value) return;
  if (!Number.isInteger(formYearBe.value) || formYearBe.value < 2500 || formYearBe.value > 2700) {
    void dialog.alert('ปีไม่ถูกต้อง', 'กรุณาระบุปี พ.ศ. 4 หลัก (เช่น 2569)', 'error');
    return;
  }
  if (!Number.isInteger(formMonth.value) || formMonth.value < 1 || formMonth.value > 12) {
    void dialog.alert('เดือนไม่ถูกต้อง', 'กรุณาเลือกเดือน 1–12', 'error');
    return;
  }

  isCreating.value = true;
  try {
    const payload = {
      year_be: formYearBe.value,
      month: formMonth.value,
      ...(formNote.value.trim() ? { note: formNote.value.trim() } : {}),
    };
    const res = await FinanceService.createMonthlyReport(currentRoomId, payload);
    dialog.notify(`สร้างฉบับร่าง ${res.report.report_no} แล้ว — ตรวจยอดและนับเงินสดต่อได้เลย`);
    detail.value = res;
    seedCounted(res);
    // ↔️ replace: ปุ่ม back ต้องไม่พากลับไปฟอร์มสร้างซ้ำ
    await router.replace({ name: 'finance-monthly-report', params: { id: res.report.id } });
  } catch (error: unknown) {
    void dialog.alert(
      'สร้างรายงานปิดงบไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isCreating.value = false;
  }
};

// ── ส่งค่าให้ backend ────────────────────────────────────────────────────────
/** เติมทศนิยมให้ครบ 2 ตำแหน่งเป็น string — ห้ามแปลงเป็น number (ดูหัวไฟล์ ข้อ 2) */
const toTwoDecimals = (raw: string): string => {
  const normalized = normalizeCashInput(raw);
  const [whole = '0', frac = ''] = normalized.split('.');
  return `${whole || '0'}.${(frac + '00').slice(0, 2)}`;
};

const finalizeReport = async () => {
  if (!report.value || !canSubmitFinalize.value) return;

  const confirm = await dialog.confirm(
    'ปิดงบทันที?',
    `${varianceMessage(counted.value, expectedCash.value)} — หลังปิดงบจะแก้ยอดไม่ได้ (ต้องยกเลิกและออกเวอร์ชันใหม่)`,
    { confirmButtonText: 'ปิดงบ' },
  );
  if (!confirm.isConfirmed) return;

  isFinalizing.value = true;
  try {
    const payload: { counted_cash: string; note?: string } = {
      counted_cash: toTwoDecimals(counted.value),
    };
    const trimmedNote = finalizeNote.value.trim();
    if (trimmedNote) payload.note = trimmedNote;

    const res = await FinanceService.finalizeMonthlyReport(
      currentRoomId,
      report.value.id,
      payload,
    );
    detail.value = res;
    seedCounted(res);
    dialog.notify(`ปิดงบ ${res.report.report_no} แล้ว`);
  } catch (error: unknown) {
    // 400 มักเป็นยอดต่าง — แสดงข้อความ backend ตรง ๆ (เขาเป็นเจ้าของสูตร)
    void dialog.alert(
      'ปิดงบไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาตรวจยอดนับได้อีกครั้ง',
      'error',
    );
  } finally {
    isFinalizing.value = false;
  }
};

const voidReport = async () => {
  if (!report.value || isVoiding.value) return;
  const result = await dialog.confirm(
    'ยกเลิกรายงานปิดงบนี้?',
    'เลขที่เอกสารจะถูกเก็บไว้เป็นหลักฐาน — ต้องออกเวอร์ชันใหม่ถ้าต้องการปิดงบเดือนนี้',
    {
      danger: true,
      confirmButtonText: 'ยกเลิกรายงาน',
      input: 'textarea',
      inputLabel: 'เหตุผลที่ยกเลิก (บังคับ)',
      inputPlaceholder: 'เช่น นับเงินสดผิด / มีรายการค้างบันทึก',
      preConfirm: (value: string) => {
        const trimmed = value.trim();
        if (!trimmed) throw new Error('กรุณาระบุเหตุผลที่ยกเลิก');
        return trimmed;
      },
    },
  );
  if (!result.isConfirmed) return;

  isVoiding.value = true;
  try {
    await FinanceService.voidMonthlyReport(currentRoomId, report.value.id, {
      reason: result.value.trim(),
    });
    dialog.notify('ยกเลิกรายงานแล้ว');
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

const downloadPdf = async () => {
  if (!report.value || isDownloadingPdf.value) return;
  isDownloadingPdf.value = true;
  try {
    const blob = await FinanceService.downloadMonthlyReportPdf(currentRoomId, report.value.id);
    // 🏷️ เลขเอกสารมีขีดกลางอยู่แล้ว — ล้างเฉพาะอักขระต้องห้ามของ filesystem
    const safeName = report.value.report_no.replace(/[\\/:*?"<>|\s]/g, '-');
    downloadBlob(blob, `${safeName}.pdf`);
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

const startNewVersion = () => {
  if (!report.value) return;
  void router.push({
    name: 'finance-monthly-report-new',
    query: { year: String(report.value.year_be), month: String(report.value.month) },
  });
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <!-- ═════════════════════════ โหมดสร้างใหม่ ═════════════════════════ -->
    <template v-if="isNewMode">
      <PageIntro
        title="สร้างรายงานปิดงบ"
        description="ระบบจะสรุปยอดรายรับ-รายจ่ายของเดือนเป็นฉบับร่างก่อน แล้วค่อยตรวจนับเงินสดเพื่อปิดงบ"
      />

      <div class="page-card max-w-xl space-y-4 p-4 sm:p-5">
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label class="field-label" for="rpt-new-year">ปี (พ.ศ.)</label>
            <input
              id="rpt-new-year"
              v-model.number="formYearBe"
              class="field num"
              type="number"
              inputmode="numeric"
              min="2500"
              max="2700"
              :disabled="isCreating"
            />
          </div>
          <div>
            <label class="field-label" for="rpt-new-month">เดือน</label>
            <select
              id="rpt-new-month"
              v-model.number="formMonth"
              class="field"
              :disabled="isCreating"
            >
              <option v-for="option in MONTH_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>
        </div>

        <div>
          <label class="field-label" for="rpt-new-note">หมายเหตุ (ไม่บังคับ)</label>
          <textarea
            id="rpt-new-note"
            v-model="formNote"
            class="field min-h-20"
            maxlength="255"
            :disabled="isCreating"
            placeholder="เช่น ปิดงบต้นเดือนหลังเก็บเงินรอบสุดท้าย"
          ></textarea>
        </div>

        <div class="flex gap-2 rounded-control border border-line bg-canvas px-3 py-2.5">
          <i class="bi bi-info-circle mt-0.5 text-ink-3" aria-hidden="true"></i>
          <p class="text-caption leading-relaxed text-ink-2">
            สร้างแล้วระบบจะดึงยอดจากบัญชี ณ วันสิ้นเดือนที่เลือกไว้เป็น snapshot
            — ยอดจะไม่เปลี่ยนตามการแก้ไขเอกสารภายหลัง และยังไม่ถือว่าปิดงบจนกว่าจะยืนยันยอดนับ
          </p>
        </div>

        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <RouterLink to="/finance/monthly-reports" class="btn-ghost-ui justify-center">
            ยกเลิก
          </RouterLink>
          <AppButton variant="primary" :loading="isCreating" @click="createReport">
            สร้างฉบับร่าง
          </AppButton>
        </div>
      </div>
    </template>

    <!-- ═════════════════════════ โหมดรายละเอียด ═════════════════════════ -->
    <template v-else>
      <PageIntro
        :description="
          report
            ? `${report.report_no} · งวด ${periodLabel}`
            : 'รายงานปิดงบเดือน'
        "
      >
        <template #actions>
          <AppButton
            variant="secondary"
            :loading="isDownloadingPdf"
            :disabled="!report"
            @click="downloadPdf"
          >
            <i v-if="!isDownloadingPdf" class="bi bi-printer" aria-hidden="true"></i>
            ดาวน์โหลด PDF
          </AppButton>
          <AppButton
            v-if="canManageFinance && report && !isVoided"
            variant="danger"
            :loading="isVoiding"
            @click="voidReport"
          >
            ยกเลิก
          </AppButton>
        </template>
      </PageIntro>

      <SkeletonRows v-if="isLoading" :rows="3" height="h-32" />
      <StateBlock
        v-else-if="isNotFound"
        variant="empty"
        title="ไม่พบรายงานปิดงบนี้"
        hint="อาจถูกลบไปแล้ว หรือลิงก์ไม่ถูกต้อง"
        icon="bi-file-earmark-x"
      >
        <RouterLink to="/finance/monthly-reports" class="btn-ghost-ui mt-2">
          กลับหน้ารายงานปิดงบ
        </RouterLink>
      </StateBlock>
      <StateBlock
        v-else-if="hasError || !report"
        variant="error"
        hint="โหลดรายงานปิดงบไม่สำเร็จ"
        @retry="load"
      />

      <template v-else>
        <!-- แบนเนอร์สถานะ -->
        <div
          v-if="isVoided"
          class="flex flex-wrap items-start justify-between gap-3 rounded-card border border-danger-200 bg-danger-50 px-3.5 py-3"
          role="status"
        >
          <div class="flex min-w-0 gap-2.5">
            <i class="bi bi-slash-circle mt-0.5 text-danger-600" aria-hidden="true"></i>
            <div class="text-sm leading-relaxed text-danger-700">
              <p class="font-bold">รายงานนี้ถูกยกเลิกแล้ว</p>
              <p v-if="report.void_reason" class="mt-0.5">เหตุผล: {{ report.void_reason }}</p>
            </div>
          </div>
          <AppButton v-if="canManageFinance" variant="secondary" @click="startNewVersion">
            ออกเวอร์ชันใหม่
          </AppButton>
        </div>

        <!-- ═══ การ์ด 1: สรุปจากบัญชี ═══ -->
        <div class="page-card p-4 sm:p-5">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="section-title">สรุปจากบัญชี (snapshot)</h2>
            <span
              class="chip"
              :class="
                isVoided
                  ? 'bg-danger-50 text-danger-700'
                  : isFinal
                    ? 'bg-ok-50 text-ok-700'
                    : 'bg-warn-50 text-warn-700'
              "
            >
              {{ isVoided ? 'ยกเลิกแล้ว' : isFinal ? 'ปิดงบแล้ว' : 'ฉบับร่าง' }}
            </span>
          </div>

          <dl class="mt-4 grid gap-2 sm:grid-cols-4">
            <div class="rounded-control bg-canvas px-3 py-2.5">
              <dt class="text-caption text-ink-3">รายรับ</dt>
              <dd class="num mt-0.5 text-lg font-bold text-ok-700">
                {{ formatMoney(report.total_income) }}
              </dd>
            </div>
            <div class="rounded-control bg-canvas px-3 py-2.5">
              <dt class="text-caption text-ink-3">รายจ่าย</dt>
              <dd class="num mt-0.5 text-lg font-bold text-danger-600">
                {{ formatMoney(report.total_expense) }}
              </dd>
            </div>
            <div class="rounded-control bg-canvas px-3 py-2.5">
              <dt class="text-caption text-ink-3">เงินสดยกมา</dt>
              <dd class="num mt-0.5 text-lg font-bold text-ink-1">
                {{ formatMoney(report.opening_cash) }}
              </dd>
            </div>
            <div class="rounded-control bg-canvas px-3 py-2.5">
              <dt class="text-caption text-ink-3">เงินสดปิด (ควรเป็น)</dt>
              <dd class="num mt-0.5 text-lg font-bold text-ink-1">
                {{ formatMoney(report.closing_cash) }}
              </dd>
            </div>
          </dl>

          <div v-if="incomeLines.length || expenseLines.length" class="mt-4 grid gap-4 sm:grid-cols-2">
            <div v-if="incomeLines.length">
              <h3 class="text-sm font-bold text-ink-2">รายรับตามหมวด</h3>
              <ul class="mt-1.5 space-y-1">
                <li
                  v-for="line in incomeLines"
                  :key="`in-${line.account_code}`"
                  class="flex items-baseline justify-between gap-3 text-sm"
                >
                  <span class="min-w-0 truncate text-ink-2">{{ line.account_name }}</span>
                  <span class="num shrink-0 font-bold text-ink">{{ formatMoney(line.amount) }}</span>
                </li>
              </ul>
            </div>
            <div v-if="expenseLines.length">
              <h3 class="text-sm font-bold text-ink-2">รายจ่ายตามหมวด</h3>
              <ul class="mt-1.5 space-y-1">
                <li
                  v-for="line in expenseLines"
                  :key="`ex-${line.account_code}`"
                  class="flex items-baseline justify-between gap-3 text-sm"
                >
                  <span class="min-w-0 truncate text-ink-2">{{ line.account_name }}</span>
                  <span class="num shrink-0 font-bold text-ink">{{ formatMoney(line.amount) }}</span>
                </li>
              </ul>
            </div>
          </div>

          <p v-if="report.snapshot.note" class="mt-3 text-sm text-ink-2">
            หมายเหตุ: {{ report.snapshot.note }}
          </p>
        </div>

        <!-- ═══ การ์ด 2: นับเงินสดจริง ═══ -->
        <div class="page-card p-4 sm:p-5">
          <h2 class="section-title">นับเงินสดจริง</h2>
          <p class="mt-1 mb-3 text-sm text-ink-3">
            ตรวจนับเงินสดในกล่อง/กระเป๋า แล้วกรอกยอดจริง — ต้องตรงกับยอดจากบัญชีจึงจะปิดงบได้
          </p>
          <CashCountPanel
            v-model="counted"
            :expected="expectedCash"
            :disabled="!isEditable"
          />
        </div>

        <!-- ═══ การ์ด 3: ยืนยันปิดงบ ═══ -->
        <div class="page-card p-4 sm:p-5">
          <h2 class="section-title">ยืนยันปิดงบ</h2>

          <template v-if="isFinal">
            <p class="mt-2 flex items-center gap-2 text-sm text-ok-700">
              <i class="bi bi-check2-circle" aria-hidden="true"></i>
              ปิดงบเมื่อ {{ formatThaiDateTime(report.finalized_at) }}
            </p>
            <p v-if="report.snapshot.finalize_note" class="mt-2 text-sm text-ink-2">
              หมายเหตุการปิดงบ: {{ report.snapshot.finalize_note }}
            </p>
          </template>

          <template v-else-if="isVoided">
            <p class="mt-2 text-sm text-ink-2">
              ถ้าต้องปิดงบเดือนนี้ ให้ออกเวอร์ชันใหม่จากปุ่มด้านบน — ยอดใหม่จะ snapshot ณ ตอนที่สร้าง
            </p>
          </template>

          <template v-else>
            <p
              class="mt-2 text-sm leading-relaxed"
              :class="canFinalize(variance) ? 'text-ok-700' : 'text-danger-600'"
            >
              {{ varianceMessage(counted, expectedCash) }}
            </p>
            <p v-if="!canFinalize(variance)" class="mt-1 text-caption text-ink-3">
              ระบบปิดงบได้เฉพาะเมื่อยอดนับตรงกับบัญชี — ถ้านับได้ต่างจริง
              ให้ตรวจยอดหรือบันทึกรายการที่ตกหล่นก่อน
            </p>

            <div v-if="isEditable" class="mt-3">
              <label class="field-label" for="rpt-finalize-note">หมายเหตุการปิดงบ (ไม่บังคับ)</label>
              <textarea
                id="rpt-finalize-note"
                v-model="finalizeNote"
                class="field min-h-16"
                maxlength="255"
                :disabled="isFinalizing"
              ></textarea>
            </div>

            <div class="mt-4 flex justify-end">
              <AppButton
                variant="primary"
                :loading="isFinalizing"
                :disabled="!canSubmitFinalize"
                @click="finalizeReport"
              >
                ปิดงบ
              </AppButton>
            </div>
          </template>
        </div>
      </template>
    </template>
  </div>
</template>
