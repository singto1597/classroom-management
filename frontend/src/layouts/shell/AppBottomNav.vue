<script setup lang="ts">
/**
 * 📱 แถบนำทางล่าง — 5 ปลายทางเต็มความกว้าง (PIRIvoice)
 *
 * 🔑 ไฮไลต์จาก `route.meta.navTab` ไม่ใช่ `startsWith(path)` — หน้า detail
 *    เช่น `/finance/receipts/REC-…` ยังต้องไฮไลต์แท็บ "การเงิน" และ `/more`
 *    ไฮไลต์เมื่ออยู่หน้าใดก็ตามที่ประกาศ `navTab: 'more'`
 *
 * ความสูง `--app-nav-h` (3.5rem) + safe-area ⇒ MainLayout/FAB/sticky bars
 * ใช้ค่าเดียวกันทั้งหมด จะได้ไม่ต้องเดาความสูงซ้ำหลายที่
 */
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import { NAV_TABS } from '@/constants/nav';

const route = useRoute();
const activeTab = computed(() => route.meta.navTab ?? null);
</script>

<template>
  <nav
    class="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
    aria-label="เมนูหลัก"
  >
    <div class="mx-auto flex h-[var(--app-nav-h)] w-full max-w-lg items-stretch">
      <RouterLink
        v-for="tab in NAV_TABS"
        :key="tab.key"
        :to="tab.path"
        class="flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 transition-colors"
        :class="
          activeTab === tab.key
            ? 'font-bold text-brand'
            : 'font-semibold text-ink-3 hover:text-ink-1'
        "
        :aria-current="activeTab === tab.key ? 'page' : undefined"
      >
        <i :class="['bi', tab.icon, 'text-lg']" aria-hidden="true"></i>
        <span class="w-full truncate text-center text-xs leading-tight">{{ tab.name }}</span>
      </RouterLink>
    </div>
  </nav>
</template>
