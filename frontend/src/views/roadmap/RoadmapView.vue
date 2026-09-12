<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import { displayName as personDisplayName } from '@/utils/name';
import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import type { Student } from '@/types/student';
import Swal from 'sweetalert2';

// Types
interface DepartmentNode {
  role: string;
  label: string;
  icon: string;
  colorTheme: string;
  head: Student | null;
  staffs: Student[];
}

const authStore = useAuthStore();
const roomId = authStore.currentRoomId!;
const students = ref<Student[]>([]);
const isLoading = ref(true);

// สถานะผิดพลาดของการโหลด (เดิมแจ้งผ่าน Swal เท่านั้น ทำให้หน้าจอเหลือแต่ตำแหน่งว่าง)
const hasError = ref(false);

// 🎨 Config Theme & Labels สำหรับแต่ละตำแหน่ง
const rolesConfig: Record<string, { label: string, icon: string, theme: string }> = {
  president: { label: 'หัวหน้าห้อง', icon: 'bi-award-fill', theme: 'amber' },
  vice_president: { label: 'รองหัวหน้าห้อง', icon: 'bi-award', theme: 'slate' },
  secretary: { label: 'เลขานุการ (เรขา)', icon: 'bi-journal-bookmark-fill', theme: 'cyan' },
  vice_academic: { label: 'รองวิชาการ', icon: 'bi-book-half', theme: 'blue' },
  vice_activity: { label: 'รองกิจกรรม', icon: 'bi-music-note-beamed', theme: 'purple' },
  vice_discipline: { label: 'รองระเบียบวินัย', icon: 'bi-shield-fill-check', theme: 'rose' },
  vice_reception: { label: 'รองปฏิคม', icon: 'bi-people-fill', theme: 'emerald' },
  vice_pr: { label: 'รองประชาสัมพันธ์', icon: 'bi-megaphone-fill', theme: 'fuchsia' },
  vice_sanitation: { label: 'รองสุขาภิบาล', icon: 'bi-heart-pulse-fill', theme: 'teal' },
  staff_academic: { label: 'กรรมการวิชาการ', icon: 'bi-journal-text', theme: 'blue' },
  staff_activity: { label: 'กรรมการกิจกรรม', icon: 'bi-star-fill', theme: 'purple' },
  staff_discipline: { label: 'กรรมการระเบียบวินัย', icon: 'bi-shield-fill-exclamation', theme: 'rose' },
  staff_reception: { label: 'กรรมการปฏิคม', icon: 'bi-emoji-smile-fill', theme: 'emerald' },
  staff_pr: { label: 'กรรมการประชาสัมพันธ์', icon: 'bi-megaphone-fill', theme: 'fuchsia' },
  staff_sanitation: { label: 'กรรมการสุขาภิบาล', icon: 'bi-heart-pulse-fill', theme: 'teal' },
  treasurer: { label: 'เหรัญญิก', icon: 'bi-cash-coin', theme: 'amber' },
};

const viceToStaff: Record<string, string> = {
  vice_academic: 'staff_academic',
  vice_activity: 'staff_activity',
  vice_discipline: 'staff_discipline',
  vice_reception: 'staff_reception',
  vice_pr: 'staff_pr',
  vice_sanitation: 'staff_sanitation',
};

// Utils
const findStudentByRole = (role: string): Student | null =>
  students.value.find((s) => s.class_role === role) ?? null;

const getStudentLink = (student: Student) => `/students/${student.student_no}`;
const displayName = (student: Student) => student.nickname || student.nickname_en || personDisplayName(student);

// Computed Data
const president = computed(() => findStudentByRole('president'));
const treasurer = computed(() => findStudentByRole('treasurer'));

// 🧑‍⚖️ ระดับบริหาร (Executive): รองหัวหน้าห้อง + เลขานุการ/เรขา
const execRoles = ['vice_president', 'secretary'] as const;
const execSlots = computed(() =>
  execRoles.map((role) => {
    const config = rolesConfig[role] || { label: role, icon: 'bi-person', theme: 'slate' };
    return { role, config, student: findStudentByRole(role) };
  })
);

// จัดกลุ่มเป็น "ฝ่าย" (Department)
const viceRoles = ['vice_academic', 'vice_activity', 'vice_discipline', 'vice_reception', 'vice_pr', 'vice_sanitation'] as const;
const departments = computed<DepartmentNode[]>(() =>
  viceRoles.map((role) => {
    const staffRole = viceToStaff[role];
    const config = rolesConfig[role];
    return {
      role,
      label: config?.label?.replace('รอง', 'ฝ่าย') || role,
      icon: config?.icon || 'bi-person',
      colorTheme: config?.theme || 'blue',
      head: findStudentByRole(role),
      staffs: students.value.filter((s) => s.class_role === staffRole),
    };
  })
);


// Fetch
const fetchStudents = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    const data = await StudentService.getStudents(roomId);
    students.value = Array.isArray(data) ? data : [];
  } catch {
    Swal.fire({
      icon: 'error',
      title: 'โหลดข้อมูลไม่สำเร็จ',
      text: 'ไม่สามารถดึงข้อมูลรายชื่อนักเรียนได้',
      confirmButtonColor: '#1d4ed8'
    });
    hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

onMounted(fetchStudents);

// 🎨 Academic Ledger ใช้สีเน้นเดียว (brand-700) ทุกตำแหน่งจึงได้โทนเดียวกัน
// คงลายเซ็นเดิม (theme, type) ไว้เพื่อไม่ให้กระทบจุดเรียกใช้
const themeClasses = {
  borderTop: 'border-t-brand-700',
  borderLeft: 'border-s-brand-700',
  text: 'text-brand-700',
  iconBg: 'bg-brand-50 text-brand-700',
} as const;

const getThemeClasses = (_theme: string, type: keyof typeof themeClasses) => themeClasses[type];
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Classroom Structure"
      title="แผนผังห้องเรียน"
      description="โครงสร้างการบริหารและ Roadmap การทำงานของห้อง"
    />

    <!-- ============================================ -->
    <!-- โหลด / ผิดพลาด / ว่าง                        -->
    <!-- ============================================ -->
    <SkeletonRows v-if="isLoading" :rows="5" height="h-20" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดโครงสร้างไม่สำเร็จ"
      hint="ตรวจสอบการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
      @retry="fetchStudents"
    />

    <StateBlock
      v-else-if="!students.length"
      variant="empty"
      title="ยังไม่มีนักเรียนในห้องนี้"
      hint="เมื่อมีรายชื่อนักเรียน โครงสร้างการบริหารจะแสดงเป็นลำดับชั้นที่นี่"
    />

    <!-- ============================================ -->
    <!-- ไทม์ไลน์แนวตั้ง — เส้นบาง + จุด marker brand-700 -->
    <!-- ============================================ -->
    <ol v-else class="page-card p-4 sm:p-5">
      <!-- 👑 TIER 1: หัวหน้าห้อง -->
      <li class="flex gap-3 sm:gap-4">
        <div class="flex flex-col items-center" aria-hidden="true">
          <span class="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-brand-700"></span>
          <span class="mt-1 w-px flex-1 bg-stone-200"></span>
        </div>

        <div class="min-w-0 flex-1 pb-5">
          <p class="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">หัวหน้าห้องเรียน</p>

          <RouterLink
            v-if="president"
            :to="getStudentLink(president)"
            class="page-card card-hover flex items-center gap-3 p-4"
          >
            <div
              class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-xl"
              :class="getThemeClasses('amber', 'iconBg')"
            >
              <i class="bi bi-award-fill" aria-hidden="true"></i>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate font-bold text-stone-900">{{ displayName(president) }}</p>
              <p class="num mt-0.5 truncate text-xs text-stone-500">
                เลขที่ {{ president.student_no }}
              </p>
            </div>
            <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
          </RouterLink>

          <div
            v-else
            class="rounded-2xl border border-dashed border-stone-200 bg-stone-50/60 p-4 text-center"
          >
            <p class="text-sm font-bold text-stone-400">หัวหน้าห้อง (ว่าง)</p>
          </div>
        </div>
      </li>

      <!-- 🧑‍⚖️ TIER 2: คณะบริหาร (รองหัวหน้าห้อง + เลขานุการ) -->
      <li class="flex gap-3 sm:gap-4">
        <div class="flex flex-col items-center" aria-hidden="true">
          <span class="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-brand-700"></span>
          <span class="mt-1 w-px flex-1 bg-stone-200"></span>
        </div>

        <div class="min-w-0 flex-1 pb-5">
          <p class="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">คณะบริหาร</p>

          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <template v-for="slot in execSlots" :key="slot.role">
              <RouterLink
                v-if="slot.student"
                :to="getStudentLink(slot.student)"
                class="page-card card-hover flex items-center gap-3 p-3.5"
              >
                <div
                  class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-base"
                  :class="getThemeClasses(slot.config.theme, 'iconBg')"
                >
                  <i :class="`bi ${slot.config.icon}`" aria-hidden="true"></i>
                </div>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[11px] font-bold uppercase tracking-wider text-stone-400">
                    {{ slot.config.label }}
                  </p>
                  <p class="truncate text-sm font-bold text-stone-900">
                    {{ displayName(slot.student) }}
                  </p>
                  <p class="num truncate text-xs text-stone-500">
                    เลขที่ {{ slot.student.student_no }}
                  </p>
                </div>
              </RouterLink>

              <div
                v-else
                class="rounded-2xl border border-dashed border-stone-200 bg-stone-50/60 p-3.5 text-center"
              >
                <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">
                  {{ slot.config.label }}
                </p>
                <p class="mt-0.5 text-xs font-medium text-stone-500">ตำแหน่งว่าง</p>
              </div>
            </template>
          </div>
        </div>
      </li>

      <!-- 🏢 TIER 3: ฝ่ายต่าง ๆ (หัวหน้าฝ่าย + กรรมการ) -->
      <li v-for="dept in departments" :key="dept.role" class="flex gap-3 sm:gap-4">
        <div class="flex flex-col items-center" aria-hidden="true">
          <span class="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-brand-700"></span>
          <span class="mt-1 w-px flex-1 bg-stone-200"></span>
        </div>

        <div class="min-w-0 flex-1 pb-5">
          <p class="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">{{ dept.label }}</p>

          <!-- หัวหน้าฝ่าย -->
          <RouterLink
            v-if="dept.head"
            :to="getStudentLink(dept.head)"
            class="page-card card-hover flex items-center gap-3 p-3.5"
          >
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg"
              :class="getThemeClasses(dept.colorTheme, 'iconBg')"
            >
              <i :class="`bi ${dept.icon}`" aria-hidden="true"></i>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-[11px] font-bold uppercase tracking-wider text-stone-400">
                {{ rolesConfig[dept.role]?.label || dept.label }}
              </p>
              <p class="truncate font-bold text-stone-900">{{ displayName(dept.head) }}</p>
              <p class="num truncate text-xs text-stone-500">เลขที่ {{ dept.head.student_no }}</p>
            </div>
            <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
          </RouterLink>

          <div
            v-else
            class="rounded-2xl border border-dashed border-stone-200 bg-stone-50/60 p-3.5 text-center"
          >
            <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">
              {{ rolesConfig[dept.role]?.label || dept.label }}
            </p>
            <p class="mt-0.5 text-xs font-medium text-stone-500">ตำแหน่งว่าง</p>
          </div>

          <!-- กรรมการในฝ่าย (ซ้อนใต้หัวหน้าฝ่าย) -->
          <div
            v-if="dept.staffs.length > 0"
            class="mt-2 space-y-1.5 border-s border-stone-200 ps-3 sm:ps-4"
          >
            <RouterLink
              v-for="staff in dept.staffs"
              :key="staff.id"
              :to="getStudentLink(staff)"
              class="flex items-center gap-3 rounded-xl border border-stone-200 px-3 py-2 transition-colors hover:border-stone-300 hover:bg-stone-50 active:scale-[0.99]"
            >
              <span
                class="num flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-stone-100 text-xs font-bold text-stone-500"
              >
                {{ staff.student_no }}
              </span>
              <div class="min-w-0 flex-1">
                <p class="truncate text-xs font-bold text-stone-900">{{ displayName(staff) }}</p>
                <p class="truncate text-[10px] text-stone-500">{{ personDisplayName(staff) }}</p>
              </div>
            </RouterLink>
          </div>
        </div>
      </li>

      <!-- 💰 TIER 4: เหรัญญิก (ปิดท้ายไทม์ไลน์) -->
      <li class="flex gap-3 sm:gap-4">
        <div class="flex flex-col items-center" aria-hidden="true">
          <span class="mt-2 h-2.5 w-2.5 shrink-0 rounded-full bg-brand-700"></span>
        </div>

        <div class="min-w-0 flex-1">
          <p class="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">เหรัญญิก</p>

          <RouterLink
            v-if="treasurer"
            :to="getStudentLink(treasurer)"
            class="page-card card-hover flex items-center gap-3 p-3.5"
          >
            <div
              class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg"
              :class="getThemeClasses('amber', 'iconBg')"
            >
              <i class="bi bi-safe2-fill" aria-hidden="true"></i>
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate font-bold text-stone-900">{{ displayName(treasurer) }}</p>
              <p class="num truncate text-xs text-stone-500">เลขที่ {{ treasurer.student_no }}</p>
            </div>
            <i class="bi bi-chevron-right shrink-0 text-stone-300" aria-hidden="true"></i>
          </RouterLink>

          <div
            v-else
            class="rounded-2xl border border-dashed border-stone-200 bg-stone-50/60 p-3.5 text-center"
          >
            <p class="text-[11px] font-bold uppercase tracking-wider text-stone-400">เหรัญญิก</p>
            <p class="mt-0.5 text-xs font-medium text-stone-500">ตำแหน่งว่าง</p>
          </div>
        </div>
      </li>
    </ol>
  </div>
</template>
