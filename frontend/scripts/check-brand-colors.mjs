#!/usr/bin/env node
/**
 * 🎨 ด่าน `npm run lint:colors` — ห้ามมี hex สีกระจายใน `src/`
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมีด่านนี้
 * ═══════════════════════════════════════════════════════════════════════════
 * ก่อน พ.ย. 2026 ระบบมี hex อยู่ ~190 จุดใน 40 ไฟล์ โดย `'#1d4ed8'` ซ้ำ 96 ครั้ง
 * คนละตัวสะกดกันบ้าง (`#1D4ED8`, `#1d4ed8`) และไม่มีใครรู้ว่าเปลี่ยนสีแบรนด์
 * ต้องแก้ตรงไหนบ้าง — TYPE CHECKER จับไม่ได้ และ unit test ก็จับไม่ได้
 *
 * ตอนนี้ค่าสีทั้งหมดอยู่ในสองที่:
 *   • `tailwind.config.js`        — คลาส (`bg-danger-50`)
 *   • `src/constants/theme.ts`    — ค่าที่ JS ต้องใช้ (Swal / Chart.js / inline style)
 *   • `src/assets/main.css`       — CSS variable + `@apply`
 *   • `src/views/auth/Login.vue`  — โลโก้ Google (สีแบรนด์ของเขา เปลี่ยนไม่ได้)
 *
 * ⚠️ ขอบเขตของด่าน (แคบโดยเจตนา — ดู `lint:palette` สำหรับชื่อคลาสสี):
 *   ตรวจเฉพาะโฟลเดอร์ `src/` และเฉพาะรูปแบบ `#rgb` / `#rrggbb` / `#rrggbbaa`
 *   ที่ **ไม่อยู่ในคอมเมนต์** ⇒ ไฟล์ SVG/รูปใน `public/` และ `index.html` ไม่ถูกตรวจ
 */

import fs from 'node:fs'
import path from 'node:path'

const ROOT = 'src'

/** ไฟล์ที่อนุญาตให้มี hex — เหตุผลกำกับไว้ทุกไฟล์ */
const ALLOWED = new Map([
  ['src/assets/main.css', 'CSS variable + @apply ของทั้งระบบ'],
  ['src/constants/theme.ts', 'ค่าสีที่ JS ใช้ (Swal/Chart.js) — สำเนาของ tailwind.config.js'],
  ['src/views/auth/Login.vue', 'สีโลโก้ Google (SVG) — แบรนด์ผู้ให้บริการกำหนดตายตัว'],
])

const EXT = new Set(['.vue', '.ts', '.js', '.mjs', '.css'])
const HEX = /#[0-9a-fA-F]{3,8}\b/g

/**
 * แทนที่เนื้อหาคอมเมนต์ด้วยช่องว่าง **โดยรักษาจำนวนบรรทัด**
 * ⇒ เลขบรรทัดที่รายงานยังตรงกับไฟล์จริง
 */
function stripComments(src) {
  const blank = (m) => m.replace(/[^\n]/g, ' ')
  return src
    .replace(/<!--[\s\S]*?-->/g, blank) // HTML comment (.vue template)
    .replace(/\/\*[\s\S]*?\*\//g, blank) // block comment
    .replace(/(^|[^:])\/\/[^\n]*/gm, (m, p1) => p1 + ' '.repeat(m.length - p1.length)) // line comment (ไม่กิน `://`)
}

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'dist') continue
      walk(full, out)
    } else if (EXT.has(path.extname(entry.name))) {
      out.push(full)
    }
  }
  return out
}

const findings = []
for (const file of walk(ROOT)) {
  const rel = file.split(path.sep).join('/')
  if (ALLOWED.has(rel)) continue

  const lines = stripComments(fs.readFileSync(file, 'utf8')).split('\n')
  lines.forEach((line, i) => {
    for (const m of line.matchAll(HEX)) {
      findings.push(`${rel}:${i + 1}  ${m[0]}`)
    }
  })
}

if (findings.length > 0) {
  console.error('\n🔴 พบ hex สีที่ไม่อยู่ในที่อนุญาต ' + findings.length + ' จุด\n')
  for (const f of findings) console.error('   ' + f)
  console.error(`
   แก้โดย:
     • ในเทมเพลต/คลาส → ใช้คลาส Tailwind (brand-*, ok-*, warn-*, danger-*, info-*, stone-*)
     • ใน Swal / Chart.js / inline style → import { UI_COLOR } from '@/constants/theme'
     • ถ้าเป็นสีของบุคคลที่สาม (โลโก้ผู้ให้บริการ) → เพิ่มใน PROVIDER_COLOR ของ theme.ts
       หรือเพิ่มไฟล์ใน ALLOWED พร้อมคอมเมนต์เหตุผล (เฉพาะกรณีที่เปลี่ยนสีไม่ได้จริง ๆ)
`)
  process.exit(1)
}

console.log(`✅ lint:colors — ไม่มี hex นอกที่อนุญาต (ตรวจ ${walk(ROOT).length} ไฟล์)`)
