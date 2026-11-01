// 🔔 แจ้งเตือนในแอป — แมปตรงกับ backend/models/notification_schemas.py

/** กลุ่มแจ้งเตือน — ต้องตรงกับ CHECK ของตาราง `notifications` */
export type NotificationGroup = 'task' | 'finance' | 'activity' | 'member' | 'announcement';

/** กลุ่มที่ผู้ใช้ปิดเองได้ (`announcement` ปิดไม่ได้ — เป็นช่องทางราชการของห้อง) */
export type MutableNotificationGroup = Exclude<NotificationGroup, 'announcement'>;

export type NotificationPriority = 'normal' | 'high' | 'urgent';

export interface NotificationItem {
  id: number;
  group_type: NotificationGroup;
  type: string;
  priority: NotificationPriority;
  title: string;
  body: string;
  entity_type: string | null;
  entity_id: string | null;
  /** ลิงก์ภายในแอป เช่น `/announcements/12` — ไม่มี = กดแล้วไม่ไปไหน */
  url: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  /** ตัวเลขเดียวกับที่กระดิ่งแสดง — มาจาก backend ไม่นับซ้ำฝั่งหน้า */
  unread_count: number;
  has_more: boolean;
}

export interface UnreadCountResponse {
  unread_count: number;
}

export interface MarkReadResponse {
  notification_id: number;
  /** `false` = แถวนี้ไม่ใช่ของผู้ขอ (หรือไม่มีอยู่) — ไม่ใช่ error */
  marked: boolean;
}

export interface MarkAllReadResponse {
  marked_count: number;
}

export interface NotificationPreference {
  group_type: MutableNotificationGroup;
  inapp: boolean;
  push: boolean;
}

export interface PreferenceListResponse {
  items: NotificationPreference[];
}

/** ช่วงงดรบกวนของห้อง — `start === end` หมายถึง "ปิด" */
export interface QuietHours {
  enabled: boolean;
  /** HH:MM เวลาไทย */
  start: string;
  /** HH:MM เวลาไทย */
  end: string;
}
