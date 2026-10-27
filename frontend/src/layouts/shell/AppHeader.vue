<script setup lang="ts">
/**
 * 🔝 Header — ปุ่มย้อนกลับ (จาก `route.meta.headerBack`) · breadcrumb ห้อง · โปรไฟล์
 *
 * ⚠️ ปุ่มย้อนกลับมีที่เดียวคือที่นี่ — หน้าลูกต้องไม่วาดปุ่มย้อนของตัวเองซ้ำ
 *    (DoD P1: ไม่มี route ที่มีปุ่มย้อน 2 อัน)
 */
import { computed } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import type { ShellMenu } from './useAppShell';

defineProps<{
  roomId: number | null;
  roomName: string;
  subMenuName: string | null;
  userName: string;
  roleLabel: string;
  avatarChar: string;
  activeDropdown: ShellMenu | null;
}>();

const emit = defineEmits<{
  changeRoom: [];
  toggleDropdown: [event: MouseEvent, menu: ShellMenu];
}>();

const route = useRoute();
const router = useRouter();

const canGoBack = computed(() => route.meta.headerBack === true);

const goBack = () => {
  if (window.history.length > 1) router.back();
  else router.push('/');
};
</script>

<template>
  <header
    class="z-20 shrink-0 border-b border-stone-200 bg-white"
    :style="{ paddingTop: 'env(safe-area-inset-top)' }"
  >
    <div class="flex h-14 items-center justify-between gap-3 px-4 sm:h-16 sm:px-6">
      <!-- ซ้าย: ปุ่มย้อนกลับ / โลโก้มือถือ / breadcrumb -->
      <div class="flex min-w-0 items-center gap-2">
        <button
          v-if="canGoBack"
          type="button"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-900"
          aria-label="ย้อนกลับ"
          @click="goBack"
        >
          <i class="bi bi-arrow-left text-lg" aria-hidden="true"></i>
        </button>

        <RouterLink
          v-else
          to="/dashboard"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white lg:hidden"
          aria-label="หน้าหลัก"
        >
          <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
        </RouterLink>

        <div class="flex min-w-0 items-center gap-1.5 text-sm font-bold text-stone-700">
          <template v-if="roomId">
            <button
              type="button"
              class="flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2 text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
              aria-haspopup="menu"
              :aria-expanded="activeDropdown === 'roomSwitcher'"
              @click.stop="emit('toggleDropdown', $event, 'roomSwitcher')"
            >
              <span class="max-w-[110px] truncate sm:max-w-[180px]">
                {{ roomName || roomId }}
              </span>
              <i class="bi bi-chevron-down text-[10px] opacity-50" aria-hidden="true"></i>
            </button>

            <template v-if="subMenuName">
              <i
                class="bi bi-chevron-right shrink-0 text-[10px] text-stone-300"
                aria-hidden="true"
              ></i>
              <span class="max-w-[90px] truncate px-1 text-brand-700 sm:max-w-[140px]">
                {{ subMenuName }}
              </span>
            </template>
          </template>

          <template v-else>
            <span class="font-display text-base tracking-tight text-stone-900">
              SYNC<span class="font-normal text-stone-400">ROOM</span>
            </span>
          </template>
        </div>
      </div>

      <!-- ขวา: โปรไฟล์ -->
      <div class="flex shrink-0 items-center gap-2">
        <button
          type="button"
          class="flex items-center rounded-full border border-stone-200 bg-white p-1 transition-colors hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30 sm:pe-3.5"
          :class="{ 'ring-2 ring-brand-500/25': activeDropdown === 'headerSettings' }"
          aria-haspopup="menu"
          :aria-expanded="activeDropdown === 'headerSettings'"
          @click.stop="emit('toggleDropdown', $event, 'headerSettings')"
        >
          <div
            class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-700 text-sm font-bold text-white"
          >
            {{ avatarChar }}
          </div>
          <div class="ms-2.5 hidden text-left sm:block">
            <p class="text-[13px] font-bold leading-tight text-stone-800">{{ userName }}</p>
            <p class="mt-0.5 text-[10px] font-bold text-brand-700">{{ roleLabel }}</p>
          </div>
          <i
            class="bi bi-chevron-down ms-2.5 hidden text-[10px] text-stone-400 sm:block"
            aria-hidden="true"
          ></i>
        </button>
      </div>
    </div>
  </header>
</template>
