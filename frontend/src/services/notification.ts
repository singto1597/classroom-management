/**
 * 🔔 แจ้งเตือนในแอป — HTTP เท่านั้น (ไม่รู้จักเบราว์เซอร์ ไม่มี state)
 *
 * แยกจาก `services/push.ts` อย่างตั้งใจ:
 *   • ที่นี่ = รายการ/อ่านแล้ว/สวิตช์กลุ่ม/quiet hours (ใช้ได้ทุกเบราว์เซอร์)
 *   • `push.ts` = อุปกรณ์ (service worker, การอนุญาต, subscription)
 * ถ้ารวมกัน หน้า settings จะต้องพึ่ง `Notification` API ทั้งที่แค่เปิดดูสวิตช์
 *
 * 📌 ทุกเส้นทางต้องมี `target_type=room` — backend ใช้แปลงเป็น room_id
 *    (บอทใช้ `target_type=server` ระบบนี้จึงไม่ผูกกับ Discord id)
 */

import api from './api';
import type {
  MarkAllReadResponse,
  MarkReadResponse,
  NotificationListResponse,
  NotificationPreference,
  MutableNotificationGroup,
  PreferenceListResponse,
  PushDeliveryStats,
  QuietHours,
  UnreadCountResponse,
} from '@/types/notification';

const base = (roomId: number) => `/api/classroom/${roomId}/notifications`;
const roomParams = { target_type: 'room' } as const;

export const NotificationService = {
  /**
   * หน้ารายการ — ใหม่สุดก่อน แบ่งหน้าด้วย `before_id` (id ของแถวสุดท้ายที่เห็น)
   * ค่า `unread_count` ที่ได้มาคือตัวเลขที่กระดิ่งต้องแสดง (ไม่คำนวณเองฝั่งหน้า)
   */
  async list(
    roomId: number,
    params: { limit?: number; before_id?: number } = {},
  ): Promise<NotificationListResponse> {
    return await api.get(base(roomId), { params: { ...roomParams, ...params } });
  },

  async unreadCount(roomId: number): Promise<UnreadCountResponse> {
    return await api.get(`${base(roomId)}/unread-count`, { params: roomParams });
  },

  /** ไม่ 404 เมื่อไม่มีแถว — backend ตอบ 200 + `marked: false` */
  async markRead(roomId: number, notificationId: number): Promise<MarkReadResponse> {
    return await api.post(`${base(roomId)}/${notificationId}/read`, null, {
      params: roomParams,
    });
  },

  async markAllRead(roomId: number): Promise<MarkAllReadResponse> {
    return await api.post(`${base(roomId)}/read-all`, null, { params: roomParams });
  },

  async getPreferences(roomId: number): Promise<PreferenceListResponse> {
    return await api.get(`${base(roomId)}/preferences`, { params: roomParams });
  },

  async setPreference(
    roomId: number,
    payload: { group_type: MutableNotificationGroup; inapp: boolean; push: boolean },
  ): Promise<NotificationPreference> {
    return await api.put(`${base(roomId)}/preferences`, payload, { params: roomParams });
  },

  /** สมาชิกทุกคนอ่านได้ — เพื่ออธิบายว่าทำไม push เงียบตอนกลางคืน */
  async getQuietHours(roomId: number): Promise<QuietHours> {
    return await api.get(`${base(roomId)}/quiet-hours`, { params: roomParams });
  },

  /** ต้องมี `MANAGE_CLASSROOM_SETTINGS` — backend ตอบ 403 ให้สมาชิกทั่วไป */
  async setQuietHours(roomId: number, payload: QuietHours): Promise<QuietHours> {
    return await api.put(`${base(roomId)}/quiet-hours`, payload, { params: roomParams });
  },

  /**
   * สถิติการส่ง push — ต้องมี `MANAGE_CLASSROOM_SETTINGS` (backend ตอบ 403 ให้สมาชิกทั่วไป)
   * `queue` = ของห้องนี้ · `last_round` = ของ worker ทั้งระบบ (อาจเป็น `null` = ไม่รู้)
   */
  async getPushStats(roomId: number): Promise<PushDeliveryStats> {
    return await api.get(`${base(roomId)}/push/stats`, { params: roomParams });
  },

  /** URL ของสตรีม SSE — ใช้กับ `openNotificationStream()` (ต้องแนบ header เอง) */
  streamUrl(roomId: number): string {
    const origin = (api.defaults.baseURL ?? '').replace(/\/+$/, '');
    return `${origin}${base(roomId)}/stream?target_type=room`;
  },
};
