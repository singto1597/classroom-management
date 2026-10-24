<script setup lang="ts">
/**
 * 🕳️ 404 — catch-all ของ router (`/:pathMatch(.*)*`)
 *
 * เดิมไม่มี route นี้เลย ⇒ พิมพ์ URL ผิดหรือเปิดลิงก์เก่าที่ถูกย้ายแล้ว
 * จะได้ **หน้าจอว่างเปล่า** (router ไม่มีอะไรให้ render) โดยไม่มีข้อความบอกอะไรเลย
 * ผู้ใช้จึงไม่รู้ว่า "URL ผิด" หรือ "ระบบล่ม"
 *
 * หน้านี้อยู่นอก `MainLayout` จึงต้องจัดหน้าตาเต็มหน้าเอง (แบบเดียวกับ Login)
 * และ **ไม่ต้องล็อกอิน** — การบอกว่าไม่มีหน้านี้ไม่ได้รั่วข้อมูลใด ๆ
 */
import { computed } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';

defineOptions({ name: 'NotFoundView' });

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

/** ผู้ใช้ที่ล็อกอินแล้วกลับแดชบอร์ด — คนที่ยังไม่ล็อกอินกลับหน้าเข้าสู่ระบบ */
const homeTarget = computed(() => (authStore.isAuthenticated ? '/dashboard' : '/login'));

/**
 * ปุ่ม "ย้อนกลับ" มีประโยชน์เฉพาะเมื่อมีประวัติให้ย้อน
 * (เปิดลิงก์ตรง ๆ ในแท็บใหม่ = ไม่มีประวัติ ⇒ ซ่อนปุ่มไปเลย)
 */
const canGoBack = computed(() => typeof window !== 'undefined' && window.history.length > 1);
</script>

<template>
  <div class="flex min-h-screen min-h-dvh flex-col bg-paper font-sans text-ink">
    <header class="border-b border-stone-200 bg-white">
      <div class="page-wrap flex h-14 items-center justify-between gap-3 px-4 sm:h-16 sm:px-6 lg:px-8">
        <RouterLink
          to="/"
          class="flex min-w-0 items-center gap-2.5 rounded-lg focus-visible:ring-2 focus-visible:ring-brand-500/30"
        >
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
          >
            <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
          </span>
          <span class="font-display truncate text-lg font-bold tracking-[0.2em] text-stone-900">
            SYNC<span class="font-normal text-stone-400">ROOM</span>
          </span>
        </RouterLink>
      </div>
    </header>

    <main class="flex flex-1 items-center justify-center px-4 py-12 sm:px-6">
      <div class="w-full max-w-lg text-center">
        <p class="font-display text-6xl font-bold leading-none tracking-tight text-stone-200" aria-hidden="true">
          404
        </p>

        <h1 class="font-display mt-4 text-2xl font-bold text-stone-900 sm:text-3xl">
          ไม่พบหน้าที่ต้องการ
        </h1>

        <p class="mt-2 text-sm leading-relaxed text-stone-600">
          หน้านี้อาจถูกย้าย ลบไปแล้ว หรือที่อยู่ในแถบที่อยู่พิมพ์ผิด
        </p>

        <!-- Path ที่พยายามเปิด — ช่วยให้ผู้ใช้เห็นว่าผิดตรงไหน (Vue escape ให้แล้ว) -->
        <p class="mt-4 flex justify-center">
          <code
            class="max-w-full truncate rounded-lg border border-stone-200 bg-white px-3 py-1.5 font-mono text-xs text-stone-500"
            :title="route.fullPath"
          >
            {{ route.fullPath }}
          </code>
        </p>

        <div class="mt-8 flex flex-col justify-center gap-2 sm:flex-row">
          <RouterLink :to="homeTarget" class="btn-primary justify-center">
            <i class="bi bi-house-door" aria-hidden="true"></i>
            {{ authStore.isAuthenticated ? 'กลับหน้าหลัก' : 'ไปหน้าเข้าสู่ระบบ' }}
          </RouterLink>

          <button v-if="canGoBack" type="button" class="btn-ghost-ui justify-center" @click="router.back()">
            <i class="bi bi-arrow-left" aria-hidden="true"></i>
            ย้อนกลับ
          </button>
        </div>
      </div>
    </main>
  </div>
</template>
