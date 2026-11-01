/**
 * 👤 อักษรย่อสำหรับ avatar — กฎภาษาไทยที่ทำให้ตัวอักษร "อ่านออก"
 *
 * ปัญหาที่มันแก้: `displayName(...).charAt(0)` บนชื่อไทยมักได้ **สระนำ**
 * ("เก่ง" → "เ", "โอม" → "โ", "ใหม่" → "ไ") ซึ่งไม่ใช่พยัญชนะต้นของชื่อ
 * และเมื่อเอาขึ้นวงกลม avatar ผู้ใช้จะอ่านไม่ออกว่าเป็นใคร
 *
 * กฎ:
 *   1. ข้ามสระนำ เ แ โ ใ ไ (language-level: มันนำหน้าพยัญชนะเสมอ)
 *   2. ข้ามเครื่องหมายวรรณยุกต์/สระบน-ล่างที่อาจติดมาก่อนพยัญชนะในสตริงที่ normalize แล้ว
 *   3. ถ้าเป็นชื่อละติน ใช้ตัวแรกและแปลงเป็นตัวพิมพ์ใหญ่
 *   4. ชื่อว่าง/มีแต่ช่องว่าง → fallback ที่ผู้เรียกกำหนด
 *
 * ⚠️ ไม่ได้พยายามทำ grapheme clustering เต็มรูปแบบ — avatar แสดงอักษรตัวเดียว
 *    จึงเอา "พยัญชนะตัวแรก" พอ และต้องได้ผลเหมือนกันทั้ง StudentList/StudentProfile/shell
 */

const THAI_LEADING_VOWELS = new Set(['เ', 'แ', 'โ', 'ใ', 'ไ']);

/** Combining marks ที่ตามหลัง/อยู่เหนือพยัญชนะ: ั ิ ี ึ ื ุ ู ฺ ็ ่ ้ ๊ ๋ ์ ํ ๎ ฯลฯ */
const THAI_MARKS = /[ัิ-ฺ็-๎]/;

const LATIN = /^[A-Za-z]$/;

/**
 * คืนอักษรย่อ 1 ตัวจากชื่อที่ให้มา
 * @param name ชื่อที่พร้อมแสดงผล (ไทยหรืออังกฤษ)
 * @param fallback ค่าที่ใช้เมื่อไม่มีชื่อ (เช่น '?' หรือ 'ส')
 */
export function avatarInitial(name: string | null | undefined, fallback = '?'): string {
  const trimmed = (name ?? '').trim();
  if (!trimmed) return fallback;

  const chars = Array.from(trimmed);

  // ชื่อละติน: ใช้อักษรตัวแรกและทำเป็นตัวพิมพ์ใหญ่ (Aomsin → A)
  const first = chars[0] ?? '';
  if (LATIN.test(first)) return first.toUpperCase();

  for (const ch of chars) {
    if (THAI_LEADING_VOWELS.has(ch)) continue;
    if (THAI_MARKS.test(ch)) continue;
    if (/\s/.test(ch)) continue;
    return ch;
  }

  return fallback;
}
