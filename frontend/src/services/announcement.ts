import api from './api';
import type {
  AnnouncementCreateRequest,
  AnnouncementCreateResponse,
  AnnouncementItem,
  AnnouncementListResponse,
  AnnouncementUpdateRequest,
  MarkAnnouncementReadResponse,
} from '@/types/announcement';

/**
 * 📢 ประกาศของห้อง — หนึ่งครั้งไปถึง in-app + push + Discord
 *
 * ใช้ `target_type=room` เหมือน service อื่น ๆ ฝั่งเว็บ (backend แปลงเป็น room_id)
 */
export const AnnouncementService = {
  async list(
    roomId: number,
    params: { limit?: number; before_id?: number; include_archived?: boolean } = {}
  ): Promise<AnnouncementListResponse> {
    return await api.get(`/api/classroom/${roomId}/announcements`, {
      params: { target_type: 'room', ...params },
    });
  },

  async get(roomId: number, announcementId: number): Promise<AnnouncementItem> {
    return await api.get(`/api/classroom/${roomId}/announcements/${announcementId}`, {
      params: { target_type: 'room' },
    });
  },

  async create(roomId: number, payload: AnnouncementCreateRequest): Promise<AnnouncementCreateResponse> {
    return await api.post(`/api/classroom/${roomId}/announcements?target_type=room`, payload);
  },

  async update(
    roomId: number,
    announcementId: number,
    payload: AnnouncementUpdateRequest
  ): Promise<AnnouncementItem> {
    return await api.patch(
      `/api/classroom/${roomId}/announcements/${announcementId}?target_type=room`,
      payload
    );
  },

  async setArchived(roomId: number, announcementId: number, archived = true): Promise<AnnouncementItem> {
    return await api.post(
      `/api/classroom/${roomId}/announcements/${announcementId}/archive`,
      null,
      { params: { target_type: 'room', archived } }
    );
  },

  async markRead(roomId: number, announcementId: number): Promise<MarkAnnouncementReadResponse> {
    return await api.post(
      `/api/classroom/${roomId}/announcements/${announcementId}/read?target_type=room`
    );
  },
};
