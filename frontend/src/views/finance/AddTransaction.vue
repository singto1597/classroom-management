<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { FinanceService } from '@/services/finance';
import type { Account, Category } from '@/types/finance';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const router = useRouter();

const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const activeTab = ref<'expense' | 'income' | 'transfer'>('expense');
const isLoading = ref(true);
const isSubmitting = ref(false);

// Form States
const form = ref({
  amount: 0,
  account_id: '',
  category_id: '',
  description: '',
  from_account_id: '',
  to_account_id: '',
  slip_image_url: ''
});

const fetchInitData = async () => {
  isLoading.value = true;
  try {
    const [accRes, catRes] = await Promise.all([
      FinanceService.getAccounts(currentServerId),
      FinanceService.getCategories(currentServerId)
    ]);
    accounts.value = accRes;
    categories.value = catRes;
  } catch (error: any) {
    Swal.fire('Error', 'ไม่สามารถโหลดข้อมูลเริ่มต้นได้', 'error');
  } finally {
    isLoading.value = false;
  }
};

const filteredCategories = computed(() => {
  if (activeTab.value === 'transfer') return [];
  return categories.value.filter(c => c.category_type === activeTab.value);
});

const handleSubmit = async () => {
  if (activeTab.value === 'transfer') {
    if (form.value.from_account_id === form.value.to_account_id) {
      return Swal.fire('ห๊ะ!', 'จะโอนเข้ากระเป๋าตัวเองทำไมครับพี่!', 'warning');
    }
  }

  isSubmitting.value = true;
  try {
    if (activeTab.value === 'transfer') {
      await FinanceService.transferMoney(currentServerId, {
        from_account_id: Number(form.value.from_account_id),
        to_account_id: Number(form.value.to_account_id),
        amount: form.value.amount,
        description: form.value.description,
        user_name: currentUserName
      });
    } else {
      await FinanceService.addTransaction(currentServerId, {
        account_id: Number(form.value.account_id),
        category_id: Number(form.value.category_id),
        amount: form.value.amount,
        description: form.value.description,
        transaction_type: activeTab.value,
        user_name: currentUserName
      });
    }

    await Swal.fire({
      icon: 'success',
      title: 'บันทึกสำเร็จ!',
      text: 'รายการของคุณถูกบันทึกเรียบร้อยแล้ว',
      timer: 1500,
      showConfirmButton: false
    });
    router.push('/finance/transactions');
  } catch (error: any) {
    Swal.fire('พัง!', error.message || 'บันทึกรายการไม่สำเร็จ', 'error');
  } finally {
    isSubmitting.value = false;
  }
};

onMounted(() => {
  fetchInitData();
});
</script>

<template>
  <div class="p-4 md:p-8 max-w-2xl mx-auto">
    <div class="flex justify-between items-center mb-8">
      <div class="flex items-center gap-4">
        <RouterLink 
          to="/finance/transactions"
          class="bg-gray-100 hover:bg-gray-200 text-gray-600 p-2 rounded-xl transition shadow-sm group"
          title="กลับหน้าประวัติ"
        >
          <i class="bi bi-arrow-left text-xl"></i>
        </RouterLink>
        <h1 class="text-2xl md:text-3xl font-bold text-gray-800">บันทึกรายการเงิน</h1>
      </div>
    </div>

    <!-- Tabs -->
    <div class="bg-gray-100 p-1 rounded-2xl flex mb-8">
      <button 
        v-for="tab in ['expense', 'income', 'transfer']" 
        :key="tab"
        @click="activeTab = tab as any"
        :class="[
          'flex-1 py-2.5 rounded-xl font-bold transition-all',
          activeTab === tab 
            ? 'bg-white shadow-sm text-gray-800' 
            : 'text-gray-400 hover:text-gray-600'
        ]"
      >
        <span v-if="tab === 'expense'">🔴 รายจ่าย</span>
        <span v-if="tab === 'income'">🟢 รายรับ</span>
        <span v-if="tab === 'transfer'">🔵 โอนเงิน</span>
      </button>
    </div>

    <!-- Form Section -->
    <div v-if="isLoading" class="flex flex-col items-center justify-center py-20 bg-white rounded-3xl border border-gray-100 shadow-sm">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>

    <form v-else @submit.prevent="handleSubmit" class="bg-white rounded-3xl border border-gray-100 shadow-sm p-6 md:p-8 space-y-6">
      
      <!-- Amount Input -->
      <div>
        <label class="block text-sm font-bold text-gray-400 mb-2 uppercase">จำนวนเงิน (฿)</label>
        <input 
          v-model="form.amount" 
          type="number" 
          step="0.01" 
          required 
          class="w-full text-right text-3xl font-extrabold text-gray-800 bg-gray-50 border border-gray-100 rounded-2xl p-4 focus:ring-4 focus:ring-blue-100 outline-none transition"
          placeholder="0.00"
        >
      </div>

      <!-- Account Selection (Non-Transfer) -->
      <div v-if="activeTab !== 'transfer'">
        <label class="block text-sm font-bold text-gray-400 mb-2 uppercase">บัญชี/กระเป๋าเงิน</label>
        <select 
          v-model="form.account_id" 
          required 
          class="w-full bg-gray-50 border border-gray-100 p-4 rounded-2xl focus:ring-4 focus:ring-blue-100 outline-none transition font-bold"
        >
          <option value="" disabled>-- เลือกบัญชี --</option>
          <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
            {{ acc.account_name }} (เหลือ ฿{{ new Intl.NumberFormat().format(acc.balance) }})
          </option>
        </select>
      </div>

      <!-- Transfer Accounts Selection -->
      <div v-if="activeTab === 'transfer'" class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm font-bold text-rose-500 mb-2 uppercase">โอนจาก</label>
          <select 
            v-model="form.from_account_id" 
            required 
            class="w-full bg-gray-50 border border-gray-100 p-4 rounded-2xl focus:ring-4 focus:ring-rose-100 outline-none transition font-bold"
          >
            <option value="" disabled>-- ต้นทาง --</option>
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.account_name }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-bold text-emerald-500 mb-2 uppercase">เข้าสู่</label>
          <select 
            v-model="form.to_account_id" 
            required 
            class="w-full bg-gray-50 border border-gray-100 p-4 rounded-2xl focus:ring-4 focus:ring-emerald-100 outline-none transition font-bold"
          >
            <option value="" disabled>-- ปลายทาง --</option>
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.account_name }}</option>
          </select>
        </div>
      </div>

      <!-- Category Selection (Non-Transfer) -->
      <div v-if="activeTab !== 'transfer'">
        <label class="block text-sm font-bold text-gray-400 mb-2 uppercase">หมวดหมู่</label>
        <select 
          v-model="form.category_id" 
          required 
          class="w-full bg-gray-50 border border-gray-100 p-4 rounded-2xl focus:ring-4 focus:ring-blue-100 outline-none transition font-bold"
        >
          <option value="" disabled>-- เลือกหมวดหมู่ --</option>
          <option v-for="cat in filteredCategories" :key="cat.id" :value="cat.id">
            {{ cat.category_name }}
          </option>
        </select>
      </div>

      <!-- Description Input -->
      <div>
        <label class="block text-sm font-bold text-gray-400 mb-2 uppercase">รายละเอียด (บันทึกช่วยจำ)</label>
        <input 
          v-model="form.description" 
          type="text" 
          required 
          class="w-full bg-gray-50 border border-gray-100 p-4 rounded-2xl focus:ring-4 focus:ring-blue-100 outline-none transition"
          placeholder="เช่น ซื้อเครื่องเขียน, ค่าขนมเพื่อน..."
        >
      </div>

      <!-- Slip Image (Optional) -->
      <div v-if="activeTab === 'transfer'">
        <label class="block text-sm font-bold text-gray-400 mb-2 uppercase">URL รูปสลิปหลักฐาน (ถ้ามี)</label>
        <input 
          v-model="form.slip_image_url" 
          type="url" 
          class="w-full bg-gray-50 border border-gray-100 p-4 rounded-2xl focus:ring-4 focus:ring-blue-100 outline-none transition"
          placeholder="https://..."
        >
      </div>

      <!-- Submit Button -->
      <button 
        type="submit" 
        :disabled="isSubmitting"
        :class="[
          'w-full py-4 rounded-2xl font-bold text-white shadow-lg transition-all flex items-center justify-center gap-2',
          activeTab === 'expense' ? 'bg-rose-600 hover:bg-rose-700' : 
          activeTab === 'income' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-blue-600 hover:bg-blue-700',
          isSubmitting ? 'opacity-50 cursor-not-allowed' : ''
        ]"
      >
        <span v-if="isSubmitting" class="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
        <span v-else>
          {{ activeTab === 'expense' ? 'บันทึกรายจ่าย' : activeTab === 'income' ? 'บันทึกรายรับ' : 'ยืนยันการโอนเงิน' }}
        </span>
      </button>

    </form>
  </div>
</template>

