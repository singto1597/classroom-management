<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { FinanceService } from '@/services/finance';
import type { Debtor, StudentDebtProfile, Account, StudentDebtItem } from '@/types/finance';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;
const isAdmin = computed(() => authStore.isAdmin);

const debtors = ref<Debtor[]>([]);
const accounts = ref<Account[]>([]);
const isLoading = ref(true);

// Modal/Batch Pay State
const isModalOpen = ref(false);
const selectedStudent = ref<{ id: number; name: string } | null>(null);
const studentDebts = ref<StudentDebtItem[]>([]);
const isLoadingDebts = ref(false);
const selectedPaymentIds = ref<number[]>([]);
const payAmounts = ref<Record<number, number>>({});
const paidToAccountId = ref<string>('');
const slipImageUrl = ref('');

// Memory logic
const lastSelectedMemory = ref<number[] | null>(null);

const fetchDebtors = async () => {
  isLoading.value = true;
  try {
    const [debtRes, accRes] = await Promise.all([
      FinanceService.getAllDebtors(currentServerId),
      FinanceService.getAccounts(currentServerId)
    ]);
    debtors.value = debtRes;
    accounts.value = accRes;
    
    // Auto-select first account
    if (accounts.value.length > 0) {
      paidToAccountId.value = accounts.value[0]?.id.toString() || '';
    }
  } catch (error: any) {
    Swal.fire('Error', 'โหลดข้อมูลลูกหนี้ไม่สำเร็จ', 'error');
  } finally {
    isLoading.value = false;
  }
};

const handleClearDebt = async (debtor: Debtor) => {
  // ดักฝั่ง Script: ป้องกันคนกดเรียกฟังก์ชันข้าม UI
  if (!isAdmin.value) {
    Swal.fire('ไม่มีสิทธิ์เข้าถึง', 'เฉพาะแอดมินเท่านั้นที่สามารถเคลียร์หนี้ได้', 'error');
    return;
  }

  selectedStudent.value = { id: debtor.student_id, name: debtor.student_name };
  isModalOpen.value = true;
  isLoadingDebts.value = true;
  selectedPaymentIds.value = [];
  payAmounts.value = {};
  slipImageUrl.value = '';

  try {
    const res = await FinanceService.getStudentDebts(currentServerId, debtor.student_id);
    studentDebts.value = res.debts;

    // Logic: Auto-Select ฉลาดจำค่าเดิม
    studentDebts.value.forEach(debt => {
      let shouldCheck = false;
      if (lastSelectedMemory.value === null) {
        shouldCheck = true;
      } else {
        shouldCheck = lastSelectedMemory.value.includes(debt.collection_id);
      }

      if (shouldCheck) {
        selectedPaymentIds.value.push(debt.payment_id);
      }
      payAmounts.value[debt.payment_id] = debt.amount;
    });
  } catch (error: any) {
    Swal.fire('Error', 'ดึงรายการค้างชำระไม่สำเร็จ', 'error');
    isModalOpen.value = false;
  } finally {
    isLoadingDebts.value = false;
  }
};

const totalSelectedAmount = computed(() => {
  return selectedPaymentIds.value.reduce((total, id) => {
    return total + (payAmounts.value[id] || 0);
  }, 0);
});

const handleBatchPay = async () => {
  // ดักอีกชั้นตอนกดยืนยันจ่ายเงิน
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');
  }

  if (selectedPaymentIds.value.length === 0) {
    return Swal.fire('อ๊ะ!', 'กรุณาเลือกรายการที่ต้องการชำระเงิน', 'warning');
  }

  // จดจำการตั้งค่าก่อนกดยืนยัน
  lastSelectedMemory.value = studentDebts.value
    .filter(d => selectedPaymentIds.value.includes(d.payment_id))
    .map(d => d.collection_id);

  try {
    Swal.fire({
      title: 'กำลังบันทึก...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading()
    });

    // ลูปยิงทีละรายการตาม Logic เดิม
    const promises = selectedPaymentIds.value.map(pid => {
      return FinanceService.confirmPayment(currentServerId, pid, {
        paid_to_account_id: Number(paidToAccountId.value),
        paid_amount: payAmounts.value[pid] || 0,
        slip_image_url: slipImageUrl.value || undefined,
        user_name: currentUserName
      });
    });

    await Promise.all(promises);

    Swal.fire({ icon: 'success', title: 'สำเร็จ!', text: 'บันทึกการรับเงินรวบยอดเรียบร้อย', timer: 1500, showConfirmButton: false });
    isModalOpen.value = false;
    fetchDebtors();
  } catch (error: any) {
    Swal.fire('Error', error.message || 'บันทึกไม่สำเร็จ', 'error');
  }
};

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

onMounted(() => {
  fetchDebtors();
});
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 md:p-8">
    <div class="max-w-7xl mx-auto">
      
      <!-- Header Section -->
      <div class="flex flex-col md:flex-row items-start md:items-center mb-8 gap-4 md:gap-6">
        <RouterLink 
          to="/finance"
          class="bg-white hover:bg-slate-100 text-slate-600 p-3 rounded-2xl transition-all shadow-sm border border-slate-200 group flex-shrink-0"
          title="กลับหน้าภาพรวม"
        >
          <i class="bi bi-arrow-left text-xl group-hover:-translate-x-1 transition-transform"></i>
        </RouterLink>
        <div>
          <h1 class="text-2xl md:text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-rose-600 to-orange-500 flex items-center gap-2">
            <i class="bi bi-exclamation-triangle-fill text-rose-500 drop-shadow-sm"></i> สรุปผู้ค้างชำระ
          </h1>
          <p class="text-slate-500 mt-1 text-sm md:text-base font-medium">รายชื่อผู้ค้างจ่ายเงินจากทุกโปรเจกต์ (รวมโปรเจกต์ที่ปิดไปแล้ว)</p>
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="isLoading" class="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-slate-100 shadow-sm">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-rose-500 mb-4"></div>
        <span class="text-slate-400 font-medium">กำลังโหลดข้อมูล...</span>
      </div>

      <div v-else>
        <!-- MOBILE VIEW: Cards (Shows only on small screens) -->
        <div class="block md:hidden space-y-4">
          <div v-if="debtors.length === 0" class="flex flex-col items-center justify-center py-20 bg-white rounded-3xl border border-emerald-100 shadow-sm text-center px-4">
            <div class="w-20 h-20 bg-emerald-50 rounded-full flex items-center justify-center mb-4 shadow-inner">
              <span class="text-4xl">🎉</span>
            </div>
            <h3 class="text-emerald-600 font-extrabold text-lg">ไม่มีใครติดหนี้ห้องเลย!</h3>
            <p class="text-slate-500 text-sm mt-1">ห้องนี้รวยมาก ทุกคนจ่ายเงินครบเป๊ะ</p>
          </div>

          <div v-for="d in debtors" :key="d.student_id" class="bg-white p-5 rounded-3xl shadow-sm border border-slate-100 relative overflow-hidden group">
            <div class="absolute left-0 top-0 bottom-0 w-1.5 bg-rose-500"></div>
            
            <div class="flex justify-between items-start mb-4">
              <div>
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-xs font-black text-slate-300 bg-slate-50 px-2 py-0.5 rounded-md">#{{ d.student_no }}</span>
                </div>
                <h3 class="font-extrabold text-slate-800 text-lg">{{ d.student_name }}</h3>
                <div class="mt-2 inline-flex items-center gap-1.5 bg-rose-50 border border-rose-100 text-rose-600 px-2.5 py-1 rounded-lg text-[11px] font-bold">
                  <i class="bi bi-receipt"></i> ค้าง {{ d.overdue_count }} รายการ
                </div>
              </div>
              <div class="text-right">
                <span class="block text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">ยอดรวม</span>
                <div class="font-black text-rose-600 text-xl tracking-tight">
                  ฿{{ formatNumber(d.total_pending_amount) }}
                </div>
              </div>
            </div>

            <div class="pt-4 border-t border-slate-50 flex justify-end">
              <button 
                v-if="isAdmin"
                @click="handleClearDebt(d)"
                class="w-full sm:w-auto bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-bold py-2.5 px-5 rounded-xl shadow-md shadow-blue-600/20 transition-all flex items-center justify-center gap-2"
              >
                <i class="bi bi-wallet2"></i> เคลียร์หนี้
              </button>
              <span v-else class="w-full sm:w-auto text-center text-xs text-slate-400 font-medium bg-slate-50 px-4 py-2.5 rounded-xl border border-slate-100 block">
                <i class="bi bi-lock me-1"></i> รอแอดมินดำเนินการ
              </span>
            </div>
          </div>
        </div>

        <!-- DESKTOP VIEW: Table (Shows only on medium screens and up) -->
        <div class="hidden md:block bg-white rounded-3xl border border-slate-200/60 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.03)] overflow-hidden">
          <div class="overflow-x-auto w-full">
            <table class="w-full text-left border-collapse min-w-[800px]">
              <thead>
                <tr class="bg-slate-50/80 text-slate-400 text-xs uppercase tracking-wider font-bold border-b border-slate-200">
                  <th class="px-6 py-5 w-24">เลขที่</th>
                  <th class="px-6 py-5">ชื่อนักเรียน</th>
                  <th class="px-6 py-5 text-center">จำนวนที่ค้าง (บิล)</th>
                  <th class="px-6 py-5 text-right">ยอดรวม (฿)</th>
                  <th class="px-6 py-5 text-right pe-8">จัดการ</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100">
                <tr v-if="debtors.length === 0">
                  <td colspan="5" class="px-6 py-20 text-center">
                    <div class="inline-block w-16 h-16 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-3 shadow-inner">
                      <span class="text-3xl">🎉</span>
                    </div>
                    <p class="text-emerald-600 font-extrabold text-lg">ไม่มีใครติดหนี้ห้องเลย! (รวยมาก)</p>
                  </td>
                </tr>
                <tr v-for="d in debtors" :key="d.student_id" class="hover:bg-rose-50/30 transition-colors group">
                  <td class="px-6 py-5 font-bold text-slate-400">#{{ d.student_no }}</td>
                  <td class="px-6 py-5 font-extrabold text-slate-800 text-base">{{ d.student_name }}</td>
                  <td class="px-6 py-5 text-center">
                    <span class="inline-flex items-center justify-center bg-rose-50 border border-rose-100 text-rose-600 px-3 py-1 rounded-full text-xs font-bold min-w-[80px]">
                      {{ d.overdue_count }} รายการ
                    </span>
                  </td>
                  <td class="px-6 py-5 text-right whitespace-nowrap font-black text-rose-600 text-lg">
                    ฿{{ formatNumber(d.total_pending_amount) }}
                  </td>
                  <td class="px-6 py-5 text-right pe-8">
                    <button 
                      v-if="isAdmin"
                      @click="handleClearDebt(d)"
                      class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-5 rounded-xl shadow-md shadow-blue-600/20 transition-all text-sm flex items-center gap-2 ml-auto"
                    >
                      <i class="bi bi-wallet2"></i> เคลียร์หนี้
                    </button>
                    <span v-else class="text-xs text-slate-400 font-medium bg-slate-50 px-3 py-2 rounded-lg border border-slate-100 inline-block">
                      <i class="bi bi-lock"></i> รอแอดมิน
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- MODAL BATCH PAY (Premium Bottom Sheet for Mobile, Center Modal for Desktop) -->
      <div v-if="isModalOpen && isAdmin" class="fixed inset-0 z-50 flex items-end md:items-center justify-center p-0 md:p-4 bg-slate-900/40 backdrop-blur-sm transition-opacity">
        <div class="bg-white w-full max-w-2xl rounded-t-3xl md:rounded-3xl shadow-2xl flex flex-col max-h-[90vh] md:max-h-[85vh] animate-in slide-in-from-bottom-10 md:zoom-in-95 duration-300">
          
          <!-- Modal Header (Sticky) -->
          <div class="px-6 py-5 border-b border-slate-100 flex justify-between items-center bg-white rounded-t-3xl md:rounded-t-3xl shrink-0">
            <div>
              <h3 class="text-lg md:text-xl font-extrabold text-slate-800 tracking-tight">
                บันทึกรับเงินรวบยอด
              </h3>
              <p class="text-sm font-bold text-blue-600 mt-0.5"><i class="bi bi-person-fill"></i> {{ selectedStudent?.name }}</p>
            </div>
            <button @click="isModalOpen = false" class="w-10 h-10 bg-slate-50 hover:bg-slate-100 rounded-full flex items-center justify-center text-slate-500 transition-colors">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>

          <!-- Modal Body (Scrollable) -->
          <div class="p-4 md:p-6 overflow-y-auto flex-1 bg-slate-50/50">
            <div v-if="isLoadingDebts" class="flex justify-center py-10">
              <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
            <div v-else class="space-y-3">
              <p class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 ms-1">เลือกรายการบิลที่ต้องการชำระ</p>
              
              <label 
                v-for="debt in studentDebts" 
                :key="debt.payment_id"
                :class="[
                  'flex flex-row items-center gap-3 md:gap-4 p-4 rounded-2xl border transition-all cursor-pointer shadow-sm',
                  selectedPaymentIds.includes(debt.payment_id) ? 'bg-emerald-50/50 border-emerald-300 shadow-emerald-500/5' : 'bg-white border-slate-200 hover:border-slate-300'
                ]"
              >
                <!-- Checkbox -->
                <div class="flex-shrink-0">
                  <div :class="[
                    'w-6 h-6 rounded-lg border-2 flex items-center justify-center transition-colors',
                    selectedPaymentIds.includes(debt.payment_id) ? 'bg-emerald-500 border-emerald-500' : 'bg-white border-slate-300'
                  ]">
                    <i v-if="selectedPaymentIds.includes(debt.payment_id)" class="bi bi-check-lg text-white font-black text-sm"></i>
                  </div>
                  <input 
                    type="checkbox" 
                    :value="debt.payment_id" 
                    v-model="selectedPaymentIds"
                    class="hidden"
                  >
                </div>

                <!-- Debt Detail -->
                <div class="flex-1 min-w-0">
                  <h4 class="font-bold text-slate-800 text-sm truncate">{{ debt.title }}</h4>
                  <p class="text-rose-500 text-[11px] font-bold mt-0.5">ยอดค้าง: ฿{{ formatNumber(debt.amount) }}</p>
                </div>

                <!-- Amount Input -->
                <div class="w-24 md:w-32 flex-shrink-0 relative">
                  <div class="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
                    <span class="text-slate-400 text-sm font-bold">฿</span>
                  </div>
                  <input 
                    type="number" 
                    v-model="payAmounts[debt.payment_id]" 
                    :disabled="!selectedPaymentIds.includes(debt.payment_id)"
                    class="w-full bg-white border border-slate-200 rounded-xl py-2 pl-7 pr-3 outline-none text-right text-sm font-bold text-slate-800 focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 disabled:bg-slate-50 disabled:text-slate-400 transition-all shadow-inner"
                  >
                </div>
              </label>
            </div>

            <!-- Settings Inputs -->
            <div class="mt-6 p-5 bg-white rounded-2xl border border-slate-200 shadow-sm">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label class="block text-[11px] font-bold text-slate-400 mb-1.5 uppercase tracking-wider">รับเข้ากระเป๋า</label>
                  <select v-model="paidToAccountId" class="w-full bg-slate-50 border border-slate-200 py-2.5 px-3 rounded-xl text-sm font-bold text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/50 transition-all">
                    <option v-for="acc in accounts" :key="acc.id" :value="acc.id.toString()">{{ acc.account_name }}</option>
                  </select>
                </div>
                <div>
                  <label class="block text-[11px] font-bold text-slate-400 mb-1.5 uppercase tracking-wider">URL รูปสลิป (ถ้ามี)</label>
                  <input v-model="slipImageUrl" type="url" placeholder="https://..." class="w-full bg-slate-50 border border-slate-200 py-2.5 px-3 rounded-xl text-sm outline-none focus:ring-2 focus:ring-blue-500/50 transition-all">
                </div>
              </div>
            </div>
          </div>

          <!-- Modal Footer (Sticky) -->
          <div class="p-4 md:p-6 bg-white border-t border-slate-100 shadow-[0_-10px_20px_-10px_rgba(0,0,0,0.05)] shrink-0">
            <div class="flex flex-col sm:flex-row justify-between items-center gap-4">
              <div class="w-full sm:w-auto flex justify-between sm:block items-center">
                <span class="text-[11px] font-bold uppercase tracking-wider block text-slate-400">ยอดรวมที่เลือกชำระ</span>
                <span class="text-2xl font-black text-rose-600 tracking-tight">฿{{ formatNumber(totalSelectedAmount) }}</span>
              </div>
              <button 
                @click="handleBatchPay"
                class="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-700 active:scale-95 text-white font-bold py-3.5 px-8 rounded-2xl shadow-lg shadow-emerald-600/30 transition-all"
              >
                <i class="bi bi-check-circle-fill me-1"></i> ยืนยันการรับเงิน
              </button>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
/* ซ่อนปุ่มลูกศรในช่อง Input Number ให้ดูคลีนๆ แบบแอปธนาคาร */
input[type=number]::-webkit-inner-spin-button, 
input[type=number]::-webkit-outer-spin-button { 
  -webkit-appearance: none; 
  margin: 0; 
}
input[type=number] {
  -moz-appearance: textfield;
}

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