<script setup lang="ts">
/**
 * 🎛️ Field Control — render input/dropdown/checkbox/datetime ตามชนิดของ ActivityField
 * ใช้ร่วมกันทั้ง Smart Participant Table (แก้ในตาราง) และ Batch Apply Modal (DRY)
 */
import { computed } from 'vue'
import type { ActivityField } from '@/constants/activityFields'

const props = defineProps<{
  field: ActivityField
  modelValue: unknown
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: unknown): void
  /** ปล่อยเมื่อค่า "ตกลง" แล้ว (blur / select change / checkbox) — ใช้บันทึกต่อทันที */
  (e: 'change', value: unknown): void
}>()

const stringValue = computed(() =>
  props.modelValue === null || props.modelValue === undefined ? '' : String(props.modelValue),
)

const isPaid = computed(() => props.modelValue === true || props.modelValue === 'true' || props.modelValue === '1')

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
}

function onBlur(e: Event) {
  emit('change', (e.target as HTMLInputElement).value)
}

function onCheckbox(e: Event) {
  const value = (e.target as HTMLInputElement).checked
  emit('update:modelValue', value)
  emit('change', value)
}

function onSelect(e: Event) {
  const value = (e.target as HTMLSelectElement).value
  emit('update:modelValue', value)
  emit('change', value)
}

function onDatetime(e: Event) {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
  emit('change', (e.target as HTMLInputElement).value)
}
</script>

<template>
  <!-- 🔤 Input -->
  <input
    v-if="field.type === 'input'"
    :value="stringValue"
    :placeholder="field.placeholder || ''"
    :disabled="disabled"
    @input="onInput"
    @blur="onBlur"
    class="w-full px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
  />

  <!-- 📄 Dropdown -->
  <select
    v-else-if="field.type === 'dropdown'"
    :value="stringValue"
    :disabled="disabled"
    @change="onSelect"
    class="w-full px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
  >
    <option value="">—</option>
    <option v-for="opt in field.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
  </select>

  <!-- ☑️ Boolean Checkbox -->
  <label
    v-else-if="field.type === 'boolean'"
    class="inline-flex items-center gap-1.5 cursor-pointer select-none whitespace-nowrap"
    :class="{ 'opacity-50 pointer-events-none': disabled }"
  >
    <input
      type="checkbox"
      :checked="isPaid"
      :disabled="disabled"
      @change="onCheckbox"
      class="w-4 h-4 rounded accent-violet-600"
    />
    <span class="text-[11px] font-bold text-slate-500">{{ isPaid ? '✅ จ่ายแล้ว' : '⏳ ยังไม่จ่าย' }}</span>
  </label>

  <!-- 🕐 Datetime -->
  <input
    v-else-if="field.type === 'datetime'"
    type="datetime-local"
    :value="stringValue"
    :disabled="disabled"
    @input="onInput"
    @change="onDatetime"
    class="w-full px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
  />
</template>
