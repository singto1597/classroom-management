<script setup lang="ts">
/**
 * PageHeader — หัวหน้าสำหรับทุกหน้าในระบบ
 * รูปแบบบรรณาธิการ: eyebrow (ตัวพิมพ์ใหญ่สีน้ำเงิน) → h1 → คำโปรย
 * ใช้เหมือนกันทุกหน้าเพื่อให้ทั้งระบบหน้าตาเป็นภาษาเดียวกัน
 *
 * @example
 * <PageHeader eyebrow="Academic Records" title="ทะเบียนนักเรียน"
 *             description="ข้อมูลนักเรียนทั้งหมดในห้อง">
 *   <template #actions>
 *     <button class="btn-primary">เพิ่มนักเรียน</button>
 *   </template>
 * </PageHeader>
 */
defineProps<{
  /** ป้ายเล็กเหนือหัวข้อ — ภาษาอังกฤษตัวพิมพ์ใหญ่ เช่น "Academic Records" */
  eyebrow?: string;
  /** หัวข้อหลักของหน้า */
  title: string;
  /** คำโปรยอธิบาย 1 บรรทัด */
  description?: string;
}>();
</script>

<template>
  <header class="mb-5 flex flex-wrap items-end justify-between gap-3 sm:mb-7 sm:gap-4">
    <div class="min-w-0 flex-1">
      <p v-if="eyebrow" class="eyebrow mb-1.5">{{ eyebrow }}</p>
      <h1 class="page-title break-words">{{ title }}</h1>
      <p v-if="description" class="page-lede mt-1.5 max-w-2xl">{{ description }}</p>
    </div>

    <div v-if="$slots.actions" class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>
