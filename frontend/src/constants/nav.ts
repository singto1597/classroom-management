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

export interface NavItem {
  /** ชื่อที่แสดงในเมนู / breadcrumb */
  name: string;
  /** path ปลายทาง (ต้องมี route จริง) */
  path: string;
  /** ไอคอน bootstrap-icons เช่น 'bi-people' */
  icon: string;
}

/**
 * เมนูทั้งหมด (sidebar เดสก์ท็อป + ชีต "เพิ่มเติม" บนมือถือ)
 *
 * ⚠️ ลำดับคือลำดับที่ผู้ใช้เห็น — เรียงตามความถี่การใช้งาน ไม่ใช่ตามตัวอักษร
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { name: 'แดชบอร์ด', path: '/dashboard', icon: 'bi-grid' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people' },
  { name: 'งานและโน้ต', path: '/tasks', icon: 'bi-clipboard-check' },
  { name: 'ตารางเรียน', path: '/schedules', icon: 'bi-calendar-event' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
  { name: 'กิจกรรม', path: '/activities', icon: 'bi-calendar-heart' },
  { name: 'ประกาศ Discord', path: '/messages', icon: 'bi-megaphone' },
  { name: 'แผนผังห้องเรียน', path: '/roadmap', icon: 'bi-map' },
];

/**
 * แท็บบนมือถือ (แถบล่าง) — ช่องตรงกลางใน `MainLayout` เป็น FAB สร้างงาน
 * จึงมีแค่ 3 ปลายทาง และต้องมีอยู่จริงใน `NAV_ITEMS` (เทสต์ตรวจ)
 */
export const NAV_TABS: readonly NavItem[] = [
  { name: 'หน้าแรก', path: '/dashboard', icon: 'bi-house-door' },
  { name: 'นักเรียน', path: '/students', icon: 'bi-people' },
  { name: 'การเงิน', path: '/finance', icon: 'bi-wallet2' },
];

/** path ที่อยู่ในแท็บล่างแล้ว ⇒ ไม่ต้องซ้ำในชีต "เพิ่มเติม" */
export const NAV_TAB_PATHS: readonly string[] = NAV_TABS.map((tab) => tab.path);

/** รายการที่เหลือในชีต "เพิ่มเติม" (มือถือ) — คำนวณครั้งเดียวตอนโหลดโมดูล */
export const MORE_NAV_ITEMS: readonly NavItem[] = NAV_ITEMS.filter(
  (item) => !NAV_TAB_PATHS.includes(item.path),
);

/**
 * ตรวจว่าเมนู `itemPath` กำลังใช้งานอยู่หรือไม่จาก path ปัจจุบัน
 *
 * 🔴 `/dashboard` ต้องเทียบแบบ "เท่ากับ" ไม่ใช่ `startsWith` — ไม่งั้น
 * `/dashboard` จะไป match ทุก path ที่ขึ้นต้นด้วยคำเดียวกันในอนาคต
 * (และ `/` คือ path ที่ redirect ไป dashboard จึงต้องนับด้วย)
 */
export function isNavItemActive(itemPath: string, currentPath: string): boolean {
  if (itemPath === '/dashboard') {
    return currentPath === '/dashboard' || currentPath === '/';
  }
  return currentPath.startsWith(itemPath);
}

/**
 * ชื่อเมนูแม่ของ path ปัจจุบัน — ใช้ทำ breadcrumb
 * คืน `null` เมื่ออยู่ที่แดชบอร์ด/ราก (ไม่มีอะไรให้ breadcrumb)
 */
export function navSectionName(currentPath: string): string | null {
  if (currentPath === '/dashboard' || currentPath === '/') return null;
  const matched = NAV_ITEMS.find(
    (item) => item.path !== '/dashboard' && currentPath.startsWith(item.path),
  );
  return matched ? matched.name : null;
}

/**
 * ชื่อหน้า (แท็บเบราว์เซอร์) ของทุก route — ตั้งใจให้ตรงกับ `<h1>` ของหน้านั้น
 *
 * ⚠️ คีย์คือ **ชื่อ route (`name`)** ใน `router/routes.ts` ไม่ใช่ path
 *    ⇒ route ที่เปลี่ยน path ได้โดยไม่ต้องแก้ชื่อจะไม่ทำให้ชื่อหน้าเพี้ยน
 */
export const routeTitles = {
  // ── Global (ไม่ต้องมีห้อง) ──────────────────────────────────────────────
  login: 'เข้าสู่ระบบ',
  'google-callback': 'กำลังเข้าสู่ระบบ',
  'discord-callback': 'กำลังเข้าสู่ระบบ',
  onboarding: 'กรอกข้อมูลส่วนตัว',
  lobby: 'เลือกห้องเรียน',
  'not-found': 'ไม่พบหน้านี้',

  // ── หน้าหลัก ────────────────────────────────────────────────────────────
  dashboard: 'แดชบอร์ด',
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

  // ── อื่น ๆ ──────────────────────────────────────────────────────────────
  DiscordConnect: 'เชื่อมต่อ Discord',
  'send-message': 'ประกาศเข้า Discord',
} as const satisfies Readonly<Record<string, string>>;
