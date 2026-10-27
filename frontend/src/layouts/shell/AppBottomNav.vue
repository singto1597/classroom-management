<script setup lang="ts">
/**
 * 📱 แถบนำทางล่าง — 4 ปลายทางหลัก + "เพิ่มเติม" = 5 ช่อง
 *
 * ไม่มี FAB สร้างงานแล้ว: งานย้ายมาเป็นแท็บของตัวเอง และปุ่มสร้างงาน
 * อยู่ในหัวหน้า TaskList ที่เดียว (หนึ่งปลายทาง = หนึ่งทางเข้า)
 */
import { RouterLink, useRoute } from 'vue-router';
import { NAV_TABS, isNavItemActive } from '@/constants/nav';

defineProps<{ moreOpen: boolean }>();

const emit = defineEmits<{ openMore: [] }>();

const route = useRoute();
const isActive = (path: string) => isNavItemActive(path, route.path);
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-40 px-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] lg:hidden"
    aria-label="เมนูหลัก"
  >
    <div
      class="mx-auto flex max-w-[460px] items-center justify-between gap-0.5 rounded-3xl border border-stone-200 bg-white px-1.5 py-1.5 shadow-[0_10px_34px_-14px_rgba(28,25,23,0.28)]"
    >
      <RouterLink
        v-for="tab in NAV_TABS"
        :key="tab.path"
        :to="tab.path"
        class="relative flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl py-1.5 transition-colors"
        :class="isActive(tab.path) ? 'text-brand-700' : 'text-stone-400 hover:text-stone-700'"
        :aria-current="isActive(tab.path) ? 'page' : undefined"
      >
        <i :class="['bi', tab.icon, 'text-lg']" aria-hidden="true"></i>
        <span class="text-[10px] font-bold">{{ tab.name }}</span>
      </RouterLink>

      <button
        type="button"
        class="flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl py-1.5 text-stone-400 transition-colors hover:text-stone-700"
        :class="{ 'text-brand-700': moreOpen }"
        aria-haspopup="dialog"
        :aria-expanded="moreOpen"
        @click="emit('openMore')"
      >
        <i class="bi bi-three-dots text-lg" aria-hidden="true"></i>
        <span class="text-[10px] font-bold">เพิ่มเติม</span>
      </button>
    </div>
  </nav>
</template>
