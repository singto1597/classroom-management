import { describe, expect, it } from 'vitest';
import {
  DEADLINE_SOON_DAYS,
  daysUntilDeadline,
  deadlineLabel,
  deadlineState,
} from '@/utils/activityDeadline';

const TODAY = '2026-11-01';

describe('utils/activityDeadline', () => {
  it('ไม่มีวันปิดรับ ⇒ none ไม่ใช่ closed', () => {
    expect(deadlineState(null, TODAY)).toBe('none');
    expect(deadlineState(undefined, TODAY)).toBe('none');
    expect(deadlineState('', TODAY)).toBe('none');
  });

  it('รูปแบบวันที่เสีย ⇒ none (ไม่ทำให้การ์ดขึ้นป้ายผิด)', () => {
    expect(deadlineState('01/11/2026', TODAY)).toBe('none');
    expect(daysUntilDeadline('not-a-date', TODAY)).toBeNull();
  });

  it('วันนี้และในอนาคต ⇒ closed / soon / open ตามจำนวนวัน', () => {
    expect(deadlineState('2026-10-31', TODAY)).toBe('closed');
    expect(deadlineState('2026-11-01', TODAY)).toBe('soon');
    expect(deadlineState('2026-11-08', TODAY)).toBe('soon');
    expect(deadlineState('2026-11-09', TODAY)).toBe('open');
  });

  it(`ขอบเขต ${DEADLINE_SOON_DAYS} วันต้องนับรวมวันนั้น`, () => {
    expect(DEADLINE_SOON_DAYS).toBe(7);
    expect(daysUntilDeadline('2026-11-08', TODAY)).toBe(7);
    expect(daysUntilDeadline('2026-10-31', TODAY)).toBe(-1);
  });

  it('ป้ายข้อความ: ปิดรับแล้ว / ปิดรับวันนี้ / เหลือ N วัน / ไม่แสดง', () => {
    expect(deadlineLabel('2026-10-30', TODAY)).toBe('ปิดรับแล้ว');
    expect(deadlineLabel('2026-11-01', TODAY)).toBe('ปิดรับวันนี้');
    expect(deadlineLabel('2026-11-05', TODAY)).toBe('เหลือ 4 วัน');
    expect(deadlineLabel('2026-12-01', TODAY)).toBeNull();
    expect(deadlineLabel(null, TODAY)).toBeNull();
  });

  it('ข้ามเดือน/ข้ามปีคำนวณถูก (บวก-ลบข้ามเขต DST ได้เพราะใช้ UTC)', () => {
    expect(daysUntilDeadline('2027-01-01', '2026-12-30')).toBe(2);
    expect(daysUntilDeadline('2026-03-01', '2026-02-28')).toBe(1);
  });
});
