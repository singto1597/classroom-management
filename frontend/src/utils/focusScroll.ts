/**
 * 🖱️ กันรายการกระโดดเมื่อคลิก checkbox ที่ซ่อนด้วย `sr-only`
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * อาการ
 * ═══════════════════════════════════════════════════════════════════════════
 * คลิก checkbox กลางลิสต์ยาว (ทะเบียนเอกสาร) → `<main>` เลื่อนลงเองหลายสิบ px
 * ต่อการคลิกหนึ่งครั้ง · คลิกซ้ำ ๆ ต่อเนื่องจะไหลไปจนสุดลิสต์ ("ทะลุจอลงไปเลย")
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * สาเหตุ
 * ═══════════════════════════════════════════════════════════════════════════
 * `<input type="checkbox" class="sr-only">` ถูกคลิปเหลือกล่อง 1×1 px ที่ตำแหน่ง
 * ต่างจากจุดที่ผู้ใช้เห็น · เมื่อ label forward การคลิกให้ input เบราว์เซอร์จะ
 * **focus** input แล้วเลื่อน scroll container ให้กล่อง 1×1 นั้น "เห็น" —
 * เป็นการเลื่อนที่เกิดจากเบราว์เซอร์ ไม่ใช่โค้ดแอป (จึงหา `scrollIntoView` ไม่เจอ)
 * · `@mousedown.prevent` / `tabindex="-1"` / `pointer-events:none` ไม่หยุดพฤติกรรมนี้
 *   (ทดสอบบน Chromium จริงแล้วทั้งสามแบบยังเลื่อน)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * วิธีแก้
 * ═══════════════════════════════════════════════════════════════════════════
 * จำ `scrollTop` ณ ขณะ focus แล้วคืนค่าในเฟรมถัดไป (เบราว์เซอร์เลื่อนหลัง event
 * focus จึงต้องคืนใน `requestAnimationFrame`)
 * • ทำงานเฉพาะ focus ที่ตามหลัง `pointerdown` ≤ 700 ms
 *   ⇒ การกด Tab (คีย์บอร์ด) ยังได้รับการเลื่อนให้เห็นตามปกติ (a11y)
 * • ตัวเลื่อนคือ `[data-scroll-container]` (ดู router/scroll.ts) ไม่ใช่ window
 */
import { SCROLL_CONTAINER_SELECTOR } from '@/router/scroll';

/** หน้าต่างเวลาที่ถือว่า focus มาจากการคลิก (ms) — คลิกแล้ว focus เกิดทันที */
const POINTER_FOCUS_WINDOW_MS = 700;

export function guardCheckboxPointerFocus(): () => void {
  if (typeof document === 'undefined') return () => {};

  let lastPointerDownAt = 0;

  const onPointerDown = () => {
    lastPointerDownAt = Date.now();
  };

  const onFocusIn = (event: FocusEvent) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement) || target.type !== 'checkbox') return;
    if (Date.now() - lastPointerDownAt > POINTER_FOCUS_WINDOW_MS) return;

    const container = document.querySelector<HTMLElement>(SCROLL_CONTAINER_SELECTOR);
    if (!container) return;
    const top = container.scrollTop;
    // ⚠️ ต้องคืนในเฟรมถัดไป — ถ้าคืนทันทีใน event handler เบราว์เซอร์จะเลื่อนทับ
    requestAnimationFrame(() => {
      container.scrollTop = top;
    });
  };

  document.addEventListener('pointerdown', onPointerDown, true);
  document.addEventListener('focusin', onFocusIn, true);

  return () => {
    document.removeEventListener('pointerdown', onPointerDown, true);
    document.removeEventListener('focusin', onFocusIn, true);
  };
}
