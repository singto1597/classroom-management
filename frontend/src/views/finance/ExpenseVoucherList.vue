<script setup lang="ts">
/**
 * ExpenseVoucherList — รายการใบสำคัญจ่าย (FIN-V2 / P4.3) — `/finance/expense-vouchers`
 *
 * 🔓 อ่านเปิดให้สมาชิกทุกคน (backend `require_member`) · ปุ่มสร้างเฉพาะ
 *    `canManageFinance` (ตรงกับ `MANAGE_FINANCE` ที่ backend บังคับซ้ำ)
 *
 * 🔴 **การ์ด/แถวนี้แสดง badge CERT ไม่ได้** — `GET /finance/expense-vouchers` (P4.1)
 *    JOIN แค่ PV และไม่คืน `cert_receipt_no`/`cert_amount` เลย ⇒ หน้ารายละเอียดเป็น
 *    ที่เดียวที่อ่านเลข/ยอด CERT ได้ (ห้ามเดาว่าแถวมีฟิลด์นี้)
 *
 * ⚠️ `total` ใน response คือ **ผลบวกยอดเงินของทุกใบ** ไม่ใช่จำนวนใบ ⇒ ป้ายต้องเขียน
 *    "ยอดรวมทุกใบ" ไม่งั้นผู้ใช้อ่านเป็น "มี N ใบ"
 *
 * ⚠️ ช่วงวันที่กรองตาม **วันตามปฏิทินไทย** (`voucher_date` เป็น date-only อยู่แล้ว)
 *    ⇒ แสดงผลด้วย `formatThaiDate` (ไม่ใช่ `formatThaiDateTime`)
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
import type { ExpenseVoucherListItem } from '@/types/finance';

const authStore = useAuthStore();
const router = useRouter();
const currentRoomId = authStore.currentRoomId!;

const canManageFinance = computed(() => authStore.canManageFinance);

const initial = todayThaiYearMonth();
const period = ref<PeriodValue>({ mode: 'month', month: initial.month, year: initial.year });
const statusFilter = ref<'all' | 'active' | 'voided'>('active');

const items = ref<ExpenseVoucherListItem[]>([]);
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

/** ใบสำคัญจ่ายกรองด้วยช่วงวันที่เท่านั้น — โหมด `asof` ไม่มีความหมาย จึงคืน null */
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
    const res = await FinanceService.getExpenseVouchers(currentRoomId, {
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
  void router.push({ name: 'finance-expense-voucher-detail', params: { id } });
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="รายจ่ายหลายบรรทัดในใบเดียว — ออก PV ทุกใบ และ CERT เมื่อมีรายการที่ไม่มีใบเสร็จ"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" :disabled="isLoading" @click="load">
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
          รีเฟรช
        </button>
        <RouterLink
          v-if="canManageFinance"
          to="/finance/expense-vouchers/new"
          class="btn-primary"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          สร้างใบสำคัญจ่าย
        </RouterLink>
      </template>
    </PageIntro>

    <PeriodPicker v-model="period" :modes="['month', 'range']" label="ช่วงวันที่ใบสำคัญจ่าย" />

    <!-- 🧾 ตัวกรองสถานะ — ส่งค่า `active`/`voided` ให้ backend กรอง (ไม่กรองฝั่งจอ) -->
    <div class="flex flex-wrap items-center gap-2" role="group" aria-label="สถานะใบสำคัญจ่าย">
      <button
        v-for="opt in STATUS_FILTERS"
        :key="opt.value"
        type="button"
        class="chip transition-colors"
        :class="statusFilter === opt.value ? 'bg-brand-700 text-white' : 'bg-canvas text-ink-2'"
        :aria-pressed="statusFilter === opt.value"
        @click="statusFilter = opt.value"
      >
        {{ opt.label }}
      </button>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-16" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดรายการใบสำคัญจ่ายไม่สำเร็จ"
      @retry="load"
    />
    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      title="ยังไม่มีใบสำคัญจ่ายในช่วงนี้"
      hint="สร้างใบแรกเมื่อมีการเบิกจ่าย และเลือกสถานะใบเสร็จของแต่ละบรรทัดให้ครบ"
      icon="bi-cash-coin"
    >
      <RouterLink
        v-if="canManageFinance"
        to="/finance/expense-vouchers/new"
        class="btn-primary mt-2"
      >
        <i class="bi bi-plus-lg" aria-hidden="true"></i>
        สร้างใบสำคัญจ่าย
      </RouterLink>
    </StateBlock>

    <template v-else>
      <!-- 📊 สรุปหัวตาราง — `total` คือผลบวกยอดเงิน ไม่ใช่จำนวนใบ -->
      <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p class="text-ink-3">
          พบ {{ items.length }} ใบ
          <span class="mx-1 text-ink-3">·</span>
          ยอดรวมทุกใบ
          <span class="num font-bold text-ink-1">{{ formatMoney(totalAmount) }}</span>
        </p>
        <!-- ℹ️ badge CERT ไม่มีในรายการนี้ — backend list ไม่คืนฟิลด์ CERT (P4.1) -->
        <p class="text-xs text-ink-3">เลข/ยอด CERT ดูได้ในหน้ารายละเอียดของแต่ละใบ</p>
      </div>

      <div class="page-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>วันที่</th>
                <th>เลขที่ PV</th>
                <th>ผู้รับเงิน</th>
                <th class="text-right">ยอดรวม</th>
                <th class="text-right">บรรทัด</th>
                <th>สถานะ</th>
                <th class="w-10"><span class="sr-only">เปิด</span></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in items"
                :key="row.id"
                class="cursor-pointer"
                data-test="voucher-row"
                @click="openDetail(row.id)"
              >
                <td class="num whitespace-nowrap text-ink-3">
                  {{ formatThaiDate(row.voucher_date) }}
                </td>
                <td class="num font-bold text-ink">
                  <!-- ลิงก์จริงเพื่อให้คีย์บอร์ด/อ่านจอเข้าถึงได้ (แถวคลิกซ้ำได้) -->
                  <RouterLink
                    :to="{ name: 'finance-expense-voucher-detail', params: { id: row.id } }"
                    class="hover:underline"
                    @click.stop
                  >
                    {{ row.pv_receipt_no || `#${row.id}` }}
                  </RouterLink>
                </td>
                <td class="max-w-[16rem] truncate">{{ row.payee_name }}</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(row.total_amount) }}
                </td>
                <td class="num text-right text-ink-3">{{ row.line_count }}</td>
                <td>
                  <span
                    class="chip"
                    :class="
                      row.status === 'voided'
                        ? 'bg-danger-50 text-danger-700'
                        : 'bg-ok-50 text-ok-700'
                    "
                  >
                    {{ STATUS_LABELS[row.status] ?? row.status }}
                  </span>
                </td>
                <td class="text-right text-ink-3">
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
