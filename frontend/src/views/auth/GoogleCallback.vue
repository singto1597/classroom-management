<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { linkGoogleAccount, loginWithGoogle } from '@/services/auth';
import Swal from 'sweetalert2';
import StateBlock from '@/components/ui/StateBlock.vue';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const errorMsg = ref<string | null>(null);

/** รูปร่าง error ที่หลุดมาจาก axios/Backend — api.ts reject เป็น Error ที่มี message เสมอ */
interface ApiErrorLike {
  message?: string;
  response?: { data?: { detail?: string } };
}

onMounted(async () => {
  const code = typeof route.query.code === 'string' ? route.query.code : null;
  if (!code) {
    errorMsg.value = 'ไม่พบรหัสยืนยันตัวตนจาก Google';
    return;
  }

  try {
    if (authStore.isAuthenticated) {
      // 🔗 โหมดผูกบัญชี
      const response = await linkGoogleAccount(code);
      await authStore.fetchProfile();
      Swal.fire({
        icon: 'success',
        title: 'สำเร็จ!',
        text: response?.message || 'ผูกบัญชี Google เข้ากับระบบสำเร็จแล้ว',
        confirmButtonColor: '#1d4ed8',
      }).then(() => router.push('/dashboard'));

    } else {
      // 🔑 โหมดเข้าสู่ระบบ
      const response = await loginWithGoogle(code);
      authStore.setToken(response.access_token);

      // เซฟ user_id ลง Store
      authStore.setUserId(response.user_id);

      await authStore.fetchProfile();
      if (!authStore.isOnboarded) {
        router.push('/onboarding');
      } else {
        router.push('/lobby');
      }
    }
  } catch (err: unknown) {
    console.error('Google Auth failed:', err);
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
            class="bi bi-google absolute inset-0 flex items-center justify-center text-2xl text-brand-700"
            aria-hidden="true"
          ></i>
        </div>
        <p class="font-display text-lg font-bold text-stone-900">
          {{ authStore.isAuthenticated ? 'กำลังผูกบัญชี Google...' : 'กำลังเข้าสู่ระบบ...' }}
        </p>
        <p class="mt-1 text-sm leading-relaxed text-stone-500">
          กรุณารอสักครู่ ระบบกำลังสื่อสารกับเซิร์ฟเวอร์อย่างปลอดภัย
        </p>
      </div>

      <StateBlock
        v-else
        variant="error"
        icon="bi-exclamation-triangle"
        title="ทำรายการไม่สำเร็จ"
        :hint="errorMsg || undefined"
        retry-text="กลับไปหน้าเข้าสู่ระบบ"
        @retry="goBackToLogin"
      />

      <p class="mt-6 text-center text-xs text-stone-400">SYNCROOM — ระบบจัดการห้องเรียน</p>
    </div>
  </div>
</template>
