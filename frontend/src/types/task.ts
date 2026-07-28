export interface Task {
  id: number;
  room_id: number; // ✨ แก้จาก string เป็น number
  task_name: string;
  task_detail: string;
  due_date: string;
  status: 'pending' | 'done';
  created_at: string;
  updated_at: string;
  deleted_at?: string | null;
}

export interface TaskCreate {
  task_name: string;
  task_detail: string;
  due_date: string;
  user_name: string;
}

export interface TaskUpdate {
  task_name: string;
  task_detail: string;
  due_date: string;
  user_name: string;
}

export interface DailyNote {
  id: number;
  room_id: number; // ✨ แก้จาก string เป็น number
  target_date: string;
  bring_items: string;
  announcement: string;
  created_at: string;
}

export interface DailyNoteCreate {
  target_date: string;
  bring_items: string;
  announcement: string;
  user_name: string;
}