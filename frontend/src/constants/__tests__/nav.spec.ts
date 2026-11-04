import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MORE_NAV_GROUPS, NAV_ITEMS, NAV_TABS, PRIMARY_NAV_ITEMS } from '@/constants/nav';

/**
 * ไอคอนที่พิมพ์ผิด (เช่น `bi-person-bookmark` ที่ไม่มีจริงใน bootstrap-icons)
 * จะ render เป็น `<i>` เปล่า ๆ ⇒ แถวเมนูนั้นขาดไอคอนและข้อความเหลื่อมจากแถวอื่น
 * โดยไม่มี error ใด ๆ — เทสต์นี้เปิดไฟล์ CSS ของไลบรารีมาตรวจทุกคลาสแทน
 */
const iconCssPath = resolve(process.cwd(), 'node_modules/bootstrap-icons/font/bootstrap-icons.css');
const iconCss = readFileSync(iconCssPath, 'utf8');
const iconExists = (icon: string) => iconCss.includes(`.${icon}::before`);

const allIcons = [
  ...NAV_ITEMS.map((item) => item.icon),
  ...NAV_TABS.map((tab) => tab.icon),
  ...PRIMARY_NAV_ITEMS.map((item) => item.icon),
  ...MORE_NAV_GROUPS.flatMap((group) => group.items.map((item) => item.icon)),
];

describe('constants/nav', () => {
  it('ไอคอนทุกตัวมีอยู่จริงใน bootstrap-icons', () => {
    const missing = [...new Set(allIcons)].filter((icon) => !iconExists(icon));
    expect(missing).toEqual([]);
  });

  it('ทุกเมนูมี path ไม่ซ้ำกันภายในกลุ่มที่แสดงผลจริง', () => {
    for (const group of MORE_NAV_GROUPS) {
      const paths = group.items.map((item) => item.path);
      expect(new Set(paths).size).toBe(paths.length);
    }
  });
});
