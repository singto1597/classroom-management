/**
 * 🔔 กลุ่มแจ้งเตือน — คำไทย ไอคอน และคำอธิบายชุดเดียวของทั้งแอป
 *
 * ทำไมต้องมีไฟล์นี้: กระดิ่ง (NotificationCenter) · หน้าตั้งค่า · ป้ายในรายการ
 * ต้องเรียกกลุ่มเดียวกันด้วยชื่อเดียวกัน——ถ้าต่างคนต่างเขียน จะได้ "งาน" / "การบ้าน"
 * / "Task" ปนกันในหน้าเดียว ซึ่งขัดกับ `docs/glossary.md`
 *
 * ⚠️ `group` ต้องตรงกับ CHECK ของตาราง `notifications` และ
 *    `NotificationGroup` ใน `types/notification.ts`
 * ⚠️ `announcement` ไม่อยู่ในลิสต์นี้ — ปิดไม่ได้ จึงไม่มีสวิตช์ให้แสดง
 */

import type { MutableNotificationGroup, NotificationGroup, NotificationPriority } from '@/types/notification';

export interface NotificationGroupMeta {
  group: MutableNotificationGroup;
  /** ชื่อกลุ่มที่ผู้ใช้เห็น */
  label: string;
  /** ประโยคอธิบายว่ากลุ่มนี้แจ้งอะไร — ใช้ใต้สวิตช์ในหน้าตั้งค่า */
  hint: string;
  /** ชื่อคลาส bootstrap-icons */
  icon: string;
}

/** ลำดับตรงกับที่ผู้ใช้เจอบ่อยที่สุด — ไม่ใช่ตามตัวอักษร */
export const NOTIFICATION_GROUPS: readonly NotificationGroupMeta[] = [
  {
    group: 'task',
    label: 'งาน',
    hint: 'งานใหม่ งานใกล้ครบกำหนด และงานที่ถูกแก้ไข',
    icon: 'bi-clipboard-check',
  },
  {
    group: 'finance',
    label: 'การเงิน',
    hint: 'บิลใหม่ การรับชำระเงิน และยอดค้างชำระ',
    icon: 'bi-wallet2',
  },
  {
    group: 'activity',
    label: 'กิจกรรม',
    hint: 'กิจกรรมใหม่ ใกล้เปิดรับ และผลการเช็คชื่อ',
    icon: 'bi-calendar-heart',
  },
  {
    group: 'member',
    label: 'สมาชิก',
    hint: 'คำขอเข้าร่วมห้อง คำเชิญยืนยันตัวตน และการอนุมัติ',
    icon: 'bi-person-plus',
  },
];

/** ชื่อกลุ่มแบบอ่านได้ทุกค่า (รวม `announcement` ที่ไม่มีสวิตช์) */
export const NOTIFICATION_GROUP_LABELS: Record<NotificationGroup, string> = {
  task: 'งาน',
  finance: 'การเงิน',
  activity: 'กิจกรรม',
  member: 'สมาชิก',
  announcement: 'ประกาศ',
};

/** ไอคอนของกลุ่ม (ใช้ในรายการแจ้งเตือน/ประกาศ) */
export const NOTIFICATION_GROUP_ICONS: Record<NotificationGroup, string> = {
  task: 'bi-clipboard-check',
  finance: 'bi-wallet2',
  activity: 'bi-calendar-heart',
  member: 'bi-person-plus',
  announcement: 'bi-megaphone',
};

/** ป้ายความสำคัญของประกาศ — ตรงกับ `notification_priority`/`announcements.priority` */
export const PRIORITY_LABELS: Record<NotificationPriority, string> = {
  normal: 'ปกติ',
  high: 'สำคัญ',
  urgent: 'ด่วน',
};

/** สีของป้ายความสำคัญ — ใช้ token ของระบบ (แดง = danger, ไม่ใช่สีแบรนด์) */
export const PRIORITY_BADGE_CLASSES: Record<NotificationPriority, string> = {
  normal: 'bg-stone-100 text-stone-700',
  high: 'bg-info-100 text-info-800',
  urgent: 'bg-danger-100 text-danger-800',
};
