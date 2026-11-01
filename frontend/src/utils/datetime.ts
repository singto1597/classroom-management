/**
 * 🗓️ วันที่/เวลาไทย — แหล่งความจริงเดียวของ frontend
 *
 * กฎของโปรเจกต์: ทุกวันที่/เวลาที่ผู้ใช้เห็นต้องเป็น **Asia/Bangkok** และปี พ.ศ.
 * ห้ามเรียก `toLocaleDateString`/`toLocaleTimeString` ตรงใน view เพราะลืม `timeZone`
 * ง่ายมาก ⇒ อุปกรณ์ที่ตั้งโซนอื่นจะเห็นวัน/เวลาคลาดเคลื่อน (เคยเกิดกับเวลาเช็คอิน
 * และวันที่ออกใบเสร็จ)
 *
 * ⚠️ แยกความหมายสองแบบ:
 *   - **date-only** (`YYYY-MM-DD` เช่น `due_date`, `activity_date`)
 *     → ใช้ `formatThaiDate()` ซึ่งไม่ผ่าน `new Date(iso)` เพื่อกัน UTC ดันข้ามวัน
 *   - **timestamp** (มี `Z`/offset เช่น `created_at`, `issued_at`)
 *     → ใช้ `formatThaiDateTime()` / `formatThaiTime()` ซึ่งต้องผ่าน Date
 *       เพื่อแปลง "จุดเวลาสัมบูรณ์" เป็นโซนไทย
 *   ส่ง timestamp ให้ `formatThaiDate()` = วันที่แบบ UTC (ผิด) — ดูคอมเมนต์ในฟังก์ชัน
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

export type ThaiMonthStyle = 'short' | 'long';

const pad2 = (n: number): string => String(n).padStart(2, '0');

/** แยก YYYY-MM-DD เป็นตัวเลขโดยไม่ผ่าน Date เพื่อไม่ให้ timezone ดันวันที่ข้ามวัน */
const parseIsoDate = (iso: string): { y: number; m: number; d: number } | null => {
  const parts = iso.slice(0, 10).split('-').map(Number);
  const [y, m, d] = parts;
  if (!y || !m || !d || parts.length !== 3) return null;
  return { y, m, d };
};

/** วันที่วันนี้ตามเวลาไทย (YYYY-MM-DD) — 'en-CA' ให้รูป ISO ตรง ๆ */
export const todayIso = (): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: BANGKOK_TZ }).format(new Date());

/** ชั่วโมงปัจจุบันตามเวลาไทย (0–23) — ไม่ใช้ `new Date().getHours()` ของอุปกรณ์ */
export const bangkokHour = (): number =>
  Number(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: BANGKOK_TZ,
      hour: '2-digit',
      hourCycle: 'h23',
    }).format(new Date()),
  );

/**
 * วันที่แบบไทย (พ.ศ. อัตโนมัติจาก locale th-TH) — **สำหรับ date-only เท่านั้น**
 *
 * ประกอบ Date จากชิ้นส่วน local ตรง ๆ (ไม่ปล่อยให้ parse ISO) เพราะ `new Date('2026-10-01')`
 * คือเที่ยงคืน UTC ซึ่งเมื่อแสดงในโซนไทยจะเป็น 07:00 ของวันเดียวกันก็จริง แต่ถ้ามีคนเผลอ
 * ใส่ออฟเซตหรือเวลาเข้าไป วันที่ที่เห็นจะเลื่อนได้ — ดังนั้นเราจึงอ่านเฉพาะ 10 ตัวแรก
 */
export const formatThaiDate = (
  iso?: string | null,
  monthStyle: ThaiMonthStyle = 'short',
): string => {
  if (!iso) return '—';
  const parsed = parseIsoDate(iso);
  if (!parsed) return iso;
  return new Date(parsed.y, parsed.m - 1, parsed.d).toLocaleDateString('th-TH', {
    day: 'numeric',
    month: monthStyle,
    year: 'numeric',
  });
};

/**
 * วัน **และเวลา** แบบไทยจาก timestamp จริง — "5 ส.ค. 2569 14:30 น."
 *
 * ⚠️ ห้ามใช้ `formatThaiDate` กับ timestamp: มันตัดเอาแค่ส่วนวันที่ของสตริง ISO
 *    ซึ่งเป็น **วันที่แบบ UTC** — ใบเสร็จที่ออก 18:30 UTC คือ 01:30 ของ **วันรุ่งขึ้น** ในไทย
 *    แล้วผู้ใช้จะเห็นวันที่ไม่ตรงกับวันที่บนเอกสาร และไม่ตรงกับตัวกรองช่วงวันที่ของตัวเอง
 */
export const formatThaiDateTime = (iso?: string | null): string => {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  const { date, time } = formatThaiDateTimeParts(iso);
  return `${date} ${time} น.`;
};

/** แยกส่วนวันที่กับเวลา (สำหรับตารางที่แยกคอลัมน์) — ใช้ timestamp เท่านั้น */
export const formatThaiDateTimeParts = (
  iso?: string | null,
): { date: string; time: string } => {
  if (!iso) return { date: '—', time: '' };
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return { date: iso, time: '' };
  return {
    date: parsed.toLocaleDateString('th-TH', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: BANGKOK_TZ,
    }),
    time: parsed.toLocaleTimeString('th-TH', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: BANGKOK_TZ,
    }),
  };
};

/**
 * เวลาแบบไทย (ชม.:นาที) จาก timestamp จริง — ใช้กับเวลาที่เป็น **หลักฐาน**
 * เช่น เวลาเช็คอินบนใบยืนยันชั่วโมงจิตอาสา
 *
 * ⚠️ รับได้เฉพาะ timestamp จริง (มี `Z`/offset) — ถ้าส่งสตริงวันที่ล้วน (`YYYY-MM-DD`)
 *    เข้ามันจะกลายเป็นเที่ยงคืน UTC แล้วจัดรูปเป็น 07:00 ซึ่งไม่มีความหมาย
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

/**
 * จำนวนวันจาก "วันนี้ตามเวลาไทย" ถึง date-only ที่ให้มา (ลบ = ผ่านมาแล้ว)
 * คืน `null` เมื่อรูปแบบวันที่ไม่ถูกต้อง — ผู้เรียกตัดสินใจเองว่าจะแสดงอะไร
 */
export const daysFromThaiToday = (dateIso: string): number | null => {
  const target = parseIsoDate(dateIso);
  const today = parseIsoDate(todayIso());
  if (!target || !today) return null;
  const targetUtc = Date.UTC(target.y, target.m - 1, target.d);
  const todayUtc = Date.UTC(today.y, today.m - 1, today.d);
  return Math.round((targetUtc - todayUtc) / 86_400_000);
};

/** "วันนี้"/"พรุ่งนี้" สำหรับ date-only — คืน `null` เมื่อไม่ใช่ทั้งสองอย่าง */
export const relativeThaiDay = (dateIso: string): 'วันนี้' | 'พรุ่งนี้' | null => {
  const diff = daysFromThaiToday(dateIso);
  if (diff === 0) return 'วันนี้';
  if (diff === 1) return 'พรุ่งนี้';
  return null;
};

/** ตรวจว่า ISO วันที่ใช้ได้ (ใช้ในเทสต์/ฟอร์มที่ต้องแยก "ยังไม่กรอก" กับ "กรอกผิด") */
export const isValidIsoDate = (iso: string): boolean => parseIsoDate(iso) !== null;

/** เติมศูนย์ให้เดือน/วัน — ใช้ประกอบค่า date-only ให้ backend */
export const isoDateOf = (year: number, month: number, day: number): string =>
  `${year}-${pad2(month)}-${pad2(day)}`;
