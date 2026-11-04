<script setup lang="ts">
/**
 * 📢 รายการประกาศของห้อง — ปลายทางของกระดิ่ง (deep link `/announcements`)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **ปักหมุดอยู่คนละลิสต์** (`pinned`) ตามสัญญาของ backend — หน้าถัดไปส่ง
 *     `pinned` เป็นลิสต์ว่าง จึงต้องแสดงส่วนปักหมุดเฉพาะหน้าแรก ไม่ใช่ซ้ำทุกหน้า
 *  2. **เก็บถาวรไม่ใช่การลบ** — ยังเปิดดูได้ด้วยสวิตช์ "รวมที่เก็บถาวรแล้ว"
 *     และต้องมีป้ายบอก ไม่ใช่ซ่อนจนเหมือนหาย
 *  3. ผู้ที่ไม่มีสิทธิ์ส่งประกาศยังต้องอ่านได้ — ปุ่มสร้างแสดงเฉพาะผู้มีสิทธิ์
 *  4. กดแถว = ไปหน้ารายละเอียด (ที่นั่นเป็นตัวทำเครื่องหมายว่าอ่านแล้ว)
 */
import { computed, onMounted, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import PageIntro from '@/components/ui/PageIntro.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppEmptyState from '@/components/ui/AppEmptyState.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import { AnnouncementService } from '@/services/announcement';
import { useAuthStore } from '@/stores/auth';
import { useNotificationStore } from '@/stores/notifications';
import { formatThaiDateTime } from '@/utils/datetime';
import { PRIORITY_BADGE_CLASSES, PRIORITY_LABELS } from '@/constants/notificationGroups';
import type { AnnouncementItem } from '@/types/announcement';

/** ตรงกับ DEFAULT_PAGE_SIZE ฝั่ง backend */
const PAGE_SIZE = 20;

const authStore = useAuthStore();
const notificationStore = useNotificationStore();
const route = useRoute();
const roomId = authStore.currentRoomId ?? 0;

const canSend = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_SETTINGS'),
);

const pinned = ref<AnnouncementItem[]>([]);
const items = ref<AnnouncementItem[]>([]);
const hasMore = ref(false);
const isLoading = ref(true);
const isLoadingMore = ref(false);
const hasLoaded = ref(false);
const error = ref<string | null>(null);
const includeArchived = ref(false);

/**
 * 🔵 "ยังไม่อ่านเท่านั้น" — ปลายทางของการ์ด "ประกาศยังไม่อ่าน" บนหน้าหลัก
 *
 * ตัวกรองนี้ **ต้องกรองที่ backend** (ไม่ใช่ซ่อนแถวที่โหลดมา) เพราะรายการแบ่งหน้า:
 * ซ่อนฝั่งหน้าจะได้หน้าแรกที่เหลือ 2 ใบทั้งที่ยังมีอีก 10 ใบรออยู่หน้า 2
 * ⇒ ตัวเลขบนการ์ดกับจำนวนที่เห็นจะไม่ตรงกัน (กฎ "34 กดแล้วเจอ 5")
 */
const unreadOnly = ref(route.query.unread === '1');

/** กดการ์ดหน้าหลักซ้ำระหว่างอยู่หน้านี้ — query เปลี่ยนแต่ component ไม่ remount */
watch(
  () => route.query.unread,
  (value) => {
    unreadOnly.value = value === '1';
  },
);

let seq = 0;

const messageOf = (err: unknown): string =>
  err instanceof Error && err.message ? err.message : 'โหลดประกาศไม่สำเร็จ';

const load = async () => {
  const mySeq = ++seq;
  isLoading.value = true;
  error.value = null;
  try {
    const response = await AnnouncementService.list(roomId, {
      limit: PAGE_SIZE,
      include_archived: includeArchived.value,
      unread_only: unreadOnly.value,
    });
    if (mySeq !== seq) return;
    pinned.value = response.pinned;
    items.value = response.items;
    hasMore.value = response.has_more;
    hasLoaded.value = true;
  } catch (err) {
    if (mySeq !== seq) return;
    error.value = messageOf(err);
  } finally {
    if (mySeq === seq) isLoading.value = false;
  }
};

onMounted(load);

// เปลี่ยนตัวกรอง = โหลดใหม่ทั้งชุด (ไม่ patch รายการเดิม เพราะการเก็บถาวรเปลี่ยนชุดข้อมูล)
watch([includeArchived, unreadOnly], () => {
  pinned.value = [];
  items.value = [];
  hasMore.value = false;
  hasLoaded.value = false;
  void load();
});

const loadMore = async () => {
  const last = items.value[items.value.length - 1];
  if (!last || !hasMore.value || isLoadingMore.value) return;

  const mySeq = seq;
  isLoadingMore.value = true;
  try {
    const response = await AnnouncementService.list(roomId, {
      limit: PAGE_SIZE,
      before_id: last.id,
      include_archived: includeArchived.value,
    });
    if (mySeq !== seq) return;
    const seen = new Set(items.value.map((item) => item.id));
    items.value = [...items.value, ...response.items.filter((item) => !seen.has(item.id))];
    hasMore.value = response.has_more;
  } catch (err) {
    if (mySeq === seq) error.value = messageOf(err);
  } finally {
    if (mySeq === seq) isLoadingMore.value = false;
  }
};

/** ป้ายเล็ก ๆ ที่แถวใช้ร่วมกัน — ลดการเขียนซ้ำใน template */
const badgeFor = (item: AnnouncementItem) => ({
  priority: item.priority !== 'normal' ? PRIORITY_LABELS[item.priority] : null,
  priorityClass: PRIORITY_BADGE_CLASSES[item.priority],
});

/** เปิดรายละเอียดแล้วตัวเลขกระดิ่งต้องขยับ — หน้ารายละเอียดอัปเดต store ให้เอง */
const refreshUnread = () => {
  void notificationStore.load({ silent: true });
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="ประกาศของห้อง — ยังไม่อ่านจะขึ้นป้าย ใหม่"
    >
      <template #actions>
        <AppButton v-if="canSend" variant="primary" to="/messages">
          <i class="bi bi-megaphone-fill" aria-hidden="true"></i>
          ส่งประกาศ
        </AppButton>
      </template>
    </PageIntro>

    <div class="flex flex-wrap items-center gap-2">
      <label
        class="flex min-h-11 w-fit cursor-pointer items-center gap-2.5 rounded-xl border border-stone-200 bg-white px-3"
      >
        <input v-model="unreadOnly" type="checkbox" class="h-4 w-4 accent-brand-700" />
        <span class="text-xs font-bold text-stone-700">ยังไม่อ่านเท่านั้น</span>
      </label>

      <label
        class="flex min-h-11 w-fit cursor-pointer items-center gap-2.5 rounded-xl border border-stone-200 bg-white px-3"
      >
        <input v-model="includeArchived" type="checkbox" class="h-4 w-4 accent-brand-700" />
        <span class="text-xs font-bold text-stone-700">รวมที่เก็บถาวรแล้ว</span>
      </label>
    </div>

    <SkeletonRows v-if="isLoading && !hasLoaded" :rows="4" height="h-20" />

    <StateBlock
      v-else-if="error && !hasLoaded"
      variant="error"
      title="โหลดประกาศไม่สำเร็จ"
      :hint="error"
      @retry="load"
    />

    <AppEmptyState
      v-else-if="hasLoaded && pinned.length === 0 && items.length === 0"
      icon="bi-megaphone"
      :title="
        unreadOnly
          ? 'อ่านครบทุกประกาศแล้ว'
          : includeArchived
            ? 'ยังไม่มีประกาศ'
            : 'ยังไม่มีประกาศของห้องนี้'
      "
      :hint="
        unreadOnly
          ? 'ปิดตัวกรอง &quot;ยังไม่อ่านเท่านั้น&quot; เพื่อดูประกาศเก่าที่อ่านแล้ว'
          : includeArchived
            ? 'ห้องนี้ยังไม่เคยมีประกาศ รวมถึงที่เก็บถาวรแล้ว'
            : 'เมื่อมีประกาศ จะขึ้นที่นี่และแจ้งเตือนสมาชิกอัตโนมัติ'
      "
    >
      <AppButton
        v-if="unreadOnly"
        variant="secondary"
        @click="unreadOnly = false"
      >
        ดูประกาศทั้งหมด
      </AppButton>
      <AppButton v-else-if="canSend" variant="primary" to="/messages">ส่งประกาศแรก</AppButton>
    </AppEmptyState>

    <div v-else class="space-y-5">
      <p
        v-if="error"
        class="rounded-xl border border-danger-200 bg-danger-50 px-3 py-2 text-xs font-bold text-danger-800"
        role="status"
      >
        อัปเดตล่าสุดไม่สำเร็จ — ข้อมูลที่เห็นอาจไม่ใช่ล่าสุด
      </p>

      <!-- ปักหมุด -->
      <section v-if="pinned.length > 0" aria-labelledby="pinned-heading" class="space-y-2">
        <h2 id="pinned-heading" class="flex items-center gap-1.5 text-xs font-bold text-stone-500">
          <i class="bi bi-pin-angle-fill" aria-hidden="true"></i>
          ปักหมุด
        </h2>
        <ul class="space-y-2">
          <li v-for="item in pinned" :key="`pinned-${item.id}`">
            <RouterLink
              :to="`/announcements/${item.id}`"
              class="block rounded-2xl border border-warn-200 bg-warn-50/60 p-4 transition-colors hover:bg-warn-50"
              @click="refreshUnread"
            >
              <div class="mb-1 flex flex-wrap items-center gap-1.5">
                <span
                  class="inline-flex items-center gap-1 rounded-full bg-warn-100 px-2 py-0.5 text-[11px] font-bold text-warn-800"
                >
                  <i class="bi bi-pin-angle-fill" aria-hidden="true"></i>
                  ปักหมุด
                </span>
                <span
                  v-if="badgeFor(item).priority"
                  class="rounded-full px-2 py-0.5 text-[11px] font-bold"
                  :class="badgeFor(item).priorityClass"
                >
                  {{ badgeFor(item).priority }}
                </span>
                <span
                  v-if="item.is_unread"
                  class="rounded-full bg-brand-100 px-2 py-0.5 text-[11px] font-bold text-brand-800"
                >
                  ใหม่
                </span>
                <span
                  v-if="item.archived_at"
                  class="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-bold text-stone-600"
                >
                  เก็บถาวรแล้ว
                </span>
              </div>
              <p class="break-words text-sm font-bold text-stone-900">{{ item.title }}</p>
              <p
                v-if="item.body"
                class="mt-1 line-clamp-2 break-words text-xs leading-relaxed text-stone-600"
              >
                {{ item.body }}
              </p>
              <p class="mt-2 text-[11px] font-bold text-stone-400">
                {{ formatThaiDateTime(item.created_at) }}
              </p>
            </RouterLink>
          </li>
        </ul>
      </section>

      <!-- รายการปกติ -->
      <section aria-label="ประกาศทั้งหมด" class="space-y-2">
        <ul class="space-y-2">
          <li v-for="item in items" :key="item.id">
            <RouterLink
              :to="`/announcements/${item.id}`"
              class="block rounded-2xl border p-4 transition-colors"
              :class="
                item.is_unread
                  ? 'border-brand-200 bg-brand-50/60 hover:bg-brand-50'
                  : 'border-stone-200 bg-white hover:bg-stone-50'
              "
              @click="refreshUnread"
            >
              <div class="mb-1 flex flex-wrap items-center gap-1.5">
                <span
                  v-if="item.is_unread"
                  class="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-[11px] font-bold text-brand-800"
                >
                  <span class="h-1.5 w-1.5 rounded-full bg-brand-600" aria-hidden="true"></span>
                  ใหม่
                </span>
                <span
                  v-if="badgeFor(item).priority"
                  class="rounded-full px-2 py-0.5 text-[11px] font-bold"
                  :class="badgeFor(item).priorityClass"
                >
                  {{ badgeFor(item).priority }}
                </span>
                <span
                  v-if="item.archived_at"
                  class="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-bold text-stone-600"
                >
                  เก็บถาวรแล้ว
                </span>
              </div>
              <p class="break-words text-sm font-bold text-stone-900">{{ item.title }}</p>
              <p
                v-if="item.body"
                class="mt-1 line-clamp-2 break-words text-xs leading-relaxed text-stone-600"
              >
                {{ item.body }}
              </p>
              <p class="mt-2 text-[11px] font-bold text-stone-400">
                {{ formatThaiDateTime(item.created_at) }}
              </p>
            </RouterLink>
          </li>
        </ul>

        <AppButton
          v-if="hasMore"
          variant="secondary"
          block
          :loading="isLoadingMore"
          @click="loadMore"
        >
          <i class="bi bi-chevron-down" aria-hidden="true"></i>
          โหลดประกาศเพิ่มเติม
        </AppButton>
      </section>
    </div>
  </div>
</template>
