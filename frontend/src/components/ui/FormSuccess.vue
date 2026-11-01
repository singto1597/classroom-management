<script setup lang="ts">
/**
 * ✅ FormSuccess — หน้ายืนยันหลังบันทึกสำเร็จ (แทน Swal ที่หายไปเองใน 1.5 วิ)
 *
 * ทำไมไม่ใช้ Swal อย่างเดียว:
 *   ผลลัพธ์ที่ผู้ใช้ต้อง "อ่านต่อ/ทำต่อ" (รหัส, ลิงก์, จำนวนที่สร้าง) ต้องค้างบนจอ
 *   ไม่ใช่ป๊อปอัปที่ปิดเอง — ผู้ใช้ที่พิมพ์ช้าอ่านไม่ทัน และบนมือถือกดพลาดง่าย
 *
 * @example
 * <FormSuccess v-if="submitted" title="เพิ่มนักเรียนแล้ว" :hint="`เลขที่ ${no}`">
 *   <RouterLink to="/students" class="btn-primary">ดูรายชื่อ</RouterLink>
 *   <button class="btn-ghost-ui" @click="reset">เพิ่มอีกคน</button>
 * </FormSuccess>
 */
withDefaults(
  defineProps<{
    title: string
    hint?: string
    /** ไอคอน Bootstrap Icons */
    icon?: string
  }>(),
  { icon: 'bi-check-circle-fill' },
)
</script>

<template>
  <div
    class="flex flex-col items-center justify-center gap-2 rounded-2xl border border-ok-200 bg-white px-5 py-10 text-center sm:gap-2.5 sm:px-6 sm:py-14"
    role="status"
    aria-live="polite"
  >
    <i :class="['bi', icon, 'text-4xl text-ok-600']" aria-hidden="true"></i>

    <p class="font-display text-lg font-bold text-stone-900">{{ title }}</p>

    <p v-if="hint" class="max-w-sm break-words text-sm leading-relaxed text-stone-600">{{ hint }}</p>

    <!-- ทางไปต่อ 1–2 ปุ่ม: "ดูรายการ" หลัก + "เพิ่มอีก" รอง -->
    <div class="mt-2 flex w-full flex-col items-stretch gap-2 sm:w-auto sm:flex-row">
      <slot />
    </div>
  </div>
</template>
