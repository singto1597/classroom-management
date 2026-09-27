import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import router from '@/router';
import api from '@/services/api';
import { refreshAccessToken, type UserProfileResponse } from '@/services/auth';
import type { UserRoom } from '@/types/classroom';
import {
  ACCESS_TOKEN_KEY,
  ALL_LOCAL_STORAGE_KEYS,
  ALL_SESSION_STORAGE_KEYS,
  LAST_ROOM_KEY,
  LEGACY_ROOM_STORAGE_KEYS,
  ROOMS_KEY,
  SESSION_ROOM_KEY,
  TOKEN_REFRESHED_AT_KEY,
} from '@/constants/storageKeys';

/** ต่ออายุ token ได้เมื่อผ่านไปเกินช่วงนี้ (ตอนเปิดแอป) — ไม่ต้องยิงทุกครั้งที่โหลดหน้า */
const TOKEN_REFRESH_INTERVAL_MS = 12 * 60 * 60 * 1000;

// ✨ ฟังก์ชันกวาดล้างข้อมูลผี (Ghost Data Cleaner)
//    รับ `storage` เข้ามาได้ เพราะห้องที่เปิดอยู่เก็บใน sessionStorage ไม่ใช่ localStorage
const safeGetItem = (key: string, storage: Storage = localStorage) => {
  const val = storage.getItem(key);
  if (!val || val === 'null' || val === 'undefined' || val === 'ไม่ระบุชื่อ') return null;
  return val;
};

/** อ่าน JSON แบบไม่โยน exception — ค่าที่พังต้องไม่ทำให้แอปทั้งแอปสร้าง store ไม่ขึ้น */
const safeParseArray = <T,>(raw: string | null): T[] => {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
};

/**
 * ห้องที่ใช้ได้จริง — กรองข้อมูลผีที่อาจค้างอยู่ใน storage
 *
 * ⚠️ ต้องกรอง ไม่งั้นค่าอย่าง `room_name: undefined` จะไหลเข้าไปใน UI เงียบ ๆ
 *    (บทเรียนเดิมของ repo นี้ — ดู docs/skills.md หัวข้อ `room_name: undefined`)
 */
const isUsableRoom = (room: UserRoom | null | undefined): room is UserRoom =>
  !!room &&
  typeof room.room_id === 'number' &&
  Number.isFinite(room.room_id) &&
  typeof room.room_name === 'string' &&
  room.room_name.trim() !== '';

/** อ่านรายการห้องจาก localStorage — **synchronous โดยเจตนา** (router guard ต้องใช้ค่าทันที) */
const readStoredRooms = (): UserRoom[] => {
  const stored = safeParseArray<UserRoom>(safeGetItem(ROOMS_KEY)).filter(isUsableRoom);
  if (stored.length > 0) return stored;

  // ไม่มีรายการห้อง แต่มีคีย์รุ่นเก่าค้างอยู่ = ผู้ใช้ที่ใช้งานมาตั้งแต่ก่อนเปลี่ยนระบบ
  // ⇒ สร้างรายการชั่วคราวจากค่าที่มี เพื่อไม่ให้ถูกเด้งกลับหน้าเลือกห้องทั้งที่ยังล็อกอินอยู่
  //    (Lobby จะ fetch รายการจริงมาเขียนทับในอีกไม่ช้า)
  const legacyRoomId = Number(safeGetItem('current_room_id'));
  const legacyName = safeGetItem('current_room_name');
  if (!Number.isFinite(legacyRoomId) || legacyRoomId <= 0 || !legacyName) return [];

  const permissions = safeParseArray<unknown>(safeGetItem('current_permissions')).filter(
    (p): p is string => typeof p === 'string'
  );

  return [
    {
      room_id: legacyRoomId,
      room_name: legacyName,
      room_code: safeGetItem('current_room_code') ?? undefined,
      role: safeGetItem('current_role') ?? 'student',
      status: 'active',
      is_admin: safeGetItem('current_is_admin') === 'true',
      permissions,
    },
  ];
};

/**
 * อ่านห้องที่แท็บนี้เปิดอยู่ — เรียงตามความจำเพาะ:
 *   1. `sessionStorage` = ห้องที่ **แท็บนี้** เลือกไว้ (แม่นสุด)
 *   2. `last_room_id` = ห้องล่าสุดของเบราว์เซอร์นี้ (ให้แท็บใหม่เปิดมาเจอห้องเดิม)
 *   3. `current_room_id` = คีย์รุ่นเก่า — **จำเป็นสำหรับผู้ใช้ที่ใช้งานมาตั้งแต่ก่อนเปลี่ยนระบบ**
 *      ถ้าไม่มีข้อนี้ คนกลุ่มนั้นจะถูกเด้งกลับหน้าเลือกห้องทั้งที่ยังล็อกอินอยู่
 *      (เทสต์ `roomState.spec.ts` → "ย้ายเข้าที่อัตโนมัติ" จับเคสนี้ไว้)
 */
const readActiveRoomId = (): number | null => {
  const raw =
    safeGetItem(SESSION_ROOM_KEY, sessionStorage) ??
    safeGetItem(LAST_ROOM_KEY) ??
    safeGetItem('current_room_id');
  const id = Number(raw);
  return Number.isFinite(id) && id > 0 ? id : null;
};

/** true เมื่อสคริปต์อยู่ในเบราว์เซอร์จริง (กัน test runner ที่ไม่มี sessionStorage) */
const hasWebStorage = (): boolean =>
  typeof window !== 'undefined' && typeof window.sessionStorage !== 'undefined';

/** ตัวดัก `storage` ผูกกับ `window` ครั้งเดียวต่อหน้าเว็บ (ไม่ใช่ต่อ store instance) */
let isStorageSyncAttached = false;

export const useAuthStore = defineStore('auth', () => {
  // ดึงค่าผ่าน safeGetItem ทั้งหมด
  const token = ref<string | null>(safeGetItem(ACCESS_TOKEN_KEY));
  const userId = ref<string | null>(safeGetItem('user_id_str'));

  const prefix = ref<string | null>(safeGetItem('user_prefix'));
  const firstName = ref<string | null>(safeGetItem('user_first_name'));
  const lastName = ref<string | null>(safeGetItem('user_last_name'));
  // 🌟 ชื่อภาษาอังกฤษ — กุญแจตัวตนหลัก (identity/dedupe/search); แสดงเมื่อไม่มีชื่อไทย
  const firstNameEn = ref<string | null>(safeGetItem('user_first_name_en'));
  const lastNameEn = ref<string | null>(safeGetItem('user_last_name_en'));
  const nicknameEn = ref<string | null>(safeGetItem('user_nickname_en'));
  const email = ref<string | null>(safeGetItem('user_email'));
  const discordId = ref<string | null>(safeGetItem('user_discord_id'));
  const googleId = ref<string | null>(safeGetItem('user_google_id'));
  const nickname = ref<string | null>(safeGetItem('user_nickname'));
  const phoneNumber = ref<string | null>(safeGetItem('user_phone_number'));

  // ===================================================================================
  // 🏫 ห้องเรียน — แยกระหว่าง "รายการห้อง" กับ "ห้องที่แท็บนี้เปิดอยู่"
  // ===================================================================================
  //
  // เดิมเก็บเป็นค่าชุดเดียวใน localStorage (`current_room_id` + ผองเพื่อน) ซึ่งใช้ร่วม
  // ทุกแท็บ ⇒ เปิดห้อง B ในแท็บใหม่จะทับค่าของแท็บ A ทำให้อยู่สองห้องพร้อมกันไม่ได้
  //
  // ตอนนี้: `rooms` (รายการห้อง + สิทธิ์ของแต่ละห้อง) อยู่ใน localStorage ใช้ร่วมทุกแท็บ
  //         `activeRoomId` (ห้องที่เปิดอยู่) อยู่ใน sessionStorage = ของแท็บนี้เท่านั้น
  //
  // 🔑 ชื่อ `currentRoom*` ทั้งหมดยังคงอยู่ แต่เปลี่ยนจาก ref เป็น computed ที่คำนวณจาก
  //    สองตัวข้างบน ⇒ วิวอีก ~35 ไฟล์ที่เรียก `authStore.currentRoomId` ไม่ต้องแก้อะไรเลย

  const rooms = ref<UserRoom[]>(readStoredRooms());
  const activeRoomId = ref<number | null>(readActiveRoomId());

  const currentRoom = computed<UserRoom | null>(
    () => rooms.value.find((room) => room.room_id === activeRoomId.value) ?? null
  );

  // ⚠️ ผูกกับ `currentRoom` ไม่ใช่ `activeRoomId` โดยเจตนา — ถ้าห้องที่ active ไม่อยู่ใน
  //    รายการแล้ว (ถูกลบ / ถูกถอดสิทธิ์) ต้องมองเป็น "ไม่มีห้อง" ⇒ router guard เด้งไป
  //    หน้าเลือกห้อง ดีกว่าปล่อยให้เข้าไปในหน้าที่ข้อมูลจะพังทุกคำขอ
  const currentRoomId = computed<number | null>(() => currentRoom.value?.room_id ?? null);
  const currentRoomName = computed<string | null>(() => currentRoom.value?.room_name ?? null);
  const currentRoomCode = computed<string | null>(() => currentRoom.value?.room_code ?? null);
  const currentRole = computed<string | null>(() => currentRoom.value?.role ?? null);

  // 🎯 สิทธิ์ที่แท้จริง (RBAC) ของห้องที่กำลังเปิด
  const currentIsAdmin = computed<boolean>(() => currentRoom.value?.is_admin === true);
  const currentPermissions = computed<string[]>(() => currentRoom.value?.permissions ?? []);

  const isAuthenticated = computed(() => !!token.value);

  // 🚨 เปลี่ยนนิยามของ isAdmin ใหม่ทั้งหมด (เช็คจาก Flag ของ DB ไม่ใช่ป้ายชื่อตำแหน่ง)
  const isAdmin = computed(() => currentIsAdmin.value === true);

  // 🎯 เช็คสิทธิ์รายตัวให้ตรงกับ backend (core/rbac.py: require_permission) — isAdmin เป็น superset
  //    ⚠️ backend ไม่มี wildcard "all" — `required_permission not in user_permissions` คือเช็คตรงตัว
  //    ถ้าวันหนึ่งเพิ่ม wildcard ที่นั่น ต้องมาแก้ที่นี่ด้วย ไม่งั้นปุ่มจะถูกซ่อนทั้งที่ API อนุญาต
  const hasPermission = (permission: string): boolean =>
    currentIsAdmin.value === true || currentPermissions.value.includes(permission);

  // 🎯 งานการเงิน (เขียน): ตรงกับ require_permission(conn, room_id, user_id, "MANAGE_FINANCE")
  const canManageFinance = computed(() => hasPermission('MANAGE_FINANCE'));

  // 🏷️ แปลง class_role (จาก Backend เป็นภาษาอังกฤษ) → ป้ายภาษาไทยสำหรับ UI
  const ROLE_LABELS: Record<string, string> = {
    student: 'นักเรียน',
    president: 'หัวหน้าห้อง',
    vice_president: 'รองหัวหน้าห้อง',
    secretary: 'เลขานุการ (เรขา)',
    vice_academic: 'รองวิชาการ',
    vice_activity: 'รองกิจกรรม',
    vice_discipline: 'รองระเบียบวินัย',
    vice_reception: 'รองปฏิคม',
    vice_pr: 'รองประชาสัมพันธ์',
    vice_sanitation: 'รองสุขาภิบาล',
    staff_academic: 'กรรมการวิชาการ',
    staff_activity: 'กรรมการกิจกรรม',
    staff_discipline: 'กรรมการระเบียบวินัย',
    staff_reception: 'กรรมการปฏิคม',
    staff_pr: 'กรรมการประชาสัมพันธ์',
    staff_sanitation: 'กรรมการสุขาภิบาล',
    treasurer: 'เหรัญญิก',
    admin: 'ผู้ดูแลระบบ'
  };

  /**
   * แปลง class_role → ป้ายไทย
   *
   * เปิดเป็นฟังก์ชันสาธารณะ (ไม่ใช่แค่ computed ของห้องปัจจุบัน) เพราะตัวสลับห้อง
   * ต้องแสดงบทบาทของ **ทุกห้องในรายการ** เพื่อให้เลือกถูกว่าห้องไหนเป็นอะไร
   */
  const roleLabel = (role: string | null | undefined): string => {
    const raw = role || '';
    if (!raw) return 'สมาชิก';
    return ROLE_LABELS[raw] || raw;
  };

  // computed ใช้กับทุกหน้า (Sidebar, Header, Dashboard) แทนการโชว์ raw role
  const currentRoleLabel = computed(() => roleLabel(currentRole.value));

  const isOnboarded = computed(() => !!prefix.value && prefix.value.trim() !== '' && !!phoneNumber.value && phoneNumber.value.trim() !== '');

  // ประกอบชื่อให้สมบูรณ์ — ชื่อไทยก่อน (ถ้ามี) แล้วค่อยชื่ออังกฤษ
  const currentUserName = computed(() => {
    const p = prefix.value || '';
    const f = firstName.value || '';
    const l = lastName.value || '';
    const full = `${p}${f} ${l}`.trim();
    if (full) return full;
    const enF = firstNameEn.value || '';
    const enL = lastNameEn.value || '';
    return `${enF} ${enL}`.trim() || 'ผู้ใช้งานระบบ';
  });

  const isFetchingProfile = ref(false);

  /**
   * ดึงโปรไฟล์ล่าสุดจาก Backend แล้วเขียนทับค่าทั้งหมดใน store + localStorage
   *
   * @returns `true` = **ไม่มีความล้มเหลวให้รายงาน** · `false` = ดึงไม่สำเร็จ
   *
   * 🔑 ทำไมต้องคืนค่า (เดิมเป็น `void` แล้วกลืน error ด้วย `console.error` เฉย ๆ):
   *    ผู้เรียกที่ต้องรู้ว่า "ข้อมูลพร้อมใช้แล้วหรือยัง" แยกไม่ออกระหว่าง
   *    **"ดึงเสร็จและค่าว่าง"** กับ **"ดึงไม่สำเร็จแล้วยังค่าว่าง"** — ทั้งสองอย่าง
   *    มองจากข้างนอกเหมือนกันเป๊ะ ⇒ หน้าออนบอร์ดจึงขึ้นฟอร์มว่างเปล่าโดยไม่บอกอะไร
   *    ⇒ คนที่มีข้อมูลอยู่ในระบบแล้ว (ล็อกอินเครื่องใหม่ / เน็ตสะดุด) เข้าใจว่า
   *      "ข้อมูลหาย" หรือกรอกทับข้อมูลเดิมของตัวเองโดยไม่รู้ตัว
   *
   * ⚠️ `true` สองกรณีแรก (ไม่มี token / มีรอบค้างอยู่) หมายถึง **"ไม่มีอะไรต้องรายงาน"**
   *    ไม่ได้แปลว่า "ดึงข้อมูลมาแล้ว" — ผู้เรียกต้องอ่านค่าจริงจาก store อีกชั้น
   *    (ปัจจุบันมี Onboarding เป็นผู้ใช้ค่าที่คืนเพียงรายเดียว และอยู่บนเส้นทางที่มี token แน่นอน)
   */
  const fetchProfile = async (): Promise<boolean> => {
    // ยังไม่ล็อกอิน = ไม่มีอะไรให้ดึง และไม่ใช่ความล้มเหลว
    if (!token.value) return true;
    // มีการดึงค้างอยู่แล้ว = รอบนี้ถูกข้าม ไม่ใช่ความล้มเหลว
    if (isFetchingProfile.value) return true;

    isFetchingProfile.value = true;
    try {
      const data = await api.get(`/api/auth/me`) as unknown as UserProfileResponse;

      if (data.id) setUserId(data.id);

      prefix.value = data.prefix && data.prefix !== 'null' ? data.prefix : '';
      firstName.value = data.first_name && data.first_name !== 'null' && data.first_name !== 'ไม่ระบุชื่อ' ? data.first_name : '';
      lastName.value = data.last_name && data.last_name !== 'null' ? data.last_name : '';
      firstNameEn.value = data.first_name_en && data.first_name_en !== 'null' ? data.first_name_en : '';
      lastNameEn.value = data.last_name_en && data.last_name_en !== 'null' ? data.last_name_en : '';
      nicknameEn.value = data.nickname_en && data.nickname_en !== 'null' ? data.nickname_en : '';
      email.value = data.email && data.email !== 'null' ? data.email : '';
      discordId.value = data.discord_id ? String(data.discord_id) : null;
      googleId.value = data.google_id ? String(data.google_id) : null;
      nickname.value = data.nickname && data.nickname !== 'null' ? data.nickname : '';
      phoneNumber.value = data.phone_number && data.phone_number !== 'null' ? data.phone_number : '';

      if (prefix.value) localStorage.setItem('user_prefix', prefix.value);
      else localStorage.removeItem('user_prefix');

      if (firstName.value) localStorage.setItem('user_first_name', firstName.value);
      else localStorage.removeItem('user_first_name');

      if (lastName.value) localStorage.setItem('user_last_name', lastName.value);
      else localStorage.removeItem('user_last_name');

      if (firstNameEn.value) localStorage.setItem('user_first_name_en', firstNameEn.value);
      else localStorage.removeItem('user_first_name_en');
      if (lastNameEn.value) localStorage.setItem('user_last_name_en', lastNameEn.value);
      else localStorage.removeItem('user_last_name_en');
      if (nicknameEn.value) localStorage.setItem('user_nickname_en', nicknameEn.value);
      else localStorage.removeItem('user_nickname_en');

      if (email.value) localStorage.setItem('user_email', email.value);
      if (discordId.value) localStorage.setItem('user_discord_id', discordId.value);
      if (googleId.value) localStorage.setItem('user_google_id', googleId.value);
      if (nickname.value) localStorage.setItem('user_nickname', nickname.value);
      else localStorage.removeItem('user_nickname');
      if (phoneNumber.value) localStorage.setItem('user_phone_number', phoneNumber.value);
      else localStorage.removeItem('user_phone_number');

      return true;
    } catch (error) {
      // 🔕 ยัง log ไว้เหมือนเดิม (เป็นร่องรอยให้ dev) แต่ **ไม่กลืน** อีกต่อไป —
      //    คืน `false` ให้ผู้เรียกรู้ว่าข้อมูลที่อ่านได้ยังไม่ใช่ของจริง
      console.error("Failed to fetch user profile", error);
      return false;
    } finally {
      isFetchingProfile.value = false;
    }
  };

  const setToken = (newToken: string) => {
    token.value = newToken;
    localStorage.setItem(ACCESS_TOKEN_KEY, newToken);
    // ประทับเวลาไว้ตรงนี้จุดเดียว — ครอบทั้งตอนล็อกอินและตอนต่ออายุ
    // ⇒ เปิดแอปครั้งถัดไปจะไม่ยิง refresh ซ้ำถ้าเพิ่งได้ token มาไม่นาน
    localStorage.setItem(TOKEN_REFRESHED_AT_KEY, String(Date.now()));
  };

  const setUserId = (id: string | number | null | undefined) => {
    if (id === null || id === undefined) {
      userId.value = null;
      localStorage.removeItem('user_id_str');
    } else {
      const idStr = String(id);
      userId.value = idStr;
      localStorage.setItem('user_id_str', idStr);
    }
  };

  /**
   * เก็บกวาดคีย์รุ่นก่อน — เรียก **หลัง** ได้รายการห้องจริงจากเซิร์ฟเวอร์แล้วเท่านั้น
   * (ถ้าเรียกก่อนหน้า จะลบข้อมูลที่ใช้ bootstrap ระหว่างทางทิ้ง)
   */
  const clearLegacyRoomKeys = () => {
    LEGACY_ROOM_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));
  };

  /** เขียนรายการห้องทั้งชุดลง store + localStorage (ใช้ร่วมทุกแท็บ) */
  const setRooms = (list: UserRoom[]) => {
    rooms.value = list.filter(isUsableRoom);
    localStorage.setItem(ROOMS_KEY, JSON.stringify(rooms.value));
    // ได้ข้อมูลจริงแล้ว ⇒ คีย์เก่าไม่มีประโยชน์อีก เก็บกวาดได้
    clearLegacyRoomKeys();
    // ห้องที่เปิดอยู่อาจไม่ปรากฏในรายการใหม่ (ถูกลบ / ถูกถอดสิทธิ์)
    if (activeRoomId.value !== null && currentRoom.value === null) clearActiveRoom();
  };

  /** เปิดห้องใน **แท็บนี้** — ไม่กระทบแท็บอื่นที่อาจเปิดห้องอื่นอยู่ */
  const setActiveRoom = (roomId: number) => {
    activeRoomId.value = roomId;
    if (hasWebStorage()) sessionStorage.setItem(SESSION_ROOM_KEY, String(roomId));
    // จดไว้เป็นค่าเริ่มต้นของแท็บใหม่/รอบเปิดเบราว์เซอร์ถัดไป (พฤติกรรมเดิมที่ผู้ใช้คุ้น)
    localStorage.setItem(LAST_ROOM_KEY, String(roomId));
  };

  /** ออกจากห้องที่เปิดอยู่ — ไม่ลบรายการห้อง และไม่ล็อกเอาต์ */
  const clearActiveRoom = () => {
    activeRoomId.value = null;
    if (hasWebStorage()) sessionStorage.removeItem(SESSION_ROOM_KEY);
    localStorage.removeItem(LAST_ROOM_KEY);
  };

  /**
   * ต่ออายุ session ล่วงหน้า — ให้ผู้ใช้ไม่ต้องล็อกอินใหม่เมื่อ token ครบอายุ
   *
   * เรียกตอนเปิดแอป (MainLayout) และ throttle ด้วย `TOKEN_REFRESHED_AT_KEY`
   * ⇒ token ที่อายุ 30 วันจะถูกต่อใหม่เรื่อย ๆ ตราบใดที่ยังเข้าใช้งาน
   */
  const refreshSession = async (): Promise<void> => {
    if (!token.value) return;

    const lastRefreshedAt = Number(safeGetItem(TOKEN_REFRESHED_AT_KEY) ?? 0);
    if (Date.now() - lastRefreshedAt < TOKEN_REFRESH_INTERVAL_MS) return;

    try {
      const result = await refreshAccessToken();
      setToken(result.access_token);
      if (result.user_id) setUserId(result.user_id);
    } catch {
      // 🔕 ต่ออายุไม่สำเร็จ ณ จุดนี้ **ไม่ใช่เรื่องที่ต้องรายงาน** —
      //    token เดิมอาจยังใช้ได้อีกนาน (เน็ตสะดุด / backend รีสตาร์ทชั่วคราว)
      //    ถ้ามันตายจริง คำขอถัดไปจะได้ 401 แล้วตัวดักใน services/api.ts จัดการเอง
      //    ⇒ ไม่ล้าง token ที่นี่ ไม่งั้นจะกลายเป็นการล็อกเอาต์ผู้ใช้เพราะเน็ตกระตุก
    }
  };

  const logout = () => {
    token.value = null;
    userId.value = null;
    prefix.value = null;
    firstName.value = null;
    lastName.value = null;
    firstNameEn.value = null;
    lastNameEn.value = null;
    nicknameEn.value = null;
    email.value = null;
    discordId.value = null;
    googleId.value = null;
    nickname.value = null;
    phoneNumber.value = null;
    rooms.value = [];
    clearActiveRoom();
    ALL_LOCAL_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));
    if (hasWebStorage()) ALL_SESSION_STORAGE_KEYS.forEach((key) => sessionStorage.removeItem(key));
    router.push('/login');
  };

  // ===================================================================================
  // 🔄 ประสานกับแท็บอื่น
  // ===================================================================================
  // localStorage ยิง event `storage` ไปยัง **แท็บอื่น** (ไม่ยิงกลับแท็บที่เขียนเอง)
  // ⇒ ใช้ซิงก์เฉพาะสิ่งที่ใช้ร่วมกัน (รายการห้อง / การล็อกเอาต์) ส่วน `activeRoomId`
  //    เป็นของแท็บนี้ จึงต้องไม่ยุ่งกับมัน
  //  ⚠️ ผูกครั้งเดียวต่อหน้าเว็บ — store ถูกสร้างใหม่ได้ (เช่นในเทสต์ที่สร้าง pinia ใหม่)
  //     ถ้าไม่กันไว้จะได้ listener ซ้อนกันหลายตัวโดยไม่มีใครรู้
  const attachStorageSync = () => {
    if (!hasWebStorage() || isStorageSyncAttached) return;
    isStorageSyncAttached = true;
    window.addEventListener('storage', (event) => {
      if (event.key === ROOMS_KEY) {
        rooms.value = readStoredRooms();
        if (activeRoomId.value !== null && currentRoom.value === null) clearActiveRoom();
        return;
      }

      // แท็บอื่นออกจากระบบ (หรือ session ตายแล้วถูกล้าง) — แท็บนี้ต้องไปด้วย
      // ไม่งั้นจะค้างในสภาพที่ดูเหมือนยังล็อกอินอยู่ แต่ยิง API ไม่ผ่านสักคำขอ
      if (event.key === ACCESS_TOKEN_KEY && !event.newValue) {
        token.value = null;
        clearActiveRoom();
        if (!window.location.pathname.startsWith('/login')) window.location.href = '/login';
      }
    });
  };

  attachStorageSync();

  return {
    token, userId, prefix, firstName, lastName, firstNameEn, lastNameEn, nicknameEn, currentUserName,
    email, discordId, googleId, nickname, phoneNumber, isOnboarded,
    rooms, activeRoomId,
    currentRoomId, currentRoomName, currentRoomCode, currentRole,
    currentIsAdmin, currentPermissions, // 🎯 Expose ไปให้ Component อื่นดึงไปใช้ได้
    isAuthenticated, isAdmin, currentRoleLabel, roleLabel,
    hasPermission, canManageFinance,
    setToken, setUserId, setRooms, setActiveRoom, clearActiveRoom, logout, fetchProfile, refreshSession
  };
});
