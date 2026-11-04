<script setup lang="ts">
/**
 * 🔝 Header — เจ้าของ `<h1>` ของทุกหน้า (PIRIvoice)
 *
 * องค์ประกอบที่เหลือมีแค่:
 *  - ปุ่มย้อนกลับ 44px (เมื่อ `route.meta.headerBack`)
 *  - ตัวสลับห้องเรียนแบบกะทัดรัด 44px (ไอคอน + ชื่อห้องที่ตัดได้ + chevron)
 *  - กระดิ่งแจ้งเตือน
 *
 * 🚫 ไม่มี avatar / ชื่อผู้ใช้ / เมนูโปรไฟล์ที่นี่ — งานบัญชีเป็นเรื่องส่วนกลาง
 *    (หน้า "เพิ่มเติม" และ `/account`) ไม่ใช่ของห้องใดห้องหนึ่ง
 *
 * ชื่อหน้า: `usePageTitle` override มาก่อนเสมอ แล้วจึง fallback ไป `route.meta.title`
 * (หน้า detail ที่โหลดชื่อจริงได้ทีหลังจะเรียก `usePageTitle` ใน setup)
 */
import { computed, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import NotificationBell from '@/components/notifications/NotificationBell.vue';
import { APP_NAME, pageTitle } from '@/router/meta';
import { clearPageTitle, pageTitleOverride } from '@/composables/usePageTitle';
import type { ShellMenu } from './useAppShell';

defineProps<{
  roomId: number | null;
  roomName: string;
  activeDropdown: ShellMenu | null;
  /** ตัวเลขยังไม่อ่านจาก store (backend เป็นเจ้าของตัวเลข) */
  unreadCount: number;
  /** แผงแจ้งเตือนเปิดอยู่หรือไม่ — ใช้ทำ `aria-expanded` */
  notificationsOpen: boolean;
}>();

const emit = defineEmits<{
  changeRoom: [];
  toggleDropdown: [event: MouseEvent, menu: ShellMenu];
  openNotifications: [];
}>();

const route = useRoute();
const router = useRouter();

const canGoBack = computed(() => route.meta.headerBack === true);

const title = computed(() => pageTitleOverride.value || route.meta.title || APP_NAME);

/** ความกว้างเดียวกับเนื้อหา — หัวข้อจึงอยู่ตรงกับคอลัมน์แรกของการ์ด */
const widthClass = computed(() => {
  switch (route.meta.width) {
    case 'reading':
      return 'max-w-3xl';
    case 'form':
      return 'max-w-2xl';
    default:
      return 'max-w-7xl';
  }
});

// เปลี่ยนหน้า = ล้างหัวข้อไดนามิกของหน้าเดิมทันที (กันชื่อค้าง)
watch(
  () => route.fullPath,
  () => clearPageTitle(),
  // ต้องล้าง **ก่อน** หน้าใหม่ mount — ถ้าใช้ flush ปกติ (pre) การล้างอาจเกิด
  // หลัง view ใหม่ตั้งชื่อของตัวเองแล้ว ⇒ ชื่อ detail หายทันทีที่โหลดเสร็จ
  { flush: 'sync' },
);

watch(
  title,
  (value) => {
    if (typeof document !== 'undefined') document.title = pageTitle(value);
  },
  { immediate: true },
);

const goBack = () => {
  if (window.history.length > 1) router.back();
  else router.push('/dashboard');
};
</script>

<template>
  <header
    class="z-20 shrink-0 border-b border-line bg-surface"
    :style="{ paddingTop: 'env(safe-area-inset-top)' }"
  >
    <div
      class="mx-auto flex h-14 w-full items-center gap-1.5 px-4 sm:px-6 lg:px-8"
      :class="widthClass"
    >
      <button
        v-if="canGoBack"
        type="button"
        class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-ink-2 transition-colors hover:bg-canvas hover:text-ink-1"
        aria-label="ย้อนกลับ"
        @click="goBack"
      >
        <i class="bi bi-arrow-left text-lg" aria-hidden="true"></i>
      </button>

      <RouterLink
        v-else
        to="/dashboard"
        class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-brand text-white lg:hidden"
        aria-label="หน้าหลัก"
      >
        <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
      </RouterLink>

      <h1 class="min-w-0 flex-1 truncate px-1.5 text-base font-bold text-ink-1">
        {{ title }}
      </h1>

      <div class="flex shrink-0 items-center gap-1">
        <!-- ตัวสลับห้องเรียน: 44px, ชื่อห้องตัดด้วย ellipsis ไม่ดันหัวข้อ -->
        <button
          v-if="roomId"
          type="button"
          class="flex h-11 min-w-0 items-center gap-1.5 rounded-control px-2 text-ink-2 transition-colors hover:bg-canvas hover:text-ink-1"
          aria-haspopup="menu"
          :aria-expanded="activeDropdown === 'roomSwitcher'"
          :aria-label="`สลับห้องเรียน — ${roomName || `ห้อง ${roomId}`}`"
          :title="roomName || `ห้อง ${roomId}`"
          @click.stop="emit('toggleDropdown', $event, 'roomSwitcher')"
        >
          <i class="bi bi-door-open shrink-0 text-base" aria-hidden="true"></i>
          <!-- มือถือซ่อนชื่อห้อง (เหลือไอคอน+chevron) เพื่อคืนพื้นที่ให้หัวข้อหน้า
               ชื่อเต็มยังเข้าถึงได้ผ่าน aria-label/title และเมนูสลับห้อง -->
          <span class="hidden max-w-[12rem] truncate text-sm font-semibold text-ink-1 sm:inline">
            {{ roomName || `ห้อง ${roomId}` }}
          </span>
          <i class="bi bi-chevron-down shrink-0 text-xs opacity-60" aria-hidden="true"></i>
        </button>

        <!-- 🔔 มีห้องที่กำลังเปิดอยู่เท่านั้น — ยังไม่มีห้อง = ไม่มีอะไรให้แจ้ง -->
        <NotificationBell
          v-if="roomId"
          :unread-count="unreadCount"
          :expanded="notificationsOpen"
          @open="emit('openNotifications')"
        />
      </div>
    </div>
  </header>
</template>
