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

// ── [P6.5] สถิติการส่ง push ──────────────────────────────────────────────────

/** สถานะคิว **ของห้องนี้** — "จะลองใหม่" (`retry`) แยกจาก "ยอมแพ้" (`dropped`/`stale`) */
export interface PushQueueStats {
  pending: number;
  retry: number;
  dropped: number;
  stale: number;
  /** ส่งสำเร็จในช่วง 24 ชม. ล่าสุด (ไม่ใช่ยอดสะสมตลอดชีพ) */
  sent_24h: number;
  /** ถึงกำหนดส่งแล้วแต่ยังไม่ได้ส่ง */
  due_now: number;
  /** ของที่รอนานที่สุดกี่วินาที (0 = ไม่มีของค้าง) */
  oldest_due_seconds: number;
}

/** ผลรอบล่าสุดของ worker — **ทั้งระบบ ไม่เฉพาะห้องนี้** (worker ตัวเดียวส่งทุกห้อง) */
export interface PushLastRoundStats {
  at: string;
  claimed: number;
  sent: number;
  retry: number;
  gone: number;
  dropped: number;
  deferred: number;
  stale: number;
  /** `false` = ตอนนั้นยังไม่ได้ตั้ง VAPID (worker วนอยู่แต่ส่งไม่ได้) */
  enabled: boolean;
}

export interface PushDeliveryStats {
  room_id: number;
  queue: PushQueueStats;
  /** `null` = ไม่รู้ (worker ยังไม่เคยรายงาน / Redis ต่อไม่ได้) — **ไม่ใช่ศูนย์** */
  last_round: PushLastRoundStats | null;
  worker_heartbeat_age_seconds: number | null;
  generated_at: string;
}
