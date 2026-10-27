/**
 * ป้ายสถานะกลาง — คำไทยชุดเดียวที่ผู้ใช้เห็นสำหรับ `students.status` และ `tasks.status`
 *
 * ทำไมต้องรวมไว้ที่เดียว: ตรวจตอน P0.5 พบว่า StudentList / StudentProfile / Lobby
 * เขียนป้ายนักเรียนคนละชุด ("ใช้งาน" / "กำลังศึกษา" / "นักเรียนปัจจุบัน") และ TaskList
 * เรียกงานที่ปิดแล้วว่า "ส่งแล้ว" ทั้งที่ `docs/glossary.md` กำหนดคำไว้แล้ว
 * ⇒ แก้ทีละหน้าแล้วจะเพี้ยนอีกเพราะไม่มีแหล่งเดียว
 *
 * ⚠️ ต้องตรงกับ `backend/services/student/constants.py` → `STATUS_LABELS`
 *    และ `docs/glossary.md` → "ป้ายสถานะนักเรียน" / "ป้ายสถานะงาน"
 *    เพิ่มค่าใหม่ = แก้ทั้งสามที่พร้อมกันใน PR เดียว
 *
 * หมายเหตุ: "ส่งวันนี้ / ส่งพรุ่งนี้ / เลยกำหนดมา N วัน" ใน TaskList เป็นคำอธิบาย
 * กำหนดส่ง ไม่ใช่ป้ายสถานะ จึงไม่ต้องอยู่ในไฟล์นี้
 */

export type StudentStatus = 'active' | 'pending' | 'inactive';
export type TaskStatus = 'pending' | 'done';

export const STUDENT_STATUS_LABELS: Record<StudentStatus, string> = {
  active: 'กำลังเรียน',
  pending: 'รออนุมัติ',
  inactive: 'พ้นสภาพ',
};

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  pending: 'ยังไม่เสร็จ',
  done: 'เสร็จแล้ว',
};

/** สถานะที่ frontend ยังไม่รู้จัก (backend เพิ่มค่าใหม่ก่อน) — ห้ามปล่อยป้ายว่างหรือหลุดเป็นอังกฤษ */
export const UNKNOWN_STATUS_LABEL = 'ไม่ทราบสถานะ';

export function studentStatusLabel(status: string): string {
  return STUDENT_STATUS_LABELS[status as StudentStatus] ?? UNKNOWN_STATUS_LABEL;
}

export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABELS[status as TaskStatus] ?? UNKNOWN_STATUS_LABEL;
}
