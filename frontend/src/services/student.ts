import api from '@/services/api'
import type {
  Student,
  Invite,
  StudentQuickAdd,
  StudentAddPayload,
  PendingStudentRequest
} from '@/types/student'
import type { ApiSuccessResponse } from '@/types/api'

export const StudentService = {
  /**
   * ดึงรายชื่อนักเรียนทั้งหมดในห้อง
   */
  async getStudents(roomId: number): Promise<Student[]> {
    return await api.get(`/api/classroom/${roomId}/students?target_type=room`)
  },

  /**
   * ดึงข้อมูลนักเรียนรายคน (ตามเลขที่)
   */
  async getStudentByNo(roomId: number, studentNo: string | number): Promise<Student> {
    return await api.get(`/api/classroom/${roomId}/students/profile/${studentNo}?target_type=room`) as Student
  },

  /**
   * ดึงโปรไฟล์นักเรียนของ "ตัวเอง" ในห้องที่ระบุ (ใช้ขึ้นหน้าโปรไฟล์ส่วนตัว)
   */
  async getMyProfile(roomId: number): Promise<Student> {
    return (await api.get(
      `/api/classroom/${roomId}/students/me?target_type=room`,
    )) as Student
  },

  /**
   * อัปเดตข้อมูลนักเรียน
   */
  async updateStudent(
    roomId: number,
    studentNo: string | number,
    payload: Partial<Student>
  ): Promise<void> {
    await api.patch(`/api/classroom/${roomId}/students/${studentNo}?target_type=room`, payload)
  },

  /**
   * ลบนักเรียน
   */
  async deleteStudent(roomId: number, studentNo: number, userName: string): Promise<void> {
    await api.delete(`/api/classroom/${roomId}/students/${studentNo}?target_type=room`, {
      data: { user_name: userName }
    })
  },

  /**
   * อัปเดตสถานะนักเรียน (เช่น active, inactive)
   */
  async updateStatus(
    roomId: number,
    studentNo: number,
    status: string,
    userName: string
  ): Promise<void> {
    await api.patch(`/api/classroom/${roomId}/students/${studentNo}/status?target_type=room`, {
      status,
      user_name: userName
    })
  },

  /**
   * เพิ่มนักเรียน (คนเดียว)
   */
  async addStudent(roomId: number, payload: StudentAddPayload): Promise<void> {
    await api.post(`/api/classroom/${roomId}/students?target_type=room`, payload)
  },

  /**
   * เพิ่มนักเรียน (Bulk)
   */
  async bulkAddStudents(
    roomId: number,
    students: StudentQuickAdd[],
    userName: string
  ): Promise<void> {
    await api.post(`/api/classroom/${roomId}/students/bulk?target_type=room`, {
      students,
      user_name: userName
    })
  },

  async getPendingRequests(roomId: number): Promise<PendingStudentRequest[]> {
    return await api.get(`/api/classroom/${roomId}/requests`);
  },

  /** 🛡️ คำเชิญเข้าร่วมห้องของฉัน (แอดมินแอดชื่อให้) — ต้องกดรับเองก่อนถึงเป็นสมาชิก */
  async getInvites(): Promise<Invite[]> {
    return await api.get('/api/classroom/invites');
  },
  async acceptInvite(inviteId: number): Promise<void> {
    await api.post(`/api/classroom/invites/${inviteId}/accept`);
  },
  async approveStudent(roomId: number, studentNo: number): Promise<ApiSuccessResponse> {
    return await api.put(`/api/classroom/${roomId}/requests/${studentNo}/approve`) as unknown as ApiSuccessResponse;
  },
  async rejectStudent(roomId: number, studentNo: number): Promise<ApiSuccessResponse> {
    return await api.delete(`/api/classroom/${roomId}/requests/${studentNo}/reject`) as unknown as ApiSuccessResponse;
  },

  /**
   * ขอไฟล์ Export นักเรียนเป็น Excel (รับกลับมาเป็น Blob)
   */
  async exportStudentsExcel(roomId: number, fields: string[], userName: string): Promise<Blob> {
    const response = await api.post(`/api/classroom/${roomId}/export?target_type=room`, {
      fields: fields,
      user_name: userName
    }, {
      // 🚨 สำคัญมาก! บังคับให้ Axios รับข้อมูลมาเป็นไฟล์ไบนารี
      responseType: 'blob' 
    });
    
    // 👇 เติม as unknown as Blob เพื่อตบตา TypeScript ให้ยอม Build ผ่าน
    return response as unknown as Blob; 
  }
}

export default StudentService