<script setup lang="ts">
/**
 * ✅ CheckinSheetSection — แผ่นเช็คชื่อ 1 แผ่น (เช็คขึ้นรถ, เช็คเข้าฐาน ฯลฯ)
 * - หัวการ์ด: ชื่อแผ่น + badge checked/total + ปุ่มขยาย/ย่อ + ลบ
 * - เมื่อขยาย: รายชื่อผู้เข้าร่วมพร้อมปุ่มเช็ค "มาแล้ว/ยังไม่มา" ต่อคน + ปุ่ม "เช็คทั้งหมด"
 * Presentational — parent จัดการ fetch detail และยิง API
 */
import { computed } from 'vue'
import { displayName } from '@/utils/name'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
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
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : 'bg-white text-stone-500 border-stone-200 hover:border-emerald-300 hover:text-emerald-600'
}
</script>

<template>
  <!-- การ์ดซ้อนใน page-card ของแม่แล้ว → ลดเป็นกล่องด้านในเส้นเดียว ไม่ให้เห็นกรอบซ้อนกรอบ -->
  <div
    class="overflow-hidden rounded-xl border border-stone-200 bg-white transition-colors"
    :class="expanded ? 'ring-1 ring-brand-200' : ''"
  >
    <!-- Header -->
    <div class="flex items-center gap-2 px-3 py-2.5 sm:px-4">
      <button
        type="button"
        :aria-expanded="expanded"
        :aria-label="`${expanded ? 'ย่อ' : 'ขยาย'}แผ่นเช็คชื่อ ${sheet.title}`"
        class="flex min-w-0 flex-1 items-center gap-2.5 py-1 text-left"
        @click="emit('toggleExpand')"
      >
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700"
        >
          <i class="bi bi-clipboard2-check" aria-hidden="true"></i>
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-bold text-stone-900">{{ sheet.title }}</p>
          <p class="mt-0.5 text-xs text-stone-500">
            <span v-if="sheet.event_date">{{ formatDate(sheet.event_date) }} · </span>
            ตรวจแล้ว <b class="num text-emerald-600">{{ checkedCount }}</b>/<span class="num">{{ totalCount }}</span>
          </p>
        </div>
        <span
          class="shrink-0 text-xs text-stone-400 transition-transform"
          :class="expanded ? 'rotate-90' : ''"
          aria-hidden="true"
        >
          <i class="bi bi-chevron-right"></i>
        </span>
      </button>

      <button
        v-if="canManage"
        type="button"
        title="ลบแผ่นเช็คชื่อ"
        aria-label="ลบแผ่นเช็คชื่อ"
        class="btn-danger h-11 w-11 shrink-0 px-0"
        @click="emit('deleteSheet')"
      >
        <i class="bi bi-trash3" aria-hidden="true"></i>
      </button>
    </div>

    <!-- Body (ขยาย) -->
    <div v-if="expanded" class="border-t border-stone-200">
      <div v-if="loading" class="p-3">
        <SkeletonRows :rows="4" height="h-14" />
      </div>

      <!-- โหลดไม่สำเร็จ (parent กลืน error แล้วปล่อย participants = null) — ต้องไม่โกหกว่าว่าง -->
      <div v-else-if="participants === null" class="px-4 py-6 text-center text-sm text-stone-400">
        โหลดรายชื่อไม่สำเร็จ — ลองย่อแล้วกดขยายอีกครั้ง
      </div>

      <div v-else-if="participants.length === 0" class="px-4 py-6 text-center text-sm text-stone-400">
        ยังไม่มีผู้เข้าร่วมในกิจกรรมนี้
      </div>

      <div v-else class="space-y-2 px-3 pb-3 pt-2">
        <div v-if="canManage && checkedCount < totalCount" class="mb-1 flex sm:justify-end">
          <button
            type="button"
            class="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-xs font-bold text-emerald-700 transition-colors hover:bg-emerald-100 sm:w-auto"
            @click="emit('markAllPresent')"
          >
            <i class="bi bi-check2-all" aria-hidden="true"></i> เช็คทั้งหมดว่า "มาแล้ว"
          </button>
        </div>

        <div
          v-for="p in participants"
          :key="p.id"
          class="flex items-center gap-3 rounded-xl border px-3 py-2"
          :class="p.is_present ? 'border-emerald-100 bg-emerald-50/40' : 'border-stone-200 bg-white'"
        >
          <div
            class="num flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-stone-200 bg-stone-50 text-xs font-bold text-stone-600"
          >
            {{ p.student_no }}
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-bold text-stone-900">{{ displayName(p) }}</p>
            <p v-if="p.checked_at" class="mt-0.5 text-xs text-stone-500">
              เช็ค
              {{ new Date(p.checked_at).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' }) }}
              น.
            </p>
          </div>
          <button
            v-if="canManage"
            type="button"
            :disabled="loading"
            class="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-xl border px-3 text-xs font-bold transition-colors active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
            :class="actionClass(p.is_present)"
            @click="emit('togglePresent', p.id, !p.is_present)"
          >
            <i class="bi" :class="p.is_present ? 'bi-check-circle-fill' : 'bi-circle'" aria-hidden="true"></i>
            {{ p.is_present ? 'มาแล้ว' : 'ยังไม่มา' }}
          </button>
          <span
            v-else
            class="chip shrink-0"
            :class="p.is_present ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-600'"
          >
            {{ p.is_present ? 'มาแล้ว' : 'ยังไม่มา' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
