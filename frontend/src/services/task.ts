import api from './api'
import type { Task, TaskCreate, TaskUpdate, DailyNote, DailyNoteCreate } from '@/types/task'

export const TaskService = {
  // --- Task API ---
  async getAllTasks(roomId: number): Promise<Task[]> {
    return await api.get(`/api/classroom/${roomId}/tasks?target_type=room`) as any[]
  },

  async getTaskById(roomId: number, taskId: number): Promise<Task> {
    return await api.get(`/api/classroom/${roomId}/tasks/${taskId}?target_type=room`)
  },

  async createTask(roomId: number, data: TaskCreate): Promise<void> {
    await api.post(`/api/classroom/${roomId}/tasks?target_type=room`, data)
  },

  async updateTask(roomId: number, taskId: number, data: TaskUpdate): Promise<void> {
    await api.put(`/api/classroom/${roomId}/tasks/${taskId}?target_type=room`, data)
  },

  async markDone(roomId: number, taskId: number, userName: string): Promise<void> {
    await api.patch(`/api/classroom/${roomId}/tasks/${taskId}/done?target_type=room`, { user_name: userName })
  },

  async markPending(roomId: number, taskId: number, userName: string): Promise<void> {
    await api.patch(`/api/classroom/${roomId}/tasks/${taskId}/restore?target_type=room`, { user_name: userName })
  },

  async deleteTask(roomId: number, taskId: number, userName: string): Promise<void> {
    await api.delete(`/api/classroom/${roomId}/tasks/${taskId}?target_type=room`, { data: { user_name: userName } })
  },

  // --- Daily Note API ---
  async getDailyNotes(roomId: number): Promise<DailyNote[]> {
    return await api.get(`/api/classroom/${roomId}/notes?target_type=room`) as any[]
  },

  async createDailyNote(roomId: number, data: DailyNoteCreate): Promise<void> {
    await api.post(`/api/classroom/${roomId}/notes?target_type=room`, data)
  }
}