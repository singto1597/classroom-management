#!/usr/bin/env node
/**
 * 🖼️ สร้างไอคอน PWA จาก SVG ด้วย Chromium ของ Playwright
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องมีสคริปต์นี้
 * ═══════════════════════════════════════════════════════════════════════════
 * `manifest.webmanifest` ต้องการ PNG (192/512) — เบราว์เซอร์ Android ไม่รับ SVG
 * เป็นไอคอนติดตั้ง และ `apple-touch-icon` ก็รับเฉพาะ PNG
 * เครื่องนี้ไม่มี ImageMagick / rsvg-convert และไม่อยากเพิ่ม dependency
 * image-processing ลงในโปรเจกต์ ⇒ ใช้ Chromium ที่ **มีอยู่แล้ว** สำหรับ e2e
 * เรนเดอร์ SVG แล้ว screenshot ออกมาเป็น PNG
 *
 * ⚠️ ไฟล์ PNG ถูก commit ไว้ — สคริปต์นี้ไว้ทำใหม่เมื่อ **เปลี่ยนโลโก้/สีแบรนด์**
 *    เท่านั้น ไม่ได้รันใน CI (ไม่ต้องมี browser ในขั้น build)
 *
 * ใช้: `node scripts/generate-icons.mjs`
 *
 * 📌 สองแบบที่ต่างกันจริง:
 *    • `any`      — มุมโค้ง + ขอบโปร่งใส (iOS/เดสก์ท็อปใช้ตามที่ให้)
 *    • `maskable` — เต็มจัตุรัส ไม่มีมุมโค้ง รูปอยู่ในโซนปลอดภัย 80%
 *      (Android จะตัดเป็นวงกลม/เหลี่ยมตามธีมเครื่องเอง — ถ้ามุมโค้งมาแล้วจะเห็นรอย)
 */

import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium } from '@playwright/test'

const BRAND = '#1D4ED8' // = brand-700 ใน tailwind.config.js
const PAPER = '#F7F7F8'

// เส้นทางของไอคอน bootstrap-icons `box-fill` (viewBox 16×16) — ตัวเดียวกับ favicon
const GLYPH =
  'M8.186 1.113a.5.5 0 0 0-.372 0L1.846 3.5l2.404.961L10.404 2zm3.564 1.426L5.596 5 8 5.961 14.154 3.5zm3.25 1.7-6.5 2.6v7.922l6.5-2.6V4.24zM7.5 14.762V6.838L1 4.239v7.923zM7.443.184a1.5 1.5 0 0 1 1.114 0l7.129 2.852A.5.5 0 0 1 16 3.5v8.662a1 1 0 0 1-.629.928l-7.185 2.874a.5.5 0 0 1-.372 0L.63 13.09a1 1 0 0 1-.63-.928V3.5a.5.5 0 0 1 .314-.464z'

/**
 * @param {number} size ขนาดจริงเป็นพิกเซล
 * @param {'any'|'maskable'|'apple'} purpose
 */
function buildSvg(size, purpose) {
  // สัดส่วน: maskable ต้องเผื่อที่ตัด ⇒ รูปเล็กลง / พื้นเต็ม
  const padRatio = purpose === 'maskable' ? 0.24 : 0.2
  const radius = purpose === 'any' ? size * 0.22 : 0
  const pad = size * padRatio
  const inner = size - pad * 2

  // apple-touch-icon ห้ามมีช่องโปร่งใส (iOS เติมดำ) ⇒ พื้นเต็มจัตุรัส
  const radiusFinal = purpose === 'apple' ? 0 : radius

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    <rect width="${size}" height="${size}" rx="${radiusFinal}" fill="${BRAND}"/>
    <g transform="translate(${pad} ${pad}) scale(${inner / 16})">
      <path fill="#FFFFFF" fill-rule="evenodd" d="${GLYPH}"/>
    </g>
  </svg>`
}

const TARGETS = [
  { file: 'icon-192.png', size: 192, purpose: 'any' },
  { file: 'icon-512.png', size: 512, purpose: 'any' },
  { file: 'icon-maskable-512.png', size: 512, purpose: 'maskable' },
  { file: 'apple-touch-icon.png', size: 180, purpose: 'apple' },
]

const outDir = path.resolve('public/icons')
await fs.mkdir(outDir, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ colorScheme: 'light' })

for (const { file, size, purpose } of TARGETS) {
  await page.setViewportSize({ width: size, height: size })
  await page.setContent(
    `<!doctype html><html><head><style>
       html,body{margin:0;padding:0;background:${PAPER}}
       svg{display:block}
     </style></head><body>${buildSvg(size, purpose)}</body></html>`,
    { waitUntil: 'load' },
  )
  const target = path.join(outDir, file)
  await page.screenshot({
    path: target,
    clip: { x: 0, y: 0, width: size, height: size },
    omitBackground: purpose === 'any', // any = ขอบโปร่งได้ / maskable+apple = พื้นทึบ
  })
  const { size: bytes } = await fs.stat(target)
  console.log(`✅ ${file}  ${size}×${size}  ${bytes} bytes`)
}

await browser.close()
console.log(`\nไอคอนอยู่ใน ${outDir}`)
