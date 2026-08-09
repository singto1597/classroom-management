<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
// import type { Student } from '@/types/student'; // ถ้าไม่ได้ใช้ให้คอมเมนต์ไว้
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
  fetchData();
};

onMounted(() => fetchData());

// 🏷️ แปลง class_role (ภาษาอังกฤษ) → ป้ายภาษาไทยที่เข้าใจง่าย
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
  if (!canManageStudents.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'คุณไม่มีสิทธิ์ลบข้อมูลนักเรียน', 'error');
  }

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    text: `ลบ ${student.first_name} (เลขที่ ${student.student_no}) ใช่หรือไม่?`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    cancelButtonColor: '#64748b',
    confirmButtonText: 'ใช่, ลบเลย',
    cancelButtonText: 'ยกเลิก',
    borderRadius: '1rem'
  });

  if (result.isConfirmed) {
    try {
      await StudentService.deleteStudent(currentRoomId, student.student_no, currentUserName);
      Swal.fire({ title: 'ลบสำเร็จ!', icon: 'success', timer: 1500, showConfirmButton: false });
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
    confirmButtonColor: '#ef4444',
    cancelButtonColor: '#64748b',
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
  <div class="p-3 sm:p-6 md:p-8 max-w-7xl mx-auto bg-slate-50/50 min-h-screen">
    
    <!-- HEADER -->
    <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
      <div>
        <h1 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight flex items-center gap-3">
          <div class="w-10 h-10 bg-blue-100 text-blue-600 rounded-xl flex items-center justify-center shadow-inner">
            <i class="bi bi-people-fill text-xl"></i>
          </div>
          จัดการนักเรียน
        </h1>
        <p class="text-slate-500 text-sm mt-1 ml-13">จัดการข้อมูล สิทธิ์ และสถานะของนักเรียนในห้อง</p>
      </div>
      
      <div class="flex gap-2 w-full sm:w-auto">
        <RouterLink v-if="canExportStudents" to="/students/export" class="flex-1 sm:flex-none bg-white hover:bg-emerald-50 text-emerald-600 font-bold px-4 py-2.5 rounded-xl transition-all flex items-center justify-center border border-slate-200 hover:border-emerald-200 shadow-sm active:scale-95 group" title="Export Excel">
          <i class="bi bi-file-earmark-excel-fill text-lg group-hover:scale-110 transition-transform"></i>
          <span class="ml-2 sm:hidden">ส่งออก</span>
        </RouterLink>
        <RouterLink v-if="canManageStudents" to="/students/add" class="flex-[3] sm:flex-none bg-blue-600 hover:bg-blue-700 text-white font-bold px-5 py-2.5 rounded-xl shadow-md shadow-blue-600/20 transition-all flex items-center justify-center active:scale-95">
          <i class="bi bi-person-plus-fill me-2"></i>เพิ่มนักเรียน
        </RouterLink>
      </div>
    </div>

    <!-- TABS -->
    <div v-if="canManageStudents" class="flex gap-1 mb-5 bg-slate-200/60 p-1 rounded-xl w-fit">
      <button 
        @click="switchTab('active')" 
        class="py-2 px-5 font-bold text-sm transition-all rounded-lg flex items-center gap-2"
        :class="currentTab === 'active' ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200'"
      >
        <i class="bi bi-person-lines-fill"></i> นักเรียนปัจจุบัน
      </button>
      <button 
        @click="switchTab('pending')" 
        class="py-2 px-5 font-bold text-sm transition-all rounded-lg flex items-center gap-2"
        :class="currentTab === 'pending' ? 'bg-white text-amber-600 shadow-sm' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200'"
      >
        <i class="bi bi-person-fill-exclamation"></i> รออนุมัติ 
        <span v-if="pendingStudents.length > 0" class="bg-rose-500 text-white text-[10px] px-2 py-0.5 rounded-full font-black animate-pulse">
          {{ pendingStudents.length }}
        </span>
      </button>
    </div>

    <!-- SEARCH & FILTER (สำหรับ Tab Active) -->
    <div v-if="currentTab === 'active'" class="bg-white p-3 md:p-4 rounded-2xl shadow-sm border border-slate-100 mb-5 flex flex-col md:flex-row gap-4 md:items-center justify-between">
      <div class="relative w-full md:flex-1 max-w-md">
        <span class="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400">
          <i class="bi bi-search"></i>
        </span>
        <input v-model="searchQuery" type="text" placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..." class="w-full pl-10 pr-4 py-2.5 text-sm font-medium border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all bg-slate-50 focus:bg-white" />
      </div>
      <div class="flex items-center gap-2 select-none border-t md:border-t-0 pt-3 md:pt-0 border-slate-100">
        <label class="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" v-model="showInactive" class="sr-only peer">
          <div class="w-10 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-slate-800"></div>
          <span class="ms-2.5 text-sm font-bold text-slate-600">แสดง Inactive</span>
        </label>
      </div>
    </div>

    <!-- LOADER -->
    <div v-if="isLoading" class="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
      <div class="animate-spin rounded-full h-10 w-10 border-4 border-slate-100 border-t-blue-600"></div>
      <span class="text-sm font-medium">กำลังโหลดข้อมูล...</span>
    </div>

    <!-- ====================== TAB: ACTIVE STUDENTS ====================== -->
    <div v-else-if="currentTab === 'active'">
      <div v-if="filteredStudents.length === 0" class="bg-white rounded-2xl py-16 text-center text-slate-400 font-medium border border-slate-100 flex flex-col items-center">
        <i class="bi bi-folder-x text-5xl text-slate-200 mb-3"></i>
        <p>ไม่พบข้อมูลนักเรียนที่คุณค้นหา</p>
      </div>

      <!-- 📱 Mobile Cards Layout (ออกแบบใหม่หมด ไม่บีบชื่อ) -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 md:hidden">
        <div
          v-for="student in filteredStudents"
          :key="student.id"
          class="bg-white rounded-2xl shadow-sm border border-slate-100 flex flex-col overflow-hidden transition-opacity"
          :class="{ 'opacity-60 grayscale-[0.3]': student.status === 'inactive' }"
        >
          <!-- ส่วนข้อมูลด้านบน (ได้พื้นที่เต็มๆ) -->
          <div class="p-4 flex gap-3.5 items-start">
            <!-- เลขที่ -->
            <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-50 text-blue-600 border border-blue-100 flex items-center justify-center font-black text-lg shrink-0 shadow-sm">
              {{ student.student_no }}
            </div>
            
            <!-- ข้อมูลชื่อ -->
            <div class="flex-1 min-w-0 pt-0.5">
              <div class="flex items-center gap-2 flex-wrap mb-1">
                <span
                  v-if="student.status === 'active'"
                  class="bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-md text-[10px] font-bold border border-emerald-100"
                >Active</span>
                <span
                  v-else-if="student.status === 'pending'"
                  class="bg-amber-50 text-amber-600 px-2 py-0.5 rounded-md text-[10px] font-bold border border-amber-100"
                >รออนุมัติ</span>
                <span
                  v-else
                  class="bg-rose-50 text-rose-600 px-2 py-0.5 rounded-md text-[10px] font-bold border border-rose-100"
                >Inactive</span>

                <i v-if="student.is_admin" class="bi bi-shield-check text-amber-500 text-sm" title="System Admin"></i>
              </div>
              
              <h3 class="font-bold text-slate-800 text-[15px] leading-tight break-words">
                {{ student.prefix ? student.prefix + ' ' : '' }}{{ student.first_name }} {{ student.last_name }}
              </h3>
              
              <div class="flex flex-wrap items-center gap-2 mt-1.5 text-xs">
                <span v-if="student.nickname" class="text-slate-500 font-medium">เล่น: {{ student.nickname }}</span>
                <span class="text-slate-300" v-if="student.nickname">•</span>
                <span class="font-bold uppercase" :class="student.class_role === 'student' || !student.class_role ? 'text-slate-500' : 'text-indigo-600'">
                  {{ roleLabel(student.class_role) }}
                </span>
              </div>
            </div>
          </div>

          <!-- แถบปุ่มจัดการด้านล่าง (ใหญ่ กดง่าย ไม่แย่งที่ชื่อ) -->
          <div class="grid grid-cols-3 divide-x divide-slate-100 border-t border-slate-100 bg-slate-50/50">
            <RouterLink :to="`/students/${student.student_no}`" class="py-2.5 flex items-center justify-center gap-1.5 text-blue-600 text-xs font-bold hover:bg-blue-50 transition-colors">
              <i class="bi bi-eye-fill"></i> ดู
            </RouterLink>
            <template v-if="canManageStudents">
              <RouterLink :to="`/students/${student.student_no}/edit`" class="py-2.5 flex items-center justify-center gap-1.5 text-amber-600 text-xs font-bold hover:bg-amber-50 transition-colors">
                <i class="bi bi-pencil-fill"></i> แก้ไข
              </RouterLink>
              <button @click="confirmDelete(student)" class="py-2.5 flex items-center justify-center gap-1.5 text-rose-600 text-xs font-bold hover:bg-rose-50 transition-colors">
                <i class="bi bi-trash-fill"></i> ลบ
              </button>
            </template>
            <template v-else>
               <!-- ช่องว่างเติมให้เต็มถ้าไม่มีสิทธิ์แก้ไข -->
               <div class="col-span-2"></div>
            </template>
          </div>
        </div>
      </div>

      <!-- 💻 Desktop Table (ปรับให้กระชับขึ้น) -->
      <div class="hidden md:block bg-white rounded-2xl shadow-sm overflow-hidden border border-slate-200">
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse min-w-[750px]">
            <thead>
              <tr class="bg-slate-50/80 text-slate-500 uppercase text-[11px] tracking-wider border-b border-slate-200">
                <th class="py-3 px-4 font-black text-center w-16">เลขที่</th>
                <th class="py-3 px-4 font-black">ชื่อ-นามสกุล</th>
                <th class="py-3 px-4 font-black">ชื่อเล่น</th>
                <th class="py-3 px-4 font-black">บทบาท</th>
                <th class="py-3 px-4 font-black text-center w-24">สถานะ</th>
                <th class="py-3 px-4 font-black text-center w-36">จัดการ</th>
              </tr>
            </thead>
            <tbody class="text-slate-700 text-[13px] font-medium divide-y divide-slate-100">
              <tr v-for="student in filteredStudents" :key="student.id" class="hover:bg-blue-50/30 transition-colors group" :class="{ 'opacity-60 grayscale-[0.2] bg-slate-50/50': student.status === 'inactive' }">
                <td class="py-2.5 px-4 text-center">
                  <div class="w-7 h-7 mx-auto rounded-lg bg-slate-100 text-slate-600 flex items-center justify-center font-bold text-xs group-hover:bg-blue-100 group-hover:text-blue-600 transition-colors">
                    {{ student.student_no }}
                  </div>
                </td>
                <td class="py-2.5 px-4">
                  <div class="flex items-center gap-2">
                    <span class="truncate">{{ student.prefix ? student.prefix + ' ' : '' }}{{ student.first_name }} {{ student.last_name }}</span>
                    <i v-if="student.is_admin" class="bi bi-shield-check text-amber-500 text-sm" title="System Admin"></i>
                  </div>
                </td>
                <td class="py-2.5 px-4 text-slate-500">{{ student.nickname || '-' }}</td>
                <td class="py-2.5 px-4">
                  <span class="px-2 py-1 rounded-md text-[10px] font-bold uppercase" :class="student.class_role === 'student' || !student.class_role ? 'bg-slate-100 text-slate-500' : 'bg-indigo-50 text-indigo-600 border border-indigo-100'">
                    {{ roleLabel(student.class_role) }}
                  </span>
                </td>
                <td class="py-2.5 px-4 text-center">
                  <span v-if="student.status === 'active'" class="text-emerald-600 bg-emerald-50 py-1 px-2.5 rounded-md text-[10px] font-bold border border-emerald-100">Active</span>
                  <span v-else-if="student.status === 'pending'" class="text-amber-600 bg-amber-50 py-1 px-2.5 rounded-md text-[10px] font-bold border border-amber-100">รออนุมัติ</span>
                  <span v-else class="text-rose-600 bg-rose-50 py-1 px-2.5 rounded-md text-[10px] font-bold border border-rose-100">Inactive</span>
                </td>
                <td class="py-2.5 px-4 text-center">
                  <div class="flex items-center justify-center gap-1.5 opacity-80 group-hover:opacity-100 transition-opacity">
                    <RouterLink :to="`/students/${student.student_no}`" class="w-8 h-8 flex items-center justify-center bg-slate-100 text-slate-600 rounded-lg hover:bg-blue-500 hover:text-white transition-colors" title="ดูข้อมูล"><i class="bi bi-eye-fill"></i></RouterLink>
                    <template v-if="canManageStudents">
                      <RouterLink :to="`/students/${student.student_no}/edit`" class="w-8 h-8 flex items-center justify-center bg-slate-100 text-slate-600 rounded-lg hover:bg-amber-500 hover:text-white transition-colors" title="แก้ไข"><i class="bi bi-pencil-fill"></i></RouterLink>
                      <button @click="confirmDelete(student)" class="w-8 h-8 flex items-center justify-center bg-slate-100 text-slate-600 rounded-lg hover:bg-rose-500 hover:text-white transition-colors" title="ลบ"><i class="bi bi-trash-fill"></i></button>
                    </template>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ====================== TAB: PENDING STUDENTS ====================== -->
    <div v-else-if="currentTab === 'pending'">
      <div v-if="pendingStudents.length === 0" class="bg-white rounded-2xl py-16 text-center border border-dashed border-slate-300">
        <div class="w-16 h-16 bg-emerald-50 text-emerald-500 rounded-full flex items-center justify-center mx-auto mb-3 text-3xl shadow-sm"><i class="bi bi-check-circle-fill"></i></div>
        <h3 class="text-slate-800 font-bold text-lg">ไม่มีคำขอที่รออนุมัติ</h3>
        <p class="text-slate-500 text-sm mt-1">นักเรียนทุกคนในระบบได้รับการตรวจสอบแล้ว</p>
      </div>

      <!-- 📱 Mobile Cards (Pending) -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 md:hidden">
        <div v-for="req in pendingStudents" :key="req.student_no" class="bg-white rounded-2xl shadow-md border-t-4 border-t-amber-400 border-x border-b border-slate-100 overflow-hidden flex flex-col">
          <div class="p-4 flex items-center gap-3.5">
            <div class="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center font-black text-lg shrink-0">
              {{ req.student_no }}
            </div>
            <div class="flex-1 min-w-0">
              <p class="font-bold text-slate-800 text-[15px] truncate">{{ req.first_name }} {{ req.last_name }}</p>
              <p class="text-xs text-slate-400 mt-1 flex items-center gap-1">
                <i class="bi bi-clock"></i> {{ new Date(req.created_at).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) }}
              </p>
            </div>
          </div>
          <!-- ปุ่มอนุมัติ กว้างเต็มที่ กดง่ายสุดๆ -->
          <div class="grid grid-cols-2 divide-x divide-slate-100 border-t border-slate-100 text-sm font-bold">
            <button @click="rejectJoin(req.student_no)" class="py-3 text-rose-600 bg-rose-50/50 hover:bg-rose-100 transition-colors flex items-center justify-center gap-1.5">
              <i class="bi bi-x-lg"></i> ปฏิเสธ
            </button>
            <button @click="approveJoin(req.student_no)" class="py-3 text-emerald-600 bg-emerald-50/50 hover:bg-emerald-100 transition-colors flex items-center justify-center gap-1.5">
              <i class="bi bi-check-lg text-lg"></i> ยอมรับ
            </button>
          </div>
        </div>
      </div>

      <!-- 💻 Desktop Table (Pending) -->
      <div class="hidden md:block bg-white rounded-2xl shadow-sm overflow-hidden border border-amber-100">
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse min-w-[700px]">
            <thead>
              <tr class="bg-amber-50/50 text-amber-700 uppercase text-[11px] tracking-wider border-b border-amber-100">
                <th class="py-3 px-4 font-black text-center w-20">เลขที่</th>
                <th class="py-3 px-4 font-black">ชื่อ-นามสกุล</th>
                <th class="py-3 px-4 font-black">เวลาที่ส่งคำขอ</th>
                <th class="py-3 px-4 font-black text-right w-52">จัดการคำขอ</th>
              </tr>
            </thead>
            <tbody class="text-slate-700 text-[13px] font-medium divide-y divide-slate-100">
              <tr v-for="req in pendingStudents" :key="req.student_no" class="hover:bg-amber-50/30 transition-colors">
                <td class="py-3 px-4 text-center font-bold text-slate-800">{{ req.student_no }}</td>
                <td class="py-3 px-4">{{ req.first_name }} {{ req.last_name }}</td>
                <td class="py-3 px-4 text-slate-500 text-xs">
                  <i class="bi bi-clock me-1"></i> {{ new Date(req.created_at).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) }}
                </td>
                <td class="py-3 px-4 text-right">
                  <div class="flex items-center justify-end gap-2">
                    <button @click="rejectJoin(req.student_no)" class="flex items-center gap-1.5 px-3 py-1.5 text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-lg text-xs font-bold transition-all border border-transparent hover:border-rose-200">
                      ปฏิเสธ
                    </button>
                    <button @click="approveJoin(req.student_no)" class="flex items-center gap-1.5 px-4 py-1.5 bg-emerald-500 text-white hover:bg-emerald-600 rounded-lg text-xs font-bold transition-all shadow-sm shadow-emerald-500/20">
                      <i class="bi bi-check-lg"></i> ยอมรับ
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ลดขนาด Scrollbar สำหรับตารางแนวนอนเผื่อจอยาว */
::-webkit-scrollbar {
  height: 6px;
  width: 6px;
}
::-webkit-scrollbar-track {
  background: #f1f5f9; 
  border-radius: 4px;
}
::-webkit-scrollbar-thumb {
  background: #cbd5e1; 
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: #94a3b8; 
}
</style>