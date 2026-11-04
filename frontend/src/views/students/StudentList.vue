<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { isAxiosError } from 'axios';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import type { Student, PendingStudentRequest } from '@/types/student';
import { displayName } from '@/utils/name';
import { avatarInitial } from '@/utils/avatar';
import { formatThaiDateTime } from '@/utils/datetime';
import PageIntro from '@/components/ui/PageIntro.vue';
import AppTabs from '@/components/ui/AppTabs.vue';
import type { AppTabItem } from '@/components/ui/AppTabs.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import RowActionMenu from '@/components/ui/RowActionMenu.vue';
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue';
import { useDialog } from '@/composables/useDialog';
import { studentStatusLabel } from '@/constants/statusLabels'

const router = useRouter();
const authStore = useAuthStore();
const dialog = useDialog();
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
const tabs = computed<AppTabItem[]>(() => [
  { value: 'active', label: 'นักเรียน' },
  { value: 'pending', label: 'รออนุมัติ', count: pendingStudents.value.length || undefined },
]);

// ให้ StateBlock มีสถานะผิดพลาดของตัวเอง (เดิมพึ่ง Swal อย่างเดียว)
const hasError = ref(false);

// 🔒 เมนูจุด 3 จุดใช้ `RowActionMenu` กลาง — เดิมมี dropdown ที่นี่ 2 สำเนา
//    (ตารางเดสก์ท็อป + การ์ดมือถือ) และแต่ละสำเนาเป็น `absolute` ในตารางที่ `overflow-hidden`
//    ⇒ แถวล่างสุดของตารางเห็นเมนูถูกตัดหาย
//    ปิดเองเมื่อคลิกนอก/Esc/scroll ให้แล้ว ไม่ต้องมี listener ที่ `document` อีก
const studentMenuItems = (student: Student): RowActionItem[] => [
  // มี `to` ⇒ RowActionMenu เรนเดอร์เป็น RouterLink เอง ไม่ต้องดักที่ @select
  {
    key: 'edit',
    label: 'แก้ไขข้อมูล',
    icon: 'bi-pencil-square',
    to: `/students/${student.student_no}/edit`,
  },
  { key: 'delete', label: 'ลบข้อมูล', icon: 'bi-trash3-fill', tone: 'danger' },
];

const handleStudentAction = (student: Student, key: string) => {
  if (key === 'delete') void confirmDelete(student);
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
    } else {
      // Promise.allSettled ไม่ throw — ต้องเช็คสถานะเอง ไม่งั้นโหลดพังแล้วผู้ใช้เห็นเป็น "ไม่มีนักเรียน"
      hasError.value = true;
    }
    if (pendingRes.status === 'fulfilled' && canManageStudents.value) {
      pendingStudents.value = Array.isArray(pendingRes.value) ? pendingRes.value : [];
    }
  } catch (error: unknown) {
    hasError.value = true;
    void dialog.alert('ข้อผิดพลาด', apiErrorDetail(error) || 'ไม่สามารถโหลดข้อมูลได้', 'error');
  } finally {
    isLoading.value = false;
  }
};

const switchTab = (tab: string) => {
  currentTab.value = tab === 'pending' ? 'pending' : 'active';
  fetchData();
};

onMounted(fetchData);

// --- Navigation ---
const goToStudent = (studentNo: number) => {
  router.push(`/students/${studentNo}`);
};

// 🏷️ แปลง class_role
const ROLE_LABELS: Record<string, string> = {
  student: 'นักเรียน',
  president: 'หัวหน้าห้อง',
  vice_president: 'รองหัวหน้าห้อง',
  secretary: 'เลขานุการ (เรขา)',
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

// 🚪 รายชื่อว่างมีสามสาเหตุ — แต่ละสาเหตุต้องมี "ทางออก" คนละปุ่ม
// (เดิมใช้ hint ก้อนเดียว ⇒ คนที่กรองจนไม่เจอได้รับคำแนะนำให้ "เพิ่มนักเรียนคนแรก")
const inactiveCount = computed(
  () => students.value.filter((student) => student.status === 'inactive').length
);

const emptyState = computed(() => {
  if (searchQuery.value.trim()) {
    return {
      title: 'ไม่พบนักเรียนที่ค้นหา',
      hint: 'ลองใช้คำสั้นลง หรือล้างคำค้นหาเพื่อดูรายชื่อทั้งหมด',
      action: 'clearSearch' as const,
      actionLabel: 'ล้างคำค้นหา'
    };
  }

  if (!showInactive.value && inactiveCount.value > 0) {
    return {
      title: 'ยังไม่มีนักเรียนที่กำลังเรียน',
      hint: `มีนักเรียนที่พ้นสภาพ ${inactiveCount.value} คนซ่อนอยู่ใต้ตัวกรอง เปิดตัวกรองเพื่อดูรายชื่อ`,
      action: 'showInactive' as const,
      actionLabel: 'แสดงนักเรียนที่พ้นสภาพ'
    };
  }

  return {
    title: 'ยังไม่มีนักเรียนในห้องนี้',
    hint: 'เพิ่มนักเรียนคนแรกเพื่อเริ่มต้นทะเบียนห้องนี้',
    action: null,
    actionLabel: ''
  };
});

const runEmptyAction = () => {
  if (emptyState.value.action === 'clearSearch') searchQuery.value = '';
  else if (emptyState.value.action === 'showInactive') showInactive.value = true;
};

const confirmDelete = async (student: Student) => {
  if (!canManageStudents.value) return;

  const result = await dialog.confirm(
    'ยืนยันการลบ?',
    `ลบ ${displayName(student)} (เลขที่ ${student.student_no}) ใช่หรือไม่?`,
    { icon: 'warning', danger: true, confirmButtonText: 'ลบข้อมูล' }
  );

  if (result.isConfirmed) {
    try {
      await StudentService.deleteStudent(currentRoomId, student.student_no, currentUserName);
      void dialog.notify('ลบสำเร็จ');
      fetchData();
    } catch (error: unknown) {
      void dialog.alert('ลบไม่สำเร็จ', apiErrorDetail(error), 'error');
    }
  }
};

const approveJoin = async (studentNo: number) => {
  try {
    await StudentService.approveStudent(currentRoomId, studentNo);
    await fetchData();
    void dialog.notify('อนุมัติสำเร็จ');
  } catch (error: unknown) {
    void dialog.alert('ข้อผิดพลาด', apiErrorDetail(error), 'error');
  }
};

const rejectJoin = async (studentNo: number) => {
  const result = await dialog.confirm('ปฏิเสธคำขอ?', 'คำขอนี้จะถูกลบออกจากระบบ', {
    icon: 'warning',
    danger: true,
    confirmButtonText: 'ปฏิเสธ'
  });
  if (result.isConfirmed) {
    try {
      await StudentService.rejectStudent(currentRoomId, studentNo);
      await fetchData();
    } catch (error: unknown) {
      void dialog.alert('ข้อผิดพลาด', apiErrorDetail(error), 'error');
    }
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">

    <PageIntro
      description="รายชื่อนักเรียนในห้องนี้"
    >
      <template #actions>
        <RouterLink
          v-if="canExportStudents"
          to="/students/export"
          class="btn-ghost-ui"
          aria-label="ส่งออกข้อมูลนักเรียนเป็น Excel"
        >
          <i class="bi bi-file-earmark-excel-fill text-base" aria-hidden="true"></i>
          <span>ส่งออก</span>
        </RouterLink>
        <RouterLink
          v-if="canManageStudents"
          to="/students/add"
          class="btn-primary hidden lg:inline-flex"
        >
          <i class="bi bi-person-plus-fill" aria-hidden="true"></i> เพิ่มนักเรียน
        </RouterLink>
      </template>
    </PageIntro>

    <!-- แท็บ: ทะเบียนนักเรียน / คำขอรออนุมัติ -->
    <AppTabs
      v-if="canManageStudents"
      :model-value="currentTab"
      :tabs="tabs"
      group-label="มุมมองรายชื่อนักเรียน"
      variant="segmented"
      @update:model-value="switchTab"
    />

    <!-- ค้นหา + ตัวกรอง -->
    <div
      v-if="currentTab === 'active'"
      class="page-card flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between sm:p-4"
    >
      <div class="relative min-w-0 flex-1">
        <i
          class="bi bi-search pointer-events-none absolute inset-y-0 start-0 flex w-10 items-center justify-center text-ink-3"
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

      <div class="flex shrink-0 items-center border-t border-line pt-3 sm:border-t-0 sm:pt-0">
        <label class="flex cursor-pointer select-none items-center">
          <input v-model="showInactive" type="checkbox" class="peer sr-only" />
          <span
            class="relative h-5 w-10 shrink-0 rounded-full bg-line transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-surface after:transition-all after:content-[''] peer-checked:bg-brand-700 peer-checked:after:translate-x-full"
            aria-hidden="true"
          ></span>
          <span class="ms-2.5 text-sm font-bold text-ink-2">แสดงนักเรียนที่พ้นสภาพ</span>
        </label>
      </div>
    </div>

    <!-- โหลด -->
    <SkeletonRows v-if="isLoading" :rows="4" height="h-16" />

    <!-- ผิดพลาด -->
    <StateBlock v-else-if="hasError" variant="error" @retry="fetchData" />

    <!-- ====================== TAB: ACTIVE ====================== -->
    <template v-else-if="currentTab === 'active'">
      <StateBlock
        v-if="filteredStudents.length === 0"
        variant="empty"
        :title="emptyState.title"
        :hint="emptyState.hint"
      >
        <button
          v-if="emptyState.action"
          type="button"
          class="btn-ghost-ui mt-1"
          @click="runEmptyAction"
        >
          {{ emptyState.actionLabel }}
        </button>
      </StateBlock>

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
                <td class="num font-bold text-ink-1">{{ student.student_no }}</td>

                <td>
                  <div class="flex min-w-0 items-center gap-2">
                    <span class="truncate font-bold text-ink-1">
                      {{ student.prefix ? student.prefix + ' ' : '' }}{{ displayName(student) }}
                    </span>
                    <i
                      v-if="student.is_admin"
                      class="bi bi-shield-lock-fill shrink-0 text-warn-500"
                      title="System Admin"
                      aria-hidden="true"
                    ></i>
                    <!-- 🏠 ยังไม่ยืนยันตัวตน — ข้อมูลที่ห้องบันทึกไว้ยังใช้ได้; ผู้จัดการห้องเห็นข้อมูลส่วนตัว -->
                    <span
                      v-if="student.identity_claimed === false"
                      class="chip shrink-0 bg-canvas text-ink-2"
                      title="ยังไม่ยืนยันตัวตน — ข้อมูลส่วนตัวเห็นได้เฉพาะผู้จัดการห้อง"
                    >
                      <i class="bi bi-lock-fill" aria-hidden="true"></i> ยังไม่ยืนยันตัวตน
                    </span>
                  </div>
                </td>

                <td class="text-ink-3">
                  <span class="block truncate">{{ student.nickname || student.nickname_en || '-' }}</span>
                </td>

                <td>
                  <span
                    class="chip"
                    :class="student.class_role && student.class_role !== 'student'
                      ? 'bg-brand-50 text-brand-700'
                      : 'bg-canvas text-ink-2'"
                  >
                    {{ roleLabel(student.class_role) }}
                  </span>
                </td>

                <td>
                  <span
                    class="chip"
                    :class="{
                      'bg-ok-50 text-ok-700': student.status === 'active',
                      'bg-warn-50 text-warn-700': student.status === 'pending',
                      'bg-canvas text-ink-2': student.status === 'inactive'
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
                    {{ studentStatusLabel(student.status) }}
                  </span>
                </td>

                <td class="text-right">
                  <div class="flex justify-end">
                    <RowActionMenu
                      v-if="canManageStudents"
                      :label="`ตัวเลือกจัดการ ${displayName(student)}`"
                      :items="studentMenuItems(student)"
                      @select="handleStudentAction(student, $event)"
                    />
                    <i v-else class="bi bi-chevron-right p-2 text-ink-3" aria-hidden="true"></i>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 📱 มือถือ: การ์ดเรียงแนวตั้ง -->
        <div class="space-y-2.5 lg:hidden">
          <RouterLink
            v-for="student in filteredStudents"
            :key="student.id"
            :to="`/students/${student.student_no}`"
            class="page-card card-hover relative block p-4 sm:p-5"
            :class="{ 'opacity-60': student.status === 'inactive' }"
          >
            <div class="flex items-start gap-3">
              <!-- avatar ตัวอักษรแรก -->
              <div
                class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-brand-50 font-display text-base font-bold text-brand-700"
                aria-hidden="true"
              >
                {{ avatarInitial(displayName(student)) }}
              </div>

              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <p class="truncate font-display text-[15px] font-bold text-ink-1">
                    {{ student.prefix ? student.prefix + ' ' : '' }}{{ displayName(student) }}
                  </p>
                  <i
                    v-if="student.is_admin"
                    class="bi bi-shield-lock-fill shrink-0 text-xs text-warn-500"
                    title="System Admin"
                    aria-hidden="true"
                  ></i>
                </div>

                <p class="num mt-0.5 truncate text-xs text-ink-3">
                  เลขที่ {{ student.student_no }}
                  <span v-if="student.nickname || student.nickname_en"> · {{ student.nickname || student.nickname_en }}</span>
                </p>

                <div class="mt-2 flex flex-wrap items-center gap-1.5">
                  <span
                    class="chip"
                    :class="student.class_role && student.class_role !== 'student'
                      ? 'bg-brand-50 text-brand-700'
                      : 'bg-canvas text-ink-2'"
                  >
                    {{ roleLabel(student.class_role) }}
                  </span>

                  <span
                    class="chip"
                    :class="{
                      'bg-ok-50 text-ok-700': student.status === 'active',
                      'bg-warn-50 text-warn-700': student.status === 'pending',
                      'bg-canvas text-ink-2': student.status === 'inactive'
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
                    {{ studentStatusLabel(student.status) }}
                  </span>

                  <!-- 🏠 ยังไม่ยืนยันตัวตน — ข้อมูลที่ห้องบันทึกไว้ยังใช้ได้; ผู้จัดการห้องเห็นข้อมูลส่วนตัว -->
                  <span
                    v-if="student.identity_claimed === false"
                    class="chip bg-canvas text-ink-2"
                    title="ยังไม่ยืนยันตัวตน — ข้อมูลส่วนตัวเห็นได้เฉพาะผู้จัดการห้อง"
                  >
                    <i class="bi bi-lock-fill" aria-hidden="true"></i> ยังไม่ยืนยันตัวตน
                  </span>
                </div>
              </div>

              <!-- เมนูจัดการ — การ์ดทั้งใบกดไปหน้านักเรียนได้อยู่แล้ว (RowActionMenu หยุด event ให้เอง) -->
              <div v-if="canManageStudents" class="shrink-0">
                <RowActionMenu
                  :label="`ตัวเลือกจัดการ ${displayName(student)}`"
                  :items="studentMenuItems(student)"
                  @select="handleStudentAction(student, $event)"
                />
              </div>

              <i v-else class="bi bi-chevron-right shrink-0 p-2 text-ink-3" aria-hidden="true"></i>
            </div>
          </RouterLink>
        </div>
      </template>
    </template>

    <!-- ====================== TAB: PENDING ====================== -->
    <template v-else-if="currentTab === 'pending'">
      <StateBlock
        v-if="pendingStudents.length === 0"
        variant="empty"
        title="ไม่มีคำขอที่รออนุมัติ"
        hint="เมื่อมีนักเรียนขอเข้าร่วมห้อง หรือขออ้างสิทธิ์เลขที่ รายการคำขอจะแสดงที่นี่"
      />

      <div v-else class="space-y-2.5">
        <div
          v-for="req in pendingStudents"
          :key="req.student_no"
          class="page-card border-s-4 border-s-warn-400 p-4 sm:p-5"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <!-- ซ้าย: ข้อมูล -->
            <div class="flex min-w-0 items-start gap-3">
              <div
                class="num flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-warn-50 font-display text-base font-bold text-warn-700"
              >
                {{ req.student_no }}
              </div>

              <div class="min-w-0 flex-1">
                <!-- 🛡️ claim_request: มีคนขออ้างสิทธิ์ ghost → แอดมินเห็นชื่อเดิม vs ชื่อผู้ขอ แล้วตัดสิน -->
                <template v-if="req.request_type === 'claim_request'">
                  <p class="truncate font-display text-[15px] font-bold leading-snug text-ink-1">
                    {{ displayName(req) }} <span class="text-warn-700">อ้างสิทธิ์เลขที่นี้</span>
                  </p>
                  <p class="mt-0.5 text-sm text-ink-3">
                    ชื่อในระบบเดิม: <span class="font-bold text-ink-2">{{ req.ghost_first_name || '-' }} {{ req.ghost_last_name || '-' }}</span>
                    <span
                      v-if="req.name_match !== undefined"
                      class="chip ms-1.5"
                      :class="req.name_match ? 'bg-ok-50 text-ok-700' : 'bg-danger-50 text-danger-700'"
                    >
                      {{ req.name_match ? 'ชื่อตรงกัน' : 'ชื่อไม่ตรง' }}
                    </span>
                  </p>
                  <p class="mt-0.5 text-xs text-ink-3">
                    <i class="bi bi-person-check me-1" aria-hidden="true"></i>ตรวจสอบว่าเป็นคนเดียวกันก่อนอนุมัติ
                  </p>
                </template>

                <!-- join_request: ขอเข้าห้องเอง ปกติ -->
                <template v-else>
                  <p class="truncate font-display text-[15px] font-bold leading-snug text-ink-1">
                    {{ displayName(req) }}
                  </p>
                  <p class="mt-0.5 flex items-center gap-1.5 text-sm text-ink-3">
                    <i class="bi bi-clock text-ink-3" aria-hidden="true"></i> ขอเข้าร่วมเมื่อ {{ formatThaiDateTime(req.created_at) }}
                  </p>
                </template>
              </div>
            </div>

            <!-- ขวา: ปุ่มจัดการคำขอเข้าร่วม/ขออ้างสิทธิ์ -->
            <div class="flex gap-2 sm:shrink-0">
              <button type="button" class="btn-danger flex-1 sm:flex-none" @click="rejectJoin(req.student_no)">
                <i class="bi bi-x-lg" aria-hidden="true"></i> ปฏิเสธ
              </button>
              <button type="button" class="btn-primary flex-1 sm:flex-none" @click="approveJoin(req.student_no)">
                <i class="bi bi-check-lg" aria-hidden="true"></i> ยอมรับ
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

  </div>
</template>
