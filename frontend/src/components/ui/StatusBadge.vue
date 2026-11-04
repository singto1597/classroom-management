<script setup lang="ts">
/**
 * StatusBadge — ป้ายสถานะที่ **ไม่ใช้สีเป็นช่องทางเดียว**
 * จุดสี + ข้อความเสมอ ⇒ ผู้ใช้ตาบอดสี/พิมพ์ขาวดำยังอ่านความหมายได้
 *
 * @example
 * <StatusBadge tone="ok" label="กำลังเรียน" />
 * <StatusBadge tone="warn" label="รออนุมัติ" icon="bi-clock-fill" />
 */
withDefaults(
  defineProps<{
    tone: 'neutral' | 'ok' | 'warn' | 'danger' | 'brand';
    /** ข้อความภาษาไทยที่ผู้ใช้อ่าน — ห้ามเว้นว่าง */
    label: string;
    /** ไอคอนเสริม (ไม่แทนข้อความ) */
    icon?: string;
  }>(),
  { icon: '' },
)

const TONE_CLASS = {
  neutral: 'bg-canvas text-ink-2',
  ok: 'bg-ok-50 text-ok-700',
  warn: 'bg-warn-50 text-warn-700',
  danger: 'bg-danger-50 text-danger-700',
  brand: 'bg-brand-tint text-brand',
} as const
</script>

<template>
  <span class="chip" :class="TONE_CLASS[tone]">
    <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true"></span>
    <i v-if="icon" :class="['bi', icon]" aria-hidden="true"></i>
    {{ label }}
  </span>
</template>
