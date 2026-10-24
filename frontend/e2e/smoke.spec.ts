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

test('เปิด path ที่ไม่มีอยู่จริง ⇒ หน้า 404 ไม่ใช่จอขาว', async ({ page }) => {
  // 🕳️ ก่อนมี catch-all route ระบบจะ render อะไรไม่ออกเลย (หน้าจอว่าง)
  // เทสต์นี้พิสูจน์ทั้ง route, ข้อความ และชื่อแท็บเบราว์เซอร์ที่มาจาก meta.title
  await page.goto('/this-page-does-not-exist')

  await expect(page.getByRole('heading', { level: 1, name: 'ไม่พบหน้าที่ต้องการ' })).toBeVisible()
  await expect(page).toHaveTitle(/ไม่พบหน้านี้/)
  await expect(page).toHaveURL(/\/this-page-does-not-exist$/)

  await page.getByRole('link', { name: 'กลับหน้าหลัก' }).click()
  await expect(page).toHaveURL(/\/dashboard$/)
})

test('เปิดลิงก์ลึกตอนยังไม่เลือกห้อง ⇒ เลือกห้องแล้วกลับไปหน้านั้น', async ({ page }) => {
  test.skip(!session, MISSING_SESSION)

  // จำลอง "ล็อกอินแล้วแต่ยังไม่ได้เลือกห้อง" — ล้างคีย์ห้องที่ seedSession ใส่ไว้
  // (init script นี้ทำงานหลัง seedSession เพราะถูกเพิ่มทีหลัง)
  await page.addInitScript(() => {
    sessionStorage.removeItem('active_room_id')
    localStorage.removeItem('last_room_id')
  })

  await page.goto('/students')

  // guard พาไป Lobby พร้อมพกปลายทางเดิมไว้ (ไม่ใช่ทิ้งไปเฉย ๆ)
  // ⚠️ vue-router ไม่ encode `/` ใน query ⇒ URL จริงคือ `?next=/students` ไม่ใช่ `%2Fstudents`
  await expect(page).toHaveURL(/\/lobby\?next=\/students$/)

  await page.getByRole('button', { name: new RegExp(session.room.name) }).first().click()

  // เลือกห้องเสร็จกลับไปหน้าปลายทางที่ตั้งใจ ไม่ใช่ dashboard
  await expect(page).toHaveURL(/\/students$/)
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
