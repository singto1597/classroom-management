import api from './api';
import type { UserRoom } from '@/types/classroom';

export const ClassroomService = {
  async getUserRooms(userId: string): Promise<UserRoom[]> {
    return await api.get(`/api/classroom/${userId}/rooms`);
  },
  async createRoom(payload: { room_name: string }): Promise<any> {
    return await api.post('/api/classroom/create', payload);
  },
  async joinRoom(payload: { room_code: string; student_no: number; first_name: string; last_name: string }): Promise<any> {
    // 🚨 ยิง API เข้าห้อง (Backend จะจัดการรวมร่างให้ที่จุดนี้)
    return await api.post('/api/classroom/join', payload);
  }
};