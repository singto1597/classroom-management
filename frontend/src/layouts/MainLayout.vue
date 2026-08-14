<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { RouterView, useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';
import { StudentService } from '@/services/student';

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

// 🌙 สถานะ sidebar
const isMobileDrawerOpen = ref(false);
const isSidebarCollapsed = ref(false);
const activeDropdown = ref<string | null>(null);

// จำสถานะย่อ sidebar ไว้ใช้ครั้งถัดไป
const COLLAPSE_KEY = 'syncroom_sidebar_collapsed';

onMounted(async () => {
  isSidebarCollapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1';
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
  // 🔁 ปิด Dropdown เมื่อมีการ Scroll หน้าจอ (UX ที่ดีกว่าการพยายามเลื่อนตาม)
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

// 🎯 Dropdown System แบบใหม่ (ฉลาดขึ้น & ไม่ล้นจอ)
const dropdownStyle = ref<{ top: string; left: string; bottom?: string }>({ top: '0px', left: '0px' });
const dropdownAlign = ref<'left' | 'right' | 'center'>('left');

const toggleDropdown = (event: MouseEvent, dropdownName: string) => {
  // ถ้ากดอันเดิมให้ปิด
  if (activeDropdown.value === dropdownName) {
    closeDropdowns();
    return;
  }
  
  activeDropdown.value = dropdownName;
  
  // ใช้ currentTarget จากอีเวนต์โดยตรง แม่นยำ 100% ไม่ต้องพึ่ง ID
  const trigger = event.currentTarget as HTMLElement;
  const rect = trigger.getBoundingClientRect();
  
  // กำหนดความกว้างโดยประมาณของ Dropdown แต่ละตัว
  const panelWidth = dropdownName === 'headerSettings' ? 240 : 224; 
  const panelHeight = 200; // ความสูงโดยประมาณ เพื่อเช็คว่าล้นขอบล่างไหม

  // คำนวณแกน X (ซ้าย-ขวา)
  let left = dropdownName === 'headerSettings' 
    ? rect.right - panelWidth 
    : rect.left;

  // กันหลุดขอบจอซ้าย-ขวา
  left = Math.max(12, Math.min(left, window.innerWidth - panelWidth - 12));

  // คำนวณแกน Y (บน-ล่าง) - ถ้าระยะด้านล่างไม่พอ ให้เปิดขึ้นข้างบน (Drop-up)
  const spaceBelow = window.innerHeight - rect.bottom;
  
  if (spaceBelow < panelHeight) {
    // เปิดขึ้นด้านบน
    dropdownStyle.value = { 
      top: 'auto',
      bottom: `${window.innerHeight - rect.top + 8}px`,
      left: `${left}px` 
    };
  } else {
    // เปิดลงด้านล่างปกติ
    dropdownStyle.value = { 
      top: `${rect.bottom + 8}px`, 
      bottom: 'auto',
      left: `${left}px` 
    };
  }
};

const closeDropdowns = () => {
  activeDropdown.value = null;
};

// Drawer มือถือ
const openMobileDrawer = () => {
  closeDropdowns();
  isMobileDrawerOpen.value = true;
};
const closeMobileDrawer = () => {
  isMobileDrawerOpen.value = false;
};

watch(
  () => route.path,
  () => {
    closeMobileDrawer();
    closeDropdowns();
  }
);

// Toggle Sidebar Desktop
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
  { name: 'กิจกรรม', path: '/activities', icon: 'bi-calendar-heart-fill' },
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
      customClass: { popup: 'rounded-[2rem] shadow-2xl' }
    });
  }
};

const showAccountInfo = () => {
  closeDropdowns();
  Swal.fire({
    title: '<span class="text-slate-800 font-bold">ข้อมูลบัญชีระบบ</span>',
    html: `
      <div class="text-left mt-5 space-y-4 bg-slate-50 p-5 rounded-2xl border border-slate-100">
        <div class="flex items-center justify-between border-b border-slate-200 pb-3">
          <span class="text-sm text-slate-500 font-medium">Discord ID</span>
          <span class="bg-indigo-50 text-indigo-700 px-3 py-1 rounded-lg font-mono text-sm font-bold shadow-sm">${authStore.discordId || 'ยังไม่ระบุ'}</span>
        </div>
        <div class="flex items-center justify-between pt-1">
          <span class="text-sm text-slate-500 font-medium">บทบาทในห้อง</span>
          <span class="uppercase font-black text-blue-600 bg-blue-50 px-3 py-1 rounded-lg tracking-wider text-xs">${authStore.currentRoleLabel}</span>
        </div>
      </div>
    `,
    icon: 'info',
    confirmButtonText: 'ปิดหน้าต่าง',
    confirmButtonColor: '#3b82f6',
    customClass: {
      popup: 'rounded-[2rem] shadow-2xl border border-slate-100',
      confirmButton: 'rounded-xl px-8 py-2.5 font-bold tracking-wide'
    }
  });
};

const logout = () => {
  closeDropdowns();
  authStore.logout();
};

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
    title: '<i class="bi bi-shield-check text-4xl text-slate-800 mb-2 inline-block"></i><br><span class="font-bold text-xl">จัดการบัญชีและการเชื่อมต่อ</span>',
    html: `
      <div class="text-left mt-5 space-y-4">
        <p class="text-sm text-slate-500 font-medium px-1">เชื่อมต่อแพลตฟอร์มต่างๆ เพื่อรวมข้อมูลของคุณให้เป็นหนึ่งเดียว ป้องกันการสูญหาย</p>

        <div class="p-4 rounded-[1.5rem] border transition-all duration-300 ${isGoogleLinked ? 'bg-emerald-50/50 border-emerald-200' : 'bg-white border-slate-200 hover:border-slate-300 shadow-sm'} flex items-center justify-between">
          <div class="flex items-center gap-4">
            <div class="w-11 h-11 rounded-full flex items-center justify-center bg-white shadow-sm border border-slate-100">
              <img src="https://www.svgrepo.com/show/475656/google-color.svg" class="w-5 h-5" alt="Google">
            </div>
            <div>
              <p class="font-bold text-slate-800 leading-tight">Google Account</p>
              <p class="text-xs font-bold mt-1 ${isGoogleLinked ? 'text-emerald-600' : 'text-slate-400'}">
                ${isGoogleLinked ? '<i class="bi bi-check-circle-fill me-1"></i> เชื่อมต่อแล้ว' : 'ยังไม่ได้เชื่อมต่อ'}
              </p>
            </div>
          </div>
          ${!isGoogleLinked ? `<a href="${googleUrl}" class="px-5 py-2 bg-slate-800 hover:bg-slate-900 text-white text-xs font-bold rounded-xl transition-all shadow-sm">ผูกบัญชี</a>` : ''}
        </div>

        <div class="p-4 rounded-[1.5rem] border transition-all duration-300 ${isDiscordLinked ? 'bg-emerald-50/50 border-emerald-200' : 'bg-white border-slate-200 hover:border-slate-300 shadow-sm'} flex items-center justify-between">
          <div class="flex items-center gap-4">
            <div class="w-11 h-11 rounded-full flex items-center justify-center bg-[#5865F2]/10 border border-[#5865F2]/20">
              <i class="bi bi-discord text-[#5865F2] text-xl"></i>
            </div>
            <div>
              <p class="font-bold text-slate-800 leading-tight">Discord Account</p>
              <p class="text-xs font-bold mt-1 ${isDiscordLinked ? 'text-emerald-600' : 'text-slate-400'}">
                ${isDiscordLinked ? '<i class="bi bi-check-circle-fill me-1"></i> เชื่อมต่อแล้ว' : 'ยังไม่ได้เชื่อมต่อ'}
              </p>
            </div>
          </div>
          ${!isDiscordLinked ? `<a href="${discordUrl}" class="px-5 py-2 bg-[#5865F2] hover:bg-[#4752C4] text-white text-xs font-bold rounded-xl transition-all shadow-sm">ผูกบัญชี</a>` : ''}
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
  <div class="flex h-screen h-dvh bg-slate-50 overflow-hidden font-sans relative text-slate-800">

    <!-- ============================================
         🖥️ DESKTOP SIDEBAR
         ============================================ -->
    <aside
      class="hidden md:flex md:flex-shrink-0 relative z-30 transition-[width] duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
      :class="isSidebarCollapsed ? 'md:w-[84px]' : 'md:w-64'"
    >
      <div
        class="flex flex-col bg-white border-r border-slate-200/60 shadow-[4px_0_24px_-12px_rgba(0,0,0,0.05)] h-full overflow-hidden transition-all duration-300"
        :class="isSidebarCollapsed ? 'w-[84px]' : 'w-64'"
      >
        <!-- Logo -->
        <RouterLink
          to="/dashboard"
          class="flex items-center h-16 px-5 bg-gradient-to-r from-blue-600 to-indigo-700 hover:from-blue-700 hover:to-indigo-800 transition-all duration-300 cursor-pointer shrink-0"
          :class="isSidebarCollapsed ? 'justify-center px-0' : ''"
        >
          <div class="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center backdrop-blur-sm shrink-0" :class="isSidebarCollapsed ? '' : 'me-3'">
            <i class="bi bi-box-fill text-white text-lg"></i>
          </div>
          <span v-if="!isSidebarCollapsed" class="text-white text-xl font-black tracking-widest whitespace-nowrap">SYNC<span class="font-light opacity-80">ROOM</span></span>
        </RouterLink>

        <!-- Menu -->
        <div class="flex-1 flex flex-col overflow-y-auto overflow-x-hidden scrollbar-hide py-5">
          <nav class="flex-1 px-3 space-y-1.5">
            <RouterLink
              v-for="item in menuItems"
              :key="item.path"
              :to="item.path"
              class="flex items-center rounded-xl transition-all duration-200 group relative"
              :class="[
                isSidebarCollapsed ? 'justify-center px-0 py-3 w-full' : 'px-4 py-3',
                isItemActive(item.path) 
                  ? 'bg-blue-50/80 text-blue-700 font-bold shadow-sm ring-1 ring-blue-100' 
                  : 'text-slate-500 font-semibold hover:bg-slate-50 hover:text-slate-900'
              ]"
              :title="isSidebarCollapsed ? item.name : undefined"
            >
              <i :class="['bi', item.icon, 'shrink-0 transition-transform duration-300 group-hover:scale-110', isSidebarCollapsed ? 'text-xl' : 'text-lg me-3.5', isItemActive(item.path) ? 'text-blue-600' : '']"></i>
              <span v-if="!isSidebarCollapsed" class="text-sm truncate">{{ item.name }}</span>
            </RouterLink>
          </nav>

          <!-- ปุ่มย่อ/ขยาย sidebar -->
          <div class="px-3 mt-4">
            <button
              @click="toggleSidebarCollapse"
              class="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-bold text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors border border-dashed border-slate-200 hover:border-slate-300"
              :title="isSidebarCollapsed ? 'ขยายเมนู' : 'ย่อเมนู'"
            >
              <i :class="['bi', isSidebarCollapsed ? 'bi-chevron-double-right' : 'bi-chevron-double-left', 'text-base']"></i>
              <span v-if="!isSidebarCollapsed">ย่อเมนูบาร์</span>
            </button>
          </div>
        </div>

        <!-- User Footer (ส่วนที่เคยมีปัญหา Dropdown) -->
        <div class="p-3 border-t border-slate-100 bg-slate-50/50 shrink-0">
          <div class="flex items-center gap-2 rounded-xl bg-white p-1.5 border border-slate-200 shadow-sm hover:shadow-md hover:border-slate-300 transition-all">
            <button
              class="flex items-center overflow-hidden flex-1 cursor-pointer min-w-0"
              @click="showAccountInfo"
            >
              <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-100 to-indigo-50 text-blue-700 flex items-center justify-center font-bold shadow-inner border border-blue-100/50 shrink-0">
                {{ avatarChar }}
              </div>
              <div v-if="!isSidebarCollapsed" class="ms-3 overflow-hidden text-left">
                <p class="text-[13px] font-bold text-slate-800 truncate leading-tight">{{ displayName }}</p>
                <p class="text-[10px] tracking-widest text-blue-600 font-bold uppercase truncate mt-0.5">{{ authStore.currentRoleLabel }}</p>
              </div>
            </button>

            <!-- 🚨 แก้ไขตรงนี้: ส่ง $event เข้าไปในฟังก์ชัน -->
            <button
              @click.stop="toggleDropdown($event, 'sidebarSettings')"
              class="w-9 h-9 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-800 hover:bg-slate-100 transition-colors shrink-0"
              :class="{'bg-slate-200 text-slate-800 ring-2 ring-slate-200': activeDropdown === 'sidebarSettings'}"
              :title="isSidebarCollapsed ? 'การตั้งค่า' : undefined"
            >
              <i class="bi bi-gear-fill text-lg transition-transform duration-300 hover:rotate-90"></i>
            </button>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============================================
         📱 MOBILE DRAWER
         ============================================ -->
    <Transition name="fade">
      <div
        v-if="isMobileDrawerOpen"
        class="fixed inset-0 z-50 md:hidden bg-slate-900/40 backdrop-blur-sm"
        @click="closeMobileDrawer"
      ></div>
    </Transition>

    <Transition name="slide-right">
      <div
        v-if="isMobileDrawerOpen"
        class="fixed inset-y-0 left-0 z-[60] w-[280px] max-w-[85vw] bg-white shadow-2xl flex flex-col md:hidden"
      >
        <div class="flex items-center justify-between h-16 px-5 bg-gradient-to-r from-blue-600 to-indigo-700 shrink-0">
          <RouterLink
            to="/dashboard"
            @click="closeMobileDrawer"
            class="flex items-center gap-3 text-white font-black tracking-widest"
          >
            <div class="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center backdrop-blur-sm">
              <i class="bi bi-box-fill text-white text-lg"></i>
            </div>
            <span>SYNC<span class="font-light opacity-80">ROOM</span></span>
          </RouterLink>
          <button @click="closeMobileDrawer" class="w-10 h-10 flex items-center justify-center text-white/80 hover:text-white bg-white/10 hover:bg-white/20 rounded-lg transition-colors" aria-label="ปิดเมนู">
            <i class="bi bi-x-lg text-lg"></i>
          </button>
        </div>

        <nav class="flex-1 px-4 py-6 space-y-2 overflow-y-auto">
          <RouterLink
            v-for="item in menuItems"
            :key="item.path"
            :to="item.path"
            @click="closeMobileDrawer"
            class="flex items-center px-4 py-3.5 text-sm font-semibold rounded-xl transition-all"
            :class="isItemActive(item.path) ? 'bg-blue-50 text-blue-700 shadow-sm ring-1 ring-blue-100' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'"
          >
            <i :class="['bi', item.icon, 'text-xl me-4', isItemActive(item.path) ? 'text-blue-600' : '']"></i>
            {{ item.name }}
          </RouterLink>
        </nav>

        <div class="p-4 border-t border-slate-100 shrink-0 space-y-2.5 bg-slate-50">
          <button @click="goToMyProfile" class="w-full flex items-center justify-center px-4 py-3 text-sm font-bold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 hover:border-slate-300 shadow-sm rounded-xl transition-all">
            <i class="bi bi-person-badge text-lg me-2 text-slate-400"></i> โปรไฟล์ของฉัน
          </button>
          <button @click="goToProfileSettings" class="w-full flex items-center justify-center px-4 py-3 text-sm font-bold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 hover:border-slate-300 shadow-sm rounded-xl transition-all">
            <i class="bi bi-link-45deg text-xl me-2 text-slate-400"></i> จัดการผูกบัญชี
          </button>
          <div class="flex gap-2">
            <button @click="handleChangeRoom" class="flex-1 flex items-center justify-center px-3 py-3 text-sm font-bold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 shadow-sm rounded-xl transition-all" title="สลับห้องเรียน">
              <i class="bi bi-arrow-left-right text-lg"></i>
            </button>
            <button @click="logout" class="flex-1 flex items-center justify-center px-3 py-3 text-sm font-bold text-red-600 bg-red-50 border border-red-100 hover:bg-red-100 shadow-sm rounded-xl transition-all" title="ออกจากระบบ">
              <i class="bi bi-power text-lg"></i>
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- ============================================
         ⚙️ MAIN AREA (Header + Content)
         ============================================ -->
    <div class="flex flex-col flex-1 min-w-0 overflow-hidden bg-slate-50/50">

      <header class="flex-shrink-0 bg-white/80 backdrop-blur-xl border-b border-slate-200/60 z-20 sticky top-0">
        <div class="h-16 flex items-center justify-between px-4 sm:px-6">
          <div class="flex items-center min-w-0 gap-2">
            
            <!-- Mobile Menu Btn -->
            <button
              @click="openMobileDrawer"
              class="md:hidden w-10 h-10 -ml-1 rounded-xl text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors flex items-center justify-center border border-transparent hover:border-slate-200"
            >
              <i class="bi bi-list text-2xl"></i>
            </button>

            <!-- Desktop Collapse Btn (Optional location) -->
            <button
              @click="toggleSidebarCollapse"
              class="hidden md:flex w-10 h-10 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors items-center justify-center"
            >
              <i class="bi bi-text-left text-xl"></i>
            </button>

            <!-- Breadcrumb Navigation -->
            <div class="flex items-center text-sm font-bold text-slate-700 tracking-tight gap-1.5 min-w-0 ms-1">
              <template v-if="authStore.currentRoomId">
                <button
                  @click="handleChangeRoom"
                  class="flex items-center justify-center w-9 h-9 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-colors shrink-0"
                  title="หน้าเลือกห้อง"
                >
                  <i class="bi bi-grid-3x3-gap-fill text-base"></i>
                </button>

                <i class="bi bi-chevron-right text-[10px] font-black text-slate-300"></i>

                <div class="relative flex items-center shrink-0">
                  <button
                    @click.stop="toggleDropdown($event, 'breadcrumbMenu')"
                    class="flex items-center justify-center h-8 px-2.5 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-slate-800 transition-colors"
                  >
                    <span class="truncate max-w-[100px] sm:max-w-[180px]">{{ authStore.currentRoomName || authStore.currentRoomId }}</span>
                    <i class="bi bi-chevron-down text-[10px] ms-2 opacity-50"></i>
                  </button>
                </div>

                <template v-if="currentSubMenuName">
                  <i class="bi bi-chevron-right text-[10px] font-black text-slate-300 shrink-0"></i>
                  <span class="text-blue-600 px-2 truncate max-w-[90px] sm:max-w-[140px]">{{ currentSubMenuName }}</span>
                </template>
              </template>
              <template v-else>
                <div class="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center text-slate-400 shrink-0">
                  <i class="bi bi-house-door-fill"></i>
                </div>
                <i class="bi bi-chevron-right text-[10px] font-black text-slate-300 mx-2"></i>
                <span>ระบบจัดการ</span>
              </template>
            </div>
          </div>

          <!-- Header Right Profile -->
          <div class="relative shrink-0">
            <button
              @click.stop="toggleDropdown($event, 'headerSettings')"
              class="flex items-center p-1 sm:pe-4 bg-white hover:bg-slate-50 border border-slate-200 rounded-full transition-all duration-300 shadow-sm hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              :class="{'ring-2 ring-blue-500/30 border-blue-300': activeDropdown === 'headerSettings'}"
            >
              <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center font-bold text-sm shadow-inner transition-transform duration-300 hover:rotate-6">
                {{ avatarChar }}
              </div>
              <div class="ms-3 hidden sm:block text-left">
                <p class="text-[13px] font-bold text-slate-800 leading-tight">{{ displayName }}</p>
                <p class="text-[10px] text-emerald-500 font-bold uppercase tracking-wider mt-0.5 flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                  Online
                </p>
              </div>
              <i class="bi bi-chevron-down text-slate-400 text-[10px] ms-3 hidden sm:block"></i>
            </button>
          </div>
        </div>
      </header>

      <main class="flex-1 overflow-y-auto overflow-x-hidden focus:outline-none scroll-smooth p-4 md:p-6 lg:p-8">
        <div class="max-w-7xl mx-auto h-full">
          <RouterView v-slot="{ Component, route }">
            <transition name="fade-slide" mode="out-in">
              <div :key="route.path" class="h-full">
                <component :is="Component" />
              </div>
            </transition>
          </RouterView>
        </div>
      </main>
    </div>

    <!-- ============================================
         🗂️ TELEPORT DROPDOWNS
         ============================================ -->
    <Teleport to="body">
      <!-- Backdrop ล่องหน เพื่อดักจับการคลิกนอกกรอบ -->
      <div
        v-if="activeDropdown"
        class="fixed inset-0 z-[70]"
        @click="closeDropdowns"
      ></div>

      <!-- Dropdown สำหรับ Sidebar Settings -->
      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown === 'sidebarSettings'"
          class="fixed z-[80] bg-white/95 backdrop-blur-xl rounded-2xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] border border-slate-200/60 py-2 w-56 max-w-[calc(100vw-2rem)] overflow-hidden"
          :style="dropdownStyle"
        >
          <div class="px-4 py-2.5 mb-1 border-b border-slate-100 bg-slate-50/50">
            <p class="text-[10px] font-black text-slate-400 uppercase tracking-widest">การจัดการบัญชี</p>
          </div>
          <button @click.stop="goToMyProfile" class="w-full text-left px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-blue-50 hover:text-blue-700 transition-colors flex items-center gap-3">
            <i class="bi bi-person-badge text-lg opacity-70"></i> โปรไฟล์ของฉัน
          </button>
          <button @click.stop="goToProfileSettings" class="w-full text-left px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-blue-50 hover:text-blue-700 transition-colors flex items-center gap-3">
            <i class="bi bi-link-45deg text-xl opacity-70 -ms-0.5"></i> จัดการผูกบัญชี
          </button>
          <button @click.stop="handleChangeRoom" class="w-full text-left px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-blue-50 hover:text-blue-700 transition-colors flex items-center gap-3">
            <i class="bi bi-arrow-left-right text-lg opacity-70"></i> สลับห้องเรียน
          </button>
          <div class="h-px bg-slate-100 my-1.5 mx-3"></div>
          <button @click.stop="logout" class="w-full text-left px-4 py-2.5 text-sm font-black text-red-500 hover:bg-red-50 hover:text-red-600 transition-colors flex items-center gap-3">
            <i class="bi bi-box-arrow-right text-lg opacity-80"></i> ออกจากระบบ
          </button>
        </div>
      </Transition>

      <!-- Dropdown สำหรับ Breadcrumb Navigation -->
      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown === 'breadcrumbMenu'"
          class="fixed z-[80] bg-white/95 backdrop-blur-xl rounded-2xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.15)] border border-slate-200/60 py-2 w-56 max-w-[calc(100vw-2rem)]"
          :style="dropdownStyle"
        >
          <p class="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-b border-slate-100 bg-slate-50/50 mb-1">เมนูด่วน</p>
          <RouterLink
            v-for="item in menuItems"
            :key="item.path"
            :to="item.path"
            @click="closeDropdowns"
            class="flex items-center px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-blue-50 hover:text-blue-700 transition-colors"
          >
            <i :class="['bi', item.icon, 'text-base me-3 opacity-70']"></i>
            {{ item.name }}
          </RouterLink>
        </div>
      </Transition>

      <!-- Dropdown สำหรับ Header Profile -->
      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown === 'headerSettings'"
          class="fixed z-[80] bg-white/95 backdrop-blur-xl rounded-3xl shadow-[0_15px_50px_-12px_rgba(0,0,0,0.15)] border border-slate-200/60 w-64 max-w-[calc(100vw-2rem)] overflow-hidden flex flex-col"
          :style="dropdownStyle"
        >
          <div class="px-5 py-4 border-b border-slate-100 bg-gradient-to-br from-slate-50 to-white flex items-center gap-3">
            <div class="w-10 h-10 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center font-bold text-base shadow-sm shrink-0">
                {{ avatarChar }}
            </div>
            <div class="min-w-0">
              <p class="text-sm font-black text-slate-800 truncate leading-tight">{{ displayName }}</p>
              <p class="text-xs text-blue-600 font-bold uppercase truncate mt-0.5">{{ authStore.currentRoleLabel }}</p>
            </div>
          </div>
          <div class="py-2">
            <button @click.stop="goToMyProfile" class="w-full text-left px-5 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50 hover:text-blue-700 transition-colors flex items-center gap-3">
              <i class="bi bi-person-badge text-lg opacity-70"></i> โปรไฟล์ของฉัน
            </button>
            <button @click.stop="goToProfileSettings" class="w-full text-left px-5 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50 hover:text-blue-700 transition-colors flex items-center gap-3">
              <i class="bi bi-link-45deg text-xl opacity-70 -ms-0.5"></i> จัดการบัญชีเชื่อมต่อ
            </button>
            <button @click.stop="handleChangeRoom" class="w-full text-left px-5 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50 hover:text-blue-700 transition-colors flex items-center gap-3">
              <i class="bi bi-grid-3x3-gap-fill text-base opacity-70 ms-0.5"></i> สลับห้องเรียน
            </button>
          </div>
          <div class="p-2 border-t border-slate-100 bg-slate-50/50">
            <button @click.stop="logout" class="w-full text-center px-4 py-2.5 text-sm font-black text-red-600 bg-white hover:bg-red-50 border border-slate-200 hover:border-red-200 rounded-xl transition-colors shadow-sm">
              ออกจากระบบ
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* ซ่อน Scrollbar แต่อยู่ให้ Scroll ได้ */
.scrollbar-hide::-webkit-scrollbar {
    display: none;
}
.scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
}

/* 🪄 Router View Animation */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(15px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-15px);
}

/* 🪄 General Fade */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 🪄 Drawer Animation */
.slide-right-enter-active,
.slide-right-leave-active {
  transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.slide-right-enter-from,
.slide-right-leave-to {
  transform: translateX(-100%);
}

/* 🪄 Dropdown Animation (Smooth Scale) */
.dropdown-anim-enter-active {
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dropdown-anim-leave-active {
  transition: all 0.15s cubic-bezier(0.4, 0, 1, 1);
}
.dropdown-anim-enter-from,
.dropdown-anim-leave-to {
  opacity: 0;
  transform: scale(0.92) translateY(-10px);
}
</style>