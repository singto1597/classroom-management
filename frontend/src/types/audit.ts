/**
 * 🔍 บันทึกกิจกรรมของห้อง (`audit_logs`) — หน้าดูของผู้บริหารห้อง (P6.2)
 *
 * สัญญากับ backend (`routers/audit_router.py`):
 *  · ต้องมีสิทธิ์ `VIEW_AUDIT_LOGS` — สมาชิกธรรมดาได้ 403
 *  · `old_values`/`new_values` เป็น JSONB ⇒ ชนิดเป็น `unknown` ไม่ใช่ `Record`
 *    (backend เก็บได้ทั้ง object และ array; การเดาเป็น object แล้วเข้าถึง key
 *    จะ throw ตอน render)
 *  · การเลื่อนหน้าเป็น **keyset** — ส่ง `next_cursor` กลับมาเป็น `cursor`
 *    ห้ามคำนวณ offset เอง (แถวใหม่จะแทรกหัวตารางตลอดเวลา)
 *  · ช่วงวันที่เป็นวันที่ไทย `YYYY-MM-DD` และ **รวมวันสุดท้าย**
 */

export interface AuditLogItem {
  id: string;
  trace_id: string | null;
  user_id: number | null;
  /** `user_id:12` หรือ `ip:...` — ตัวระบุที่บันทึกไว้ตอนนั้นจริง ๆ */
  actor_identifier: string;
  /** ชื่อจากตาราง users (null ถ้าผู้ใช้ถูกลบ/ไม่มีแถว) */
  actor_name: string | null;
  client_source: string;
  service_name: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  status: string | null;
  error_detail: string | null;
  old_values: unknown;
  new_values: unknown;
  endpoint_or_command: string | null;
  ip_address: string | null;
  user_agent: string | null;
  execution_time_ms: number | null;
  /** ISO 8601 (มี timezone) — แสดงผลด้วย `formatThaiDateTime` */
  created_at: string;
}

export interface AuditLogPage {
  items: AuditLogItem[];
  /** null = หมดแล้ว */
  next_cursor: string | null;
  has_more: boolean;
}

export interface AuditLogOptions {
  service_names: string[];
  actions: string[];
  statuses: string[];
}

export interface AuditLogFilters {
  service_name?: string;
  action?: string;
  status?: string;
  /** ค้นในผู้ทำ / endpoint / entity / ข้อผิดพลาด */
  q?: string;
  /** `YYYY-MM-DD` (เวลาไทย, รวมวันนั้น) */
  date_from?: string;
  date_to?: string;
  /** ขนาดหน้า 1–100 */
  limit?: number;
  /** ค่าทึบจาก `next_cursor` ของหน้าก่อน */
  cursor?: string;
}
