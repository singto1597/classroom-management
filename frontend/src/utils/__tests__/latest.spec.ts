import { describe, expect, it } from 'vitest'

import { createLatestGuard } from '@/utils/latest'

/**
 * 🏁 `createLatestGuard` เป็นตัวช่วยที่ **ถูกใช้จริงใน 4 หน้าจอการเงิน**
 *    (ReceiptList, BudgetList, FinancialStatements, FinanceDashboard)
 *    ⇒ เทสต์ชุดนี้ต้องพิสูจน์ "รูปร่างการใช้งาน" ที่ถูกต้อง ไม่ใช่แค่ตัวนับ
 *    เพราะบั๊กที่มันกันอยู่ไม่ใช่ "ตัวนับเพี้ยน" แต่คือ "ลืมเช็คจุดใดจุดหนึ่งในสามจุด"
 */
describe('createLatestGuard', () => {
  it('คำขอแรกเป็นคำขอล่าสุดเสมอ', () => {
    const guard = createLatestGuard()
    expect(guard.isCurrent(guard.begin())).toBe(true)
  })

  it('token ของคำขอเก่าถูกทำให้เป็นโมฆะทันทีที่เริ่มคำขอใหม่', () => {
    const guard = createLatestGuard()
    const first = guard.begin()
    const second = guard.begin()
    expect(guard.isCurrent(first)).toBe(false)
    expect(guard.isCurrent(second)).toBe(true)
  })

  it('เริ่มคำขอใหม่กี่ครั้งก็ได้ — มีเพียงอันสุดท้ายเท่านั้นที่ยังใช้ได้', () => {
    const guard = createLatestGuard()
    const tokens = [guard.begin(), guard.begin(), guard.begin(), guard.begin(), guard.begin()]
    const stillValid = tokens.filter((t) => guard.isCurrent(t))
    expect(stillValid).toHaveLength(1)
    expect(stillValid[0]).toBe(tokens[tokens.length - 1])
  })

  it('token ถูกทำให้เป็นโมฆะก่อนที่คำตอบจะมาถึง (คำขอซ้อนแบบกลับลำดับ)', () => {
    const guard = createLatestGuard()
    // จำลองสถานการณ์จริง: ส่ง A → ส่ง B → A ตอบกลับมา (ช้ากว่า) → B ตอบกลับมา
    const tokenA = guard.begin()
    const tokenB = guard.begin()

    // A ตอบกลับมาก่อนทั้งที่ถูกส่งก่อน ⇒ ต้องถูกทิ้ง ไม่เขียนทับ
    expect(guard.isCurrent(tokenA)).toBe(false)
    // B ตอบกลับมา ⇒ เขียนได้
    expect(guard.isCurrent(tokenB)).toBe(true)
  })

  it('สอง guard แยกกันไม่รบกวนกัน (หน้ากรรมการมีตัวโหลดอิสระ 2 ตัว)', () => {
    // ⚠️ ถ้าเผลอใช้ guard ตัวร่วมกันสองตัวโหลด ตัวที่เริ่มทีหลังจะฆ่า token ของตัวแรก
    //    แล้วตัวแรกจะไม่ปิด `isLoading` ของตัวเอง → สปินเนอร์ค้างถาวร
    const summaryGuard = createLatestGuard()
    const budgetGuard = createLatestGuard()

    const summary = summaryGuard.begin()
    const budget = budgetGuard.begin()

    expect(summaryGuard.isCurrent(summary)).toBe(true)
    expect(budgetGuard.isCurrent(budget)).toBe(true)
  })

  it('token เป็นจำนวนเต็มและเพิ่มขึ้นเสมอ (ใช้เป็นตัวเทียบตรง ๆ ได้)', () => {
    const guard = createLatestGuard()
    const a = guard.begin()
    const b = guard.begin()
    const c = guard.begin()
    expect([a, b, c]).toEqual([1, 2, 3])
  })

  it('token ที่ไม่เคยออกจาก guard นี้ไม่มีทางเป็น "ล่าสุด" (กัน 0 ปลอม)', () => {
    const guard = createLatestGuard()
    guard.begin()
    // ก่อนเริ่มครั้งแรก ตัวนับเป็น 0 — ค่า 0 ต้องไม่ถูกตีความว่าใช้ได้
    // (โค้ดที่ผิดคือ `let latest = -1` แล้วเช็ค `token >= latest` จะพังตรงนี้)
    expect(guard.isCurrent(0)).toBe(false)
    expect(guard.isCurrent(999)).toBe(false)
  })
})
