// 📢 ประกาศของห้อง — แมปจาก backend/models/announcement_schemas.py

export type AnnouncementPriority = 'normal' | 'high' | 'urgent';

export interface AnnouncementItem {
  id: number;
  title: string;
  body: string;
  priority: AnnouncementPriority;
  pinned: boolean;
  archived_at: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  /** ยังไม่อ่าน = มีแจ้งเตือนของผู้ใช้คนนี้ที่ยังไม่ได้เปิด */
  is_unread: boolean;
}

export interface AnnouncementListResponse {
  /** เฉพาะหน้าแรก — หน้าถัดไปเป็นลิสต์ว่าง */
  pinned: AnnouncementItem[];
  items: AnnouncementItem[];
  has_more: boolean;
}

export interface AnnouncementCreateRequest {
  title: string;
  body?: string;
  priority?: AnnouncementPriority;
  pinned?: boolean;
}

export interface AnnouncementCreateResponse {
  item: AnnouncementItem;
  /** จำนวนสมาชิกที่ล็อกอินจริงซึ่งได้รับแจ้งเตือน (ไม่รวมผู้เขียน) */
  delivered_count: number;
}

export interface AnnouncementUpdateRequest {
  title?: string;
  body?: string;
  priority?: AnnouncementPriority;
  pinned?: boolean;
}

export interface MarkAnnouncementReadResponse {
  announcement_id: number;
  marked: boolean;
}
