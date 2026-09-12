export interface UserRoom {
  room_id: number;
  server_id?: string;
  server_id_str?: string;
  room_code?: string;
  room_name: string;
  role: string;
  status: string;

  is_admin?: boolean;
  permissions?: string[];
}

// --- Request Payloads (ตรงกับ backend/models/room_schemas.py) ---

/** POST /api/classroom/create */
export interface RoomCreatePayload {
  room_name: string;
}

/** POST /api/classroom/join */
export interface RoomJoinPayload {
  room_code: string;
  student_no: number;
  first_name: string;
  last_name: string;
  first_name_en?: string;
  last_name_en?: string;
}

// --- Responses ---

/** คำตอบจาก POST /api/classroom/create (RoomResponse) */
export interface RoomCreateResponse {
  room_id: number;
  room_name: string;
  room_code: string;
  message: string;
}

/**
 * คำตอบจาก POST /api/classroom/join
 * `room_name` มาจาก dict ที่ RoomManagementService.join_room คืนค่า
 * (ฝั่งหน้าเว็บใช้ต่อใน authStore.setRoom ทันทีหลังเข้าห้องสำเร็จ)
 */
export interface RoomJoinResponse {
  room_id: number;
  student_id: number;
  room_name: string;
  message: string;
}

/** คำตอบจาก GET /api/classroom/{room_id}?target_type=room (RoomDataResponse) */
export interface RoomData {
  id: number;
  server_id: number | null;
  room_name: string;
  announcement_channel_id: number | null;
  birthday_channel_id: number | null;
  minor_notify_channel_id: number | null;
  notify_time: string | null;
}