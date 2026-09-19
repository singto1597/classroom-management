<script setup lang="ts">
/**
 * 🔵 ActivityVennDiagram — แผนภาพเวน/ออยเลอร์ของ 2–3 กิจกรรม
 *
 * 🎯 ตอบคำถาม "ใครอยู่กิจกรรมไหน" ให้เห็นก่อนตัดสินใจ export
 *    แต่ละภูมิภาค (region) คือกลุ่มคนที่มี **ชุดกิจกรรมที่อยู่เหมือนกันเป๊ะ**
 *    ภูมิภาคมีคนอยู่เท่านั้นที่จะถูกวาด (backend ไม่ส่งภูมิภาคเปล่ามา)
 *
 * 📐 ทำไม "แผนภาพเวน" ไม่ใช่ "แผนภาพออยเลอร์"
 *    - จำนวนภูมิภาคที่วาด = จำนวนภูมิภาคที่มีคนจริง ⇒ วงกลมไม่ได้แปลว่าทุกภูมิภาคมีคน
 *      ⇒ โดยพฤตินัยคือ **ออยเลอร์** (วงทับกันเฉพาะที่มีส่วนร่วมจริง)
 *    - แต่ตำแหน่งวง/ป้ายยังยึดเรขาคณิตเวนมาตรฐาน (2 วง = 3 ภูมิภาค, 3 วง = 7 ภูมิภาค)
 *      เพื่อให้ตำแหน่งป้ายนิ่ง ไม่กระโดดไปมาตามข้อมูล
 *
 * 🔴 ห้ามคำนวณคีย์ภูมิภาคเองในไฟล์นี้ — รูปแบบคีย์ (`"3-7"`) เป็นความรับผิดชอบของ
 *    backend (`services/activity/sets.py:region_key`) ที่นี่อ่าน `region.key` เท่านั้น
 *    (mask ที่คำนวณด้านล่างใช้แค่ **หาตำแหน่งป้าย** ไม่ได้ใช้สร้างคีย์)
 *
 * 🎨 สี: `brand-*` + `stone-*` + `paper` เท่านั้น (frontend.md §6)
 *    - คลาสทั้งหมดเป็น **literal ใน array คงที่** เพราะ Tailwind JIT ไม่ compile
 *      คลาสที่ประกอบตอน runtime (skills.md — บั๊กเดียวกับ `ExportStudent`)
 *    - ไม่ใช้สีเป็นช่องทางเดียว: แต่ละวงมี `stroke-dasharray` ต่างกัน + มีป้ายชื่อกิจกรรม
 *      กำกับข้างวง ⇒ ผู้ใช้ที่แยกสีไม่ได้ก็ยังรู้ว่าวงไหนคือกิจกรรมไหน
 *
 * 📱 มือถือ: แผนภาพ **แสดงเสมอ** แต่มี `min-w` คุมไว้ในกรอบที่เลื่อนแนวนอนได้
 *    ❌ ไม่ซ่อนอีกต่อไป — "ซ่อนบนจอแคบ" ทำให้ผู้ใช้มือถือไม่เห็นแผนภาพเลยทั้งที่ขอมา
 *    ❌ ไม่ปล่อยให้ย่อเต็มจอเช่นกัน — ย่อถึง ~340px แล้วตัวอักษร 11px เหลือ ~5.8px อ่านไม่ออก
 *    ⇒ เลือกทางที่สาม: ล็อกความกว้างขั้นต่ำ (34rem) แล้วให้กรอบเลื่อนแนวนอน
 *      ตัวอักษรยังอ่านออก และไม่ต้องเรนเดอร์ SVG สองแบบตาม breakpoint (เพิ่มสถานะให้เพี้ยนได้)
 *
 * 📌 ชื่อบนป้ายแผนภาพถูกตัดได้ (2 บรรทัด + `+N`) — เป็น "ป้าย" ไม่ใช่รายชื่อ
 *    ชื่อครบทุกคนอยู่ใน `<title>` ของป้าย (hover/โฟกัส) และในรายการภูมิภาคด้านล่าง
 */
import { computed } from 'vue'

import {
  CANVAS_H,
  CANVAS_W,
  PILL_FONT,
  circleGeometry,
  circleLabelPoint,
  layoutPill,
  pillBaselineY,
  regionAnchor,
  regionMask,
} from '@/utils/activityDiagram'
import { nicknameOf, regionMembershipLabel } from '@/utils/activitySets'
import type { CompareActivityInfo, CompareRegion } from '@/types/activity'

const props = defineProps<{
  /** กิจกรรมที่เลือก (2–3 ตัว) — เรียงลำดับใดก็ได้ ตัวคอมโพเนนต์จะเรียงตาม id เอง */
  activities: CompareActivityInfo[]
  /** ภูมิภาคจาก backend — ใช้ `key`/`activity_ids`/`members` ตรง ๆ ห้ามดัดแปลง */
  regions: CompareRegion[]
  /** คีย์ภูมิภาคที่เลือกอยู่ */
  selectedKeys: string[]
}>()

const emit = defineEmits<{ (e: 'toggle', key: string): void }>()

/** 🎨 คลาสของวงกลม — literal คงที่ (Tailwind JIT สแกนไม่เจอถ้าประกอบตอน runtime) */
const CIRCLE_FILL = 'fill-brand-100'
const CIRCLE_STROKE_CLASSES = ['stroke-brand-500', 'stroke-brand-700', 'stroke-brand-300'] as const
/** ช่องทางที่สองนอกจากสี — ลายเส้นต่างกันต่อวง */
const CIRCLE_DASH = ['9 5', '2 4', '16 4 3 4'] as const

/** 🎨 คลาสของป้ายภูมิภาค */
const PILL_SELECTED_CLASSES = 'fill-brand-700 stroke-brand-800'
const PILL_IDLE_CLASSES = 'fill-paper stroke-stone-300'
const PILL_TEXT_SELECTED = 'fill-white'
const PILL_TEXT_IDLE = 'fill-stone-700'

const PILL_R = 11

/** กิจกรรมเรียงตาม id — ลำดับนี้ต้องตรงกับที่ backend ใช้คิดบิตของ mask */
const sortedActivities = computed(() =>
  [...props.activities].sort((a, b) => a.id - b.id),
)

const geometry = computed(() => circleGeometry(sortedActivities.value.length))

const circles = computed(() => {
  const geom = geometry.value
  if (!geom) return []
  const count = sortedActivities.value.length
  return sortedActivities.value.map((activity, index) => {
    const center = geom.centers[index] ?? [CANVAS_W / 2, CANVAS_H / 2]
    return {
      id: activity.id,
      title: activity.title,
      cx: center[0],
      cy: center[1],
      r: geom.radius,
      strokeClass: CIRCLE_STROKE_CLASSES[index % CIRCLE_STROKE_CLASSES.length],
      dash: CIRCLE_DASH[index % CIRCLE_DASH.length],
      label: circleLabelPoint(count, index, activity.title),
    }
  })
})

interface PlacedRegion {
  key: string
  x: number
  y: number
  width: number
  height: number
  lines: string[]
  selected: boolean
  ariaLabel: string
}

/** ชื่อเล่นของภูมิภาค เรียงตามเลขที่ — ลำดับเดียวกับรายการภูมิภาคด้านล่าง */
function pillNames(region: CompareRegion): string[] {
  return region.members
    .slice()
    .sort((a, b) => a.student_no - b.student_no || a.student_id - b.student_id)
    .map(nicknameOf)
}

const selectedSet = computed(() => new Set(props.selectedKeys))

/** ภูมิภาคที่วาดได้ (มี anchor) — กรองตรงนี้ ไม่ใช้ `v-if` คู่กับ `v-for` บน element เดียว */
const diagramRegions = computed<PlacedRegion[]>(() => {
  if (!geometry.value) return []
  const count = sortedActivities.value.length
  const sortedIds = sortedActivities.value.map((activity) => activity.id)
  const selected = selectedSet.value

  const placed: PlacedRegion[] = []
  for (const region of props.regions) {
    const anchor = regionAnchor(count, regionMask(region.activity_ids, sortedIds))
    if (!anchor) continue

    const names = pillNames(region)
    const layout = layoutPill(names)
    const membership = regionMembershipLabel(region, sortedActivities.value)
    // ชื่อครบทุกคนใน tooltip/aria — ป้ายมีที่จำกัดแต่ข้อมูลต้องไม่หาย (skills.md:679)
    const everyone = names.join(', ') || 'ไม่มีผู้เข้าร่วม'
    placed.push({
      key: region.key,
      x: anchor[0],
      y: anchor[1],
      width: layout.width,
      height: layout.height,
      lines: layout.lines,
      selected: selected.has(region.key),
      ariaLabel: `${membership} — ${region.members.length} คน: ${everyone}${
        selected.has(region.key) ? ' (เลือกอยู่)' : ''
      }`,
    })
  }
  return placed
})

/** ภูมิภาคที่ไม่มีตำแหน่งบนแผนภาพ — ต้องบอกผู้ใช้ ไม่ใช่เงียบหาย (skills.md:679) */
const unplacedCount = computed(
  () => props.regions.length - diagramRegions.value.length,
)

function toggle(key: string): void {
  emit('toggle', key)
}
</script>

<template>
  <!--
    📱 กรอบเลื่อนแนวนอน: แผนภาพล็อกความกว้างขั้นต่ำ 34rem (≈544px) ⇒ ตัวอักษร 11px
       ย่อเหลือ ~9.3px ยังอ่านออก · จอกว้างพอ (≥ md) ก็ไม่ต้องเลื่อน `min-w-0` คืนค่า
    ⚠️ ข้อความเตือนภูมิภาคที่วาดไม่ได้ อยู่นอกกรอบเลื่อน — ไม่งั้นต้องเลื่อนอ่านทั้งประโยค
  -->
  <div class="w-full">
    <div class="w-full overflow-x-auto">
      <svg
        v-if="geometry"
        :viewBox="`0 0 ${CANVAS_W} ${CANVAS_H}`"
        class="h-auto w-full min-w-[34rem] md:min-w-0"
        role="group"
        aria-label="แผนภาพเวนของกิจกรรมที่เลือก"
      >
        <!-- วงกลมกิจกรรม: พื้นจางทับกันแล้วเข้มขึ้นเองตรงส่วนซ้อน -->
        <circle
          v-for="circle in circles"
          :key="`circle-${circle.id}`"
          :cx="circle.cx"
          :cy="circle.cy"
          :r="circle.r"
          fill-opacity="0.5"
          :stroke-width="2"
          :stroke-dasharray="circle.dash"
          :class="[CIRCLE_FILL, circle.strokeClass]"
        />

        <!-- ป้ายชื่อกิจกรรม "ข้างวง" (ช่องทางที่สองนอกจากสี) -->
        <text
          v-for="circle in circles"
          :key="`label-${circle.id}`"
          :x="circle.label.x"
          :y="circle.label.y"
          text-anchor="middle"
          font-size="12"
          class="fill-stone-600 font-medium"
        >
          {{ circle.title }}
        </text>

        <!-- ป้ายภูมิภาค: กดเลือก/ยกเลิกได้ (เมาส์ + คีย์บอร์ด) -->
        <g
          v-for="region in diagramRegions"
          :key="region.key"
          role="button"
          tabindex="0"
          :aria-pressed="region.selected"
          :aria-label="region.ariaLabel"
          class="cursor-pointer focus:outline-none"
          @click="toggle(region.key)"
          @keydown.enter.prevent="toggle(region.key)"
          @keydown.space.prevent="toggle(region.key)"
        >
          <title>{{ region.ariaLabel }}</title>
          <rect
            :x="region.x - region.width / 2"
            :y="region.y - region.height / 2"
            :width="region.width"
            :height="region.height"
            :rx="PILL_R"
            stroke-width="1.5"
            :class="region.selected ? PILL_SELECTED_CLASSES : PILL_IDLE_CLASSES"
          />
          <!-- หนึ่ง `<text>` ต่อหนึ่งบรรทัด — ตัดบรรทัดเองใน `layoutPill`
               (SVG ไม่ตัดบรรทัดให้เอง ถ้าไม่แยก element ข้อความจะล้นออกนอกป้าย) -->
          <text
            v-for="(line, lineIndex) in region.lines"
            :key="`${region.key}-line-${lineIndex}`"
            :x="region.x"
            :y="pillBaselineY(region.y, lineIndex, region.lines.length)"
            text-anchor="middle"
            :font-size="PILL_FONT"
            class="font-semibold"
            :class="region.selected ? PILL_TEXT_SELECTED : PILL_TEXT_IDLE"
          >
            {{ line }}
          </text>
        </g>
      </svg>
    </div>

    <p v-if="unplacedCount > 0" class="mt-2 text-xs text-stone-500">
      มี {{ unplacedCount }} ภูมิภาคที่แสดงบนแผนภาพไม่ได้ — ดูรายละเอียดได้ในรายการภูมิภาคด้านล่าง
    </p>
  </div>
</template>
