#!/usr/bin/env node
/**
 * 🔤 ด่าน `npm run lint:thai` — ห้าม `uppercase` / `tracking-*` บนข้อความไทย
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมีด่านนี้
 * ═══════════════════════════════════════════════════════════════════════════
 * ภาษาไทยไม่มีตัวพิมพ์ใหญ่ ⇒ `uppercase` ไม่ทำอะไรกับตัวอักษร แต่ `letter-spacing`
 * (Tailwind: `tracking-*`) ดันสระ/วรรณยุกต์ให้ห่างจากพยัญชนะที่มันเกาะอยู่
 * ทำให้คำไทยอ่านยากขึ้น — และมันติดมาจาก template ที่ออกแบบให้ label อังกฤษเป็นตัวใหญ่
 *
 * ด่านนี้กวาดเฉพาะ "บรรทัดที่มีข้อความไทย" (หรือป้ายไทยใน 2 บรรทัดถัดไป
 * กรณี class อยู่บรรทัดบนแล้วข้อความอยู่บรรทัดล่าง) ⇒ label อังกฤษยังใช้
 * `uppercase tracking-wider` ได้ตามเดิม
 *
 * ⚠️ ขอบเขต: ตรวจ `src/` เฉพาะ `.vue`/`.ts` และตัดคอมเมนต์ก่อนตรวจ
 *    ไม่จับกรณีที่ข้อความไทยอยู่ไกลกว่า 2 บรรทัดจาก class — เขียน class ให้อยู่ใกล้ข้อความ
 */

import fs from 'node:fs'
import path from 'node:path'

const ROOT = 'src'
const THAI = /[฀-๿]/
const TOKEN = /(?<![A-Za-z0-9_-])(?:uppercase|tracking-(?:tighter|tight|normal|wide|wider|widest)|tracking-\[[^\]]+\])(?![A-Za-z0-9_-])/g
const EXT = new Set(['.vue', '.ts'])

function stripComments(src) {
  const blank = (m) => m.replace(/[^\n]/g, ' ')
  return src
    .replace(/<!--[\s\S]*?-->/g, blank)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|[^:])\/\/[^\n]*/gm, (m, p1) => p1 + ' '.repeat(m.length - p1.length))
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

const files = walk(ROOT)
const findings = []

for (const file of files) {
  const rel = file.split(path.sep).join('/')
  const lines = stripComments(fs.readFileSync(file, 'utf8')).split('\n')
  lines.forEach((line, i) => {
    const tokens = line.match(TOKEN)
    if (!tokens) return
    // class อยู่บรรทัดบน ข้อความไทยอยู่บรรทัดถัดไปได้ (สูงสุด 2 บรรทัด)
    const window = lines.slice(i, i + 3).join('\n')
    if (!THAI.test(window)) return
    findings.push(`${rel}:${i + 1}  ${[...new Set(tokens)].join(' ')}`)
  })
}

if (findings.length > 0) {
  console.error('\n🔴 พบ uppercase/letter-spacing บนข้อความไทย ' + findings.length + ' จุด\n')
  for (const f of findings) console.error('   ' + f)
  console.error(`
   ภาษาไทยไม่มีตัวพิมพ์ใหญ่ และ letter-spacing ทำให้สระ/วรรณยุกต์ห่างจากพยัญชนะ
   ⇒ ลบ \`uppercase\`/\`tracking-*\` ออกจาก element ที่มีข้อความไทย
   (label อังกฤษยังใช้ได้ — ด่านนี้ตรวจเฉพาะบรรทัดที่มีอักษรไทย)
`)
  process.exit(1)
}

console.log(`✅ lint:thai — ไม่มี uppercase/letter-spacing บนข้อความไทย (ตรวจ ${files.length} ไฟล์)`)
