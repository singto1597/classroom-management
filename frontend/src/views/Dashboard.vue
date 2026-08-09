<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import { TaskService } from '@/services/task';
import Swal from 'sweetalert2';

const router = useRouter();
const authStore = useAuthStore();

// ✨ ระบบชื่อใหม่ ดึงจาก authStore โดยตรง
const userName = computed(() => authStore.currentUserName || 'ผู้ใช้งาน');
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

const fetchTaskCount = async () => {
  try {
    const result = await TaskService.getAllTasks(authStore.currentRoomId!);
    taskCount.value = result.length;
    pendingTaskCount.value = result.filter((task: any) => task.status === 'pending').length;
  } catch {
    // การ์ดยังแสดงได้โดยไม่ต้องมีตัวเลขถ้าดึงไม่สำเร็จ
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
    const myProfile: any = await StudentService.getMyProfile(authStore.currentRoomId!);
    Swal.close();
    router.push(`/students/${myProfile.student_no}`);
  } catch (error) {
    Swal.fire({
      icon: 'warning',
      title: 'ข้อผิดพลาด',
      text: 'ไม่สามารถเข้าถึงโปรไฟล์ได้ (คุณอาจเป็นผู้ดูแลระบบที่ไม่ได้มีชื่อในทะเบียนนักเรียน)',
      customClass: { popup: 'rounded-3xl shadow-xl' },
      confirmButtonColor: '#3b82f6',
      confirmButtonText: 'รับทราบ'
    });
  }
};
</script>

<template>
  <div class="relative overflow-hidden pb-12 bg-slate-50 min-h-screen font-sans">
    <div class="max-w-7xl mx-auto space-y-6 md:space-y-8 relative z-10 p-4 sm:p-6 md:p-8">
      
      <!-- ========================================== -->
      <!-- 1. HERO SECTION (Modern Glass & Gradient)    -->
      <!-- ========================================== -->
      <div class="relative bg-gradient-to-r from-blue-700 via-indigo-600 to-violet-700 rounded-[2rem] p-6 sm:p-8 md:p-10 shadow-2xl shadow-indigo-500/30 overflow-hidden group">
        <!-- Glow Effects & Textures -->
        <div class="absolute top-0 right-0 w-72 h-72 bg-white/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/3 transition-transform duration-700 group-hover:scale-110"></div>
        <div class="absolute bottom-0 left-10 w-56 h-56 bg-blue-400/20 rounded-full blur-2xl translate-y-1/2 transition-transform duration-700 group-hover:scale-110"></div>
        
        <div class="relative z-10 flex flex-col xl:flex-row justify-between items-start xl:items-center gap-6">
          
          <!-- Welcome Text -->
          <div class="text-white min-w-0">
            <h1 class="text-2xl sm:text-3xl lg:text-4xl font-black tracking-tight mb-2 drop-shadow-md truncate">
              สวัสดี, {{ userName }}! <span class="inline-block animate-bounce origin-bottom">👋</span>
            </h1>
            <p class="text-blue-100 text-sm sm:text-base font-medium tracking-wide opacity-90">
              ยินดีต้อนรับสู่แดชบอร์ดจัดการห้องเรียนของคุณ
            </p>
          </div>

          <!-- Badges & Action Buttons -->
          <div class="flex flex-wrap items-center w-full xl:w-auto gap-3">
            
            <!-- Discord Connect Button (Fixed SVG Bug) -->
            <RouterLink to="/discord-connect" class="inline-flex items-center gap-2 px-4 py-2.5 bg-white/10 hover:bg-white/20 border border-white/20 text-white backdrop-blur-md rounded-xl font-semibold text-sm transition-all shadow-sm hover:shadow-md active:scale-95">
              <i class="bi bi-discord text-lg text-indigo-200"></i>
              เชื่อมต่อ Discord
            </RouterLink>

            <!-- Room Code Badge -->
            <div class="bg-white/10 backdrop-blur-md border border-white/20 px-4 py-2 rounded-xl flex items-center gap-3 shadow-sm">
              <div class="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center">
                <i class="bi bi-key-fill text-blue-200 text-lg"></i>
              </div>
              <div class="flex flex-col">
                <span class="text-[10px] font-bold text-blue-200 uppercase tracking-wider leading-none mb-1">Room Code</span>
                <span class="text-white font-mono font-bold text-sm tracking-widest leading-none">{{ roomCode }}</span>
              </div>
            </div>

            <!-- Role Badge -->
            <div class="bg-white/10 backdrop-blur-md border border-white/20 px-4 py-2.5 rounded-xl flex items-center gap-2.5 shadow-sm">
              <span class="relative flex h-2.5 w-2.5">
                <span :class="isAdmin ? 'bg-emerald-400' : 'bg-blue-400'" class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"></span>
                <span :class="isAdmin ? 'bg-emerald-400' : 'bg-blue-400'" class="relative inline-flex rounded-full h-2.5 w-2.5"></span>
              </span>
              <span class="text-white font-bold text-xs tracking-widest uppercase leading-none">{{ role }}</span>
            </div>

            <!-- Switch Room Button -->
            <button @click="handleChangeRoom" class="h-[42px] w-[42px] bg-white/10 hover:bg-white/20 active:scale-95 backdrop-blur-md border border-white/20 rounded-xl flex items-center justify-center text-white transition-all shadow-sm hover:shadow-md" title="สลับห้องเรียน">
              <i class="bi bi-arrow-left-right text-lg"></i>
            </button>

          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- MAIN GRID WIDGETS (Bento Box Style)        -->
      <!-- ========================================== -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">

        <!-- 2. TASKS WIDGET -->
        <div class="bg-white rounded-[2rem] shadow-sm border border-slate-200 p-6 md:p-8 flex flex-col hover:shadow-xl hover:border-blue-200/60 transition-all duration-300 group/card">
          <div class="flex items-center gap-4 mb-6">
            <div class="w-14 h-14 bg-gradient-to-br from-blue-50 to-indigo-50 text-blue-600 rounded-2xl flex items-center justify-center text-2xl shadow-inner border border-blue-100 group-hover/card:scale-105 transition-transform duration-500 shrink-0">
              <i class="bi bi-journal-check"></i>
            </div>
            <h2 class="text-xl md:text-2xl font-black text-slate-800 tracking-tight">ตารางและงาน</h2>
          </div>

          <div class="flex flex-col gap-3 mb-6">
            <!-- All Tasks -->
            <router-link to="/tasks" class="flex items-center justify-between p-4 bg-slate-50 hover:bg-blue-50 active:scale-[0.98] rounded-2xl transition-all duration-300 border border-slate-100 hover:border-blue-200 group">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-blue-500 text-xl border border-slate-100 group-hover:scale-110 transition-transform shrink-0">
                  <i class="bi bi-card-checklist"></i>
                </div>
                <div class="flex flex-col min-w-0">
                  <span class="font-bold text-slate-700 text-sm group-hover:text-blue-700 transition-colors">ดูรายการงานทั้งหมด</span>
                  <span v-if="taskCount > 0" class="text-xs text-slate-500 font-medium mt-1">ยังไม่เสร็จ {{ pendingTaskCount }} / ทั้งหมด {{ taskCount }} ชิ้น</span>
                </div>
              </div>
              <i class="bi bi-chevron-right text-slate-400 group-hover:text-blue-600 shrink-0 transition-colors"></i>
            </router-link>

            <!-- Add Task -->
            <router-link v-if="canManageTasks" to="/tasks/add" class="flex items-center justify-between p-4 bg-slate-50 hover:bg-blue-50 active:scale-[0.98] rounded-2xl transition-all duration-300 border border-slate-100 hover:border-blue-200 group">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-blue-500 text-xl border border-slate-100 group-hover:scale-110 transition-transform shrink-0">
                  <i class="bi bi-plus-lg text-lg"></i>
                </div>
                <span class="font-bold text-slate-700 text-sm group-hover:text-blue-700 transition-colors">เพิ่มงาน / โน้ตใหม่</span>
              </div>
              <i class="bi bi-chevron-right text-slate-400 group-hover:text-blue-600 shrink-0 transition-colors"></i>
            </router-link>

            <!-- Read Only State -->
            <div v-else class="flex items-center justify-center p-4 bg-slate-50/50 rounded-2xl border border-dashed border-slate-200 text-slate-400 font-medium text-sm">
              <i class="bi bi-lock-fill me-2"></i> เฉพาะผู้ดูแลที่เพิ่มงานได้
            </div>
          </div>

          <!-- Bottom Actions -->
          <div class="mt-auto pt-6 border-t border-slate-100">
            <div class="flex flex-wrap gap-3">
              <router-link to="/schedules" class="flex-1 text-center px-4 py-3.5 bg-slate-100 hover:bg-slate-800 hover:text-white text-slate-600 font-bold text-sm rounded-xl transition-all active:scale-95">ตารางเรียนยืนพื้น</router-link>
              <router-link v-if="canManageTasks" to="/schedules" class="flex-1 text-center px-4 py-3.5 bg-rose-50 hover:bg-rose-600 hover:text-white text-rose-600 font-bold text-sm rounded-xl transition-all border border-rose-100 hover:border-rose-600 active:scale-95">ข้อยกเว้นฉุกเฉิน</router-link>
            </div>
          </div>
        </div>

        <!-- 3. STUDENTS WIDGET -->
        <div class="bg-white rounded-[2rem] shadow-sm border border-slate-200 p-6 md:p-8 flex flex-col hover:shadow-xl hover:border-emerald-200/60 transition-all duration-300 group/card">
          <div class="flex items-center gap-4 mb-6">
            <div class="w-14 h-14 bg-gradient-to-br from-emerald-50 to-teal-50 text-emerald-600 rounded-2xl flex items-center justify-center text-2xl shadow-inner border border-emerald-100 group-hover/card:scale-105 transition-transform duration-500 shrink-0">
              <i class="bi bi-people-fill"></i>
            </div>
            <h2 class="text-xl md:text-2xl font-black text-slate-800 tracking-tight">ระบบนักเรียน</h2>
          </div>

          <div class="flex flex-col gap-3 flex-grow">
            <!-- Student List -->
            <router-link to="/students" class="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-bold p-4 rounded-2xl shadow-lg shadow-emerald-500/20 active:scale-[0.98] transition-all duration-300 flex items-center justify-between group">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white/20 rounded-xl flex items-center justify-center text-xl backdrop-blur-md border border-white/10 group-hover:scale-110 transition-transform shrink-0">
                  <i class="bi bi-person-lines-fill"></i>
                </div>
                <span class="text-sm tracking-wide">ดูรายชื่อเพื่อนทั้งห้อง</span>
              </div>
              <i class="bi bi-chevron-right opacity-70 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-lg shrink-0"></i>
            </router-link>

            <!-- My Profile -->
            <button @click="goToMyProfile" class="w-full bg-slate-50 hover:bg-emerald-50 active:scale-[0.98] text-slate-700 font-bold p-4 rounded-2xl border border-slate-100 hover:border-emerald-200 transition-all duration-300 flex items-center justify-between group text-left">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-slate-500 text-xl border border-slate-100 group-hover:scale-110 group-hover:text-emerald-500 transition-all shrink-0">
                  <i class="bi bi-person-badge"></i>
                </div>
                <span class="group-hover:text-emerald-700 transition-colors text-sm">โปรไฟล์ของฉัน</span>
              </div>
              <i class="bi bi-chevron-right text-slate-400 group-hover:text-emerald-600 shrink-0 transition-colors"></i>
            </button>

            <!-- Admin Actions -->
            <template v-if="canManageStudents">
              <router-link to="/students/add" class="w-full bg-slate-50 hover:bg-emerald-50 active:scale-[0.98] text-slate-700 font-bold p-4 rounded-2xl border border-slate-100 hover:border-emerald-200 transition-all duration-300 flex items-center justify-between group text-left">
                <div class="flex items-center gap-4">
                  <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-slate-500 text-xl border border-slate-100 group-hover:scale-110 group-hover:text-emerald-500 transition-all shrink-0">
                    <i class="bi bi-person-plus-fill"></i>
                  </div>
                  <span class="group-hover:text-emerald-700 transition-colors text-sm">เพิ่มนักเรียนใหม่</span>
                </div>
                <i class="bi bi-chevron-right text-slate-400 group-hover:text-emerald-600 shrink-0 transition-colors"></i>
              </router-link>
              <router-link to="/students/export" class="mt-2 text-xs font-bold text-slate-400 hover:text-emerald-600 transition-colors flex items-center justify-center gap-2 py-2 active:scale-95 w-full bg-transparent">
                <i class="bi bi-file-earmark-excel-fill text-sm"></i> สร้างไฟล์ Export (Excel)
              </router-link>
            </template>
          </div>
        </div>

        <!-- 4. FINANCE WIDGET (Span 2 Columns on Desktop) -->
        <div class="lg:col-span-2 relative overflow-hidden bg-gradient-to-r from-amber-500 to-orange-500 rounded-[2rem] shadow-xl shadow-orange-500/20 hover:shadow-2xl hover:-translate-y-1 transition-all duration-500 group">
          <!-- Ambient Textures -->
          <div class="absolute inset-0 bg-white/5 opacity-50 mix-blend-overlay pointer-events-none"></div>
          
          <div class="relative z-10 p-6 md:p-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            <div class="flex items-center gap-5 w-full md:w-auto">
              <div class="w-16 h-16 bg-white/20 backdrop-blur-md rounded-2xl flex items-center justify-center text-3xl text-white shadow-inner border border-white/30 shrink-0 group-hover:rotate-6 transition-transform duration-500">
                <i class="bi bi-wallet2"></i>
              </div>
              <div class="min-w-0">
                <h2 class="text-2xl font-black text-white mb-1.5 tracking-tight drop-shadow-sm">การเงินห้อง</h2>
                <p class="text-orange-50 font-medium text-sm tracking-wide">จัดการรายรับ-จ่าย, โปรเจกต์เก็บเงิน, และติดตามบิล</p>
              </div>
            </div>

            <!-- Finance Actions -->
            <div class="grid grid-cols-2 sm:flex sm:flex-wrap sm:justify-end gap-3 w-full md:w-auto">
              <router-link to="/finance" class="flex items-center justify-center px-5 py-3 bg-amber-900/90 hover:bg-slate-900 text-white text-sm font-bold rounded-xl transition-all shadow-lg active:scale-95 whitespace-nowrap">
                <i class="bi bi-bar-chart-fill me-2"></i> สรุปยอด
              </router-link>
              <router-link to="/finance/transactions" class="flex items-center justify-center px-5 py-3 bg-white hover:bg-orange-50 text-amber-900 text-sm font-bold rounded-xl transition-all shadow-lg active:scale-95 whitespace-nowrap">
                <i class="bi bi-receipt-cutoff me-2"></i> ประวัติ
              </router-link>
              <router-link to="/finance/collections" class="flex items-center justify-center px-5 py-3 bg-white hover:bg-orange-50 text-amber-900 text-sm font-bold rounded-xl transition-all shadow-lg active:scale-95 whitespace-nowrap">
                <i class="bi bi-box-seam-fill me-2"></i> โปรเจกต์
              </router-link>
              <router-link v-if="isAdmin" to="/finance/debtors" class="flex items-center justify-center px-5 py-3 bg-rose-600 hover:bg-rose-700 text-white text-sm font-bold rounded-xl transition-all shadow-lg active:scale-95 whitespace-nowrap border border-rose-500">
                <i class="bi bi-exclamation-triangle-fill me-2"></i> ทวงหนี้
              </router-link>
            </div>
          </div>
        </div>

        <!-- 5. DISCORD ANNOUNCEMENT WIDGET (Fixed Bug: Added lg:col-span-2) -->
        <div class="lg:col-span-2 relative overflow-hidden bg-gradient-to-r from-rose-500 to-red-500 rounded-[2rem] shadow-xl shadow-rose-500/20 hover:shadow-2xl hover:-translate-y-1 transition-all duration-500 group">
          <div class="absolute inset-0 bg-white/5 opacity-50 mix-blend-overlay pointer-events-none"></div>

          <div class="relative z-10 p-6 md:p-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            <div class="flex items-center gap-5 w-full md:w-auto">
              <div class="w-16 h-16 bg-white/20 backdrop-blur-md rounded-2xl flex items-center justify-center text-3xl text-white shadow-inner border border-white/30 shrink-0 group-hover:-rotate-6 transition-transform duration-500">
                <i class="bi bi-broadcast"></i>
              </div>
              <div class="min-w-0">
                <h2 class="text-2xl font-black text-white mb-1.5 tracking-tight drop-shadow-sm">ประกาศเข้า Discord</h2>
                <p class="text-rose-50 font-medium text-sm tracking-wide">พิมพ์ประกาศผ่านเว็บไซต์ ส่งตรงเข้าเซิร์ฟเวอร์ห้องทันที</p>
              </div>
            </div>

            <!-- Discord Actions -->
            <div class="flex flex-col sm:flex-row gap-3 w-full md:w-auto">
              <router-link to="/messages" class="flex items-center justify-center px-6 py-3 bg-rose-900/90 hover:bg-slate-900 text-white text-sm font-bold rounded-xl transition-all shadow-lg active:scale-95 whitespace-nowrap">
                <i class="bi bi-megaphone-fill me-2"></i> เขียนประกาศ
              </router-link>
              <router-link to="/discord-connect" class="flex items-center justify-center px-6 py-3 bg-white hover:bg-rose-50 text-rose-700 text-sm font-bold rounded-xl transition-all shadow-lg active:scale-95 whitespace-nowrap">
                <i class="bi bi-discord me-2"></i> จัดการบอท
              </router-link>
            </div>
          </div>
        </div>

        <!-- 6. ROADMAP WIDGET -->
        <div class="lg:col-span-2 group">
          <router-link to="/roadmap" class="bg-slate-900 hover:bg-slate-800 rounded-[2rem] p-6 md:p-8 shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-500 cursor-pointer border border-slate-800 flex items-center justify-between">
            <div class="flex items-center gap-5">
              <div class="w-14 h-14 bg-slate-800 rounded-2xl flex items-center justify-center text-2xl text-blue-400 shadow-inner border border-slate-700 shrink-0 group-hover:scale-110 group-hover:bg-blue-500 group-hover:text-white transition-all duration-500">
                <i class="bi bi-map"></i>
              </div>
              <div class="min-w-0">
                <h2 class="text-xl md:text-2xl font-bold text-white mb-1">แผนผังห้องเรียน</h2>
                <p class="text-slate-400 font-medium text-sm truncate">โครงสร้างการบริหารและ Roadmap การทำงาน</p>
              </div>
            </div>
            <div class="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center text-slate-300 group-hover:bg-blue-600 group-hover:text-white group-hover:shadow-lg group-hover:shadow-blue-500/30 transition-all shrink-0">
              <i class="bi bi-arrow-right text-xl"></i>
            </div>
          </router-link>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
* {
  -webkit-tap-highlight-color: transparent;
}
</style>