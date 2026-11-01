<script setup lang="ts">
/**
 * 🔔 กระดิ่งแจ้งเตือนใน header — ปุ่มเดียวที่เปิด NotificationCenter
 *
 * กฎที่ฝังไว้:
 *  - ตัวเลขมาจาก `store.unreadCount` (backend) — ห้ามนับเองในคอมโพเนนต์
 *  - เกิน 99 แสดง "99+" แต่ `aria-label` บอกจำนวนจริง (screen reader ไม่ควรได้ "99+")
 *  - มีของใหม่ ⇒ ปุ่มมีจุดสีแดงด้วย ไม่พึ่งตัวเลขอย่างเดียว (สีไม่ใช่ข้อมูลเดียว)
 *  - ขนาด 44×44 ตาม DESIGN.md §6
 *
 * ⚠️ `aria-label` ไม่ผูกกับจำนวน (ไม่ใช่ "แจ้งเตือน 5 รายการที่ยังไม่อ่าน")
 *    เพราะชื่อปุ่มจะเปลี่ยนทุกครั้งที่มีของใหม่ — ใส่จำนวนใน `title` แทน
 */
import { computed } from 'vue';

const props = defineProps<{
  unreadCount: number;
  /** สถานะของแผงที่ผูกอยู่ — ใช้ทำ `aria-expanded` */
  expanded?: boolean;
}>();

const emit = defineEmits<{ open: [] }>();

const displayCount = computed(() => (props.unreadCount > 99 ? '99+' : String(props.unreadCount)));
const hasUnread = computed(() => props.unreadCount > 0);
</script>

<template>
  <button
    type="button"
    class="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900 active:scale-[0.97]"
    aria-label="การแจ้งเตือน"
    aria-haspopup="dialog"
    :aria-expanded="expanded === true"
    :title="hasUnread ? `ยังไม่อ่าน ${unreadCount} รายการ` : 'ไม่มีการแจ้งเตือนใหม่'"
    @click="emit('open')"
  >
    <i class="bi bi-bell text-lg" aria-hidden="true"></i>

    <!-- จุดสี: บอกว่ามีของใหม่โดยไม่ต้องอ่านตัวเลข -->
    <span
      v-if="hasUnread"
      class="pointer-events-none absolute end-1.5 top-1.5 flex min-w-[18px] items-center justify-center rounded-full bg-danger-600 px-1 text-[10px] font-bold leading-[18px] text-white"
      aria-hidden="true"
    >
      {{ displayCount }}
    </span>
  </button>
</template>
