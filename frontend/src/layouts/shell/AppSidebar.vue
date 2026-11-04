<script setup lang="ts">
/**
 * 🖥️ Sidebar เดสก์ท็อป — โลโก้ · เมนูแบบกลุ่ม · ย่อ/ขยาย · การ์ดผู้ใช้
 *
 * ใช้ข้อมูลกลุ่มเดียวกับหน้า "เพิ่มเติม" (`MORE_NAV_GROUPS`) ⇒ เดสก์ท็อปกับมือถือ
 * ไม่มีทางตันจากกัน: เพิ่มเมนูในกลุ่มเดียว ปรากฏทั้งสองที่
 *
 * 🚫 ไม่มีเมนูโปรไฟล์/บัญชีซ้ำ — การ์ดผู้ใช้พาไปหน้า "เพิ่มเติม" ที่เดียว
 *    (Stage 4 จะเปลี่ยนปลายทางเป็นการ์ดบัญชีส่วนกลาง `/account`)
 */
import { RouterLink, useRoute } from 'vue-router';
import {
  MORE_NAV_GROUPS,
  PRIMARY_NAV_ITEMS,
  isNavItemActive,
  type NavItem,
} from '@/constants/nav';

defineProps<{
  collapsed: boolean;
  userName: string;
  roleLabel: string;
  avatarChar: string;
}>();

const emit = defineEmits<{ toggleCollapse: [] }>();

const route = useRoute();

const itemClass = (path: string, collapsed: boolean) => [
  'flex h-11 items-center rounded-control text-sm transition-colors',
  collapsed ? 'justify-center px-0' : 'px-3',
  isNavItemActive(path, route.path)
    ? 'bg-brand-tint font-bold text-brand'
    : 'font-semibold text-ink-2 hover:bg-canvas hover:text-ink-1',
];

const allGroups = (): ReadonlyArray<{ title: string; items: readonly NavItem[] }> => [
  { title: 'เมนูหลัก', items: PRIMARY_NAV_ITEMS },
  ...MORE_NAV_GROUPS,
];
</script>

<template>
  <aside
    class="relative z-30 hidden shrink-0 transition-[width] duration-300 ease-smooth lg:flex"
    :class="collapsed ? 'lg:w-[80px]' : 'lg:w-[264px]'"
  >
    <div class="flex h-full flex-col overflow-hidden border-r border-line bg-surface">
      <!-- โลโก้ — ความสูงเท่า header (56px) เพื่อให้เส้นคั่นตรงกัน -->
      <RouterLink
        to="/dashboard"
        class="flex h-14 shrink-0 items-center border-b border-line px-4 transition-colors hover:bg-canvas"
        :class="collapsed ? 'justify-center px-0' : ''"
      >
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-brand text-white"
          :class="collapsed ? '' : 'me-3'"
        >
          <i class="bi bi-box-fill text-base"></i>
        </div>
        <span
          v-if="!collapsed"
          class="font-display whitespace-nowrap text-lg font-bold tracking-[0.16em] text-ink-1"
        >
          SYNC<span class="font-normal text-ink-3">ROOM</span>
        </span>
      </RouterLink>

      <!-- เมนู -->
      <div class="flex flex-1 flex-col overflow-y-auto overflow-x-hidden py-4">
        <nav class="flex-1 space-y-5 px-3">
          <div v-for="(group, index) in allGroups()" :key="group.title">
            <p
              v-if="!collapsed"
              class="mb-1.5 px-3 text-xs font-semibold text-ink-3"
            >
              {{ group.title }}
            </p>
            <div v-else-if="index > 0" class="mx-2 mb-2 border-t border-line"></div>

            <div class="space-y-0.5">
              <RouterLink
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                :class="itemClass(item.path, collapsed)"
                :title="collapsed ? item.name : undefined"
              >
                <!-- ความกว้างกล่องไอคอนคงที่ ⇒ ไอคอนต่างรูปทรง (เช่น bi-map) ไม่ทำให้ข้อความเหลื่อมกัน -->
                <i
                  :class="[
                    'bi',
                    item.icon,
                    'w-5 shrink-0 text-center text-lg',
                    collapsed ? '' : 'me-3',
                  ]"
                  aria-hidden="true"
                ></i>
                <span v-if="!collapsed" class="truncate">{{ item.name }}</span>
              </RouterLink>
            </div>
          </div>
        </nav>

        <!-- ปุ่มย่อ/ขยาย -->
        <div class="mt-4 px-3">
          <button
            type="button"
            class="flex h-10 w-full items-center justify-center gap-2 rounded-control border border-line text-xs font-bold text-ink-2 transition-colors hover:bg-canvas hover:text-ink-1"
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
      <div class="shrink-0 border-t border-line p-3">
        <!-- 👤 ไปหน้าบัญชีส่วนกลาง (ไม่ใช่หน้า "เพิ่มเติม") — บัญชีอยู่นอกห้อง -->
        <RouterLink
          to="/account"
          class="flex items-center gap-2 rounded-control p-1.5 transition-colors hover:bg-canvas"
          :class="collapsed ? 'justify-center p-1' : ''"
          :title="collapsed ? `${userName} · บัญชีส่วนกลาง` : 'บัญชีส่วนกลาง'"
        >
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-tint text-sm font-bold text-brand"
          >
            {{ avatarChar }}
          </div>
          <div v-if="!collapsed" class="ms-1 min-w-0 flex-1 overflow-hidden">
            <p class="truncate text-sm font-bold leading-tight text-ink-1">
              {{ userName }}
            </p>
            <p class="mt-0.5 truncate text-xs font-medium text-ink-3">{{ roleLabel }}</p>
          </div>
        </RouterLink>
      </div>
    </div>
  </aside>
</template>
