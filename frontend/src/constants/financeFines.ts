/**
 * ⚖️ ฉลากไทยของค่าปรับ — แหล่งเดียวของหน้าจอค่าปรับ/รายละเอียด/รายงาน
 *
 * ⚠️ ค่าดิบต้องตรงกับ `backend/services/finance/constants.py` → `FINE_STATUS_LABELS`
 *    และ `FINE_WAIVER_CATEGORY_LABELS` — ถ้า backend เพิ่มสถานะใหม่ ให้เพิ่มที่นี่ด้วย
 *    (ไม่ครบ = หน้าจอโชว์ค่าดิบอังกฤษ ซึ่งผู้ใช้อ่านไม่ออก)
 */

export const FINE_STATUS_LABELS: Record<string, string> = {
  issued: 'ออกแล้ว',
  partially_paid: 'ชำระบางส่วน',
  paid: 'ชำระแล้ว',
  waived: 'ยกเว้น/ลด',
  cancelled: 'ยกเลิก',
  refunded: 'คืนเงินแล้ว',
};

/** โทนป้ายสถานะ — คู่กับ `StatusBadge` (สีไม่ใช่ช่องทางเดียว มีข้อความกำกับเสมอ) */
export const FINE_STATUS_TONES: Record<
  string,
  'neutral' | 'ok' | 'warn' | 'danger' | 'brand'
> = {
  issued: 'warn',
  partially_paid: 'brand',
  paid: 'ok',
  waived: 'neutral',
  cancelled: 'neutral',
  refunded: 'ok',
};

export const WAIVER_STATUS_LABELS: Record<string, string> = {
  pending: 'รออนุมัติ',
  approved: 'อนุมัติแล้ว',
  rejected: 'ปฏิเสธแล้ว',
  cancelled: 'ยกเลิกแล้ว',
};

export const REFUND_STATUS_LABELS: Record<string, string> = WAIVER_STATUS_LABELS;

export const WAIVER_CATEGORY_LABELS: Record<string, string> = {
  discount: 'ส่วนลดค่าปรับ',
  uncollectible: 'หนี้สูญ (ตามไม่ได้)',
};

export const fineStatusLabel = (status: string): string =>
  FINE_STATUS_LABELS[status] ?? status;

export const fineStatusTone = (
  status: string,
): 'neutral' | 'ok' | 'warn' | 'danger' | 'brand' => FINE_STATUS_TONES[status] ?? 'neutral';
