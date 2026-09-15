import { describe, it, expect } from 'vitest';
import {
  groupReceipts,
  batchDisplayName,
  batchVisibilityNote,
  batchVoidedNote,
  visibleNosOf,
  rowAmount,
  rowSelectionState,
  toggleRowSelection,
  selectedAmountOf,
  allVisibleSelected,
  type GroupableReceipt,
} from '@/utils/receiptGroups';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "ชุดเอกสาร" 3 ข้อที่พังแล้วเจ็บ (ดูหัวไฟล์ `utils/receiptGroups.ts`)
 *
 * ⚠️ ทุกเทสต์มี invariant คู่กันเสมอ: `groups.flatMap(items) + solos === input`
 *    ถ้าข้อนี้หลุด = เอกสารหายจากจอ = ผู้ใช้ตรวจไม่ได้ว่าขาดอะไร
 */

/**
 * ดึงสมาชิกที่ "ต้องมีอยู่" ออกจาก array
 *
 * ⚠️ จำเป็นเพราะ tsconfig เปิด `noUncheckedIndexedAccess` ⇒ `arr[0]` มีชนิด
 *    `T | undefined` และส่งต่อให้ฟังก์ชันที่รับ `T` ไม่ได้
 *    ใช้ helper นี้แทน `!` (non-null assertion) เพราะถ้าสมมติฐานผิดจะได้ error
 *    ที่บอกชื่อ index จริง ไม่ใช่ `undefined is not a function` ลอย ๆ
 */
const at = <T>(arr: readonly T[], i: number): T => {
  const value = arr[i];
  if (value === undefined) {
    throw new Error(`เทสต์คาดว่ามีสมาชิกที่ index ${i} แต่มีแค่ ${arr.length} ตัว`);
  }
  return value;
};

const doc = (receipt_no: string, over: Partial<GroupableReceipt> = {}): GroupableReceipt => ({
  receipt_no,
  amount: 100,
  batch_id: null,
  batch_title: null,
  batch_size: null,
  batch_voided_count: null,
  ...over,
});

/** 🔑 invariant ที่ต้องจริงทุกครั้ง — ไม่มีใบไหนหายและไม่มีใบไหนถูกนับซ้ำ */
const expectNoDocumentLost = (
  input: readonly GroupableReceipt[],
  result: ReturnType<typeof groupReceipts<GroupableReceipt>>,
) => {
  const seen = result.rows.flatMap((r) =>
    r.kind === 'batch' ? r.items.map((i) => i.receipt_no) : [r.item.receipt_no],
  );
  expect(seen.slice().sort()).toEqual(
    input
      .map((i) => i.receipt_no)
      .slice()
      .sort(),
  );
  expect(seen.length).toBe(input.length);
};

describe('groupReceipts', () => {
  it('ใบที่ batch_id = null ต้องเป็นแถวเดี่ยว ณ ตำแหน่งของตัวเอง', () => {
    const items = [doc('A'), doc('B'), doc('C')];
    const result = groupReceipts(items);

    expect(result.groups).toEqual([]);
    expect(result.solos.map((s) => s.receipt_no)).toEqual(['A', 'B', 'C']);
    expect(result.rows.map((r) => r.kind)).toEqual(['doc', 'doc', 'doc']);
    expectNoDocumentLost(items, result);
  });

  it('สมาชิกของชุดเดียวกันต้องรวมเป็นกลุ่มเดียว และเรียงตามลำดับที่ backend ส่งมา', () => {
    const items = [
      doc('A'),
      doc('B', { batch_id: 7, batch_size: 2 }),
      doc('C'),
      doc('D', { batch_id: 7, batch_size: 2 }),
    ];
    const result = groupReceipts(items);

    expect(result.rows.map((r) => r.key)).toEqual(['doc:A', 'batch:7', 'doc:C']);
    const group = at(result.groups, 0);
    expect(group.items.map((i) => i.receipt_no)).toEqual(['B', 'D']);
    expect(group.visibleCount).toBe(2);
    expectNoDocumentLost(items, result);
  });

  it('🔴 กลุ่มต้องไปปรากฏ ณ ตำแหน่งของสมาชิกที่ใหม่ที่สุด — ไม่ใช่ของตัวแรกที่เจอ', () => {
    // สมาชิกที่ใหม่ที่สุดคือ 'D' (ตำแหน่ง 1) ส่วน 'Z' เป็นสมาชิกเก่าที่ตามมาทีหลัง
    const items = [
      doc('A'),
      doc('D', { batch_id: 7, batch_size: 2 }),
      doc('B'),
      doc('Z', { batch_id: 7, batch_size: 2 }),
    ];
    const result = groupReceipts(items);

    expect(result.rows.map((r) => r.key)).toEqual(['doc:A', 'batch:7', 'doc:B']);
    const groupRow = at(result.rows, 1);
    expect(groupRow.kind).toBe('batch');
    if (groupRow.kind !== 'batch') throw new Error('แถวที่ 1 ต้องเป็นชุด');
    expect(groupRow.items.map((i) => i.receipt_no)).toEqual(['D', 'Z']);
    expectNoDocumentLost(items, result);
  });

  it('🔑 ขนาดชุดต้องมาจาก batch_size ของ backend ไม่ใช่จำนวนที่รอดตัวกรอง', () => {
    // สถานการณ์จริง: ชุดมี 20 ใบ แต่กรองช่วงวันที่แล้วเหลือ 3 ใบ
    const items = [
      doc('A', { batch_id: 7, batch_size: 20, batch_voided_count: 2 }),
      doc('B', { batch_id: 7, batch_size: 20, batch_voided_count: 2 }),
      doc('C', { batch_id: 7, batch_size: 20, batch_voided_count: 2 }),
    ];
    const group = at(groupReceipts(items).groups, 0);

    expect(group.visibleCount).toBe(3);
    expect(group.batchSize).toBe(20);
    expect(group.activeCount).toBe(18); // 20 - 2 ที่ถูกยกเลิก
    expect(group.isPartiallyVisible).toBe(true);
    expect(batchVisibilityNote(group)).toBe('แสดง 3 จาก 20 ใบ');
    // 🧪 ถ้ามีใครเปลี่ยนไปใช้ items.length ที่นี่ ตัวเลขนี้จะกลายเป็น 3 แล้วเทสต์ล้ม
    expect(batchDisplayName(group)).toBe('ชุดเอกสาร 20 ใบ');
    expectNoDocumentLost(items, groupReceipts(items));
  });

  it('เห็นครบทั้งชุด → isPartiallyVisible = false และไม่มีข้อความกำกับ', () => {
    const items = [
      doc('A', { batch_id: 7, batch_size: 2 }),
      doc('B', { batch_id: 7, batch_size: 2 }),
    ];
    const group = at(groupReceipts(items).groups, 0);

    expect(group.isPartiallyVisible).toBe(false);
    expect(batchVisibilityNote(group)).toBeNull();
  });

  it('ยอดรวมของกลุ่มนับเฉพาะสมาชิกที่เห็นบนจอ', () => {
    const items = [
      doc('A', { amount: 500.5, batch_id: 7, batch_size: 20 }),
      doc('B', { amount: 249.5, batch_id: 7, batch_size: 20 }),
    ];
    const group = at(groupReceipts(items).groups, 0);

    expect(group.visibleAmount).toBe(750);
    expect(rowAmount(group)).toBe(750);
  });

  it('ชื่อที่ผู้ใช้ตั้งไว้ต้องชนะชื่อที่ระบบประกอบ', () => {
    const group = at(
      groupReceipts([doc('A', { batch_id: 7, batch_size: 3, batch_title: 'ชุดผู้ปกครอง' })]).groups,
      0,
    );

    expect(batchDisplayName(group)).toBe('ชุดผู้ปกครอง');
  });

  it('ข้อความ "ยกเลิก N" ต้องไม่โชว์เมื่อไม่มีใบถูกยกเลิก', () => {
    const none = at(groupReceipts([doc('A', { batch_id: 7, batch_size: 1 })]).groups, 0);
    expect(batchVoidedNote(none)).toBeNull();

    const some = at(
      groupReceipts([doc('A', { batch_id: 7, batch_size: 5, batch_voided_count: 3 })]).groups,
      0,
    );
    expect(batchVoidedNote(some)).toBe('ยกเลิก 3');
  });

  it('🛡️ backend ไม่ส่ง batch_size มา → ถอยไปใช้จำนวนที่เห็น ไม่ใช่ NaN หรือ 0', () => {
    const group = at(
      groupReceipts([doc('A', { batch_id: 7 }), doc('B', { batch_id: 7 })]).groups,
      0,
    );

    expect(group.batchSize).toBe(2);
    expect(group.activeCount).toBe(2);
    expect(Number.isNaN(group.batchSize)).toBe(false);
    expect(batchDisplayName(group)).toBe('ชุดเอกสาร 2 ใบ');
  });

  it('🛡️ ค่าที่ backend ส่งมาเพี้ยน (ติดลบ / ไม่ใช่ตัวเลข) ต้องไม่ทำให้ยอดรวมกลายเป็น NaN', () => {
    const group = at(
      groupReceipts([
        doc('A', { amount: Number.NaN, batch_id: 7, batch_size: -5, batch_voided_count: -1 }),
      ]).groups,
      0,
    );

    expect(group.batchSize).toBe(1); // ถอยไปใช้จำนวนที่เห็น
    expect(group.voidedCount).toBe(0);
    expect(group.visibleAmount).toBe(0);
    expect(batchDisplayName(group)).toBe('ชุดเอกสาร 1 ใบ');
  });

  it('หลายชุดพร้อมกันต้องไม่ปนกัน และคงลำดับที่ backend ส่งมา', () => {
    const items = [
      doc('A', { batch_id: 1, batch_size: 2 }),
      doc('B', { batch_id: 2, batch_size: 1 }),
      doc('C'),
      doc('D', { batch_id: 1, batch_size: 2 }),
    ];
    const result = groupReceipts(items);

    expect(result.rows.map((r) => r.key)).toEqual(['batch:1', 'batch:2', 'doc:C']);
    expect(result.groups.map((g) => g.batchId)).toEqual([1, 2]);
    expect(at(result.groups, 0).items.map((i) => i.receipt_no)).toEqual(['A', 'D']);
    expectNoDocumentLost(items, result);
  });

  it('รายการว่างต้องได้ผลลัพธ์ว่างที่ใช้งานได้ (ไม่ throw)', () => {
    const result = groupReceipts([]);

    expect(result.rows).toEqual([]);
    expect(result.groups).toEqual([]);
    expect(allVisibleSelected(result.rows, [])).toBe(false);
  });
});

describe('การติ๊กเลือก', () => {
  const grouped = () =>
    groupReceipts([
      doc('A', { amount: 100 }),
      doc('B', { amount: 200, batch_id: 7, batch_size: 20 }),
      doc('C', { amount: 300, batch_id: 7, batch_size: 20 }),
    ]);

  /** ชุด = แถวที่ 1 ของ `rows` (แถว 0 คือเอกสารเดี่ยว 'A') */
  const batchRow = (rows: ReturnType<typeof grouped>['rows']) => {
    const row = at(rows, 1);
    if (row.kind !== 'batch') throw new Error('แถวที่ 1 ต้องเป็นชุด');
    return row;
  };

  it('🔑 ติ๊กชุด = เลือก **เฉพาะสมาชิกที่เห็นบนจอ** ไม่ใช่ทั้ง 20 ใบที่มองไม่เห็น', () => {
    const { rows } = grouped();
    const group = batchRow(rows);
    const selected = toggleRowSelection(group, []);

    // ⛔ ถ้ามีใครเปลี่ยนไปใช้ batchSize ที่นี่ จะได้ 20 ใบ ซึ่งโหลดเอกสารที่ผู้ใช้ตรวจไม่ได้
    expect(selected).toEqual(['B', 'C']);
    expect(selected).toHaveLength(group.visibleCount);
    expect(visibleNosOf(group)).toEqual(['B', 'C']);
  });

  it('แถวเดี่ยวติ๊กได้ตามปกติ', () => {
    const { rows } = grouped();
    const solo = at(rows, 0);

    expect(toggleRowSelection(solo, [])).toEqual(['A']);
    expect(toggleRowSelection(solo, ['A'])).toEqual([]);
  });

  it("🔴 ต้องแยกสถานะ 'some' ออกจาก 'none' — ไม่งั้นกดติ๊กจะล้างใบที่เลือกไว้", () => {
    const { rows } = grouped();
    const group = batchRow(rows);

    expect(rowSelectionState(group, [])).toBe('none');
    expect(rowSelectionState(group, ['B'])).toBe('some');
    expect(rowSelectionState(group, ['B', 'C'])).toBe('all');
    // ติ๊กครบแล้วกดอีกครั้ง = ยกเลิกทั้งชุด
    expect(toggleRowSelection(group, ['B', 'C'])).toEqual([]);
  });

  it('ติ๊กบางใบแล้วกด → เติมให้ครบโดยไม่ทิ้งใบอื่นที่ติ๊กไว้', () => {
    const { rows } = grouped();

    expect(toggleRowSelection(batchRow(rows), ['A', 'B'])).toEqual(['A', 'B', 'C']);
  });

  it('ยอดรวมที่นับได้ตรงกับเลขที่ติ๊ก และไม่นับใบที่หลุดตัวกรอง', () => {
    const { rows } = grouped();

    expect(selectedAmountOf(rows, [])).toBe(0);
    expect(selectedAmountOf(rows, ['A'])).toBe(100);
    expect(selectedAmountOf(rows, ['B', 'C'])).toBe(500);
    // เลขที่ที่ไม่ปรากฏบนจอ (หลุดตัวกรองไปแล้ว) ต้องไม่ถูกนับ — ไม่ใช่ throw
    expect(selectedAmountOf(rows, ['B', 'C', 'ZZZ-9999-9999'])).toBe(500);
  });

  it('"เลือกทั้งหมด" ต้องนับสมาชิกในชุดด้วย ไม่ใช่แค่แถวเดี่ยว', () => {
    const { rows } = grouped();

    expect(allVisibleSelected(rows, ['A', 'B'])).toBe(false);
    expect(allVisibleSelected(rows, ['A', 'B', 'C'])).toBe(true);
  });

  it('toggleRowSelection ต้องไม่แก้ array ที่ส่งเข้ามา (pure)', () => {
    const { rows } = grouped();
    const original = ['A'];
    toggleRowSelection(batchRow(rows), original);

    expect(original).toEqual(['A']);
  });
});
