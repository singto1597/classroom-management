/**
 * 🎯 ตรรกะภูมิภาคของแผนภาพเวน (Intersection / Union / ลบ) — บริสุทธิ์ ไม่แตะ DOM/API
 *
 * แนวคิด: **ปุ่มสำเร็จรูปเป็นแค่ทางลัดของการติ๊กภูมิภาค** ไม่ใช่คนละกลไก
 * ทั้ง "รวมทั้งหมด" / "ซ้ำทุกกิจกรรม" / "เฉพาะ A" ต่างก็คืนรายการ *คีย์ภูมิภาค*
 * ชุดเดียวกันกับที่ผู้ใช้กดเองบนแผนภาพ ⇒ มีสถานะเดียวในหน้าจอ คือ `Set<string>` ของคีย์
 *
 * 🔴 ฟังก์ชันในไฟล์นี้ **ห้ามประกอบคีย์ภูมิภาคเอง** (`activity_ids.join('-')`)
 *    รูปแบบคีย์เป็นความรับผิดชอบของ backend (`services/activity/sets.py:region_key`)
 *    ที่นี่แค่ "เลือก" จาก `region.key` ที่ server ส่งมา ⇒ ถ้าวันหนึ่งรูปแบบคีย์เปลี่ยน
 *    ฝั่งหน้าไม่ต้องแก้เลย
 */
import type { CompareActivityInfo, CompareMember, CompareRegion } from '@/types/activity'

export type RegionPreset = 'union' | 'intersection' | 'difference'

/** เปรียบเทียบ "ชุดกิจกรรม" โดยไม่สนลำดับ — ใช้ตัดสินว่าใช่ภูมิภาคเดียวกันไหม */
const sameActivitySet = (a: number[], b: number[]): boolean => {
  if (a.length !== b.length) return false
  const sortedA = [...a].sort((x, y) => x - y)
  const sortedB = [...b].sort((x, y) => x - y)
  return sortedA.every((value, index) => value === sortedB[index])
}

/**
 * ชื่อเล่นที่ใช้แสดงบนแผนภาพ/รายการ — ไม่มีชื่อเล่นก็ถอยไปชื่อจริง แล้วค่อยเลขที่
 * (ห้ามปล่อยว่าง เพราะป้ายเปล่าบนแผนภาพอ่านไม่ออกว่าใคร)
 */
export function nicknameOf(member: CompareMember): string {
  const nick = (member.nickname ?? '').trim()
  if (nick) return nick
  const first = (member.first_name ?? '').trim()
  if (first) return first
  return `#${member.student_no || member.student_id}`
}

/** ป้ายของภูมิภาค เช่น `"ไปทัศนศึกษา + กีฬาสี"` (ใช้ชื่อกิจกรรม ไม่ใช่ id) */
export function regionMembershipLabel(
  region: CompareRegion,
  activities: CompareActivityInfo[],
): string {
  const titleById = new Map(activities.map((activity) => [activity.id, activity.title]))
  return region.activity_ids.map((id) => titleById.get(id) ?? `#${id}`).join(' + ')
}

/** ชื่อเล่นของทุกคนในภูมิภาค เรียงตามเลขที่ (ใช้แสดงในรายการภูมิภาค) */
export function regionNicknames(region: CompareRegion): string[] {
  return [...region.members]
    .sort((a, b) => a.student_no - b.student_no || a.student_id - b.student_id)
    .map(nicknameOf)
}

/**
 * คีย์ภูมิภาคของปุ่มสำเร็จรูป
 *
 * - `union`        → ทุกภูมิภาค (คนที่อยู่กิจกรรมใดก็ได้)
 * - `intersection` → ภูมิภาคที่มี **กิจกรรมครบทุกตัวที่เลือก** — ถ้าไม่มีใครอยู่ครบ
 *                    จะได้ `[]` (ไม่ใช่ "ภูมิภาคที่ลึกที่สุด" ซึ่งจะกลายเป็น "อยู่ 2 จาก 3"
 *                    ทั้งที่ป้ายบอกว่า "ซ้ำทุกกิจกรรม" ⇒ ตัวเลขบนจอโกหก)
 * - `difference`   → ภูมิภาคที่อยู่ `baseActivityId` **เดี่ยว ๆ** เท่านั้น (= A \ (B ∪ C))
 *                    ถ้าอยากได้ A \ B แบบมี C ร่วมด้วย ต้องกดภูมิภาคเอง (เจตนา)
 */
export function regionsForPreset(
  regions: CompareRegion[],
  preset: RegionPreset,
  activityIds: number[],
  baseActivityId?: number,
): string[] {
  if (preset === 'union') return regions.map((region) => region.key)

  if (preset === 'intersection') {
    return regions
      .filter((region) => sameActivitySet(region.activity_ids, activityIds))
      .map((region) => region.key)
  }

  if (baseActivityId === undefined) return []
  return regions
    .filter(
      (region) =>
        region.activity_ids.length === 1 && region.activity_ids[0] === baseActivityId,
    )
    .map((region) => region.key)
}

/** จำนวนคนที่ไม่ซ้ำของภูมิภาคที่เลือก (ใช้กับตัวนับ "เลือกแล้ว N คน") */
export function countUniqueMembers(regions: CompareRegion[], selectedKeys: Iterable<string>): number {
  const selected = new Set(selectedKeys)
  const studentIds = new Set<number>()
  for (const region of regions) {
    if (!selected.has(region.key)) continue
    for (const member of region.members) studentIds.add(member.student_id)
  }
  return studentIds.size
}
