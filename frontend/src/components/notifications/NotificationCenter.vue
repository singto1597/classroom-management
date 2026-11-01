<script setup lang="ts">
/**
 * 🔔 NotificationCenter — แผ่นรายการแจ้งเตือนของห้องที่กำลังเปิด
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **แสดงครบ 4 สถานะ**: กำลังโหลด · ผิดพลาด · ว่างจริง · ยังไม่เคยถาม
 *     (`hasLoaded` ใน store) — ห้ามใช้ `items.length === 0` แทนทุกกรณี
 *  2. **กดแถว = อ่านแล้ว + พาไปตาม `url`** ที่ backend ให้มา และ `url` ต้องผ่าน
 *     `safeRedirect()` ก่อนเสมอ — ค่าใน DB เป็นข้อมูลที่ระบบอื่นอาจเขียนได้
 *  3. **ไม่ซ่อนของที่อ่านแล้ว** — รายการคือประวัติ ไม่ใช่กล่องจดหมาย
 *     (ตัวเลขบนกระดิ่งต่างหากที่ลดลง)
 *  4. ปุ่ม "อ่านทั้งหมด" แสดงเฉพาะเมื่อมีของยังไม่อ่าน — ไม่มีของ = ไม่มีปุ่มหลอก
 *
 * ⚠️ ใช้ `AppSheet` (Teleport ไป body) ไม่ใช่ modal ในหน้า — z-index ต้องชนะ layout
 */
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import AppSheet from '@/components/ui/AppSheet.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppEmptyState from '@/components/ui/AppEmptyState.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import { useNotificationStore } from '@/stores/notifications';
import { safeRedirect } from '@/router/redirect';
import { formatThaiDateTime } from '@/utils/datetime';
import {
  NOTIFICATION_GROUP_ICONS,
  NOTIFICATION_GROUP_LABELS,
  PRIORITY_BADGE_CLASSES,
  PRIORITY_LABELS,
} from '@/constants/notificationGroups';
import type { NotificationItem } from '@/types/notification';

defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const store = useNotificationStore();
const router = useRouter();

const showLoading = computed(() => store.isLoading && !store.hasLoaded);
const showError = computed(() => !showLoading.value && store.error !== null && !store.hasLoaded);
const showEmpty = computed(
  () => !showLoading.value && !showError.value && store.hasLoaded && store.items.length === 0,
);

/** เปิดแถว: ทำเครื่องหมายอ่าน (ไม่รอ) แล้วพาไปปลายทางที่ปลอดภัย */
const openItem = (item: NotificationItem) => {
  if (!item.read_at) void store.markRead(item.id);

  const target = safeRedirect(item.url);
  if (target) {
    emit('close');
    void router.push(target);
  }
};

const onSheetClose = () => emit('close');
</script>

<template>
  <AppSheet :open="open" label="การแจ้งเตือน" @close="onSheetClose">
    <template #header>
      <div class="flex shrink-0 items-center justify-between gap-2 px-4 pb-3 pt-3">
        <div class="flex min-w-0 items-center gap-2">
          <h2 class="font-display text-lg font-bold text-stone-900">การแจ้งเตือน</h2>
          <span
            v-if="store.unreadCount > 0"
            class="rounded-full bg-danger-100 px-2 py-0.5 text-[11px] font-bold text-danger-800"
          >
            ยังไม่อ่าน {{ store.unreadCount }}
          </span>
        </div>

        <div class="flex shrink-0 items-center gap-1">
          <button
            v-if="store.unreadCount > 0"
            type="button"
            class="min-h-11 rounded-lg px-2.5 text-xs font-bold text-brand-700 transition-colors hover:bg-brand-50"
            @click="store.markAllRead()"
          >
            อ่านทั้งหมด
          </button>
          <button
            type="button"
            class="flex h-11 w-11 items-center justify-center rounded-xl text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-800"
            aria-label="ปิดการแจ้งเตือน"
            @click="onSheetClose"
          >
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>
      </div>
    </template>

    <!-- สถานะ 1: กำลังโหลดรอบแรก -->
    <SkeletonRows v-if="showLoading" :rows="4" height="h-16" />

    <!-- สถานะ 2: ผิดพลาดและยังไม่เคยได้ข้อมูล -->
    <StateBlock
      v-else-if="showError"
      variant="error"
      title="โหลดการแจ้งเตือนไม่สำเร็จ"
      :hint="store.error ?? undefined"
      @retry="store.load()"
    />

    <!-- สถานะ 3: ว่างจริง (โหลดแล้ว ไม่มีของ) -->
    <AppEmptyState
      v-else-if="showEmpty"
      icon="bi-bell-slash"
      title="ยังไม่มีการแจ้งเตือน"
      hint="เมื่อมีงานใหม่ ประกาศ หรือความเคลื่อนไหวของห้อง จะขึ้นที่นี่"
    />

    <!-- สถานะ 4: มีของ -->
    <div v-else class="space-y-2 pb-2">
      <!-- ผิดพลาดระหว่างรีเฟรช: เตือนเบา ๆ ไม่ทับของเดิม -->
      <p
        v-if="store.error"
        class="rounded-xl border border-danger-200 bg-danger-50 px-3 py-2 text-xs font-bold text-danger-800"
        role="status"
      >
        อัปเดตล่าสุดไม่สำเร็จ — ข้อมูลที่เห็นอาจไม่ใช่ล่าสุด
      </p>

      <ul class="space-y-2" aria-label="รายการแจ้งเตือน">
        <li v-for="item in store.items" :key="item.id">
          <button
            type="button"
            class="flex w-full items-start gap-3 rounded-2xl border p-3.5 text-left transition-colors active:scale-[0.99]"
            :class="
              item.read_at
                ? 'border-stone-200 bg-white hover:bg-stone-50'
                : 'border-brand-200 bg-brand-50/70 hover:bg-brand-50'
            "
            @click="openItem(item)"
          >
            <span
              class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
              :class="item.read_at ? 'bg-stone-100 text-stone-500' : 'bg-brand-100 text-brand-700'"
              aria-hidden="true"
            >
              <i :class="['bi', NOTIFICATION_GROUP_ICONS[item.group_type], 'text-base']"></i>
            </span>

            <span class="min-w-0 flex-1">
              <span class="flex flex-wrap items-center gap-1.5">
                <span class="text-[10px] font-bold text-stone-500">
                  {{ NOTIFICATION_GROUP_LABELS[item.group_type] }}
                </span>
                <span
                  v-if="item.priority !== 'normal'"
                  class="rounded-full px-1.5 py-0.5 text-[10px] font-bold"
                  :class="PRIORITY_BADGE_CLASSES[item.priority]"
                >
                  {{ PRIORITY_LABELS[item.priority] }}
                </span>
                <span
                  v-if="!item.read_at"
                  class="inline-flex items-center gap-1 text-[10px] font-bold text-brand-700"
                >
                  <span class="h-1.5 w-1.5 rounded-full bg-brand-600" aria-hidden="true"></span>
                  ใหม่
                </span>
              </span>

              <span class="mt-0.5 block break-words text-sm font-bold text-stone-900">
                {{ item.title }}
              </span>
              <span
                v-if="item.body"
                class="mt-0.5 line-clamp-2 block break-words text-xs leading-relaxed text-stone-600"
              >
                {{ item.body }}
              </span>
              <span class="mt-1 block text-[11px] font-bold text-stone-400">
                {{ formatThaiDateTime(item.created_at) }}
              </span>
            </span>
          </button>
        </li>
      </ul>

      <AppButton
        v-if="store.hasMore"
        variant="secondary"
        block
        :loading="store.isLoading"
        @click="store.loadMore()"
      >
        <i class="bi bi-chevron-down" aria-hidden="true"></i>
        โหลดเพิ่มเติม
      </AppButton>
    </div>
  </AppSheet>
</template>
