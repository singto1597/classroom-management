// auth.ts
import api from './api';
import type { Router } from 'vue-router';

// 1. ✨ สร้าง Interface กำหนดสิทธิ์ให้ Store (แก้ปัญหาใช้ any)
interface MinimalAuthStore {
  setToken: (token: string) => void;
  setUserId: (id: string) => void;
}

// 2. ✨ สร้าง Interface สำหรับข้อมูลใน JWT Payload
interface JwtPayload {
  user_id?: string | number;
  discord_id?: string | number;
  sub?: string | number;
  [key: string]: any; // สำหรับค่าอื่นๆ ที่ติดมาใน Token
}

// Discord Configs
const DISCORD_CLIENT_ID = import.meta.env.VITE_DISCORD_CLIENT_ID;
const DISCORD_REDIRECT_URI = import.meta.env.VITE_DISCORD_REDIRECT_URI;

// Google Configs
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;
const GOOGLE_REDIRECT_URI = import.meta.env.VITE_GOOGLE_REDIRECT_URI;

export const getDiscordAuthUrl = (): string => {
  const scope = encodeURIComponent('identify email');
  return `https://discord.com/api/oauth2/authorize?client_id=${DISCORD_CLIENT_ID}&redirect_uri=${encodeURIComponent(DISCORD_REDIRECT_URI)}&response_type=code&scope=${scope}`;
};

export const getGoogleAuthUrl = (): string => {
  const scope = encodeURIComponent('openid email profile');
  return `https://accounts.google.com/o/oauth2/v2/auth?client_id=${GOOGLE_CLIENT_ID}&redirect_uri=${encodeURIComponent(GOOGLE_REDIRECT_URI)}&response_type=code&scope=${scope}`;
};

export const loginWithDiscord = async (code: string): Promise<{ access_token: string }> => {
  return await api.post('/api/auth/discord/login', { code });
};

export const loginWithGoogle = async (code: string): Promise<{ access_token: string }> => {
  return await api.post('/api/auth/google/login', { code });
};

/**
 * 3. ✨ แยกฟังก์ชันย่อยสำหรับแกะ JWT Token ออกมาต่างหาก (Separation of Concerns)
 * ช่วยให้โค้ดหลักอ่านง่ายขึ้น และดักจับ Error ได้เป็นสัดส่วน
 */
const decodeJwtPayload = (token: string): JwtPayload => {
  const parts = token.split('.');
  if (parts.length < 2) {
    throw new Error('โครงสร้าง JWT Token ไม่ถูกต้อง (รูปแบบไม่ครบ 3 ส่วน)');
  }

  const payloadBase64 = parts[1];
  if (!payloadBase64) {
    throw new Error('โครงสร้าง JWT Token ไม่ถูกต้อง (ไม่พบก้อน Payload)');
  }

  const base64 = payloadBase64.replace(/-/g, '+').replace(/_/g, '/');
  const jsonPayload = decodeURIComponent(
    atob(base64)
      .split('')
      .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
      .join('')
  );

  return JSON.parse(jsonPayload) as JwtPayload;
};

/**
 * 4. 🚀 ฟังก์ชันหลักสำหรับจัดการสิทธิ์เข้าสู่ระบบเมื่อสำเร็จ
 * ถอด `any` ออกแล้วใช้ Type ที่ถูกต้องทั้งหมด
 */
export const processAuthSuccess = (token: string, authStore: MinimalAuthStore, router: Router): void => {
  // บันทึก Token ทันที
  authStore.setToken(token);
  
  try {
    // เรียกใช้ฟังก์ชันแกะ Token ด้านบน
    const decoded = decodeJwtPayload(token);
    
    // ดึง User ID จาก Provider ต่างๆ
    const userId = String(decoded.user_id || decoded.discord_id || decoded.sub);
    
    if (!userId || userId === 'undefined') {
      throw new Error('ไม่พบข้อมูล User ID ภายใน Token');
    }

    // บันทึกข้อมูลและพาวาร์ปไปหน้าเลือกห้อง
    authStore.setUserId(userId);
    router.push('/lobby');
    
  } catch (err: any) {
    console.error('JWT Processing error:', err);
    throw new Error(`การประมวลผลสิทธิ์ล้มเหลว: ${err.message}`);
  }
};