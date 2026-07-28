<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { RouterView, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const router = useRouter();
const activeDropdown = ref(false);

// 🚨 บังคับดึงข้อมูลให้เป็นปัจจุบันที่สุดเสมอ ป้องกันข้อมูลผี
onMounted(async () => {
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
});

const toggleDropdown = () => {
  activeDropdown.value = !activeDropdown.value;
};

const closeDropdown = () => {
  activeDropdown.value = false;
};

const logout = () => {
  closeDropdown();
  authStore.logout();
};

const goToProfileSettings = async () => {
  closeDropdown();
  await authStore.fetchProfile();

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
        <p class="text-sm text-slate-500 font-medium">จัดการเชื่อมต่อแพลตฟอร์มต่างๆ เพื่อป้องกันการสูญหายของข้อมูลห้องเรียน</p>
        
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
  <div class="min-h-screen bg-[#f8fafc] font-sans flex flex-col relative overflow-hidden">
    
    <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-400/5 rounded-full blur-[100px] pointer-events-none -translate-y-1/2 translate-x-1/3"></div>
    <div class="absolute top-40 left-0 w-[400px] h-[400px] bg-indigo-400/5 rounded-full blur-[80px] pointer-events-none -translate-x-1/2"></div>

    <div v-if="activeDropdown" class="fixed inset-0 z-40" @click="closeDropdown"></div>

    <header class="bg-white/70 backdrop-blur-xl border-b border-slate-200/50 sticky top-0 z-50 shadow-[0_4px_30px_rgba(0,0,0,0.02)]">
      <div class="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
        
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 bg-gradient-to-br from-slate-800 to-slate-900 rounded-xl flex items-center justify-center shadow-lg shadow-slate-900/20">
            <i class="bi bi-box-fill text-white text-xl"></i>
          </div>
          <h1 class="text-2xl font-black tracking-widest text-slate-800">SYNC<span class="font-light text-slate-500">ROOM</span></h1>
        </div>

        <div class="relative">
          <button 
            @click="toggleDropdown" 
            class="flex items-center gap-3 p-1.5 pe-4 bg-white/50 hover:bg-white border border-slate-200/60 rounded-full transition-all duration-300 shadow-sm hover:shadow-md cursor-pointer active:scale-95 group"
          >
            <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-indigo-500 to-blue-600 text-white flex items-center justify-center font-black shadow-inner group-hover:scale-105 transition-transform duration-300">
              {{ authStore.firstName ? authStore.firstName.charAt(0).toUpperCase() : 'U' }}
            </div>
            <span class="text-sm font-bold text-slate-700 hidden sm:block tracking-wide">{{ authStore.currentUserName }}</span>
            <i class="bi bi-chevron-down text-xs text-slate-400 ms-1 transition-transform duration-300" :class="{'rotate-180': activeDropdown}"></i>
          </button>

          <transition name="fade-scale">
            <div v-if="activeDropdown" class="absolute right-0 mt-3 w-64 bg-white rounded-[1.5rem] shadow-2xl shadow-slate-200/50 border border-slate-100 py-3 z-50 origin-top-right">
              <div class="px-5 py-3 mb-2 bg-slate-50/50 mx-2 rounded-2xl border border-slate-100/50">
                <p class="text-sm font-black text-slate-800 truncate">{{ authStore.currentUserName }}</p>
                <p class="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-1">Global Account</p>
              </div>
              <div class="px-2 space-y-1">
                <button @click="goToProfileSettings" class="w-full text-left px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 hover:text-indigo-600 rounded-xl transition-all duration-200 flex items-center gap-3">
                  <div class="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center"><i class="bi bi-link-45deg text-slate-400 text-lg"></i></div> จัดการผูกบัญชี
                </button>
                <div class="h-px bg-slate-100 my-2 mx-2"></div>
                <button @click="logout" class="w-full text-left px-4 py-2.5 text-sm font-black text-rose-500 hover:bg-rose-50 hover:text-rose-600 rounded-xl transition-all duration-200 flex items-center gap-3">
                  <div class="w-7 h-7 rounded-lg bg-rose-50 flex items-center justify-center"><i class="bi bi-power text-rose-400"></i></div> ออกจากระบบ
                </button>
              </div>
            </div>
          </transition>
        </div>

      </div>
    </header>

    <main class="flex-1 w-full mx-auto relative z-10 p-6 md:p-8">
      <RouterView v-slot="{ Component }">
        <transition name="fade-slide" mode="out-in">
          <component :is="Component" />
        </transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.fade-slide-enter-active, .fade-slide-leave-active { transition: all 0.5s cubic-bezier(0.2, 0.8, 0.2, 1); }
.fade-slide-enter-from { opacity: 0; transform: translateY(20px) scale(0.98); }
.fade-slide-leave-to { opacity: 0; transform: translateY(-20px) scale(0.98); }

.fade-scale-enter-active, .fade-scale-leave-active { transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.fade-scale-enter-from, .fade-scale-leave-to { opacity: 0; transform: scale(0.95) translateY(-10px); }
</style>