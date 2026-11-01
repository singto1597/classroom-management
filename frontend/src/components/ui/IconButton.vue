<script setup lang="ts">
/**
 * IconButton — ปุ่มไอคอนล้วน
 *
 * กฎที่บังคับด้วยชนิดข้อมูล:
 *  - `label` เป็น **required** ⇒ ปุ่มไอคอนทุกตัวมีชื่อสำหรับ screen reader
 *  - ขนาดคงที่ 44×44px (h-11 w-11) ตาม DESIGN.md §6
 *
 * @example
 * <IconButton label="ปิดเมนู" icon="bi-x-lg" @click="close" />
 */
withDefaults(
  defineProps<{
    /** ชื่อการกระทำ — ต้องไม่ผูกกับสถานะ (ใช้ "ปิดเมนู" ไม่ใช่ "เปิดอยู่") */
    label: string;
    /** ชื่อคลาส bootstrap-icons เช่น 'bi-x-lg' */
    icon: string;
    tone?: 'neutral' | 'brand' | 'danger';
    type?: 'button' | 'submit';
  }>(),
  { tone: 'neutral', type: 'button' },
)

const emit = defineEmits<{ click: [event: MouseEvent] }>()

const TONE_CLASS = {
  neutral: 'text-stone-500 hover:bg-stone-100 hover:text-stone-800',
  brand: 'text-brand-700 hover:bg-brand-50',
  danger: 'text-danger-600 hover:bg-danger-50',
} as const
</script>

<template>
  <button
    :type="type"
    class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors active:scale-[0.97]"
    :class="TONE_CLASS[tone]"
    :aria-label="label"
    :title="label"
    @click="emit('click', $event)"
  >
    <i :class="['bi', icon, 'text-base']" aria-hidden="true"></i>
  </button>
</template>
