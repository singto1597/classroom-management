#!/usr/bin/env node
/**
 * ตรวจ manifest ของประวัติเวอร์ชัน — รันก่อน backfill เสมอ
 *
 *   node scripts/version-manifest.mjs
 *
 * ตรวจ: จำนวนแถว, SemVer, วันที่เรียงขึ้น, cut มีจริง/reachable จาก HEAD,
 * ความต่อเนื่องตั้งแต่ monorepo root repo (2026-06-01), และ PR ที่ merge แล้ว (1–98 ยกเว้น 3/4/91) ถูกนับครบพอดีครั้งเดียว
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const manifestPath = join(root, 'scripts/version-manifest.tsv');
const changelogPath = join(root, 'CHANGELOG.md');
const UNMERGED = new Set([3, 4, 91]);
const PR_MAX = 98;

const git = (...args) =>
  execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();

const rows = readFileSync(manifestPath, 'utf8')
  .split('\n')
  .filter((l) => l && !l.startsWith('#'))
  .map((line, i) => {
    const [version, date, cut, bump, theme, refs] = line.split('\t');
    if (!version || !date || !cut || !bump || !theme || !refs) {
      throw new Error(`แถว ${i + 1} คอลัมน์ไม่ครบ 6: ${line}`);
    }
    return { version, date, cut, bump, theme, refs };
  });

const errors = [];
const ok = [];
const semver = /^\d+\.\d+\.\d+$/;

let prevDate = '';
for (const [i, r] of rows.entries()) {
  if (!semver.test(r.version)) errors.push(`${r.version}: SemVer ไม่ถูกต้อง`);
  if (!['major', 'minor', 'patch'].includes(r.bump)) errors.push(`${r.version}: bump ต้องเป็น major/minor/patch`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(r.date)) errors.push(`${r.version}: date ต้องเป็น YYYY-MM-DD`);
  if (prevDate && r.date < prevDate) errors.push(`${r.version}: วันที่ย้อนหลัง (${r.date} < ${prevDate})`);
  prevDate = r.date;

  if (r.cut !== 'RELEASE') {
    try {
      git('cat-file', '-e', `${r.cut}^{commit}`);
    } catch {
      errors.push(`${r.version}: ไม่พบ commit ${r.cut}`);
      continue;
    }
    try {
      git('merge-base', '--is-ancestor', r.cut, 'HEAD');
    } catch {
      errors.push(`${r.version}: ${r.cut} ไม่ได้เป็น ancestor ของ HEAD`);
    }
  }
}
ok.push(`manifest ${rows.length} แถว, วันที่เรียงขึ้น, cut มีจริงและ reachable`);

// ตั้งแต่ V1 release (2026-06-30) ประวัติต้องเป็นเส้นเดียว — ก่อนหน้านี้มี 4 root
const MONOREPO_START = '2026-06-30';
const linear = rows.filter((r) => r.date >= MONOREPO_START && r.cut !== 'RELEASE');
for (let i = 1; i < linear.length; i++) {
  const a = linear[i - 1];
  const b = linear[i];
  try {
    git('merge-base', '--is-ancestor', a.cut, b.cut);
  } catch {
    errors.push(`ความต่อเนื่อง: ${a.version} (${a.cut}) ไม่ใช่ ancestor ของ ${b.version} (${b.cut})`);
  }
}
ok.push(`ความต่อเนื่องตั้งแต่ ${MONOREPO_START}: ${linear.length - 1} คู่`);

// PR coverage — นับเฉพาะ refs ที่ขึ้นต้นด้วย "PR #" (component PR ใช้ "bot PR", "backend PR" ฯลฯ)
const assigned = [];
for (const r of rows) {
  const m = r.refs.match(/^PR #(\d+)(?:-#(\d+))?/);
  if (!m) continue;
  const a = Number(m[1]);
  const b = m[2] ? Number(m[2]) : a;
  for (let n = a; n <= b; n++) assigned.push({ n, version: r.version });
}
const counts = new Map();
for (const { n, version } of assigned) {
  if (!counts.has(n)) counts.set(n, []);
  counts.get(n).push(version);
}
const expected = [];
for (let n = 1; n <= PR_MAX; n++) if (!UNMERGED.has(n)) expected.push(n);
const missing = expected.filter((n) => !counts.has(n));
const dup = [...counts.entries()].filter(([, v]) => v.length > 1);
const stray = [...counts.keys()].filter((n) => n > PR_MAX || UNMERGED.has(n));
if (missing.length) errors.push(`PR ที่ยังไม่ถูกนับ: ${missing.join(', ')}`);
if (dup.length) errors.push(`PR ที่ถูกนับซ้ำ: ${dup.map(([n, v]) => `#${n} (${v.join('/')})`).join(', ')}`);
if (stray.length) errors.push(`PR ที่ไม่ควรมี: ${stray.join(', ')}`);
if (!missing.length && !dup.length && !stray.length) {
  ok.push(`PR coverage: ${expected.length} merged PR ถูกนับครบพอดีครั้งเดียว`);
}

// CHANGELOG ต้องมี section ของทุก version
if (existsSync(changelogPath)) {
  const changelog = readFileSync(changelogPath, 'utf8');
  const absent = rows.filter((r) => !changelog.includes(`## [${r.version}]`));
  if (absent.length) errors.push(`CHANGELOG ขาด section: ${absent.map((r) => r.version).join(', ')}`);
  else ok.push(`CHANGELOG มี section ครบ ${rows.length} versions`);
} else {
  console.warn('⚠️  ยังไม่มี CHANGELOG.md — ข้ามการตรวจ section');
}

for (const line of ok) console.log(`✅ ${line}`);
if (errors.length) {
  console.error(`\n❌ พบ ${errors.length} ปัญหา:`);
  for (const e of errors) console.error(`   - ${e}`);
  process.exit(1);
}
console.log('\n🎉 manifest ผ่านทุกด่าน');
