<script setup lang="ts">
/**
 * ➕ หน้า "เพิ่มเติม" — ทางเข้าทั้งหมดที่ไม่อยู่ใน 4 แท็บหลัก
 *
 * เดิมหน้านี้เป็นชีต (`AppMoreSheet`) ที่เปิดจากแถบล่าง ⇒ เปิดได้อย่างเดียว
 * ปิดแล้วจำอะไรไม่ได้ และเพิ่มเนื้อหา (บัญชี · เวอร์ชัน · ทางลัด) ได้จำกัด
 * ตอนนี้เป็นหน้าจริงที่ใช้ `route.meta.navTab = 'more'` ไฮไลต์แท็บ
 *
 * ⚠️ ทางเข้าหนึ่งทาง = หนึ่งรายการ — ไม่มีเมนูซ้ำระหว่างกลุ่มกับ "บัญชี"
 */
import { computed, onMounted, ref } from 'vue';
import { RouterLink, useRouter } from 'vue-router';
import { MORE_NAV_GROUPS, isNavItemActive } from '@/constants/nav';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import { VersionService } from '@/services/version';
import { avatarInitial } from '@/utils/avatar';
import AppSheet from '@/components/ui/AppSheet.vue';

const authStore = useAuthStore();
const router = useRouter();

const avatarChar = computed(() =>
  avatarInitial(authStore.nickname || authStore.firstName, 'ส'),
);

const isOpeningProfile = ref(false);
const profileError = ref('');
const isLogoutOpen = ref(false);

const versionLabel = ref(`v${__APP_VERSION__}`);
onMounted(async () => {
  try {
    const info = await VersionService.getVersion();
    const sha = info.git_sha === 'unknown' ? 'dev' : info.git_sha.slice(0, 7);
    versionLabel.value = `v${info.version} · ${sha}`;
  } catch {
    // backend ไม่ตอบ — คงเวอร์ชันจาก package.json ไว้
  }
});

/** เปิดโปรไฟล์นักเรียนของตัวเอง — admin ที่ไม่มีแถวในห้องนี้จะเห็นคำอธิบายแทน */
const openMyProfile = async () => {
  if (!authStore.currentRoomId) return;
  isOpeningProfile.value = true;
  profileError.value = '';
  try {
    const myProfile = await StudentService.getMyProfile(authStore.currentRoomId);
    await router.push(`/students/${myProfile.student_no}`);
  } catch {
    profileError.value =
      'คุณอาจเป็นผู้ดูแลระบบ (Admin) ที่ไม่มีข้อมูลในรายชื่อนักเรียนห้องนี้';
  } finally {
    isOpeningProfile.value = false;
  }
};

const confirmLogout = () => {
  isLogoutOpen.value = false;
  authStore.logout();
};
</script>

<template>
  <div class="space-y-6">
    <!-- ข้อมูลตัวตนในห้องนี้ -->
    <section class="page-card p-5">
      <div class="flex items-center gap-4">
        <div
          class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-tint text-xl font-bold text-brand"
        >
          {{ avatarChar }}
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-title-m font-bold text-ink-1">{{ authStore.currentUserName }}</p>
          <p class="mt-0.5 truncate text-caption text-ink-3">
            {{ authStore.currentRoleLabel }} · {{ authStore.currentRoomName || 'ยังไม่เลือกห้อง' }}
          </p>
        </div>
      </div>

      <button
        type="button"
        class="btn-ghost-ui mt-4 w-full"
        :disabled="isOpeningProfile"
        @click="openMyProfile"
      >
        <i class="bi bi-person-badge" aria-hidden="true"></i>
        {{ isOpeningProfile ? 'กำลังเปิดโปรไฟล์…' : 'ดูโปรไฟล์ของฉันในห้องนี้' }}
      </button>

      <p v-if="profileError" class="mt-3 rounded-control bg-warn-50 p-3 text-caption text-warn-800">
        {{ profileError }}
      </p>
    </section>

    <!-- กลุ่มเมนู -->
    <section v-for="group in MORE_NAV_GROUPS" :key="group.title" class="page-card overflow-hidden">
      <h2 class="px-5 pb-1 pt-4 text-caption font-bold text-ink-3">{{ group.title }}</h2>
      <nav :aria-label="group.title">
        <RouterLink
          v-for="item in group.items"
          :key="item.path"
          :to="item.path"
          class="flex min-h-12 items-center gap-3 border-t border-line px-5 py-3 transition-colors first:border-t-0 hover:bg-canvas"
          :class="isNavItemActive(item.path, $route.path) ? 'text-brand' : 'text-ink-1'"
        >
          <i
            :class="['bi', item.icon, 'w-5 shrink-0 text-lg text-ink-3']"
            aria-hidden="true"
          ></i>
          <span class="min-w-0 flex-1 truncate text-sm font-semibold">{{ item.name }}</span>
          <i class="bi bi-chevron-right text-xs text-ink-3" aria-hidden="true"></i>
        </RouterLink>
      </nav>
    </section>

    <!-- บัญชี -->
    <section class="page-card overflow-hidden">
      <h2 class="px-5 pb-1 pt-4 text-caption font-bold text-ink-3">บัญชี</h2>
      <button
        type="button"
        class="flex min-h-12 w-full items-center gap-3 border-t border-line px-5 py-3 text-left text-sm font-semibold text-danger-600 transition-colors hover:bg-danger-50"
        @click="isLogoutOpen = true"
      >
        <i class="bi bi-box-arrow-right w-5 shrink-0 text-lg" aria-hidden="true"></i>
        <span class="flex-1">ออกจากระบบ</span>
      </button>
    </section>

    <p class="text-center text-caption text-ink-3">SYNCROOM · {{ versionLabel }}</p>

    <AppSheet
      :open="isLogoutOpen"
      label="ยืนยันออกจากระบบ"
      title="ออกจากระบบ?"
      @close="isLogoutOpen = false"
    >
      <p class="text-sm text-ink-2">
        คุณจะกลับไปหน้าเลือกห้องในครั้งถัดไป และต้องเข้าสู่ระบบใหม่เพื่อใช้งาน
      </p>
      <div class="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" class="btn-ghost-ui" @click="isLogoutOpen = false">ยกเลิก</button>
        <button type="button" class="btn-danger" @click="confirmLogout">ออกจากระบบ</button>
      </div>
    </AppSheet>
  </div>
</template>
