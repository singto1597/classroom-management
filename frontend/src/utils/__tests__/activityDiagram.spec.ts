import { describe, expect, it } from 'vitest'

import {
  CANVAS_H,
  CANVAS_W,
  CIRCLE_GEOMETRY,
  REGION_ANCHORS,
  circleGeometry,
  circleLabelPoint,
  regionAnchor,
  regionMask,
} from '@/utils/activityDiagram'

/**
 * 🎯 เทสต์ชุดนี้พิสูจน์ **เรขาคณิต** ไม่ใช่แค่การคืนค่า
 *
 * บั๊กที่อันตรายที่สุดของแผนภาพคือ "ป้ายชี้ผิดภูมิภาค" — หน้าจอยังดูปกติทุกอย่าง
 * สีสวย กดได้ ไม่มี error แต่ชื่อคนไปโผล่ผิดวง แล้วครู export ผิดกลุ่มโดยไม่รู้ตัว
 * ⇒ ต้องพิสูจน์ด้วยคณิตศาสตร์ว่าจุด anchor อยู่ในวงที่ถูกต้อง **จริง**
 *    ไม่ใช่ดูจากภาพ (ซึ่งตรวจไม่ได้ในเทสต์และพลาดได้ง่ายเวลาใครขยับพิกัด)
 */

/** อยู่ในวงกลมไหม (ระยะจากจุดศูนย์กลางน้อยกว่ารัศมี) */
const insideCircle = (
  point: [number, number],
  center: [number, number],
  radius: number,
): boolean => Math.hypot(point[0] - center[0], point[1] - center[1]) < radius

describe('CIRCLE_GEOMETRY', () => {
  it('มีเรขาคณิตให้เฉพาะ 2 และ 3 กิจกรรม', () => {
    expect(Object.keys(CIRCLE_GEOMETRY).map(Number).sort()).toEqual([2, 3])
    expect(circleGeometry(1)).toBeNull()
    expect(circleGeometry(4)).toBeNull()
  })

  it.each([2, 3])('N=%i — วงกลมทุกวงต้องอยู่ใน canvas ไม่ล้นขอบ', (count) => {
    const geometry = circleGeometry(count)!
    for (const [cx, cy] of geometry.centers) {
      expect(cx - geometry.radius).toBeGreaterThanOrEqual(0)
      expect(cx + geometry.radius).toBeLessThanOrEqual(CANVAS_W)
      expect(cy - geometry.radius).toBeGreaterThanOrEqual(0)
      expect(cy + geometry.radius).toBeLessThanOrEqual(CANVAS_H)
    }
  })

  it.each([2, 3])('N=%i — วงกลมต้องทับกันจริง (ไม่ใช่แยกกันลอย)', (count) => {
    const geometry = circleGeometry(count)!
    for (let i = 0; i < geometry.centers.length; i += 1) {
      for (let j = i + 1; j < geometry.centers.length; j += 1) {
        const a = geometry.centers[i]!
        const b = geometry.centers[j]!
        const distance = Math.hypot(a[0] - b[0], a[1] - b[1])
        // ห่างกันน้อยกว่า 2r ⇒ มีพื้นที่ซ้อน และต้องไม่ทับกันจนวงหนึ่งอยู่ในอีกวง
        expect(distance).toBeLessThan(2 * geometry.radius)
        expect(distance).toBeGreaterThan(0)
      }
    }
  })
})

describe('REGION_ANCHORS', () => {
  it('N=2 ต้องมีครบ 3 ภูมิภาค (1, 2, 3)', () => {
    expect(Object.keys(REGION_ANCHORS[2]!).map(Number).sort((a, b) => a - b)).toEqual([1, 2, 3])
  })

  it('N=3 ต้องมีครบ 7 ภูมิภาค (1–7)', () => {
    expect(Object.keys(REGION_ANCHORS[3]!).map(Number).sort((a, b) => a - b)).toEqual([
      1, 2, 3, 4, 5, 6, 7,
    ])
  })

  it.each([
    [2, 1],
    [2, 2],
    [2, 3],
    [3, 1],
    [3, 2],
    [3, 3],
    [3, 4],
    [3, 5],
    [3, 6],
    [3, 7],
  ])('N=%i mask=%i — จุด anchor ต้องอยู่ในวงตามบิตของ mask เท่านั้น', (count, mask) => {
    const geometry = circleGeometry(count)!
    const point = regionAnchor(count, mask)!

    const expected = geometry.centers.map((_, index) => ((mask >> index) & 1 ? 1 : 0))
    const actual = geometry.centers.map((center) =>
      insideCircle(point, center, geometry.radius) ? 1 : 0,
    )

    expect(actual).toEqual(expected)
  })

  it('mask ที่ไม่รู้จัก → null (ไม่แอบคืนจุดมั่ว)', () => {
    expect(regionAnchor(2, 4)).toBeNull()
    expect(regionAnchor(3, 8)).toBeNull()
    expect(regionAnchor(4, 1)).toBeNull()
  })
})

describe('regionMask', () => {
  it('เรียงบิตตามลำดับ id ที่ส่งเข้ามา (ไม่ใช่ลำดับใน activity_ids)', () => {
    // กิจกรรมเรียงแล้ว [3, 7] ⇒ 3 = บิต 1, 7 = บิต 2
    expect(regionMask([3], [3, 7])).toBe(1)
    expect(regionMask([7], [3, 7])).toBe(2)
    expect(regionMask([3, 7], [3, 7])).toBe(3)
  })

  it('N=3 — บิตที่สามคือ 4 (ไม่ใช่ 3)', () => {
    expect(regionMask([9], [3, 7, 9])).toBe(4)
    expect(regionMask([3, 9], [3, 7, 9])).toBe(5)
    expect(regionMask([3, 7, 9], [3, 7, 9])).toBe(7)
  })

  it('ลำดับใน activity_ids ไม่มีผล (เข้าใจว่าเป็นชุด)', () => {
    expect(regionMask([9, 3], [3, 7, 9])).toBe(5)
  })

  it('id ที่ไม่อยู่ในลิสต์ที่เลือก → ไม่ร่วมบิต (ได้ 0)', () => {
    expect(regionMask([99], [3, 7])).toBe(0)
  })

  it('ทุกชุดย่อยของ N=3 ให้ mask ไม่ซ้ำกัน', () => {
    const masks = new Set<number>()
    const ids = [3, 7, 9]
    for (let bits = 1; bits < 8; bits += 1) {
      const picked = ids.filter((_, index) => (bits >> index) & 1)
      masks.add(regionMask(picked, ids))
    }
    expect(masks.size).toBe(7)
  })
})

describe('circleLabelPoint', () => {
  it.each([2, 3])('N=%i — ป้ายชื่อกิจกรรมต้องอยู่ใน canvas', (count) => {
    for (let index = 0; index < count; index += 1) {
      const point = circleLabelPoint(count, index, 'กิจกรรม')
      expect(point.x).toBeGreaterThan(0)
      expect(point.x).toBeLessThan(CANVAS_W)
      expect(point.y).toBeGreaterThan(0)
      expect(point.y).toBeLessThan(CANVAS_H)
    }
  })

  it('ชื่อกิจกรรมยาวมาก → ถูก clamp ไม่ให้ล้นขอบซ้าย/ขวา', () => {
    const long = 'กิจกรรมทัศนศึกษาเชิงอนุรักษ์ธรรมชาติและสิ่งแวดล้อมประจำปีการศึกษา'
    for (let index = 0; index < 3; index += 1) {
      const point = circleLabelPoint(3, index, long)
      const half = (long.length * 7.2) / 2
      expect(point.x - half).toBeGreaterThanOrEqual(0)
      expect(point.x + half).toBeLessThanOrEqual(CANVAS_W)
    }
  })

  it('ป้ายของแต่ละวงต้องไม่ทับกันเองเมื่อชื่อยาว', () => {
    const long = 'กิจกรรมพัฒนาแหล่งเรียนรู้ชุมชน'
    const xs = [0, 1, 2].map((index) => circleLabelPoint(3, index, long).x)
    expect(new Set(xs).size).toBe(3)
  })
})
