<script setup lang="ts">
/**
 * AppTabs — ตัวสลับหมวด/ตัวกรองภายในหน้าเดียว
 *
 * ใช้แค่สลับ "มุมมอง" ของเนื้อหาที่โหลดไว้แล้ว — ไม่โหลดแท็บเอง
 * ทุกปุ่มสูง ≥44px และบังคับทิศทางลูกศร/Home/End ได้ (roving tabindex)
 *
 * รูปแบบ
 *  - `underline` (ค่าเริ่มต้น) — แท็บขีดเส้นใต้แบบ PIRIvoice สำหรับสลับส่วนหลักของหน้า
 *  - `segmented` — ปุ่มพิลใช้พื้นที่น้อย เหมาะกับตัวกรองสั้น ๆ ในแถบเครื่องมือ
 *
 * @example
 * <AppTabs v-model="filter" :tabs="[
 *   { value: 'pending', label: 'ยังไม่เสร็จ', count: 8 },
 *   { value: 'done', label: 'เสร็จแล้ว', count: 3 },
 * ]" group-label="กรองสถานะงาน" />
 */
export interface AppTabItem {
  value: string;
  label: string;
  count?: number;
}

withDefaults(
  defineProps<{
    modelValue: string;
    tabs: readonly AppTabItem[];
    /** ชื่อกลุ่มสำหรับ screen reader (ส่งไปที่ `aria-label` ของแท็บลิสต์) */
    groupLabel: string;
    /** `underline` = แท็บหลักของหน้า · `segmented` = ตัวกรองแบบพิล */
    variant?: 'underline' | 'segmented';
  }>(),
  { variant: 'underline' },
);

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const onKeydown = (event: KeyboardEvent) => {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  if (!keys.includes(event.key)) return

  const container = event.currentTarget as HTMLElement | null
  if (!container) return

  const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('button[role="tab"]'))
  if (buttons.length === 0) return

  event.preventDefault()
  // ถ้าโฟกัสยังไม่อยู่ในกลุ่ม (เช่นทดสอบ/เพิ่งเปิดหน้า) เริ่มจากแท็บที่เลือกอยู่
  const focused = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const current =
    focused >= 0 ? focused : buttons.findIndex((button) => button.getAttribute('aria-selected') === 'true')
  const from = current >= 0 ? current : 0
  const last = buttons.length - 1
  let next = from

  if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = last
  else if (event.key === 'ArrowLeft') next = from <= 0 ? last : from - 1
  else if (event.key === 'ArrowRight') next = from >= last ? 0 : from + 1

  const target = buttons[next]
  if (!target) return
  target.focus()
  emit('update:modelValue', target.dataset.value ?? '')
}
</script>

<template>
  <div
    v-if="variant === 'segmented'"
    class="inline-flex max-w-full flex-wrap items-center gap-1 rounded-control border border-line bg-surface p-1"
  >
    <div class="flex items-center gap-1" role="tablist" :aria-label="groupLabel" @keydown="onKeydown">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        type="button"
        role="tab"
        :data-value="tab.value"
        :aria-selected="modelValue === tab.value"
        :tabindex="modelValue === tab.value ? 0 : -1"
        class="flex min-h-11 items-center justify-center gap-1.5 rounded-[9px] px-3 py-2 text-sm font-semibold transition-colors"
        :class="
          modelValue === tab.value
            ? 'bg-brand text-white'
            : 'text-ink-2 hover:bg-canvas hover:text-ink-1'
        "
        @click="emit('update:modelValue', tab.value)"
      >
        {{ tab.label }}
        <span
          v-if="tab.count !== undefined"
          class="num rounded-full px-1.5 py-0.5 text-[11px] font-bold"
          :class="modelValue === tab.value ? 'bg-white/20 text-white' : 'bg-canvas text-ink-3'"
        >
          {{ tab.count }}
        </span>
      </button>
    </div>
  </div>

  <div
    v-else
    class="-mx-1 overflow-x-auto border-b border-line"
    role="tablist"
    :aria-label="groupLabel"
    @keydown="onKeydown"
  >
    <div class="flex min-w-max items-center gap-1 px-1">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        type="button"
        role="tab"
        :data-value="tab.value"
        :aria-selected="modelValue === tab.value"
        :tabindex="modelValue === tab.value ? 0 : -1"
        class="-mb-px flex min-h-11 items-center justify-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-semibold transition-colors"
        :class="
          modelValue === tab.value
            ? 'border-brand text-brand'
            : 'border-transparent text-ink-3 hover:text-ink-1'
        "
        @click="emit('update:modelValue', tab.value)"
      >
        {{ tab.label }}
        <span
          v-if="tab.count !== undefined"
          class="num rounded-full px-1.5 py-0.5 text-[11px] font-bold"
          :class="modelValue === tab.value ? 'bg-brand-tint text-brand' : 'bg-canvas text-ink-3'"
        >
          {{ tab.count }}
        </span>
      </button>
    </div>
  </div>
</template>
