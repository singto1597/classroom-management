/**
 * 🔔 Web Push ฝั่งเบราว์เซอร์ — ขออนุญาต · สมัคร/เลิกสมัครอุปกรณ์ · ส่งทะเบียนให้ backend
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ลำดับที่ถูกต้อง (และสาเหตุที่ต้องเรียงแบบนี้)
 * ═══════════════════════════════════════════════════════════════════════════
 * 1. ขอคีย์ VAPID สาธารณะจาก backend — ถ้าผู้ดูแลยังไม่ตั้งคีย์ (`enabled: false`)
 *    ต้องหยุดตรงนี้ **ก่อน** ขออนุญาตผู้ใช้ (ไม่ควรขึ้นกล่องอนุญาตแล้วจบด้วย error)
 * 2. ขออนุญาต (`Notification.requestPermission`) — ต้องเรียกจาก gesture ของผู้ใช้
 *    (การกดปุ่ม) เท่านั้น ไม่งั้น Safari/Chrome บล็อกเงียบ ๆ
 * 3. `PushManager.subscribe` ด้วยคีย์จากขั้น 1
 * 4. ส่ง endpoint + keys ให้ backend เก็บ
 *
 * ⚠️ `p256dh`/`auth` ต้องเป็น base64url — ใช้ค่าเดียวกับที่เบราว์เซอร์ให้มา
 *    ห้ามแปลงเป็น base64 ปกติ ไม่งั้นฝั่ง Python ถอดรหัสไม่ตรงและส่งไม่สำเร็จ
 *
 * ⚠️ ไม่มี `any` · ทุกฟังก์ชันคืนสถานะ ไม่โยน exception ออกไปให้ UI ต้อง try/catch เอง
 */

import api from './api';
import { getServiceWorkerRegistration, isServiceWorkerSupported } from './pwa';

/** ต้องตรงกับ `PushConfigResponse` ใน `backend/models/notification_schemas.py` */
export interface PushConfig {
  /** คีย์สาธารณะ VAPID (base64url) — ว่างเมื่อยังไม่ตั้งระบบ */
  public_key: string;
  enabled: boolean;
}

export type PushPermissionState = 'unsupported' | 'default' | 'denied' | 'granted';

/** ผลของการพยายามเปิด/ปิด — UI ใช้เลือกข้อความ */
export type PushToggleOutcome =
  | 'subscribed'
  | 'unsubscribed'
  | 'unsupported'
  | 'denied'
  | 'not_configured'
  | 'error';

/** แปลง base64url → Uint8Array (รูปแบบที่ `applicationServerKey` ต้องการ) */
export function urlBase64ToUint8Array(base64Url: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64Url.length % 4)) % 4);
  const base64 = (base64Url + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(base64);
  // ⚠️ TypeScript 5.7+ พิมพ์ `Uint8Array<ArrayBufferLike>` ⇒ ระบุ buffer ตรง ๆ
  //    ไม่งั้น `applicationServerKey` ไม่รับ (BufferSource ต้องเป็น ArrayBuffer)
  const buffer = new ArrayBuffer(raw.length);
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/** สถานะการอนุญาตปัจจุบัน (ไม่ขอ — แค่อ่าน) */
export function getPermissionState(): PushPermissionState {
  if (!isServiceWorkerSupported() || typeof Notification === 'undefined') return 'unsupported';
  return Notification.permission as PushPermissionState;
}

/** ดึงคีย์ VAPID + สถานะเปิดใช้จาก backend */
export async function fetchPushConfig(roomId: number): Promise<PushConfig> {
  return await api.get(`/api/classroom/${roomId}/notifications/push/config`, {
    params: { target_type: 'room' },
  });
}

/** อุปกรณ์นี้สมัครไว้แล้วหรือยัง (ดูจากเบราว์เซอร์ ไม่ใช่จาก DB) */
export async function isSubscribedOnDevice(): Promise<boolean> {
  if (!isServiceWorkerSupported()) return false;
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration) return false;
  const subscription = await registration.pushManager.getSubscription();
  return subscription !== null;
}

/**
 * เปิดการแจ้งเตือนบนอุปกรณ์นี้
 *
 * **ต้องเรียกจากการคลิกของผู้ใช้** (ไม่ใช่ตอน mount) ไม่งั้นเบราว์เซอร์ไม่ขึ้นกล่องอนุญาต
 */
export async function enablePush(roomId: number): Promise<PushToggleOutcome> {
  if (!isServiceWorkerSupported() || typeof Notification === 'undefined') return 'unsupported';

  const config = await fetchPushConfig(roomId).catch((): PushConfig => ({ public_key: '', enabled: false }));
  if (!config.enabled || !config.public_key) return 'not_configured';

  if (Notification.permission === 'denied') return 'denied';
  if (Notification.permission !== 'granted') {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'unsupported';
  }

  const registration = await getServiceWorkerRegistration();
  if (!registration) return 'unsupported';
  await navigator.serviceWorker.ready;

  try {
    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        // Chrome บังคับให้เป็น true; Safari/Firefox ไม่สนใจค่า
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(config.public_key),
      }));

    const json = subscription.toJSON();
    const p256dh = json.keys?.p256dh;
    const auth = json.keys?.auth;
    if (!p256dh || !auth) return 'error';

    await api.post(
      `/api/classroom/${roomId}/notifications/push/subscribe?target_type=room`,
      { endpoint: subscription.endpoint, keys: { p256dh, auth } },
    );
    return 'subscribed';
  } catch (error) {
    console.error('[push] สมัครอุปกรณ์ไม่สำเร็จ:', error);
    return 'error';
  }
}

/** ปิดการแจ้งเตือนบนอุปกรณ์นี้ (ทั้งฝั่งเบราว์เซอร์และทะเบียนใน DB) */
export async function disablePush(roomId: number): Promise<PushToggleOutcome> {
  if (!isServiceWorkerSupported()) return 'unsupported';
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return 'unsubscribed';

  try {
    await api.post(`/api/classroom/${roomId}/notifications/push/unsubscribe?target_type=room`, {
      endpoint: subscription.endpoint,
    });
  } catch (error) {
    // ลบฝั่ง backend ไม่สำเร็จก็ยังต้องเลิกที่เบราว์เซอร์ ไม่งั้นผู้ใช้จะยังได้ push
    console.error('[push] แจ้ง backend เรื่องเลิกสมัครไม่สำเร็จ:', error);
  }

  try {
    await subscription.unsubscribe();
  } catch (error) {
    console.error('[push] ถอน subscription จากเบราว์เซอร์ไม่สำเร็จ:', error);
    return 'error';
  }
  return 'unsubscribed';
}

/**
 * ซิงก์ทะเบียนซ้ำเมื่อเบราว์เซอร์เปลี่ยน endpoint เอง
 * (`pushsubscriptionchange` ใน sw.js จะ postMessage มาบอก)
 */
export async function resubscribeAfterChange(roomId: number): Promise<PushToggleOutcome> {
  if (getPermissionState() !== 'granted') return 'unsupported';
  return await enablePush(roomId);
}
