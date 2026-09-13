import { describe, it, expect, vi, afterEach } from 'vitest';
import { todayIso, todayThaiYearMonth, referenceDate } from '@/utils/period';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "ปฏิทินไทย" ของค่าเริ่มต้นตัวกรองเดือน
 *
 * บั๊กที่มันจับ (พบโดย adversarial review 2026-09-13): `FinanceDashboard.vue` เดิม seed
 * `selectedMonth`/`selectedYear` จาก `new Date().getMonth()` ซึ่งเป็นปฏิทินของ **อุปกรณ์ผู้ใช้**
 * ⇒ เครื่องที่ TZ ไม่ใช่ UTC+7 เปิดหน้ามาผิดเดือน แล้วติดป้ายเดือนไทยทับตัวเลขของอีกเดือน
 *
 * ⚠️ ห้ามลบเทสต์นี้แล้วกลับไปใช้ `new Date()` — ดูคอมเมนต์ใน `utils/period.todayThaiYearMonth`
 *
 * เลือก instant ที่ "วันที่ไทย" ไม่ตรงกับ "วันที่ UTC" เพื่อให้เทสต์แยกสองพฤติกรรมออกจากกันได้
 * โดยไม่ต้องพึ่ง TZ ของ process ที่รันเทสต์ (Intl ระบุ timeZone ไว้ตายตัวอยู่แล้ว)
 */

/** 2026-09-30 18:00 UTC = 2026-10-01 01:00 เวลาไทย (ข้ามเดือนไทยแล้ว แต่ UTC ยังเป็น ก.ย.) */
const CROSSES_THAI_MONTH = '2026-09-30T18:00:00Z';

/** 2026-12-31 18:00 UTC = 2027-01-01 01:00 เวลาไทย (ข้ามปีไทยแล้ว) */
const CROSSES_THAI_YEAR = '2026-12-31T18:00:00Z';

afterEach(() => {
  vi.useRealTimers();
});

describe('todayThaiYearMonth', () => {
  it('ต้องตรงกับ todayIso() เสมอ (แหล่งความจริงเดียว — ห้ามคำนวณซ้ำเอง)', () => {
    const iso = todayIso();
    expect(todayThaiYearMonth()).toEqual({
      year: Number(iso.slice(0, 4)),
      month: Number(iso.slice(5, 7)),
    });
  });

  it('ตอนไทยข้ามเดือนแล้ว ต้องได้เดือนใหม่ แม้ UTC ยังเป็นเดือนเดิม', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(CROSSES_THAI_MONTH));

    expect(todayThaiYearMonth()).toEqual({ year: 2026, month: 10 });

    // ยืนยันว่าเทสต์นี้ "แยกได้จริง" — ปฏิทิน UTC (สิ่งที่ `new Date().getMonth()` ให้) ยังเป็นกันยา
    expect(new Date().getUTCMonth() + 1).toBe(9);

    vi.useRealTimers();
  });

  it('ตอนไทยข้ามปีแล้ว ต้องได้ปีใหม่', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(CROSSES_THAI_YEAR));

    expect(todayThaiYearMonth()).toEqual({ year: 2027, month: 1 });
    expect(new Date().getUTCFullYear()).toBe(2026);

    vi.useRealTimers();
  });
});

describe('referenceDate', () => {
  it('โหมด month → คืนค่าที่ผู้ใช้ตั้งไว้ตรง ๆ (ไม่ยุ่งกับนาฬิกา)', () => {
    expect(referenceDate({ mode: 'month', year: 2025, month: 3 })).toEqual({ year: 2025, month: 3 });
  });

  it('ISO เพี้ยน → ถอยไปใช้เดือนไทย ไม่ใช่เดือนของอุปกรณ์', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(CROSSES_THAI_MONTH));

    expect(referenceDate({ mode: 'asof', asOfDate: 'ไม่ใช่วันที่' })).toEqual({ year: 2026, month: 10 });

    vi.useRealTimers();
  });
});
