<script setup lang="ts">
/**
 * 🔵 CompareActivities — เทียบ 2–3 กิจกรรม แล้ว export Excel ของภูมิภาคที่เลือก
 *
 * 🎯 ตอบโจทย์ผู้ใช้ 3 ข้อในหน้าเดียว:
 *   1. Intersection / Union / ลบ — "ปุ่มสำเร็จรูป" เป็นแค่ **ทางลัดของการติ๊กภูมิภาค**
 *      ⇒ ในหน้านี้มีสถานะเดียวที่ควบคุมทุกอย่าง คือ `selectedRegionKeys: string[]`
 *      ปุ่มสำเร็จรูปแค่เขียนทับทั้งชุด ไม่ได้เป็นกลไกคนละอัน (ไม่งั้นปุ่มกับตัวเลขจะไม่ตรงกัน)
 *   2. เห็นก่อนตัดสินใจ — แผนภาพเวน + ชื่อเล่นรายภูมิภาค (กดเลือกภูมิภาคได้จากทั้งแผนภาพและรายการ)
 *   3. วันที่ในไฟล์ออกมาเป็นรูปแบบไทย — backend จัดให้แล้ว (read-side) หน้านี้ไม่ต้องทำอะไร
 *
 * 🔴 `selectedRegionKeys` ต้องมีแต่คีย์ที่ **backend ส่งมา** เท่านั้น
 *    ห้ามประกอบคีย์เอง (`ids.join('-')`) — รูปแบบคีย์เป็นสัญญาของ `services/activity/sets.py`
 *    และ backend คำนวณใหม่จาก DB ทุกครั้งที่ export ⇒ คีย์ที่เดาเองจะได้ 400
 *
 * 🔒 สิทธิ์: `compare` เปิดให้สมาชิกห้องทุกคน (require_member) แต่ `export` ต้องมี
 *    `MANAGE_ACTIVITIES` ⇒ คนที่ไม่มีสิทธิ์ดูแผนภาพได้ แต่ไม่เห็นปุ่ม export
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Swal from 'sweetalert2'

import { ActivityService } from '@/services/activity'
import { useAuthStore } from '@/stores/auth'
import { combinedActivityFilename, downloadBlob } from '@/utils/download'
import {
  countUniqueMembers,
  regionMembershipLabel,
  regionNicknames,
  regionsForPreset,
  type RegionPreset,
} from '@/utils/activitySets'
import { createLatestGuard } from '@/utils/latest'
import type { Activity, ActivityCompare, CompareRegion } from '@/types/activity'
import ActivityVennDiagram from '@/components/activities/ActivityVennDiagram.vue'
import RegionMemberNames from '@/components/activities/RegionMemberNames.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'

/** เพดานกิจกรรมที่เปรียบเทียบได้ — เกินนี้แผนภาพเวนไม่ครอบคลุมทุกภูมิภาคทางเรขาคณิต */
const MAX_ACTIVITIES = 3
const MIN_ACTIVITIES = 2

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const canManageActivities = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

// --- รายการกิจกรรมของห้อง (ตัวเลือก) ---
const activities = ref<Activity[]>([])
const isLoadingList = ref(true)
const listError = ref(false)

// --- ผลการเทียบ (ภูมิภาค) ---
const compare = ref<ActivityCompare | null>(null)
const isLoadingCompare = ref(false)
const compareError = ref(false)

const selectedIds = ref<number[]>(readIdsFromQuery())
const selectedRegionKeys = ref<string[]>([])
const includeActivityFields = ref(false)
const isExporting = ref(false)

/** 🔢 ตัวโหลดสองตัวที่ผูกกับ watch คนละจังหวะ ⇒ ต้องมี guard คนละตัว
 *  (ใช้ร่วมกันแล้ว `begin()` ของตัวหนึ่งจะฆ่า token ของอีกตัว) — ดู utils/latest.ts */
const listGuard = createLatestGuard()
const compareGuard = createLatestGuard()

const regions = computed<CompareRegion[]>(() => compare.value?.regions ?? [])
const compareInfo = computed(() => compare.value?.activities ?? [])
const selectedSet = computed(() => new Set(selectedRegionKeys.value))

/**
 * 📋 แถวของรายการภูมิภาค — คำนวณป้ายกำกับและชื่อเล่นไว้ล่วงหน้า
 *
 * 🔴 ชื่อเล่นต้องอยู่ในรูป **รายการแยกชื่อ** ไม่ใช่สตริงที่ `join(', ')` แล้ว
 *    เทมเพลตต้องตัดบรรทัด **ระหว่างชื่อ** ได้ เพื่อให้เห็นชื่อทุกคนครบ
 *    ⇒ ฝั่งเทมเพลตห่อแต่ละชื่อด้วย `whitespace-nowrap` (ชื่อเดียวไม่ถูกตัดกลางคำ)
 *      แล้วคั่นด้วยช่องว่างหลังจุลภาค ซึ่งเป็นจุดตัดบรรทัดธรรมชาติ
 */
const regionRows = computed(() =>
  regions.value.map((region) => ({
    key: region.key,
    membership: regionMembershipLabel(region, compareInfo.value),
    count: region.members.length,
    names: regionNicknames(region),
  })),
)
const selectedMemberCount = computed(() =>
  countUniqueMembers(regions.value, selectedRegionKeys.value),
)
const hasEnoughSelected = computed(() => selectedIds.value.length >= MIN_ACTIVITIES)

/** กิจกรรมที่เลือกได้จาก query (`?ids=3,7`) — กรองค่าขยะทิ้ง ไม่ให้ชิปผีโผล่ */
function readIdsFromQuery(): number[] {
  const raw = route.query.ids
  const text = Array.isArray(raw) ? (raw[0] ?? '') : (raw ?? '')
  const ids = String(text)
    .split(',')
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isInteger(value) && value > 0)
  return [...new Set(ids)].slice(0, MAX_ACTIVITIES)
}

const titleById = computed(() => {
  const map = new Map<number, string>()
  for (const activity of activities.value) map.set(activity.id, activity.title)
  for (const info of compareInfo.value) map.set(info.id, info.title)
  return map
})

const titleOf = (id: number): string => titleById.value.get(id) ?? `#${id}`

/**
 * 🧩 `metadata_keys` ส่งเป็น `[]` โดยเจตนา — ฝั่ง backend `if only_keys:` แปลว่า
 * **ไม่กรอง** ⇒ ทุกฟิลด์ที่แต่ละกิจกรรมประกาศ (required_fields + dynamic_fields) ออกเป็นคอลัมน์
 * ห้ามเปลี่ยนไปส่ง `required_fields` ของกิจกรรม เพราะจะ **ตัด dynamic_fields ทิ้งเงียบ ๆ**
 * (ผู้ใช้สร้างฟิลด์เองไว้แต่ค่าไม่โผล่ในไฟล์ โดยไม่มี error ให้เห็น)
 */
const ACTIVITY_FIELD_KEYS: string[] = []

const fetchActivities = async () => {
  const token = listGuard.begin()
  isLoadingList.value = true
  listError.value = false
  try {
    const rows = await ActivityService.getActivities(currentRoomId)
    if (!listGuard.isCurrent(token)) return
    activities.value = rows
    // 🧹 กิจกรรมที่ติดมาจาก query อาจถูกลบไปแล้ว — ตัดออก ไม่ให้ค้างเป็นชิปที่เทียบไม่ได้ (404)
    const known = new Set(rows.map((row) => row.id))
    selectedIds.value = selectedIds.value.filter((id) => known.has(id))
  } catch (error: unknown) {
    if (!listGuard.isCurrent(token)) return
    listError.value = true
    Toast.fire({
      icon: 'error',
      title: error instanceof Error ? error.message : 'ดึงรายการกิจกรรมไม่สำเร็จ',
    })
  } finally {
    if (listGuard.isCurrent(token)) isLoadingList.value = false
  }
}

const fetchCompare = async () => {
  if (!hasEnoughSelected.value) {
    compare.value = null
    selectedRegionKeys.value = []
    return
  }
  const token = compareGuard.begin()
  isLoadingCompare.value = true
  compareError.value = false
  try {
    const res = await ActivityService.compareActivities(currentRoomId, [...selectedIds.value])
    if (!compareGuard.isCurrent(token)) return
    compare.value = res
    // 🔄 เปลี่ยนกิจกรรม = ภูมิภาคทั้งชุดเปลี่ยน ⇒ คีย์เดิมใช้ไม่ได้ (backend จะตอบ 400)
    //    ตั้งต้นที่ "ทุกภูมิภาค" (= union) เพื่อให้ผู้ใช้เห็นของจริงทันทีแล้วค่อยกดตัดออก
    //    ทางเลือกอื่นคือคงคีย์เดิมไว้ แต่จะเหลือ 0 ภูมิภาคแล้ว export ไม่ได้เลยโดยไม่รู้สาเหตุ
    selectedRegionKeys.value = res.regions.map((region) => region.key)
  } catch (error: unknown) {
    if (!compareGuard.isCurrent(token)) return
    compare.value = null
    selectedRegionKeys.value = []
    compareError.value = true
    Toast.fire({
      icon: 'error',
      title: error instanceof Error ? error.message : 'เปรียบเทียบกิจกรรมไม่สำเร็จ',
    })
  } finally {
    if (compareGuard.isCurrent(token)) isLoadingCompare.value = false
  }
}

// 🔗 ids ต้องสะท้อนใน URL — ครูแชร์ลิงก์ให้กัน หรือกด refresh แล้วได้หน้าเดิม
//   (และเป็นทางเดียวที่สถานะนี้รอดข้ามการ reload)
//
// ⚠️ `watch` ไม่ใช่ `immediate` **โดยเจตนา** — การเรียก `router.replace` ตอน setup
//    คือการนำทางระหว่างที่ยัง mount ไม่เสร็จ จึงเรียกทั้งสองอย่างใน `onMounted` แทน
//    (ผลข้างเคียง: ถ้า `fetchActivities` ตัด id ที่ถูกลบออกจริง จะยิงซ้ำอีกรอบ ซึ่งกันได้ด้วย guard)
watch(selectedIds, (ids) => {
  void router.replace({ query: ids.length ? { ids: ids.join(',') } : {} })
  void fetchCompare()
})

function toggleActivity(id: number): void {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((value) => value !== id)
    return
  }
  if (selectedIds.value.length >= MAX_ACTIVITIES) {
    Toast.fire({
      icon: 'warning',
      title: `เปรียบเทียบได้สูงสุด ${MAX_ACTIVITIES} กิจกรรม`,
    })
    return
  }
  // เรียงตาม id เสมอ — ให้ตรงกับบิตของ mask ฝั่ง backend (ตำแหน่งป้ายบนแผนภาพอ้างค่านี้)
  selectedIds.value = [...selectedIds.value, id].sort((a, b) => a - b)
}

function clearActivities(): void {
  selectedIds.value = []
}

function toggleRegion(key: string): void {
  selectedRegionKeys.value = selectedRegionKeys.value.includes(key)
    ? selectedRegionKeys.value.filter((value) => value !== key)
    : [...selectedRegionKeys.value, key]
}

function selectAllRegions(): void {
  selectedRegionKeys.value = regions.value.map((region) => region.key)
}

interface PresetButton {
  key: string
  label: string
  icon: string
  keys: string[]
  active: boolean
}

const sameKeySet = (a: string[], b: Iterable<string>): boolean => {
  const setB = new Set(b)
  return a.length === setB.size && a.every((key) => setB.has(key))
}

/**
 * ปุ่มสำเร็จรูป — เขียนทับ `selectedRegionKeys` ทั้งชุด
 * `active` กันปัญหา "ป้ายบอกอย่าง ตัวเลขบอกอีกอย่าง": ปุ่มจะสว่างเฉพาะเมื่อชุดที่เลือก
 * **เท่ากันจริง** กับที่ปุ่มนั้นหมายถึง ไม่ใช่แค่ "เพิ่งกดปุ่มนี้มา"
 */
const presets = computed<PresetButton[]>(() => {
  const build = (
    key: string,
    label: string,
    icon: string,
    preset: RegionPreset,
    baseActivityId?: number,
  ): PresetButton => {
    const keys = regionsForPreset(regions.value, preset, [...selectedIds.value], baseActivityId)
    return { key, label, icon, keys, active: sameKeySet(keys, selectedRegionKeys.value) }
  }

  return [
    build('union', 'รวมทั้งหมด', 'bi-collection-fill', 'union'),
    build('intersection', 'ซ้ำทุกกิจกรรม', 'bi-intersect', 'intersection'),
    // "ลบ" ต้องระบุว่าลบจากกิจกรรมไหน ⇒ ปุ่มละกิจกรรม (ผู้ใช้อาจอยากได้ A\B หรือ B\A)
    ...selectedIds.value.map((id) =>
      build(`difference-${id}`, `เฉพาะ ${titleOf(id)}`, 'bi-dash-circle-fill', 'difference', id),
    ),
  ]
})

function applyPreset(preset: PresetButton): void {
  if (preset.keys.length === 0) {
    Toast.fire({
      icon: 'info',
      title: 'ไม่มีภูมิภาคที่ตรงเงื่อนไข — ลองติ๊กภูมิภาคเองบนแผนภาพ',
    })
    return
  }
  selectedRegionKeys.value = [...preset.keys]
}

const exportExcel = async () => {
  if (!canManageActivities.value) {
    void Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะผู้ดูแลกิจกรรมเท่านั้นที่ export ได้',
      confirmButtonColor: '#1d4ed8',
    })
    return
  }
  if (selectedRegionKeys.value.length === 0) {
    void Swal.fire({
      icon: 'warning',
      title: 'ยังไม่ได้เลือกภูมิภาค',
      text: 'เลือกอย่างน้อย 1 ภูมิภาคก่อน export',
      confirmButtonColor: '#1d4ed8',
    })
    return
  }

  isExporting.value = true
  try {
    const blob = await ActivityService.exportCombinedExcel(
      currentRoomId,
      [...selectedIds.value],
      [...selectedRegionKeys.value],
      ACTIVITY_FIELD_KEYS,
      includeActivityFields.value,
      currentUserName,
    )
    // ⚠️ ห้ามเขียน anchor เอง — ต้องผ่าน downloadBlob เพราะ revoke ต้องเลื่อนคาบ
    const titles = selectedIds.value.map(titleOf)
    downloadBlob(blob, combinedActivityFilename(titles))
    Toast.fire({ icon: 'success', title: 'Export Excel เรียบร้อย 📄' })
  } catch (error: unknown) {
    void Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: error instanceof Error ? error.message : 'Export ไม่สำเร็จ',
      confirmButtonColor: '#1d4ed8',
    })
  } finally {
    isExporting.value = false
  }
}

onMounted(() => {
  void fetchActivities()
  // 🔴 ต้องเรียกเอง — หน้านี้เข้าจาก query `?ids=3,7` เป็นปกติ (ปุ่ม "เปรียบเทียบกิจกรรม")
  //    ถ้าพึ่งแต่ `watch` จะไม่ยิงเลยเมื่อ id ที่ส่งมาถูกต้องครบ ⇒ จอค้างที่สถานะ "ว่าง"
  void fetchCompare()
})
</script>

<template>
  <div class="page-wrap space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Activity Comparison"
      title="เปรียบเทียบกิจกรรม"
      description="เลือก 2–3 กิจกรรม ดูว่าใครอยู่ร่วมกันบ้าง แล้ว export เฉพาะภูมิภาคที่ต้องการ"
    >
      <template #actions>
        <router-link to="/activities" class="btn-ghost-ui">
          <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับหน้ากิจกรรม
        </router-link>
      </template>
    </PageHeader>

    <!-- ── เลือกกิจกรรม ─────────────────────────────────────────── -->
    <section class="page-card p-4 sm:p-5">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="font-display text-base font-bold text-stone-900">เลือกกิจกรรม</h2>
        <p class="num text-xs font-bold text-stone-500">
          เลือกแล้ว {{ selectedIds.length }}/{{ MAX_ACTIVITIES }} กิจกรรม
        </p>
      </div>

      <SkeletonRows v-if="isLoadingList" :rows="2" height="h-11" class="mt-3" />

      <StateBlock v-else-if="listError" variant="error" class="mt-3" @retry="fetchActivities" />

      <StateBlock
        v-else-if="activities.length === 0"
        variant="empty"
        icon="bi-calendar-x"
        title="ยังไม่มีกิจกรรมในห้องนี้"
        hint="สร้างกิจกรรมและเพิ่มผู้เข้าร่วมก่อน จึงจะเปรียบเทียบได้"
        class="mt-3"
      />

      <template v-else>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            v-for="activity in activities"
            :key="activity.id"
            type="button"
            class="chip min-h-9 gap-1.5 px-3 transition-colors"
            :class="
              selectedIds.includes(activity.id)
                ? 'bg-brand-700 text-white'
                : 'bg-stone-100 text-stone-700 hover:bg-stone-200'
            "
            :aria-pressed="selectedIds.includes(activity.id)"
            @click="toggleActivity(activity.id)"
          >
            <i
              :class="selectedIds.includes(activity.id) ? 'bi bi-check-circle-fill' : 'bi bi-circle'"
              aria-hidden="true"
            ></i>
            {{ activity.title }}
          </button>
        </div>

        <div v-if="selectedIds.length" class="mt-3 flex items-center justify-between gap-2">
          <p class="min-w-0 truncate text-xs text-stone-500">
            กำลังเปรียบเทียบ: {{ selectedIds.map(titleOf).join(' + ') }}
          </p>
          <button type="button" class="btn-ghost-ui shrink-0" @click="clearActivities">
            <i class="bi bi-x-lg" aria-hidden="true"></i> ล้างที่เลือก
          </button>
        </div>
      </template>
    </section>

    <!-- ── ยังเลือกไม่ครบ 2 กิจกรรม ─────────────────────────────── -->
    <StateBlock
      v-if="!hasEnoughSelected && !isLoadingList && activities.length > 0"
      variant="empty"
      icon="bi-diagram-3"
      :title="selectedIds.length === 0 ? 'ยังไม่ได้เลือกกิจกรรม' : 'เลือกกิจกรรมเพิ่มอีก 1 รายการ'"
      :hint="
        selectedIds.length === 0
          ? 'ติ๊กอย่างน้อย 2 กิจกรรมด้านบน เพื่อดูว่าใครอยู่กิจกรรมไหนบ้าง'
          : 'ต้องมีอย่างน้อย 2 กิจกรรมจึงจะเทียบกันได้ (สูงสุด 3)'
      "
    />

    <template v-else-if="hasEnoughSelected">
      <SkeletonRows v-if="isLoadingCompare" :rows="2" height="h-64" />

      <StateBlock v-else-if="compareError" variant="error" @retry="fetchCompare" />

      <StateBlock
        v-else-if="regions.length === 0"
        variant="empty"
        icon="bi-people"
        title="ไม่มีผู้เข้าร่วมในกิจกรรมที่เลือก"
        hint="กิจกรรมเหล่านี้อาจยังไม่ได้เพิ่มนักเรียน หรือถูกลบผู้เข้าร่วมออกทั้งหมด"
      />

      <template v-else>
        <!-- ── แผนภาพ + ตัวเลือกภูมิภาค ───────────────────────── -->
        <section class="page-card p-4 sm:p-5">
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <h2 class="font-display text-base font-bold text-stone-900">แผนภาพภูมิภาค</h2>
            <p class="num text-xs font-bold text-brand-700">
              เลือกแล้ว {{ selectedRegionKeys.length }}/{{ regions.length }} ภูมิภาค ·
              {{ selectedMemberCount }} คน
            </p>
          </div>

          <!-- 📱 แผนภาพแสดงทุกขนาดจอ — ตัวคอมโพเนนต์คุมความกว้างขั้นต่ำ + เลื่อนแนวนอนเอง
               (ไม่ซ่อนบนมือถืออีกแล้ว) ⇒ ไม่ต้องมี wrapper อะไรตรงนี้ -->
          <ActivityVennDiagram
            class="mt-4"
            :activities="compareInfo"
            :regions="regions"
            :selected-keys="selectedRegionKeys"
            @toggle="toggleRegion"
          />

          <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-stone-100 pt-4">
            <button
              v-for="preset in presets"
              :key="preset.key"
              type="button"
              class="btn-ghost-ui"
              :class="preset.active ? 'border-brand-700 bg-brand-50 text-brand-700' : ''"
              :aria-pressed="preset.active"
              @click="applyPreset(preset)"
            >
              <i :class="`bi ${preset.icon}`" aria-hidden="true"></i> {{ preset.label }}
            </button>
            <button type="button" class="btn-ghost-ui" @click="selectAllRegions">
              <i class="bi bi-check2-square" aria-hidden="true"></i> ทุกภูมิภาค
            </button>
          </div>

          <!-- 📋 รายการภูมิภาค — แสดงชื่อเล่น **ครบทุกคน** (ป้ายบนแผนภาพมีที่จำกัด)
               ห้าม truncate ข้อมูลอ่านอย่างเดียว ⇒ ที่นี่คือแหล่งอ้างอิงจริงของผู้ใช้
               กติกาการตัดบรรทัดอยู่ใน `RegionMemberNames` -->
          <ul class="mt-4 divide-y divide-stone-100 border-t border-stone-100">
            <li v-for="row in regionRows" :key="row.key">
              <label class="flex min-h-11 cursor-pointer items-start gap-3 py-3">
                <input
                  type="checkbox"
                  class="mt-1 h-4 w-4 shrink-0 accent-brand-700"
                  :checked="selectedSet.has(row.key)"
                  @change="toggleRegion(row.key)"
                />
                <span class="min-w-0 flex-1">
                  <span class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span class="text-sm font-bold text-stone-900">{{ row.membership }}</span>
                    <span class="chip bg-brand-50 text-brand-700">
                      <span class="num">{{ row.count }}</span> คน
                    </span>
                  </span>
                  <RegionMemberNames
                    :names="row.names"
                    class="mt-1 block text-sm leading-relaxed text-stone-600"
                  />
                </span>
              </label>
            </li>
          </ul>
        </section>

        <!-- ── Export ──────────────────────────────────────────── -->
        <section class="page-card p-4 sm:p-5">
          <h2 class="font-display text-base font-bold text-stone-900">Export Excel</h2>
          <p class="mt-1 text-sm text-stone-600">
            จะได้รายชื่อ
            <span class="font-bold text-stone-900">{{ selectedMemberCount }} คน</span>
            จาก {{ selectedRegionKeys.length }} ภูมิภาค พร้อมคอลัมน์ติ๊กถูกเทียบทุกกิจกรรม
          </p>

          <label
            v-if="canManageActivities"
            class="mt-3 flex min-h-11 cursor-pointer items-center gap-3"
          >
            <input
              v-model="includeActivityFields"
              type="checkbox"
              class="h-4 w-4 shrink-0 accent-brand-700"
            />
            <span class="text-sm text-stone-700">
              รวมข้อมูลที่เก็บรายคนของแต่ละกิจกรรม (วันที่ หน้าที่ และฟิลด์ที่สร้างเอง)
            </span>
          </label>

          <div class="mt-3">
            <button
              v-if="canManageActivities"
              type="button"
              class="btn-primary"
              :disabled="isExporting || selectedRegionKeys.length === 0"
              @click="exportExcel"
            >
              <i
                :class="isExporting ? 'bi bi-hourglass-split' : 'bi bi-file-earmark-excel'"
                aria-hidden="true"
              ></i>
              {{ isExporting ? 'กำลังสร้างไฟล์...' : 'Export Excel' }}
            </button>
            <p v-else class="text-sm text-stone-500">
              <i class="bi bi-lock" aria-hidden="true"></i>
              ดูแผนภาพได้ทุกคน แต่การ export ต้องมีสิทธิ์จัดการกิจกรรม
            </p>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>
