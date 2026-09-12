<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const route = useRoute();

// 🚨 บังคับดึงข้อมูลให้เป็นปัจจุบันที่สุดเสมอ ป้องกันข้อมูลผี
const activeDropdown = ref(false);
const dropdownStyle = ref<{ top: string; left: string; right: string }>({
  top: '0px',
  left: 'auto',
  right: '0px',
});

onMounted(async () => {
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }
  window.addEventListener('scroll', closeDropdown, true);
  window.addEventListener('resize', closeDropdown);
});

onUnmounted(() => {
  window.removeEventListener('scroll', closeDropdown, true);
  window.removeEventListener('resize', closeDropdown);
});

const closeDropdown = () => {
  activeDropdown.value = false;
};

watch(
  () => route.path,
  () => closeDropdown(),
);

const toggleDropdown = (event: MouseEvent) => {
  if (activeDropdown.value) {
    closeDropdown();
    return;
  }

  const trigger = event.currentTarget as HTMLElement;
  const rect = trigger.getBoundingClientRect();
  const panelWidth = 256;

  // ชิดขวาเสมอ แต่ไม่ให้ล้นขอบจอ
  const right = Math.max(12, window.innerWidth - rect.right);

  dropdownStyle.value = {
    top: `${rect.bottom + 8}px`,
    left: 'auto',
    right: `${Math.min(right, Math.max(12, window.innerWidth - panelWidth - 12))}px`,
  };

  activeDropdown.value = true;
};

const avatarChar = () => {
  const name = authStore.nickname || authStore.firstName;
  return name && name !== 'ไม่ระบุชื่อ' ? name.charAt(0).toUpperCase() : 'ส';
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

  const row = (linked: boolean, label: string, icon: string, href: string, brandColor: string) => `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px;border-radius:14px;border:1px solid ${linked ? '#A7F3D0' : '#E7E5E4'};background:${linked ? '#ECFDF5' : '#FFFFFF'}">
      <div style="display:flex;align-items:center;gap:12px;min-width:0">
        <div style="width:40px;height:40px;border-radius:12px;background:#F5F5F4;display:flex;align-items:center;justify-content:center;flex-shrink:0">
          <i class="${icon}" style="font-size:18px;color:${brandColor}"></i>
        </div>
        <div style="text-align:left;min-width:0">
          <p style="font-weight:700;color:#1C1917;margin:0;font-size:14px">${label}</p>
          <p style="font-size:11px;font-weight:700;margin:2px 0 0;color:${linked ? '#059669' : '#A8A29E'}">
            ${linked ? 'เชื่อมต่อแล้ว' : 'ยังไม่ได้เชื่อมต่อ'}
          </p>
        </div>
      </div>
      ${!linked ? `<a href="${href}" style="flex-shrink:0;padding:8px 16px;background:#1D4ED8;color:#fff;font-size:12px;font-weight:700;border-radius:10px;text-decoration:none">ผูกบัญชี</a>` : ''}
    </div>
  `;

  Swal.fire({
    title:
      '<span style="font-family:Anuphan;font-weight:700;font-size:19px">จัดการบัญชีและการเชื่อมต่อ</span>',
    html: `
      <div style="text-align:left;display:flex;flex-direction:column;gap:12px;margin-top:16px">
        <p style="font-size:13px;color:#78716C;margin:0">เชื่อมต่อแพลตฟอร์มต่างๆ เพื่อรวมข้อมูลของคุณให้เป็นหนึ่งเดียว ป้องกันการสูญหาย</p>
        ${row(isGoogleLinked, 'Google Account', 'bi bi-google', googleUrl, '#EA4335')}
        ${row(isDiscordLinked, 'Discord Account', 'bi bi-discord', discordUrl, '#5865F2')}
      </div>
    `,
    showConfirmButton: true,
    confirmButtonText: 'ปิดหน้าต่าง',
    confirmButtonColor: '#1d4ed8',
  });
};
</script>

<template>
  <div class="relative flex min-h-screen min-h-dvh flex-col bg-paper font-sans text-ink">
    <!-- ============================================
         🔝 HEADER แบบแบน — เส้นคั่นบาง ไม่มีกระจกเงา
         ============================================ -->
    <header
      class="sticky top-0 z-30 border-b border-stone-200 bg-white"
      :style="{ paddingTop: 'env(safe-area-inset-top)' }"
    >
      <div class="page-wrap flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:h-20">
        <!-- โลโก้ -->
        <RouterLink to="/lobby" class="flex min-w-0 items-center gap-2.5">
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white sm:h-10 sm:w-10"
          >
            <i class="bi bi-box-fill text-base sm:text-lg" aria-hidden="true"></i>
          </div>
          <span
            class="font-display truncate text-lg font-bold tracking-[0.2em] text-stone-900 sm:text-xl"
          >
            SYNC<span class="font-normal text-stone-400">ROOM</span>
          </span>
        </RouterLink>

        <!-- โปรไฟล์ -->
        <div class="shrink-0">
          <button
            v-if="authStore.isAuthenticated"
            type="button"
            class="flex items-center gap-2 rounded-full border border-stone-200 bg-white p-1 transition-colors hover:border-stone-300 hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30 sm:pe-3"
            :class="{ 'ring-2 ring-brand-500/25': activeDropdown }"
            @click.stop="toggleDropdown"
          >
            <div
              class="flex h-9 w-9 items-center justify-center rounded-full bg-brand-700 text-sm font-bold text-white"
            >
              {{ avatarChar() }}
            </div>
            <span class="hidden max-w-[140px] truncate text-sm font-bold text-stone-700 sm:block">
              {{ authStore.currentUserName }}
            </span>
            <i
              class="bi bi-chevron-down hidden text-[10px] text-stone-400 transition-transform duration-200 sm:block"
              :class="{ 'rotate-180': activeDropdown }"
              aria-hidden="true"
            ></i>
          </button>
        </div>
      </div>
    </header>

    <!-- ============================================
         📄 เนื้อหา
         ============================================ -->
    <main class="relative z-10 flex-1 px-4 py-6 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] sm:px-6 sm:py-8 lg:py-10">
      <div class="page-wrap">
        <RouterView v-slot="{ Component, route: r }">
          <transition name="fade-slide" mode="out-in">
            <div :key="r.path">
              <component :is="Component" />
            </div>
          </transition>
        </RouterView>
      </div>
    </main>

    <!-- ============================================
         ⚓ ท้ายหน้า — จุดยึดสายตาปิดท้าย
         ============================================ -->
    <footer class="border-t border-stone-200 bg-white">
      <div
        class="page-wrap flex flex-col items-center justify-between gap-2 px-4 py-5 text-xs text-stone-400 sm:flex-row sm:px-6"
      >
        <p class="font-semibold">SYNCROOM — ระบบจัดการห้องเรียน</p>
        <p>เวลาไทย (Asia/Bangkok) · ใช้ฟรีสำหรับห้องเรียน</p>
      </div>
    </footer>

    <!-- ============================================
         🗂️ DROPDOWN (Teleport กัน stacking context)
         ============================================ -->
    <Teleport to="body">
      <div v-if="activeDropdown" class="fixed inset-0 z-[70]" @click="closeDropdown"></div>

      <Transition name="dropdown-anim">
        <div
          v-if="activeDropdown"
          class="fixed z-[80] flex w-64 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
          :style="dropdownStyle"
        >
          <div class="border-b border-stone-100 bg-stone-50/70 px-5 py-4">
            <p class="truncate text-sm font-bold text-stone-800">
              {{ authStore.currentUserName }}
            </p>
            <p class="mt-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-stone-400">
              Global Account
            </p>
          </div>

          <div class="py-1.5">
            <button
              type="button"
              class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-brand-50 hover:text-brand-700"
              @click.stop="goToProfileSettings"
            >
              <i class="bi bi-link-45deg text-xl opacity-70" aria-hidden="true"></i>
              จัดการผูกบัญชี
            </button>
          </div>

          <div class="border-t border-stone-100 bg-stone-50/60 p-2">
            <button
              type="button"
              class="w-full rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-center text-sm font-bold text-red-600 transition-colors hover:border-red-200 hover:bg-red-50"
              @click.stop="logout"
            >
              ออกจากระบบ
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.dropdown-anim-enter-active {
  transition: all 0.18s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.dropdown-anim-leave-active {
  transition: all 0.12s ease-in;
}
.dropdown-anim-enter-from,
.dropdown-anim-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .fade-slide-enter-active,
  .fade-slide-leave-active,
  .dropdown-anim-enter-active,
  .dropdown-anim-leave-active {
    transition-duration: 0.01ms;
  }
}
</style>
