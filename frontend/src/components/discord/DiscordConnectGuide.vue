<script setup lang="ts">
import { computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';

const authStore = useAuthStore();

const currentRoomCode = computed(() => {
  return authStore.currentRoomCode || 'N/A';
});

const botInviteUrl = computed(() => {
  return import.meta.env.VITE_DISCORD_BOT_INVITE_URL || '#';
});

const copyRoomCode = async () => {
  try {
    await navigator.clipboard.writeText(currentRoomCode.value);
    Swal.fire({
      icon: 'success',
      title: 'คัดลอกแล้ว!',
      text: `รหัสห้อง "${currentRoomCode.value}" ถูกคัดลอกไปยังคลิปบอร์ดแล้ว`,
      timer: 2000,
      showConfirmButton: false,
      customClass: { popup: 'rounded-3xl' },
    });
  } catch {
    Swal.fire({
      icon: 'error',
      title: 'ไม่สามารถคัดลอกได้',
      text: 'กรุณาคัดลอกด้วยตนเอง',
      customClass: { popup: 'rounded-3xl' },
    });
  }
};
</script>

<template>
  <div class="min-h-[80vh] w-full flex items-center justify-center p-4">
    <div class="bg-white shadow-xl border border-slate-200/60 rounded-[1.75rem] sm:rounded-[2rem] overflow-hidden max-w-2xl w-full">
    <!-- Header -->
    <div class="bg-gradient-to-r from-[#5865F2] to-[#4752C4] px-4 sm:px-6 py-4 sm:py-5 flex items-center gap-3 sm:gap-4">
      <!-- Discord SVG icon -->
      <svg
        class="w-9 h-9 sm:w-10 sm:h-10 shrink-0"
        viewBox="0 0 127.14 96.36"
        fill="white"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z"
        />
      </svg>
      <div class="min-w-0">
        <h2 class="text-white text-lg sm:text-xl font-black tracking-tight">
          เชื่อมต่อ Discord
        </h2>
        <p class="text-indigo-200 text-sm font-medium truncate">
          รับการแจ้งเตือนและเช็คข้อมูลส่วนตัวผ่านบอท
        </p>
      </div>
    </div>

    <!-- Body -->
    <div class="px-4 sm:px-6 py-5 sm:py-6 space-y-5">
      <!-- Step 1 -->
      <div class="flex gap-4">
        <div
          class="w-9 h-9 rounded-full bg-[#5865F2] text-white font-black text-sm flex items-center justify-center shrink-0"
        >
          1
        </div>
        <div class="flex-1 min-w-0">
          <h3 class="font-bold text-slate-800 text-base mb-1">
            เชิญบอทเข้าเซิร์ฟเวอร์ของคุณ
          </h3>
          <p class="text-slate-500 text-sm leading-relaxed mb-3">
            คลิกปุ่มด้านล่างเพื่อเพิ่มบอทลงในเซิร์ฟเวอร์ Discord
            ที่คุณต้องการรับการแจ้งเตือน
          </p>
          <a
            :href="botInviteUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-2 px-6 py-3 bg-[#5865F2] hover:bg-[#4752C4] text-white font-bold rounded-2xl transition-all shadow-md"
          >
            <svg
              class="w-5 h-5"
              viewBox="0 0 127.14 96.36"
              fill="currentColor"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.7,77.7,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.25,105.25,0,0,0,126.6,80.22h0C129.24,52.84,122.09,29.11,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z"
              />
            </svg>
            เพิ่มบอทลง Discord
          </a>
        </div>
      </div>

      <!-- Divider -->
      <div class="flex items-center gap-3">
        <span class="flex-1 h-px bg-slate-200"></span>
        <span class="text-xs font-bold text-slate-400 uppercase tracking-widest"
          >จากนั้น</span
        >
        <span class="flex-1 h-px bg-slate-200"></span>
      </div>

      <!-- Step 2 -->
      <div class="flex gap-4">
        <div
          class="w-9 h-9 rounded-full bg-[#5865F2] text-white font-black text-sm flex items-center justify-center shrink-0"
        >
          2
        </div>
        <div class="flex-1 min-w-0">
          <h3 class="font-bold text-slate-800 text-base mb-1">
            พิมพ์คำสั่งใน Discord
          </h3>
          <p class="text-slate-500 text-sm leading-relaxed mb-3">
            หลังจากเพิ่มบอทแล้ว ให้พิมพ์คำสั่งด้านล่างในช่องแชท
            (หรือ DM หาบอท) เพื่อเชื่อมต่อบัญชีของคุณกับห้องเรียน
          </p>

          <!-- Command box -->
          <div
            class="bg-slate-50 border border-slate-200 rounded-2xl p-4 space-y-3"
          >
            <div
              class="bg-slate-800 text-green-300 font-mono text-sm px-4 py-3 rounded-xl overflow-x-auto whitespace-nowrap"
            >
              <span class="text-slate-400">/</span>sync_room
              <span class="text-yellow-300">{{ currentRoomCode }}&nbsp;</span><span class="text-blue-300">5</span>
            </div>
            <p class="text-xs text-slate-400 leading-relaxed">
              เปลี่ยนเลข
              <span class="text-blue-400 font-bold">5</span>
              เป็นเลขที่ของคุณ (เช่น
              <span class="text-blue-400 font-bold">1</span>,
              <span class="text-blue-400 font-bold">12</span>,
              <span class="text-blue-400 font-bold">30</span>)
            </p>
          </div>

          <!-- Room code copy -->
          <div class="mt-3 flex items-center gap-2">
            <span class="text-sm font-semibold text-slate-600"
              >รหัสห้อง:</span
            >
            <code
              class="bg-slate-100 text-slate-800 font-mono font-bold px-3 py-1.5 rounded-lg text-sm"
            >
              {{ currentRoomCode }}
            </code>
            <button
              class="ml-auto px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-600 font-bold rounded-xl transition-colors flex items-center gap-1.5 text-sm active:scale-95"
              @click="copyRoomCode"
            >
              <i class="bi bi-clipboard"></i>
              คัดลอก
            </button>
          </div>
        </div>
      </div>
    </div>
    <!-- Back to dashboard button -->
    <div class="px-4 sm:px-6 pb-5 sm:pb-6">
      <RouterLink to="/dashboard" class="px-6 py-3 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold rounded-xl transition-all active:scale-95 w-full inline-flex items-center justify-center">
        กลับสู่หน้าหลัก
      </RouterLink>
    </div>
  </div>
</div>
</template>
