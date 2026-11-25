import { describe, expect, it } from 'vitest';

import { isSettled, outstandingOf } from '@/utils/outstanding';

/**
 * 📐 [FIN-V2 / P6.3] สูตร 3 พจน์ของหน้าจอ
 *
 * 🎯 ล็อก "ไม่ clamp" และ "ทศนิยมไม่ลอย" — สองจุดที่จออาจโชว์ยอดที่ backend ไม่เห็นด้วย
 */
describe('outstandingOf', () => {
  it('บิลยังไม่เคยตัด — amount - paid', () => {
    expect(outstandingOf({ amount: 1000, paid: 200 })).toBe(800);
  });

  it('หักยอดที่ตัดจำหน่ายด้วย', () => {
    expect(outstandingOf({ amount: 1000, paid: 200, writtenOff: 500 })).toBe(300);
  });

  it('ตัดครบจนเหลือ 0 → settled', () => {
    const value = outstandingOf({ amount: 1000, paid: 0, writtenOff: 1000 });
    expect(value).toBe(0);
    expect(isSettled(value)).toBe(true);
  });

  it('ตัดเกินยอด → ติดลบและไม่ clamp (ข้อมูลผิดต้องเห็น)', () => {
    const value = outstandingOf({ amount: 1000, paid: 200, writtenOff: 900 });
    expect(value).toBe(-100);
    expect(isSettled(value)).toBe(false);
  });

  it('ทศนิยม 0.1 + 0.2 ไม่หลุดเป็น -5.5e-17', () => {
    expect(outstandingOf({ amount: 0.3, paid: 0.1, writtenOff: 0.2 })).toBe(0);
  });

  it('ส่วนต่างระดับสตางค์ยังถือว่า settled', () => {
    expect(isSettled(0.004)).toBe(true);
    expect(isSettled(0.006)).toBe(false);
  });
});
