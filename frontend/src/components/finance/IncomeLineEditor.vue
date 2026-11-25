<script setup lang="ts">
/**
 * IncomeLineEditor — 1 บรรทัดของใบรับเงิน (FIN-V2 / P4.5)
 *
 * 🔑 **Presentational เท่านั้น** — ไม่เรียก API, ไม่ validate ทั้งใบ
 *    (การตรวจ ≥1 บรรทัด/ยอดรวม/หมวด อยู่ที่ `IncomeBatchCreate.vue`)
 *
 * 🔴 **ไม่มีช่องกระเป๋าต่อบรรทัดโดยเจตนา** — schema ของ P4.4 มีกระเป๋าเดียวต่อใบ
 *    (`finance_income_batches.wallet_account_id`) ⇒ เพิ่มช่อง "เผื่ออนาคต" จะทำให้
 *    ผู้ใช้เข้าใจผิดว่าจ่ายเข้าหลายกระเป๋าได้
 * 🔴 ไม่มีงบ/สถานะใบเสร็จ/แหล่งเงิน — คอลัมน์เหล่านี้ไม่มีใน INC
 *
 * 🚫 ห้าม `formatMoney` ในช่องกรอก — ตัวเลขที่มี `฿`/`,` ถูก number input ตีความไม่ได้
 */
import type { Category, IncomeBatchLinePayload } from '@/types/finance';

const props = defineProps<{
  modelValue: IncomeBatchLinePayload;
  categories: Category[];
  /** ลำดับบนจอ (เริ่ม 1) — ใช้ทำ label/aria ให้ไม่ซ้ำกัน */
  index: number;
  canRemove: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [IncomeBatchLinePayload];
  remove: [];
}>();

const patch = (partial: Partial<IncomeBatchLinePayload>) => {
  emit('update:modelValue', { ...props.modelValue, ...partial });
};

const onDescriptionInput = (event: Event) => {
  patch({ description: (event.target as HTMLInputElement).value });
};

/** ค่าว่าง/ไม่ใช่ตัวเลข = 0 — กัน NaN หลุดเข้า payload (`JSON.stringify(NaN) = null`) */
const onAmountInput = (event: Event) => {
  const raw = (event.target as HTMLInputElement).value;
  const value = Number(raw);
  patch({ amount: raw === '' || !Number.isFinite(value) ? 0 : value });
};

const onCategoryChange = (event: Event) => {
  patch({ category_id: Number((event.target as HTMLSelectElement).value) });
};
</script>

<template>
  <div class="rounded-card border border-line bg-surface p-3 sm:p-4" data-test="line-editor">
    <div class="mb-3 flex items-center justify-between gap-2">
      <p class="text-sm font-bold text-ink-1">บรรทัดที่ {{ index }}</p>
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
      <div class="sm:col-span-6">
        <label class="field-label" :for="`income-line-${index}-desc`">
          รายละเอียด <span class="text-danger-600">*</span>
        </label>
        <input
          :id="`income-line-${index}-desc`"
          :value="modelValue.description"
          type="text"
          class="field"
          maxlength="300"
          placeholder="เช่น เงินสนับสนุนจากผู้ปกครอง, ดอกเบี้ย"
          data-test="line-description"
          @input="onDescriptionInput"
        />
      </div>

      <!-- 💰 จำนวนเงิน -->
      <div class="sm:col-span-3">
        <label class="field-label" :for="`income-line-${index}-amount`">
          จำนวนเงิน (฿) <span class="text-danger-600">*</span>
        </label>
        <input
          :id="`income-line-${index}-amount`"
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

      <!-- 🗂️ หมวดรายรับ -->
      <div class="sm:col-span-3">
        <label class="field-label" :for="`income-line-${index}-category`">
          หมวดรายรับ <span class="text-danger-600">*</span>
        </label>
        <select
          :id="`income-line-${index}-category`"
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
    </div>
  </div>
</template>
