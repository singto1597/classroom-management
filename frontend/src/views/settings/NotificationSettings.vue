<script setup lang="ts">
/**
 * 🔔 ตั้งค่าการแจ้งเตือน — อุปกรณ์นี้ · กลุ่มแจ้งเตือน · ช่วงงดรบกวน
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * สามชั้นที่ต้องแยกให้ชัด (ผู้ใช้สับสนกันบ่อย)
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **อุปกรณ์นี้** — เปิด/ปิด push ของเบราว์เซอร์เครื่องที่กำลังใช้
 *     (ผูกกับเครื่อง ไม่ใช่บัญชี — เครื่องอื่นไม่เปลี่ยนตาม)
 *  2. **กลุ่มแจ้งเตือน** — เลือกได้ว่าจะรับกลุ่มไหน ทาง in-app และ/หรือ push
 *     (ผูกกับบัญชี ใช้ทุกเครื่อง) · ประกาศปิดไม่ได้
 *  3. **ช่วงงดรบกวน** — ตั้งระดับห้อง (ผู้มีสิทธิ์) สมาชิกทุกคนอ่านได้
 *
 * ⚠️ `Notification.requestPermission()` และ `PushManager.subscribe()` ต้องเรียกจาก
 *    การคลิกของผู้ใช้ ⇒ สวิตช์อุปกรณ์จึงเป็น `<button>` ที่เรียกใน handler ตรง ๆ
 *    ไม่ใช่ `watch` ที่ยิงเองตอนโหลดหน้า
 */
import { computed, onMounted, ref } from 'vue';
import Swal from 'sweetalert2';
import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import QuietHoursCard from '@/components/settings/QuietHoursCard.vue';
import PushStatsCard from '@/components/settings/PushStatsCard.vue';
import { NotificationService } from '@/services/notification';
import {
  disablePush,
  enablePush,
  fetchPushConfig,
  getPermissionState,
  isSubscribedOnDevice,
  type PushConfig,
  type PushPermissionState,
  type PushToggleOutcome,
} from '@/services/push';
import { isServiceWorkerSupported } from '@/services/pwa';
import { useAuthStore } from '@/stores/auth';
import { useNotificationStore } from '@/stores/notifications';
import { UI_COLOR } from '@/constants/theme';
import { NOTIFICATION_GROUPS } from '@/constants/notificationGroups';
import type { MutableNotificationGroup, NotificationPreference } from '@/types/notification';

const authStore = useAuthStore();
const notificationStore = useNotificationStore();
const roomId = authStore.currentRoomId ?? 0;

// 🛡️ นิพจน์เดียวกับ backend (`require_permission(..., 'MANAGE_CLASSROOM_SETTINGS')`)
//    ⇒ ผู้ที่ไม่มีสิทธิ์จะไม่ได้ยิง endpoint ที่จะได้ 403 กลับมา
const canViewStats = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_SETTINGS'),
);

// ── ชั้นที่ 1: อุปกรณ์นี้ ───────────────────────────────────────────────────
const pushConfig = ref<PushConfig | null>(null);
const permission = ref<PushPermissionState>('unsupported');
const deviceSubscribed = ref(false);
const isPushLoading = ref(true);
const isPushBusy = ref(false);

const pushSupported = computed(() => isServiceWorkerSupported() && permission.value !== 'unsupported');
const pushReady = computed(() => pushConfig.value?.enabled === true && !!pushConfig.value.public_key);

const loadDevicePush = async () => {
  isPushLoading.value = true;
  permission.value = getPermissionState();
  try {
    pushConfig.value = await fetchPushConfig(roomId);
  } catch {
    // ผู้ดูแลยังไม่ตั้งคีย์ หรือ endpoint ล่ม — ถือว่า "ยังใช้ไม่ได้" ไม่ใช่ error ทั้งหน้า
    pushConfig.value = { public_key: '', enabled: false };
  }
  try {
    deviceSubscribed.value = await isSubscribedOnDevice();
  } catch {
    deviceSubscribed.value = false;
  } finally {
    isPushLoading.value = false;
  }
};

onMounted(loadDevicePush);

const OUTCOME_MESSAGES: Record<PushToggleOutcome, { icon: 'success' | 'error' | 'info' | 'warning'; title: string; text: string }> = {
  subscribed: {
    icon: 'success',
    title: 'เปิดการแจ้งเตือนบนเครื่องนี้แล้ว',
    text: 'เมื่อปิดแอปไว้ก็ยังได้รับแจ้งเตือนตามกลุ่มที่เลือกไว้',
  },
  unsubscribed: {
    icon: 'success',
    title: 'ปิดการแจ้งเตือนบนเครื่องนี้แล้ว',
    text: 'เครื่องนี้จะไม่ได้รับ push อีก — เครื่องอื่นยังได้รับตามเดิม',
  },
  unsupported: {
    icon: 'warning',
    title: 'เครื่องนี้ยังเปิดไม่ได้',
    text: 'เบราว์เซอร์หรือการตั้งค่าอุปกรณ์ไม่รองรับการแจ้งเตือนแบบ push',
  },
  denied: {
    icon: 'warning',
    title: 'เบราว์เซอร์ถูกตั้งค่าให้บล็อก',
    text: 'ต้องเปิดสิทธิ์การแจ้งเตือนของเว็บนี้ในตั้งค่าเบราว์เซอร์ก่อน แล้วกลับมาลองอีกครั้ง',
  },
  not_configured: {
    icon: 'info',
    title: 'ผู้ดูแลยังไม่ได้เปิดระบบ push',
    text: 'ยังใช้การแจ้งเตือนในแอปได้ตามปกติ — แจ้งผู้ดูแลห้องเพื่อเปิดคีย์ VAPID',
  },
  error: {
    icon: 'error',
    title: 'ทำรายการไม่สำเร็จ',
    text: 'เกิดข้อผิดพลาดระหว่างติดต่อเซิร์ฟเวอร์ โปรดลองอีกครั้ง',
  },
};

const toggleDevicePush = async () => {
  if (isPushBusy.value) return;
  isPushBusy.value = true;
  try {
    const outcome = deviceSubscribed.value ? await disablePush(roomId) : await enablePush(roomId);
    deviceSubscribed.value = await isSubscribedOnDevice();
    permission.value = getPermissionState();

    // เลิกสมัครสำเร็จ = ไม่ต้องกวนด้วยกล่องข้อความ (ผู้ใช้เพิ่งสั่งให้ปิด)
    if (outcome === 'unsubscribed') return;
    const message = OUTCOME_MESSAGES[outcome];
    await Swal.fire({
      icon: message.icon,
      title: message.title,
      text: message.text,
      confirmButtonColor: UI_COLOR.brand,
    });
  } finally {
    isPushBusy.value = false;
  }
};

// ── ชั้นที่ 2: กลุ่มแจ้งเตือน ───────────────────────────────────────────────
const preferences = ref<NotificationPreference[]>([]);
const isPreferencesLoading = ref(true);
const preferencesError = ref<string | null>(null);
/** id ของกลุ่มที่กำลังบันทึก — กันกดรัว/กดหลายกลุ่มพร้อมกันสลับค่า */
const savingGroup = ref<MutableNotificationGroup | null>(null);

const findPreference = (group: MutableNotificationGroup): NotificationPreference | undefined =>
  preferences.value.find((item) => item.group_type === group);

const loadPreferences = async () => {
  isPreferencesLoading.value = true;
  preferencesError.value = null;
  try {
    const response = await NotificationService.getPreferences(roomId);
    preferences.value = response.items;
  } catch (error) {
    preferencesError.value =
      error instanceof Error && error.message ? error.message : 'โหลดการตั้งค่าไม่สำเร็จ';
  } finally {
    isPreferencesLoading.value = false;
  }
};

onMounted(loadPreferences);

const updatePreference = async (
  group: MutableNotificationGroup,
  patch: Partial<Pick<NotificationPreference, 'inapp' | 'push'>>,
) => {
  const current = findPreference(group);
  if (!current || savingGroup.value !== null) return;

  const next: NotificationPreference = {
    group_type: group,
    inapp: patch.inapp ?? current.inapp,
    push: patch.push ?? current.push,
  };

  // อัปเดตจอก่อนเพื่อให้สวิตช์ตอบสนองทันที แล้วคืนค่าจริงถ้า API ล้ม
  savingGroup.value = group;
  const previous = current;
  const original = { inapp: current.inapp, push: current.push };
  Object.assign(previous, next);

  try {
    const saved = await NotificationService.setPreference(roomId, next);
    Object.assign(previous, saved);
    // ตัวเลขกระดิ่งอาจเปลี่ยนถ้าปิด in-app — ดึงใหม่เงียบ ๆ
    void notificationStore.load({ silent: true });
  } catch (error) {
    // คืนค่าที่เห็นบนจอ แล้วดึงความจริงจากเซิร์ฟเวอร์ทับอีกชั้น
    Object.assign(previous, original);
    await loadPreferences();
    await Swal.fire({
      icon: 'error',
      title: 'บันทึกการตั้งค่าไม่สำเร็จ',
      text: error instanceof Error ? error.message : 'เกิดข้อผิดพลาดจากระบบ โปรดลองใหม่',
      confirmButtonColor: UI_COLOR.brand,
    });
  } finally {
    savingGroup.value = null;
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="เลือกว่าจะให้แจ้งอะไร ทางไหน และช่วงเวลาไหน — ตั้งค่าแยกตามอุปกรณ์และตามบัญชี"
    />

    <!-- ชั้นที่ 1: อุปกรณ์นี้ -->
    <section class="page-card p-4 sm:p-6">
      <div class="flex items-start gap-3 border-b border-stone-100 pb-3 sm:pb-4">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
        >
          <i class="bi bi-phone-fill text-base" aria-hidden="true"></i>
        </div>
        <div class="min-w-0">
          <h2 class="section-title">การแจ้งเตือนบนเครื่องนี้</h2>
          <p class="mt-0.5 text-xs leading-relaxed text-stone-500">
            ผูกกับเบราว์เซอร์ที่กำลังใช้ — เครื่องอื่นต้องเปิดแยก
          </p>
        </div>
      </div>

      <SkeletonRows v-if="isPushLoading" :rows="1" height="h-14" />

      <div v-else class="mt-3 flex flex-wrap items-center justify-between gap-3 sm:mt-4">
        <div class="min-w-0 flex-1">
          <p class="text-sm font-bold text-stone-800">
            <template v-if="!pushSupported">เบราว์เซอร์นี้ไม่รองรับการแจ้งเตือน</template>
            <template v-else-if="!pushReady">ยังไม่พร้อมใช้งาน</template>
            <template v-else-if="permission === 'denied'">ถูกบล็อกในตั้งค่าเบราว์เซอร์</template>
            <template v-else-if="deviceSubscribed">เปิดอยู่บนเครื่องนี้</template>
            <template v-else>ปิดอยู่บนเครื่องนี้</template>
          </p>
          <p class="mt-0.5 text-xs leading-relaxed text-stone-500">
            <template v-if="!pushSupported">
              ยังใช้การแจ้งเตือนในแอปได้ตามปกติ
            </template>
            <template v-else-if="!pushReady">
              ผู้ดูแลห้องยังไม่ได้ตั้งค่าคีย์สำหรับส่งการแจ้งเตือน
            </template>
            <template v-else-if="permission === 'denied'">
              เปิดสิทธิ์ "การแจ้งเตือน" ให้เว็บนี้ในตั้งค่าเบราว์เซอร์ก่อน
            </template>
            <template v-else>
              รับแจ้งเตือนได้แม้ปิดแอปไว้ — ตามกลุ่มที่เลือกด้านล่าง
            </template>
          </p>
        </div>

        <button
          v-if="pushSupported && pushReady && permission !== 'denied'"
          type="button"
          role="switch"
          :aria-checked="deviceSubscribed"
          aria-label="การแจ้งเตือนบนเครื่องนี้"
          class="flex h-11 shrink-0 items-center gap-2 rounded-full border px-3 transition-colors disabled:opacity-60"
          :class="deviceSubscribed ? 'border-brand-200 bg-brand-50' : 'border-stone-200 bg-stone-50'"
          :disabled="isPushBusy"
          @click="toggleDevicePush"
        >
          <span
            class="relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors"
            :class="deviceSubscribed ? 'bg-brand-700' : 'bg-stone-300'"
            aria-hidden="true"
          >
            <span
              class="inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform"
              :class="deviceSubscribed ? 'translate-x-[22px]' : 'translate-x-0.5'"
            ></span>
          </span>
          <span class="text-xs font-bold text-stone-700">
            {{ isPushBusy ? 'กำลังทำ…' : deviceSubscribed ? 'เปิด' : 'ปิด' }}
          </span>
        </button>
      </div>
    </section>

    <!-- ชั้นที่ 2: กลุ่มแจ้งเตือน -->
    <section class="page-card p-4 sm:p-6">
      <div class="flex items-start gap-3 border-b border-stone-100 pb-3 sm:pb-4">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
        >
          <i class="bi bi-sliders2 text-base" aria-hidden="true"></i>
        </div>
        <div class="min-w-0">
          <h2 class="section-title">กลุ่มแจ้งเตือน</h2>
          <p class="mt-0.5 text-xs leading-relaxed text-stone-500">
            ตั้งตามบัญชี — ใช้กับทุกเครื่องที่ล็อกอินด้วยบัญชีนี้
          </p>
        </div>
      </div>

      <SkeletonRows v-if="isPreferencesLoading" :rows="4" height="h-16" />

      <StateBlock
        v-else-if="preferencesError"
        variant="error"
        title="โหลดการตั้งค่าไม่สำเร็จ"
        :hint="preferencesError"
        @retry="loadPreferences"
      />

      <ul v-else class="mt-3 divide-y divide-stone-100 sm:mt-4">
        <li
          v-for="group in NOTIFICATION_GROUPS"
          :key="group.group"
          class="py-3 first:pt-0 last:pb-0"
        >
          <div class="flex items-start gap-3">
            <span
              class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-600"
              aria-hidden="true"
            >
              <i :class="['bi', group.icon, 'text-base']"></i>
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-bold text-stone-800">{{ group.label }}</p>
              <p class="mt-0.5 text-xs leading-relaxed text-stone-500">{{ group.hint }}</p>

              <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
                <label class="flex min-h-11 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    class="h-4 w-4 accent-brand-700"
                    :checked="findPreference(group.group)?.inapp ?? true"
                    :disabled="savingGroup !== null || !findPreference(group.group)"
                    @change="
                      updatePreference(group.group, {
                        inapp: ($event.target as HTMLInputElement).checked,
                      })
                    "
                  />
                  <span class="text-xs font-bold text-stone-700">ในแอป</span>
                </label>
                <label class="flex min-h-11 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    class="h-4 w-4 accent-brand-700"
                    :checked="findPreference(group.group)?.push ?? true"
                    :disabled="savingGroup !== null || !findPreference(group.group)"
                    @change="
                      updatePreference(group.group, {
                        push: ($event.target as HTMLInputElement).checked,
                      })
                    "
                  />
                  <span class="text-xs font-bold text-stone-700">บนมือถือ (push)</span>
                </label>
              </div>
            </div>
          </div>
        </li>

        <!-- ประกาศปิดไม่ได้ — ช่องทางราชการของห้อง -->
        <li class="py-3 last:pb-0">
          <div class="flex items-start gap-3">
            <span
              class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-600"
              aria-hidden="true"
            >
              <i class="bi bi-megaphone text-base"></i>
            </span>
            <div class="min-w-0 flex-1">
              <p class="flex items-center gap-1.5 text-sm font-bold text-stone-800">
                ประกาศ
                <i class="bi bi-lock-fill text-xs text-stone-400" aria-hidden="true"></i>
              </p>
              <p class="mt-0.5 text-xs leading-relaxed text-stone-500">
                ประกาศของห้องเป็นช่องทางราชการ — ปิดไม่ได้ แต่ประกาศ "ด่วน" ยังทะลุช่วงงดรบกวนเสมอ
              </p>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <!-- ชั้นที่ 3: ช่วงงดรบกวน -->
    <QuietHoursCard />

    <!-- ชั้นที่ 4: สถิติการส่ง (ผู้ดูแลเท่านั้น — ซ่อนด้วย v-if ไม่ใช่ CSS) -->
    <PushStatsCard v-if="canViewStats" />
  </div>
</template>
