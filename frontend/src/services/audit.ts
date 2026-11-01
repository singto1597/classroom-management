import api from './api';
import type { AuditLogFilters, AuditLogOptions, AuditLogPage } from '@/types/audit';

/**
 * 🔍 บันทึกกิจกรรมของห้อง (P6.2)
 *
 * ⚠️ ต้องพา `target_type=room` ทุกคำขอ (เหมือน service อื่นฝั่งเว็บ) — ลืมแล้ว
 * backend จะตีความ `target_id` เป็น Discord server id ⇒ 404 หรืออ่านห้องผิด
 *
 * ⚠️ ตัวกรองที่ไม่ได้เลือก **ห้ามส่งเป็นสตริงว่าง** — backend ใช้
 * `service_name = $2` ⇒ `''` จะไม่ตรงกับใครเลย (ได้ผลลัพธ์ว่างแบบหลอกตา)
 * ⇒ ตัดคีย์ที่ไม่มีค่าออกก่อนสร้าง query
 *
 * ⚠️ `cursor` ต้องส่งกลับตามที่ได้มาเป๊ะ ๆ ห้ามแปลง/ตัด — มันคือ
 * `base64(created_at|id)` ที่ backend ใช้ตัดสินว่าหน้าถัดไปเริ่มตรงไหน
 */
const base = (roomId: number): string => `/api/classroom/${roomId}/audit-logs`;

const cleanFilters = (filters: AuditLogFilters): Record<string, string | number> => {
  const query: Record<string, string | number> = { target_type: 'room' };
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === '') continue;
    query[key] = value;
  }
  return query;
};

export const AuditService = {
  async list(roomId: number, filters: AuditLogFilters = {}): Promise<AuditLogPage> {
    return await api.get(base(roomId), { params: cleanFilters(filters) });
  },

  async options(roomId: number): Promise<AuditLogOptions> {
    // ⚠️ `/options` ต้องไม่ชนกับ `/{target_id}` — backend ประกาศ route แยกไว้แล้ว
    return await api.get(`${base(roomId)}/options`, { params: { target_type: 'room' } });
  },
};
