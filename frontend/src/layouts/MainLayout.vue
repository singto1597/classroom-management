<script setup lang="ts">
/**
 * 🧱 MainLayout — ประกอบเปลือกแอปเท่านั้น
 *
 * ชิ้นส่วนจริงอยู่ใน `layouts/shell/`:
 *   AppSidebar · AppHeader · AppBottomNav · AppMoreSheet · AppMenus
 * สถานะ/คำสั่งอยู่ใน `useAppShell` และกล่องโปรไฟล์อยู่ใน `useProfileDialogs`
 *
 * ⚠️ `fullscreen`/`headerHidden` มาจาก `route.meta` (router/meta.ts) — หน้าลูก
 *    ห้ามซ่อน header ด้วย CSS เอง เพราะจะเหลือที่ว่างและปุ่มย้อนค้าง
 */
import { RouterView, useRoute } from 'vue-router';
import { useAppShell } from './shell/useAppShell';
import { useProfileDialogs } from './shell/useProfileDialogs';
import AppSidebar from './shell/AppSidebar.vue';
import AppHeader from './shell/AppHeader.vue';
import AppBottomNav from './shell/AppBottomNav.vue';
import AppMoreSheet from './shell/AppMoreSheet.vue';
import AppMenus from './shell/AppMenus.vue';

const route = useRoute();
const shell = useAppShell();
const profile = useProfileDialogs();

const closeOverlays = () => {
  shell.closeDropdowns();
  shell.closeMoreSheet();
};

const openMyProfile = () => {
  closeOverlays();
  profile.goToMyProfile();
};

const openProfileSettings = () => {
  closeOverlays();
  profile.goToProfileSettings();
};

const openAccountInfo = () => {
  closeOverlays();
  profile.showAccountInfo();
};
</script>

<template>
  <div class="relative flex h-screen h-dvh overflow-hidden bg-paper font-sans text-ink">
    <AppSidebar
      :collapsed="shell.isSidebarCollapsed.value"
      :user-name="shell.displayName.value"
      :role-label="shell.authStore.currentRoleLabel"
      :avatar-char="shell.avatarChar.value"
      @toggle-collapse="shell.toggleSidebarCollapse"
      @open-account="openAccountInfo"
    />

    <!-- พื้นที่หลัก (Header + เนื้อหา) -->
    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <AppHeader
        v-if="!route.meta.headerHidden && !route.meta.fullscreen"
        :room-id="shell.authStore.currentRoomId"
        :room-name="shell.authStore.currentRoomName || ''"
        :sub-menu-name="shell.currentSubMenuName.value"
        :user-name="shell.displayName.value"
        :role-label="shell.authStore.currentRoleLabel"
        :avatar-char="shell.avatarChar.value"
        :active-dropdown="shell.activeDropdown.value"
        @change-room="shell.handleChangeRoom"
        @toggle-dropdown="shell.toggleDropdown"
      />

      <!-- เนื้อหา — scroll เกิดที่นี่ที่เดียว -->
      <!--
        ⚠️ ต้องใช้ sm:px-* / sm:pt-* ไม่ใช่ sm:p-* — เพราะ sm:p-6 จะเขียนทับ padding-bottom
        ที่กันแท็บล่างไว้ และแท็บล่างซ่อนที่ lg: เท่านั้น (640–1023px ยังเห็นอยู่)
      -->
      <main
        class="flex-1 overflow-y-auto overflow-x-hidden p-4 pb-[calc(env(safe-area-inset-bottom)+6.5rem)] focus:outline-none sm:px-6 sm:pt-6 lg:px-8 lg:pb-8 lg:pt-8"
      >
        <div class="page-wrap">
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
      <AppBottomNav :more-open="shell.isMoreSheetOpen.value" @open-more="shell.openMoreSheet" />

      <AppMoreSheet
        :open="shell.isMoreSheetOpen.value"
        :room-name="shell.authStore.currentRoomName || ''"
        @close="shell.closeMoreSheet"
        @my-profile="openMyProfile"
        @profile-settings="openProfileSettings"
        @logout="shell.logout"
      />
    </template>

    <AppMenus
      :which="shell.activeDropdown.value"
      :position="shell.dropdownStyle.value"
      :rooms="shell.authStore.rooms"
      :current-room-id="shell.authStore.currentRoomId"
      :user-name="shell.displayName.value"
      :role-label="shell.authStore.currentRoleLabel"
      :avatar-char="shell.avatarChar.value"
      @close="shell.closeDropdowns"
      @select-room="shell.switchRoom"
      @change-room="shell.handleChangeRoom"
      @my-profile="openMyProfile"
      @profile-settings="openProfileSettings"
      @logout="shell.logout"
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
