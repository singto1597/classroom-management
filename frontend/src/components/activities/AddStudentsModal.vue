<script setup lang="ts">
/**
 * ➕ AddStudentsModal — เลือกนักเรียนในห้องที่ยังไม่ได้เข้าร่วมกิจกรรมนี้ แล้วกดเพิ่มเข้ากลุ่ม
 * Presentational — parent โหลดรายการ available ผ่าน ActivityService.getAvailableStudents
 * และยิง ActivityService.batchAddParticipants ตอนกดยืนยัน
 */
import { ref, computed, watch } from 'vue'
import { displayName } from '@/utils/name'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
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
        class="fixed inset-0 z-[70] flex items-end justify-center bg-stone-900/40 px-3 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] md:items-center md:px-4 md:py-4"
        @click.self="emit('close')"
      >
        <div
          class="max-h-[85dvh] w-full overflow-y-auto overscroll-contain rounded-2xl border border-stone-200 bg-white p-4 sm:p-6 md:max-w-lg"
        >
          <!-- Header -->
          <div class="mb-4 flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h4 class="flex items-center gap-2 font-display text-base font-bold text-stone-900">
                <i class="bi bi-person-plus-fill shrink-0 text-brand-700" aria-hidden="true"></i>
                เพิ่มนักเรียนเข้ากิจกรรม
              </h4>
              <p class="mt-0.5 text-xs leading-relaxed text-stone-500">ติ๊กชื่อแล้วกดเพิ่ม</p>
            </div>
            <button
              type="button"
              class="-me-1.5 -mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
              aria-label="ปิดหน้าต่าง"
              @click="emit('close')"
            >
              <i class="bi bi-x-lg" aria-hidden="true"></i>
            </button>
          </div>

          <!-- Search -->
          <div class="relative mb-3">
            <span
              class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3.5 text-stone-400"
            >
              <i class="bi bi-search" aria-hidden="true"></i>
            </span>
            <input
              v-model="searchQuery"
              type="text"
              placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..."
              class="field ps-10"
            />
          </div>

          <div class="mb-3 flex items-center gap-2">
            <button
              type="button"
              class="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-brand-50 px-3 text-xs font-bold text-brand-700 transition-colors hover:bg-brand-100 active:scale-[0.97]"
              @click="selectAll"
            >
              <i class="bi bi-check-all" aria-hidden="true"></i> เลือกทั้งหมด
            </button>
            <button
              v-if="selected.size > 0"
              type="button"
              class="inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-stone-100 px-3 text-xs font-bold text-stone-600 transition-colors hover:bg-stone-200 active:scale-[0.97]"
              @click="clearAll"
            >
              <i class="bi bi-x-lg" aria-hidden="true"></i> ล้าง
            </button>
            <span class="num ms-auto text-xs font-bold text-brand-700">
              เลือกแล้ว {{ selected.size }} คน
            </span>
          </div>

          <!-- Loading -->
          <SkeletonRows v-if="loading" :rows="4" height="h-14" />

          <!-- Empty -->
          <StateBlock
            v-else-if="filtered.length === 0"
            variant="empty"
            :icon="props.students.length === 0 ? 'bi-people' : 'bi-search'"
            :title="props.students.length === 0 ? 'ไม่มีนักเรียนให้เพิ่ม' : 'ไม่พบนักเรียนที่ค้นหา'"
            :hint="
              props.students.length === 0
                ? 'ทุกคนอาจเข้าร่วมกิจกรรมนี้แล้ว หรือโหลดรายชื่อไม่สำเร็จ — ปิดแล้วเปิดใหม่เพื่อลองอีกครั้ง'
                : 'ลองพิมพ์ชื่อ เลขที่ หรือชื่อเล่นใหม่อีกครั้ง'
            "
          />

          <!-- List -->
          <div v-else class="space-y-2">
            <label
              v-for="s in filtered"
              :key="s.student_id"
              class="flex cursor-pointer select-none items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors"
              :class="
                isSelected(s.student_no)
                  ? 'border-brand-200 bg-brand-50/60'
                  : 'border-stone-100 bg-white hover:border-stone-200 hover:bg-stone-50'
              "
            >
              <input
                type="checkbox"
                :checked="isSelected(s.student_no)"
                @change="toggle(s.student_no)"
                class="h-4 w-4 shrink-0 rounded accent-brand-700"
              />
              <div
                class="num flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-stone-100 bg-stone-50 text-sm font-bold text-stone-600"
              >
                {{ s.student_no }}
              </div>
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-bold text-stone-800">{{ displayName(s) }}</p>
                <p v-if="s.nickname" class="truncate text-[11px] text-stone-400">
                  {{ s.nickname }}
                </p>
              </div>
            </label>
          </div>

          <!-- Actions — sticky ให้ปุ่มหลักกดถึงเสมอแม้ลิสต์ยาว -->
          <div
            class="sticky bottom-0 -mx-4 mt-4 flex flex-col-reverse gap-2 border-t border-stone-100 bg-white px-4 pt-4 sm:-mx-6 sm:px-6"
          >
            <button type="button" class="btn-ghost-ui" @click="emit('close')">ยกเลิก</button>
            <button
              type="button"
              class="btn-primary"
              :disabled="selected.size === 0"
              @click="confirmAdd"
            >
              <i class="bi bi-person-plus-fill" aria-hidden="true"></i>
              เพิ่ม {{ selected.size }} คน
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
