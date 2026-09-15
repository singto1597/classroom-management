import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '@/services/api';
import { FinanceService } from '@/services/finance';
import { AxiosHeaders } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "รูปแบบการ serialize อาร์เรย์ลง query string"
 *
 * บั๊กที่มันจับ (พบโดยการเรนเดอร์หน้าจริงในเบราว์เซอร์ 2026-09-14):
 * `getCreditPlan` เดิมส่ง `params: { student_ids: [1, 2] }` ให้ axios ⇒ axios 1.x
 * serialize เป็น **`student_ids[]=1&student_ids[]=2`** (วงเล็บเหลี่ยม)
 * แต่ FastAPI `Query(List[int])` ต้องการ **คีย์ซ้ำ** `student_ids=1&student_ids=2`
 * ⇒ ปลายทางได้ `422 {"loc":["query","student_ids"],"type":"missing"}`
 * ⇒ ปุ่ม "ดูข้อเสนอการหัก" (หัวใจของ flow "ระบบเสนอ → ครูยืนยัน") **ใช้ไม่ได้เลย**
 *
 * ⚠️ ทำไมเทสต์ฝั่ง backend 895 ตัวจับไม่ได้: `TestClient` ส่ง `params={"student_ids": [1,2]}`
 *    ซึ่ง httpx serialize เป็นคีย์ซ้ำให้เองอยู่แล้ว ⇒ ฝั่ง Python ไม่มีทางเห็นความต่างนี้
 *    ความผิดพลาดเกิดใน **ไคลเอนต์** เท่านั้น ⇒ ต้องมีเทสต์ที่ผูกกับไคลเอนต์จริง
 *
 * ⚠️ เทสต์นี้ใช้ axios instance **ตัวจริง** (`@/services/api`) ผ่าน adapter ปลอม
 *    ไม่ได้ mock `api.get` — เพราะถ้า mock ตัว `get` เราจะเห็นแค่ argument ที่เราส่ง
 *    ไม่เห็น **URL สุดท้าย** ที่ axios ประกอบจริง ซึ่งคือที่ที่บั๊กเกิด
 */

/**
 * URL สุดท้ายที่ axios จะยิงออกจริง
 *
 * ⚠️ ใช้ `api.getUri(config)` ไม่ใช่ `config.url` — เพราะ axios สร้าง query string
 *    **ใน adapter** (ไม่ใช่ก่อนเรียก adapter) ⇒ ตอนอยู่ใน adapter นั้น `config.url`
 *    ยังไม่มี `?params` ต่อท้าย และ `config.params` ยังเป็นออบเจ็กต์ดิบ
 *    `getUri()` รัน `buildURL` + `paramsSerializer` ชุดเดียวกับที่ adapter ใช้
 *    ⇒ สิ่งที่เห็นคือ URL จริง รวม `baseURL` ด้วย
 */
interface Captured {
  uri: string;
  method: string;
  /**
   * body ที่ axios ส่งออกจริง — `undefined` แปลว่าไม่มี body
   *
   * ⚠️ เก็บ **สตริงดิบ** ไม่ใช่ object ที่ parse แล้ว เพราะสิ่งที่ต้องพิสูจน์คือ
   *    "ฟิลด์นั้นถูก serialize ออกไปจริงไหม" — ถ้า parse เป็น object แล้วเช็ค
   *    `obj.title === null` จะผ่านทั้งที่ `undefined` ก็ถูกตัดทิ้งเหมือนกัน
   */
  body: unknown;
}

const captured: Captured[] = [];

beforeEach(() => {
  captured.length = 0;
  // ⚠️ ต้องคืนรูป `AxiosResponse` ให้ครบ (headers ต้องเป็น `AxiosHeaders` ไม่ใช่ `{}`)
  //    ไม่งั้น `vue-tsc` ล้ม — repo นี้ไม่มีการผ่อนเป็น `any`
  api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    captured.push({
      uri: api.getUri(config),
      method: (config.method ?? 'get').toUpperCase(),
      body: config.data,
    });
    return {
      data: { status: 'ok', items: [], total_applied: 0, total_balance_after: 0 },
      status: 200,
      statusText: 'OK',
      headers: new AxiosHeaders(),
      config,
    };
  };
});

/** คำขอแรก — และ **ต้องมี** คำขอจริง ไม่งั้นเทสต์จะเขียวหลอก */
const first = (): Captured => {
  const req = captured[0];
  if (!req) throw new Error('ไม่มีการเรียก API เลย — adapter ไม่ถูกเรียก (เทสต์จะเขียวหลอก)');
  return req;
};

/** URL ของคำขอแรก — และ **ต้องมี** คำขอจริง ไม่งั้นเทสต์จะเขียวหลอก */
const firstUri = (): string => first().uri;

/**
 * body ของคำขอแรกในรูป object
 *
 * ⚠️ parse จาก **สตริง JSON ที่ axios ส่งจริง** ไม่ได้อ่าน `config.data` ตรง ๆ
 *    เพื่อให้สิ่งที่เทสต์เห็น = สิ่งที่ลวดส่งออกไป (ถ้าวันหนึ่งมี transformRequest
 *    มาเปลี่ยน payload เทสต์นี้จะเห็น ไม่ใช่เห็น object ต้นทางที่เราเพิ่งสร้างเอง)
 */
const firstBody = (): Record<string, unknown> => {
  const raw = first().body;
  if (typeof raw !== 'string') {
    throw new Error(`คาดว่า body เป็นสตริง JSON แต่ได้ ${typeof raw} (ไม่มี body?)`);
  }
  return JSON.parse(raw) as Record<string, unknown>;
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FinanceService.getCreditPlan — การส่ง student_ids ลง query', () => {
  it('ส่ง student_ids เป็นคีย์ซ้ำ ไม่ใช่วงเล็บเหลี่ยม', async () => {
    await FinanceService.getCreditPlan(42, [7, 9]);

    const url = firstUri();
    expect(url).toContain('student_ids=7');
    expect(url).toContain('student_ids=9');
    // 🔴 ตัวที่ทำให้ FastAPI 422 — ถ้าบรรทัดนี้ล้ม แปลว่ากลับไปใช้ `params:` ของ axios แล้ว
    expect(decodeURIComponent(url)).not.toContain('student_ids[]');
    expect(url).not.toContain('%5B');
  });

  it('ไม่ส่งเป็น "7,9" ก้อนเดียว (FastAPI อ่านเป็น int ไม่ได้ → 422)', async () => {
    await FinanceService.getCreditPlan(42, [7, 9]);
    expect(decodeURIComponent(firstUri())).not.toMatch(/student_ids=7,9/);
  });

  it('มี target_type=room มาด้วยเสมอ (backend ใช้แยก web/bot)', async () => {
    await FinanceService.getCreditPlan(42, [7]);
    expect(firstUri()).toContain('target_type=room');
  });

  it('จำนวนคีย์ student_ids เท่ากับจำนวนนักเรียนที่เลือก (ไม่ตกหล่น/ไม่ซ้ำ)', async () => {
    await FinanceService.getCreditPlan(42, [3, 5, 8]);
    const matches = decodeURIComponent(firstUri()).match(/student_ids=/g) ?? [];
    expect(matches).toHaveLength(3);
  });

  it('🔎 พิสูจน์ว่ากับดักยังมีจริง — `params:` ของ axios ให้ "[]" (เทสต์นี้คือเหตุผลของโค้ดข้างบน)', async () => {
    // ยิงด้วยรูปแบบที่ "ดูถูก" แต่พัง — ถ้าวันหนึ่ง axios เปลี่ยนพฤติกรรมเป็นคีย์ซ้ำ
    // เทสต์นี้จะล้ม ⇒ เป็นสัญญาณให้กลับมาใช้ `params:` ได้อย่างปลอดภัย (และลบโค้ดอ้อมทิ้ง)
    await api.get('/probe', { params: { target_type: 'room', student_ids: [7, 9] } });
    expect(decodeURIComponent(firstUri())).toContain('student_ids[]=7');
  });
});

/**
 * 🔒 เทสต์ชุดนี้ล็อก "ชุดเอกสาร" (F5) 3 ข้อที่พังแล้วเงียบ
 *
 * 1. `receipt_nos` ต้องไปทาง **body** — ถ้าหลุดไป query จะกลายเป็น `receipt_nos[]=`
 *    แล้ว FastAPI ตอบ 422 ที่อ่านไม่ออก (กับดักเดิมของ `downloadCombinedPdf`)
 * 2. `title: null` ต้องถูกส่งออกไป **จริง** — ถ้าส่ง `undefined` axios จะตัดฟิลด์ทิ้ง
 *    แล้ว backend ตอบ 400 "ไม่มีฟิลด์ที่จะแก้ไข" ⇒ ปุ่ม "ล้างชื่อชุด" ตายเงียบ
 * 3. URL ต้องแยก list (`/receipt-batches`) กับ detail (`/receipt-batches/{id}`) ออกจากกัน
 *    — backend ประกาศ route คงที่ก่อน route ที่มี path param ถ้าไคลเอนต์เผลอส่ง
 *    `/receipt-batches/undefined` จะได้ 422 แทนที่จะเป็นรายการชุด
 */
describe('FinanceService — 📚 ชุดเอกสาร (F5)', () => {
  const ROOM = 42;

  it('getReceiptBatches: ยิง GET ไปที่ /receipt-batches ตรง ๆ ไม่มี id ต่อท้าย', async () => {
    await FinanceService.getReceiptBatches(ROOM);

    expect(first().method).toBe('GET');
    expect(firstUri()).toContain(`/api/classroom/${ROOM}/finance/receipt-batches?`);
    // 🔴 กัน `${batchId}` ที่เป็น undefined หลุดเข้า URL
    expect(firstUri()).not.toMatch(/receipt-batches\/(undefined|null|NaN)/);
  });

  it('getReceiptBatch: ต่อ batch_id ท้าย URL และยังมี target_type=room', async () => {
    await FinanceService.getReceiptBatch(ROOM, 7);

    expect(first().method).toBe('GET');
    expect(firstUri()).toContain(`/api/classroom/${ROOM}/finance/receipt-batches/7?`);
    expect(firstUri()).toContain('target_type=room');
  });

  it('🔴 createReceiptBatch: receipt_nos ไปใน body ไม่ใช่ query string', async () => {
    await FinanceService.createReceiptBatch(ROOM, { receipt_nos: ['A-1', 'A-2'] });

    expect(first().method).toBe('POST');
    expect(firstUri()).toContain('target_type=room');
    // ⛔ บรรทัดนี้คือหัวใจ — ถ้าล้มแปลว่ามีคนย้าย receipt_nos ไป `params:`
    expect(firstUri()).not.toContain('receipt_nos');
    expect(decodeURIComponent(firstUri())).not.toContain('receipt_nos[]');
    expect(firstBody()['receipt_nos']).toEqual(['A-1', 'A-2']);
  });

  it('createReceiptBatch: ส่ง title/note ไปด้วยเมื่อมี', async () => {
    await FinanceService.createReceiptBatch(ROOM, {
      receipt_nos: ['A-1', 'A-2'],
      title: 'ชุดผู้ปกครอง ม.1',
      note: 'ออกพร้อมกัน',
    });

    expect(firstBody()).toMatchObject({ title: 'ชุดผู้ปกครอง ม.1', note: 'ออกพร้อมกัน' });
  });

  it('🔴 updateReceiptBatch: `title: null` ต้องถูกส่งออกไปจริง (ไม่ใช่ถูกตัดทิ้งแบบ undefined)', async () => {
    await FinanceService.updateReceiptBatch(ROOM, 7, { title: null });

    expect(first().method).toBe('PATCH');
    const body = firstBody();
    // ⛔ ถ้าล้ม = ปุ่ม "ล้างชื่อชุด" พังด้วย 400 จาก backend
    expect(Object.prototype.hasOwnProperty.call(body, 'title')).toBe(true);
    expect(body['title']).toBeNull();
    // และต้องไม่มี note โผล่มาเอง (PATCH = ส่งเท่าที่แก้)
    expect(Object.prototype.hasOwnProperty.call(body, 'note')).toBe(false);
  });

  it('updateReceiptBatch: ส่งเฉพาะฟิลด์ที่แก้ ไม่ยัด title มาด้วยเมื่อแก้แค่ note', async () => {
    await FinanceService.updateReceiptBatch(ROOM, 7, { note: 'โน้ตใหม่' });

    const body = firstBody();
    expect(body['note']).toBe('โน้ตใหม่');
    expect(Object.prototype.hasOwnProperty.call(body, 'title')).toBe(false);
  });

  it('setReceiptBatchReceipts: ใช้ PUT และส่งเซตสมาชิกทั้งชุดใน body', async () => {
    await FinanceService.setReceiptBatchReceipts(ROOM, 7, { receipt_nos: ['B-1'] });

    expect(first().method).toBe('PUT');
    expect(firstUri()).toContain(`/receipt-batches/7/receipts?`);
    expect(firstUri()).not.toContain('receipt_nos');
    expect(firstBody()['receipt_nos']).toEqual(['B-1']);
  });

  it('setReceiptBatchReceipts: ลิสต์ว่างต้องถูกส่งเป็น [] จริง ไม่ใช่หายไป', async () => {
    // backend ตอบ 422 ให้ลิสต์ว่าง (ต้องมีอย่างน้อย 1 ฉบับ) — แต่ที่เทสต์ตรงนี้ล็อกคือ
    // **ไคลเอนต์ส่ง [] ออกไปจริง** ไม่ใช่ตัดฟิลด์ทิ้งจนกลายเป็น 400 คนละความหมาย
    await FinanceService.setReceiptBatchReceipts(ROOM, 7, { receipt_nos: [] });

    expect(firstBody()['receipt_nos']).toEqual([]);
  });

  it('deleteReceiptBatch: ใช้ DELETE และ **ไม่มี body** (เลขที่เอกสารไม่ถูกแตะ)', async () => {
    await FinanceService.deleteReceiptBatch(ROOM, 7);

    expect(first().method).toBe('DELETE');
    expect(firstUri()).toContain(`/api/classroom/${ROOM}/finance/receipt-batches/7?`);
    expect(firstUri()).toContain('target_type=room');
    expect(first().body).toBeUndefined();
  });

  it('ทุกเมธอดเขียน/อ่าน ส่ง target_type=room เสมอ (backend ใช้แยก web/bot)', async () => {
    await FinanceService.getReceiptBatches(ROOM);
    await FinanceService.getReceiptBatch(ROOM, 7);
    await FinanceService.createReceiptBatch(ROOM, { receipt_nos: ['A-1'] });
    await FinanceService.setReceiptBatchReceipts(ROOM, 7, { receipt_nos: ['A-1'] });
    await FinanceService.updateReceiptBatch(ROOM, 7, { note: 'x' });
    await FinanceService.deleteReceiptBatch(ROOM, 7);

    expect(captured).toHaveLength(6);
    for (const req of captured) {
      expect(req.uri).toContain('target_type=room');
    }
  });
});

/**
 * 🔒 เทสต์ชุดนี้ล็อกสัญญาของ "เคลียร์หนี้แล้วออกใบเสร็จให้ทุกรายการ" (F5/PR-2)
 *
 * บั๊กที่มันจับ:
 * 1. **ติ๊กปิดแล้วยังส่ง `issue_receipts: true`** (หรือตัดฟิลด์ทิ้งจน backend ใช้ default)
 *    ⇒ ครูที่ตั้งใจไม่ออกใบเสร็จจะได้ใบเสร็จทุกครั้ง และเลขเอการถูกกินไปเปล่า ๆ
 * 2. **URL ผิด** — `/payments/batch` เป็น route ที่มี `/payments/{payment_id}/pay` อยู่ข้าง ๆ
 *    ⇒ ถ้าเผลอต่อ `/pay` เข้าไปจะไปโดน route บิลเดียวแทน (400 เพราะ body คนละรูป)
 * 3. `receipts` ต้องเป็น **object เต็ม** ไม่ใช่แค่เลขที่ — หน้าจอใช้ `receipt_no` ของสมาชิก
 *    ทุกใบยิง `downloadCombined` ต่อทันที ถ้า backend ส่งแต่เลขที่จะพังตอนกดดูรวม
 */
describe('FinanceService — 🧾 เคลียร์หนี้แล้วออกใบเสร็จ (F5/PR-2)', () => {
  const ROOM = 42;
  const PAYLOAD = {
    items: [
      { payment_id: 11, paid_amount: 500 },
      { payment_id: 12, paid_amount: 300 },
    ],
    paid_to_account_id: 5,
    user_name: 'ครูสมชาย',
  };

  it('confirmBatchPayment: ยิง PUT ไปที่ /finance/payments/batch (ไม่ใช่ route บิลเดียว)', async () => {
    await FinanceService.confirmBatchPayment(ROOM, PAYLOAD);

    expect(first().method).toBe('PUT');
    expect(firstUri()).toContain(`/api/classroom/${ROOM}/finance/payments/batch?`);
    expect(firstUri()).toContain('target_type=room');
    // ⛔ กันหลุดไปโดน `/payments/{id}/pay` ซึ่งรับ body คนละรูป
    expect(firstUri()).not.toContain('/pay?');
  });

  it('🔴 issue_receipts=true ต้องถูกส่งออกไปจริงใน body (ไม่ใช่ query)', async () => {
    await FinanceService.confirmBatchPayment(ROOM, { ...PAYLOAD, issue_receipts: true });

    expect(firstUri()).not.toContain('issue_receipts');
    expect(firstBody()['issue_receipts']).toBe(true);
    expect(firstBody()['items']).toEqual(PAYLOAD.items);
    expect(firstBody()['paid_to_account_id']).toBe(5);
  });

  it('🔴 issue_receipts=false ต้องไปถึง backend ตรง ๆ (ไม่ถูกตัดเป็น undefined = เปิด)', async () => {
    await FinanceService.confirmBatchPayment(ROOM, { ...PAYLOAD, issue_receipts: false });

    const body = firstBody();
    // ⛔ ถ้าล้ม = ติ๊กปิดไม่ได้ผล เพราะ backend จะ fallback ไป default `True`
    expect(Object.prototype.hasOwnProperty.call(body, 'issue_receipts')).toBe(true);
    expect(body['issue_receipts']).toBe(false);
  });

  it('ไม่ส่ง issue_receipts เลย = ปล่อยให้ backend ตัดสิน (เปิด) — ไม่ยัด true มาเอง', async () => {
    // 🔎 เทสต์นี้กัน "ความช่วยเหลือที่ไม่ได้ขอ": ถ้ามีคนเติม `?? true` ใน service
    //    วันหนึ่ง backend เปลี่ยน default เป็นปิด เทสต์นี้จะล้มทันที (ซึ่งถูกต้อง)
    await FinanceService.confirmBatchPayment(ROOM, PAYLOAD);
    expect(Object.prototype.hasOwnProperty.call(firstBody(), 'issue_receipts')).toBe(false);
  });

  it('คำตอบเก็บ `receipts` เป็น object เต็ม + ตัวนับ (ไม่ถูกตัดทิ้งระหว่างทาง)', async () => {
    const receipt = {
      id: 1,
      receipt_no: 'REC-2569-0001',
      doc_type: 'receipt',
      amount: 500,
      issued_at: '2026-09-15T02:00:00Z',
      batch_id: 9,
    };
    api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
      captured.push({
        uri: api.getUri(config),
        method: (config.method ?? 'get').toUpperCase(),
        body: config.data,
      });
      return {
        data: {
          status: 'success',
          message: 'รับเงินรวบยอด 2 รายการสำเร็จ · ออกใบเสร็จ 2 ใบ',
          receipts: [receipt],
          issued_count: 2,
          reused_count: 0,
          batch_id: 9,
        },
        status: 200,
        statusText: 'OK',
        headers: new AxiosHeaders(),
        config,
      };
    };

    const res = await FinanceService.confirmBatchPayment(ROOM, PAYLOAD);

    // ⛔ หน้าจอใช้ 3 อย่างนี้ตรง ๆ: `receipts[].receipt_no` ยิง downloadCombined,
    //    `issued_count` เขียนข้อความ, `batch_id` ตัดสินว่า "รวมเป็นชุดเดียว"
    expect(res.receipts.map((r) => r.receipt_no)).toEqual(['REC-2569-0001']);
    expect(res.issued_count).toBe(2);
    expect(res.reused_count).toBe(0);
    expect(res.batch_id).toBe(9);
  });
});

describe('FinanceService — กับดักเดิมยังมีจริง (กันเทสต์ข้างบนเขียวหลอก)', () => {
  it('🔎 พิสูจน์ว่ากับดักทั้ง 2 ข้อมีจริง — ถ้า 2 เทสต์นี้ล้ม แปลว่าเทสต์ข้างบนเขียวหลอก', async () => {
    // (ก) array ทาง query ⇒ axios ใส่วงเล็บเหลี่ยม (เหตุผลที่ receipt_nos ต้องอยู่ใน body)
    await api.post('/probe', null, { params: { receipt_nos: ['A-1', 'A-2'] } });
    expect(decodeURIComponent(firstUri())).toContain('receipt_nos[]=A-1');

    // (ข) `undefined` ถูกตัดทิ้งจาก body แต่ `null` อยู่ — เหตุผลที่ `title: null` ต้องส่ง null
    captured.length = 0;
    await api.patch('/probe', { title: undefined, note: null });
    const body = firstBody();
    expect(Object.prototype.hasOwnProperty.call(body, 'title')).toBe(false);
    expect(body['note']).toBeNull();
  });
});
