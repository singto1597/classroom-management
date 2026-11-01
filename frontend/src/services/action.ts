import api from './api';
import type { CustomMessageRequest, CustomMessageResponse } from '@/types/action';

/**
 * @deprecated ใช้ `AnnouncementService` (`services/announcement.ts`) แทน —
 * ประกาศควรขึ้นครบทั้ง in-app + push + Discord ไม่ใช่แค่ Discord
 * (`POST .../messages` ฝั่ง backend ยังคงอยู่เพื่อความเข้ากันได้ของบอท/ไคลเอนต์เดิม)
 */
export const ActionService = {
  /**
   * 📢 ส่งข้อความประกาศจากเว็บเข้า Discord (event: CUSTOM_MESSAGE)
   * Web path: POST /api/classroom/{room_id}/messages?target_type=room
   */
  async sendCustomMessage(roomId: number, payload: CustomMessageRequest): Promise<CustomMessageResponse> {
    return await api.post(`/api/classroom/${roomId}/messages?target_type=room`, payload);
  }
};
