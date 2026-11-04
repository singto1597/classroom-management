<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth'; // เพิ่ม import authStore
import { FinanceService } from '@/services/finance';
import type { Account, AccountKind, Category } from '@/types/finance';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import RowActionMenu from '@/components/ui/RowActionMenu.vue';
import AppSheet from '@/components/ui/AppSheet.vue';
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue';
import { useDialog } from '@/composables/useDialog';

const authStore = useAuthStore();


// 🔒 ตั้งค่าการเงิน: "แก้ไข" เป็นปุ่มหลักที่อยู่จริงในแถว
//    "ลบ" ทำลายข้อมูล (และลบหมวดที่ถูกใช้แล้วจะถูกปฏิเสธฝั่ง backend) ⇒ ซ่อนในเมนู
//    เดิมเป็นไอคอนเปลือย 2 ปุ่มติดกัน — "ลบ" อยู่ห่างนิ้วโป้งแค่ ~44px จาก "แก้ไข"
const accountMenuItems: RowActionItem[] = [
  { key: 'delete', label: 'ลบกระเป๋าเงิน', icon: 'bi-trash3-fill', tone: 'danger' },
];
const categoryMenuItems: RowActionItem[] = [
  { key: 'delete', label: 'ลบหมวดหมู่', icon: 'bi-trash3-fill', tone: 'danger' },
];

const handleAccountAction = (acc: Account, key: string) => {
  if (key === 'delete') void handleDeleteAccount(acc.id);
};
const handleCategoryAction = (cat: Category, key: string) => {
  if (key === 'delete') void handleDeleteCategory(cat.id);
};
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

const dialog = useDialog();

/** 🔒 กันทุกฟังก์ชันที่แตะข้อมูล — ข้อความเดียว ไม่ต้องเขียนซ้ำ 8 ที่ */
const ensureAdmin = (): boolean => {
  if (isAdmin.value) return true;
  void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้น', 'error');
  return false;
};

// --- 📝 ฟอร์มกระเป๋าเงิน (AppSheet) — ไม่ต้องประกอบ HTML สตริงอีก ---
interface AccountForm {
  account_name: string;
  initial_balance: string;
  account_kind: AccountKind;
  bank_name: string;
  bank_account_no: string;
  bank_account_name: string;
}

const accountSheetOpen = ref(false);
const editingAccount = ref<Account | null>(null);
const isSavingAccount = ref(false);
const accountForm = reactive<AccountForm>({
  account_name: '',
  initial_balance: '0',
  account_kind: 'cash',
  bank_name: '',
  bank_account_no: '',
  bank_account_name: ''
});

const resetAccountForm = () => {
  Object.assign(accountForm, {
    account_name: '',
    initial_balance: '0',
    account_kind: 'cash' as AccountKind,
    bank_name: '',
    bank_account_no: '',
    bank_account_name: ''
  });
};

const handleAddAccount = () => {
  if (!ensureAdmin()) return;
  editingAccount.value = null;
  resetAccountForm();
  accountSheetOpen.value = true;
};

const handleEditAccount = (account: Account) => {
  if (!ensureAdmin()) return;
  editingAccount.value = account;
  Object.assign(accountForm, {
    account_name: account.account_name,
    initial_balance: '0',
    account_kind: account.account_kind ?? 'cash',
    bank_name: account.bank_name ?? '',
    bank_account_no: account.bank_account_no ?? '',
    bank_account_name: account.bank_account_name ?? ''
  });
  accountSheetOpen.value = true;
};

const saveAccount = async () => {
  const name = accountForm.account_name.trim();
  if (!name) {
    void dialog.alert('กรอกข้อมูลไม่ครบ', 'กรุณากรอกชื่อกระเป๋าเงิน', 'warning');
    return;
  }
  // ชื่อธนาคาร/เลขบัญชีว่าง → `null` ไม่ใช่สตริงว่าง (backend แยกสองอย่างนี้)
  const channel = {
    account_kind: accountForm.account_kind,
    bank_name: accountForm.bank_name.trim() || null,
    bank_account_no: accountForm.bank_account_no.trim() || null,
    bank_account_name: accountForm.bank_account_name.trim() || null
  };
  isSavingAccount.value = true;
  try {
    if (editingAccount.value) {
      await FinanceService.updateAccount(currentServerId, editingAccount.value.id, {
        account_name: name,
        ...channel,
        user_name: currentUserName
      });
      dialog.notify('แก้ไขกระเป๋าเงินแล้ว');
    } else {
      await FinanceService.createAccount(currentServerId, {
        account_name: name,
        initial_balance: Number.parseFloat(accountForm.initial_balance) || 0,
        ...channel,
        user_name: currentUserName
      });
      dialog.notify('เพิ่มกระเป๋าเงินแล้ว');
    }
    accountSheetOpen.value = false;
    await fetchSettingsData();
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'บันทึกกระเป๋าเงินไม่สำเร็จ',
      'error'
    );
  } finally {
    isSavingAccount.value = false;
  }
};

const handleDeleteAccount = async (id: number) => {
  if (!ensureAdmin()) return;

  const result = await dialog.confirm(
    'ยืนยันการลบ?',
    'หากลบแล้วข้อมูลประวัติที่เกี่ยวข้องอาจได้รับผลกระทบ',
    { icon: 'warning', danger: true, confirmButtonText: 'ลบทันที' }
  );
  if (!result.isConfirmed) return;

  try {
    await FinanceService.deleteAccount(currentServerId, id);
    dialog.notify('ลบกระเป๋าเงินแล้ว');
    await fetchSettingsData();
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'ลบกระเป๋าเงินไม่สำเร็จ',
      'error'
    );
  }
};

// --- Category Actions ---

const categorySheetOpen = ref(false);
const editingCategory = ref<Category | null>(null);
const isSavingCategory = ref(false);
const categoryForm = reactive<{ category_name: string; category_type: 'income' | 'expense' }>({
  category_name: '',
  category_type: 'income'
});

const handleAddCategory = () => {
  if (!ensureAdmin()) return;
  editingCategory.value = null;
  categoryForm.category_name = '';
  categoryForm.category_type = 'income';
  categorySheetOpen.value = true;
};

const handleEditCategory = (category: Category) => {
  if (!ensureAdmin()) return;
  editingCategory.value = category;
  categoryForm.category_name = category.category_name;
  categoryForm.category_type = category.category_type;
  categorySheetOpen.value = true;
};

const saveCategory = async () => {
  const name = categoryForm.category_name.trim();
  if (!name) {
    void dialog.alert('กรอกข้อมูลไม่ครบ', 'กรุณากรอกชื่อหมวดหมู่', 'warning');
    return;
  }
  isSavingCategory.value = true;
  try {
    if (editingCategory.value) {
      await FinanceService.updateCategory(currentServerId, editingCategory.value.id, name, currentUserName);
      dialog.notify('แก้ไขหมวดหมู่แล้ว');
    } else {
      await FinanceService.createCategory(currentServerId, {
        category_name: name,
        category_type: categoryForm.category_type,
        user_name: currentUserName
      });
      dialog.notify('เพิ่มหมวดหมู่แล้ว');
    }
    categorySheetOpen.value = false;
    await fetchSettingsData();
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'บันทึกหมวดหมู่ไม่สำเร็จ',
      'error'
    );
  } finally {
    isSavingCategory.value = false;
  }
};

const handleDeleteCategory = async (id: number) => {
  if (!ensureAdmin()) return;

  const result = await dialog.confirm('ลบหมวดหมู่?', 'การลบหมวดหมู่อาจส่งผลต่อการจัดกลุ่มรายงาน', {
    icon: 'warning',
    danger: true,
    confirmButtonText: 'ลบทันที'
  });
  if (!result.isConfirmed) return;

  try {
    await FinanceService.deleteCategory(currentServerId, id);
    dialog.notify('ลบหมวดหมู่แล้ว');
    await fetchSettingsData();
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'ลบหมวดหมู่ไม่สำเร็จ',
      'error'
    );
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
    <PageIntro
      description="จัดการกระเป๋าเงินห้องและหมวดหมู่สำหรับบันทึกรายรับ/รายจ่าย"
    ></PageIntro>

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
          class="flex items-center justify-between gap-3 border-b border-line bg-canvas px-4 py-3 sm:px-5"
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
              class="group flex items-center justify-between gap-3 rounded-control border border-line p-3 transition-colors hover:border-ink-3/30"
            >
              <div class="min-w-0">
                <p class="truncate font-bold text-ink-1">{{ acc.account_name }}</p>
                <p class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-ink-3">
                  <span>
                    คงเหลือ
                    <span class="num font-bold text-brand-700">฿ {{ formatNumber(acc.balance) }}</span>
                  </span>
                  <!-- 🏦 ช่องทางจ่ายที่ใบสำคัญจ่ายจะพิมพ์ — แสดงเสมอแม้ไม่ได้ตั้งค่า
                       ไม่งั้นผู้ใช้ไม่มีทางรู้ว่ายัง "ไม่ได้ตั้ง" (ช่องว่างอ่านได้สองความหมาย) -->
                  <span class="chip bg-canvas text-ink-2">
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
                  class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                  title="แก้ไข"
                  aria-label="แก้ไขกระเป๋าเงิน"
                  @click="handleEditAccount(acc)"
                >
                  <i class="bi bi-pencil-square" aria-hidden="true"></i>
                </button>
                <RowActionMenu
                  :label="`ตัวเลือกของกระเป๋า ${acc.account_name}`"
                  :items="accountMenuItems"
                  @select="handleAccountAction(acc, $event)"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- หมวดหมู่รายการ -->
      <div class="page-card h-fit overflow-hidden">
        <div
          class="flex items-center justify-between gap-3 border-b border-line bg-canvas px-4 py-3 sm:px-5"
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
            <div class="mb-3 flex items-center justify-between gap-2 border-b border-line pb-2">
              <span class="chip bg-ok-50 text-ok-700">
                <i class="bi bi-arrow-down-left" aria-hidden="true"></i>
                รายรับ
              </span>
              <span class="num text-xs font-bold text-ink-3">{{ incomeCategories.length }}</span>
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
                class="group flex items-center justify-between gap-2 rounded-control border border-line px-3 py-1.5"
              >
                <span class="truncate text-sm font-bold text-ink-1">{{ cat.category_name }}</span>
                <div v-if="isAdmin" class="flex shrink-0 items-center gap-1">
                  <button
                    class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                    title="แก้ไข"
                    aria-label="แก้ไขหมวดหมู่"
                    @click.stop="handleEditCategory(cat)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <RowActionMenu
                    :label="`ตัวเลือกของหมวดหมู่ ${cat.category_name}`"
                    :items="categoryMenuItems"
                    @select="handleCategoryAction(cat, $event)"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- รายจ่าย -->
          <div class="min-w-0">
            <div class="mb-3 flex items-center justify-between gap-2 border-b border-line pb-2">
              <span class="chip bg-danger-50 text-danger-700">
                <i class="bi bi-arrow-up-right" aria-hidden="true"></i>
                รายจ่าย
              </span>
              <span class="num text-xs font-bold text-ink-3">{{ expenseCategories.length }}</span>
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
                class="group flex items-center justify-between gap-2 rounded-control border border-line px-3 py-1.5"
              >
                <span class="truncate text-sm font-bold text-ink-1">{{ cat.category_name }}</span>
                <div v-if="isAdmin" class="flex shrink-0 items-center gap-1">
                  <button
                    class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                    title="แก้ไข"
                    aria-label="แก้ไขหมวดหมู่"
                    @click.stop="handleEditCategory(cat)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true"></i>
                  </button>
                  <RowActionMenu
                    :label="`ตัวเลือกของหมวดหมู่ ${cat.category_name}`"
                    :items="categoryMenuItems"
                    @select="handleCategoryAction(cat, $event)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 🏦 ฟอร์มกระเป๋าเงิน — AppSheet แทน `Swal.fire({ html })` -->
    <AppSheet
      :open="accountSheetOpen"
      :label="editingAccount ? 'แก้ไขกระเป๋าเงิน' : 'เพิ่มกระเป๋าเงินใหม่'"
      :title="editingAccount ? 'แก้ไขกระเป๋าเงิน' : 'เพิ่มกระเป๋าเงินใหม่'"
      size="form"
      :dismissible="!isSavingAccount"
      @close="accountSheetOpen = false"
    >
      <div class="space-y-4">
        <div>
          <label class="field-label" for="accountName">
            ชื่อกระเป๋าเงิน <span class="text-danger-600">*</span>
          </label>
          <input
            id="accountName"
            v-model="accountForm.account_name"
            type="text"
            class="field"
            placeholder="เช่น เงินสด, ธนาคาร"
          />
        </div>

        <div v-if="!editingAccount">
          <label class="field-label" for="accountBalance">เงินตั้งต้น (฿)</label>
          <input
            id="accountBalance"
            v-model="accountForm.initial_balance"
            type="number"
            min="0"
            step="0.01"
            inputmode="decimal"
            class="field num"
          />
        </div>

        <div>
          <label class="field-label" for="accountKind">ช่องทางจ่าย</label>
          <select id="accountKind" v-model="accountForm.account_kind" class="field">
            <option value="cash">เงินสด</option>
            <option value="transfer">โอนเข้าบัญชี</option>
          </select>
          <p class="mt-1 text-xs leading-relaxed text-ink-3">
            ช่องทางนี้จะถูกพิมพ์ในใบสำคัญจ่ายโดยอัตโนมัติ
          </p>
        </div>

        <div
          v-if="accountForm.account_kind === 'transfer'"
          class="space-y-3 rounded-control border border-line bg-canvas p-3"
        >
          <div>
            <label class="field-label" for="accountBank">ธนาคาร</label>
            <input
              id="accountBank"
              v-model="accountForm.bank_name"
              type="text"
              class="field"
              placeholder="เช่น ธ.ไทยพาณิชย์"
            />
          </div>
          <div>
            <label class="field-label" for="accountNo">เลขที่บัญชี</label>
            <input
              id="accountNo"
              v-model="accountForm.bank_account_no"
              type="text"
              inputmode="numeric"
              class="field num"
              placeholder="เช่น 123-4-56789-0"
            />
          </div>
          <div>
            <label class="field-label" for="accountOwner">ชื่อเจ้าของบัญชี</label>
            <input
              id="accountOwner"
              v-model="accountForm.bank_account_name"
              type="text"
              class="field"
              placeholder="ชื่อ-นามสกุลเจ้าของบัญชี"
            />
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isSavingAccount"
            @click="accountSheetOpen = false"
          >
            ยกเลิก
          </button>
          <button type="button" class="btn-primary" :disabled="isSavingAccount" @click="saveAccount">
            <span
              v-if="isSavingAccount"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              aria-hidden="true"
            ></span>
            <template v-else><i class="bi bi-check-lg" aria-hidden="true"></i> บันทึกข้อมูล</template>
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- 🏷️ ฟอร์มหมวดหมู่ — AppSheet -->
    <AppSheet
      :open="categorySheetOpen"
      :label="editingCategory ? 'แก้ไขหมวดหมู่' : 'เพิ่มหมวดหมู่ใหม่'"
      :title="editingCategory ? 'แก้ไขชื่อหมวดหมู่' : 'เพิ่มหมวดหมู่ใหม่'"
      size="form"
      :dismissible="!isSavingCategory"
      @close="categorySheetOpen = false"
    >
      <div class="space-y-4">
        <div v-if="!editingCategory">
          <label class="field-label" for="categoryType">ประเภทรายการ</label>
          <select id="categoryType" v-model="categoryForm.category_type" class="field">
            <option value="income">รายรับ</option>
            <option value="expense">รายจ่าย</option>
          </select>
        </div>

        <div>
          <label class="field-label" for="categoryName">
            ชื่อหมวดหมู่ <span class="text-danger-600">*</span>
          </label>
          <input
            id="categoryName"
            v-model="categoryForm.category_name"
            type="text"
            class="field"
            placeholder="เช่น ค่าอุปกรณ์, ค่าพาน"
          />
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isSavingCategory"
            @click="categorySheetOpen = false"
          >
            ยกเลิก
          </button>
          <button type="button" class="btn-primary" :disabled="isSavingCategory" @click="saveCategory">
            <span
              v-if="isSavingCategory"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              aria-hidden="true"
            ></span>
            <template v-else><i class="bi bi-check-lg" aria-hidden="true"></i> บันทึก</template>
          </button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
