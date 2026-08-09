<script setup lang="ts">
import { getDiscordAuthUrl, getGoogleAuthUrl } from '@/services/auth';

const handleDiscordLogin = () => {
  window.location.href = getDiscordAuthUrl();
};

const handleGoogleLogin = () => {
  window.location.href = getGoogleAuthUrl();
};
</script>

<template>
  <div class="min-h-screen bg-slate-50 flex items-center justify-center p-4 relative overflow-hidden">
    <!-- Decorative Glows -->
    <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-500/10 rounded-full blur-[100px] pointer-events-none -translate-y-1/2 translate-x-1/3"></div>
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] bg-indigo-500/10 rounded-full blur-[80px] pointer-events-none translate-y-1/2 -translate-x-1/3"></div>

    <div class="max-w-md w-full bg-white/80 backdrop-blur-xl rounded-[2rem] shadow-2xl shadow-slate-200/50 border border-white p-6 sm:p-8 md:p-10 text-center relative z-10">

      <div class="w-16 h-16 sm:w-20 sm:h-20 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-2xl sm:rounded-[1.5rem] flex items-center justify-center shadow-lg shadow-blue-600/30 mx-auto mb-5">
        <i class="bi bi-box-fill text-white text-3xl sm:text-4xl"></i>
      </div>

      <h1 class="text-2xl sm:text-3xl font-black text-slate-800 tracking-tight mb-2">
        SYNC<span class="font-light">ROOM</span>
      </h1>
      <p class="text-slate-500 font-medium mb-6">เข้าสู่ระบบเพื่อจัดการห้องเรียนของคุณ</p>

      <div class="flex flex-col gap-3">
        <button
          @click="handleGoogleLogin"
          class="w-full flex items-center justify-center gap-3 bg-white border border-slate-200 hover:border-blue-300 hover:shadow-md text-slate-700 font-bold py-3.5 px-4 rounded-2xl transition-all duration-200 shadow-sm active:scale-95"
        >
          <i class="bi bi-google text-xl text-rose-500"></i>
          เข้าสู่ระบบด้วย Google
        </button>

        <button
          @click="handleDiscordLogin"
          class="w-full flex items-center justify-center gap-3 bg-[#5865F2] hover:bg-[#4752C4] text-white font-bold py-3.5 px-4 rounded-2xl transition-all duration-200 shadow-lg shadow-[#5865F2]/20 active:scale-95"
        >
          <i class="bi bi-discord text-xl"></i>
          เข้าสู่ระบบด้วย Discord
        </button>
      </div>

      <p class="text-xs text-slate-400 font-medium mt-6 leading-relaxed">
        การเข้าสู่ระบบจะใช้ข้อมูลโปรไฟล์จากบัญชีของคุณ<br>เพื่อผูกกับรายชื่อในห้องเรียน
      </p>
    </div>
  </div>
</template>
