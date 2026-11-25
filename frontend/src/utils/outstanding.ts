/**
 * 📐 [FIN-V2 / P6.3] สูตร **ยอดคงเหลือ 3 พจน์** ของฝั่งหน้าจอ — ที่เดียวของทั้งแอป
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมีไฟล์นี้
 * ═══════════════════════════════════════════════════════════════════════════
 * P6.2 เปลี่ยนสูตรยอดค้างฝั่ง backend เป็น `amount - paid - written_off` (~20 จุด)
 * แต่ฝั่งหน้าจอยังมี `total_amount - paid_amount` กระจายอยู่ (CollectionDetail 5 จุด)
 * ⇒ พอมีบิลที่ถูกตัดจำหน่าย หน้าจอจะโชว์ยอดเกินจริงทุกจุดที่ลืม
 *
 * 🔴 กติกา:
 *   1. เขียนสูตรใหม่ที่ไหน **ต้องเรียก `outstandingOf`** ไม่ใช่ลบเองในเทมเพลต/วิว
 *   2. **ไม่ clamp ที่ 0** — ยอดติดลบคือข้อมูลผิด (ตัดเกินยอด) ต้องเห็น ไม่ใช่ซ่อน
 *   3. `isSettled` เป็นตัวตัดสิน "ไม่มีอะไรค้าง" — ห้ามใช้ `paid === amount` เพราะบิลที่
 *      ถูกตัดหนี้มี `paid < amount` แต่ settled แล้ว
 *   4. ตัวเลขจาก API เป็น string 2 ตำแหน่ง ⇒ แปลง `Number(...)` ก่อนเรียก และปัดผ่าน
 *      `roundMoney` เพื่อไม่ให้ทศนิยมลอย (0.1 + 0.2 ≠ 0.3)
 */
import { roundMoney } from '@/utils/money';

export interface OutstandingParts {
  /** ยอดเต็มของบิล (`fee_collections.amount`) */
  amount: number;
  /** จ่ายมาแล้ว (`student_payments.paid_amount`) */
  paid: number;
  /** ตัดจำหน่าย/ให้ส่วนลดสะสม (`student_payments.written_off_amount`) — ไม่ส่ง = 0 */
  writtenOff?: number;
}

/** ยอดที่ยังต้องเก็บจริง = ยอดบิล − จ่ายแล้ว − ตัดไปแล้ว (ปัด 2 ตำแหน่ง, ไม่ clamp) */
export const outstandingOf = ({ amount, paid, writtenOff = 0 }: OutstandingParts): number => {
  const value = roundMoney(amount - paid - writtenOff);
  // `Math.round(-1e-15 * 100) / 100` ได้ `-0` ซึ่ง Intl แสดงเป็น "-0.00" ⇒ normalize
  // (เทียบ `===` ถือว่า -0 เท่ากับ 0 จึงคืน 0 ตรง ๆ; ค่าติดลบจริง (เช่น -100) ไม่ถูกแตะ)
  return value === 0 ? 0 : value;
};

/** "ไม่มีอะไรค้างแล้ว" — ใช้ `0.005` ตัวเดียวกับ epsilon ฝั่ง backend */
export const isSettled = (value: number): boolean => Math.abs(value) < 0.005;
