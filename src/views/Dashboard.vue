<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import Swal from 'sweetalert2';

const router = useRouter();
const authStore = useAuthStore();

// ✨ ระบบชื่อใหม่ ดึงจาก authStore โดยตรง
const userName = computed(() => authStore.currentUserName || 'User');
const role = computed(() => authStore.currentRole || 'Unknown');
const isAdmin = computed(() => authStore.isAdmin);

// ✨ ดึง roomCode จาก Store
const roomCode = computed(() => authStore.currentRoomCode || 'N/A');

// ✨ ฟีเจอร์สลับห้องเรียน (กลับไปหน้า lobby)
const handleChangeRoom = () => {
  authStore.clearRoom();
  router.push('/lobby'); 
};

const goToMyProfile = async () => {
  try {
    Swal.fire({ title: 'กำลังดึงข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
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
  <div class="relative overflow-hidden pb-12 bg-slate-50/50 min-h-screen">
    <div class="max-w-7xl mx-auto space-y-6 md:space-y-8 relative z-10 p-4 sm:p-6 md:p-8">
      
      <!-- 1. HERO SECTION (สีฟ้า และลดขนาดตัวหนังสือ) -->
      <div class="relative bg-gradient-to-br from-blue-700 via-indigo-600 to-violet-700 rounded-[2.5rem] p-6 md:p-10 shadow-[0_10px_40px_-10px_rgba(79,70,229,0.4)] overflow-hidden group">
        <!-- Glow Effects -->
        <div class="absolute top-0 right-0 w-64 h-64 bg-white/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/3 transition-transform duration-700 group-hover:scale-110"></div>
        <div class="absolute bottom-0 left-10 w-48 h-48 bg-blue-400/20 rounded-full blur-2xl translate-y-1/2 transition-transform duration-700 group-hover:scale-110"></div>
        <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')] opacity-10 mix-blend-overlay pointer-events-none"></div>

        <div class="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center gap-6 md:gap-8">
          <div class="text-white">
            <h1 class="text-2xl md:text-3xl lg:text-4xl font-black tracking-tight mb-2 drop-shadow-md">สวัสดี, {{ userName }}! 👋</h1>
            <p class="text-blue-100 text-sm md:text-base font-medium tracking-wide opacity-90">ยินดีต้อนรับสู่แดชบอร์ดจัดการห้องเรียน</p>
          </div>
          
          <div class="flex flex-wrap items-center w-full md:w-auto gap-3 md:gap-4">
            <div class="bg-white/10 backdrop-blur-xl border border-white/20 px-5 py-3 rounded-[1.25rem] flex items-center gap-3 shadow-lg">
              <i class="bi bi-key-fill text-blue-200 text-lg"></i>
              <div class="flex flex-col">
                <span class="text-[10px] font-black text-blue-200 uppercase tracking-widest leading-none mb-1">Room Code</span>
                <span class="text-white font-mono font-bold text-sm md:text-base tracking-widest leading-none">{{ roomCode }}</span>
              </div>
            </div>

            <div class="bg-white/10 backdrop-blur-xl border border-white/20 px-5 py-3 rounded-[1.25rem] flex items-center gap-3 shadow-lg h-full">
              <span class="relative flex h-2.5 w-2.5">
                <span :class="isAdmin ? 'bg-emerald-400' : 'bg-blue-400'" class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"></span>
                <span :class="isAdmin ? 'bg-emerald-400' : 'bg-blue-400'" class="relative inline-flex rounded-full h-2.5 w-2.5"></span>
              </span>
              <span class="text-white font-black text-xs md:text-sm tracking-widest uppercase leading-none mt-0.5">{{ role }}</span>
            </div>

            <button 
              @click="handleChangeRoom"
              class="h-11 w-11 md:h-12 md:w-12 bg-white/10 hover:bg-white/20 active:scale-95 backdrop-blur-xl border border-white/20 rounded-[1.25rem] flex items-center justify-center text-white transition-all shadow-lg"
              title="สลับห้องเรียน"
            >
              <i class="bi bi-arrow-left-right text-base md:text-lg"></i>
            </button>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 md:gap-8">
        
        <!-- 2. TASKS WIDGET -->
        <div class="bg-white rounded-[2.5rem] shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-slate-200/60 p-8 md:p-10 flex flex-col hover:shadow-xl hover:border-blue-200/60 transition-all duration-500 group/card">
          <div class="flex items-center gap-5 mb-8">
            <div class="w-16 h-16 bg-gradient-to-br from-blue-50 to-indigo-50 text-blue-600 rounded-[1.5rem] flex items-center justify-center text-2xl shadow-inner border border-blue-100 group-hover/card:scale-105 transition-transform duration-500">
              <i class="bi bi-journal-check"></i>
            </div>
            <h2 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight">ตารางและงาน</h2>
          </div>
          
          <div class="flex flex-col gap-4 mb-8">
            <router-link to="/tasks" class="flex items-center justify-between p-5 bg-slate-50 hover:bg-white hover:shadow-lg active:scale-[0.98] rounded-[1.5rem] transition-all duration-300 border border-slate-100 hover:border-blue-100 group">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-xl border border-slate-100 group-hover:scale-110 transition-transform">📋</div>
                <span class="font-bold text-slate-700 text-base">ดูรายการงานทั้งหมด</span>
              </div>
              <div class="w-10 h-10 rounded-full bg-white flex items-center justify-center border border-slate-200 group-hover:border-blue-200 group-hover:bg-blue-50 transition-colors shadow-sm">
                <i class="bi bi-arrow-right text-slate-400 group-hover:text-blue-600"></i>
              </div>
            </router-link>
            
            <router-link v-if="isAdmin" to="/tasks/add" class="flex items-center justify-between p-5 bg-slate-50 hover:bg-white hover:shadow-lg active:scale-[0.98] rounded-[1.5rem] transition-all duration-300 border border-slate-100 hover:border-blue-100 group">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-xl border border-slate-100 group-hover:scale-110 transition-transform">➕</div>
                <span class="font-bold text-slate-700 text-base">เพิ่มงาน / โน้ตใหม่</span>
              </div>
              <div class="w-10 h-10 rounded-full bg-white flex items-center justify-center border border-slate-200 group-hover:border-blue-200 group-hover:bg-blue-50 transition-colors shadow-sm">
                <i class="bi bi-arrow-right text-slate-400 group-hover:text-blue-600"></i>
              </div>
            </router-link>

            <div v-else class="flex items-center justify-center p-5 bg-slate-50/50 rounded-[1.5rem] border border-dashed border-slate-200 text-slate-400 font-medium text-sm">
              <i class="bi bi-lock-fill me-2"></i> เฉพาะแอดมินที่เพิ่มงานได้
            </div>
          </div>

          <div class="mt-auto pt-6 border-t border-slate-100">
            <div class="flex flex-wrap gap-3">
              <router-link to="/schedules" class="flex-1 text-center px-5 py-3.5 bg-slate-100 hover:bg-slate-800 hover:text-white text-slate-600 font-bold text-sm rounded-2xl transition-colors active:scale-95">ตารางเรียนยืนพื้น</router-link>
              <router-link v-if="isAdmin" to="/schedules" class="flex-1 text-center px-5 py-3.5 bg-rose-50 hover:bg-rose-600 hover:text-white text-rose-600 font-bold text-sm rounded-2xl transition-colors border border-rose-100 active:scale-95">ข้อยกเว้นฉุกเฉิน</router-link>
            </div>
          </div>
        </div>

        <!-- 3. STUDENTS WIDGET -->
        <div class="bg-white rounded-[2.5rem] shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-slate-200/60 p-8 md:p-10 flex flex-col hover:shadow-xl hover:border-emerald-200/60 transition-all duration-500 group/card">
          <div class="flex items-center gap-5 mb-8">
            <div class="w-16 h-16 bg-gradient-to-br from-emerald-50 to-teal-50 text-emerald-600 rounded-[1.5rem] flex items-center justify-center text-2xl shadow-inner border border-emerald-100 group-hover/card:scale-105 transition-transform duration-500">
              <i class="bi bi-people-fill"></i>
            </div>
            <h2 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight">ระบบนักเรียน</h2>
          </div>
          
          <div class="flex flex-col gap-4 flex-grow">
            <!-- ✨ แก้ไขปุ่มรายชื่อเพื่อนให้กลับมาเป็นสีเขียว Gradient แบบดั้งเดิม -->
            <router-link to="/students" class="w-full bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-bold p-5 rounded-[1.5rem] shadow-lg shadow-emerald-600/20 active:scale-[0.98] transition-all duration-300 flex items-center justify-between group">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white/20 rounded-xl flex items-center justify-center text-xl backdrop-blur-md border border-white/10 group-hover:scale-110 transition-transform">📑</div>
                <span class="text-base tracking-wide">ดูรายชื่อเพื่อนทั้งห้อง</span>
              </div>
              <i class="bi bi-arrow-right opacity-70 group-hover:opacity-100 transition-opacity text-xl"></i>
            </router-link>
            
            <button @click="goToMyProfile" class="w-full bg-slate-50 hover:bg-white hover:shadow-lg active:scale-[0.98] text-slate-700 font-bold p-5 rounded-[1.5rem] border border-slate-100 hover:border-blue-100 transition-all duration-300 flex items-center justify-between group text-left">
              <div class="flex items-center gap-4">
                <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-xl border border-slate-100 group-hover:scale-110 transition-transform">🪪</div>
                <span class="group-hover:text-blue-600 transition-colors text-base">โปรไฟล์ของฉัน</span>
              </div>
              <div class="w-10 h-10 rounded-full bg-white flex items-center justify-center border border-slate-200 group-hover:border-blue-200 group-hover:bg-blue-50 transition-colors shadow-sm">
                <i class="bi bi-person-badge text-slate-400 group-hover:text-blue-600"></i>
              </div>
            </button>

            <template v-if="isAdmin">
              <router-link to="/students/add" class="w-full bg-slate-50 hover:bg-white hover:shadow-lg active:scale-[0.98] text-slate-700 font-bold p-5 rounded-[1.5rem] border border-slate-100 hover:border-emerald-100 transition-all duration-300 flex items-center justify-between group text-left mt-2">
                <div class="flex items-center gap-4">
                  <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-xl border border-slate-100 group-hover:scale-110 transition-transform">➕</div>
                  <span class="group-hover:text-emerald-600 transition-colors text-base">เพิ่มนักเรียนใหม่</span>
                </div>
                <div class="w-10 h-10 rounded-full bg-white flex items-center justify-center border border-slate-200 group-hover:border-emerald-200 group-hover:bg-emerald-50 transition-colors shadow-sm">
                  <i class="bi bi-person-plus text-slate-400 group-hover:text-emerald-600"></i>
                </div>
              </router-link>
              <router-link to="/students/export" class="text-xs font-bold text-slate-400 hover:text-emerald-600 mt-2 transition-colors flex items-center justify-center gap-1.5 py-2 active:scale-95 w-full bg-transparent">
                <i class="bi bi-file-earmark-excel"></i> สร้างไฟล์ Export (Excel)
              </router-link>
            </template>
          </div>
        </div>

        <!-- 4. FINANCE WIDGET -->
        <div class="lg:col-span-2 relative overflow-hidden bg-gradient-to-br from-amber-500 to-orange-600 rounded-[2.5rem] shadow-xl shadow-orange-500/20 hover:shadow-2xl hover:-translate-y-1 transition-all duration-500 group border border-orange-400/50">
          <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')] opacity-10 mix-blend-overlay"></div>
          
          <div class="relative z-10 p-8 md:p-12 flex flex-col md:flex-row items-center justify-between gap-8">
            <div class="flex items-center gap-6 w-full md:w-auto">
              <div class="w-20 h-20 md:w-24 md:h-24 bg-white/20 backdrop-blur-xl rounded-[1.5rem] flex items-center justify-center text-4xl shadow-inner border border-white/30 shrink-0 group-hover:rotate-12 transition-transform duration-500">💰</div>
              <div>
                <h2 class="text-3xl md:text-4xl font-black text-white mb-2 tracking-tight drop-shadow-sm">การเงินห้อง</h2>
                <p class="text-orange-100 font-bold text-sm md:text-base tracking-wide">จัดการรายรับ-จ่าย, โปรเจกต์เก็บเงิน, และติดตามบิล</p>
              </div>
            </div>
            
            <div class="grid grid-cols-2 md:flex md:flex-wrap md:justify-end gap-3 md:gap-4 w-full md:w-auto">
              <router-link to="/finance" class="flex items-center justify-center py-4 px-6 bg-amber-950 hover:bg-slate-900 text-white text-sm font-bold rounded-2xl transition-all shadow-lg active:scale-95">
                <i class="bi bi-bar-chart-fill me-2"></i> สรุปยอด
              </router-link>
              <router-link to="/finance/transactions" class="flex items-center justify-center py-4 px-6 bg-white/90 hover:bg-white text-amber-900 text-sm font-bold rounded-2xl transition-all shadow-lg backdrop-blur-md active:scale-95">
                <i class="bi bi-receipt-cutoff me-2"></i> ประวัติ
              </router-link>
              <router-link to="/finance/collections" class="flex items-center justify-center py-4 px-6 bg-white/90 hover:bg-white text-amber-900 text-sm font-bold rounded-2xl transition-all shadow-lg backdrop-blur-md active:scale-95">
                <i class="bi bi-box-seam-fill me-2"></i> โปรเจกต์
              </router-link>
              <router-link v-if="isAdmin" to="/finance/debtors" class="flex items-center justify-center py-4 px-6 bg-rose-600 hover:bg-rose-700 text-white text-sm font-bold rounded-2xl transition-all shadow-lg border border-rose-500 active:scale-95">
                <i class="bi bi-exclamation-triangle-fill me-2"></i> ทวงหนี้
              </router-link>
            </div>
          </div>
        </div>

        <!-- 5. ROADMAP WIDGET -->
        <div class="lg:col-span-2 group">
          <router-link to="/roadmap" class="bg-slate-900 rounded-[2.5rem] p-8 shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-500 cursor-pointer border border-slate-800 flex items-center justify-between">
            <div class="flex items-center gap-6">
              <div class="w-16 h-16 bg-slate-800 rounded-[1.5rem] flex items-center justify-center text-3xl shadow-inner border border-slate-700 shrink-0 group-hover:scale-110 transition-transform duration-500">
                🗺️
              </div>
              <div>
                <h2 class="text-xl md:text-2xl font-bold text-white mb-1">Class Roadmap & Committee</h2>
                <p class="text-slate-400 font-medium text-sm">แผนการดำเนินงานของคณะกรรมการห้อง</p>
              </div>
            </div>
            <div class="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center text-white group-hover:bg-blue-600 group-hover:shadow-lg group-hover:shadow-blue-500/30 transition-all shrink-0">
              <i class="bi bi-chevron-right text-xl"></i>
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

@keyframes shimmer {
  100% { transform: translateX(100%); }
}
</style>