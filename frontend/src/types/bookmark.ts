/** บุ๊กมาร์ก "บันทึกไว้" (P3.4) */

export type BookmarkEntityType = 'announcement' | 'activity';

export interface BookmarkItem {
  bookmark_id: number;
  entity_type: BookmarkEntityType;
  entity_id: number;
  title: string;
  snippet: string;
  /** ประกาศ = วันที่โพสต์ · กิจกรรม = วันที่จัด (YYYY-MM-DD) */
  occurred_on: string | null;
  url: string;
  /** false = เป้าหมายถูกลบแล้ว — ห้ามลิงก์ไป 404 */
  available: boolean;
  created_at: string;
}

export interface BookmarkListResponse {
  items: BookmarkItem[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface BookmarkCreateResponse {
  id: number;
  entity_type: BookmarkEntityType;
  entity_id: number;
  created_at: string;
  /** false = บันทึกไว้อยู่แล้ว (คำขอซ้ำไม่มีผลข้างเคียง) */
  created: boolean;
}

export interface BookmarkState {
  bookmarked: boolean;
  bookmark_id: number | null;
}

export const BOOKMARK_ENTITY_LABELS: Record<BookmarkEntityType, string> = {
  announcement: 'ประกาศ',
  activity: 'กิจกรรม',
};
