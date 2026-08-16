<script setup lang="ts">
/**
 * 🎯 BatchApplyModal — ตั้งค่าแบบกลุ่ม (คลุมดำ) ให้ผู้เข้าร่วมที่ถูกติ๊กพร้อมกัน
 * - หน้าที่/ตำแหน่ง (role_detail) ตั้งเป็นชุดได้ + เตือนว่าจะแทนที่หน้าที่เดิมทั้งหมด
 * - ฟิลด์ Type B (รถบัส/ห้องพัก ฯลฯ) ตามที่เลือกใน Required Data
 * Presentational — parent เป็นคนยิง API / จัดการ local draft
 */
import { ref, watch } from 'vue'
import type { ActivityField } from '@/constants/activityFields'
import ActivityFieldControl from '@/components/activities/ActivityFieldControl.vue'

const props = defineProps<{
  open: boolean
  positions: string[]
  typeBFields: ActivityField[]
  count: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', payload: { dutyPosition: string; typeB: Record<string, unknown> }): void
}>()

const dutyPosition = ref('')
const typeBValues = ref<Record<string, unknown>>({})

watch(
  () => props.open,
  (open) => {
    if (open) {
      dutyPosition.value = ''
      typeBValues.value = {}
    }
  },
)

const hasSomethingToSet = () => {
  return (
    dutyPosition.value !== '' ||
    Object.values(typeBValues.value).some((v) => v !== '' && v !== null && v !== undefined)
  )
}

function handleApply() {
  if (!hasSomethingToSet()) return
  const filled: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(typeBValues.value)) {
    if (v !== '' && v !== null && v !== undefined) filled[k] = v
  }
  emit('apply', { dutyPosition: dutyPosition.value, typeB: filled })
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-[70] bg-slate-900/40 backdrop-blur-sm flex items-end md:items-center justify-center p-0 md:p-4"
        @click.self="emit('close')"
      >
        <div
          class="w-full md:max-w-lg bg-white rounded-t-3xl md:rounded-3xl shadow-2xl p-5 md:p-6 max-h-[90dvh] overflow-y-auto overflow-x-hidden"
        >
          <!-- Header -->
          <div class="flex items-center justify-between mb-1">
            <h4 class="text-base font-bold text-slate-800 flex items-center gap-2">
              <i class="bi bi-lightning-charge-fill text-fuchsia-500"></i>
              ตั้งค่าแบบกลุ่ม
            </h4>
            <button
              @click="emit('close')"
              class="w-9 h-9 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 flex items-center justify-center"
            >
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <p class="text-xs text-slate-400 mb-4">
            ตั้งค่าให้ผู้เข้าร่วม <b class="text-fuchsia-600">{{ count }} คน</b> พร้อมกัน
          </p>

          <!-- หน้าที่/ตำแหน่ง -->
          <div v-if="positions.length > 0" class="mb-5">
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block flex items-center gap-1.5"
            >
              <i class="bi bi-diagram-3 text-fuchsia-500"></i> หน้าที่/ตำแหน่ง
            </label>
            <select
              v-model="dutyPosition"
              class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-fuchsia-500/30 focus:border-fuchsia-400"
            >
              <option value="">— ตั้งหน้าที่ทั้งหมด —</option>
              <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
            </select>
            <p
              v-if="dutyPosition"
              class="text-[11px] text-amber-600 mt-1.5 flex items-center gap-1"
            >
              <i class="bi bi-exclamation-triangle-fill"></i> จะแทนที่หน้าที่เดิมทั้งหมดของ
              {{ count }} คนนี้
            </p>
          </div>

          <!-- Type B fields -->
          <div v-if="typeBFields.length > 0">
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block flex items-center gap-1.5"
            >
              <i class="bi bi-list-check text-fuchsia-500"></i> ข้อมูลที่จัดเก็บ
            </label>
            <div class="space-y-4">
              <div v-for="field in typeBFields" :key="field.key">
                <label
                  class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block flex items-center gap-1.5"
                >
                  <i
                    class="bi"
                    :class="field.type === 'boolean' ? 'bi-check-circle' : 'bi-pencil'"
                  ></i>
                  {{ field.label }}
                </label>
                <ActivityFieldControl
                  :field="field"
                  :model-value="typeBValues[field.key]"
                  @update:model-value="
                    (v: unknown) => {
                      typeBValues[field.key] = v
                    }
                  "
                />
              </div>
            </div>
          </div>

          <div
            v-if="positions.length === 0 && typeBFields.length === 0"
            class="text-sm text-slate-500 bg-slate-50 rounded-xl p-4 text-center"
          >
            ยังไม่มีฟิลด์ที่ตั้งค่าแบบกลุ่มได้ — เพิ่มตำแหน่ง/หน้าที่ หรือเลือกฟิลด์ในส่วน Required
            Data ก่อน
          </div>

          <!-- Actions -->
          <div class="flex justify-end gap-3 mt-6">
            <button
              @click="emit('close')"
              class="px-5 py-2.5 text-sm font-bold text-slate-500 hover:bg-slate-100 rounded-xl transition-colors"
            >
              ยกเลิก
            </button>
            <button
              @click="handleApply"
              :disabled="!hasSomethingToSet()"
              class="px-6 py-2.5 text-sm font-bold text-white bg-fuchsia-600 hover:bg-fuchsia-700 disabled:opacity-50 rounded-xl shadow-lg shadow-fuchsia-600/20 transition-all inline-flex items-center gap-1.5"
            >
              <i class="bi bi-lightning-charge-fill"></i> ใช้ค่ากับ {{ count }} คน
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
