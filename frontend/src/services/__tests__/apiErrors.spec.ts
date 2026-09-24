import { describe, it, expect } from 'vitest';
import { AxiosError, AxiosHeaders, isAxiosError } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { normalizeApiError } from '@/services/api';

/**
 * 🔒 เทสต์ชุดนี้ล็อก **ชนิดของ error ที่ interceptor ส่งต่อให้วิว**
 *
 * บั๊กที่มันจับ (พบจากการตรวจระบบ 2026-09-23):
 * `api.ts` เดิมจบด้วย `return Promise.reject(new Error(detail))` ⇒ error ที่วิวได้รับ
 * เป็น `Error` ธรรมดา **ไม่ใช่ `AxiosError`** ⇒ วิว 11 แห่งที่ขึ้นต้นด้วย
 *
 *     if (!isAxiosError(error)) return undefined
 *
 * คืน `undefined` ทันที แล้วตกไปใช้ข้อความ fallback ของตัวเอง
 * ⇒ ข้อความไทยที่ backend ส่งมาแม่น ๆ ถูกกลืนหาย **ทุกครั้ง** โดยหน้าจอยังขึ้น
 * กล่อง error ปกติ ไม่มีอะไรดูผิด ⇒ อ่านโค้ดวิวอย่างเดียวจับไม่ได้เลย
 *
 * ⚠️ เทสต์นี้ต้องยิงผ่าน `normalizeApiError` **ตัวจริง** ไม่ใช่จำลองพฤติกรรมเอง
 *    ถ้าเขียนเทสต์ที่ assert "Error ธรรมดาก็ได้" มันจะผ่านทั้งที่มีบั๊ก
 */

/** สร้าง AxiosError ของจริง (ไม่ใช่ object ปลอม) เพื่อให้ `isAxiosError()` ตอบตามจริง */
function axiosErrorWith(status: number, data: unknown): AxiosError<{ detail?: unknown }> {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  return new AxiosError(
    `Request failed with status code ${status}`,
    'ERR_BAD_REQUEST',
    config,
    undefined,
    {
      status,
      statusText: '',
      headers: {},
      config,
      data,
    } as AxiosResponse,
  );
}

/** ดึงค่าที่ถูก reject ออกมาตรวจ (แบบไม่ให้ unhandled rejection) */
async function rejectionOf(error: AxiosError<{ detail?: unknown }>): Promise<unknown> {
  return normalizeApiError(error).then(
    () => {
      throw new Error('ต้อง reject แต่กลับ resolve');
    },
    (e: unknown) => e,
  );
}

/**
 * จำลอง helper ที่วิวทั้ง 11 แห่งใช้ — "สัญญา" ที่เทสต์ชุดนี้ผูกไว้
 * (คัดลอกมาจาก AddStudent.vue / StudentList.vue ฯลฯ ซึ่งเหมือนกันทุกตัวอักษร)
 */
function viewHelper(error: unknown): string | undefined {
  if (!isAxiosError<{ detail?: unknown }>(error)) return undefined;
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : undefined;
}

describe('normalizeApiError — ต้องไม่ทำลายชนิดของ AxiosError', () => {
  it('reject ด้วย AxiosError (ไม่ใช่ Error ธรรมดา) — นี่คือบั๊กต้นทาง', async () => {
    const rejected = await rejectionOf(axiosErrorWith(403, { detail: 'ไม่มีสิทธิ์ลบงานนี้' }));

    expect(isAxiosError(rejected)).toBe(true);
  });

  it('helper ของวิวต้องได้ข้อความไทยจาก backend ไม่ใช่ undefined', async () => {
    const rejected = await rejectionOf(axiosErrorWith(403, { detail: 'ไม่มีสิทธิ์ลบงานนี้' }));

    // ถ้า interceptor กลับไปใช้ `new Error(detail)` บรรทัดนี้จะเป็น undefined
    // แล้ววิวจะขึ้น "ไม่สามารถโหลดข้อมูลได้" แทนข้อความจริงของ backend
    expect(viewHelper(rejected)).toBe('ไม่มีสิทธิ์ลบงานนี้');
  });

  it('ตั้ง message เป็นข้อความไทยด้วย — วิวที่อ่าน error.message ยังทำงานได้', async () => {
    // Lobby.vue:232 ทำ `error instanceof Error ? error.message : ''` แล้วเอาข้อความไปแสดง
    const rejected = await rejectionOf(
      axiosErrorWith(400, { detail: 'รหัสห้องผิด หรือเลขที่นี้มีผู้ใช้งานแล้ว' }),
    );

    expect(rejected).toBeInstanceOf(Error);
    expect((rejected as Error).message).toBe('รหัสห้องผิด หรือเลขที่นี้มีผู้ใช้งานแล้ว');
  });

  it('status ยังอยู่ครบ — วิวที่แยกเคส 422 ยังแยกได้', async () => {
    // EditStudent.vue:188 ใช้ `error.response?.status === 422`
    const rejected = await rejectionOf(axiosErrorWith(422, { detail: 'อะไรก็ได้' }));

    expect((rejected as AxiosError).response?.status).toBe(422);
  });

  it('Pydantic 422 array ถูกแปลงเป็นข้อความไทยที่อ่านรู้เรื่อง', async () => {
    const rejected = await rejectionOf(
      axiosErrorWith(422, {
        detail: [
          { loc: ['body', 'student_no'], msg: 'Input should be greater than 0' },
          { loc: ['body', 'first_name'], msg: 'Field required' },
        ],
      }),
    );

    expect(viewHelper(rejected)).toBe(
      "ฟิลด์ 'student_no': Input should be greater than 0\nฟิลด์ 'first_name': Field required",
    );
  });

  it('backend ตอบโดยไม่มี detail → ใช้ข้อความกลาง', async () => {
    const rejected = await rejectionOf(axiosErrorWith(500, {}));

    expect(viewHelper(rejected)).toBe('เกิดข้อผิดพลาดจาก API');
  });

  it('error body เป็น Blob (export Excel/PDF) ยังถูกคลี่ออกเป็น JSON', async () => {
    const rejected = await rejectionOf(
      axiosErrorWith(502, new Blob([JSON.stringify({ detail: 'สร้างไฟล์ PDF ไม่สำเร็จ' })])),
    );

    expect(viewHelper(rejected)).toBe('สร้างไฟล์ PDF ไม่สำเร็จ');
  });

  it('error body เป็น Blob ที่ไม่ใช่ JSON (HTML ของ proxy) → ข้อความกลาง ไม่ใช่ [object Blob]', async () => {
    const rejected = await rejectionOf(axiosErrorWith(502, new Blob(['<html>502</html>'])));

    expect(viewHelper(rejected)).toBe('เกิดข้อผิดพลาดจาก API');
  });

  it('ต่อ backend ไม่ได้ (ไม่มี response) → ยังเป็น AxiosError และมีข้อความไทย', async () => {
    const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
    const networkError = new AxiosError<{ detail?: unknown }>('Network Error', 'ERR_NETWORK', config);

    const rejected = await rejectionOf(networkError);

    expect(isAxiosError(rejected)).toBe(true);
    expect((rejected as Error).message).toContain('ไม่สามารถเชื่อมต่อกับ Backend ได้');
  });

  it('non-sensitive ฟิลด์อื่นใน body ไม่หายไป', async () => {
    const rejected = await rejectionOf(
      axiosErrorWith(400, { detail: 'ข้อมูลไม่ถูกต้อง', code: 'INVALID_ROOM' }),
    );

    expect((rejected as AxiosError<{ detail?: unknown; code?: string }>).response?.data).toEqual({
      detail: 'ข้อมูลไม่ถูกต้อง',
      code: 'INVALID_ROOM',
    });
  });
});
