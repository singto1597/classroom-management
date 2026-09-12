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
  <header class="mb-4 sm:mb-6">
    <!--
      ⚠️ ห้ามใช้ flex-row + flex-1 บนมือถือ: flex-1 คือ flex: 1 1 0% ทำให้กล่องหัวข้อหดได้ไม่จำกัด
      เบราว์เซอร์จึงไม่ตัดบรรทัดให้ปุ่ม แต่จะ "บีบ" หัวข้อให้เหลือคอลัมน์แคบ ๆ ข้างปุ่ม
      → มือถือจึงต้องเป็น flex-col ให้หัวข้อได้เต็มความกว้าง แล้วค่อยกลับเป็นแถวเดียวที่ sm:
    -->
    <div
      class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between sm:gap-4"
    >
      <!-- sm:min-w-[16rem] สำคัญ: flex-1 คือ flex: 1 1 0% (flex-basis 0) ทำให้ความกว้าง
           "ตามทฤษฎี" ของกล่องหัวข้อเป็น 0 เบราว์เซอร์จึงไม่เคยตัดปุ่มขึ้นบรรทัดใหม่ให้
           การใส่ min-width กลับไปทำให้ wrap ทำงานจริงเมื่อปุ่มเยอะจนล้น -->
      <div class="min-w-0 sm:min-w-[16rem] sm:flex-1">
        <!-- ป้าย eyebrow เป็นภาษาอังกฤษ เปลืองพื้นที่บนมือถือ — ซ่อนเฉพาะจอเล็ก -->
        <p v-if="eyebrow" class="eyebrow mb-1 hidden sm:mb-1.5 sm:block">{{ eyebrow }}</p>
        <h1 class="page-title break-words">{{ title }}</h1>
        <p v-if="description" class="page-lede mt-1 sm:mt-1.5 sm:max-w-2xl">{{ description }}</p>
      </div>

      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2 sm:shrink-0">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
