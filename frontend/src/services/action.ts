import api from './api';
import type { CustomMessageRequest, CustomMessageResponse } from '@/types/action';

export const ActionService = {
  /**
   * 📢 ส่งข้อความประกาศจากเว็บเข้า Discord (event: CUSTOM_MESSAGE)
   * Web path: POST /api/classroom/{room_id}/messages?target_type=room
   */
  async sendCustomMessage(roomId: number, payload: CustomMessageRequest): Promise<CustomMessageResponse> {
    return await api.post(`/api/classroom/${roomId}/messages?target_type=room`, payload);
  }
};
