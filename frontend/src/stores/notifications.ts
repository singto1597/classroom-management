/**
 * 🔔 สถานะแจ้งเตือนของ **ห้องที่กำลังเปิด** — แหล่งเดียวของกระดิ่งและหน้ารายการ
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้ใน store นี้
 * ═══════════════════════════════════════════════════════════════════════════
 *   1. **ตัวเลขบนกระดิ่งมาจาก backend** (`unread_count` ของ response) ไม่นับเอง
 *      — ถ้านับเองหลัง `markRead` ตัวเลขจะเพี้ยนทันทีที่มีแถวหลุดจากการแบ่งหน้า
 *   2. **สลับห้อง = ล้างของเดิมทันที** ก่อนโหลดชุดใหม่ (ไม่ใช่โชว์ของห้องเก่า
 *      ค้างไว้ระหว่างรอネットワーク — ผู้ใช้อาจอ่านผิดห้อง)
 *   3. **สตรีมเป็นแค่สัญญาณ** ⇒ ได้สัญญาณแล้วเรียก `load()` ใหม่ ไม่ patch จาก payload
 *      (payload มีแค่ id — และการ patch จาก id เดียวทำให้ลำดับ/ตัวนับไม่ตรง)
 *   4. คำขอที่แข่งกัน (สลับห้องเร็ว ๆ) ใช้ `seq` ทิ้งผลของรอบเก่า
 *
 * ⚠️ ไม่มี `any` · error เก็บเป็นข้อความไทยพร้อมแสดงผล
 */

import { computed, ref, watch } from 'vue';
import { defineStore } from 'pinia';
import { useAuthStore } from '@/stores/auth';
import { NotificationService } from '@/services/notification';
import {
  openNotificationStream,
  type NotificationStreamHandle,
  type StreamStatus,
} from '@/services/notificationStream';
import type { NotificationItem } from '@/types/notification';

/** จำนวนต่อหน้า — ตรงกับ DEFAULT_PAGE_SIZE ฝั่ง backend (20) */
const PAGE_SIZE = 20;

const errorMessage = (error: unknown): string =>
  error instanceof Error && error.message
    ? error.message
    : 'โหลดการแจ้งเตือนไม่สำเร็จ';

/**
 * Badge API ยังไม่อยู่ใน lib.dom ของ TypeScript รุ่นที่ติดตั้ง
 * ⇒ ประกาศเฉพาะส่วนที่ใช้ (ไม่ใช้ `any`)
 */
type BadgeNavigator = Navigator & {
  setAppBadge?: (count?: number) => Promise<void>;
  clearAppBadge?: () => Promise<void>;
};

export const useNotificationStore = defineStore('notifications', () => {
  const authStore = useAuthStore();

  const items = ref<NotificationItem[]>([]);
  const unreadCount = ref(0);
  const hasMore = ref(false);
  const isLoading = ref(false);
  const isRefreshing = ref(false);
  /** โหลดรอบแรกเสร็จหรือยัง — ใช้แยก "ยังไม่มีของ" กับ "ยังไม่เคยถาม" */
  const hasLoaded = ref(false);
  const error = ref<string | null>(null);
  const streamStatus = ref<StreamStatus>('idle');

  const roomId = computed<number | null>(() => authStore.currentRoomId);

  /** นับคำขอ — ผลของคำขอเก่าที่กลับมาช้าหลังสลับห้องต้องถูกทิ้ง */
  let seq = 0;
  let stream: NotificationStreamHandle | null = null;

  const syncBadge = () => {
    const badgeNavigator = navigator as BadgeNavigator;
    const count = unreadCount.value;
    try {
      if (count > 0) void badgeNavigator.setAppBadge?.(count);
      else void badgeNavigator.clearAppBadge?.();
    } catch {
      // Badge API ไม่รองรับ/ถูกบล็อก — ไม่ใช่เหตุให้แจ้งเตือนในแอปล้ม
    }
  };

  const reset = () => {
    items.value = [];
    unreadCount.value = 0;
    hasMore.value = false;
    hasLoaded.value = false;
    error.value = null;
    syncBadge();
  };

  /** โหลดหน้าแรก (หรือรีเฟรช) ของห้องปัจจุบัน */
  const load = async (options: { silent?: boolean } = {}): Promise<void> => {
    const currentRoom = roomId.value;
    if (!currentRoom) {
      reset();
      return;
    }

    const mySeq = ++seq;
    if (options.silent) isRefreshing.value = true;
    else isLoading.value = true;
    error.value = null;

    try {
      const response = await NotificationService.list(currentRoom, { limit: PAGE_SIZE });
      if (mySeq !== seq) return; // สลับห้อง/โหลดซ้อนระหว่างรอคำตอบ
      items.value = response.items;
      unreadCount.value = response.unread_count;
      hasMore.value = response.has_more;
      hasLoaded.value = true;
      syncBadge();
    } catch (err) {
      if (mySeq !== seq) return;
      error.value = errorMessage(err);
    } finally {
      if (mySeq === seq) {
        isLoading.value = false;
        isRefreshing.value = false;
      }
    }
  };

  /** โหลดหน้าเก่าต่อจากท้ายรายการ (cursor = id ของแถวสุดท้าย) */
  const loadMore = async (): Promise<void> => {
    const currentRoom = roomId.value;
    const last = items.value.at(-1);
    if (!currentRoom || !hasMore.value || isLoading.value || !last) return;

    const mySeq = seq; // ต้องเท่าเดิม — ถ้าสลับห้องระหว่างนี้จะถูกทิ้ง
    isLoading.value = true;
    try {
      const response = await NotificationService.list(currentRoom, {
        limit: PAGE_SIZE,
        before_id: last.id,
      });
      if (mySeq !== seq) return;
      // กันแถวซ้ำเมื่อมีของใหม่แทรกเข้ามาระหว่างหน้า
      const seen = new Set(items.value.map((item) => item.id));
      items.value = [...items.value, ...response.items.filter((item) => !seen.has(item.id))];
      hasMore.value = response.has_more;
      unreadCount.value = response.unread_count;
      syncBadge();
    } catch (err) {
      if (mySeq === seq) error.value = errorMessage(err);
    } finally {
      if (mySeq === seq) isLoading.value = false;
    }
  };

  /**
   * ทำเครื่องหมายว่าอ่านแล้ว
   *
   * อัปเดต UI ก่อน (ให้รู้สึกตอบสนองทันที) แล้วค่อยลดตัวนับ
   * — ถ้า API ล้ม ให้ดึงรายการใหม่เพื่อคืนค่าความจริง (ไม่ปล่อยให้จอโกหก)
   */
  const markRead = async (notificationId: number): Promise<void> => {
    const currentRoom = roomId.value;
    if (!currentRoom) return;

    const item = items.value.find((row) => row.id === notificationId);
    if (item && !item.read_at) {
      item.read_at = new Date().toISOString();
      unreadCount.value = Math.max(0, unreadCount.value - 1);
      syncBadge();
    }

    try {
      await NotificationService.markRead(currentRoom, notificationId);
    } catch (err) {
      error.value = errorMessage(err);
      await load({ silent: true });
    }
  };

  /** อ่านทั้งหมดของห้องนี้ */
  const markAllRead = async (): Promise<void> => {
    const currentRoom = roomId.value;
    if (!currentRoom) return;
    try {
      const response = await NotificationService.markAllRead(currentRoom);
      const now = new Date().toISOString();
      items.value = items.value.map((row) => (row.read_at ? row : { ...row, read_at: now }));
      unreadCount.value = 0;
      syncBadge();
      if (response.marked_count === 0) {
        // ไม่มีอะไรเปลี่ยน — ตัวเลขที่เห็นอาจมาจากหน้าอื่นที่เพิ่งอ่านไป
        await load({ silent: true });
      }
    } catch (err) {
      error.value = errorMessage(err);
    }
  };

  /** เปิดสตรีมสดของห้องปัจจุบัน (เรียกครั้งเดียวจากเปลือกแอป) */
  const startStream = (): void => {
    const currentRoom = roomId.value;
    if (!currentRoom || stream) return;
    stream = openNotificationStream({
      roomId: currentRoom,
      onSignal: () => {
        void load({ silent: hasLoaded.value });
      },
      onStatus: (status) => {
        streamStatus.value = status;
        // ต่อกลับได้แล้ว ⇒ ไล่เก็บของที่พลาดไประหว่างหลุด
        if (status === 'open') void load({ silent: true });
      },
    });
    stream.start();
  };

  const stopStream = (): void => {
    stream?.stop();
    stream = null;
    streamStatus.value = 'stopped';
  };

  /** กลับมาที่แท็บ = ดึงใหม่ (เบราว์เซอร์มือถือระงับ connection ตอนอยู่เบื้องหลัง) */
  const handleVisibility = (): void => {
    if (document.visibilityState === 'visible') {
      startStream();
      void load({ silent: true });
    } else {
      stopStream();
    }
  };

  // สลับห้อง = ล้างของเก่าทันที แล้วเริ่มใหม่ให้ห้องนั้น
  watch(
    roomId,
    () => {
      stopStream();
      reset();
      if (roomId.value) {
        void load();
        startStream();
      }
    },
    { immediate: false },
  );

  return {
    // state
    items,
    unreadCount,
    hasMore,
    isLoading,
    isRefreshing,
    hasLoaded,
    error,
    streamStatus,
    // actions
    load,
    loadMore,
    markRead,
    markAllRead,
    startStream,
    stopStream,
    handleVisibility,
    syncBadge,
  };
});
