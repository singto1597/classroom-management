/**
 * 💵 [FIN-V2 / P5.5] ผลต่างเงินสดนับจริง vs ยอดบัญชี — ตรรกะบริสุทธิ์ของหน้าปิดงบ
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องแยกออกมาเป็นไฟล์
 * ═══════════════════════════════════════════════════════════════════════════
 * 1. **การเทียบ "ต่างเป็นศูนย์" เป็นเรื่องของเงิน ไม่ใช่เรื่องของหน้าจอ** — backend
 *    บังคับ `abs(variance) < 0.005` (`_VARIANCE_EPSILON` ใน `monthly_reports.py`)
 *    ⇒ FE ต้องใช้เกณฑ์เดียวกัน ไม่งั้นจอจะเปิดปุ่มที่ backend จะตอบ 400 หรือปิดปุ่ม
 *    ทั้งที่ปิดงบได้
 * 2. **ห้ามส่ง number จาก input ตรง ๆ** — `0.1 + 0.2` ใน JavaScript คือ 0.30000000000000004
 *    ⇒ parse จาก string เป็น "สตางค์" (integer) ก่อน แล้วหารกลับทีหลัง ผลต่างจึงเป็น
 *    ผลลบของจำนวนเต็มที่แม่นยำ 100% และการเทียบ `=== 0` ใช้ได้จริง
 * 3. testing แยกได้โดยไม่ต้อง mount หน้าจอ (`utils/__tests__/cashVariance.spec.ts`)
 *
 * 🔴 ยอดค้าง/ยอดรับเงินอื่น ๆ ห้ามคำนวณที่นี่ — ไฟล์นี้รู้จักแค่ "เงินสดที่นับได้"
 *    กับ "ยอดที่บัญชีบอก" ซึ่ง backend ส่งมาให้แล้วเท่านั้น
 */

/**
 * เกณฑ์เดียวกับ backend (`_VARIANCE_EPSILON = 0.005`)
 *
 * ต่างน้อยกว่านี้ถือว่า "ตรง" — เป็นครึ่งสตางค์ที่เกิดจากการปัดของ DECIMAL(15,2)
 * ไม่ใช่เงินที่หายจริง
 */
export const VARIANCE_EPSILON = 0.005;

/**
 * 🧹 ล้างสิ่งที่ผู้ใช้พิมพ์ให้เหลือ "เลข + จุดเดียว + ทศนิยม ≤2" หรือ `''`
 *
 * - คั่นหลักพัน/ช่องว่าง/ตัวอักษร → ทิ้ง (วาง "1,234.567" ได้ผล "1234.56")
 * - เครื่องหมายลบ → **ทั้งค่าว่าง** เพราะเงินสดที่นับได้ไม่มีค่าลบ และการลบ '-' ทิ้ง
 *   เงียบ ๆ จะเปลี่ยน "-5" เป็น 5 ซึ่งเป็นเงินที่บันทึกได้ทั้งที่ผู้ใช้พิมพ์ติดลบ
 * - จุดที่ไม่มีเลขนำหน้า (".") → "0." เพื่อให้ผู้ใช้พิมพ์ต่อได้ตามปกติ
 */
export const normalizeCashInput = (raw: string): string => {
  if (typeof raw !== 'string') return '';
  const trimmed = raw.trim();
  if (trimmed === '') return '';
  if (trimmed.includes('-')) return '';

  let whole = '';
  let frac = '';
  let seenDot = false;
  for (const ch of trimmed) {
    if (ch >= '0' && ch <= '9') {
      if (seenDot) frac += ch;
      else whole += ch;
    } else if (ch === '.' && !seenDot) {
      seenDot = true;
    }
    // comma / ช่องว่าง / ตัวอื่น: ข้าม
  }

  if (!seenDot) return whole;
  return `${whole === '' ? '0' : whole}.${frac.slice(0, 2)}`;
};

/** string (หรือ number ที่ปัดแล้ว) → จำนวนสตางค์แบบ integer หรือ `null` เมื่อยังไม่กรอก */
const toCents = (value: string | number | null | undefined): number | null => {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') {
    return Number.isFinite(value) ? Math.round(value * 100) : null;
  }
  const normalized = normalizeCashInput(value);
  if (normalized === '') return null;
  const [whole = '0', frac = ''] = normalized.split('.');
  const wholeCents = (Number(whole || '0') || 0) * 100;
  const fracCents = Number(`${frac}00`.slice(0, 2)) || 0;
  return wholeCents + fracCents;
};

/**
 * ผลต่าง = นับได้ − ควรเป็น (บวก = เงินเกิน, ลบ = เงินขาด)
 *
 * คืน `null` เมื่อยังไม่ได้กรอกยอดนับได้ (แยก "ยังไม่นับ" ออกจาก "นับได้ 0" ซึ่ง
 * เป็นค่าที่ถูกต้องและปิดงบได้เมื่อยอดบัญชีเป็นศูนย์พอดี)
 */
export const computeVariance = (
  counted: string | number | null | undefined,
  expected: number,
): number | null => {
  const countedCents = toCents(counted);
  if (countedCents === null) return null;
  const expectedCents = Number.isFinite(expected) ? Math.round(expected * 100) : 0;
  return (countedCents - expectedCents) / 100;
};

/** ปิดงบได้เมื่อมีผลต่างและ |ผลต่าง| < 0.005 เท่านั้น (เกณฑ์เดียวกับ backend) */
export const canFinalize = (variance: number | null | undefined): boolean =>
  typeof variance === 'number' &&
  Number.isFinite(variance) &&
  Math.abs(variance) < VARIANCE_EPSILON;

/**
 * ข้อความอธิบายผลต่างเป็นภาษาไทย — บอก **สามตัวเลข** เสมอ (นับได้ / ควรเป็น / ต่าง)
 *
 * 🔴 ห้ามให้หน้าจอประกอบข้อความเอง เพราะข้อความนี้ถูกใช้ทั้งป้ายผลต่างสด ๆ และ
 *    กล่องยืนยัน ⇒ ถ้าแยกกันเขียน วันหนึ่งตัวเลขบนป้ายกับในกล่องจะไม่ตรงกัน
 */
export const varianceMessage = (
  counted: string | number | null | undefined,
  expected: number,
): string => {
  const countedValue = toCents(counted);
  const expectedValue = Number.isFinite(expected) ? expected : 0;
  const expectedText = expectedValue.toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  if (countedValue === null) {
    return `ยังไม่ได้กรอกยอดนับได้ · ควรเป็น ฿${expectedText}`;
  }

  const variance = (countedValue - Math.round(expectedValue * 100)) / 100;
  const countedText = (countedValue / 100).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const varianceText = formatVariance(variance);
  return `นับได้ ฿${countedText} · ควรเป็น ฿${expectedText} · ต่าง ${varianceText}`;
};

/** ผลต่างแบบมีเครื่องหมาย — ติดลบใช้ `−` (U+2212) เหมือน `formatMoney` */
const formatVariance = (variance: number): string => {
  const body = Math.abs(variance).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${variance < 0 ? '−' : ''}฿${body}`;
};
