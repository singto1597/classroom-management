import api from './api';
import type { HomeSummary } from '@/types/home';

/**
 * 🏠 หน้าหลัก = **คำขอเดียว** (P3.1)
 *
 * เดิม Dashboard ต้องยิง getAllTasks() เต็มลิสต์มาแค่นับเลข (ก้อนใหญ่ที่ไม่ได้ใช้)
 * ตอนนี้ backend นับให้ใน snapshot เดียว (`repeatable_read`) ⇒ ตัวเลขทุกใบมาจาก
 * ช่วงเวลาเดียวกัน ไม่ใช่คนละคำขอที่ตัวเลขไม่ตรงกันได้
 */
export const HomeService = {
  async getSummary(roomId: number): Promise<HomeSummary> {
    return await api.get(`/api/classroom/${roomId}/home/summary`, {
      params: { target_type: 'room' },
    });
  },
};
