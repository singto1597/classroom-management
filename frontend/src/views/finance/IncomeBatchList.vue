<script setup lang="ts">
/**
 * IncomeBatchList — รายการใบรับเงิน (FIN-V2 / P4.5) — `/finance/income-batches`
 *
 * 🔓 อ่านเปิดให้สมาชิก (backend `require_member`) · ปุ่มสร้างเฉพาะ `canManageFinance`
 *    (ตรงกับ `MANAGE_FINANCE` ที่ backend บังคับซ้ำ)
 *
 * ⚠️ "ใบรับเงิน" (INC) ≠ "ใบเสร็จรับเงิน" (REC) — INC คือรายรับอื่นที่ไม่ใช่บิลนักเรียน
 *    (เงินบริจาค/สนับสนุน/ขายของ) และไม่มีผู้จ่ายเป็น person ในฐานข้อมูล
 *
 * ⚠️ `total` ใน response คือ **ผลบวกยอดเงินของทุกใบ** ไม่ใช่จำนวนใบ
 * ⚠️ ช่วงวันที่กรองตาม `income_date` ซึ่งเป็น date-only ⇒ แสดงด้วย `formatThaiDate`
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PeriodPicker from '@/components/finance/PeriodPicker.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { createLatestGuard } from '@/utils/latest';
import { formatMoney } from '@/utils/money';
import { formatThaiDate } from '@/utils/datetime';
import {
  isRangeReversed,
  toRange,
  todayThaiYearMonth,
  type PeriodValue,
} from '@/utils/period';
import type { IncomeBatchListItem } from '@/types/finance';

const authStore = useAuthStore();
const router = useRouter();
const currentRoomId = authStore.currentRoomId!;

const canManageFinance = computed(() => authStore.canManageFinance);

const initial = todayThaiYearMonth();
const period = ref<PeriodValue>({ mode: 'month', month: initial.month, year: initial.year });
const statusFilter = ref<'all' | 'active' | 'voided'>('active');

const items = ref<IncomeBatchListItem[]>([]);
/** ผลบวกยอดเงิน (ไม่ใช่จำนวนใบ) — ใช้ตรงจาก backend */
const totalAmount = ref(0);
const isLoading = ref(true);
const hasError = ref(false);

// 🏁 ตัวกรองเปลี่ยนเร็ว ๆ ได้ ⇒ คำตอบเก่าห้ามทับคำตอบใหม่ (ดู utils/latest.ts)
const guard = createLatestGuard();

const STATUS_FILTERS: { value: 'all' | 'active' | 'voided'; label: string }[] = [
  { value: 'active', label: 'ใช้งาน' },
  { value: 'voided', label: 'ยกเลิกแล้ว' },
  { value: 'all', label: 'ทั้งหมด' },
];

const STATUS_LABELS: Record<string, string> = {
  active: 'ใช้งาน',
  voided: 'ยกเลิกแล้ว',
};

/** ใบรับเงินกรองด้วยช่วงวันที่เท่านั้น — โหมด `asof` ไม่มีความหมาย จึงคืน null */
const rangeOf = (p: PeriodValue): { startDate: string; endDate: string } | null =>
  p.mode === 'asof' ? null : toRange(p);

const load = async () => {
  if (isRangeReversed(period.value)) return;
  const range = rangeOf(period.value);
  if (!range) return;

  const token = guard.begin();
  isLoading.value = true;
  hasError.value = false;
  try {
    const res = await FinanceService.getIncomeBatches(currentRoomId, {
      from: range.startDate,
      to: range.endDate,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    });
    if (!guard.isCurrent(token)) return;
    items.value = res.items;
    totalAmount.value = res.total;
  } catch {
    if (!guard.isCurrent(token)) return;
    items.value = [];
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

watch([period, statusFilter], () => {
  void load();
});

onMounted(() => {
  void load();
});

const openDetail = (id: number) => {
  void router.push({ name: 'finance-income-batch-detail', params: { id } });
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro description="รายรับอื่นที่ไม่ใช่บิลนักเรียน — หลายหมวดในใบเดียว และ INC ออกทุกใบ">
      <template #actions>
        <button type="button" class="btn-ghost-ui" :disabled="isLoading" @click="load">
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
          รีเฟรช
        </button>
        <RouterLink
          v-if="canManageFinance"
          to="/finance/income-batches/new"
          class="btn-primary"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          สร้างใบรับเงิน
        </RouterLink>
      </template>
    </PageIntro>

    <!-- ตัวกรอง -->
    <div class="page-card p-3 sm:p-4">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <PeriodPicker v-model="period" :modes="['month', 'range']" label="ช่วงที่รับเงิน" />
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="option in STATUS_FILTERS"
            :key="option.value"
            type="button"
            class="chip"
            :class="
              statusFilter === option.value
                ? 'bg-brand-600 text-white'
                : 'bg-canvas text-ink-2'
            "
            @click="statusFilter = option.value"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-14" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดรายการใบรับเงินไม่สำเร็จ"
      @retry="load"
    />
    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      title="ยังไม่มีใบรับเงินในช่วงนี้"
      hint="รายรับอื่นที่ไม่ใช่บิลนักเรียน (เงินบริจาค/สนับสนุน/ขายของ) บันทึกได้ที่นี่"
      icon="bi-cash-stack"
    >
      <RouterLink
        v-if="canManageFinance"
        to="/finance/income-batches/new"
        class="btn-primary mt-2"
      >
        สร้างใบรับเงิน
      </RouterLink>
    </StateBlock>

    <template v-else>
      <p class="px-1 text-sm text-ink-3">
        พบ
        <span class="num font-bold text-ink-2">{{ items.length }}</span>
        ใบ · ยอดรวมทุกใบ
        <span class="num font-bold text-ink-2">{{ formatMoney(totalAmount) }}</span>
      </p>

      <div class="page-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>วันที่</th>
                <th>เลข INC</th>
                <th>ผู้จ่าย</th>
                <th>ผู้รับเงิน</th>
                <th class="text-right">บรรทัด</th>
                <th class="text-right">ยอดรวม</th>
                <th>สถานะ</th>
                <th class="w-8"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.id"
                class="cursor-pointer"
                @click="openDetail(item.id)"
              >
                <td class="whitespace-nowrap">{{ formatThaiDate(item.income_date) }}</td>
                <td class="whitespace-nowrap">
                  <span class="num font-bold text-ink-1">
                    {{ item.inc_receipt_no || `#${item.id}` }}
                  </span>
                </td>
                <td class="min-w-[10rem]">{{ item.payer_name }}</td>
                <td class="min-w-[8rem] text-ink-3">{{ item.receiver_name }}</td>
                <td class="num text-right text-ink-3">{{ item.line_count }}</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(item.total_amount) }}
                </td>
                <td>
                  <span
                    class="chip"
                    :class="
                      item.status === 'voided'
                        ? 'bg-danger-50 text-danger-700'
                        : 'bg-ok-50 text-ok-700'
                    "
                  >
                    {{ STATUS_LABELS[item.status] ?? item.status }}
                  </span>
                </td>
                <td class="text-ink-3">
                  <i class="bi bi-chevron-right" aria-hidden="true"></i>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
