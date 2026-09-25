import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { AxiosHeaders } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/auth';

/**
 * ล็อก **สัญญาการคืนค่า** ของ `authStore.fetchProfile()` (ผลตรวจระบบ 2026-09-23 → L3)
 *
 * บั๊กที่มันจับ: `fetchProfile` เดิมเป็น `void` และกลืน error ด้วย `console.error` เฉย ๆ
 * ⇒ ผู้เรียก **แยกไม่ออก** ระหว่าง
 *    (ก) "ดึงเสร็จแล้ว และผู้ใช้คนนี้ยังไม่มีข้อมูล" กับ
 *    (ข) "ดึงไม่สำเร็จ เลยยังไม่มีข้อมูล"
 * เพราะทั้งสองกรณีทิ้ง store ไว้ในสภาพเดียวกันเป๊ะ (ค่าว่าง)
 *
 * ⇒ หน้าออนบอร์ด (`Onboarding.vue`) จึงขึ้น **ฟอร์มว่างเปล่า** โดยไม่บอกอะไร ซึ่งอ่านได้
 *   สองความหมาย และคนที่มีข้อมูลอยู่ในระบบแล้ว (ล็อกอินเครื่องใหม่ / เน็ตสะดุดตอน
 *   backend รีสตาร์ท) จะเข้าใจว่าข้อมูลหาย แล้ว **กรอกทับข้อมูลเดิมของตัวเอง**
 *
 * ⚠️ ใช้ axios instance **ตัวจริง** (`@/services/api`) ผ่าน adapter ปลอม — ไม่ได้ mock
 *    `api.get` — เพื่อให้เทสต์วิ่งผ่าน interceptor จริงของโปรเจกต์ (ซึ่งเป็นชั้นที่แปลง
 *    error ให้เป็น `Error` ภาษาไทย) ⇒ สิ่งที่ล็อกไว้คือพฤติกรรมจากต้นทางถึงปลายทาง
 *    ไม่ใช่แค่ argument ที่เราส่งเอง
 */

const TOKEN_KEY = 'access_token';

/** โปรไฟล์ที่ Backend ตอบ — คีย์ตาม `UserProfileResponse` จริง */
const PROFILE: Record<string, unknown> = {
  id: 42,
  prefix: 'นาย',
  first_name: 'สมชาย',
  last_name: 'ใจดี',
  first_name_en: 'Somchai',
  last_name_en: 'Jaidee',
  nickname_en: 'Chat',
  email: 'somchai@example.com',
  discord_id: null,
  google_id: null,
  nickname: 'ชาย',
  phone_number: '0812345678',
};

/** สิ่งที่ adapter จะทำเมื่อถูกเรียก */
type Outcome =
  | { kind: 'ok'; body: Record<string, unknown> }
  | { kind: 'fail'; error: Error }
  /** ค้างไว้ไม่ตอบ — ใช้ทดสอบเส้นทาง "มีคำขอค้างอยู่แล้ว" */
  | { kind: 'hold' };

let outcome: Outcome = { kind: 'ok', body: {} };
let calls = 0;
let releaseHeld: (() => void) | null = null;

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  calls = 0;
  releaseHeld = null;
  outcome = { kind: 'ok', body: {} };

  // ⚠️ ต้องคืนรูป `AxiosResponse` ให้ครบ (headers ต้องเป็น `AxiosHeaders` ไม่ใช่ `{}`)
  //    ไม่งั้น `vue-tsc` ล้ม — repo นี้ไม่มีการผ่อนเป็น `any`
  api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    calls += 1;
    // จับค่า ณ ตอนยิงคำขอ — `outcome` เป็น `let` ที่เทสต์แก้ระหว่างนั้นได้
    const current = outcome;

    if (current.kind === 'fail') throw current.error;
    if (current.kind === 'hold') {
      await new Promise<void>((resolve) => {
        releaseHeld = resolve;
      });
    }

    return {
      data: current.kind === 'ok' ? current.body : PROFILE,
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

/**
 * store ที่ "ล็อกอินแล้ว"
 *
 * ⚠️ ต้องตั้ง `localStorage` **ก่อน** เรียก `useAuthStore()` เพราะ setup store อ่านค่า
 *    ตั้งต้นของทุก ref จาก localStorage ตอนถูกสร้างครั้งแรกของ pinia นั้น
 */
const authedStore = () => {
  localStorage.setItem(TOKEN_KEY, 'fake-token');
  return useAuthStore();
};

/** เงียบ `console.error` ที่ fetchProfile ตั้งใจ log ไว้ (ไม่ใช่สิ่งที่เทสต์ชุดนี้ตรวจ) */
const silenceExpectedLog = () => vi.spyOn(console, 'error').mockImplementation(() => {});

describe('authStore.fetchProfile — สัญญาการคืนค่า (L3)', () => {
  it('ดึงสำเร็จ → true และค่าลงครบทั้ง store', async () => {
    outcome = { kind: 'ok', body: PROFILE };
    const store = authedStore();

    expect(await store.fetchProfile()).toBe(true);

    expect(calls).toBe(1);
    expect(store.prefix).toBe('นาย');
    expect(store.firstName).toBe('สมชาย');
    expect(store.phoneNumber).toBe('0812345678');
  });

  it('🔴 ดึงล้มเหลว → false (หัวใจของ L3 — เดิมค่านี้หายไปกับ console.error)', async () => {
    outcome = { kind: 'fail', error: new Error('ไม่สามารถเชื่อมต่อกับ Backend ได้') };
    const store = authedStore();
    silenceExpectedLog();

    expect(await store.fetchProfile()).toBe(false);
  });

  it('🔎 พิสูจน์ว่ากับดักยังมีจริง — ดูแค่ค่าใน store แยก "ไม่มีข้อมูล" กับ "ดึงไม่สำเร็จ" ไม่ออก', async () => {
    // ถ้าเทสต์นี้ล้ม (คือค่าที่อ่านได้ไม่ว่าง) แปลว่ามีคนใส่ค่า fallback ลง store
    // ⇒ กลับมาทบทวนได้ว่ายังจำเป็นต้องมีค่าที่คืนอยู่ไหม
    outcome = { kind: 'fail', error: new Error('network') };
    const store = authedStore();
    silenceExpectedLog();

    await store.fetchProfile();

    // เหมือนคนที่ยังไม่เคยมีข้อมูลเป๊ะ ๆ ⇒ ถ้าไม่มีค่าที่คืน ผู้เรียกไม่มีทางแยกออก
    expect(store.prefix).toBeNull();
    expect(store.firstName).toBeNull();
    expect(store.phoneNumber).toBeNull();
  });

  it('ดึงล้มเหลวต้องไม่ล้างค่าที่เคยได้มา — ข้อมูลเก่าที่จริง ดีกว่าฟอร์มว่าง', async () => {
    const store = authedStore();

    outcome = { kind: 'ok', body: PROFILE };
    await store.fetchProfile();
    expect(store.firstName).toBe('สมชาย');

    outcome = { kind: 'fail', error: new Error('network') };
    silenceExpectedLog();

    expect(await store.fetchProfile()).toBe(false);
    // 🔑 ถ้าวันหนึ่งมีคนเพิ่มโค้ด "เคลียร์ค่าเมื่อล้มเหลว" เทสต์นี้จะล้มทันที
    //    การล้างค่าจะทำให้อาการ L3 กลับมาในรูปที่แย่กว่าเดิม (ข้อมูลหายจริง ไม่ใช่แค่ไม่โชว์)
    expect(store.firstName).toBe('สมชาย');
    expect(store.phoneNumber).toBe('0812345678');
  });

  it('ยังไม่ล็อกอิน → true และไม่ยิง API เลย (ไม่มีอะไรต้องดึง ≠ ล้มเหลว)', async () => {
    const store = useAuthStore(); // ไม่ตั้ง localStorage = ไม่มี token
    expect(store.isAuthenticated).toBe(false);

    expect(await store.fetchProfile()).toBe(true);
    expect(calls).toBe(0);
  });

  it('มีคำขอค้างอยู่ → รอบที่สองได้ true ทันที และไม่ยิงซ้ำ (dedupe เดิมยังอยู่ครบ)', async () => {
    outcome = { kind: 'hold' };
    const store = authedStore();

    const first = store.fetchProfile();
    const second = store.fetchProfile();

    expect(await second).toBe(true); // ถูกข้าม ไม่ได้ล้มเหลว
    expect(calls).toBe(1); // ⬅️ ยังกันคำขอซ้ำเหมือนก่อนแก้

    releaseHeld?.();
    expect(await first).toBe(true);
    expect(store.firstName).toBe('สมชาย');
  });
});
