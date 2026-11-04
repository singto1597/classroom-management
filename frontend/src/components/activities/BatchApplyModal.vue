<script setup lang="ts">
/**
 * 🎯 BatchApplyModal — ตั้งค่าแบบกลุ่ม (คลุมดำ) ให้ผู้เข้าร่วมที่ถูกติ๊กพร้อมกัน
 * - หน้าที่/ตำแหน่ง (role_detail) ตั้งเป็นชุดได้ + เตือนว่าจะแทนที่หน้าที่เดิมทั้งหมด
 * - ฟิลด์ Type B (รถบัส/ห้องพัก ฯลฯ) ตามที่เลือกใน Required Data
 * - 🌟 ขยาย (ManageActivity): role_type / status / earned_hours / dynamic fields (df_<n>)
 * Presentational — parent เป็นคนยิง API / จัดการ local draft
 */
import { ref, watch } from 'vue'
import type { ActivityField } from '@/constants/activityFields'
import ActivityFieldControl from '@/components/activities/ActivityFieldControl.vue'
import AppSheet from '@/components/ui/AppSheet.vue'

const props = defineProps<{
  open: boolean
  positions: string[]
  typeBFields: ActivityField[]
  count: number
  /** 🌟 แสดงส่วน role_type (participant/staff/leader) — ใช้หน้า ManageActivity */
  showRoleType?: boolean
  /** 🌟 แสดงส่วน status (confirmed/cancelled/attended) — ใช้หน้า ManageActivity */
  showStatus?: boolean
  /** 🌟 แสดงส่วน earned_hours — ใช้หน้า ManageActivity */
  showEarnedHours?: boolean
  /** 🌟 Dynamic Fields (df_<n>) — render เป็น ActivityFieldControl ในส่วน "ฟิลด์เพิ่มเติม" */
  dynamicFields?: ActivityField[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', payload: {
    dutyPosition: string
    typeB: Record<string, unknown>
    roleType: string
    status: string
    earnedHours: string
  }): void
}>()

const dutyPosition = ref('')
const typeBValues = ref<Record<string, unknown>>({})
const roleType = ref('')
const status = ref('')
const earnedHours = ref('')

watch(
  () => props.open,
  (open) => {
    if (open) {
      dutyPosition.value = ''
      typeBValues.value = {}
      roleType.value = ''
      status.value = ''
      earnedHours.value = ''
    }
  },
)

const ROLE_TYPE_OPTIONS = [
  { value: 'participant', label: 'ผู้เข้าร่วม' },
  { value: 'staff', label: 'ทีมงาน' },
  { value: 'leader', label: 'หัวหน้ากลุ่ม' },
]

const STATUS_OPTIONS = [
  { value: 'confirmed', label: 'ยืนยันแล้ว' },
  { value: 'cancelled', label: 'ยกเลิก' },
  { value: 'attended', label: 'มาแล้ว' },
]

const hasSomethingToSet = () => {
  return (
    dutyPosition.value !== '' ||
    roleType.value !== '' ||
    status.value !== '' ||
    earnedHours.value !== '' ||
    Object.values(typeBValues.value).some((v) => v !== '' && v !== null && v !== undefined)
  )
}

function handleApply() {
  if (!hasSomethingToSet()) return
  const filled: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(typeBValues.value)) {
    if (v !== '' && v !== null && v !== undefined) filled[k] = v
  }
  emit('apply', {
    dutyPosition: dutyPosition.value,
    typeB: filled,
    roleType: roleType.value,
    status: status.value,
    earnedHours: earnedHours.value,
  })
}
</script>

<template>
  <AppSheet
    :open="open"
    label="ตั้งค่าแบบกลุ่ม"
    title="ตั้งค่าแบบกลุ่ม"
    description="ใช้กับคนที่ติ๊กเท่านั้น — คนที่ไม่ได้ติ๊กจะไม่ถูกแตะ"
    size="form"
    @close="emit('close')"
  >
    <!-- หน้าที่/ตำแหน่ง -->
    <div v-if="positions.length > 0" class="mb-4">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-diagram-3 text-ink-3" aria-hidden="true"></i> หน้าที่/ตำแหน่ง
      </div>
      <select v-model="dutyPosition" aria-label="หน้าที่/ตำแหน่ง" class="field">
        <option value="">— ตั้งหน้าที่ทั้งหมด —</option>
        <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
      </select>
      <p
        v-if="dutyPosition"
        class="mt-1.5 flex items-start gap-1 text-xs font-semibold leading-relaxed text-warn-700"
      >
        <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> จะแทนที่หน้าที่เดิมทั้งหมดของ
        {{ count }} คนนี้
      </p>
    </div>

    <!-- role_type / status / earned_hours -->
    <div
      v-if="showRoleType || showStatus || showEarnedHours"
      class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3"
    >
      <div v-if="showRoleType">
        <label class="field-label" for="batch-role">บทบาท</label>
        <select id="batch-role" v-model="roleType" class="field">
          <option value="">— ไม่เปลี่ยน —</option>
          <option v-for="opt in ROLE_TYPE_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>
      <div v-if="showStatus">
        <label class="field-label" for="batch-status">สถานะ</label>
        <select id="batch-status" v-model="status" class="field">
          <option value="">— ไม่เปลี่ยน —</option>
          <option v-for="opt in STATUS_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>
      <div v-if="showEarnedHours">
        <label class="field-label" for="batch-hours">ชั่วโมงจิตอาสา</label>
        <input
          id="batch-hours"
          v-model.number="earnedHours"
          type="number"
          min="0"
          step="0.5"
          placeholder="ไม่เปลี่ยน"
          class="field num"
        />
      </div>
    </div>

    <!-- Dynamic Fields -->
    <div v-if="dynamicFields && dynamicFields.length > 0" class="mb-4">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-puzzle text-ink-3" aria-hidden="true"></i> ฟิลด์เพิ่มเติม
      </div>
      <div class="space-y-3">
        <div v-for="field in dynamicFields" :key="field.key">
          <div class="field-label">{{ field.label }}</div>
          <ActivityFieldControl
            :field="field"
            :aria-label="field.label"
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

    <!-- Type B fields -->
    <div v-if="typeBFields.length > 0">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-list-check text-ink-3" aria-hidden="true"></i> ข้อมูลที่จัดเก็บ
      </div>
      <div class="space-y-3">
        <div v-for="field in typeBFields" :key="field.key">
          <div class="field-label flex items-center gap-1.5">
            <i
              class="bi text-ink-3"
              :class="field.type === 'boolean' ? 'bi-check-circle' : 'bi-pencil'"
              aria-hidden="true"
            ></i>
            {{ field.label }}
          </div>
          <ActivityFieldControl
            :field="field"
            :aria-label="field.label"
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
      v-if="
        positions.length === 0 &&
        typeBFields.length === 0 &&
        !showRoleType &&
        !showStatus &&
        !showEarnedHours &&
        !(dynamicFields && dynamicFields.length > 0)
      "
      class="rounded-control border border-line bg-canvas p-4 text-center text-sm leading-relaxed text-ink-3"
    >
      ยังไม่มีค่าที่ตั้งค่าแบบกลุ่มได้ — เพิ่มตำแหน่ง/หน้าที่ หรือเลือกฟิลด์ในส่วน Required Data ก่อน
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row">
        <button type="button" class="btn-ghost-ui sm:flex-1" @click="emit('close')">ยกเลิก</button>
        <button
          type="button"
          class="btn-primary sm:flex-[2]"
          :disabled="!hasSomethingToSet()"
          @click="handleApply"
        >
          <i class="bi bi-lightning-charge-fill" aria-hidden="true"></i>
          ใช้ค่ากับ {{ count }} คน
        </button>
      </div>
    </template>
  </AppSheet>
</template>
