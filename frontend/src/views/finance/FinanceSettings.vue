<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth'; // เพิ่ม import authStore
import { FinanceService } from '@/services/finance';
import type { Account, AccountKind, Category } from '@/types/finance';
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
const errorMessage = ref('');

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
    errorMessage.value = error instanceof Error ? error.message : 'โหลดข้อมูลการตั้งค่าไม่สำเร็จ';
    hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

const incomeCategories = computed(() => categories.value.filter(c => c.category_type === 'income'));
const expenseCategories = computed(() => categories.value.filter(c => c.category_type === 'expense'));

// --- Account Actions ---

/** 🏦 ฉลากช่องทางจ่าย — ตรงกับ `chk_finance_account_kind` ฝั่ง backend */
const ACCOUNT_KIND_LABELS: Record<AccountKind, string> = {
  cash: 'เงินสด',
  transfer: 'โอนเข้าบัญชี'
};

/**
 * 🔒 Escape ค่าก่อนยัดลง attribute ของ `html:` ใน Swal
 *
 * 🔴 ชื่อกระเป๋า/ชื่อบัญชีเป็น **ข้อความที่ผู้ใช้พิมพ์เอง** และถูก interpolate ลง HTML
 *    ตรง ๆ ⇒ เครื่องหมายคำพูดตัวเดียวในชื่อ (เช่น `กระเป๋า "ห้อง 1"`) จะหลุดออกจาก
 *    `value="…"` แล้วกลายเป็นมาร์กอัป — พังอย่างน้อยที่สุดคือฟอร์มเพี้ยน
 *    (ของเดิมไม่ต้องระวังเพราะไม่ได้ interpolate ค่าเดิมกลับเข้าไปในฟอร์ม)
 */
const escapeAttr = (value: string | null | undefined): string =>
  (value ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * 🧩 HTML ของฟอร์ม "ช่องทางจ่าย" ที่ใช้ทั้งตอนเพิ่มและตอนแก้ไข
 *
 * ช่องธนาคารซ่อนไว้จนกว่าจะเลือก "โอนเข้าบัญชี" — แสดงตลอดเวลาจะทำให้คนที่ใช้เงินสด
 * ต้องอ่านช่องที่ไม่เกี่ยวกับตัวเอง 3 ช่องทุกครั้งที่เปิดฟอร์ม
 */
const channelFieldsHtml = (
  kind: AccountKind,
  bank: { bank_name?: string | null; bank_account_no?: string | null; bank_account_name?: string | null } = {}
): string => `
  <select id="swal-account-kind" class="swal2-select">
    <option value="cash"${kind === 'cash' ? ' selected' : ''}>เงินสด</option>
    <option value="transfer"${kind === 'transfer' ? ' selected' : ''}>โอนเข้าบัญชี</option>
  </select>
  <div id="swal-bank-fields" style="${kind === 'transfer' ? '' : 'display:none'}">
    <input id="swal-bank-name" class="swal2-input" placeholder="ธนาคาร (เช่น ธ.ไทยพาณิชย์)" value="${escapeAttr(bank.bank_name)}">
    <input id="swal-bank-no" class="swal2-input" placeholder="เลขที่บัญชี" value="${escapeAttr(bank.bank_account_no)}">
    <input id="swal-bank-owner" class="swal2-input" placeholder="ชื่อเจ้าของบัญชี" value="${escapeAttr(bank.bank_account_name)}">
  </div>
`;

/** 🪄 ผูก event ให้ select ที่เพิ่งถูกยัดลง DOM — ต้องทำหลัง `didOpen` เท่านั้น */
const wireChannelToggle = () => {
  const select = document.getElementById('swal-account-kind') as HTMLSelectElement | null;
  const box = document.getElementById('swal-bank-fields') as HTMLElement | null;
  if (!select || !box) return;
  select.addEventListener('change', () => {
    box.style.display = select.value === 'transfer' ? '' : 'none';
  });
};

/** 📥 อ่าน 4 ช่องนี้ออกจาก DOM (ป้าย/ชื่อธนาคารว่าง → `null` ไม่ใช่สตริงว่าง) */
const readChannelFields = () => {
  const value = (id: string) =>
    ((document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null)?.value ?? '').trim();
  const kind = (value('swal-account-kind') || 'cash') as AccountKind;
  const bankName = value('swal-bank-name');
  const bankNo = value('swal-bank-no');
  const bankOwner = value('swal-bank-owner');
  return {
    account_kind: kind,
    bank_name: bankName || null,
    bank_account_no: bankNo || null,
    bank_account_name: bankOwner || null
  };
};

const handleAddAccount = async () => {
  if (!isAdmin.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้น',
      confirmButtonColor: '#1d4ed8'
    });

  const { value: formValues } = await Swal.fire({
    title: 'เพิ่มกระเป๋าเงินใหม่',
    html:
      '<input id="swal-input1" class="swal2-input" placeholder="ชื่อกระเป๋าเงิน (เช่น เงินสด, ธนาคาร)">' +
      '<input id="swal-input2" type="number" class="swal2-input" placeholder="เงินตั้งต้น (฿)" value="0">' +
      channelFieldsHtml('cash'),
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonText: 'บันทึกข้อมูล',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    didOpen: wireChannelToggle,
    preConfirm: () => {
      const name = (document.getElementById('swal-input1') as HTMLInputElement).value;
      const balance = (document.getElementById('swal-input2') as HTMLInputElement).value;
      if (!name) {
        Swal.showValidationMessage('กรุณากรอกชื่อกระเป๋าเงิน');
        return false;
      }
      return { account_name: name, initial_balance: parseFloat(balance), ...readChannelFields() };
    }
  });

  if (formValues) {
    try {
      await FinanceService.createAccount(currentServerId, { ...formValues, user_name: currentUserName });
      Swal.fire({ icon: 'success', title: 'เพิ่มสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: unknown) {
      Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: error instanceof Error ? error.message : 'เพิ่มกระเป๋าเงินไม่สำเร็จ',
        confirmButtonColor: '#1d4ed8'
      });
    }
  }
};

const handleEditAccount = async (account: Account) => {
  if (!isAdmin.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้น',
      confirmButtonColor: '#1d4ed8'
    });

  const { value: formValues } = await Swal.fire({
    title: 'แก้ไขกระเป๋าเงิน',
    // 🏦 [F6] ฟอร์มนี้แก้ได้ทั้งชื่อและ "ช่องทางจ่าย" — ใบสำคัญจ่ายดึงช่องทางไปพิมพ์
    //    ⇒ ตั้งครั้งเดียวที่นี่แล้วเอกสารทุกใบหลังจากนั้นใช้ค่านี้
    html:
      `<input id="swal-input1" class="swal2-input" placeholder="ชื่อกระเป๋าเงิน" value="${escapeAttr(account.account_name)}">` +
      channelFieldsHtml(account.account_kind ?? 'cash', account),
    showCancelButton: true,
    confirmButtonText: 'บันทึก',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: '#1d4ed8',
    cancelButtonColor: '#78716c',
    didOpen: wireChannelToggle,
    preConfirm: () => {
      const name = (document.getElementById('swal-input1') as HTMLInputElement).value.trim();
      if (!name) {
        Swal.showValidationMessage('กรุณากรอกชื่อกระเป๋าเงิน');
        return false;
      }
      return { account_name: name, ...readChannelFields() };
    }
  });

  if (formValues) {
    try {
      await FinanceService.updateAccount(currentServerId, account.id, {
        ...formValues,
        user_name: currentUserName
      });
      Swal.fire({ icon: 'success', title: 'แก้ไขสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchSettingsData();
    } catch (error: unknown) {
      Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: error instanceof Error ? error.message : 'แก้ไขกระเป๋าเงินไม่สำเร็จ',
        confirmButtonColor: '#1d4ed8'
      });
    }
  }
};

const handleDeleteAccount = async (id: number) => {
  if (!isAdmin.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้น',
      confirmButtonColor: '#1d4ed8'
    });

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
      Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: error instanceof Error ? error.message : 'ลบกระเป๋าเงินไม่สำเร็จ',
        confirmButtonColor: '#1d4ed8'
      });
    }
  }
};

// --- Category Actions ---

const handleAddCategory = async () => {
  if (!isAdmin.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้น',
      confirmButtonColor: '#1d4ed8'
    });

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
      Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: error instanceof Error ? error.message : 'เพิ่มหมวดหมู่ไม่สำเร็จ',
        confirmButtonColor: '#1d4ed8'
      });
    }
  }
};

const handleEditCategory = async (category: Category) => {
  if (!isAdmin.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้น',
      confirmButtonColor: '#1d4ed8'
    });

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
      Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: error instanceof Error ? error.message : 'แก้ไขหมวดหมู่ไม่สำเร็จ',
        confirmButtonColor: '#1d4ed8'
      });
    }
  }
};

const handleDeleteCategory = async (id: number) => {
  if (!isAdmin.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะแอดมินเท่านั้น',
      confirmButtonColor: '#1d4ed8'
    });

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
      Swal.fire({
        icon: 'error',
        title: 'เกิดข้อผิดพลาด',
        text: error instanceof Error ? error.message : 'ลบหมวดหมู่ไม่สำเร็จ',
        confirmButtonColor: '#1d4ed8'
      });
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
    <StateBlock
      v-else-if="hasError"
      variant="error"
      :hint="errorMessage"
      @retry="fetchSettingsData"
    />

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
                <p class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-stone-500">
                  <span>
                    คงเหลือ
                    <span class="num font-bold text-brand-700">฿ {{ formatNumber(acc.balance) }}</span>
                  </span>
                  <!-- 🏦 ช่องทางจ่ายที่ใบสำคัญจ่ายจะพิมพ์ — แสดงเสมอแม้ไม่ได้ตั้งค่า
                       ไม่งั้นผู้ใช้ไม่มีทางรู้ว่ายัง "ไม่ได้ตั้ง" (ช่องว่างอ่านได้สองความหมาย) -->
                  <span class="chip bg-stone-100 text-stone-600">
                    <i
                      class="bi"
                      :class="(acc.account_kind ?? 'cash') === 'transfer' ? 'bi-bank' : 'bi-cash'"
                      aria-hidden="true"
                    ></i>
                    {{ ACCOUNT_KIND_LABELS[acc.account_kind ?? 'cash'] }}
                    <template v-if="acc.account_kind === 'transfer' && acc.bank_name">
                      · {{ acc.bank_name }}
                    </template>
                  </span>
                </p>
              </div>

              <div
                v-if="isAdmin"
                class="flex shrink-0 items-center gap-1 lg:opacity-0 lg:transition-opacity lg:group-hover:opacity-100 lg:focus-within:opacity-100"
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
          <button v-if="isAdmin" class="btn-primary shrink-0" @click="handleAddCategory">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่มหมวดหมู่
          </button>
        </div>

        <div class="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 sm:gap-4 sm:p-5">
          <!-- รายรับ -->
          <div class="min-w-0">
            <div class="mb-3 flex items-center justify-between gap-2 border-b border-stone-100 pb-2">
              <span class="chip bg-emerald-50 text-emerald-700">
                <i class="bi bi-arrow-down-left" aria-hidden="true"></i>
                รายรับ
              </span>
              <span class="num text-xs font-bold text-stone-400">{{ incomeCategories.length }}</span>
            </div>

            <StateBlock
              v-if="incomeCategories.length === 0"
              variant="empty"
              icon="bi-tags"
              title="ยังไม่มีหมวดหมู่รายรับ"
              hint="เพิ่มหมวดหมู่เพื่อใช้จัดกลุ่มรายรับ"
            />

            <div v-else class="space-y-2">
              <div
                v-for="cat in incomeCategories"
                :key="cat.id"
                class="group flex items-center justify-between gap-2 rounded-xl border border-stone-200 px-3 py-1.5"
              >
                <span class="truncate text-sm font-bold text-stone-700">{{ cat.category_name }}</span>
                <div v-if="isAdmin" class="flex shrink-0 items-center gap-1">
                  <button
                    class="flex h-11 w-11 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-brand-700"
                    title="แก้ไข"
                    aria-label="แก้ไขหมวดหมู่"
                    @click.stop="handleEditCategory(cat)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <button
                    class="flex h-11 w-11 items-center justify-center rounded-lg text-red-600 transition-colors hover:bg-red-50"
                    title="ลบ"
                    aria-label="ลบหมวดหมู่"
                    @click.stop="handleDeleteCategory(cat.id)"
                  >
                    <i class="bi bi-trash" aria-hidden="true"></i>
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

            <StateBlock
              v-if="expenseCategories.length === 0"
              variant="empty"
              icon="bi-tags"
              title="ยังไม่มีหมวดหมู่รายจ่าย"
              hint="เพิ่มหมวดหมู่เพื่อใช้จัดกลุ่มรายจ่าย"
            />

            <div v-else class="space-y-2">
              <div
                v-for="cat in expenseCategories"
                :key="cat.id"
                class="group flex items-center justify-between gap-2 rounded-xl border border-stone-200 px-3 py-1.5"
              >
                <span class="truncate text-sm font-bold text-stone-700">{{ cat.category_name }}</span>
                <div v-if="isAdmin" class="flex shrink-0 items-center gap-1">
                  <button
                    class="flex h-11 w-11 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-brand-700"
                    title="แก้ไข"
                    aria-label="แก้ไขหมวดหมู่"
                    @click.stop="handleEditCategory(cat)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <button
                    class="flex h-11 w-11 items-center justify-center rounded-lg text-red-600 transition-colors hover:bg-red-50"
                    title="ลบ"
                    aria-label="ลบหมวดหมู่"
                    @click.stop="handleDeleteCategory(cat.id)"
                  >
                    <i class="bi bi-trash" aria-hidden="true"></i>
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
