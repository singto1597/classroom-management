<script setup lang="ts">
/**
 * 👤 "ของฉัน" — ไทม์ไลน์ส่วนตัว · สถิติ · รายการที่บันทึกไว้ (P3.3 + P3.4)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **ตัวเลขของห้องต้องมีป้าย "ของห้อง"** — `room_tasks_*` มาจาก backend ที่
 *     ตั้งชื่อแยกไว้แล้ว หน้าจอห้ามตัด `room_` ออกตอนแสดงผล ไม่งั้นผู้ใช้จะอ่าน
 *     งานทั้งห้องเป็นงานของตัวเอง
 *  2. **ไม่มีโปรไฟล์นักเรียน ≠ ไม่มีข้อมูล** — `has_profile: false` มีคำอธิบายของ
 *     ตัวเอง ไม่ใช่จอว่างและไม่ใช่ 0 ลอย ๆ
 *  3. แท็บ "บันทึกไว้" โหลดเมื่อเปิดครั้งแรก (lazy) — ไม่ยิงคำขอที่ผู้ใช้อาจไม่ดู
 *  4. รายการที่เป้าหมายถูกลบแล้ว (`available: false`) แสดงเป็นข้อความ ไม่ใช่ลิงก์
 *     ที่กดแล้วไปเจอ 404
 *  5. 🗓️ **ตัวกรองปี/เทอม (P5) มีผลกับการ์ดสถิติเท่านั้น** — ฟีดด้านล่างเป็น
 *     ไทม์ไลน์ทั้งหมดเสมอ หน้าจอจึงต้องเขียนบอกตรง ๆ ไม่งั้นผู้ใช้จะคิดว่ารายการ
 *     ที่เห็นถูกกรองไปด้วยแล้ว (และหาว่า "ทำไมกิจกรรมเมื่อวานหาย")
 *  6. ไม่ส่ง `year_id`/`term_id` เลย = ให้ backend ใช้ปี/เทอมปัจจุบันของห้อง
 *     ⇒ ห้ามส่งค่าปลอม (0) แทน "อัตโนมัติ"
 */
import { computed, onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import Swal from 'sweetalert2';
import PageHeader from '@/components/ui/PageHeader.vue';
import AppTabs from '@/components/ui/AppTabs.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppEmptyState from '@/components/ui/AppEmptyState.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import { MeService } from '@/services/me';
import { AcademicService } from '@/services/academic';
import { BookmarkService } from '@/services/bookmark';
import { useAuthStore } from '@/stores/auth';
import { formatThaiDate, formatThaiDateTime } from '@/utils/datetime';
import { formatMoney } from '@/utils/money';
import { UI_COLOR } from '@/constants/theme';
import { BOOKMARK_ENTITY_LABELS } from '@/types/bookmark';
import type { BookmarkItem } from '@/types/bookmark';
import type { AppTabItem } from '@/components/ui/AppTabs.vue';
import type { MeActivityItem, MeStats } from '@/types/me';
import type { AcademicPeriods } from '@/types/academic';

type TabValue = 'feed' | 'saved';

/** ตรงกับ DEFAULT_PAGE_SIZE ฝั่ง backend */
const PAGE_SIZE = 20;

const authStore = useAuthStore();
const roomId = authStore.currentRoomId ?? 0;

const tab = ref<TabValue>('feed');
const tabs: readonly AppTabItem[] = [
  { value: 'feed', label: 'กิจกรรมของฉัน' },
  { value: 'saved', label: 'บันทึกไว้' },
];

const messageOf = (err: unknown): string =>
  err instanceof Error && err.message ? err.message : 'โหลดข้อมูลไม่สำเร็จ';

// ── สถิติ ──────────────────────────────────────────────────────────────────
const stats = ref<MeStats | null>(null);
const statsLoading = ref(true);
const statsRefreshing = ref(false);
const statsError = ref<string | null>(null);
let statsSeq = 0;

/** ตัวกรองที่ผู้ใช้เลือกเอง — `null` = ให้ backend ใช้ปี/เทอมปัจจุบันของห้อง */
const filterYearId = ref<number | null>(null);
const filterTermId = ref<number | null>(null);

const statsParams = (): { year_id?: number; term_id?: number } => {
  if (filterYearId.value === null) return {};
  // เลือกปีอย่างเดียว = "ทั้งปี" (backend ตีความเป็นช่วงของปี ไม่ใช่ทั้งระบบ)
  if (filterTermId.value === null) return { year_id: filterYearId.value };
  return { year_id: filterYearId.value, term_id: filterTermId.value };
};

const loadStats = async () => {
  const mySeq = ++statsSeq;
  // สเกเลตันเฉพาะครั้งแรก — เปลี่ยนตัวกรองแล้วให้ตัวเลขเดิมค้างไว้จนของใหม่มา
  // (กระพริบเป็น skeleton ทุกครั้งที่เปลี่ยนปีอ่านยากกว่า)
  statsLoading.value = stats.value === null;
  statsRefreshing.value = stats.value !== null;
  statsError.value = null;
  try {
    const result = await MeService.stats(roomId, statsParams());
    if (mySeq !== statsSeq) return;
    stats.value = result;
  } catch (err) {
    if (mySeq !== statsSeq) return;
    statsError.value = messageOf(err);
  } finally {
    if (mySeq === statsSeq) {
      statsLoading.value = false;
      statsRefreshing.value = false;
    }
  }
};

// ── ปฏิทินของห้อง (สำหรับตัวเลือกปี/เทอม) ─────────────────────────────────
// โหลดล้มเหลว = ซ่อนตัวเลือกเฉย ๆ ไม่ใช่ error ของหน้า — สถิติยังดูได้
const academic = ref<AcademicPeriods | null>(null);

const loadAcademic = async () => {
  try {
    academic.value = await AcademicService.periods(roomId);
  } catch {
    academic.value = null;
  }
};

const yearOptions = computed(() => academic.value?.years ?? []);

const selectedYear = computed(
  () => yearOptions.value.find((year) => year.id === filterYearId.value) ?? null,
);

const hasAnyFilter = computed(() => filterYearId.value !== null);

const setYear = (event: Event) => {
  const raw = (event.target as HTMLSelectElement).value;
  filterYearId.value = raw === '' ? null : Number(raw);
  filterTermId.value = null; // เปลี่ยนปีแล้วเทอมเดิมไม่มีความหมาย
  void loadStats();
};

const setTerm = (event: Event) => {
  const raw = (event.target as HTMLSelectElement).value;
  filterTermId.value = raw === '' ? null : Number(raw);
  void loadStats();
};

const resetFilter = () => {
  filterYearId.value = null;
  filterTermId.value = null;
  void loadStats();
};

/**
 * คำอธิบายว่าตัวเลขชุดนี้ครอบช่วงไหน
 * `stats.term === null` = ห้องยังไม่มีปีปัจจุบัน ⇒ ไม่กรอง (ไม่ใช่ 0 และไม่ใช่ error)
 */
const statsPeriodLabel = computed(() => {
  const term = stats.value?.term;
  if (!term) return 'ทั้งหมด (ห้องนี้ยังไม่ได้ตั้งปีปัจจุบัน)';
  const suffix = term.term_name ? ` · ${term.term_name}` : ' · ทั้งปี';
  return `ปีการศึกษา ${term.year_be}${suffix}`;
});

const statsPeriodSource = computed<'explicit' | 'current' | null>(() => stats.value?.term?.source ?? null);

// ── ฟีด ────────────────────────────────────────────────────────────────────
const feedItems = ref<MeActivityItem[]>([]);
const feedCursor = ref<string | null>(null);
const feedHasMore = ref(false);
const feedLoaded = ref(false);
const feedLoading = ref(true);
const feedLoadingMore = ref(false);
const feedError = ref<string | null>(null);
let feedSeq = 0;

const loadFeed = async (reset: boolean) => {
  const mySeq = ++feedSeq;
  if (reset) {
    feedLoading.value = true;
    feedError.value = null;
  } else {
    feedLoadingMore.value = true;
  }
  try {
    const response = await MeService.activity(roomId, {
      limit: PAGE_SIZE,
      cursor: reset ? null : feedCursor.value,
    });
    if (mySeq !== feedSeq) return;
    feedItems.value = reset ? response.items : [...feedItems.value, ...response.items];
    feedCursor.value = response.next_cursor;
    feedHasMore.value = response.has_more;
    feedLoaded.value = true;
  } catch (err) {
    if (mySeq !== feedSeq) return;
    feedError.value = messageOf(err);
  } finally {
    if (mySeq === feedSeq) {
      feedLoading.value = false;
      feedLoadingMore.value = false;
    }
  }
};

// ── บันทึกไว้ (โหลดเมื่อเปิดแท็บครั้งแรก) ──────────────────────────────────
const savedItems = ref<BookmarkItem[]>([]);
const savedCursor = ref<string | null>(null);
const savedHasMore = ref(false);
const savedLoaded = ref(false);
const savedLoading = ref(false);
const savedLoadingMore = ref(false);
const savedError = ref<string | null>(null);
let savedSeq = 0;

const loadSaved = async (reset: boolean) => {
  const mySeq = ++savedSeq;
  if (reset) {
    savedLoading.value = true;
    savedError.value = null;
  } else {
    savedLoadingMore.value = true;
  }
  try {
    const response = await BookmarkService.list(roomId, {
      limit: PAGE_SIZE,
      cursor: reset ? null : savedCursor.value,
    });
    if (mySeq !== savedSeq) return;
    savedItems.value = reset ? response.items : [...savedItems.value, ...response.items];
    savedCursor.value = response.next_cursor;
    savedHasMore.value = response.has_more;
    savedLoaded.value = true;
  } catch (err) {
    if (mySeq !== savedSeq) return;
    savedError.value = messageOf(err);
  } finally {
    if (mySeq === savedSeq) {
      savedLoading.value = false;
      savedLoadingMore.value = false;
    }
  }
};

// AppTabs ส่งค่าออกมาเป็น `string` — แคบกลับเป็น union ที่เรารู้จักเท่านั้น
// (ใช้ `:model-value` + handler แทน `v-model` เพราะ `v-model` จะพยายามเขียน
//  `string` ลง `Ref<TabValue>` ซึ่ง vue-tsc ไม่ยอม)
const setTab = (value: string) => {
  if (value !== 'feed' && value !== 'saved') return;
  tab.value = value;
};

watch(tab, (value) => {
  if (value === 'saved' && !savedLoaded.value && !savedLoading.value) {
    void loadSaved(true);
  }
});

onMounted(() => {
  if (!roomId) {
    feedLoading.value = false;
    statsLoading.value = false;
    feedError.value = 'ยังไม่ได้เลือกห้องเรียน';
    statsError.value = 'ยังไม่ได้เลือกห้องเรียน';
    return;
  }
  void loadFeed(true);
  void loadStats();
  void loadAcademic();
});

const removeSaved = async (item: BookmarkItem) => {
  try {
    await BookmarkService.remove(roomId, item.bookmark_id);
    savedItems.value = savedItems.value.filter((row) => row.bookmark_id !== item.bookmark_id);

    const undo = await Swal.fire({
      icon: 'success',
      title: 'ยกเลิกการบันทึกแล้ว',
      text: item.title,
      confirmButtonText: 'บันทึกกลับ',
      showCancelButton: true,
      cancelButtonText: 'ปิด',
      confirmButtonColor: UI_COLOR.brand,
    });
    if (undo.isConfirmed) {
      await BookmarkService.add(roomId, item.entity_type, item.entity_id);
      await loadSaved(true);
    }
  } catch (err) {
    await Swal.fire({
      icon: 'error',
      title: 'ยกเลิกการบันทึกไม่สำเร็จ',
      text: messageOf(err),
      confirmButtonColor: UI_COLOR.brand,
    });
  }
};

const feedIcon = (item: MeActivityItem): string =>
  item.kind === 'payment' ? 'bi-receipt' : 'bi-calendar-heart';

const feedIconClass = (item: MeActivityItem): string =>
  item.kind === 'payment' ? 'bg-ok-50 text-ok-700' : 'bg-brand-50 text-brand-700';

const feedWhen = (item: MeActivityItem): string =>
  item.kind === 'payment'
    ? formatThaiDateTime(item.happened_at)
    : `เข้าร่วมเมื่อ ${formatThaiDateTime(item.happened_at)}`;

const hasNoStats = computed(() => stats.value !== null && !stats.value.has_profile);
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader title="ของฉัน" description="ไทม์ไลน์ส่วนตัว · สถิติ · รายการที่บันทึกไว้" />

    <AppTabs
      :model-value="tab"
      :tabs="tabs"
      group-label="เลือกหมวดของฉัน"
      @update:model-value="setTab"
    />

    <!-- ── กิจกรรมของฉัน ────────────────────────────────────────────────── -->
    <section v-if="tab === 'feed'" class="space-y-4" aria-label="กิจกรรมของฉัน">
      <SkeletonRows v-if="statsLoading" :rows="1" height="h-24" />
      <StateBlock
        v-else-if="statsError"
        variant="error"
        title="โหลดสถิติไม่สำเร็จ"
        :hint="statsError"
        @retry="loadStats"
      />
      <div v-else-if="stats" class="space-y-2" :aria-busy="statsRefreshing">
        <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 class="text-xs font-bold text-stone-500">สถิติของฉัน</h2>
          <p class="text-[11px] font-bold text-stone-500">
            ช่วงที่ใช้: {{ statsPeriodLabel }}
            <span v-if="statsPeriodSource === 'current'" class="font-normal text-stone-400">
              (ระบบเลือกให้)
            </span>
          </p>
        </div>

        <!-- 🗓️ ตัวกรองปี/เทอม — มีผลกับ "การ์ดสถิติ" เท่านั้น -->
        <div
          v-if="yearOptions.length > 0"
          class="flex flex-wrap items-end gap-2 rounded-2xl border border-stone-200 bg-white p-3"
        >
          <label class="min-w-[10rem] flex-1">
            <span class="text-[11px] font-bold text-stone-600">ดูสถิติตามปี</span>
            <select
              :value="filterYearId ?? ''"
              class="mt-1 min-h-11 w-full rounded-xl border border-stone-300 bg-white px-3 text-sm"
              @change="setYear"
            >
              <option value="">อัตโนมัติ (ปี/เทอมปัจจุบัน)</option>
              <option v-for="year in yearOptions" :key="year.id" :value="year.id">
                ปีการศึกษา {{ year.year_be }}
              </option>
            </select>
          </label>

          <label v-if="selectedYear" class="min-w-[10rem] flex-1">
            <span class="text-[11px] font-bold text-stone-600">เทอม</span>
            <select
              :value="filterTermId ?? ''"
              class="mt-1 min-h-11 w-full rounded-xl border border-stone-300 bg-white px-3 text-sm"
              @change="setTerm"
            >
              <option value="">ทั้งปี</option>
              <option v-for="term in selectedYear.terms" :key="term.id" :value="term.id">
                {{ term.name }}
              </option>
            </select>
          </label>

          <AppButton v-if="hasAnyFilter" variant="quiet" @click="resetFilter">
            กลับเป็นอัตโนมัติ
          </AppButton>
        </div>

        <div
          class="grid grid-cols-2 gap-2 transition-opacity sm:grid-cols-4"
          :class="statsRefreshing ? 'opacity-60' : ''"
        >
          <div class="rounded-2xl border border-stone-200 bg-white p-3">
            <p class="text-[11px] font-bold text-stone-500">กิจกรรมที่เข้าร่วม</p>
            <p class="mt-1 text-xl font-black text-stone-900">{{ stats.activities_joined }}</p>
            <p class="text-[11px] font-bold text-stone-400">กิจกรรม</p>
          </div>
          <div class="rounded-2xl border border-stone-200 bg-white p-3">
            <p class="text-[11px] font-bold text-stone-500">ชั่วโมงกิจกรรม</p>
            <p class="mt-1 text-xl font-black text-stone-900">{{ stats.activity_hours }}</p>
            <p class="text-[11px] font-bold text-stone-400">ชั่วโมง</p>
          </div>
          <div class="rounded-2xl border border-stone-200 bg-white p-3">
            <p class="text-[11px] font-bold text-stone-500">จ่ายแล้ว</p>
            <p class="mt-1 text-xl font-black text-ok-700">{{ formatMoney(stats.paid_total) }}</p>
            <p class="text-[11px] font-bold text-stone-400">จากใบเสร็จที่ยังใช้งาน</p>
          </div>
          <div class="rounded-2xl border border-stone-200 bg-white p-3">
            <p class="text-[11px] font-bold text-stone-500">ค้างชำระ</p>
            <p
              class="mt-1 text-xl font-black"
              :class="stats.outstanding > 0 ? 'text-danger-700' : 'text-stone-900'"
            >
              {{ formatMoney(stats.outstanding) }}
            </p>
            <p class="text-[11px] font-bold text-stone-400">{{ stats.unpaid_bills }} บิล</p>
          </div>
        </div>

        <p
          v-if="hasNoStats"
          class="rounded-xl border border-info-200 bg-info-50 px-3 py-2 text-xs font-bold text-info-800"
          role="status"
        >
          บัญชีนี้ยังไม่ได้ผูกกับรายชื่อนักเรียนในห้อง — ตัวเลขส่วนตัวจึงเป็น 0
        </p>

        <p class="text-[11px] font-bold text-stone-400">
          งานของห้อง: เสร็จ {{ stats.room_tasks_done }} · ค้าง {{ stats.room_tasks_pending }}
          (นับทั้งห้อง ไม่ใช่ของฉัน)
        </p>

        <p class="text-[11px] leading-relaxed text-stone-400">
          ตัวกรองปี/เทอมมีผลกับ <span class="font-bold">การ์ดสถิติด้านบนเท่านั้น</span> —
          รายการด้านล่างยังเป็นทั้งหมด · ยอดค้างชำระและงานของห้องคือสถานะปัจจุบัน ไม่ขึ้นกับช่วงที่เลือก
        </p>
      </div>

      <SkeletonRows v-if="feedLoading && !feedLoaded" :rows="4" height="h-20" />

      <StateBlock
        v-else-if="feedError && !feedLoaded"
        variant="error"
        title="โหลดกิจกรรมไม่สำเร็จ"
        :hint="feedError"
        @retry="loadFeed(true)"
      />

      <AppEmptyState
        v-else-if="feedLoaded && feedItems.length === 0"
        icon="bi-person-lines-fill"
        title="ยังไม่มีกิจกรรมของฉัน"
        hint="เมื่อจ่ายเงินหรือเข้าร่วมกิจกรรม รายการจะขึ้นที่นี่"
      >
        <AppButton variant="secondary" to="/activities">ดูกิจกรรมของห้อง</AppButton>
      </AppEmptyState>

      <div v-else-if="feedLoaded" class="space-y-3">
        <p
          v-if="feedError"
          class="rounded-xl border border-danger-200 bg-danger-50 px-3 py-2 text-xs font-bold text-danger-800"
          role="status"
        >
          อัปเดตล่าสุดไม่สำเร็จ — ข้อมูลที่เห็นอาจไม่ใช่ล่าสุด
        </p>

        <ul class="space-y-2">
          <li v-for="item in feedItems" :key="`${item.kind}-${item.entity_id}`">
            <RouterLink
              :to="item.url"
              class="flex gap-3 rounded-2xl border border-stone-200 bg-white p-4 transition-colors hover:bg-stone-50"
            >
              <span
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl"
                :class="feedIconClass(item)"
              >
                <i :class="['bi', feedIcon(item)]" aria-hidden="true"></i>
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-start justify-between gap-2">
                  <p class="break-words text-sm font-bold text-stone-900">{{ item.title }}</p>
                  <span
                    v-if="item.kind === 'payment' && item.amount !== null"
                    class="shrink-0 text-sm font-black text-ok-700"
                  >
                    {{ formatMoney(item.amount) }}
                  </span>
                </div>
                <p
                  v-if="item.detail"
                  class="mt-1 line-clamp-2 break-words text-xs leading-relaxed text-stone-600"
                >
                  {{ item.detail }}
                </p>
                <p class="mt-1 text-[11px] font-bold text-stone-400">
                  {{ feedWhen(item) }}
                  <span v-if="item.reference"> · {{ item.reference }}</span>
                  <span v-if="item.kind === 'activity' && item.activity_date">
                    · จัด {{ formatThaiDate(item.activity_date) }}
                  </span>
                </p>
              </div>
            </RouterLink>
          </li>
        </ul>

        <AppButton
          v-if="feedHasMore"
          variant="secondary"
          block
          :loading="feedLoadingMore"
          @click="loadFeed(false)"
        >
          <i class="bi bi-chevron-down" aria-hidden="true"></i>
          โหลดเพิ่ม
        </AppButton>
      </div>
    </section>

    <!-- ── บันทึกไว้ ─────────────────────────────────────────────────────── -->
    <section v-else class="space-y-3" aria-label="บันทึกไว้">
      <SkeletonRows v-if="savedLoading && !savedLoaded" :rows="4" height="h-20" />

      <StateBlock
        v-else-if="savedError && !savedLoaded"
        variant="error"
        title="โหลดรายการที่บันทึกไว้ไม่สำเร็จ"
        :hint="savedError"
        @retry="loadSaved(true)"
      />

      <AppEmptyState
        v-else-if="savedLoaded && savedItems.length === 0"
        icon="bi-bookmark"
        title="ยังไม่มีรายการที่บันทึกไว้"
        hint="กดไอคอนบุ๊กมาร์กในหน้าประกาศหรือกิจกรรมเพื่อเก็บไว้ดูทีหลัง"
      >
        <AppButton variant="secondary" to="/announcements">ดูประกาศของห้อง</AppButton>
      </AppEmptyState>

      <div v-else-if="savedLoaded" class="space-y-3">
        <p
          v-if="savedError"
          class="rounded-xl border border-danger-200 bg-danger-50 px-3 py-2 text-xs font-bold text-danger-800"
          role="status"
        >
          อัปเดตล่าสุดไม่สำเร็จ — ข้อมูลที่เห็นอาจไม่ใช่ล่าสุด
        </p>

        <ul class="space-y-2">
          <li
            v-for="item in savedItems"
            :key="item.bookmark_id"
            class="flex gap-3 rounded-2xl border border-stone-200 bg-white p-4"
          >
            <div class="min-w-0 flex-1">
              <div class="mb-1 flex flex-wrap items-center gap-1.5">
                <span class="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-bold text-stone-600">
                  {{ BOOKMARK_ENTITY_LABELS[item.entity_type] }}
                </span>
                <span
                  v-if="!item.available"
                  class="rounded-full bg-danger-50 px-2 py-0.5 text-[11px] font-bold text-danger-700"
                >
                  ถูกลบแล้ว
                </span>
              </div>

              <RouterLink
                v-if="item.available"
                :to="item.url"
                class="break-words text-sm font-bold text-brand-700 hover:underline"
              >
                {{ item.title }}
              </RouterLink>
              <p v-else class="break-words text-sm font-bold text-stone-500">{{ item.title }}</p>

              <p
                v-if="item.snippet"
                class="mt-1 line-clamp-2 break-words text-xs leading-relaxed text-stone-600"
              >
                {{ item.snippet }}
              </p>
              <p class="mt-1 text-[11px] font-bold text-stone-400">
                <span v-if="item.occurred_on">{{ formatThaiDate(item.occurred_on) }} · </span>
                บันทึกเมื่อ {{ formatThaiDateTime(item.created_at) }}
              </p>
            </div>

            <button
              type="button"
              class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-500 transition-colors hover:bg-danger-50 hover:text-danger-700"
              aria-label="เลิกบันทึกไว้"
              title="เลิกบันทึกไว้"
              @click="removeSaved(item)"
            >
              <i class="bi bi-bookmark-x text-base" aria-hidden="true"></i>
            </button>
          </li>
        </ul>

        <AppButton
          v-if="savedHasMore"
          variant="secondary"
          block
          :loading="savedLoadingMore"
          @click="loadSaved(false)"
        >
          <i class="bi bi-chevron-down" aria-hidden="true"></i>
          โหลดเพิ่ม
        </AppButton>
      </div>
    </section>
  </div>
</template>
