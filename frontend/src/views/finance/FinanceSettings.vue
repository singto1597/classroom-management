<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth'; // เพิ่ม import authStore
import { FinanceService } from '@/services/finance';
import type {
  Account,
  AccountKind,
  BasicStudent,
  Category,
  FinancePerson,
  FinanceSettings,
  PersonRole,
  PersonType
} from '@/types/finance';

import PersonPicker from '@/components/finance/PersonPicker.vue';
import PaymentChannelsSettings from '@/components/finance/PaymentChannelsSettings.vue';
import PageIntro from '@/components/ui/PageIntro.vue';
import AppTabs from '@/components/ui/AppTabs.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import RowActionMenu from '@/components/ui/RowActionMenu.vue';
import AppSheet from '@/components/ui/AppSheet.vue';
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue';
import { useDialog } from '@/composables/useDialog';
// 👜 [FIN-V2 / P3.2] สรุปเงินสดรอส่งมอบบนการ์ดทางเข้า
import { formatMoney } from '@/utils/money';

const authStore = useAuthStore();

// 🗂️ แท็บภายในหน้าเดียว — ค่า local เท่านั้น (ไม่ผูก query route ในรอบนี้)
//    "ทั่วไป" = กระเป๋า/หมวดหมู่/ผู้เกี่ยวข้อง/ค่าเริ่มต้น (ของเดิมทั้งหมด)
//    "ช่องทางชำระเงิน" = component แยกที่โหลด/เซฟเอง (P2.5)
const settingsTab = ref<'general' | 'channels'>('general');


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

// ═══════════════════════════════════════════════════════════════════
// 👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน + ค่าเริ่มต้นของหน้าจอรับเงิน
// ═══════════════════════════════════════════════════════════════════
// 🔒 ปุ่มเขียนของส่วนนี้ gate ด้วย `canManageFinance` (MANAGE_FINANCE) — ตรงกับ
//    backend; ส่วนกระเป๋า/หมวดหมู่ด้านบนยังใช้ `isAdmin` แบบเดิม (ไม่แตะในงานนี้)
const canManageFinance = computed(() => authStore.canManageFinance);

const PERSON_TYPE_LABELS: Record<PersonType, string> = {
  student: 'นักเรียน',
  teacher: 'ครู',
  external: 'บุคคลภายนอก'
};
const ROLE_LABELS: Record<PersonRole, string> = {
  receive: 'ผู้รับเงิน',
  pay: 'ผู้จ่าย',
  approve: 'ผู้อนุมัติ'
};
/** ลำดับปุ่มบทบาทในฟอร์ม — ประกาศเป็นค่าคงที่เพื่อให้ template วนได้โดยไม่ต้อง cast */
const PERSON_ROLES: PersonRole[] = ['receive', 'pay', 'approve'];

const people = ref<FinancePerson[]>([]);
const students = ref<BasicStudent[]>([]);
const isLoadingPeople = ref(true);
/** ตัวนับบอก `PersonPicker` ให้โหลดรายชื่อใหม่หลังทะเบียนถูกแก้ */
const peopleRefreshKey = ref(0);

interface SettingsForm {
  default_receiver_person_id: number | null;
  default_wallet_account_id: number | null;
  require_receiver: boolean;
  receipt_note: string;
}
const settingsForm = reactive<SettingsForm>({
  default_receiver_person_id: null,
  default_wallet_account_id: null,
  require_receiver: true,
  receipt_note: ''
});
const isSavingSettings = ref(false);
const isSyncingPeople = ref(false);

const applySettings = (s: FinanceSettings) => {
  settingsForm.default_receiver_person_id = s.default_receiver_person_id;
  settingsForm.default_wallet_account_id = s.default_wallet_account_id;
  settingsForm.require_receiver = s.require_receiver;
  settingsForm.receipt_note = s.receipt_note ?? '';
};

const fetchPeopleAndSettings = async () => {
  isLoadingPeople.value = true;
  try {
    const [peopleRes, settings, studentsRes] = await Promise.all([
      FinanceService.getPeople(currentServerId),
      FinanceService.getFinanceSettings(currentServerId),
      FinanceService.getActiveStudents(currentServerId)
    ]);
    people.value = peopleRes;
    students.value = studentsRes;
    applySettings(settings);
    peopleRefreshKey.value += 1;
  } catch (error: unknown) {
    void dialog.alert(
      'โหลดข้อมูลไม่สำเร็จ',
      error instanceof Error ? error.message : 'โหลดทะเบียนผู้เกี่ยวข้องไม่สำเร็จ',
      'error'
    );
  } finally {
    isLoadingPeople.value = false;
  }
};

// ── ฟอร์มเพิ่ม/แก้ผู้เกี่ยวข้อง (AppSheet) ──
interface PersonForm {
  person_type: PersonType;
  student_id: number | null;
  display_name: string;
  phone: string;
  roles: PersonRole[];
  is_active: boolean;
  note: string;
}

const personSheetOpen = ref(false);
const editingPerson = ref<FinancePerson | null>(null);
const isSavingPerson = ref(false);
const personForm = reactive<PersonForm>({
  person_type: 'teacher',
  student_id: null,
  display_name: '',
  phone: '',
  roles: ['receive'],
  is_active: true,
  note: ''
});

const resetPersonForm = () => {
  Object.assign(personForm, {
    person_type: 'teacher' as PersonType,
    student_id: null,
    display_name: '',
    phone: '',
    roles: ['receive'] as PersonRole[],
    is_active: true,
    note: ''
  });
};

const handleAddPerson = () => {
  if (!canManageFinance.value) return;
  editingPerson.value = null;
  resetPersonForm();
  personSheetOpen.value = true;
};

const handleEditPerson = (person: FinancePerson) => {
  if (!canManageFinance.value) return;
  editingPerson.value = person;
  Object.assign(personForm, {
    person_type: person.person_type,
    student_id: person.student_id,
    display_name: person.display_name,
    phone: person.phone ?? '',
    roles: [...person.roles],
    is_active: person.is_active,
    note: person.note ?? ''
  });
  personSheetOpen.value = true;
};

const togglePersonRole = (role: PersonRole) => {
  if (personForm.roles.includes(role)) {
    personForm.roles = personForm.roles.filter((r) => r !== role);
  } else {
    personForm.roles = [...personForm.roles, role];
  }
};

const savePerson = async () => {
  if (!canManageFinance.value) return;
  const name = personForm.display_name.trim();
  if (!name) {
    void dialog.alert('กรอกข้อมูลไม่ครบ', 'กรุณากรอกชื่อผู้เกี่ยวข้อง', 'warning');
    return;
  }
  if (personForm.roles.length === 0) {
    void dialog.alert('กรอกข้อมูลไม่ครบ', 'เลือกบทบาทอย่างน้อย 1 อย่าง', 'warning');
    return;
  }
  // นักเรียนต้องมี student_id; ครู/บุคคลภายนอกต้องไม่ส่ง student_id (ตรงกับ CHECK ของ DB)
  const studentId = personForm.person_type === 'student' ? personForm.student_id : null;
  if (personForm.person_type === 'student' && studentId === null) {
    void dialog.alert('กรอกข้อมูลไม่ครบ', 'กรุณาเลือกนักเรียน', 'warning');
    return;
  }

  isSavingPerson.value = true;
  try {
    if (editingPerson.value) {
      await FinanceService.updatePerson(currentServerId, editingPerson.value.person_id, {
        person_type: personForm.person_type,
        student_id: studentId,
        display_name: name,
        phone: personForm.phone.trim() || null,
        roles: personForm.roles,
        is_active: personForm.is_active,
        note: personForm.note.trim() || null
      });
      dialog.notify('แก้ไขผู้เกี่ยวข้องแล้ว');
    } else {
      await FinanceService.createPerson(currentServerId, {
        person_type: personForm.person_type,
        student_id: studentId,
        display_name: name,
        phone: personForm.phone.trim() || null,
        roles: personForm.roles,
        is_active: personForm.is_active,
        note: personForm.note.trim() || null
      });
      dialog.notify('เพิ่มผู้เกี่ยวข้องแล้ว');
    }
    personSheetOpen.value = false;
    await fetchPeopleAndSettings();
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'บันทึกผู้เกี่ยวข้องไม่สำเร็จ',
      'error'
    );
  } finally {
    isSavingPerson.value = false;
  }
};

const handleDeletePerson = async (person: FinancePerson) => {
  if (!canManageFinance.value) return;
  const result = await dialog.confirm(
    'ปิดใช้งานผู้เกี่ยวข้อง?',
    `${person.display_name} จะหายจากรายชื่อให้เลือก แต่ประวัติเอกสารเดิมยังคงอยู่`,
    { icon: 'warning', danger: true, confirmButtonText: 'ปิดใช้งาน' }
  );
  if (!result.isConfirmed) return;

  try {
    await FinanceService.deletePerson(currentServerId, person.person_id);
    dialog.notify('ปิดใช้งานแล้ว');
    await fetchPeopleAndSettings();
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'ปิดใช้งานไม่สำเร็จ',
      'error'
    );
  }
};

const runSyncStudents = async () => {
  if (!canManageFinance.value) return;
  isSyncingPeople.value = true;
  try {
    const result = await FinanceService.syncStudents(currentServerId);
    await dialog.alert(
      'ซิงก์รายชื่อแล้ว',
      `เพิ่มใหม่ ${result.created} คน · อัปเดต ${result.updated} คน` +
        (result.skipped > 0 ? ` · ข้าม ${result.skipped} คน` : '') +
        ' — ชื่อที่แก้ไว้จะไม่ถูกทับ',
      'success'
    );
    await fetchPeopleAndSettings();
  } catch (error: unknown) {
    void dialog.alert(
      'ซิงก์ไม่สำเร็จ',
      error instanceof Error ? error.message : 'ซิงก์รายชื่อนักเรียนไม่สำเร็จ',
      'error'
    );
  } finally {
    isSyncingPeople.value = false;
  }
};

const saveFinanceSettings = async () => {
  if (!canManageFinance.value) return;
  isSavingSettings.value = true;
  try {
    const saved = await FinanceService.updateFinanceSettings(currentServerId, {
      default_receiver_person_id: settingsForm.default_receiver_person_id,
      default_wallet_account_id: settingsForm.default_wallet_account_id,
      require_receiver: settingsForm.require_receiver,
      receipt_note: settingsForm.receipt_note.trim() || null
    });
    applySettings(saved);
    dialog.notify('บันทึกค่าเริ่มต้นแล้ว');
  } catch (error: unknown) {
    void dialog.alert(
      'เกิดข้อผิดพลาด',
      error instanceof Error ? error.message : 'บันทึกค่าเริ่มต้นไม่สำเร็จ',
      'error'
    );
  } finally {
    isSavingSettings.value = false;
  }
};

onMounted(() => {
  void fetchPeopleAndSettings();
});

/* 👜 [FIN-V2 / P3.2] สรุปเงินสดรอส่งมอบ — การ์ดทางเข้าไปหน้า `/finance/custody`
 * ⚠️ โหลดแบบ **ไม่บล็อกหน้า**: ถ้า API ล้มเหลว ซ่อนเฉพาะตัวเลข ไม่ทำให้หน้า
 *    ตั้งค่าพัง (brief P3.2 กำหนดไว้แบบนี้) — ยอดจริงอยู่ในหน้าคุมเอง */
const custodySummary = ref<{ total_held: number; count: number } | null>(null);

void (async () => {
  try {
    const res = await FinanceService.getCustody(authStore.currentRoomId!);
    custodySummary.value = { total_held: res.total_held, count: res.items.length };
  } catch {
    custodySummary.value = null;
  }
})();
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="จัดการกระเป๋าเงินห้อง หมวดหมู่ และช่องทางชำระเงินสำหรับบันทึกรายรับ/รายจ่าย"
    ></PageIntro>

    <!-- 🗂️ แท็บ “ทั่วไป / ช่องทางชำระเงิน” — เนื้อหาแต่ละแท็บโหลดแยกกัน -->
    <AppTabs
      v-model="settingsTab"
      :tabs="[
        { value: 'general', label: 'ทั่วไป' },
        { value: 'channels', label: 'ช่องทางชำระเงิน' },
      ]"
      group-label="หมวดการตั้งค่าการเงิน"
    />

    <template v-if="settingsTab === 'general'">
    <!-- สถานะโหลด / ผิดพลาด -->
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      :hint="errorMessage"
      @retry="fetchSettingsData"
    />

    <template v-else>
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
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

    <!-- ═══════════════════════════════════════════════════════════════
         👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน
         ═══════════════════════════════════════════════════════════════
         🔑 ทะเบียนคน ไม่ใช่ช่องข้อความอิสระ: เอกสารทุกใบต้องตอบได้ว่า
            "ใครรับเงินไปเท่าไร" และ snapshot ชื่อลงใบเสร็จได้ (P2.1/P2.2)
         ปุ่มเขียน gate ด้วย `canManageFinance` — ตรงกับ MANAGE_FINANCE ฝั่ง backend -->
    <div v-if="!isLoading && !hasError" class="page-card overflow-hidden">
      <div
        class="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-canvas px-4 py-3 sm:px-5"
      >
        <div class="min-w-0">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-people text-brand-700" aria-hidden="true"></i>
            <span class="truncate">ผู้เกี่ยวข้องทางการเงิน</span>
          </h2>
          <p class="mt-0.5 text-sm text-ink-3">
            คนที่รับเงิน จ่ายเงิน หรืออนุมัติ — ใช้เลือกในเอกสารการเงิน
          </p>
        </div>
        <div v-if="canManageFinance" class="flex shrink-0 items-center gap-2">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isSyncingPeople"
            @click="runSyncStudents"
          >
            <i
              class="bi bi-arrow-repeat"
              :class="{ 'animate-spin': isSyncingPeople }"
              aria-hidden="true"
            ></i>
            ซิงก์นักเรียน
          </button>
          <button type="button" class="btn-primary" @click="handleAddPerson">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่ม
          </button>
        </div>
      </div>

      <div class="p-4 sm:p-5">
        <p v-if="isLoadingPeople" class="text-sm text-ink-3">กำลังโหลดรายชื่อ…</p>

        <StateBlock
          v-else-if="people.length === 0"
          variant="empty"
          icon="bi-people"
          title="ยังไม่มีผู้เกี่ยวข้อง"
          hint="เพิ่มเอง หรือกด “ซิงก์นักเรียน” เพื่อดึงรายชื่อนักเรียนทั้งห้อง"
        />

        <div v-else class="space-y-2">
          <div
            v-for="person in people"
            :key="person.person_id"
            class="group flex items-center justify-between gap-3 rounded-control border border-line p-3 transition-colors hover:border-ink-3/30"
          >
            <div class="min-w-0">
              <p class="flex flex-wrap items-center gap-2">
                <span class="truncate font-bold text-ink-1">{{ person.display_name }}</span>
                <span class="chip bg-canvas text-ink-2">
                  {{ PERSON_TYPE_LABELS[person.person_type] }}
                </span>
                <span v-if="!person.is_active" class="chip bg-canvas text-ink-3">ปิดใช้งาน</span>
              </p>
              <p class="mt-1 flex flex-wrap items-center gap-1 text-xs text-ink-3">
                <span
                  v-for="role in person.roles"
                  :key="role"
                  class="chip bg-canvas text-ink-2"
                >
                  {{ ROLE_LABELS[role] }}
                </span>
                <span v-if="person.phone" class="num ml-1">{{ person.phone }}</span>
              </p>
            </div>

            <div
              v-if="canManageFinance"
              class="flex shrink-0 items-center gap-1 lg:opacity-0 lg:transition-opacity lg:group-hover:opacity-100 lg:focus-within:opacity-100"
            >
              <button
                type="button"
                class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                title="แก้ไข"
                aria-label="แก้ไขผู้เกี่ยวข้อง"
                @click="handleEditPerson(person)"
              >
                <i class="bi bi-pencil-square" aria-hidden="true"></i>
              </button>
              <button
                type="button"
                class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-danger-600"
                title="ปิดใช้งาน"
                aria-label="ปิดใช้งานผู้เกี่ยวข้อง"
                @click="handleDeletePerson(person)"
              >
                <i class="bi bi-person-slash" aria-hidden="true"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         ⚙️ [FIN-V2 / P1.2] ค่าเริ่มต้นหน้า “รับเงิน”
         ═══════════════════════════════════════════════════════════════
         ค่าเหล่านี้เป็นเพียง **ค่าที่ฟอร์มเติมให้ก่อน** — ไม่บังคับตอนบันทึกจริง
         (ผู้รับเงินบังคับหรือไม่ ขึ้นกับ `require_receiver` ซึ่งเอกสารมีคำอธิบาย) -->
    <div v-if="!isLoading && !hasError" class="page-card overflow-hidden">
      <div class="border-b border-line bg-canvas px-4 py-3 sm:px-5">
        <h2 class="section-title flex items-center gap-2">
          <i class="bi bi-sliders text-brand-700" aria-hidden="true"></i>
          <span class="truncate">ค่าเริ่มต้นการรับเงิน</span>
        </h2>
        <p class="mt-0.5 text-sm text-ink-3">
          ฟอร์มรับเงินจะเติมค่าเหล่านี้ให้อัตโนมัติ — เปลี่ยนรายครั้งได้ตอนบันทึก
        </p>
      </div>

      <form class="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 sm:p-5" @submit.prevent="saveFinanceSettings">
        <div class="sm:col-span-2">
          <PersonPicker
            v-model="settingsForm.default_receiver_person_id"
            label="ผู้รับเงินเริ่มต้น"
            :roles="['receive']"
            placeholder="เลือกผู้รับเงิน…"
            :disabled="!canManageFinance"
            :refresh-key="peopleRefreshKey"
          />
        </div>

        <div>
          <label class="field-label" for="defaultWallet">กระเป๋าเงินเริ่มต้น</label>
          <select
            id="defaultWallet"
            v-model="settingsForm.default_wallet_account_id"
            class="field"
            :disabled="!canManageFinance"
          >
            <option :value="null">— ไม่กำหนด —</option>
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
              {{ acc.account_name }}
            </option>
          </select>
        </div>

        <div class="flex items-center">
          <label class="flex cursor-pointer items-center gap-2 text-sm font-bold text-ink-1">
            <input
              v-model="settingsForm.require_receiver"
              type="checkbox"
              class="h-4 w-4 rounded border-line text-brand-700"
              :disabled="!canManageFinance"
            />
            บังคับระบุผู้รับเงินในทุกการรับเงิน
          </label>
        </div>

        <div class="sm:col-span-2">
          <label class="field-label" for="receiptNote">ข้อความท้ายใบเสร็จ (ไม่บังคับ)</label>
          <textarea
            id="receiptNote"
            v-model="settingsForm.receipt_note"
            class="field min-h-[5rem]"
            maxlength="500"
            placeholder="เช่น “ขอบคุณที่ชำระเงินครบถ้วน”"
            :disabled="!canManageFinance"
          ></textarea>
        </div>

        <div v-if="canManageFinance" class="flex justify-end sm:col-span-2">
          <button type="submit" class="btn-primary" :disabled="isSavingSettings">
            <i v-if="isSavingSettings" class="bi bi-arrow-repeat animate-spin" aria-hidden="true"></i>
            <i v-else class="bi bi-check-lg" aria-hidden="true"></i>
            {{ isSavingSettings ? 'กำลังบันทึก…' : 'บันทึกค่าเริ่มต้น' }}
          </button>
        </div>
      </form>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         👜 [FIN-V2 / P3.2] เงินสดรอส่งมอบ — การ์ดทางเข้า (ไม่ใช่เมนูหลัก)
         ═══════════════════════════════════════════════════════════════
         ยอดเป็นสรุปจาก `GET /finance/custody` (โหลดแบบไม่บล็อก) — ถ้าโหลดไม่ได้
         จะซ่อนตัวเลขแต่ลิงก์ยังใช้ได้ (หน้าปลายทางโหลดเองอีกครั้ง)
         🔓 สมาชิกทุกคนเข้าได้ (backend `require_member`); ปุ่มเขียนอยู่ในหน้านั้น -->
    <div class="page-card overflow-hidden">
      <div class="border-b border-line bg-canvas px-4 py-3 sm:px-5">
        <h2 class="section-title flex items-center gap-2">
          <i class="bi bi-wallet2 text-brand-700" aria-hidden="true"></i>
          <span class="truncate">เงินสดรอส่งมอบ</span>
        </h2>
        <p class="mt-0.5 text-sm text-ink-3">
          ยอดที่ผู้ถือเงินรับไปแล้วยังไม่นำส่ง — โอนเข้า-ออกได้โดยไม่นับเป็นรายรับหรือรายจ่าย
        </p>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5">
        <div v-if="custodySummary">
          <p class="text-xs font-bold text-ink-3">ยอดถือรวมทั้งห้อง</p>
          <p class="text-xl font-bold tabular-nums text-ink-1">
            {{ formatMoney(custodySummary.total_held) }}
          </p>
          <p class="text-xs text-ink-3">ผู้ถือเงิน {{ custodySummary.count }} คน</p>
        </div>
        <p v-else class="text-sm text-ink-3">เปิดหน้าเพื่อดูยอดและจัดการผู้ถือเงิน</p>
        <RouterLink to="/finance/custody" class="btn-ghost-ui">
          <i class="bi bi-arrow-right-circle" aria-hidden="true"></i>
          เปิดหน้าเงินสดรอส่งมอบ
        </RouterLink>
      </div>
    </div>
    </template>
    </template>

    <PaymentChannelsSettings v-else />

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

    <!-- 👥 [FIN-V2 / P1.2] ฟอร์มผู้เกี่ยวข้องทางการเงิน -->
    <AppSheet
      :open="personSheetOpen"
      :label="editingPerson ? 'แก้ไขผู้เกี่ยวข้อง' : 'เพิ่มผู้เกี่ยวข้อง'"
      :title="editingPerson ? 'แก้ไขผู้เกี่ยวข้อง' : 'เพิ่มผู้เกี่ยวข้อง'"
      size="form"
      :dismissible="!isSavingPerson"
      @close="personSheetOpen = false"
    >
      <div class="space-y-4">
        <div>
          <label class="field-label" for="personType">ประเภท</label>
          <select id="personType" v-model="personForm.person_type" class="field">
            <option value="student">นักเรียน</option>
            <option value="teacher">ครู</option>
            <option value="external">บุคคลภายนอก</option>
          </select>
        </div>

        <!-- นักเรียนต้องผูก student_id (ตรงกับ CHECK ฝั่ง DB) — ครู/บุคคลภายนอกไม่ต้อง -->
        <div v-if="personForm.person_type === 'student'">
          <label class="field-label" for="personStudent">
            นักเรียน <span class="text-danger-600">*</span>
          </label>
          <select id="personStudent" v-model="personForm.student_id" class="field">
            <option :value="null">— เลือกนักเรียน —</option>
            <option v-for="student in students" :key="student.id" :value="student.id">
              {{ student.student_no }}. {{ student.first_name }} {{ student.last_name }}
              <template v-if="student.nickname"> ({{ student.nickname }})</template>
            </option>
          </select>
        </div>

        <div>
          <label class="field-label" for="personName">
            ชื่อที่แสดง <span class="text-danger-600">*</span>
          </label>
          <input
            id="personName"
            v-model="personForm.display_name"
            type="text"
            class="field"
            maxlength="200"
            placeholder="เช่น ครูสมชาย, ผู้ปกครองน้องบี"
          />
        </div>

        <div>
          <label class="field-label" for="personPhone">เบอร์โทร (ไม่บังคับ)</label>
          <input
            id="personPhone"
            v-model="personForm.phone"
            type="tel"
            class="field"
            maxlength="50"
            placeholder="08x-xxx-xxxx"
          />
        </div>

        <div>
          <span class="field-label">บทบาท</span>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="role in PERSON_ROLES"
              :key="role"
              type="button"
              class="chip transition-colors"
              :class="
                personForm.roles.includes(role)
                  ? 'bg-brand-700 text-white'
                  : 'bg-canvas text-ink-2'
              "
              :aria-pressed="personForm.roles.includes(role)"
              @click="togglePersonRole(role)"
            >
              {{ ROLE_LABELS[role] }}
            </button>
          </div>
        </div>

        <label class="flex cursor-pointer items-center gap-2 text-sm font-bold text-ink-1">
          <input
            v-model="personForm.is_active"
            type="checkbox"
            class="h-4 w-4 rounded border-line text-brand-700"
          />
          เปิดใช้งาน (แสดงในรายชื่อให้เลือก)
        </label>

        <div>
          <label class="field-label" for="personNote">หมายเหตุ (ไม่บังคับ)</label>
          <textarea
            id="personNote"
            v-model="personForm.note"
            class="field min-h-[4rem]"
            maxlength="500"
          ></textarea>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isSavingPerson"
            @click="personSheetOpen = false"
          >
            ยกเลิก
          </button>
          <button type="button" class="btn-primary" :disabled="isSavingPerson" @click="savePerson">
            <span
              v-if="isSavingPerson"
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
