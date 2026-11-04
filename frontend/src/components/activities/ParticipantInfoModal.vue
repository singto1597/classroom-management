<script setup lang="ts">
/**
 * 📋 ParticipantInfoModal — modal ข้อมูลเพิ่มเติมของนักเรียน 1 คน
 * แบ่งส่วน: หน้าที่ / ข้อมูลที่จัดเก็บ (Type B + custom_fields) / ข้อมูลจากโปรไฟล์ (Type A 🔒)
 * Presentational — parent เป็นคนยิง API ตอนกดบันทึก
 */
import { computed, ref, watch } from 'vue'
import {
  splitDutyRole,
  joinDutyRole,
  type ActivityField,
  type CustomFieldEntry,
} from '@/constants/activityFields'
import ActivityFieldControl from '@/components/activities/ActivityFieldControl.vue'
import ExtraInfoRows from '@/components/activities/ExtraInfoRows.vue'
import { displayName } from '@/utils/name'
import AppSheet from '@/components/ui/AppSheet.vue'
import type { RosterItem } from '@/types/activity'

const sheetLabel = computed(
  () => (props.item ? `ข้อมูลเพิ่มเติม — ${displayName(props.item)}` : 'ข้อมูลเพิ่มเติม'),
)

const props = defineProps<{
  open: boolean
  item: RosterItem | null
  typeAFields: ActivityField[]
  typeBFields: ActivityField[]
  positions: string[]
  canManage: boolean
  /** 🌟 โหมดแสดงผลอย่างเดียว — ไม่มีปุ่มบันทึก/แก้ไข (ActivityDetail) */
  readOnly?: boolean
  /** 🌟 Dynamic Fields (df_<n>) — ฟิลด์ที่ผู้จัดการกิจกรรมสร้างเอง ค่าเก็บใน metadata เหมือน Type B */
  dynamicFields?: ActivityField[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (
    e: 'save',
    payload: {
      role_detail: string | null
      metadata: Record<string, unknown>
      customFields: CustomFieldEntry[]
    },
  ): void
}>()

// --- Local draft (copy ตอนเปิด modal) ---
const dutyPosition = ref('')
const dutyNote = ref('')
const typeBValues = ref<Record<string, unknown>>({})
const customFields = ref<CustomFieldEntry[]>([])

function copyFromItem(item: RosterItem | null) {
  const role = splitDutyRole(item?.role_detail ?? '')
  dutyPosition.value = role.position
  dutyNote.value = role.note
  typeBValues.value = { ...item?.metadata }
  const custom = item?.metadata?.custom_fields
  customFields.value = Array.isArray(custom)
    ? custom
        .filter((e): e is CustomFieldEntry => !!e && typeof e === 'object')
        .map((e) => ({ label: String(e.label ?? ''), value: String(e.value ?? '') }))
    : []
}

watch(
  () => props.open,
  (open) => {
    if (open) copyFromItem(props.item)
  },
)

/** ค่า Type A จาก profile (🔒 อ่านอย่างเดียว) */
function profileValue(field: ActivityField): unknown {
  return props.item?.profile?.[field.key]
}

function handleSave() {
  const meta: Record<string, unknown> = { ...typeBValues.value }
  // custom_fields เฉพาะแถวที่กรอกครบ
  const cleaned = customFields.value
    .map((r) => ({ label: r.label.trim(), value: r.value.trim() }))
    .filter((r) => r.label && r.value)
  if (cleaned.length > 0) {
    meta.custom_fields = cleaned
  } else {
    delete meta.custom_fields
  }
  emit('save', {
    role_detail: joinDutyRole(dutyPosition.value, dutyNote.value) || null,
    metadata: meta,
    customFields: cleaned,
  })
}
</script>

<template>
  <AppSheet
    :open="open && !!item"
    :label="sheetLabel"
    :title="sheetLabel"
    :description="item ? `เลขที่ ${item.student_no}` : undefined"
    size="form"
    @close="emit('close')"
  >
    <!-- หน้าที่ -->
    <div class="mb-4">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-diagram-3 shrink-0 text-ink-3" aria-hidden="true"></i> หน้าที่/ตำแหน่ง
      </div>
      <template v-if="readOnly">
        <div
          v-if="!dutyPosition && !dutyNote"
          class="rounded-control border border-line bg-canvas px-3 py-2.5 text-sm text-ink-3"
        >
          — ไม่มีหน้าที่ —
        </div>
        <div v-else class="flex flex-wrap gap-1.5">
          <span v-if="dutyPosition" class="chip bg-brand-50 text-brand-700">
            <i class="bi bi-diagram-3" aria-hidden="true"></i> {{ dutyPosition }}
          </span>
          <span v-if="dutyNote" class="chip bg-canvas text-ink-2">
            {{ dutyNote }}
          </span>
        </div>
      </template>
      <div v-else class="flex flex-col gap-2 sm:flex-row">
        <select
          v-model="dutyPosition"
          :disabled="!canManage"
          class="field min-w-0 flex-1"
          aria-label="หน้าที่/ตำแหน่ง"
        >
          <option value="">— ไม่มีหน้าที่ —</option>
          <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
        </select>
        <input
          v-model="dutyNote"
          type="text"
          placeholder="หมายเหตุ (เพิ่มเติม)"
          :disabled="!canManage"
          class="field min-w-0 flex-1"
        />
      </div>
    </div>

    <!-- Type B ข้อมูลที่จัดเก็บ -->
    <div v-if="typeBFields.length > 0" class="mb-4">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-list-check shrink-0 text-ink-3" aria-hidden="true"></i> ข้อมูลที่จัดเก็บของกิจกรรมนี้
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div v-for="field in typeBFields" :key="field.key">
          <label class="field-label">{{ field.label }}</label>
          <ActivityFieldControl
            :field="field"
            :model-value="typeBValues[field.key]"
            :disabled="!canManage || readOnly"
            @update:model-value="
              (v: unknown) => {
                typeBValues[field.key] = v
              }
            "
          />
        </div>
      </div>
    </div>

    <!-- 🌟 Dynamic Fields -->
    <div v-if="dynamicFields && dynamicFields.length > 0" class="mb-4">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-puzzle shrink-0 text-ink-3" aria-hidden="true"></i> ฟิลด์เพิ่มเติมของกิจกรรมนี้
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div v-for="field in dynamicFields" :key="field.key">
          <label class="field-label">{{ field.label }}</label>
          <ActivityFieldControl
            :field="field"
            :model-value="typeBValues[field.key]"
            :disabled="!canManage || readOnly"
            @update:model-value="
              (v: unknown) => {
                typeBValues[field.key] = v
              }
            "
          />
        </div>
      </div>
    </div>

    <!-- ข้อมูลเพิ่มเติม (หัวข้อ+ค่า) -->
    <div class="mb-4">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-asterisk shrink-0 text-ink-3" aria-hidden="true"></i> ข้อมูลเพิ่มเติมเฉพาะคนนี้
      </div>
      <ExtraInfoRows
        :rows="customFields"
        compact
        :placeholder="'เช่น เบอร์ที่นั่ง, ขนาดเสื้อ, อาหารที่ชอบ'"
        :quick-add="[]"
        :read-only="readOnly"
        @update:rows="
          (rows: CustomFieldEntry[]) => {
            customFields = rows
          }
        "
      />
    </div>

    <!-- Type A (🔒 จากโปรไฟล์) -->
    <div v-if="typeAFields.length > 0">
      <div class="mb-2 flex items-center gap-1.5 border-b border-line pb-1.5 text-sm font-bold text-ink-1">
        <i class="bi bi-lock-fill shrink-0 text-ink-3" aria-hidden="true"></i> จากโปรไฟล์ส่วนตัว (อ่านอย่างเดียว)
      </div>
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div
          v-for="field in typeAFields"
          :key="field.key"
          class="flex items-center justify-between gap-2 rounded-control border border-line bg-canvas px-3 py-2"
        >
          <span class="shrink-0 text-xs font-semibold text-ink-3">{{ field.label }}</span>
          <span
            class="min-w-0 break-words text-end text-xs font-bold leading-snug text-ink-1"
            :title="String(profileValue(field) ?? '—')"
          >
            {{ String(profileValue(field) ?? '—') }}
          </span>
        </div>
      </div>
      <p class="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-ink-3">
        <i class="bi bi-lock-fill shrink-0 text-ink-3" aria-hidden="true"></i>
        <span>ข้อมูลนี้อัปเดตได้ที่หน้าโปรไฟล์ของนักเรียน ไม่ถูกบันทึกลงกิจกรรมนี้</span>
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button type="button" class="btn-ghost-ui" @click="emit('close')">ปิด</button>
        <button
          v-if="canManage && !readOnly"
          type="button"
          class="btn-primary"
          @click="handleSave"
        >
          <i class="bi bi-check-lg" aria-hidden="true"></i> บันทึก
        </button>
      </div>
    </template>
  </AppSheet>
</template>
