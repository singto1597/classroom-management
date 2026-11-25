<script setup lang="ts">
/**
 * ExpenseLineEditor — 1 บรรทัดของใบสำคัญจ่าย (FIN-V2 / P4.3)
 *
 * 🔑 **Presentational เท่านั้น** — ไม่เรียก API, ไม่ตรวจว่า "ทั้งใบผ่านหรือไม่"
 *    การ validate (≥1 บรรทัด, category/wallet ครบ, ยอดรวม > 0) อยู่ที่
 *    `ExpenseVoucherCreate.vue` ⇒ คอมโพเนนต์นี้ใช้ซ้ำได้กับรายรับ (P4.5) โดยไม่ลาก logic
 *
 * 🚫 ห้าม `formatMoney` ในช่อง input — ใช้เฉพาะตอนแสดง (ตัวเลขที่มี `฿`/`,` จะถูก
 *    number input ตีความไม่ได้ และผู้ใช้พิมพ์ต่อไม่ได้)
 * ⚠️ `v-model.number` บน prop จะ mutate prop ⇒ ทุกช่องใช้ `:value` + `@input` แล้ว emit
 *    ออบเจ็กต์ใหม่ทั้งก้อน (ตาม style `modelValue` + `update:modelValue` ของ repo)
 *
 * @example
 * <ExpenseLineEditor
 *   v-model="line"
 *   :categories="expenseCategories"
 *   :budgets="budgets"
 *   :accounts="accounts"
 *   :index="i"
 *   :can-remove="lines.length > 1"
 *   @remove="removeLine(i)"
 * />
 */
import { computed } from 'vue';
import type {
  Account,
  Budget,
  Category,
  ExpenseVoucherLinePayload,
  FundingSource,
  ReceiptStatus,
} from '@/types/finance';

const props = withDefaults(
  defineProps<{
    modelValue: ExpenseVoucherLinePayload;
    categories: Category[];
    budgets: Budget[];
    accounts: Account[];
    /** ลำดับบนจอ (เริ่ม 1) — ใช้ทำ label/aria ให้ไม่ซ้ำกัน */
    index: number;
    canRemove: boolean;
    /** กระเป๋าหัวใบ — แสดงเป็นคำใบ้ใต้ตัวเลือกกระเป๋า */
    defaultWalletAccountId?: number;
  }>(),
  { defaultWalletAccountId: 0 },
);

const emit = defineEmits<{
  'update:modelValue': [ExpenseVoucherLinePayload];
  remove: [];
}>();

// 🧾 คำที่ผู้ใช้เห็น — ตรงกับ `docs/glossary.md` และ brief P4.3
const RECEIPT_STATUS_OPTIONS: { value: ReceiptStatus; label: string }[] = [
  { value: 'attached', label: 'มีใบเสร็จ' },
  { value: 'paper', label: 'ใบเสร็จกระดาษ' },
  { value: 'none', label: 'ไม่มีใบเสร็จ (ออก CERT)' },
];

const FUNDING_SOURCE_OPTIONS: { value: FundingSource; label: string }[] = [
  { value: 'room_fund', label: 'เงินห้อง' },
  { value: 'pass_through', label: 'เงินผ่านบัญชี' },
];

/** งบต้องกรองตามหมวด — งบของหมวดอื่นเลือกไม่ได้ */
const filteredBudgets = computed(() =>
  props.budgets.filter((b) => b.category_id === props.modelValue.category_id),
);

const isCertLine = computed(() => props.modelValue.receipt_status === 'none');

const patch = (partial: Partial<ExpenseVoucherLinePayload>) => {
  emit('update:modelValue', { ...props.modelValue, ...partial });
};

const onDescriptionInput = (event: Event) => {
  patch({ description: (event.target as HTMLInputElement).value });
};

/**
 * จำนวนเงิน — เก็บเป็น `number` (ไม่ใช่ string) และไม่ปัดเศษเอง
 * 🔴 ค่าว่าง = 0 ไม่ใช่ NaN — `Number('')` ได้ 0 อยู่แล้ว แต่ `Number('abc')` ได้ NaN
 *    ⇒ กัน NaN ไม่ให้หลุดเข้า payload (JSON.stringify(NaN) = null)
 */
const onAmountInput = (event: Event) => {
  const raw = (event.target as HTMLInputElement).value;
  const value = Number(raw);
  patch({ amount: raw === '' || !Number.isFinite(value) ? 0 : value });
};

/**
 * เปลี่ยนหมวด → ถ้างบเดิมไม่ใช่ของหมวดใหม่ ให้ล้างทิ้ง (gotcha P4.3)
 * ไม่งั้นฟอร์มส่ง `budget_id` ของอีกหมวดไป แล้ว backend ตอบ 400
 */
const onCategoryChange = (event: Event) => {
  const nextCategoryId = Number((event.target as HTMLSelectElement).value);
  const currentBudgetId = props.modelValue.budget_id ?? null;
  const budgetStillValid =
    currentBudgetId === null ||
    props.budgets.some(
      (b) => b.id === currentBudgetId && b.category_id === nextCategoryId,
    );
  patch({
    category_id: nextCategoryId,
    budget_id: budgetStillValid ? currentBudgetId : null,
  });
};

const onBudgetChange = (event: Event) => {
  const raw = (event.target as HTMLSelectElement).value;
  patch({ budget_id: raw === '' ? null : Number(raw) });
};

/** เปลี่ยนกระเป๋า — หน้าลูกเป็นผู้ตัดสินว่า "ผู้ใช้แตะแล้ว" (walletTouched) */
const onWalletChange = (event: Event) => {
  patch({ wallet_account_id: Number((event.target as HTMLSelectElement).value) });
};

/**
 * เปลี่ยนสถานะใบเสร็จ — ออกจาก `paper` ต้องล้างจำนวนใบกระดาษเป็น 0 เสมอ
 * ไม่งั้นค่าค้างจากสถานะก่อนหน้าจะถูกพิมพ์ลงเอกสาร (gotcha P4.3)
 */
const onReceiptStatusChange = (event: Event) => {
  const status = (event.target as HTMLSelectElement).value as ReceiptStatus;
  patch({
    receipt_status: status,
    paper_bill_count: status === 'paper' ? props.modelValue.paper_bill_count : 0,
  });
};

const onPaperCountInput = (event: Event) => {
  const value = Math.trunc(Number((event.target as HTMLInputElement).value));
  patch({ paper_bill_count: Number.isFinite(value) && value > 0 ? value : 0 });
};

const onFundingSourceChange = (event: Event) => {
  patch({ funding_source: (event.target as HTMLSelectElement).value as FundingSource });
};

const onAttachmentInput = (event: Event) => {
  const raw = (event.target as HTMLInputElement).value;
  patch({ attachment_placeholder: raw.trim() === '' ? null : raw });
};
</script>

<template>
  <div class="rounded-card border border-line bg-surface p-3 sm:p-4" data-test="line-editor">
    <div class="mb-3 flex items-center justify-between gap-2">
      <p class="flex min-w-0 items-center gap-2 text-sm font-bold text-ink-1">
        <span class="shrink-0">บรรทัดที่ {{ index }}</span>
        <!-- 🧾 บอกให้เห็นตั้งแต่ยังไม่บันทึกว่าบรรทัดนี้จะทำให้ออก CERT -->
        <span
          v-if="isCertLine"
          class="chip shrink-0 bg-warn-50 text-warn-700"
          data-test="cert-badge"
        >
          จะอยู่ใน CERT
        </span>
      </p>
      <button
        v-if="canRemove"
        type="button"
        class="btn-ghost-ui shrink-0 !px-2 !py-1 text-danger-600"
        :aria-label="`ลบบรรทัดที่ ${index}`"
        data-test="line-remove"
        @click="emit('remove')"
      >
        <i class="bi bi-trash3" aria-hidden="true"></i>
        ลบ
      </button>
    </div>

    <div class="grid grid-cols-1 gap-3 sm:grid-cols-12 sm:gap-4">
      <!-- 📝 คำอธิบาย -->
      <div class="sm:col-span-8">
        <label class="field-label" :for="`line-${index}-desc`">
          รายละเอียด <span class="text-danger-600">*</span>
        </label>
        <input
          :id="`line-${index}-desc`"
          :value="modelValue.description"
          type="text"
          class="field"
          maxlength="300"
          placeholder="เช่น กระดาษ A4, ค่าขนส่ง"
          data-test="line-description"
          @input="onDescriptionInput"
        />
      </div>

      <!-- 💰 จำนวนเงิน -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-amount`">
          จำนวนเงิน (฿) <span class="text-danger-600">*</span>
        </label>
        <input
          :id="`line-${index}-amount`"
          :value="modelValue.amount"
          type="number"
          inputmode="decimal"
          min="0.01"
          step="0.01"
          class="field num text-right"
          placeholder="0.00"
          data-test="line-amount"
          @input="onAmountInput"
        />
      </div>

      <!-- 🗂️ หมวดรายจ่าย -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-category`">
          หมวดรายจ่าย <span class="text-danger-600">*</span>
        </label>
        <select
          :id="`line-${index}-category`"
          :value="modelValue.category_id || ''"
          class="field"
          data-test="line-category"
          @change="onCategoryChange"
        >
          <option value="" disabled>— เลือกหมวด —</option>
          <option v-for="cat in categories" :key="cat.id" :value="cat.id">
            {{ cat.category_name }}
          </option>
        </select>
      </div>

      <!-- 📊 งบ (ไม่บังคับ กรองตามหมวด) -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-budget`">งบประมาณ (ถ้ามี)</label>
        <select
          :id="`line-${index}-budget`"
          :value="modelValue.budget_id ?? ''"
          class="field"
          :disabled="!modelValue.category_id || filteredBudgets.length === 0"
          data-test="line-budget"
          @change="onBudgetChange"
        >
          <option value="">— ไม่งบ —</option>
          <option v-for="budget in filteredBudgets" :key="budget.id" :value="budget.id">
            {{ budget.category_name }} · {{ budget.start_date }} – {{ budget.end_date }}
          </option>
        </select>
      </div>

      <!-- 🏦 กระเป๋าที่จ่ายจริง -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-wallet`">
          จ่ายจากกระเป๋า <span class="text-danger-600">*</span>
        </label>
        <select
          :id="`line-${index}-wallet`"
          :value="modelValue.wallet_account_id || ''"
          class="field"
          data-test="line-wallet"
          @change="onWalletChange"
        >
          <option value="" disabled>— เลือกกระเป๋า —</option>
          <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
            {{ acc.account_name }}
          </option>
        </select>
        <p
          v-if="defaultWalletAccountId && modelValue.wallet_account_id === defaultWalletAccountId"
          class="mt-1 text-xs text-ink-3"
        >
          ตามกระเป๋าหัวใบ
        </p>
      </div>

      <!-- 🧾 สถานะใบเสร็จ -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-status`">หลักฐานการรับเงิน</label>
        <select
          :id="`line-${index}-status`"
          :value="modelValue.receipt_status"
          class="field"
          data-test="line-status"
          @change="onReceiptStatusChange"
        >
          <option v-for="opt in RECEIPT_STATUS_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>

      <!-- 📎 จำนวนใบกระดาษ — เปิดเฉพาะ paper -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-paper`">ใบกระดาษ (ใบ)</label>
        <input
          :id="`line-${index}-paper`"
          :value="modelValue.paper_bill_count"
          type="number"
          inputmode="numeric"
          min="0"
          step="1"
          class="field num text-right"
          :disabled="modelValue.receipt_status !== 'paper'"
          data-test="line-paper-count"
          @input="onPaperCountInput"
        />
        <p class="mt-1 text-xs text-ink-3">
          {{ modelValue.receipt_status === 'paper' ? 'นับเฉพาะใบกระดาษที่แนบมา' : 'ใช้เมื่อเลือก "ใบเสร็จกระดาษ"' }}
        </p>
      </div>

      <!-- 💼 แหล่งเงิน -->
      <div class="sm:col-span-4">
        <label class="field-label" :for="`line-${index}-funding`">แหล่งเงิน</label>
        <select
          :id="`line-${index}-funding`"
          :value="modelValue.funding_source"
          class="field"
          data-test="line-funding-source"
          @change="onFundingSourceChange"
        >
          <option v-for="opt in FUNDING_SOURCE_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>

      <!-- 🗒️ หมายเหตุแนบ -->
      <div class="sm:col-span-8">
        <label class="field-label" :for="`line-${index}-attachment`">หมายเหตุเอกสารแนบ (ถ้ามี)</label>
        <input
          :id="`line-${index}-attachment`"
          :value="modelValue.attachment_placeholder ?? ''"
          type="text"
          class="field"
          maxlength="200"
          placeholder="เช่น ใบเสร็จจากร้านวัสดุ เลขที่ 1234"
          data-test="line-attachment"
          @input="onAttachmentInput"
        />
      </div>
    </div>
  </div>
</template>
