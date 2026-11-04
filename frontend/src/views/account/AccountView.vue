<script setup lang="ts">
/**
 * 👤 บัญชีส่วนกลาง (`/account`)
 *
 * ย้ายงานจัดการบัญชีออกจาก dropdown บน header เดิม ⇒ หน้าสำหรับ **บัญชีระดับระบบ**
 * ไม่ผูกกับห้องใดห้องหนึ่ง: ข้อมูลส่วนตัวใช้ร่วมทุกห้อง, การเชื่อมต่อ Google/Discord
 * ผูกกับผู้ใช้ ไม่ใช่สมาชิกภาพในห้อง และออกจากระบบได้แม้ยังไม่เลือกห้อง
 *
 * ข้อมูลโปรไฟล์ดึงจาก `getMyProfile()` (global) ไม่ใช่ตัว store เพราะ store เก็บ
 * เฉพาะฟิลด์ที่ใช้บ่อย — birthday/line/ที่อยู่จะหายถ้าพึ่ง store
 */
defineOptions({ name: 'AccountView' });

import { computed, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import {
  getDiscordLinkUrl,
  getGoogleLinkUrl,
  getMyProfile,
  type UserProfileResponse,
} from '@/services/auth';
import { OAUTH_LINK_RETURN_KEY } from '@/constants/storageKeys';
import { avatarInitial } from '@/utils/avatar';
import { formatThaiDate } from '@/utils/datetime';
import AppSheet from '@/components/ui/AppSheet.vue';
import PageIntro from '@/components/ui/PageIntro.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';

const authStore = useAuthStore();

const profile = ref<UserProfileResponse | null>(null);
const isLoading = ref(true);
const hasError = ref(false);
const isLogoutOpen = ref(false);

const loadProfile = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    profile.value = await getMyProfile();
  } catch (error: unknown) {
    console.error('Failed to load account profile:', error);
    hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

onMounted(() => void loadProfile());

/** ค่าที่ backend เก็บเป็น NULL/null-string ต้องไม่โผล่คำว่า "null" บนหน้าจอ */
const clean = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined) return '—';
  const text = String(value).trim();
  return text && text !== 'null' ? text : '—';
};

const avatarChar = computed(() =>
  avatarInitial(
    profile.value?.nickname || profile.value?.first_name || profile.value?.first_name_en,
    'ส',
  ),
);

const fullName = computed(() => {
  const p = profile.value;
  if (!p) return 'ผู้ใช้งานระบบ';
  const thai = `${p.prefix ?? ''}${p.first_name ?? ''} ${p.last_name ?? ''}`.trim();
  if (thai) return thai;
  const english = `${p.first_name_en ?? ''} ${p.last_name_en ?? ''}`.trim();
  return english || 'ผู้ใช้งานระบบ';
});

const englishName = computed(() => {
  const p = profile.value;
  if (!p) return '—';
  return `${p.first_name_en ?? ''} ${p.last_name_en ?? ''}`.trim() || '—';
});

const addressText = computed(() => {
  const p = profile.value;
  if (!p) return '—';
  const parts = [
    p.address_house_no,
    p.address_road,
    p.address_sub_district,
    p.address_district,
    p.address_province,
    p.address_post_code,
  ].filter((part): part is string => !!part && part !== 'null');
  return parts.length ? parts.join(' ') : '—';
});

const detailRows = computed(() => {
  const p = profile.value;
  if (!p) return [];
  return [
    { label: 'ชื่อ-นามสกุล', value: fullName.value },
    { label: 'ชื่อภาษาอังกฤษ', value: englishName.value },
    { label: 'ชื่อเล่น', value: clean(p.nickname) },
    { label: 'วันเกิด', value: p.birthday ? formatThaiDate(p.birthday, 'long') : '—' },
    { label: 'เบอร์โทรศัพท์', value: clean(p.phone_number) },
    { label: 'Line ID', value: clean(p.line_id) },
    { label: 'ที่อยู่', value: addressText.value },
  ];
});

/**
 * 🔗 เริ่มผูกบัญชี — จำหน้าที่จะกลับมาไว้ใน sessionStorage
 * (callback ฝั่ง OAuth อ่านคีย์นี้แล้วพากลับ `/account` แทน `/dashboard`)
 */
const startLink = (href: string) => {
  sessionStorage.setItem(OAUTH_LINK_RETURN_KEY, '/account');
  window.location.href = href;
};

const connectedAccounts = computed(() => {
  const p = profile.value;
  return [
    {
      key: 'google',
      label: 'Google',
      icon: 'bi-google',
      linked: !!p?.google_id,
      href: getGoogleLinkUrl(),
    },
    {
      key: 'discord',
      label: 'Discord',
      icon: 'bi-discord',
      linked: !!p?.discord_id,
      href: getDiscordLinkUrl(),
    },
  ];
});

const confirmLogout = () => {
  isLogoutOpen.value = false;
  authStore.logout();
};
</script>

<template>
  <div class="space-y-4">
    <PageIntro
      description="ข้อมูลบัญชีใช้ร่วมทุกห้องเรียน — แก้ไขแล้วมีผลกับการยืนยันตัวตนในทุกห้องที่คุณเป็นสมาชิก"
    />

    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดข้อมูลบัญชีไม่สำเร็จ"
      hint="ตรวจสอบการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
      @retry="loadProfile"
    />

    <template v-else>
      <!-- ── ตัวตนของบัญชี ─────────────────────────────────────────── -->
      <section class="page-card p-5">
        <div class="flex items-center gap-4">
          <div
            class="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-tint text-xl font-bold text-brand"
          >
            {{ avatarChar }}
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-title-m font-bold text-ink-1">{{ fullName }}</p>
            <p class="mt-0.5 truncate text-caption text-ink-3">
              {{ clean(profile?.email) }}
            </p>
          </div>
        </div>

        <RouterLink to="/account/profile" class="btn-ghost-ui mt-4 w-full">
          <i class="bi bi-pencil-square" aria-hidden="true"></i>
          แก้ไขข้อมูลส่วนตัว
        </RouterLink>
      </section>

      <!-- ── ข้อมูลส่วนตัว ────────────────────────────────────────── -->
      <section class="page-card overflow-hidden">
        <h2 class="px-5 pb-1 pt-4 text-caption font-bold text-ink-3">ข้อมูลส่วนตัว</h2>
        <dl class="divide-y divide-line">
          <div
            v-for="row in detailRows"
            :key="row.label"
            class="flex flex-col gap-0.5 px-5 py-3 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6"
          >
            <dt class="shrink-0 text-sm font-medium text-ink-3">{{ row.label }}</dt>
            <dd class="min-w-0 break-words text-sm font-semibold text-ink-1 sm:text-right">
              {{ row.value }}
            </dd>
          </div>
        </dl>
      </section>

      <!-- ── บัญชีที่เชื่อมต่อ ────────────────────────────────────── -->
      <section class="page-card overflow-hidden">
        <div class="px-5 pb-1 pt-4">
          <h2 class="text-caption font-bold text-ink-3">บัญชีที่เชื่อมต่อ</h2>
          <p class="mt-1 text-caption leading-relaxed text-ink-3">
            ผูกผู้ให้บริการเข้าด้วยกันเพื่อให้เข้าสู่ระบบได้ทุกช่องทาง
          </p>
        </div>

        <div
          v-for="account in connectedAccounts"
          :key="account.key"
          class="flex items-center gap-3 border-t border-line px-5 py-3.5"
        >
          <span
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-canvas text-ink-2"
          >
            <i :class="['bi', account.icon, 'text-lg']" aria-hidden="true"></i>
          </span>

          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-semibold text-ink-1">{{ account.label }}</p>
            <p
              class="mt-0.5 text-caption font-medium"
              :class="account.linked ? 'text-ok-700' : 'text-ink-3'"
            >
              {{ account.linked ? 'เชื่อมต่อแล้ว' : 'ยังไม่ได้เชื่อมต่อ' }}
            </p>
          </div>

          <span
            v-if="account.linked"
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ok-50 text-ok-700"
            aria-label="เชื่อมต่อแล้ว"
          >
            <i class="bi bi-check-lg text-sm" aria-hidden="true"></i>
          </span>
          <button
            v-else
            type="button"
            class="btn-ghost-ui h-9 shrink-0 px-3 text-xs"
            @click="startLink(account.href)"
          >
            ผูกบัญชี
          </button>
        </div>
      </section>

      <!-- ── เซสชัน ───────────────────────────────────────────────── -->
      <section class="page-card overflow-hidden">
        <h2 class="px-5 pb-1 pt-4 text-caption font-bold text-ink-3">เซสชัน</h2>
        <button
          type="button"
          class="flex min-h-12 w-full items-center gap-3 border-t border-line px-5 py-3 text-left text-sm font-semibold text-danger-600 transition-colors hover:bg-danger-50"
          @click="isLogoutOpen = true"
        >
          <i class="bi bi-box-arrow-right w-5 shrink-0 text-lg" aria-hidden="true"></i>
          <span class="flex-1">ออกจากระบบ</span>
        </button>
      </section>

      <p class="pt-1 text-center text-caption text-ink-3">
        <RouterLink to="/lobby" class="font-semibold text-ink-2 hover:text-brand">
          กลับไปเลือกห้องเรียน
        </RouterLink>
      </p>
    </template>

    <AppSheet
      :open="isLogoutOpen"
      label="ยืนยันออกจากระบบ"
      title="ออกจากระบบ?"
      @close="isLogoutOpen = false"
    >
      <p class="text-sm leading-relaxed text-ink-2">
        คุณจะต้องเข้าสู่ระบบใหม่เพื่อใช้งาน และห้องที่เปิดอยู่จะถูกปิดในแท็บนี้
      </p>
      <div class="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" class="btn-ghost-ui" @click="isLogoutOpen = false">ยกเลิก</button>
        <button type="button" class="btn-danger" @click="confirmLogout">ออกจากระบบ</button>
      </div>
    </AppSheet>
  </div>
</template>
