// 🏠 สรุปหน้าหลัก — แมปจาก `backend/models/home_schemas.py` (P3)
//
// 🔑 ทุกตัวเลขในก้อนนี้มี "ปลายทาง" ที่กรองตรงกับมัน:
//    tasks.total → /tasks?filter=all · pending_total → ?filter=pending
//    due_today → ?filter=today · overdue → ?filter=overdue
//    finance.unpaid_bills → /finance/my-debts · announcements.unread_count → /announcements?unread=1
// ⇒ ห้ามเอาไปแสดงการ์ดที่ไม่มีลิงก์รองรับ (จะกลายเป็นตัวเลขที่กดแล้วไม่เจอของ)

export interface HomeTaskItem {
  id: number;
  task_name: string;
  /** YYYY-MM-DD */
  due_date: string;
  status: string;
}

export interface HomeTaskSummary {
  total: number;
  pending_total: number;
  due_today: number;
  overdue: number;
  items: HomeTaskItem[];
}

export interface HomeNote {
  bring_items: string | null;
  announcement: string | null;
}

export interface HomeActivityItem {
  id: number;
  title: string;
  /** YYYY-MM-DD */
  activity_date: string;
  status: string;
  base_hours: number;
}

export interface HomeFinanceSummary {
  /** false = ผู้ใช้ไม่มีแถวนักเรียนในห้องนี้ (เช่น แอดมิน) ⇒ ไม่มี "ยอดของฉัน" */
  has_profile: boolean;
  outstanding: number;
  unpaid_bills: number;
}

export interface HomeAnnouncementSummary {
  unread_count: number;
}

export interface HomeSchedule {
  day_of_week: string;
  attire: string | null;
  subjects: string | null;
  override_note: string | null;
}

export interface HomeSummary {
  /** YYYY-MM-DD ตามเวลาไทย — มาจาก backend ไม่ใช่นาฬิกาอุปกรณ์ */
  today: string;
  tasks: HomeTaskSummary;
  note: HomeNote | null;
  activities: HomeActivityItem[];
  finance: HomeFinanceSummary;
  announcements: HomeAnnouncementSummary;
  schedule: HomeSchedule;
}
