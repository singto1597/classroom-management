import axios, { AxiosError } from 'axios';
import type { PydanticValidationError } from '@/types/api';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  },
});

// Interceptor ขาออก
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor ขาเข้า: จัดการ Error และดักจับ 401
let isRedirectingToLogin = false;

/**
 * แปลง error ดิบของ axios ให้เป็น **AxiosError ตัวเดิม** ที่พกข้อความไทยอ่านรู้เรื่อง
 *
 * ⚠️ ห้ามเปลี่ยนกลับไปเป็น `Promise.reject(new Error(detail))` เด็ดขาด
 *
 * การ reject ด้วย `new Error(...)` ทำให้ **`isAxiosError()` เป็น false** ⇒ วิวทั้ง 11 แห่ง
 * ที่เขียนว่า `if (!isAxiosError(error)) return undefined` จะคืน `undefined` ทันที
 * แล้วตกไปใช้ข้อความ fallback ของตัวเอง — ข้อความไทยที่ backend ส่งมาแม่น ๆ
 * (เช่น "เลขที่นี้มีผู้ใช้งานแล้ว" / "ไม่มีสิทธิ์ลบงานนี้") **ถูกกลืนหายทุกครั้ง**
 * โดยที่หน้าจอยังขึ้นกล่อง error ปกติ ไม่มีอะไรดูผิด ⇒ เป็นบั๊กที่มองไม่เห็นจากโค้ดวิว
 *
 * แก้โดย **ไม่ทิ้งชนิดของ error**: เซ็ต `message` เป็นข้อความไทย (ผู้บริโภคที่ใช้
 * `error instanceof Error ? error.message` ยังทำงานเหมือนเดิม — เช่น Lobby.vue)
 * และเขียน `detail` ที่แปลง 422 เป็นข้อความแล้วกลับลง `response.data`
 * (ผู้บริโภคที่ใช้ `error.response?.data?.detail` ก็ได้ข้อความเดียวกัน)
 *
 * เทสต์ที่ล็อกสัญญานี้: `src/services/__tests__/apiErrors.spec.ts`
 */
export const normalizeApiError = async (
  error: AxiosError<{ detail?: unknown }>
): Promise<never> => {
  if (!error.response) {
    error.message = 'ไม่สามารถเชื่อมต่อกับ Backend ได้: ' + error.message;
    return Promise.reject(error);
  }

  if (error.response.status === 401) {
    // ✅ เคลียร์ Session ทั้งหมด (ไม่ใช่แค่ token) เพื่อป้องกัน redirect วนลูป
    // และคืนค่าผู้ใช้ไปหน้า Login ครั้งเดียวเท่านั้น
    localStorage.removeItem('access_token');
    localStorage.removeItem('user_id_str');
    localStorage.removeItem('current_room_id');
    localStorage.removeItem('current_room_name');
    localStorage.removeItem('current_room_code');
    localStorage.removeItem('current_role');
    localStorage.removeItem('current_is_admin');
    localStorage.removeItem('current_permissions');

    if (!isRedirectingToLogin && !window.location.pathname.startsWith('/login')) {
      isRedirectingToLogin = true;
      window.location.href = '/login';
    }
  }

  // 🚨 คำขอที่ส่ง `responseType: 'blob'` (export Excel / ดาวน์โหลด PDF) จะได้ error body
  //    มาเป็น **Blob** ทั้งที่ backend ตอบ JSON — ถ้าไม่คลี่ออกจะได้ข้อความไร้ค่า "[object Blob]"
  //    แล้วผู้ใช้ไม่รู้เลยว่าพลาดเพราะอะไร (เช่น Gotenberg ล่ม → 502 "สร้างไฟล์ PDF ไม่สำเร็จ")
  let payload: unknown = error.response.data;
  if (payload instanceof Blob) {
    try {
      payload = JSON.parse(await payload.text());
    } catch {
      // ไม่ใช่ JSON (เช่น HTML error page ของ reverse proxy) — ตกไปใช้ข้อความกลาง
      payload = undefined;
    }
  }

  const rawDetail: unknown = (payload as { detail?: unknown } | undefined)?.detail;
  let detail = rawDetail ? String(rawDetail) : 'เกิดข้อผิดพลาดจาก API';

  // ✨ ปลดล็อก Pydantic 422 Error ให้อ่านรู้เรื่อง!
  // ถ้า Backend ส่ง Array Error มา จะจับมาแกะชื่อฟิลด์บอกให้ชัดเจน
  if (Array.isArray(rawDetail)) {
    detail = (rawDetail as PydanticValidationError[]).map((err) => {
      const field = err.loc ? err.loc[err.loc.length - 1] : 'Unknown';
      return `ฟิลด์ '${field}': ${err.msg}`;
    }).join('\n');
  }

  error.message = detail;
  // คงฟิลด์อื่นที่ backend ส่งมาด้วย (เช่น code) ไว้ ไม่ให้ข้อมูลหายไปโดยไม่จำเป็น
  const original = error.response.data;
  error.response.data =
    original && typeof original === 'object' && !(original instanceof Blob)
      ? { ...original, detail }
      : { detail };

  return Promise.reject(error);
};

api.interceptors.response.use(
  (response) => response.data,
  normalizeApiError
);

export default api;