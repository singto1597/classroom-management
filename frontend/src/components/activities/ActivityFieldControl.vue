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
    class="field"
  />

  <!-- 📄 Dropdown -->
  <select
    v-else-if="field.type === 'dropdown'"
    :value="stringValue"
    :disabled="disabled"
    @change="onSelect"
    class="field"
  >
    <option value="">—</option>
    <option v-for="opt in field.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
  </select>

  <!-- ☑️ Boolean Checkbox — พื้นที่กดสูง ≥44px เพื่อให้แตะง่ายบนมือถือ -->
  <label
    v-else-if="field.type === 'boolean'"
    class="inline-flex min-h-[44px] cursor-pointer select-none items-center gap-2 whitespace-nowrap"
    :class="{ 'pointer-events-none opacity-50': disabled }"
  >
    <input
      type="checkbox"
      :checked="isPaid"
      :disabled="disabled"
      @change="onCheckbox"
      class="h-4 w-4 shrink-0 rounded accent-brand-700"
    />
    <span class="chip" :class="isPaid ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-600'">
      <i class="bi" :class="isPaid ? 'bi-check-circle-fill' : 'bi-clock'" aria-hidden="true"></i>
      {{ isPaid ? 'จ่ายแล้ว' : 'ยังไม่จ่าย' }}
    </span>
  </label>

  <!-- 🕐 Datetime -->
  <input
    v-else-if="field.type === 'datetime'"
    type="datetime-local"
    :value="stringValue"
    :disabled="disabled"
    @input="onInput"
    @change="onDatetime"
    class="field"
  />
</template>
