<script setup lang="ts">
/**
 * 🗂️ Dropdown สลับห้องเรียน — Teleport ไป body เพื่อไม่ให้ z-index แพ้ stacking
 * context ของ layout
 *
 * เหลือเมนูเดียวโดยเจตนา: งานบัญชี/โปรไฟล์ย้ายไปหน้า "เพิ่มเติม" และ `/account`
 * ⇒ header ไม่ต้องถือสถานะเมนูโปรไฟล์อีก
 */
import type { UserRoom } from '@/types/classroom';
import type { ShellMenu } from './useAppShell';

defineProps<{
  which: ShellMenu | null;
  position: { top: string; left: string; bottom?: string };
  rooms: readonly UserRoom[];
  currentRoomId: number | null;
}>();

const emit = defineEmits<{
  close: [];
  selectRoom: [room: UserRoom];
  changeRoom: [];
}>();
</script>

<template>
  <Teleport to="body">
    <div v-if="which" class="fixed inset-0 z-[70]" @click="emit('close')"></div>

    <Transition name="dropdown-anim">
      <div
        v-if="which === 'roomSwitcher'"
        class="fixed z-[80] w-60 max-w-[calc(100vw-2rem)] overflow-hidden rounded-card border border-line bg-surface py-1.5 shadow-lg"
        :style="position"
        role="menu"
        aria-label="สลับห้องเรียน"
      >
        <p class="border-b border-line px-4 py-2.5 text-caption font-semibold text-ink-3">
          ห้องเรียนของฉัน
        </p>

        <div class="max-h-[220px] overflow-y-auto overscroll-contain">
          <button
            v-for="room in rooms"
            :key="room.room_id"
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-canvas"
            @click.stop="emit('selectRoom', room)"
          >
            <i
              :class="[
                'bi text-base',
                room.room_id === currentRoomId
                  ? 'bi-check-circle-fill text-brand'
                  : 'bi-circle text-ink-3',
              ]"
              aria-hidden="true"
            ></i>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold text-ink-1">
                {{ room.room_name }}
              </span>
            </span>
          </button>
        </div>

        <div class="mx-3 my-1.5 h-px bg-line"></div>
        <button
          type="button"
          role="menuitem"
          class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm font-semibold text-ink-2 transition-colors hover:bg-canvas hover:text-brand"
          @click.stop="emit('changeRoom')"
        >
          <i class="bi bi-grid-3x3-gap text-base" aria-hidden="true"></i>
          ดูห้องทั้งหมด
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dropdown-anim-enter-active {
  transition: all 0.18s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.dropdown-anim-leave-active {
  transition: all 0.12s ease-in;
}
.dropdown-anim-enter-from,
.dropdown-anim-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .dropdown-anim-enter-active,
  .dropdown-anim-leave-active {
    transition-duration: 0.01ms;
  }
}
</style>
