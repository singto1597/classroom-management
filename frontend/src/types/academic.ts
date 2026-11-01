/**
 * 🗓️ ปีการศึกษา + เทอม — **ตัวกรองเวลาของสถิติ** ไม่ใช่ระบบเลื่อนชั้น (P5)
 *
 * ข้อตกลงกับ backend (`routers/academic_router.py`):
 *  · `start_date`/`end_date` เป็น DATE `YYYY-MM-DD` และ **รวมวันสุดท้าย**
 *  · ไม่มีปีปัจจุบัน (`current_year_id: null`) = สถิติไม่กรอง (ห้ามเดาปีแรก)
 *  · เทอมต้องอยู่ในช่วงของปีและห้ามทับกัน — backend ตอบ 400 พร้อมเหตุผลภาษาไทย
 *  · เขียนได้เฉพาะผู้มี `MANAGE_CLASSROOM_SETTINGS`; อ่านได้ทุกสมาชิก
 *
 * ⚠️ หน้านี้ **ไม่ย้ายนักเรียน** ไปปีใหม่ — ตัวเลขของปี/เทอมนับจาก "วันที่ของเหตุการณ์"
 * (ใบเสร็จ / วันที่จัดกิจกรรม) เท่านั้น สมาชิกทุกคนจึงอยู่ในทุกปีโดยปริยาย
 */

export interface AcademicTerm {
  id: number;
  name: string;
  /** `YYYY-MM-DD` — รวมวันสุดท้าย */
  start_date: string;
  end_date: string;
  is_current: boolean;
}

export interface AcademicYear {
  id: number;
  /** ปี พ.ศ. เช่น 2569 (ไม่ใช่ ค.ศ.) */
  year_be: number;
  name: string | null;
  start_date: string;
  end_date: string;
  is_current: boolean;
  terms: AcademicTerm[];
}

export interface AcademicPeriods {
  years: AcademicYear[];
  /** `null` = ห้องนี้ยังไม่มีปีปัจจุบัน ⇒ สถิติทั้งก้อน */
  current_year_id: number | null;
  current_term_id: number | null;
}

export interface AcademicYearInput {
  year_be: number;
  name?: string | null;
  start_date: string;
  end_date: string;
  is_current?: boolean;
}

/** PATCH — ไม่ส่งฟิลด์ = ไม่แตะ; `name: null` = ล้างชื่อ */
export interface AcademicYearPatch {
  name?: string | null;
  start_date?: string;
  end_date?: string;
}

export interface AcademicTermInput {
  name: string;
  start_date: string;
  end_date: string;
  is_current?: boolean;
}

export interface AcademicTermPatch {
  name?: string | null;
  start_date?: string;
  end_date?: string;
}

/** `year_id: null` = ปลดปี/เทอมปัจจุบัน (สถิติกลับไปนับทั้งหมด) */
export interface SetCurrentPeriodInput {
  year_id: number | null;
  term_id?: number | null;
}

export interface CurrentPeriod {
  current_year_id: number | null;
  current_term_id: number | null;
}

export interface DeletePeriodResult {
  deleted: boolean;
  year_id?: number | null;
  term_id?: number | null;
}
