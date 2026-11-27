import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/**
 * 🔒 กันบั๊ก "นายนาย ชินภัทร" กลับมา (2026-11-27)
 *
 * `displayName()` **เติม prefix ให้แล้ว** — หน้าจอที่ต่อ `prefix + ' ' + displayName(x)`
 * จะได้คำนำหน้าสองครั้ง · เทสต์นี้อ่านไฟล์จริงเพื่อกันการเผลอเขียนซ้ำในเทมเพลต
 * (ตัว logic ของ `displayName()` ถูกต้องอยู่แล้ว — ดู `name.spec.ts`)
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const TEMPLATE_FILES = [
  '../../views/students/StudentList.vue',
  '../../views/students/StudentProfile.vue',
  '../../components/activities/ParticipantRosterList.vue',
];

describe('template ไม่เติม prefix ซ้ำหน้า displayName()', () => {
  it.each(TEMPLATE_FILES)('%s', (relative) => {
    const source = read(relative);
    const duplicatePrefixLines = source
      .split('\n')
      .filter((line) => line.includes('displayName(') && /\bprefix\b/.test(line));
    expect(duplicatePrefixLines).toEqual([]);
  });
});

describe('หน้าบัญชีใช้ displayName() แทนการต่อสตริงเอง', () => {
  it('AccountView.vue', () => {
    const source = read('../../views/account/AccountView.vue');
    expect(source).toContain("from '@/utils/name'");
    // ห้ามมีรูปแบบ `${p.prefix ...}${p.first_name` ที่ทำให้คำนำหน้าติดชื่อไม่มีช่องว่าง
    expect(source).not.toMatch(/p\.prefix[^`]*p\.first_name/);
  });

  it('stores/auth.ts — currentUserName ผ่าน displayName()', () => {
    const source = read('../../stores/auth.ts');
    expect(source).toContain("from '@/utils/name'");
    expect(source).toMatch(/currentUserName[\s\S]{0,400}displayName\(/);
  });
});
