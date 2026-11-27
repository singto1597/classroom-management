/**
 * 🧭 รีเซ็ตตำแหน่ง scroll เมื่อเปลี่ยนหน้า
 *
 * 🔴 แอปนี้ **ไม่ได้ scroll ที่ `window`** — ตัวเลื่อนคือ `<main data-scroll-container>`
 * ของ `MainLayout` / `GlobalLayout` (`overflow-y-auto`)
 * ⇒ `scrollBehavior` ที่คืน `{ top: 0 }` ให้ vue-router ไปเรียก `window.scrollTo`
 *    ซึ่งเป็น **no-op** · `<main>` จึงคง `scrollTop` เดิมไว้
 * ⇒ จากลิสต์ยาวเปิดเอกสารสั้น หน้าจอค้างล่างสุด = **ดูเหมือนหน้าขาว**
 *    (บั๊ก "ติ๊กแถวกลางลิสต์แล้วจอว่าง" 2026-11-27)
 *
 * ⚠️ ห้ามคืน `{ el }` / `{ top }` จาก scrollBehavior เพราะ vue-router 5
 *    ลงเอยที่ `window.scrollTo` อยู่ดี — ต้องรีเซ็ต container เองแล้วคืน `false`
 *    (ค่า `false` = ไม่ให้ router ทำอะไรเพิ่ม)
 */
export const SCROLL_CONTAINER_SELECTOR = '[data-scroll-container]';

export interface SavedScrollPosition {
  left?: number;
  top?: number;
}

export function resetLayoutScroll(
  savedPosition?: SavedScrollPosition | null,
): false | SavedScrollPosition {
  const el = document.querySelector<HTMLElement>(SCROLL_CONTAINER_SELECTOR);
  // ไม่มี container (เช่นหน้า fullscreen ที่ไม่ได้อยู่ใน layout) — ปล่อยให้ router
  // รีเซ็ต window ตามปกติ
  if (!el) return savedPosition ?? { top: 0 };

  const apply = () => {
    el.scrollTop = savedPosition?.top ?? 0;
    el.scrollLeft = savedPosition?.left ?? 0;
  };

  if (savedPosition) {
    // กดย้อนกลับ — รอ component ใหม่ render ก่อน เพราะความสูงหน้าเปลี่ยน
    requestAnimationFrame(apply);
  } else {
    apply();
  }
  return false;
}
