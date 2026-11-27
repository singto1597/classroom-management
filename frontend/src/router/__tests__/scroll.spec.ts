import { describe, it, expect, vi, afterEach } from 'vitest';
import { resetLayoutScroll, SCROLL_CONTAINER_SELECTOR } from '@/router/scroll';

/**
 * 🧭 ล็อกการแก้บั๊ก "ติ๊กแถวกลางลิสต์แล้วจอว่าง" (2026-11-27)
 *
 * ตัวเลื่อนจริงของแอปคือ `<main data-scroll-container>` ไม่ใช่ `window`
 * ⇒ scrollBehavior ต้องรีเซ็ต container เองแล้วคืน `false`
 *    (ถ้าคืน `{ top: 0 }` router จะไปเรียก `window.scrollTo` ซึ่งไม่ช่วยอะไร)
 */
afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('resetLayoutScroll', () => {
  it('รีเซ็ต scrollTop ของ container แล้วคืน false (router ห้ามแตะ window)', () => {
    const main = document.createElement('main');
    main.setAttribute('data-scroll-container', '');
    main.style.overflowY = 'auto';
    const spacer = document.createElement('div');
    spacer.style.height = '4000px';
    main.appendChild(spacer);
    document.body.appendChild(main);
    main.scrollTop = 640;

    const scrollTo = vi.spyOn(window, 'scrollTo');

    expect(resetLayoutScroll()).toBe(false);
    expect(main.scrollTop).toBe(0);
    expect(scrollTo).not.toHaveBeenCalled();
    expect(SCROLL_CONTAINER_SELECTOR).toBe('[data-scroll-container]');
  });

  it('ไม่มี container → คืน { top: 0 } ให้ router จัดการ window เอง', () => {
    expect(resetLayoutScroll()).toEqual({ top: 0 });
  });
});
