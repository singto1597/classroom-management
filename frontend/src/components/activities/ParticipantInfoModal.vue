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
        class="fixed inset-0 z-[70] bg-slate-900/40 backdrop-blur-sm flex items-end md:items-center justify-center p-0 md:p-4"
        @click.self="emit('close')"
      >
        <div
          class="w-full md:max-w-xl bg-white rounded-t-3xl md:rounded-3xl shadow-2xl p-5 md:p-6 max-h-[90dvh] overflow-y-auto overflow-x-hidden"
        >
          <!-- Header -->
          <div class="flex items-center justify-between mb-1">
            <h4 class="text-base font-bold text-slate-800 flex items-center gap-2">
              <i class="bi bi-person-badge text-violet-500"></i>
              ข้อมูลเพิ่มเติม — {{ displayName(item) }}
            </h4>
            <button
              @click="emit('close')"
              class="w-9 h-9 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 flex items-center justify-center"
            >
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <p class="text-xs text-slate-400 mb-5">
            เลขที่ {{ item.student_no }} ·
            {{ readOnly ? 'ดูหน้าที่และข้อมูลของคนนี้' : 'ตั้งค่าหน้าที่และข้อมูลเฉพาะคนนี้' }}
          </p>

          <!-- หน้าที่ -->
          <div class="mb-5">
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block flex items-center gap-1.5"
            >
              <i class="bi bi-diagram-3 text-violet-500"></i> หน้าที่/ตำแหน่ง
            </label>
            <!-- readOnly: แสดงเป็น text -->
            <template v-if="readOnly">
              <div
                v-if="!dutyPosition && !dutyNote"
                class="text-sm text-slate-400 bg-slate-50 rounded-xl px-3 py-2.5 border border-slate-100"
              >
                — ไม่มีหน้าที่ —
              </div>
              <div v-else class="flex flex-wrap gap-1.5">
                <span
                  v-if="dutyPosition"
                  class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-bold bg-violet-50 text-violet-700 border border-violet-100"
                >
                  <i class="bi bi-diagram-3 text-[10px]"></i> {{ dutyPosition }}
                </span>
                <span
                  v-if="dutyNote"
                  class="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-50 text-slate-500 border border-slate-100"
                >
                  {{ dutyNote }}
                </span>
              </div>
            </template>
            <!-- mode แก้ไข: select + input -->
            <div v-else class="flex flex-col sm:flex-row gap-2">
              <select
                v-model="dutyPosition"
                :disabled="!canManage"
                class="flex-1 min-w-0 px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
              >
                <option value="">— ไม่มีหน้าที่ —</option>
                <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
              </select>
              <input
                v-model="dutyNote"
                type="text"
                placeholder="หมายเหตุ (เพิ่มเติม)"
                :disabled="!canManage"
                class="flex-1 min-w-0 px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 disabled:opacity-50"
              />
            </div>
          </div>

          <!-- Type B ข้อมูลที่จัดเก็บ -->
          <div v-if="typeBFields.length > 0" class="mb-5">
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block flex items-center gap-1.5"
            >
              <i class="bi bi-list-check text-violet-500"></i> ข้อมูลที่จัดเก็บของกิจกรรมนี้
            </label>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div v-for="field in typeBFields" :key="field.key">
                <label class="text-[11px] font-bold text-slate-400 mb-1 block">{{
                  field.label
                }}</label>
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
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block flex items-center gap-1.5"
            >
              <i class="bi bi-puzzle text-violet-500"></i> ฟิลด์เพิ่มเติมของกิจกรรมนี้
            </label>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div v-for="field in dynamicFields" :key="field.key">
                <label class="text-[11px] font-bold text-slate-400 mb-1 block">{{
                  field.label
                }}</label>
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
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block flex items-center gap-1.5"
            >
              <i class="bi bi-asterisk text-violet-500"></i> ข้อมูลเพิ่มเติมเฉพาะคนนี้
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
            <label
              class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 block flex items-center gap-1.5"
            >
              <i class="bi bi-lock-fill text-violet-500"></i> จากโปรไฟล์ส่วนตัว (อ่านอย่างเดียว)
            </label>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div
                v-for="field in typeAFields"
                :key="field.key"
                class="bg-slate-50 rounded-xl px-3 py-2 flex items-center justify-between gap-2"
              >
                <span class="text-[11px] font-semibold text-slate-500">{{ field.label }}</span>
                <span class="text-xs font-bold text-slate-700">{{
                  String(profileValue(field) ?? '—')
                }}</span>
              </div>
            </div>
            <p class="text-[11px] text-slate-400 mt-1.5">
              🔒 ข้อมูลนี้อัปเดตได้ที่หน้าโปรไฟล์ของนักเรียน ไม่ถูกบันทึกลงกิจกรรมนี้
            </p>
          </div>

          <!-- Actions -->
          <div class="flex justify-end gap-3 mt-2">
            <button
              @click="emit('close')"
              class="px-5 py-2.5 text-sm font-bold text-slate-500 hover:bg-slate-100 rounded-xl transition-colors"
            >
              ปิด
            </button>
            <button
              v-if="canManage && !readOnly"
              @click="handleSave"
              class="px-6 py-2.5 text-sm font-bold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center gap-1.5"
            >
              <i class="bi bi-check-lg"></i> บันทึก
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
