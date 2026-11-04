<script setup lang="ts">
/**
 * AppChip — ป้ายเล็กสำหรับสถานะ/หมวด
 * โทนพาสเทลพื้นอ่อน + ตัวอักษรเข้ม (DESIGN.md) ไม่ใช่สีสดทึบ
 *
 * ⚠️ สีไม่ใช่ช่องทางเดียวของความหมาย — ใส่ข้อความบอกสถานะเสมอ
 * (ไอคอนเป็นตัวช่วย ไม่ใช่ตัวแทนข้อความ)
 *
 * @example
 * <AppChip tone="warn" icon="bi-clock">รออนุมัติ</AppChip>
 */
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'brand' | 'ok' | 'warn' | 'danger' | 'info';
    /** ชื่อคลาส bootstrap-icons — ไม่ใส่ก็ได้ */
    icon?: string;
  }>(),
  { tone: 'neutral', icon: '' },
)

const TONE_CLASS = {
  neutral: 'bg-canvas text-ink-2',
  brand: 'bg-brand-tint text-brand',
  ok: 'bg-ok-50 text-ok-700',
  warn: 'bg-warn-50 text-warn-700',
  danger: 'bg-danger-50 text-danger-700',
  info: 'bg-info-50 text-info-700',
} as const
</script>

<template>
  <span class="chip" :class="TONE_CLASS[tone]">
    <i v-if="icon" :class="['bi', icon]" aria-hidden="true"></i>
    <slot />
  </span>
</template>
