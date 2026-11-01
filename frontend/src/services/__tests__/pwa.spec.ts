import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  isCoarsePointer,
  isStandalone,
  promptInstall,
  registerServiceWorker,
} from '@/services/pwa';
import { urlBase64ToUint8Array } from '@/services/push';

/**
 * 📲 PWA — กฎที่ล็อกไว้
 *
 *   • `urlBase64ToUint8Array` ต้องถอดคีย์ VAPID ที่มี `-`/`_` และไม่มี `=` ได้
 *     (ถ้าถอดผิด ฝั่ง Python จะถอดรหัสไม่ตรงและ push ล้มเงียบ ๆ ทุกเครื่อง)
 *   • เงื่อนไข "ติดตั้งแล้ว" / "อุปกรณ์ชี้แบบหยาบ" ต้องอ่านจาก `matchMedia`
 *     ตัวเดียวกับที่ component ใช้ตัดสินใจ (ห้ามเดาจาก user-agent ในสองที่)
 *   • ไม่ใช่ production build ⇒ ไม่ลงทะเบียน SW (กัน cache ค้างตอน dev)
 */

/** รูปย่อของ MediaQueryList ที่โค้ดจริงอ่านแค่ `.matches` */
interface MatchMediaStub {
  matches: boolean;
  media: string;
  onchange: null;
  addListener: () => void;
  removeListener: () => void;
  addEventListener: () => void;
  removeEventListener: () => void;
  dispatchEvent: () => boolean;
}

function stubMatchMedia(matches: (query: string) => boolean): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn<(query: string) => MatchMediaStub>((query: string) => ({
      matches: matches(query),
      media: query,
      onchange: null,
      addListener: vi.fn<() => void>(),
      removeListener: vi.fn<() => void>(),
      addEventListener: vi.fn<() => void>(),
      removeEventListener: vi.fn<() => void>(),
      dispatchEvent: vi.fn<() => boolean>(),
    })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('urlBase64ToUint8Array', () => {
  it('ถอด base64url ที่ไม่มี padding ได้', () => {
    // "hello" → base64 "aGVsbG8=" → base64url "aGVsbG8"
    const bytes = urlBase64ToUint8Array('aGVsbG8');
    expect(Array.from(bytes)).toEqual([104, 101, 108, 108, 111]);
  });

  it('ถอด `-` และ `_` ได้เหมือน `+` และ `/`', () => {
    // 3 ไบต์ 0xFB 0xFF 0xBF → base64 "+/+/" → base64url "-_-_"
    const bytes = urlBase64ToUint8Array('-_-_');
    expect(Array.from(bytes)).toEqual([0xfb, 0xff, 0xbf]);
  });

  it('คืน Uint8Array ที่ใช้เป็น applicationServerKey ได้ (ArrayBuffer ตรง)', () => {
    const bytes = urlBase64ToUint8Array('aGVsbG8');
    expect(bytes.buffer).toBeInstanceOf(ArrayBuffer);
    expect(bytes.byteLength).toBe(bytes.buffer.byteLength);
  });
});

describe('isStandalone', () => {
  it('จริงเมื่อ display-mode: standalone', () => {
    stubMatchMedia((query) => query === '(display-mode: standalone)');
    expect(isStandalone()).toBe(true);
  });

  it('จริงเมื่อ iOS ตั้ง standalone ไว้ (window.navigator.standalone)', () => {
    stubMatchMedia(() => false);
    Object.defineProperty(window.navigator, 'standalone', {
      value: true,
      configurable: true,
    });
    expect(isStandalone()).toBe(true);
    // ล้างค่าที่ defineProperty ไว้ ไม่ให้รั่วไปเทสต์อื่น
    Reflect.deleteProperty(window.navigator, 'standalone');
  });

  it('เท็จเมื่อเปิดในเบราว์เซอร์ปกติ', () => {
    stubMatchMedia(() => false);
    expect(isStandalone()).toBe(false);
  });
});

describe('isCoarsePointer', () => {
  it('อ่านจาก (pointer: coarse) เท่านั้น', () => {
    stubMatchMedia((query) => query === '(pointer: coarse)');
    expect(isCoarsePointer()).toBe(true);

    stubMatchMedia((query) => query === '(hover: hover)');
    expect(isCoarsePointer()).toBe(false);
  });
});

describe('registerServiceWorker', () => {
  it('ไม่ลงทะเบียนเมื่อไม่ใช่ production build', async () => {
    const register = vi.fn<() => Promise<never>>();
    vi.stubGlobal('navigator', { ...navigator, serviceWorker: { register } });
    await expect(registerServiceWorker()).resolves.toBeNull();
    expect(register).not.toHaveBeenCalled();
  });
});

describe('promptInstall', () => {
  it('คืน unavailable เมื่อเบราว์เซอร์ไม่เคยยิง beforeinstallprompt', async () => {
    await expect(promptInstall()).resolves.toBe('unavailable');
  });
});
