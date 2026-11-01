/**
 * "ของฉัน" — ฟีดและสถิติส่วนตัว (P3.3)
 *
 * 🔑 `MeStats` แยก **ของฉัน** (`activities_joined`, `paid_total`, …) ออกจาก
 * **ของห้อง** (`room_tasks_done`, `room_tasks_pending`) ด้วยชื่อเสมอ — หน้าจอ
 * ห้ามตัด `room_` ออกตอนแสดงผล ไม่งั้นผู้ใช้จะอ่านว่างานทั้งห้องเป็นงานของตัวเอง
 */

export type MeActivityKind = 'payment' | 'activity';

export interface MeActivityItem {
  kind: MeActivityKind;
  entity_id: number;
  title: string;
  detail: string | null;
  happened_at: string;
  /** เฉพาะ payment — ยอดที่จ่ายครั้งนั้น */
  amount: number | null;
  /** เฉพาะ payment — เลขที่ใบเสร็จ */
  reference: string | null;
  status: string | null;
  /** เฉพาะ activity — วันที่จัดกิจกรรม (YYYY-MM-DD) */
  activity_date: string | null;
  url: string;
}

export interface MeActivityResponse {
  items: MeActivityItem[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface MeStats {
  has_profile: boolean;
  /** P5 จะเติมข้อมูลเทอม — ตอนนี้ null = ทั้งหมด */
  term: Record<string, unknown> | null;
  activities_joined: number;
  activity_hours: number;
  paid_total: number;
  outstanding: number;
  unpaid_bills: number;
  /** งานของ *ห้อง* — ไม่ใช่ของฉัน */
  room_tasks_done: number;
  /** งานของ *ห้อง* — ไม่ใช่ของฉัน */
  room_tasks_pending: number;
}
