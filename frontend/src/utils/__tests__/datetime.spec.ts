import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  bangkokHour,
  daysFromThaiToday,
  formatThaiDate,
  formatThaiDateTime,
  formatThaiDateTimeParts,
  formatThaiTime,
  relativeThaiDay,
  todayIso,
} from '@/utils/datetime';

/**
 * 🔒 ล็อกพฤติกรรม "วันที่ไทย" ของ utils/datetime
 *
 * เน้นเคสที่อุปกรณ์ผู้ใช้ตั้ง TZ ไม่ใช่ไทย — ค่าที่แสดงต้องอิง Asia/Bangkok เสมอ
 * และ date-only ต้องไม่ถูก UTC ดันข้ามวัน
 */

afterEach(() => {
  vi.useRealTimers();
});

describe('formatThaiDate (date-only)', () => {
  it('แสดงปี พ.ศ. และไม่ถูก UTC ดันข้ามวัน', () => {
    expect(formatThaiDate('2026-10-01')).toBe('1 ต.ค. 2569');
  });

  it('เลือกเดือนแบบเต็มได้', () => {
    expect(formatThaiDate('2026-10-01', 'long')).toBe('1 ตุลาคม 2569');
  });

  it('ค่าว่าง/รูปแบบผิด คืนค่าเดิมหรือ dash ไม่ throw', () => {
    expect(formatThaiDate(null)).toBe('—');
    expect(formatThaiDate('ไม่ใช่วันที่')).toBe('ไม่ใช่วันที่');
  });
});

describe('formatThaiDateTime (timestamp)', () => {
  it('จุดเวลา UTC ที่ข้ามวันไทย ต้องแสดงวันที่ไทยถัดไป', () => {
    // 2026-09-30 18:00 UTC = 2026-10-01 01:00 เวลาไทย
    expect(formatThaiDateTime('2026-09-30T18:00:00Z')).toBe('1 ต.ค. 2569 01:00 น.');
  });

  it('แยกส่วนวันที่/เวลาได้ตรงกัน (ใช้ในตาราง)', () => {
    expect(formatThaiDateTimeParts('2026-09-30T18:00:00Z')).toEqual({
      date: '1 ต.ค. 2569',
      time: '01:00',
    });
  });

  it('ค่าที่ parse ไม่ได้คืนค่าเดิม ไม่สร้างวันที่ปลอม', () => {
    expect(formatThaiDateTime('not-a-date')).toBe('not-a-date');
  });
});

describe('formatThaiTime', () => {
  it('ใช้โซนไทยเสมอ', () => {
    expect(formatThaiTime('2026-09-30T18:00:00Z')).toBe('01:00');
  });
});

describe('bangkokHour', () => {
  it('คำนวณชั่วโมงจาก Asia/Bangkok ไม่ใช่โซนอุปกรณ์', () => {
    vi.useFakeTimers();
    // 18:00 UTC = 01:00 ไทย
    vi.setSystemTime(new Date('2026-09-30T18:00:00Z'));
    expect(bangkokHour()).toBe(1);
  });
});

describe('daysFromThaiToday / relativeThaiDay', () => {
  it('เทียบกับวันนี้ตามเวลาไทย (ตอน UTC ยังเป็นเมื่อวาน)', () => {
    vi.useFakeTimers();
    // 2026-10-31 18:00 UTC = 2026-11-01 01:00 ไทย
    vi.setSystemTime(new Date('2026-10-31T18:00:00Z'));

    expect(todayIso()).toBe('2026-11-01');
    expect(daysFromThaiToday('2026-11-01')).toBe(0);
    expect(daysFromThaiToday('2026-11-02')).toBe(1);
    expect(daysFromThaiToday('2026-10-31')).toBe(-1);
    expect(relativeThaiDay('2026-11-01')).toBe('วันนี้');
    expect(relativeThaiDay('2026-11-02')).toBe('พรุ่งนี้');
    expect(relativeThaiDay('2026-11-05')).toBeNull();
  });

  it('รูปแบบผิดคืน null', () => {
    expect(daysFromThaiToday('31/10/2026')).toBeNull();
  });
});
