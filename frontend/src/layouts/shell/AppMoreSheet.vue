<script setup lang="ts">
/**
 * 📱 ชีต "เพิ่มเติม" บนมือถือ — เมนูที่ไม่อยู่ใน 4 แท็บหลัก + งานบัญชี
 *
 * ⚠️ ต้อง `<Teleport to="body">` — z-index ไม่ชนะ stacking context ของ layout
 *    (กฎเดียวกับ modal อื่นใน repo)
 */
import { RouterLink, useRoute } from 'vue-router';
import { MORE_NAV_ITEMS, isNavItemActive } from '@/constants/nav';

defineProps<{
  open: boolean;
  roomName: string;
}>();

const emit = defineEmits<{
  close: [];
  myProfile: [];
  profileSettings: [];
  logout: [];
}>();

const route = useRoute();
const isActive = (path: string) => isNavItemActive(path, route.path);
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div v-if="open" class="fixed inset-0 z-50 bg-stone-900/40" @click="emit('close')"></div>
    </Transition>

    <Transition name="sheet-slide">
      <div
        v-if="open"
        class="fixed inset-x-0 bottom-0 z-[60] flex max-h-[86vh] flex-col overflow-hidden rounded-t-3xl border-t border-stone-200 bg-white"
        role="dialog"
        aria-modal="true"
        aria-label="เมนูเพิ่มเติม"
      >
        <!-- drag handle (แสดงผลเท่านั้น) -->
        <div class="flex shrink-0 justify-center pt-3" aria-hidden="true">
          <div class="h-1 w-10 rounded-full bg-stone-300"></div>
        </div>

        <div class="flex shrink-0 items-center justify-between px-5 pb-3 pt-3">
          <div>
            <p class="mb-1 text-[10px] font-bold text-stone-400">เมนูทั้งหมด</p>
            <p class="font-display text-lg font-bold text-stone-900">
              {{ roomName || 'SYNCROOM' }}
            </p>
          </div>
          <button
            type="button"
            class="flex h-11 w-11 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-800"
            aria-label="ปิดเมนู"
            @click="emit('close')"
          >
            <i class="bi bi-x-lg text-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
          <nav class="grid grid-cols-3 gap-2" aria-label="เมนูเพิ่มเติม">
            <RouterLink
              v-for="item in MORE_NAV_ITEMS"
              :key="item.path"
              :to="item.path"
              class="flex min-h-11 flex-col items-center justify-center gap-2 rounded-2xl border px-2 py-4 text-center transition-colors"
              :class="
                isActive(item.path)
                  ? 'border-brand-200 bg-brand-50 text-brand-700'
                  : 'border-stone-200 bg-white text-stone-600 hover:bg-stone-50'
              "
            >
              <i :class="['bi', item.icon, 'text-2xl']" aria-hidden="true"></i>
              <span class="text-[11px] font-bold leading-tight">{{ item.name }}</span>
            </RouterLink>
          </nav>

          <div class="my-4 h-px bg-stone-200"></div>

          <p class="mb-2 px-1 text-[10px] font-bold text-stone-400">บัญชี</p>
          <div class="space-y-1">
            <button
              type="button"
              class="flex min-h-11 w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
              @click="emit('myProfile')"
            >
              <i class="bi bi-person-badge text-lg text-stone-400" aria-hidden="true"></i>
              โปรไฟล์ของฉัน
            </button>
            <button
              type="button"
              class="flex min-h-11 w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
              @click="emit('profileSettings')"
            >
              <i class="bi bi-link-45deg text-xl text-stone-400" aria-hidden="true"></i>
              จัดการผูกบัญชี
            </button>
            <button
              type="button"
              class="flex min-h-11 w-full items-center gap-3 rounded-xl px-3.5 py-3 text-left text-sm font-bold text-danger-600 transition-colors hover:bg-danger-50"
              @click="emit('logout')"
            >
              <i class="bi bi-box-arrow-right text-lg" aria-hidden="true"></i>
              ออกจากระบบ
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sheet-fade-enter-active,
.sheet-fade-leave-active {
  transition: opacity 0.22s ease;
}
.sheet-fade-enter-from,
.sheet-fade-leave-to {
  opacity: 0;
}

.sheet-slide-enter-active,
.sheet-slide-leave-active {
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
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
    transition-duration: 0.01ms;
  }
}
</style>
