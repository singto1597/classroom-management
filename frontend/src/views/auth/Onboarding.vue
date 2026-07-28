<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import api from '@/services/api';
import Swal from 'sweetalert2';

const router = useRouter();
const authStore = useAuthStore();

const form = ref({
  prefix: '',
  first_name: '',
  last_name: ''
});

const isSubmitting = ref(false);

onMounted(() => {
  // ดึงชื่อที่ Google แอบให้มา เป็นค่าเริ่มต้นเบื้องต้น (เผื่อเด็กขี้เกียจพิมพ์)
  form.value.first_name = authStore.firstName && authStore.firstName !== 'ไม่ระบุชื่อ' ? authStore.firstName : '';
  form.value.last_name = authStore.lastName || '';
});

const submitProfile = async () => {
  if (!form.value.prefix || !form.value.first_name || !form.value.last_name) {
    Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกคำนำหน้า ชื่อ และนามสกุลให้ครบถ้วน', 'warning');
    return;
  }

  isSubmitting.value = true;
  try {
    // 🚀 ยิง API อัปเดตข้อมูลตัวเอง
    await api.patch('/api/auth/me', {
      prefix: form.value.prefix,
      first_name: form.value.first_name,
      last_name: form.value.last_name
    });

    // 🔄 สั่งให้ Store ดึงข้อมูลใหม่ เพื่อรับรองว่า Onboard แล้ว
    await authStore.fetchProfile();
    
    // 🚪 ปล่อยผ่านเข้าล็อบบี้ได้เลย!
    router.push('/lobby');
    
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error.message || 'ไม่สามารถบันทึกข้อมูลได้', 'error');
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <div class="min-h-screen bg-slate-50 flex items-center justify-center p-4 relative overflow-hidden">
    <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-500/10 rounded-full blur-[100px] pointer-events-none -translate-y-1/2 translate-x-1/3"></div>
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] bg-indigo-500/10 rounded-full blur-[80px] pointer-events-none translate-y-1/2 -translate-x-1/3"></div>

    <div class="max-w-lg w-full bg-white/80 backdrop-blur-xl rounded-[2.5rem] shadow-2xl shadow-slate-200/50 border border-white p-8 md:p-12 relative z-10">
      
      <div class="w-20 h-20 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-[1.5rem] flex items-center justify-center shadow-lg shadow-blue-500/30 mb-8 mx-auto">
        <i class="bi bi-person-vcard text-white text-4xl"></i>
      </div>
      
      <div class="text-center mb-10">
        <h1 class="text-3xl font-black text-slate-800 tracking-tight mb-2">ตั้งค่าโปรไฟล์ครั้งแรก</h1>
        <p class="text-slate-500 font-medium text-sm">ข้อมูลนี้จะถูกใช้เพื่อยืนยันตัวตนและผูกเข้ากับรายชื่อในห้องเรียน กรุณากรอกให้ตรงตามความจริง</p>
      </div>

      <form @submit.prevent="submitProfile" class="space-y-5">
        
        <div>
          <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">คำนำหน้า <span class="text-rose-500">*</span></label>
          <div class="relative">
            <select v-model="form.prefix" required class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm appearance-none cursor-pointer">
              <option value="" disabled selected>เลือกคำนำหน้า</option>
              <option value="นาย">นาย</option>
              <option value="นางสาว">นางสาว</option>
              <option value="เด็กชาย">เด็กชาย (ด.ช.)</option>
              <option value="เด็กหญิง">เด็กหญิง (ด.ญ.)</option>
            </select>
            <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-5 text-slate-400">
              <i class="bi bi-chevron-down"></i>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div>
            <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">ชื่อจริง <span class="text-rose-500">*</span></label>
            <input v-model="form.first_name" type="text" required placeholder="สมชาย" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
          </div>
          <div>
            <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">นามสกุล <span class="text-rose-500">*</span></label>
            <input v-model="form.last_name" type="text" required placeholder="ใจดี" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
          </div>
        </div>

        <div class="pt-6">
          <button type="submit" :disabled="isSubmitting" class="w-full bg-slate-900 hover:bg-slate-800 text-white font-black text-lg py-4 rounded-2xl transition-all shadow-lg shadow-slate-900/20 active:scale-95 disabled:opacity-50 disabled:active:scale-100 flex items-center justify-center gap-2">
            <span v-if="isSubmitting" class="animate-spin inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full"></span>
            <span v-else>บันทึกและเข้าสู่ระบบ <i class="bi bi-arrow-right"></i></span>
          </button>
        </div>

      </form>
    </div>
  </div>
</template>