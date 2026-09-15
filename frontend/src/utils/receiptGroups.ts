/**
 * 📚 [F5] จัดกลุ่มทะเบียนเอกสารเป็น "ชุด" — ตรรกะบริสุทธิ์ (ไม่มี Vue, ไม่มี DOM)
 *
 * 🔴 **ไฟล์นี้มีอยู่เพราะข้อผิดพลาดที่มันกันไว้แพงมาก** — ทะเบียนโหลดได้ถึง 500 แถวและ
 *    ถูกกรองด้วยช่วงวันที่ ⇒ กลุ่มที่ประกอบที่หน้าจอ **ไม่เคยมีสมาชิกครบ** โดยธรรมชาติ
 *    ถ้าเผลอใช้ `items.length` เป็น "ขนาดชุด" ผู้ใช้จะอ่านว่า "ชุดนี้มี 3 ใบ" ทั้งที่ในชุด
 *    มี 20 ใบ แล้วโหลด PDF ขาดไป 17 ใบโดยไม่มีอะไรฟ้อง ⇒ ขนาดชุดต้องมาจาก
 *    `batch_size` ของ backend **เสมอ** (ดู `docs/skills.md` เรื่อง window function)
 *
 * 🎯 กติกา 3 ข้อที่ล็อกไว้:
 *
 * 1. **ห้ามมีเอกสารหายจากจอ** — ใบที่มี `batch_id` จะต้องโผล่ในกลุ่มของตัวเองเสมอ
 *    (แม้เป็นสมาชิกที่หลงเหลืออยู่ใบเดียวหลังกรอง) และใบที่ `batch_id` เป็น `null`
 *    กลายเป็นแถวเดี่ยว ⇒ `ผลรวมของทุกกลุ่ม + แถวเดี่ยว === items.length` เสมอ
 *
 * 2. **ไม่เรียงใหม่** — ลำดับบนจอต้องเป็นลำดับที่ backend ส่งมา (`_DOC_DATE DESC, id DESC`)
 *    กลุ่มจะไปปรากฏ ณ ตำแหน่งของสมาชิกที่ **ใหม่ที่สุด** ที่รอดตัวกรอง และสมาชิกที่เหลือ
 *    ของกลุ่มนั้นถูกดึงขึ้นมาอยู่ด้วยกัน ⇒ การเรียงที่หน้าจอไม่สามารถขัดกับ backend ได้
 *    (ถ้าเรา sort กลุ่มเองด้วยวันที่สูงสุดของกลุ่ม วันเดียวกันหลายใบจะสลับกันแบบสุ่ม)
 *
 * 3. **ติ๊ก = เฉพาะที่เห็นบนจอ** — หน้านี้ยึดหลัก "ทำงานกับสิ่งที่ผู้ใช้เห็น" มาตั้งแต่ F3
 *    (`ReceiptList.vue` ตัด `selectedNos` ที่หลุดตัวกรองทิ้งทุกครั้งที่โหลด) ⇒ ติ๊กชุด
 *    ที่แสดง 3 จาก 20 ใบ ต้องเลือก **3 ใบ** แล้วให้ป้ายบอกตรง ๆ ว่า "แสดง 3 จาก 20 ใบ"
 *    ไม่ใช่แอบเลือก 17 ใบที่ผู้ใช้มองไม่เห็นแล้วโหลดเอกสารที่ตรวจไม่ได้ลงเครื่อง
 *
 * ⚠️ ไฟล์นี้ **ไม่รู้จัก** `ReceiptListItem` โดยตรง — รับ generic ที่มีฟิลด์ที่ต้องใช้
 *    ⇒ เทสต์ได้ด้วยออบเจ็กต์จิ๋ว และไม่ผูกกับ schema ที่อาจเพิ่มฟิลด์อีก
 */

/** ฟิลด์ขั้นต่ำที่ตัวจัดกลุ่มต้องใช้ (เป็น subset ของ `ReceiptListItem`) */
export interface GroupableReceipt {
  receipt_no: string;
  amount: number;
  batch_id: number | null;
  /** `null` = ให้หน้าจอประกอบชื่อเอง */
  batch_title?: string | null;
  /** ขนาด **ทั้งชุด** จาก backend — `null` = ไม่รู้ (ไม่ควรเกิด) ⇒ ถอยไปใช้จำนวนที่เห็น */
  batch_size?: number | null;
  batch_voided_count?: number | null;
}

/** กลุ่มที่ **พร้อมแสดง** — ตัวเลขทุกตัวคำนวณเสร็จแล้ว ไม่ต้องคิดต่อที่ template */
export interface ReceiptGroup<T extends GroupableReceipt> {
  kind: 'batch';
  /** คีย์ของ `v-for` — ใช้ `batch_id` ตรง ๆ ได้เพราะกลุ่มถูกสร้างจาก id นั้น */
  key: string;
  batchId: number;
  /** ชื่อที่ผู้ใช้ตั้งไว้ หรือ `null` ให้ template เรียก `batchDisplayName` */
  title: string | null;
  /** สมาชิกที่ **เห็นบนจอตอนนี้** (subset ของทั้งชุด) */
  items: T[];
  /** จำนวนที่เห็นบนจอ = `items.length` (มีไว้ให้ template อ่านง่าย ไม่ต้อง `.length`) */
  visibleCount: number;
  /** ขนาด **ทั้งชุด** ตาม backend */
  batchSize: number;
  /** จำนวนสมาชิกทั้งชุดที่ถูกยกเลิก/ลบ */
  voidedCount: number;
  /** สมาชิกทั้งชุดที่ยัง active และยังไม่ถูกกรองออก — ใช้เทียบว่ากรองตัดไปกี่ใบ */
  activeCount: number;
  /** ยอดรวม **เฉพาะที่เห็นบนจอ** (ใบที่ถูกยกเลิกไม่ถูกส่งมาในทะเบียนอยู่แล้ว) */
  visibleAmount: number;
  /** `true` = ตัวกรองตัดสมาชิกออก ⇒ ต้องบอกผู้ใช้ ไม่ใช่ปล่อยให้อ่านว่า "มีเท่านี้" */
  isPartiallyVisible: boolean;
}

/** แถวเดี่ยว (ไม่อยู่ในชุด) */
export interface ReceiptSoloRow<T extends GroupableReceipt> {
  kind: 'doc';
  key: string;
  item: T;
}

export type ReceiptRow<T extends GroupableReceipt> = ReceiptGroup<T> | ReceiptSoloRow<T>;

export interface GroupedReceipts<T extends GroupableReceipt> {
  /** แถวพร้อมแสดง เรียงตามลำดับที่ backend ส่งมา */
  rows: ReceiptRow<T>[];
  groups: ReceiptGroup<T>[];
  /** ใบที่ไม่ได้อยู่ในชุด (ยังต้องแสดงเป็นแถวเดี่ยว) */
  solos: T[];
}

/**
 * จัดกลุ่มทะเบียนเป็นแถวพร้อมแสดง — ดูกติกา 3 ข้อบนหัวไฟล์
 *
 * @param items แถวจาก `FinanceService.getReceipts` **ตามลำดับที่ได้มา** (ห้าม sort ก่อนส่ง)
 */
export function groupReceipts<T extends GroupableReceipt>(items: readonly T[]): GroupedReceipts<T> {
  const groups = new Map<number, ReceiptGroup<T>>();
  const solos: T[] = [];
  const rows: ReceiptRow<T>[] = [];

  for (const item of items) {
    // 🕳️ `batch_id` เป็น null/undefined = ไม่ได้จัดกลุ่ม ⇒ แถวเดี่ยว ณ ตำแหน่งของตัวเอง
    if (item.batch_id === null || item.batch_id === undefined) {
      solos.push(item);
      rows.push({ kind: 'doc', key: `doc:${item.receipt_no}`, item });
      continue;
    }

    const existing = groups.get(item.batch_id);
    if (existing) {
      // สมาชิกตัวถัดไปของกลุ่มที่เจอแล้ว ⇒ เก็บเข้าที่ ไม่สร้างแถวใหม่
      existing.items.push(item);
      existing.visibleCount = existing.items.length;
      existing.visibleAmount += toAmount(item.amount);
      continue;
    }

    // 🆕 เจอสมาชิกตัวแรกของชุดนี้ ⇒ สร้างกลุ่ม **ณ ตำแหน่งนี้** (กติกาข้อ 2)
    const group = buildGroup(item);
    groups.set(item.batch_id, group);
    rows.push(group);
  }

  // 🔁 ค่าที่ **derive ได้** (`batchSize`/`activeCount`/`isPartiallyVisible`) คำนวณที่เดียว
  //    ตรงนี้หลังลูปจบ — ไม่คำนวณระหว่างทาง
  //    🧪 บทเรียนจากการเขียนไฟล์นี้: ตอนแรกคำนวณใน `buildGroup` (ตอนเจอสมาชิกตัวแรก)
  //       ผลคือกลุ่มที่มีสมาชิกตามมาทีหลังยังประกาศ `batchSize`/`activeCount` ของตอนที่มี
  //       สมาชิกใบเดียว ⇒ "ชุดเอกสาร 1 ใบ" ทั้งที่มี 2 ใบ · การคำนวณแบบกระจายมีจุดที่ต้อง
  //       อัปเดตหลายจุดและลืมง่ายกว่าการรวมมาไว้ที่เดียวมาก
  for (const group of groups.values()) {
    // 🛡️ `Math.max` ไม่ใช่การเขียนทับ: ทางเดียวที่ `visibleCount` แซง `batchSize` ได้คือ
    //    ทางถอย (backend ไม่ได้ส่ง `batch_size` มา) ⇒ ต้องให้ขนาดโตตามสมาชิกที่เห็น
    //    ส่วนกรณีปกติ (backend ส่ง 20 มา แต่เห็น 3) `max` คง 20 ไว้ = ไม่รายงานต่ำกว่าจริง
    group.batchSize = Math.max(group.batchSize, group.visibleCount);
    group.activeCount = Math.max(0, group.batchSize - group.voidedCount);
    group.isPartiallyVisible = group.visibleCount < group.batchSize;
  }

  return { rows, groups: [...groups.values()], solos };
}

/**
 * สร้างกลุ่มจากสมาชิกตัวแรก — ใส่ค่า **ดิบ** ไว้ก่อน แล้วให้ `groupReceipts` derive
 * `batchSize`/`activeCount`/`isPartiallyVisible` ทีหลัง (ดูคอมเมนต์ตรงลูป)
 */
function buildGroup<T extends GroupableReceipt>(first: T): ReceiptGroup<T> {
  const batchId = first.batch_id as number;

  // 🔴 `batch_size` มาจาก backend เท่านั้น — ถอยไปใช้จำนวนที่เห็น **เฉพาะ**เมื่อ backend
  //    ไม่ได้ส่งมา (คำตอบเก่า/ยังไม่ deploy) ซึ่งยังดีกว่าโชว์ NaN · ไม่ใช่ทางปกติ
  const batchSize = toCount(first.batch_size) ?? 1;

  return {
    kind: 'batch',
    key: `batch:${batchId}`,
    batchId,
    title: first.batch_title ?? null,
    items: [first],
    visibleCount: 1,
    batchSize,
    voidedCount: toCount(first.batch_voided_count) ?? 0,
    activeCount: batchSize,
    visibleAmount: toAmount(first.amount),
    isPartiallyVisible: false,
  };
}

/**
 * 🏷️ ชื่อที่แสดงของชุด — ใช้ชื่อที่ผู้ใช้ตั้งก่อน ถ้าไม่มีก็ประกอบขึ้นเอง
 *
 * 🔴 **ห้ามเก็บสตริงนี้ลง DB** (backend เก็บ `title = NULL` โดยเจตนา): ชื่อที่ประกอบแล้ว
 *    กลายเป็น snapshot ที่โกหกทันทีที่มีใบถูกยกเลิก — "ชุด 20 ใบ" ที่เขียนค้างไว้จะไม่
 *    เปลี่ยนตามทั้งที่ในชุดเหลือ 17 ใบ ⇒ ประกอบสด ๆ ที่นี่ที่เดียว
 *
 * ⚠️ ใช้คำว่า "ชุดเอกสาร" ไม่ใช่ "ชุดใบเสร็จ" เพราะชุด **ปนชนิดได้** (ใบเสร็จ + ใบแจ้งหนี้
 *    อยู่ในชุดเดียวกันได้ — ทะเบียนนี้แสดงทั้งสองชนิดรวมกัน)
 */
export function batchDisplayName(group: ReceiptGroup<GroupableReceipt>): string {
  if (group.title) return group.title;
  return `ชุดเอกสาร ${group.batchSize} ใบ`;
}

/**
 * 📊 ข้อความบรรยายขนาดชุด — บอกความจริงเสมอว่ากรองตัดไปกี่ใบ
 *
 * คืน `null` เมื่อเห็นครบ (ไม่ต้องมีข้อความ) ⇒ template แค่ `v-if` ก็พอ
 */
export function batchVisibilityNote(group: ReceiptGroup<GroupableReceipt>): string | null {
  if (!group.isPartiallyVisible) return null;
  return `แสดง ${group.visibleCount} จาก ${group.batchSize} ใบ`;
}

/** 🚫 ข้อความเมื่อมีสมาชิกถูกยกเลิก — `null` เมื่อไม่มี (อย่าโชว์ "ยกเลิก 0") */
export function batchVoidedNote(group: ReceiptGroup<GroupableReceipt>): string | null {
  if (group.voidedCount <= 0) return null;
  return `ยกเลิก ${group.voidedCount}`;
}

// ==========================================
// ☑️ การติ๊กเลือก — ทำงานกับ "ที่เห็นบนจอ" เท่านั้น (กติกาข้อ 3)
// ==========================================

/** เลขที่เอกสารของสมาชิกที่เห็นบนจอ — สิ่งที่ติ๊กชุดหนึ่งครั้งควรเลือก */
export function visibleNosOf(row: ReceiptRow<GroupableReceipt>): string[] {
  return row.kind === 'batch' ? row.items.map((i) => i.receipt_no) : [row.item.receipt_no];
}

/** ยอดรวมของแถว (ชุด = ผลรวมสมาชิกที่เห็น) */
export function rowAmount(row: ReceiptRow<GroupableReceipt>): number {
  return row.kind === 'batch' ? row.visibleAmount : toAmount(row.item.amount);
}

/**
 * สถานะติ๊กของแถว — `'all'` (ติ๊กครบทุกใบที่เห็น) · `'some'` (บางใบ) · `'none'`
 *
 * 🔴 ต้องแยก `'some'` ออกจาก `'none'` ให้ได้ ไม่งั้นชุดที่ติ๊กไว้ 1 ใบจาก 5 จะดูเหมือน
 *    ไม่ได้ติ๊กเลย แล้วผู้ใช้ที่กดติ๊กจะ **ยกเลิก** ใบที่เลือกไว้แทนที่จะเลือกเพิ่ม
 */
export function rowSelectionState(
  row: ReceiptRow<GroupableReceipt>,
  selectedNos: readonly string[],
): 'all' | 'some' | 'none' {
  const nos = visibleNosOf(row);
  if (nos.length === 0) return 'none';
  const selected = new Set(selectedNos);
  const hit = nos.filter((no) => selected.has(no)).length;
  if (hit === 0) return 'none';
  return hit === nos.length ? 'all' : 'some';
}

/**
 * ติ๊ก/ยกเลิกติ๊กทั้งแถว — คืน `selectedNos` ชุดใหม่ (ไม่แก้ของเดิม)
 *
 * พฤติกรรม: ถ้าติ๊กครบอยู่แล้ว → ยกเลิกเฉพาะสมาชิกที่เห็น · ถ้ายังไม่ครบ → เติมให้ครบ
 * ⇒ กดซ้ำ = สลับไปมา ไม่ค้างอยู่ในสถานะ `'some'` ที่กดแล้วไม่ไปไหน
 *
 * 🔒 ลำดับของ `selectedNos` ที่คงไว้ต้องรักษา "ใบอื่นที่ติ๊กไว้" ให้อยู่ครบเสมอ
 */
export function toggleRowSelection(
  row: ReceiptRow<GroupableReceipt>,
  selectedNos: readonly string[],
): string[] {
  const nos = visibleNosOf(row);
  if (rowSelectionState(row, selectedNos) === 'all') {
    const remove = new Set(nos);
    return selectedNos.filter((no) => !remove.has(no));
  }
  const selected = new Set(selectedNos);
  const added = nos.filter((no) => !selected.has(no));
  return added.length ? [...selectedNos, ...added] : [...selectedNos];
}

/** ยอดรวมของเลขที่ที่ติ๊กไว้ — นับเฉพาะที่ปรากฏในทะเบียนปัจจุบัน (ใบที่หลุดกรองถูกตัดทิ้งแล้ว) */
export function selectedAmountOf(
  rows: readonly ReceiptRow<GroupableReceipt>[],
  selectedNos: readonly string[],
): number {
  const selected = new Set(selectedNos);
  let sum = 0;
  for (const row of rows) {
    for (const item of row.kind === 'batch' ? row.items : [row.item]) {
      if (selected.has(item.receipt_no)) sum += toAmount(item.amount);
    }
  }
  return sum;
}

/** จำนวนใบที่ติ๊กไว้เทียบกับที่เห็นทั้งหมด — ใช้ตัดสินสถานะ "เลือกทั้งหมด" ของหัวตาราง */
export function allVisibleSelected(
  rows: readonly ReceiptRow<GroupableReceipt>[],
  selectedNos: readonly string[],
): boolean {
  const selected = new Set(selectedNos);
  const all = rows.flatMap((row) => visibleNosOf(row));
  return all.length > 0 && all.every((no) => selected.has(no));
}

function toAmount(value: number | null | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function toCount(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}
