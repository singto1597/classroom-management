<script setup lang="ts">
/**
 * FinancialStatements — หน้างบการเงิน 3 งบในหน้าเดียว (งบทดลอง / งบกำไรขาดทุน / งบดุล)
 *
 * ทำไมหน้าเดียวไม่แยก 3 หน้า: ทั้งสามใช้งบเดียวกันในเรื่อง period picker และสถานะ
 * โหลด/ว่าง/ผิดพลาด ถ้าแยกจะต้องเขียน SkeletonRows → StateBlock error → StateBlock empty
 * ซ้ำสามรอบโดยไม่ได้อะไรกลับมา
 *
 * ⚠️ ทั้งสามงบอ่านจาก **journal อย่างเดียว** และถูก clamp ที่ CUTOFF_DATE (2026-09-01)
 *    ถ้าเลือกวันก่อนเส้น ระบบคืน "ว่าง" + `note` — note ต้องแสดงให้เด่น (ไม่ใช่ตัวพิมพ์เล็ก)
 *    ไม่งั้นผู้ใช้อ่านตัวเลขผิด (ดู docs/skills.md)
 *
 * 🔓 หน้านี้อ่านอย่างเดียว ไม่มี RBAC gate — ตรงกับ `require_member` ฝั่ง backend
 *    (การอ่านการเงินของห้องเปิดให้สมาชิกทุกคนโดยเจตนา) ห้ามเปลี่ยนเป็น canManageFinance
 */
import { computed, onMounted, ref, watch } from 'vue';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import AppTabs from '@/components/ui/AppTabs.vue';
import type { AppTabItem } from '@/components/ui/AppTabs.vue';
import PeriodPicker from '@/components/finance/PeriodPicker.vue';
import StatementTable from '@/components/finance/StatementTable.vue';
import { useDialog } from '@/composables/useDialog';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { formatThaiDate, todayIso } from '@/utils/datetime';
import {
  describePeriod,
  isRangeReversed,
  referenceDate,
  toAsOf,
  toRange,
  type AsOfCapablePeriod,
  type PeriodMode,
  type PeriodValue,
} from '@/utils/period';
import { downloadBlob } from '@/utils/download';
import { createLatestGuard } from '@/utils/latest';
import type {
  BalanceSheet,
  IncomeStatement,
  StatementColumn,
  StatementRow,
  TrialBalance,
  TrialBalanceLedgerRow,
} from '@/types/finance';

const authStore = useAuthStore();
const dialog = useDialog();
const currentRoomId = authStore.currentRoomId!;

type StatementTab = 'trial-balance' | 'income-statement' | 'balance-sheet';

const TAB_ORDER: StatementTab[] = ['trial-balance', 'income-statement', 'balance-sheet'];

// Record keyed by tab (ไม่ใช่ array + find) → การเข้าถึงด้วย StatementTab ได้ค่าที่ไม่ใช่ undefined
const TAB_CONFIG: Record<StatementTab, { label: string; modes: PeriodMode[] }> = {
  // งบทดลอง = ยอด ณ วัน → asof (หรือรายเดือน ซึ่งแปลงเป็น "วันสิ้นเดือน" ได้)
  'trial-balance': { label: 'งบทดลอง', modes: ['asof', 'month'] },
  // งบกำไรขาดทุน = ของ "ช่วง" → range/month เท่านั้น (asof แปลงเป็นช่วงไม่ได้ ห้ามเดา)
  'income-statement': { label: 'งบกำไรขาดทุน', modes: ['month', 'range'] },
  'balance-sheet': { label: 'งบดุล', modes: ['asof', 'month'] },
};

const TYPE_LABELS: Record<string, string> = {
  asset: 'สินทรัพย์',
  liability: 'หนี้สิน',
  equity: 'ส่วนของเจ้าของ',
  revenue: 'รายได้',
  expense: 'ค่าใช้จ่าย',
};

const tabs: AppTabItem[] = TAB_ORDER.map((tab) => ({
  value: tab,
  label: TAB_CONFIG[tab].label,
}));

const activeTab = ref<StatementTab>('trial-balance');
const period = ref<PeriodValue>({ mode: 'asof', asOfDate: todayIso() });

const isLoading = ref(true);
const hasError = ref(false);
// 🏁 กันคำตอบของคำขอเก่ามาทับคำตอบของคำขอใหม่ (ดู utils/latest.ts)
const guard = createLatestGuard();

const trialBalance = ref<TrialBalance | null>(null);
const incomeStatement = ref<IncomeStatement | null>(null);
const balanceSheet = ref<BalanceSheet | null>(null);

const activeTabConfig = computed(() => TAB_CONFIG[activeTab.value]);
const activeModes = computed(() => activeTabConfig.value.modes);

const asOfPeriod = (p: PeriodValue): AsOfCapablePeriod | null => (p.mode === 'range' ? null : p);
const rangePeriod = (p: PeriodValue) =>
  p.mode === 'asof' ? null : (p as Extract<PeriodValue, { mode: 'month' | 'range' }>);

/**
 * เงินทุกตัวในหน้านี้ผ่านฟังก์ชันเดียว — เติม `฿` เสมอ และดึงเครื่องหมายลบออกมาข้างหน้า
 * สกุล (`−฿1,234.00`) แทนที่จะปล่อยให้ติดกับตัวเลข (`฿-1,234.00`) ซึ่งอ่านผิดได้ง่าย
 */
const formatMoney = (value: number): string =>
  `${value < 0 ? '−' : ''}฿${Math.abs(value).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/** แถว ledger → แถวตาราง พร้อมหัวกลุ่มตามชนิดบัญชี (เรียงตามที่ backend ส่งมา) */
const ledgerRows = (ledgers: TrialBalanceLedgerRow[], withGroup: boolean): StatementRow[] => {
  const rows: StatementRow[] = [];
  let lastType = '';
  for (const lg of ledgers) {
    if (withGroup && lg.account_type !== lastType) {
      lastType = lg.account_type;
      rows.push({ group: TYPE_LABELS[lg.account_type] ?? lg.account_type });
    }
    rows.push({
      code: lg.account_code,
      name: lg.account_name,
      debit: lg.total_debit,
      credit: lg.total_credit,
      amount: lg.balance,
    });
  }
  return rows;
};

const TB_COLUMNS: StatementColumn[] = [
  { key: 'code', label: 'รหัส' },
  { key: 'name', label: 'ชื่อบัญชี' },
  { key: 'debit', label: 'เดบิต', numeric: true },
  { key: 'credit', label: 'เครดิต', numeric: true },
  { key: 'amount', label: 'ยอดคงเหลือ', numeric: true },
];

const AMOUNT_COLUMNS: StatementColumn[] = [
  { key: 'name', label: 'รายการ' },
  { key: 'amount', label: 'จำนวนเงิน (บาท)', numeric: true },
];

const activeColumns = computed(() =>
  activeTab.value === 'trial-balance' ? TB_COLUMNS : AMOUNT_COLUMNS,
);

const activeRows = computed<StatementRow[]>(() => {
  if (activeTab.value === 'trial-balance') {
    const data = trialBalance.value;
    if (!data) return [];
    const rows = ledgerRows(data.ledgers, true);
    rows.push({
      name: 'รวมทั้งสิ้น',
      debit: data.total_debit,
      credit: data.total_credit,
      amount: data.total_debit - data.total_credit,
      isTotal: true,
    });
    return rows;
  }

  if (activeTab.value === 'income-statement') {
    const data = incomeStatement.value;
    if (!data) return [];
    const rows: StatementRow[] = [];
    if (data.revenues.length) {
      rows.push({ group: 'รายได้' });
      rows.push(...data.revenues.map((r) => ({ name: r.account_name, amount: r.amount })));
      rows.push({ name: 'รวมรายได้', amount: data.total_revenue, isTotal: true });
    }
    if (data.expenses.length) {
      rows.push({ group: 'ค่าใช้จ่าย' });
      rows.push(...data.expenses.map((r) => ({ name: r.account_name, amount: r.amount })));
      rows.push({ name: 'รวมค่าใช้จ่าย', amount: data.total_expense, isTotal: true });
    }
    rows.push({ name: 'กำไร (ขาดทุน) สุทธิ', amount: data.net_income, isTotal: true });
    return rows;
  }

  const data = balanceSheet.value;
  if (!data) return [];
  const rows: StatementRow[] = [];
  if (data.assets.length) {
    rows.push({ group: 'สินทรัพย์' });
    rows.push(...ledgerRows(data.assets, false));
    rows.push({ name: 'รวมสินทรัพย์', amount: data.assets_total, isTotal: true });
  }
  if (data.liabilities.length) {
    rows.push({ group: 'หนี้สิน' });
    rows.push(...ledgerRows(data.liabilities, false));
    rows.push({ name: 'รวมหนี้สิน', amount: data.liability_total, isTotal: true });
  }
  rows.push({ group: 'ส่วนของเจ้าของ' });
  rows.push(...ledgerRows(data.equities, false));
  rows.push({ name: 'กำไร (ขาดทุน) สะสม', amount: data.retained_earnings });
  rows.push({ name: 'รวมส่วนของเจ้าของ', amount: data.total_equity_side, isTotal: true });
  rows.push({
    name: 'รวมหนี้สินและส่วนของเจ้าของ',
    amount: data.total_liabilities_and_equity,
    isTotal: true,
  });
  return rows;
});

/** note ที่ backend ส่งมาเฉพาะเส้นทางที่ถูก clamp — ต้องเด่น */
const activeNote = computed(() => {
  if (activeTab.value === 'trial-balance') return trialBalance.value?.note ?? null;
  if (activeTab.value === 'income-statement') return incomeStatement.value?.note ?? null;
  return balanceSheet.value?.note ?? null;
});

const isEmpty = computed(() => {
  if (activeTab.value === 'trial-balance') return (trialBalance.value?.ledgers.length ?? 0) === 0;
  if (activeTab.value === 'income-statement') {
    const data = incomeStatement.value;
    return !data || (data.revenues.length === 0 && data.expenses.length === 0);
  }
  const data = balanceSheet.value;
  if (!data) return true;
  return (
    data.assets.length === 0 &&
    data.liabilities.length === 0 &&
    data.equities.length === 0 &&
    data.retained_earnings === 0
  );
});

const periodCaption = computed(() => {
  const data = balanceSheet.value;
  if (activeTab.value === 'balance-sheet' && data) {
    return `กำไรของงวด ${formatThaiDate(data.period_start)} – ${formatThaiDate(data.period_end)}`;
  }
  return describePeriod(period.value);
});

const load = async () => {
  // ช่วงวันที่กลับด้าน — PeriodPicker แสดง error  inline อยู่แล้ว ไม่ต้องยิง API (backend จะ 400)
  if (isRangeReversed(period.value)) return;

  // 🏁 หน้านี้มีสองแกนที่ทำให้เกิดคำขอซ้อน: สลับแท็บ (activeTab) และเลื่อนช่วงเวลา
  //    `selectTab` เปลี่ยนทั้งคู่พร้อมกันจึงยิงครั้งเดียว แต่ผู้ใช้ยังกดแท็บรัวได้
  //    ⇒ คำตอบของ "งบกำไรขาดทุนของเดือนที่แล้ว" อาจมาถึงหลังคำตอบของ "งบดุลของเดือนนี้"
  //    แล้วถูกเขียนลง `incomeStatement` ทั้งที่จอกำลังโชว์แท็บงบดุล — พอกลับไปแท็บเดิม
  //    จะเห็นตัวเลขของเดือนที่ไม่ได้เลือกแล้วโดยไม่มีสปินเนอร์ (isLoading ถูกปิดไปก่อนหน้า)
  const token = guard.begin();

  isLoading.value = true;
  hasError.value = false;
  try {
    if (activeTab.value === 'trial-balance') {
      const p = asOfPeriod(period.value);
      if (!p) return;
      const res = await FinanceService.getTrialBalance(currentRoomId, toAsOf(p));
      if (!guard.isCurrent(token)) return;
      trialBalance.value = res;
    } else if (activeTab.value === 'income-statement') {
      const p = rangePeriod(period.value);
      if (!p) return;
      const range = toRange(p);
      const res = await FinanceService.getIncomeStatement(
        currentRoomId,
        range.startDate,
        range.endDate,
      );
      if (!guard.isCurrent(token)) return;
      incomeStatement.value = res;
    } else {
      const p = asOfPeriod(period.value);
      if (!p) return;
      const res = await FinanceService.getBalanceSheet(currentRoomId, toAsOf(p));
      if (!guard.isCurrent(token)) return;
      balanceSheet.value = res;
    }
  } catch (error) {
    // error ของคำขอเก่าไม่ควรขึ้นจอ ถ้าคำขอใหม่กว่าไปถึงแล้ว
    if (!guard.isCurrent(token)) return;
    console.error('Failed to load financial statements:', error);
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

/** สลับแท็บ — โหมดที่ไม่รองรับจะถูกแปลงเป็น 'month' โดยคงเดือน/ปีที่กำลังดูอยู่ */
const selectTab = (tab: StatementTab) => {
  activeTab.value = tab;
  if (!TAB_CONFIG[tab].modes.includes(period.value.mode)) {
    period.value = { mode: 'month', ...referenceDate(period.value) };
  }
};

const setTab = (value: string) => {
  if (!TAB_ORDER.includes(value as StatementTab)) return;
  selectTab(value as StatementTab);
};

// activeTab และ period ถูก watch รวมกัน → แก้ทั้งคู่ในจังหวะเดียว (selectTab) ยังได้ load ครั้งเดียว
watch([activeTab, period], () => {
  void load();
});

onMounted(() => {
  void load();
});

// 📥 ส่งออกเป็น Excel — reuse สมุดรายวันเดิม (workbook 6 แผ่นมี GL/TB/IS/BS อยู่แล้ว)
const isExporting = ref(false);

const exportExcel = async () => {
  if (isExporting.value) return;
  isExporting.value = true;

  // export รับได้แค่ month/year หรือ start/end — "ณ วันที่" จึงแปลงเป็นเดือนของวันนั้น
  const p = period.value;
  const range = p.mode === 'range' ? { startDate: p.startDate, endDate: p.endDate } : null;
  const monthYear = range ? null : referenceDate(period.value);

  const filename = range
    ? `งบการเงิน_${range.startDate}_${range.endDate}.xlsx`
    : `งบการเงิน_${String(monthYear!.month).padStart(2, '0')}-${monthYear!.year + 543}.xlsx`;

  void dialog.loading('กำลังสร้างไฟล์ Excel...', 'ระบบกำลังรวบรวมงบการเงินให้คุณ');

  try {
    const blob = await FinanceService.exportJournalExcel(
      currentRoomId,
      monthYear?.month,
      monthYear?.year,
      range?.startDate,
      range?.endDate,
    );
    downloadBlob(blob, filename);
    dialog.close();
    await dialog.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: 'ดาวน์โหลดไฟล์ Excel เรียบร้อยแล้ว',
      timer: 1500,
    });
  } catch (error) {
    console.error('Export failed:', error);
    dialog.close();
    // ใช้ข้อความจริงจาก backend — `services/api.ts` คลี่ Blob error body ให้แล้ว
    // (คำขอนี้เป็น `responseType: 'blob'`) ข้อความกลาง ๆ จะกลบสาเหตุจริง เช่น 403 ติดสิทธิ์
    void dialog.alert(
      'ส่งออกไม่สำเร็จ',
      error instanceof Error && error.message
        ? error.message
        : 'ไม่สามารถสร้างไฟล์ Excel ได้ กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isExporting.value = false;
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="งบทดลอง งบกำไรขาดทุน และงบดุล ของห้องนี้"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" :disabled="isExporting" @click="exportExcel">
          <i class="bi bi-file-earmark-excel" aria-hidden="true"></i>
          ส่งออก Excel
        </button>
      </template>
    </PageIntro>

    <!-- แท็บงบ: เส้นใต้บาง (คนละแบบกับสวิตช์โหมดใน PeriodPicker ซึ่งเป็น pill ทึบ) -->
    <AppTabs
      :model-value="activeTab"
      :tabs="tabs"
      group-label="เลือกงบการเงิน"
      @update:model-value="setTab"
    />

    <PeriodPicker v-model="period" :modes="activeModes" />

    <!-- ⚠️ note = ตัวเลขครอบช่วงแคบกว่าที่ผู้ใช้เลือก → ต้องเด่นพอที่จะไม่ถูกอ่านข้าม -->
    <div
      v-if="activeNote"
      class="flex items-start gap-2.5 rounded-card border border-warn-200 bg-warn-50 p-3.5 sm:p-4"
      role="status"
    >
      <i class="bi bi-exclamation-triangle-fill mt-0.5 shrink-0 text-warn-600" aria-hidden="true"></i>
      <div class="min-w-0">
        <p class="text-sm font-bold text-warn-800">ช่วงเวลาถูกปรับโดยระบบ</p>
        <p class="mt-0.5 text-sm leading-relaxed text-warn-700">{{ activeNote }}</p>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="6" height="h-14" />

    <StateBlock v-else-if="hasError" variant="error" @retry="load" />

    <StateBlock
      v-else-if="isEmpty"
      variant="empty"
      icon="bi-clipboard-x"
      title="ยังไม่มีข้อมูลในช่วงเวลานี้"
      :hint="
        activeTab === 'income-statement'
          ? 'ลองขยายช่วงวันที่ให้กว้างขึ้น — งบนี้เริ่มนับตั้งแต่ 1 ก.ย. 2026 เป็นต้นมา'
          : 'ลองเลื่อนวันที่ให้อยู่หลัง 1 ก.ย. 2026 ซึ่งเป็นวันที่ระบบเริ่มเก็บบัญชีคู่'
      "
    />

    <template v-else>
      <!-- KPI ของงบที่กำลังดูอยู่ -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <template v-if="activeTab === 'trial-balance' && trialBalance">
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">รวมเดบิต</p>
            <p class="num mt-2 break-words text-lg font-bold text-ink sm:text-2xl">
              {{ formatMoney(trialBalance.total_debit) }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">รวมเครดิต</p>
            <p class="num mt-2 break-words text-lg font-bold text-ink sm:text-2xl">
              {{ formatMoney(trialBalance.total_credit) }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">จำนวนบัญชี</p>
            <p class="num mt-2 text-lg font-bold text-ink sm:text-2xl">
              {{ trialBalance.ledgers.length }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">สถานะ</p>
            <p class="mt-2">
              <span
                class="chip"
                :class="
                  trialBalance.is_balanced
                    ? 'bg-ok-50 text-ok-700'
                    : 'bg-danger-50 text-danger-700'
                "
              >
                <i
                  class="bi"
                  :class="trialBalance.is_balanced ? 'bi-check-circle-fill' : 'bi-x-circle-fill'"
                  aria-hidden="true"
                />
                {{ trialBalance.is_balanced ? 'สมดุล' : 'ไม่สมดุล' }}
              </span>
            </p>
          </div>
        </template>

        <template v-else-if="activeTab === 'income-statement' && incomeStatement">
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">รายได้รวม</p>
            <p class="num mt-2 break-words text-lg font-bold text-ok-600 sm:text-2xl">
              {{ formatMoney(incomeStatement.total_revenue) }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">ค่าใช้จ่ายรวม</p>
            <p class="num mt-2 break-words text-lg font-bold text-danger-600 sm:text-2xl">
              {{ formatMoney(incomeStatement.total_expense) }}
            </p>
          </div>
          <div class="page-card p-3.5 border-s-4 border-s-brand-700 sm:p-5 lg:col-span-2">
            <p class="text-caption font-bold text-ink-3">
              กำไร (ขาดทุน) สุทธิ
            </p>
            <p
              class="num mt-2 break-words text-lg font-bold sm:text-2xl"
              :class="incomeStatement.net_income < 0 ? 'text-danger-600' : 'text-ink'"
            >
              {{ formatMoney(incomeStatement.net_income) }}
            </p>
            <p class="mt-1 text-xs font-bold text-ink-3">{{ periodCaption }}</p>
          </div>
        </template>

        <template v-else-if="balanceSheet">
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">สินทรัพย์รวม</p>
            <p class="num mt-2 break-words text-lg font-bold text-ink sm:text-2xl">
              {{ formatMoney(balanceSheet.assets_total) }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">หนี้สินรวม</p>
            <p class="num mt-2 break-words text-lg font-bold text-ink sm:text-2xl">
              {{ formatMoney(balanceSheet.liability_total) }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">
              ส่วนของเจ้าของ
            </p>
            <p class="num mt-2 break-words text-lg font-bold text-ink sm:text-2xl">
              {{ formatMoney(balanceSheet.total_equity_side) }}
            </p>
          </div>
          <div class="page-card p-3.5 sm:p-5">
            <p class="text-caption font-bold text-ink-3">สถานะ</p>
            <p class="mt-2">
              <span
                class="chip"
                :class="
                  balanceSheet.is_balanced ? 'bg-ok-50 text-ok-700' : 'bg-danger-50 text-danger-700'
                "
              >
                <i
                  class="bi"
                  :class="balanceSheet.is_balanced ? 'bi-check-circle-fill' : 'bi-x-circle-fill'"
                  aria-hidden="true"
                />
                {{ balanceSheet.is_balanced ? 'สมดุล' : 'ไม่สมดุล' }}
              </span>
            </p>
            <p class="num mt-1.5 text-xs font-bold text-ink-3">
              กำไรของงวด {{ formatMoney(balanceSheet.period_net_income) }}
            </p>
          </div>
        </template>
      </div>

      <div class="page-card overflow-hidden">
        <div class="flex flex-col gap-1.5 border-b border-line p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <h2 class="section-title min-w-0 truncate">
            {{ activeTabConfig.label }}
          </h2>
          <p class="min-w-0 truncate text-xs font-bold text-ink-3">{{ periodCaption }}</p>
        </div>

        <StatementTable :rows="activeRows" :columns="activeColumns" />
      </div>
    </template>
  </div>
</template>
