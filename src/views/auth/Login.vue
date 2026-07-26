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
  <div class="min-h-screen flex items-center justify-center bg-gray-100">
    <div class="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center">
      <h1 class="text-2xl font-bold mb-6 text-gray-800">Classroom Sync</h1>
      <p class="text-gray-600 mb-8">Please login to continue</p>
      
      <div class="flex flex-col gap-4">
        <button 
          @click="handleGoogleLogin"
          class="w-full flex items-center justify-center gap-3 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 font-bold py-3 px-4 rounded-lg transition duration-200 shadow-sm"
        >
          <i class="bi bi-google text-xl text-red-500"></i>
          Login with Google
        </button>

        <button 
          @click="handleDiscordLogin"
          class="w-full flex items-center justify-center gap-3 bg-[#5865F2] hover:bg-[#4752C4] text-white font-bold py-3 px-4 rounded-lg transition duration-200 shadow-sm"
        >
          <i class="bi bi-discord text-xl"></i>
          Login with Discord
        </button>
      </div>
    </div>
  </div>
</template>