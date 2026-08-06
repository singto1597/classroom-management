<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { ActionService } from '@/services/action';
import { ClassroomService } from '@/services/classroom';
import Swal from 'sweetalert2';

const router = useRouter();
const authStore = useAuthStore();

const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

// สิทธิ์: แอดมิน หรือผู้ที่มีสิทธิ์จัดการการตั้งค่าห้อง (ประกาศ @everyone ทั้งห้อง)
const canSendMessage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_SETTINGS')
);

// ✨ สถานะการผูก Discord ของห้อง (ถ้าไม่ผูก → บอทจะไม่มีปลายทางประกาศ)
const isDiscordLinked = ref(false);
const isLoadingRoom = ref(true);

const fetchRoomStatus = async () => {
  isLoadingRoom.value = true;
  try {
    const roomData = await ClassroomService.getRoomData(currentRoomId);
    isDiscordLinked.value = !!roomData?.server_id;
  } catch {
    // เก็บค่าเริ่มต้น (false) ไว้ — การ์ดจะชี้ไปหน้าเชื่อมต่อ Discord
  } finally {
    isLoadingRoom.value = false;
  }
};

onMounted(fetchRoomStatus);

const messageForm = reactive({
  title: '',
  message: '',
  // ✨ default ชื่อเป็นชื่อผู้ใช้ (แอดมินแก้ได้) — backend แสดงใน footer ของ embed
  user_name: currentUserName
});

const isSubmitting = ref(false);
const charCount = computed(() => messageForm.message.length);

const handleSend = async () => {
  if (!canSendMessage.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแล (หรือผู้ที่มีสิทธิ์จัดการตั้งค่าห้อง) เท่านั้นที่ส่งประกาศได้', 'error');
  }

  if (!messageForm.title.trim()) {
    return Swal.fire('กรุณากรอกหัวข้อ', 'หัวข้อประกาศต้องไม่ว่างเปล่า', 'warning');
  }
  if (!messageForm.message.trim()) {
    return Swal.fire('กรุณากรอกข้อความ', 'ข้อความประกาศต้องไม่ว่างเปล่า', 'warning');
  }

  isSubmitting.value = true;
  try {
    await ActionService.sendCustomMessage(currentRoomId, {
      title: messageForm.title.trim(),
      message: messageForm.message.trim(),
      user_name: messageForm.user_name.trim() || currentUserName
    });
    await Swal.fire({
      icon: 'success',
      title: 'ส่งประกาศเรียบร้อยแล้ว!',
      html: `ข้อความ "${messageForm.title}" จะถูกประกาศใน Discord ทันที 🎉`,
      timer: 2000,
      showConfirmButton: false
    });
    messageForm.title = '';
    messageForm.message = '';
  } catch (error: unknown) {
    Swal.fire({
      icon: 'error',
      title: 'ส่งประกาศไม่สำเร็จ',
      text: error instanceof Error ? error.message : 'เกิดข้อผิดพลาดจากระบบ โปรดลองใหม่อีกครั้ง',
      confirmButtonColor: '#3b82f6'
    });
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 py-10 px-4 sm:px-6">
    <div class="max-w-2xl mx-auto">

      <div class="flex items-center gap-4 mb-8">
        <button
          @click="router.push('/dashboard')"
          class="w-10 h-10 bg-white rounded-full flex items-center justify-center text-slate-500 shadow-sm border border-slate-200 hover:text-slate-800 hover:shadow transition-all"
        >
          <i class="bi bi-arrow-left text-lg"></i>
        </button>
        <div>
          <h1 class="text-2xl font-extrabold text-slate-800">ประกาศเข้า Discord</h1>
          <p class="text-slate-500 text-sm mt-0.5">ส่งข้อความประกาศจากเว็บไปยังห้อง Discord ถึงเพื่อนทุกคน</p>
        </div>
      </div>

      <!-- ⚠️ เตือนห้องที่ยังไม่ได้ผูก Discord -->
      <div
        v-if="isLoadingRoom"
        class="bg-white shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-2xl border border-slate-100 p-5 mb-6 flex items-center gap-3"
      >
        <div class="w-5 h-5 border-2 border-slate-200 border-t-blue-600 rounded-full animate-spin"></div>
        <p class="text-sm font-semibold text-slate-500">กำลังตรวจสอบการเชื่อมต่อ Discord...</p>
      </div>

      <div
        v-else-if="!isDiscordLinked"
        class="bg-amber-50 border border-amber-200 rounded-2xl p-5 mb-6 flex items-start gap-4"
      >
        <div class="w-10 h-10 bg-amber-100 rounded-xl flex items-center justify-center text-amber-600 shrink-0">
          <i class="bi bi-discord text-xl"></i>
        </div>
        <div class="flex-1">
          <p class="font-bold text-amber-800 text-sm">ห้องนี้ยังไม่ได้เชื่อมต่อกับ Discord</p>
          <p class="text-amber-700/80 text-xs font-medium mt-1 leading-relaxed">
            ประกาศจะถูกส่งได้เฉพาะห้องที่มี Discord Server ผูกไว้แล้ว — กดเชื่อมต่อเพื่อให้บอทประกาศข้อความถึงเพื่อนทุกคนได้
          </p>
          <router-link
            to="/discord-connect"
            class="inline-flex items-center gap-2 mt-3 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white text-xs font-bold rounded-xl transition-all shadow-sm active:scale-95"
          >
            <i class="bi bi-plug-fill"></i> ไปหน้าเชื่อมต่อ Discord
          </router-link>
        </div>
      </div>

      <!-- ✅ แจ้งว่าห้องผูก Discord แล้ว -->
      <div
        v-else
        class="bg-emerald-50 border border-emerald-200 rounded-2xl p-5 mb-6 flex items-start gap-4"
      >
        <div class="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center text-emerald-600 shrink-0">
          <i class="bi bi-discord text-xl"></i>
        </div>
        <div>
          <p class="font-bold text-emerald-800 text-sm">ห้องเชื่อมต่อ Discord เรียบร้อยแล้ว</p>
          <p class="text-emerald-700/80 text-xs font-medium mt-1">ประกาศจะถูกส่งไปยังช่องประกาศของห้องทันที</p>
        </div>
      </div>

      <div class="bg-white shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-[2rem] overflow-hidden border border-slate-100">
        <form @submit.prevent="handleSend" class="p-8 md:p-10 space-y-6">

          <div class="flex items-center gap-4 pb-4 border-b border-slate-100">
            <div class="w-14 h-14 bg-gradient-to-br from-rose-50 to-red-50 text-rose-600 rounded-2xl flex items-center justify-center text-2xl shadow-inner border border-rose-100">
              <i class="bi bi-megaphone-fill"></i>
            </div>
            <div>
              <h2 class="font-black text-slate-800 text-lg">แบบฟอร์มประกาศ</h2>
              <p class="text-xs text-slate-400 font-semibold mt-0.5">บอทจะประกาศเป็น Embed ในช่องที่กำหนดไว้</p>
            </div>
          </div>

          <div class="space-y-2">
            <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-bookmark-fill text-rose-500"></i> หัวข้อประกาศ <span class="text-rose-500">*</span>
            </label>
            <input
              :disabled="!canSendMessage"
              v-model="messageForm.title"
              type="text"
              maxlength="200"
              class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all outline-none disabled:opacity-60"
              placeholder="เช่น ประกาศด่วน! พรุ่งนี้เลื่อนเรียน"
              required
            />
          </div>

          <div class="space-y-2">
            <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-card-text text-rose-500"></i> ข้อความประกาศ <span class="text-rose-500">*</span>
            </label>
            <textarea
              :disabled="!canSendMessage"
              v-model="messageForm.message"
              maxlength="2000"
              class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl h-40 focus:bg-white focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all outline-none resize-none disabled:opacity-60"
              placeholder="รายละเอียดประกาศ เช่น วันเวลา สถานที่ หรือสิ่งที่ต้องเตรียม..."
              required
            ></textarea>
            <div class="text-right text-xs font-semibold text-slate-400">
              {{ charCount }} / 2000
            </div>
          </div>

          <div class="space-y-2">
            <label class="text-sm font-bold text-slate-700 flex items-center gap-2">
              <i class="bi bi-person-fill text-rose-500"></i> ชื่อผู้ประกาศ
            </label>
            <input
              :disabled="!canSendMessage"
              v-model="messageForm.user_name"
              type="text"
              maxlength="100"
              class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500 transition-all outline-none disabled:opacity-60"
              placeholder="ชื่อที่จะแสดงใต้ประกาศใน Discord"
            />
          </div>

          <div class="pt-4">
            <template v-if="canSendMessage">
              <button
                type="submit"
                class="w-full bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-600 hover:to-red-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-rose-600/20 transition-all flex items-center justify-center gap-2"
                :disabled="isSubmitting"
              >
                <span v-if="isSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                <template v-else><i class="bi bi-send-fill"></i> ส่งประกาศไป Discord</template>
              </button>
            </template>
            <div v-else class="w-full text-center py-3.5 bg-slate-100 text-slate-500 rounded-xl font-medium border border-slate-200 flex items-center justify-center gap-2">
              <i class="bi bi-lock-fill"></i> เฉพาะผู้ดูแล / ผู้มีสิทธิ์จัดการตั้งค่าห้อง
            </div>
          </div>

        </form>
      </div>
    </div>
  </div>
</template>
