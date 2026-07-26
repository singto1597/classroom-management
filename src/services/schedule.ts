import api from './api'
import type { DefaultScheduleCreate, ScheduleOverrideCreate } from '@/types/schedule'

export const ScheduleService = {
  async saveDefault(roomId: number, data: DefaultScheduleCreate): Promise<void> {
    await api.post(`/api/classroom/${roomId}/schedule/default?target_type=room`, data)
  },

  async saveOverride(roomId: number, data: ScheduleOverrideCreate): Promise<void> {
    await api.post(`/api/classroom/${roomId}/schedule/override?target_type=room`, data)
  }
}