<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import { displayName as personDisplayName } from '@/utils/name';
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
  try {
    const data = await StudentService.getStudents(roomId);
    students.value = Array.isArray(data) ? data : [];
  } catch (error) {
    Swal.fire({
      icon: 'error',
      title: 'โหลดข้อมูลไม่สำเร็จ',
      text: 'ไม่สามารถดึงข้อมูลรายชื่อนักเรียนได้',
      confirmButtonColor: '#3b82f6',
      customClass: { popup: 'rounded-3xl shadow-xl' }
    });
  } finally {
    isLoading.value = false;
  }
};

onMounted(fetchStudents);

// Helper สำหรับ Theme CSS Classes ให้เป็นทางการมากขึ้น (เส้นขอบหนาด้านบน/ด้านซ้าย)
const getThemeClasses = (theme: string, type: 'borderTop' | 'borderLeft' | 'text' | 'iconBg') => {
  const themes: Record<string, any> = {
    blue: { borderTop: 'border-t-blue-500', borderLeft: 'border-l-blue-500', text: 'text-blue-600', iconBg: 'bg-blue-50 text-blue-600' },
    purple: { borderTop: 'border-t-purple-500', borderLeft: 'border-l-purple-500', text: 'text-purple-600', iconBg: 'bg-purple-50 text-purple-600' },
    rose: { borderTop: 'border-t-rose-500', borderLeft: 'border-l-rose-500', text: 'text-rose-600', iconBg: 'bg-rose-50 text-rose-600' },
    emerald: { borderTop: 'border-t-emerald-500', borderLeft: 'border-l-emerald-500', text: 'text-emerald-600', iconBg: 'bg-emerald-50 text-emerald-600' },
    amber: { borderTop: 'border-t-amber-500', borderLeft: 'border-l-amber-500', text: 'text-amber-600', iconBg: 'bg-amber-50 text-amber-600' },
    slate: { borderTop: 'border-t-slate-500', borderLeft: 'border-l-slate-500', text: 'text-slate-600', iconBg: 'bg-slate-50 text-slate-600' },
    cyan: { borderTop: 'border-t-cyan-500', borderLeft: 'border-l-cyan-500', text: 'text-cyan-600', iconBg: 'bg-cyan-50 text-cyan-600' },
    fuchsia: { borderTop: 'border-t-fuchsia-500', borderLeft: 'border-l-fuchsia-500', text: 'text-fuchsia-600', iconBg: 'bg-fuchsia-50 text-fuchsia-600' },
    teal: { borderTop: 'border-t-teal-500', borderLeft: 'border-l-teal-500', text: 'text-teal-600', iconBg: 'bg-teal-50 text-teal-600' },
  };
  return themes[theme]?.[type] || '';
};
</script>

<template>
  <div class="min-h-screen bg-slate-50 py-8 md:py-12">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 space-y-8">
      
      <!-- HEADER -->
      <header class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 sm:p-5 flex items-center gap-3">
        <div class="w-11 h-11 sm:w-12 sm:h-12 bg-slate-800 text-white rounded-xl flex items-center justify-center text-xl sm:text-2xl shadow-sm shrink-0">
          <i class="bi bi-diagram-3-fill"></i>
        </div>
        <div class="min-w-0">
          <h1 class="text-lg sm:text-xl font-bold text-slate-800 tracking-tight truncate">แผนผังองค์กรห้องเรียน</h1>
          <p class="text-slate-500 font-medium text-sm mt-0.5 truncate">โครงสร้างการบริหารระดับชั้นเรียน</p>
        </div>
      </header>

      <!-- LOADER -->
      <div v-if="isLoading" class="flex flex-col items-center justify-center py-24 bg-white rounded-2xl shadow-sm border border-slate-200">
        <div class="animate-spin rounded-full h-10 w-10 border-4 border-slate-100 border-t-slate-800 mb-4"></div>
        <p class="text-slate-500 font-medium">กำลังโหลดโครงสร้าง...</p>
      </div>

      <!-- ORG CHART CONTENT (SCROLLABLE CONTAINER) -->
      <div v-else class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 sm:p-8 overflow-x-auto w-full custom-scrollbar">
        <!-- Inner Wrapper: บังคับความกว้างขั้นต่ำ เพื่อให้เป็นทรงแผนผังทางการเสมอ -->
        <div class="min-w-[1400px] flex flex-col items-center mx-auto pb-8">
          
          <!-- 👑 TIER 1: PRESIDENT -->
          <div class="relative z-10 flex flex-col items-center">
            <div v-if="president" class="w-[280px]">
              <RouterLink :to="getStudentLink(president)" class="block bg-slate-900 border-t-4 border-amber-400 rounded-xl p-5 shadow-lg hover:-translate-y-1 transition-transform group relative overflow-hidden">
                <div class="flex items-center gap-4 relative z-10">
                  <div class="w-14 h-14 bg-amber-400/10 border border-amber-400/30 rounded-lg flex items-center justify-center text-amber-400 text-2xl shrink-0">
                    <i class="bi bi-award-fill"></i>
                  </div>
                  <div class="text-left">
                    <p class="text-amber-400 text-[10px] font-bold uppercase tracking-wider mb-0.5">หัวหน้าห้องเรียน</p>
                    <h2 class="text-lg font-bold text-white leading-tight mb-1 truncate">{{ displayName(president) }}</h2>
                    <span class="text-slate-400 text-xs">เลขที่ {{ president.student_no }}</span>
                  </div>
                </div>
              </RouterLink>
            </div>
            <div v-else class="w-[280px] bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl p-5 text-center">
              <p class="text-slate-500 font-bold text-sm">หัวหน้าห้อง (ว่าง)</p>
            </div>
            
            <!-- เส้นลากลงมาจากหัวหน้า -->
            <div class="w-[2px] h-8 bg-slate-300"></div>
          </div>

          <!-- 🧑‍⚖️ TIER 2: EXECUTIVE BOARD (รองหัวหน้าห้อง + เลขานุการ/เรขา) -->
          <div class="relative z-10 flex flex-col items-center">
            <div class="w-full grid grid-cols-2 gap-8 max-w-[560px]">
              <div v-for="slot in execSlots" :key="slot.role" class="flex flex-col items-center">
                <RouterLink
                  v-if="slot.student"
                  :to="getStudentLink(slot.student)"
                  class="block w-full bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden"
                >
                  <div :class="`absolute top-0 left-0 right-0 h-[4px] ${getThemeClasses(slot.config.theme, 'borderTop').replace('border-t-', 'bg-')}`"></div>
                  <div class="flex items-center gap-3">
                    <div :class="`w-10 h-10 rounded-full flex items-center justify-center text-lg shrink-0 ${getThemeClasses(slot.config.theme, 'iconBg')}`">
                      <i :class="`bi ${slot.config.icon}`"></i>
                    </div>
                    <div class="text-left min-w-0">
                      <p :class="`text-[10px] font-bold uppercase tracking-wider mb-0.5 ${getThemeClasses(slot.config.theme, 'text')}`">{{ slot.config.label }}</p>
                      <h3 class="text-sm font-bold text-slate-800 leading-tight truncate">{{ displayName(slot.student) }}</h3>
                      <span class="text-[11px] text-slate-500">เลขที่ {{ slot.student.student_no }}</span>
                    </div>
                  </div>
                </RouterLink>
                <div v-else class="w-full bg-slate-50 border-2 border-dashed border-slate-200 rounded-xl p-4 text-center">
                  <p class="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">{{ slot.config.label }}</p>
                  <p class="text-xs font-medium text-slate-500">ตำแหน่งว่าง</p>
                </div>
              </div>
            </div>
            <!-- เส้นลากลงมาจากระดับบริหาร -->
            <div class="w-[2px] h-8 bg-slate-300"></div>
          </div>

          <!-- 🏢 TIER 3 & 4: THE TREE STRUCTURE -->
          <div class="w-full relative z-0">
            <!-- เส้นแกนกลางลากยาวลงไปหาเหรัญญิก (ซ่อนอยู่หลัง Grid) -->
            <div class="absolute top-0 bottom-0 left-1/2 w-[2px] bg-slate-300 -translate-x-1/2 -z-10"></div>

            <div class="grid grid-cols-6 w-full relative z-10">

              <div v-for="(dept, index) in departments" :key="dept.role" class="flex flex-col items-center relative">
                
                <!-- 🌿 เส้นเชื่อมแนวนอนด้านบนสุด (วาดแบบ Segmented เพื่อความสมบูรณ์แบบ) -->
                <div v-if="index === 0" class="absolute top-0 left-1/2 right-0 h-[2px] bg-slate-300"></div>
                <div v-else-if="index === departments.length - 1" class="absolute top-0 left-0 right-1/2 h-[2px] bg-slate-300"></div>
                <div v-else class="absolute top-0 left-0 right-0 h-[2px] bg-slate-300"></div>

                <!-- เส้นลากลงมาหารองประธานแต่ละฝ่าย -->
                <div class="absolute top-0 left-1/2 w-[2px] h-8 bg-slate-300 -translate-x-1/2"></div>

                <!-- กล่องแผนก (เว้นระยะจากเส้นบน) -->
                <div class="pt-8 w-full px-4 flex flex-col items-center">
                  
                  <!-- VP NODE -->
                  <div class="w-full max-w-[220px]">
                    <RouterLink 
                      v-if="dept.head" 
                      :to="getStudentLink(dept.head)"
                      class="block bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden"
                    >
                      <!-- แถบสีด้านบน -->
                      <div :class="`absolute top-0 left-0 right-0 h-[4px] ${getThemeClasses(dept.colorTheme, 'borderTop').replace('border-t-', 'bg-')}`"></div>
                      
                      <div class="flex flex-col items-center text-center mt-1">
                        <div :class="`w-10 h-10 rounded-full flex items-center justify-center text-lg mb-2 ${getThemeClasses(dept.colorTheme, 'iconBg')}`">
                          <i :class="`bi ${dept.icon}`"></i>
                        </div>
                        <p :class="`text-[10px] font-bold uppercase tracking-wider mb-1 ${getThemeClasses(dept.colorTheme, 'text')}`">{{ rolesConfig[dept.role]?.label || dept.label }}</p>
                        <h3 class="text-sm font-bold text-slate-800 leading-tight mb-1 w-full truncate">{{ displayName(dept.head) }}</h3>
                        <span class="text-[11px] text-slate-500">เลขที่ {{ dept.head.student_no }}</span>
                      </div>
                    </RouterLink>
                    
                    <div v-else class="bg-slate-50 border-2 border-dashed border-slate-200 rounded-xl p-4 text-center">
                      <p class="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">{{ rolesConfig[dept.role]?.label || dept.label }}</p>
                      <p class="text-xs font-medium text-slate-500">ตำแหน่งว่าง</p>
                    </div>
                  </div>

                  <!-- เส้นลากลงไปหากรรมการ (แสดงเฉพาะเมื่อมีกรรมการ) -->
                  <div v-if="dept.staffs.length > 0" class="w-[2px] h-6 bg-slate-300"></div>

                  <!-- STAFF NODES STACK -->
                  <div class="flex flex-col items-center w-full max-w-[220px]">
                    <template v-for="(staff, sIndex) in dept.staffs" :key="staff.id">
                      
                      <!-- Staff Card -->
                      <RouterLink 
                        :to="getStudentLink(staff)"
                        :class="`w-full bg-white border border-slate-200 shadow-sm hover:shadow-md transition-shadow p-3 flex items-center gap-3 relative rounded-lg ${getThemeClasses(dept.colorTheme, 'borderLeft')}`"
                      >
                        <div class="w-7 h-7 bg-slate-100 rounded text-slate-500 flex items-center justify-center text-xs font-bold shrink-0">
                          {{ staff.student_no }}
                        </div>
                        <div class="flex-col overflow-hidden text-left">
                          <p class="text-xs font-bold text-slate-800 truncate leading-tight">{{ displayName(staff) }}</p>
                          <p class="text-[10px] text-slate-500 truncate mt-0.5">{{ personDisplayName(staff) }}</p>
                        </div>
                      </RouterLink>

                      <!-- เส้นลากระหว่างกรรมการแต่ละคน -->
                      <div v-if="sIndex !== dept.staffs.length - 1" class="w-[2px] h-4 bg-slate-300"></div>
                    </template>
                  </div>

                </div>
              </div>
            </div>
          </div>

          <!-- 💰 TIER 4: TREASURER (เชื่อมกับเส้นแกนกลาง) -->
          <div class="flex flex-col items-center mt-8 relative z-10">
            <!-- เส้นเชื่อมเหรัญญิก (ต่อจากแกนกลาง) -->
            <div class="w-[2px] h-8 bg-slate-300"></div>
            
            <div v-if="treasurer" class="w-[260px]">
              <RouterLink 
                :to="getStudentLink(treasurer)"
                class="block bg-white border border-slate-200 border-t-4 border-t-amber-500 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow"
              >
                <div class="flex items-center gap-4">
                  <div class="w-12 h-12 bg-amber-50 rounded-lg flex items-center justify-center text-amber-600 text-xl shrink-0">
                    <i class="bi bi-safe2-fill"></i>
                  </div>
                  <div class="text-left">
                    <p class="text-amber-600 text-[10px] font-bold uppercase tracking-wider mb-0.5">เหรัญญิก</p>
                    <h3 class="text-sm font-bold text-slate-800 leading-tight mb-1 truncate">{{ displayName(treasurer) }}</h3>
                    <span class="text-[11px] text-slate-500">เลขที่ {{ treasurer.student_no }}</span>
                  </div>
                </div>
              </RouterLink>
            </div>
            
            <div v-else class="w-[260px] bg-slate-50 border-2 border-dashed border-slate-200 rounded-xl p-4 text-center">
              <div class="flex flex-col items-center">
                <i class="bi bi-safe2-fill text-slate-300 text-2xl mb-1"></i>
                <p class="text-[10px] font-bold uppercase tracking-wider text-slate-400">เหรัญญิก</p>
                <p class="text-xs font-medium text-slate-500">ตำแหน่งว่าง</p>
              </div>
            </div>
          </div>

        </div>
      </div>
      
    </div>
  </div>
</template>

<style scoped>
/* สไตล์แต่ง Scrollbar ให้ดูเรียบร้อยแบบทางการ */
.custom-scrollbar::-webkit-scrollbar {
  height: 8px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: #f1f5f9;
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

* {
  -webkit-tap-highlight-color: transparent;
}
</style>