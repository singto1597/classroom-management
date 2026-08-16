<script setup lang="ts">
/**
 * 👥 ParticipantRosterList — รายชื่อผู้เข้าร่วม/นักเรียนแบบการ์ด (ตามแบบ StudentList.vue)
 * ใช้ร่วมทั้งหน้าแก้ไขกิจกรรม (ActivityForm) และหน้ารายละเอียด (ActivityDetail)
 * - การ์ด rounded-2xl: badge เลขที่ + ชื่อ/status dot/ชื่อเล่น + เลือกหน้าที่ + หมายเหตุ
 * - Search ชื่อ/เลขที่/ชื่อเล่น
 * - Toolbar: ตั้งค่าแบบกลุ่ม (เมื่อมีการติ๊ก) / เลือกทั้งหมด / ล้าง
 * Presentational — parent เป็นคนเก็บ state และยิง API ผ่าน emits
 */
import { ref, computed } from 'vue'
import { splitDutyRole } from '@/constants/activityFields'
import type { RosterItem } from '@/types/activity'

const props = defineProps<{
  items: RosterItem[]
  positions: string[]
  /** ชุด key ที่ถูกติ๊ก — ส่ง Set ใหม่ทุกครั้งเพื่อ trigger reactivity */
  selectedKeys: Set<string | number>
  /** ActivityForm: ต้องติ๊กก่อนถึงจะแก้หน้าที่/ข้อมูลได้ */
  selectable?: boolean
  canManage?: boolean
  /** ActivityDetail: แสดงปุ่มเช็คอิน/ยกเลิก */
  showStatusToggle?: boolean
  /** ActivityDetail: แสดงปุ่มนำออก */
  showRemove?: boolean
  emptyText?: string
}>()

const emit = defineEmits<{
  (e: 'toggleSelect', key: string | number): void
  (e: 'selectAll'): void
  (e: 'clearAll'): void
  (e: 'changeDuty', key: string | number, position: string, note: string): void
  (e: 'openInfo', key: string | number): void
  (e: 'toggleStatus', key: string | number): void
  (e: 'remove', key: string | number): void
  (e: 'batch'): void
}>()

const searchQuery = ref('')

const filteredItems = computed(() => {
  const query = searchQuery.value.toLowerCase().trim()
  if (!query) return props.items
  return props.items.filter((item) => {
    const fullName = `${item.first_name} ${item.last_name}`.toLowerCase()
    const no = String(item.student_no)
    const nickname = (item.nickname || '').toLowerCase()
    return fullName.includes(query) || no.includes(query) || nickname.includes(query)
  })
})

const isSelected = (item: RosterItem) => props.selectedKeys.has(item.key)
const isDisabled = (item: RosterItem) => (props.selectable ?? false) && !isSelected(item)

/** ตำแหน่ง/หมายเหตุ ของ item นี้ (แยกจาก role_detail ด้วย ": ") */
function dutyOf(item: RosterItem): { position: string; note: string } {
  return splitDutyRole(item.role_detail)
}

/** หน้าที่ที่เลือกมีอยู่ในรายการแล้วหรือไม่ (กันข้อมูลหายตอนลบตำแหน่ง) */
function isOrphanedDuty(item: RosterItem): boolean {
  const pos = dutyOf(item).position
  if (!pos) return false
  return !props.positions.includes(pos)
}

const statusLabel = (status: string) => {
  if (status === 'attended') return 'มาแล้ว'
  if (status === 'cancelled') return 'ยกเลิก'
  return 'ยืนยันแล้ว'
}

const statusClass = (status: string) => {
  if (status === 'attended') return 'bg-emerald-50 text-emerald-600 border-emerald-200'
  if (status === 'cancelled') return 'bg-rose-50 text-rose-600 border-rose-200'
  return 'bg-amber-50 text-amber-600 border-amber-200'
}

/** ค่าป้ายสถานะ (dot สี) แบบ StudentList */
const statusDot = (status: string) => {
  if (status === 'attended') return 'bg-emerald-400'
  if (status === 'cancelled') return 'bg-rose-400'
  return 'bg-amber-400'
}

/** เปลี่ยนหน้าที่ (select) ของผู้เข้าร่วมคนนี้ */
function onDutyChange(e: Event, item: RosterItem) {
  emit('changeDuty', item.key, (e.target as HTMLSelectElement).value, dutyOf(item).note)
}

/** เปลี่ยนหมายเหตุหน้าที่ (input) ของผู้เข้าร่วมคนนี้ */
function onDutyNoteChange(e: Event, item: RosterItem) {
  emit('changeDuty', item.key, dutyOf(item).position, (e.target as HTMLInputElement).value)
}
</script>

<template>
  <div>
    <!-- Search + Toolbar -->
    <div class="flex flex-col md:flex-row gap-3 md:items-center justify-between mb-4">
      <div class="relative w-full md:flex-1 md:max-w-xs">
        <span
          class="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400 pointer-events-none"
        >
          <i class="bi bi-search"></i>
        </span>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..."
          class="w-full pl-10 pr-4 py-2.5 text-sm font-medium border border-slate-200 rounded-xl focus:ring-2 focus:ring-violet-500/20 focus:border-violet-300 outline-none transition-all bg-slate-50 focus:bg-white"
        />
      </div>

      <div v-if="canManage !== false" class="flex flex-wrap items-center gap-2">
        <button
          v-if="selectedKeys.size > 0"
          @click="emit('batch')"
          class="px-3.5 py-2 text-xs font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-1.5"
        >
          <i class="bi bi-lightning-charge-fill"></i> ตั้งค่าแบบกลุ่ม ({{ selectedKeys.size }})
        </button>
        <button
          @click="emit('selectAll')"
          class="px-3 py-2 text-xs font-bold text-slate-500 hover:text-violet-600 bg-slate-50 hover:bg-violet-50 rounded-lg transition-colors inline-flex items-center gap-1"
        >
          <i class="bi bi-check-all"></i> เลือกทั้งหมด
        </button>
        <button
          v-if="selectedKeys.size > 0"
          @click="emit('clearAll')"
          class="px-3 py-2 text-xs font-bold text-slate-500 hover:text-rose-600 bg-slate-50 hover:bg-rose-50 rounded-lg transition-colors inline-flex items-center gap-1"
        >
          <i class="bi bi-x-lg"></i> ล้าง
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="filteredItems.length === 0"
      class="text-center py-12 text-slate-400 text-sm bg-slate-50 rounded-2xl border border-dashed border-slate-200"
    >
      {{ emptyText || 'ไม่มีรายชื่อในรายการนี้' }}
    </div>

    <!-- List cards (แบบ StudentList) -->
    <div v-else class="flex flex-col gap-2.5 sm:gap-3">
      <div
        v-for="item in filteredItems"
        :key="item.key"
        class="group relative bg-white rounded-2xl p-3.5 sm:p-4 shadow-sm border border-slate-100 hover:shadow-md hover:border-slate-200 transition-all duration-300"
        :class="[
          isSelected(item) ? 'bg-violet-50/50 border-violet-200' : '',
          isDisabled(item) ? 'opacity-70' : '',
        ]"
      >
        <div class="flex items-center gap-3 sm:gap-4">
          <!-- Checkbox (selectable mode) -->
          <input
            v-if="selectable"
            type="checkbox"
            :checked="isSelected(item)"
            @change="emit('toggleSelect', item.key)"
            class="w-4 h-4 sm:w-5 sm:h-5 rounded accent-violet-600 flex-shrink-0"
          />

          <!-- เลขที่ badge -->
          <div
            class="w-11 h-11 sm:w-12 sm:h-12 rounded-2xl bg-slate-50 text-slate-600 flex items-center justify-center font-black text-base sm:text-lg group-hover:bg-violet-50 group-hover:text-violet-600 transition-colors shrink-0 border border-slate-100"
          >
            {{ item.student_no }}
          </div>

          <!-- ข้อมูลหลัก -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-0.5">
              <span
                class="w-2 h-2 rounded-full flex-shrink-0"
                :class="statusDot(item.status)"
              ></span>
              <h4 class="font-bold text-slate-800 text-sm sm:text-[15px] truncate">
                {{ item.prefix ? item.prefix + ' ' : '' }}{{ item.first_name }} {{ item.last_name }}
              </h4>
            </div>
            <div class="flex items-center gap-2 text-[11px] sm:text-xs text-slate-400">
              <span v-if="item.nickname" class="truncate">{{ item.nickname }}</span>
              <template v-if="item.earned_hours > 0">
                <span class="text-slate-300 hidden sm:inline">•</span>
                <span class="text-emerald-600 font-semibold">⏱️ {{ item.earned_hours }} ชม.</span>
              </template>
            </div>
          </div>

          <!-- ปุ่มข้อมูลเพิ่มเติม -->
          <button
            type="button"
            @click="emit('openInfo', item.key)"
            :disabled="isDisabled(item)"
            class="px-3 py-2 rounded-xl text-[11px] font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 border border-violet-100 hover:border-violet-200 transition-colors inline-flex items-center gap-1.5 shrink-0 disabled:opacity-40 disabled:pointer-events-none"
          >
            <i class="bi bi-info-circle"></i> ข้อมูลเพิ่มเติม
          </button>
        </div>

        <!-- Duty + note (แก้ได้เมื่อจัดการ) -->
        <div class="mt-3 flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <select
            :value="dutyOf(item).position"
            :disabled="isDisabled(item) || canManage === false"
            @change="(e: Event) => onDutyChange(e, item)"
            class="flex-1 min-w-0 px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
          >
            <option value="">— ไม่มีหน้าที่ —</option>
            <option
              v-if="isOrphanedDuty(item) && dutyOf(item).position"
              :value="dutyOf(item).position"
            >
              {{ dutyOf(item).position }} (ถูกลบแล้ว)
            </option>
            <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
          </select>
          <input
            :value="dutyOf(item).note"
            type="text"
            placeholder="หมายเหตุ (เพิ่มเติม)"
            :disabled="isDisabled(item) || canManage === false"
            @change="(e: Event) => onDutyNoteChange(e, item)"
            class="flex-1 min-w-0 px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
          />
        </div>

        <!-- Detail actions -->
        <div v-if="showStatusToggle || showRemove" class="mt-2.5 flex items-center gap-2">
          <button
            v-if="showStatusToggle"
            type="button"
            @click="emit('toggleStatus', item.key)"
            class="px-2.5 py-1.5 rounded-lg text-[11px] font-bold border transition-all"
            :class="statusClass(item.status)"
          >
            {{ statusLabel(item.status) }}
          </button>
          <button
            v-if="showRemove"
            type="button"
            @click="emit('remove', item.key)"
            class="px-2.5 py-1.5 rounded-lg text-[11px] font-bold text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors inline-flex items-center gap-1"
          >
            <i class="bi bi-trash3"></i> นำออก
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
