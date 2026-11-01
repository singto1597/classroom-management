import api from './api';
import type { MeActivityResponse, MeStats } from '@/types/me';

/**
 * 👤 "ของฉัน" — ฟีดและสถิติส่วนตัว (P3.3)
 *
 * ใช้ `target_type=room` เหมือน service อื่น ๆ ฝั่งเว็บ · backend ตรวจสมาชิกห้องเอง
 * ⇒ คนนอกห้องได้ 403 ซึ่งหน้าจอต้องแยกจาก "ยังไม่มีข้อมูล"
 */
export const MeService = {
  async activity(
    roomId: number,
    params: { limit?: number; cursor?: string | null } = {}
  ): Promise<MeActivityResponse> {
    return await api.get(`/api/classroom/${roomId}/me/activity`, {
      params: { target_type: 'room', ...params },
    });
  },

  async stats(roomId: number): Promise<MeStats> {
    return await api.get(`/api/classroom/${roomId}/me/stats`, {
      params: { target_type: 'room' },
    });
  },
};
