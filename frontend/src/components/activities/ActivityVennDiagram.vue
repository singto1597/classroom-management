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
 * 📱 มือถือ: แผนภาพถูกซ่อน (`hidden md:block`) — บนจอแคบ วงกลม 640px ย่อจนอ่านชื่อไม่ออก
 *    ตัวหลักคือ "รายการภูมิภาค" ที่ผู้เรียก (CompareActivities) แสดงใต้แผนภาพ
 *    ซึ่งกดเลือกได้เหมือนกันและแสดงชื่อเล่นครบทุกคน
 */
import { computed } from 'vue'

import {
  CANVAS_H,
  CANVAS_W,
  circleGeometry,
  circleLabelPoint,
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

const PILL_H = 22
const PILL_R = 11
const PILL_FONT = 11
/** ความกว้างตัวอักษรไทยเฉลี่ยที่ font-size 11 — ใช้ประมาณความกว้างป้าย (ไม่ต้องวัด DOM) */
const PILL_CHAR_W = 7.4
/** ชื่อเล่นที่แสดงบนป้ายได้สูงสุด — ที่เหลือย่อเป็น `+N` (รายการด้านล่างแสดงครบ) */
const PILL_NAME_LIMIT = 3
/** เพดานความยาวป้าย กันชื่อยาวทะลุออกนอกวง — รายการภูมิภาคด้านล่างมีชื่อเต็ม */
const PILL_LABEL_MAX = 22

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
  label: string
  selected: boolean
  ariaLabel: string
}

/** ข้อความบนป้าย — ชื่อเล่นไม่เกิน 3 ชื่อ แล้ว `+N` */
function pillLabel(region: CompareRegion): string {
  const names = region.members
    .slice()
    .sort((a, b) => a.student_no - b.student_no || a.student_id - b.student_id)
    .map(nicknameOf)
  if (names.length === 0) return '—'
  const shown =
    names.length > PILL_NAME_LIMIT
      ? `${names.slice(0, PILL_NAME_LIMIT).join(', ')} +${names.length - PILL_NAME_LIMIT}`
      : names.join(', ')
  return shown.length > PILL_LABEL_MAX ? `${shown.slice(0, PILL_LABEL_MAX - 1)}…` : shown
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

    const label = pillLabel(region)
    const membership = regionMembershipLabel(region, sortedActivities.value)
    const width = Math.max(58, label.length * PILL_CHAR_W + 20)
    placed.push({
      key: region.key,
      x: anchor[0],
      y: anchor[1],
      width,
      label,
      selected: selected.has(region.key),
      ariaLabel: `${membership} — ${region.members.length} คน${
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
  <div class="w-full">
    <svg
      v-if="geometry"
      :viewBox="`0 0 ${CANVAS_W} ${CANVAS_H}`"
      class="hidden h-auto w-full md:block"
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
          :y="region.y - PILL_H / 2"
          :width="region.width"
          :height="PILL_H"
          :rx="PILL_R"
          stroke-width="1.5"
          :class="region.selected ? PILL_SELECTED_CLASSES : PILL_IDLE_CLASSES"
        />
        <text
          :x="region.x"
          :y="region.y + 4"
          text-anchor="middle"
          :font-size="PILL_FONT"
          class="font-semibold"
          :class="region.selected ? PILL_TEXT_SELECTED : PILL_TEXT_IDLE"
        >
          {{ region.label }}
        </text>
      </g>
    </svg>

    <p v-if="unplacedCount > 0" class="mt-2 text-xs text-stone-500">
      มี {{ unplacedCount }} ภูมิภาคที่แสดงบนแผนภาพไม่ได้ — ดูรายละเอียดได้ในรายการภูมิภาคด้านล่าง
    </p>
  </div>
</template>
