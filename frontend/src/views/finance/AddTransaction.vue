<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { FinanceService } from '@/services/finance';
import type { Account, Category } from '@/types/finance';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

const authStore = useAuthStore();
const router = useRouter();

const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const activeTab = ref<'expense' | 'income' | 'transfer'>('expense');
const isLoading = ref(true);
const isSubmitting = ref(false);

// รายการแท็บสำหรับ segmented control (พิมพ์ type ไว้ให้ template รู้จัก union โดยไม่ต้อง cast)
const tabs: Array<'expense' | 'income' | 'transfer'> = ['expense', 'income', 'transfer'];

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false);

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
  hasError.value = false;
  try {
    const [accRes, catRes] = await Promise.all([
      FinanceService.getAccounts(currentServerId),
      FinanceService.getCategories(currentServerId)
    ]);
    accounts.value = accRes;
    categories.value = catRes;
  } catch {
    hasError.value = true;
    Swal.fire('เกิดข้อผิดพลาด', 'ไม่สามารถโหลดข้อมูลเริ่มต้นได้', 'error');
  } finally {
    isLoading.value = false;
  }
};

const filteredCategories = computed(() => {
  if (activeTab.value === 'transfer') return [];
  return categories.value.filter(c => c.category_type === activeTab.value);
});

// ข้อความบนปุ่มยืนยัน — แยกออกมาเพื่อให้คง accessible name ไว้ระหว่างส่งข้อมูล
const submitLabel = computed(() =>
  activeTab.value === 'expense' ? 'บันทึกรายจ่าย' : activeTab.value === 'income' ? 'บันทึกรายรับ' : 'ยืนยันการโอนเงิน'
);

// จัดรูปแบบเงินให้ตรงกับหน้าอื่นในระบบ (ทศนิยม 2 ตำแหน่งเสมอ)
const formatMoney = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

// 🔄 เมื่อสลับแท็บ ให้เคลียร์ค่าที่เลือกไว้ เพื่อไม่ให้ส่ง id ค้างจาก tab ก่อน
const switchTab = (tab: 'expense' | 'income' | 'transfer') => {
  activeTab.value = tab;
  form.value.account_id = '';
  form.value.category_id = '';
  form.value.from_account_id = '';
  form.value.to_account_id = '';
};

const handleSubmit = async () => {
  if (activeTab.value === 'transfer') {
    if (form.value.from_account_id === form.value.to_account_id) {
      return Swal.fire('ห๊ะ!', 'จะโอนเข้ากระเป๋าตัวเองทำไมครับพี่!', 'warning');
    }
  }

  // ✅ ป้องกันกรอกจำนวนเงินติดลบ / ศูนย์
  if (!form.value.amount || Number(form.value.amount) <= 0) {
    return Swal.fire('ตรวจสอบจำนวนเงิน', 'กรุณากรอกจำนวนเงินที่มากกว่า 0', 'warning');
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
        slip_image_url: form.value.slip_image_url || undefined,
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
  } catch (error: unknown) {
    Swal.fire('พัง!', error instanceof Error ? error.message : 'บันทึกรายการไม่สำเร็จ', 'error');
  } finally {
    isSubmitting.value = false;
  }
};

onMounted(() => {
  fetchInitData();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader eyebrow="New Transaction" title="บันทึกรายการเงิน">
      <template #actions>
        <RouterLink to="/finance/transactions" class="btn-ghost-ui" title="กลับหน้าประวัติ">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าประวัติ
        </RouterLink>
      </template>
    </PageHeader>

    <!-- สถานะโหลด / ผิดพลาด / ยังไม่มีกระเป๋าเงิน -->
    <SkeletonRows v-if="isLoading" :rows="4" height="h-14" />
    <StateBlock v-else-if="hasError" variant="error" @retry="fetchInitData" />
    <StateBlock
      v-else-if="!accounts.length"
      variant="empty"
      title="ยังไม่มีกระเป๋าเงิน"
      hint="เพิ่มกระเป๋าเงินได้ที่หน้าตั้งค่าการเงินก่อนบันทึกรายการ"
    />

    <template v-else>
      <!-- เลือกประเภท: segmented ขอบบาง -->
      <div class="flex gap-1 rounded-xl border border-stone-200 bg-stone-50 p-1">
        <button
          v-for="tab in tabs"
          :key="tab"
          type="button"
          class="flex-1 rounded-lg px-2 py-2.5 text-sm font-bold transition-colors active:scale-[0.97]"
          :class="
            activeTab === tab
              ? 'border border-stone-200 bg-white text-brand-700'
              : 'border border-transparent text-stone-500 hover:text-stone-800'
          "
          :aria-pressed="activeTab === tab"
          @click="switchTab(tab)"
        >
          <span v-if="tab === 'expense'"><i class="bi bi-arrow-up-right me-1" aria-hidden="true"></i>รายจ่าย</span>
          <span v-if="tab === 'income'"><i class="bi bi-arrow-down-left me-1" aria-hidden="true"></i>รายรับ</span>
          <span v-if="tab === 'transfer'"><i class="bi bi-arrow-left-right me-1" aria-hidden="true"></i>โอนเงิน</span>
        </button>
      </div>

      <div class="page-card p-4 sm:p-6">
        <form class="space-y-4" @submit.prevent="handleSubmit">
          <!-- จำนวนเงิน -->
          <div>
            <label class="field-label" for="amount">จำนวนเงิน (฿)</label>
            <input
              id="amount"
              v-model="form.amount"
              class="field num font-display text-right !text-xl font-bold"
              type="number"
              inputmode="decimal"
              step="0.01"
              placeholder="0.00"
              required
              @focus="($event.target as HTMLInputElement).select()"
            />
          </div>

          <!-- บัญชีปลายทาง (ไม่ใช่โอน) -->
          <div v-if="activeTab !== 'transfer'">
            <label class="field-label" for="accountId">บัญชี/กระเป๋าเงิน</label>
            <select id="accountId" v-model="form.account_id" class="field" required>
              <option value="" disabled>-- เลือกบัญชี --</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
                {{ acc.account_name }} (เหลือ ฿{{ formatMoney(acc.balance) }})
              </option>
            </select>
          </div>

          <!-- บัญชีต้นทาง/ปลายทาง (โอนเงิน) -->
          <div v-if="activeTab === 'transfer'" class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
            <div>
              <label class="field-label" for="fromAccountId">โอนจาก</label>
              <select id="fromAccountId" v-model="form.from_account_id" class="field" required>
                <option value="" disabled>-- ต้นทาง --</option>
                <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.account_name }}</option>
              </select>
            </div>
            <div>
              <label class="field-label" for="toAccountId">เข้าสู่</label>
              <select id="toAccountId" v-model="form.to_account_id" class="field" required>
                <option value="" disabled>-- ปลายทาง --</option>
                <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.account_name }}</option>
              </select>
            </div>
          </div>

          <!-- หมวดหมู่ (ไม่ใช่โอน) -->
          <div v-if="activeTab !== 'transfer'">
            <label class="field-label" for="categoryId">หมวดหมู่</label>
            <select id="categoryId" v-model="form.category_id" class="field" required>
              <option value="" disabled>-- เลือกหมวดหมู่ --</option>
              <option v-for="cat in filteredCategories" :key="cat.id" :value="cat.id">
                {{ cat.category_name }}
              </option>
            </select>
          </div>

          <!-- รายละเอียด -->
          <div>
            <label class="field-label" for="description">รายละเอียด (บันทึกช่วยจำ)</label>
            <input
              id="description"
              v-model="form.description"
              class="field"
              type="text"
              placeholder="เช่น ซื้อเครื่องเขียน, ค่าขนมเพื่อน..."
              required
            />
          </div>

          <!-- สลิป (ไม่บังคับ) -->
          <div>
            <label class="field-label" for="slipUrl">URL รูปสลิปหลักฐาน (ถ้ามี)</label>
            <input
              id="slipUrl"
              v-model="form.slip_image_url"
              class="field"
              type="url"
              placeholder="https://..."
            />
          </div>

          <div class="border-t border-stone-100 pt-3 sm:pt-4">
            <button type="submit" class="btn-primary w-full py-3" :disabled="isSubmitting">
              <span
                v-if="isSubmitting"
                class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                aria-hidden="true"
              ></span>
              <span>{{ isSubmitting ? 'กำลังบันทึก...' : submitLabel }}</span>
            </button>
          </div>
        </form>
      </div>
    </template>
  </div>
</template>
