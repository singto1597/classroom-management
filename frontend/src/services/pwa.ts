/**
 * 📲 ฝั่งเบราว์เซอร์ของ PWA — ลงทะเบียน service worker + ตรวจว่ากำลังเปิดแบบติดตั้งแล้วหรือไม่
 *
 * ⚠️ **ลงทะเบียนเฉพาะ production build**
 * ในโหมด dev Vite เสิร์ฟไฟล์จาก `public/` ตรง ๆ แต่ไฟล์ `/assets/*` ยังไม่มี hash
 * ⇒ service worker ที่แคชแบบ cache-first จะค้างโค้ดเก่าไว้ และ hot-reload จะดูเหมือนพัง
 * (แก้โค้ดแล้วหน้าไม่เปลี่ยน) ซึ่งเสียเวลาหาสาเหตุมากกว่าประโยชน์ที่ได้
 *
 * 📌 ไม่มี `any` และไม่โยน exception ออกไป — PWA เป็นส่วนเสริม ถ้าลงทะเบียนไม่ได้
 *    แอปต้องยังใช้งานได้ครบเหมือนเดิม (แค่ไม่มี push/ติดตั้ง)
 */

/** ไฟล์ SW อยู่ที่รากของ origin — scope ครอบทั้งแอป */
const SW_URL = '/sw.js';

let registrationPromise: Promise<ServiceWorkerRegistration | null> | null = null;

/** เบราว์เซอร์รองรับ service worker ไหม (Safari ในPrivate mode เก่า ๆ ไม่รองรับ) */
export function isServiceWorkerSupported(): boolean {
  return typeof navigator !== 'undefined' && 'serviceWorker' in navigator;
}

/**
 * ลงทะเบียน service worker ครั้งเดียวต่อหน้า (idempotent)
 *
 * คืน `null` เมื่อไม่รองรับ/ไม่ใช่ production/ลงทะเบียนล้ม — ผู้เรียกไม่ต้องเช็คเอง
 */
export function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (registrationPromise) return registrationPromise;

  registrationPromise = (async () => {
    if (!isServiceWorkerSupported() || !import.meta.env.PROD) return null;
    try {
      return await navigator.serviceWorker.register(SW_URL, { scope: '/' });
    } catch (error) {
      console.error('[pwa] ลงทะเบียน service worker ไม่สำเร็จ:', error);
      return null;
    }
  })();

  return registrationPromise;
}

/** ดึง registration ที่มีอยู่ (ลงทะเบียนให้ถ้ายังไม่มี) */
export async function getServiceWorkerRegistration(): Promise<ServiceWorkerRegistration | null> {
  return await registerServiceWorker();
}

/**
 * เปิดอยู่แบบ "ติดตั้งแล้ว" หรือไม่ (standalone / iOS full-screen)
 * ใช้ตัดสินใจว่าจะโชว์ป้ายเชิญติดตั้งไหม — คนที่ติดตั้งแล้วไม่ควรเห็น
 */
export function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
  return window.matchMedia('(display-mode: standalone)').matches || iosStandalone;
}

/** อุปกรณ์ชี้แบบหยาบ = มือถือ/แท็บเล็ต — เงื่อนไขเดียวที่เราจะเสนอ "ติดตั้ง" */
export function isCoarsePointer(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(pointer: coarse)').matches;
}

/** iOS/iPadOS — ไม่มี `beforeinstallprompt` ต้องแนะนำผ่านเมนูแชร์แทน */
export function isIOS(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
}

/**
 * เก็บ event `beforeinstallprompt` ไว้ใช้ภายหลัง
 *
 * ⚠️ event นี้ยิง **ครั้งเดียวตอนโหลดหน้า** — ถ้าไปฟังตอน component mount
 * (หลัง Vue เริ่ม) จะพลาดไปแล้วในบางเบราว์เซอร์ จึงฟังที่ระดับโมดูล
 * แล้วให้ component มาอ่านค่าทีหลัง (`services/pwa.ts` ถูก import จาก `main.ts`)
 */
export interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;

export function captureInstallPrompt(): void {
  if (typeof window === 'undefined') return;
  window.addEventListener('beforeinstallprompt', (event) => {
    // บล็อกแถบติดตั้งอัตโนมัติของเบราว์เซอร์ — เราจะเสนอเองในจังหวะที่ผู้ใช้พร้อม
    event.preventDefault();
    deferredPrompt = event as BeforeInstallPromptEvent;
  });
}

/** event ที่เก็บไว้ (null = เบราว์เซอร์ไม่รองรับ หรือผู้ใช้ติดตั้งแล้ว) */
export function getInstallPrompt(): BeforeInstallPromptEvent | null {
  return deferredPrompt;
}

/** เรียกกล่องติดตั้งของเบราว์เซอร์ · คืนผลลัพธ์ที่ผู้ใช้เลือก */
export async function promptInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  const prompt = deferredPrompt;
  if (!prompt) return 'unavailable';
  try {
    await prompt.prompt();
    const choice = await prompt.userChoice;
    return choice.outcome;
  } catch (error) {
    console.error('[pwa] เปิดกล่องติดตั้งไม่สำเร็จ:', error);
    return 'unavailable';
  } finally {
    // ใช้ได้ครั้งเดียวต่อ event
    deferredPrompt = null;
  }
}
