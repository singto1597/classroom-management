<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { loginWithDiscord } from '@/services/auth';
import api from '@/services/api'; 
import Swal from 'sweetalert2';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const errorMsg = ref<string | null>(null);

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
      </div>
    </div>
  </div>
</template>