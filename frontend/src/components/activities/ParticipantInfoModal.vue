<script setup lang="ts">
/**
 * 📋 ParticipantInfoModal — modal ข้อมูลเพิ่มเติมของนักเรียน 1 คน
 * แบ่งส่วน: หน้าที่ / ข้อมูลที่จัดเก็บ (Type B + custom_fields) / ข้อมูลจากโปรไฟล์ (Type A 🔒)
 * Presentational — parent เป็นคนยิง API ตอนกดบันทึก
 */
import { ref, watch } from 'vue'
import {
  splitDutyRole,
  joinDutyRole,
  type ActivityField,
  type CustomFieldEntry,
} from '@/constants/activityFields'
import ActivityFieldControl from '@/components/activities/ActivityFieldControl.vue'
import ExtraInfoRows from '@/components/activities/ExtraInfoRows.vue'
import { displayName } from '@/utils/name'
import type { RosterItem } from '@/types/activity'

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
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open && item"
        class="fixed inset-0 z-[70] flex items-end justify-center bg-stone-900/40 p-3 md:items-center md:p-4"
        @click.self="emit('close')"
      >
        <div
          class="max-h-[85vh] w-full overflow-y-auto overscroll-contain rounded-2xl border border-stone-200 bg-white p-5 sm:p-6 md:max-w-xl"
        >
          <!-- Header -->
          <div class="mb-4 flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h4 class="flex items-center gap-2 font-display text-base font-bold text-stone-900">
                <i class="bi bi-person-badge shrink-0 text-brand-700" aria-hidden="true"></i>
                <span class="min-w-0 truncate">ข้อมูลเพิ่มเติม — {{ displayName(item) }}</span>
              </h4>
              <p class="mt-1 text-xs leading-relaxed text-stone-400">
                เลขที่ <span class="num">{{ item.student_no }}</span> ·
                {{ readOnly ? 'ดูหน้าที่และข้อมูลของคนนี้' : 'ตั้งค่าหน้าที่และข้อมูลเฉพาะคนนี้' }}
              </p>
            </div>
            <button
              type="button"
              class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
              aria-label="ปิดหน้าต่าง"
              @click="emit('close')"
            >
              <i class="bi bi-x-lg" aria-hidden="true"></i>
            </button>
          </div>

          <!-- หน้าที่ -->
          <div class="mb-5">
            <label class="field-label flex items-center gap-1.5">
              <i class="bi bi-diagram-3 text-stone-400" aria-hidden="true"></i> หน้าที่/ตำแหน่ง
            </label>
            <!-- readOnly: แสดงเป็น text -->
            <template v-if="readOnly">
              <div
                v-if="!dutyPosition && !dutyNote"
                class="rounded-xl border border-stone-200 bg-stone-50/60 px-3 py-2.5 text-sm text-stone-400"
              >
                — ไม่มีหน้าที่ —
              </div>
              <div v-else class="flex flex-wrap gap-1.5">
                <span v-if="dutyPosition" class="chip bg-brand-50 text-brand-700">
                  <i class="bi bi-diagram-3" aria-hidden="true"></i> {{ dutyPosition }}
                </span>
                <span v-if="dutyNote" class="chip bg-stone-100 text-stone-600">
                  {{ dutyNote }}
                </span>
              </div>
            </template>
            <!-- mode แก้ไข: select + input -->
            <div v-else class="flex flex-col gap-2 sm:flex-row">
              <select v-model="dutyPosition" :disabled="!canManage" class="field min-w-0 flex-1">
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
          <div v-if="typeBFields.length > 0" class="mb-5">
            <label class="field-label flex items-center gap-1.5">
              <i class="bi bi-list-check text-stone-400" aria-hidden="true"></i> ข้อมูลที่จัดเก็บของกิจกรรมนี้
            </label>
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

          <!-- 🌟 Dynamic Fields (ฟิลด์เพิ่มเติมของกิจกรรมนี้) -->
          <div v-if="dynamicFields && dynamicFields.length > 0" class="mb-5">
            <label class="field-label flex items-center gap-1.5">
              <i class="bi bi-puzzle text-stone-400" aria-hidden="true"></i> ฟิลด์เพิ่มเติมของกิจกรรมนี้
            </label>
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
          <div class="mb-5">
            <label class="field-label flex items-center gap-1.5">
              <i class="bi bi-asterisk text-stone-400" aria-hidden="true"></i> ข้อมูลเพิ่มเติมเฉพาะคนนี้
            </label>
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
          <div v-if="typeAFields.length > 0" class="mb-5">
            <label class="field-label flex items-center gap-1.5">
              <i class="bi bi-lock-fill text-stone-400" aria-hidden="true"></i> จากโปรไฟล์ส่วนตัว (อ่านอย่างเดียว)
            </label>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <div
                v-for="field in typeAFields"
                :key="field.key"
                class="flex items-center justify-between gap-2 rounded-xl border border-stone-200 bg-stone-50/60 px-3 py-2"
              >
                <span class="shrink-0 text-[11px] font-semibold text-stone-500">{{ field.label }}</span>
                <span class="min-w-0 truncate text-xs font-bold text-stone-700">{{
                  String(profileValue(field) ?? '—')
                }}</span>
              </div>
            </div>
            <p class="mt-1.5 text-[11px] leading-relaxed text-stone-400">
              🔒 ข้อมูลนี้อัปเดตได้ที่หน้าโปรไฟล์ของนักเรียน ไม่ถูกบันทึกลงกิจกรรมนี้
            </p>
          </div>

          <!-- Actions -->
          <div
            class="mt-2 flex flex-col-reverse gap-2 border-t border-stone-100 pt-4 sm:flex-row sm:justify-end"
          >
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
