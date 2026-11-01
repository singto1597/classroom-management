<script setup lang="ts">
/**
 * AppTabs — ตัวสลับหมวดแบบปุ่ม (ไม่ใช่แท็บที่โหลดเนื้อหาเอง)
 *
 * - ปุ่มสูง ≥44px ทุกตัว
 * - ลูกศรซ้าย/ขวา, Home, End เลื่อนและเลือกได้ (roving tabindex)
 * - `aria-pressed` บอกสถานะที่เลือก — ไม่พึ่งสีอย่างเดียว
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

defineProps<{
  modelValue: string;
  tabs: readonly AppTabItem[];
  /** ชื่อกลุ่มสำหรับ screen reader (ส่งไปที่ `aria-label` ของกลุ่ม) */
  groupLabel: string;
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const onKeydown = (event: KeyboardEvent) => {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  if (!keys.includes(event.key)) return

  const container = event.currentTarget as HTMLElement | null
  if (!container) return

  const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
  if (buttons.length === 0) return

  event.preventDefault()
  // ถ้าโฟกัสยังไม่อยู่ในกลุ่ม (เช่นทดสอบ/เพิ่งเปิดหน้า) เริ่มจากแท็บที่เลือกอยู่
  const focused = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const current =
    focused >= 0
      ? focused
      : buttons.findIndex((button) => button.getAttribute('aria-pressed') === 'true')
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
  <div class="page-card p-1.5">
    <div class="flex items-center gap-1" role="group" :aria-label="groupLabel" @keydown="onKeydown">
      <button
        v-for="tab in tabs"
        :key="tab.value"
        type="button"
        :data-value="tab.value"
        :aria-pressed="modelValue === tab.value"
        :tabindex="modelValue === tab.value ? 0 : -1"
        class="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2.5 text-sm font-bold transition-colors active:scale-[0.97]"
        :class="
          modelValue === tab.value
            ? 'bg-brand-700 text-white'
            : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'
        "
        @click="emit('update:modelValue', tab.value)"
      >
        {{ tab.label }}
        <span
          v-if="tab.count !== undefined"
          class="num rounded-full px-1.5 py-0.5 text-[11px] font-bold"
          :class="modelValue === tab.value ? 'bg-white/20 text-white' : 'bg-stone-200 text-stone-600'"
        >
          {{ tab.count }}
        </span>
      </button>
    </div>
  </div>
</template>
