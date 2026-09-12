<script setup lang="ts">
/**
 * StateBlock — สถานะ "ผิดพลาด" และ "ไม่มีข้อมูล" ในรูปแบบเดียวกันทั้งระบบ
 * กรอบเส้นประ + ไอคอน + ข้อความ + ปุ่มลองใหม่ (เฉพาะ error)
 *
 * @example
 * <StateBlock v-if="hasError" variant="error" @retry="load" />
 * <StateBlock v-else-if="!items.length" variant="empty"
 *             title="ยังไม่มีนักเรียน" hint="เพิ่มนักเรียนคนแรกเพื่อเริ่มต้น" />
 */
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
  <div
    class="flex flex-col items-center justify-center gap-2.5 rounded-2xl px-6 py-12 text-center"
    :class="
      variant === 'error'
        ? 'border border-dashed border-stone-300 bg-white'
        : 'border border-dashed border-stone-200 bg-stone-50/60'
    "
    :role="variant === 'error' ? 'alert' : undefined"
  >
    <i
      class="bi text-3xl"
      :class="[
        icon || (variant === 'error' ? 'bi-wifi-off' : 'bi-inbox'),
        variant === 'error' ? 'text-stone-400' : 'text-stone-300',
      ]"
      aria-hidden="true"
    ></i>

    <p class="font-display text-base font-bold text-stone-700">
      {{ title || (variant === 'error' ? 'โหลดข้อมูลไม่สำเร็จ' : 'ยังไม่มีข้อมูล') }}
    </p>

    <p v-if="hint" class="max-w-sm text-sm leading-relaxed text-stone-500">{{ hint }}</p>

    <button v-if="variant === 'error'" type="button" class="btn-ghost-ui mt-1.5" @click="emit('retry')">
      <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
      {{ retryText }}
    </button>

    <!-- ช่องสำหรับปุ่มเพิ่มเติม เช่น "เพิ่มรายการแรก" -->
    <slot />
  </div>
</template>
