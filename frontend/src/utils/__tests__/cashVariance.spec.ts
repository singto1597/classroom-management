import { describe, expect, it } from 'vitest';
import {
  canFinalize,
  computeVariance,
  normalizeCashInput,
  varianceMessage,
} from '@/utils/cashVariance';

/**
 * 💵 [FIN-V2 / P5.5] ล็อกสัญญาของผลต่างเงินสด
 *
 * 🔴 เคสที่สำคัญที่สุดคือทศนิยม: ถ้าคำนวณด้วย float ("12244.99" − 12345) อาจได้
 *    -0.010000000000000675 แล้วปุ่ม finalize ที่เทียบ `=== 0` จะทำงานผิด
 *    ⇒ ทุกเคสด้านล่างต้องได้ค่าที่เทียบแบบ `toBe` ได้ตรง ๆ
 */
describe('utils/cashVariance', () => {
  it('นับได้ตรงกับบัญชี → ผลต่าง 0 และปิดงบได้', () => {
    const variance = computeVariance('12345.00', 12345);
    expect(variance).toBe(0);
    expect(canFinalize(variance)).toBe(true);
  });

  it('นับได้เกินครึ่งบาท → ผลต่าง 0.5 แต่ปิดงบไม่ได้', () => {
    const variance = computeVariance('12345.50', 12345);
    expect(variance).toBe(0.5);
    expect(canFinalize(variance)).toBe(false);
  });

  // ⚠️ brief P5.5 เขียน '12244.99' แต่ 12345 − 12244.99 = 100.01 บาท (พิมพ์เลขผิด)
  //    เจตนาคือ "ขาด 1 สตางค์" ⇒ ใช้ 12344.99 ซึ่งได้ -0.01 ตามที่เอกสารอธิบายไว้
  it('นับได้ขาด 1 สตางค์ → -0.01 ไม่เพี้ยนจาก floating point', () => {
    const variance = computeVariance('12344.99', 12345);
    expect(variance).toBe(-0.01);
    expect(canFinalize(variance)).toBe(false);
  });

  it('ยังไม่กรอกยอดนับได้ → ผลต่าง null (แยกจาก "นับได้ 0")', () => {
    expect(computeVariance('', 12345)).toBeNull();
    expect(canFinalize(null)).toBe(false);
    expect(computeVariance('0', 0)).toBe(0);
    expect(canFinalize(computeVariance('0', 0))).toBe(true);
  });

  it('normalizeCashInput ตัด comma และทศนิยมเกิน 2 ตำแหน่ง', () => {
    expect(normalizeCashInput('1,234.567')).toBe('1234.56');
    expect(normalizeCashInput(' 12,000 ')).toBe('12000');
    expect(normalizeCashInput('0.5')).toBe('0.5');
  });

  it('normalizeCashInput ไม่รับค่าที่ไม่ใช่ตัวเลข', () => {
    expect(normalizeCashInput('abc')).toBe('');
    expect(normalizeCashInput('')).toBe('');
  });

  it('normalizeCashInput ไม่รับค่าติดลบ', () => {
    expect(normalizeCashInput('-5')).toBe('');
    expect(normalizeCashInput('-0.01')).toBe('');
  });

  it('varianceMessage แสดงสามตัวเลขเป็นภาษาไทย', () => {
    const message = varianceMessage('12344.99', 12345);
    expect(message).toContain('นับได้');
    expect(message).toContain('12,344.99');
    expect(message).toContain('ควรเป็น');
    expect(message).toContain('12,345.00');
    expect(message).toContain('ต่าง');
    expect(message).toContain('0.01');
  });
});
