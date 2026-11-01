import { describe, expect, it } from 'vitest';
import {
  ACTIVITY_CATEGORIES,
  UNCATEGORIZED_LABEL,
  activityCategoryLabel,
} from '@/constants/activityCategories';

/**
 * ล็อกรายการหมวดกิจกรรมไว้ให้ตรงกับ `backend/services/activity/constants.py`
 * (และ `docs/glossary.md`) — ถ้าเพิ่ม/เปลี่ยนหมวดที่ฝั่งใดฝั่งหนึ่ง เทสต์หรือการบันทึก
 * ฝั่งตรงข้ามจะพังทันที ไม่ปล่อยไปถึงมือผู้ใช้
 */
describe('constants/activityCategories', () => {
  it('ชุดค่าและป้ายตรงกับ backend', () => {
    expect(ACTIVITY_CATEGORIES).toEqual([
      { value: 'camp', label: 'ค่าย' },
      { value: 'competition', label: 'การแข่งขัน' },
      { value: 'volunteer', label: 'จิตอาสา' },
      { value: 'training', label: 'อบรม/สัมมนา' },
      { value: 'ceremony', label: 'พิธีการ' },
      { value: 'other', label: 'อื่น ๆ' },
    ]);
  });

  it('"อื่น ๆ" อยู่ท้ายสุดของลิสต์', () => {
    const last: { value: string } | undefined =
      ACTIVITY_CATEGORIES[ACTIVITY_CATEGORIES.length - 1];
    expect(last?.value).toBe('other');
  });

  it('แปลง slug เป็นป้ายไทยได้', () => {
    expect(activityCategoryLabel('camp')).toBe('ค่าย');
    expect(activityCategoryLabel('volunteer')).toBe('จิตอาสา');
  });

  it('ยังไม่จัดหมวด / ค่าที่ไม่รู้จัก คืน null (หน้าจอเลือกแสดงเอง)', () => {
    expect(activityCategoryLabel(null)).toBeNull();
    expect(activityCategoryLabel(undefined)).toBeNull();
    expect(activityCategoryLabel('')).toBeNull();
    expect(activityCategoryLabel('festival')).toBeNull();
    expect(UNCATEGORIZED_LABEL).toBe('ไม่ระบุหมวด');
  });
});
