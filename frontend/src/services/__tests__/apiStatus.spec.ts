import { describe, it, expect } from 'vitest';
import { AxiosError, AxiosHeaders } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { apiStatus, normalizeApiError } from '@/services/api';

/**
 * 🔢 `apiStatus()` — ตัวอ่าน status ตัวเดียวของระบบ
 *
 * กฎที่ล็อกไว้:
 *   • ไม่ใช่ AxiosError → `undefined` (ไม่ใช่ `0` / ไม่โยน)
 *   • ต่อ backend ไม่ได้ (network error) → `undefined` — **ไม่มี status จริง**
 *   • ผ่าน interceptor แล้ว status ยังอยู่ครบ (normalizeApiError ไม่ทำหล่น)
 */

function axiosErrorWith(status: number, data: unknown): AxiosError<{ detail?: unknown }> {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', config, undefined, {
    status,
    statusText: '',
    headers: {},
    config,
    data,
  } as AxiosResponse);
}

describe('apiStatus', () => {
  it('คืน status จาก AxiosError', () => {
    expect(apiStatus(axiosErrorWith(409, { detail: 'เลขที่ซ้ำ' }))).toBe(409);
  });

  it('คืน status หลังผ่าน normalizeApiError (interceptor ตัวจริง)', async () => {
    const rejected = await normalizeApiError(axiosErrorWith(403, { detail: 'ไม่มีสิทธิ์' })).then(
      () => {
        throw new Error('ต้อง reject');
      },
      (e: unknown) => e,
    );

    expect(apiStatus(rejected)).toBe(403);
  });

  it('network error (ไม่มี response) ⇒ undefined ไม่ใช่ 0', () => {
    const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
    const networkError = new AxiosError('Network Error', 'ERR_NETWORK', config);

    expect(apiStatus(networkError)).toBeUndefined();
  });

  it('Error ธรรมดา ⇒ undefined', () => {
    expect(apiStatus(new Error('boom'))).toBeUndefined();
  });

  it('ค่าที่ไม่ใช่ error เลย ⇒ undefined', () => {
    for (const value of [null, undefined, 'error', 500, {}, { response: { status: 500 } }]) {
      expect(apiStatus(value)).toBeUndefined();
    }
  });
});
