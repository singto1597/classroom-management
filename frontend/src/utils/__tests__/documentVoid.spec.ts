import { beforeEach, describe, expect, it, vi } from 'vitest';

import { FinanceService } from '@/services/finance';
import {
  dispatchDocumentVoid,
  voidActionLabel,
  voidDialogCopy,
} from '@/utils/documentVoid';
import type { DocumentVoidTarget } from '@/types/finance';

/**
 * 🚫 `dispatchDocumentVoid` — จุดเดียวที่เลือก endpoint void ตาม `void_target`
 *
 * บั๊กที่มันกัน: จอเดา endpoint จาก `doc_type` แล้วเรียกผิด
 * (เช่น REC ยกเลิกผ่าน `/documents/receipt/{id}/void` ที่ backend 409)
 * ⇒ เทสต์ผูก method → service ให้ครบทุกตัว และเช็คว่า legacy **ไม่ส่ง reason**
 */
type VoidFn = (...args: unknown[]) => Promise<unknown>;

vi.mock('@/services/finance', () => ({
  FinanceService: {
    voidDocument: vi.fn<VoidFn>(),
    voidPaymentEvent: vi.fn<VoidFn>(),
    voidExpenseVoucher: vi.fn<VoidFn>(),
    voidIncomeBatch: vi.fn<VoidFn>(),
    voidAcknowledgement: vi.fn<VoidFn>(),
    voidMonthlyReport: vi.fn<VoidFn>(),
    revertTransaction: vi.fn<VoidFn>(),
  },
}));

const mocked = vi.mocked(FinanceService);

const DOC = { doc_type: 'receipt' as const, doc_id: 10 };

const target = (over: Partial<DocumentVoidTarget>): DocumentVoidTarget => ({
  method: 'invoice',
  id: 10,
  receipt_no: null,
  ...over,
});

const ALL_MOCKS = [
  mocked.voidDocument,
  mocked.voidPaymentEvent,
  mocked.voidExpenseVoucher,
  mocked.voidIncomeBatch,
  mocked.voidAcknowledgement,
  mocked.voidMonthlyReport,
  mocked.revertTransaction,
];

describe('dispatchDocumentVoid', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const fn of ALL_MOCKS) fn.mockResolvedValue(undefined as never);
  });

  it('invoice → voidDocument ด้วย doc_type/doc_id ของแถว', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: { ...DOC, void_target: target({ method: 'invoice', id: 10 }) },
      reason: 'ผิดคน',
      userName: 'นาย สมชาย',
    });
    expect(mocked.voidDocument).toHaveBeenCalledWith(7, 'invoice', 10, { reason: 'ผิดคน' });
  });

  it('payment_event → voidPaymentEvent ด้วย event id (ไม่ใช่ doc_id ของใบเสร็จ)', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: { ...DOC, void_target: target({ method: 'payment_event', id: 77 }) },
      reason: 'ผิด',
      userName: 'นาย สมชาย',
    });
    expect(mocked.voidPaymentEvent).toHaveBeenCalledWith(7, 77, { reason: 'ผิด' });
  });

  it('expense_voucher → voidExpenseVoucher', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: { ...DOC, doc_type: 'payment_voucher', void_target: target({ method: 'expense_voucher', id: 42 }) },
      reason: 'ผิด',
      userName: 'นาย สมชาย',
    });
    expect(mocked.voidExpenseVoucher).toHaveBeenCalledWith(7, 42, { reason: 'ผิด' });
  });

  it('income_batch → voidIncomeBatch', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: { ...DOC, doc_type: 'income', void_target: target({ method: 'income_batch', id: 5 }) },
      reason: 'ผิด',
      userName: 'นาย สมชาย',
    });
    expect(mocked.voidIncomeBatch).toHaveBeenCalledWith(7, 5, { reason: 'ผิด' });
  });

  it('acknowledgement → voidAcknowledgement ด้วย receipt_no', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: {
        ...DOC,
        doc_type: 'acknowledgement',
        void_target: target({ method: 'acknowledgement', id: null, receipt_no: 'ACK-2569-0001' }),
      },
      reason: 'ผิด',
      userName: 'นาย สมชาย',
    });
    expect(mocked.voidAcknowledgement).toHaveBeenCalledWith(7, 'ACK-2569-0001', {
      reason: 'ผิด',
    });
  });

  it('monthly_report → voidMonthlyReport', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: {
        ...DOC,
        doc_type: 'monthly_report',
        void_target: target({ method: 'monthly_report', id: 3 }),
      },
      reason: 'ผิด',
      userName: 'นาย สมชาย',
    });
    expect(mocked.voidMonthlyReport).toHaveBeenCalledWith(7, 3, { reason: 'ผิด' });
  });

  it('legacy_transaction → revertTransaction และไม่ส่ง reason (endpoint ไม่รับ)', async () => {
    await dispatchDocumentVoid({
      roomId: 7,
      doc: { ...DOC, void_target: target({ method: 'legacy_transaction', id: 88 }) },
      reason: 'ผู้ใช้พิมพ์มาแต่ไม่ควรถูกส่ง',
      userName: 'นาย สมชาย',
    });
    expect(mocked.revertTransaction).toHaveBeenCalledWith(7, 88, 'นาย สมชาย');
    expect(mocked.revertTransaction).toHaveBeenCalledTimes(1);
  });

  it('ไม่มี void_target → โยน error และไม่เรียก service ใดเลย', async () => {
    await expect(
      dispatchDocumentVoid({
        roomId: 7,
        doc: { ...DOC, void_target: null },
        reason: 'x',
        userName: 'นาย สมชาย',
      }),
    ).rejects.toThrow('ยกเลิกจากทะเบียนไม่ได้');
    for (const fn of ALL_MOCKS) expect(fn).not.toHaveBeenCalled();
  });
});

describe('ข้อความบนจอ', () => {
  it('legacy ใช้ "ย้อนกลับรายการ" และไม่บังคับเหตุผล', () => {
    const t = target({ method: 'legacy_transaction', id: 1 });
    expect(voidActionLabel(t)).toBe('ย้อนกลับรายการ');
    expect(voidDialogCopy(t).reasonRequired).toBe(false);
  });

  it.each([
    ['invoice', 'ยกเลิก'],
    ['payment_event', 'ยกเลิก'],
    ['expense_voucher', 'ยกเลิก'],
    ['income_batch', 'ยกเลิก'],
    ['acknowledgement', 'ยกเลิก'],
    ['monthly_report', 'ยกเลิก'],
  ] as const)('%s บังคับเหตุผล', (method, label) => {
    const t = target({ method });
    expect(voidActionLabel(t)).toBe(label);
    expect(voidDialogCopy(t).reasonRequired).toBe(true);
  });

  it('ไม่มี target → ค่าเริ่มต้นแบบยกเลิกได้', () => {
    expect(voidActionLabel(null)).toBe('ยกเลิก');
    expect(voidDialogCopy(null).reasonRequired).toBe(true);
  });
});
