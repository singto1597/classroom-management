<script setup lang="ts">
/**
 * 🧱 MainLayout — เปลือกแอปแบบ PIRIvoice
 *
 *   ┌──────────┬──────────────────────────────┐
 *   │ Sidebar  │ Header (in-flow, h-14)       │
 *   │ (lg+)    ├──────────────────────────────┤
 *   │          │ Main — scroll ที่นี่ที่เดียว │
 *   ├──────────┴──────────────────────────────┤
 *   │ BottomNav (mobile) · FAB (absolute)     │
 *   └─────────────────────────────────────────┘
 *
 * 🔑 root ตรึง `h-[100dvh] overflow-hidden` ⇒ มี scroll container เดียวคือ `<main>`
 *    ซึ่งทำให้ header อยู่นิ่ง, `position: sticky` ในหน้าเนื้อหาทำงาน, และ
 *    safe-area ของแถบล่างไม่ทับเนื้อหาสุดท้าย
 *
 * ความกว้างเนื้อหาอ่านจาก `route.meta.width` (wide/reading/form)
 * — header ใช้ค่าเดียวกันจึงจัดแนวคอลัมน์ตรงกัน
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import { useAppShell } from './shell/useAppShell';
import AppSidebar from './shell/AppSidebar.vue';
import AppHeader from './shell/AppHeader.vue';
import AppBottomNav from './shell/AppBottomNav.vue';
import AppFab from './shell/AppFab.vue';
import AppMenus from './shell/AppMenus.vue';
import InstallPrompt from '@/components/pwa/InstallPrompt.vue';
import NotificationCenter from '@/components/notifications/NotificationCenter.vue';
import { useNotificationStore } from '@/stores/notifications';

const route = useRoute();
const shell = useAppShell();
const notifications = useNotificationStore();

const isNotificationCenterOpen = ref(false);
const openNotificationCenter = () => {
  shell.closeDropdowns();
  isNotificationCenterOpen.value = true;
};

/** ความกว้างเดียวกับ AppHeader — จัดหัวข้อกับเนื้อหาให้อยู่คอลัมน์เดียวกัน */
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

/**
 * 🔔 สตรีมแจ้งเตือนมีชีวิตเท่าที่เปลือกแอปมีชีวิต
 *
 * store จัดการ "สลับห้อง" เองผ่าน `watch(roomId)` — ที่นี่รับผิดชอบแค่
 * เริ่มเมื่อเข้าเปลือกแอป และหยุดเมื่อออก (เช่น ไปหน้า lobby) เพื่อไม่ถือ connection ค้าง
 * ⚠️ เบราว์เซอร์มือถือตัด connection ตอนอยู่เบื้องหลัง ⇒ ฟัง `visibilitychange`
 */
onMounted(() => {
  // ดึงตัวเลขบนกระดิ่งทันที ไม่รอ `event: ready` — ถ้าสตรีมต่อไม่ได้
  // (เน็ตหลุด/พร็อกซีบล็อก SSE) ผู้ใช้ยังต้องเห็นจำนวนที่ค้างอยู่
  void notifications.load();
  notifications.startStream();
  document.addEventListener('visibilitychange', notifications.handleVisibility);
});

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', notifications.handleVisibility);
  notifications.stopStream();
});
</script>

<template>
  <div class="relative flex h-[100dvh] overflow-hidden bg-canvas font-sans text-ink-1">
    <AppSidebar
      :collapsed="shell.isSidebarCollapsed.value"
      :user-name="shell.displayName.value"
      :role-label="shell.authStore.currentRoleLabel"
      :avatar-char="shell.avatarChar.value"
      @toggle-collapse="shell.toggleSidebarCollapse"
    />

    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <AppHeader
        v-if="!route.meta.headerHidden && !route.meta.fullscreen"
        :room-id="shell.authStore.currentRoomId"
        :room-name="shell.authStore.currentRoomName || ''"
        :active-dropdown="shell.activeDropdown.value"
        :unread-count="notifications.unreadCount"
        :notifications-open="isNotificationCenterOpen"
        @change-room="shell.handleChangeRoom"
        @toggle-dropdown="shell.toggleDropdown"
        @open-notifications="openNotificationCenter"
      />

      <!-- เนื้อหา — scroll เกิดที่นี่ที่เดียว -->
      <main
        class="flex-1 overflow-y-auto overflow-x-hidden overscroll-contain px-4 pt-4 pb-[calc(var(--app-nav-h)+env(safe-area-inset-bottom,0px)+1rem)] focus:outline-none sm:px-6 lg:px-8 lg:pt-6 lg:pb-8"
      >
        <div class="mx-auto w-full" :class="widthClass">
          <!--
            ⚠️ key ต้องมี roomId ด้วย ไม่ใช่แค่ path — วิวส่วนใหญ่อ่าน currentRoomId
            ใส่ `const` ตอน setup (ไม่ reactive) ⇒ สลับห้องแล้วไม่ remount จะยิง API ห้องเดิมต่อ
          -->
          <RouterView v-slot="{ Component, route: r }">
            <transition name="fade-slide" mode="out-in">
              <div :key="`${r.path}::${shell.authStore.currentRoomId ?? 'none'}`">
                <component :is="Component" />
              </div>
            </transition>
          </RouterView>
        </div>
      </main>
    </div>

    <template v-if="!route.meta.fullscreen">
      <AppBottomNav />

      <!-- ➕ FAB ของหน้ารายการ (ถ้า route ประกาศ `fab` และผู้ใช้มีสิทธิ์) -->
      <AppFab />

      <!-- 📲 แถบชวนติดตั้ง — ซ่อนเองเมื่อไม่ใช่มือถือ/ติดตั้งแล้ว/เคยปิด -->
      <InstallPrompt />
    </template>

    <!-- 🔔 แผงแจ้งเตือน — Teleport ไป body เอง (z-index ชนะ layout) -->
    <NotificationCenter
      :open="isNotificationCenterOpen"
      @close="isNotificationCenterOpen = false"
    />

    <AppMenus
      :which="shell.activeDropdown.value"
      :position="shell.dropdownStyle.value"
      :rooms="shell.authStore.rooms"
      :current-room-id="shell.authStore.currentRoomId"
      @close="shell.closeDropdowns"
      @select-room="shell.switchRoom"
      @change-room="shell.handleChangeRoom"
    />
  </div>
</template>

<style scoped>
/* 🪄 เปลี่ยนหน้าเนื้อหาเท่านั้น (header/tab bar อยู่นิ่ง) */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (prefers-reduced-motion: reduce) {
  .fade-slide-enter-active,
  .fade-slide-leave-active {
    transition-duration: 0.01ms;
  }
}
</style>
