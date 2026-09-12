<script setup lang="ts">
defineOptions({ name: 'DashboardView' });

import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import { TaskService } from '@/services/task';
import PageHeader from '@/components/ui/PageHeader.vue';
import Swal from 'sweetalert2';

const router = useRouter();
const authStore = useAuthStore();

// ✨ ระบบชื่อใหม่ ดึงจาก authStore โดยตรง
const userName = computed(() => authStore.currentUserName || 'ผู้ใช้งาน');
// ⏰ ทักทายตามช่วงเวลาไทย (UTC+7 คงที่ ไม่มี DST) — เปลี่ยนแค่ถ้อยคำบนหัวหน้า ไม่ใช่ข้อมูล
const greeting = computed(() => {
  const bangkokHour = new Date(Date.now() + 7 * 60 * 60 * 1000).getUTCHours();
  if (bangkokHour < 12) return 'สวัสดีตอนเช้า';
  if (bangkokHour < 17) return 'สวัสดีตอนบ่าย';
  return 'สวัสดีตอนเย็น';
});
const greetingTitle = computed(() => `${greeting.value}, ${userName.value}`);
// บทบาทเป็นภาษาไทย ผ่าน computed จาก store (รองรับ class_role ทุกตำแหน่ง)
const role = computed(() => authStore.currentRoleLabel);
const isAdmin = computed(() => authStore.isAdmin);

// ✨ สิทธิ์ละเอียดสำหรับการ์ด (ให้ตรงกับหน้า StudentList)
const canManageStudents = computed(() => isAdmin.value || authStore.currentPermissions.includes('MANAGE_STUDENTS'));
const canManageTasks = computed(() => isAdmin.value || authStore.currentPermissions.includes('MANAGE_CLASSROOM_TASKS'));

// ✨ ดึง roomCode จาก Store
const roomCode = computed(() => authStore.currentRoomCode || 'ไม่มีรหัส');

// ✨ นับจำนวนงานในห้อง เพื่อแสดงบนการ์ดตารางและงาน
const taskCount = ref(0);
const pendingTaskCount = ref(0);
// แยกสถานะโหลดของตัวเลขออกจากตัวหน้า — ระหว่างรอต้องไม่โชว์ 0 เพราะอ่านผิดความหมาย
const isTaskCountLoading = ref(true);
// ดึงไม่สำเร็จต้องไม่โชว์ 0 หลอก ๆ — ตัวเลขที่ไม่รู้แสดงเป็น "—" แทน
const isTaskCountError = ref(false);

// สีของตัวเลขงานค้าง — เทาเมื่อไม่รู้ค่า, เหลืองเมื่อมีงานค้าง, ดำเมื่อไม่มี
const pendingCountClass = computed(() => {
  if (isTaskCountError.value) return 'text-stone-400';
  return pendingTaskCount.value > 0 ? 'text-amber-600' : 'text-stone-900';
});

const fetchTaskCount = async () => {
  try {
    const result = await TaskService.getAllTasks(authStore.currentRoomId!);
    taskCount.value = result.length;
    pendingTaskCount.value = result.filter((task) => task.status === 'pending').length;
  } catch {
    // การ์ดยังแสดงได้โดยไม่ต้องมีตัวเลขถ้าดึงไม่สำเร็จ
    isTaskCountError.value = true;
  } finally {
    isTaskCountLoading.value = false;
  }
};

onMounted(fetchTaskCount);

// ✨ ฟีเจอร์สลับห้องเรียน (กลับไปหน้า lobby)
const handleChangeRoom = () => {
  authStore.clearRoom();
  router.push('/lobby');
};

const goToMyProfile = async () => {
  try {
    Swal.fire({
      title: 'กำลังดึงข้อมูล...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading()
    });
    const myProfile = await StudentService.getMyProfile(authStore.currentRoomId!);
    Swal.close();
    router.push(`/students/${myProfile.student_no}`);
  } catch {
    Swal.fire({
      icon: 'warning',
      title: 'ข้อผิดพลาด',
      text: 'ไม่สามารถเข้าถึงโปรไฟล์ได้ (คุณอาจเป็นผู้ดูแลระบบที่ไม่ได้มีชื่อในทะเบียนนักเรียน)',
      confirmButtonColor: '#1d4ed8',
      confirmButtonText: 'รับทราบ'
    });
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <!-- ========================================== -->
    <!-- 1. หัวหน้าแบบบรรณาธิการ                     -->
    <!-- ========================================== -->
    <PageHeader eyebrow="Classroom Dashboard" :title="greetingTitle">
      <template #actions>
        <button type="button" class="btn-ghost-ui" title="สลับห้องเรียน" @click="handleChangeRoom">
          <i class="bi bi-arrow-left-right" aria-hidden="true"></i>
          <span class="hidden sm:inline">สลับห้องเรียน</span>
          <span class="sm:hidden">สลับห้อง</span>
        </button>
      </template>
    </PageHeader>

    <!-- ========================================== -->
    <!-- 2. KPI — พื้นขาว ขอบบาง ตัวเลข font-display -->
    <!-- ========================================== -->
    <!-- บทบาทของฉัน ย้ายไปอยู่ที่การ์ด "ภาพรวมห้อง" ที่เดียว ไม่ซ้ำสามที่เหมือนเดิม -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <div class="page-card p-3.5 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">งานทั้งหมด</p>
        <p
          v-if="isTaskCountLoading"
          class="mt-2 h-7 w-12 rounded-lg bg-stone-100 sm:h-9 sm:w-16"
          aria-hidden="true"
        ></p>
        <p
          v-else
          class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
          :class="isTaskCountError ? 'text-stone-400' : 'text-stone-900'"
        >
          {{ isTaskCountError ? '—' : taskCount }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-400">รายการในห้องนี้</p>
      </div>

      <div class="page-card p-3.5 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">งานค้าง</p>
        <p
          v-if="isTaskCountLoading"
          class="mt-2 h-7 w-12 rounded-lg bg-stone-100 sm:h-9 sm:w-16"
          aria-hidden="true"
        ></p>
        <p
          v-else
          class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
          :class="pendingCountClass"
        >
          {{ isTaskCountError ? '—' : pendingTaskCount }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-400">ยังไม่ปิดงาน</p>
      </div>

      <div class="page-card col-span-2 p-3.5 sm:col-span-1 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">รหัสห้องเรียน</p>
        <p class="font-display num mt-2 truncate text-2xl font-bold tracking-widest text-stone-900 sm:text-3xl">
          {{ roomCode }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-400">แชร์ให้นักเรียนเข้าร่วม</p>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- 3. การ์ดหลัก — งานที่ต้องทำ (2) + ภาพรวมห้อง (1) -->
    <!-- ========================================== -->
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3 sm:gap-5">
      <!-- งานที่ต้องทำ -->
      <div class="page-card p-4 sm:p-5 lg:col-span-2">
        <div class="flex items-center gap-3">
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-clipboard-check text-lg" aria-hidden="true"></i>
          </div>
          <div class="min-w-0">
            <h2 class="section-title truncate">งานที่ต้องทำ</h2>
            <p class="truncate text-xs text-stone-500">งาน โน้ต และตารางเรียนของห้องนี้</p>
          </div>
        </div>

        <div class="mt-3 space-y-2 sm:mt-4">
          <RouterLink
            to="/tasks"
            class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-3 transition-colors hover:border-stone-300 hover:bg-stone-50 active:scale-[0.99]"
          >
            <div class="flex min-w-0 items-center gap-3">
              <i class="bi bi-card-checklist shrink-0 text-lg text-brand-700" aria-hidden="true"></i>
              <p class="min-w-0 truncate text-sm font-bold text-stone-900">ดูรายการงานทั้งหมด</p>
            </div>
            <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
          </RouterLink>

          <RouterLink
            v-if="canManageTasks"
            to="/tasks/add"
            class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-3 transition-colors hover:border-stone-300 hover:bg-stone-50 active:scale-[0.99]"
          >
            <div class="flex min-w-0 items-center gap-3">
              <i class="bi bi-plus-lg shrink-0 text-lg text-brand-700" aria-hidden="true"></i>
              <p class="truncate text-sm font-bold text-stone-900">เพิ่มงาน / โน้ตใหม่</p>
            </div>
            <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
          </RouterLink>

          <div
            v-else
            class="rounded-xl border border-dashed border-stone-200 px-3.5 py-3 text-center text-xs font-bold text-stone-400"
          >
            <i class="bi bi-lock-fill me-1.5" aria-hidden="true"></i> เฉพาะผู้ดูแลที่เพิ่มงานได้
          </div>
        </div>

        <div class="mt-3 flex gap-2 border-t border-stone-100 pt-3 sm:mt-4 sm:pt-4">
          <RouterLink to="/schedules" class="btn-ghost-ui min-w-0 flex-1">
            <i class="bi bi-calendar-event shrink-0" aria-hidden="true"></i> ตารางเรียน
          </RouterLink>
          <RouterLink v-if="canManageTasks" to="/schedules" class="btn-ghost-ui min-w-0 flex-1">
            <i class="bi bi-exclamation-triangle shrink-0" aria-hidden="true"></i> ข้อยกเว้น
          </RouterLink>
        </div>
      </div>

      <!-- ภาพรวมห้อง -->
      <div class="page-card p-4 sm:p-5">
        <div class="flex items-center gap-3">
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-buildings text-lg" aria-hidden="true"></i>
          </div>
          <div class="min-w-0">
            <h2 class="section-title truncate">ภาพรวมห้อง</h2>
          </div>
        </div>

        <dl class="mt-3 space-y-2.5 border-t border-stone-100 pt-3 sm:mt-4 sm:space-y-3 sm:pt-4">
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
        </dl>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- 4. ทางลัด — การ์ดขอบบาง ไม่มี gradient       -->
    <!-- ========================================== -->
    <section class="space-y-3">
      <h2 class="section-title">ทางลัด</h2>

      <!-- แผงทางลัดแบบแน่น: ไอคอน + ป้ายสั้น อ่านจบใน 2–3 แถวแทนการ์ดสูง ๆ ที่มีลิสต์ซ้อนใน -->
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
          class="card-hover flex min-w-0 flex-col items-center justify-center gap-1.5 rounded-2xl border border-red-200 bg-white p-3 text-center sm:p-4"
        >
          <i class="bi bi-exclamation-triangle text-lg text-red-500" aria-hidden="true"></i>
          <span class="w-full min-w-0 break-words text-xs font-bold leading-snug text-red-600">
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
  </div>
</template>
