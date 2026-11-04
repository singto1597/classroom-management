<script setup lang="ts">
/**
 * PageIntro — คำโปรยและปุ่มประจำหน้า
 *
 * 🔑 ตั้งแต่ Stage 2 หัวข้อ `<h1>` ของทุกหน้าเป็นของ `AppHeader` แล้ว
 * ⇒ หน้างานไม่ต้องพิมพ์ชื่อหน้าซ้ำ ใช้คอมโพเนนต์นี้วาง "คำอธิบาย" กับ "ปุ่มหลัก"
 * ให้อยู่ในตำแหน่งเดียวกันทั้งระบบ (PIRIvoice วาง lede + actions ใต้ header)
 *
 * @example
 * <PageIntro description="รายชื่อนักเรียนทั้งหมดในห้องนี้">
 *   <template #actions>
 *     <RouterLink to="/students/add" class="btn-primary">เพิ่มนักเรียน</RouterLink>
 *   </template>
 * </PageIntro>
 */
withDefaults(
  defineProps<{
    /** คำอธิบาย 1–2 บรรทัด — ไม่ใช่ชื่อหน้า (ชื่อหน้าอยู่บน header) */
    description?: string;
  }>(),
  { description: '' },
);
</script>

<template>
  <header
    v-if="description || $slots.actions"
    class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:gap-4"
  >
    <p v-if="description" class="min-w-0 max-w-2xl text-sm leading-relaxed text-ink-2">
      {{ description }}
    </p>

    <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2 sm:shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
