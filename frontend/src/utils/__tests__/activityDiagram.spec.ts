import { describe, expect, it } from 'vitest'

import {
  CANVAS_H,
  CANVAS_W,
  CIRCLE_GEOMETRY,
  PILL_CHARS_PER_LINE,
  PILL_MAX_LINES,
  PILL_MAX_W,
  PILL_MIN_W,
  REGION_ANCHORS,
  circleGeometry,
  circleLabelPoint,
  layoutPill,
  maxPillBox,
  pillBaselineY,
  pillHeight,
  regionAnchor,
  regionMask,
  type PillBox,
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

/**
 * 🏷️ ป้ายภูมิภาค (pill)
 *
 * บั๊กที่เทสต์ชุดนี้กันไว้:
 *  1. 🔴 **ป้ายทับกัน** — เพดานความกว้าง/ความสูงของป้ายโตขึ้นได้โดยไม่มีอะไรห้าม
 *     ⇒ ป้ายของภูมิภาคที่อยู่ใกล้กันทับกัน แล้วอ่านชื่อผิดภูมิภาค (แผนภาพโกหก)
 *     ⇒ พิสูจน์ด้วย "กรอบใหญ่สุดที่เป็นไปได้" ของทุกคู่ ไม่ต้องรู้ชื่อคนเลย
 *  2. 🔴 **`+N` หาย** — ถ้าตัด `+N` ต่อท้ายบรรทัดที่เต็มพอดีโดยไม่ตัดชื่อออกก่อน
 *     ตัวเลข "ยังมีอีก N คน" จะถูก `fitLine` ตัดทิ้งไปด้วย ⇒ รายชื่อขาดแบบเงียบ ๆ
 *  3. **ชื่อหายทั้งที่ไม่ได้บอก** — ผลรวมชื่อที่แสดง + จำนวนใน `+N` ต้องเท่าจำนวนจริงเสมอ
 */
describe('layoutPill', () => {
  const SHORT = ['สม', 'หญิง', 'ปลา', 'ต้อม', 'นก', 'ออย', 'เบียร์', 'มิ้น']

  it('ไม่มีสมาชิก → ป้ายสั้นที่สุด 1 บรรทัด', () => {
    const layout = layoutPill([])
    expect(layout.lines).toEqual(['—'])
    expect(layout.hidden).toBe(0)
    expect(layout.width).toBe(PILL_MIN_W)
  })

  it('ชื่อไม่กี่ชื่อที่พอดี → บรรทัดเดียว ไม่มี `+N`', () => {
    const layout = layoutPill(['สม', 'หญิง'])
    expect(layout.lines).toEqual(['สม, หญิง'])
    expect(layout.hidden).toBe(0)
    expect(layout.height).toBe(pillHeight(1))
  })

  it('ชื่อเยอะ → ตัดบรรทัดให้เอง ไม่เกิน PILL_MAX_LINES', () => {
    const layout = layoutPill(SHORT)
    expect(layout.lines.length).toBeGreaterThan(1)
    expect(layout.lines.length).toBeLessThanOrEqual(PILL_MAX_LINES)
    expect(layout.height).toBe(pillHeight(layout.lines.length))
  })

  it.each([
    ['2 ชื่อ', ['สม', 'หญิง']],
    ['8 ชื่อ', SHORT],
    ['ชื่อยาว', ['ณัฐพงษ์สิทธิ์', 'วรวรรณธนา', 'ปัณณวิชญ์', 'ฐิติพร']],
  ])('%s — ทุกบรรทัดไม่ล้นเพดานความกว้าง และความกว้างอยู่ในกรอบ', (_label, names) => {
    const layout = layoutPill(names)
    for (const line of layout.lines) {
      expect(line.length).toBeLessThanOrEqual(PILL_CHARS_PER_LINE)
    }
    expect(layout.width).toBeGreaterThanOrEqual(PILL_MIN_W)
    expect(layout.width).toBeLessThanOrEqual(PILL_MAX_W)
  })

  it('🔴 `+N` ต้องไม่ถูกตัดทิ้ง แม้บรรทัดสุดท้ายจะเต็มพอดี', () => {
    // ชื่อยาวจนบรรทัดที่สองเต็มพอดี — เคสที่ทำให้ `+N` ถูกตัดถ้าไม่ตัดชื่อออกก่อน
    const names = ['ณัฐพงษ์สิทธิ์', 'วรวรรณธนา', 'ปัณณวิชญ์', 'ฐิติพร', 'กมลวรรณ', 'สุทธิพงษ์']
    const layout = layoutPill(names)
    const last = layout.lines[layout.lines.length - 1] ?? ''
    expect(last).toMatch(/\+\d+$/)
    expect(Number(last.match(/\+(\d+)$/)?.[1])).toBe(layout.hidden)
    for (const line of layout.lines) {
      expect(line.length).toBeLessThanOrEqual(PILL_CHARS_PER_LINE)
    }
  })

  it('🔴 จำนวนชื่อที่แสดง + จำนวนใน `+N` = จำนวนสมาชิกจริงเสมอ (ไม่มีชื่อหายเงียบ)', () => {
    for (const names of [SHORT, SHORT.slice(0, 1), SHORT.slice(0, 4), SHORT.slice(0, 6)]) {
      const layout = layoutPill(names)
      const text = layout.lines.join('\n')
      const shown = names.filter((name) => text.includes(name)).length
      expect(shown + layout.hidden).toBe(names.length)
    }
  })

  it('บรรทัดสุดท้ายที่เหลือชื่อเดียวและ `+N` ไม่พอ → ทิ้งชื่อนั้นเข้า `+N` (ไม่ตัด `+N`)', () => {
    // บรรทัดที่ 2 มีชื่อเดียวที่ยาวจน `+N` ต่อไม่ลง
    const names = ['ก', 'ข', 'ค', 'ง', 'จ', 'ฉ', 'ช', 'ณัฐพงษ์สิทธิ์ศักดิ์ชัย', 'ญ', 'ฎ']
    const layout = layoutPill(names)
    const last = layout.lines[layout.lines.length - 1] ?? ''
    expect(last).toMatch(/\+\d+$/)
    const text = layout.lines.join('\n')
    const shown = names.filter((name) => text.includes(name)).length
    expect(shown + layout.hidden).toBe(names.length)
  })
})

describe('pillBaselineY', () => {
  it('บรรทัดเดียว → อยู่ที่ centerY + 4 (ตำแหน่งเดิมก่อนรองรับหลายบรรทัด)', () => {
    expect(pillBaselineY(210, 0, 1)).toBe(214)
  })

  it('หลายบรรทัด → เรียงจากบนลงล่าง และกึ่งกลางที่ centerY', () => {
    const first = pillBaselineY(210, 0, 2)
    const second = pillBaselineY(210, 1, 2)
    expect(first).toBeLessThan(second)
    expect((first + second) / 2).toBeCloseTo(214, 5)
  })

  it('ทุกบรรทัดอยู่ในกรอบป้ายที่ความสูงนั้น', () => {
    for (const lines of [1, PILL_MAX_LINES]) {
      const height = pillHeight(lines)
      const top = 210 - height / 2
      const bottom = 210 + height / 2
      for (let index = 0; index < lines; index += 1) {
        const baseline = pillBaselineY(210, index, lines)
        expect(baseline).toBeGreaterThan(top)
        expect(baseline).toBeLessThan(bottom)
      }
    }
  })
})

describe('maxPillBox', () => {
  /** กรอบสองกรอบทับกันจริงไหม (แตะขอบพอดีไม่นับเป็นทับ) */
  const overlaps = (a: PillBox, b: PillBox): boolean =>
    a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

  it.each([2, 3])('N=%i — ป้ายทุกคู่ไม่มีทางทับกัน ไม่ว่าจะมีสมาชิกกี่คน', (count) => {
    const masks = Object.keys(REGION_ANCHORS[count] ?? {}).map(Number)
    const boxes = masks.map((mask) => ({ mask, box: maxPillBox(count, mask) }))
    for (const entry of boxes) expect(entry.box).not.toBeNull()

    // รวมคู่ที่ทับกันเป็นรายการเดียว ⇒ ข้อความเทสต์ที่ fail บอกตรง ๆ ว่าคู่ไหนทับ
    const colliding: string[] = []
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const left = boxes[i]
        const right = boxes[j]
        if (!left?.box || !right?.box) continue
        if (overlaps(left.box, right.box)) colliding.push(`${left.mask} ↔ ${right.mask}`)
      }
    }
    expect(colliding).toEqual([])
  })

  it.each([2, 3])('N=%i — ป้ายใหญ่สุดยังอยู่ในขอบ canvas', (count) => {
    for (const mask of Object.keys(REGION_ANCHORS[count] ?? {}).map(Number)) {
      const box = maxPillBox(count, mask)
      expect(box).not.toBeNull()
      if (!box) continue
      expect(box.left).toBeGreaterThanOrEqual(0)
      expect(box.right).toBeLessThanOrEqual(CANVAS_W)
      expect(box.top).toBeGreaterThanOrEqual(0)
      expect(box.bottom).toBeLessThanOrEqual(CANVAS_H)
    }
  })

  it('mask ที่ไม่มี anchor → null (ไม่มีกรอบให้ตรวจ)', () => {
    expect(maxPillBox(3, 99)).toBeNull()
    expect(maxPillBox(1, 1)).toBeNull()
  })
})
