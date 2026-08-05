<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import type { Student } from '@/types/student';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

// 🎯 แกะสิทธิ์แบบละเอียดยิบ
const isGodAdmin = computed(() => authStore.isAdmin);
const canManageStudents = computed(() => isGodAdmin.value || authStore.currentPermissions.includes('MANAGE_STUDENTS'));
const canExportStudents = computed(() => isGodAdmin.value || authStore.currentPermissions.includes('EXPORT_STUDENTS'));

// --- States ---
const currentTab = ref<'active' | 'pending'>('active');
const students = ref<any[]>([]); // เปลี่ยนเป็น any เพื่อรองรับ is_admin
const pendingStudents = ref<any[]>([]);
const isLoading = ref(true);
const searchQuery = ref('');
const showInactive = ref(false);

const fetchData = async () => {
  isLoading.value = true;
  try {
    if (currentTab.value === 'active') {
      const data = await StudentService.getStudents(currentRoomId);
      students.value = Array.isArray(data) ? data : [];
    } else if (canManageStudents.value) {
      pendingStudents.value = await StudentService.getPendingRequests(currentRoomId);
    }
  } catch (error: any) {
    Swal.fire({ icon: 'error', title: 'ข้อผิดพลาด', text: error.response?.data?.detail || 'ไม่สามารถโหลดข้อมูลได้' });
  } finally {
    isLoading.value = false;
  }
};

const switchTab = (tab: 'active' | 'pending') => {
  currentTab.value = tab;
  fetchData();
};

onMounted(() => fetchData());

// 🏷️ แปลง class_role (ภาษาอังกฤษ) → ป้ายภาษาไทยที่เข้าใจง่าย
const ROLE_LABELS: Record<string, string> = {
  student: 'นักเรียน',
  president: 'หัวหน้าห้อง',
  vice_academic: 'รองวิชาการ',
  vice_activity: 'รองกิจกรรม',
  vice_discipline: 'รองระเบียบวินัย',
  vice_reception: 'รองปฏิคม',
  staff_academic: 'กรรมการวิชาการ',
  staff_activity: 'กรรมการกิจกรรม',
  staff_discipline: 'กรรมการระเบียบวินัย',
  staff_reception: 'กรรมการปฏิคม',
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
  if (!canManageStudents.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'คุณไม่มีสิทธิ์ลบข้อมูลนักเรียน', 'error');
  }

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    text: `ลบ ${student.first_name} (เลขที่ ${student.student_no}) ใช่หรือไม่?`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    confirmButtonText: 'ลบเลย',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await StudentService.deleteStudent(currentRoomId, student.student_no, currentUserName);
      Swal.fire('ลบสำเร็จ!', '', 'success');
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
    text: 'ข้อมูลคำขอนี้จะถูกลบออกจากระบบทันที',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    confirmButtonText: 'ปฏิเสธ',
    cancelButtonText: 'ยกเลิก'
  });
  if (result.isConfirmed) {
    try {
      await StudentService.rejectStudent(currentRoomId, studentNo);
      await fetchData();
      Swal.fire({ title: 'ปฏิเสธคำขอแล้ว', icon: 'success', timer: 1500, showConfirmButton: false });
    } catch (error: any) {
      Swal.fire('ข้อผิดพลาด', error.response?.data?.detail, 'error');
    }
  }
};
</script>

<template>
  <div class="p-4 sm:p-6 md:p-8">
    
    <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
      <h1 class="text-2xl font-black text-slate-800 tracking-tight">
        <i class="bi bi-people-fill me-2 text-blue-600"></i>จัดการนักเรียน
      </h1>
      <div class="flex gap-2">
        <RouterLink v-if="canExportStudents" to="/students/export" class="bg-emerald-50 hover:bg-emerald-100 text-emerald-600 font-bold px-4 py-2.5 rounded-xl transition-all flex items-center justify-center border border-emerald-200 shadow-sm active:scale-95">
          <i class="bi bi-file-earmark-excel-fill text-lg"></i>
        </RouterLink>
        <RouterLink v-if="canManageStudents" to="/students/add" class="bg-slate-900 hover:bg-slate-800 text-white font-bold px-5 py-2.5 rounded-xl shadow-lg shadow-slate-900/20 transition-all flex items-center justify-center active:scale-95">
          <i class="bi bi-person-plus-fill me-2"></i>เพิ่มนักเรียน
        </RouterLink>
      </div>
    </div>

    <!-- ซ่อนแท็บรออนุมัติ ถ้าไม่มีสิทธิ์จัดการนักเรียน -->
    <div v-if="canManageStudents" class="border-b border-slate-200 mb-6 flex gap-6 px-2">
      <button 
        @click="switchTab('active')" 
        class="py-3 px-1 font-bold text-sm transition-all border-b-2"
        :class="currentTab === 'active' ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700'"
      >
        นักเรียนปัจจุบัน
      </button>
      <button 
        @click="switchTab('pending')" 
        class="py-3 px-1 font-bold text-sm transition-all border-b-2 flex items-center gap-2"
        :class="currentTab === 'pending' ? 'border-amber-500 text-amber-600' : 'border-transparent text-slate-500 hover:text-slate-700'"
      >
        รอการอนุมัติ 
        <span v-if="currentTab !== 'pending' && pendingStudents.length > 0" class="bg-red-500 text-white text-[10px] px-2 py-0.5 rounded-full">{{ pendingStudents.length }}</span>
      </button>
    </div>

    <div v-if="currentTab === 'active'" class="bg-white p-4 rounded-2xl shadow-sm border border-slate-100 mb-6 flex flex-col lg:flex-row gap-4 lg:items-center justify-between">
      <div class="relative w-full lg:flex-1">
        <span class="absolute inset-y-0 left-0 pl-4 flex items-center text-slate-400"><i class="bi bi-search"></i></span>
        <input v-model="searchQuery" type="text" placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..." class="w-full pl-11 pr-4 py-2.5 text-sm font-medium border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all" />
      </div>
      <div class="flex items-center gap-2 select-none">
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" v-model="showInactive" class="sr-only peer">
          <div class="w-11 h-6 bg-slate-200 peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
          <span class="ms-3 text-sm font-bold text-slate-600">แสดงนักเรียน Inactive</span>
        </label>
      </div>
    </div>

    <div v-if="isLoading" class="flex justify-center py-20">
      <div class="animate-spin rounded-full h-10 w-10 border-4 border-slate-200 border-t-blue-600"></div>
    </div>

    <div v-else-if="currentTab === 'active'" class="bg-white rounded-2xl shadow-sm overflow-hidden border border-slate-100">
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse min-w-[700px]">
          <thead>
            <tr class="bg-slate-50 text-slate-500 uppercase text-xs tracking-wider">
              <th class="py-4 px-5 font-black text-center w-20">เลขที่</th>
              <th class="py-4 px-5 font-black">ชื่อ-นามสกุล</th>
              <th class="py-4 px-5 font-black">ชื่อเล่น</th>
              <th class="py-4 px-5 font-black">บทบาท</th>
              <th class="py-4 px-5 font-black text-center">สถานะ</th>
              <th class="py-4 px-5 font-black text-center">จัดการ</th>
            </tr>
          </thead>
          <tbody class="text-slate-700 text-sm font-medium">
            <tr v-for="student in filteredStudents" :key="student.id" class="border-b border-slate-50 hover:bg-slate-50 transition-colors" :class="{ 'opacity-50 grayscale-[0.5]': student.status === 'inactive' }">
              <td class="py-4 px-5 text-center font-bold text-slate-800">{{ student.student_no }}</td>
              <td class="py-4 px-5">{{ student.prefix || '' }}{{ student.first_name }} {{ student.last_name }}</td>
              <td class="py-4 px-5">{{ student.nickname || '-' }}</td>
              <td class="py-4 px-5 flex items-center gap-2">
                <span class="px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase" :class="student.class_role === 'student' || !student.class_role ? 'bg-slate-100 text-slate-600' : 'bg-indigo-50 text-indigo-600 border border-indigo-100'">
                  {{ roleLabel(student.class_role) }}
                </span>
                <!-- 🎯 ติดมงกุฎหรือประแจ ให้แอดมิน/สต๊าฟในตารางรายชื่อ -->
                <i v-if="student.is_admin" class="bi bi-shield-lock-fill text-amber-500 text-lg" title="System Admin"></i>
              </td>
              <td class="py-4 px-5 text-center">
                <span v-if="student.status === 'active'" class="bg-emerald-50 text-emerald-600 py-1 px-3 rounded-full text-[10px] font-bold border border-emerald-100">Active</span>
                <span v-else-if="student.status === 'pending'" class="bg-amber-50 text-amber-600 py-1 px-3 rounded-full text-[10px] font-bold border border-amber-100">รออนุมัติ</span>
                <span v-else class="bg-rose-50 text-rose-600 py-1 px-3 rounded-full text-[10px] font-bold border border-rose-100">Inactive</span>
              </td>
              <td class="py-4 px-5 text-center">
                <div class="flex items-center justify-center gap-2">
                  <RouterLink :to="`/students/${student.student_no}`" class="w-8 h-8 flex items-center justify-center bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-600 hover:text-white transition-colors"><i class="bi bi-eye-fill"></i></RouterLink>
                  <!-- ซ่อนปุ่มแก้ไข/ลบ ถ้าไม่ใช่คนที่ดูแลนักเรียนได้ -->
                  <template v-if="canManageStudents">
                    <RouterLink :to="`/students/${student.student_no}/edit`" class="w-8 h-8 flex items-center justify-center bg-amber-50 text-amber-600 rounded-lg hover:bg-amber-500 hover:text-white transition-colors"><i class="bi bi-pencil-fill"></i></RouterLink>
                    <button @click="confirmDelete(student)" class="w-8 h-8 flex items-center justify-center bg-rose-50 text-rose-600 rounded-lg hover:bg-rose-600 hover:text-white transition-colors"><i class="bi bi-trash-fill"></i></button>
                  </template>
                </div>
              </td>
            </tr>
            <tr v-if="filteredStudents.length === 0"><td colspan="6" class="py-12 text-center text-slate-400 font-medium">ไม่พบข้อมูลนักเรียน</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="currentTab === 'pending'" class="bg-white rounded-2xl shadow-sm overflow-hidden border border-amber-100 ring-1 ring-amber-500/10">
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse min-w-[700px]">
          <thead>
            <tr class="bg-amber-50/50 text-slate-500 uppercase text-xs tracking-wider">
              <th class="py-4 px-5 font-black text-center w-20">เลขที่</th>
              <th class="py-4 px-5 font-black">ชื่อ-นามสกุล</th>
              <th class="py-4 px-5 font-black">วันที่ขอเข้า</th>
              <th class="py-4 px-5 font-black text-center w-40">อนุมัติคำขอ</th>
            </tr>
          </thead>
          <tbody class="text-slate-700 text-sm font-medium">
            <tr v-for="req in pendingStudents" :key="req.student_no" class="border-b border-slate-50 hover:bg-amber-50/30 transition-colors">
              <td class="py-4 px-5 text-center font-black text-slate-800">{{ req.student_no }}</td>
              <td class="py-4 px-5">{{ req.first_name }} {{ req.last_name }}</td>
              <td class="py-4 px-5 text-xs text-slate-500">{{ new Date(req.created_at).toLocaleString('th-TH') }}</td>
              <td class="py-4 px-5 text-center">
                <div class="flex items-center justify-center gap-2">
                  <button @click="approveJoin(req.student_no)" class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 hover:bg-emerald-500 hover:text-white rounded-lg text-xs font-bold transition-all border border-emerald-100 hover:border-emerald-500">
                    <i class="bi bi-check-lg"></i> ยอมรับ
                  </button>
                  <button @click="rejectJoin(req.student_no)" class="flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 text-rose-700 hover:bg-rose-500 hover:text-white rounded-lg text-xs font-bold transition-all border border-rose-100 hover:border-rose-500">
                    <i class="bi bi-x-lg"></i> ปฏิเสธ
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="pendingStudents.length === 0">
              <td colspan="4" class="py-16 text-center">
                <div class="w-16 h-16 bg-slate-50 text-slate-300 rounded-full flex items-center justify-center mx-auto mb-3 text-2xl"><i class="bi bi-check2-all"></i></div>
                <p class="text-slate-500 font-medium">ไม่มีคำขอเข้าร่วมที่รอการอนุมัติ</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</template>

<style scoped>
</style>