<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { RouterView, useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';
import { StudentService } from '@/services/student';

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

// 🌙 สถานะ sidebar (desktop) + bottom sheet (มือถือ)
const isMoreSheetOpen = ref(false);
const isSidebarCollapsed = ref(false);
const activeDropdown = ref<string | null>(null);

// จำสถานะย่อ sidebar ไว้ใช้ครั้งถัดไป
const COLLAPSE_KEY = 'syncroom_sidebar_collapsed';

onMounted(async () => {
  isSidebarCollapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1';
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
  // 🔁 ปิด Dropdown เมื่อมีการ Scroll หน้าจอ
  window.addEventListener('scroll', closeDropdowns, true);
  window.addEventListener('resize', closeDropdowns);
});

onUnmounted(() => {
  window.removeEventListener('scroll', closeDropdowns, true);
  window.removeEventListener('resize', closeDropdowns);
});

// ✨ ระบบชื่อและรูปโปรไฟล์
const displayName = computed(() => authStore.currentUserName);
const avatarChar = computed(() => {
  const name = authStore.nickname || authStore.firstName;
  return name && name !== 'ไม่ระบุชื่อ' ? name.charAt(0).toUpperCase() : 'ส';
});

// 🎯 Dropdown System (ฉลาดขึ้น & ไม่ล้นจอ)
const dropdownStyle = ref<{ top: string; left: string; bottom?: string }>({ top: '0px', left: '0px' });

const toggleDropdown = (event: MouseEvent, dropdownName: string) => {
  if (activeDropdown.value === dropdownName) {
    closeDropdowns();
    return;
  }

  activeDropdown.value = dropdownName;

  const trigger = event.currentTarget as HTMLElement;
  const rect = trigger.getBoundingClientRect();
  const panelWidth = 240;
  const panelHeight = 220;

  let left = rect.right - panelWidth;
  left = Math.max(12, Math.min(left, window.innerWidth - panelWidth - 12));

  const spaceBelow = window.innerHeight - rect.bottom;

  if (spaceBelow < panelHeight) {
    dropdownStyle.value = {
      top: 'auto',
      bottom: `${window.innerHeight - rect.top + 8}px`,
      left: `${left}px`,
    };
  } else {
    dropdownStyle.value = {
      top: `${rect.bottom + 8}px`,
      bottom: 'auto',
      left: `${left}px`,
    };
  }
};

const closeDropdowns = () => {
  activeDropdown.value = null;
};

const openMoreSheet = () => {
  closeDropdowns();
  isMoreSheetOpen.value = true;
};
const closeMoreSheet = () => {
  isMoreSheetOpen.value = false;
};

watch(
  () => route.path,
  () => {
    closeMoreSheet();
    closeDropdowns();
  },
);

// Toggle Sidebar Desktop
const toggleSidebarCollapse = () => {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
  localStorage.setItem(COLLAPSE_KEY, isSidebarCollapsed.value ? '1' : '0');
};

// ---------------- เมนู ----------------
type MenuItem = { name: string; path: string; icon: string };

const menuItems: MenuItem[] = [
  { name: 'แดชบอร์ด', path: '/dashboard', icon: 'bi-grid' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people' },
  { name: 'งานและโน้ต', path: '/tasks', icon: 'bi-clipboard-check' },
  { name: 'ตารางเรียน', path: '/schedules', icon: 'bi-calendar-event' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
  { name: 'กิจกรรม', path: '/activities', icon: 'bi-calendar-heart' },
  { name: 'ประกาศ Discord', path: '/messages', icon: 'bi-megaphone' },
  { name: 'แผนผังห้องเรียน', path: '/roadmap', icon: 'bi-map' },
];

// แท็บบนมือถือ 4 ช่อง (ช่องกลางเป็น FAB)
const bottomTabs = computed<MenuItem[]>(() => [
  { name: 'หน้าแรก', path: '/dashboard', icon: 'bi-house-door' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
]);

const canManageTasks = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_TASKS'),
);

// เมนูที่เหลือในชีต "เพิ่มเติม" (มือถือ) — ตัดตัวที่อยู่ในแท็บล่างออกแล้ว
const moreItems = computed<MenuItem[]>(() =>
  menuItems.filter((i) => !['/dashboard', '/students', '/finance'].includes(i.path)),
);

const isItemActive = (path: string) =>
  path === '/dashboard'
    ? route.path === '/dashboard' || route.path === '/'
    : route.path.startsWith(path);

// ชื่อเมนูย่อยสำหรับ breadcrumb
const currentSubMenuName = computed(() => {
  if (route.path === '/dashboard' || route.path === '/') return null;
  const matchedMenu = menuItems.find(
    (item) => item.path !== '/dashboard' && route.path.startsWith(item.path),
  );
  return matchedMenu ? matchedMenu.name : null;
});

// ---------------- การทำงาน ----------------
const handleChangeRoom = () => {
  closeDropdowns();
  closeMoreSheet();
  authStore.clearRoom();
  router.push('/lobby');
};

const goToMyProfile = async () => {
  closeDropdowns();
  closeMoreSheet();
  try {
    Swal.fire({
      title: 'กำลังโหลดข้อมูล...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading(),
    });
    const myProfile = await StudentService.getMyProfile(authStore.currentRoomId!);
    Swal.close();
    router.push(`/students/${myProfile.student_no}`);
  } catch {
    Swal.fire({
      icon: 'warning',
      title: 'ไม่สามารถเข้าถึงได้',
      text: 'คุณอาจเป็นผู้ดูแลระบบ (Admin) ที่ไม่มีข้อมูลในรายชื่อนักเรียนห้องนี้',
      confirmButtonColor: '#1d4ed8',
    });
  }
};

const showAccountInfo = () => {
  closeDropdowns();
  Swal.fire({
    title: '<span style="font-family:Anuphan;font-weight:700">ข้อมูลบัญชีระบบ</span>',
    html: `
      <div style="text-align:left;margin-top:18px;display:flex;flex-direction:column;gap:14px">
        <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #E7E5E4;padding-bottom:12px">
          <span style="font-size:13px;color:#78716C;font-weight:600">Discord ID</span>
          <span style="font-family:ui-monospace,monospace;font-size:13px;font-weight:700;color:#1C1917">${authStore.discordId || 'ยังไม่ระบุ'}</span>
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-size:13px;color:#78716C;font-weight:600">บทบาทในห้อง</span>
          <span style="font-size:12px;font-weight:700;color:#1D4ED8;background:#EFF6FF;padding:4px 10px;border-radius:8px">${authStore.currentRoleLabel}</span>
        </div>
      </div>
    `,
    icon: 'info',
    confirmButtonText: 'ปิดหน้าต่าง',
    confirmButtonColor: '#1d4ed8',
  });
};

const logout = () => {
  closeDropdowns();
  closeMoreSheet();
  authStore.logout();
};

const goToProfileSettings = async () => {
  closeDropdowns();
  closeMoreSheet();

  Swal.fire({
    title: 'กำลังโหลดข้อมูล...',
    allowOutsideClick: false,
    didOpen: () => Swal.showLoading(),
  });
  await authStore.fetchProfile();
  Swal.close();

  const isDiscordLinked = !!authStore.discordId;
  const isGoogleLinked = !!authStore.googleId;

  const discordScope = encodeURIComponent('identify email');
  const discordUrl = `https://discord.com/api/oauth2/authorize?client_id=${import.meta.env.VITE_DISCORD_CLIENT_ID}&redirect_uri=${encodeURIComponent(import.meta.env.VITE_DISCORD_REDIRECT_URI)}&response_type=code&scope=${discordScope}`;

  const googleScope = encodeURIComponent('openid email profile');
  const googleUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${import.meta.env.VITE_GOOGLE_CLIENT_ID}&redirect_uri=${encodeURIComponent(import.meta.env.VITE_GOOGLE_REDIRECT_URI)}&response_type=code&scope=${googleScope}`;

  const row = (linked: boolean, label: string, sub: string, icon: string, href: string) => `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px;border-radius:14px;border:1px solid ${linked ? '#A7F3D0' : '#E7E5E4'};background:${linked ? '#ECFDF5' : '#FFFFFF'}">
      <div style="display:flex;align-items:center;gap:12px;min-width:0">
        <div style="width:40px;height:40px;border-radius:12px;background:#F5F5F4;display:flex;align-items:center;justify-content:center;flex-shrink:0">
          <i class="${icon}" style="font-size:18px"></i>
        </div>
        <div style="text-align:left;min-width:0">
          <p style="font-weight:700;color:#1C1917;margin:0;font-size:14px">${label}</p>
          <p style="font-size:11px;font-weight:700;margin:2px 0 0;color:${linked ? '#059669' : '#A8A29E'}">${linked ? 'เชื่อมต่อแล้ว' : sub}</p>
        </div>
      </div>
      ${!linked ? `<a href="${href}" style="flex-shrink:0;padding:8px 16px;background:#1D4ED8;color:#fff;font-size:12px;font-weight:700;border-radius:10px;text-decoration:none">ผูกบัญชี</a>` : ''}
    </div>
  `;

  Swal.fire({
    title: '<span style="font-family:Anuphan;font-weight:700;font-size:19px">จัดการบัญชีและการเชื่อมต่อ</span>',
    html: `
      <div style="text-align:left;display:flex;flex-direction:column;gap:12px;margin-top:16px">
        <p style="font-size:13px;color:#78716C;margin:0">เชื่อมต่อแพลตฟอร์มต่างๆ เพื่อรวมข้อมูลของคุณให้เป็นหนึ่งเดียว ป้องกันการสูญหาย</p>
        ${row(isGoogleLinked, 'Google Account', 'ยังไม่ได้เชื่อมต่อ', 'bi bi-google', googleUrl)}
        ${row(isDiscordLinked, 'Discord Account', 'ยังไม่ได้เชื่อมต่อ', 'bi bi-discord', discordUrl)}
      </div>
    `,
    showConfirmButton: true,
    confirmButtonText: 'ปิดหน้าต่าง',
    confirmButtonColor: '#1d4ed8',
  });
};
</script>

<template>
  <div class="relative flex h-screen h-dvh overflow-hidden bg-paper font-sans text-ink">
    <!-- ============================================
         🖥️ DESKTOP SIDEBAR
         ============================================ -->
    <aside
      class="relative z-30 hidden shrink-0 transition-[width] duration-300 ease-smooth lg:flex"
      :class="isSidebarCollapsed ? 'lg:w-[80px]' : 'lg:w-[264px]'"
    >
      <div class="flex h-full flex-col overflow-hidden border-r border-stone-200 bg-white">
        <!-- โลโก้ -->
        <RouterLink
          to="/dashboard"
          class="flex h-16 shrink-0 items-center border-b border-stone-200 px-5 transition-colors hover:bg-stone-50"
          :class="isSidebarCollapsed ? 'justify-center px-0' : ''"
        >
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
            :class="isSidebarCollapsed ? '' : 'me-3'"
          >
            <i class="bi bi-box-fill text-base"></i>
          </div>
          <span
            v-if="!isSidebarCollapsed"
            class="font-display whitespace-nowrap text-lg font-bold tracking-[0.2em] text-stone-900"
          >
            SYNC<span class="font-normal text-stone-400">ROOM</span>
          </span>
        </RouterLink>

        <!-- เมนู -->
        <div class="flex flex-1 flex-col overflow-y-auto overflow-x-hidden py-4">
          <p
            v-if="!isSidebarCollapsed"
            class="mb-2 px-5 text-[10px] font-bold uppercase tracking-[0.16em] text-stone-400"
          >
            เมนูหลัก
          </p>

          <nav class="flex-1 space-y-0.5 px-3">
            <RouterLink
              v-for="item in menuItems"
              :key="item.path"
              :to="item.path"
              class="group relative flex items-center rounded-xl transition-colors"
              :class="[
                isSidebarCollapsed ? 'w-full justify-center px-0 py-3' : 'px-3.5 py-2.5',
                isItemActive(item.path)
                  ? 'bg-brand-50 font-bold text-brand-700'
                  : 'font-semibold text-stone-500 hover:bg-stone-100 hover:text-stone-900',
              ]"
              :title="isSidebarCollapsed ? item.name : undefined"
            >
              <!-- แถบ indicator ด้านซ้ายเมื่อ active -->
              <span
                v-if="isItemActive(item.path) && !isSidebarCollapsed"
                class="absolute inset-y-2 start-0 w-[3px] rounded-full bg-brand-700"
                aria-hidden="true"
              ></span>
              <i
                :class="[
                  'bi',
                  item.icon,
                  'shrink-0',
                  isSidebarCollapsed ? 'text-xl' : 'me-3 text-lg',
                ]"
                aria-hidden="true"
              ></i>
              <span v-if="!isSidebarCollapsed" class="truncate text-sm">{{ item.name }}</span>
            </RouterLink>
          </nav>

          <!-- ปุ่มย่อ/ขยาย -->
          <div class="mt-4 px-3">
            <button
              type="button"
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-stone-200 py-2.5 text-xs font-bold text-stone-400 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-700"
              :title="isSidebarCollapsed ? 'ขยายเมนู' : 'ย่อเมนู'"
              @click="toggleSidebarCollapse"
            >
              <i
                :class="[
                  'bi text-base',
                  isSidebarCollapsed ? 'bi-chevron-double-right' : 'bi-chevron-double-left',
                ]"
                aria-hidden="true"
              ></i>
              <span v-if="!isSidebarCollapsed">ย่อเมนูบาร์</span>
            </button>
          </div>
        </div>

        <!-- ผู้ใช้ -->
        <div class="shrink-0 border-t border-stone-200 bg-stone-50/60 p-3">
          <div
            class="flex items-center gap-2 rounded-xl border border-stone-200 bg-white p-1.5"
          >
            <button
              type="button"
              class="flex min-w-0 flex-1 cursor-pointer items-center overflow-hidden text-left"
              @click="showAccountInfo"
            >
              <div
                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-700 text-sm font-bold text-white"
              >
                {{ avatarChar }}
              </div>
              <div v-if="!isSidebarCollapsed" class="ms-3 overflow-hidden">
                <p class="truncate text-[13px] font-bold leading-tight text-stone-800">
                  {{ displayName }}
                </p>
                <p
                  class="mt-0.5 truncate text-[10px] font-bold uppercase tracking-wider text-brand-700"
                >
                  {{ authStore.currentRoleLabel }}
                </p>
              </div>
            </button>

            <button
              type="button"
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-800"
              :class="{ 'bg-stone-100 text-stone-800': activeDropdown === 'sidebarSettings' }"
              :title="isSidebarCollapsed ? 'การตั้งค่า' : undefined"
              @click.stop="toggleDropdown($event, 'sidebarSettings')"
            >
              <i class="bi bi-three-dots-vertical text-lg" aria-hidden="true"></i>
            </button>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============================================
         ⚙️ พื้นที่หลัก (Header + เนื้อหา)
         ============================================ -->
    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <!-- Header -->
      <header
        class="z-20 shrink-0 border-b border-stone-200 bg-white"
        :style="{ paddingTop: 'env(safe-area-inset-top)' }"
      >
        <div class="flex h-16 items-center justify-between gap-3 px-4 sm:px-6">
          <!-- ซ้าย: โลโก้ (มือถือ) + breadcrumb -->
          <div class="flex min-w-0 items-center gap-2">
            <RouterLink
              to="/dashboard"
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white lg:hidden"
              aria-label="หน้าแรก"
            >
              <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
            </RouterLink>

            <div class="flex min-w-0 items-center gap-1.5 text-sm font-bold text-stone-700">
              <template v-if="authStore.currentRoomId">
                <button
                  type="button"
                  class="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-brand-50 hover:text-brand-700 sm:flex"
                  title="หน้าเลือกห้อง"
                  @click="handleChangeRoom"
                >
                  <i class="bi bi-grid-3x3-gap text-base" aria-hidden="true"></i>
                </button>

                <button
                  type="button"
                  class="flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2 text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
                  @click.stop="toggleDropdown($event, 'breadcrumbMenu')"
                >
                  <span class="max-w-[110px] truncate sm:max-w-[180px]">
                    {{ authStore.currentRoomName || authStore.currentRoomId }}
                  </span>
                  <i class="bi bi-chevron-down text-[10px] opacity-50" aria-hidden="true"></i>
                </button>

                <template v-if="currentSubMenuName">
                  <i
                    class="bi bi-chevron-right shrink-0 text-[10px] text-stone-300"
                    aria-hidden="true"
                  ></i>
                  <span class="max-w-[90px] truncate px-1 text-brand-700 sm:max-w-[140px]">
                    {{ currentSubMenuName }}
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

          <!-- ขวา: ปุ่มสลับห้อง + โปรไฟล์ -->
          <div class="flex shrink-0 items-center gap-2">
            <button
              v-if="authStore.currentRoomId"
              type="button"
              class="hidden h-10 w-10 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-800 sm:flex"
              title="สลับห้องเรียน"
              @click="handleChangeRoom"
            >
              <i class="bi bi-arrow-left-right text-base" aria-hidden="true"></i>
            </button>

            <div class="relative">
              <button
                type="button"
                class="flex items-center rounded-full border border-stone-200 bg-white p-1 transition-colors hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30 sm:pe-3.5"
                :class="{ 'ring-2 ring-brand-500/25': activeDropdown === 'headerSettings' }"
                @click.stop="toggleDropdown($event, 'headerSettings')"
              >
                <div
                  class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-700 text-sm font-bold text-white"
                >
                  {{ avatarChar }}
                </div>
                <div class="ms-2.5 hidden text-left sm:block">
                  <p class="text-[13px] font-bold leading-tight text-stone-800">
                    {{ displayName }}
                  </p>
                  <p class="mt-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-700">
                    {{ authStore.currentRoleLabel }}
                  </p>
                </div>
                <i
                  class="bi bi-chevron-down ms-2.5 hidden text-[10px] text-stone-400 sm:block"
                  aria-hidden="true"
                ></i>
              </button>
            </div>
          </div>
        </div>
      </header>

      <!-- เนื้อหา — scroll เกิดที่นี่ที่เดียว -->
      <main
        class="flex-1 overflow-y-auto overflow-x-hidden p-4 pb-[calc(env(safe-area-inset-bottom)+7rem)] focus:outline-none sm:p-6 lg:p-8 lg:pb-8"
      >
        <div class="page-wrap">
          <RouterView v-slot="{ Component, route: r }">
            <transition name="fade-slide" mode="out-in">
              <div :key="r.path">
                <component :is="Component" />
              </div>
            </transition>
          </RouterView>
        </div>
      </main>
    </div>

    <!-- ============================================
         📱 BOTTOM TAB BAR (มือถือ)
         ============================================ -->
    <nav
      class="fixed inset-x-0 bottom-0 z-40 px-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] lg:hidden"
      aria-label="เมนูหลัก"
    >
      <div
        class="mx-auto flex max-w-[460px] items-center justify-between gap-0.5 rounded-3xl border border-stone-200 bg-white px-1.5 py-1.5 shadow-[0_10px_34px_-14px_rgba(28,25,23,0.28)]"
      >
        <!-- แท็บ 1–2 -->
        <RouterLink
          v-for="tab in bottomTabs.slice(0, 2)"
          :key="tab.path"
          :to="tab.path"
          class="relative flex flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl py-2 transition-colors"
          :class="
            isItemActive(tab.path)
              ? 'text-brand-700'
              : 'text-stone-400 hover:text-stone-700'
          "
          :aria-current="isItemActive(tab.path) ? 'page' : undefined"
        >
          <i :class="['bi', tab.icon, 'text-xl']" aria-hidden="true"></i>
          <span class="text-[10px] font-bold">{{ tab.name }}</span>
        </RouterLink>

        <!-- ★ FAB กลาง -->
        <div class="flex shrink-0 items-center justify-center px-0.5">
          <RouterLink
            v-if="canManageTasks"
            to="/tasks/add"
            class="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-700 text-white transition-transform active:scale-95"
            aria-label="เพิ่มงานหรือโน้ตใหม่"
          >
            <i class="bi bi-plus-lg text-xl" aria-hidden="true"></i>
          </RouterLink>
          <button
            v-else
            type="button"
            class="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-700 text-white transition-transform active:scale-95"
            aria-label="เปิดเมนูทั้งหมด"
            @click="openMoreSheet"
          >
            <i class="bi bi-plus-lg text-xl" aria-hidden="true"></i>
          </button>
        </div>

        <!-- แท็บ 3 -->
        <RouterLink
          v-for="tab in bottomTabs.slice(2)"
          :key="tab.path"
          :to="tab.path"
          class="relative flex flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl py-2 transition-colors"
          :class="
            isItemActive(tab.path)
              ? 'text-brand-700'
              : 'text-stone-400 hover:text-stone-700'
          "
          :aria-current="isItemActive(tab.path) ? 'page' : undefined"
        >
          <i :class="['bi', tab.icon, 'text-xl']" aria-hidden="true"></i>
          <span class="text-[10px] font-bold">{{ tab.name }}</span>
        </RouterLink>

        <!-- แท็บ 4: เพิ่มเติม -->
        <button
          type="button"
          class="flex flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl py-2 text-stone-400 transition-colors hover:text-stone-700"
          :class="{ 'text-brand-700': isMoreSheetOpen }"
          @click="openMoreSheet"
        >
          <i class="bi bi-three-dots text-xl" aria-hidden="true"></i>
          <span class="text-[10px] font-bold">เพิ่มเติม</span>
        </button>
      </div>
    </nav>

    <!-- ============================================
         📱 BOTTOM SHEET — เมนู "เพิ่มเติม"
         ============================================ -->
    <Transition name="sheet-fade">
      <div
        v-if="isMoreSheetOpen"
        class="fixed inset-0 z-50 bg-stone-900/40 lg:hidden"
        @click="closeMoreSheet"
      ></div>
    </Transition>

    <Transition name="sheet-slide">
      <div
        v-if="isMoreSheetOpen"
        class="fixed inset-x-0 bottom-0 z-[60] flex max-h-[86vh] flex-col overflow-hidden rounded-t-3xl border-t border-stone-200 bg-white lg:hidden"
        role="dialog"
        aria-label="เมนูเพิ่มเติม"
      >
        <!-- drag handle (แสดงผลเท่านั้น) -->
        <div class="flex shrink-0 justify-center pt-3" aria-hidden="true">
          <div class="h-1 w-10 rounded-full bg-stone-300"></div>
        </div>

        <div class="flex shrink-0 items-center justify-between px-5 pb-3 pt-3">
          <div>
            <p class="eyebrow mb-1">เมนูทั้งหมด</p>
            <p class="font-display text-lg font-bold text-stone-900">
              {{ authStore.currentRoomName || 'SYNCROOM' }}
            </p>
          </div>
          <button
            type="button"
            class="flex h-10 w-10 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-800"
            aria-label="ปิดเมนู"
            @click="closeMoreSheet"
          >
            <i class="bi bi-x-lg text-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
          <nav class="grid grid-cols-3 gap-2">
            <RouterLink
              v-for="item in moreItems"
              :key="item.path"
              :to="item.path"
              class="flex flex-col items-center justify-center gap-2 rounded-2xl border px-2 py-4 text-center transition-colors"
              :class="
                isItemActive(item.path)
                  ? 'border-brand-200 bg-brand-50 text-brand-700'
                  : 'border-stone-200 bg-white text-stone-600 hover:bg-stone-50'
              "
            >
              <i :class="['bi', item.icon, 'text-2xl']" aria-hidden="true"></i>
              <span class="text-[11px] font-bold leading-tight">{{ item.name }}</span>
            </RouterLink>
          </nav>

          <div class="my-4 h-px bg-stone-200"></div>

          <p class="mb-2 px-1 text-[10px] font-bold uppercase tracking-[0.16em] text-stone-400">
            บัญชี
          </p>
          <div class="space-y-1">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
              @click="goToMyProfile"
            >
              <i class="bi bi-person-badge text-lg text-stone-400" aria-hidden="true"></i>
              โปรไฟล์ของฉัน
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
              @click="goToProfileSettings"
            >
              <i class="bi bi-link-45deg text-xl text-stone-400" aria-hidden="true"></i>
              จัดการผูกบัญชี
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
              @click="handleChangeRoom"
            >
              <i class="bi bi-arrow-left-right text-lg text-stone-400" aria-hidden="true"></i>
              สลับห้องเรียน
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-red-600 transition-colors hover:bg-red-50"
              @click="logout"
            >
              <i class="bi bi-box-arrow-right text-lg" aria-hidden="true"></i>
              ออกจากระบบ
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ============================================
         🗂️ DROPDOWNS (Teleport)
         ============================================ -->
    <Teleport to="body">
      <div v-if="activeDropdown" class="fixed inset-0 z-[70]" @click="closeDropdowns"></div>

      <!-- ตั้งค่าบัญชี (sidebar) -->
      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown === 'sidebarSettings'"
          class="fixed z-[80] w-60 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-stone-200 bg-white py-1.5 shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
          :style="dropdownStyle"
        >
          <p
            class="mb-1 border-b border-stone-100 bg-stone-50/70 px-4 py-2.5 text-[10px] font-bold uppercase tracking-[0.16em] text-stone-400"
          >
            การจัดการบัญชี
          </p>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-brand-50 hover:text-brand-700"
            @click.stop="goToMyProfile"
          >
            <i class="bi bi-person-badge text-lg opacity-70" aria-hidden="true"></i>
            โปรไฟล์ของฉัน
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-brand-50 hover:text-brand-700"
            @click.stop="goToProfileSettings"
          >
            <i class="bi bi-link-45deg text-xl opacity-70" aria-hidden="true"></i>
            จัดการผูกบัญชี
          </button>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-brand-50 hover:text-brand-700"
            @click.stop="handleChangeRoom"
          >
            <i class="bi bi-arrow-left-right text-lg opacity-70" aria-hidden="true"></i>
            สลับห้องเรียน
          </button>
          <div class="mx-3 my-1.5 h-px bg-stone-100"></div>
          <button
            type="button"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm font-bold text-red-600 transition-colors hover:bg-red-50"
            @click.stop="logout"
          >
            <i class="bi bi-box-arrow-right text-lg" aria-hidden="true"></i>
            ออกจากระบบ
          </button>
        </div>
      </Transition>

      <!-- เมนูด่วน (breadcrumb) -->
      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown === 'breadcrumbMenu'"
          class="fixed z-[80] w-60 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-stone-200 bg-white py-1.5 shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
          :style="dropdownStyle"
        >
          <p
            class="mb-1 border-b border-stone-100 bg-stone-50/70 px-4 py-2.5 text-[10px] font-bold uppercase tracking-[0.16em] text-stone-400"
          >
            เมนูด่วน
          </p>
          <RouterLink
            v-for="item in menuItems"
            :key="item.path"
            :to="item.path"
            class="flex items-center px-4 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:bg-brand-50 hover:text-brand-700"
            @click="closeDropdowns"
          >
            <i :class="['bi', item.icon, 'me-3 text-base opacity-70']" aria-hidden="true"></i>
            {{ item.name }}
          </RouterLink>
        </div>
      </Transition>

      <!-- โปรไฟล์ (header) -->
      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown === 'headerSettings'"
          class="fixed z-[80] flex w-64 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
          :style="dropdownStyle"
        >
          <div class="flex items-center gap-3 border-b border-stone-100 bg-stone-50/70 px-5 py-4">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-700 text-base font-bold text-white"
            >
              {{ avatarChar }}
            </div>
            <div class="min-w-0">
              <p class="truncate text-sm font-bold leading-tight text-stone-800">
                {{ displayName }}
              </p>
              <p class="mt-0.5 truncate text-[11px] font-bold uppercase tracking-wider text-brand-700">
                {{ authStore.currentRoleLabel }}
              </p>
            </div>
          </div>
          <div class="py-1.5">
            <button
              type="button"
              class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-50 hover:text-brand-700"
              @click.stop="goToMyProfile"
            >
              <i class="bi bi-person-badge text-lg opacity-70" aria-hidden="true"></i>
              โปรไฟล์ของฉัน
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-50 hover:text-brand-700"
              @click.stop="goToProfileSettings"
            >
              <i class="bi bi-link-45deg text-xl opacity-70" aria-hidden="true"></i>
              จัดการบัญชีเชื่อมต่อ
            </button>
            <button
              type="button"
              class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-50 hover:text-brand-700"
              @click.stop="handleChangeRoom"
            >
              <i class="bi bi-grid-3x3-gap text-base opacity-70" aria-hidden="true"></i>
              สลับห้องเรียน
            </button>
          </div>
          <div class="border-t border-stone-100 bg-stone-50/60 p-2">
            <button
              type="button"
              class="w-full rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-center text-sm font-bold text-red-600 transition-colors hover:border-red-200 hover:bg-red-50"
              @click.stop="logout"
            >
              ออกจากระบบ
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
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

/* 🪄 Bottom sheet */
.sheet-fade-enter-active,
.sheet-fade-leave-active {
  transition: opacity 0.22s ease;
}
.sheet-fade-enter-from,
.sheet-fade-leave-to {
  opacity: 0;
}

.sheet-slide-enter-active,
.sheet-slide-leave-active {
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.sheet-slide-enter-from,
.sheet-slide-leave-to {
  transform: translateY(100%);
}

/* 🪄 Dropdown */
.dropdown-anim-enter-active {
  transition: all 0.18s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.dropdown-anim-leave-active {
  transition: all 0.12s ease-in;
}
.dropdown-anim-enter-from,
.dropdown-anim-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .fade-slide-enter-active,
  .fade-slide-leave-active,
  .sheet-slide-enter-active,
  .sheet-slide-leave-active,
  .dropdown-anim-enter-active,
  .dropdown-anim-leave-active {
    transition-duration: 0.01ms;
  }
}
</style>
