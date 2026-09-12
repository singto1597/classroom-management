<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { linkDiscordAccount, loginWithDiscord } from '@/services/auth';
import Swal from 'sweetalert2';
import StateBlock from '@/components/ui/StateBlock.vue';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const errorMsg = ref<string | null>(null);
const botInviteUrl = computed(() => import.meta.env.VITE_DISCORD_BOT_INVITE_URL || '#');

/** รูปร่าง error ที่หลุดมาจาก axios/Backend — api.ts reject เป็น Error ที่มี message เสมอ */
interface ApiErrorLike {
  message?: string;
  response?: { data?: { detail?: string } };
}

onMounted(async () => {
  const code = typeof route.query.code === 'string' ? route.query.code : null;
  if (!code) {
    errorMsg.value = 'ไม่พบรหัสยืนยันตัวตนจาก Discord';
    return;
  }

  try {
    if (authStore.isAuthenticated) {
      const response = await linkDiscordAccount(code);
      await authStore.fetchProfile();
      Swal.fire({
        icon: 'success',
        title: 'สำเร็จ!',
        text: response?.message || 'ผูกบัญชี Discord สำเร็จแล้ว',
        confirmButtonColor: '#1d4ed8',
      }).then(() => router.push('/dashboard'));
    } else {
      const response = await loginWithDiscord(code);
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
  } catch (err: unknown) {
    console.error('Discord Auth failed:', err);
    const apiError = typeof err === 'object' && err !== null ? (err as ApiErrorLike) : null;
    errorMsg.value = apiError?.response?.data?.detail || apiError?.message || 'การยืนยันตัวตนล้มเหลว';
  }
});

const goBackToLogin = () => router.push('/login');
</script>

<template>
  <!-- ⚠️ หน้านี้อยู่นอก MainLayout จึงต้องจัดระยะขอบ + จัดกลางจอเอง -->
  <div
    class="flex min-h-screen min-h-dvh flex-col items-center justify-center bg-paper px-4 py-10 font-sans text-ink"
  >
    <div class="w-full max-w-md">
      <div class="mb-6 flex items-center justify-center gap-2.5">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
        >
          <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
        </div>
        <span class="font-display truncate text-lg font-bold tracking-[0.2em] text-stone-900">
          SYNC<span class="font-normal text-stone-400">ROOM</span>
        </span>
      </div>

      <div v-if="!errorMsg" class="page-card p-8 text-center">
        <div class="relative mx-auto mb-5 h-16 w-16">
          <div class="absolute inset-0 rounded-full border-2 border-stone-200"></div>
          <div
            class="absolute inset-0 animate-spin rounded-full border-2 border-brand-700 border-t-transparent"
          ></div>
          <i
            class="bi bi-discord absolute inset-0 flex items-center justify-center text-2xl text-brand-700"
            aria-hidden="true"
          ></i>
        </div>
        <p class="font-display text-lg font-bold text-stone-900">
          {{ authStore.isAuthenticated ? 'กำลังผูกบัญชี Discord...' : 'กำลังเข้าสู่ระบบ...' }}
        </p>
        <p class="mt-1 text-sm leading-relaxed text-stone-500">
          กรุณารอสักครู่ ระบบกำลังสื่อสารกับเซิร์ฟเวอร์อย่างปลอดภัย
        </p>
      </div>

      <template v-else>
        <StateBlock
          variant="error"
          icon="bi-exclamation-triangle"
          title="ทำรายการไม่สำเร็จ"
          :hint="errorMsg || undefined"
          retry-text="กลับไปหน้าเข้าสู่ระบบ"
          @retry="goBackToLogin"
        />

        <!-- ทางออกสำรอง: ชวนบอทเข้ากับเซิร์ฟเวอร์ -->
        <a :href="botInviteUrl" target="_blank" rel="noopener noreferrer" class="btn-ghost-ui mt-3 w-full">
          <svg
            class="h-5 w-5 shrink-0"
            viewBox="0 0 127.14 96.36"
            fill="currentColor"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z"/>
          </svg>
          เพิ่มบอทลง Discord
        </a>
      </template>

      <p class="mt-6 text-center text-xs text-stone-400">SYNCROOM — ระบบจัดการห้องเรียน</p>
    </div>
  </div>
</template>
