<script setup lang="ts">
/**
 * PeriodPicker — ตัวเลือกช่วงเวลากลางของงานการเงิน (ใช้ร่วมกัน F1/F2/F3)
 *
 * เปล่ง `PeriodValue` ออกไปแบบ discriminated union แล้ว **หน้าลูกเป็นคนแปลง**
 * เป็นพารามิเตอร์ของ endpoint ตัวเองผ่าน `toAsOf()` / `toRange()` ใน `@/utils/period`
 * → ตัวนี้ไม่รู้จัก endpoint ใด ๆ จึงไม่มีทางสร้าง period convention ที่สี่ขึ้นมา
 *
 * `modes` ต้องส่งเฉพาะโหมดที่หน้านั้น **แปลงได้จริง**:
 *   - งบทดลอง / งบดุล  → `['asof', 'month']`
 *   - งบกำไรขาดทุน      → `['month', 'range']`
 *   - งบประมาณ (F2)     → `['month', 'range']`
 *
 * @example
 * <PeriodPicker v-model="period" :modes="['asof', 'month']" />
 */
import { computed } from 'vue';
import {
  THAI_MONTHS,
  todayIso,
  todayThaiYearMonth,
  firstDayOfMonth,
  lastDayOfMonth,
  referenceDate,
  isRangeReversed,
  type PeriodMode,
  type PeriodValue,
} from '@/utils/period';

const props = withDefaults(
  defineProps<{
    modelValue: PeriodValue;
    /** โหมดที่หน้านี้รองรับ — ห้ามเปิดโหมดที่แปลงไม่ได้ */
    modes?: PeriodMode[];
    /** ป้ายกำกับด้านซ้ายของแถบ */
    label?: string;
  }>(),
  {
    modes: () => ['month', 'range', 'asof'] as PeriodMode[],
    label: 'ช่วงเวลา',
  },
);

const emit = defineEmits<{ 'update:modelValue': [PeriodValue] }>();

const MODE_LABELS: Record<PeriodMode, string> = {
  month: 'รายเดือน',
  range: 'ช่วงวันที่',
  asof: 'ณ วันที่',
};

const MODE_ICONS: Record<PeriodMode, string> = {
  month: 'bi-calendar-month',
  range: 'bi-calendar-range',
  asof: 'bi-calendar-check',
};

// ✨ ปีที่เลือก: ปีก่อนหน้า–ปีถัดไป + ปีที่กำลังดูอยู่ (เผื่อข้อมูลเก่าที่หลุดช่วง)
// [TIMEZONE] "ปีปัจจุบัน" ต้องเป็นปีไทย ไม่ใช่ปีของอุปกรณ์ (ดู utils/period.todayThaiYearMonth)
const yearOptions = computed(() => {
  const currentYear = todayThaiYearMonth().year;
  const years = new Set([currentYear - 1, currentYear, currentYear + 1]);
  if (props.modelValue.mode === 'month') years.add(props.modelValue.year);
  return [...years].sort((a, b) => a - b);
});

const isReversed = computed(() => isRangeReversed(props.modelValue));

/** สลับโหมดโดยยกค่าที่ผู้ใช้ตั้งไว้ไปด้วย แทนที่จะรีเซ็ตเป็น "วันนี้" ทุกครั้ง */
const switchMode = (mode: PeriodMode) => {
  const current = props.modelValue;
  if (mode === current.mode) return;
  if (!props.modes.includes(mode)) return;

  const ref = referenceDate(current);
  if (mode === 'month') {
    emit('update:modelValue', { mode: 'month', month: ref.month, year: ref.year });
  } else if (mode === 'range') {
    emit('update:modelValue', {
      mode: 'range',
      startDate: firstDayOfMonth(ref.year, ref.month),
      endDate: lastDayOfMonth(ref.year, ref.month),
    });
  } else {
    emit('update:modelValue', { mode: 'asof', asOfDate: lastDayOfMonth(ref.year, ref.month) });
  }
};

// --- getters/setters ของแต่ละโหมด (คืนค่าเป็น PeriodValue ก้อนใหม่เสมอ ไม่ mutate) ---

const month = computed({
  // fallback ใช้เมื่อ mode ไม่ใช่ 'month' (ปัจจุบัน template ยังไม่เรนเดอร์ช่องนี้ในโหมดอื่น)
  // → ยังต้องเป็น "เดือนไทย" ไว้ก่อน เผื่อวันหลังมีคนเอาไปใช้  (ดู utils/period.todayThaiYearMonth)
  get: () => (props.modelValue.mode === 'month' ? props.modelValue.month : todayThaiYearMonth().month),
  set: (value: number) =>
    emit('update:modelValue', {
      mode: 'month',
      month: Number(value),
      year: props.modelValue.mode === 'month' ? props.modelValue.year : todayThaiYearMonth().year,
    }),
});

const year = computed({
  get: () => (props.modelValue.mode === 'month' ? props.modelValue.year : todayThaiYearMonth().year),
  set: (value: number) =>
    emit('update:modelValue', {
      mode: 'month',
      year: Number(value),
      month: props.modelValue.mode === 'month' ? props.modelValue.month : todayThaiYearMonth().month,
    }),
});

const startDate = computed({
  get: () => (props.modelValue.mode === 'range' ? props.modelValue.startDate : todayIso()),
  set: (value: string) => {
    if (props.modelValue.mode !== 'range') return;
    emit('update:modelValue', { mode: 'range', startDate: value, endDate: props.modelValue.endDate });
  },
});

const endDate = computed({
  get: () => (props.modelValue.mode === 'range' ? props.modelValue.endDate : todayIso()),
  set: (value: string) => {
    if (props.modelValue.mode !== 'range') return;
    emit('update:modelValue', { mode: 'range', startDate: props.modelValue.startDate, endDate: value });
  },
});

const asOfDate = computed({
  get: () => (props.modelValue.mode === 'asof' ? props.modelValue.asOfDate : todayIso()),
  set: (value: string) => {
    if (props.modelValue.mode !== 'asof') return;
    emit('update:modelValue', { mode: 'asof', asOfDate: value });
  },
});
</script>

<template>
  <div class="page-card p-3 sm:p-4">
    <div class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:gap-4">
      <!-- สลับโหมด: pill ทึบสี (แบบเดียวกับ AddTask) ไม่ใช่เส้นใต้ เพราะเป็น "สวิตช์" ไม่ใช่แท็บเนื้อหา -->
      <div class="min-w-0 sm:min-w-[16rem]">
        <p class="field-label mb-1.5">{{ label }}</p>
        <div class="flex items-center gap-1" role="group" :aria-label="label">
          <button
            v-for="m in modes"
            :key="m"
            type="button"
            :aria-pressed="modelValue.mode === m"
            class="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl px-2 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="
              modelValue.mode === m
                ? 'bg-brand-700 text-white'
                : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'
            "
            @click="switchMode(m)"
          >
            <i class="bi text-base" :class="MODE_ICONS[m]" aria-hidden="true"></i>
            <span class="truncate">{{ MODE_LABELS[m] }}</span>
          </button>
        </div>
      </div>

      <!-- ตัวเลือกของโหมดที่ใช้งานอยู่ -->
      <div class="flex flex-wrap items-end gap-2 sm:gap-3">
        <template v-if="modelValue.mode === 'month'">
          <div>
            <label class="field-label" for="period-month">เดือน</label>
            <div class="relative">
              <select id="period-month" v-model="month" class="field appearance-none pe-9 sm:w-40">
                <option v-for="(name, i) in THAI_MONTHS" :key="name" :value="i + 1">{{ name }}</option>
              </select>
              <i
                class="bi bi-chevron-down pointer-events-none absolute inset-y-0 end-3 flex items-center text-xs text-stone-400"
                aria-hidden="true"
              ></i>
            </div>
          </div>
          <div>
            <label class="field-label" for="period-year">ปี (พ.ศ.)</label>
            <div class="relative">
              <select id="period-year" v-model="year" class="field appearance-none pe-9 sm:w-32">
                <option v-for="y in yearOptions" :key="y" :value="y">{{ y + 543 }}</option>
              </select>
              <i
                class="bi bi-chevron-down pointer-events-none absolute inset-y-0 end-3 flex items-center text-xs text-stone-400"
                aria-hidden="true"
              ></i>
            </div>
          </div>
        </template>

        <template v-else-if="modelValue.mode === 'range'">
          <div>
            <label class="field-label" for="period-start">ตั้งแต่</label>
            <input
              id="period-start"
              v-model="startDate"
              type="date"
              class="field sm:w-44"
              :class="isReversed ? 'border-red-300 focus:ring-red-500/15' : ''"
            />
          </div>
          <div>
            <label class="field-label" for="period-end">ถึง</label>
            <input
              id="period-end"
              v-model="endDate"
              type="date"
              class="field sm:w-44"
              :class="isReversed ? 'border-red-300 focus:ring-red-500/15' : ''"
            />
          </div>
        </template>

        <template v-else>
          <div>
            <label class="field-label" for="period-asof">ณ วันที่</label>
            <input id="period-asof" v-model="asOfDate" type="date" class="field sm:w-44" />
          </div>
        </template>
      </div>
    </div>

    <p v-if="isReversed" class="mt-2 text-xs font-bold text-red-600">
      วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด
    </p>
  </div>
</template>
