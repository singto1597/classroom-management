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

const fetchTaskCount = async () => {
  try {
    const result = await TaskService.getAllTasks(authStore.currentRoomId!);
    taskCount.value = result.length;
    pendingTaskCount.value = result.filter((task) => task.status === 'pending').length;
  } catch {
    // การ์ดยังแสดงได้โดยไม่ต้องมีตัวเลขถ้าดึงไม่สำเร็จ
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
    <PageHeader
      eyebrow="Classroom Dashboard"
      :title="greetingTitle"
      :description="authStore.currentRoomName || 'ภาพรวมห้องเรียนของคุณ'"
    >
      <template #actions>
        <span class="chip bg-brand-50 text-brand-700">
          <i class="bi bi-person-badge" aria-hidden="true"></i>{{ role }}
        </span>
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
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div class="page-card p-4 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">งานทั้งหมด</p>
        <p
          v-if="isTaskCountLoading"
          class="mt-2 h-7 w-12 animate-pulse rounded-lg bg-stone-100 sm:h-9 sm:w-16"
          aria-hidden="true"
        ></p>
        <p v-else class="font-display num mt-2 text-2xl font-bold text-stone-900 sm:text-3xl">
          {{ taskCount }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-400">รายการในห้องนี้</p>
      </div>

      <div class="page-card p-4 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">งานค้าง</p>
        <p
          v-if="isTaskCountLoading"
          class="mt-2 h-7 w-12 animate-pulse rounded-lg bg-stone-100 sm:h-9 sm:w-16"
          aria-hidden="true"
        ></p>
        <p
          v-else
          class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
          :class="pendingTaskCount > 0 ? 'text-amber-600' : 'text-stone-900'"
        >
          {{ pendingTaskCount }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-400">ยังไม่ปิดงาน</p>
      </div>

      <div class="page-card p-4 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">รหัสห้องเรียน</p>
        <p class="font-display num mt-2 truncate text-2xl font-bold tracking-widest text-stone-900 sm:text-3xl">
          {{ roomCode }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-400">แชร์ให้นักเรียนเข้าร่วม</p>
      </div>

      <div class="page-card p-4 sm:p-5">
        <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">บทบาทของฉัน</p>
        <p class="font-display mt-2 truncate text-xl font-bold text-stone-900 sm:text-2xl">{{ role }}</p>
        <p
          class="mt-1 text-xs font-bold"
          :class="isAdmin ? 'text-emerald-600' : 'text-stone-400'"
        >
          {{ isAdmin ? 'ผู้ดูแลห้องเรียน' : 'สมาชิกในห้อง' }}
        </p>
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

        <div class="mt-4 space-y-2">
          <RouterLink
            to="/tasks"
            class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-3 transition-colors hover:border-stone-300 hover:bg-stone-50 active:scale-[0.99]"
          >
            <div class="flex min-w-0 items-center gap-3">
              <i class="bi bi-card-checklist shrink-0 text-lg text-brand-700" aria-hidden="true"></i>
              <div class="min-w-0">
                <p class="truncate text-sm font-bold text-stone-900">ดูรายการงานทั้งหมด</p>
                <p v-if="taskCount > 0" class="num truncate text-xs font-medium text-stone-500">
                  ยังไม่เสร็จ {{ pendingTaskCount }} / ทั้งหมด {{ taskCount }} ชิ้น
                </p>
              </div>
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

        <div class="mt-4 flex flex-col gap-2 border-t border-stone-100 pt-4 sm:flex-row">
          <RouterLink to="/schedules" class="btn-ghost-ui flex-1">
            <i class="bi bi-calendar-event" aria-hidden="true"></i> ตารางเรียนยืนพื้น
          </RouterLink>
          <RouterLink v-if="canManageTasks" to="/schedules" class="btn-danger flex-1">
            <i class="bi bi-exclamation-triangle" aria-hidden="true"></i> ข้อยกเว้นฉุกเฉิน
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
            <p class="truncate text-xs text-stone-500">ข้อมูลห้องและการเชื่อมต่อ</p>
          </div>
        </div>

        <dl class="mt-4 space-y-3 border-t border-stone-100 pt-4">
          <div class="flex items-center justify-between gap-3">
            <dt class="shrink-0 text-xs font-bold text-stone-500">ชื่อห้อง</dt>
            <dd class="min-w-0 truncate text-sm font-bold text-stone-900">
              {{ authStore.currentRoomName || '—' }}
            </dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="shrink-0 text-xs font-bold text-stone-500">รหัสห้อง</dt>
            <dd class="num shrink-0 text-sm font-bold tracking-widest text-stone-900">{{ roomCode }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="shrink-0 text-xs font-bold text-stone-500">บทบาท</dt>
            <dd class="shrink-0">
              <span class="chip bg-brand-50 text-brand-700">{{ role }}</span>
            </dd>
          </div>
        </dl>

        <div class="mt-4 flex flex-col gap-2 border-t border-stone-100 pt-4">
          <RouterLink to="/discord-connect" class="btn-primary">
            <i class="bi bi-discord" aria-hidden="true"></i> เชื่อมต่อ Discord
          </RouterLink>
          <button type="button" class="btn-ghost-ui" @click="handleChangeRoom">
            <i class="bi bi-arrow-left-right" aria-hidden="true"></i> สลับห้องเรียน
          </button>
        </div>
      </div>
    </div>

    <!-- ========================================== -->
    <!-- 4. ทางลัด — การ์ดขอบบาง ไม่มี gradient       -->
    <!-- ========================================== -->
    <section class="space-y-3">
      <h2 class="section-title">ทางลัด</h2>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <!-- นักเรียน -->
        <div class="page-card p-4 sm:p-5">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
            >
              <i class="bi bi-people text-lg" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <h3 class="section-title truncate">นักเรียน</h3>
              <p class="truncate text-xs text-stone-500">รายชื่อและทะเบียนของห้อง</p>
            </div>
          </div>

          <div class="mt-4 space-y-2">
            <RouterLink
              to="/students"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
            >
              <span class="truncate">ดูรายชื่อเพื่อนทั้งห้อง</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>

            <button
              type="button"
              class="flex w-full items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
              @click="goToMyProfile"
            >
              <span class="truncate">โปรไฟล์ของฉัน</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </button>

            <template v-if="canManageStudents">
              <RouterLink
                to="/students/add"
                class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
              >
                <span class="truncate">เพิ่มนักเรียนใหม่</span>
                <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
              </RouterLink>

              <RouterLink
                to="/students/export"
                class="flex items-center justify-center gap-2 rounded-xl px-3.5 py-2.5 text-xs font-bold text-stone-400 transition-colors hover:bg-stone-50 hover:text-brand-700 active:scale-[0.99]"
              >
                <i class="bi bi-file-earmark-excel-fill" aria-hidden="true"></i>
                สร้างไฟล์ Export (Excel)
              </RouterLink>
            </template>
          </div>
        </div>

        <!-- การเงิน -->
        <div class="page-card p-4 sm:p-5">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
            >
              <i class="bi bi-wallet2 text-lg" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <h3 class="section-title truncate">การเงินห้อง</h3>
              <p class="truncate text-xs text-stone-500">รายรับ-จ่าย โปรเจกต์ และบิล</p>
            </div>
          </div>

          <div class="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <RouterLink
              to="/finance"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
            >
              <span class="truncate">สรุปยอด</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>

            <RouterLink
              to="/finance/transactions"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
            >
              <span class="truncate">ประวัติ</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>

            <RouterLink
              to="/finance/collections"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
            >
              <span class="truncate">โปรเจกต์</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>

            <RouterLink
              v-if="isAdmin"
              to="/finance/debtors"
              class="flex items-center justify-between gap-3 rounded-xl border border-red-200 px-3.5 py-2.5 text-sm font-bold text-red-600 transition-colors hover:bg-red-50 active:scale-[0.99]"
            >
              <span class="truncate">ทวงหนี้</span>
              <i class="bi bi-chevron-right shrink-0 text-red-300" aria-hidden="true"></i>
            </RouterLink>
          </div>
        </div>

        <!-- ประกาศ Discord -->
        <div class="page-card p-4 sm:p-5">
          <div class="flex items-center gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
            >
              <i class="bi bi-broadcast text-lg" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <h3 class="section-title truncate">ประกาศ Discord</h3>
              <p class="truncate text-xs text-stone-500">ส่งประกาศตรงเข้าเซิร์ฟเวอร์ห้อง</p>
            </div>
          </div>

          <div class="mt-4 space-y-2">
            <RouterLink
              to="/messages"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
            >
              <span class="truncate">เขียนประกาศ</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>

            <RouterLink
              to="/discord-connect"
              class="flex items-center justify-between gap-3 rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm font-bold text-stone-600 transition-colors hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 active:scale-[0.99]"
            >
              <span class="truncate">จัดการบอท</span>
              <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
            </RouterLink>
          </div>
        </div>

        <!-- แผนผังห้องเรียน — กดได้ทั้งใบ -->
        <RouterLink
          to="/roadmap"
          class="page-card card-hover flex items-center justify-between gap-3 p-4 sm:p-5"
        >
          <div class="flex min-w-0 items-center gap-3">
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
            >
              <i class="bi bi-map text-lg" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <h3 class="section-title truncate">แผนผังห้องเรียน</h3>
              <p class="truncate text-xs text-stone-500">โครงสร้างการบริหารและ Roadmap การทำงาน</p>
            </div>
          </div>
          <i class="bi bi-arrow-right shrink-0 text-stone-300" aria-hidden="true"></i>
        </RouterLink>
      </div>
    </section>
  </div>
</template>
