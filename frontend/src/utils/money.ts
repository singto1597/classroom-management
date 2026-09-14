/**
 * 💰 เงิน — รูปแบบเดียวสำหรับทั้งระบบ (`DESIGN.md` §7)
 *
 * ⚠️ **ไฟล์นี้ไม่ใช่การรื้อของเดิม** — ใน repo ยังมีสำเนา `formatMoney` อยู่ ~5 ที่
 *    (`ReceiptList`, `ReceiptDetail`, `BudgetList`, `FinancialStatements`, …)
 *    ที่เขียนถูกอยู่แล้วและ **ไม่ต้องแก้** (งานคนละชิ้น) · ไฟล์นี้มีไว้เพื่อให้
 *    **โค้ดใหม่** (F4: เงินรับล่วงหน้า) ไม่ต้องเพิ่มสำเนาที่ 6
 *
 * 🔴 กติกาที่ต้องเหมือนกันทุกที่ไม่ว่าจะเรียกจากไหน:
 *   1. คั่นหลักพันแบบไทย (`toLocaleString('th-TH')`) + ทศนิยม **2 ตำแหน่งเสมอ**
 *      (ไม่ใช่ "ตัดทศนิยมเมื่อเป็น .00" — ตัวเลขการเงินต้องอ่านเทียบกันได้ตรงคอลัมน์)
 *   2. เติม `฿` **นำหน้า** ตัวเลข ไม่ใช่ต่อท้าย
 *   3. ค่าติดลบใช้ `−` (U+2212 minus sign) **ไม่ใช่** `-` (hyphen) — ยาวเท่ากัน
 *      อ่านง่ายกว่า และไม่ถูกสับสนกับขีดกลางในชื่อรายการ
 *   4. `฿` อยู่นอกเครื่องหมายลบ ⇒ `−฿1,200.00` ไม่ใช่ `฿-1,200.00`
 */

/** ตัวคั่นหลักพันไทย + ทศนิยม 2 ตำแหน่ง + `฿` นำหน้า (ติดลบได้) */
export const formatMoney = (value: number | null | undefined): string => {
  // 🛡️ ค่าที่ backend ส่งมาเป็น Optional ได้ (เช่น ฟิลด์ที่เพิ่งเพิ่มและยังไม่ถูกเติม)
  //    ⇒ โชว์ ฿0.00 ดีกว่าโชว์ NaN บนหน้าจอการเงิน
  const n = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  const body = Math.abs(n).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${n < 0 ? '−' : ''}฿${body}`;
};

/** ตัวเลขล้วน (ไม่มี `฿`) — สำหรับช่องกรอก/ตารางที่หัวคอลัมน์บอกหน่วยแล้ว */
export const formatAmount = (value: number | null | undefined): string => {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  return Math.abs(n).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

/**
 * 🔑 รหัสกันบันทึกซ้ำสำหรับ **การกดหนึ่งครั้ง** (`idempotency_key`)
 *
 * ⚠️ **เรียกครั้งเดียวต่อการกดหนึ่งครั้ง แล้วเก็บค่าไว้ใช้ตลอดรอบนั้น** — ห้ามเรียก
 *    ใหม่ตอน retry: คีย์ที่เปลี่ยนไปคือ "รายการใหม่" ในสายตาของ backend ⇒ ผู้ใช้ที่
 *    กดซ้ำเพราะเน็ตสะดุดจะได้เครดิตสองรอบจากเงินก้อนเดียว
 *
 * ใช้ `crypto.randomUUID()` (มีในเบราว์เซอร์ที่ระบบนี้รองรับทุกตัว + jsdom ของ vitest
 * ผ่าน `globalThis.crypto`) แล้วตัดขีดออกให้เหลือ 32 ตัวอักษร — อยู่ในช่วง 8–64 ที่
 * backend บังคับ และอ่านคัดลอกใน log ได้ง่ายกว่า
 *
 * 🛡️ ถ้า `crypto.randomUUID` ไม่มีจริง (เบราว์เซอร์เก่า/บริบทที่ไม่ใช่ secure context)
 *    จะ **ไม่ถอยไปใช้ `Math.random()`** เพราะคีย์ที่ชนกันได้ = เงินสองรอบหายเงียบ ๆ
 *    ⇒ โยน error ให้ผู้ใช้รู้ตัวดีกว่า (หน้าจอจะโชว์ข้อความจาก `Swal`)
 */
export const newIdempotencyKey = (): string => {
  const c = globalThis.crypto as Crypto | undefined;
  if (!c || typeof c.randomUUID !== 'function') {
    throw new Error(
      'เบราว์เซอร์นี้ไม่รองรับการสร้างรหัสกันบันทึกซ้ำอย่างปลอดภัย — กรุณาอัปเดตเบราว์เซอร์ก่อนทำรายการเงิน'
    );
  }
  return c.randomUUID().replace(/-/g, '');
};

/** ตัดเศษทศนิยมให้เหลือสตางค์เดียวกับที่ DB เก็บ (`DECIMAL(15,2)`) — ใช้เทียบ/ส่งค่า */
export const roundMoney = (value: number): number => Math.round(value * 100) / 100;
