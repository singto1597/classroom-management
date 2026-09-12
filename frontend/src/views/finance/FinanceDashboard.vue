<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { FinanceService } from '@/services/finance';
import type { FinanceSummary, Account } from '@/types/finance';
import { Doughnut } from 'vue-chartjs';
import { Chart as ChartJS, Title, Tooltip, Legend, ArcElement, CategoryScale } from 'chart.js';
import type { ChartOptions } from 'chart.js';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';

ChartJS.register(Title, Tooltip, Legend, ArcElement, CategoryScale);

const authStore = useAuthStore();
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName || 'ผู้ดูแลระบบ';

const summary = ref<FinanceSummary | null>(null);
const accounts = ref<Account[]>([]);
const isLoading = ref(true);

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false);

const isExporting = ref(false);
const isExportMenuOpen = ref(false);

// 📥 Export แต่ละแบบ: 'summary' = สรุปรายการเดิม, 'journal' = สมุดรายวัน (นักบัญชี)
type ExportKind = 'summary' | 'journal';

const selectedMonth = ref(new Date().getMonth() + 1);
const selectedYear = ref(new Date().getFullYear());

const thaiMonths = [
  'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
  'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'
];

// ✨ ปีที่เลือก: ตั้งแต่ปีที่แล้วถึงปีหน้า (รอบปีปัจจุบัน) ไม่ต้องแก้โค้ดทุกปี
const yearOptions = computed(() => {
  const currentYear = new Date().getFullYear();
  return [currentYear - 1, currentYear, currentYear + 1];
});

const fetchDashboardData = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    const [summaryRes, accountsRes] = await Promise.all([
      FinanceService.getSummary(currentServerId, selectedMonth.value, selectedYear.value),
      FinanceService.getAccounts(currentServerId)
    ]);
    summary.value = summaryRes;
    accounts.value = accountsRes;
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error);
    hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

const chartData = computed(() => {
  if (!summary.value || summary.value.expense_breakdown.length === 0) {
    return {
      labels: ['ยังไม่มีรายจ่าย'],
      datasets: [{
        data: [1],
        backgroundColor: ['#e7e5e4'], // stone-200
        borderWidth: 0
      }]
    };
  }

  return {
    labels: summary.value.expense_breakdown.map(item => item.category_name),
    datasets: [{
      data: summary.value.expense_breakdown.map(item => item.total_amount),
      // 🎨 ธีม Academic Ledger: เฉดน้ำเงิน brand ไล่ระดับ + เทา stone (ไม่ใช้สีรุ้ง)
      backgroundColor: [
        '#1D4ED8', '#2563EB', '#3B82F6', '#93C5FD', '#78716C', '#A8A29E', '#D6D3D1'
      ],
      borderWidth: 0,
      hoverOffset: 6
    }]
  };
});

const chartOptions: ChartOptions<'doughnut'> = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom',
      labels: {
        usePointStyle: true,
        padding: 20,
        boxWidth: 8,
        font: {
          family: "'Noto Sans Thai', sans-serif",
          size: 11,
          weight: 'bold'
        },
        color: '#78716c' // stone-500
      }
    },
    tooltip: {
      enabled: () => (summary.value?.expense_breakdown.length ?? 0) > 0,
      backgroundColor: 'rgba(28, 25, 23, 0.92)', // stone-900
      titleFont: { family: "'Noto Sans Thai', sans-serif", size: 13 },
      bodyFont: { family: "'Noto Sans Thai', sans-serif", size: 13, weight: 'bold' },
      padding: 12,
      cornerRadius: 12,
      displayColors: true,
      boxPadding: 6
    }
  },
  cutout: '75%',
  animation: {
    animateScale: true,
    animateRotate: true
  }
};

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

// 📥 สร้างลิงก์ดาวน์โหลดจาก Blob แล้วคลิกให้เบราว์เซอร์โหลดไฟล์
const downloadBlob = (blob: Blob, filename: string) => {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

// 📥 ส่งออกของเดือนที่เลือกเป็นไฟล์ Excel ตามชนิดที่เลือก
//   'summary' = สรุปรายการแบบเดิม (POST /finance/export)
//   'journal' = สมุดรายวันทั่วไปสำหรับนักบัญชี (GET /finance/export/journal)
const runExport = async (kind: ExportKind) => {
  if (isExporting.value) return;

  isExporting.value = true;
  isExportMenuOpen.value = false;

  const isJournal = kind === 'journal';
  Swal.fire({
    title: isJournal ? 'กำลังคราฟต์สมุดรายวัน...' : 'กำลังคราฟต์ไฟล์ Excel...',
    text: isJournal
      ? 'ระบบกำลังรวบรวมรายการเดบิต/เครดิตของเดือนที่เลือกให้คุณ'
      : 'ระบบกำลังรวบรวมประวัติการทำรายการให้คุณ',
    allowOutsideClick: false,
    didOpen: () => Swal.showLoading()
  });

  try {
    const blob = isJournal
      ? await FinanceService.exportJournalExcel(currentServerId, selectedMonth.value, selectedYear.value)
      : await FinanceService.exportTransactionsExcel(
        currentServerId,
        selectedMonth.value,
        selectedYear.value,
        currentUserName
      );

    // ตั้งชื่อไฟล์สวยๆ (ใช้เดือน/ปีที่เลือกบนหน้า)
    const mm = String(selectedMonth.value).padStart(2, '0');
    const beYear = selectedYear.value + 543;
    const filename = isJournal
      ? `สมุดรายวัน_${mm}-${beYear}.xlsx`
      : `ประวัติการเงิน_${mm}-${beYear}.xlsx`;

    downloadBlob(blob, filename);

    Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: 'ดาวน์โหลดไฟล์ Excel เรียบร้อยแล้ว',
      timer: 1500,
      showConfirmButton: false
    });
  } catch (error) {
    console.error(error);
    Swal.fire({
      icon: 'error',
      title: 'เกิดข้อผิดพลาด',
      text: 'ไม่สามารถส่งออกข้อมูลได้ กรุณาลองใหม่อีกครั้ง',
      confirmButtonColor: '#1d4ed8'
    });
  } finally {
    isExporting.value = false;
  }
};

onMounted(() => {
  fetchDashboardData();
});

watch([selectedMonth, selectedYear], () => {
  fetchDashboardData();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Finance Overview"
      title="ภาพรวมการเงิน"
      :description="`สรุปการเงินประจำเดือน ${thaiMonths[selectedMonth - 1]} ${selectedYear + 543}`"
    >
      <template #actions>
        <!-- ตัวกรองเดือน/ปี -->
        <div class="relative w-[calc(50%_-_0.25rem)] sm:w-auto">
          <select v-model="selectedMonth" class="field appearance-none pe-9 sm:w-36" aria-label="เลือกเดือน">
            <option v-for="(month, index) in thaiMonths" :key="index" :value="index + 1">
              {{ month }}
            </option>
          </select>
          <i
            class="bi bi-chevron-down pointer-events-none absolute inset-y-0 end-3 flex items-center text-xs text-stone-400"
            aria-hidden="true"
          ></i>
        </div>

        <div class="relative w-[calc(50%_-_0.25rem)] sm:w-auto">
          <select v-model="selectedYear" class="field appearance-none pe-9 sm:w-32" aria-label="เลือกปีการศึกษา">
            <option v-for="y in yearOptions" :key="y" :value="y">
              พ.ศ. {{ y + 543 }}
            </option>
          </select>
          <i
            class="bi bi-chevron-down pointer-events-none absolute inset-y-0 end-3 flex items-center text-xs text-stone-400"
            aria-hidden="true"
          ></i>
        </div>

        <!-- 📥 ปุ่มส่งออก Excel (ตามเดือน/ปีที่เลือก) — Dropdown เลือกแบบสรุปรายการ หรือสมุดรายวัน -->
        <div class="relative w-full sm:w-auto">
          <button
            @click="isExportMenuOpen = !isExportMenuOpen"
            :disabled="isExporting"
            class="btn-primary w-full sm:w-auto"
            title="ส่งออกข้อมูลการเงินของเดือนนี้เป็น Excel"
          >
            <i class="bi bi-file-earmark-excel" aria-hidden="true"></i>
            <span>ส่งออก Excel</span>
            <i class="bi bi-chevron-down text-xs" aria-hidden="true"></i>
          </button>

          <!-- Overlay ไว้ปิดเมนูเมื่อคลิกข้างนอก -->
          <div v-if="isExportMenuOpen" class="fixed inset-0 z-20" @click="isExportMenuOpen = false"></div>

          <!-- Dropdown Menu: 2 ตัวเลือก -->
          <div
            v-if="isExportMenuOpen"
            class="absolute end-0 top-full z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-stone-200 bg-white"
          >
            <!-- แบบที่ 1: สรุปรายการ (แบบปกติ) -->
            <button
              @click="runExport('summary')"
              class="group flex w-full items-center gap-3 p-3.5 text-left transition-colors hover:bg-stone-50 active:scale-[0.99]"
              title="ดาวน์โหลดสรุป รายรับ/รายจ่าย + ยอดคงเหลือรายบัญชี"
            >
              <div
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700 transition-colors group-hover:bg-brand-700 group-hover:text-white"
              >
                <i class="bi bi-file-earmark-excel text-xl" aria-hidden="true"></i>
              </div>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-stone-900">ดาวน์โหลดสรุปรายการ (แบบปกติ)</p>
                <p class="mt-0.5 text-xs text-stone-400">รายรับ/รายจ่าย แยกหมวดหมู่ + ยอดคงเหลือบัญชี</p>
              </div>
              <i class="bi bi-chevron-right shrink-0 self-center text-stone-300" aria-hidden="true"></i>
            </button>

            <div class="mx-4 border-t border-stone-100"></div>

            <!-- แบบที่ 2: สมุดรายวัน (แบบนักบัญชี) -->
            <button
              @click="runExport('journal')"
              class="group flex w-full items-center gap-3 p-3.5 text-left transition-colors hover:bg-stone-50 active:scale-[0.99]"
              title="ดาวน์โหลดสมุดรายวันทั่วไป (เดบิต/เครดิต) สำหรับนักบัญชี"
            >
              <div
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-600 transition-colors group-hover:bg-stone-800 group-hover:text-white"
              >
                <i class="bi bi-journal-text text-xl" aria-hidden="true"></i>
              </div>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-stone-900">ดาวน์โหลดสมุดรายวัน (แบบนักบัญชี)</p>
                <p class="mt-0.5 text-xs text-stone-400">รายการ เดบิต/เครดิต รายบัญชี (สมุดรายวันทั่วไป)</p>
              </div>
              <i class="bi bi-chevron-right shrink-0 self-center text-stone-300" aria-hidden="true"></i>
            </button>
          </div>
        </div>
      </template>
    </PageHeader>

    <!-- สถานะโหลด / ผิดพลาด -->
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />
    <StateBlock v-else-if="hasError || !summary" variant="error" @retry="fetchDashboardData" />

    <template v-else>
      <!-- KPI การเงิน: ยอดคงเหลือ / ค้างชำระ / รายรับ / รายจ่าย -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div class="page-card col-span-2 border-s-4 border-s-brand-700 p-3.5 sm:p-5 lg:col-span-1">
          <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">เงินคงเหลือรวม</p>
          <p class="font-display num mt-2 break-words text-2xl font-bold text-stone-900 sm:text-3xl">
            <span class="me-1 text-lg text-stone-400">฿</span>{{ formatNumber(summary.net_worth) }}
          </p>
        </div>

        <div class="page-card col-span-2 p-3.5 sm:p-5 lg:col-span-1">
          <p class="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">
            <i class="bi bi-hourglass-split text-amber-600" aria-hidden="true"></i>
            ยอดที่เพื่อนค้างจ่ายรวม
          </p>
          <p class="font-display num mt-2 break-words text-2xl font-bold text-amber-700 sm:text-3xl">
            <span class="me-1 text-lg text-amber-500/70">฿</span>{{ formatNumber(summary.pending_collection_amount) }}
          </p>
        </div>

        <div class="page-card p-3.5 sm:p-5">
          <p class="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">
            <i class="bi bi-graph-up-arrow text-emerald-600" aria-hidden="true"></i>
            รายรับเดือนนี้
          </p>
          <p class="font-display num mt-2 break-words text-base font-bold text-emerald-600 sm:text-2xl">
            +{{ formatNumber(summary.total_income) }}
          </p>
        </div>

        <div class="page-card p-3.5 sm:p-5">
          <p class="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">
            <i class="bi bi-graph-down-arrow text-red-600" aria-hidden="true"></i>
            รายจ่ายเดือนนี้
          </p>
          <p class="font-display num mt-2 break-words text-base font-bold text-red-600 sm:text-2xl">
            -{{ formatNumber(summary.total_expense) }}
          </p>
        </div>
      </div>

      <!-- ทางลัด -->
      <div class="page-card p-4 sm:p-5">
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <RouterLink
            to="/finance/transactions"
            class="flex flex-col items-center gap-1.5 rounded-xl border border-stone-200 px-2 py-2.5 text-center transition-colors hover:bg-stone-50 active:scale-[0.97]"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
              <i class="bi bi-receipt text-xl" aria-hidden="true"></i>
            </span>
            <span class="text-xs font-bold text-stone-600">ประวัติรายการ</span>
          </RouterLink>

          <RouterLink
            to="/finance/collections"
            class="flex flex-col items-center gap-1.5 rounded-xl border border-stone-200 px-2 py-2.5 text-center transition-colors hover:bg-stone-50 active:scale-[0.97]"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
              <i class="bi bi-box-seam text-xl" aria-hidden="true"></i>
            </span>
            <span class="text-xs font-bold text-stone-600">โปรเจกต์เก็บเงิน</span>
          </RouterLink>

          <RouterLink
            to="/finance/debtors"
            class="flex flex-col items-center gap-1.5 rounded-xl border border-stone-200 px-2 py-2.5 text-center transition-colors hover:bg-stone-50 active:scale-[0.97]"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
              <i class="bi bi-exclamation-triangle text-xl" aria-hidden="true"></i>
            </span>
            <span class="text-xs font-bold text-stone-600">สรุปยอดค้างจ่าย</span>
          </RouterLink>

          <!-- Admin Only: ถ้าไม่ใช่แอดมิน ช่องนี้แสดงแบบปิดการใช้งาน -->
          <div
            v-if="!authStore.isAdmin"
            class="flex flex-col items-center gap-1.5 rounded-xl border border-dashed border-stone-200 bg-stone-50/60 px-2 py-2.5 text-center"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-stone-100 text-stone-400">
              <i class="bi bi-gear text-xl" aria-hidden="true"></i>
            </span>
            <span class="text-xs font-bold text-stone-500">ตั้งค่า (แอดมิน)</span>
          </div>

          <RouterLink
            v-else
            to="/finance/settings"
            class="flex flex-col items-center gap-1.5 rounded-xl border border-stone-200 px-2 py-2.5 text-center transition-colors hover:bg-stone-50 active:scale-[0.97]"
          >
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-stone-100 text-stone-600">
              <i class="bi bi-gear text-xl" aria-hidden="true"></i>
            </span>
            <span class="text-xs font-bold text-stone-600">ตั้งค่าการเงิน</span>
          </RouterLink>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- กระเป๋าเงินห้อง -->
        <div class="page-card p-4 sm:p-5 lg:col-span-2">
          <div class="mb-4 flex items-center justify-between gap-3">
            <h2 class="section-title flex min-w-0 items-center gap-2">
              <i class="bi bi-credit-card-2-front text-brand-700" aria-hidden="true"></i>
              <span class="truncate">กระเป๋าเงินห้อง</span>
            </h2>
            <RouterLink
              v-if="authStore.isAdmin"
              to="/finance/settings"
              class="btn-ghost-ui shrink-0 px-3 py-2 text-xs"
            >
              จัดการบัญชี
            </RouterLink>
          </div>

          <StateBlock
            v-if="accounts.length === 0"
            variant="empty"
            title="ยังไม่มีกระเป๋าเงิน"
            hint="เพิ่มกระเป๋าเงินได้ที่หน้าตั้งค่าการเงิน"
          />

          <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div
              v-for="acc in accounts"
              :key="acc.id"
              class="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-stone-200 bg-stone-50/60 p-3.5"
            >
              <p class="min-w-0 truncate font-display text-base font-bold text-stone-900">
                {{ acc.account_name }}
              </p>
              <p class="num shrink-0 font-display text-base font-bold text-brand-700">
                ฿ {{ formatNumber(acc.balance) }}
              </p>
            </div>
          </div>
        </div>

        <!-- สัดส่วนรายจ่าย -->
        <div class="page-card flex flex-col p-4 sm:p-5">
          <h2 class="section-title mb-4 flex items-center gap-2">
            <i class="bi bi-pie-chart text-stone-400" aria-hidden="true"></i>
            สัดส่วนรายจ่าย
          </h2>
          <div class="relative h-[240px] w-full sm:h-[280px]">
            <!-- ป้ายกลางวง เมื่อยังไม่มีรายจ่าย -->
            <div
              v-if="!summary?.expense_breakdown.length"
              class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"
            >
              <i class="bi bi-cup-hot mb-1 text-3xl text-stone-300" aria-hidden="true"></i>
              <p class="text-xs font-bold text-stone-400">ยังไม่มีรายจ่าย</p>
            </div>
            <div class="h-full w-full">
              <Doughnut :data="chartData" :options="chartOptions" />
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
