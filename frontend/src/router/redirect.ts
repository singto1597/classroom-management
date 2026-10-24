/**
 * 🔐 `safeRedirect()` — ประตูเดียวสำหรับ "พาผู้ใช้กลับไปหน้าที่ตั้งใจจะไป"
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องเข้มถึงขนาดนี้
 * ═══════════════════════════════════════════════════════════════════════════
 * ปลายทางที่ส่งมากับ URL (`?next=...`) เป็น **ข้อมูลที่ผู้โจมตีควบคุมได้**
 * ถ้าเอาไป `router.push()` หรือ `window.location.href = ...` ตรง ๆ จะได้ช่องโหว่
 * open redirect: ลิงก์ที่ดูเหมือนของระบบเรา (`https://class.singto1597.xyz/login?next=...`)
 * พาเหยื่อไปหน้า phishing ที่หน้าตาเหมือนหน้าเข้าสู่ระบบของเราได้ทันที
 *
 * รูปแบบที่ต้องปฏิเสธ (ทั้งหมดเป็น "URL ที่ไม่ใช่ path ภายใน"):
 *   `//evil.com`            → protocol-relative ⇒ ไปโดเมนอื่น
 *   `https://evil.com`      → absolute ⇒ ไปโดเมนอื่น
 *   `/\/evil.com`           → เบราว์เซอร์ตีความ `\` เป็น `/` ⇒ protocol-relative
 *   `/\evil.com`            → เหมือนข้างบน
 *   `%2F%2Fevil.com`        → ต้องถอด encode ก่อนตัดสิน (ทำแล้ว)
 *   `javascript:alert(1)`   → ไม่ได้เริ่มด้วย `/` ⇒ ปฏิเสธอยู่แล้ว
 *   ` /students` (มีช่องว่างนำ) → trim แล้วต้องเริ่มด้วย `/` (จัดการแล้ว)
 *   `\r\n...`               → อักขระควบคุมถูกปฏิเสธ
 *
 * ⚠️ นี่คือ **denylist ของรูปแบบ URL ที่อันตราย** + allowlist แบบ "ต้องเป็น path
 *    ภายในเสมอ" ไม่ใช่ allowlist ของ path ที่รู้จัก ⇒ หน้าใหม่ไม่ต้องมาแก้ไฟล์นี้
 *    แต่หน้า auth (`/login`, `/auth/*`) ถูกปฏิเสธโดยเจตนาเพื่อกัน redirect วนลูป
 */

/** ยาวเกินนี้ถือว่าผิดปกติ — path จริงของระบบสั้นกว่านี้มาก */
const MAX_LENGTH = 2048;

/** path ที่ห้ามเป็นปลายทางหลังล็อกอิน (จะวนกลับหน้า auth) */
const LOOP_PREFIXES: readonly string[] = ['/login', '/onboarding', '/auth/'];

/** มีอักขระควบคุม (U+0000–U+001F, U+007F — รวม CR/LF) หรือไม่ — ใช้ทำ header injection ได้ */
function hasControlChars(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code < 0x20 || code === 0x7f) return true;
  }
  return false;
}

/**
 * คืน path ภายในที่ปลอดภัย หรือ `null` เมื่อไม่ผ่านเกณฑ์
 *
 * ผู้เรียกต้องถอยไปใช้ปลายทางเริ่มต้น (`/dashboard`) เมื่อได้ `null` — ห้าม
 * พยายาม "ซ่อม" ค่าที่ไม่ผ่าน เพราะการเดาเจตนาของ URL ที่ถูกดัดแปลงคือที่มาของช่องโหว่
 */
export function safeRedirect(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;

  const value = raw.trim();
  if (!value || value.length > MAX_LENGTH) return null;
  if (!value.startsWith('/')) return null;
  if (value.startsWith('//')) return null;
  if (value.includes('\\')) return null;
  if (hasControlChars(value)) return null;

  // ค่าที่ encode มา (`%2F%2Fevil.com`, `%5Cevil.com`) ต้องถูกถอดก่อนตัดสิน
  // ตัว decodeURIComponent โยน error เมื่อ `%` ไม่ครบ ⇒ ถือว่าไม่ผ่าน
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  if (decoded.startsWith('//') || decoded.includes('\\')) return null;
  if (hasControlChars(decoded)) return null;

  // ตัด query/hash ก่อนตรวจ path — `/login?x=1` ก็ยังวนลูป
  const pathOnly = decoded.split(/[?#]/)[0] ?? decoded;
  if (LOOP_PREFIXES.some((prefix) => pathOnly === prefix || pathOnly.startsWith(prefix))) {
    return null;
  }

  return value;
}
