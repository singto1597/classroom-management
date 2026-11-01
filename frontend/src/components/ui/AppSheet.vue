<script setup lang="ts">
/**
 * AppSheet — แผ่นเลื่อนขึ้นจากขอบล่าง (มือถือ) สำหรับตัวเลือก/ยืนยันสั้น ๆ
 *
 * กฎที่ฝังไว้ในคอมโพเนนต์:
 *  - `<Teleport to="body">` — z-index ไม่ชนะ stacking context ของ layout
 *  - `z-[60]` อยู่เหนือ backdrop `z-50`
 *  - Esc ปิดได้ · คลิกฉากหลังปิดได้ (ปิดได้เฉพาะเมื่อ `closeOnBackdrop`)
 *  - คืนโฟกัสกลับให้ปุ่มที่เปิดแผ่นเมื่อปิด
 *  - `aria-modal` + `aria-labelledby` ชี้ชื่อแผ่นจริง
 *
 * @example
 * <AppSheet :open="open" label="ตัวกรอง" title="กรองรายการ" @close="open = false">
 *   …เนื้อหา…
 * </AppSheet>
 */
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import IconButton from '@/components/ui/IconButton.vue'

const props = withDefaults(
  defineProps<{
    open: boolean;
    /** ชื่อแผ่นสำหรับ screen reader — ต้องมีเสมอ */
    label: string;
    /** หัวข้อที่แสดงให้เห็น (ถ้าไม่ส่งจะแสดงเฉพาะปุ่มปิด) */
    title?: string;
    closeOnBackdrop?: boolean;
  }>(),
  { title: '', closeOnBackdrop: true },
)

const emit = defineEmits<{ close: [] }>()

const titleId = `app-sheet-${useId()}`
const panel = ref<HTMLElement | null>(null)
let lastFocused: HTMLElement | null = null

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
      window.addEventListener('keydown', onKeydown)
      await nextTick()
      panel.value?.focus()
    } else {
      window.removeEventListener('keydown', onKeydown)
      if (lastFocused?.isConnected) lastFocused.focus()
      lastFocused = null
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 bg-stone-900/40"
        aria-hidden="true"
        @click="closeOnBackdrop && emit('close')"
      ></div>
    </Transition>

    <Transition name="sheet-slide">
      <div
        v-if="open"
        ref="panel"
        class="fixed inset-x-0 bottom-0 z-[60] flex max-h-[86vh] flex-col overflow-hidden rounded-t-3xl border-t border-stone-200 bg-white outline-none"
        role="dialog"
        aria-modal="true"
        :aria-label="title ? undefined : label"
        :aria-labelledby="title ? titleId : undefined"
        tabindex="-1"
      >
        <div class="flex shrink-0 justify-center pt-3" aria-hidden="true">
          <div class="h-1 w-10 rounded-full bg-stone-300"></div>
        </div>

        <slot name="header">
          <div class="flex shrink-0 items-center justify-between gap-3 px-5 pb-3 pt-3">
            <h2 v-if="title" :id="titleId" class="font-display text-lg font-bold text-stone-900">
              {{ title }}
            </h2>
            <span v-else></span>
            <IconButton label="ปิดแผ่น" icon="bi-x-lg" @click="emit('close')" />
          </div>
        </slot>

        <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sheet-fade-enter-active,
.sheet-fade-leave-active {
  transition: opacity 0.18s ease;
}
.sheet-fade-enter-from,
.sheet-fade-leave-to {
  opacity: 0;
}

.sheet-slide-enter-active,
.sheet-slide-leave-active {
  transition: transform 0.22s ease;
}
.sheet-slide-enter-from,
.sheet-slide-leave-to {
  transform: translateY(100%);
}

@media (prefers-reduced-motion: reduce) {
  .sheet-fade-enter-active,
  .sheet-fade-leave-active,
  .sheet-slide-enter-active,
  .sheet-slide-leave-active {
    transition: none;
  }
}
</style>
