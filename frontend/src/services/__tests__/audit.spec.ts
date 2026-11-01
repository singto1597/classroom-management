import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AxiosHeaders } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { api } from '@/services/api';
import { AuditService } from '@/services/audit';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "สัญญาปลายทาง" ของหน้าดูบันทึกกิจกรรม (P6.2)
 *
 * กฎที่ต้องกันไม่ให้ถอยหลัง:
 * 1. ทุกคำขอต้องพา `target_type=room` — ลืมแล้ว backend ตีความ `target_id`
 *    เป็น Discord server id ⇒ 404 หรืออ่านห้องผิดแบบเงียบ ๆ
 * 2. **ตัวกรองว่างต้องไม่ถูกส่ง** — backend ใช้ `service_name = $2` ⇒ ส่ง `''`
 *    ไปจะไม่ตรงกับใครเลยและได้หน้าว่างที่ดูเหมือน "ไม่มีบันทึก" (หลอกผู้ใช้)
 * 3. `cursor` ต้องส่งกลับตามที่ได้มาเป๊ะ ๆ (ค่าทึบ base64) — ห้ามตัด/แปลง
 * 4. `options()` ต้องชี้ `/audit-logs/options` ไม่ใช่ `/audit-logs`
 * 5. `limit` ต้องส่งเป็นตัวเลข ไม่ใช่สตริง (backend รับ `int` และตอบ 422 ถ้าผิดชนิด)
 */

interface Captured {
  uri: string;
  method: string;
}

const captured: Captured[] = [];

beforeEach(() => {
  captured.length = 0;
  api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    captured.push({
      uri: api.getUri(config),
      method: (config.method ?? 'get').toUpperCase(),
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

/** `api.getUri()` ติด baseURL มาด้วย ⇒ เทียบเฉพาะ path+query */
const firstPath = (): string => {
  const req = captured[0];
  if (!req) throw new Error('ไม่มีการเรียก API เลย — adapter ไม่ถูกเรียก (เทสต์จะเขียวหลอก)');
  return req.uri.replace(/^https?:\/\/[^/]+/, '');
};

const queryOf = (): URLSearchParams =>
  new URLSearchParams(firstPath().split('?')[1] ?? '');

describe('AuditService — เส้นทาง API ของบันทึกกิจกรรม', () => {
  it('list() เรียก /audit-logs พร้อม target_type=room', async () => {
    await AuditService.list(7);
    expect(firstPath()).toBe('/api/classroom/7/audit-logs?target_type=room');
    expect(captured[0]?.method).toBe('GET');
  });

  it('ตัวกรองที่ไม่ได้เลือกต้องไม่ถูกส่งเป็นค่าว่าง', async () => {
    await AuditService.list(7, {
      service_name: '',
      action: '',
      status: '',
      q: '',
      date_from: '',
      date_to: '',
    });
    const query = queryOf();
    expect([...query.keys()]).toEqual(['target_type']);
  });

  it('ส่งเฉพาะตัวกรองที่มีค่าจริง', async () => {
    await AuditService.list(7, {
      service_name: 'FINANCE',
      action: 'CREATE',
      status: 'failed',
      q: 'receipt',
      date_from: '2026-10-01',
      date_to: '2026-10-31',
      limit: 50,
    });
    const query = queryOf();
    expect(query.get('target_type')).toBe('room');
    expect(query.get('service_name')).toBe('FINANCE');
    expect(query.get('action')).toBe('CREATE');
    expect(query.get('status')).toBe('failed');
    expect(query.get('q')).toBe('receipt');
    expect(query.get('date_from')).toBe('2026-10-01');
    expect(query.get('date_to')).toBe('2026-10-31');
    expect(query.get('limit')).toBe('50');
  });

  it('cursor ถูกส่งกลับตามที่ได้มาเป๊ะ ๆ (ไม่ตัด/ไม่เข้ารหัสซ้ำ)', async () => {
    const cursor = 'MjAyNi0xMC0yNFQwMTowMDowMCswMDowMHxhYmM=';
    await AuditService.list(7, { cursor });
    expect(queryOf().get('cursor')).toBe(cursor);
  });

  it('options() ต้องชี้ /audit-logs/options', async () => {
    await AuditService.options(7);
    expect(firstPath()).toBe('/api/classroom/7/audit-logs/options?target_type=room');
  });
});
