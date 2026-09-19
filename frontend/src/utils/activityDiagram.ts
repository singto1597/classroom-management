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
