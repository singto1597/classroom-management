<script setup lang="ts">
/**
 * AppButton — ปุ่มเดียวของระบบ 4 โทน
 *
 * | variant     | ใช้เมื่อ                                  |
 * |-------------|-------------------------------------------|
 * | `primary`   | การกระทำหลักของหน้า (มีได้หน้าละ 1-2 ปุ่ม) |
 * | `secondary` | ทางเลือก/ยกเลิก — ขอบเทา พื้นขาว          |
 * | `danger`    | ลบ/ยกเลิกข้อมูล — ขอบแดง พื้นขาว          |
 * | `quiet`     | การกระทำเบาในเนื้อหา (แก้ไข/ดูทั้งหมด)     |
 *
 * ปุ่มทุกโทนสูง ≥44px (`min-h-11`) ตาม DESIGN.md §6 — ทั้งแบบ `<button>` และ `<RouterLink>`
 *
 * @example
 * <AppButton variant="primary" :loading="saving" @click="save">บันทึก</AppButton>
 * <AppButton variant="secondary" to="/tasks">ยกเลิก</AppButton>
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { RouteLocationRaw } from 'vue-router'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'danger' | 'quiet';
    /** ถ้าส่ง `to` จะเรนเดอร์เป็น RouterLink (ปุ่มนำทาง ไม่ใช่ปุ่ม submit) */
    to?: RouteLocationRaw;
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
    /** แสดง spinner + กันการกดซ้ำ + `aria-busy` */
    loading?: boolean;
    /** ขยายเต็มความกว้าง (มือถือ/form) */
    block?: boolean;
  }>(),
  { variant: 'primary', type: 'button', disabled: false, loading: false, block: false },
)

const VARIANT_CLASS = {
  primary: 'btn-primary',
  secondary: 'btn-ghost-ui',
  danger: 'btn-danger',
  quiet:
    'inline-flex min-h-11 items-center justify-center gap-2 rounded-control px-3 py-2.5 text-sm font-bold text-brand transition-colors hover:bg-brand-tint active:scale-[0.97]',
} as const

const classes = computed(() => [
  VARIANT_CLASS[props.variant],
  props.block ? 'w-full' : '',
])

const isDisabled = computed(() => props.disabled || props.loading)

/** ลิงก์ไม่รู้จัก `disabled` — ต้องดักคลิกเองไม่ให้พาออกจากหน้าในสภาพที่กดไม่ได้ */
const onLinkClick = (event: MouseEvent) => {
  if (isDisabled.value) event.preventDefault()
}
</script>

<template>
  <RouterLink
    v-if="to"
    :to="to"
    :class="classes"
    :aria-disabled="isDisabled || undefined"
    :tabindex="isDisabled ? -1 : undefined"
    @click="onLinkClick"
  >
    <slot />
  </RouterLink>

  <button
    v-else
    :type="type"
    :class="classes"
    :disabled="isDisabled"
    :aria-busy="loading || undefined"
  >
    <span
      v-if="loading"
      class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent"
      aria-hidden="true"
    ></span>
    <slot />
  </button>
</template>
