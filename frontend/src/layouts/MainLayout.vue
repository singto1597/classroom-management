<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { RouterView, useRouter, useRoute, RouterLink } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';
import { StudentService } from '@/services/student'; 

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

const isSidebarOpen = ref(false);
const activeDropdown = ref<string | null>(null);

// ✨ โหลดข้อมูลโปรไฟล์ (บังคับดึงเสมอ เพื่อให้ข้อมูลสดใหม่ตลอดเวลา)
onMounted(async () => {
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
});

// ✨ ระบบชื่อใหม่ ดึงจาก authStore ที่จัดการแล้ว 100%
const displayName = computed(() => authStore.currentUserName);

// ✨ ดึงตัวอักษรตัวแรกของชื่อมาทำเป็นรูปโปรไฟล์
const avatarChar = computed(() => {
  return authStore.firstName && authStore.firstName !== 'ไม่ระบุชื่อ' 
    ? authStore.firstName.charAt(0).toUpperCase() : 'U';
});

const toggleDropdown = (dropdownName: string) => {
  activeDropdown.value = activeDropdown.value === dropdownName ? null : dropdownName;
};

const closeDropdowns = () => {
  activeDropdown.value = null;
};

const menuItems = [
  { name: 'หน้าหลัก (เลือกห้อง)', path: '/dashboard', icon: 'bi-grid-fill' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people-fill' },
  { name: 'งานและโน้ต', path: '/tasks', icon: 'bi-clipboard-check-fill' },
  { name: 'ตารางเรียน', path: '/schedules', icon: 'bi-calendar-event-fill' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
];

const handleChangeRoom = () => {
  closeDropdowns();
  authStore.clearRoom(); 
  router.push('/lobby'); 
};

const currentSubMenuName = computed(() => {
  if (route.path === '/dashboard' || route.path === '/') return null;
  const matchedMenu = menuItems.find(item => 
    item.path !== '/dashboard' && route.path.startsWith(item.path)
  );
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
        <p class="text-sm text-gray-600"><b>Room Role:</b> <span class="uppercase font-bold text-blue-600">${authStore.currentRole}</span></p>
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
  closeDropdowns(); // 🚨 แก้บัคเรียกฟังก์ชันผิดชื่อ
  
  // โหลดสถานะล่าสุดจาก Backend ก่อนเปิดหน้าต่าง
  Swal.fire({ title: 'กำลังโหลดข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
  await authStore.fetchProfile();
  Swal.close();

  const isDiscordLinked = !!authStore.discordId;
  const isGoogleLinked = !!authStore.googleId;

  // 🚀 ประกอบ URL สำหรับ OAuth สดๆ จาก .env
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
  <div class="flex h-screen bg-gray-50 overflow-hidden font-sans relative">
    
    <div 
      v-if="activeDropdown" 
      class="fixed inset-0 z-20" 
      @click="closeDropdowns"
    ></div>

    <aside class="hidden md:flex md:flex-shrink-0 relative z-50">
      <div class="flex flex-col w-64 bg-white border-r border-gray-100 shadow-[2px_0_8px_-4px_rgba(0,0,0,0.05)] h-full">
        <RouterLink 
          to="/dashboard" 
          active-class="_no_effects_"
          exact-active-class="_no_effects_"
          class="flex items-center h-16 px-6 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 transition-all duration-300 cursor-pointer shrink-0"
        >
          <i class="bi bi-box-fill text-white text-xl me-3 opacity-90"></i>
          <span class="text-white text-lg font-black tracking-widest">SYNC<span class="font-light opacity-80">ROOM</span></span>
        </RouterLink>

        <div class="flex-1 flex flex-col overflow-y-auto">
          <nav class="flex-1 px-4 py-6 space-y-1.5">
            <RouterLink 
              v-for="item in menuItems" 
              :key="item.path"
              :to="item.path"
              class="flex items-center px-4 py-3.5 text-sm font-semibold rounded-xl transition-all duration-200 group"
              :class="route.path.startsWith(item.path) && item.path !== '/dashboard' || (route.path === '/dashboard' && item.path === '/dashboard') ? 'bg-blue-50 text-blue-600 shadow-sm border border-blue-100/50' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'"
            >
              <i :class="['bi', item.icon, 'text-lg me-4 transition-transform duration-200 group-hover:scale-110', route.path.startsWith(item.path) && item.path !== '/dashboard' || (route.path === '/dashboard' && item.path === '/dashboard') ? 'scale-110' : '']"></i>
              {{ item.name }}
            </RouterLink>
          </nav>

          <div class="p-3 border-t border-gray-100 bg-gray-50/50 relative">
            <div class="flex items-center justify-between p-2 rounded-xl hover:bg-white border border-transparent hover:border-gray-200 hover:shadow-sm transition-all group">
              <div class="flex items-center overflow-hidden flex-1 cursor-pointer" @click="showAccountInfo">
                <div class="w-9 h-9 rounded-full bg-gradient-to-br from-blue-100 to-blue-50 text-blue-600 flex items-center justify-center font-bold shadow-inner border border-blue-100 shrink-0">
                  {{ avatarChar }}
                </div>
                <div class="ms-3 overflow-hidden">
                  <p class="text-sm font-bold text-gray-800 truncate leading-none mb-1">{{ displayName }}</p>
                  <p class="text-[10px] tracking-wider text-blue-500 font-bold uppercase truncate leading-none">{{ authStore.currentRole || 'User' }}</p>
                </div>
              </div>
              
              <button 
                @click.stop="toggleDropdown('sidebarSettings')"
                class="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors shrink-0 ms-1"
                :class="{'bg-gray-200 text-gray-800': activeDropdown === 'sidebarSettings'}"
              >
                <i class="bi bi-gear-fill text-lg"></i>
              </button>
            </div>

            <transition name="fade-up">
              <div v-if="activeDropdown === 'sidebarSettings'" class="absolute bottom-full left-4 mb-2 w-56 bg-white rounded-2xl shadow-xl border border-gray-100 py-2 z-50 transform origin-bottom-left">
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
            </transition>
          </div>
        </div>
      </div>
    </aside>

    <Transition name="fade">
      <div 
        v-if="isSidebarOpen" 
        class="fixed inset-0 z-40 md:hidden bg-gray-900/40 backdrop-blur-sm transition-opacity"
        @click="isSidebarOpen = false"
      ></div>
    </Transition>

    <div 
      class="fixed inset-y-0 left-0 z-50 w-64 bg-white transform transition-transform duration-300 cubic-bezier(0.4, 0, 0.2, 1) md:hidden shadow-2xl flex flex-col"
      :class="isSidebarOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="flex items-center justify-between h-16 px-6 bg-gradient-to-r from-blue-600 to-blue-700 shrink-0">
        <RouterLink 
          to="/dashboard" 
          @click="isSidebarOpen = false" 
          class="flex items-center h-16 hover:opacity-80 transition cursor-pointer"
        >
          <span class="text-white text-lg font-black tracking-widest">SYNC<span class="font-light opacity-80">ROOM</span></span>
        </RouterLink>
        <button @click="isSidebarOpen = false" class="text-white/80 hover:text-white p-1 rounded-lg transition-colors">
          <i class="bi bi-x-lg text-xl"></i>
        </button>
      </div>
      
      <nav class="flex-1 px-4 py-6 space-y-1.5 overflow-y-auto">
        <RouterLink 
          v-for="item in menuItems" 
          :key="item.path"
          :to="item.path"
          @click="isSidebarOpen = false"
          class="flex items-center px-4 py-3.5 text-sm font-semibold rounded-xl transition-all"
          :class="route.path.startsWith(item.path) && item.path !== '/dashboard' || (route.path === '/dashboard' && item.path === '/dashboard') ? 'bg-blue-50 text-blue-600 shadow-sm border border-blue-100/50' : 'text-gray-500 hover:bg-gray-50'"
        >
          <i :class="['bi', item.icon, 'text-lg me-4']"></i>
          {{ item.name }}
        </RouterLink>
      </nav>

      <div class="p-4 border-t border-gray-100 shrink-0 space-y-2 bg-gray-50">
        <button @click="handleChangeRoom" class="w-full flex items-center justify-center px-4 py-2.5 text-sm font-bold text-gray-600 bg-white border border-gray-200 hover:bg-gray-50 rounded-xl transition-colors shadow-sm">
          <i class="bi bi-arrow-left-right me-2"></i> สลับห้องเรียน
        </button>
        <button @click="logout" class="w-full flex items-center justify-center px-4 py-2.5 text-sm font-bold text-red-500 bg-white border border-red-100 hover:bg-red-50 rounded-xl transition-colors shadow-sm">
          <i class="bi bi-power me-2"></i> ออกจากระบบ
        </button>
      </div>
    </div>

    <div class="flex flex-col flex-1 overflow-hidden relative">
      <header class="flex-shrink-0 bg-white/80 backdrop-blur-md border-b border-gray-100 z-30 sticky top-0 supports-[backdrop-filter]:bg-white/60 relative">
        <div class="h-16 flex items-center justify-between px-4 md:px-6">
          <div class="flex items-center">
            <button 
              @click="isSidebarOpen = true" 
              class="md:hidden p-2 me-3 rounded-xl text-gray-500 hover:text-gray-800 hover:bg-gray-100 transition-colors"
            >
              <i class="bi bi-list text-2xl"></i>
            </button>
            
            <div class="flex items-center text-sm font-bold text-gray-800 tracking-tight gap-1.5 md:gap-2">
              <template v-if="authStore.currentRoomId">
                
                <button 
                  @click="handleChangeRoom" 
                  class="flex items-center justify-center w-8 h-8 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors cursor-pointer"
                  title="กลับหน้าเลือกห้อง"
                >
                  <i class="bi bi-house-door-fill text-lg"></i>
                </button>
                
                <div class="relative flex items-center">
                  <button 
                    @click.stop="toggleDropdown('breadcrumbMenu')" 
                    class="flex items-center justify-center w-6 h-6 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors cursor-pointer relative z-40"
                  >
                    <i class="bi bi-chevron-right text-[10px] font-black"></i>
                  </button>

                  <transition name="fade-scale">
                    <div v-if="activeDropdown === 'breadcrumbMenu'" class="absolute top-full left-0 mt-1 w-48 bg-white rounded-xl shadow-lg border border-gray-100 py-1.5 z-50">
                      <p class="px-3 py-1.5 text-[10px] font-bold text-gray-400 uppercase tracking-wider border-b border-gray-50 mb-1">นำทางด่วน</p>
                      <RouterLink 
                        v-for="item in menuItems" 
                        :key="item.path"
                        :to="item.path"
                        @click="closeDropdowns"
                        class="flex items-center px-4 py-2 text-sm font-semibold text-gray-600 hover:bg-blue-50 hover:text-blue-600 transition-colors"
                      >
                        <i :class="['bi', item.icon, 'text-base me-3']"></i>
                        {{ item.name }}
                      </RouterLink>
                    </div>
                  </transition>
                </div>
                
                <router-link 
                  to="/dashboard" 
                  class="px-2 py-1 rounded-md hover:bg-gray-100 transition-colors cursor-pointer truncate max-w-[120px] sm:max-w-[200px]"
                  title="หน้าหลักห้องเรียน"
                >
                  {{ authStore.currentRoomName || authStore.currentRoomId }}
                </router-link>
                
                <template v-if="currentSubMenuName">
                  <i class="bi bi-chevron-right text-[10px] font-black text-gray-300"></i>
                  <span class="text-blue-600 px-1">{{ currentSubMenuName }}</span>
                </template>

              </template>

              <template v-else>
                <div class="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-400">
                  <i class="bi bi-house-door-fill text-lg"></i>
                </div>
                <i class="bi bi-chevron-right text-[10px] font-black text-gray-300 mx-1"></i>
                <span>ระบบจัดการห้องเรียน</span>
              </template>

            </div>
          </div>

          <div class="relative">
            <button 
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

            <transition name="fade-scale">
              <div v-if="activeDropdown === 'headerSettings'" class="absolute top-full right-0 mt-2 w-56 bg-white rounded-2xl shadow-xl border border-gray-100 py-2 z-50 origin-top-right">
                <div class="px-4 py-3 mb-1 border-b border-gray-50 bg-gray-50/50">
                  <p class="text-sm font-bold text-gray-800 truncate">{{ displayName }}</p>
                  <p class="text-xs text-blue-500 font-bold uppercase truncate">{{ authStore.currentRole }}</p>
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
            </transition>
          </div>
        </div>
      </header>

      <main class="flex-1 overflow-y-auto bg-[#f8fafc] focus:outline-none scroll-smooth relative z-0">
        <div class="py-8">
          <div class="max-w-7xl mx-auto px-4 sm:px-6 md:px-8">
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
  </div>
</template>

<style scoped>
/* 🪄 แอนิเมชันสำหรับ Router View */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(15px) scale(0.99);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-15px) scale(0.99);
}

/* 🪄 แอนิเมชันทั่วไป */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* แอนิเมชันสำหรับเมนู Dropdown แถบ Sidebar ล่าง */
.fade-up-enter-active,
.fade-up-leave-active {
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.fade-up-enter-from,
.fade-up-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.95);
}

/* แอนิเมชันสำหรับเมนู Dropdown มุมขวาบน / Breadcrumb */
.fade-scale-enter-active,
.fade-scale-leave-active {
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: scale(0.95) translateY(-10px);
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>