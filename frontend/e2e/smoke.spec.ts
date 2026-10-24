import { test, expect } from '@playwright/test'
import { loadSession, seedSession } from './session'

/**
 * 🚬 E2E smoke — ต้องพิสูจน์ว่า frontend + backend + DB คุยกันได้จริง
 *
 * แทนที่ `vue.spec.ts` scaffold เดิม (`h1 = "You did it!"`) ที่ตกทุกครั้งและ
 * ไม่ได้บอกอะไรเกี่ยวกับระบบเลย
 *
 * ถ้าไม่มี session (ยังไม่รัน `docker compose -f docker-compose.e2e.yml` +
 * `e2e_seed`) เทสต์จะ **skip พร้อมเหตุผล** ไม่ใช่ผ่านหลอกหรือตก
 */
const session = loadSession()
const MISSING_SESSION =
  'ไม่พบ e2e/.auth/session.json — รัน docker compose -f docker-compose.e2e.yml up + e2e_seed ก่อน'

test.beforeEach(async ({ page }) => {
  if (!session) return
  await seedSession(page, session)
})

test('เปิด / แล้วไป dashboard ได้โดยไม่ถูกเด้งกลับ login', async ({ page }) => {
  test.skip(!session, MISSING_SESSION)

  await page.goto('/')

  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  // token ถูกใช้ยิง API จริง — ถ้า backend ไม่ตอบ/ห้องไม่ถูก หน้าแรกจะขึ้น StateBlock
  await expect(page.getByText('ไม่สามารถโหลดข้อมูลได้')).toHaveCount(0)
})

test('สร้างงานใหม่แล้วเห็นในรายการทันที', async ({ page }) => {
  test.skip(!session, MISSING_SESSION)

  const title = `งานทดสอบ E2E ${Date.now()}`

  await page.goto('/tasks/add')
  await page.locator('#taskName').fill(title)
  await page.getByRole('button', { name: 'บันทึกงานใหม่' }).click()

  await page.waitForURL(/\/tasks$/)
  await expect(page.getByText(title)).toBeVisible()
})
