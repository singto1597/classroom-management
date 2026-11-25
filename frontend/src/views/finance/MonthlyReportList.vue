<script setup lang="ts">
/**
 * 📊 [FIN-V2 / P5.5] MonthlyReportList — รายงานปิดงบเดือน (RPT) — `/finance/monthly-reports`
 *
 * 🔓 อ่านเปิดให้สมาชิก (backend `require_member`) · ปุ่มสร้างเฉพาะ `canManageFinance`
 *
 * 📌 1 เดือนออกได้หลาย "เวอร์ชัน" (`version`) — เลขเอกสารจึงมี `-v2`, `-v3` …
 *    ⇒ ห้ามจัดกลุ่มหรือ dedupe ตาม `year_be`/`month` บนจอ เพราะเวอร์ชันเก่ายังเป็น
 *    หลักฐานแยกใบ · การออกเวอร์ชันใหม่เกิดจาก "ยกเลิกแล้วออกใหม่" เท่านั้น
 *
 * ⚠️ ตัวกรอง `year` เป็น **ปี พ.ศ.** ตามที่ backend เก็บ (`year_be`) — ไม่แปลงเป็น ค.ศ.
 *    ฝั่งจอเพราะผู้ใช้เห็น "พ.ศ." ตลอดทั้งระบบ
 *
 * ⚠️ `counted_cash`/`variance` เป็น `null` จนกว่าจะปิดงบ — ห้ามใช้ truthiness
 *    (`0` คือยอดที่นับได้ถูกต้อง ไม่ใช่ "ไม่มีค่า")
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { createLatestGuard } from '@/utils/latest';
import { formatMoney } from '@/utils/money';
import { THAI_MONTHS } from '@/utils/datetime';
import { todayThaiYearMonth } from '@/utils/period';
import type { MonthlyReportResponse, MonthlyReportStatus } from '@/types/finance';

const authStore = useAuthStore();
const router = useRouter();
const currentRoomId = authStore.currentRoomId!;

const canManageFinance = computed(() => authStore.canManageFinance);

type StatusFilter = 'all' | MonthlyReportStatus;

const currentYearBe = todayThaiYearMonth().year + 543;

/** ปีที่เลือกให้ตรงกับปีที่มีข้อมูลจริงได้ง่ายที่สุด — 4 ปีย้อนหลัง + ปีนี้ */
const YEAR_OPTIONS = Array.from({ length: 5 }, (_, i) => currentYearBe - i);

const yearFilter = ref<number>(currentYearBe);
const statusFilter = ref<StatusFilter>('all');

const items = ref<MonthlyReportResponse[]>([]);
const isLoading = ref(true);
const hasError = ref(false);

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'ทั้งหมด' },
  { value: 'draft', label: 'ฉบับร่าง' },
  { value: 'final', label: 'ปิดงบแล้ว' },
  { value: 'voided', label: 'ยกเลิกแล้ว' },
];

const STATUS_LABELS: Record<MonthlyReportStatus, string> = {
  draft: 'ฉบับร่าง',
  final: 'ปิดงบแล้ว',
  voided: 'ยกเลิกแล้ว',
};

const STATUS_CLASSES: Record<MonthlyReportStatus, string> = {
  draft: 'bg-warn-50 text-warn-700',
  final: 'bg-ok-50 text-ok-700',
  voided: 'bg-danger-50 text-danger-700',
};

// 🏁 เปลี่ยนปี/สถานะเร็ว ๆ ได้ ⇒ คำตอบเก่าห้ามทับคำตอบใหม่
const guard = createLatestGuard();

const periodLabel = (report: MonthlyReportResponse): string =>
  `${THAI_MONTHS[report.month - 1] ?? report.month} ${report.year_be}`;

const load = async () => {
  const token = guard.begin();
  isLoading.value = true;
  hasError.value = false;
  try {
    const res = await FinanceService.getMonthlyReports(currentRoomId, {
      year: yearFilter.value,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    });
    if (!guard.isCurrent(token)) return;
    items.value = res.items;
  } catch {
    if (!guard.isCurrent(token)) return;
    items.value = [];
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

watch([yearFilter, statusFilter], () => {
  void load();
});

onMounted(() => {
  void load();
});

const openReport = (report: MonthlyReportResponse) => {
  void router.push({ name: 'finance-monthly-report', params: { id: report.id } });
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="ปิดงบรายเดือน: ระบบสรุปยอดจากบัญชี แล้วให้ตรวจนับเงินสดจริงก่อนปิดงบ"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" :disabled="isLoading" @click="load">
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
          รีเฟรช
        </button>
        <RouterLink
          v-if="canManageFinance"
          to="/finance/monthly-reports/new"
          class="btn-primary"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          สร้างรายงานปิดงบ
        </RouterLink>
      </template>
    </PageIntro>

    <div class="flex flex-wrap items-end gap-3">
      <div>
        <label class="field-label" for="rpt-year">ปี (พ.ศ.)</label>
        <select id="rpt-year" v-model.number="yearFilter" class="field w-36">
          <option v-for="year in YEAR_OPTIONS" :key="year" :value="year">{{ year }}</option>
        </select>
      </div>
      <div>
        <label class="field-label" for="rpt-status">สถานะ</label>
        <select id="rpt-status" v-model="statusFilter" class="field w-40">
          <option v-for="option in STATUS_FILTERS" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-14" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดรายงานปิดงบไม่สำเร็จ"
      @retry="load"
    />
    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      title="ยังไม่มีรายงานปิดงบในปีนี้"
      hint="สร้างรายงานเพื่อสรุปยอดรายรับ-รายจ่าย และตรวจนับเงินสดก่อนปิดงบของเดือน"
      icon="bi-file-earmark-bar-graph"
    >
      <RouterLink
        v-if="canManageFinance"
        to="/finance/monthly-reports/new"
        class="btn-primary mt-2"
      >
        สร้างรายงานปิดงบ
      </RouterLink>
    </StateBlock>

    <template v-else>
      <p class="px-1 text-sm text-ink-3">
        พบ <span class="num font-bold text-ink-2">{{ items.length }}</span> ฉบับ
      </p>

      <div class="page-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>เลขที่</th>
                <th>งวด</th>
                <th>สถานะ</th>
                <th class="text-right">รายรับ</th>
                <th class="text-right">รายจ่าย</th>
                <th class="text-right">เงินสดปิด</th>
                <th class="text-right">นับได้</th>
                <th class="text-right">ผลต่าง</th>
                <th class="text-right">เปิด</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="report in items"
                :key="report.id"
                class="cursor-pointer"
                @click="openReport(report)"
              >
                <td class="whitespace-nowrap">
                  <span class="num font-bold text-ink-1">{{ report.report_no }}</span>
                </td>
                <td class="whitespace-nowrap text-ink-2">{{ periodLabel(report) }}</td>
                <td>
                  <span class="chip" :class="STATUS_CLASSES[report.status]">
                    {{ STATUS_LABELS[report.status] }}
                  </span>
                </td>
                <td class="num whitespace-nowrap text-right text-ink">
                  {{ formatMoney(report.total_income) }}
                </td>
                <td class="num whitespace-nowrap text-right text-ink">
                  {{ formatMoney(report.total_expense) }}
                </td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(report.closing_cash) }}
                </td>
                <td class="num whitespace-nowrap text-right text-ink-2">
                  {{ report.counted_cash === null ? '—' : formatMoney(report.counted_cash) }}
                </td>
                <td
                  class="num whitespace-nowrap text-right font-bold"
                  :class="
                    report.variance === null
                      ? 'text-ink-3'
                      : Math.abs(report.variance) < 0.005
                        ? 'text-ok-700'
                        : 'text-danger-600'
                  "
                >
                  {{ report.variance === null ? '—' : formatMoney(report.variance) }}
                </td>
                <td class="text-right">
                  <button
                    type="button"
                    class="btn-ghost-ui min-h-9 text-sm"
                    :aria-label="`เปิดรายงาน ${report.report_no}`"
                    @click.stop="openReport(report)"
                  >
                    เปิด
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
