import type { Page } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Session ของ E2E — มาจาก `backend/scripts/e2e_seed.py`
 *
 * 🔑 ทำไมต้อง seed แทนการกดปุ่ม login: ระบบนี้ล็อกอินผ่าน Discord/Google OAuth
 *    เท่านั้น ⇒ E2E ที่ต้องพึ่ง provider จริงจะเปราะและต้องมี secret
 *    เราข้ามเฉพาะขั้น OAuth (ออก token ด้วยฟังก์ชันเดียวกับที่ login ใช้) แล้วปล่อย
 *    ให้ทุกอย่างหลัง login ถูกทดสอบจริง — router guard, room bootstrap, API, ฟอร์ม
 */
export interface E2ESession {
  token: string
  user: {
    id: number
    prefix: string
    first_name: string
    last_name: string
    phone_number: string
  }
  room: {
    id: number
    name: string
    code: string
  }
}

const SESSION_PATH = join(dirname(fileURLToPath(import.meta.url)), '.auth', 'session.json')

export function loadSession(): E2ESession | null {
  if (!existsSync(SESSION_PATH)) return null
  return JSON.parse(readFileSync(SESSION_PATH, 'utf-8')) as E2ESession
}

/**
 * ใส่ session ลง localStorage/sessionStorage **ก่อน** แอปโหลด
 *
 * ต้องเป็น `addInitScript` ไม่ใช่ `page.evaluate` หลัง goto — เพราะ router guard
 * ตรวจ token ตั้งแต่ navigation แรก ถ้าใส่ช้าเกินไปจะถูกเด้งไป `/login` ก่อน
 * (คีย์ทั้งหมดต้องตรงกับ `constants/storageKeys.ts` ฝั่งแอป)
 */
export async function seedSession(page: Page, session: E2ESession): Promise<void> {
  await page.addInitScript((s: E2ESession) => {
    const room = {
      room_id: s.room.id,
      room_name: s.room.name,
      room_code: s.room.code,
      role: 'president',
      status: 'active',
      is_admin: true,
      permissions: [],
    }

    const entries: Record<string, string> = {
      access_token: s.token,
      user_id_str: String(s.user.id),
      user_prefix: s.user.prefix,
      user_first_name: s.user.first_name,
      user_last_name: s.user.last_name,
      user_phone_number: s.user.phone_number,
      user_rooms: JSON.stringify([room]),
      last_room_id: String(s.room.id),
    }

    for (const [key, value] of Object.entries(entries)) {
      localStorage.setItem(key, value)
    }
    sessionStorage.setItem('active_room_id', String(s.room.id))
  }, session)
}
