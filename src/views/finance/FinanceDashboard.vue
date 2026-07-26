<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { FinanceService } from '@/services/finance';
import type { FinanceSummary, Account } from '@/types/finance';
import { Doughnut } from 'vue-chartjs';
import { Chart as ChartJS, Title, Tooltip, Legend, ArcElement, CategoryScale } from 'chart.js';

import { useAuthStore } from '@/stores/auth';

ChartJS.register(Title, Tooltip, Legend, ArcElement, CategoryScale);

const authStore = useAuthStore();
const currentServerId = authStore.currentRoomId!;

const summary = ref<FinanceSummary | null>(null);
const accounts = ref<Account[]>([]);
const isLoading = ref(true);

const selectedMonth = ref(new Date().getMonth() + 1);
const selectedYear = ref(new Date().getFullYear());

const thaiMonths = [
  'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
  'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'
];

const fetchDashboardData = async () => {
  isLoading.value = true;
  try {
    const [summaryRes, accountsRes] = await Promise.all([
      FinanceService.getSummary(currentServerId, selectedMonth.value, selectedYear.value),
      FinanceService.getAccounts(currentServerId)
    ]);
    summary.value = summaryRes;
    accounts.value = accountsRes;
  } catch (error) {
    console.error('Failed to fetch dashboard data:', error);
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
        backgroundColor: ['#f1f5f9'], // slate-100
        borderWidth: 0
      }]
    };
  }

  return {
    labels: summary.value.expense_breakdown.map(item => item.category_name),
    datasets: [{
      data: summary.value.expense_breakdown.map(item => item.total_amount),
      backgroundColor: [
        '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#6366f1'
      ],
      borderWidth: 0,
      hoverOffset: 6
    }]
  };
});

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom' as const,
      labels: {
        usePointStyle: true,
        padding: 20,
        boxWidth: 8,
        font: {
          family: "'Sarabun', sans-serif",
          size: 11,
          weight: 'bold'
        },
        color: '#64748b' // slate-500
      }
    },
    tooltip: {
      enabled: summary.value?.expense_breakdown.length !== 0,
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      titleFont: { family: "'Sarabun', sans-serif", size: 13 },
      bodyFont: { family: "'Sarabun', sans-serif", size: 13, weight: 'bold' },
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
} as any ;

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

onMounted(() => {
  fetchDashboardData();
});

watch([selectedMonth, selectedYear], () => {
  fetchDashboardData();
});
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-7xl mx-auto">
      
      <!-- Header Section -->
      <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 md:mb-8 gap-4">
        <div class="flex items-center gap-4 w-full md:w-auto">
          <RouterLink 
            to="/dashboard"
            class="bg-white hover:bg-slate-100 text-slate-600 p-3 rounded-2xl transition-all shadow-sm border border-slate-200 shrink-0 group"
            title="กลับหน้าหลัก"
          >
            <i class="bi bi-house-door-fill text-xl group-hover:scale-110 transition-transform"></i>
          </RouterLink>
          <div>
            <h1 class="text-2xl md:text-3xl font-extrabold text-slate-800 tracking-tight flex items-center gap-2">
              ภาพรวมการเงิน
            </h1>
            <p class="text-slate-500 mt-0.5 text-sm md:text-base font-medium">
              ประจำเดือน <span class="text-blue-600 font-bold">{{ thaiMonths[selectedMonth - 1] }} {{ selectedYear + 543 }}</span>
            </p>
          </div>
        </div>

        <!-- Date Filters (Pill Style) -->
        <div class="flex flex-row gap-2 w-full md:w-auto">
          <div class="relative flex-1 md:flex-none">
            <select 
              v-model="selectedMonth" 
              class="w-full appearance-none bg-white border border-slate-200 text-slate-700 py-2.5 pl-4 pr-10 rounded-2xl shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 font-bold text-sm transition-all cursor-pointer"
            >
              <option v-for="(month, index) in thaiMonths" :key="index" :value="index + 1">
                {{ month }}
              </option>
            </select>
            <i class="bi bi-chevron-down absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none text-xs font-bold"></i>
          </div>
          <div class="relative flex-1 md:flex-none">
            <select 
              v-model="selectedYear" 
              class="w-full appearance-none bg-white border border-slate-200 text-slate-700 py-2.5 pl-4 pr-10 rounded-2xl shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 font-bold text-sm transition-all cursor-pointer"
            >
              <option v-for="y in [2024, 2025, 2026]" :key="y" :value="y">
                พ.ศ. {{ y + 543 }}
              </option>
            </select>
            <i class="bi bi-chevron-down absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none text-xs font-bold"></i>
          </div>
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="isLoading" class="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-slate-100 shadow-sm">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
        <p class="text-slate-400 font-medium">กำลังโหลดข้อมูลภาพรวม...</p>
      </div>

      <div v-else-if="summary" class="space-y-6 md:space-y-8">
        
        <!-- SUMMARY CARDS (Smart Mobile Grid) -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3.5 md:gap-5">
          <!-- Net Worth Card (Full width on mobile) -->
          <div class="col-span-2 lg:col-span-1 bg-gradient-to-br from-slate-800 to-slate-900 rounded-[1.5rem] shadow-lg shadow-slate-900/20 p-5 md:p-6 text-white relative overflow-hidden group">
            <div class="absolute -right-4 -bottom-4 w-32 h-32 bg-white/5 rounded-full blur-2xl group-hover:scale-150 transition-transform duration-700"></div>
            <i class="bi bi-wallet2 absolute -right-2 -bottom-2 text-6xl text-white/10 group-hover:scale-110 transition-transform duration-500"></i>
            <p class="text-slate-300 text-xs md:text-sm font-bold uppercase tracking-wider mb-2">เงินคงเหลือรวม</p>
            <h2 class="text-3xl md:text-4xl font-black tracking-tight">
              <span class="text-xl md:text-2xl mr-1 opacity-80">฿</span>{{ formatNumber(summary.net_worth) }}
            </h2>
          </div>

          <!-- Pending Debt Card (Full width on mobile) -->
          <div class="col-span-2 lg:col-span-1 bg-gradient-to-br from-amber-500 to-orange-600 rounded-[1.5rem] shadow-lg shadow-orange-500/20 p-5 md:p-6 text-white relative overflow-hidden group">
            <div class="absolute -right-4 -bottom-4 w-32 h-32 bg-white/10 rounded-full blur-2xl group-hover:scale-150 transition-transform duration-700"></div>
            <i class="bi bi-hourglass-split absolute -right-2 -bottom-2 text-6xl text-white/10 group-hover:scale-110 group-hover:-rotate-12 transition-transform duration-500"></i>
            <p class="text-amber-100 text-xs md:text-sm font-bold uppercase tracking-wider mb-2">ยอดที่เพื่อนค้างจ่ายรวม</p>
            <h2 class="text-3xl md:text-4xl font-black tracking-tight">
              <span class="text-xl md:text-2xl mr-1 opacity-80">฿</span>{{ formatNumber(summary.pending_collection_amount) }}
            </h2>
          </div>

          <!-- Income Card (Half width on mobile) -->
          <div class="col-span-1 bg-gradient-to-br from-emerald-500 to-teal-600 rounded-[1.5rem] shadow-md shadow-emerald-500/10 p-4 md:p-6 text-white relative overflow-hidden group">
            <i class="bi bi-graph-up-arrow absolute -right-2 -bottom-2 text-5xl text-white/10 group-hover:scale-110 group-hover:-translate-y-1 transition-transform duration-500"></i>
            <p class="text-emerald-100 text-[10px] md:text-xs font-bold uppercase tracking-wider mb-1.5 md:mb-2 line-clamp-1">รายรับเดือนนี้</p>
            <h2 class="text-xl sm:text-2xl md:text-3xl font-black tracking-tight truncate">
              <span class="text-sm md:text-xl mr-0.5 opacity-80">+</span>{{ formatNumber(summary.total_income) }}
            </h2>
          </div>

          <!-- Expense Card (Half width on mobile) -->
          <div class="col-span-1 bg-gradient-to-br from-rose-500 to-pink-600 rounded-[1.5rem] shadow-md shadow-rose-500/10 p-4 md:p-6 text-white relative overflow-hidden group">
            <i class="bi bi-graph-down-arrow absolute -right-2 -bottom-2 text-5xl text-white/10 group-hover:scale-110 group-hover:translate-y-1 transition-transform duration-500"></i>
            <p class="text-rose-100 text-[10px] md:text-xs font-bold uppercase tracking-wider mb-1.5 md:mb-2 line-clamp-1">รายจ่ายเดือนนี้</p>
            <h2 class="text-xl sm:text-2xl md:text-3xl font-black tracking-tight truncate">
              <span class="text-sm md:text-xl mr-0.5 opacity-80">-</span>{{ formatNumber(summary.total_expense) }}
            </h2>
          </div>
        </div>

        <!-- QUICK MENU (App Style - 4 Icons in a row on mobile) -->
        <div class="bg-white rounded-3xl p-4 md:p-6 shadow-sm border border-slate-100">
          <div class="grid grid-cols-4 gap-2 md:gap-4">
            <RouterLink 
              to="/finance/transactions"
              class="flex flex-col items-center gap-2 group active:scale-95 transition-transform"
            >
              <div class="w-12 h-12 md:w-14 md:h-14 flex items-center justify-center bg-blue-50 text-blue-600 rounded-[1rem] md:rounded-2xl group-hover:bg-blue-600 group-hover:text-white transition-colors shadow-sm">
                <i class="bi bi-receipt text-xl md:text-2xl"></i>
              </div>
              <span class="text-[10px] md:text-sm font-bold text-slate-600 text-center leading-tight">ประวัติ<br class="md:hidden">รายการ</span>
            </RouterLink>

            <RouterLink 
              to="/finance/collections"
              class="flex flex-col items-center gap-2 group active:scale-95 transition-transform"
            >
              <div class="w-12 h-12 md:w-14 md:h-14 flex items-center justify-center bg-emerald-50 text-emerald-600 rounded-[1rem] md:rounded-2xl group-hover:bg-emerald-600 group-hover:text-white transition-colors shadow-sm">
                <i class="bi bi-box-seam-fill text-xl md:text-2xl"></i>
              </div>
              <span class="text-[10px] md:text-sm font-bold text-slate-600 text-center leading-tight">โปรเจกต์<br class="md:hidden">เก็บเงิน</span>
            </RouterLink>

            <RouterLink 
              to="/finance/debtors"
              class="flex flex-col items-center gap-2 group active:scale-95 transition-transform"
            >
              <div class="w-12 h-12 md:w-14 md:h-14 flex items-center justify-center bg-rose-50 text-rose-600 rounded-[1rem] md:rounded-2xl group-hover:bg-rose-600 group-hover:text-white transition-colors shadow-sm">
                <i class="bi bi-exclamation-triangle-fill text-xl md:text-2xl"></i>
              </div>
              <span class="text-[10px] md:text-sm font-bold text-slate-600 text-center leading-tight">สรุปยอด<br class="md:hidden">ค้างจ่าย</span>
            </RouterLink>

            <!-- Admin Only: If not admin, this space can be empty or show a disabled icon -->
            <div v-if="!authStore.isAdmin" class="flex flex-col items-center gap-2 opacity-40 grayscale">
              <div class="w-12 h-12 md:w-14 md:h-14 flex items-center justify-center bg-slate-100 text-slate-400 rounded-[1rem] md:rounded-2xl shadow-sm">
                <i class="bi bi-gear-fill text-xl md:text-2xl"></i>
              </div>
              <span class="text-[10px] md:text-sm font-bold text-slate-400 text-center leading-tight">ตั้งค่า<br class="md:hidden">(แอดมิน)</span>
            </div>
            
            <RouterLink 
              v-else
              to="/finance/settings"
              class="flex flex-col items-center gap-2 group active:scale-95 transition-transform"
            >
              <div class="w-12 h-12 md:w-14 md:h-14 flex items-center justify-center bg-slate-100 text-slate-600 rounded-[1rem] md:rounded-2xl group-hover:bg-slate-800 group-hover:text-white transition-colors shadow-sm">
                <i class="bi bi-gear-fill text-xl md:text-2xl"></i>
              </div>
              <span class="text-[10px] md:text-sm font-bold text-slate-600 text-center leading-tight">ตั้งค่า<br class="md:hidden">การเงิน</span>
            </RouterLink>
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 md:gap-8">
          <!-- WALLETS SECTION (Digital Card Style) -->
          <div class="lg:col-span-2 bg-white rounded-3xl border border-slate-100 shadow-sm p-5 md:p-7">
            <div class="flex justify-between items-center mb-6">
              <h3 class="text-lg md:text-xl font-extrabold text-slate-800 flex items-center gap-2">
                <i class="bi bi-credit-card-2-front text-blue-500"></i> กระเป๋าเงินห้อง
              </h3>
              <RouterLink 
                v-if="authStore.isAdmin"
                to="/finance/settings" 
                class="text-[11px] md:text-xs font-bold text-slate-500 bg-slate-50 border border-slate-200 hover:bg-slate-100 hover:text-slate-800 px-3 py-1.5 rounded-lg transition-colors"
              >
                จัดการบัญชี
              </RouterLink>
            </div>

            <div v-if="accounts.length === 0" class="text-center py-12 border border-dashed border-slate-200 rounded-2xl bg-slate-50">
              <i class="bi bi-wallet2 text-3xl text-slate-300 mb-2 block"></i>
              <p class="text-slate-400 font-bold text-sm">ยังไม่มีกระเป๋าเงิน</p>
            </div>
            <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div 
                v-for="acc in accounts" 
                :key="acc.id" 
                class="relative overflow-hidden p-5 rounded-[1.25rem] border border-slate-200 bg-gradient-to-br from-white to-slate-50 group hover:shadow-md hover:border-blue-200 transition-all"
              >
                <!-- Decorative Card Chip -->
                <div class="absolute top-5 right-5 opacity-20 group-hover:opacity-40 transition-opacity">
                  <i class="bi bi-sim text-2xl text-slate-400"></i>
                </div>
                
                <div class="mb-6">
                  <span class="text-slate-400 text-[10px] font-bold uppercase tracking-wider block mb-0.5">ชื่อบัญชี</span>
                  <span class="font-extrabold text-slate-800 text-base line-clamp-1">{{ acc.account_name }}</span>
                </div>
                <div>
                  <span class="text-slate-400 text-[10px] font-bold uppercase tracking-wider block mb-0.5">ยอดคงเหลือ</span>
                  <span class="text-blue-600 font-black text-xl tracking-tight">฿ {{ formatNumber(acc.balance) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- EXPENSE CHART SECTION -->
          <div class="bg-white rounded-3xl border border-slate-100 shadow-sm p-5 md:p-7 flex flex-col">
            <h3 class="text-lg md:text-xl font-extrabold text-slate-800 flex items-center gap-2 mb-6">
              <i class="bi bi-pie-chart text-rose-500"></i> สัดส่วนรายจ่าย
            </h3>
            <div class="flex-grow flex items-center justify-center relative min-h-[220px] md:min-h-[260px]">
              <!-- Custom Center Label if empty -->
              <div v-if="!summary?.expense_breakdown.length" class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <i class="bi bi-cup-hot text-slate-300 text-3xl mb-1"></i>
                <p class="text-slate-400 text-xs font-bold">ยังไม่มีรายจ่าย</p>
              </div>
              <div class="w-full h-full max-h-[260px]">
                <Doughnut :data="chartData" :options="chartOptions" />
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600;700;800&display=swap');

/* ให้แน่ใจว่า Font Sarabun ทำงานทั้งหน้า */
* {
  font-family: 'Sarabun', sans-serif;
  -webkit-tap-highlight-color: transparent;
}
</style>