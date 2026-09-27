/**
 * คีย์ทั้งหมดที่แอปเขียนลง Web Storage — **แหล่งความจริงเดียว**
 *
 * 🔑 ทำไมต้องรวมไว้ที่นี่: เดิมรายการคีย์ถูกคัดลอกไว้สองที่
 *    (`stores/auth.ts` → `AUTH_KEYS` สำหรับ `logout()` และ `services/api.ts`
 *    → ลิสต์ในตัวดัก 401) ซึ่ง **ไม่ตรงกันอยู่แล้ว** — ตัวดัก 401 ลบแค่ 8 คีย์
 *    จาก 19 ⇒ ล็อกเอาต์สองเส้นทางทิ้งขยะไว้ไม่เท่ากัน
 *    ถ้าปล่อยไว้ การเพิ่มคีย์ใหม่ทีหลังจะยิ่งทำให้สองที่นี้ต่างกันมากขึ้นเรื่อย ๆ
 *    แบบที่ไม่มีอะไรฟ้อง (ไม่มี type error ไม่มีเทสต์ไหนรู้)
 */

// =====================================================================================
// localStorage — ตัวตนผู้ใช้ (ล้างเมื่อออกจากระบบ / เมื่อ session ตาย)
// =====================================================================================

export const ACCESS_TOKEN_KEY = 'access_token';

/** เวลาที่ต่ออายุ token ครั้งล่าสุด (epoch ms) — ใช้ throttle การเรียก /api/auth/refresh */
export const TOKEN_REFRESHED_AT_KEY = 'token_refreshed_at';

export const AUTH_STORAGE_KEYS: readonly string[] = [
  ACCESS_TOKEN_KEY,
  TOKEN_REFRESHED_AT_KEY,
  'user_id_str',
  'user_prefix',
  'user_first_name',
  'user_last_name',
  'user_first_name_en',
  'user_last_name_en',
  'user_nickname_en',
  'user_email',
  'user_discord_id',
  'user_google_id',
  'user_nickname',
  'user_phone_number',
];

// =====================================================================================
// localStorage — ห้องเรียน
// =====================================================================================

/** รายการห้องทั้งหมดที่ผู้ใช้เป็นสมาชิก (JSON ของ `UserRoom[]`) — ใช้ร่วมทุกแท็บ */
export const ROOMS_KEY = 'user_rooms';

/**
 * ห้องล่าสุดที่เปิด — ใช้เป็นค่าตั้งต้นให้ **แท็บใหม่ / เปิดเบราว์เซอร์ใหม่**
 * (ต่างจาก `SESSION_ROOM_KEY` ที่เป็นของแท็บนั้น ๆ โดยเฉพาะ)
 */
export const LAST_ROOM_KEY = 'last_room_id';

/**
 * คีย์รุ่นก่อนการเปลี่ยนเป็น "หลายห้อง" — เก็บห้องได้ทีละห้องและเป็นค่าที่แบนราบ
 *
 * ⚠️ ยังต้องรู้จักคีย์เหล่านี้เพื่อ **ย้ายข้อมูลผู้ใช้เดิม** (bootstrap `user_rooms`
 *    จากค่าที่ค้างอยู่) ไม่งั้นคนที่ใช้งานอยู่จะถูกเด้งกลับไปหน้าเลือกห้องทั้งที่
 *    ยังล็อกอินอยู่ · ลบทิ้งได้หลัง `setRooms()` ทำงานสำเร็จครั้งแรก
 */
export const LEGACY_ROOM_STORAGE_KEYS: readonly string[] = [
  'current_room_id',
  'current_room_name',
  'current_room_code',
  'current_role',
  'current_is_admin',
  'current_permissions',
];

/** ทุกคีย์ใน localStorage ที่เป็นของแอปนี้ (ไม่กวาดคีย์ของเจ้าอื่น) */
export const ALL_LOCAL_STORAGE_KEYS: readonly string[] = [
  ...AUTH_STORAGE_KEYS,
  ROOMS_KEY,
  LAST_ROOM_KEY,
  ...LEGACY_ROOM_STORAGE_KEYS,
];

// =====================================================================================
// sessionStorage — สถานะเฉพาะแท็บ
// =====================================================================================

/**
 * ห้องที่แท็บนี้กำลังเปิดอยู่
 *
 * 🔑 ต้องเป็น sessionStorage ไม่ใช่ localStorage: localStorage ใช้ร่วมทุกแท็บ
 *    ⇒ เปิดห้อง B ในแท็บใหม่จะทับค่าของแท็บ A ทำให้อยู่สองห้องพร้อมกันไม่ได้
 *    (อาการเดิมที่ผู้ใช้รายงาน)
 */
export const SESSION_ROOM_KEY = 'active_room_id';

/** ทุกคีย์ใน sessionStorage ที่เป็นของแอปนี้ */
export const ALL_SESSION_STORAGE_KEYS: readonly string[] = [SESSION_ROOM_KEY];
