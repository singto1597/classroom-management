<script setup lang="ts">
/**
 * 🌐 GlobalLayout — เปลือกของหน้า **นอกห้องเรียน** (Lobby · Onboarding · Account)
 *
 * ตาม decision ของการรีดีไซน์: header ของเปลือกนี้มีแค่ **โลโก้ + ชื่อหน้า**
 * ไม่มี avatar/dropdown/การจัดการบัญชี — งานบัญชีทั้งหมดย้ายไปหน้า `/account`
 * (ซึ่งเข้าถึงได้แม้ยังไม่เลือกห้อง) เพื่อรองรับการขยายเป็นหลายห้องเรียนในอนาคต
 *
 * ใช้สูตรเดียวกับ MainLayout (PIRIvoice): ความสูงเต็มจอ + `<main>` เป็นที่เลื่อนเพียงจุดเดียว
 * ⇒ header/footer ไม่เลื่อนหาย และ safe-area ของมือถือทำงานถูก
 */
import { computed, onMounted } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

const route = useRoute();
const authStore = useAuthStore();

/**
 * ความกว้างเนื้อหา — อ่านจาก `route.meta.width` ชุดเดียวกับ MainLayout
 *   lobby = wide (การ์ดห้อง 3 คอลัมน์) · account = reading · ฟอร์ม = form
 */
const widthClass = computed(() => {
  switch (route.meta.width) {
    case 'reading':
      return 'max-w-3xl';
    case 'form':
      return 'max-w-2xl';
    default:
      return 'max-w-6xl';
  }
});

/** หน้าย่อยที่มีปุ่มย้อนกลับ — หน้า Lobby คือบ้านของเปลือกนี้จึงไม่ต้องมี */
const showBack = computed(() => route.meta.headerBack === true);

onMounted(async () => {
  // 🚨 ดึงข้อมูลให้สดเสมอ — sidebar/การ์ดบัญชีแสดงค่าจาก store
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
});
</script>

<template>
  <div class="relative flex h-[100dvh] flex-col overflow-hidden bg-canvas font-sans text-ink-1">
    <!-- ── Header: โลโก้ + ชื่อหน้า (ไม่มี avatar/dropdown) ─────────────── -->
    <header
      class="shrink-0 border-b border-line bg-surface"
      :style="{ paddingTop: 'env(safe-area-inset-top)' }"
    >
      <div class="mx-auto flex h-14 w-full items-center gap-1.5 px-3 sm:px-6" :class="widthClass">
        <RouterLink
          v-if="showBack"
          to="/lobby"
          class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-ink-1 transition-colors hover:bg-canvas"
          aria-label="กลับหน้าเลือกห้องเรียน"
        >
          <i class="bi bi-arrow-left text-lg" aria-hidden="true"></i>
        </RouterLink>

        <RouterLink v-else to="/lobby" class="flex h-11 shrink-0 items-center gap-2.5 px-1">
          <span
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-brand text-white"
          >
            <i class="bi bi-box-fill text-sm" aria-hidden="true"></i>
          </span>
          <span class="font-display hidden text-base font-bold text-ink-1 sm:inline">
            SYNC<span class="font-normal text-ink-3">ROOM</span>
          </span>
        </RouterLink>

        <h1 class="min-w-0 flex-1 truncate px-1.5 text-base font-bold text-ink-1">
          {{ route.meta.title }}
        </h1>

        <RouterLink
          v-if="showBack"
          to="/lobby"
          class="hidden h-11 shrink-0 items-center gap-1.5 rounded-control px-2 text-sm font-semibold text-ink-2 transition-colors hover:bg-canvas hover:text-ink-1 sm:inline-flex"
        >
          <i class="bi bi-grid-1x2 text-sm" aria-hidden="true"></i>
          ห้องเรียน
        </RouterLink>
      </div>
    </header>

    <!-- ── Main: ที่เลื่อนได้เพียงจุดเดียว ─────────────────────────────── -->
    <main class="flex-1 overflow-y-auto overflow-x-hidden overscroll-contain px-4 py-5 sm:px-6 sm:py-8">
      <div class="mx-auto w-full" :class="widthClass">
        <RouterView v-slot="{ Component, route: r }">
          <component :is="Component" :key="r.path" />
        </RouterView>
      </div>
    </main>

    <!-- ── Footer: จุดปิดท้ายแบบเส้นบาง ────────────────────────────────── -->
    <footer class="shrink-0 border-t border-line bg-surface">
      <div
        class="mx-auto flex w-full flex-col items-center justify-between gap-1 px-4 py-3 text-[11px] text-ink-3 sm:flex-row sm:px-6"
        :class="widthClass"
      >
        <p class="font-semibold">SYNCROOM — ระบบจัดการห้องเรียน</p>
        <p>เวลาไทย (Asia/Bangkok)</p>
      </div>
    </footer>
  </div>
</template>
