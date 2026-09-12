<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { ActionService } from '@/services/action';
import { ClassroomService } from '@/services/classroom';
import Swal from 'sweetalert2';
import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

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

// แยก "ตรวจสอบไม่สำเร็จ" ออกจาก "ยืนยันแล้วว่าไม่ได้ผูก" — เดิม catch เงียบทำให้ขึ้นการ์ด
// "ยังไม่ได้เชื่อมต่อ" ทั้งที่ระบบไม่เคยรู้จริง ๆ
const hasError = ref(false);

const fetchRoomStatus = async () => {
  isLoadingRoom.value = true;
  hasError.value = false;
  try {
    const roomData = await ClassroomService.getRoomData(currentRoomId);
    isDiscordLinked.value = !!roomData?.server_id;
  } catch {
    hasError.value = true;
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
      confirmButtonColor: '#1d4ed8'
    });
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Discord Announcement"
      title="ประกาศเข้า Discord"
      description="ส่งข้อความประกาศจากเว็บไปยังห้อง Discord ถึงเพื่อนทุกคน"
    >
      <template #actions>
        <button
          type="button"
          class="btn-ghost-ui"
          title="กลับหน้าหลัก"
          @click="router.push('/dashboard')"
        >
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าหลัก
        </button>
      </template>
    </PageHeader>

    <!-- ⚠️ สถานะการผูก Discord ของห้อง -->
    <SkeletonRows v-if="isLoadingRoom" :rows="1" height="h-20" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="ตรวจสอบสถานะ Discord ไม่สำเร็จ"
      hint="ไม่สามารถดึงข้อมูลห้องได้ในขณะนี้"
      @retry="fetchRoomStatus"
    />

    <div
      v-else-if="!isDiscordLinked"
      class="page-card flex items-start gap-3 border-amber-200 bg-amber-50 p-4 sm:gap-4 sm:p-5"
    >
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700"
      >
        <i class="bi bi-discord text-lg" aria-hidden="true"></i>
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-bold text-amber-800">ห้องนี้ยังไม่ได้เชื่อมต่อกับ Discord</p>
        <p class="mt-1 text-xs leading-relaxed text-amber-700">
          ประกาศจะถูกส่งได้เฉพาะห้องที่มี Discord Server ผูกไว้แล้ว — กดเชื่อมต่อเพื่อให้บอทประกาศข้อความถึงเพื่อนทุกคนได้
        </p>
        <RouterLink to="/discord-connect" class="btn-ghost-ui mt-3">
          <i class="bi bi-plug-fill" aria-hidden="true"></i>
          ไปหน้าเชื่อมต่อ Discord
        </RouterLink>
      </div>
    </div>

    <div
      v-else
      class="page-card flex items-start gap-3 border-emerald-200 bg-emerald-50 p-4 sm:gap-4 sm:p-5"
    >
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700"
      >
        <i class="bi bi-discord text-lg" aria-hidden="true"></i>
      </div>
      <div class="min-w-0">
        <p class="text-sm font-bold text-emerald-800">ห้องเชื่อมต่อ Discord เรียบร้อยแล้ว</p>
        <p class="mt-1 text-xs leading-relaxed text-emerald-700">
          ประกาศจะถูกส่งไปยังช่องประกาศของห้องทันที
        </p>
      </div>
    </div>

    <div class="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-3">
      <!-- ฟอร์ม -->
      <div class="page-card p-4 sm:p-6 lg:col-span-2">
        <form class="space-y-4" @submit.prevent="handleSend">
          <div class="flex items-center gap-3 border-b border-stone-100 pb-3 sm:pb-4">
            <div
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
            >
              <i class="bi bi-megaphone-fill text-base" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <p class="section-title truncate">แบบฟอร์มประกาศ</p>
              <p class="truncate text-xs text-stone-400">
                บอทจะประกาศเป็น Embed ในช่องที่กำหนดไว้
              </p>
            </div>
          </div>

          <div>
            <label class="field-label" for="announceTitle">หัวข้อประกาศ *</label>
            <input
              id="announceTitle"
              :disabled="!canSendMessage"
              v-model="messageForm.title"
              type="text"
              maxlength="200"
              class="field"
              placeholder="เช่น ประกาศด่วน! พรุ่งนี้เลื่อนเรียน"
              required
            />
          </div>

          <div>
            <label class="field-label" for="announceMessage">ข้อความประกาศ *</label>
            <textarea
              id="announceMessage"
              :disabled="!canSendMessage"
              v-model="messageForm.message"
              maxlength="2000"
              class="field h-32 resize-none sm:h-40"
              placeholder="รายละเอียดประกาศ เช่น วันเวลา สถานที่ หรือสิ่งที่ต้องเตรียม..."
              required
            ></textarea>
            <div class="num mt-1 text-right text-xs font-bold text-stone-400">
              {{ charCount }} / 2000
            </div>
          </div>

          <div>
            <label class="field-label" for="announceAuthor">ชื่อผู้ประกาศ</label>
            <input
              id="announceAuthor"
              :disabled="!canSendMessage"
              v-model="messageForm.user_name"
              type="text"
              maxlength="100"
              class="field"
              placeholder="ชื่อที่จะแสดงใต้ประกาศใน Discord"
            />
          </div>

          <div class="border-t border-stone-100 pt-3 sm:pt-4">
            <template v-if="canSendMessage">
              <button type="submit" class="btn-primary w-full" :disabled="isSubmitting">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-white/30 border-t-white"
                  aria-hidden="true"
                ></span>
                <i v-else class="bi bi-send-fill" aria-hidden="true"></i>
                {{ isSubmitting ? 'กำลังส่งประกาศ...' : 'ส่งประกาศไป Discord' }}
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-4 py-2.5 text-center text-sm font-bold text-stone-500"
            >
              <i class="bi bi-lock-fill" aria-hidden="true"></i>
              เฉพาะผู้ดูแล / ผู้มีสิทธิ์จัดการตั้งค่าห้อง
            </div>
          </div>
        </form>
      </div>

      <!-- ตัวอย่างที่จะปรากฏใน Discord -->
      <div class="page-card order-first h-fit p-4 sm:p-5 lg:order-none">
        <p class="mb-2 text-[11px] font-bold text-stone-400">ตัวอย่างประกาศ</p>
        <div class="rounded-xl border-s-4 border-s-brand-700 bg-stone-50 p-3.5">
          <p class="min-w-0 break-words font-display text-sm font-bold text-stone-900">
            {{ messageForm.title || 'หัวข้อประกาศ' }}
          </p>
          <p
            class="mt-1 whitespace-pre-line break-words text-sm leading-relaxed text-stone-600"
          >
            {{ messageForm.message || 'รายละเอียดประกาศจะแสดงที่นี่' }}
          </p>
          <p class="mt-3 truncate border-t border-stone-200 pt-2.5 text-xs font-bold text-stone-400">
            ประกาศโดย {{ messageForm.user_name || currentUserName }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
