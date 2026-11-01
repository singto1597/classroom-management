<script setup lang="ts">
/**
 * AppCard — การ์ดพื้นฐานของการออกแบบ "Academic Ledger"
 * ขอบทึบ hairline + มุมโค้ง 2xl + พื้นขาว บนกระดาษ stone
 *
 * ⚠️ ห้ามใส่ `border-dashed` — เส้นประสื่อ "ช่องที่ยังกรอกไม่ครบ" ไม่ใช่การ์ด
 *
 * @example
 * <AppCard padding="md" hover>
 *   <h3 class="section-title">โน้ตวันนี้</h3>
 * </AppCard>
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** ระยะขอบในของการ์ด — 'none' เมื่อเนื้อหาจัดการเอง (เช่น หัวการ์ด + ตาราง) */
    padding?: 'none' | 'sm' | 'md' | 'lg';
    /** ยกขึ้นเล็กน้อยเมื่อ hover (ใช้เฉพาะการ์ดที่กดได้) */
    hover?: boolean;
    /** ตัดเนื้อหาที่ล้นออก (การ์ดที่มีหัวมีท้ายหรือตาราง) */
    clip?: boolean;
  }>(),
  { padding: 'none', hover: false, clip: false },
)

const PADDING_CLASS = {
  none: '',
  sm: 'p-3.5 sm:p-4',
  md: 'p-4 sm:p-5',
  lg: 'p-5 sm:p-6',
} as const

const classes = computed(() => [
  'page-card',
  PADDING_CLASS[props.padding],
  props.hover ? 'card-hover' : '',
  props.clip ? 'overflow-hidden' : '',
])
</script>

<template>
  <div :class="classes">
    <slot />
  </div>
</template>
