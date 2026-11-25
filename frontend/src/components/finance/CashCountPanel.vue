<script setup lang="ts">
/**
 * 💵 [FIN-V2 / P5.5] CashCountPanel — ช่องกรอก "เงินสดนับได้จริง" + ผลต่างสด ๆ
 *
 * 📌 ใช้ใน `MonthlyReportWizard` เท่านั้น (ทั้งโหมดกรอกและโหมดอ่านอย่างเดียวหลังปิดงบ)
 *
 * 🔴 ค่าที่ emit เป็น **string ที่ normalize แล้ว** (เลขล้วน + จุดเดียว + ทศนิยม ≤2)
 *    ห้ามแปลงเป็น number ที่นี่ — ผู้เรียกต้องส่งต่อเป็น string 2 ตำแหน่ง
 *    (`normalizeCashInput(...)` + เติม `.00`) ให้ backend ไม่งั้น floating point
 *    จะทำให้ backend เห็นผลต่าง `1e-12` แล้วตอบ 400 ทั้งที่ครูกรอกถูก
 *
 * 🎯 การเทียบ "ตรงหรือไม่" อยู่ที่ `utils/cashVariance.ts` (เกณฑ์เดียวกับ backend)
 *    ⇒ ตัวเลขบนป้ายกับที่ backend ตัดสินใช้สูตรเดียวกัน ไม่ใช่สองสูตรที่ต้องคอยแก้คู่กัน
 */
import { computed } from 'vue';

import { formatMoney } from '@/utils/money';
import {
  canFinalize,
  computeVariance,
  normalizeCashInput,
  varianceMessage,
} from '@/utils/cashVariance';

const model = defineModel<string>({ default: '' });

const props = withDefaults(
  defineProps<{
    /** ยอดเงินสดที่ **บัญชี** บอกว่าควรมี (backend คำนวณจาก snapshot) */
    expected: number;
    disabled?: boolean;
  }>(),
  { disabled: false },
);

const onInput = (event: Event) => {
  const target = event.target as HTMLInputElement;
  const normalized = normalizeCashInput(target.value);
  // 🛡️ เขียนค่าที่ล้างแล้วกลับเข้าช่องทันที — ถ้าปล่อย DOM แสดงตัวอักษรที่ถูกปฏิเสธ
  //    ผู้ใช้จะเห็นตัวเลขที่ไม่มีอยู่ใน model (พิมพ์ต่อแล้วได้ยอดที่ไม่ตรงกับที่เห็น)
  target.value = normalized;
  model.value = normalized;
};

const variance = computed(() => computeVariance(model.value, props.expected));
const isMatched = computed(() => canFinalize(variance.value));
const hasCounted = computed(() => model.value.trim() !== '');

const countedMoney = computed(() =>
  hasCounted.value ? formatMoney(Number(model.value) || 0) : '—',
);

const varianceTone = computed(() => {
  if (variance.value === null) return 'text-ink-3';
  return isMatched.value ? 'text-ok-700' : 'text-danger-600';
});
</script>

<template>
  <div class="space-y-3">
    <div>
      <label class="field-label" for="cash-count-input">เงินสดนับได้จริง (บาท)</label>
      <div class="relative">
        <input
          id="cash-count-input"
          class="field num pe-10"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          placeholder="0.00"
          :disabled="disabled"
          :value="model"
          :aria-invalid="hasCounted && !isMatched ? 'true' : undefined"
          @input="onInput"
        />
        <span
          class="pointer-events-none absolute inset-y-0 end-3 flex items-center text-sm text-ink-3"
          aria-hidden="true"
          >บาท</span
        >
      </div>
      <p class="mt-1 text-caption text-ink-3">
        กรอกยอดที่ตรวจนับจริง — จุดทศนิยมได้ไม่เกิน 2 ตำแหน่ง
      </p>
    </div>

    <dl class="grid gap-2 sm:grid-cols-3">
      <div class="rounded-control bg-canvas px-3 py-2.5">
        <dt class="text-caption text-ink-3">ควรเป็น (จากบัญชี)</dt>
        <dd class="num mt-0.5 font-bold text-ink-1">{{ formatMoney(expected) }}</dd>
      </div>
      <div class="rounded-control bg-canvas px-3 py-2.5">
        <dt class="text-caption text-ink-3">นับได้</dt>
        <dd class="num mt-0.5 font-bold" :class="hasCounted ? 'text-ink-1' : 'text-ink-3'">
          {{ countedMoney }}
        </dd>
      </div>
      <div class="rounded-control bg-canvas px-3 py-2.5">
        <dt class="text-caption text-ink-3">ผลต่าง</dt>
        <dd class="num mt-0.5 font-bold" :class="varianceTone">
          {{ variance === null ? '—' : formatMoney(variance) }}
        </dd>
      </div>
    </dl>

    <!-- 🗣️ ข้อความเดียวกันนี้ถูกใช้ในกล่องยืนยันด้วย ⇒ ห้ามประกอบเองที่หน้าจอ -->
    <p
      class="text-sm leading-relaxed"
      :class="hasCounted ? varianceTone : 'text-ink-3'"
      aria-live="polite"
    >
      {{ varianceMessage(model, expected) }}
    </p>
  </div>
</template>
