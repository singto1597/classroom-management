import { describe, expect, it } from 'vitest';

import {
  DEFAULT_DOC_TYPES,
  DOCUMENT_BUNDLE_MAX,
  DOC_TYPES,
  EXPENSE_DOC_TYPES,
  INCOME_DOC_TYPES,
  canPrintBundle,
  buildDocumentQuery,
  selectionKey,
  typeLabel,
} from '@/utils/documentFilters';
import type { DocumentType } from '@/types/finance';

/**
 * 🔒 ล็อกสัญญาของทะเบียนเอกสาร (FIN-V2 / P5.2)
 *
 * สิ่งที่เทสต์กัน:
 *  - query ที่ส่ง API มีแต่คีย์ที่มีค่า (axios ส่ง `null`/`''` เป็นสตริงขยะ → 422)
 *  - `status: 'all'` แปลงเป็น `include_voided=true` (backend รับแค่ active/voided)
 *  - selection ใช้ composite key — id ชนกันข้ามตารางได้จริง
 *  - เพดานพิมพ์ชุด 1–100 ตรงกับ backend
 *  - ป้ายไทยครบทั้ง 8 ชนิด + fallback ไม่ throw
 */
describe('buildDocumentQuery', () => {
  it('ตัดค่าว่าง/null ออกและคง limit ไว้', () => {
    const out = buildDocumentQuery({
      from: '',
      to: '',
      q: '   ',
      student_id: null,
      receiver_id: null,
      channel_id: null,
      limit: 50,
      offset: 0,
    });

    expect(out).toEqual({ limit: 50, offset: 0 });
  });

  it('แปลง status=all → include_voided=true และไม่ส่ง status', () => {
    const out = buildDocumentQuery({ status: 'all' });

    expect(out).toEqual({ include_voided: 'true' });
    expect(out.status).toBeUndefined();
  });

  it('status active/voided ส่งตรงตามค่า', () => {
    expect(buildDocumentQuery({ status: 'active' })).toEqual({ status: 'active' });
    expect(buildDocumentQuery({ status: 'voided' })).toEqual({ status: 'voided' });
  });

  it('รวม doc_types เป็นสตริงคั่นจุลภาค + ตัดช่องว่างของ q', () => {
    const out = buildDocumentQuery({
      doc_types: ['receipt', 'monthly_report'],
      q: '  REC-2569  ',
    });

    expect(out).toEqual({ doc_types: 'receipt,monthly_report', q: 'REC-2569' });
  });

  it('doc_types ว่าง = ไม่กรอง (ไม่ส่งคีย์)', () => {
    expect(buildDocumentQuery({ doc_types: [] })).toEqual({});
  });
});

describe('selectionKey', () => {
  it('ต่างกันตาม doc_type แม้ doc_id เท่ากัน', () => {
    const receipt = selectionKey({ doc_type: 'receipt', doc_id: 12 });
    const report = selectionKey({ doc_type: 'monthly_report', doc_id: 12 });

    expect(receipt).toBe('receipt:12');
    expect(report).toBe('monthly_report:12');
    expect(receipt).not.toBe(report);
  });
});

describe('canPrintBundle', () => {
  it('false เมื่อ 0 หรือเกิน 100', () => {
    expect(canPrintBundle(0)).toBe(false);
    expect(canPrintBundle(DOCUMENT_BUNDLE_MAX + 1)).toBe(false);
    expect(canPrintBundle(-1)).toBe(false);
    expect(canPrintBundle(1.5)).toBe(false);
  });

  it('true เมื่อ 1–100', () => {
    expect(canPrintBundle(1)).toBe(true);
    expect(canPrintBundle(DOCUMENT_BUNDLE_MAX)).toBe(true);
  });
});

describe('typeLabel', () => {
  it('คืนป้ายไทยครบทั้ง 8 ชนิด', () => {
    const expected: Record<DocumentType, string> = {
      receipt: 'ใบเสร็จรับเงิน',
      invoice: 'ใบแจ้งหนี้',
      acknowledgement: 'ใบรับทราบยอดค้าง',
      deposit: 'ใบรับเงินล่วงหน้า',
      payment_voucher: 'ใบสำคัญจ่าย',
      certificate: 'ใบรับรองแทนใบเสร็จ',
      income: 'ใบรับเงิน',
      monthly_report: 'รายงานปิดงบ',
    };

    expect(DOC_TYPES).toHaveLength(8);
    for (const docType of DOC_TYPES) {
      expect(typeLabel(docType)).toBe(expected[docType]);
    }
  });

  it('fallback เป็นรหัสดิบเมื่อไม่รู้จัก (ไม่ throw)', () => {
    expect(typeLabel('purchase_order')).toBe('purchase_order');
  });
});

describe('ตัวกรองเริ่มต้น (รายรับ + รายจ่าย)', () => {
  it('ค่าเริ่มต้นรวมเฉพาะเอกสารเงินเข้า/ออก ไม่รวมใบแจ้งหนี้/ACK/RPT', () => {
    expect(new Set(DEFAULT_DOC_TYPES)).toEqual(
      new Set([...INCOME_DOC_TYPES, ...EXPENSE_DOC_TYPES]),
    );
    expect(DEFAULT_DOC_TYPES).toContain('receipt');
    expect(DEFAULT_DOC_TYPES).toContain('income');
    expect(DEFAULT_DOC_TYPES).toContain('payment_voucher');
    expect(DEFAULT_DOC_TYPES).not.toContain('invoice');
    expect(DEFAULT_DOC_TYPES).not.toContain('acknowledgement');
    expect(DEFAULT_DOC_TYPES).not.toContain('monthly_report');
  });
});
