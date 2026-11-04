<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { FinanceService } from '@/services/finance';
import type { Account, Category } from '@/types/finance';
import { useAuthStore } from '@/stores/auth';
import { downloadBlob } from '@/utils/download';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import AppTabs from '@/components/ui/AppTabs.vue';
import type { AppTabItem } from '@/components/ui/AppTabs.vue';
import { useDialog } from '@/composables/useDialog';

const authStore = useAuthStore();
const router = useRouter();
const dialog = useDialog();

const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const activeTab = ref<'expense' | 'income' | 'transfer'>('expense');
const isLoading = ref(true);
const isSubmitting = ref(false);

// รายการแท็บสำหรับ segmented control (พิมพ์ type ไว้ให้ template รู้จัก union โดยไม่ต้อง cast)
const TAB_VALUES: readonly ('expense' | 'income' | 'transfer')[] = ['expense', 'income', 'transfer'];
const tabs: AppTabItem[] = [
  { value: 'expense', label: 'รายจ่าย' },
  { value: 'income', label: 'รายรับ' },
  { value: 'transfer', label: 'โอนเงิน' },
];

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
  slip_image_url: '',
  // 🧾 [F6] ข้อมูลที่พิมพ์ลงบน "ใบสำคัญจ่าย" / "ใบรับเงิน"
  payee_name: '',
  approver_name: '',
  attachment_count: 0
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
    void dialog.alert('เกิดข้อผิดพลาด', 'ไม่สามารถโหลดข้อมูลเริ่มต้นได้', 'error');
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

/**
 * 🧾 ป้ายของช่อง "อีกฝ่าย" ของรายการ
 *
 * 🔴 ชื่อเดียวกันแต่ความหมายกลับกันตามชนิดรายการ — และ **บังคับทั้งสองฝั่ง** เพราะ
 *    ทั้งใบสำคัญจ่าย (`PV-`) และใบรับเงิน (`INC-`) พิมพ์ชื่อนั้นลงบนกระดาษที่แจกจริง
 *    ⇒ ไม่มีคำตอบที่ถูกสำหรับ "ปล่อยว่าง" (ฝั่ง backend ตอบ 400 ถ้าว่าง — ดู
 *    `FinanceService.add_transaction`)
 */
const payeeLabel = computed(() =>
  activeTab.value === 'income' ? 'ผู้จ่ายเงิน/แหล่งที่มา' : 'ผู้เบิก/ผู้รับเงิน'
);

// 🔄 เมื่อสลับแท็บ ให้เคลียร์ค่าที่เลือกไว้ เพื่อไม่ให้ส่ง id ค้างจาก tab ก่อน
//    ⚠️ `payee_name` ต้องเคลียร์ด้วย — ชื่อที่กรอกในแท็บรายจ่าย ("ผู้เบิก") จะกลายเป็น
//       "ผู้จ่ายเงิน" ทันทีที่สลับแท็บ ซึ่งเป็นคนละคนกันได้
const switchTab = (tab: 'expense' | 'income' | 'transfer') => {
  activeTab.value = tab;
  form.value.account_id = '';
  form.value.category_id = '';
  form.value.from_account_id = '';
  form.value.to_account_id = '';
  form.value.payee_name = '';
  form.value.approver_name = '';
  form.value.attachment_count = 0;
};

const setTab = (value: string) => {
  if (!TAB_VALUES.includes(value as 'expense' | 'income' | 'transfer')) return;
  switchTab(value as 'expense' | 'income' | 'transfer');
};

/**
 * 🖨️ แจ้งผลสำเร็จ + เสนอโหลด PDF ของเอกสารที่เพิ่งออกให้
 *
 * ถ้าไม่มีเลขเอกสาร (เช่นเส้นทางที่ไม่ได้ออกเอกสาร) จะถอยไปใช้กล่องสำเร็จแบบเดิม
 * ⚠️ ข้อความใช้ `text` ไม่ใช่ `html` — เลขที่เอกสารมาจากเซิร์ฟเวอร์ อย่าให้มันกลายเป็นมาร์กอัป
 */
const offerDocumentDownload = async (
  receiptNo: string | null,
  docType: string | null,
  docTypeLabel: string | null
) => {
  if (!receiptNo) {
    await dialog.fire({
      icon: 'success',
      title: 'บันทึกสำเร็จ!',
      text: 'รายการของคุณถูกบันทึกเรียบร้อยแล้ว',
      timer: 1500
    });
    return;
  }

  const answer = await dialog.confirm(
    'บันทึกสำเร็จ!',
    `ออก${docTypeLabel ?? 'เอกสาร'} เลขที่ ${receiptNo} แล้ว`,
    { icon: 'success', confirmButtonText: 'ดาวน์โหลด PDF', cancelButtonText: 'ปิด' }
  );

  if (!answer.isConfirmed) return;

  try {
    const blob = await FinanceService.downloadReceiptPdf(currentServerId, receiptNo);
    downloadBlob(blob, `${docType ?? 'document'}-${receiptNo}.pdf`);
  } catch (error: unknown) {
    // 502 = Gotenberg ล่ม (ไม่ใช่ 500 ของโค้ดเรา) — service แปลงเป็นข้อความไทยให้แล้ว
    // 🔑 รายการถูกบันทึกไปแล้ว ⇒ ต้องบอกให้ชัด ไม่งั้นผู้ใช้จะกดบันทึกซ้ำ
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      `${error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง'} — รายการถูกบันทึกแล้ว สามารถโหลดเอกสารซ้ำได้ที่ทะเบียนเอกสาร`,
      'error'
    );
  }
};

const handleSubmit = async () => {
  if (activeTab.value === 'transfer') {
    if (form.value.from_account_id === form.value.to_account_id) {
      void dialog.alert('ห๊ะ!', 'จะโอนเข้ากระเป๋าตัวเองทำไมครับพี่!', 'warning');
      return;
    }
  }

  // ✅ ป้องกันกรอกจำนวนเงินติดลบ / ศูนย์
  if (!form.value.amount || Number(form.value.amount) <= 0) {
    void dialog.alert('ตรวจสอบจำนวนเงิน', 'กรุณากรอกจำนวนเงินที่มากกว่า 0', 'warning');
    return;
  }

  // 🧾 ตรวจ "อีกฝ่าย" ที่ฝั่งจอก่อน เพื่อให้ได้ข้อความที่บอกทางออกทันที
  //    (backend บังคับซ้ำที่ชั้น service — ด่านนี้ไม่ใช่ด่านเดียว)
  if (activeTab.value !== 'transfer' && !form.value.payee_name.trim()) {
    void dialog.alert(
      `ตรวจสอบ${payeeLabel.value}`,
      'กรุณาระบุชื่อคู่กรณี เพราะชื่อนี้พิมพ์ลงบนเอกสารที่ออกให้',
      'warning'
    );
    return;
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
      await dialog.fire({
        icon: 'success',
        title: 'บันทึกสำเร็จ!',
        text: 'รายการของคุณถูกบันทึกเรียบร้อยแล้ว',
        timer: 1500
      });
    } else {
      const result = await FinanceService.addTransaction(currentServerId, {
        account_id: Number(form.value.account_id),
        category_id: Number(form.value.category_id),
        amount: form.value.amount,
        description: form.value.description,
        transaction_type: activeTab.value,
        slip_image_url: form.value.slip_image_url || undefined,
        payee_name: form.value.payee_name.trim(),
        // 🖊️ ผู้อนุมัติ/เอกสารแนบเป็นเรื่องของ "ใบสำคัญจ่าย" ⇒ แท็บรายรับไม่ส่งไป
        approver_name: activeTab.value === 'expense' ? form.value.approver_name.trim() || null : null,
        attachment_count: activeTab.value === 'expense' ? Number(form.value.attachment_count) || 0 : 0,
        user_name: currentUserName
      });

      // 🖨️ เสนอทางโหลดเอกสารที่เพิ่งออก — ใช้เส้นทาง PDF เดิมของทะเบียนเอกสาร
      //    (ไม่เขียนเส้นทางใหม่ · ถ้า Gotenberg ล่ม ผู้ใช้ยังบันทึกสำเร็จไปแล้ว)
      await offerDocumentDownload(result.receipt_no ?? null, result.doc_type ?? null, result.doc_type_label ?? null);
    }

    router.push('/finance/transactions');
  } catch (error: unknown) {
    void dialog.alert(
      'พัง!',
      error instanceof Error ? error.message : 'บันทึกรายการไม่สำเร็จ',
      'error',
    );
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
    <PageIntro></PageIntro>

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
      <AppTabs
        :model-value="activeTab"
        :tabs="tabs"
        group-label="ประเภทของรายการ"
        variant="segmented"
        @update:model-value="setTab"
      />

      <div class="page-card p-4 sm:p-6">
        <form class="space-y-4" @submit.prevent="handleSubmit">
          <!-- จำนวนเงิน -->
          <div>
            <label class="field-label" for="amount">จำนวนเงิน (฿)</label>
            <input
              id="amount"
              v-model="form.amount"
              class="field num text-right !text-xl font-bold"
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

          <!-- 🧾 คู่กรณีของรายการ — พิมพ์ลงบนใบสำคัญจ่าย/ใบรับเงิน (บังคับ) -->
          <div v-if="activeTab !== 'transfer'">
            <label class="field-label" for="payeeName">
              {{ payeeLabel }} <span class="text-danger-600">*</span>
            </label>
            <input
              id="payeeName"
              v-model="form.payee_name"
              class="field"
              type="text"
              maxlength="150"
              :placeholder="
                activeTab === 'income' ? 'เช่น ผู้ปกครองนายสมชาย / งานวันเกิด' : 'เช่น นายสมชาย ใจดี'
              "
              required
            />
            <p class="mt-1 text-xs text-ink-3">
              ชื่อนี้จะพิมพ์อยู่บน{{ activeTab === 'income' ? 'ใบรับเงิน' : 'ใบสำคัญจ่าย' }}ที่ออกให้
            </p>
          </div>

          <!-- 🖊️ ผู้อนุมัติ + เอกสารแนบ — เฉพาะใบสำคัญจ่าย (ฝั่งรายรับไม่มีช่องนี้บนกระดาษ) -->
          <div v-if="activeTab === 'expense'" class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
            <div>
              <label class="field-label" for="approverName">ผู้อนุมัติ (ถ้ามี)</label>
              <input
                id="approverName"
                v-model="form.approver_name"
                class="field"
                type="text"
                maxlength="150"
                placeholder="เช่น หัวหน้าห้อง"
              />
            </div>
            <div>
              <label class="field-label" for="attachmentCount">เอกสารแนบ (ใบ)</label>
              <input
                id="attachmentCount"
                v-model.number="form.attachment_count"
                class="field num text-right"
                type="number"
                inputmode="numeric"
                min="0"
                step="1"
                placeholder="0"
              />
              <p class="mt-1 text-xs text-ink-3">บิลเงินสด/ใบเสร็จจากร้านค้าที่แนบมาด้วย</p>
            </div>
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

          <div class="border-t border-line pt-3 sm:pt-4">
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
