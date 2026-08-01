<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
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
  president: { label: 'หัวหน้าห้อง', icon: 'bi-award-fill', theme: 'from-slate-900 to-slate-800 text-amber-400' },
  vice_academic: { label: 'รองวิชาการ', icon: 'bi-book-half', theme: 'blue' },
  vice_activity: { label: 'รองกิจกรรม', icon: 'bi-music-note-beamed', theme: 'purple' },
  vice_discipline: { label: 'รองระเบียบวินัย', icon: 'bi-shield-fill-check', theme: 'rose' },
  vice_reception: { label: 'รองปฏิคม', icon: 'bi-people-fill', theme: 'emerald' },
  staff_academic: { label: 'กรรมการวิชาการ', icon: 'bi-journal-text', theme: 'blue' },
  staff_activity: { label: 'กรรมการกิจกรรม', icon: 'bi-star-fill', theme: 'purple' },
  staff_discipline: { label: 'กรรมการระเบียบวินัย', icon: 'bi-shield-fill-exclamation', theme: 'rose' },
  staff_reception: { label: 'กรรมการปฏิคม', icon: 'bi-emoji-smile-fill', theme: 'emerald' },
  treasurer: { label: 'เหรัญญิก', icon: 'bi-safe2-fill', theme: 'amber' },
};

const viceToStaff: Record<string, string> = {
  vice_academic: 'staff_academic',
  vice_activity: 'staff_activity',
  vice_discipline: 'staff_discipline',
  vice_reception: 'staff_reception',
};

// Utils
const findStudentByRole = (role: string): Student | null =>
  students.value.find((s) => s.class_role === role) ?? null;

const getStudentLink = (student: Student) => `/students/${student.student_no}`;
const displayName = (student: Student) => student.nickname || `${student.first_name} ${student.last_name}`;

// Computed Data
const president = computed(() => findStudentByRole('president'));
const treasurer = computed(() => findStudentByRole('treasurer'));

// จัดกลุ่มเป็น "ฝ่าย" (Department)
const viceRoles = ['vice_academic', 'vice_activity', 'vice_discipline', 'vice_reception'] as const;
const departments = computed<DepartmentNode[]>(() =>
  viceRoles.map((role) => {
    const staffRole = viceToStaff[role];
    return {
      role,
      label: rolesConfig[role].label.replace('รองฯ ', 'ฝ่าย'), // แปลงชื่อเป็นชื่อฝ่าย
      icon: rolesConfig[role].icon,
      colorTheme: rolesConfig[role].theme,
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

// Helper สำหรับ Theme CSS Classes
const getThemeClasses = (theme: string, type: 'bg' | 'text' | 'border' | 'lightBg' | 'iconBg') => {
  const themes: Record<string, any> = {
    blue: { bg: 'bg-blue-500', text: 'text-blue-600', border: 'border-blue-200 hover:border-blue-400', lightBg: 'bg-blue-50/50', iconBg: 'bg-blue-100 text-blue-600' },
    purple: { bg: 'bg-purple-500', text: 'text-purple-600', border: 'border-purple-200 hover:border-purple-400', lightBg: 'bg-purple-50/50', iconBg: 'bg-purple-100 text-purple-600' },
    rose: { bg: 'bg-rose-500', text: 'text-rose-600', border: 'border-rose-200 hover:border-rose-400', lightBg: 'bg-rose-50/50', iconBg: 'bg-rose-100 text-rose-600' },
    emerald: { bg: 'bg-emerald-500', text: 'text-emerald-600', border: 'border-emerald-200 hover:border-emerald-400', lightBg: 'bg-emerald-50/50', iconBg: 'bg-emerald-100 text-emerald-600' },
    amber: { bg: 'bg-amber-500', text: 'text-amber-600', border: 'border-amber-200 hover:border-amber-400', lightBg: 'bg-amber-50/50', iconBg: 'bg-amber-100 text-amber-600' },
  };
  return themes[theme]?.[type] || '';
};
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 py-8 md:py-12">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 space-y-8">
      
      <!-- HEADER -->
      <header class="bg-white rounded-[2.5rem] shadow-sm border border-slate-100 p-6 md:p-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div class="flex items-center gap-5">
          <div class="w-16 h-16 bg-gradient-to-br from-slate-800 to-slate-900 text-white rounded-[1.5rem] flex items-center justify-center text-2xl shadow-lg shadow-slate-900/20">
            <i class="bi bi-diagram-3-fill"></i>
          </div>
          <div>
            <h1 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight">แผนผังองค์กรห้องเรียน</h1>
            <p class="text-slate-500 font-medium text-sm mt-1">โครงสร้างการบริหารและคณะกรรมการห้อง</p>
          </div>
        </div>
      </header>

      <!-- LOADER -->
      <div v-if="isLoading" class="flex flex-col items-center justify-center py-24 bg-white rounded-[2.5rem] shadow-sm border border-slate-100">
        <div class="animate-spin rounded-full h-12 w-12 border-4 border-slate-100 border-t-slate-800 mb-4"></div>
        <p class="text-slate-400 font-bold tracking-wide">กำลังโหลดโครงสร้าง...</p>
      </div>

      <!-- ORG CHART CONTENT -->
      <div v-else class="space-y-8 md:space-y-12">
        
        <!-- 👑 TIER 1: PRESIDENT -->
        <div class="flex justify-center relative z-10">
          <div v-if="president" class="w-full max-w-md group">
            <RouterLink :to="getStudentLink(president)" class="block bg-gradient-to-br from-slate-900 via-slate-800 to-black rounded-[2rem] p-1 shadow-2xl shadow-slate-900/30 hover:-translate-y-2 transition-all duration-500">
              <div class="bg-slate-900/50 backdrop-blur-xl rounded-[1.8rem] p-6 md:p-8 border border-slate-700 relative overflow-hidden flex items-center gap-6">
                <!-- Decorative Glow -->
                <div class="absolute -right-10 -top-10 w-40 h-40 bg-amber-500/20 rounded-full blur-3xl pointer-events-none group-hover:bg-amber-500/30 transition-all"></div>
                
                <div class="w-20 h-20 bg-gradient-to-br from-amber-400 to-orange-500 rounded-2xl flex items-center justify-center text-4xl shadow-inner border border-amber-300 shrink-0 text-white z-10">
                  <i class="bi bi-award-fill"></i>
                </div>
                <div class="z-10 text-left">
                  <p class="text-amber-400 text-[11px] font-black uppercase tracking-widest mb-1">หัวหน้าห้อง</p>
                  <h2 class="text-xl md:text-2xl font-black text-white leading-tight mb-1">{{ displayName(president) }}</h2>
                  <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/10 text-slate-300 text-xs font-bold border border-white/10">
                    เลขที่ {{ president.student_no }}
                  </span>
                </div>
              </div>
            </RouterLink>
          </div>
          <div v-else class="w-full max-w-md bg-white border-2 border-dashed border-slate-200 rounded-[2rem] p-8 text-center">
            <i class="bi bi-person-x text-4xl text-slate-300 mb-3 block"></i>
            <p class="text-slate-400 font-bold">ยังไม่มีข้อมูลหัวหน้าห้อง</p>
          </div>
        </div>

        <!-- 🏢 TIER 2: DEPARTMENTS (Vices & Staffs) -->
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 relative z-0">
          
          <div v-for="dept in departments" :key="dept.role" class="flex flex-col gap-4">
            
            <!-- Department Header / Vice President -->
            <div class="relative group h-full">
              <RouterLink 
                v-if="dept.head" 
                :to="getStudentLink(dept.head)"
                class="block bg-white rounded-[1.8rem] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border transition-all duration-300 hover:-translate-y-1 hover:shadow-xl h-full"
                :class="getThemeClasses(dept.colorTheme, 'border')"
              >
                <div class="flex flex-col items-center text-center">
                  <div class="w-14 h-14 rounded-2xl flex items-center justify-center text-2xl mb-4 transition-transform group-hover:scale-110" :class="getThemeClasses(dept.colorTheme, 'iconBg')">
                    <i :class="`bi ${dept.icon}`"></i>
                  </div>
                  <p class="text-[10px] font-black uppercase tracking-widest mb-1.5" :class="getThemeClasses(dept.colorTheme, 'text')">{{ rolesConfig[dept.role].label }}</p>
                  <h3 class="text-lg font-black text-slate-800 leading-tight mb-2">{{ displayName(dept.head) }}</h3>
                  <span class="text-xs font-bold text-slate-400 bg-slate-50 px-3 py-1 rounded-full">เลขที่ {{ dept.head.student_no }}</span>
                </div>
              </RouterLink>

              <!-- Empty Vice -->
              <div v-else class="bg-white/50 border-2 border-dashed border-slate-200 rounded-[1.8rem] p-6 text-center h-full flex flex-col items-center justify-center">
                <div class="w-12 h-12 bg-slate-100 rounded-2xl flex items-center justify-center text-xl mb-3 text-slate-300"><i :class="`bi ${dept.icon}`"></i></div>
                <p class="text-[10px] font-black uppercase tracking-widest mb-1 text-slate-400">{{ rolesConfig[dept.role].label }}</p>
                <p class="text-sm font-bold text-slate-300">ตำแหน่งว่าง</p>
              </div>
            </div>

            <!-- Department Staffs -->
            <div class="bg-white rounded-[1.8rem] p-4 shadow-sm border border-slate-100 flex-grow" :class="getThemeClasses(dept.colorTheme, 'lightBg')">
              <h4 class="text-[10px] font-black text-slate-500 uppercase tracking-widest text-center mb-4 pt-2">กรรมการฝ่าย</h4>
              
              <div v-if="dept.staffs.length" class="space-y-2.5">
                <RouterLink 
                  v-for="staff in dept.staffs" 
                  :key="staff.id"
                  :to="getStudentLink(staff)"
                  class="flex items-center gap-3 bg-white p-3 rounded-2xl shadow-sm border border-slate-100 hover:border-slate-300 hover:shadow-md transition-all active:scale-95 group"
                >
                  <div class="w-10 h-10 rounded-xl flex items-center justify-center text-slate-400 bg-slate-50 group-hover:bg-slate-800 group-hover:text-white transition-colors">
                    <span class="text-[10px] font-black">{{ staff.student_no }}</span>
                  </div>
                  <div class="flex-grow overflow-hidden">
                    <p class="text-sm font-bold text-slate-800 truncate">{{ displayName(staff) }}</p>
                    <p class="text-[10px] font-bold text-slate-400 truncate">{{ staff.first_name }} {{ staff.last_name }}</p>
                  </div>
                </RouterLink>
              </div>
              
              <div v-else class="py-6 text-center">
                <p class="text-xs font-bold text-slate-400">ยังไม่มีรายชื่อกรรมการ</p>
              </div>
            </div>
          </div>

        </div>

        <!-- 💰 TIER 3: TREASURER (Special Role) -->
        <div class="flex justify-center mt-12">
          <div class="w-full max-w-sm group">
            <RouterLink 
              v-if="treasurer" 
              :to="getStudentLink(treasurer)"
              class="flex items-center gap-5 bg-white rounded-[2rem] p-5 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-amber-100 hover:border-amber-400 hover:-translate-y-1 hover:shadow-xl transition-all duration-300"
            >
              <div class="w-16 h-16 bg-gradient-to-br from-amber-100 to-orange-100 rounded-[1.25rem] flex items-center justify-center text-2xl text-amber-600 border border-amber-200 shrink-0 group-hover:scale-110 transition-transform">
                <i class="bi bi-safe2-fill"></i>
              </div>
              <div>
                <p class="text-amber-600 text-[10px] font-black uppercase tracking-widest mb-0.5">เหรัญญิก</p>
                <h3 class="text-lg font-black text-slate-800 leading-tight mb-1">{{ displayName(treasurer) }}</h3>
                <span class="text-[11px] font-bold text-slate-400">เลขที่ {{ treasurer.student_no }}</span>
              </div>
            </RouterLink>
            
            <div v-else class="flex items-center gap-5 bg-white/50 border-2 border-dashed border-slate-200 rounded-[2rem] p-5">
              <div class="w-16 h-16 bg-slate-100 rounded-[1.25rem] flex items-center justify-center text-2xl text-slate-300 shrink-0">
                <i class="bi bi-safe2-fill"></i>
              </div>
              <div>
                <p class="text-slate-400 text-[10px] font-black uppercase tracking-widest mb-0.5">เหรัญญิก</p>
                <p class="text-sm font-bold text-slate-300">ตำแหน่งว่าง</p>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* เอา CSS ::before, ::after ที่เป็นเส้นๆ ออกหมดเลยครับ ให้มัน Clean ที่สุด */
* {
  -webkit-tap-highlight-color: transparent;
}
</style>