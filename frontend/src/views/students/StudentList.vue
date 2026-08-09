<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue';
import { useRouter } from 'vue-router'; 
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
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
const students = ref<any[]>([]); 
const pendingStudents = ref<any[]>([]);
const isLoading = ref(true);
const searchQuery = ref('');
const showInactive = ref(false);

// --- Dropdown Menu State (จุด 3 จุด) ---
const openDropdown = ref<number | null>(null);

const toggleDropdown = (id: number, event: Event) => {
  event.stopPropagation(); // ป้องกันไม่ให้คลิกทะลุไปโดน Card
  openDropdown.value = openDropdown.value === id ? null : id;
};

const closeDropdown = () => {
  openDropdown.value = null;
};

const fetchData = async () => {
  isLoading.value = true;
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
  } catch (error: any) {
    Swal.fire({ icon: 'error', title: 'ข้อผิดพลาด', text: error.response?.data?.detail || 'ไม่สามารถโหลดข้อมูลได้' });
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
    
    const fullName = `${student.first_name || ''} ${student.last_name || ''}`.toLowerCase();
    const studentNo = student.student_no?.toString() || '';
    const studentId = student.student_id?.toString().toLowerCase() || '';
    const nickname = student.nickname?.toLowerCase() || '';

    return fullName.includes(query) || studentNo.includes(query) || studentId.includes(query) || nickname.includes(query);
  });
});

const confirmDelete = async (student: any) => {
  closeDropdown();
  if (!canManageStudents.value) return;

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    text: `ลบ ${student.first_name} (เลขที่ ${student.student_no}) ใช่หรือไม่?`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    cancelButtonColor: '#64748b',
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await StudentService.deleteStudent(currentRoomId, student.student_no, currentUserName);
      Swal.fire({ title: 'ลบสำเร็จ', icon: 'success', timer: 1500, showConfirmButton: false });
      fetchData();
    } catch (error: any) {
      Swal.fire('ลบไม่สำเร็จ', error.response?.data?.detail, 'error');
    }
  }
};

const approveJoin = async (studentNo: number) => {
  try {
    await StudentService.approveStudent(currentRoomId, studentNo);
    await fetchData(); 
    Swal.fire({ title: 'อนุมัติสำเร็จ', icon: 'success', timer: 1500, showConfirmButton: false });
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error.response?.data?.detail, 'error');
  }
};

const rejectJoin = async (studentNo: number) => {
  const result = await Swal.fire({
    title: 'ปฏิเสธคำขอ?',
    text: 'คำขอนี้จะถูกลบออกจากระบบ',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    confirmButtonText: 'ปฏิเสธ',
    cancelButtonText: 'ยกเลิก'
  });
  if (result.isConfirmed) {
    try {
      await StudentService.rejectStudent(currentRoomId, studentNo);
      await fetchData();
    } catch (error: any) {
      Swal.fire('ข้อผิดพลาด', error.response?.data?.detail, 'error');
    }
  }
};
</script>

<template>
  <div class="p-4 sm:p-6 md:p-8 max-w-5xl mx-auto min-h-screen">
    
    <!-- HEADER -->
    <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
      <h1 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight flex items-center gap-3">
        <div class="w-10 h-10 bg-slate-100 text-slate-700 rounded-xl flex items-center justify-center">
          <i class="bi bi-people-fill"></i>
        </div>
        จัดการนักเรียน
      </h1>
      
      <div class="flex gap-2 w-full sm:w-auto">
        <RouterLink v-if="canExportStudents" to="/students/export" class="flex-[1] sm:flex-none bg-white hover:bg-emerald-50 text-emerald-600 font-bold px-4 py-2.5 rounded-xl transition-all flex items-center justify-center border border-slate-200 shadow-sm active:scale-95 group">
          <i class="bi bi-file-earmark-excel-fill text-lg group-hover:scale-110 transition-transform"></i>
        </RouterLink>
        <RouterLink v-if="canManageStudents" to="/students/add" class="flex-[4] sm:flex-none bg-slate-900 hover:bg-slate-800 text-white font-bold px-5 py-2.5 rounded-xl shadow-md transition-all flex items-center justify-center active:scale-95 gap-2">
          <i class="bi bi-person-plus-fill"></i> เพิ่มนักเรียน
        </RouterLink>
      </div>
    </div>

    <!-- TABS -->
    <div v-if="canManageStudents" class="flex gap-2 mb-6 bg-slate-100/70 p-1.5 rounded-xl w-fit">
      <button 
        @click="switchTab('active')" 
        class="py-2 px-4 font-bold text-sm transition-all rounded-lg flex items-center gap-2"
        :class="currentTab === 'active' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'"
      >
        นักเรียนปัจจุบัน
      </button>
      <button 
        @click="switchTab('pending')" 
        class="py-2 px-4 font-bold text-sm transition-all rounded-lg flex items-center gap-2"
        :class="currentTab === 'pending' ? 'bg-white text-amber-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'"
      >
        รออนุมัติ 
        <span v-if="pendingStudents.length > 0" class="bg-rose-500 text-white text-[10px] px-2 py-0.5 rounded-full font-black">
          {{ pendingStudents.length }}
        </span>
      </button>
    </div>

    <!-- SEARCH & FILTER -->
    <div v-if="currentTab === 'active'" class="bg-white p-3 md:p-4 rounded-2xl shadow-sm border border-slate-100 mb-6 flex flex-col md:flex-row gap-4 md:items-center justify-between">
      <div class="relative w-full md:flex-1 max-w-md">
        <span class="absolute inset-y-0 left-0 pl-4 flex items-center text-slate-400">
          <i class="bi bi-search"></i>
        </span>
        <input v-model="searchQuery" type="text" placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..." class="w-full pl-11 pr-4 py-2.5 text-sm font-medium border border-slate-200 rounded-xl focus:ring-2 focus:ring-slate-200 focus:border-slate-400 outline-none transition-all bg-slate-50 focus:bg-white" />
      </div>
      <div class="flex items-center gap-2 select-none border-t md:border-t-0 pt-3 md:pt-0 border-slate-100">
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" v-model="showInactive" class="sr-only peer">
          <div class="w-10 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-slate-700"></div>
          <span class="ms-2.5 text-sm font-bold text-slate-600">แสดง Inactive</span>
        </label>
      </div>
    </div>

    <!-- LOADER -->
    <div v-if="isLoading" class="flex justify-center py-20">
      <div class="animate-spin rounded-full h-10 w-10 border-4 border-slate-100 border-t-slate-700"></div>
    </div>

    <!-- ====================== TAB: ACTIVE (LIST CARDS) ====================== -->
    <div v-else-if="currentTab === 'active'">
      <div v-if="filteredStudents.length === 0" class="bg-white rounded-2xl py-16 text-center text-slate-400 font-medium border border-slate-100">
        ไม่พบข้อมูลนักเรียน
      </div>

      <!-- 📋 List Cards (เรียงยาวลงมาเหมือนตาราง แต่เป็น Card) -->
      <div class="flex flex-col gap-3 sm:gap-4">
        <div
          v-for="student in filteredStudents"
          :key="student.id"
          @click="goToStudent(student.student_no)"
          class="group relative bg-white rounded-2xl p-4 sm:p-5 shadow-sm border border-slate-100 hover:shadow-md hover:border-slate-200 cursor-pointer transition-all duration-300 flex items-center justify-between"
          :class="{ 'opacity-60 grayscale-[0.4]': student.status === 'inactive' }"
        >
          
          <!-- ส่วนซ้าย: ข้อมูลนักเรียน -->
          <div class="flex items-center gap-4 sm:gap-5 flex-1 min-w-0">
            <!-- เลขที่ -->
            <div class="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-slate-50 text-slate-600 flex items-center justify-center font-black text-lg sm:text-xl group-hover:bg-slate-100 transition-colors shrink-0 border border-slate-100">
              {{ student.student_no }}
            </div>
            
            <!-- ชื่อและรายละเอียด -->
            <div class="flex-1 min-w-0 flex flex-col justify-center">
              <div class="flex items-center gap-2 mb-1">
                <h3 class="font-bold text-slate-800 text-[16px] sm:text-[17px] truncate group-hover:text-blue-600 transition-colors">
                  {{ student.prefix ? student.prefix + ' ' : '' }}{{ student.first_name }} {{ student.last_name }}
                </h3>
                <i v-if="student.is_admin" class="bi bi-shield-lock-fill text-amber-500 text-sm shrink-0" title="System Admin"></i>
              </div>
              
              <div class="flex items-center flex-wrap gap-x-2 gap-y-1 text-xs sm:text-sm text-slate-500">
                <!-- ป้ายสถานะแบบเนียนๆ -->
                <div class="flex items-center gap-1.5 font-medium">
                  <span class="w-2 h-2 rounded-full" :class="{
                    'bg-emerald-400': student.status === 'active',
                    'bg-amber-400': student.status === 'pending',
                    'bg-slate-300': student.status === 'inactive'
                  }"></span>
                  <span>{{ student.status === 'active' ? 'Active' : student.status === 'pending' ? 'รออนุมัติ' : 'Inactive' }}</span>
                </div>
                
                <span class="text-slate-300 hidden sm:inline">•</span>
                
                <!-- ชื่อเล่น -->
                <div v-if="student.nickname" class="flex items-center">
                  <span class="sm:hidden mr-1">,</span>เล่น {{ student.nickname }}
                </div>
                
                <span class="text-slate-300 hidden sm:inline" v-if="student.nickname">•</span>
                <span class="text-slate-300 sm:hidden" v-else-if="student.class_role && student.class_role !== 'student'">,</span>

                <!-- บทบาท -->
                <span v-if="student.class_role && student.class_role !== 'student'" class="font-bold text-indigo-600">
                  {{ roleLabel(student.class_role) }}
                </span>
                <span v-else class="text-slate-400">นักเรียน</span>
              </div>
            </div>
          </div>

          <!-- ส่วนขวา: จุด 3 จุด Dropdown -->
          <div class="relative ml-3 shrink-0" v-if="canManageStudents">
            <button 
              @click.stop="toggleDropdown(student.student_no, $event)" 
              class="w-10 h-10 flex items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            >
              <i class="bi bi-three-dots-vertical text-lg"></i>
            </button>

            <!-- Dropdown Menu -->
            <transition name="fade">
              <div v-if="openDropdown === student.student_no" class="absolute right-0 top-12 w-36 bg-white rounded-2xl shadow-[0_4px_20px_-4px_rgba(0,0,0,0.1)] border border-slate-100 overflow-hidden z-20 py-1 origin-top-right">
                <button @click.stop="editStudent(student.student_no)" class="w-full text-left px-4 py-2.5 text-sm text-slate-700 font-medium hover:bg-slate-50 flex items-center gap-2.5 transition-colors">
                  <i class="bi bi-pencil-square text-slate-400"></i> แก้ไข
                </button>
                <div class="h-px bg-slate-100 my-1 mx-2"></div>
                <button @click.stop="confirmDelete(student)" class="w-full text-left px-4 py-2.5 text-sm text-rose-600 font-medium hover:bg-rose-50 flex items-center gap-2.5 transition-colors">
                  <i class="bi bi-trash text-rose-400"></i> ลบข้อมูล
                </button>
              </div>
            </transition>
          </div>
        </div>
      </div>
    </div>

    <!-- ====================== TAB: PENDING (LIST CARDS) ====================== -->
    <div v-else-if="currentTab === 'pending'">
      <div v-if="pendingStudents.length === 0" class="bg-white rounded-2xl py-16 text-center border border-dashed border-slate-300 text-slate-400 font-medium">
        ไม่มีคำขอที่รออนุมัติ
      </div>

      <div class="flex flex-col gap-3 sm:gap-4">
        <div v-for="req in pendingStudents" :key="req.student_no" class="bg-white rounded-2xl p-4 sm:p-5 shadow-sm border border-l-4 border-amber-100 border-l-amber-400 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          
          <!-- ซ้าย: ข้อมูล -->
          <div class="flex items-center gap-4 min-w-0">
            <div class="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center font-black text-lg border border-amber-100 shrink-0">
              {{ req.student_no }}
            </div>
            
            <div class="flex-1 min-w-0">
              <h3 class="font-bold text-slate-800 text-[16px] sm:text-[17px] leading-snug truncate">
                {{ req.first_name }} {{ req.last_name }}
              </h3>
              <p class="text-xs sm:text-sm text-slate-500 mt-0.5 flex items-center gap-1.5">
                <i class="bi bi-clock text-slate-400"></i> ขอเข้าร่วมเมื่อ {{ new Date(req.created_at).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok', dateStyle: 'short', timeStyle: 'short' }) }}
              </p>
            </div>
          </div>

          <!-- ขวา: ปุ่มจัดการ -->
          <div class="flex gap-2 sm:shrink-0 mt-2 sm:mt-0">
            <button @click="rejectJoin(req.student_no)" class="flex-1 sm:flex-none px-5 py-2.5 rounded-xl text-rose-600 bg-rose-50 hover:bg-rose-100 transition-colors text-sm font-bold flex items-center justify-center gap-1.5">
               ปฏิเสธ
            </button>
            <button @click="approveJoin(req.student_no)" class="flex-1 sm:flex-none px-5 py-2.5 rounded-xl text-white bg-amber-500 hover:bg-amber-600 transition-colors text-sm font-bold flex items-center justify-center gap-1.5 shadow-sm shadow-amber-500/20">
               ยอมรับ
            </button>
          </div>
        </div>
      </div>
    </div>

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