<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { loginWithDiscord } from '@/services/auth';
import api from '@/services/api'; 
import Swal from 'sweetalert2';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const errorMsg = ref<string | null>(null);
const botInviteUrl = computed(() => import.meta.env.VITE_DISCORD_BOT_INVITE_URL || '#');

onMounted(async () => {
  const code = route.query.code as string;
  if (!code) {
    errorMsg.value = 'ไม่พบรหัสยืนยันตัวตนจาก Discord';
    return;
  }

  try {
    if (authStore.isAuthenticated) {
      const response: any = await api.post('/api/auth/discord/link', { code });
      await authStore.fetchProfile();
      Swal.fire({
        icon: 'success', title: 'สำเร็จ!', text: response?.message || 'ผูกบัญชี Discord สำเร็จแล้ว',
        customClass: { popup: 'rounded-3xl' }, confirmButtonColor: '#10b981'
      }).then(() => router.push('/dashboard'));
    } else {
      // 🚨 แก้ไขตรงนี้: ใส่ : any เพื่อบอก TypeScript ว่าเราดึงค่าอะไรก็ได้
      const response: any = await loginWithDiscord(code);
      authStore.setToken(response.access_token);
      
      // เซฟ user_id ลง Store ทันที
      authStore.setUserId(response.user_id);
      
      await authStore.fetchProfile();
      if (!authStore.isOnboarded) {
        router.push('/onboarding');
      } else {
        router.push('/lobby');
      }
    }
  } catch (err: any) {
    console.error('Discord Auth failed:', err);
    errorMsg.value = err.response?.data?.detail || err.message || 'การยืนยันตัวตนล้มเหลว';
  }
});

const goBackToLogin = () => router.push('/login');
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-slate-50">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-xl border border-slate-100 p-10 text-center">
      <div v-if="!errorMsg">
        <div class="relative w-20 h-20 mx-auto mb-6">
          <div class="absolute inset-0 rounded-full border-4 border-slate-100"></div>
          <div class="absolute inset-0 rounded-full border-4 border-[#5865F2] border-t-transparent animate-spin"></div>
          <i class="bi bi-discord absolute inset-0 flex items-center justify-center text-2xl text-[#5865F2]"></i>
        </div>
        <h2 class="text-2xl font-bold text-slate-800 mb-2">{{ authStore.isAuthenticated ? 'กำลังผูกบัญชี Discord...' : 'กำลังเข้าสู่ระบบ...' }}</h2>
        <p class="text-slate-500 font-medium">กรุณารอสักครู่ ระบบกำลังสื่อสารกับเซิร์ฟเวอร์อย่างปลอดภัย</p>
      </div>
      <div v-else class="animate-in fade-in zoom-in duration-300">
        <div class="w-20 h-20 bg-rose-50 text-rose-500 rounded-full flex items-center justify-center mx-auto mb-6 shadow-inner"><i class="bi bi-exclamation-triangle-fill text-3xl"></i></div>
        <h2 class="text-2xl font-bold text-slate-800 mb-2">ทำรายการไม่สำเร็จ</h2>
        <p class="text-rose-600 font-medium mb-8 bg-rose-50 p-4 rounded-xl border border-rose-100 text-sm break-words">{{ errorMsg }}</p>
        <button @click="goBackToLogin" class="w-full bg-slate-900 hover:bg-slate-800 text-white font-bold py-3.5 px-6 rounded-xl transition-all shadow-lg flex items-center justify-center gap-2"><i class="bi bi-arrow-left"></i> กลับไปหน้าเข้าสู่ระบบ</button>
        <a
          :href="botInviteUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="mt-4 w-full inline-flex items-center justify-center gap-2 bg-[#5865F2] hover:bg-[#4752C4] text-white font-bold py-3.5 px-6 rounded-xl transition-all shadow-lg"
        >
          <svg class="w-5 h-5" viewBox="0 0 127.14 96.36" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
            <path d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z"/>
          </svg>
          เพิ่มบอทลง Discord
        </a>
      </div>
    </div>
  </div>
</template>
