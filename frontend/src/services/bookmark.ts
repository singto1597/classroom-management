import api from './api';
import type {
  BookmarkCreateResponse,
  BookmarkEntityType,
  BookmarkListResponse,
  BookmarkState,
} from '@/types/bookmark';

/**
 * 🔖 บันทึกไว้ (P3.4)
 *
 * `add` ซ้ำได้และตอบ `created: false` เมื่อมีอยู่แล้ว — หน้าเว็บไม่ต้องเช็คสถานะก่อนกด
 * (กัน race: อีกแท็บกดไปแล้ว) ใช้ค่าที่ backend ตอบเป็นความจริงเดียว
 */
export const BookmarkService = {
  async list(
    roomId: number,
    params: { entity_type?: BookmarkEntityType; limit?: number; cursor?: string | null } = {}
  ): Promise<BookmarkListResponse> {
    return await api.get(`/api/classroom/${roomId}/bookmarks`, {
      params: { target_type: 'room', ...params },
    });
  },

  async add(
    roomId: number,
    entityType: BookmarkEntityType,
    entityId: number
  ): Promise<BookmarkCreateResponse> {
    return await api.post(`/api/classroom/${roomId}/bookmarks?target_type=room`, {
      entity_type: entityType,
      entity_id: entityId,
    });
  },

  async remove(roomId: number, bookmarkId: number): Promise<void> {
    await api.delete(`/api/classroom/${roomId}/bookmarks/${bookmarkId}`, {
      params: { target_type: 'room' },
    });
  },

  async state(
    roomId: number,
    entityType: BookmarkEntityType,
    entityId: number
  ): Promise<BookmarkState> {
    return await api.get(`/api/classroom/${roomId}/bookmarks/state`, {
      params: { target_type: 'room', entity_type: entityType, entity_id: entityId },
    });
  },
};
