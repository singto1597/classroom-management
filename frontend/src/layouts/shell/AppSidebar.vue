<script setup lang="ts">
/**
 * 🖥️ Sidebar เดสก์ท็อป — โลโก้ · เมนูหลัก · ย่อ/ขยาย · การ์ดผู้ใช้
 *
 * ⚠️ ไม่มีเมนูตั้งค่าบัญชีซ้ำที่นี่ — header มีโปรไฟล์อยู่แล้ว
 *    (P1: หนึ่งปลายทาง = หนึ่งทางเข้า)
 */
import { RouterLink, useRoute } from 'vue-router';
import { NAV_ITEMS, isNavItemActive } from '@/constants/nav';

defineProps<{
  collapsed: boolean;
  userName: string;
  roleLabel: string;
  avatarChar: string;
}>();

const emit = defineEmits<{
  toggleCollapse: [];
  openAccount: [];
}>();

const route = useRoute();
const isActive = (path: string) => isNavItemActive(path, route.path);
</script>

<template>
  <aside
    class="relative z-30 hidden shrink-0 transition-[width] duration-300 ease-smooth lg:flex"
    :class="collapsed ? 'lg:w-[80px]' : 'lg:w-[264px]'"
  >
    <div class="flex h-full flex-col overflow-hidden border-r border-stone-200 bg-white">
      <!-- โลโก้ -->
      <RouterLink
        to="/dashboard"
        class="flex h-16 shrink-0 items-center border-b border-stone-200 px-5 transition-colors hover:bg-stone-50"
        :class="collapsed ? 'justify-center px-0' : ''"
      >
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
          :class="collapsed ? '' : 'me-3'"
        >
          <i class="bi bi-box-fill text-base"></i>
        </div>
        <span
          v-if="!collapsed"
          class="font-display whitespace-nowrap text-lg font-bold tracking-[0.2em] text-stone-900"
        >
          SYNC<span class="font-normal text-stone-400">ROOM</span>
        </span>
      </RouterLink>

      <!-- เมนู -->
      <div class="flex flex-1 flex-col overflow-y-auto overflow-x-hidden py-4">
        <p v-if="!collapsed" class="mb-2 px-5 text-[10px] font-bold text-stone-400">เมนูหลัก</p>

        <nav class="flex-1 space-y-0.5 px-3">
          <RouterLink
            v-for="item in NAV_ITEMS"
            :key="item.path"
            :to="item.path"
            class="group relative flex items-center rounded-xl transition-colors"
            :class="[
              collapsed ? 'w-full justify-center px-0 py-3' : 'px-3.5 py-2.5',
              isActive(item.path)
                ? 'bg-brand-50 font-bold text-brand-700'
                : 'font-semibold text-stone-500 hover:bg-stone-100 hover:text-stone-900',
            ]"
            :title="collapsed ? item.name : undefined"
          >
            <span
              v-if="isActive(item.path) && !collapsed"
              class="absolute inset-y-2 start-0 w-[3px] rounded-full bg-brand-700"
              aria-hidden="true"
            ></span>
            <i
              :class="['bi', item.icon, 'shrink-0', collapsed ? 'text-xl' : 'me-3 text-lg']"
              aria-hidden="true"
            ></i>
            <span v-if="!collapsed" class="truncate text-sm">{{ item.name }}</span>
          </RouterLink>
        </nav>

        <!-- ปุ่มย่อ/ขยาย -->
        <div class="mt-4 px-3">
          <button
            type="button"
            class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 py-2.5 text-xs font-bold text-stone-400 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-700"
            :title="collapsed ? 'ขยายเมนู' : 'ย่อเมนู'"
            @click="emit('toggleCollapse')"
          >
            <i
              :class="[
                'bi text-base',
                collapsed ? 'bi-chevron-double-right' : 'bi-chevron-double-left',
              ]"
              aria-hidden="true"
            ></i>
            <span v-if="!collapsed">ย่อเมนูบาร์</span>
          </button>
        </div>
      </div>

      <!-- ผู้ใช้ -->
      <div class="shrink-0 border-t border-stone-200 bg-stone-50/60 p-3">
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-xl border border-stone-200 bg-white p-1.5 text-left transition-colors hover:border-stone-300 hover:bg-stone-50"
          @click="emit('openAccount')"
        >
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-700 text-sm font-bold text-white"
          >
            {{ avatarChar }}
          </div>
          <div v-if="!collapsed" class="ms-3 min-w-0 overflow-hidden">
            <p class="truncate text-[13px] font-bold leading-tight text-stone-800">
              {{ userName }}
            </p>
            <p class="mt-0.5 truncate text-[10px] font-bold text-brand-700">{{ roleLabel }}</p>
          </div>
        </button>
      </div>
    </div>
  </aside>
</template>
