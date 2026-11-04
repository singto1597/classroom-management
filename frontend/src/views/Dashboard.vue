<script setup lang="ts">
/**
 * 🏠 หน้าหลัก — **คำขอเดียว** (P3.1 + P3.2)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กติกาที่ผังหน้านี้บังคับไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. ทุกตัวเลขมาจาก `GET /home/summary` ก้อนเดียว (snapshot เดียวฝั่ง backend)
 *     ⇒ ไม่ต้องดึงรายการทั้งห้องมานับฝั่งหน้า ซึ่งวันหนึ่งจะนับไม่ตรงกับลิสต์ปลายทาง
 *  2. **การ์ดที่กดได้ → ปลายทางต้องกรองเหลือชุดเดียวกับตัวเลข** เช่น
 *     งานค้าง 34 → `/tasks?filter=pending` (ไม่ใช่ `/tasks` เปล่า ๆ)
 *     บิลค้าง 5   → `/finance/my-debts` (ของฉัน ไม่ใช่ `/finance/debtors` ของทุกคน)
 *     ยังไม่อ่าน 3 → `/announcements?unread=1` (กรองฝั่ง backend เพราะแบ่งหน้า)
 *  3. **การ์ดที่ไม่มีปลายทางที่ตัวเลขตรงกัน = ไม่กด** และคอมเมนต์บอกเหตุผล
 *     (เช่นรหัสห้อง — ไม่ใช่จำนวนของรายการใด ๆ)
 */
defineOptions({ name: 'DashboardView' });

import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { HomeService } from '@/services/home';
import { StudentService } from '@/services/student';
import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import Swal from 'sweetalert2';
import { UI_COLOR } from '@/constants/theme';
import {
  bangkokHour,
  daysFromThaiToday,
  formatThaiDate,
  relativeThaiDay,
} from '@/utils/datetime';
import { formatMoney } from '@/utils/money';
import { usePageTitle } from '@/composables/usePageTitle';
import type { HomeSummary } from '@/types/home';

const router = useRouter();
const authStore = useAuthStore();

const userName = computed(() => authStore.currentUserName || 'ผู้ใช้งาน');
// ⏰ ทักทายตามช่วงเวลาไทย (UTC+7 คงที่ ไม่มี DST) — เปลี่ยนแค่ถ้อยคำบนหัวหน้า ไม่ใช่ข้อมูล
const greeting = computed(() => {
  const hour = bangkokHour();
  if (hour < 12) return 'สวัสดีตอนเช้า';
  if (hour < 17) return 'สวัสดีตอนบ่าย';
  return 'สวัสดีตอนเย็น';
});
const greetingTitle = computed(() => `${greeting.value}, ${userName.value}`);
// 🏷️ header เป็นเจ้าของ <h1> — หน้าหลักแสดงคำทักทายตามเวลาแทนชื่อ route
usePageTitle(greetingTitle);
const role = computed(() => authStore.currentRoleLabel);
const isAdmin = computed(() => authStore.isAdmin);

const canManageStudents = computed(
  () => isAdmin.value || authStore.currentPermissions.includes('MANAGE_STUDENTS'),
);
const canManageTasks = computed(
  () => isAdmin.value || authStore.currentPermissions.includes('MANAGE_CLASSROOM_TASKS'),
);

const roomCode = computed(() => authStore.currentRoomCode || 'ไม่มีรหัส');

// ── สรุปหน้าหลัก (ก้อนเดียว) ────────────────────────────────────────────────
const summary = ref<HomeSummary | null>(null);
const isLoading = ref(true);
const hasError = ref(false);
const errorMessage = ref('');

const load = async () => {
  isLoading.value = true;
  hasError.value = false;
  errorMessage.value = '';
  try {
    summary.value = await HomeService.getSummary(authStore.currentRoomId!);
  } catch (err) {
    hasError.value = true;
    errorMessage.value =
      err instanceof Error && err.message ? err.message : 'โหลดสรุปหน้าหลักไม่สำเร็จ';
  } finally {
    isLoading.value = false;
  }
};

onMounted(load);

/** สีของตัวเลข: เทาเมื่อไม่มี, เตือนเมื่อมีของค้าง */
const toneClass = (count: number, tone: 'warn' | 'danger'): string => {
  if (count <= 0) return 'text-stone-900';
  return tone === 'danger' ? 'text-danger-600' : 'text-warn-600';
};

/** ป้ายกำหนดส่งของงานตัวอย่าง — ไม่ต้องคำนวณใน template ซ้ำ */
const taskDueBadge = (dueDate: string): { text: string; classes: string } => {
  const diff = daysFromThaiToday(dueDate);
  if (diff !== null && diff < 0) {
    return { text: `เลยกำหนด ${Math.abs(diff)} วัน`, classes: 'bg-danger-50 text-danger-700' };
  }
  const relative = relativeThaiDay(dueDate);
  if (relative) {
    return { text: `ครบกำหนด${relative}`, classes: 'bg-warn-50 text-warn-800' };
  }
  return { text: formatThaiDate(dueDate), classes: 'bg-stone-100 text-stone-600' };
};

const activityDayBadge = (dateIso: string): string | null => relativeThaiDay(dateIso);

const hasNote = computed(
  () => Boolean(summary.value?.note?.bring_items || summary.value?.note?.announcement),
);

// ✨ ไปหน้าเลือกห้อง — ไม่ล้างห้องที่เปิดอยู่ (ปุ่มสลับห้องแบบเร็วอยู่ใน header ของ MainLayout)
const handleChangeRoom = () => {
  router.push('/lobby');
};

const goToMyProfile = async () => {
  try {
    Swal.fire({
      title: 'กำลังดึงข้อมูล...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading(),
    });
    const myProfile = await StudentService.getMyProfile(authStore.currentRoomId!);
    Swal.close();
    router.push(`/students/${myProfile.student_no}`);
  } catch {
    Swal.fire({
      icon: 'warning',
      title: 'ข้อผิดพลาด',
      text: 'ไม่สามารถเข้าถึงโปรไฟล์ได้ (คุณอาจเป็นผู้ดูแลระบบที่ไม่ได้มีชื่อในทะเบียนนักเรียน)',
      confirmButtonColor: UI_COLOR.brand,
      confirmButtonText: 'รับทราบ',
    });
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <!-- ========================================== -->
    <!-- 1. หัวหน้า                                  -->
    <!-- ========================================== -->
    <PageIntro>
      <template #actions>
        <button type="button" class="btn-ghost-ui" title="สลับห้องเรียน" @click="handleChangeRoom">
          <i class="bi bi-arrow-left-right" aria-hidden="true"></i>
          <span class="hidden sm:inline">สลับห้องเรียน</span>
          <span class="sm:hidden">สลับห้อง</span>
        </button>
      </template>
    </PageIntro>

    <!-- ========================================== -->
    <!-- 2. สรุป — โหลด / ผิดพลาด / ข้อมูล           -->
    <!-- ========================================== -->
    <SkeletonRows v-if="isLoading" :rows="3" height="h-24" />

    <StateBlock
      v-else-if="hasError || !summary"
      variant="error"
      title="โหลดสรุปหน้าหลักไม่สำเร็จ"
      :hint="errorMessage"
      @retry="load"
    />

    <template v-else>
      <!-- KPI 4 ใบ — ทุกใบกดได้และส่งตัวกรองที่ตรงกับตัวเลขเสมอ -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <RouterLink
          to="/tasks?filter=all"
          class="page-card block p-3.5 transition-colors hover:bg-stone-50 active:scale-[0.99] sm:p-5"
          aria-label="ดูงานทั้งหมดในห้องนี้"
        >
          <p class="text-[11px] font-bold text-stone-500">งานทั้งหมด</p>
          <p class="font-display num mt-2 text-2xl font-bold text-stone-900 sm:text-3xl">
            {{ summary.tasks.total }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-500">รายการในห้องนี้</p>
        </RouterLink>

        <RouterLink
          to="/tasks?filter=pending"
          class="page-card block p-3.5 transition-colors hover:bg-stone-50 active:scale-[0.99] sm:p-5"
          aria-label="ดูงานที่ยังไม่ปิด"
        >
          <p class="text-[11px] font-bold text-stone-500">งานค้าง</p>
          <p
            class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
            :class="toneClass(summary.tasks.pending_total, 'warn')"
          >
            {{ summary.tasks.pending_total }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-500">ยังไม่ปิดงาน</p>
        </RouterLink>

        <RouterLink
          to="/tasks?filter=today"
          class="page-card block p-3.5 transition-colors hover:bg-stone-50 active:scale-[0.99] sm:p-5"
          aria-label="ดูงานที่ครบกำหนดวันนี้"
        >
          <p class="text-[11px] font-bold text-stone-500">ครบกำหนดวันนี้</p>
          <p
            class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
            :class="toneClass(summary.tasks.due_today, 'warn')"
          >
            {{ summary.tasks.due_today }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-500">งานที่ยังไม่ปิด</p>
        </RouterLink>

        <RouterLink
          to="/tasks?filter=overdue"
          class="page-card block p-3.5 transition-colors hover:bg-stone-50 active:scale-[0.99] sm:p-5"
          aria-label="ดูงานที่เลยกำหนดแล้ว"
        >
          <p class="text-[11px] font-bold text-stone-500">เลยกำหนด</p>
          <p
            class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
            :class="toneClass(summary.tasks.overdue, 'danger')"
          >
            {{ summary.tasks.overdue }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-500">ควรจัดการก่อน</p>
        </RouterLink>
      </div>

      <!-- การ์ดสรุป 3 ใบ — ประกาศ / การเงิน / ตารางเรียน -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
        <!-- ประกาศยังไม่อ่าน → หน้า /announcements?unread=1 (กรองฝั่ง backend) -->
        <RouterLink
          to="/announcements?unread=1"
          class="page-card flex items-center gap-3 p-4 transition-colors hover:bg-stone-50 active:scale-[0.99]"
        >
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-megaphone text-lg" aria-hidden="true"></i>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-[11px] font-bold text-stone-500">ประกาศยังไม่อ่าน</p>
            <p
              class="font-display num text-2xl font-bold"
              :class="summary.announcements.unread_count > 0 ? 'text-brand-700' : 'text-stone-900'"
            >
              {{ summary.announcements.unread_count }}
            </p>
          </div>
          <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
        </RouterLink>

        <!-- บิลค้างชำระของฉัน → /finance/my-debts (ของฉัน ไม่ใช่ของทุกคน) -->
        <RouterLink
          v-if="summary.finance.has_profile"
          to="/finance/my-debts"
          class="page-card flex items-center gap-3 p-4 transition-colors hover:bg-stone-50 active:scale-[0.99]"
        >
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-danger-50 text-danger-600"
          >
            <i class="bi bi-receipt text-lg" aria-hidden="true"></i>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-[11px] font-bold text-stone-500">บิลค้างชำระของฉัน</p>
            <p
              class="font-display num text-2xl font-bold"
              :class="summary.finance.unpaid_bills > 0 ? 'text-danger-600' : 'text-stone-900'"
            >
              {{ summary.finance.unpaid_bills }}
            </p>
            <p
              v-if="summary.finance.unpaid_bills > 0"
              class="text-[11px] font-bold text-stone-500"
            >
              รวม {{ formatMoney(summary.finance.outstanding) }}
            </p>
          </div>
          <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
        </RouterLink>

        <!--
          🔒 ไม่มีโปรไฟล์นักเรียน (เช่น แอดมิน) ⇒ ไม่กด: `/finance/me/debts` จะตอบ 404
             การ์ดจึงกลายเป็น "กดแล้วเจอ error" — แสดงค่าคงที่พร้อมคำอธิบายแทน
        -->
        <div v-else class="page-card flex items-center gap-3 p-4">
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-400"
          >
            <i class="bi bi-receipt text-lg" aria-hidden="true"></i>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-[11px] font-bold text-stone-500">บิลค้างชำระของฉัน</p>
            <p class="text-sm font-bold text-stone-400">—</p>
            <p class="text-[11px] leading-snug text-stone-400">
              บัญชีนี้ไม่มีทะเบียนนักเรียนในห้องนี้
            </p>
          </div>
        </div>

        <!-- ตารางเรียนวันนี้ → /schedules -->
        <RouterLink
          to="/schedules"
          class="page-card flex items-center gap-3 p-4 transition-colors hover:bg-stone-50 active:scale-[0.99]"
        >
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-calendar-event text-lg" aria-hidden="true"></i>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-[11px] font-bold text-stone-500">ตารางเรียนวันนี้</p>
            <p class="truncate text-sm font-bold text-stone-900">
              วัน{{ summary.schedule.day_of_week }}
            </p>
            <p class="truncate text-[11px] font-bold text-stone-500">
              {{ summary.schedule.attire || 'ชุดปกติ' }}
            </p>
          </div>
          <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
        </RouterLink>
      </div>

      <!-- ========================================== -->
      <!-- 3. โน้ตวันนี้ + งานที่ต้องทำ + กิจกรรม       -->
      <!-- ========================================== -->
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3 sm:gap-5">
        <!-- โน้ตวันนี้ — ข้อมูล ไม่ใช่จำนวน ⇒ ไม่กด -->
        <div v-if="hasNote" class="page-card p-4 sm:p-5">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-warn-50 text-warn-800"
            >
              <i class="bi bi-journal-text text-lg" aria-hidden="true"></i>
            </div>
            <h2 class="section-title min-w-0 truncate">โน้ตวันนี้</h2>
          </div>
          <dl class="mt-3 space-y-2.5 border-t border-stone-100 pt-3">
            <div v-if="summary.note?.bring_items">
              <dt class="text-[11px] font-bold text-stone-500">สิ่งที่ต้องเตรียม</dt>
              <dd class="mt-0.5 break-words text-sm leading-relaxed text-stone-800">
                {{ summary.note.bring_items }}
              </dd>
            </div>
            <div v-if="summary.note?.announcement">
              <dt class="text-[11px] font-bold text-stone-500">ประกาศจากครู</dt>
              <dd class="mt-0.5 break-words text-sm leading-relaxed text-stone-800">
                {{ summary.note.announcement }}
              </dd>
            </div>
          </dl>
        </div>

        <!-- งานที่ต้องทำ — ตัวอย่าง 3 รายการ ตัวเลขจริงอยู่บน KPI -->
        <div class="page-card p-4 sm:p-5" :class="hasNote ? 'lg:col-span-2' : 'lg:col-span-3'">
          <div class="flex items-center justify-between gap-3">
            <div class="flex min-w-0 items-center gap-3">
              <div
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
              >
                <i class="bi bi-clipboard-check text-lg" aria-hidden="true"></i>
              </div>
              <div class="min-w-0">
                <h2 class="section-title truncate">งานที่ต้องทำ</h2>
                <p class="truncate text-xs text-stone-500">เรียงตามกำหนดส่ง · ตัวอย่าง 3 รายการ</p>
              </div>
            </div>
            <RouterLink
              to="/tasks?filter=pending"
              class="btn-ghost-ui shrink-0 text-xs"
              aria-label="ดูงานค้างทั้งหมด"
            >
              ดูทั้งหมด
              <i class="bi bi-arrow-right" aria-hidden="true"></i>
            </RouterLink>
          </div>

          <div v-if="summary.tasks.items.length === 0" class="mt-3 rounded-xl border border-stone-200 px-3.5 py-4 text-center text-xs font-bold text-stone-500">
            <i class="bi bi-check2-circle me-1.5" aria-hidden="true"></i>
            ไม่มีงานค้าง — ทำงานครบแล้ว
          </div>

          <ul v-else class="mt-3 space-y-2">
            <li
              v-for="item in summary.tasks.items"
              :key="item.id"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5"
            >
              <p class="min-w-0 flex-1 truncate text-sm font-bold text-stone-900">
                {{ item.task_name }}
              </p>
              <span
                class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold"
                :class="taskDueBadge(item.due_date).classes"
              >
                {{ taskDueBadge(item.due_date).text }}
              </span>
            </li>
          </ul>

          <div class="mt-3 flex gap-2 border-t border-stone-100 pt-3 sm:pt-4">
            <RouterLink to="/tasks" class="btn-ghost-ui min-w-0 flex-1">
              <i class="bi bi-card-checklist shrink-0" aria-hidden="true"></i> รวมงานและโน้ต
            </RouterLink>
            <RouterLink v-if="canManageTasks" to="/tasks/add" class="btn-ghost-ui min-w-0 flex-1">
              <i class="bi bi-plus-lg shrink-0" aria-hidden="true"></i> เพิ่มงาน / โน้ต
            </RouterLink>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- 4. กิจกรรมที่เปิดรับ (3 รายการ)              -->
      <!-- ========================================== -->
      <section v-if="summary.activities.length > 0" class="page-card p-4 sm:p-5">
        <div class="flex items-center justify-between gap-3">
          <div class="flex min-w-0 items-center gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
            >
              <i class="bi bi-calendar-heart text-lg" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <h2 class="section-title truncate">กิจกรรมที่เปิดรับ</h2>
              <p class="truncate text-xs text-stone-500">ใกล้วันก่อน · สูงสุด 3 รายการ</p>
            </div>
          </div>
          <RouterLink to="/activities" class="btn-ghost-ui shrink-0 text-xs">
            ทั้งหมด
            <i class="bi bi-arrow-right" aria-hidden="true"></i>
          </RouterLink>
        </div>

        <ul class="mt-3 space-y-2">
          <li v-for="activity in summary.activities" :key="activity.id">
            <RouterLink
              :to="`/activities/${activity.id}`"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 transition-colors hover:bg-stone-50"
            >
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-stone-900">{{ activity.title }}</p>
                <p class="text-[11px] font-bold text-stone-500">
                  {{ formatThaiDate(activity.activity_date) }} · {{ activity.base_hours }} ชม.
                </p>
              </div>
              <span
                v-if="activityDayBadge(activity.activity_date)"
                class="shrink-0 rounded-full bg-warn-50 px-2 py-0.5 text-[11px] font-bold text-warn-800"
              >
                {{ activityDayBadge(activity.activity_date) }}
              </span>
              <i v-else class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>
          </li>
        </ul>
      </section>

      <!-- ========================================== -->
      <!-- 5. ทางลัด                                    -->
      <!-- ========================================== -->
      <section class="space-y-3">
        <h2 class="section-title">ทางลัด</h2>

        <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
          <RouterLink
            to="/students"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-people text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              รายชื่อนักเรียน
            </span>
          </RouterLink>

          <button
            type="button"
            class="page-card card-hover flex w-full min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
            @click="goToMyProfile"
          >
            <i class="bi bi-person-badge text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              โปรไฟล์ของฉัน
            </span>
          </button>

          <template v-if="canManageStudents">
            <RouterLink
              to="/students/add"
              class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
            >
              <i class="bi bi-person-plus text-lg text-brand-700" aria-hidden="true"></i>
              <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
                เพิ่มนักเรียน
              </span>
            </RouterLink>

            <RouterLink
              to="/students/export"
              class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
            >
              <i class="bi bi-file-earmark-excel-fill text-lg text-brand-700" aria-hidden="true"></i>
              <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
                ไฟล์ Export
              </span>
            </RouterLink>
          </template>

          <RouterLink
            to="/finance"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-wallet2 text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              สรุปการเงิน
            </span>
          </RouterLink>

          <RouterLink
            to="/finance/transactions"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-clock-history text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              ประวัติรายการ
            </span>
          </RouterLink>

          <RouterLink
            to="/finance/collections"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-folder2-open text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              โปรเจกต์เก็บเงิน
            </span>
          </RouterLink>

          <RouterLink
            v-if="isAdmin"
            to="/finance/debtors"
            class="card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 rounded-2xl border border-danger-200 bg-white p-3 text-center sm:p-4"
          >
            <i class="bi bi-exclamation-triangle text-lg text-danger-500" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-danger-600">
              ทวงหนี้
            </span>
          </RouterLink>

          <RouterLink
            to="/messages"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-megaphone text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              เขียนประกาศ
            </span>
          </RouterLink>

          <RouterLink
            to="/discord-connect"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-discord text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              จัดการบอท
            </span>
          </RouterLink>

          <RouterLink
            to="/roadmap"
            class="page-card card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 p-3 text-center sm:p-4"
          >
            <i class="bi bi-map text-lg text-brand-700" aria-hidden="true"></i>
            <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-stone-600">
              แผนผังห้องเรียน
            </span>
          </RouterLink>
        </div>
      </section>

      <!-- ========================================== -->
      <!-- 6. ภาพรวมห้อง (รหัสห้อง — ไม่กด โดยเจตนา)     -->
      <!-- ========================================== -->
      <div class="page-card p-4 sm:p-5">
        <div class="flex items-center gap-3">
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-buildings text-lg" aria-hidden="true"></i>
          </div>
          <h2 class="section-title min-w-0 truncate">ภาพรวมห้อง</h2>
        </div>

        <dl class="mt-3 space-y-2.5 border-t border-stone-100 pt-3 sm:space-y-3">
          <div class="flex items-center justify-between gap-3">
            <dt class="shrink-0 text-xs font-bold text-stone-500">ชื่อห้อง</dt>
            <dd class="min-w-0 truncate text-sm font-bold text-stone-900">
              {{ authStore.currentRoomName || '—' }}
            </dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="shrink-0 text-xs font-bold text-stone-500">บทบาท</dt>
            <dd class="shrink-0">
              <span class="chip bg-brand-50 text-brand-700">{{ role }}</span>
            </dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="shrink-0 text-xs font-bold text-stone-500">รหัสห้องเรียน</dt>
            <dd class="font-display num min-w-0 truncate text-sm font-bold tracking-widest text-stone-900">
              {{ roomCode }}
            </dd>
          </div>
        </dl>
      </div>
    </template>
  </div>
</template>
