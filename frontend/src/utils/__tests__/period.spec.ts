import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  todayIso,
  todayThaiYearMonth,
  referenceDate,
  formatThaiDate,
  formatThaiDateTime,
} from '@/utils/period';

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

/**
 * 🔒 เทสต์ชุดนี้ล็อกความต่างระหว่าง `formatThaiDate` (วันที่ล้วน) กับ `formatThaiDateTime` (เวลาจริง)
 *
 * ⚠️ **ห้ามยุบสองตัวนี้เข้าด้วยกัน** — มันไม่ใช่ของซ้ำ
 *   `formatThaiDate` อ่านวันที่จาก 10 ตัวอักษรแรกของสตริง ISO = **วันที่แบบ UTC**
 *   ⇒ ใบเสร็จที่ออก 18:30 UTC (01:30 ของวันรุ่งขึ้นในไทย) จะถูกแสดงเป็น "วันที่ 13"
 *     ขณะที่ backend กรองด้วย **วันไทย** ⇒ เอกสารโผล่ในวันที่ 14 แต่จอเขียนว่า 13
 *     และไม่ตรงกับวันที่พิมพ์อยู่บนกระดาษ
 *
 * เทสต์นี้จับคู่ "วันไทยที่ถูกต้อง" ด้วยเส้นทางอิสระ (`en-CA` + timeZone ไทย อ่านเป็นตัวเลข)
 * แทนการฮาร์ดโค้ดสตริงของ locale th-TH — กันเทสต์เปราะกับเวอร์ชัน ICU
 */

/** ตัวช่วยอิสระ: วันตามปฏิทินไทยของ instant นี้ เป็น `YYYY-MM-DD` */
const thaiCalendarDay = (iso: string): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' }).format(new Date(iso));

/** 2026-09-13 18:30 UTC = 2026-09-14 01:30 เวลาไทย (ข้ามวันไทยแล้ว แต่ UTC ยังเป็นวันที่ 13) */
const CROSSES_THAI_DAY = '2026-09-13T18:30:00Z';

describe('formatThaiDateTime', () => {
  // เคสตั้งต้นของบั๊กทั้งตัว — วันที่ไทยกับวันที่ UTC ไม่ตรงกัน
  it('timestamp ตอนค่ำ UTC → ต้องเป็น "วันรุ่งขึ้น" ตามปฏิทินไทย ไม่ใช่วันที่ของ UTC', () => {
    expect(thaiCalendarDay(CROSSES_THAI_DAY)).toBe('2026-09-14');

    const shown = formatThaiDateTime(CROSSES_THAI_DAY);

    // วันที่ที่แสดงตรงกับวันไทยจริง และเป็น พ.ศ. 2569 (th-TH ใช้พุทธศักราชอัตโนมัติ)
    expect(shown).toContain('14');
    expect(shown).toContain('ก.ย.');
    expect(shown).toContain('2569');
    // เวลาไทย 01:30 ไม่ใช่ 18:30 UTC
    expect(shown).toContain('01:30');
    expect(shown).not.toContain('18:30');

    // 🔑 พิสูจน์ว่าสองตัวไม่ interchangeable — นี่คือเหตุผลที่ต้องมีเทสต์นี้
    expect(shown).not.toBe(formatThaiDate(CROSSES_THAI_DAY));
    expect(formatThaiDate(CROSSES_THAI_DAY)).toContain('13');
  });

  it('timestamp กลางวัน UTC ที่ยังเป็นวันไทยวันเดียวกัน → วันที่ตรงกัน แต่เวลาต่าง', () => {
    const iso = '2026-09-13T12:41:46.661768Z'; // รูปที่ Pydantic v2 ส่งจริง (ลงท้าย Z)
    expect(thaiCalendarDay(iso)).toBe('2026-09-13');

    const shown = formatThaiDateTime(iso);
    expect(shown).toContain('13');
    expect(shown).toContain('19:41'); // 12:41 UTC + 7
  });

  it('timestamp ที่ตกเลขข้ามปีไทย → วันที่และปีต้องเป็นของปีใหม่', () => {
    const iso = '2026-12-31T18:00:00Z'; // = 2027-01-01 01:00 ไทย
    expect(thaiCalendarDay(iso)).toBe('2027-01-01');

    const shown = formatThaiDateTime(iso);
    expect(shown).toContain('2570'); // 2027 + 543
    expect(shown).toContain('01:00');
  });

  it('ลงท้ายด้วย " น." เสมอ เพื่อให้อ่านออกว่าเป็นเวลานาฬิกา', () => {
    expect(formatThaiDateTime('2026-09-13T12:41:46Z').endsWith(' น.')).toBe(true);
  });

  it('ไม่มีค่า / ค่าว่าง → ขีดกลาง (ไม่ใช่ "Invalid Date")', () => {
    expect(formatThaiDateTime(null)).toBe('—');
    expect(formatThaiDateTime(undefined)).toBe('—');
    expect(formatThaiDateTime('')).toBe('—');
  });

  it('สตริงที่ parse ไม่ได้ → คืนค่าเดิมกลับไป ไม่กลืนเป็น "Invalid Date"', () => {
    expect(formatThaiDateTime('ไม่ใช่วันที่')).toBe('ไม่ใช่วันที่');
  });

  /**
   * ⚠️ กับดักที่ต้องรู้: ส่ง **วันที่ล้วน** เข้ามาจะได้เวลา 07:00 ติดมาด้วย
   *    เพราะ `new Date('2026-09-13')` ตีความเป็นเที่ยงคืน UTC = 07:00 ไทย
   *    ⇒ ฟิลด์ที่เป็น DATE จริง (เช่น `collection_due_date`) **ต้องใช้ `formatThaiDate`**
   *      เทสต์นี้ไม่ได้บอกว่าพฤติกรรมนี้ "ดี" — มันล็อกไว้ว่ารู้ตัวและเลือกแล้ว
   */
  it('วันที่ล้วน → ได้ 07:00 ไทยติดมา (จึงต้องใช้ formatThaiDate กับฟิลด์ DATE)', () => {
    expect(formatThaiDateTime('2026-09-13')).toContain('07:00');
    expect(formatThaiDate('2026-09-13')).not.toContain('07:00');
  });
});
