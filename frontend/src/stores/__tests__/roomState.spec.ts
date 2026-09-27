import { describe, it, expect, beforeEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from '@/stores/auth';
import {
  ACCESS_TOKEN_KEY,
  LAST_ROOM_KEY,
  LEGACY_ROOM_STORAGE_KEYS,
  ROOMS_KEY,
  SESSION_ROOM_KEY,
} from '@/constants/storageKeys';
import type { UserRoom } from '@/types/classroom';

/**
 * ล็อกพฤติกรรม "หลายห้อง" ของ `stores/auth.ts`
 *
 * **ที่มา:** เดิม store เก็บห้องที่เปิดอยู่เป็นค่าชุดเดียวใน `localStorage`
 * (`current_room_id` + `current_role` + `current_permissions` + ...) ซึ่ง **ใช้ร่วมทุกแท็บ**
 * ⇒ เปิดห้อง B ในแท็บใหม่จะทับค่าของแท็บ A ทำให้อยู่สองห้องพร้อมกันไม่ได้
 * (ผู้ใช้รายงานว่า "อยากก็อปจากห้องนี้ไปอีกห้องนึง มันทำไม่ได้ เพราะจำคนละค่า")
 *
 * **สัญญาที่ไฟล์นี้ล็อกไว้:**
 * 1. ห้องที่เปิดอยู่เก็บใน `sessionStorage` (ของแท็บนั้น) — ไม่ใช่ `localStorage`
 * 2. แท็บใหม่ที่ยังไม่มีค่า → fallback ไปห้องล่าสุด (พฤติกรรมเดิมที่ผู้ใช้คุ้น)
 * 3. สองแท็บที่ถือค่าต่างกัน อ่านได้คนละห้อง จากรายการห้องชุดเดียวกัน
 * 4. สิทธิ์ (is_admin/permissions) **เปลี่ยนตามห้อง** ไม่ค้างของห้องก่อน
 * 5. ห้องที่เปิดอยู่หลุดจากรายการ → ถือว่า "ไม่มีห้อง" (กันค้างอยู่หน้าที่ข้อมูลจะพัง)
 * 6. ผู้ใช้เดิม (คีย์รุ่นเก่า) ถูกย้ายเข้าที่โดยไม่ถูกเด้งกลับหน้าเลือกห้อง
 */

const ROOM_A: UserRoom = {
  room_id: 101,
  room_name: 'ม.4/1',
  room_code: 'AAA111',
  role: 'president',
  status: 'active',
  is_admin: true,
  permissions: ['MANAGE_FINANCE'],
};

const ROOM_B: UserRoom = {
  room_id: 202,
  room_name: 'ม.5/2',
  room_code: 'BBB222',
  role: 'student',
  status: 'active',
  is_admin: false,
  permissions: [],
};

/** สร้าง store ใหม่จากค่าที่อยู่ใน storage ตอนนี้ (จำลอง "เปิดแท็บใหม่") */
const freshStore = () => {
  setActivePinia(createPinia());
  return useAuthStore();
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe('ห้องที่เปิดอยู่เป็นของ "แท็บนี้" ไม่ใช่ของทั้งเบราว์เซอร์', () => {
  it('setActiveRoom เก็บลง sessionStorage ซึ่งเป็นช่องทางเฉพาะแท็บ', () => {
    const auth = freshStore();
    auth.setRooms([ROOM_A, ROOM_B]);

    auth.setActiveRoom(ROOM_A.room_id);

    expect(sessionStorage.getItem(SESSION_ROOM_KEY)).toBe(String(ROOM_A.room_id));
    expect(auth.currentRoomId).toBe(ROOM_A.room_id);
  });

  it('จำห้องล่าสุดไว้ให้แท็บใหม่ — sessionStorage ว่างก็ยังเข้าห้องเดิมได้', () => {
    const first = freshStore();
    first.setRooms([ROOM_A, ROOM_B]);
    first.setActiveRoom(ROOM_B.room_id);

    // จำลอง "เปิดแท็บใหม่": sessionStorage เป็นของว่าง แต่ localStorage อยู่ครบ
    sessionStorage.clear();
    const secondTab = freshStore();

    expect(secondTab.currentRoomId).toBe(ROOM_B.room_id);
    expect(secondTab.currentRoomName).toBe('ม.5/2');
  });

  it('🔴 สองแท็บถือค่าต่างกัน → ได้คนละห้อง จากรายการห้องชุดเดียวกัน', () => {
    const tabOne = freshStore();
    tabOne.setRooms([ROOM_A, ROOM_B]);
    tabOne.setActiveRoom(ROOM_A.room_id);

    // แท็บที่สองเลือกห้องอื่น — ต้องไม่ทำให้แท็บแรกเปลี่ยนตาม
    sessionStorage.setItem(SESSION_ROOM_KEY, String(ROOM_B.room_id));
    const tabTwo = freshStore();

    expect(tabTwo.currentRoomId).toBe(ROOM_B.room_id);
    // รายการห้องยังเป็นชุดเดียวกัน (เก็บใน localStorage) — หายไปไม่ได้
    expect(tabTwo.rooms.map((r) => r.room_id)).toEqual([ROOM_A.room_id, ROOM_B.room_id]);
  });
});

describe('สิทธิ์ต้องเปลี่ยนตามห้องที่เปิดอยู่', () => {
  it('สลับจากห้องที่เป็นแอดมิน ไปห้องที่เป็นนักเรียน → สิทธิ์หายตาม', () => {
    const auth = freshStore();
    auth.setRooms([ROOM_A, ROOM_B]);

    auth.setActiveRoom(ROOM_A.room_id);
    expect(auth.currentIsAdmin).toBe(true);
    expect(auth.canManageFinance).toBe(true);
    expect(auth.currentRoleLabel).toBe('หัวหน้าห้อง');

    auth.setActiveRoom(ROOM_B.room_id);
    expect(auth.currentIsAdmin).toBe(false);
    expect(auth.canManageFinance).toBe(false);
    expect(auth.currentRoleLabel).toBe('นักเรียน');
    expect(auth.currentPermissions).toEqual([]);
  });

  it('roleLabel แปลงบทบาทของ "ห้องอื่น" ได้ ไม่ใช่แค่ห้องที่เปิดอยู่', () => {
    const auth = freshStore();
    expect(auth.roleLabel('treasurer')).toBe('เหรัญญิก');
    expect(auth.roleLabel(null)).toBe('สมาชิก');
    expect(auth.roleLabel('ไม่รู้จัก')).toBe('ไม่รู้จัก');
  });
});

describe('ห้องที่เปิดอยู่หลุดจากรายการ', () => {
  it('ห้องถูกลบ/ถูกถอดสิทธิ์ → currentRoomId เป็น null ไม่ค้างอยู่หน้าเดิม', () => {
    const auth = freshStore();
    auth.setRooms([ROOM_A, ROOM_B]);
    auth.setActiveRoom(ROOM_A.room_id);
    expect(auth.currentRoomId).toBe(ROOM_A.room_id);

    // เซิร์ฟเวอร์ตอบรายการใหม่ที่ไม่มีห้อง A แล้ว (ถูกลบ / ถูกถอดออก)
    auth.setRooms([ROOM_B]);

    expect(auth.currentRoomId).toBeNull();
    expect(sessionStorage.getItem(SESSION_ROOM_KEY)).toBeNull();
  });
});

describe('ผู้ใช้เดิมที่ยังมีคีย์รุ่นเก่าอยู่', () => {
  const seedLegacyRoom = () => {
    localStorage.setItem('current_room_id', String(ROOM_A.room_id));
    localStorage.setItem('current_room_name', ROOM_A.room_name);
    localStorage.setItem('current_room_code', ROOM_A.room_code!);
    localStorage.setItem('current_role', ROOM_A.role);
    localStorage.setItem('current_is_admin', 'true');
    localStorage.setItem('current_permissions', JSON.stringify(ROOM_A.permissions));
  };

  it('ย้ายเข้าที่อัตโนมัติ — ไม่ถูกเด้งกลับหน้าเลือกห้อง', () => {
    seedLegacyRoom();

    const auth = freshStore();

    expect(auth.currentRoomId).toBe(ROOM_A.room_id);
    expect(auth.currentRoomName).toBe(ROOM_A.room_name);
    expect(auth.currentIsAdmin).toBe(true);
    expect(auth.currentPermissions).toEqual(['MANAGE_FINANCE']);
  });

  it('เก็บกวาดคีย์เก่าทิ้งหลังได้รายการห้องจริงจากเซิร์ฟเวอร์', () => {
    seedLegacyRoom();
    const auth = freshStore();

    auth.setRooms([ROOM_A, ROOM_B]);

    LEGACY_ROOM_STORAGE_KEYS.forEach((key) => {
      expect(localStorage.getItem(key)).toBeNull();
    });
    expect(JSON.parse(localStorage.getItem(ROOMS_KEY) ?? '[]')).toHaveLength(2);
  });

  it('ข้อมูลผี (room_name ว่าง) ต้องไม่ถูกย้ายเข้ามาเป็นห้อง', () => {
    seedLegacyRoom();
    localStorage.setItem('current_room_name', '');

    const auth = freshStore();

    expect(auth.rooms).toEqual([]);
    expect(auth.currentRoomId).toBeNull();
  });
});

describe('ออกจากระบบ', () => {
  it('ล้างทั้ง localStorage และ sessionStorage ไม่เหลือห้องค้าง', () => {
    const auth = freshStore();
    auth.setToken('tok');
    auth.setRooms([ROOM_A, ROOM_B]);
    auth.setActiveRoom(ROOM_A.room_id);

    auth.logout();

    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(ROOMS_KEY)).toBeNull();
    expect(localStorage.getItem(LAST_ROOM_KEY)).toBeNull();
    expect(sessionStorage.getItem(SESSION_ROOM_KEY)).toBeNull();
    expect(auth.rooms).toEqual([]);
    expect(auth.currentRoomId).toBeNull();
  });
});
