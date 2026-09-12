<script setup lang="ts">
/**
 * 📝 ExtraInfoRows — ตัวแก้ "ข้อมูลเพิ่มเติม" แบบ User-Friendly (หัวข้อ + ค่า)
 * ใช้ร่วมทั้งข้อมูลเพิ่มเติมของกิจกรรม (ActivityForm) และของนักเรียน (ParticipantInfoModal)
 * - Row = หัวข้อ input + ค่า input + ปุ่มลบ
 * - ปุ่ม "เพิ่มข้อมูล" + chips quick-add (กดแล้วเพิ่มแถวที่เติมหัวข้อให้อัตโนมัติ)
 * Presentational — emit update:rows ให้ parent เป็นคนเก็บ state
 *
 * 🌟 readOnly: แสดงเป็น text (หัวข้อ : ค่า) ไม่ให้แก้ไข
 */
import type { CustomFieldEntry } from '@/constants/activityFields'

const props = defineProps<{
  rows: CustomFieldEntry[]
  quickAdd?: Array<{ label: string; key: string; placeholder: string }>
  /** จำกัดจำนวนบรรทัด (placeholder ของช่องค่า) */
  compact?: boolean
  placeholder?: string
  /** 🌟 โหมดแสดงผลอย่างเดียว — ไม่มี input/ปุ่มเพิ่ม/ลบ */
  readOnly?: boolean
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
    <!-- 🌟 readOnly: แสดงเป็น text (หัวข้อ : ค่า) -->
    <template v-if="readOnly">
      <div
        v-if="rows.length === 0"
        class="rounded-xl border border-dashed border-stone-200 bg-stone-50/60 py-5 text-center text-xs text-stone-400"
      >
        ไม่มีข้อมูลเพิ่มเติม
      </div>
      <div v-else class="flex flex-col gap-2">
        <div
          v-for="(row, index) in rows"
          :key="index"
          class="flex flex-col gap-x-2 gap-y-0.5 rounded-xl border border-stone-200 bg-stone-50/60 px-3 py-2 text-sm sm:flex-row sm:items-baseline"
        >
          <span v-if="row.label" class="shrink-0 text-xs font-bold text-brand-700">{{ row.label }}:</span>
          <span class="min-w-0 break-words text-stone-600">{{ row.value }}</span>
        </div>
      </div>
    </template>

    <!-- 🔧 โหมดแก้ไข -->
    <template v-else>
      <!-- Quick-add chips -->
      <div v-if="quickAdd && quickAdd.length > 0" class="mb-3 flex flex-wrap gap-2">
        <button
          v-for="q in quickAdd"
          :key="q.key"
          type="button"
          @click="addRow({ label: q.label, value: '' })"
          class="chip min-h-11 bg-brand-50 px-3.5 text-xs text-brand-700 transition-colors hover:bg-brand-100 active:scale-[0.97]"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i> {{ q.label }}
        </button>
      </div>

      <!-- Rows -->
      <div
        v-if="rows.length === 0"
        class="rounded-xl border border-dashed border-stone-200 bg-stone-50/60 py-5 text-center text-xs text-stone-400"
      >
        ยังไม่มีข้อมูลเพิ่มเติม — กดปุ่มด้านล่างเพื่อเพิ่ม
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="(row, index) in rows"
          :key="index"
          class="flex items-center gap-2 rounded-xl border border-stone-200 bg-white p-2"
        >
          <div class="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
            <input
              :value="row.label"
              type="text"
              :placeholder="compact ? 'หัวข้อ' : 'หัวข้อ (เช่น อาหารที่แพ้, ไซส์รองเท้า)'"
              aria-label="หัวข้อ"
              @input="(e: Event) => updateRow(index, { label: (e.target as HTMLInputElement).value })"
              class="field min-w-0 flex-1"
            />
            <input
              :value="row.value"
              type="text"
              :placeholder="placeholder || 'ค่า'"
              aria-label="ค่า"
              @input="(e: Event) => updateRow(index, { value: (e.target as HTMLInputElement).value })"
              class="field min-w-0 flex-1"
            />
          </div>
          <button
            type="button"
            @click="removeRow(index)"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-red-50 hover:text-red-600 sm:h-9 sm:w-9"
            title="ลบข้อมูลนี้"
            aria-label="ลบข้อมูลนี้"
          >
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>
      </div>

      <!-- เพิ่มข้อมูล -->
      <button
        type="button"
        @click="addRow()"
        class="btn-ghost-ui mt-3 w-full sm:w-auto"
      >
        <i class="bi bi-plus-lg" aria-hidden="true"></i> เพิ่มข้อมูล
      </button>
    </template>
  </div>
</template>
