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

  /**
   * สถิติของฉัน — ส่ง `year_id`/`term_id` เฉพาะเมื่อผู้ใช้เลือกเอง
   *
   * ไม่ส่งเลย = backend ใช้ **ปี/เทอมปัจจุบันของห้อง** (ถ้ามี) แล้วบอกกลับมาใน
   * `stats.term.source === 'current'` ⇒ ห้ามส่งค่าปลอม (0/null) แทน "ไม่กรอง"
   * เพราะ `null` ของ `year_id` ใน endpoint นี้ไม่มีความหมายแบบนั้น
   */
  async stats(
    roomId: number,
    params: { year_id?: number; term_id?: number } = {},
  ): Promise<MeStats> {
    return await api.get(`/api/classroom/${roomId}/me/stats`, {
      params: { target_type: 'room', ...params },
    });
  },
};
