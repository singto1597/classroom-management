<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { RouterView, useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';
import { StudentService } from '@/services/student';

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

// 🌙 สถานะ sidebar: เปิดบนมือถือ (drawer) / ย่อ-ขยายบนเดสก์ท็อป
const isMobileDrawerOpen = ref(false);
const isSidebarCollapsed = ref(false);
const activeDropdown = ref<string | null>(null);

// จำสถานะย่อ sidebar ไว้ใช้ครั้งถัดไป (UX ส่วนตัวของผู้ใช้)
const COLLAPSE_KEY = 'syncroom_sidebar_collapsed';
onMounted(async () => {
  isSidebarCollapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1';
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
  // 🔁 คำนวณตำแหน่ง dropdown ใหม่ทุกครั้งที่ scroll/resize
  window.addEventListener('scroll', repositionOpenDropdown, true);
  window.addEventListener('resize', repositionOpenDropdown);
});
onUnmounted(() => {
  window.removeEventListener('scroll', repositionOpenDropdown, true);
  window.removeEventListener('resize', repositionOpenDropdown);
});

// คำนวณตำแหน่ง dropdown ที่เปิดอยู่ใหม่ (กันลอยห่างจาก trigger เมื่อ scroll)
const repositionOpenDropdown = () => {
  const name = activeDropdown.value;
  if (!name) return;
  const align = dropdownAlign.value;
  positionDropdown(document.querySelector(`[data-dropdown-trigger="${name}"]`), align);
};

// ✨ ระบบชื่อใหม่ ดึงจาก authStore ที่จัดการแล้ว 100%
const displayName = computed(() => authStore.currentUserName);

// ✨ ดึงตัวอักษรตัวแรกของชื่อ/ชื่อเล่นมาทำเป็นรูปโปรไฟล์
const avatarChar = computed(() => {
  const name = authStore.nickname || authStore.firstName;
  return name && name !== 'ไม่ระบุชื่อ'
    ? name.charAt(0).toUpperCase()
    : 'ส'; // ส ตัวแรกของ "สมาชิก"
});

// 🎯 ตำแหน่ง dropdown (คำนวณจาก trigger จริง กันลอยห่างตอน teleport)
const dropdownStyle = ref<{ top: string; left: string }>({ top: '0px', left: '0px' });
const dropdownAlign = ref<'left' | 'right'>('left');

const positionDropdown = (trigger: HTMLElement | null, align: 'left' | 'right' = 'left') => {
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  dropdownAlign.value = align;
  const panelWidth = align === 'right' ? 240 : 192; // headerSettings=240, breadcrumb=192
  let left = rect.left;
  if (align === 'right') left = rect.right - panelWidth;
  // กัน dropdown ล้นขอบจอ
  left = Math.max(8, Math.min(left, window.innerWidth - panelWidth - 8));
  dropdownStyle.value = { top: `${rect.bottom + 8}px`, left: `${left}px` };
};

const toggleDropdown = (dropdownName: string) => {
  // ปิดถ้าเปิดอันเดิม / สลับอันอื่น
  if (activeDropdown.value === dropdownName) {
    activeDropdown.value = null;
    return;
  }
  activeDropdown.value = dropdownName;
  // วาง dropdown ให้ตรงกับ trigger
  if (dropdownName === 'headerSettings') {
    positionDropdown(document.querySelector('[data-dropdown-trigger="headerSettings"]'), 'right');
  } else if (dropdownName === 'breadcrumbMenu') {
    positionDropdown(document.querySelector('[data-dropdown-trigger="breadcrumbMenu"]'), 'left');
  } else if (dropdownName === 'sidebarSettings') {
    positionDropdown(document.querySelector('[data-dropdown-trigger="sidebarSettings"]'), 'left');
  }
};

const closeDropdowns = () => {
  activeDropdown.value = null;
};

// เปิด-ปิด drawer บนมือถือ พร้อมล้าง dropdown ค้าง (กัน state leak)
const openMobileDrawer = () => {
  closeDropdowns();
  isMobileDrawerOpen.value = true;
};
const closeMobileDrawer = () => {
  isMobileDrawerOpen.value = false;
};

// 🚨 ปิด drawer อัตโนมัติเมื่อเปลี่ยนหน้า (กัน drawer ค้างทับหน้าจอ)
watch(
  () => route.path,
  () => {
    closeMobileDrawer();
    closeDropdowns();
  }
);

// ย่อ/ขยาย sidebar บนเดสก์ท็อป
const toggleSidebarCollapse = () => {
  isSidebarCollapsed.value = !isSidebarCollapsed.value;
  localStorage.setItem(COLLAPSE_KEY, isSidebarCollapsed.value ? '1' : '0');
};

const menuItems = [
  { name: 'แดชบอร์ด', path: '/dashboard', icon: 'bi-grid-fill' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people-fill' },
  { name: 'งานและโน้ต', path: '/tasks', icon: 'bi-clipboard-check-fill' },
  { name: 'ตารางเรียน', path: '/schedules', icon: 'bi-calendar-event-fill' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
  { name: 'ประกาศ Discord', path: '/messages', icon: 'bi-megaphone-fill' },
];

const isItemActive = (path: string) =>
  path === '/dashboard'
    ? route.path === '/dashboard' || route.path === '/'
    : route.path.startsWith(path);

const handleChangeRoom = () => {
  closeDropdowns();
  authStore.clearRoom();
  router.push('/lobby');
};

const currentSubMenuName = computed(() => {
  if (route.path === '/dashboard' || route.path === '/') return null;
  const matchedMenu = menuItems.find((item) => item.path !== '/dashboard' && route.path.startsWith(item.path));
  return matchedMenu ? matchedMenu.name : null;
});

const goToMyProfile = async () => {
  closeDropdowns();
  try {
    Swal.fire({ title: 'กำลังโหลดข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
    const myProfile: any = await StudentService.getMyProfile(authStore.currentRoomId!);
    Swal.close();
    router.push(`/students/${myProfile.student_no}`);
  } catch (error) {
    Swal.fire({
      icon: 'warning',
      title: 'ไม่สามารถเข้าถึงได้',
      text: 'คุณอาจเป็นผู้ดูแลระบบ (Admin) ที่ไม่มีข้อมูลในรายชื่อนักเรียนห้องนี้',
      customClass: { popup: 'rounded-3xl' }
    });
  }
};

const showAccountInfo = () => {
  closeDropdowns();
  Swal.fire({
    title: 'ข้อมูลบัญชีระบบ',
    html: `
      <div class="text-left mt-4 space-y-3">
        <p class="text-sm text-gray-600"><b>Discord ID:</b> <span class="bg-gray-100 px-2 py-1 rounded font-mono">${authStore.discordId || 'ยังไม่ระบุ'}</span></p>
        <p class="text-sm text-gray-600"><b>บทบาทในห้อง:</b> <span class="uppercase font-bold text-blue-600">${authStore.currentRoleLabel}</span></p>
      </div>
    `,
    icon: 'info',
    confirmButtonText: 'ปิด',
    confirmButtonColor: '#3b82f6',
    customClass: {
      popup: 'rounded-2xl shadow-2xl border border-gray-100',
      confirmButton: 'rounded-xl px-6'
    }
  });
};

const logout = () => {
  closeDropdowns();
  authStore.logout();
};

// 🌟 ระบบจัดการบัญชี (Smart Link Accounts)
const goToProfileSettings = async () => {
  closeDropdowns();
  closeMobileDrawer();

  Swal.fire({ title: 'กำลังโหลดข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
  await authStore.fetchProfile();
  Swal.close();

  const isDiscordLinked = !!authStore.discordId;
  const isGoogleLinked = !!authStore.googleId;

  const discordScope = encodeURIComponent('identify email');
  const discordUrl = `https://discord.com/api/oauth2/authorize?client_id=${import.meta.env.VITE_DISCORD_CLIENT_ID}&redirect_uri=${encodeURIComponent(import.meta.env.VITE_DISCORD_REDIRECT_URI)}&response_type=code&scope=${discordScope}`;

  const googleScope = encodeURIComponent('openid email profile');
  const googleUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${import.meta.env.VITE_GOOGLE_CLIENT_ID}&redirect_uri=${encodeURIComponent(import.meta.env.VITE_GOOGLE_REDIRECT_URI)}&response_type=code&scope=${googleScope}`;

  Swal.fire({
    title: '<i class="bi bi-shield-lock-fill text-3xl text-slate-800"></i><br>จัดการบัญชีและการเชื่อมต่อ',
    html: `
      <div class="text-left mt-4 space-y-4">
        <p class="text-sm text-slate-500 font-medium">เชื่อมต่อแพลตฟอร์มต่างๆ เพื่อรวมข้อมูลของคุณให้เป็นหนึ่งเดียว ป้องกันการสูญหาย</p>

        <div class="p-4 rounded-[1.5rem] border ${isGoogleLinked ? 'bg-emerald-50/50 border-emerald-100' : 'bg-slate-50 border-slate-200'} flex items-center justify-between">
          <div class="flex items-center gap-4">
            <div class="w-10 h-10 rounded-full flex items-center justify-center bg-white shadow-sm border border-slate-100">
              <i class="bi bi-google text-rose-500 text-lg"></i>
            </div>
            <div>
              <p class="font-bold text-slate-800 leading-tight">Google Account</p>
              <p class="text-[11px] font-bold mt-0.5 ${isGoogleLinked ? 'text-emerald-600' : 'text-slate-400'}">
                ${isGoogleLinked ? '<i class="bi bi-check-circle-fill"></i> เชื่อมต่อแล้ว' : 'ยังไม่ได้เชื่อมต่อ'}
              </p>
            </div>
          </div>
          ${!isGoogleLinked ? `<a href="${googleUrl}" class="px-4 py-2 bg-white border border-slate-200 hover:border-blue-500 hover:text-blue-600 text-xs font-bold rounded-xl transition-all shadow-sm">ผูกบัญชี</a>` : ''}
        </div>

        <div class="p-4 rounded-[1.5rem] border ${isDiscordLinked ? 'bg-emerald-50/50 border-emerald-100' : 'bg-slate-50 border-slate-200'} flex items-center justify-between">
          <div class="flex items-center gap-4">
            <div class="w-10 h-10 rounded-full flex items-center justify-center bg-white shadow-sm border border-slate-100">
              <i class="bi bi-discord text-[#5865F2] text-xl"></i>
            </div>
            <div>
              <p class="font-bold text-slate-800 leading-tight">Discord Account</p>
              <p class="text-[11px] font-bold mt-0.5 ${isDiscordLinked ? 'text-emerald-600' : 'text-slate-400'}">
                ${isDiscordLinked ? '<i class="bi bi-check-circle-fill"></i> เชื่อมต่อแล้ว' : 'ยังไม่ได้เชื่อมต่อ'}
              </p>
            </div>
          </div>
          ${!isDiscordLinked ? `<a href="${discordUrl}" class="px-4 py-2 bg-white border border-slate-200 hover:border-[#5865F2] hover:text-[#5865F2] text-xs font-bold rounded-xl transition-all shadow-sm">ผูกบัญชี</a>` : ''}
        </div>
      </div>
    `,
    showConfirmButton: true,
    confirmButtonText: 'ปิดหน้าต่าง',
    confirmButtonColor: '#0f172a',
    customClass: {
      popup: 'rounded-[2.5rem] shadow-2xl border border-slate-100 p-6',
      confirmButton: 'rounded-xl px-8 py-3 font-bold tracking-wide'
    }
  });
};
</script>

<template>
  <div class="flex h-screen h-dvh bg-gray-50 overflow-hidden font-sans relative">

    <!-- ============================================
         🖥️ DESKTOP SIDEBAR (md+) — ย่อ-ขยายได้
         ============================================ -->
    <aside
      class="hidden md:flex md:flex-shrink-0 relative z-30 transition-[width] duration-300 ease-out"
      :class="isSidebarCollapsed ? 'md:w-[76px]' : 'md:w-64'"
    >
      <div
        class="flex flex-col bg-white border-r border-gray-100 shadow-[2px_0_8px_-4px_rgba(0,0,0,0.05)] h-full overflow-hidden"
        :class="isSidebarCollapsed ? 'w-[76px]' : 'w-64'"
      >
        <!-- Logo -->
        <RouterLink
          to="/dashboard"
          class="flex items-center h-14 md:h-16 px-4 md:px-6 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 transition-all duration-300 cursor-pointer shrink-0"
          :class="isSidebarCollapsed ? 'justify-center px-0' : ''"
          :title="isSidebarCollapsed ? 'SyncRoom' : undefined"
        >
          <i class="bi bi-box-fill text-white text-xl me-3 opacity-90" :class="isSidebarCollapsed ? 'me-0' : ''"></i>
          <span v-if="!isSidebarCollapsed" class="text-white text-lg font-black tracking-widest whitespace-nowrap">SYNC<span class="font-light opacity-80">ROOM</span></span>
        </RouterLink>

        <!-- Menu -->
        <div class="flex-1 flex flex-col overflow-y-auto overflow-x-hidden">
          <nav class="flex-1 px-2.5 md:px-3 py-4 space-y-1" :class="isSidebarCollapsed ? 'px-2' : ''">
            <RouterLink
              v-for="item in menuItems"
              :key="item.path"
              :to="item.path"
              class="flex items-center rounded-xl transition-all duration-200 group"
              :class="[
                isSidebarCollapsed ? 'justify-center px-0 py-3 w-full' : 'px-3.5 py-2.5',
                isItemActive(item.path) ? 'bg-blue-50 text-blue-600 shadow-sm border border-blue-100/50' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
              ]"
              :title="isSidebarCollapsed ? item.name : undefined"
            >
              <i :class="['bi', item.icon, 'shrink-0 transition-transform duration-200 group-hover:scale-110', isSidebarCollapsed ? 'text-lg' : 'text-lg me-3']"></i>
              <span v-if="!isSidebarCollapsed" class="text-sm font-semibold truncate">{{ item.name }}</span>
            </RouterLink>
          </nav>

          <!-- ปุ่มย่อ/ขยาย sidebar (เฉพาะเดสก์ท็อป) -->
          <button
            @click="toggleSidebarCollapse"
            class="mx-2.5 mb-2 flex items-center justify-center gap-2 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors shrink-0"
            :title="isSidebarCollapsed ? 'ขยายเมนู' : 'ย่อเมนู'"
          >
            <i :class="['bi', isSidebarCollapsed ? 'bi-chevron-double-right' : 'bi-chevron-double-left', 'text-base']"></i>
            <span v-if="!isSidebarCollapsed">ย่อเมนู</span>
          </button>

          <!-- User Footer -->
          <div class="p-2.5 md:p-3 border-t border-gray-100 bg-gray-50/50 relative">
            <div class="flex items-center gap-2 rounded-xl hover:bg-white border border-transparent hover:border-gray-200 hover:shadow-sm transition-all">
              <button
                class="flex items-center overflow-hidden flex-1 cursor-pointer min-w-0"
                @click="showAccountInfo"
              >
                <div class="w-9 h-9 rounded-full bg-gradient-to-br from-blue-100 to-blue-50 text-blue-600 flex items-center justify-center font-bold shadow-inner border border-blue-100 shrink-0">
                  {{ avatarChar }}
                </div>
                <div v-if="!isSidebarCollapsed" class="ms-2.5 overflow-hidden text-left">
                  <p class="text-sm font-bold text-gray-800 truncate leading-none mb-1">{{ displayName }}</p>
                  <p class="text-[10px] tracking-wider text-blue-500 font-bold uppercase truncate leading-none">{{ authStore.currentRoleLabel }}</p>
                </div>
              </button>

              <button
                data-dropdown-trigger="sidebarSettings"
                @click.stop="toggleDropdown('sidebarSettings')"
                class="w-9 h-9 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors shrink-0"
                :class="{'bg-gray-200 text-gray-800': activeDropdown === 'sidebarSettings'}"
                :title="isSidebarCollapsed ? 'การจัดการ' : undefined"
              >
                <i class="bi bi-gear-fill text-lg"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============================================
         📱 MOBILE DRAWER (< md)
         ============================================ -->
    <Transition name="fade">
      <div
        v-if="isMobileDrawerOpen"
        class="fixed inset-0 z-50 md:hidden bg-gray-900/50 backdrop-blur-sm"
        @click="closeMobileDrawer"
      ></div>
    </Transition>

    <Transition name="slide-right">
      <div
        v-if="isMobileDrawerOpen"
        class="fixed inset-y-0 left-0 z-[60] w-[280px] max-w-[85vw] bg-white shadow-2xl flex flex-col md:hidden"
      >
        <div class="flex items-center justify-between h-14 px-5 bg-gradient-to-r from-blue-600 to-blue-700 shrink-0">
          <RouterLink
            to="/dashboard"
            @click="closeMobileDrawer"
            class="flex items-center gap-2 text-white font-black tracking-widest"
          >
            <i class="bi bi-box-fill text-white text-lg"></i>
            SYNC<span class="font-light opacity-80">ROOM</span>
          </RouterLink>
          <button @click="closeMobileDrawer" class="w-11 h-11 flex items-center justify-center text-white/80 hover:text-white rounded-lg transition-colors -me-2" aria-label="ปิดเมนู">
            <i class="bi bi-x-lg text-xl"></i>
          </button>
        </div>

        <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto overflow-x-hidden">
          <RouterLink
            v-for="item in menuItems"
            :key="item.path"
            :to="item.path"
            @click="closeMobileDrawer"
            class="flex items-center px-3.5 py-3 text-sm font-semibold rounded-xl transition-all"
            :class="isItemActive(item.path) ? 'bg-blue-50 text-blue-600 shadow-sm border border-blue-100/50' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'"
          >
            <i :class="['bi', item.icon, 'text-lg me-3']"></i>
            {{ item.name }}
          </RouterLink>
        </nav>

        <div class="p-3 border-t border-gray-100 shrink-0 space-y-2 bg-gray-50">
          <button @click="goToMyProfile" class="w-full flex items-center justify-center px-4 py-3 text-sm font-bold text-gray-600 bg-white border border-gray-200 hover:bg-gray-50 rounded-xl transition-colors">
            <i class="bi bi-person-badge me-2"></i> โปรไฟล์ของฉัน
          </button>
          <button @click="goToProfileSettings" class="w-full flex items-center justify-center px-4 py-3 text-sm font-bold text-gray-600 bg-white border border-gray-200 hover:bg-gray-50 rounded-xl transition-colors">
            <i class="bi bi-link-45deg me-2"></i> จัดการผูกบัญชี
          </button>
          <button @click="handleChangeRoom" class="w-full flex items-center justify-center px-4 py-3 text-sm font-bold text-gray-600 bg-white border border-gray-200 hover:bg-gray-50 rounded-xl transition-colors">
            <i class="bi bi-arrow-left-right me-2"></i> สลับห้องเรียน
          </button>
          <button @click="logout" class="w-full flex items-center justify-center px-4 py-3 text-sm font-bold text-red-500 bg-white border border-red-100 hover:bg-red-50 rounded-xl transition-colors">
            <i class="bi bi-power me-2"></i> ออกจากระบบ
          </button>
        </div>
      </div>
    </Transition>

    <!-- ============================================
         ⚙️ MAIN AREA (Header + Content)
         ============================================ -->
    <div class="flex flex-col flex-1 min-w-0 overflow-hidden">

      <header class="flex-shrink-0 bg-white/80 backdrop-blur-md border-b border-gray-100 z-20">
        <div class="h-14 md:h-16 flex items-center justify-between px-3 sm:px-5">
          <div class="flex items-center min-w-0">
            <!-- Hamburger (mobile) -->
            <button
              @click="openMobileDrawer"
              class="md:hidden w-11 h-11 -ml-2 me-1 rounded-xl text-gray-500 hover:text-gray-800 hover:bg-gray-100 transition-colors flex items-center justify-center"
              aria-label="เปิดเมนู"
            >
              <i class="bi bi-list text-2xl"></i>
            </button>

            <!-- Hamburger (desktop: ย่อ sidebar) -->
            <button
              @click="toggleSidebarCollapse"
              class="hidden md:flex w-10 h-10 me-1 rounded-xl text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors items-center justify-center"
              :title="isSidebarCollapsed ? 'ขยายเมนู' : 'ย่อเมนู'"
            >
              <i :class="['bi', isSidebarCollapsed ? 'bi-chevron-double-right' : 'bi-chevron-double-left', 'text-lg']"></i>
            </button>

            <!-- Breadcrumb -->
            <div class="flex items-center text-sm font-bold text-gray-800 tracking-tight gap-1.5 min-w-0">
              <template v-if="authStore.currentRoomId">
                <button
                  @click="handleChangeRoom"
                  class="flex items-center justify-center w-10 h-10 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors cursor-pointer shrink-0"
                  title="กลับหน้าเลือกห้อง"
                >
                  <i class="bi bi-house-door-fill text-lg"></i>
                </button>

                <div class="relative flex items-center shrink-0">
                  <button
                    data-dropdown-trigger="breadcrumbMenu"
                    @click.stop="toggleDropdown('breadcrumbMenu')"
                    class="flex items-center justify-center w-9 h-9 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors cursor-pointer relative z-40"
                    title="นำทางด่วน"
                  >
                    <i class="bi bi-chevron-right text-xs font-black"></i>
                  </button>
                </div>

                <router-link
                  to="/dashboard"
                  class="px-1.5 py-1 rounded-md hover:bg-gray-100 transition-colors cursor-pointer truncate max-w-[100px] sm:max-w-[180px] min-w-0"
                  title="หน้าหลักห้องเรียน"
                >
                  {{ authStore.currentRoomName || authStore.currentRoomId }}
                </router-link>

                <template v-if="currentSubMenuName">
                  <i class="bi bi-chevron-right text-[10px] font-black text-gray-300 shrink-0"></i>
                  <span class="text-blue-600 px-1 truncate max-w-[90px] sm:max-w-[140px]">{{ currentSubMenuName }}</span>
                </template>
              </template>

              <template v-else>
                <div class="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                  <i class="bi bi-house-door-fill text-lg"></i>
                </div>
                <i class="bi bi-chevron-right text-[10px] font-black text-gray-300 mx-1 shrink-0"></i>
                <span class="truncate">ระบบจัดการห้องเรียน</span>
              </template>
            </div>
          </div>

          <!-- Avatar / Settings -->
          <div class="relative shrink-0">
            <button
              data-dropdown-trigger="headerSettings"
              @click.stop="toggleDropdown('headerSettings')"
              class="flex items-center p-1.5 sm:pe-4 bg-white hover:bg-gray-50 border border-gray-100 rounded-full transition-all duration-300 shadow-sm hover:shadow group cursor-pointer focus:outline-none relative z-40"
              :class="{'ring-2 ring-blue-500/20': activeDropdown === 'headerSettings'}"
            >
              <div class="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center font-bold text-sm shadow-inner group-hover:scale-105 transition-transform duration-300">
                {{ avatarChar }}
              </div>
              <div class="ms-3 hidden sm:block text-left">
                <p class="text-sm font-bold text-gray-800 leading-none">{{ displayName }}</p>
                <p class="text-[10px] text-gray-400 font-semibold uppercase tracking-wider mt-1 flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full bg-green-500 inline-block animate-pulse"></span>
                  Online
                </p>
              </div>
            </button>
          </div>
        </div>
      </header>

      <main class="flex-1 overflow-y-auto overflow-x-hidden bg-[#f8fafc] focus:outline-none scroll-smooth">
        <div class="py-4 md:py-6">
          <div class="max-w-7xl mx-auto px-3 sm:px-5 md:px-6">
            <RouterView v-slot="{ Component, route }">
              <transition name="fade-slide" mode="out-in">
                <div :key="route.path">
                  <component :is="Component" />
                </div>
              </transition>
            </RouterView>
          </div>
        </div>
      </main>
    </div>

    <!-- ============================================
         🗂️ Dropdown Panels (Teleport ไป body กัน stacking context)
         ============================================ -->
    <Teleport to="body">
      <!-- Backdrop ปิด dropdown เมื่อคลิกนอก -->
      <div
        v-if="activeDropdown"
        class="fixed inset-0 z-[70]"
        @click="closeDropdowns"
      ></div>

      <!-- Sidebar settings (desktop) -->
      <Transition name="fade-scale">
        <div
          v-if="activeDropdown === 'sidebarSettings'"
          class="fixed z-[80] bg-white rounded-2xl shadow-xl border border-gray-100 py-2 w-56 max-w-[calc(100vw-2rem)]"
          :style="dropdownStyle"
        >
          <div class="px-4 py-2 mb-1 border-b border-gray-50">
            <p class="text-[10px] font-bold text-gray-400 uppercase tracking-widest">การจัดการ</p>
          </div>
          <button @click.stop="goToMyProfile" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center gap-3">
            <i class="bi bi-person-badge text-lg"></i> โปรไฟล์ของฉัน
          </button>
          <button @click.stop="goToProfileSettings" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center gap-3">
            <i class="bi bi-link-45deg text-lg"></i> จัดการผูกบัญชี
          </button>
          <button @click.stop="handleChangeRoom" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center gap-3">
            <i class="bi bi-arrow-left-right text-lg"></i> สลับห้องเรียน
          </button>
          <div class="h-px bg-gray-100 my-1"></div>
          <button @click.stop="logout" class="w-full text-left px-4 py-2.5 text-sm font-bold text-red-500 hover:bg-red-50 hover:text-red-600 transition-colors flex items-center gap-3">
            <i class="bi bi-box-arrow-right text-lg"></i> ออกจากระบบ
          </button>
        </div>
      </Transition>

      <!-- Breadcrumb quick nav -->
      <Transition name="fade-scale">
        <div
          v-if="activeDropdown === 'breadcrumbMenu'"
          class="fixed z-[80] bg-white rounded-xl shadow-lg border border-gray-100 py-1.5 w-48 max-w-[calc(100vw-2rem)]"
          :style="dropdownStyle"
        >
          <p class="px-3 py-1.5 text-[10px] font-bold text-gray-400 uppercase tracking-wider border-b border-gray-50 mb-1">นำทางด่วน</p>
          <RouterLink
            v-for="item in menuItems"
            :key="item.path"
            :to="item.path"
            @click="closeDropdowns"
            class="flex items-center px-4 py-2.5 text-sm font-semibold text-gray-600 hover:bg-blue-50 hover:text-blue-600 transition-colors"
          >
            <i :class="['bi', item.icon, 'text-base me-3']"></i>
            {{ item.name }}
          </RouterLink>
        </div>
      </Transition>

      <!-- Header settings -->
      <Transition name="fade-scale">
        <div
          v-if="activeDropdown === 'headerSettings'"
          class="fixed z-[80] bg-white rounded-2xl shadow-xl border border-gray-100 py-2 w-60 max-w-[calc(100vw-2rem)]"
          :style="dropdownStyle"
        >
          <div class="px-4 py-3 mb-1 border-b border-gray-50 bg-gray-50/50">
            <p class="text-sm font-bold text-gray-800 truncate">{{ displayName }}</p>
            <p class="text-xs text-blue-500 font-bold uppercase truncate">{{ authStore.currentRoleLabel }}</p>
          </div>
          <button @click.stop="goToMyProfile" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center gap-3">
            <i class="bi bi-person-badge text-lg"></i> โปรไฟล์ของฉัน
          </button>
          <button @click.stop="goToProfileSettings" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center gap-3">
            <i class="bi bi-link-45deg text-lg"></i> จัดการผูกบัญชี
          </button>
          <button @click.stop="handleChangeRoom" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center gap-3">
            <i class="bi bi-arrow-left-right text-lg"></i> สลับห้องเรียน
          </button>
          <div class="h-px bg-gray-100 my-1"></div>
          <button @click.stop="logout" class="w-full text-left px-4 py-2.5 text-sm font-bold text-red-500 hover:bg-red-50 hover:text-red-600 transition-colors flex items-center gap-3">
            <i class="bi bi-power text-lg"></i> ออกจากระบบ
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* 🪄 แอนิเมชันสำหรับ Router View */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* 🪄 แอนิเมชันทั่วไป */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* แอนิเมชันสำหรับ drawer มือถือ */
.slide-right-enter-active,
.slide-right-leave-active {
  transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
}
.slide-right-enter-from,
.slide-right-leave-to {
  transform: translateX(-100%);
}

/* แอนิเมชันสำหรับเมนู Dropdown */
.fade-scale-enter-active,
.fade-scale-leave-active {
  transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: scale(0.96) translateY(-6px);
}
</style>
