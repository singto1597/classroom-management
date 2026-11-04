<script setup lang="ts">
/**
 * AppSheet — พื้นผิวสนทนากลางของทั้งระบบ (แทน SweetAlert2 และโมดัลที่เขียนเอง)
 *
 * กฎที่ฝังไว้ในคอมโพเนนต์:
 *  - `<Teleport to="body">` — z-index ไม่ชนะ stacking context ของ layout
 *  - มือถือ = แผ่นเลื่อนขึ้นจากขอบล่าง · จอ `sm+` = กล่องกลางจอ (`position="responsive"`)
 *  - `size="form"` เต็มความสูงบนมือถือ เพื่อให้คีย์บอร์ดไม่บังช่องกรอก และมี footer ติดล่าง
 *  - Esc / ฉากหลังปิดได้เมื่อ `dismissible` (ปิดฉากหลังเพิ่มได้อีกชั้นด้วย `closeOnBackdrop`)
 *  - ล็อกการเลื่อนของหน้าไว้ระหว่างเปิด และคืนโฟกัสกลับให้ปุ่มที่เปิดแผ่นเมื่อปิด
 *  - `Tab`/`Shift+Tab` วนอยู่ในแผ่น (focus trap), `aria-modal` + `aria-labelledby`
 *
 * @example
 * <AppSheet :open="open" label="ตัวกรอง" title="กรองรายการ" @close="open = false">
 *   …เนื้อหา…
 *   <template #footer>
 *     <button type="button" class="btn-primary w-full" @click="apply">ใช้ตัวกรอง</button>
 *   </template>
 * </AppSheet>
 */
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import IconButton from '@/components/ui/IconButton.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    /** ชื่อแผ่นสำหรับ screen reader — ต้องมีเสมอ */
    label: string
    /** หัวข้อที่แสดงให้เห็น (ถ้าไม่ส่งจะแสดงเฉพาะปุ่มปิด) */
    title?: string
    /** คำอธิบายใต้หัวข้อ — ผูกกับ `aria-describedby` */
    description?: string
    /** ปิดได้ด้วย Esc/ฉากหลังหรือไม่ (ตั้ง false ระหว่างกำลังทำงาน) */
    dismissible?: boolean
    /** ปิดเมื่อคลิกฉากหลัง (ต้อง `dismissible` ด้วย) */
    closeOnBackdrop?: boolean
    /** ความกว้าง/ความสูงของแผ่น */
    size?: 'auto' | 'dialog' | 'form' | 'full'
    /**
     * ตำแหน่งบนจอ
     *  - `responsive` (ค่าเริ่มต้น) — ล่างบนมือถือ · กลางจอบน `sm+`
     *  - `center` — กลางจอทุกขนาด
     *  - `bottom` — ชิดล่างทุกขนาด
     */
    position?: 'responsive' | 'center' | 'bottom'
  }>(),
  {
    title: '',
    description: '',
    dismissible: true,
    closeOnBackdrop: true,
    size: 'auto',
    position: 'responsive',
  },
)

const emit = defineEmits<{ close: [] }>()

const titleId = `app-sheet-title-${useId()}`
const descriptionId = `app-sheet-desc-${useId()}`
const panel = ref<HTMLElement | null>(null)
let lastFocused: HTMLElement | null = null

/* ── ล็อกการเลื่อนหน้า (นับชั้น เผื่อมีหลายแผ่นซ้อนกัน) ─────────────── */
let lockCount = 0
let previousOverflow = ''

const lockScroll = () => {
  if (lockCount === 0) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  lockCount += 1
}

const unlockScroll = () => {
  if (lockCount === 0) return
  lockCount -= 1
  if (lockCount === 0) document.body.style.overflow = previousOverflow
}

/* ── overlay / panel geometry ──────────────────────────────────────── */
const overlayClass = computed(() => {
  if (props.position === 'bottom') return 'flex items-end justify-center'
  if (props.position === 'center') return 'flex items-center justify-center p-4'
  return 'flex items-end justify-center sm:items-center sm:p-4'
})

const panelClass = computed(() => {
  const classes = [
    'relative flex w-full flex-col overflow-hidden bg-surface shadow-sheet outline-none',
  ]

  // ความสูง + มุมโค้ง
  if (props.size === 'form' || props.size === 'full') {
    classes.push('h-[100dvh] max-h-none rounded-none sm:h-auto')
    if (props.size === 'full') classes.push('sm:h-[92dvh] sm:max-h-[92dvh]')
    else classes.push('sm:max-h-[92dvh]')
    classes.push('sm:rounded-sheet')
  } else if (props.position === 'bottom') {
    classes.push('max-h-[92dvh] rounded-t-sheet')
  } else {
    classes.push('max-h-[92dvh] rounded-t-sheet sm:rounded-sheet')
  }

  // ความกว้าง
  if (props.size === 'full') classes.push('sm:max-w-5xl')
  else if (props.size === 'form') classes.push('sm:max-w-xl')
  else if (props.size === 'dialog') classes.push('sm:max-w-lg')
  else classes.push('sm:max-w-lg')

  return classes
})

const grabberClass = computed(() =>
  props.position === 'responsive' ? 'sm:hidden' : '',
)

/* ── focus trap + Esc ──────────────────────────────────────────────── */
const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

const focusableElements = (): HTMLElement[] => {
  if (!panel.value) return []
  return Array.from(panel.value.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (el) => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true',
  )
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    if (props.dismissible) emit('close')
    return
  }
  if (event.key !== 'Tab' || !panel.value) return

  const items = focusableElements()
  if (items.length === 0) {
    event.preventDefault()
    panel.value.focus()
    return
  }

  const first = items[0]
  const last = items[items.length - 1]
  if (!first || !last) {
    event.preventDefault()
    panel.value.focus()
    return
  }
  const active = document.activeElement
  const inside = active instanceof Node && panel.value.contains(active)

  if (!inside) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
    return
  }
  if (event.shiftKey && active === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

const teardown = () => {
  window.removeEventListener('keydown', onKeydown)
  unlockScroll()
  if (lastFocused?.isConnected) lastFocused.focus()
  lastFocused = null
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
      lockScroll()
      window.addEventListener('keydown', onKeydown)
      await nextTick()
      panel.value?.focus()
    } else {
      teardown()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (props.open) unlockScroll()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 bg-ink-1/40"
        aria-hidden="true"
        @click="dismissible && closeOnBackdrop && emit('close')"
      ></div>
    </Transition>

    <Transition name="sheet-slide">
      <div v-if="open" class="pointer-events-none fixed inset-0 z-[60]">
        <div :class="['pointer-events-auto h-full w-full', overlayClass]">
          <div
            ref="panel"
            :class="panelClass"
            role="dialog"
            aria-modal="true"
            :aria-label="title ? undefined : label"
            :aria-labelledby="title ? titleId : undefined"
            :aria-describedby="description ? descriptionId : undefined"
            tabindex="-1"
          >
              <div
                v-if="position !== 'center'"
                :class="['flex shrink-0 justify-center pt-3', grabberClass]"
                aria-hidden="true"
              >
                <div class="h-1 w-10 rounded-full bg-line"></div>
              </div>

              <header class="shrink-0 px-5 pb-3 pt-3">
                <slot name="header">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0 flex-1">
                      <h2
                        v-if="title"
                        :id="titleId"
                        class="font-display text-title-m font-bold text-ink-1"
                      >
                        {{ title }}
                      </h2>
                      <p
                        v-if="description"
                        :id="descriptionId"
                        class="mt-1 text-sm leading-relaxed text-ink-2"
                      >
                        {{ description }}
                      </p>
                    </div>
                    <IconButton
                      v-if="dismissible"
                      label="ปิดแผ่น"
                      icon="bi-x-lg"
                      @click="emit('close')"
                    />
                  </div>
                </slot>
              </header>

              <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-4">
                <slot />
              </div>

              <footer
                v-if="$slots.footer"
                class="shrink-0 border-t border-line bg-surface px-5 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))]"
              >
                <slot name="footer" />
              </footer>
          </div>
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
  transition:
    transform 0.22s ease,
    opacity 0.22s ease;
}
.sheet-slide-enter-from,
.sheet-slide-leave-to {
  transform: translateY(16px);
  opacity: 0;
}

@media (min-width: 640px) {
  .sheet-slide-enter-from,
  .sheet-slide-leave-to {
    transform: translateY(8px) scale(0.98);
  }
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
