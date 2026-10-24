import { describe, it, expect } from 'vitest';
import { safeRedirect } from '@/router/redirect';
import { toLobbyFor, unavailableTarget, UNAVAILABLE_QUERY_KEY } from '@/router/unavailable';

/**
 * 🔐 ล็อกสัญญาของ `safeRedirect()` — ประตูกัน open redirect
 *
 * ทุกเคสใน describe แรกคือ URL ที่ **ผู้โจมตีควบคุมได้** ผ่าน `?next=` ถ้าใครแก้
 * ไฟล์ `redirect.ts` ให้ผ่อนลง เคสใดเคสหนึ่งจะแดงทันที (ด่านไม่ใช่คอมเมนต์)
 */
describe('safeRedirect — path ภายในที่ปลอดภัย', () => {
  it.each([
    '/students',
    '/dashboard',
    '/finance/debtors?tab=overdue',
    '/students/5#balance',
    '/activities/compare',
  ])('รับ %s', (value) => {
    expect(safeRedirect(value)).toBe(value);
  });

  it('ตัดช่องว่างหัวท้ายก่อนตรวจ', () => {
    expect(safeRedirect('  /students  ')).toBe('/students');
  });
});

describe('safeRedirect — URL ที่ต้องปฏิเสธ', () => {
  it.each([
    ['//evil.com', 'protocol-relative'],
    ['https://evil.com', 'absolute URL'],
    ['http://evil.com/students', 'absolute URL หลอกว่าเป็น path'],
    ['javascript:alert(1)', 'ไม่ได้เริ่มด้วย /'],
    ['data:text/html,<script>alert(1)</script>', 'ไม่ได้เริ่มด้วย /'],
    ['/\\evil.com', 'backslash — เบราว์เซอร์ตีความเป็น //'],
    ['/students\\..\\evil', 'backslash ที่กลาง path'],
    ['%2F%2Fevil.com', 'encode ของ //'],
    ['/%5Cevil.com', 'encode ของ backslash'],
    ['/100%', 'percent ไม่ครบ ⇒ decodeURIComponent โยน error'],
    // ใช้ String.fromCharCode เพื่อไม่ให้ตัวอักษรควบคุมไปโผล่ในซอร์ส
    ['/students' + String.fromCharCode(10) + 'evil', 'อักขระควบคุม LF กลาง path'],
    ['/login', 'วนกลับหน้า login'],
    ['/login?next=/dashboard', 'วนกลับหน้า login พร้อม query'],
    ['/onboarding', 'วนกลับหน้า onboarding'],
    ['/auth/google/callback', 'วนกลับ callback'],
  ])('ปฏิเสธ %s (%s)', (value) => {
    expect(safeRedirect(value)).toBeNull();
  });

  it('ปฏิเสธค่าที่ไม่ใช่ string', () => {
    for (const value of [null, undefined, 0, 42, {}, [], ['/students']]) {
      expect(safeRedirect(value)).toBeNull();
    }
  });

  it('ปฏิเสธสตริงว่าง', () => {
    expect(safeRedirect('')).toBeNull();
    expect(safeRedirect('   ')).toBeNull();
  });

  it('ปฏิเสธ path ที่ยาวผิดปกติ (> 2048)', () => {
    expect(safeRedirect('/students?' + 'a'.repeat(2100))).toBeNull();
  });

  it('ไม่ปฏิเสธ path ที่เพียง "มีคำว่า login" — ตรวจ prefix ไม่ใช่ substring', () => {
    expect(safeRedirect('/financelogin')).toBe('/financelogin');
  });
});

describe('toLobbyFor — พกปลายทางเดิมไปหน้าเลือกห้อง', () => {
  it('แนบ ?next= เมื่อปลายทางปลอดภัย', () => {
    expect(toLobbyFor('/finance/debtors?tab=overdue')).toEqual({
      name: 'lobby',
      query: { [UNAVAILABLE_QUERY_KEY]: '/finance/debtors?tab=overdue' },
    });
  });

  it('ปลายทางไม่ปลอดภัย ⇒ ไป lobby เฉย ๆ ไม่แนบอะไร', () => {
    expect(toLobbyFor('//evil.com')).toEqual({ name: 'lobby' });
    expect(toLobbyFor('https://evil.com')).toEqual({ name: 'lobby' });
  });
});

describe('unavailableTarget — อ่านปลายทางจาก query', () => {
  it('คืน path ที่ปลอดภัย', () => {
    expect(unavailableTarget({ next: '/students/5' })).toBe('/students/5');
  });

  it('query เป็น array ⇒ ใช้ค่าแรก', () => {
    expect(unavailableTarget({ next: ['/students/5', '/finance'] })).toBe('/students/5');
  });

  it('ไม่มี key ⇒ null', () => {
    expect(unavailableTarget({})).toBeNull();
  });

  it('ค่าอันตราย ⇒ null (ไม่ push ตรง ๆ)', () => {
    expect(unavailableTarget({ next: '//evil.com' })).toBeNull();
    expect(unavailableTarget({ next: 'https://evil.com' })).toBeNull();
  });

  it('ค่าเป็น null (vue-router ให้ null ได้) ⇒ null', () => {
    expect(unavailableTarget({ next: null })).toBeNull();
  });
});
