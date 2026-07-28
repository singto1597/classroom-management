export interface DefaultSchedule {
  id?: number;
  room_id: number; // ✨ แก้จาก string เป็น number
  day_of_week: string;
  attire: string;
  subjects: string;
  updated_at?: string;
}

export interface ScheduleOverride {
  id?: number;
  room_id: number; // ✨ แก้จาก string เป็น number
  target_date: string;
  new_attire: string;
  note: string;
  created_at?: string;
}

export interface DefaultScheduleCreate {
  day_of_week: string;
  attire: string;
  subjects: string;
  user_name: string;
}

export interface ScheduleOverrideCreate {
  target_date: string;
  new_attire: string;
  note: string;
  user_name: string;
}