<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth'; // เพิ่ม import authStore
import { FinanceService } from '@/services/finance';
import type { Account, Category } from '@/types/finance';
import Swal from 'sweetalert2';

const authStore = useAuthStore();

// ดึงค่าจาก Store แทน Mock Data เดิม
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;
const isAdmin = computed(() => authStore.isAdmin); // ดึง isAdmin มาใช้งาน

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const isLoading = ref(true);

const fetchSettingsData = async () => {
  isLoading.value = true;
  try {
    const [accRes, catRes] = await Promise.all([
      FinanceService.getAccounts(currentServerId),
      FinanceService.getCategories(currentServerId)
    ]);
    accounts.value = accRes;
    categories.value = catRes;
  } catch (error: any) {
    Swal.fire('Error', error.message || 'โหลดข้อมูลล้มเหลว', 'error');
  } finally {
    isLoading.value = false;
  }
};

const incomeCategories = computed(() => categories.value.filter(c => c.category_type === 'income'));
const expenseCategories = computed(() => categories.value.filter(c => c.category_type === 'expense'));

// --- Account Actions ---

const handleAddAccount = async () => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');

  const { value: formValues } = await Swal.fire({
    title: 'เพิ่มกระเป๋าเงินใหม่',
    html:
      '<input id="swal-input1" class="swal2-input" placeholder="ชื่อกระเป๋าเงิน (เช่น เงินสด, ธนาคาร)">' +
      '<input id="swal-input2" type="number" class="swal2-input" placeholder="เงินตั้งต้น (฿)" value="0">',
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonText: 'บันทึกข้อมูล',
    cancelButtonText: 'ยกเลิก',
    preConfirm: () => {
      const name = (document.getElementById('swal-input1') as HTMLInputElement).value;
      const balance = (document.getElementById('swal-input2') as HTMLInputElement).value;
      if (!name) {
        Swal.showValidationMessage('กรุณากรอกชื่อกระเป๋าเงิน');
        return false;
      }
      return { account_name: name, initial_balance: parseFloat(balance) };
    }
  });

  if (formValues) {
    try {
      await FinanceService.createAccount(currentServerId, { ...formValues, user_name: currentUserName });
      Swal.fire({ icon: 'success', title: 'เพิ่มสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: any) {
      Swal.fire('Error', error.message, 'error');
    }
  }
};

const handleEditAccount = async (account: Account) => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');

  const { value: name } = await Swal.fire({
    title: 'แก้ไขชื่อกระเป๋าเงิน',
    input: 'text',
    inputValue: account.account_name,
    showCancelButton: true,
    confirmButtonText: 'บันทึก',
    cancelButtonText: 'ยกเลิก',
    inputValidator: (value) => {
      if (!value) return 'กรุณากรอกชื่อกระเป๋าเงิน';
      return null;
    }
  });

  if (name) {
    try {
      await FinanceService.updateAccount(currentServerId, account.id, name, currentUserName);
      Swal.fire({ icon: 'success', title: 'แก้ไขสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: any) {
      Swal.fire('Error', error.message, 'error');
    }
  }
};

const handleDeleteAccount = async (id: number) => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    text: 'หากลบแล้วข้อมูลประวัติที่เกี่ยวข้องอาจได้รับผลกระทบ',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    confirmButtonText: 'ลบทันที',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.deleteAccount(currentServerId, id);
      Swal.fire({ icon: 'success', title: 'ลบสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: any) {
      Swal.fire('Error', error.message, 'error');
    }
  }
};

// --- Category Actions ---

const handleAddCategory = async () => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');

  const { value: formValues } = await Swal.fire({
    title: 'เพิ่มหมวดหมู่ใหม่',
    html:
      '<select id="swal-type" class="swal2-input">' +
      '<option value="income">🟢 รายรับ</option>' +
      '<option value="expense">🔴 รายจ่าย</option>' +
      '</select>' +
      '<input id="swal-name" class="swal2-input" placeholder="ชื่อหมวดหมู่ (เช่น ค่าอุปกรณ์, ค่าพาน)">',
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonText: 'เพิ่มหมวดหมู่',
    cancelButtonText: 'ยกเลิก',
    preConfirm: () => {
      const type = (document.getElementById('swal-type') as HTMLSelectElement).value as 'income' | 'expense';
      const name = (document.getElementById('swal-name') as HTMLInputElement).value;
      if (!name) {
        Swal.showValidationMessage('กรุณากรอกชื่อหมวดหมู่');
        return false;
      }
      return { category_name: name, category_type: type };
    }
  });

  if (formValues) {
    try {
      await FinanceService.createCategory(currentServerId, { ...formValues, user_name: currentUserName });
      Swal.fire({ icon: 'success', title: 'เพิ่มสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: any) {
      Swal.fire('Error', error.message, 'error');
    }
  }
};

const handleEditCategory = async (category: Category) => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');

  const { value: name } = await Swal.fire({
    title: 'แก้ไขชื่อหมวดหมู่',
    input: 'text',
    inputValue: category.category_name,
    showCancelButton: true,
    confirmButtonText: 'บันทึก',
    cancelButtonText: 'ยกเลิก',
    inputValidator: (value) => {
      if (!value) return 'กรุณากรอกชื่อหมวดหมู่';
      return null;
    }
  });

  if (name) {
    try {
      await FinanceService.updateCategory(currentServerId, category.id, name, currentUserName);
      Swal.fire({ icon: 'success', title: 'แก้ไขสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: any) {
      Swal.fire('Error', error.message, 'error');
    }
  }
};

const handleDeleteCategory = async (id: number) => {
  if (!isAdmin.value) return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');

  const result = await Swal.fire({
    title: 'ลบหมวดหมู่?',
    text: 'การลบหมวดหมู่อาจส่งผลต่อการจัดกลุ่มรายงาน',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    confirmButtonText: 'ลบทันที',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.deleteCategory(currentServerId, id);
      Swal.fire({ icon: 'success', title: 'ลบสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: any) {
      Swal.fire('Error', error.message, 'error');
    }
  }
};

onMounted(() => {
  fetchSettingsData();
});

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};
</script>

<template>
  <div class="p-4 md:p-8 max-w-6xl mx-auto">
    <div class="mb-8 flex items-center gap-4">
      <RouterLink 
        to="/finance"
        class="bg-gray-100 hover:bg-gray-200 text-gray-600 p-2 rounded-xl transition shadow-sm group"
        title="กลับหน้าภาพรวม"
      >
        <i class="bi bi-arrow-left text-xl"></i>
      </RouterLink>
      <div>
        <h1 class="text-2xl md:text-3xl font-bold text-gray-800 flex items-center gap-2">
          ⚙️ ตั้งค่าระบบการเงิน
        </h1>
        <p class="text-gray-500 mt-1">จัดการกระเป๋าเงินห้องและหมวดหมู่สำหรับบันทึกรายรับ/รายจ่าย</p>
      </div>
    </div>

    <div v-if="isLoading" class="flex flex-col items-center justify-center py-20">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>

    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <div class="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden h-fit">
        <div class="p-6 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
          <h3 class="text-xl font-bold text-gray-800 flex items-center gap-2">
            <i class="bi bi-wallet2 text-blue-500"></i> กระเป๋าเงินห้อง
          </h3>
          <button 
            v-if="isAdmin"
            @click="handleAddAccount"
            class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded-xl shadow-sm transition flex items-center gap-2 text-sm"
          >
            <i class="bi bi-plus-circle"></i> เพิ่มบัญชี
          </button>
        </div>
        
        <div class="p-6">
          <div v-if="accounts.length === 0" class="text-center py-10 text-gray-400">
            ยังไม่มีกระเป๋าเงิน
          </div>
          <div v-else class="space-y-3">
            <div 
              v-for="acc in accounts" 
              :key="acc.id" 
              class="flex justify-between items-center p-4 rounded-2xl border border-gray-50 bg-white hover:border-blue-100 hover:shadow-md transition-all group"
            >
              <div>
                <h4 class="font-bold text-gray-800">{{ acc.account_name }}</h4>
                <p class="text-gray-500 text-sm">คงเหลือ: <span class="text-blue-600 font-bold">฿ {{ formatNumber(acc.balance) }}</span></p>
              </div>
              <div v-if="isAdmin" class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button @click="handleEditAccount(acc)" class="p-2 text-blue-600 hover:bg-blue-50 rounded-lg transition" title="แก้ไข">
                  <i class="bi bi-pencil-square"></i>
                </button>
                <button @click="handleDeleteAccount(acc.id)" class="p-2 text-rose-600 hover:bg-rose-50 rounded-lg transition" title="ลบ">
                  <i class="bi bi-trash"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
        <div class="p-6 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
          <h3 class="text-xl font-bold text-gray-800 flex items-center gap-2">
            <i class="bi bi-tags text-emerald-500"></i> หมวดหมู่รายการ
          </h3>
          <button 
            v-if="isAdmin"
            @click="handleAddCategory"
            class="bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2 px-4 rounded-xl shadow-sm transition flex items-center gap-2 text-sm"
          >
            <i class="bi bi-plus-circle"></i> เพิ่มหมวดหมู่
          </button>
        </div>

        <div class="p-6">
          <div class="grid grid-cols-2 gap-6">
            <div>
              <h5 class="font-bold text-emerald-600 mb-4 flex items-center gap-2 border-b border-emerald-50 pb-2">
                🟢 รายรับ
              </h5>
              <div v-if="incomeCategories.length === 0" class="text-center py-4 text-gray-300 text-xs italic">ไม่มีข้อมูล</div>
              <div class="flex flex-wrap gap-2">
                <div 
                  v-for="cat in incomeCategories" 
                  :key="cat.id"
                  class="bg-emerald-50 text-emerald-700 border border-emerald-100 py-1.5 px-3 rounded-full text-sm font-semibold flex items-center gap-2 group hover:bg-emerald-600 hover:text-white transition-all"
                >
                  {{ cat.category_name }}
                  <div v-if="isAdmin" class="flex gap-1 overflow-hidden w-0 group-hover:w-10 transition-all duration-300">
                    <i @click.stop="handleEditCategory(cat)" class="bi bi-pencil text-[10px] cursor-pointer hover:scale-125 transition-transform"></i>
                    <i @click.stop="handleDeleteCategory(cat.id)" class="bi bi-x-lg text-[10px] cursor-pointer hover:scale-125 transition-transform"></i>
                  </div>
                </div>
              </div>
            </div>

            <div>
              <h5 class="font-bold text-rose-600 mb-4 flex items-center gap-2 border-b border-rose-50 pb-2">
                🔴 รายจ่าย
              </h5>
              <div v-if="expenseCategories.length === 0" class="text-center py-4 text-gray-300 text-xs italic">ไม่มีข้อมูล</div>
              <div class="flex flex-wrap gap-2">
                <div 
                  v-for="cat in expenseCategories" 
                  :key="cat.id"
                  class="bg-rose-50 text-rose-700 border border-rose-100 py-1.5 px-3 rounded-full text-sm font-semibold flex items-center gap-2 group hover:bg-rose-600 hover:text-white transition-all"
                >
                  {{ cat.category_name }}
                  <div v-if="isAdmin" class="flex gap-1 overflow-hidden w-0 group-hover:w-10 transition-all duration-300">
                    <i @click.stop="handleEditCategory(cat)" class="bi bi-pencil text-[10px] cursor-pointer hover:scale-125 transition-transform"></i>
                    <i @click.stop="handleDeleteCategory(cat.id)" class="bi bi-x-lg text-[10px] cursor-pointer hover:scale-125 transition-transform"></i>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.swal2-input, .swal2-select {
  border-radius: 1rem !important;
  font-family: 'Sarabun', sans-serif !important;
}
</style>