/**
 * 🧭 NAV — แหล่งความจริงเดียวของ "เมนู" และ "ชื่อหน้า"
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องย้ายออกมาจาก MainLayout.vue
 * ═══════════════════════════════════════════════════════════════════════════
 * เดิมรายการเมนู (8 รายการ), แท็บมือถือ (3 รายการ) และชื่อ breadcrumb
 * ถูกเขียนไว้กลาง `layouts/MainLayout.vue` (1,009 บรรทัด) ⇒
 *   • เพิ่มหน้าใหม่แล้วลืมใส่เมนู = ไม่มีอะไรฟ้อง (ไม่มี type error)
 *   • หน้าใหม่ที่ไม่มี `title` ทำให้แท็บเบราว์เซอร์ค้างชื่อหน้าเก่า
 *   • ทดสอบไม่ได้เลยเพราะต้อง mount layout ทั้งตัว
 *
 * ที่นี่จึงเก็บ "ข้อความที่ผู้ใช้เห็น" ไว้ที่เดียว ส่วน `router/routes.ts`
 * อ้าง `routeTitles` และ `MainLayout.vue` อ้าง `NAV_ITEMS`/`NAV_TABS`
 * เทสต์ `router/__tests__/routes.spec.ts` กันไม่ให้มี route ที่ไม่มีชื่อ
 *
 * ⚠️ `path` ของ NAV_ITEMS ต้องตรงกับ path จริงใน `router/routes.ts`
 *    (มีเทสต์ตรวจอยู่ — เพิ่มเมนูที่ชี้ path ผีจะพังตอน CI)
 */

import type { NavTabKey } from '@/router/meta';

export interface NavItem {
  /** ชื่อที่แสดงในเมนู / breadcrumb */
  name: string;
  /** path ปลายทาง (ต้องมี route จริง) */
  path: string;
  /** ไอคอน bootstrap-icons เช่น 'bi-people' */
  icon: string;
}

/** แท็บล่าง — ผูกกับ `route.meta.navTab` เพื่อไฮไลต์ทั้ง section ไม่ใช่แค่ path ตรงตัว */
export interface NavTab extends NavItem {
  key: NavTabKey;
}

/** กลุ่มเมนูในหน้า "เพิ่มเติม" และ sidebar เดสก์ท็อป */
export interface NavGroup {
  title: string;
  items: readonly NavItem[];
}

/**
 * เมนูทั้งหมด (sidebar เดสก์ท็อป + ชีต "เพิ่มเติม" บนมือถือ)
 *
 * ⚠️ ลำดับคือลำดับที่ผู้ใช้เห็น — เรียงตามความถี่การใช้งาน ไม่ใช่ตามตัวอักษร
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { name: 'หน้าแรก', path: '/dashboard', icon: 'bi-grid' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people' },
  { name: 'งานและโน้ต', path: '/tasks', icon: 'bi-clipboard-check' },
  { name: 'ตารางเรียน', path: '/schedules', icon: 'bi-calendar-event' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
  { name: 'กิจกรรม', path: '/activities', icon: 'bi-calendar-heart' },
  // 📢 P2.6 — "ประกาศ" คือรายการที่อ่านได้ทุกคน (เดิมเมนูชี้ไปหน้าเขียนอย่างเดียว)
  // ปุ่ม "ส่งประกาศ" อยู่ในหน้ารายการ ไม่ต้องมีเมนูที่สอง
  { name: 'ประกาศ', path: '/announcements', icon: 'bi-megaphone' },
  // 👤 P3.4 — "ของฉัน" = ไทม์ไลน์ส่วนตัว + สถิติ + รายการที่บันทึกไว้
  //    อยู่ใต้ "เพิ่มเติม" (ไม่ใช่แท็บหลัก) เพราะเป็นหน้าที่เปิดเป็นครั้งคราว
  { name: 'ของฉัน', path: '/me/activity', icon: 'bi-bookmark-star' },
  { name: 'ตั้งค่าการแจ้งเตือน', path: '/settings/notifications', icon: 'bi-bell' },
  // 🗓️ P5 — ปฏิทินของห้อง (ปี พ.ศ. + เทอม) ใช้เป็นตัวกรองสถิติ ไม่ใช่การเลื่อนชั้น
  { name: 'ปีการศึกษา', path: '/settings/academic-periods', icon: 'bi-calendar3' },
  // 🔍 P6.2 — บันทึกกิจกรรม: หน้าแสดงสำหรับทุกคน แต่เนื้อหาจะบอกเองว่าต้องมีสิทธิ์
  //    (backend ตอบ 403) ⇒ ไม่ซ่อนเมนู ไม่ให้ผู้ใช้เดาว่ามีฟีเจอร์นี้หรือไม่
  { name: 'บันทึกกิจกรรม', path: '/settings/audit-logs', icon: 'bi-journal-text' },
  { name: 'แผนผังห้องเรียน', path: '/roadmap', icon: 'bi-map' },
];

/**
 * แท็บบนมือถือ (แถบล่าง) — 5 ปลายทาง เท่ากับ PIRIvoice
 *
 * `key` ต้องตรงกับ `route.meta.navTab` ของทุกหน้าใน section นั้น
 * (`/students/:id` ยังไฮไลต์แท็บนักเรียน) — ไม่ได้ใช้ `startsWith(path)`
 * เพราะหน้า detail หลายหน้ามี path ที่ไม่ขึ้นต้นด้วย path ของแท็บ
 *
 * ⚠️ `/more` ไม่ได้อยู่ใน `NAV_ITEMS` (desktop sidebar ไม่ต้องมีทางเข้าที่สอง)
 *    เทสต์จึงต้องยกเว้นให้เฉพาะแท็บนี้
 */
export const NAV_TABS: readonly NavTab[] = [
  { key: 'home', name: 'หน้าแรก', path: '/dashboard', icon: 'bi-house-door' },
  { key: 'students', name: 'นักเรียน', path: '/students', icon: 'bi-people' },
  { key: 'tasks', name: 'งาน', path: '/tasks', icon: 'bi-clipboard-check' },
  { key: 'finance', name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
  { key: 'more', name: 'เพิ่มเติม', path: '/more', icon: 'bi-grid-3x3-gap' },
];

/** path ที่อยู่ในแท็บล่างแล้ว ⇒ ไม่ต้องซ้ำในหน้า "เพิ่มเติม" */
export const NAV_TAB_PATHS: readonly string[] = NAV_TABS.map((tab) => tab.path);

/** รายการที่เหลือในหน้า "เพิ่มเติม" (มือถือ) — คำนวณครั้งเดียวตอนโหลดโมดูล */
export const MORE_NAV_ITEMS: readonly NavItem[] = NAV_ITEMS.filter(
  (item) => !NAV_TAB_PATHS.includes(item.path),
);

/**
 * กลุ่มเมนูของหน้า "เพิ่มเติม" และ sidebar เดสก์ท็อป
 *
 * ✅ ทุกรายการใน `MORE_NAV_ITEMS` ต้องปรากฏ **ครั้งเดียว** ในกลุ่มใดกลุ่มหนึ่ง
 *    (มีเทสต์ตรวจ) ⇒ เพิ่มเมนูใหม่แล้วลืมจัดกลุ่ม = CI แดง ไม่ใช่เมนูหายเงียบ ๆ
 */
export const MORE_NAV_GROUPS: readonly NavGroup[] = [
  {
    title: 'การเรียน',
    items: [
      { name: 'ตารางเรียน', path: '/schedules', icon: 'bi-calendar-event' },
      { name: 'ของฉัน', path: '/me/activity', icon: 'bi-bookmark-star' },
      { name: 'แผนผังห้องเรียน', path: '/roadmap', icon: 'bi-map' },
    ],
  },
  {
    title: 'กิจกรรมและประกาศ',
    items: [
      { name: 'กิจกรรม', path: '/activities', icon: 'bi-calendar-heart' },
      { name: 'ประกาศ', path: '/announcements', icon: 'bi-megaphone' },
    ],
  },
  {
    title: 'ระบบ',
    items: [
      { name: 'ปีการศึกษา', path: '/settings/academic-periods', icon: 'bi-calendar3' },
      { name: 'บันทึกกิจกรรม', path: '/settings/audit-logs', icon: 'bi-journal-text' },
      { name: 'ตั้งค่าการแจ้งเตือน', path: '/settings/notifications', icon: 'bi-bell' },
    ],
  },
];

/** เมนูหลักที่ยังอยู่ในแท็บล่าง — sidebar แสดงก่อนกลุ่มอื่น */
export const PRIMARY_NAV_ITEMS: readonly NavItem[] = NAV_ITEMS.filter((item) =>
  NAV_TAB_PATHS.includes(item.path),
);

/**
 * ตรวจว่าเมนู `itemPath` กำลังใช้งานอยู่หรือไม่จาก path ปัจจุบัน
 *
 * 🔴 `/dashboard` ต้องเทียบแบบ "เท่ากับ" ไม่ใช่ `startsWith` — ไม่งั้น
 * `/dashboard` จะไป match ทุก path ที่ขึ้นต้นด้วยคำเดียวกันในอนาคต
 * (`/` ไม่นับแล้ว — เป็นหน้า landing สาธารณะตั้งแต่ Stage 3)
 */
export function isNavItemActive(itemPath: string, currentPath: string): boolean {
  if (itemPath === '/dashboard') return currentPath === '/dashboard';
  return currentPath === itemPath || currentPath.startsWith(`${itemPath}/`);
}

/**
 * ชื่อหน้า (แท็บเบราว์เซอร์) ของทุก route — ตั้งใจให้ตรงกับ `<h1>` ของหน้านั้น
 *
 * ⚠️ คีย์คือ **ชื่อ route (`name`)** ใน `router/routes.ts` ไม่ใช่ path
 *    ⇒ route ที่เปลี่ยน path ได้โดยไม่ต้องแก้ชื่อจะไม่ทำให้ชื่อหน้าเพี้ยน
 */
export const routeTitles = {
  // ── Global (ไม่ต้องมีห้อง) ──────────────────────────────────────────────
  landing: 'หน้าแรก',
  login: 'เข้าสู่ระบบ',
  'google-callback': 'กำลังเข้าสู่ระบบ',
  'discord-callback': 'กำลังเข้าสู่ระบบ',
  onboarding: 'กรอกข้อมูลส่วนตัว',
  lobby: 'เลือกห้องเรียน',
  account: 'บัญชีส่วนกลาง',
  'account-profile': 'แก้ไขข้อมูลส่วนตัว',
  'not-found': 'ไม่พบหน้านี้',

  // ── หน้าหลัก ────────────────────────────────────────────────────────────
  dashboard: 'หน้าแรก',
  more: 'เพิ่มเติม',
  roadmap: 'แผนผังห้องเรียน',
  schedules: 'ตารางเรียน',

  // ── นักเรียน ───────────────────────────────────────────────────────────
  students: 'จัดการนักเรียน',
  'add-student': 'เพิ่มนักเรียนใหม่',
  'export-students': 'เครื่องมือสร้างไฟล์ Export',
  'student-profile': 'โปรไฟล์นักเรียน',
  'edit-student': 'แก้ไขข้อมูลนักเรียน',

  // ── งานและโน้ต ──────────────────────────────────────────────────────────
  tasks: 'รายการงานและโน้ต',
  'add-task': 'สร้างงานใหม่',
  'edit-task': 'แก้ไขงาน',

  // ── การเงิน ─────────────────────────────────────────────────────────────
  'finance-dashboard': 'ภาพรวมการเงิน',
  'finance-settings': 'ตั้งค่าระบบการเงิน',
  'finance-add-transaction': 'บันทึกรายการเงิน',
  'finance-transaction-history': 'ประวัติการทำรายการ',
  'finance-collections': 'โปรเจกต์เก็บเงิน',
  'finance-collection-detail': 'รายละเอียดโปรเจกต์',
  'finance-debtors': 'ผู้ค้างชำระ',
  'finance-my-debts': 'ยอดค้างชำระของฉัน',
  'finance-credits': 'เงินรับล่วงหน้า',
  'finance-statements': 'งบการเงิน',
  'finance-budgets': 'งบประมาณ',
  'finance-receipts': 'ใบเสร็จ / ใบแจ้งหนี้',
  'finance-receipt-detail': 'รายละเอียดเอกสาร',

  // ── กิจกรรม ─────────────────────────────────────────────────────────────
  activities: 'กิจกรรมและผู้เข้าร่วม',
  'create-activity': 'สร้างกิจกรรม',
  'compare-activities': 'เปรียบเทียบกิจกรรม',
  'edit-activity': 'แก้ไขกิจกรรม',
  'manage-activity': 'จัดการผู้เข้าร่วม',
  'activity-detail': 'รายละเอียดกิจกรรม',

  // ── ประกาศ & แจ้งเตือน ─────────────────────────────────────────────────
  announcements: 'ประกาศ',
  // 👤 ของฉัน — ไทม์ไลน์/สถิติส่วนตัว + บุ๊กมาร์ก (P3.3 + P3.4)
  'my-activity': 'ของฉัน',
  'announcement-detail': 'รายละเอียดประกาศ',
  'notification-settings': 'ตั้งค่าการแจ้งเตือน',
  // 🗓️ P5 — ชื่อหน้าเดียวกับเมนู เพื่อให้ breadcrumb กับแท็บเบราว์เซอร์ตรงกัน
  'academic-periods': 'ปีการศึกษาและเทอม',
  // 🔍 P6.2 — ใช้ให้ตรงกันทั้งเมนู แท็บเบราว์เซอร์ และหัวหน้า
  'audit-logs': 'บันทึกกิจกรรม',

  // ── อื่น ๆ ──────────────────────────────────────────────────────────────
  DiscordConnect: 'เชื่อมต่อ Discord',
  'send-message': 'ส่งประกาศ',
} as const satisfies Readonly<Record<string, string>>;
