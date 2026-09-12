import api from './api';
import type {
  UserRoom,
  RoomCreatePayload,
  RoomJoinPayload,
  RoomCreateResponse,
  RoomJoinResponse,
  RoomData
} from '@/types/classroom';

export const ClassroomService = {
  async getUserRooms(userId: string): Promise<UserRoom[]> {
    return await api.get(`/api/classroom/${userId}/rooms`);
  },
  async createRoom(payload: RoomCreatePayload): Promise<RoomCreateResponse> {
    return await api.post('/api/classroom/create', payload) as unknown as RoomCreateResponse;
  },
  async joinRoom(payload: RoomJoinPayload): Promise<RoomJoinResponse> {
    // 🚨 ยิง API เข้าห้อง (Backend จะจัดการรวมร่างให้ที่จุดนี้)
    return await api.post('/api/classroom/join', payload) as unknown as RoomJoinResponse;
  },

  // 🏠 ดึงข้อมูลห้อง (server_id บอกว่าห้องผูก Discord ไว้แล้วหรือยัง)
  async getRoomData(roomId: number): Promise<RoomData> {
    return await api.get(`/api/classroom/${roomId}?target_type=room`) as unknown as RoomData;
  }
};
