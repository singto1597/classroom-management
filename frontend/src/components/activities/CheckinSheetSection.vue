<script setup lang="ts">
/**
 * ✅ CheckinSheetSection — แผ่นเช็คชื่อ 1 แผ่น (เช็คขึ้นรถ, เช็คเข้าฐาน ฯลฯ)
 * - หัวการ์ด: ชื่อแผ่น + badge checked/total + ปุ่มขยาย/ย่อ + ลบ
 * - เมื่อขยาย: รายชื่อผู้เข้าร่วมพร้อมปุ่มเช็ค "มาแล้ว/ยังไม่มา" ต่อคน + ปุ่ม "เช็คทั้งหมด"
 * Presentational — parent จัดการ fetch detail และยิง API
 */
import { computed } from 'vue'
import { displayName } from '@/utils/name'
import type { ActivityParticipant, CheckinMark, CheckinSheet } from '@/types/activity'

const props = defineProps<{
  sheet: CheckinSheet
  /** null = ยังไม่ได้โหลด detail; เต็ม = participant + CheckinMark */
  participants: (ActivityParticipant & CheckinMark)[] | null
  loading?: boolean
  expanded: boolean
  canManage?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggleExpand'): void
  (e: 'togglePresent', participantId: number, next: boolean): void
  (e: 'deleteSheet'): void
  (e: 'markAllPresent'): void
}>()

const checkedCount = computed(() => {
  if (props.participants === null) return props.sheet.checked_count
  return props.participants.filter((p) => p.is_present).length
})

const totalCount = computed(() => {
  if (props.participants === null) return props.sheet.total_count
  return props.participants.length
})

function formatDate(value: string | null): string {
  if (!value) return ''
  const d = new Date(value + 'T00:00:00')
  return d.toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' })
}

function actionClass(isPresent: boolean): string {
  return isPresent
    ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
    : 'bg-white text-slate-500 border-slate-200 hover:border-emerald-300 hover:text-emerald-600'
}
</script>

<template>
  <div
    class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden transition-all"
    :class="expanded ? 'ring-1 ring-violet-200' : ''"
  >
    <!-- Header -->
    <div class="flex items-center gap-3 px-4 py-3">
      <button
        type="button"
        @click="emit('toggleExpand')"
        class="flex-1 min-w-0 flex items-center gap-3 text-left"
      >
        <div
          class="w-9 h-9 rounded-xl bg-violet-50 text-violet-600 flex items-center justify-center flex-shrink-0"
        >
          <i class="bi bi-clipboard2-check"></i>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-bold text-slate-800 truncate">{{ sheet.title }}</p>
          <p class="text-[11px] text-slate-400">
            <span v-if="sheet.event_date">{{ formatDate(sheet.event_date) }} · </span>
            ตรวจแล้ว <b class="text-emerald-600">{{ checkedCount }}</b>/{{ totalCount }}
          </p>
        </div>
        <span
          class="text-xs text-slate-400 transition-transform flex-shrink-0"
          :class="expanded ? 'rotate-90' : ''"
        >
          <i class="bi bi-chevron-right"></i>
        </span>
      </button>

      <button
        v-if="canManage"
        type="button"
        @click="emit('deleteSheet')"
        title="ลบแผ่นเช็คชื่อ"
        class="w-9 h-9 rounded-lg flex items-center justify-center text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors flex-shrink-0"
      >
        <i class="bi bi-trash3"></i>
      </button>
    </div>

    <!-- Body (ขยาย) -->
    <div v-if="expanded" class="border-t border-slate-100">
      <div
        v-if="loading"
        class="flex flex-col items-center py-8 gap-3"
      >
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600"></div>
        <p class="text-xs text-slate-400">กำลังโหลดรายชื่อ...</p>
      </div>

      <div v-else-if="participants === null || participants.length === 0" class="text-center py-8 text-slate-400 text-sm">
        ยังไม่มีผู้เข้าร่วมในกิจกรรมนี้
      </div>

      <div v-else class="p-3 space-y-2">
        <div class="flex justify-end mb-1">
          <button
            v-if="canManage && checkedCount < totalCount"
            type="button"
            @click="emit('markAllPresent')"
            class="px-3 py-1.5 text-[11px] font-bold text-emerald-600 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-lg transition-colors inline-flex items-center gap-1"
          >
            <i class="bi bi-check2-all"></i> เช็คทั้งหมดว่า "มาแล้ว"
          </button>
        </div>

        <div
          v-for="p in participants"
          :key="p.id"
          class="flex items-center gap-3 px-3 py-2 rounded-xl border border-slate-100"
          :class="p.is_present ? 'bg-emerald-50/40 border-emerald-100' : 'bg-white'"
        >
          <div
            class="w-8 h-8 rounded-lg bg-slate-50 text-slate-600 flex items-center justify-center font-black text-xs shrink-0 border border-slate-100"
          >
            {{ p.student_no }}
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-bold text-slate-800 truncate">{{ displayName(p) }}</p>
            <p
              v-if="p.checked_at"
              class="text-[10px] text-slate-400"
            >
              🕒 {{ new Date(p.checked_at).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' }) }}
              น.
            </p>
          </div>
          <button
            v-if="canManage"
            type="button"
            :disabled="loading"
            @click="emit('togglePresent', p.id, !p.is_present)"
            class="px-3 py-1.5 min-h-[32px] rounded-lg text-[11px] font-bold border transition-all inline-flex items-center gap-1"
            :class="actionClass(p.is_present)"
          >
            <i class="bi" :class="p.is_present ? 'bi-check-circle-fill' : 'bi-circle'"></i>
            {{ p.is_present ? 'มาแล้ว' : 'ยังไม่มา' }}
          </button>
          <span v-else class="px-3 py-1.5 rounded-lg text-[11px] font-bold" :class="p.is_present ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'">
            {{ p.is_present ? 'มาแล้ว' : 'ยังไม่มา' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
