import { describe, expect, it } from 'vitest'

import {
  countUniqueMembers,
  nicknameOf,
  regionMembershipLabel,
  regionNicknames,
  regionsForPreset,
} from '@/utils/activitySets'
import type { CompareActivityInfo, CompareMember, CompareRegion } from '@/types/activity'

/**
 * 🎯 เทสต์ชุดนี้พิสูจน์ **ความหมายของปุ่มสำเร็จรูป** ไม่ใช่แค่การกรอง array
 *    เพราะบั๊กที่อันตรายที่สุดของฟีเจอร์นี้คือ "ปุ่มบอกอย่าง แต่ตัวเลขบนจอเป็นอีกอย่าง"
 *    (เช่น กด 'ซ้ำทุกกิจกรรม' แล้วได้คนที่อยู่แค่ 2 จาก 3 กิจกรรม)
 */

const ACTIVITIES: CompareActivityInfo[] = [
  { id: 3, title: 'ไปทัศนศึกษา', activity_date: '2026-10-01', participant_count: 3 },
  { id: 7, title: 'กีฬาสี', activity_date: '2026-10-05', participant_count: 3 },
]

const member = (student_id: number, student_no: number, nickname: string | null = null): CompareMember => ({
  student_id,
  student_no,
  nickname,
  first_name: `ชื่อ${student_no}`,
  last_name: 'นามสกุล',
  first_name_en: null,
  last_name_en: null,
  nickname_en: null,
})

/** ภูมิภาค "อยู่ทั้งสองกิจกรรม" — แยกเป็นค่าคงที่เพราะถูกอ้างหลายเทสต์
 *  (`noUncheckedIndexedAccess` ทำให้ `REGIONS[2]` มีชนิดเป็น `CompareRegion | undefined`) */
const BOTH: CompareRegion = {
  key: '3-7',
  activity_ids: [3, 7],
  members: [member(2, 2, 'สอง'), member(3, 3, null)],
}

/** 2 กิจกรรม: 3 = {1}, 7 = {4}, 3+7 = {2,3} */
const REGIONS: CompareRegion[] = [
  { key: '3', activity_ids: [3], members: [member(1, 1, 'หนึ่ง')] },
  { key: '7', activity_ids: [7], members: [member(4, 4, 'สี่')] },
  BOTH,
]

describe('regionsForPreset', () => {
  it('union → ทุกภูมิภาค (คนที่อยู่กิจกรรมใดก็ได้)', () => {
    expect(regionsForPreset(REGIONS, 'union', [3, 7])).toEqual(['3', '7', '3-7'])
  })

  it('intersection → เฉพาะภูมิภาคที่มีกิจกรรมครบทุกตัวที่เลือก', () => {
    expect(regionsForPreset(REGIONS, 'intersection', [3, 7])).toEqual(['3-7'])
  })

  it('intersection → ไม่มีใครอยู่ครบ ต้องได้ [] ไม่ใช่ภูมิภาคที่ลึกที่สุด', () => {
    // 🚨 ถ้าเผลอใช้ "ความลึกมากสุด" จะได้ ['3-7'] = "อยู่ 2 จาก 3" ทั้งที่ป้ายบอก "ซ้ำทุกกิจกรรม"
    expect(regionsForPreset(REGIONS, 'intersection', [3, 7, 9])).toEqual([])
  })

  it('difference → อยู่กิจกรรมตั้งต้นเดี่ยว ๆ เท่านั้น (A \\ (B ∪ C))', () => {
    expect(regionsForPreset(REGIONS, 'difference', [3, 7], 3)).toEqual(['3'])
    expect(regionsForPreset(REGIONS, 'difference', [3, 7], 7)).toEqual(['7'])
  })

  it('difference → ถ้าไม่มีใครอยู่ base เดี่ยว ๆ ต้องได้ []', () => {
    const pairOnly: CompareRegion[] = [{ key: '3-7', activity_ids: [3, 7], members: [member(2, 2)] }]
    expect(regionsForPreset(pairOnly, 'difference', [3, 7], 3)).toEqual([])
  })

  it('difference → ไม่ระบุกิจกรรมตั้งต้น ได้ [] (ไม่โยน error)', () => {
    expect(regionsForPreset(REGIONS, 'difference', [3, 7])).toEqual([])
  })

  it('เลือกกิจกรรมลำดับสลับกันก็ยังได้คีย์เดิม (เทียบเป็นชุด ไม่ใช่ลำดับ)', () => {
    expect(regionsForPreset(REGIONS, 'intersection', [7, 3])).toEqual(['3-7'])
  })

  it('ไม่สร้างคีย์เอง — คีย์ที่ได้ต้องมีอยู่จริงใน regions', () => {
    const allKeys = new Set(REGIONS.map((region) => region.key))
    for (const preset of ['union', 'intersection', 'difference'] as const) {
      for (const key of regionsForPreset(REGIONS, preset, [3, 7], 3)) {
        expect(allKeys.has(key)).toBe(true)
      }
    }
  })
})

describe('nicknameOf', () => {
  it('มีชื่อเล่น → ใช้ชื่อเล่น', () => {
    expect(nicknameOf(member(1, 1, 'หนึ่ง'))).toBe('หนึ่ง')
  })

  it('ไม่มีชื่อเล่น → ถอยไปชื่อจริง (ไม่ปล่อยว่าง)', () => {
    expect(nicknameOf(member(2, 2, null))).toBe('ชื่อ2')
  })

  it('ชื่อเล่นเป็นช่องว่างล้วน → ถือว่าไม่มี', () => {
    expect(nicknameOf(member(3, 3, '   '))).toBe('ชื่อ3')
  })

  it('ไม่มีทั้งชื่อเล่นและชื่อจริง → ใช้เลขที่', () => {
    const bare = { ...member(9, 9, null), first_name: null }
    expect(nicknameOf(bare)).toBe('#9')
  })
})

describe('regionMembershipLabel', () => {
  it('ใช้ชื่อกิจกรรมคั่นด้วย +', () => {
    expect(regionMembershipLabel(BOTH, ACTIVITIES)).toBe('ไปทัศนศึกษา + กีฬาสี')
  })

  it('กิจกรรมที่ไม่อยู่ในลิสต์ → ถอยไปใช้ id', () => {
    const orphan: CompareRegion = { key: '99', activity_ids: [99], members: [] }
    expect(regionMembershipLabel(orphan, ACTIVITIES)).toBe('#99')
  })
})

describe('regionNicknames', () => {
  it('เรียงตามเลขที่ในห้อง', () => {
    expect(regionNicknames(BOTH)).toEqual(['สอง', 'ชื่อ3'])
  })
})

describe('countUniqueMembers', () => {
  it('นับคนไม่ซ้ำในภูมิภาคที่เลือก', () => {
    expect(countUniqueMembers(REGIONS, ['3', '3-7'])).toBe(3)
  })

  it('ไม่ได้เลือกอะไร → 0', () => {
    expect(countUniqueMembers(REGIONS, [])).toBe(0)
  })

  it('เลือกทุกภูมิภาค → เท่าจำนวนคนทั้งหมด', () => {
    expect(countUniqueMembers(REGIONS, REGIONS.map((region) => region.key))).toBe(4)
  })

  it('คีย์ที่ไม่มีอยู่จริง → ไม่ถูกนับ', () => {
    expect(countUniqueMembers(REGIONS, ['999'])).toBe(0)
  })
})
