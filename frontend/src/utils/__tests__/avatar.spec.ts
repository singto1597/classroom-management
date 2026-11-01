import { describe, it, expect } from 'vitest';
import { avatarInitial } from '@/utils/avatar';

/**
 * 🔒 ล็อกกฎอักษรย่อไทย — สระนำต้องไม่ถูกเลือกเป็นตัวย่อ
 * (เดิม `charAt(0)` ทำให้ "เก่ง" → "เ", "โอม" → "โ", "ใหม่" → "ไ")
 */

describe('avatarInitial — ไทย', () => {
  it.each([
    ['เก่ง', 'ก'],
    ['โอม', 'อ'],
    ['ใหม่', 'ห'],
    ['แอน', 'อ'],
    ['ใจ', 'จ'],
    ['น้ำ', 'น'],
    ['ญาณี', 'ญ'],
  ])('%s → %s', (name, expected) => {
    expect(avatarInitial(name)).toBe(expected);
  });
});

describe('avatarInitial — อังกฤษ', () => {
  it('ใช้ตัวแรกและทำเป็นพิมพ์ใหญ่', () => {
    expect(avatarInitial('aomsin')).toBe('A');
    expect(avatarInitial('Somchai')).toBe('S');
  });
});

describe('avatarInitial — ค่าว่าง', () => {
  it('ใช้ fallback ที่กำหนด', () => {
    expect(avatarInitial('')).toBe('?');
    expect(avatarInitial('   ')).toBe('?');
    expect(avatarInitial(null, 'ส')).toBe('ส');
    expect(avatarInitial(undefined, 'ส')).toBe('ส');
  });
});
