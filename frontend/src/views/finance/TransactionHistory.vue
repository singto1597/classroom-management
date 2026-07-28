<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { FinanceService } from '@/services/finance';
import type { Transaction } from '@/types/finance';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

// ดึง isAdmin ออกมาเป็น computed เพื่อให้ reactivity ทำงานถูกต้องและเรียกใช้สั้นลง
const isAdmin = computed(() => authStore.isAdmin);

const transactions = ref<Transaction[]>([]);
const totalCount = ref(0);
const isLoading = ref(true);

const filters = ref({
  type: '',
  start_date: '',
  end_date: '',
  limit: 50,
  offset: 0
});

const currentPage = ref(1);

const fetchTransactions = async () => {
  isLoading.value = true;
  try {
    const apiFilters = {
      ...filters.value,
      transaction_type: filters.value.type || undefined,
      start_date: filters.value.start_date || undefined,
      end_date: filters.value.end_date || undefined,
      offset: (currentPage.value - 1) * filters.value.limit
    };
    
    // Remove empty strings to avoid sending them to API
    Object.keys(apiFilters).forEach(key => {
      if ((apiFilters as any)[key] === '') delete (apiFilters as any)[key];
    });

    const res = await FinanceService.getTransactions(currentServerId, apiFilters);
    transactions.value = res.items;
    totalCount.value = res.total_count;
  } catch (error: any) {
    Swal.fire('Error', error.message || 'โหลดข้อมูลไม่สำเร็จ', 'error');
  } finally {
    isLoading.value = false;
  }
};

const handleRevert = async (transaction: Transaction) => {
  // เพิ่ม Guard ป้องกันเผื่อมีคนเรียกฟังก์ชันนี้ข้าม UI
  if (!isAdmin.value) {
    Swal.fire('ไม่มีสิทธิ์เข้าถึง', 'เฉพาะผู้ดูแลระบบเท่านั้นที่สามารถยกเลิกรายการได้', 'error');
    return;
  }

  const result = await Swal.fire({
    title: 'ต้องการยกเลิก?',
    html: `คุณกำลังจะยกเลิกรายการ:<br><b class="text-lg text-slate-800 mt-2 block">"${transaction.description}"</b><br><span class="text-rose-500 text-sm font-medium bg-rose-50 px-3 py-2 rounded-lg block mt-2 border border-rose-100">ยอดเงินจะถูกคืนกลับกระเป๋าเดิม<br>หากเป็นรายการรับเงินจากเพื่อน สถานะบิลจะถูกตีกลับเป็น "ค้างจ่าย" ทันที</span>`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#e11d48',
    cancelButtonColor: '#94a3b8',
    confirmButtonText: 'ยืนยันการยกเลิก',
    cancelButtonText: 'ปิด'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.revertTransaction(currentServerId, transaction.id, currentUserName);
      Swal.fire({ icon: 'success', title: 'ยกเลิกรายการสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchTransactions();
    } catch (error: any) {
      Swal.fire('ยกเลิกไม่ได้', error.message, 'error');
    }
  }
};

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr);
  const datePart = date.toLocaleDateString('en-GB'); // dd/mm/yyyy
  const timePart = date.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' });
  return { datePart, timePart };
};

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

const totalPages = computed(() => Math.ceil(totalCount.value / filters.value.limit));

onMounted(() => {
  fetchTransactions();
});

watch([currentPage, () => filters.value.limit], () => {
  fetchTransactions();
});

const applyFilters = () => {
  currentPage.value = 1;
  fetchTransactions();
};

const resetFilters = () => {
  filters.value = {
    type: '',
    start_date: '',
    end_date: '',
    limit: 50,
    offset: 0
  };
  currentPage.value = 1;
  fetchTransactions();
};
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-7xl mx-auto">
      
      <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 md:mb-8 gap-4 md:gap-6">
        <div class="flex items-center gap-4 w-full md:w-auto">
          <RouterLink 
            to="/finance"
            class="bg-white hover:bg-slate-100 text-slate-600 p-3 rounded-2xl transition-all shadow-sm border border-slate-200 group flex-shrink-0"
            title="กลับหน้าภาพรวม"
          >
            <i class="bi bi-arrow-left text-xl group-hover:-translate-x-1 transition-transform"></i>
          </RouterLink>
          <div>
            <h1 class="text-2xl md:text-3xl font-extrabold text-slate-800 tracking-tight">ประวัติการทำรายการ</h1>
            <p class="text-slate-500 mt-1 text-sm md:text-base font-medium">รายการรับ จ่าย และโอนเงินทั้งหมดของห้อง</p>
          </div>
        </div>
        
        <RouterLink 
          v-if="isAdmin"
          to="/finance/transactions/add"
          class="w-full md:w-auto bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-bold py-3 px-6 rounded-2xl shadow-lg shadow-blue-600/25 transition-all flex items-center justify-center gap-2"
        >
          <i class="bi bi-plus-lg text-lg"></i> บันทึกรายการใหม่
        </RouterLink>
      </div>

      <div class="bg-white rounded-3xl border border-slate-200/60 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.03)] p-5 md:p-6 mb-6 md:mb-8">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
          <div>
            <label class="block text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">ประเภทรายการ</label>
            <select v-model="filters.type" class="w-full bg-slate-50 border border-slate-200 py-2.5 px-4 rounded-xl focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 outline-none transition-all text-slate-700 font-medium">
              <option value="">ทั้งหมด</option>
              <option value="income">รายรับ</option>
              <option value="expense">รายจ่าย</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">จากวันที่</label>
            <input type="date" v-model="filters.start_date" class="w-full bg-slate-50 border border-slate-200 py-2.5 px-4 rounded-xl focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 outline-none transition-all text-slate-700 font-medium">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">ถึงวันที่</label>
            <input type="date" v-model="filters.end_date" class="w-full bg-slate-50 border border-slate-200 py-2.5 px-4 rounded-xl focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 outline-none transition-all text-slate-700 font-medium">
          </div>
          <div class="flex gap-3">
            <button @click="applyFilters" class="flex-1 bg-slate-800 hover:bg-slate-900 text-white font-bold py-2.5 rounded-xl shadow-md transition-all">
              ค้นหา
            </button>
            <button @click="resetFilters" class="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-600 font-bold py-2.5 rounded-xl transition-all border border-slate-200">
              ล้างค่า
            </button>
          </div>
        </div>
      </div>

      <div class="flex flex-col sm:flex-row justify-between items-center mb-4 px-1 gap-3">
        <p class="text-sm font-bold text-slate-500">
          พบข้อมูลทั้งหมด <span class="text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md">{{ totalCount }}</span> รายการ
        </p>
        <div class="flex items-center gap-2">
          <span class="text-xs font-bold text-slate-400 uppercase">แสดง:</span>
          <select v-model="filters.limit" class="text-sm bg-white border border-slate-200 py-1.5 px-3 rounded-lg outline-none font-medium text-slate-700 shadow-sm">
            <option :value="10">10 แถว</option>
            <option :value="50">50 แถว</option>
            <option :value="100">100 แถว</option>
          </select>
        </div>
      </div>

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 bg-white rounded-3xl border border-slate-200/60 shadow-sm">
        <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mb-4"></div>
        <span class="text-slate-400 font-medium">กำลังโหลดข้อมูลการเงิน...</span>
      </div>

      <div v-else-if="transactions.length === 0" class="flex flex-col items-center justify-center py-20 bg-white rounded-3xl border border-slate-200/60 shadow-sm">
        <div class="w-20 h-20 bg-slate-50 rounded-full flex items-center justify-center mb-4">
          <i class="bi bi-receipt text-3xl text-slate-300"></i>
        </div>
        <p class="text-slate-500 font-medium">ไม่พบข้อมูลการทำรายการในช่วงเวลานี้</p>
      </div>

      <div v-else>
        <div class="block md:hidden space-y-4">
          <div v-for="t in transactions" :key="t.id" class="bg-white p-5 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden group">
            <div class="absolute left-0 top-0 bottom-0 w-1.5" :class="t.transaction_type === 'income' ? 'bg-emerald-500' : 'bg-rose-500'"></div>
            
            <div class="flex justify-between items-start mb-3">
              <div class="pr-3">
                <h3 class="font-bold text-slate-800 text-base leading-tight mb-1">{{ t.description }}</h3>
                <div class="text-[11px] font-medium text-slate-400 flex items-center gap-1.5">
                  <i class="bi bi-clock"></i> {{ formatDate(t.created_at).datePart }} • {{ formatDate(t.created_at).timePart }} น.
                </div>
              </div>
              <div class="text-right flex-shrink-0">
                <div :class="[t.transaction_type === 'income' ? 'text-emerald-600' : 'text-rose-600', 'font-extrabold text-lg tracking-tight']">
                  {{ t.transaction_type === 'income' ? '+' : '-' }}฿{{ formatNumber(t.amount) }}
                </div>
              </div>
            </div>

            <div class="flex justify-between items-center mt-4 pt-4 border-t border-slate-50">
              <div class="flex flex-wrap items-center gap-2">
                <span class="inline-flex items-center gap-1 bg-slate-50 text-slate-600 px-2.5 py-1 rounded-lg text-[10px] font-bold border border-slate-200">
                  <i class="bi bi-wallet2 text-blue-500"></i> {{ t.account_name || 'ไม่ระบุ' }}
                </span>
                <span v-if="t.category_name" class="bg-slate-100 text-slate-500 text-[10px] px-2 py-1 rounded-lg font-bold">
                  {{ t.category_name }}
                </span>
              </div>
              
              <div>
                <div v-if="t.transfer_group_id && t.transaction_type === 'income'" class="text-slate-300 italic text-[10px] bg-slate-50 px-2 py-1 rounded-md" title="ยกเลิกได้ที่รายการขาออก">
                  <i class="bi bi-link-45deg"></i> โอนเข้า
                </div>
                <button 
                  v-else-if="isAdmin"
                  @click="handleRevert(t)"
                  class="flex items-center gap-1 text-[11px] font-bold text-rose-500 bg-rose-50 px-3 py-1.5 rounded-lg active:bg-rose-100 transition-colors"
                >
                  <i class="bi bi-arrow-counterclockwise"></i> ยกเลิก
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="hidden md:block bg-white rounded-3xl border border-slate-200/60 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.03)] overflow-hidden">
          <div class="overflow-x-auto w-full">
            <table class="w-full text-left border-collapse min-w-[800px]">
              <thead>
                <tr class="bg-slate-50/80 text-slate-400 text-xs uppercase tracking-wider font-bold border-b border-slate-200">
                  <th class="px-6 py-4 w-40">วันที่-เวลา</th>
                  <th class="px-6 py-4">รายละเอียดรายการ</th>
                  <th class="px-6 py-4">กระเป๋าเงิน</th>
                  <th class="px-6 py-4 text-right">จำนวนเงิน</th>
                  <th class="px-6 py-4 text-center w-24">จัดการ</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                <tr v-for="t in transactions" :key="t.id" class="hover:bg-slate-50 transition-colors group">
                  <td class="px-6 py-4 whitespace-nowrap">
                    <div class="text-sm font-bold text-slate-700">{{ formatDate(t.created_at).datePart }}</div>
                    <div class="text-xs font-medium text-slate-400 mt-0.5">{{ formatDate(t.created_at).timePart }} น.</div>
                  </td>
                  <td class="px-6 py-4">
                    <div class="font-bold text-slate-800 text-base">{{ t.description }}</div>
                    <div class="flex items-center gap-2 mt-1.5">
                      <span v-if="t.category_name" class="bg-slate-100 text-slate-600 text-[10px] px-2.5 py-0.5 rounded-md font-bold">
                        {{ t.category_name }}
                      </span>
                      <span class="text-[10px] font-medium text-slate-400 flex items-center gap-1">
                        <i class="bi bi-person-circle"></i> {{ t.recorded_by }}
                      </span>
                    </div>
                  </td>
                  <td class="px-6 py-4">
                    <span class="inline-flex items-center gap-1.5 bg-blue-50/50 text-blue-700 px-3 py-1.5 rounded-xl text-xs font-bold border border-blue-100/50">
                      <i class="bi bi-wallet2"></i> {{ t.account_name || 'ไม่ระบุ' }}
                    </span>
                  </td>
                  <td class="px-6 py-4 text-right whitespace-nowrap">
                    <span :class="[t.transaction_type === 'income' ? 'text-emerald-600 bg-emerald-50' : 'text-rose-600 bg-rose-50', 'font-extrabold text-base px-3 py-1.5 rounded-xl']">
                      {{ t.transaction_type === 'income' ? '+' : '-' }} ฿{{ formatNumber(t.amount) }}
                    </span>
                  </td>
                  <td class="px-6 py-4 text-center">
                    <div v-if="t.transfer_group_id && t.transaction_type === 'income'" class="text-slate-300 italic text-[11px] font-medium" title="ยกเลิกได้ที่รายการขาออก">
                      <i class="bi bi-link-45deg"></i> โอนเงิน
                    </div>
                    <button 
                      v-else-if="isAdmin"
                      @click="handleRevert(t)"
                      class="w-9 h-9 flex items-center justify-center text-rose-500 bg-white border border-slate-200 hover:border-rose-200 hover:bg-rose-50 hover:shadow-sm rounded-xl transition-all opacity-0 group-hover:opacity-100 mx-auto"
                      title="ยกเลิกรายการ"
                    >
                      <i class="bi bi-arrow-counterclockwise text-lg"></i>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="totalPages > 1" class="mt-8 flex justify-center">
        <div class="flex flex-wrap justify-center gap-2 bg-white p-2 rounded-2xl shadow-sm border border-slate-100 w-fit">
          <button 
            v-for="page in totalPages" 
            :key="page"
            @click="currentPage = page"
            :class="[
              'min-w-[40px] h-10 rounded-xl font-bold transition-all text-sm px-2',
              currentPage === page ? 'bg-slate-800 text-white shadow-md' : 'bg-transparent text-slate-500 hover:bg-slate-100'
            ]"
          >
            {{ page }}
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
/* Optional: ซ่อน Scrollbar ของตารางสำหรับความมินิมอล แต่ยัง Scroll ได้ปกติ */
.overflow-x-auto::-webkit-scrollbar {
  height: 6px;
}
.overflow-x-auto::-webkit-scrollbar-track {
  background: #f1f5f9; 
  border-radius: 4px;
}
.overflow-x-auto::-webkit-scrollbar-thumb {
  background: #cbd5e1; 
  border-radius: 4px;
}
.overflow-x-auto::-webkit-scrollbar-thumb:hover {
  background: #94a3b8; 
}
</style>