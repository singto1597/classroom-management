/**
 * 🏷️ หมวดกิจกรรม (P4.3) — คำไทยชุดเดียวที่ผู้ใช้เห็นสำหรับ `activities.category`
 *
 * ทำไมต้องเป็นรายการปิด: ฝั่ง backend ตรวจ slug กับ `ACTIVITY_CATEGORIES` ใน
 * `backend/services/activity/constants.py` และปฏิเสธค่าที่ไม่รู้จักด้วย 400
 * ⇒ ถ้าเพิ่มหมวดที่หน้าเว็บโดยไม่แก้ backend = กดบันทึกแล้วพังเงียบ ๆ
 *
 * ⚠️ ต้องตรงกับ `backend/services/activity/constants.py` → `ACTIVITY_CATEGORIES`
 *    และ `docs/glossary.md` → "หมวดกิจกรรม" · เพิ่มค่าใหม่ = แก้ทั้งสามที่ใน PR เดียว
 *    (คอลัมน์เป็น TEXT ไม่ต้อง migration — แต่ต้องแก้ `activityCategories.spec.ts` ด้วย)
 *
 * ลำดับในลิสต์ = ลำดับในดรอปดาวน์/ชิปกรอง ("อื่น ๆ" อยู่ท้ายเสมอ)
 */

export interface ActivityCategoryOption {
  value: string;
  label: string;
}

export const ACTIVITY_CATEGORIES: ActivityCategoryOption[] = [
  { value: 'camp', label: 'ค่าย' },
  { value: 'competition', label: 'การแข่งขัน' },
  { value: 'volunteer', label: 'จิตอาสา' },
  { value: 'training', label: 'อบรม/สัมมนา' },
  { value: 'ceremony', label: 'พิธีการ' },
  { value: 'other', label: 'อื่น ๆ' },
];

/** ยังไม่จัดหมวด — **อย่าแสดงเป็นค่าว่าง** ให้ใช้ป้ายนี้ */
export const UNCATEGORIZED_LABEL = 'ไม่ระบุหมวด';

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  ACTIVITY_CATEGORIES.map((c) => [c.value, c.label]),
);

/** slug → ป้ายไทย · ค่าที่ไม่รู้จัก (backend เพิ่มก่อน) คืน `null` เพื่อให้จอเลือกแสดงเอง */
export function activityCategoryLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return CATEGORY_LABELS[value] ?? null;
}
