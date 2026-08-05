<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { ClassroomService } from '@/services/classroom';
import type { UserRoom } from '@/types/classroom';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const router = useRouter();

const isLoadingRooms = ref(true);
const rooms = ref<UserRoom[]>([]);
const searchQuery = ref('');

// --- Modal States ---
const showCreateModal = ref(false);
const showJoinModal = ref(false);

const createForm = ref({ room_name: '' });
const joinForm = ref({ room_code: '', student_no: null as number | null, first_name: '', last_name: '' });

onMounted(async () => {
  if (!authStore.userId) {
    isLoadingRooms.value = false;
    return;
  }
  
  if (!authStore.firstName) {
    await authStore.fetchProfile();
  }
  
  await fetchRooms();
});

const fetchRooms = async () => {
  isLoadingRooms.value = true;
  try {
    rooms.value = await ClassroomService.getUserRooms(authStore.userId!);
  } catch (error: any) {
    console.error("Failed to load rooms:", error);
  } finally {
    isLoadingRooms.value = false;
  }
};

const filteredRooms = computed(() => {
  if (!searchQuery.value) return rooms.value;
  const q = searchQuery.value.toLowerCase();
  return rooms.value.filter(r => 
    (r.room_name && r.room_name.toLowerCase().includes(q)) ||
    (r.room_code && r.room_code.toLowerCase().includes(q))
  );
});

const selectRoom = (room: UserRoom) => {
  // 🎯 ยัดสิทธิ์ (is_admin, permissions) เข้า Store ตอนเลือกห้อง!
  authStore.setRoom(
    room.room_id, 
    room.room_name, 
    room.room_code, 
    room.role, 
    authStore.currentUserName,
    room.is_admin || false,
    room.permissions || []
  );
  router.push('/dashboard');
};

const openJoinModal = () => {
  joinForm.value = {
    room_code: '',
    student_no: null,
    first_name: authStore.firstName !== 'ไม่ระบุชื่อ' ? (authStore.firstName || '') : '',
    last_name: authStore.lastName || ''
  };
  showJoinModal.value = true;
};

const submitJoinRoom = async () => {
  // ✅ ตรวจสอบข้อมูลก่อนส่ง (รหัส, เลขที่, ชื่อ-นามสกุล)
  const code = joinForm.value.room_code.trim().toUpperCase();
  const no = Number(joinForm.value.student_no);

  if (!code) {
    return Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกรหัสเข้าห้อง', 'warning');
  }
  if (!no || no <= 0) {
    return Swal.fire('ข้อมูลไม่ถูกต้อง', 'กรุณากรอกเลขที่ที่ถูกต้อง', 'warning');
  }
  if (!joinForm.value.first_name.trim() || !joinForm.value.last_name.trim()) {
    return Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกชื่อและนามสกุลให้ครบถ้วน', 'warning');
  }

  try {
    Swal.fire({ title: 'กำลังตรวจสอบข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });

    const payload = {
      room_code: code,
      student_no: no,
      first_name: joinForm.value.first_name.trim(),
      last_name: joinForm.value.last_name.trim()
    };

    const result = await ClassroomService.joinRoom(payload);

    Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: result.message || 'เข้าสู่ห้องเรียนสำเร็จ',
      confirmButtonText: 'เข้าสู่แดชบอร์ด',
      confirmButtonColor: '#10b981',
      customClass: { popup: 'rounded-[2rem]', confirmButton: 'rounded-xl px-8 font-bold' }
    }).then(() => {
      showJoinModal.value = false;
      // 🎯 เข้าห้องใหม่ สิทธิ์ตั้งต้นจะเป็น False และ []
      authStore.setRoom(result.room_id, result.room_name, payload.room_code, 'student', authStore.currentUserName, false, []);
      router.push('/dashboard');
    });

  } catch (error: any) {
    Swal.fire({
      icon: 'error',
      title: 'ไม่สามารถเข้าร่วมได้',
      text: error.message || 'รหัสห้องผิด หรือเลขที่นี้มีผู้ใช้งานแล้ว',
      customClass: { popup: 'rounded-[2rem] shadow-xl' },
      confirmButtonColor: '#0f172a',
      confirmButtonText: 'รับทราบ'
    });
  }
};

const submitCreateRoom = async () => {
  try {
    Swal.fire({ title: 'กำลังสร้างห้อง...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
    const result = await ClassroomService.createRoom({ room_name: createForm.value.room_name });
    
    Swal.fire({
      icon: 'success',
      title: 'สร้างห้องเรียนสำเร็จ!',
      text: `นำรหัสห้อง ${result.room_code} ไปแชร์ให้นักเรียนได้เลย`,
      confirmButtonText: 'ตกลง',
      confirmButtonColor: '#3b82f6',
      customClass: { popup: 'rounded-[2rem]' }
    }).then(() => {
      showCreateModal.value = false;
      fetchRooms();
    });
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error.message || 'ไม่สามารถสร้างห้องได้', 'error');
  }
};
</script>

<template>
  <div class="max-w-6xl mx-auto pt-4 md:pt-10 pb-20 relative z-10">
    
    <div class="text-center mb-12 md:mb-16">
      <div class="inline-flex items-center justify-center w-20 h-20 bg-white rounded-3xl shadow-xl shadow-blue-500/10 border border-slate-100 mb-6">
        <i class="bi bi-grid-fill text-4xl text-transparent bg-clip-text bg-gradient-to-br from-blue-600 to-indigo-600"></i>
      </div>
      <h1 class="text-3xl md:text-5xl font-black text-slate-800 tracking-tight mb-4">ยินดีต้อนรับ, <span class="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600">{{ authStore.firstName || 'ผู้ใช้งาน' }}</span> 👋</h1>
      <p class="text-slate-500 text-base md:text-lg font-medium max-w-2xl mx-auto">เลือกห้องเรียนของคุณเพื่อเริ่มต้นการจัดการ หรือเข้าร่วมห้องเรียนใหม่ผ่านรหัสห้อง</p>
    </div>

    <div class="flex flex-col sm:flex-row justify-between items-center gap-4 mb-10">
      <div class="relative w-full sm:w-96 group">
        <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
          <i class="bi bi-search text-slate-400 group-focus-within:text-blue-500 transition-colors"></i>
        </div>
        <input 
          v-model="searchQuery" 
          type="text" 
          placeholder="ค้นหาชื่อห้อง หรือ รหัส..." 
          class="block w-full pl-11 pr-4 py-3.5 bg-white border border-slate-200 rounded-[1.25rem] text-sm font-bold text-slate-700 shadow-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
        >
      </div>
      
      <div class="flex gap-3 w-full sm:w-auto">
        <button @click="openJoinModal" class="flex-1 sm:flex-none px-6 py-3.5 bg-white border border-slate-200 hover:border-blue-300 hover:shadow-md hover:text-blue-600 text-slate-600 font-bold rounded-[1.25rem] transition-all active:scale-95 flex items-center justify-center gap-2">
          <i class="bi bi-door-open-fill"></i> เข้าห้องเรียน
        </button>
        <button @click="showCreateModal = true" class="flex-1 sm:flex-none px-6 py-3.5 bg-slate-900 hover:bg-slate-800 text-white font-bold rounded-[1.25rem] shadow-lg shadow-slate-900/20 transition-all active:scale-95 flex items-center justify-center gap-2">
          <i class="bi bi-plus-lg"></i> สร้างห้อง
        </button>
      </div>
    </div>

    <div v-if="isLoadingRooms" class="flex justify-center items-center py-20">
      <div class="animate-spin rounded-full h-12 w-12 border-4 border-slate-200 border-t-blue-600"></div>
    </div>
    
    <div v-else-if="filteredRooms.length === 0" class="text-center py-20 bg-white rounded-[2rem] border border-slate-100 border-dashed">
      <div class="text-slate-300 mb-4"><i class="bi bi-inbox-fill text-6xl"></i></div>
      <h3 class="text-xl font-bold text-slate-600 mb-2">ยังไม่มีห้องเรียน</h3>
      <p class="text-slate-400">คุณสามารถสร้างห้องใหม่ หรือขอรหัสเพื่อเข้าร่วมห้องได้เลย</p>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div 
        v-for="room in filteredRooms" :key="room.room_id"
        @click="selectRoom(room)"
        class="group bg-white rounded-[2rem] p-6 border border-slate-200/60 shadow-[0_4px_20px_rgba(0,0,0,0.03)] hover:shadow-[0_8px_30px_rgba(59,130,246,0.12)] hover:border-blue-200 cursor-pointer transition-all duration-500 hover:-translate-y-1 relative overflow-hidden"
      >
        <div class="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-blue-50 to-transparent rounded-bl-full opacity-0 group-hover:opacity-100 transition-opacity duration-500"></div>
        
        <div class="flex justify-between items-start mb-6 relative z-10">
          <div class="w-14 h-14 bg-gradient-to-br from-slate-100 to-slate-50 rounded-2xl border border-slate-200/60 flex items-center justify-center text-slate-400 text-2xl group-hover:from-blue-50 group-hover:to-indigo-50 group-hover:text-blue-600 group-hover:border-blue-100 transition-all duration-500 shadow-inner">
            <i class="bi bi-buildings-fill"></i>
          </div>
          <!-- 🎯 โซนโชว์ป้าย (Role & Admin Badges) -->
          <div class="flex flex-col items-end gap-1.5">
            <span class="px-3 py-1 bg-slate-50 border border-slate-100 text-[10px] font-black tracking-widest uppercase text-slate-500 rounded-lg group-hover:bg-blue-50 group-hover:text-blue-600 group-hover:border-blue-100 transition-colors">
              {{ room.role }}
            </span>
            <span v-if="room.is_admin" class="px-2.5 py-0.5 bg-gradient-to-r from-amber-500 to-orange-400 text-white text-[9px] font-black tracking-widest uppercase rounded-md shadow-sm shadow-orange-500/20 border border-orange-300 flex items-center gap-1">
              <i class="bi bi-shield-lock-fill"></i> ADMIN
            </span>
            <span v-else-if="room.permissions && room.permissions.length > 0" class="px-2.5 py-0.5 bg-purple-100 text-purple-700 border border-purple-200 text-[9px] font-black tracking-widest uppercase rounded-md shadow-sm flex items-center gap-1">
              <i class="bi bi-key-fill"></i> STAFF
            </span>
          </div>
        </div>
        
        <div class="relative z-10">
          <h3 class="text-xl font-black text-slate-800 mb-1 line-clamp-1 group-hover:text-blue-700 transition-colors">{{ room.room_name }}</h3>
          <p class="text-sm font-bold text-slate-400 font-mono tracking-wide flex items-center gap-2">
            <i class="bi bi-key text-slate-300"></i> {{ room.room_code || 'ไม่มีรหัส' }}
          </p>
        </div>

        <div class="mt-6 pt-5 border-t border-slate-100 flex justify-between items-center relative z-10">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"></span>
            <span class="text-xs font-bold text-slate-500 uppercase tracking-wider">{{ room.status }}</span>
          </div>
          <div class="w-8 h-8 rounded-full bg-slate-50 flex items-center justify-center text-slate-400 group-hover:bg-blue-600 group-hover:text-white transition-colors duration-300 shadow-sm">
            <i class="bi bi-arrow-right"></i>
          </div>
        </div>
      </div>
    </div>

    <!-- Modals... (ยังคงเหมือนเดิม) -->
    <Transition name="fade">
      <div v-if="showJoinModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
        <div class="bg-white rounded-[2.5rem] p-8 md:p-10 w-full max-w-md shadow-2xl transform transition-all border border-slate-100">
          <div class="w-16 h-16 bg-blue-50 text-blue-600 rounded-2xl flex items-center justify-center text-3xl mb-6 shadow-inner border border-blue-100">
            <i class="bi bi-door-open-fill"></i>
          </div>
          <h2 class="text-2xl font-black text-slate-800 mb-2">เข้าร่วมห้องเรียน</h2>
          <p class="text-sm text-slate-500 mb-8 font-medium leading-relaxed">กรอกรหัส 6 หลัก และตรวจสอบชื่อของคุณให้ตรงกับระบบเพื่อยืนยันตัวตน</p>
          
          <form @submit.prevent="submitJoinRoom" class="space-y-4">
            <div>
              <label class="block text-[11px] font-black text-slate-400 uppercase tracking-widest mb-2">รหัสเข้าห้อง <span class="text-rose-500">*</span></label>
              <input v-model="joinForm.room_code" type="text" required placeholder="เช่น AB12CD" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-lg font-mono font-bold rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all uppercase placeholder:normal-case placeholder:font-sans placeholder:font-medium placeholder:text-slate-300">
            </div>
            
            <div class="grid grid-cols-3 gap-4">
              <div class="col-span-1">
                <label class="block text-[11px] font-black text-slate-400 uppercase tracking-widest mb-2">เลขที่ <span class="text-rose-500">*</span></label>
                <input v-model="joinForm.student_no" type="number" required class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-lg font-bold rounded-2xl px-4 py-4 text-center focus:bg-white focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all">
              </div>
              <div class="col-span-2">
                <label class="block text-[11px] font-black text-slate-400 uppercase tracking-widest mb-2">ชื่อจริง <span class="text-rose-500">*</span></label>
                <input v-model="joinForm.first_name" type="text" required class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all">
              </div>
            </div>

            <div>
              <label class="block text-[11px] font-black text-slate-400 uppercase tracking-widest mb-2">นามสกุล <span class="text-rose-500">*</span></label>
              <input v-model="joinForm.last_name" type="text" required class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all">
            </div>

            <div class="flex gap-3 mt-8 pt-4">
              <button type="button" @click="showJoinModal = false" class="flex-1 px-4 py-4 bg-slate-100 hover:bg-slate-200 text-slate-600 font-bold rounded-2xl transition-all active:scale-95">ยกเลิก</button>
              <button type="submit" class="flex-1 px-4 py-4 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-2xl shadow-lg shadow-blue-600/30 transition-all active:scale-95">ยืนยันเข้าร่วม</button>
            </div>
          </form>
        </div>
      </div>
    </Transition>

    <Transition name="fade">
      <div v-if="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
        <div class="bg-white rounded-[2.5rem] p-8 md:p-10 w-full max-w-md shadow-2xl transform transition-all border border-slate-100">
          <div class="w-16 h-16 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center text-3xl mb-6 shadow-inner border border-indigo-100">
            <i class="bi bi-plus-circle-fill"></i>
          </div>
          <h2 class="text-2xl font-black text-slate-800 mb-2">สร้างห้องเรียนใหม่</h2>
          <p class="text-sm text-slate-500 mb-8 font-medium">ตั้งชื่อห้องเรียนของคุณ ระบบจะสร้างรหัสสำหรับแชร์ให้นักเรียนอัตโนมัติ</p>
          
          <form @submit.prevent="submitCreateRoom">
            <div class="mb-8">
              <label class="block text-[11px] font-black text-slate-400 uppercase tracking-widest mb-2">ชื่อห้องเรียน <span class="text-rose-500">*</span></label>
              <input v-model="createForm.room_name" type="text" required placeholder="เช่น ม.4/1, สมเกียรติวิทยา" class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-lg font-bold rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 outline-none transition-all placeholder:font-medium placeholder:text-slate-300">
            </div>
            <div class="flex gap-3">
              <button type="button" @click="showCreateModal = false" class="flex-1 px-4 py-4 bg-slate-100 hover:bg-slate-200 text-slate-600 font-bold rounded-2xl transition-all active:scale-95">ยกเลิก</button>
              <button type="submit" class="flex-1 px-4 py-4 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-2xl shadow-lg shadow-indigo-600/30 transition-all active:scale-95">สร้างห้อง</button>
            </div>
          </form>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>