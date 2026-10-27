import { describe, expect, it } from 'vitest';
import {
  STUDENT_STATUS_LABELS,
  TASK_STATUS_LABELS,
  UNKNOWN_STATUS_LABEL,
  studentStatusLabel,
  taskStatusLabel,
} from '@/constants/statusLabels';

/**
 * ล็อกคำไทยที่ผู้ใช้เห็นไว้กับ `docs/glossary.md`
 * ถ้าใครแก้คำในไฟล์ constants ต้องแก้ glossary และเทสต์นี้พร้อมกัน
 * (เจตนาให้เทสต์แดงเมื่อคำไม่ตรงกัน ไม่ใช่เพื่อทดสอบ `Record` ว่ามีคีย์)
 */
describe('constants/statusLabels', () => {
  it('ป้ายสถานะนักเรียนตรงกับ glossary', () => {
    expect(STUDENT_STATUS_LABELS).toEqual({
      active: 'กำลังเรียน',
      pending: 'รออนุมัติ',
      inactive: 'พ้นสภาพ',
    });
  });

  it('ป้ายสถานะงานตรงกับ glossary', () => {
    expect(TASK_STATUS_LABELS).toEqual({
      pending: 'ยังไม่เสร็จ',
      done: 'เสร็จแล้ว',
    });
  });

  it('คืนคำไทยของทุกสถานะที่รู้จัก', () => {
    expect(studentStatusLabel('active')).toBe('กำลังเรียน');
    expect(studentStatusLabel('pending')).toBe('รออนุมัติ');
    expect(studentStatusLabel('inactive')).toBe('พ้นสภาพ');
    expect(taskStatusLabel('pending')).toBe('ยังไม่เสร็จ');
    expect(taskStatusLabel('done')).toBe('เสร็จแล้ว');
  });

  it('สถานะที่ไม่รู้จักได้ข้อความกลาง ไม่ใช่ค่าว่างหรือภาษาอังกฤษ', () => {
    expect(studentStatusLabel('graduated')).toBe(UNKNOWN_STATUS_LABEL);
    expect(taskStatusLabel('archived')).toBe(UNKNOWN_STATUS_LABEL);
  });
});
