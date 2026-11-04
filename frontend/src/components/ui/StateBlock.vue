<script setup lang="ts">
/**
 * StateBlock — สถานะ "ผิดพลาด" และ "ไม่มีข้อมูล" ในรูปแบบเดียวกันทั้งระบบ
 *
 * - `variant="empty"` → ส่งต่อให้ `AppEmptyState` (การ์ด + ไอคอน + ทางออกผ่าน slot)
 * - `variant="error"` → การ์ดขอบแดงอ่อน + ปุ่มลองใหม่
 *
 * ⚠️ ห้ามใส่กรอบเส้นประ (`border-dashed`) — ทุกกล่องในแอปเป็นการ์ดขอบทึบ
 * เพื่อไม่ให้สถานะว่างดูเหมือน "ช่องที่ยังกรอกไม่ครบ" (DoD P1: border-dashed = 0)
 *
 * @example
 * <StateBlock v-if="hasError" variant="error" @retry="load" />
 * <StateBlock v-else-if="!items.length" variant="empty"
 *             title="ยังไม่มีนักเรียน" hint="เพิ่มนักเรียนคนแรกเพื่อเริ่มต้น" />
 */
import AppEmptyState from '@/components/ui/AppEmptyState.vue'

withDefaults(
  defineProps<{
    variant: 'error' | 'empty';
    /** หัวข้อ — ถ้าไม่ส่งจะใช้ค่าเริ่มต้นตาม variant */
    title?: string;
    /** คำอธิบายเพิ่มเติม */
    hint?: string;
    /** override ไอคอน bootstrap-icons เช่น 'bi-inbox' */
    icon?: string;
    /** ข้อความบนปุ่มลองใหม่ */
    retryText?: string;
  }>(),
  {
    icon: '',
    retryText: 'ลองอีกครั้ง',
  },
);

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <AppEmptyState v-if="variant === 'empty'" :title="title" :hint="hint" :icon="icon || 'bi-inbox'">
    <slot />
  </AppEmptyState>

  <div
    v-else
    class="flex flex-col items-center justify-center gap-2 rounded-card border border-danger-200 bg-surface px-5 py-9 text-center sm:gap-2.5 sm:px-6 sm:py-12"
    role="alert"
  >
    <i :class="['bi', icon || 'bi-wifi-off', 'text-3xl text-danger-500']" aria-hidden="true"></i>

    <p class="font-display text-title-m font-bold text-ink-1">{{ title || 'โหลดข้อมูลไม่สำเร็จ' }}</p>

    <p v-if="hint" class="max-w-sm text-sm leading-relaxed text-ink-2">{{ hint }}</p>

    <button type="button" class="btn-ghost-ui mt-1.5" @click="emit('retry')">
      <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
      {{ retryText }}
    </button>

    <!-- ช่องสำหรับปุ่มเพิ่มเติม เช่น "กลับหน้ารายชื่อ" -->
    <slot />
  </div>
</template>
