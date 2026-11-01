<script setup lang="ts">
/**
 * AppEmptyState — สถานะ "ยังไม่มีข้อมูล" (การ์ดขอบทึบ + ไอคอน + ทางออก)
 *
 * ต่างจาก error: ไม่มีปุ่ม "ลองอีกครั้ง" และ **ต้องมีทางออกที่ตรงสาเหตุ**
 * ผ่าน slot (เช่น "เพิ่มรายการแรก" / "ดูทั้งหมด") — ข้อความปลอบอย่างเดียวไม่พอ
 *
 * @example
 * <AppEmptyState title="ยังไม่มีนักเรียน" hint="เพิ่มนักเรียนคนแรกเพื่อเริ่มต้น">
 *   <AppButton to="/students/add">เพิ่มนักเรียน</AppButton>
 * </AppEmptyState>
 */
withDefaults(
  defineProps<{
    title?: string;
    hint?: string;
    /** ชื่อคลาส bootstrap-icons */
    icon?: string;
  }>(),
  { title: 'ยังไม่มีข้อมูล', hint: '', icon: 'bi-inbox' },
)
</script>

<template>
  <div
    class="flex flex-col items-center justify-center gap-2 rounded-2xl border border-stone-200 bg-white px-5 py-9 text-center sm:gap-2.5 sm:px-6 sm:py-12"
  >
    <i :class="['bi', icon, 'text-3xl text-stone-300']" aria-hidden="true"></i>
    <p class="font-display text-base font-bold text-stone-700">{{ title }}</p>
    <p v-if="hint" class="max-w-sm text-sm leading-relaxed text-stone-500">{{ hint }}</p>
    <slot />
  </div>
</template>
