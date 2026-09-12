<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth'; // เพิ่ม import authStore
import { FinanceService } from '@/services/finance';
import type { Account, Category } from '@/types/finance';
import Swal from 'sweetalert2';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

const authStore = useAuthStore();

// ดึงค่าจาก Store แทน Mock Data เดิม
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;
const isAdmin = computed(() => authStore.isAdmin); // ดึง isAdmin มาใช้งาน

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const isLoading = ref(true);

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false);

const fetchSettingsData = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    const [accRes, catRes] = await Promise.all([
      FinanceService.getAccounts(currentServerId),
      FinanceService.getCategories(currentServerId)
    ]);
    accounts.value = accRes;
    categories.value = catRes;
  } catch (error: unknown) {
    hasError.value = true;
    Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'โหลดข้อมูลล้มเหลว', 'error');
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
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
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
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'เพิ่มกระเป๋าเงินไม่สำเร็จ', 'error');
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
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
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
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'แก้ไขกระเป๋าเงินไม่สำเร็จ', 'error');
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
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบทันที',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.deleteAccount(currentServerId, id);
      Swal.fire({ icon: 'success', title: 'ลบสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'ลบกระเป๋าเงินไม่สำเร็จ', 'error');
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
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
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
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'เพิ่มหมวดหมู่ไม่สำเร็จ', 'error');
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
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
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
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'แก้ไขหมวดหมู่ไม่สำเร็จ', 'error');
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
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบทันที',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.deleteCategory(currentServerId, id);
      Swal.fire({ icon: 'success', title: 'ลบสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: unknown) {
      Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'ลบหมวดหมู่ไม่สำเร็จ', 'error');
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
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Finance Settings"
      title="ตั้งค่าระบบการเงิน"
      description="จัดการกระเป๋าเงินห้องและหมวดหมู่สำหรับบันทึกรายรับ/รายจ่าย"
    >
      <template #actions>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
      </template>
    </PageHeader>

    <!-- สถานะโหลด / ผิดพลาด -->
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />
    <StateBlock v-else-if="hasError" variant="error" @retry="fetchSettingsData" />

    <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <!-- กระเป๋าเงินห้อง -->
      <div class="page-card h-fit overflow-hidden">
        <div
          class="flex items-center justify-between gap-3 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5"
        >
          <h2 class="section-title flex min-w-0 items-center gap-2">
            <i class="bi bi-wallet2 text-brand-700" aria-hidden="true"></i>
            <span class="truncate">กระเป๋าเงินห้อง</span>
          </h2>
          <button v-if="isAdmin" class="btn-primary shrink-0" @click="handleAddAccount">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่มบัญชี
          </button>
        </div>

        <div class="p-4 sm:p-5">
          <StateBlock
            v-if="accounts.length === 0"
            variant="empty"
            title="ยังไม่มีกระเป๋าเงิน"
            hint="เพิ่มกระเป๋าเงินใบแรกเพื่อเริ่มบันทึกรายรับ/รายจ่าย"
          />

          <div v-else class="space-y-2.5">
            <div
              v-for="acc in accounts"
              :key="acc.id"
              class="group flex items-center justify-between gap-3 rounded-xl border border-stone-200 p-3 transition-colors hover:border-stone-300"
            >
              <div class="min-w-0">
                <p class="truncate font-bold text-stone-900">{{ acc.account_name }}</p>
                <p class="mt-0.5 text-sm text-stone-500">
                  คงเหลือ
                  <span class="num font-bold text-brand-700">฿ {{ formatNumber(acc.balance) }}</span>
                </p>
              </div>

              <div
                v-if="isAdmin"
                class="flex shrink-0 items-center gap-1 md:opacity-0 md:transition-opacity md:group-hover:opacity-100 md:focus-within:opacity-100"
              >
                <button
                  class="flex h-11 w-11 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-brand-700"
                  title="แก้ไข"
                  aria-label="แก้ไขกระเป๋าเงิน"
                  @click="handleEditAccount(acc)"
                >
                  <i class="bi bi-pencil-square" aria-hidden="true"></i>
                </button>
                <button
                  class="flex h-11 w-11 items-center justify-center rounded-lg text-red-600 transition-colors hover:bg-red-50"
                  title="ลบ"
                  aria-label="ลบกระเป๋าเงิน"
                  @click="handleDeleteAccount(acc.id)"
                >
                  <i class="bi bi-trash" aria-hidden="true"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- หมวดหมู่รายการ -->
      <div class="page-card h-fit overflow-hidden">
        <div
          class="flex items-center justify-between gap-3 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5"
        >
          <h2 class="section-title flex min-w-0 items-center gap-2">
            <i class="bi bi-tags text-brand-700" aria-hidden="true"></i>
            <span class="truncate">หมวดหมู่รายการ</span>
          </h2>
          <button v-if="isAdmin" class="btn-ghost-ui shrink-0" @click="handleAddCategory">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่มหมวดหมู่
          </button>
        </div>

        <div class="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 sm:p-5">
          <!-- รายรับ -->
          <div class="min-w-0">
            <div class="mb-3 flex items-center justify-between gap-2 border-b border-stone-100 pb-2">
              <span class="chip bg-emerald-50 text-emerald-700">
                <i class="bi bi-arrow-down-left" aria-hidden="true"></i>
                รายรับ
              </span>
              <span class="num text-xs font-bold text-stone-400">{{ incomeCategories.length }}</span>
            </div>

            <p v-if="incomeCategories.length === 0" class="py-3 text-center text-xs text-stone-400">
              ยังไม่มีหมวดหมู่รายรับ
            </p>

            <div v-else class="space-y-2">
              <div
                v-for="cat in incomeCategories"
                :key="cat.id"
                class="group flex items-center justify-between gap-2 rounded-xl border border-stone-200 px-3 py-1.5"
              >
                <span class="truncate text-sm font-bold text-stone-700">{{ cat.category_name }}</span>
                <div v-if="isAdmin" class="flex shrink-0 items-center gap-0.5">
                  <button
                    class="flex h-10 w-10 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-brand-700"
                    title="แก้ไข"
                    aria-label="แก้ไขหมวดหมู่"
                    @click.stop="handleEditCategory(cat)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <button
                    class="flex h-10 w-10 items-center justify-center rounded-lg text-red-600 transition-colors hover:bg-red-50"
                    title="ลบ"
                    aria-label="ลบหมวดหมู่"
                    @click.stop="handleDeleteCategory(cat.id)"
                  >
                    <i class="bi bi-x-lg" aria-hidden="true"></i>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- รายจ่าย -->
          <div class="min-w-0">
            <div class="mb-3 flex items-center justify-between gap-2 border-b border-stone-100 pb-2">
              <span class="chip bg-red-50 text-red-700">
                <i class="bi bi-arrow-up-right" aria-hidden="true"></i>
                รายจ่าย
              </span>
              <span class="num text-xs font-bold text-stone-400">{{ expenseCategories.length }}</span>
            </div>

            <p v-if="expenseCategories.length === 0" class="py-3 text-center text-xs text-stone-400">
              ยังไม่มีหมวดหมู่รายจ่าย
            </p>

            <div v-else class="space-y-2">
              <div
                v-for="cat in expenseCategories"
                :key="cat.id"
                class="group flex items-center justify-between gap-2 rounded-xl border border-stone-200 px-3 py-1.5"
              >
                <span class="truncate text-sm font-bold text-stone-700">{{ cat.category_name }}</span>
                <div v-if="isAdmin" class="flex shrink-0 items-center gap-0.5">
                  <button
                    class="flex h-10 w-10 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-brand-700"
                    title="แก้ไข"
                    aria-label="แก้ไขหมวดหมู่"
                    @click.stop="handleEditCategory(cat)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <button
                    class="flex h-10 w-10 items-center justify-center rounded-lg text-red-600 transition-colors hover:bg-red-50"
                    title="ลบ"
                    aria-label="ลบหมวดหมู่"
                    @click.stop="handleDeleteCategory(cat.id)"
                  >
                    <i class="bi bi-x-lg" aria-hidden="true"></i>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
