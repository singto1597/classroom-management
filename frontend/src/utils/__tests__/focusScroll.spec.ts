import { afterEach, describe, expect, it } from 'vitest';
import { guardCheckboxPointerFocus } from '@/utils/focusScroll';

/**
 * 🖱️ กันลิสต์กระโดดเมื่อคลิก checkbox `sr-only` (2026-11-27)
 *
 * เบราว์เซอร์ focus input 1×1 แล้ว **เลื่อน scroll container เอง** หลัง focus event
 * ⇒ guard ต้องคืน `scrollTop` ในเฟรมถัดไป เฉพาะ focus ที่มาจาก pointer
 * (กด Tab ต้องปล่อยให้เลื่อนตามปกติ)
 */
afterEach(() => {
  document.body.innerHTML = '';
});

const nextFrame = () =>
  new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

const setup = () => {
  const main = document.createElement('main');
  main.setAttribute('data-scroll-container', '');
  const input = document.createElement('input');
  input.type = 'checkbox';
  main.appendChild(input);
  document.body.appendChild(main);
  main.scrollTop = 640;
  return { main, input };
};

const pointerDown = () =>
  document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));

const focusInput = (input: HTMLInputElement) =>
  input.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));

describe('guardCheckboxPointerFocus', () => {
  it('คืน scrollTop หลัง focus จากคลิก (เบราว์เซอร์เลื่อนทับหลัง event)', async () => {
    const { main, input } = setup();
    const release = guardCheckboxPointerFocus();

    pointerDown();
    focusInput(input);
    main.scrollTop = 718; // เบราว์เซอร์เลื่อนเองหลัง focus
    await nextFrame();

    expect(main.scrollTop).toBe(640);
    release();
  });

  it('focus จากคีย์บอร์ด (ไม่มี pointerdown) ไม่ถูกย้อน — ปล่อยให้เลื่อนให้เห็น', async () => {
    const { main, input } = setup();
    const release = guardCheckboxPointerFocus();

    focusInput(input);
    main.scrollTop = 718;
    await nextFrame();

    expect(main.scrollTop).toBe(718);
    release();
  });

  it('release แล้วไม่ยุ่งกับ scroll อีก', async () => {
    const { main, input } = setup();
    const release = guardCheckboxPointerFocus();
    release();

    pointerDown();
    focusInput(input);
    main.scrollTop = 718;
    await nextFrame();

    expect(main.scrollTop).toBe(718);
  });
});
