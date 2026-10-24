#!/usr/bin/env node
/**
 * 🚦 ด่าน `npm run lint:palette` — ห้ามใช้ชื่อสีดิบ (`emerald-*`, `red-*`, …)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมีด่านนี้
 * ═══════════════════════════════════════════════════════════════════════════
 * `text-red-600` บอกว่า "สีแดง" ไม่ได้บอกว่า "อันตราย" — และเมื่อมีคนอยากปรับโทน
 * สถานะทั้งระบบ (เช่น ให้อ่านง่ายขึ้นบนมือถือ) การตามแก้ `red-` 159 จุด
 * กับ `emerald-` 100 จุดด้วยมือคือที่มาของความไม่สม่ำเสมอ
 *
 * ระบบนี้ใช้ **ชื่อความหมาย** แทนชื่อสี:
 *   ok-*      สำเร็จ / ชำระแล้ว / อนุมัติ          (เดิม emerald-*)
 *   warn-*    รอ / ค้าง / ใกล้ครบกำหนด              (เดิม amber-*)
 *   danger-*  ลบ / ผิดพลาด / ยกเลิก / ค้างชำระ     (เดิม red-* และ rose-*)
 *   info-*    ป้ายข้อมูล / กำลังจะมา                (เดิม sky-* และ blue-*)
 *   brand-*   สิ่งที่กดได้ / สิ่งที่ต้องดู
 *   stone-*   กลาง (ขอบ ข้อความรอง พื้นหลัง)
 *
 * ⚠️ ขอบเขตของด่าน: ตรวจชื่อคลาสที่มีเฉดต่อท้าย (เช่น `red-600`) ใน `src/`
 *    — ไม่ตรวจ `tailwind.config.js` (ที่นั่นคือที่นิยามสี) และไม่ตรวจคอมเมนต์
 */

import fs from 'node:fs'
import path from 'node:path'

const ROOT = 'src'

/** ชื่อสีดิบที่ห้ามใช้ — รวมสีที่ยังไม่มีในระบบตอนนี้ด้วย เพื่อกันการไหลเข้ามาใหม่ */
const FAMILIES = [
  'emerald', 'green', 'lime', 'teal', 'cyan',
  'amber', 'yellow', 'orange',
  'red', 'rose', 'pink',
  'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia',
]
const SHADES = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950']
const PATTERN = new RegExp(`\\b(${FAMILIES.join('|')})-(${SHADES.join('|')})\\b`, 'g')

const EXT = new Set(['.vue', '.ts', '.js', '.mjs', '.css'])

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

const MAP = {
  emerald: 'ok', green: 'ok', lime: 'ok', teal: 'ok', cyan: 'info',
  amber: 'warn', yellow: 'warn', orange: 'warn',
  red: 'danger', rose: 'danger', pink: 'danger',
  sky: 'info', blue: 'info', indigo: 'info', violet: 'info', purple: 'info', fuchsia: 'info',
}

const findings = []
for (const file of walk(ROOT)) {
  const rel = file.split(path.sep).join('/')
  const lines = stripComments(fs.readFileSync(file, 'utf8')).split('\n')
  lines.forEach((line, i) => {
    for (const m of line.matchAll(PATTERN)) {
      findings.push(`${rel}:${i + 1}  ${m[0]}  →  ${MAP[m[1]]}-${m[2]}`)
    }
  })
}

if (findings.length > 0) {
  console.error('\n🔴 พบชื่อสีดิบ ' + findings.length + ' จุด — ใช้ชื่อความหมายแทน\n')
  for (const f of findings) console.error('   ' + f)
  console.error(`
   เพดานของแต่ละกลุ่ม: ok = สำเร็จ · warn = รอ/ค้าง · danger = ลบ/ผิดพลาด · info = ข้อมูล
   (รายละเอียดใน frontend/DESIGN.md § สี)
`)
  process.exit(1)
}

console.log(`✅ lint:palette — ไม่มีชื่อสีดิบใน src/ (ตรวจ ${walk(ROOT).length} ไฟล์)`)
