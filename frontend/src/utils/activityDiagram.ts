/**
 * 📐 เรขาคณิตของแผนภาพเวน/ออยเลอร์ (2–3 กิจกรรม) — บริสุทธิ์ ไม่แตะ DOM/Vue
 *
 * แยกออกมาจาก `ActivityVennDiagram.vue` เพราะเป็น **ตัวเลขล้วน** ที่ผิดแล้วจับไม่ได้ด้วยตา
 * (ป้ายชี้ผิดภูมิภาค = แผนภาพโกหกผู้ใช้ ขณะที่หน้าจอยังดูปกติทุกอย่าง)
 * ⇒ ต้องมีเทสต์ตรวจว่าจุด anchor อยู่ในวงที่ถูกต้องจริง — ดู `__tests__/activityDiagram.spec.ts`
 *
 * 🔴 `mask` ที่นี่เป็น **บิตของกิจกรรมที่เรียงตาม id** เหมือนกับ `sets.build_regions` ฝั่ง backend เป๊ะ
 *    บิตที่ i = กิจกรรมตัวที่ i ในลิสต์ที่เรียง id แล้ว ⇒ หน้าจอต้องเรียงกิจกรรมตาม id ก่อนคำนวณเสมอ
 *    (คีย์ภูมิภาคยังเป็นของ backend เหมือนเดิม — mask ที่นี่ใช้แค่หาตำแหน่งป้าย)
 */

export const CANVAS_W = 640
export const CANVAS_H = 420

interface CircleGeometry {
  radius: number
  centers: [number, number][]
}

/**
 * N=2: วงกลมคู่ขนาน r=150 ที่ (240,210) และ (400,210) — ห่างกัน 160 < 2r ⇒ ทับกันจริง
 * N=3: สามเหลี่ยมด้านเท่า **ด้าน = r** (แบบเวนมาตรฐาน) จุดยอดอยู่ที่ระยะ 145/√3 ≈ 83.7
 *      จากจุดศูนย์กลาง (320,230) ⇒ วงทั้งสามตัดกันเป็นภูมิภาคกลางที่มีพื้นที่จริง
 *      (ถ้าใช้ด้านไกลกว่านี้ ภูมิภาคกลางจะว่างเปล่าทางเรขาคณิต = ป้ายลอยนอกวง)
 */
export const CIRCLE_GEOMETRY: Record<number, CircleGeometry> = {
  2: { radius: 150, centers: [[240, 210], [400, 210]] },
  3: { radius: 145, centers: [[320, 146], [248, 272], [392, 272]] },
}

/**
 * 📍 ตำแหน่งป้ายของแต่ละภูมิภาค — key = mask
 *
 * ค่ามาจากการคำนวณ "จุดกึ่งกลางของพื้นที่ภูมิภาค" (ไม่ใช่เดาจากสายตา):
 * - ภูมิภาคเดี่ยว = ตามแนวจากจุดศูนย์กลางออกไปทางจุดยอดนั้น ระยะ R+90
 * - ภูมิภาคคู่ = กึ่งกลางระหว่างสองวง แล้วดันออกจากจุดศูนย์กลางอีก ~40 (ให้พ้นวงที่สาม)
 * - ภูมิภาคกลาง = จุดศูนย์กลางพอดี (อยู่ในทั้งสามวงเพราะด้านสามเหลี่ยม = r)
 *
 * ครอบคลุมทุก mask ที่เป็นไปได้ของ N=2 (1,2,3) และ N=3 (1–7) — เทสต์บังคับว่าครบ
 * ถ้าวันหนึ่งมีภูมิภาคที่หา anchor ไม่ได้ มันจะไม่ถูกวาดลงแผนภาพแต่ยังอยู่ในรายการภูมิภาค
 * ด้านล่าง (ไม่เงียบหาย)
 */
export const REGION_ANCHORS: Record<number, Record<number, [number, number]>> = {
  2: { 1: [150, 210], 2: [490, 210], 3: [320, 210] },
  3: {
    1: [320, 56], // เฉพาะวงบน
    2: [170, 317], // เฉพาะวงซ้ายล่าง
    4: [470, 317], // เฉพาะวงขวาล่าง
    3: [249, 189], // บน ∩ ซ้ายล่าง
    5: [391, 189], // บน ∩ ขวาล่าง
    6: [320, 312], // ซ้ายล่าง ∩ ขวาล่าง
    7: [320, 230], // ทั้งสามวง
  },
}

/** วงกลมของ N กิจกรรม — `null` เมื่อ N ไม่ใช่ 2 หรือ 3 (ไม่มีเรขาคณิตที่ถูกต้องให้วาด) */
export function circleGeometry(activityCount: number): CircleGeometry | null {
  return CIRCLE_GEOMETRY[activityCount] ?? null
}

/** ตำแหน่งป้ายของ mask นั้น — `null` เมื่อวาดไม่ได้ */
export function regionAnchor(activityCount: number, mask: number): [number, number] | null {
  return REGION_ANCHORS[activityCount]?.[mask] ?? null
}

/**
 * mask ของภูมิภาคจาก `activity_ids` ที่ backend ส่งมา
 * @param activityIds    id ของกิจกรรมในภูมิภาคนั้น
 * @param sortedIds      id ของกิจกรรมที่เลือก **เรียงจากน้อยไปมาก** (ลำดับนี้กำหนดบิต)
 */
export function regionMask(activityIds: number[], sortedIds: number[]): number {
  const bitByActivityId = new Map(sortedIds.map((id, index) => [id, 1 << index]))
  return activityIds.reduce((acc, id) => acc | (bitByActivityId.get(id) ?? 0), 0)
}

/** ตำแหน่งป้ายชื่อกิจกรรม "ข้างวง" (ก่อน clamp แกน x) */
function rawLabelPoint(
  activityCount: number,
  index: number,
): { x: number; y: number } {
  if (activityCount === 2) {
    // คนละครึ่งจอ ⇒ ชื่อยาวแค่ไหนก็ไม่ชนกัน
    return { x: index === 0 ? 150 : 490, y: 44 }
  }
  if (index === 0) return { x: 320, y: 20 } // วงบน — เหนือวง
  if (index === 1) return { x: 111, y: 354 } // วงซ้ายล่าง — มุมล่างนอกวง
  return { x: 529, y: 354 } // วงขวาล่าง
}

// ─────────────────────────────────────────────────────────────────────────────
// 🏷️ ป้ายภูมิภาค (pill) — จัดวางชื่อเล่นเป็นหลายบรรทัดภายในกรอบจำกัด
//
// 🔴 ทำไมต้องมีเพดานความกว้าง/ความสูง และทำไมตัวเลขเหล่านี้ต้องเป็น "ค่าคงที่ที่พิสูจน์ได้"
//    ป้ายแต่ละอันถูกวางที่ anchor ของภูมิภาคตัวเอง ถ้าป้ายกว้างขึ้นโดยไม่มีเพดาน
//    ป้ายที่อยู่ใกล้กัน (เช่น "เฉพาะวงซ้ายล่าง" กับ "ซ้ายล่าง ∩ ขวาล่าง" ซึ่งห่างกัน 150 หน่วย)
//    จะ **ทับกัน** ⇒ อ่านชื่อผิดภูมิภาค = แผนภาพโกหกผู้ใช้ ขณะที่หน้าจอยังดูปกติ
//    ⇒ `PILL_MAX_W` ต้องไม่เกินระยะห่างป้ายที่ใกล้กันที่สุด และมีเทสต์บังคับว่ากรอบใหญ่สุด
//      ของทุกคู่ไม่ทับกัน (`__tests__/activityDiagram.spec.ts`)
//
// 📌 การตัดชื่อในป้ายเป็นเรื่องที่ตั้งใจ — ป้ายคือ "ป้ายแผนภาพ" ไม่ใช่รายชื่อ
//    รายการภูมิภาคด้านล่างแสดงชื่อเล่นครบทุกคนเสมอ และ `<title>` ของป้ายมีชื่อครบทุกคนด้วย
// ─────────────────────────────────────────────────────────────────────────────

/** font-size ของข้อความในป้าย (หน่วย viewBox) */
export const PILL_FONT = 11
/** ความกว้างตัวอักษรไทยเฉลี่ยที่ PILL_FONT — ใช้ประมาณความกว้าง ไม่ต้องวัด DOM */
export const PILL_CHAR_W = 7.4
/** เพดานความกว้างป้าย — ต้องต่ำกว่าระยะห่างระหว่าง anchor ที่ใกล้กันที่สุด (150) */
export const PILL_MAX_W = 130
/** ระยะห่างจากขอบป้ายถึงข้อความ (สองข้าง) */
export const PILL_PAD_X = 10
/** ความสูงต่อหนึ่งบรรทัด + ระยะขอบบน/ล่างรวมกัน */
export const PILL_LINE_H = 13
export const PILL_PAD_Y = 7
/** จำนวนบรรทัดสูงสุดบนป้าย — เพิ่มแล้วต้องตรวจกรอบไม่ให้ทับกัน (ดูเทสต์) */
export const PILL_MAX_LINES = 2
/** จำนวนตัวอักษรไทยสูงสุดต่อบรรทัดที่ยังอยู่ในเพดานความกว้าง */
export const PILL_CHARS_PER_LINE = Math.floor((PILL_MAX_W - 2 * PILL_PAD_X) / PILL_CHAR_W)
/** ความสูงของป้ายที่มี `lines` บรรทัด */
export function pillHeight(lines: number): number {
  return lines * PILL_LINE_H + PILL_PAD_Y
}
/** ความสูงมากสุดที่เป็นไปได้ — ใช้ตรวจการทับกันแบบไม่ต้องรู้ชื่อคน */
export const PILL_MAX_H = pillHeight(PILL_MAX_LINES)
/** ความกว้างต่ำสุดของป้าย (ป้ายของภูมิภาคที่มีคนเดียว/ว่าง) */
export const PILL_MIN_W = 58

export interface PillLayout {
  /** ข้อความแต่ละบรรทัด (อย่างน้อย 1 บรรทัดเสมอ) */
  lines: string[]
  width: number
  height: number
  /** จำนวนชื่อที่ป้ายแสดงไม่ครบ — มีครบในรายการภูมิภาคด้านล่าง */
  hidden: number
}

/** ยืนยันว่าบรรทัดไม่ล้นกรอบ — ตัดกลางชื่อได้เฉพาะกรณีชื่อเดียวยาวเกินทั้งบรรทัด */
function fitLine(line: string, maxChars: number): string {
  return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line
}

/**
 * จัดชื่อเล่นลงป้าย: เติมทีละชื่อจนเต็มบรรทัด แล้วขึ้นบรรทัดใหม่ (สูงสุด `PILL_MAX_LINES`)
 * ชื่อที่เหลือย่อเป็น `+N` ต่อท้ายบรรทัดสุดท้าย
 *
 * ⚠️ ตอนเติม `+N` ต้อง **ตัดชื่อท้ายบรรทัดออกก่อน** ถ้าที่เหลือไม่พอ ไม่งั้น `+N` จะถูก
 *    `fitLine` ตัดทิ้ง ⇒ ตัวเลขบอก "ยังมีคนอีก N คน" หายไปทั้งที่ชื่อก็ถูกตัดไปแล้ว
 *    (ผู้ใช้จะเห็นรายชื่อขาดโดยไม่รู้ว่าขาด — ผิดกฎ "ห้าม truncate ข้อมูลอ่านอย่างเดียว")
 */
export function layoutPill(names: string[]): PillLayout {
  const maxChars = PILL_CHARS_PER_LINE
  if (names.length === 0) {
    return { lines: ['—'], width: PILL_MIN_W, height: pillHeight(1), hidden: 0 }
  }

  const lines: string[] = []
  let index = 0
  while (index < names.length && lines.length < PILL_MAX_LINES) {
    let line = ''
    while (index < names.length) {
      const name = names[index] ?? ''
      const candidate = line ? `${line}, ${name}` : name
      // ชื่อเดียวยาวเกินบรรทัด: ยอมให้อยู่บรรทัดของตัวเองแล้วตัดด้วย `…` ทีหลัง
      if (line && candidate.length > maxChars) break
      line = candidate
      index += 1
    }
    lines.push(line)
  }

  let hidden = names.length - index
  if (hidden > 0) {
    const suffix = ` +${hidden}`
    const last = lines.length - 1
    let tail = lines[last] ?? ''
    while (tail.length + suffix.length > maxChars) {
      const cut = tail.lastIndexOf(', ')
      if (cut < 0) {
        // บรรทัดนี้เหลือชื่อเดียวและยังไม่พอ ⇒ ทิ้งชื่อนั้นเป็นส่วนหนึ่งของ `+N`
        tail = ''
        hidden += 1
        break
      }
      tail = tail.slice(0, cut)
      hidden += 1
    }
    lines[last] = tail ? `${tail}${suffix}` : `+${hidden}`
  }

  const fitted = lines.map((line) => fitLine(line, maxChars))
  const widest = fitted.reduce((max, line) => Math.max(max, line.length), 0)
  const width = Math.min(PILL_MAX_W, Math.max(PILL_MIN_W, widest * PILL_CHAR_W + 2 * PILL_PAD_X))
  return { lines: fitted, width, height: pillHeight(fitted.length), hidden }
}

/**
 * ตำแหน่ง baseline ของบรรทัดที่ `lineIndex` ในป้ายที่วางกึ่งกลางที่ `centerY`
 * (1 บรรทัด → `centerY + 4` เท่าเดิมที่ใช้มาตลอด)
 */
export function pillBaselineY(centerY: number, lineIndex: number, lineCount: number): number {
  return centerY + (lineIndex - (lineCount - 1) / 2) * PILL_LINE_H + 4
}

export interface PillBox {
  left: number
  right: number
  top: number
  bottom: number
}

/**
 * กรอบ **ใหญ่ที่สุดที่เป็นไปได้** ของป้ายภูมิภาคนั้น (ไม่ต้องรู้ชื่อคน)
 * ใช้พิสูจน์ว่าป้ายไม่มีทางทับกันไม่ว่าจะมีสมาชิกกี่คน — ดูเทสต์
 */
export function maxPillBox(activityCount: number, mask: number): PillBox | null {
  const anchor = regionAnchor(activityCount, mask)
  if (!anchor) return null
  const [x, y] = anchor
  return {
    left: x - PILL_MAX_W / 2,
    right: x + PILL_MAX_W / 2,
    top: y - PILL_MAX_H / 2,
    bottom: y + PILL_MAX_H / 2,
  }
}

/** ความกว้างตัวอักษรไทยเฉลี่ยที่ font-size 12 (ใช้ประมาณ ไม่ต้องวัด DOM) */
const LABEL_CHAR_W = 7.2

/**
 * ตำแหน่งป้ายชื่อกิจกรรม พร้อม clamp แกน x ไม่ให้ข้อความล้นออกนอก canvas
 * (ชื่อกิจกรรมไทยยาวได้ถึงหลักสิบตัวอักษร — `text-anchor="middle"` จะล้นสองข้างเท่ากัน)
 */
export function circleLabelPoint(
  activityCount: number,
  index: number,
  title: string,
): { x: number; y: number } {
  const { x, y } = rawLabelPoint(activityCount, index)
  const half = Math.min((title.length * LABEL_CHAR_W) / 2, 260)
  return {
    x: Math.min(Math.max(x, half + 6), CANVAS_W - half - 6),
    y,
  }
}
