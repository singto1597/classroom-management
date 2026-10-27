<script setup lang="ts">
/**
 * 🗂️ Dropdown ที่ Teleport ไป body — สลับห้องเรียน และเมนูโปรไฟล์
 *
 * รวมไว้ไฟล์เดียวเพราะใช้สไตล์/การวางตำแหน่งชุดเดียวกัน และถูกเปิดจาก header ที่เดียว
 */
import type { UserRoom } from '@/types/classroom';
import type { ShellMenu } from './useAppShell';

defineProps<{
  which: ShellMenu | null;
  position: { top: string; left: string; bottom?: string };
  rooms: readonly UserRoom[];
  currentRoomId: number | null;
  userName: string;
  roleLabel: string;
  avatarChar: string;
}>();

const emit = defineEmits<{
  close: [];
  selectRoom: [room: UserRoom];
  changeRoom: [];
  myProfile: [];
  profileSettings: [];
  logout: [];
}>();
</script>

<template>
  <Teleport to="body">
    <div v-if="which" class="fixed inset-0 z-[70]" @click="emit('close')"></div>

    <!-- สลับห้องเรียน -->
    <Transition name="dropdown-anim">
      <div
        v-if="which === 'roomSwitcher'"
        class="fixed z-[80] w-60 max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl border border-stone-200 bg-white py-1.5 shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
        :style="position"
        role="menu"
        aria-label="สลับห้องเรียน"
      >
        <p
          class="mb-1 border-b border-stone-100 bg-stone-50/70 px-4 py-2.5 text-[10px] font-bold text-stone-400"
        >
          ห้องเรียนของฉัน
        </p>

        <div class="max-h-[220px] overflow-y-auto overscroll-contain">
          <button
            v-for="room in rooms"
            :key="room.room_id"
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-brand-50"
            @click.stop="emit('selectRoom', room)"
          >
            <i
              :class="[
                'bi text-base',
                room.room_id === currentRoomId
                  ? 'bi-check-circle-fill text-brand-700'
                  : 'bi-circle text-stone-300',
              ]"
              aria-hidden="true"
            ></i>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-bold text-stone-700">
                {{ room.room_name }}
              </span>
            </span>
          </button>
        </div>

        <div class="mx-3 my-1.5 h-px bg-stone-100"></div>
        <button
          type="button"
          role="menuitem"
          class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-brand-50 hover:text-brand-700"
          @click.stop="emit('changeRoom')"
        >
          <i class="bi bi-grid-3x3-gap text-base opacity-70" aria-hidden="true"></i>
          ดูห้องทั้งหมด
        </button>
      </div>
    </Transition>

    <!-- โปรไฟล์ -->
    <Transition name="dropdown-anim">
      <div
        v-if="which === 'headerSettings'"
        class="fixed z-[80] flex w-64 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
        :style="position"
        role="menu"
        aria-label="เมนูโปรไฟล์"
      >
        <div class="flex items-center gap-3 border-b border-stone-100 bg-stone-50/70 px-5 py-4">
          <div
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand-700 text-base font-bold text-white"
          >
            {{ avatarChar }}
          </div>
          <div class="min-w-0">
            <p class="truncate text-sm font-bold leading-tight text-stone-800">{{ userName }}</p>
            <p class="mt-0.5 truncate text-[11px] font-bold text-brand-700">{{ roleLabel }}</p>
          </div>
        </div>
        <div class="py-1.5">
          <button
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-50 hover:text-brand-700"
            @click.stop="emit('myProfile')"
          >
            <i class="bi bi-person-badge text-lg opacity-70" aria-hidden="true"></i>
            โปรไฟล์ของฉัน
          </button>
          <button
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-50 hover:text-brand-700"
            @click.stop="emit('profileSettings')"
          >
            <i class="bi bi-link-45deg text-xl opacity-70" aria-hidden="true"></i>
            จัดการบัญชีเชื่อมต่อ
          </button>
          <button
            type="button"
            role="menuitem"
            class="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-50 hover:text-brand-700"
            @click.stop="emit('changeRoom')"
          >
            <i class="bi bi-grid-3x3-gap text-base opacity-70" aria-hidden="true"></i>
            สลับห้องเรียน
          </button>
        </div>
        <div class="border-t border-stone-100 bg-stone-50/60 p-2">
          <button
            type="button"
            role="menuitem"
            class="w-full rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-center text-sm font-bold text-danger-600 transition-colors hover:border-danger-200 hover:bg-danger-50"
            @click.stop="emit('logout')"
          >
            ออกจากระบบ
          </button>
        </div>
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
