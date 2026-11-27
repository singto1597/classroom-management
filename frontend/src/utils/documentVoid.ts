/**
 * 🚫 ตัวกลาง "ยกเลิกเอกสารทุกชนิดจากทะเบียน" (2026-11-27)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมี
 * ═══════════════════════════════════════════════════════════════════════════
 * ทะเบียนเอกสารแสดง 8 ชนิด และแต่ละชนิดต้องเรียก endpoint ต่างกัน:
 *
 *   INV            → POST /documents/invoice/{id}/void
 *   REC/DEP        → POST /payment-events/{event_id}/void
 *   PV/CERT        → POST /expense-vouchers/{voucher_id}/void
 *   INC            → POST /income-batches/{batch_id}/void
 *   ACK            → POST /acknowledgements/{receipt_no}/void
 *   RPT            → POST /monthly-reports/{id}/void
 *   legacy (รุ่นก่อน) → DELETE /transactions/{id} (ไม่มีเหตุผล)
 *
 * การ "เดา" จาก doc_type ฝั่งจอจะพลาดทันทีที่ backend เพิ่มความสัมพันธ์ใหม่
 * ⇒ backend ส่ง `void_target` มาพร้อมแถว และที่นี่เป็นที่เดียวที่ dispatch
 *
 * ⚠️ เอกสารที่ `void_target` เป็น `null` = ยกเลิกไม่ได้ — ผู้เรียกต้องไม่แสดงปุ่ม
 *    (ใช้ `Boolean(doc.void_target)` ไม่ใช่ `!== null` เพื่อรองรับ backend รุ่นเก่า
 *     ระหว่าง rolling deploy ที่ฟิลด์อาจยังไม่ถูกส่งมา)
 */
import { FinanceService } from '@/services/finance';
import type {
  DocumentListItem,
  DocumentVoidMethod,
  DocumentVoidTarget,
} from '@/types/finance';

export interface DocumentVoidCopy {
  title: string;
  description: string;
  confirmText: string;
  successMessage: string;
  /** `false` = ไม่ถามเหตุผล (legacy revert ไม่รับค่า reason) */
  reasonRequired: boolean;
  /** ข้อความบนปุ่มในแถว/หัวเอกสาร */
  actionLabel: string;
}

const COPY: Record<DocumentVoidMethod, DocumentVoidCopy> = {
  invoice: {
    title: 'ยกเลิกบิล / ใบแจ้งหนี้',
    description:
      'การยกเลิกจะเก็บเอกสารไว้เพื่อตรวจสอบย้อนหลัง และแสดงป้ายยกเลิกในทะเบียน — ถ้ามีใบเสร็จอ้างถึงบิลนี้ ระบบจะไม่ให้ยกเลิก',
    confirmText: 'ยืนยันยกเลิกบิล',
    successMessage: 'ยกเลิกบิลแล้ว — ยังเปิดดู/พิมพ์ได้พร้อมป้ายยกเลิก',
    reasonRequired: true,
    actionLabel: 'ยกเลิก',
  },
  payment_event: {
    title: 'ยกเลิกเหตุการณ์รับเงิน',
    description:
      'ระบบจะย้อนเงินเข้าบิล/เครดิตของนักเรียน และยกเลิกใบเสร็จที่ออกจากรายการรับเงินนี้ทั้งชุด — ย้อนกลับไม่ได้',
    confirmText: 'ยืนยันยกเลิกการรับเงิน',
    successMessage: 'ยกเลิกการรับเงินแล้ว — เงิน/เครดิต/บิลถูกย้อนกลับ',
    reasonRequired: true,
    actionLabel: 'ยกเลิก',
  },
  expense_voucher: {
    title: 'ยกเลิกใบสำคัญจ่าย',
    description:
      'ระบบจะคืนเงินเข้าทุกกระเป๋าที่จ่ายไป และยกเลิกใบรับรองแทนใบเสร็จที่ออกคู่กัน (ถ้ามี) — ย้อนกลับไม่ได้',
    confirmText: 'ยืนยันยกเลิกใบสำคัญจ่าย',
    successMessage: 'ยกเลิกใบสำคัญจ่ายแล้ว — เงินถูกคืนเข้ากระเป๋า',
    reasonRequired: true,
    actionLabel: 'ยกเลิก',
  },
  income_batch: {
    title: 'ยกเลิกใบรับเงิน',
    description:
      'ระบบจะหักเงินออกจากกระเป๋าตามยอดที่รับเข้าไป — ต้องมียอดคงเหลือพอ ไม่งั้นการยกเลิกจะถูกปฏิเสธ',
    confirmText: 'ยืนยันยกเลิกใบรับเงิน',
    successMessage: 'ยกเลิกใบรับเงินแล้ว — เงินถูกหักออกจากกระเป๋า',
    reasonRequired: true,
    actionLabel: 'ยกเลิก',
  },
  acknowledgement: {
    title: 'ยกเลิกใบรับทราบยอดค้าง',
    description:
      'เอกสารนี้เป็นเพียงหลักฐานการแจ้งยอดค้าง — การยกเลิกไม่กระทบเงินหรือเครดิตของนักเรียน',
    confirmText: 'ยืนยันยกเลิกใบรับทราบ',
    successMessage: 'ยกเลิกใบรับทราบยอดค้างแล้ว',
    reasonRequired: true,
    actionLabel: 'ยกเลิก',
  },
  monthly_report: {
    title: 'ยกเลิกรายงานปิดงบ',
    description:
      'ยกเลิกได้เฉพาะฉบับล่าสุดของเดือนนั้น — ไม่กระทบรายการเงินหรือใบเสร็จใด ๆ',
    confirmText: 'ยืนยันยกเลิกรายงาน',
    successMessage: 'ยกเลิกรายงานปิดงบแล้ว',
    reasonRequired: true,
    actionLabel: 'ยกเลิก',
  },
  legacy_transaction: {
    title: 'ย้อนกลับรายการ',
    description:
      'รายการนี้ถูกบันทึกก่อนระบบเอกสารรุ่นใหม่ — การย้อนกลับจะลบรายการออกจากบัญชี แต่ไม่ลบเอกสารนี้จากทะเบียน',
    confirmText: 'ยืนยันย้อนกลับรายการ',
    successMessage: 'ย้อนกลับรายการแล้ว',
    reasonRequired: false,
    actionLabel: 'ย้อนกลับรายการ',
  },
};

/** ข้อความบนปุ่ม — legacy ใช้ "ย้อนกลับรายการ" ไม่ใช่ "ยกเลิก" */
export function voidActionLabel(target?: DocumentVoidTarget | null): string {
  if (!target) return 'ยกเลิก';
  return COPY[target.method]?.actionLabel ?? 'ยกเลิก';
}

export function voidDialogCopy(target?: DocumentVoidTarget | null): DocumentVoidCopy {
  if (!target) return COPY.invoice;
  return COPY[target.method] ?? COPY.invoice;
}

export interface DispatchDocumentVoidArgs {
  roomId: number;
  doc: Pick<DocumentListItem, 'doc_type' | 'doc_id' | 'void_target'>;
  reason: string;
  /** ชื่อผู้ทำรายการ — legacy revert endpoint ต้องส่ง (ลง audit) */
  userName: string;
}

function requireId(target: DocumentVoidTarget): number {
  if (target.id === null) {
    throw new Error('เอกสารนี้ไม่มีรหัสอ้างอิงสำหรับยกเลิก — กรุณารีเฟรชหน้าแล้วลองใหม่');
  }
  return target.id;
}

function requireReceiptNo(target: DocumentVoidTarget): string {
  if (!target.receipt_no) {
    throw new Error('เอกสารนี้ไม่มีเลขที่สำหรับยกเลิก — กรุณารีเฟรชหน้าแล้วลองใหม่');
  }
  return target.receipt_no;
}

/**
 * เรียก endpoint void ตาม `void_target.method`
 *
 * ⚠️ legacy ไม่ส่ง `reason` — endpoint `revertTransaction` รับแค่ `user_name`
 *    (การบังคับกรอกเหตุผลต้องปิดที่ UI ด้วย `reasonRequired=false` ไม่ใช่ทิ้งเงียบ ๆ)
 */
export async function dispatchDocumentVoid({
  roomId,
  doc,
  reason,
  userName,
}: DispatchDocumentVoidArgs): Promise<void> {
  const target = doc.void_target;
  if (!target) throw new Error('เอกสารนี้ยกเลิกจากทะเบียนไม่ได้');

  switch (target.method) {
    case 'invoice':
      await FinanceService.voidDocument(roomId, 'invoice', doc.doc_id, { reason });
      return;
    case 'payment_event':
      await FinanceService.voidPaymentEvent(roomId, requireId(target), { reason });
      return;
    case 'expense_voucher':
      await FinanceService.voidExpenseVoucher(roomId, requireId(target), { reason });
      return;
    case 'income_batch':
      await FinanceService.voidIncomeBatch(roomId, requireId(target), { reason });
      return;
    case 'acknowledgement':
      await FinanceService.voidAcknowledgement(roomId, requireReceiptNo(target), { reason });
      return;
    case 'monthly_report':
      await FinanceService.voidMonthlyReport(roomId, requireId(target), { reason });
      return;
    case 'legacy_transaction':
      await FinanceService.revertTransaction(roomId, requireId(target), userName);
      return;
  }
}
