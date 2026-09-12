<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue';
import { useRouter } from 'vue-router';
import { isAxiosError } from 'axios';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import type { Student, PendingStudentRequest } from '@/types/student';
import { displayName } from '@/utils/name';
import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import Swal from 'sweetalert2';

const router = useRouter();
const authStore = useAuthStore();
const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

// 🎯 แกะสิทธิ์แบบละเอียดยิบ
const isGodAdmin = computed(() => authStore.isAdmin);
const canManageStudents = computed(() => isGodAdmin.value || authStore.currentPermissions.includes('MANAGE_STUDENTS'));
const canExportStudents = computed(() => isGodAdmin.value || authStore.currentPermissions.includes('EXPORT_STUDENTS'));

// --- States ---
const currentTab = ref<'active' | 'pending'>('active');
const students = ref<Student[]>([]);
const pendingStudents = ref<PendingStudentRequest[]>([]);
const isLoading = ref(true);
const searchQuery = ref('');
const showInactive = ref(false);

// ให้ StateBlock มีสถานะผิดพลาดของตัวเอง (เดิมพึ่ง Swal อย่างเดียว)
const hasError = ref(false);

// --- Dropdown Menu State (จุด 3 จุด) ---
const openDropdown = ref<number | null>(null);

const toggleDropdown = (id: number, event: Event) => {
  event.stopPropagation(); // ป้องกันไม่ให้คลิกทะลุไปโดน Card
  openDropdown.value = openDropdown.value === id ? null : id;
};

const closeDropdown = () => {
  openDropdown.value = null;
};

// ดึงข้อความ error จาก backend แบบปลอดภัย (catch ได้ unknown) — คงรูปแบบเดิมของโปรเจค
// ที่อ่าน detail จาก response ของ axios ไว้
const apiErrorDetail = (error: unknown): string | undefined => {
  if (!isAxiosError<{ detail?: unknown }>(error)) return undefined;
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : undefined;
};

const fetchData = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    const [activeRes, pendingRes] = await Promise.allSettled([
      StudentService.getStudents(currentRoomId),
      canManageStudents.value ? StudentService.getPendingRequests(currentRoomId) : Promise.resolve([])
    ]);

    if (activeRes.status === 'fulfilled') {
      students.value = Array.isArray(activeRes.value) ? activeRes.value : [];
    }
    if (pendingRes.status === 'fulfilled' && canManageStudents.value) {
      pendingStudents.value = Array.isArray(pendingRes.value) ? pendingRes.value : [];
    }
  } catch (error: unknown) {
    hasError.value = true;
    Swal.fire({ icon: 'error', title: 'ข้อผิดพลาด', text: apiErrorDetail(error) || 'ไม่สามารถโหลดข้อมูลได้' });
  } finally {
    isLoading.value = false;
  }
};

const switchTab = (tab: 'active' | 'pending') => {
  currentTab.value = tab;
  closeDropdown();
  fetchData();
};

onMounted(() => {
  fetchData();
  document.addEventListener('click', closeDropdown);
});

onUnmounted(() => {
  document.removeEventListener('click', closeDropdown);
});

// --- Navigation ---
const goToStudent = (studentNo: number) => {
  router.push(`/students/${studentNo}`);
};

const editStudent = (studentNo: number) => {
  closeDropdown();
  router.push(`/students/${studentNo}/edit`);
};

// 🏷️ แปลง class_role
const ROLE_LABELS: Record<string, string> = {
  student: 'นักเรียน',
  president: 'หัวหน้าห้อง',
  vice_president: 'รองหัวหน้าห้อง',
  secretary: 'เลขานุการ',
  vice_academic: 'รองวิชาการ',
  vice_activity: 'รองกิจกรรม',
  vice_discipline: 'รองระเบียบวินัย',
  vice_reception: 'รองปฏิคม',
  vice_pr: 'รองประชาสัมพันธ์',
  vice_sanitation: 'รองสุขาภิบาล',
  staff_academic: 'กรรมการวิชาการ',
  staff_activity: 'กรรมการกิจกรรม',
  staff_discipline: 'กรรมการระเบียบวินัย',
  staff_reception: 'กรรมการปฏิคม',
  staff_pr: 'กรรมการประชาสัมพันธ์',
  staff_sanitation: 'กรรมการสุขาภิบาล',
  treasurer: 'เหรัญญิก'
};

const roleLabel = (role: string) => ROLE_LABELS[role] || role || 'นักเรียน';

const filteredStudents = computed(() => {
  if (!students.value || students.value.length === 0) return [];

  return students.value.filter((student) => {
    if (!showInactive.value && student.status === 'inactive') return false;

    const query = searchQuery.value.toLowerCase().trim();
    if (!query) return true;

    const fullName = `${student.first_name || ''} ${student.last_name || ''} ${student.first_name_en || ''} ${student.last_name_en || ''}`.toLowerCase();
    const studentNo = student.student_no?.toString() || '';
    const studentId = student.student_id?.toString().toLowerCase() || '';
    const nickname = `${student.nickname || ''} ${student.nickname_en || ''}`.toLowerCase();

    return fullName.includes(query) || studentNo.includes(query) || studentId.includes(query) || nickname.includes(query);
  });
});

const confirmDelete = async (student: Student) => {
  closeDropdown();
  if (!canManageStudents.value) return;

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    text: `ลบ ${displayName(student)} (เลขที่ ${student.student_no}) ใช่หรือไม่?`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await StudentService.deleteStudent(currentRoomId, student.student_no, currentUserName);
      Swal.fire({ title: 'ลบสำเร็จ', icon: 'success', timer: 1500, showConfirmButton: false });
      fetchData();
    } catch (error: unknown) {
      Swal.fire('ลบไม่สำเร็จ', apiErrorDetail(error), 'error');
    }
  }
};

const approveJoin = async (studentNo: number) => {
  try {
    await StudentService.approveStudent(currentRoomId, studentNo);
    await fetchData();
    Swal.fire({ title: 'อนุมัติสำเร็จ', icon: 'success', timer: 1500, showConfirmButton: false });
  } catch (error: unknown) {
    Swal.fire('ข้อผิดพลาด', apiErrorDetail(error), 'error');
  }
};

const rejectJoin = async (studentNo: number) => {
  const result = await Swal.fire({
    title: 'ปฏิเสธคำขอ?',
    text: 'คำขอนี้จะถูกลบออกจากระบบ',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ปฏิเสธ',
    cancelButtonText: 'ยกเลิก'
  });
  if (result.isConfirmed) {
    try {
      await StudentService.rejectStudent(currentRoomId, studentNo);
      await fetchData();
    } catch (error: unknown) {
      Swal.fire('ข้อผิดพลาด', apiErrorDetail(error), 'error');
    }
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">

    <PageHeader
      eyebrow="Academic Records"
      title="จัดการนักเรียน"
      description="รายชื่อนักเรียนทั้งหมดในห้องนี้ พร้อมคำขอเข้าร่วมที่รออนุมัติ"
    >
      <template #actions>
        <RouterLink
          v-if="canExportStudents"
          to="/students/export"
          class="btn-ghost-ui"
          aria-label="ส่งออกข้อมูลนักเรียนเป็น Excel"
        >
          <i class="bi bi-file-earmark-excel-fill text-base" aria-hidden="true"></i>
          <span class="hidden sm:inline">ส่งออก</span>
        </RouterLink>
        <RouterLink v-if="canManageStudents" to="/students/add" class="btn-primary">
          <i class="bi bi-person-plus-fill" aria-hidden="true"></i> เพิ่มนักเรียน
        </RouterLink>
      </template>
    </PageHeader>

    <!-- แท็บ: นักเรียนปัจจุบัน / รออนุมัติ -->
    <div v-if="canManageStudents" class="flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl border border-stone-200 bg-stone-50 p-1">
      <button
        type="button"
        class="flex shrink-0 items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
        :class="currentTab === 'active'
          ? 'border-stone-200 bg-white text-brand-700'
          : 'border-transparent text-stone-500 hover:text-stone-800'"
        @click="switchTab('active')"
      >
        นักเรียนปัจจุบัน
      </button>
      <button
        type="button"
        class="flex shrink-0 items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
        :class="currentTab === 'pending'
          ? 'border-stone-200 bg-white text-brand-700'
          : 'border-transparent text-stone-500 hover:text-stone-800'"
        @click="switchTab('pending')"
      >
        รออนุมัติ
        <span v-if="pendingStudents.length > 0" class="chip num bg-amber-100 text-amber-700">
          {{ pendingStudents.length }}
        </span>
      </button>
    </div>

    <!-- ค้นหา + ตัวกรอง -->
    <div
      v-if="currentTab === 'active'"
      class="page-card flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between sm:p-4"
    >
      <div class="relative min-w-0 flex-1">
        <i
          class="bi bi-search pointer-events-none absolute inset-y-0 start-0 flex w-10 items-center justify-center text-stone-400"
          aria-hidden="true"
        ></i>
        <input
          v-model="searchQuery"
          type="text"
          class="field ps-10"
          placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..."
          aria-label="ค้นหานักเรียน"
        />
      </div>

      <div class="flex shrink-0 items-center border-t border-stone-100 pt-3 sm:border-t-0 sm:pt-0">
        <label class="flex cursor-pointer select-none items-center">
          <input v-model="showInactive" type="checkbox" class="peer sr-only" />
          <span
            class="relative h-5 w-10 shrink-0 rounded-full bg-stone-200 transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-brand-700 peer-checked:after:translate-x-full"
            aria-hidden="true"
          ></span>
          <span class="ms-2.5 text-sm font-bold text-stone-600">แสดง Inactive</span>
        </label>
      </div>
    </div>

    <!-- โหลด -->
    <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />

    <!-- ผิดพลาด -->
    <StateBlock v-else-if="hasError" variant="error" @retry="fetchData" />

    <!-- ====================== TAB: ACTIVE ====================== -->
    <template v-else-if="currentTab === 'active'">
      <StateBlock
        v-if="filteredStudents.length === 0"
        variant="empty"
        title="ไม่พบข้อมูลนักเรียน"
        :hint="searchQuery ? 'ลองปรับคำค้นหา หรือเปิดตัวกรอง Inactive ดูอีกครั้ง' : 'เพิ่มนักเรียนคนแรกเพื่อเริ่มต้นทะเบียนห้องนี้'"
      />

      <template v-else>
        <!-- 🖥️ Desktop: ตารางเต็ม (ไม่ครอบ overflow เพื่อให้เมนูจัดการล้นออกได้) -->
        <div class="page-card hidden lg:block">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-16 rounded-ss-2xl">เลขที่</th>
                <th>ชื่อ-นามสกุล</th>
                <th class="hidden xl:table-cell">ชื่อเล่น</th>
                <th>บทบาท</th>
                <th>สถานะ</th>
                <th class="w-20 rounded-se-2xl text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="student in filteredStudents"
                :key="student.id"
                class="cursor-pointer"
                :class="{ 'opacity-60': student.status === 'inactive' }"
                @click="goToStudent(student.student_no)"
              >
                <td class="num font-bold text-stone-900">{{ student.student_no }}</td>

                <td>
                  <div class="flex min-w-0 items-center gap-2">
                    <span class="truncate font-bold text-stone-900">
                      {{ student.prefix ? student.prefix + ' ' : '' }}{{ displayName(student) }}
                    </span>
                    <i
                      v-if="student.is_admin"
                      class="bi bi-shield-lock-fill shrink-0 text-amber-500"
                      title="System Admin"
                      aria-hidden="true"
                    ></i>
                    <!-- 🛡️ Consent Model: สมาชิกที่ยังไม่ได้ยืนยันตัวตน → ข้อมูลส่วนตัวถูกปิดบัง -->
                    <span
                      v-if="student.identity_claimed === false"
                      class="chip shrink-0 bg-stone-100 text-stone-500"
                      title="ยังไม่ได้ยืนยันตัวตน — ข้อมูลส่วนตัวถูกปิดบัง"
                    >
                      <i class="bi bi-lock-fill" aria-hidden="true"></i> ยังไม่ยืนยันตัวตน
                    </span>
                  </div>
                </td>

                <td class="text-stone-500">
                  <span class="block truncate">{{ student.nickname || student.nickname_en || '-' }}</span>
                </td>

                <td>
                  <span
                    class="chip"
                    :class="student.class_role && student.class_role !== 'student'
                      ? 'bg-brand-50 text-brand-700'
                      : 'bg-stone-100 text-stone-600'"
                  >
                    {{ roleLabel(student.class_role) }}
                  </span>
                </td>

                <td>
                  <span
                    class="chip"
                    :class="{
                      'bg-emerald-50 text-emerald-700': student.status === 'active',
                      'bg-amber-50 text-amber-700': student.status === 'pending',
                      'bg-stone-100 text-stone-600': student.status === 'inactive'
                    }"
                  >
                    <i
                      class="bi"
                      :class="{
                        'bi-check-circle-fill': student.status === 'active',
                        'bi-clock-fill': student.status === 'pending',
                        'bi-dash-circle-fill': student.status === 'inactive'
                      }"
                      aria-hidden="true"
                    ></i>
                    {{ student.status === 'active' ? 'Active' : student.status === 'pending' ? 'รออนุมัติ' : 'Inactive' }}
                  </span>
                </td>

                <td class="text-right">
                  <div class="relative flex justify-end">
                    <button
                      v-if="canManageStudents"
                      type="button"
                      class="flex h-9 w-9 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700 active:scale-[0.97]"
                      aria-label="ตัวเลือกจัดการนักเรียน"
                      @click.stop="toggleDropdown(student.student_no, $event)"
                    >
                      <i class="bi bi-three-dots-vertical text-lg" aria-hidden="true"></i>
                    </button>
                    <i v-else class="bi bi-chevron-right p-2 text-stone-300" aria-hidden="true"></i>

                    <transition name="fade">
                      <div
                        v-if="openDropdown === student.student_no"
                        class="absolute right-0 top-11 z-20 w-36 origin-top-right overflow-hidden rounded-xl border border-stone-200 bg-white py-1"
                        @click.stop
                      >
                        <button
                          type="button"
                          class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm font-bold text-stone-700 transition-colors hover:bg-stone-50"
                          @click.stop="editStudent(student.student_no)"
                        >
                          <i class="bi bi-pencil-square" aria-hidden="true"></i> แก้ไข
                        </button>
                        <div class="mx-2 my-1 h-px bg-stone-100"></div>
                        <button
                          type="button"
                          class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm font-bold text-red-600 transition-colors hover:bg-red-50"
                          @click.stop="confirmDelete(student)"
                        >
                          <i class="bi bi-trash" aria-hidden="true"></i> ลบข้อมูล
                        </button>
                      </div>
                    </transition>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 📱 มือถือ: การ์ดเรียงแนวตั้ง -->
        <div class="space-y-2.5 lg:hidden">
          <div
            v-for="student in filteredStudents"
            :key="student.id"
            class="page-card card-hover relative p-4"
            :class="{ 'opacity-60': student.status === 'inactive' }"
            @click="goToStudent(student.student_no)"
          >
            <div class="flex items-start gap-3">
              <!-- avatar ตัวอักษรแรก -->
              <div
                class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 font-display text-base font-bold text-brand-700"
                aria-hidden="true"
              >
                {{ displayName(student).charAt(0) || '?' }}
              </div>

              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <p class="truncate font-display text-[15px] font-bold text-stone-900">
                    {{ student.prefix ? student.prefix + ' ' : '' }}{{ displayName(student) }}
                  </p>
                  <i
                    v-if="student.is_admin"
                    class="bi bi-shield-lock-fill shrink-0 text-xs text-amber-500"
                    title="System Admin"
                    aria-hidden="true"
                  ></i>
                </div>

                <p class="num mt-0.5 truncate text-xs text-stone-500">
                  เลขที่ {{ student.student_no }}
                  <span v-if="student.nickname || student.nickname_en"> · {{ student.nickname || student.nickname_en }}</span>
                </p>

                <div class="mt-2 flex flex-wrap items-center gap-1.5">
                  <span
                    class="chip"
                    :class="student.class_role && student.class_role !== 'student'
                      ? 'bg-brand-50 text-brand-700'
                      : 'bg-stone-100 text-stone-600'"
                  >
                    {{ roleLabel(student.class_role) }}
                  </span>

                  <span
                    class="chip"
                    :class="{
                      'bg-emerald-50 text-emerald-700': student.status === 'active',
                      'bg-amber-50 text-amber-700': student.status === 'pending',
                      'bg-stone-100 text-stone-600': student.status === 'inactive'
                    }"
                  >
                    <i
                      class="bi"
                      :class="{
                        'bi-check-circle-fill': student.status === 'active',
                        'bi-clock-fill': student.status === 'pending',
                        'bi-dash-circle-fill': student.status === 'inactive'
                      }"
                      aria-hidden="true"
                    ></i>
                    {{ student.status === 'active' ? 'Active' : student.status === 'pending' ? 'รออนุมัติ' : 'Inactive' }}
                  </span>

                  <!-- 🛡️ Consent Model: ยังไม่ยืนยันตัวตน → ข้อมูลส่วนตัวถูกปิดบัง -->
                  <span
                    v-if="student.identity_claimed === false"
                    class="chip bg-stone-100 text-stone-500"
                    title="ยังไม่ได้ยืนยันตัวตน — ข้อมูลส่วนตัวถูกปิดบัง"
                  >
                    <i class="bi bi-lock-fill" aria-hidden="true"></i> ยังไม่ยืนยันตัวตน
                  </span>
                </div>
              </div>

              <!-- เมนูจัดการ -->
              <div v-if="canManageStudents" class="relative shrink-0">
                <button
                  type="button"
                  class="flex h-11 w-11 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700 active:scale-[0.97]"
                  aria-label="ตัวเลือกจัดการนักเรียน"
                  @click.stop="toggleDropdown(student.student_no, $event)"
                >
                  <i class="bi bi-three-dots-vertical text-lg" aria-hidden="true"></i>
                </button>

                <transition name="fade">
                  <div
                    v-if="openDropdown === student.student_no"
                    class="absolute right-0 top-11 z-20 w-36 origin-top-right overflow-hidden rounded-xl border border-stone-200 bg-white py-1"
                    @click.stop
                  >
                    <button
                      type="button"
                      class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm font-bold text-stone-700 transition-colors hover:bg-stone-50"
                      @click.stop="editStudent(student.student_no)"
                    >
                      <i class="bi bi-pencil-square" aria-hidden="true"></i> แก้ไข
                    </button>
                    <div class="mx-2 my-1 h-px bg-stone-100"></div>
                    <button
                      type="button"
                      class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm font-bold text-red-600 transition-colors hover:bg-red-50"
                      @click.stop="confirmDelete(student)"
                    >
                      <i class="bi bi-trash" aria-hidden="true"></i> ลบข้อมูล
                    </button>
                  </div>
                </transition>
              </div>

              <i v-else class="bi bi-chevron-right shrink-0 p-2 text-stone-300" aria-hidden="true"></i>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ====================== TAB: PENDING ====================== -->
    <template v-else-if="currentTab === 'pending'">
      <StateBlock
        v-if="pendingStudents.length === 0"
        variant="empty"
        title="ไม่มีคำขอที่รออนุมัติ"
        hint="เมื่อมีนักเรียนขอเข้าร่วมห้อง รายการคำขอจะแสดงที่นี่"
      />

      <div v-else class="space-y-2.5">
        <div
          v-for="req in pendingStudents"
          :key="req.student_no"
          class="page-card border-s-4 border-s-amber-400 p-4"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <!-- ซ้าย: ข้อมูล -->
            <div class="flex min-w-0 items-start gap-3">
              <div
                class="num flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-50 font-display text-base font-bold text-amber-700"
              >
                {{ req.student_no }}
              </div>

              <div class="min-w-0 flex-1">
                <!-- 🛡️ claim_request: มีคนขออ้างสิทธิ์ ghost → แอดมินเห็นชื่อเดิม vs ชื่อผู้ขอ แล้วตัดสิน -->
                <template v-if="req.request_type === 'claim_request'">
                  <p class="truncate font-display text-[15px] font-bold leading-snug text-stone-900">
                    {{ displayName(req) }} <span class="text-amber-700">อ้างสิทธิ์เลขที่นี้</span>
                  </p>
                  <p class="mt-0.5 text-sm text-stone-500">
                    ชื่อในระบบเดิม: <span class="font-bold text-stone-700">{{ req.ghost_first_name || '-' }} {{ req.ghost_last_name || '-' }}</span>
                    <span
                      v-if="req.name_match !== undefined"
                      class="chip ms-1.5"
                      :class="req.name_match ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'"
                    >
                      {{ req.name_match ? 'ชื่อตรงกัน' : 'ชื่อไม่ตรง' }}
                    </span>
                  </p>
                  <p class="mt-0.5 text-xs text-stone-400">
                    <i class="bi bi-person-check me-1" aria-hidden="true"></i>ผู้ขอ: {{ displayName(req) }} — ตรวจสอบว่าเป็นคนเดียวกันก่อนอนุมัติ
                  </p>
                </template>

                <!-- 🛡️ invite_pending: แอดมินแอดชื่อให้ (บัญชีจริง) → รอเจ้าตัวกดรับ แอดมินอนุมัติแทนไม่ได้ -->
                <template v-else-if="req.request_type === 'invite_pending'">
                  <p class="truncate font-display text-[15px] font-bold leading-snug text-stone-900">
                    {{ displayName(req) }}
                  </p>
                  <p class="mt-0.5 flex items-center gap-1.5 text-sm text-stone-500">
                    <i class="bi bi-envelope text-amber-600" aria-hidden="true"></i> คำเชิญที่เพิ่มให้ — รอเจ้าตัวกดรับ ข้อมูลส่วนตัวจะเปิดให้ห้องดูเมื่อยืนยันแล้ว
                  </p>
                </template>

                <!-- join_request: ขอเข้าห้องเอง ปกติ -->
                <template v-else>
                  <p class="truncate font-display text-[15px] font-bold leading-snug text-stone-900">
                    {{ displayName(req) }}
                  </p>
                  <p class="mt-0.5 flex items-center gap-1.5 text-sm text-stone-500">
                    <i class="bi bi-clock text-stone-400" aria-hidden="true"></i> ขอเข้าร่วมเมื่อ {{ new Date(req.created_at).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok', dateStyle: 'short', timeStyle: 'short' }) }}
                  </p>
                </template>
              </div>
            </div>

            <!-- ขวา: ปุ่มจัดการ (invite_pending แอดมินทำอะไรไม่ได้ ต้องรอเจ้าตัว) -->
            <div v-if="req.request_type !== 'invite_pending'" class="flex gap-2 sm:shrink-0">
              <button type="button" class="btn-danger flex-1 sm:flex-none" @click="rejectJoin(req.student_no)">
                <i class="bi bi-x-lg" aria-hidden="true"></i> ปฏิเสธ
              </button>
              <button type="button" class="btn-primary flex-1 sm:flex-none" @click="approveJoin(req.student_no)">
                <i class="bi bi-check-lg" aria-hidden="true"></i> ยอมรับ
              </button>
            </div>
            <div
              v-else
              class="flex shrink-0 items-center gap-1.5 rounded-xl bg-stone-50 px-4 py-2.5 text-xs font-bold text-stone-500"
            >
              <i class="bi bi-hourglass-split" aria-hidden="true"></i> รอการยืนยันจากนักเรียน
            </div>
          </div>
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
/* Animation สำหรับ Dropdown ตอนเด้งขึ้นมา */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: scale(0.95);
}
</style>
