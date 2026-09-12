<script setup lang="ts">
/**
 * SkeletonRows — โครงร่างระหว่างโหลด จำลองรูปทรงของการ์ดจริง
 * ใช้แทน spinner กลางจอ เพื่อให้ผู้ใช้เห็นโครงหน้าเว็บก่อนข้อมูลมา
 *
 * @example
 * <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />
 */
withDefaults(
  defineProps<{
    /** จำนวนแถว */
    rows?: number;
    /** ความสูงแต่ละแถว (Tailwind class) */
    height?: string;
  }>(),
  { rows: 5, height: 'h-16' },
);
</script>

<template>
  <div class="space-y-2.5" aria-busy="true" aria-live="polite">
    <div
      v-for="i in rows"
      :key="i"
      class="animate-pulse rounded-2xl border border-stone-200 bg-white"
      :class="height"
    ></div>
    <span class="sr-only">กำลังโหลดข้อมูล</span>
  </div>
</template>
