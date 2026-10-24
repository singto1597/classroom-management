/**
 * 🚧 "หน้านี้ยังเข้าไม่ได้" — เก็บปลายทางที่ตั้งใจไว้ระหว่างพาผู้ใช้ไปเลือกห้อง
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องเก็บ
 * ═══════════════════════════════════════════════════════════════════════════
 * ผู้ใช้ที่เปิดลิงก์ลึก เช่น `/finance/debtors` จากแชท Discord แต่ยังไม่ได้เลือกห้อง
 * จะถูก guard พาไป `/lobby` — เดิมปลายทางเดิม **หายไปเลย** ⇒ เลือกห้องเสร็จ
 * ต้องไล่กดเมนูเองอีกรอบ ทั้งที่เพิ่งเปิดลิงก์มาตรง ๆ
 *
 * ที่นี่เก็บปลายทางนั้นไว้ใน query `?next=` แล้วให้ `Lobby.vue` พากลับ
 * ผ่าน `safeRedirect()` เท่านั้น — **ห้ามอ่าน query แล้ว push ตรง ๆ** (open redirect)
 */

import type { LocationQuery, RouteLocationRaw } from 'vue-router';
import { safeRedirect } from '@/router/redirect';

/** ชื่อ query ที่ใช้ส่งปลายทาง — ต้องตรงกับ `Lobby.vue` */
export const UNAVAILABLE_QUERY_KEY = 'next';

/**
 * สร้าง location ไปหน้าเลือกห้อง พร้อมพกปลายทางเดิมไปด้วย (ถ้าปลอดภัย)
 *
 * `fullPath` ที่ไม่ผ่าน `safeRedirect()` (เช่น path ภายนอกที่ถูกยัดมา)
 * จะถูกทิ้ง — ไป lobby เฉย ๆ ดีกว่าพาไปที่อื่น
 */
export function toLobbyFor(fullPath: string): RouteLocationRaw {
  const target = safeRedirect(fullPath);
  return target ? { name: 'lobby', query: { [UNAVAILABLE_QUERY_KEY]: target } } : { name: 'lobby' };
}

/**
 * อ่านปลายทางเดิมจาก query ของ `/lobby` — คืน `null` เมื่อไม่มี/ไม่ปลอดภัย
 *
 * `LocationQuery` ให้ค่าเป็น `string | null | (string | null)[]` ⇒ ต้องดันให้เป็น
 * ค่าเดียวก่อน แล้วปล่อยให้ `safeRedirect()` ตัดสิน (มันรับ `unknown` อยู่แล้ว)
 */
export function unavailableTarget(query: LocationQuery): string | null {
  const raw = query[UNAVAILABLE_QUERY_KEY];
  const value = Array.isArray(raw) ? raw[0] : raw;
  return safeRedirect(value);
}
