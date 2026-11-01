#!/usr/bin/env node
/**
 * 🖐️ check-tap-targets.mjs — ตรวจว่าทุกอย่างที่ "กดได้" กว้าง×สูง ≥ 44px ที่ viewport 360dp
 *
 * ทำไมต้องมีด่านนี้
 *   `DESIGN.md §6` กำหนดพื้นที่กดขั้นต่ำ 44×44 px (เท่า Apple HIG / WCAG 2.5.5)
 *   แต่คลาสที่เขียนด้วยมืออย่าง `px-3 py-2` ให้แค่ ~38px และไม่มีอะไรจับได้
 *   ⇒ ปุ่มในแถวตาราง (โดยเฉพาะบนมือถือ) กดพลาดบ่อย (บทเรียนจาก PRSC: "วัดเฉพาะที่ผู้ใช้เห็น")
 *
 * หลักการวัด
 *   1. เปิดทุก route ที่ระบุ ที่ viewport **360×800** (มือถือเล็กสุดที่รองรับ)
 *   2. เก็บเฉพาะ element ที่ **ผู้ใช้เห็นจริง** — ไม่มีขนาด 0, ไม่ถูกซ่อนด้วย display/visibility,
 *      ไม่ได้ถูก `aria-hidden` คลุม, ไม่ได้ `pointer-events: none`, ไม่ใช่ `disabled`
 *      (บทเรียนเดิม: สคริปต์ที่วัดทุก node จะฟ้องหน้า login ทั้ง 20 บรรทัด)
 *   3. วัด `getBoundingClientRect()` — ขนาดจริงหลัง layout ไม่ใช่ขนาดที่เขียนในคลาส
 *
 * ข้อยกเว้นโดยเจตนา (ไม่รายงาน)
 *   - `input[type=checkbox|radio]` — พื้นที่กดจริงคือ `<label>` ที่ห่อมัน (วัดที่ label แทน)
 *   - `<a>` ที่อยู่Inlineในย่อหน้า — WCAG ยกเว้นลิงก์ในเนื้อหา (2.5.8 inline exception)
 *   - element ที่ใส่ `data-tap-exempt` พร้อมเหตุผล (ใช้ให้น้อยที่สุด และต้องมีคอมเมนต์ในโค้ด)
 *
 * วิธีใช้
 *   npm run preview            # หรือ dev server
 *   node scripts/check-tap-targets.mjs                     # ใช้ http://localhost:4173
 *   node scripts/check-tap-targets.mjs --base http://localhost:5173
 *   node scripts/check-tap-targets.mjs --json              # ผลลัพธ์แบบ JSON (CI)
 *
 * ต้องมี `e2e/.auth/session.json` (seed ด้วย `backend/scripts/e2e_seed.py` ผ่าน
 * `docker compose -f docker-compose.e2e.yml`) มิฉะนั้น router guard จะเด้งไป /login
 * และทุกหน้าไม่มีอะไรให้วัด — สคริปต์จะหยุดพร้อมบอกวิธีสร้าง session
 *
 * รหัสออก: 0 = ผ่าน · 1 = พบ target เล็กกว่า 44px · 2 = ตั้งค่าไม่ครบ (ไม่มี session/เปิดเว็บไม่ได้)
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const HERE = dirname(fileURLToPath(import.meta.url))
const SESSION_PATH = join(HERE, '..', 'e2e', '.auth', 'session.json')

const args = process.argv.slice(2)
const argValue = (name, fallback) => {
  const hit = args.find((a) => a.startsWith(`--${name}=`))
  return hit ? hit.slice(name.length + 3) : fallback
}
const BASE = argValue('base', process.env.E2E_BASE_URL || 'http://localhost:4173').replace(/\/$/, '')
const AS_JSON = args.includes('--json')

/**
 * route ที่ตรวจ — เฉพาะ route แบบคงที่ (path ที่มี `:param` ต้องมีข้อมูลจริงก่อน
 * จึงจะวัดได้อย่างมีความหมาย ⇒ ใส่เพิ่มผ่าน `--routes=/students/1,...` เมื่อต้องการ)
 */
const DEFAULT_ROUTES = [
  '/dashboard',
  '/students',
  '/students/add',
  '/students/export',
  '/roadmap',
  '/schedules',
  '/tasks',
  '/tasks/add',
  '/finance',
  '/finance/settings',
  '/finance/transactions',
  '/finance/transactions/add',
  '/finance/collections',
  '/finance/debtors',
  '/finance/credits',
  '/finance/statements',
  '/finance/budgets',
  '/finance/receipts',
  '/discord-connect',
  '/messages',
  '/activities',
  '/activities/create',
  '/activities/compare',
]

const ROUTES = argValue('routes', '')
  ? argValue('routes', '').split(',').map((r) => r.trim()).filter(Boolean)
  : DEFAULT_ROUTES

const MIN = 44

if (!existsSync(SESSION_PATH)) {
  console.error(
    [
      '✋ ไม่พบ `e2e/.auth/session.json` — วัดไม่ได้เพราะทุกหน้าจะถูก guard เด้งไป /login',
      '',
      'สร้าง session ก่อน:',
      '  docker compose -f docker-compose.e2e.yml up -d',
      '  docker compose -f docker-compose.e2e.yml exec backend python scripts/e2e_seed.py',
      '',
      `(ไฟล์ต้องอยู่ที่ ${SESSION_PATH})`,
    ].join('\n'),
  )
  process.exit(2)
}

const session = JSON.parse(readFileSync(SESSION_PATH, 'utf-8'))

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 360, height: 800 },
  deviceScaleFactor: 2,
  hasTouch: true,
  locale: 'th-TH',
  timezoneId: 'Asia/Bangkok',
})

// คีย์ต้องตรงกับ `e2e/session.ts` (แหล่งจริง) และ `constants/storageKeys.ts` ฝั่งแอป
await context.addInitScript((s) => {
  const room = {
    room_id: s.room.id,
    room_name: s.room.name,
    room_code: s.room.code,
    role: 'president',
    status: 'active',
    is_admin: true,
    permissions: [],
  }
  const entries = {
    access_token: s.token,
    user_id_str: String(s.user.id),
    user_prefix: s.user.prefix,
    user_first_name: s.user.first_name,
    user_last_name: s.user.last_name,
    user_phone_number: s.user.phone_number,
    user_rooms: JSON.stringify([room]),
    last_room_id: String(s.room.id),
  }
  for (const [key, value] of Object.entries(entries)) localStorage.setItem(key, value)
  sessionStorage.setItem('active_room_id', String(s.room.id))
}, session)

const results = []
let unreachable = false

for (const route of ROUTES) {
  const page = await context.newPage()
  try {
    const response = await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 15000 })
    if (response && response.status() >= 400) {
      results.push({ route, error: `HTTP ${response.status()}`, violations: [] })
      continue
    }

    // รอให้ router/API ลงตัว — skeleton ต้องหายก่อน ไม่งั้นเราจะวัดปุ่มที่ยังไม่ถูก render
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(600)

    const violations = await page.evaluate(
      ({ min }) => {
        const SELECTOR = [
          'a[href]',
          'button',
          '[role="button"]',
          '[role="link"]',
          '[role="switch"]',
          '[role="tab"]',
          '[role="menuitem"]',
          'input:not([type="hidden"])',
          'select',
          'textarea',
          'summary',
          '[tabindex]:not([tabindex="-1"])',
        ].join(',')

        // ลิงก์ที่ฝังอยู่ในย่อหน้า = ลิงก์ในเนื้อหา (WCAG 2.5.8 ยกเว้น) — ไม่รวมลิงก์ในตาราง/การ์ด
        const isInlineLink = (el) => el.tagName === 'A' && el.parentElement?.tagName === 'P'

        const hiddenByStyle = (el) => {
          const style = getComputedStyle(el)
          if (style.display === 'none' || style.visibility === 'hidden') return true
          if (style.pointerEvents === 'none') return true
          return false
        }

        const out = []
        for (const el of document.querySelectorAll(SELECTOR)) {
          // ปิดใช้งาน/ซ่อนจาก screen reader → ไม่ใช่เป้าหมายที่ผู้ใช้กดได้ตอนนี้
          if (el.disabled) continue
          if (el.getAttribute('aria-disabled') === 'true') continue
          if (el.closest('[aria-hidden="true"]')) continue
          if (el.hasAttribute('data-tap-exempt')) continue
          // checkbox/radio: พื้นที่กดจริงคือ label ที่ห่อ
          if (el.matches('input[type="checkbox"],input[type="radio"]')) continue
          if (isInlineLink(el)) continue
          if (hiddenByStyle(el)) continue

          const rect = el.getBoundingClientRect()
          if (rect.width === 0 || rect.height === 0) continue
          // นอกจอ (เลื่อนลงไปแล้ว) ยังนับ — ผู้ใช้เอื้อมถึงได้
          if (rect.width + 0.5 >= min && rect.height + 0.5 >= min) continue

          const label =
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 48) ||
            el.tagName.toLowerCase()
          out.push({
            tag: el.tagName.toLowerCase(),
            label,
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
            className: (el.getAttribute('class') || '').slice(0, 120),
          })
        }
        return out
      },
      { min: MIN },
    )

    results.push({ route, error: null, violations })
  } catch (error) {
    unreachable = true
    results.push({ route, error: String(error && error.message ? error.message : error), violations: [] })
  } finally {
    await page.close()
  }
}

await browser.close()

const failed = results.filter((r) => r.violations.length > 0)
const errored = results.filter((r) => r.error)
const total = failed.reduce((sum, r) => sum + r.violations.length, 0)

if (AS_JSON) {
  console.log(JSON.stringify({ base: BASE, min: MIN, routes: ROUTES.length, total, results }, null, 2))
} else {
  console.log(`🖐️ ตรวจพื้นที่กดขั้นต่ำ ${MIN}×${MIN}px · viewport 360×800 · ${BASE}`)
  console.log(`   ตรวจ ${ROUTES.length} route\n`)
  for (const r of results) {
    if (r.error) {
      console.log(`⚠️  ${r.route} — เปิดไม่สำเร็จ: ${r.error}`)
      continue
    }
    if (r.violations.length === 0) {
      console.log(`✅ ${r.route}`)
      continue
    }
    console.log(`❌ ${r.route} — ${r.violations.length} จุดเล็กกว่า ${MIN}px`)
    for (const v of r.violations) {
      console.log(`     • <${v.tag}> "${v.label}" = ${v.width}×${v.height}px · ${v.className}`)
    }
  }
  console.log('')
  if (total === 0 && errored.length === 0) {
    console.log('🎉 ผ่านทั้งหมด — ทุกเป้าหมายกดได้ ≥44px')
  } else {
    if (total > 0) console.log(`รวม ${total} จุดใน ${failed.length} หน้า — แก้ด้วย min-h-11 / min-w-11 / .tap-44`)
    if (errored.length > 0) console.log(`เปิดไม่ได้ ${errored.length} หน้า — ตรวจว่า preview server รันอยู่ที่ ${BASE}`)
  }
}

process.exit(total > 0 || errored.length > 0 || unreachable ? 1 : 0)
