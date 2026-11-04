<script setup lang="ts">
/**
 * ➕ ปุ่มลอย (FAB) — หนึ่งปุ่มต่อหนึ่งหน้ารายการ ตาม `route.meta.fab`
 *
 * - แสดงเฉพาะมือถือ (`lg:hidden`) — บนเดสก์ท็อปปุ่มหลักอยู่ใน PageIntro
 * - แสดงเฉพาะเมื่อผู้ใช้มี `fab.permission` (admin ผ่าน superset ใน `hasPermission`)
 * - อยู่เหนือแถบล่างตาม `--app-nav-h` + safe-area — ค่าเดียวกับ MainLayout
 *
 * ⚠️ ห้ามประกาศ `fab` ที่หน้า detail/edit — ปุ่ม "เพิ่ม" จะลอยทับฟอร์ม
 */
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const route = useRoute();
const authStore = useAuthStore();

const fab = computed(() => route.meta.fab ?? null);
const isAllowed = computed(() => {
  const permission = fab.value?.permission;
  return permission ? authStore.hasPermission(permission) : true;
});
</script>

<template>
  <RouterLink
    v-if="fab && isAllowed"
    :to="fab.to"
    class="absolute right-4 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-brand text-white shadow-fab transition-transform active:scale-95 lg:hidden"
    :style="{ bottom: 'calc(var(--app-nav-h) + env(safe-area-inset-bottom, 0px) + 1rem)' }"
    :aria-label="fab.label"
    :title="fab.label"
  >
    <i :class="['bi', fab.icon, 'text-xl']" aria-hidden="true"></i>
  </RouterLink>
</template>
