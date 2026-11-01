import api from './api';
import type {
  AcademicPeriods,
  AcademicTerm,
  AcademicTermInput,
  AcademicTermPatch,
  AcademicYear,
  AcademicYearInput,
  AcademicYearPatch,
  CurrentPeriod,
  DeletePeriodResult,
  SetCurrentPeriodInput,
} from '@/types/academic';

/**
 * 🗓️ ปีการศึกษา/เทอม (P5)
 *
 * สมาชิกทุกคนเรียก `periods()` ได้ (ตัวกรองสถิติต้องใช้ร่วมกัน) แต่ endpoint เขียน
 * ทั้งหมดต้องมี `MANAGE_CLASSROOM_SETTINGS` — backend ตรวจเอง ⇒ ฝั่งหน้าแค่ซ่อนฟอร์ม
 * ไม่ใช่ตาข่ายความปลอดภัย
 *
 * ใช้ `target_type=room` เหมือน service อื่นฝั่งเว็บ
 */
const base = (roomId: number): string => `/api/classroom/${roomId}/academic`;
const opts = { params: { target_type: 'room' } } as const;

export const AcademicService = {
  async periods(roomId: number): Promise<AcademicPeriods> {
    return await api.get(`${base(roomId)}/periods`, opts);
  },

  async createYear(roomId: number, payload: AcademicYearInput): Promise<AcademicYear> {
    return await api.post(`${base(roomId)}/years`, payload, opts);
  },

  async updateYear(
    roomId: number,
    yearId: number,
    patch: AcademicYearPatch,
  ): Promise<AcademicYear> {
    return await api.patch(`${base(roomId)}/years/${yearId}`, patch, opts);
  },

  async deleteYear(roomId: number, yearId: number): Promise<DeletePeriodResult> {
    return await api.delete(`${base(roomId)}/years/${yearId}`, opts);
  },

  async createTerm(
    roomId: number,
    yearId: number,
    payload: AcademicTermInput,
  ): Promise<AcademicTerm> {
    return await api.post(`${base(roomId)}/years/${yearId}/terms`, payload, opts);
  },

  async updateTerm(roomId: number, termId: number, patch: AcademicTermPatch): Promise<AcademicTerm> {
    return await api.patch(`${base(roomId)}/terms/${termId}`, patch, opts);
  },

  async deleteTerm(roomId: number, termId: number): Promise<DeletePeriodResult> {
    return await api.delete(`${base(roomId)}/terms/${termId}`, opts);
  },

  /** `year_id: null` = ปลดปีปัจจุบัน (สถิติกลับไปนับทั้งหมด ไม่ใช่ error) */
  async setCurrent(roomId: number, payload: SetCurrentPeriodInput): Promise<CurrentPeriod> {
    return await api.put(`${base(roomId)}/current`, payload, opts);
  },
};
