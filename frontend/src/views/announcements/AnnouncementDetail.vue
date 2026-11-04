<script setup lang="ts">
/**
 * 📄 รายละเอียดประกาศ — ปลายทางของ deep link `/announcements/:id`
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **เปิดหน้า = อ่านแล้ว** ถ้าประกาศยังไม่อ่าน — เรียก `announcements/{id}/read`
 *     แล้วดึงจำนวนยังไม่อ่านของกระดิ่งใหม่ (ตัวเลขต้องขยับทันที ไม่รอสตรีม)
 *  2. การกระทำของผู้ดูแล (ปักหมุด/เก็บถาวร) อยู่บนสุดและมีข้อความยืนยัน เฉพาะการเก็บถาวร
 *     (ปักหมุดเป็นเรื่องเบาและกดซ้ำได้ — ยืนยันทุกครั้งจะน่ารำคาญ)
 *  3. ไม่มีสิทธิ์ดู = backend ตอบ 404/403 ⇒ แสดง error พร้อมทางกลับรายการ
 *     ไม่ใช่จอว่างที่ผู้ใช้ไม่รู้ว่าเกิดอะไร
 *
 * ⚠️ `body` เป็นข้อความล้วน (ไม่ใช่ HTML) ⇒ ใช้ `whitespace-pre-line`
 *    ห้าม `v-html` เด็ดขาด — ประกาศเขียนโดยสมาชิกของห้อง
 */
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Swal from 'sweetalert2';
import PageIntro from '@/components/ui/PageIntro.vue';
import AppButton from '@/components/ui/AppButton.vue';
import BookmarkButton from '@/components/me/BookmarkButton.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import { AnnouncementService } from '@/services/announcement';
import { useAuthStore } from '@/stores/auth';
import { useNotificationStore } from '@/stores/notifications';
import { formatThaiDateTime } from '@/utils/datetime';
import { PRIORITY_BADGE_CLASSES, PRIORITY_LABELS } from '@/constants/notificationGroups';
import { UI_COLOR } from '@/constants/theme';
import type { AnnouncementItem } from '@/types/announcement';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const notificationStore = useNotificationStore();
const roomId = authStore.currentRoomId ?? 0;

const announcementId = Number(route.params.id);
const announcement = ref<AnnouncementItem | null>(null);
const isLoading = ref(true);
const error = ref<string | null>(null);
const isBusy = ref(false);

const canManage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_SETTINGS'),
);

const messageOf = (err: unknown): string =>
  err instanceof Error && err.message ? err.message : 'โหลดประกาศไม่สำเร็จ';

const load = async () => {
  isLoading.value = true;
  error.value = null;
  try {
    const item = await AnnouncementService.get(roomId, announcementId);
    announcement.value = item;

    if (item.is_unread) {
      // การอ่านล้มเหลวไม่ควรทำให้หน้า detail ล้มทั้งหน้า
      try {
        await AnnouncementService.markRead(roomId, announcementId);
        announcement.value = { ...item, is_unread: false };
        void notificationStore.load({ silent: true });
      } catch {
        // ยังอ่านเนื้อหาได้ — ตัวเลขกระดิ่งจะถูกแก้ตอนสตรีม/รีเฟรชรอบถัดไป
      }
    }
  } catch (err) {
    error.value = messageOf(err);
  } finally {
    isLoading.value = false;
  }
};

onMounted(() => {
  if (!Number.isFinite(announcementId) || announcementId <= 0) {
    isLoading.value = false;
    error.value = 'ลิงก์ประกาศไม่ถูกต้อง';
    return;
  }
  void load();
});

const togglePin = async () => {
  const item = announcement.value;
  if (!item || isBusy.value) return;
  isBusy.value = true;
  try {
    announcement.value = await AnnouncementService.update(roomId, item.id, {
      pinned: !item.pinned,
    });
    await Swal.fire({
      icon: 'success',
      title: announcement.value.pinned ? 'ปักหมุดแล้ว' : 'เลิกปักหมุดแล้ว',
      timer: 1600,
      showConfirmButton: false,
    });
  } catch (err) {
    await Swal.fire({
      icon: 'error',
      title: 'ทำรายการไม่สำเร็จ',
      text: messageOf(err),
      confirmButtonColor: UI_COLOR.brand,
    });
  } finally {
    isBusy.value = false;
  }
};

const toggleArchive = async () => {
  const item = announcement.value;
  if (!item || isBusy.value) return;

  const archiving = !item.archived_at;
  const confirm = await Swal.fire({
    icon: 'question',
    title: archiving ? 'เก็บประกาศนี้เข้าคลัง?' : 'นำประกาศกลับมาแสดง?',
    text: archiving
      ? 'ประกาศจะหายจากรายการปกติ แต่เปิดดูย้อนหลังได้เสมอ — ไม่ใช่การลบ'
      : 'ประกาศจะกลับไปอยู่ในรายการปกติของทุกคน',
    showCancelButton: true,
    confirmButtonText: archiving ? 'เก็บเข้าคลัง' : 'นำกลับมา',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: UI_COLOR.brand,
  });
  if (!confirm.isConfirmed) return;

  isBusy.value = true;
  try {
    announcement.value = await AnnouncementService.setArchived(roomId, item.id, archiving);
    await Swal.fire({
      icon: 'success',
      title: archiving ? 'เก็บเข้าคลังแล้ว' : 'นำกลับมาแสดงแล้ว',
      timer: 1600,
      showConfirmButton: false,
    });
  } catch (err) {
    await Swal.fire({
      icon: 'error',
      title: 'ทำรายการไม่สำเร็จ',
      text: messageOf(err),
      confirmButtonColor: UI_COLOR.brand,
    });
  } finally {
    isBusy.value = false;
  }
};

const goToList = () => {
  void router.push('/announcements');
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-20" />

    <StateBlock
      v-else-if="error"
      variant="error"
      title="เปิดประกาศไม่ได้"
      :hint="error"
      retry-text="ลองอีกครั้ง"
      @retry="load"
    >
      <AppButton variant="secondary" @click="goToList">
        <i class="bi bi-arrow-left" aria-hidden="true"></i>
        กลับรายการประกาศ
      </AppButton>
    </StateBlock>

    <template v-else-if="announcement">
      <PageIntro
        :description="`ประกาศเมื่อ ${formatThaiDateTime(announcement.created_at)}`"
      >
        <template #actions>
          <!-- 🔖 P3.4 — บันทึกไว้ (หนึ่งปุ่มต่อหนึ่งรายการ, ไม่ใช่การกระทำของผู้ดูแล) -->
          <BookmarkButton entity-type="announcement" :entity-id="announcementId" />
          <AppButton variant="secondary" @click="goToList">
            <i class="bi bi-arrow-left" aria-hidden="true"></i>
            รายการประกาศ
          </AppButton>
        </template>
      </PageIntro>

      <article class="page-card p-4 sm:p-6">
        <div class="flex flex-wrap items-center gap-1.5 border-b border-stone-100 pb-3 sm:pb-4">
          <span
            v-if="announcement.pinned"
            class="inline-flex items-center gap-1 rounded-full bg-warn-100 px-2 py-0.5 text-[11px] font-bold text-warn-800"
          >
            <i class="bi bi-pin-angle-fill" aria-hidden="true"></i>
            ปักหมุด
          </span>
          <span
            v-if="announcement.priority !== 'normal'"
            class="rounded-full px-2 py-0.5 text-[11px] font-bold"
            :class="PRIORITY_BADGE_CLASSES[announcement.priority]"
          >
            {{ PRIORITY_LABELS[announcement.priority] }}
          </span>
          <span
            v-if="announcement.archived_at"
            class="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-bold text-stone-600"
          >
            เก็บถาวรแล้ว
          </span>
        </div>

        <p
          v-if="announcement.body"
          class="mt-3 whitespace-pre-line break-words text-sm leading-relaxed text-stone-700 sm:mt-4"
        >
          {{ announcement.body }}
        </p>
        <p v-else class="mt-3 text-sm italic text-stone-500 sm:mt-4">
          ประกาศนี้มีแค่หัวข้อ ไม่มีรายละเอียดเพิ่มเติม
        </p>

        <p class="mt-4 border-t border-stone-100 pt-3 text-[11px] font-bold text-stone-400">
          แก้ไขล่าสุด {{ formatThaiDateTime(announcement.updated_at) }}
        </p>
      </article>

      <!-- การกระทำของผู้ดูแล -->
      <section v-if="canManage" class="page-card p-4 sm:p-6">
        <h2 class="section-title">จัดการประกาศ</h2>
        <p class="mt-1 text-xs leading-relaxed text-stone-500">
          การแก้ไขเหล่านี้ไม่สร้างแจ้งเตือนใหม่ให้สมาชิก
        </p>

        <div class="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <AppButton variant="secondary" :loading="isBusy" @click="togglePin">
            <i
              :class="['bi', announcement.pinned ? 'bi-pin-angle' : 'bi-pin-angle-fill']"
              aria-hidden="true"
            ></i>
            {{ announcement.pinned ? 'เลิกปักหมุด' : 'ปักหมุดไว้บนสุด' }}
          </AppButton>

          <AppButton variant="secondary" :loading="isBusy" @click="toggleArchive">
            <i
              :class="['bi', announcement.archived_at ? 'bi-arrow-counterclockwise' : 'bi-archive']"
              aria-hidden="true"
            ></i>
            {{ announcement.archived_at ? 'นำกลับมาแสดง' : 'เก็บเข้าคลัง' }}
          </AppButton>
        </div>
      </section>
    </template>
  </div>
</template>
