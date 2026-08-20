<script setup lang="ts">
/**
 * ➕ AddStudentsModal — เลือกนักเรียนในห้องที่ยังไม่ได้เข้าร่วมกิจกรรมนี้ แล้วกดเพิ่มเข้ากลุ่ม
 * Presentational — parent โหลดรายการ available ผ่าน ActivityService.getAvailableStudents
 * และยิง ActivityService.batchAddParticipants ตอนกดยืนยัน
 */
import { ref, computed, watch } from 'vue'
import { displayName } from '@/utils/name'
import type { AvailableStudent } from '@/types/activity'

const props = defineProps<{
  open: boolean
  students: AvailableStudent[]
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'add', studentNos: number[]): void
}>()

const selected = ref<Set<number>>(new Set())
const searchQuery = ref('')

watch(
  () => props.open,
  (open) => {
    if (open) {
      selected.value = new Set()
      searchQuery.value = ''
    }
  },
)

const filtered = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return props.students
  return props.students.filter((s) => {
    const name = `${s.first_name ?? ''} ${s.last_name ?? ''} ${s.first_name_en ?? ''} ${s.last_name_en ?? ''}`.toLowerCase()
    return name.includes(q) || String(s.student_no).includes(q)
  })
})

const isSelected = (no: number) => selected.value.has(no)

function toggle(no: number) {
  const next = new Set(selected.value)
  if (next.has(no)) next.delete(no)
  else next.add(no)
  selected.value = next
}

function selectAll() {
  selected.value = new Set(filtered.value.map((s) => s.student_no))
}

function clearAll() {
  selected.value = new Set()
}

function confirmAdd() {
  if (selected.value.size === 0) return
  emit('add', Array.from(selected.value))
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
              <i class="bi bi-person-plus-fill text-violet-500"></i>
              เพิ่มนักเรียนเข้ากิจกรรม
            </h4>
            <button
              @click="emit('close')"
              class="w-9 h-9 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 flex items-center justify-center"
            >
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
          <p class="text-xs text-slate-400 mb-4">
            นักเรียนในห้องที่ยังไม่ได้เข้าร่วมกิจกรรมนี้ — ติ๊กชื่อแล้วกดเพิ่ม
          </p>

          <!-- Search -->
          <div class="relative mb-3">
            <span
              class="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400 pointer-events-none"
            >
              <i class="bi bi-search"></i>
            </span>
            <input
              v-model="searchQuery"
              type="text"
              placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..."
              class="w-full pl-10 pr-4 py-2.5 text-sm font-medium border border-slate-200 rounded-xl focus:ring-2 focus:ring-violet-500/20 focus:border-violet-300 outline-none transition-all bg-slate-50 focus:bg-white"
            />
          </div>

          <div class="flex items-center gap-2 mb-3">
            <button
              @click="selectAll"
              class="px-3 py-1.5 text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 rounded-lg transition-colors inline-flex items-center gap-1"
            >
              <i class="bi bi-check-all"></i> เลือกทั้งหมด
            </button>
            <button
              v-if="selected.size > 0"
              @click="clearAll"
              class="px-3 py-1.5 text-xs font-bold text-slate-500 hover:bg-slate-100 rounded-lg transition-colors inline-flex items-center gap-1"
            >
              <i class="bi bi-x-lg"></i> ล้าง
            </button>
            <span class="ml-auto text-xs font-bold text-violet-600">
              เลือกแล้ว {{ selected.size }} คน
            </span>
          </div>

          <!-- Loading -->
          <div v-if="loading" class="flex flex-col items-center py-10 gap-3">
            <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-violet-600"></div>
            <p class="text-xs text-slate-400">กำลังโหลดรายชื่อ...</p>
          </div>

          <!-- Empty -->
          <div
            v-else-if="filtered.length === 0"
            class="text-center py-10 text-slate-400 text-sm bg-slate-50 rounded-2xl border border-dashed border-slate-200"
          >
            {{ props.students.length === 0 ? 'ทุกคนในห้องเข้ากิจกรรมนี้แล้ว 🎉' : 'ไม่พบนักเรียนที่ค้นหา' }}
          </div>

          <!-- List -->
          <div v-else class="space-y-2 max-h-72 overflow-y-auto overflow-x-hidden pr-1">
            <label
              v-for="s in filtered"
              :key="s.student_id"
              class="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-slate-100 cursor-pointer transition-all select-none"
              :class="
                isSelected(s.student_no)
                  ? 'bg-violet-50/50 border-violet-200'
                  : 'bg-white hover:border-violet-200 hover:bg-slate-50'
              "
            >
              <input
                type="checkbox"
                :checked="isSelected(s.student_no)"
                @change="toggle(s.student_no)"
                class="w-4 h-4 rounded accent-violet-600 flex-shrink-0"
              />
              <div
                class="w-9 h-9 rounded-xl bg-slate-50 text-slate-600 flex items-center justify-center font-black text-sm shrink-0 border border-slate-100"
              >
                {{ s.student_no }}
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-bold text-slate-800 truncate">{{ displayName(s) }}</p>
                <p v-if="s.nickname" class="text-[11px] text-slate-400 truncate">
                  {{ s.nickname }}
                </p>
              </div>
            </label>
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
              @click="confirmAdd"
              :disabled="selected.size === 0"
              class="px-6 py-2.5 text-sm font-bold text-white bg-violet-600 hover:bg-violet-700 disabled:opacity-50 rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center gap-1.5"
            >
              <i class="bi bi-person-plus-fill"></i> เพิ่ม {{ selected.size }} คน
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
