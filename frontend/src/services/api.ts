import axios, { AxiosError, isAxiosError } from 'axios';
import type { PydanticValidationError } from '@/types/api';
import {
  ACCESS_TOKEN_KEY,
  ALL_LOCAL_STORAGE_KEYS,
  ALL_SESSION_STORAGE_KEYS,
} from '@/constants/storageKeys';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  // 🔴 **ห้ามตั้ง `Content-Type` ที่นี่** — axios 1.x แปลง FormData เป็น JSON ทันที
  //    เมื่อ header เป็น `application/json` (`if (isFormData) return hasJSONContentType
  //    ? JSON.stringify(formDataToJSON(data)) : data`) ⇒ อัปโหลดไฟล์ได้ 422
  //    "ฟิลด์ 'files': Field required" ทั้งที่ FormData มีไฟล์ครบ
  //    axios ใส่ `application/json` ให้เองเมื่อ body เป็น object ปกติ และปล่อยให้
  //    เบราว์เซอร์ใส่ `multipart/form-data; boundary=…` เองเมื่อ body เป็น FormData
  headers: {
    'Accept': 'application/json',
  },
});

// Interceptor ขาออก
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(ACCESS_TOKEN_KEY);
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
 * ⚠️ ข้อยกเว้น: `detail` ที่ backend ส่งมาเป็น **object** (เช่น error รายคนของ
 * bulk receive) ⇒ `message` ยังเป็นข้อความไทย แต่ `response.data.detail` **คง object
 * เดิมไว้** เพื่อให้ผู้เรียกอ่านฟิลด์เพิ่ม (เช่น `student_id`) ได้
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
    //
    // ⚠️ ใช้ลิสต์กลางจาก `constants/storageKeys.ts` — เดิมที่นี่ลบมือเพียง 8 คีย์
    //    ขณะที่ `authStore.logout()` ลบ 19 ⇒ สองเส้นทางทิ้งขยะไว้ไม่เท่ากัน
    //    (ชื่อ/อีเมล/เบอร์โทรค้างอยู่ใน localStorage หลังโดนเด้ง) ซึ่งไม่มีอะไรฟ้อง
    ALL_LOCAL_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));
    if (typeof window !== 'undefined' && window.sessionStorage) {
      ALL_SESSION_STORAGE_KEYS.forEach((key) => sessionStorage.removeItem(key));
    }

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

  // 🧩 [FIN-V2 / P2.7] detail ที่เป็น **object** (ไม่ใช่ array) — เช่น
  //    `{code:'BULK_ITEM_FAILED', message, student_id, item_code}` ของรับเงินหลายคน
  //    `String(obj)` ได้ "[object Object]" ⇒ glue ให้ใช้ `message` เป็นข้อความไทย
  //    แต่ **คง object เดิมไว้ใน `response.data.detail`** เพื่อให้ผู้เรียกที่ต้องใช้
  //    `student_id` (ไฮไลต์แถวที่พัง) อ่านได้ — ห้ามเขียนทับด้วย string
  const structuredDetail =
    rawDetail !== null &&
    typeof rawDetail === 'object' &&
    !Array.isArray(rawDetail) &&
    !(rawDetail instanceof Blob)
      ? (rawDetail as { message?: unknown })
      : undefined;
  if (structuredDetail && typeof structuredDetail.message === 'string') {
    detail = structuredDetail.message;
  }

  error.message = detail;
  // คงฟิลด์อื่นที่ backend ส่งมาด้วย (เช่น code) ไว้ ไม่ให้ข้อมูลหายไปโดยไม่จำเป็น
  const original = error.response.data;
  error.response.data =
    original && typeof original === 'object' && !(original instanceof Blob)
      ? { ...original, detail: structuredDetail ?? detail }
      : { detail: structuredDetail ?? detail };

  return Promise.reject(error);
};

api.interceptors.response.use(
  (response) => response.data,
  normalizeApiError
);

/**
 * อ่าน HTTP status จาก error ที่ผ่าน interceptor มาแล้ว
 *
 * ใช้แทนการไล่เขียน `if (isAxiosError(e) && e.response?.status === 409)` กระจาย
 * ทั่วทุกวิว — ที่นี่แปลง "ไม่ใช่ AxiosError" ให้เป็น `undefined` ที่เดียว
 *
 * ⚠️ ต้องคืน `undefined` (ไม่ใช่ `0`) เมื่อไม่มี status เพราะ:
 *   • `error.response` หายไปเมื่อต่อ backend ไม่ได้ (network error) ⇒ ไม่มี status จริง
 *   • `0` จะหลุด `=== 409` ทุกเงื่อนไขเงียบ ๆ แต่กลับดูเหมือน "มีค่า" ใน log
 *     ⇒ bug ที่อ่าน log แล้วเดาไม่ออก
 *
 * @example
 * const status = apiStatus(error);
 * if (status === 409) router.push('/students'); // เลขที่ซ้ำ — พาไปช่องที่ผิด
 */
export function apiStatus(error: unknown): number | undefined {
  if (!isAxiosError(error)) return undefined;
  return error.response?.status;
}

export default api;