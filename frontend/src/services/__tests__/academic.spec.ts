import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AxiosHeaders } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { api } from '@/services/api';
import { AcademicService } from '@/services/academic';
import { MeService } from '@/services/me';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "สัญญาปลายทาง" ของปีการศึกษา/เทอม (P5)
 *
 * กฎที่ต้องกันไม่ให้ถอยหลัง:
 * 1. ทุกคำขอต้องพา `target_type=room` — ลืมแล้ว backend ตีความ `target_id` เป็น
 *    server id ⇒ เขียนปฏิทินผิดห้องแบบเงียบ ๆ
 * 2. `setCurrent` ใช้ **PUT** `/academic/current` (ไม่ใช่ POST/PATCH) และส่ง
 *    `year_id: null` ได้จริง — นี่คือทางเดียวที่ผู้ใช้จะ "ปลดปีปัจจุบัน"
 *    ⇒ ถ้าฝั่งหน้าแปลง `null` เป็น "ไม่ส่งฟิลด์" สถิติจะค้างอยู่ที่ปีเดิมตลอดกาล
 *    (backend แยก "ไม่ส่ง" กับ "ส่ง null" คนละความหมาย)
 * 3. `MeService.stats` **ห้ามส่ง** `year_id`/`term_id` เมื่อผู้ใช้ไม่ได้เลือก —
 *    ส่งไปเองแม้แต่ `undefined` ทำให้ได้ยูอาร์แอลที่อ่านไม่ออก และถ้ามีคนเปลี่ยน
 *    เป็น `0` "อัตโนมัติ" จะกลายเป็น 404
 * 4. ตัวกรองปีอย่างเดียว (ไม่เลือกเทอม) ต้องส่งแค่ `year_id` = "ทั้งปี"
 *    ไม่ใช่ส่ง `term_id=''` ซึ่ง backend มองเป็นค่าผิดชนิด
 */

interface Captured {
  uri: string;
  method: string;
  body: unknown;
}

const captured: Captured[] = [];

beforeEach(() => {
  captured.length = 0;
  api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    captured.push({
      uri: api.getUri(config),
      method: (config.method ?? 'get').toUpperCase(),
      body: config.data,
    });
    return {
      data: {},
      status: 200,
      statusText: 'OK',
      headers: new AxiosHeaders(),
      config,
    };
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

const firstUri = (): string => {
  const req = captured[0];
  if (!req) throw new Error('ไม่มีการเรียก API เลย — adapter ไม่ถูกเรียก (เทสต์จะเขียวหลอก)');
  return req.uri;
};

/**
 * axios แปลง `data` เป็น JSON string ก่อนถึง adapter (transformRequest)
 * ⇒ ต้องแยกวิเคราะห์กลับ ไม่งั้น `year_id: null` ที่ถูกตัดทิ้งจะดูเหมือน "ไม่ส่ง"
 * ซึ่งเป็นความผิดพลาดที่เทสต์นี้ตั้งใจจับ
 */
const firstBody = (): unknown => {
  const raw = captured[0]?.body;
  if (typeof raw === 'string') return JSON.parse(raw) as unknown;
  return raw;
};

/** `api.getUri()` ติด baseURL มาด้วย (ต่างกันตาม env) ⇒ เทียบเฉพาะ path+query */
const firstPath = (): string => firstUri().replace(/^https?:\/\/[^/]+/, '');

const pathOf = (index: number): string => (captured[index]?.uri ?? '').replace(/^https?:\/\/[^/]+/, '');

describe('AcademicService — เส้นทาง API ของปฏิทินห้อง', () => {
  it('periods() อ่านรายการผ่าน target_type=room', async () => {
    await AcademicService.periods(7);
    expect(firstPath()).toBe('/api/classroom/7/academic/periods?target_type=room');
    expect(captured[0]?.method).toBe('GET');
  });

  it('สร้างปีที่ /academic/years', async () => {
    const payload = { year_be: 2569, start_date: '2026-05-01', end_date: '2027-03-31' };
    await AcademicService.createYear(7, payload);
    expect(firstPath()).toBe('/api/classroom/7/academic/years?target_type=room');
    expect(captured[0]?.method).toBe('POST');
    expect(firstBody()).toMatchObject(payload);
  });

  it('แก้ปี/ลบปี ใช้ path ที่มี id ของปี', async () => {
    await AcademicService.updateYear(7, 3, { name: 'ใหม่' });
    await AcademicService.deleteYear(7, 3);

    expect(pathOf(0)).toBe('/api/classroom/7/academic/years/3?target_type=room');
    expect(captured[0]?.method).toBe('PATCH');
    expect(pathOf(1)).toBe('/api/classroom/7/academic/years/3?target_type=room');
    expect(captured[1]?.method).toBe('DELETE');
  });

  it('เทอมอยู่ใต้ปีของมัน — /years/{year}/terms', async () => {
    await AcademicService.createTerm(7, 3, {
      name: 'เทอม 1',
      start_date: '2026-05-01',
      end_date: '2026-10-31',
    });
    expect(firstPath()).toBe('/api/classroom/7/academic/years/3/terms?target_type=room');
    expect(captured[0]?.method).toBe('POST');
  });

  it('แก้/ลบเทอมใช้ /academic/terms/{id} (ไม่ผูกกับปีใน path)', async () => {
    await AcademicService.updateTerm(7, 9, { end_date: '2026-11-15' });
    await AcademicService.deleteTerm(7, 9);

    expect(pathOf(0)).toBe('/api/classroom/7/academic/terms/9?target_type=room');
    expect(captured[0]?.method).toBe('PATCH');
    expect(pathOf(1)).toBe('/api/classroom/7/academic/terms/9?target_type=room');
    expect(captured[1]?.method).toBe('DELETE');
  });

  it('ตั้งปัจจุบันเป็นการ PUT /academic/current', async () => {
    await AcademicService.setCurrent(7, { year_id: 3, term_id: 9 });
    expect(firstPath()).toBe('/api/classroom/7/academic/current?target_type=room');
    expect(captured[0]?.method).toBe('PUT');
    expect(firstBody()).toEqual({ year_id: 3, term_id: 9 });
  });

  it('ปลดปีปัจจุบันต้องส่ง year_id: null ไปถึง backend จริง', async () => {
    // 🔴 ถ้าตัวห่อกลายเป็น `JSON.stringify` ที่ตัดฟิลด์ค่า null ออก หรือใช้
    //    `exclude_unset` ฝั่งหน้า ความหมายจะเปลี่ยนเป็น "ไม่แตะ" ⇒ ปลดไม่ได้
    await AcademicService.setCurrent(7, { year_id: null });
    expect(firstBody()).toEqual({ year_id: null });
  });
});

describe('MeService.stats — ตัวกรองปี/เทอม (P5)', () => {
  it('ไม่ส่งตัวกรองเลยเมื่อผู้ใช้ใช้โหมดอัตโนมัติ', async () => {
    await MeService.stats(7);
    expect(firstPath()).toBe('/api/classroom/7/me/stats?target_type=room');
  });

  it('เลือกปีอย่างเดียว = ส่งแค่ year_id (ทั้งปี)', async () => {
    await MeService.stats(7, { year_id: 3 });
    expect(firstPath()).toBe('/api/classroom/7/me/stats?target_type=room&year_id=3');
  });

  it('เลือกทั้งปีและเทอม = ส่งทั้งคู่', async () => {
    await MeService.stats(7, { year_id: 3, term_id: 9 });
    const uri = firstPath();
    expect(uri).toContain('/api/classroom/7/me/stats');
    expect(uri).toContain('year_id=3');
    expect(uri).toContain('term_id=9');
  });
});
