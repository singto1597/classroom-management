<script setup lang="ts">
/**
 * 🔐 เข้าสู่ระบบ — การ์ดกลางหน้าจอบนกระดาษจุด (PIRIvoice light card)
 *
 * ไม่มีฮีโร่สีเข้มแบบเดิม: ผู้ใช้ที่มาถึงหน้านี้ต้องการกดปุ่มเดียว
 * ⇒ เนื้อหาที่จำเป็นมีแค่ชื่อแอป คำอธิบายสั้น ๆ และปุ่ม OAuth สองปุ่ม
 */
defineOptions({ name: 'LoginView' });

import { RouterLink } from 'vue-router';
import { getDiscordAuthUrl, getGoogleAuthUrl } from '@/services/auth';

const handleDiscordLogin = () => {
  window.location.href = getDiscordAuthUrl();
};

const handleGoogleLogin = () => {
  window.location.href = getGoogleAuthUrl();
};
</script>

<template>
  <div class="relative flex min-h-[100dvh] flex-col bg-canvas font-sans text-ink-1">
    <div
      class="pointer-events-none absolute inset-0 -z-10 opacity-60 [background-image:radial-gradient(var(--line)_1px,transparent_1px)] [background-size:20px_20px]"
      aria-hidden="true"
    ></div>

    <header class="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-5 sm:px-6">
      <RouterLink to="/" class="flex items-center gap-2.5">
        <span
          class="flex h-9 w-9 items-center justify-center rounded-control bg-brand text-white"
        >
          <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
        </span>
        <span class="font-display text-lg font-bold text-ink-1">
          SYNC<span class="font-normal text-ink-3">ROOM</span>
        </span>
      </RouterLink>

      <RouterLink
        to="/"
        class="inline-flex h-11 items-center gap-1.5 rounded-control px-2 text-sm font-semibold text-ink-2 transition-colors hover:bg-surface hover:text-ink-1"
      >
        <i class="bi bi-arrow-left text-sm" aria-hidden="true"></i>
        กลับหน้าแรก
      </RouterLink>
    </header>

    <main class="flex flex-1 items-center justify-center px-4 pb-12 pt-4">
      <div class="w-full max-w-[420px]">
        <div class="page-card p-6 sm:p-8">
          <h1 class="font-display text-title-l font-bold text-ink-1">เข้าสู่ระบบ</h1>
          <p class="mt-2 text-sm leading-relaxed text-ink-2">
            เลือกบัญชีที่คุณใช้อยู่เพื่อดำเนินการต่อ ไม่ต้องสมัครบัญชีใหม่
          </p>

          <div class="mt-6 flex flex-col gap-3">
            <button
              type="button"
              class="btn-ghost-ui h-12 w-full gap-3 text-ink-1"
              @click="handleGoogleLogin"
            >
              <svg class="h-5 w-5 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"/>
                <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A11 11 0 0 0 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52Z"/>
              </svg>
              ดำเนินการต่อด้วย Google
            </button>

            <button
              type="button"
              class="btn-ghost-ui h-12 w-full gap-3 text-ink-1"
              @click="handleDiscordLogin"
            >
              <i class="bi bi-discord shrink-0 text-xl" aria-hidden="true"></i>
              ดำเนินการต่อด้วย Discord
            </button>
          </div>

          <p class="mt-6 border-t border-line pt-4 text-center text-xs leading-relaxed text-ink-3">
            การเข้าสู่ระบบแสดงว่าคุณยอมรับ
            <a
              href="#"
              class="font-bold text-ink-2 underline underline-offset-2 transition-colors hover:text-brand"
              >ข้อตกลงการใช้งาน</a
            >
            และ
            <a
              href="#"
              class="font-bold text-ink-2 underline underline-offset-2 transition-colors hover:text-brand"
              >นโยบายความเป็นส่วนตัว</a
            >
          </p>
        </div>

        <p class="mt-4 text-center text-xs text-ink-3">
          ยังไม่รู้จักระบบ?
          <a href="/#features" class="font-bold text-ink-2 hover:text-brand">
            ดูฟีเจอร์ทั้งหมด
          </a>
        </p>
      </div>
    </main>
  </div>
</template>
