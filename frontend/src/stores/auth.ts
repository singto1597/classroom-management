import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import router from '@/router';
import api from '@/services/api'; 

// ✨ ฟังก์ชันกวาดล้างข้อมูลผี (Ghost Data Cleaner)
const safeGetItem = (key: string) => {
  const val = localStorage.getItem(key);
  if (!val || val === 'null' || val === 'undefined' || val === 'ไม่ระบุชื่อ') return null;
  return val;
};

export const useAuthStore = defineStore('auth', () => {
  // ดึงค่าผ่าน safeGetItem ทั้งหมด
  const token = ref<string | null>(safeGetItem('access_token'));
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

  const storedRoomId = safeGetItem('current_room_id');
  const currentRoomId = ref<number | null>(storedRoomId ? Number(storedRoomId) : null);
  const currentRoomName = ref<string | null>(safeGetItem('current_room_name'));
  const currentRoomCode = ref<string | null>(safeGetItem('current_room_code')); 
  const currentRole = ref<string | null>(safeGetItem('current_role'));

  // 🎯 เพิ่มตัวแปรเก็บสิทธิ์ที่แท้จริง (RBAC)
  const currentIsAdmin = ref<boolean>(safeGetItem('current_is_admin') === 'true');
  const currentPermissions = ref<string[]>(JSON.parse(safeGetItem('current_permissions') || '[]'));

  const isAuthenticated = computed(() => !!token.value);

  // 🚨 เปลี่ยนนิยามของ isAdmin ใหม่ทั้งหมด (เช็คจาก Flag ของ DB ไม่ใช่ป้ายชื่อตำแหน่ง)
  const isAdmin = computed(() => currentIsAdmin.value === true);

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

  // computed ใช้กับทุกหน้า (Sidebar, Header, Dashboard) แทนการโชว์ raw role
  const currentRoleLabel = computed(() => {
    const raw = currentRole.value || '';
    if (!raw) return 'สมาชิก';
    return ROLE_LABELS[raw] || raw;
  });

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

  const fetchProfile = async () => {
    if (!token.value || isFetchingProfile.value) return;
    
    isFetchingProfile.value = true;
    try {
      const data: any = await api.get(`/api/auth/me`);
      
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

    } catch (error) {
      console.error("Failed to fetch user profile", error);
    } finally {
      isFetchingProfile.value = false;
    }
  };

  const setToken = (newToken: string) => {
    token.value = newToken;
    localStorage.setItem('access_token', newToken);
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

  // 🎯 อัปเดต setRoom ให้รับพารามิเตอร์เรื่องสิทธิ์เพิ่ม
  const setRoom = (
    roomId: number, 
    roomName: string, 
    roomCode: string | null | undefined, 
    role: string, 
    userName?: string,
    isAdminFlag: boolean = false,
    permissionsArray: string[] = []
  ) => {
    currentRoomId.value = roomId;
    currentRoomName.value = roomName;
    currentRoomCode.value = roomCode || 'N/A';
    currentRole.value = role;
    currentIsAdmin.value = isAdminFlag;
    currentPermissions.value = permissionsArray;

    localStorage.setItem('current_room_id', String(roomId));
    localStorage.setItem('current_room_name', roomName);
    localStorage.setItem('current_room_code', roomCode || 'N/A');
    localStorage.setItem('current_role', role);
    localStorage.setItem('current_is_admin', String(isAdminFlag));
    localStorage.setItem('current_permissions', JSON.stringify(permissionsArray));
  };

  const clearRoom = () => {
    currentRoomId.value = null;
    currentRoomName.value = null;
    currentRoomCode.value = null;
    currentRole.value = null;
    currentIsAdmin.value = false;
    currentPermissions.value = [];
    
    localStorage.removeItem('current_room_id');
    localStorage.removeItem('current_room_name');
    localStorage.removeItem('current_room_code');
    localStorage.removeItem('current_role');
    localStorage.removeItem('current_is_admin');
    localStorage.removeItem('current_permissions');
  };

  // 🧹 รายการ key ที่แอพเราใช้ใน localStorage (ลบเฉพาะ key ของเรา ไม่กวาดหมด)
  const AUTH_KEYS = [
    'access_token',
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
    'current_room_id',
    'current_room_name',
    'current_room_code',
    'current_role',
    'current_is_admin',
    'current_permissions'
  ];

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
    clearRoom();
    AUTH_KEYS.forEach((key) => localStorage.removeItem(key));
    router.push('/login');
  };

  return {
    token, userId, prefix, firstName, lastName, firstNameEn, lastNameEn, nicknameEn, currentUserName,
    email, discordId, googleId, nickname, phoneNumber, isOnboarded,
    currentRoomId, currentRoomName, currentRoomCode, currentRole,
    currentIsAdmin, currentPermissions, // 🎯 Expose ไปให้ Component อื่นดึงไปใช้ได้
    isAuthenticated, isAdmin, currentRoleLabel,
    setToken, setUserId, setRoom, clearRoom, logout, fetchProfile
  };
});
