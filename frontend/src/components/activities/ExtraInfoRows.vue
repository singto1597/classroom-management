<script setup lang="ts">
/**
 * 📝 ExtraInfoRows — ตัวแก้ "ข้อมูลเพิ่มเติม" แบบ User-Friendly (หัวข้อ + ค่า)
 * ใช้ร่วมทั้งข้อมูลเพิ่มเติมของกิจกรรม (ActivityForm) และของนักเรียน (ParticipantInfoModal)
 * - Row = หัวข้อ input + ค่า input + ปุ่มลบ
 * - ปุ่ม "เพิ่มข้อมูล" + chips quick-add (กดแล้วเพิ่มแถวที่เติมหัวข้อให้อัตโนมัติ)
 * Presentational — emit update:rows ให้ parent เป็นคนเก็บ state
 */
import type { CustomFieldEntry } from '@/constants/activityFields'

const props = defineProps<{
  rows: CustomFieldEntry[]
  quickAdd?: Array<{ label: string; key: string; placeholder: string }>
  /** จำกัดจำนวนบรรทัด (placeholder ของช่องค่า) */
  compact?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:rows', rows: CustomFieldEntry[]): void
}>()

function updateRow(index: number, patch: Partial<CustomFieldEntry>) {
  const next = props.rows.map((r, i) => (i === index ? { ...r, ...patch } : r))
  emit('update:rows', next)
}

function addRow(prefilled?: Partial<CustomFieldEntry>) {
  emit('update:rows', [...props.rows, { label: prefilled?.label ?? '', value: '', ...prefilled }])
}

function removeRow(index: number) {
  emit(
    'update:rows',
    props.rows.filter((_, i) => i !== index),
  )
}
</script>

<template>
  <div>
    <!-- Quick-add chips -->
    <div v-if="quickAdd && quickAdd.length > 0" class="flex flex-wrap gap-2 mb-3">
      <button
        v-for="q in quickAdd"
        :key="q.key"
        type="button"
        @click="addRow({ label: q.label, value: '' })"
        class="px-3 py-1.5 rounded-lg text-[11px] font-bold text-violet-600 bg-violet-50 border border-violet-100 hover:bg-violet-100 hover:border-violet-200 transition-colors inline-flex items-center gap-1"
      >
        <i class="bi bi-plus-lg text-[10px]"></i> {{ q.label }}
      </button>
    </div>

    <!-- Rows -->
    <div
      v-if="rows.length === 0"
      class="text-center py-5 text-xs text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200"
    >
      ยังไม่มีข้อมูล — กด <b class="text-violet-500">เพิ่มข้อมูล</b> ด้านล่างเพื่อเริ่ม
    </div>

    <div v-else class="space-y-2.5">
      <div
        v-for="(row, index) in rows"
        :key="index"
        class="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center bg-white rounded-xl border border-slate-100 p-2"
      >
        <input
          :value="row.label"
          type="text"
          :placeholder="compact ? 'หัวข้อ' : 'หัวข้อ (เช่น อาหารที่แพ้, ไซส์รองเท้า)'"
          @input="(e: Event) => updateRow(index, { label: (e.target as HTMLInputElement).value })"
          class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
        />
        <input
          :value="row.value"
          type="text"
          :placeholder="placeholder || 'ค่า'"
          @input="(e: Event) => updateRow(index, { value: (e.target as HTMLInputElement).value })"
          class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
        />
        <button
          type="button"
          @click="removeRow(index)"
          class="w-9 h-9 sm:w-8 sm:h-8 flex-shrink-0 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors flex items-center justify-center"
          title="ลบข้อมูลนี้"
        >
          <i class="bi bi-x-lg"></i>
        </button>
      </div>
    </div>

    <!-- เพิ่มข้อมูล -->
    <button
      type="button"
      @click="addRow()"
      class="mt-3 w-full sm:w-auto px-4 py-2 text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 rounded-xl transition-colors inline-flex items-center justify-center gap-1.5"
    >
      <i class="bi bi-plus-lg"></i> เพิ่มข้อมูล
    </button>
  </div>
</template>
