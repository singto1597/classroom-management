<script setup lang="ts">
/**
 * 🏷️ [FIN-V2 / P5.2] ป้ายชนิดเอกสารของทะเบียนรวม
 *
 * 🔑 แหล่งเดียวของ "ป้ายไทย + สี" คือ `utils/documentFilters.ts` — ห้ามพิมพ์ map ซ้ำในหน้า
 *    เพราะเอกสาร 8 ชนิดต้องตอบชื่อเดียวกันทั้งทะเบียน ตัวกรอง และหน้ารายละเอียด
 *
 * 🎨 สีบอก **สถานะของเงิน** ไม่ใช่ชื่อชนิด (เขียว = เงินเข้า · เหลือง = ยังไม่ได้รับ ·
 *    เทา = เงินออก) — แดงสงวนไว้ให้ "ถูกยกเลิก" เท่านั้น
 */
import { typeBadgeClass, typeIcon, typeLabel } from '@/utils/documentFilters';

withDefaults(
  defineProps<{
    /** ชนิดเอกสารจาก API — string เพื่อให้ fallback กับชนิดใหม่ได้โดยไม่พัง */
    docType: string;
    /** ซ่อนไอคอนเมื่ออยู่ในบริบทแคบ (เช่น badge เล็กในตาราง) */
    showIcon?: boolean;
  }>(),
  { showIcon: true },
);
</script>

<template>
  <span class="chip" :class="typeBadgeClass(docType)">
    <i v-if="showIcon" :class="['bi', typeIcon(docType)]" aria-hidden="true"></i>
    {{ typeLabel(docType) }}
  </span>
</template>
