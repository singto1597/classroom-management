<script setup lang="ts">
/**
 * 🔖 ปุ่ม "บันทึกไว้" — ใช้ในหน้ารายละเอียดประกาศ/กิจกรรม
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. สถานะมาจาก backend (`/bookmarks/state`) — ไม่เดาจากลิสต์ในหน่วยความจำ
 *     เพราะผู้ใช้อาจกดบันทึกจากอีกแท็บ/อีกเครื่องได้
 *  2. `add` ซ้ำปลอดภัย (backend ตอบ `created: false`) ⇒ ไม่ต้องเช็คก่อนกด
 *  3. ยกเลิกแล้วมีปุ่ม "บันทึกกลับ" ในกล่องสำเร็จ — เลิกทำได้โดยไม่ต้องย้อนกลับ
 *     ไปหาปุ่มเดิม (ระหว่างนั้นผู้ใช้อาจเลื่อนหน้าไปแล้ว)
 *  4. โหลดสถานะไม่สำเร็จ = ปุ่มยังใช้งานได้ (เริ่มจาก "ยังไม่บันทึก") ไม่ทำให้หน้าล้ม
 */
import { onMounted, ref } from 'vue';
import IconButton from '@/components/ui/IconButton.vue';
import { BookmarkService } from '@/services/bookmark';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import type { BookmarkEntityType } from '@/types/bookmark';

const props = defineProps<{
  entityType: BookmarkEntityType;
  entityId: number;
}>();

const authStore = useAuthStore();
const dialog = useDialog();
const roomId = authStore.currentRoomId ?? 0;

const bookmarked = ref(false);
const bookmarkId = ref<number | null>(null);
const isBusy = ref(false);

const messageOf = (err: unknown): string =>
  err instanceof Error && err.message ? err.message : 'ทำรายการไม่สำเร็จ';

onMounted(async () => {
  if (!roomId || props.entityId <= 0) return;
  try {
    const state = await BookmarkService.state(roomId, props.entityType, props.entityId);
    bookmarked.value = state.bookmarked;
    bookmarkId.value = state.bookmark_id;
  } catch {
    // เงียบโดยเจตนา — ปุ่มยังใช้ได้ และแจ้ง error ตอนกดถ้าปลายทางล่มจริง
  }
});

const toggle = async () => {
  if (isBusy.value || !roomId) return;
  isBusy.value = true;
  try {
    if (bookmarked.value && bookmarkId.value !== null) {
      await BookmarkService.remove(roomId, bookmarkId.value);
      bookmarked.value = false;
      bookmarkId.value = null;

      const undo = await dialog.confirm(
        'ยกเลิกการบันทึกแล้ว',
        'รายการนี้จะหายจากหน้า "ของฉัน"',
        { icon: 'success', confirmButtonText: 'บันทึกกลับ', cancelButtonText: 'ปิด' },
      );
      if (undo.isConfirmed) {
        const created = await BookmarkService.add(roomId, props.entityType, props.entityId);
        bookmarked.value = true;
        bookmarkId.value = created.id;
      }
    } else {
      const created = await BookmarkService.add(roomId, props.entityType, props.entityId);
      bookmarked.value = true;
      bookmarkId.value = created.id;
      await dialog.fire({
        icon: 'success',
        title: 'บันทึกไว้แล้ว',
        text: 'ดูรายการทั้งหมดได้ที่เมนู "ของฉัน"',
        timer: 1600,
      });
    }
  } catch (err) {
    await dialog.fire({
      icon: 'error',
      title: 'ทำรายการไม่สำเร็จ',
      text: messageOf(err),
    });
  } finally {
    isBusy.value = false;
  }
};
</script>

<template>
  <IconButton
    :label="bookmarked ? 'เลิกบันทึกไว้' : 'บันทึกไว้'"
    :icon="bookmarked ? 'bi-bookmark-fill' : 'bi-bookmark'"
    :tone="bookmarked ? 'brand' : 'neutral'"
    @click="toggle"
  />
</template>
