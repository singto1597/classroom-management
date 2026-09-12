<script setup lang="ts">
/**
 * 🧩 DynamicFieldManager — สร้าง/ลบฟิลด์เพิ่มเติม (dynamic_fields) ของกิจกรรม
 * def อยู่ที่ activities.metadata.dynamic_fields = [{key: 'df_<n>', label, type, options?}]
 * เมื่อเพิ่มฟิลด์ → ฟิลด์นี้จะปรากฏกับผู้เข้าร่วมทุกคน (ใน modal ข้อมูลเพิ่มเติม / batch)
 * Presentational — parent ยิง PATCH activity metadata และ refetch
 */
import { ref, computed } from 'vue'
import Swal from 'sweetalert2'
import type { DynamicFieldDef, DynamicFieldType } from '@/types/activity'

const props = defineProps<{
  /** รายการ def ปัจจุบัน */
  defs: DynamicFieldDef[]
}>()

const emit = defineEmits<{
  (e: 'update', defs: DynamicFieldDef[]): void
}>()

const TYPE_LABELS: Record<DynamicFieldType, string> = {
  input: 'ข้อความ',
  dropdown: 'ตัวเลือก',
  boolean: 'ใช่/ไม่ใช่',
  datetime: 'เวลา/วันที่',
}

const newLabel = ref('')
const newType = ref<DynamicFieldType>('input')
const newOptionsText = ref('')

const showAddRow = ref(false)

/** คีย์ถัดไป: df_<max+1> — ไม่ชนกับของเดิม */
const nextKey = computed(() => {
  let max = 0
  for (const d of props.defs) {
    const m = /^df_(\d+)$/.exec(d.key)
    if (m && m[1]) {
      const n = parseInt(m[1], 10)
      if (!Number.isNaN(n) && n > max) max = n
    }
  }
  return `df_${max + 1}`
})

const hasDuplicateLabel = computed(() =>
  props.defs.some((d) => d.label.trim().toLowerCase() === newLabel.value.trim().toLowerCase()),
)

function buildOptions(): { value: string; label: string }[] | undefined {
  if (newType.value !== 'dropdown') return undefined
  const opts: { value: string; label: string }[] = []
  for (const line of newOptionsText.value.split(/[\n,]/)) {
    const label = line.trim()
    if (!label) continue
    opts.push({ value: label, label })
  }
  return opts.length > 0 ? opts : undefined
}

function addField() {
  const label = newLabel.value.trim()
  if (!label) {
    Swal.fire('กรอกหัวข้อก่อน', 'ต้องระบุหัวข้อของฟิลด์ที่ต้องการเพิ่ม', 'warning')
    return
  }
  if (hasDuplicateLabel.value) {
    Swal.fire('ซ้ำ', `ฟิลด์ "${label}" มีอยู่แล้ว`, 'warning')
    return
  }
  if (newType.value === 'dropdown' && !buildOptions()) {
    Swal.fire('กรอกตัวเลือกก่อน', 'ฟิลด์แบบตัวเลือกต้องมีตัวเลือกอย่างน้อย 1 ตัว', 'warning')
    return
  }
  const def: DynamicFieldDef = {
    key: nextKey.value,
    label,
    type: newType.value,
    options: buildOptions(),
  }
  emit('update', [...props.defs, def])
  newLabel.value = ''
  newType.value = 'input'
  newOptionsText.value = ''
  showAddRow.value = false
}

function removeField(def: DynamicFieldDef) {
  Swal.fire({
    title: 'ลบฟิลด์นี้ไหม?',
    text: `"${def.label}" จะถูกลบออกจากกิจกรรม — ค่าที่กรอกไว้แล้วในผู้เข้าร่วมจะไม่แสดงอีก`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ลบฟิลด์',
    cancelButtonText: 'ยกเลิก',
  }).then((result) => {
    if (result.isConfirmed) {
      emit(
        'update',
        props.defs.filter((d) => d.key !== def.key),
      )
    }
  })
}
</script>

<template>
  <div>
    <!-- รายการฟิลด์ปัจจุบัน -->
    <div v-if="defs.length > 0" class="mb-4 space-y-2">
      <div
        v-for="def in defs"
        :key="def.key"
        class="flex items-center gap-2 rounded-xl border border-stone-200 bg-white px-3 py-2 transition-colors hover:bg-stone-50"
      >
        <span class="num w-10 shrink-0 text-[11px] font-bold text-stone-400">{{ def.key }}</span>
        <span class="min-w-0 flex-1">
          <span class="block truncate text-xs font-bold text-stone-700">{{ def.label }}</span>
          <span class="mt-0.5 block text-[10px] text-stone-400">{{ TYPE_LABELS[def.type] }}</span>
        </span>
        <button
          type="button"
          @click="removeField(def)"
          title="ลบฟิลด์"
          aria-label="ลบฟิลด์"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-red-50 hover:text-red-600"
        >
          <i class="bi bi-x-lg text-sm" aria-hidden="true"></i>
        </button>
      </div>
    </div>
    <p v-else class="mb-4 text-xs text-stone-400">
      ยังไม่มีฟิลด์เพิ่มเติม — กด "เพิ่มฟิลด์" เพื่อสร้างฟิลด์ที่ใช้กับผู้เข้าร่วมทุกคน
    </p>

    <!-- ปุ่มเพิ่มฟิลด์ -->
    <button v-if="!showAddRow" type="button" class="btn-ghost-ui" @click="showAddRow = true">
      <i class="bi bi-plus-lg" aria-hidden="true"></i> เพิ่มฟิลด์
    </button>

    <!-- แบบฟอร์มเพิ่มฟิลด์ -->
    <div v-else class="space-y-3 rounded-xl border border-stone-200 bg-stone-50/70 p-3">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label class="field-label" for="dfLabel">หัวข้อฟิลด์ *</label>
          <input
            id="dfLabel"
            v-model="newLabel"
            type="text"
            placeholder="เช่น หมายเลขกลุ่ม, รถคันที่ลง"
            class="field"
          />
        </div>
        <div>
          <label class="field-label" for="dfType">ชนิด</label>
          <select id="dfType" v-model="newType" class="field">
            <option v-for="(label, type) in TYPE_LABELS" :key="type" :value="type">
              {{ label }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="newType === 'dropdown'">
        <label class="field-label" for="dfOptions">ตัวเลือก (คั่นด้วย , หรือขึ้นบรรทัดใหม่)</label>
        <input
          id="dfOptions"
          v-model="newOptionsText"
          type="text"
          placeholder="เช่น กลุ่มแดง, กลุ่มน้ำเงิน, กลุ่มเขียว"
          class="field"
        />
      </div>

      <div class="flex flex-col-reverse gap-2 border-t border-stone-200 pt-3 sm:flex-row sm:justify-end">
        <button type="button" class="btn-ghost-ui" @click="showAddRow = false">ยกเลิก</button>
        <button type="button" class="btn-primary" @click="addField">
          <i class="bi bi-check-lg" aria-hidden="true"></i> เพิ่มฟิลด์
        </button>
      </div>
    </div>
  </div>
</template>
