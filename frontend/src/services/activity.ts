import api from './api'
import type {
  Activity,
  ActivityCreate,
  ActivityUpdate,
  ParticipantUpdate,
  BatchParticipantUpdate,
  MyActivityRole,
  CheckinSheet,
  CheckinSheetDetail,
  CheckinRecordInput,
  AvailableStudent,
} from '@/types/activity'

/**
 * Activity & Role Management API — ทุกฟีเจอร์ผ่าน backend API เท่านั้น (ห้ามแตะ DB ตรง)
 * baseURL ที่ axios instance ใช้มี prefix /api/classroom อยู่แล้ว
 */
export const ActivityService = {
  // --- Activities ---
  async getActivities(roomId: number, status?: string): Promise<Activity[]> {
    const params = new URLSearchParams({ target_type: 'room' })
    if (status) params.set('status', status)
    return (await api.get(`/api/classroom/${roomId}/activities?${params}`)) as Activity[]
  },

  async getActivity(roomId: number, activityId: number): Promise<Activity> {
    return (await api.get(`/api/classroom/${roomId}/activities/${activityId}?target_type=room`)) as Activity
  },

  async createActivity(roomId: number, data: ActivityCreate): Promise<void> {
    await api.post(`/api/classroom/${roomId}/activities?target_type=room`, data)
  },

  async updateActivity(roomId: number, activityId: number, data: ActivityUpdate): Promise<Activity> {
    return (await api.patch(`/api/classroom/${roomId}/activities/${activityId}?target_type=room`, data)) as Activity
  },

  async deleteActivity(roomId: number, activityId: number, userName: string): Promise<void> {
    await api.delete(`/api/classroom/${roomId}/activities/${activityId}?target_type=room`, {
      data: { user_name: userName },
    })
  },

  // --- Participants ---
  /** 🎯 Batch เพิ่มผู้เข้าร่วมหลายคนพร้อมกัน (atomic) — ใช้จากปุ่ม "เพิ่มนักเรียน" */
  async batchAddParticipants(
    roomId: number,
    activityId: number,
    items: { student_no: number }[],
    userName: string,
  ): Promise<void> {
    await api.post(`/api/classroom/${roomId}/activities/${activityId}/participants/batch?target_type=room`, {
      items,
      user_name: userName,
    })
  },

  /** 👥 รายชื่อนักเรียน active ในห้องที่ยังไม่ได้เข้าร่วมกิจกรรมนี้ (ปุ่ม "เพิ่มนักเรียน") */
  async getAvailableStudents(roomId: number, activityId: number): Promise<AvailableStudent[]> {
    return (await api.get(
      `/api/classroom/${roomId}/activities/${activityId}/participants/available?target_type=room`,
    )) as AvailableStudent[]
  },

  async updateParticipant(
    roomId: number,
    activityId: number,
    participantId: number,
    data: ParticipantUpdate,
  ): Promise<void> {
    await api.patch(
      `/api/classroom/${roomId}/activities/${activityId}/participants/${participantId}?target_type=room`,
      data,
    )
  },

  async updateParticipantStatus(
    roomId: number,
    activityId: number,
    participantId: number,
    status: string,
    userName: string,
  ): Promise<void> {
    await api.patch(
      `/api/classroom/${roomId}/activities/${activityId}/participants/${participantId}/status?target_type=room`,
      { status, user_name: userName },
    )
  },

  /** 🎯 Batch Apply — อัปเดต metadata หลายคนพร้อมกัน (atomic ฝั่ง backend) */
  async batchUpdateParticipants(
    roomId: number,
    activityId: number,
    data: BatchParticipantUpdate,
  ): Promise<void> {
    await api.patch(
      `/api/classroom/${roomId}/activities/${activityId}/participants/batch?target_type=room`,
      data,
    )
  },

  // --- ✅ ระบบเช็คชื่อแยกแผ่น (Multiple Attendance Sheets) ---
  async getCheckinSheets(roomId: number, activityId: number): Promise<CheckinSheet[]> {
    return (await api.get(
      `/api/classroom/${roomId}/activities/${activityId}/checkins?target_type=room`,
    )) as CheckinSheet[]
  },

  async createCheckinSheet(
    roomId: number,
    activityId: number,
    data: { title: string; event_date?: string | null; user_name: string },
  ): Promise<void> {
    await api.post(
      `/api/classroom/${roomId}/activities/${activityId}/checkins?target_type=room`,
      data,
    )
  },

  async updateCheckinSheet(
    roomId: number,
    activityId: number,
    sheetId: number,
    data: { title?: string; event_date?: string | null; user_name: string },
  ): Promise<void> {
    await api.patch(
      `/api/classroom/${roomId}/activities/${activityId}/checkins/${sheetId}?target_type=room`,
      data,
    )
  },

  async deleteCheckinSheet(
    roomId: number,
    activityId: number,
    sheetId: number,
    userName: string,
  ): Promise<void> {
    await api.delete(
      `/api/classroom/${roomId}/activities/${activityId}/checkins/${sheetId}?target_type=room`,
      { data: { user_name: userName } },
    )
  },

  async getCheckinSheet(roomId: number, activityId: number, sheetId: number): Promise<CheckinSheetDetail> {
    return (await api.get(
      `/api/classroom/${roomId}/activities/${activityId}/checkins/${sheetId}?target_type=room`,
    )) as CheckinSheetDetail
  },

  async upsertCheckinRecord(
    roomId: number,
    activityId: number,
    sheetId: number,
    participantId: number,
    isPresent: boolean,
    userName: string,
  ): Promise<void> {
    await api.put(
      `/api/classroom/${roomId}/activities/${activityId}/checkins/${sheetId}/records/${participantId}?target_type=room`,
      { is_present: isPresent, user_name: userName },
    )
  },

  async batchUpdateCheckinRecords(
    roomId: number,
    activityId: number,
    sheetId: number,
    records: CheckinRecordInput[],
    userName: string,
  ): Promise<void> {
    await api.post(
      `/api/classroom/${roomId}/activities/${activityId}/checkins/${sheetId}/records?target_type=room`,
      { records, user_name: userName },
    )
  },

  async removeParticipant(
    roomId: number,
    activityId: number,
    participantId: number,
    userName: string,
  ): Promise<void> {
    await api.delete(
      `/api/classroom/${roomId}/activities/${activityId}/participants/${participantId}?target_type=room`,
      { data: { user_name: userName } },
    )
  },

  // --- My roles (สำหรับหน้าโปรไฟล์ / บอท) ---
  async getMyActivityRoles(roomId: number): Promise<MyActivityRole[]> {
    return (await api.get(`/api/classroom/${roomId}/activities/me/roles?target_type=room`)) as MyActivityRole[]
  },

  // --- Export ---
  async exportActivityExcel(
    roomId: number,
    activityId: number,
    metadataKeys: string[],
    userName: string,
  ): Promise<Blob> {
    const response = await api.post(
      `/api/classroom/${roomId}/activities/export?target_type=room`,
      { activity_id: activityId, metadata_keys: metadataKeys, user_name: userName },
      { responseType: 'blob' },
    )
    return response as unknown as Blob
  },
}

export default ActivityService
