<script setup lang="ts">
/**
 * AppDialogHost — เรนเดอร์กล่องสนทนากลางจาก `stores/dialog.ts`
 *
 * mount ครั้งเดียวที่ `App.vue` ⇒ ทุกหน้าใช้ `useDialog()` ได้โดยไม่ต้องมี template ของตัวเอง
 * เนื้อหาเป็น Vue จริง (ไม่ใช่ `v-html`) และสิทธิ์การเข้าถึง (focus trap, Esc,
 * aria) มาจาก `AppSheet` ทั้งหมด
 */
import { computed, onBeforeUnmount, watch } from 'vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useDialogStore, type DialogIcon } from '@/stores/dialog'

const dialog = useDialogStore()

const ICONS: Record<DialogIcon, { name: string; cls: string }> = {
  success: { name: 'bi-check-circle-fill', cls: 'text-ok-600' },
  error: { name: 'bi-x-circle-fill', cls: 'text-danger-600' },
  warning: { name: 'bi-exclamation-triangle-fill', cls: 'text-warn-600' },
  info: { name: 'bi-info-circle-fill', cls: 'text-brand' },
  question: { name: 'bi-question-circle-fill', cls: 'text-brand' },
}

const icon = computed(() => (dialog.options?.icon ? ICONS[dialog.options.icon] : null))
const toastIcon = computed(() => (dialog.toast ? ICONS[dialog.toast.icon] : null))
const showCancel = computed(() => Boolean(dialog.options?.showCancelButton))
const confirmText = computed(() => dialog.options?.confirmButtonText ?? 'ตกลง')
const cancelText = computed(() => dialog.options?.cancelButtonText ?? 'ยกเลิก')
const isDanger = computed(
  () => Boolean(dialog.options?.danger) || dialog.options?.icon === 'error',
)
const inputKind = computed(() => dialog.options?.input)

let timer: ReturnType<typeof setTimeout> | null = null

const clearTimer = () => {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

watch(
  () => [dialog.isOpen, dialog.options?.timer] as const,
  ([open, ms]) => {
    clearTimer()
    if (open && typeof ms === 'number' && ms > 0) {
      timer = setTimeout(() => {
        void dialog.accept()
      }, ms)
    }
  },
)

onBeforeUnmount(() => {
  clearTimer()
  dialog.dismissToast()
})
</script>

<template>
  <AppSheet
    :open="dialog.isOpen"
    :label="dialog.options?.title || dialog.options?.text || 'ข้อความจากระบบ'"
    :title="dialog.options?.title"
    :description="dialog.options?.text"
    :dismissible="!dialog.isBusy"
    :position="dialog.options?.position ?? 'responsive'"
    size="dialog"
    @close="dialog.dismiss()"
  >
    <div v-if="icon || inputKind" class="space-y-4">
      <div v-if="icon" class="flex justify-center py-1">
        <i :class="['bi', icon.name, 'text-4xl', icon.cls]" aria-hidden="true"></i>
      </div>

      <div v-if="inputKind">
        <label v-if="dialog.options?.inputLabel" class="field-label" for="app-dialog-input">
          {{ dialog.options.inputLabel }}
        </label>
        <textarea
          v-if="inputKind === 'textarea'"
          id="app-dialog-input"
          v-model="dialog.inputValue"
          class="field h-28 resize-none"
          :placeholder="dialog.options?.inputPlaceholder"
          autofocus
        ></textarea>
        <input
          v-else
          id="app-dialog-input"
          v-model="dialog.inputValue"
          :type="inputKind"
          class="field"
          :placeholder="dialog.options?.inputPlaceholder"
          autofocus
        />
        <p v-if="dialog.errorMessage" class="mt-2 text-caption text-danger-600" role="alert">
          {{ dialog.errorMessage }}
        </p>
      </div>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button
          v-if="showCancel"
          type="button"
          class="btn-ghost-ui"
          :disabled="dialog.isBusy"
          @click="dialog.dismiss()"
        >
          {{ cancelText }}
        </button>
        <button
          type="button"
          :class="isDanger ? 'btn-danger' : 'btn-primary'"
          :disabled="dialog.isBusy"
          @click="dialog.accept()"
        >
          {{ confirmText }}
        </button>
      </div>
    </template>
  </AppSheet>

  <Teleport to="body">
    <Transition name="dialog-toast">
      <div
        v-if="dialog.toast && toastIcon"
        class="pointer-events-none fixed inset-x-0 bottom-[calc(var(--app-nav-h,3.5rem)+env(safe-area-inset-bottom,0px)+1rem)] z-[70] flex justify-center px-4"
        role="status"
        aria-live="polite"
      >
        <div
          class="flex max-w-md items-center gap-2.5 rounded-control border border-line bg-surface px-4 py-3 text-sm font-semibold text-ink-1 shadow-sheet"
        >
          <i :class="['bi', toastIcon.name, 'shrink-0 text-base', toastIcon.cls]" aria-hidden="true"></i>
          <span class="min-w-0">{{ dialog.toast.message }}</span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-toast-enter-active,
.dialog-toast-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
}
.dialog-toast-enter-from,
.dialog-toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .dialog-toast-enter-active,
  .dialog-toast-leave-active {
    transition: none;
  }
}
</style>
