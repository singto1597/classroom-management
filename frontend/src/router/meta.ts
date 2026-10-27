/**
 * 🧩 สัญญาของ `route.meta` — ประกาศครั้งเดียว ใช้ทั้ง router และ layout
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมีไฟล์นี้
 * ═══════════════════════════════════════════════════════════════════════════
 * `route.meta` ของ vue-router เป็น `Record<string, unknown>` — พิมพ์ผิดชื่อฟิลด์
 * (`headerBack` → `headerback`) หรือใส่ค่าผิดชนิด **ไม่มี type error แม้แต่ตัวเดียว**
 * ผลคือค่านิ่งเงียบ ๆ ไม่ทำงาน ซึ่งอ่านโค้ดดูก็ดูปกติ
 *
 * การ augment `RouteMeta` ของ vue-router ทำให้ `meta: { ... }` ใน `routes.ts`
 * ถูกตรวจชนิดเต็มรูปแบบ และเมื่อ P1 เริ่มใช้ `headerBack`/`headerHidden`
 * จะได้ autocomplete + ตรวจค่าโดยไม่ต้องประกาศซ้ำ
 *
 * ⚠️ `title` คือฟิลด์เดียวที่ **ถูกใช้งานแล้ว** (ตัวตั้ง `document.title` ใน
 *    `router/index.ts`) — ฟิลด์อื่นเป็นสัญญาที่ P1 จะเป็นผู้บริโภค
 *    (การประกาศล่วงหน้าตรงนี้ทำให้ไม่ต้องกลับมาไล่เติม meta ทุก route ทีหลัง)
 */

/**
 * แท็บหลักของแอปบนมือถือ — route ที่อยู่ใต้แท็บเดียวกันจะไฮไลต์แท็บนั้น
 * (เช่น `/students/:id` ยังไฮไลต์แท็บ "นักเรียน")
 */
export type NavTabKey = 'home' | 'students' | 'tasks' | 'finance' | 'more';

declare module 'vue-router' {
  interface RouteMeta {
    /** ต้องล็อกอินก่อนเข้าหรือไม่ */
    requiresAuth?: boolean;
    /** ชื่อหน้าที่จะแสดงบนแท็บเบราว์เซอร์ (ห้ามลงท้ายด้วยชื่อแอปเอง — ดู `pageTitle`) */
    title?: string;
    /** route นี้อยู่ในแท็บใดของแถบล่าง (ใช้ไฮไลต์แท็บ) */
    navTab?: NavTabKey;
    /** หน้านี้ควรมีปุ่มย้อนกลับใน header (P1: `AppHeader`) */
    headerBack?: boolean;
    /** ซ่อน header ทั้งแถบ — สำหรับหน้าฟอร์มเต็มจอ/กล้อง (P1) */
    headerHidden?: boolean;
    /** ซ่อนทั้ง header และแถบนำทาง — หน้าสแกน QR/กล้องเต็มจอ (P1) */
    fullscreen?: boolean;
  }
}

/** ชื่อแอปที่ใช้ต่อท้ายชื่อหน้าทุกหน้า */
export const APP_NAME = 'SYNCROOM';

/** ใช้เมื่อ route ไม่ได้ประกาศ `title` — และในหน้า 404 */
export const DEFAULT_TITLE = `${APP_NAME} | ระบบจัดการห้องเรียนออนไลน์`;

/**
 * ประกอบชื่อแท็บเบราว์เซอร์จาก `meta.title`
 *
 * รูปแบบ: `นักเรียน · SYNCROOM` — วางชื่อหน้าก่อนเพราะบนแท็บมีที่จำกัด
 * และผู้ใช้มีหลายแท็บเปิดพร้อมกันจึงต้องเห็นชื่อหน้าได้ทันที
 */
export function pageTitle(title: string | undefined): string {
  const trimmed = title?.trim();
  return trimmed ? `${trimmed} · ${APP_NAME}` : DEFAULT_TITLE;
}
