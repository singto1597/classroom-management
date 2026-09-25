/**
 * ช่วงเวลา (period) — แปลง "สิ่งที่ผู้ใช้เลือก" ให้เป็นพารามิเตอร์ที่ backend ยอมรับ
 *
 * ⚠️ backend มี period convention อยู่ **3 แบบเท่านั้น ห้ามคิดแบบที่สี่**:
 *   1. `month` + `year`           → GET /finance/summary (ต้องส่งคู่กันหรือไม่ส่งเลย)
 *   2. `start_date` + `end_date`  → GET /finance/income-statement (บังคับส่งครบคู่)
 *   3. `as_of_date`               → GET /finance/trial-balance, /finance/balance-sheet
 *   `/finance/export/journal` รับได้ทั้งแบบ 1 และ 2 แต่ **ห้ามผสมกัน**
 *
 * ไฟล์นี้ไม่เพิ่มรูปแบบใหม่ — มันแค่แปลงโหมดที่ผู้ใช้เลือกให้เป็นหนึ่งในสามแบบนั้น
 * และกันไม่ให้เกิดรูปที่สี่ขึ้นมาในโค้ดด้วย type (ดู RangeCapablePeriod / AsOfCapablePeriod)
 */

export const BANGKOK_TZ = 'Asia/Bangkok';

export const THAI_MONTHS = [
  'มกราคม',
  'กุมภาพันธ์',
  'มีนาคม',
  'เมษายน',
  'พฤษภาคม',
  'มิถุนายน',
  'กรกฎาคม',
  'สิงหาคม',
  'กันยายน',
  'ตุลาคม',
  'พฤศจิกายน',
  'ธันวาคม',
] as const;

export type PeriodMode = 'month' | 'range' | 'asof';

/**
 * ค่าที่ PeriodPicker เปล่งออกไป — discriminated union เพื่อให้ **เป็นไปไม่ได้**
 * ที่จะมี month ปนกับ startDate (backend จะ 400 ถ้าส่งผสม)
 */
export type PeriodValue =
  | { mode: 'month'; month: number; year: number }
  | { mode: 'range'; startDate: string; endDate: string }
  | { mode: 'asof'; asOfDate: string };

/** โหมดที่แปลงเป็น start/end ได้ — `asof` หลุดออกเพราะ "1 วัน" ไม่ใช่ช่วง (ห้ามเดา) */
export type RangeCapablePeriod = Extract<PeriodValue, { mode: 'month' | 'range' }>;

/** โหมดที่แปลงเป็น as_of ได้ — `range` ใช้ endDate (ยอด ณ วันสิ้นสุดของช่วง) */
export type AsOfCapablePeriod = Extract<PeriodValue, { mode: 'month' | 'asof' }>;

const pad2 = (n: number): string => String(n).padStart(2, '0');

/** แยก YYYY-MM-DD เป็นตัวเลขโดยไม่ผ่าน Date เพื่อไม่ให้ timezone ดันวันที่ข้ามวัน */
const parseIso = (iso: string): { y: number; m: number; d: number } | null => {
  const parts = iso.slice(0, 10).split('-').map(Number);
  const [y, m, d] = parts;
  if (!y || !m || !d || parts.length !== 3) return null;
  return { y, m, d };
};

/** วันที่วันนี้ตามเวลาไทย (YYYY-MM-DD) — 'en-CA' ให้รูป ISO ตรง ๆ */
export const todayIso = (): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: BANGKOK_TZ }).format(new Date());

/**
 * ปี/เดือนของ "วันนี้" ตามเวลาไทย — **ที่เดียว** ที่อนุญาตให้ตอบว่า "ตอนนี้เดือนอะไร"
 *
 * ⚠️ ห้ามใช้ `new Date().getMonth()` / `.getFullYear()` เป็นค่าเริ่มต้นของตัวกรองเดือน
 * เพราะนั่นคือปฏิทินของ **อุปกรณ์ผู้ใช้** ไม่ใช่ของไทย ⇒ เครื่องที่ TZ ไม่ใช่ UTC+7
 * จะเปิดหน้ามาผิดเดือน แล้วติดป้ายเดือนไทยทับตัวเลขของอีกเดือน (เครื่องที่นำหน้าไทย
 * จะเพี้ยนช่วง 2 ชม. สุดท้ายของเดือน, เครื่องที่ตามหลังจะเพี้ยนช่วงต้นวันที่ 1)
 *
 * อ่านผ่าน `todayIso()` (ไม่ประกอบ Date เอง) เพื่อให้มีแหล่งความจริงเดียวและไม่ต้องพึ่ง
 * `noUncheckedIndexedAccess` ตอนแยกชิ้นส่วน
 */
export const todayThaiYearMonth = (): { year: number; month: number } => {
  const iso = todayIso();
  return { year: Number(iso.slice(0, 4)), month: Number(iso.slice(5, 7)) };
};

export const firstDayOfMonth = (year: number, month: number): string =>
  `${year}-${pad2(month)}-01`;

/** วันสุดท้ายของเดือน — `new Date(y, m, 0)` = วันสุดท้ายของเดือนที่ m (m เป็น 1-based) */
export const lastDayOfMonth = (year: number, month: number): string =>
  `${year}-${pad2(month)}-${pad2(new Date(year, month, 0).getDate())}`;

/** เดือน → ช่วงวันที่เต็มเดือน (convention 2) */
export const monthToRange = (
  year: number,
  month: number,
): { startDate: string; endDate: string } => ({
  startDate: firstDayOfMonth(year, month),
  endDate: lastDayOfMonth(year, month),
});

/** → `start_date` + `end_date` สำหรับงบกำไรขาดทุน */
export const toRange = (p: RangeCapablePeriod): { startDate: string; endDate: string } =>
  p.mode === 'month' ? monthToRange(p.year, p.month) : { startDate: p.startDate, endDate: p.endDate };

/** → `as_of_date` สำหรับงบทดลอง/งบดุล (endDate ของช่วงคือ "ณ วันนั้น") */
export const toAsOf = (p: AsOfCapablePeriod): string =>
  p.mode === 'month' ? lastDayOfMonth(p.year, p.month) : p.asOfDate;

/** วันที่แบบไทย (พ.ศ. อัตโนมัติจาก locale th-TH) */
export const formatThaiDate = (iso?: string | null): string => {
  if (!iso) return '—';
  const parsed = parseIso(iso);
  if (!parsed) return iso;
  // ประกอบ Date จากชิ้นส่วน local ตรง ๆ — ถ้าปล่อยให้ parse ISO จะกลายเป็น UTC แล้ว +07:00 อาจดันข้ามวัน
  return new Date(parsed.y, parsed.m - 1, parsed.d).toLocaleDateString('th-TH', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
};

/**
 * วัน **และเวลา** แบบไทย — ใช้กับ timestamp จริง (เช่น `issued_at` ของใบเสร็จ)
 *
 * ⚠️ ห้ามใช้ `formatThaiDate` กับ timestamp: มันตัดเอาแค่ส่วนวันที่ของสตริง ISO
 *    ซึ่งเป็น **วันที่แบบ UTC** — ใบเสร็จที่ออก 18:30 UTC คือ 01:30 ของ **วันรุ่งขึ้น** ในไทย
 *    แล้วผู้ใช้จะเห็นวันที่ไม่ตรงกับวันที่บนเอกสาร และไม่ตรงกับตัวกรองช่วงวันที่ของตัวเอง
 *    (backend กรองด้วยวันไทย ⇒ เอกสารโผล่ในวันที่ 14 แต่จอแสดงว่า 13)
 *
 * ทำงานถูกเพราะ `new Date(iso)` บนสตริงที่มี offset/Z ได้ "จุดเวลาสัมบูรณ์"
 * แล้วค่อยจัดรูปในโซนไทย — ค่าที่ backend ส่งมาเป็น tz-aware เสมอ (Pydantic v2 เขียน UTC เป็น `Z`)
 */
export const formatThaiDateTime = (iso?: string | null): string => {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return `${parsed.toLocaleString('th-TH', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: BANGKOK_TZ,
  })} น.`;
};

/**
 * เวลาแบบไทย (ชม.:นาที) จาก timestamp จริง — ใช้กับเวลาที่เป็น **หลักฐาน**
 * เช่น เวลาเช็คอินบนใบยืนยันชั่วโมงจิตอาสา
 *
 * ⚠️ รับได้เฉพาะ timestamp จริง (มี `Z`/offset) — ถ้าส่งสตริงวันที่ล้วน (`YYYY-MM-DD`)
 *    เข้ามันจะกลายเป็นเที่ยงคืน UTC แล้วจัดรูปเป็น 07:00 ซึ่งไม่มีความหมาย
 *
 * 🔑 แยกออกมาเป็นฟังก์ชัน (เดิมเขียน `toLocaleTimeString` ตรง ๆ ในเทมเพลต) เพราะ
 *    **การไม่ระบุ `timeZone` = ใช้โซนของอุปกรณ์ผู้ใช้** ⇒ แท็บเล็ต/มือถือที่ตั้ง TZ
 *    ไม่ใช่ไทยจะโชว์เวลาเช็คอินคลาดเคลื่อนได้หลายชั่วโมง บนเอกสารที่ครูใช้ยืนยัน
 *    ชั่วโมงจิตอาสา ⇒ ต้องเป็นโซนไทยเสมอตามกฎของโปรเจกต์
 */
export const formatThaiTime = (iso?: string | null): string => {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleTimeString('th-TH', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: BANGKOK_TZ,
  });
};

/** เดือน + ปี พ.ศ. เช่น "กันยายน 2569" */
export const formatThaiMonthYear = (year: number, month: number): string =>
  `${THAI_MONTHS[month - 1] ?? month} ${year + 543}`;

/** คำอธิบายช่วงเวลาสำหรับหัวการ์ด — ต้องบอกได้ว่ากำลังดูอะไรอยู่ */
export const describePeriod = (p: PeriodValue): string => {
  if (p.mode === 'month') return `เดือน${formatThaiMonthYear(p.year, p.month)}`;
  if (p.mode === 'range') return `${formatThaiDate(p.startDate)} – ${formatThaiDate(p.endDate)}`;
  return `ณ วันที่ ${formatThaiDate(p.asOfDate)}`;
};

/** วันที่อ้างอิงของ period — ใช้ตอนสลับโหมด เพื่อไม่ให้ค่าที่ผู้ใช้ตั้งไว้หายไป */
export const referenceDate = (p: PeriodValue): { year: number; month: number } => {
  if (p.mode === 'month') return { year: p.year, month: p.month };
  const iso = p.mode === 'range' ? p.startDate : p.asOfDate;
  const parsed = parseIso(iso);
  // ISO เพี้ยน/ว่าง → ถอยไปใช้ "วันนี้" ตามเวลาไทย ไม่ใช่ปฏิทินของอุปกรณ์ (ดู todayThaiYearMonth)
  if (!parsed) return todayThaiYearMonth();
  return { year: parsed.y, month: parsed.m };
};

/** ช่วงวันที่กลับด้าน (start > end) — backend จะ 400 จึงต้องดักที่หน้าจอก่อน */
export const isRangeReversed = (p: PeriodValue): boolean =>
  p.mode === 'range' && !!p.startDate && !!p.endDate && p.startDate > p.endDate;
