/**
 * 📅 สถานะ "วันปิดรับลงทะเบียน" ของกิจกรรม (P4.4)
 *
 * ทำไมต้องเป็นฟังก์ชันบริสุทธิ์: ป้ายบนรายการ ("ใกล้ปิดรับ" / "ปิดรับแล้ว")
 * ต้องพิสูจน์ได้โดยไม่ต้อง mount หน้าและไม่ผูกกับนาฬิกาของเครื่อง —
 * ทุกฟังก์ชันรับ `todayIso` เข้ามาเสมอ **ห้ามเรียก new Date() ข้างใน**
 * (เทสต์ที่ขึ้นกับเวลาจริงจะผ่านวันนี้และตกพรุ่งนี้)
 *
 * ⚠️ เทียบ string `YYYY-MM-DD` ตรง ๆ ได้ เพราะรูปแบบเรียงตามพจนานุกรม = เรียงตามเวลา
 *    ถ้าเปลี่ยนไปใช้ Date ต้องระวัง timezone: ฝั่งนี้ใช้ Bangkok แต่ `Date` อ่านเป็น UTC
 */

/** จำนวนวันล่วงหน้าที่ถือว่า "ใกล้ปิดรับ" */
export const DEADLINE_SOON_DAYS = 7

export type DeadlineState = 'none' | 'closed' | 'soon' | 'open'

const DAY_MS = 86_400_000

/** ระยะห่างเป็นวัน (deadline − today) · null เมื่อไม่มีวันหรือรูปแบบผิด */
export function daysUntilDeadline(
  deadline: string | null | undefined,
  todayIso: string,
): number | null {
  if (!deadline || !todayIso) return null
  const deadlineMs = Date.parse(`${deadline}T00:00:00Z`)
  const todayMs = Date.parse(`${todayIso}T00:00:00Z`)
  if (Number.isNaN(deadlineMs) || Number.isNaN(todayMs)) return null
  return Math.round((deadlineMs - todayMs) / DAY_MS)
}

/**
 * `closed` = เลยวันปิดมาแล้ว · `soon` = เหลือ 0–7 วัน · `open` = ยังมีเวลา
 * `none` = กิจกรรมนี้ไม่มีกำหนดปิดรับ (หรือข้อมูลไม่ถูกต้อง)
 */
export function deadlineState(
  deadline: string | null | undefined,
  todayIso: string,
): DeadlineState {
  const days = daysUntilDeadline(deadline, todayIso)
  if (days === null) return 'none'
  if (days < 0) return 'closed'
  if (days <= DEADLINE_SOON_DAYS) return 'soon'
  return 'open'
}

/** ข้อความป้ายบนการ์ด — `null` = ไม่ต้องแสดงป้าย */
export function deadlineLabel(
  deadline: string | null | undefined,
  todayIso: string,
): string | null {
  const state = deadlineState(deadline, todayIso)
  const days = daysUntilDeadline(deadline, todayIso)
  if (state === 'closed') return 'ปิดรับแล้ว'
  if (state === 'soon' && days !== null) {
    return days === 0 ? 'ปิดรับวันนี้' : `เหลือ ${days} วัน`
  }
  return null
}
