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
const captured: { uri: string; method: string }[] = [];

beforeEach(() => {
  captured.length = 0;
  // ⚠️ ต้องคืนรูป `AxiosResponse` ให้ครบ (headers ต้องเป็น `AxiosHeaders` ไม่ใช่ `{}`)
  //    ไม่งั้น `vue-tsc` ล้ม — repo นี้ไม่มีการผ่อนเป็น `any`
  api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    captured.push({
      uri: api.getUri(config),
      method: (config.method ?? 'get').toUpperCase(),
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

/** URL ของคำขอแรก — และ **ต้องมี** คำขอจริง ไม่งั้นเทสต์จะเขียวหลอก */
const firstUri = (): string => {
  const first = captured[0];
  if (!first) throw new Error('ไม่มีการเรียก API เลย — adapter ไม่ถูกเรียก (เทสต์จะเขียวหลอก)');
  return first.uri;
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
