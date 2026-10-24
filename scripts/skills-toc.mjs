#!/usr/bin/env node
/**
 * 📚 สร้างสารบัญของ `docs/skills.md` จากหัวข้อ `###` จริงในไฟล์
 *
 *   node scripts/skills-toc.mjs           # เขียนทับช่วงระหว่าง marker
 *   node scripts/skills-toc.mjs --check   # ตรวจว่าสารบัญตรงกับหัวข้อ (CI ใช้ตัวนี้)
 *
 * ทำไมต้องมีสคริปต์: ไฟล์นี้มีหัวข้อเกิน 200 อันและเพิ่มทุกงานที่แก้บั๊ก
 * สารบัญที่เขียนมือจะเน่าใน 1–2 สัปดาห์ แล้วกลายเป็นเอกสารที่ "ชี้ผิดที่"
 * ซึ่งแย่กว่าไม่มีสารบัญ — เหมือนกับด่าน lint ที่ไม่ได้พิสูจน์ว่าจับได้
 *
 * ⚠️ anchor ต้องเลียนแบบ GitHub (lowercase, ตัดอักขระที่ไม่ใช่ตัวอักษร/ตัวเลข/ขีด,
 *    เว้นวรรค → `-`, ซ้ำให้เติม `-1`, `-2`) ไม่งั้นลิงก์ใน GitHub จะกดไม่ไป
 *    แม้สารบัญจะ "ดูถูก" ใน terminal
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SKILLS = join(ROOT, 'docs', 'skills.md');
const START = '<!-- TOC:START — สร้างด้วย `node scripts/skills-toc.mjs` ห้ามแก้ด้วยมือ -->';
const END = '<!-- TOC:END -->';
const CHECK = process.argv.includes('--check');

/**
 * GitHub-style slug
 * - ตัด HTML tag, backtick และ `*` (markdown ที่ไม่ติด anchor)
 * - ตัด variation selector / zero-width joiner (emoji ที่มี ️ ต่อท้าย)
 * - เก็บเฉพาะตัวอักษร (\p{L}) ตัวเลข (\p{N}) เครื่องหมายผสม (\p{M} — จำเป็นกับภาษาไทย)
 * - ช่องว่างทุกชุด → `-`
 */
function slugify(text) {
  return text
    .replace(/<[^>]+>/g, '')
    .replace(/[`*]/g, '')
    .toLowerCase()
    .replace(/[\u200b-\u200d\ufe0e\ufe0f]/g, '')
    .replace(/[^\p{L}\p{N}\p{M}\s-]/gu, '')
    .trim()
    .replace(/\s+/g, '-');
}

/** หาหัวข้อ `###` ที่อยู่นอก code fence — หัวข้อในบล็อกโค้ดไม่ใช่สารบัญ */
function headings(lines) {
  const found = [];
  let inFence = false;
  lines.forEach((line, index) => {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      return;
    }
    if (inFence) return;
    if (/^###\s+\S/.test(line)) {
      found.push({ line: index, text: line.replace(/^###\s+/, '').trim() });
    }
  });
  return found;
}

function buildToc(items) {
  const seen = new Map();
  const rows = items.map(({ text }) => {
    const base = slugify(text);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    const anchor = count === 0 ? base : `${base}-${count}`;
    // ต้อง escape **ทั้ง `[` และ `]`** ในข้อความลิงก์ — ถ้า escape แค่ `]` วงเล็บเปิด
    // จะยังนับเป็นวงเล็บของลิงก์ ⇒ CommonMark มองว่าไม่สมดุลและไม่สร้างลิงก์ให้เลย
    // (หัวข้อจริงมี `[2026-05-16]` อยู่ ⇒ ถ้าไม่กันไว้จะพังตั้งแต่รายการแรก)
    const label = text.replace(/[[\]]/g, (char) => `\\${char}`);
    return `- [${label}](#${anchor})`;
  });
  return [START, '', `**สารบัญ ${rows.length} หัวข้อ** — เลื่อนด้วยลิงก์ หรือ \`Ctrl+F\` ชื่อหัวข้อ`, '', ...rows, '', END];
}

const source = readFileSync(SKILLS, 'utf8');
const lines = source.split('\n');

const startIndex = lines.findIndex((line) => line.trim() === START);
const endIndex = lines.findIndex((line) => line.trim() === END);

if (CHECK && (startIndex === -1 || endIndex === -1 || endIndex < startIndex)) {
  console.error('❌ ไม่พบคู่ marker TOC:START / TOC:END ใน docs/skills.md');
  console.error('   ⇒ เพิ่มสองบรรทัดนี้ตามลำดับ (START ก่อน END) แล้วรัน `node scripts/skills-toc.mjs`');
  process.exit(1);
}

const items = headings(lines);
const toc = buildToc(items);

if (CHECK) {
  const current = lines.slice(startIndex, endIndex + 1);
  const same = current.length === toc.length && current.every((line, i) => line === toc[i]);
  if (!same) {
    console.error('❌ สารบัญใน docs/skills.md ไม่ตรงกับหัวข้อจริง');
    const currentSet = new Set(current);
    const nextSet = new Set(toc);
    for (const line of toc) {
      if (!currentSet.has(line)) console.error(`   + ${line}`);
    }
    for (const line of current) {
      if (!nextSet.has(line)) console.error(`   - ${line}`);
    }
    console.error('   ⇒ รัน `node scripts/skills-toc.mjs` แล้ว commit ผลลัพธ์');
    process.exit(1);
  }
  console.log(`✅ สารบัญตรงกับหัวข้อจริง (${items.length} หัวข้อ)`);
  process.exit(0);
}

if (startIndex !== -1 && endIndex > startIndex) {
  lines.splice(startIndex, endIndex - startIndex + 1, ...toc);
  writeFileSync(SKILLS, lines.join('\n'), 'utf8');
  console.log(`✏️  เขียนสารบัญ ${items.length} หัวข้อลง docs/skills.md แล้ว`);
} else {
  // ยังไม่มี marker → แทรกหลัง H1 บรรทัดแรก
  const h1 = lines.findIndex((line) => line.startsWith('# '));
  const at = h1 === -1 ? 0 : h1 + 1;
  lines.splice(at, 0, '', ...toc);
  writeFileSync(SKILLS, lines.join('\n'), 'utf8');
  console.log(`✨ เพิ่ม marker + สารบัญ ${items.length} หัวข้อต่อจาก H1 ให้แล้ว`);
}
