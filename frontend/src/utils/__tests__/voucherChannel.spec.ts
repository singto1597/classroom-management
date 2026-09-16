import { describe, it, expect } from 'vitest';
import { voucherChannel } from '@/utils/voucherChannel';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "ช่องทางจ่ายเงิน" ของใบสำคัญจ่าย
 *
 * 💥 บั๊กจริง (2026-09, มือถือ Android/Chrome): ใบสำคัญจ่าย**ทุกใบ** รวมใบที่จ่ายเงินสด
 *    ขึ้นว่า "โอนเข้าบัญชี" — เพราะ `account_kind` มาเป็น `undefined` (backend
 *    `response_model` ตัดคีย์ทิ้ง) และของเดิมเทียบด้วย `=== null` ซึ่งเป็น false
 *    ⇒ ตกไปสาขาสุดท้าย · ไม่มี error ไม่มีจอขาว ⇒ **เอกสารบอกเงินสด แต่จอบอกโอน**
 *
 * ⚠️ เคส `undefined` **ต้องมีเทสต์ของตัวเอง** ไม่ใช่ใช้ `null` แทน — สองค่านี้ให้ผล
 *    ต่างกันกับ `=== null` ซึ่งเป็นกลไกของบั๊กทั้งดวง (เทสต์ที่ส่งแต่ `null` จะเขียว
 *    ทั้งที่โค้ดแบบเดิมก็เขียว)
 */
describe('voucherChannel', () => {
  it('เงินสด ⇒ "เงินสด" ไม่ใช่ "โอนเข้าบัญชี"', () => {
    expect(voucherChannel({ account_kind: 'cash' })).toBe('เงินสด');
  });

  it('โอน + ข้อมูลธนาคาร ⇒ ต่อท้ายด้วยรายละเอียดที่กรอกไว้', () => {
    expect(
      voucherChannel({
        account_kind: 'transfer',
        bank_name: 'ธ.ไทยพาณิชย์',
        bank_account_no: '123-4-56789-0',
        bank_account_name: 'นายสมชาย ใจดี',
      }),
    ).toBe('โอนเข้าบัญชี — ธ.ไทยพาณิชย์ · 123-4-56789-0 · นายสมชาย ใจดี');
  });

  it('โอนแต่ยังไม่กรอกธนาคาร ⇒ "โอนเข้าบัญชี" เฉย ๆ ไม่ใช่สตริงว่าง', () => {
    expect(voucherChannel({ account_kind: 'transfer' })).toBe('โอนเข้าบัญชี');
    expect(voucherChannel({ account_kind: 'transfer', bank_name: '' })).toBe('โอนเข้าบัญชี');
  });

  it('🔴 `account_kind` เป็น `undefined` ⇒ ซ่อน (ไม่เดาว่าโอน)', () => {
    // เคสนี้คือบั๊กจริง — `undefined` คือสิ่งที่ได้เมื่อคีย์ถูกตัดที่ชั้น serialization
    expect(voucherChannel({ account_kind: undefined })).toBeNull();
    expect(voucherChannel({ bank_name: 'ธ.กรุงไทย' })).toBeNull();
  });

  it('`account_kind` เป็น `null` ⇒ ซ่อน (สัญญา "ไม่มีค่า")', () => {
    expect(voucherChannel({ account_kind: null })).toBeNull();
  });

  it('🔴 ค่าที่ไม่รู้จัก ⇒ ซ่อน ห้ามตีความเป็น "โอนเข้าบัญชี"', () => {
    // `AccountKind` ฝั่ง TS บอกว่ามีแค่ cash|transfer แต่ backend เป็น `Optional[str]`
    // โดยเจตนา ⇒ ค่าใหม่มาถึงที่นี่ได้จริง และต้องไม่ถูก "แต่ง" ขึ้นเอง
    expect(voucherChannel({ account_kind: 'e_wallet' })).toBeNull();
    expect(voucherChannel({ account_kind: 'CASH' })).toBeNull(); // ตัวพิมพ์ใหญ่ = คนละค่า
    expect(voucherChannel({ account_kind: 'transfer ', bank_name: 'ธ.กรุงไทย' })).toBeNull();
  });

  it('ตัวเอกสารเองเป็น null/undefined ⇒ ซ่อน (ยังโหลดไม่เสร็จ)', () => {
    expect(voucherChannel(null)).toBeNull();
    expect(voucherChannel(undefined)).toBeNull();
  });

  it('ข้อมูลธนาคารที่ไม่ใช่สตริงถูกกรองออก ไม่โผล่เป็น "undefined" บนจอ', () => {
    expect(
      voucherChannel({
        account_kind: 'transfer',
        bank_name: null,
        bank_account_no: undefined,
        bank_account_name: 'นายสมชาย ใจดี',
      }),
    ).toBe('โอนเข้าบัญชี — นายสมชาย ใจดี');
  });
});
