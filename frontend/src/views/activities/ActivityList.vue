<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ActivityService } from '@/services/activity'
import type { Activity } from '@/types/activity'
import { ACTIVITY_STATUS_LABELS } from '@/types/activity'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import RowActionMenu from '@/components/ui/RowActionMenu.vue'
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue'
import Swal from 'sweetalert2'
import { UI_COLOR } from '@/constants/theme'
import { formatThaiDate, relativeThaiDay } from '@/utils/datetime'
import { ACTIVITY_CATEGORIES, activityCategoryLabel } from '@/constants/activityCategories'

const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const canManageActivities = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

const activities = ref<Activity[]>([])
const isLoading = ref(true)
const hasError = ref(false)
const filter = ref<StatusFilter>('all')
// 🏷️ P4.4 — ชิปกรองหมวด (กรองฝั่งจอ เพราะรายการโหลดมาพร้อมกันอยู่แล้ว
// และตัวเลขบนชิปสถานะต้องอิงชุดเต็ม ไม่ใช่ชุดที่ถูกกรองด้วยหมวด)
const categoryFilter = ref<string>('all')

// --- 🔵 เลือกหลายกิจกรรมเพื่อเปรียบเทียบ (Intersection / Union / ลบ) ---
/** เพดานเดียวกับฝั่งเปรียบเทียบ — เกิน 3 แล้วแผนภาพเวนครอบคลุมทุกภูมิภาคไม่ได้ */
const MAX_COMPARE = 3
/** ใช้ Set แล้ว **สร้างใหม่ทุกครั้งที่แก้** (ห้าม `.add()` ตรง ๆ) ให้ reactivity ทำงาน */
const selectedIds = ref<Set<number>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)
const canCompare = computed(() => selectedCount.value >= 2)

const selectedTitles = computed(() => {
  const byId = new Map(activities.value.map((activity) => [activity.id, activity.title]))
  return Array.from(selectedIds.value).map((id) => byId.get(id) ?? `#${id}`)
})

function toggleSelect(activity: Activity) {
  const next = new Set(selectedIds.value)
  if (next.has(activity.id)) {
    next.delete(activity.id)
  } else {
    if (next.size >= MAX_COMPARE) {
      Toast.fire({ icon: 'warning', title: `เปรียบเทียบได้สูงสุด ${MAX_COMPARE} กิจกรรม` })
      return
    }
    next.add(activity.id)
  }
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

function compareSelected() {
  if (!canCompare.value) return
  // ส่งต่อผ่าน query — หน้าเปรียบเทียบรับช่วงต่อได้เองแม้ถูก refresh/แชร์ลิงก์
  router.push({
    name: 'compare-activities',
    query: { ids: Array.from(selectedIds.value).join(',') },
  })
}

/** โทนสีป้ายสถานะ (chip) — คุมโทนตาม Design Contract ไม่ใช้สีฟ้า/ชมพูแบบเดิม */
function statusChip(status: unknown): string {
  const key = typeof status === 'string' ? status : ''
  if (key === 'ongoing') return 'bg-warn-50 text-warn-700'
  if (key === 'completed') return 'bg-ok-50 text-ok-700'
  if (key === 'cancelled') return 'bg-danger-50 text-danger-700'
  return 'bg-brand-50 text-brand-700'
}

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

const fetchData = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    activities.value = await ActivityService.getActivities(currentRoomId)
    // 🧹 ตัดกิจกรรมที่ถูกลบไประหว่างที่ติ๊กอยู่ — ไม่งั้นแถบลอยบอก "เลือกแล้ว 2" แต่พอเข้า
    //    หน้าเปรียบเทียบกลับได้ 404 เพราะ id นั้นไม่มีอยู่จริงแล้ว
    const stillListed = new Set(activities.value.map((activity) => activity.id))
    const kept = new Set(Array.from(selectedIds.value).filter((id) => stillListed.has(id)))
    if (kept.size !== selectedIds.value.size) selectedIds.value = kept
  } catch (error: unknown) {
    hasError.value = true
    const msg = error instanceof Error ? error.message : 'ดึงข้อมูลกิจกรรมไม่สำเร็จ'
    Toast.fire({ icon: 'error', titleText: msg })
  } finally {
    isLoading.value = false
  }
}

const filteredActivities = computed(() => {
  let list = activities.value
  if (filter.value !== 'all') {
    list = list.filter((a) => a.status === filter.value)
  }
  if (categoryFilter.value !== 'all') {
    list = list.filter((a) => a.category === categoryFilter.value)
  }
  return [...list].sort((a, b) => {
    // เรียงตามวันกิจกรรม (ใกล้ก่อน) — ถ้าใกล้แล้วสถานะ upcoming ขึ้นก่อน
    return (
      new Date(a.activity_date + 'T00:00:00').getTime() -
      new Date(b.activity_date + 'T00:00:00').getTime()
    )
  })
})

const categoryCount = computed(() => {
  const counts: Record<string, number> = { all: activities.value.length }
  ACTIVITY_CATEGORIES.forEach((c) => {
    counts[c.value] = 0
  })
  activities.value.forEach((a) => {
    if (typeof a.category !== 'string') return
    const current = counts[a.category]
    if (current !== undefined) counts[a.category] = current + 1
  })
  return counts
})

type StatusFilter = 'all' | 'upcoming' | 'ongoing' | 'completed' | 'cancelled'

const statusCount = computed(() => {
  const counts: Record<StatusFilter, number> = {
    all: activities.value.length,
    upcoming: 0,
    ongoing: 0,
    completed: 0,
    cancelled: 0,
  }
  activities.value.forEach((a) => {
    const key = typeof a.status === 'string' ? (a.status as StatusFilter) : 'upcoming'
    if (key in counts) counts[key] += 1
  })
  return counts
})

// 📍 เอา metadata.tags มาทำ Badge หมวดหมู่
const getTags = (activity: Activity): string[] => {
  const tags = activity.metadata?.tags
  if (Array.isArray(tags)) {
    return tags.map(String).slice(0, 3)
  }
  if (typeof tags === 'string' && tags) {
    return tags
      .split(',')
      .map((t) => t.trim())
      .slice(0, 3)
  }
  return []
}

// 🏷️ ป้ายหมวด — ใช้ป้ายไทยที่ backend แปลมาแล้วก่อน ถ้าไม่มีค่อยแปลงเอง
//    (client เก่าที่คุยกับ backend รุ่นก่อนหน้า จะได้ป้ายว่าง ไม่ใช่ slug ดิบ)
const categoryLabel = (activity: Activity): string | null =>
  activity.category_label ?? activityCategoryLabel(activity.category)

// 🗓️ วันที่ YYYY-MM-DD → ไทย (15 ตุลาคม 2569) + แสดงสถานะวันนี้/พรุ่งนี้
const formatDate = (dateStr: string): string => {
  if (!dateStr) return '-'
  return relativeThaiDay(dateStr) ?? formatThaiDate(dateStr, 'long')
}

const openActivity = (activity: Activity) => {
  router.push(`/activities/${activity.id}`)
}

const deleteActivity = async (activity: Activity) => {
  if (!canManageActivities.value)
    return Swal.fire({
      icon: 'error',
      title: 'ไม่มีสิทธิ์',
      text: 'เฉพาะผู้ดูแลกิจกรรมเท่านั้น',
      confirmButtonColor: UI_COLOR.brand,
    })
  const result = await Swal.fire({
    title: 'ลบกิจกรรมนี้ไหม?',
    text: `"${activity.title}" จะถูกลบ (soft delete) พร้อมผู้เข้าร่วมทั้งหมด`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: UI_COLOR.danger,
    cancelButtonColor: UI_COLOR.neutral,
    confirmButtonText: 'ลบข้อมูล',
    cancelButtonText: 'ยกเลิก',
  })
  if (result.isConfirmed) {
    try {
      await ActivityService.deleteActivity(currentRoomId, activity.id, currentUserName)
      Toast.fire({ icon: 'success', title: '🗑️ ลบกิจกรรมเรียบร้อยแล้ว' })
      await fetchData()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'ไม่สามารถลบกิจกรรมได้'
      Swal.fire({
        icon: 'error',
        title: 'ข้อผิดพลาด',
        text: msg,
        confirmButtonColor: UI_COLOR.brand,
      })
    }
  }
}

// 🔒 มุมขวาของการ์ดเหลือ "ปุ่มเดียวที่ตั้งใจให้กด": ตัวการ์ดเอง (เปิดรายละเอียด)
// การแก้ไข/ลบเป็นงานที่ทำไม่บ่อยและ "ลบ" ทำลายข้อมูล ⇒ ซ่อนในเมนูจุด 3 จุด
// เดิมเป็นไอคอนเปลือย 2 ปุ่มติดกัน ซึ่งอยู่ข้างการ์ดที่กดได้ทั้งใบ — กดพลาดง่ายมาก
const activityMenuItems = (activity: Activity): RowActionItem[] => [
  // มี `to` ⇒ RowActionMenu เรนเดอร์เป็น RouterLink เอง ไม่ต้องดักที่ @select
  { key: 'edit', label: 'แก้ไขกิจกรรม', icon: 'bi-pencil-square', to: `/activities/${activity.id}/edit` },
  { key: 'delete', label: 'ลบกิจกรรม', icon: 'bi-trash3-fill', tone: 'danger' },
]

// ⚠️ ต้องรับ `key` มาด้วยเสมอ — ไอเทมใหม่ที่ไม่มี `to` จะตกมาที่นี่ทันที
const handleActivityAction = (activity: Activity, key: string) => {
  if (key === 'delete') void deleteActivity(activity)
}

onMounted(fetchData)
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="บันทึกกิจกรรม หน้าที่ และชั่วโมงจิตอาสาของห้อง"
    >
      <template #actions>
        <router-link v-if="canManageActivities" to="/activities/create" class="btn-primary">
          <i class="bi bi-plus-lg" aria-hidden="true"></i> สร้างกิจกรรม
        </router-link>
      </template>
    </PageIntro>

    <!-- แถบกรองแบบเส้นใต้บาง (ไม่ใช่ปุ่ม pill ทึบสี) -->
    <nav
      class="-mx-4 flex gap-1 overflow-x-auto overscroll-contain border-b border-stone-200 px-4 sm:mx-0 sm:px-0"
      aria-label="กรองตามสถานะกิจกรรม"
    >
      <button
        v-for="f in ['all', 'upcoming', 'ongoing', 'completed', 'cancelled'] as const"
        :key="f"
        type="button"
        @click="filter = f"
        class="-mb-px flex min-h-11 shrink-0 items-center border-b-2 px-3 py-2 text-sm font-bold transition-colors"
        :class="
          filter === f
            ? 'border-brand-700 text-brand-700'
            : 'border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-900'
        "
      >
        {{ f === 'all' ? 'ทั้งหมด' : ACTIVITY_STATUS_LABELS[f] }}
        <span class="num ms-1 text-[11px] font-bold opacity-60">{{ statusCount[f] }}</span>
      </button>
    </nav>

    <!-- 🏷️ ชิปกรองหมวดกิจกรรม — เลื่อนแนวนอนได้ · "ทั้งหมด" อยู่ซ้ายเสมอ -->
    <nav class="flex gap-2 overflow-x-auto overscroll-contain pb-1" aria-label="กรองตามหมวดกิจกรรม">
      <button
        type="button"
        class="chip min-h-11 shrink-0 border"
        :class="
          categoryFilter === 'all'
            ? 'border-brand bg-brand-tint text-brand'
            : 'border-line bg-surface text-ink-2 hover:border-ink-3/40'
        "
        :aria-pressed="categoryFilter === 'all'"
        @click="categoryFilter = 'all'"
      >
        ทั้งหมด
        <span class="num ms-1 text-[11px] font-bold opacity-60">{{ categoryCount.all }}</span>
      </button>
      <button
        v-for="c in ACTIVITY_CATEGORIES"
        :key="c.value"
        type="button"
        class="chip min-h-11 shrink-0 border"
        :class="
          categoryFilter === c.value
            ? 'border-brand bg-brand-tint text-brand'
            : 'border-line bg-surface text-ink-2 hover:border-ink-3/40'
        "
        :aria-pressed="categoryFilter === c.value"
        @click="categoryFilter = c.value"
      >
        {{ c.label }}
        <span class="num ms-1 text-[11px] font-bold opacity-60">{{ categoryCount[c.value] }}</span>
      </button>
    </nav>

    <SkeletonRows v-if="isLoading" :rows="3" height="h-56" />

    <StateBlock v-else-if="hasError" variant="error" @retry="fetchData" />

    <StateBlock
      v-else-if="filteredActivities.length === 0"
      variant="empty"
      icon="bi-calendar-x"
      :title="
        activities.length === 0
          ? 'ยังไม่มีกิจกรรม'
          : categoryFilter !== 'all'
            ? 'ไม่มีกิจกรรมในหมวดนี้'
            : 'ไม่มีกิจกรรมในสถานะนี้'
      "
      :hint="
        activities.length === 0
          ? 'สร้างกิจกรรมแรกของห้องเพื่อเริ่มบันทึกผู้เข้าร่วมและชั่วโมงจิตอาสา'
          : 'ลองเลือกตัวกรองอื่น หรือสร้างกิจกรรมใหม่'
      "
    >
      <router-link
        v-if="canManageActivities && activities.length === 0"
        to="/activities/create"
        class="btn-primary mt-1.5"
      >
        <i class="bi bi-plus-lg" aria-hidden="true"></i> สร้างกิจกรรมแรก
      </router-link>
      <button
        v-else-if="activities.length > 0"
        type="button"
        class="btn-ghost-ui mt-1.5"
        @click="
          filter = 'all';
          categoryFilter = 'all';
        "
      >
        <i class="bi bi-list-ul" aria-hidden="true"></i> ล้างตัวกรอง
      </button>
    </StateBlock>

    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3">
      <div
        v-for="activity in filteredActivities"
        :key="activity.id"
        @click="openActivity(activity)"
        class="page-card card-hover flex cursor-pointer flex-col p-4 sm:p-5"
        :class="{
          'opacity-70': activity.status === 'cancelled',
          'ring-2 ring-brand-700': selectedIds.has(activity.id),
        }"
      >
        <div class="flex items-start justify-between gap-3">
          <!-- ☑️ ติ๊กเพื่อเปรียบเทียบ — `.stop` กันไม่ให้ไปเปิดหน้ารายละเอียด
               (การ์ดทั้งใบกดได้ การติ๊กจึงต้องหยุดการ bubbling) -->
          <button
            v-if="canManageActivities"
            type="button"
            role="checkbox"
            :aria-checked="selectedIds.has(activity.id)"
            :aria-label="`เลือก ${activity.title} เพื่อเปรียบเทียบ`"
            @click.stop="toggleSelect(activity)"
            class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition-colors active:scale-[0.97]"
            :class="
              selectedIds.has(activity.id)
                ? 'border-brand-700 bg-brand-700 text-white'
                : 'border-stone-300 text-transparent hover:border-brand-400'
            "
          >
            <i class="bi bi-check-lg" aria-hidden="true"></i>
          </button>
          <h2 class="min-w-0 flex-1 truncate font-display text-base font-bold text-stone-900">
            {{ activity.title }}
          </h2>
          <span class="chip shrink-0" :class="statusChip(activity.status)">
            {{
              ACTIVITY_STATUS_LABELS[
                typeof activity.status === 'string' ? activity.status : 'upcoming'
              ] || activity.status
            }}
          </span>
        </div>

        <!-- 🏷️ หมวดกิจกรรม (P4.3) + แท็กอิสระจาก metadata.tags -->
        <div
          v-if="categoryLabel(activity) || getTags(activity).length"
          class="mt-2.5 flex flex-wrap gap-1.5"
        >
          <span
            v-if="categoryLabel(activity)"
            class="chip bg-brand-50 text-brand-700"
          >
            <i class="bi bi-tag" aria-hidden="true"></i>
            {{ categoryLabel(activity) }}
          </span>
          <span
            v-for="tag in getTags(activity)"
            :key="tag"
            class="chip bg-stone-100 text-stone-600"
          >
            #{{ tag }}
          </span>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <span class="chip bg-stone-100 text-stone-600">
            <i class="bi bi-calendar-event" aria-hidden="true"></i>
            <span class="num">{{ formatDate(activity.activity_date) }}</span>
          </span>
          <span v-if="activity.base_hours > 0" class="chip bg-ok-50 text-ok-700">
            <i class="bi bi-clock-history" aria-hidden="true"></i>
            <span class="num">{{ activity.base_hours }}</span> ชม.
          </span>
        </div>

        <p class="mt-3 line-clamp-2 flex-1 text-sm leading-relaxed text-stone-600">
          {{ activity.description || 'ไม่มีรายละเอียด' }}
        </p>

        <div class="mt-3 flex items-center justify-between gap-2 border-t border-stone-100 pt-3">
          <span class="inline-flex items-center gap-1.5 text-xs font-bold text-stone-500">
            <i class="bi bi-people-fill text-brand-700" aria-hidden="true"></i>
            <span class="num">{{ activity.participant_count }}</span> คน
          </span>
          <RowActionMenu
            v-if="canManageActivities"
            :label="`ตัวเลือกจัดการกิจกรรม ${activity.title}`"
            :items="activityMenuItems(activity)"
            @select="handleActivityAction(activity, $event)"
          />
        </div>
      </div>
    </div>

    <div class="flex justify-center pt-2">
      <router-link to="/dashboard" class="btn-ghost-ui">
        <i class="bi bi-house" aria-hidden="true"></i> กลับหน้าหลัก
      </router-link>
    </div>

    <!--
      🔵 แถบเปรียบเทียบติดล่าง — โผล่เมื่อติ๊กอย่างน้อย 1 กิจกรรม
      📌 ใช้ `sticky` (ไม่ใช่ `fixed`) ตามแบบเดียวกับแถบบันทึกของ EditStudent.vue:608
         ⇒ แถบกินพื้นที่ของตัวเองในเนื้อหา ไม่ต้องเผื่อ padding กันการ์ดแถวล่างถูกบัง
      ⚠️ มือถือต้องเผื่อความสูงของแถบเมนูล่าง (`fixed bottom-0 z-40 lg:hidden` ใน MainLayout)
         ไม่งั้นปุ่ม "เปรียบเทียบกิจกรรม" ถูกทับจนกดไม่ได้ · จอ lg ไม่มีแถบล่าง ⇒ กลับมา bottom-6
      🎚️ z-30 = เหนือเนื้อหา แต่ **ใต้** แถบเมนู (z-40) และ drawer (z-50) — เมนูต้องอยู่บนสุดเสมอ
    -->
    <div
      v-if="canManageActivities && selectedCount > 0"
      class="sticky bottom-[calc(env(safe-area-inset-bottom)+6.5rem)] z-30 rounded-2xl border border-brand-200 bg-white/95 p-3 shadow-[0_16px_40px_-16px_rgba(28,25,23,0.35)] backdrop-blur lg:bottom-6"
    >
      <p class="truncate text-xs text-stone-500">
        เลือกแล้ว <span class="num font-bold text-brand-700">{{ selectedCount }}</span> กิจกรรม:
        {{ selectedTitles.join(' + ') }}
      </p>
      <div class="mt-2 flex items-center gap-2">
        <button
          type="button"
          class="btn-primary flex-1 justify-center"
          :disabled="!canCompare"
          @click="compareSelected"
        >
          <i class="bi bi-diagram-3" aria-hidden="true"></i>
          เปรียบเทียบกิจกรรม
        </button>
        <button type="button" class="btn-ghost-ui shrink-0" @click="clearSelection">
          <i class="bi bi-x-lg" aria-hidden="true"></i> ล้าง
        </button>
      </div>
      <p v-if="!canCompare" class="mt-1.5 text-center text-[11px] text-stone-500">
        เลือกอีก 1 กิจกรรมเพื่อเริ่มเปรียบเทียบ
      </p>
    </div>
  </div>
</template>
