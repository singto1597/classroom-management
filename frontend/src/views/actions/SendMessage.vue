<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { AnnouncementService } from '@/services/announcement';
import { ClassroomService } from '@/services/classroom';
import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import { useDialog } from '@/composables/useDialog';
import type { AnnouncementPriority } from '@/types/announcement';

const router = useRouter();
const dialog = useDialog();
const authStore = useAuthStore();

const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

// สิทธิ์: แอดมิน หรือผู้ที่มีสิทธิ์จัดการการตั้งค่าห้อง (ประกาศคือช่องทางราชการของห้อง)
const canSendMessage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_SETTINGS')
);

// ✨ สถานะการผูก Discord ของห้อง — ไม่ผูกก็ประกาศได้ (in-app + push) แค่ไม่ขึ้นใน Discord
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
  priority: 'normal' as AnnouncementPriority,
  pinned: false,
});

const isSubmitting = ref(false);
const charCount = computed(() => messageForm.message.length);

const priorityLabel: Record<AnnouncementPriority, string> = {
  normal: 'ปกติ',
  high: 'สำคัญ',
  urgent: 'ด่วน',
};

const handleSend = async () => {
  if (!canSendMessage.value) {
    void dialog.alert('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแล (หรือผู้ที่มีสิทธิ์จัดการตั้งค่าห้อง) เท่านั้นที่ส่งประกาศได้', 'error');
    return;
  }

  if (!messageForm.title.trim()) {
    void dialog.alert('กรุณากรอกหัวข้อ', 'หัวข้อประกาศต้องไม่ว่างเปล่า', 'warning');
    return;
  }
  if (!messageForm.message.trim()) {
    void dialog.alert('กรุณากรอกข้อความ', 'ข้อความประกาศต้องไม่ว่างเปล่า', 'warning');
    return;
  }

  isSubmitting.value = true;
  try {
    const result = await AnnouncementService.create(currentRoomId, {
      title: messageForm.title.trim(),
      body: messageForm.message.trim(),
      priority: messageForm.priority,
      pinned: messageForm.pinned,
    });
    const extra = isDiscordLinked.value ? ' และใน Discord' : '';
    await dialog.fire({
      icon: 'success',
      title: 'ประกาศเรียบร้อยแล้ว!',
      text: `“${result.item.title}” ถูกส่งถึงสมาชิก ${result.delivered_count} คน${extra} 🎉`,
      timer: 2500,
    });
    messageForm.title = '';
    messageForm.message = '';
    messageForm.priority = 'normal';
    messageForm.pinned = false;
  } catch (error: unknown) {
    void dialog.alert(
      'ส่งประกาศไม่สำเร็จ',
      error instanceof Error ? error.message : 'เกิดข้อผิดพลาดจากระบบ โปรดลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="ส่งประกาศถึงเพื่อนทุกคน — ขึ้นในแอป แจ้งเตือนบนมือถือ และ Discord (ถ้าเชื่อมต่อไว้)"
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
    </PageIntro>

    <!-- ⚠️ สถานะการผูก Discord ของห้อง -->
    <SkeletonRows v-if="isLoadingRoom" :rows="1" height="h-20" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="ตรวจสอบสถานะ Discord ไม่สำเร็จ"
      hint="ไม่สามารถดึงข้อมูลห้องได้ในขณะนี้ — ประกาศยังส่งได้ แต่จะไม่ขึ้นใน Discord"
      @retry="fetchRoomStatus"
    />

    <div
      v-else-if="!isDiscordLinked"
      class="page-card flex items-start gap-3 border-warn-200 bg-warn-50 p-4 sm:gap-4 sm:p-5"
    >
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-warn-100 text-warn-700"
      >
        <i class="bi bi-discord text-lg" aria-hidden="true"></i>
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-bold text-warn-800">ห้องนี้ยังไม่ได้เชื่อมต่อกับ Discord</p>
        <p class="mt-1 text-xs leading-relaxed text-warn-700">
          ประกาศจะขึ้นในแอปและแจ้งเตือนบนมือถือของสมาชิกตามปกติ แต่จะไม่ปรากฏใน Discord
        </p>
        <RouterLink to="/discord-connect" class="btn-ghost-ui mt-3">
          <i class="bi bi-plug-fill" aria-hidden="true"></i>
          ไปหน้าเชื่อมต่อ Discord
        </RouterLink>
      </div>
    </div>

    <div
      v-else
      class="page-card flex items-start gap-3 border-ok-200 bg-ok-50 p-4 sm:gap-4 sm:p-5"
    >
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-ok-100 text-ok-700"
      >
        <i class="bi bi-discord text-lg" aria-hidden="true"></i>
      </div>
      <div class="min-w-0">
        <p class="text-sm font-bold text-ok-800">ห้องเชื่อมต่อ Discord เรียบร้อยแล้ว</p>
        <p class="mt-1 text-xs leading-relaxed text-ok-700">
          ประกาศจะขึ้นในแอป แจ้งเตือนบนมือถือ และส่งเข้า Discord — ประกาศ "ด่วน" เท่านั้นที่ @ทุกคน
        </p>
      </div>
    </div>

    <div class="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-3">
      <!-- ฟอร์ม -->
      <div class="page-card p-4 sm:p-6 lg:col-span-2">
        <form class="space-y-4" @submit.prevent="handleSend">
          <div class="flex items-center gap-3 border-b border-line pb-3 sm:pb-4">
            <div
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-brand-50 text-brand-700"
            >
              <i class="bi bi-megaphone-fill text-base" aria-hidden="true"></i>
            </div>
            <div class="min-w-0">
              <p class="section-title truncate">แบบฟอร์มประกาศ</p>
              <p class="truncate text-xs text-ink-3">
                ประกาศโดย {{ currentUserName }}
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
              maxlength="5000"
              class="field h-32 resize-none sm:h-40"
              placeholder="รายละเอียดประกาศ เช่น วันเวลา สถานที่ หรือสิ่งที่ต้องเตรียม..."
              required
            ></textarea>
            <div class="num mt-1 text-right text-xs font-bold text-ink-3">
              {{ charCount }} / 5000
            </div>
          </div>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="field-label" for="announcePriority">ความสำคัญ</label>
              <select
                id="announcePriority"
                v-model="messageForm.priority"
                :disabled="!canSendMessage"
                class="field"
              >
                <option value="normal">ปกติ</option>
                <option value="high">สำคัญ</option>
                <option value="urgent">ด่วน (ทะลุเวลางดรบกวน)</option>
              </select>
              <p class="mt-1 text-xs leading-relaxed text-ink-3">
                ประกาศ "ด่วน" จะแจ้งเตือนแม้อยู่นอกเวลา และ @ทุกคนใน Discord
              </p>
            </div>

            <div>
              <span class="field-label">ปักหมุด</span>
              <label class="flex min-h-11 items-center gap-2.5 rounded-control border border-line px-3">
                <input
                  v-model="messageForm.pinned"
                  type="checkbox"
                  :disabled="!canSendMessage"
                  class="h-4 w-4 accent-brand"
                />
                <span class="text-sm font-bold text-ink-2">ปักหมุดไว้บนสุดของหน้าประกาศ</span>
              </label>
            </div>
          </div>

          <div class="border-t border-line pt-3 sm:pt-4">
            <template v-if="canSendMessage">
              <button type="submit" class="btn-primary w-full" :disabled="isSubmitting">
                <span
                  v-if="isSubmitting"
                  class="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-white/30 border-t-white"
                  aria-hidden="true"
                ></span>
                <i v-else class="bi bi-send-fill" aria-hidden="true"></i>
                {{ isSubmitting ? 'กำลังส่งประกาศ...' : 'ส่งประกาศ' }}
              </button>
            </template>
            <div
              v-else
              class="flex w-full items-center justify-center gap-2 rounded-control border border-line bg-canvas px-4 py-2.5 text-center text-sm font-bold text-ink-3"
            >
              <i class="bi bi-lock-fill" aria-hidden="true"></i>
              เฉพาะผู้ดูแล / ผู้มีสิทธิ์จัดการตั้งค่าห้อง
            </div>
          </div>
        </form>
      </div>

      <!-- ตัวอย่างประกาศ -->
      <div class="page-card order-first h-fit p-4 sm:p-5 lg:order-none">
        <p class="mb-2 text-xs font-bold text-ink-3">ตัวอย่างประกาศ</p>
        <div class="rounded-control border-s-4 border-s-brand-700 bg-canvas p-3.5">
          <p class="mb-1.5 flex items-center gap-1.5">
            <span
              v-if="messageForm.pinned"
              class="inline-flex items-center gap-1 rounded-full bg-warn-100 px-2 py-0.5 text-xs font-bold text-warn-800"
            >
              <i class="bi bi-pin-angle-fill" aria-hidden="true"></i>
              ปักหมุด
            </span>
            <span
              v-if="messageForm.priority !== 'normal'"
              class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold"
              :class="messageForm.priority === 'urgent' ? 'bg-danger-100 text-danger-800' : 'bg-info-100 text-info-800'"
            >
              {{ priorityLabel[messageForm.priority] }}
            </span>
          </p>
          <p class="min-w-0 break-words text-sm font-bold text-ink">
            {{ messageForm.title || 'หัวข้อประกาศ' }}
          </p>
          <p
            class="mt-1 whitespace-pre-line break-words text-sm leading-relaxed text-ink-2"
          >
            {{ messageForm.message || 'รายละเอียดประกาศจะแสดงที่นี่' }}
          </p>
          <p class="mt-3 truncate border-t border-line pt-2.5 text-xs font-bold text-ink-3">
            ประกาศโดย {{ currentUserName }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
