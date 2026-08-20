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
    confirmButtonColor: '#e11d48',
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
    <div v-if="defs.length > 0" class="space-y-2 mb-4">
      <div
        v-for="def in defs"
        :key="def.key"
        class="flex items-center gap-2 bg-violet-50/50 border border-violet-100 rounded-xl px-3 py-2"
      >
        <span class="text-[11px] font-black text-violet-400 w-10 flex-shrink-0">{{ def.key }}</span>
        <span class="flex-1 min-w-0">
          <span class="block text-xs font-bold text-slate-700 truncate">{{ def.label }}</span>
          <span class="block text-[10px] text-slate-400">{{ TYPE_LABELS[def.type] }}</span>
        </span>
        <button
          type="button"
          @click="removeField(def)"
          title="ลบฟิลด์"
          class="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors flex-shrink-0"
        >
          <i class="bi bi-x-lg text-sm"></i>
        </button>
      </div>
    </div>
    <p v-else class="text-xs text-slate-400 mb-4">
      ยังไม่มีฟิลด์เพิ่มเติม — กด "เพิ่มฟิลด์" เพื่อสร้างฟิลด์ที่ใช้กับผู้เข้าร่วมทุกคน
    </p>

    <!-- ปุ่มเพิ่มฟิลด์ -->
    <button
      v-if="!showAddRow"
      type="button"
      @click="showAddRow = true"
      class="px-3.5 py-2 text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 border border-violet-200 rounded-xl transition-colors inline-flex items-center gap-1.5"
    >
      <i class="bi bi-plus-lg"></i> เพิ่มฟิลด์
    </button>

    <!-- แบบฟอร์มเพิ่มฟิลด์ -->
    <div v-else class="bg-slate-50 border border-slate-200 rounded-xl p-3 space-y-3">
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label class="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1 block"
            >หัวข้อฟิลด์ *</label
          >
          <input
            v-model="newLabel"
            type="text"
            placeholder="เช่น หมายเลขกลุ่ม, รถคันที่ลง"
            class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
          />
        </div>
        <div>
          <label class="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1 block"
            >ชนิด</label
          >
          <select
            v-model="newType"
            class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
          >
            <option v-for="(label, type) in TYPE_LABELS" :key="type" :value="type">
              {{ label }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="newType === 'dropdown'">
        <label class="text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-1 block"
          >ตัวเลือก (คั่นด้วย , หรือขึ้นบรรทัดใหม่)</label
        >
        <input
          v-model="newOptionsText"
          type="text"
          placeholder="เช่น กลุ่มแดง, กลุ่มน้ำเงิน, กลุ่มเขียว"
          class="w-full px-3 py-2 bg-white border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
        />
      </div>

      <div class="flex justify-end gap-2">
        <button
          type="button"
          @click="showAddRow = false"
          class="px-3 py-2 text-xs font-bold text-slate-500 hover:bg-slate-100 rounded-lg transition-colors"
        >
          ยกเลิก
        </button>
        <button
          type="button"
          @click="addField"
          class="px-4 py-2 text-xs font-bold text-white bg-violet-600 hover:bg-violet-700 rounded-lg shadow-sm transition-all inline-flex items-center gap-1"
        >
          <i class="bi bi-check-lg"></i> เพิ่มฟิลด์
        </button>
      </div>
    </div>
  </div>
</template>
